/**
 * mdcg_client.ts —— 认知图显式客户端（LIB 本地库）
 *
 * 架构定位（2026-09-10 决定）
 * --------------------------
 *   · md_cg = 记忆操作系统 / **唯一真源**（记忆的写、读、裁决、留痕）。
 *   · AEIS  = **能力库**（白箱引擎、角色扮演生成等），不再是记忆真源。
 *
 * 本模块是插件侧调用 md_cg 的**唯一显式入口**：只暴露 `cg` / `stg` 两个
 * 认知基元，每个方法 = 一条 MCP 调用，不做隐式魔法。
 *
 * 显式调用映射（详见 docs/功能调用映射表_v0.1.md）
 * ------------------------------------------------
 *   路由/召回     → MdcgClient.route()      → MCP cg(op=route)
 *   读取节点      → MdcgClient.read()       → MCP cg(op=read)
 *   写入记忆      → MdcgClient.write()      → MCP cg(op=write)
 *   外部裁决回填  → MdcgClient.verify()     → MCP cg(op=verify)
 *   最近记忆      → MdcgClient.recent()     → MCP cg(op=recent)
 *   身份读取      → MdcgClient.identity()   → MCP cg(op=identity)
 *   白箱能力验证  → MdcgClient.whitebox()   → MCP cg(op=whitebox)
 *   服务信息      → MdcgClient.serviceInfo()→ MCP cg(op=info)
 *   互维主张核验  → MdcgClient.verifyClaim()→ cg(op=read) + 依据强度判定
 *   角色/转录落图 → MdcgClient.writeRole() / writeTranscript() → cg(op=write)
 */

import { LingshuBridge, type McpCallResult } from '../bridge.js'

/** md_cg 子进程与根目录配置。 */
export interface MdcgOptions {
  /** Python 可执行文件，默认取 config.python。 */
  python: string
  /** 启动参数，默认 ['-m', 'md_cg.mcp_server']。 */
  args?: string[]
  /** 认知图根目录（MDCG_ROOT）。 */
  root: string
  /** 调用主体标识（MDCG_ACTOR）。私有内容按 (tenant, actor) 派生 DEK，
   *  故与迁移脚本 --actor 必须一致，否则读不到已迁移节点。 */
  actor?: string
  /** 租户（MDCG_TENANT），默认 default。 */
  tenant?: string
  /** 调用方密级（MDCG_CLEARANCE）：只能读写 ≤ 该密级的节点，默认 private。 */
  clearance?: string
  /** 身份主体（MDCG_IDENTITY）。 */
  identity?: string
  /** 额外环境变量。 */
  env?: Record<string, string>
  timeoutMs?: number
  maxRetryDelayMs?: number
}

const DEFAULT_ARGS = ['-m', 'md_cg.mcp_server']

/** 认知图依据强度：这些 basis 视为「强依据」，可支撑 pass。
 *  取值须在 md_cg.mdcg.VERIFICATION_BASIS 允许集内：
 *  compiler | test | measurement | formal_proof | data | other（other 不算强依据）。 */
const STRONG_BASIS = new Set(['compiler', 'test', 'measurement', 'formal_proof', 'data'])

function collectItems(payload: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(payload)) return payload as Array<Record<string, unknown>>
  if (payload && typeof payload === 'object') {
    const obj = payload as Record<string, unknown>
    for (const key of ['results', 'items', 'nodes', 'hits', 'data', 'records']) {
      if (Array.isArray(obj[key])) return obj[key] as Array<Record<string, unknown>>
    }
  }
  return []
}

/**
 * 认知图显式客户端。
 *
 * 生命周期与 AEIS 桥一致：懒启动 + 自动重连；未就绪时调用会快速失败，
 * 调用方应回退到能力库路径（见 index.ts 的互维 verify 注入）。
 */
export class MdcgClient {
  readonly bridge: LingshuBridge
  private ready = false

  constructor(opts: MdcgOptions) {
    const env: Record<string, string> = {
      MDCG_ROOT: opts.root,
      MDCG_TENANT: opts.tenant ?? 'default',
      MDCG_CLEARANCE: opts.clearance ?? 'private',
      ...(opts.actor ? { MDCG_ACTOR: opts.actor } : {}),
      ...(opts.identity ? { MDCG_IDENTITY: opts.identity } : {}),
      ...(opts.env ?? {}),
    }
    this.bridge = new LingshuBridge({
      python: opts.python,
      args: opts.args ?? DEFAULT_ARGS,
      env,
      timeoutMs: opts.timeoutMs ?? 60_000,
      maxRetryDelayMs: opts.maxRetryDelayMs ?? 30_000,
    })
  }

  start(): void {
    this.bridge.start()
  }

  async waitReady(): Promise<boolean> {
    this.ready = await this.bridge.waitReady()
    return this.ready
  }

  isReady(): boolean {
    return this.ready && this.bridge.isReady()
  }

  dispose(): void {
    this.bridge.dispose()
  }

  /** 原始 cg 调用（逃生口；显式传参，不做推断）。 */
  async cg(args: Record<string, unknown>): Promise<unknown> {
    return this.call('cg', args)
  }

  /** 原始 stg 调用（时间线/关系/锚点/一致性）。 */
  async stg(args: Record<string, unknown>): Promise<unknown> {
    return this.call('stg', args)
  }

  private async call(tool: string, args: Record<string, unknown>): Promise<unknown> {
    const result: McpCallResult = await this.bridge.callTool(tool, args)
    const text = (result.content ?? [])
      .filter((c) => c.type === 'text')
      .map((c) => c.text ?? '')
      .join('')
    if (result.isError) throw new Error(text || `md_cg ${tool} 调用失败`)
    try {
      return JSON.parse(text)
    } catch {
      return text
    }
  }

  // -- 显式认知能力（每个方法一条 MCP 调用） --------------------------------

  /** 路由：意图 → 相关知识 + 建议能力。 */
  route(intent: string, extra: Record<string, unknown> = {}): Promise<unknown> {
    return this.cg({ op: 'route', intent, ...extra })
  }

  /** 读取：按语义召回节点。 */
  read(query: string, extra: Record<string, unknown> = {}): Promise<unknown> {
    return this.cg({ op: 'read', query, ...extra })
  }

  /** 按 id 精确读取单个节点。 */
  get(nodeId: string): Promise<unknown> {
    return this.cg({ op: 'read', node_id: nodeId })
  }

  /** 写入：新增/覆盖一个记忆节点。 */
  write(content: string, extra: Record<string, unknown> = {}): Promise<unknown> {
    return this.cg({ op: 'write', content, ...extra })
  }

  /** 外部裁决回填：为已有节点写 confirmed/weakened/falsified。 */
  verify(nodeId: string, evidence: string, verdict: string): Promise<unknown> {
    return this.cg({ op: 'verify', node_id: nodeId, evidence, verdict })
  }

  /** 最近记忆。 */
  recent(limit = 20): Promise<unknown> {
    return this.cg({ op: 'recent', limit })
  }

  /** 身份维度读取。 */
  identity(subjectId?: string, extra: Record<string, unknown> = {}): Promise<unknown> {
    return this.cg({ op: 'identity', ...(subjectId ? { subject_id: subjectId } : {}), ...extra })
  }

  /** 白箱能力库：显式调用 + 能力验证。 */
  whitebox(action: string, extra: Record<string, unknown> = {}): Promise<unknown> {
    return this.cg({ op: 'whitebox', action, ...extra })
  }

  /** 服务信息（信任透明度）。 */
  serviceInfo(): Promise<unknown> {
    return this.cg({ op: 'info' })
  }

  // -- 语义化封装（互维 / 角色扮演显式使用认知图） --------------------------

  /**
   * 互维主张核验（memory 通道）：用认知图替代 AEIS `wisdom_verify`。
   * 返回结构与 VerifyResult['whitebox'] 对齐，便于直接注入 mutual。
   */
  async verifyClaim(claim: string): Promise<{
    judgment: string
    best: string
    d_norm: number
    record_id: string
  }> {
    const payload = await this.read(claim, { k: 4 })
    const scored = collectItems(payload)
      .map((it) => {
        const node = (it['node'] as Record<string, unknown>) ?? it
        const fm = (node['frontmatter'] as Record<string, unknown>) ?? node
        const score = typeof it['score'] === 'number'
          ? it['score'] as number
          : Number(it['score'] ?? 0)
        return {
          id: String(node['id'] ?? it['id'] ?? ''),
          score: Number.isFinite(score) ? score : 0,
          basis: String(fm['verification_basis'] ?? node['verification_basis'] ?? ''),
          content: String(node['content'] ?? ''),
        }
      })
      .filter((x) => x.id)
      .sort((a, b) => b.score - a.score)
    const best = scored[0]
    if (best && best.score > 0 && STRONG_BASIS.has(best.basis)) {
      return {
        judgment: `采纳：认知图已有强依据节点 ${best.id}（basis=${best.basis}）`,
        best: best.content.slice(0, 200),
        d_norm: Math.min(1, best.score),
        record_id: best.id,
      }
    }
    if (best && best.score > 0) {
      return {
        judgment: `待定：命中节点 ${best.id} 但依据不足（basis=${best.basis || 'unknown'}）`,
        best: best.content.slice(0, 200),
        d_norm: -1,
        record_id: best.id,
      }
    }
    return { judgment: '未命中：认知图中无相关节点', best: '', d_norm: -1, record_id: '' }
  }

  /** 角色定义落图：layer=knowledge，tags=['roleplay','role:<id>']。 */
  writeRole(roleId: string, content: string, extra: Record<string, unknown> = {}): Promise<unknown> {
    return this.write(content, {
      node_id: `roleplay_role_${roleId}`,
      layer: 'knowledge',
      tags: ['roleplay', `role:${roleId}`, 'roleplay:role'],
      importance: 0.7,
      ...extra,
    })
  }

  /** 角色对话转录落图：layer=contextual，tags=['roleplay','role:<id>','session:<cid>']。 */
  writeTranscript(roleId: string, sessionId: string, who: 'user' | 'assistant',
                  content: string, extra: Record<string, unknown> = {}): Promise<unknown> {
    const stamp = Date.now()
    return this.write(content, {
      node_id: `roleplay_turn_${roleId}_${sessionId}_${stamp}`,
      layer: 'contextual',
      tags: ['roleplay', `role:${roleId}`, `session:${sessionId}`, `turn:${who}`],
      importance: 0.4,
      ...extra,
    })
  }
}
