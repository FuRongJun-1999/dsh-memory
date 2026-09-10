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
 *   记忆沉淀      → MdcgClient.remember()   → MCP mdcg_remember(gated=true)
 *   语义召回      → MdcgClient.recall()     → MCP cg(op=read, query)
 *   写入记忆      → MdcgClient.write()      → MCP mdcg_remember(gated=false)
 *   外部裁决回填  → MdcgClient.verify()     → MCP cg(op=verify)
 *   最近记忆时间线 → MdcgClient.timeline()  → MCP stg(op=timeline)
 *   近期事件窗口  → MdcgClient.recent()     → MCP cg(op=recent)
 *   身份读取      → MdcgClient.identity()   → MCP cg(op=identity)
 *   白箱能力验证  → MdcgClient.whitebox()   → MCP cg(op=whitebox)
 *   服务信息      → MdcgClient.serviceInfo()→ MCP cg(op=info)
 *   互维主张核验  → MdcgClient.verifyClaim()→ cg(op=read) + 依据强度判定
 *   角色/转录落图 → MdcgClient.writeRole() / writeTranscript() → mdcg_remember
 *
 * 写入为什么不能走 cg(op=write)（关键约束，勿回退）
 * ------------------------------------------------
 *   `cg(op=write)` 是**带审核**的写路径：先过 `audit.audit(content_kind)`，
 *   未声明 content_kind 且未配置 `MDCG_POLICY_FILE` 时恒判 BLINDSPOT/DEFER ——
 *   只进审核队列、**永不落盘**（自动记忆会静默全失败，实测 0 篇 md 文档）。
 *   而 `mdcg_remember`（`md_cg/mcp_server.py:1691`）直接调 `MdCG.remember_gated`
 *   / `MdCG.add`，跳过审核，是 mcp_server 顶部文档定义的「写」入口。故本客户端
 *   的**所有写入**（记忆沉淀 / 角色定义 / 对话转录）统一经 `mdcg_remember`。
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
  /** MCP 工具面（MDCG_MCP_SURFACE）：'kernel' = 仅 cg/stg 两基元；
   *  'full' = 另含 `mdcg_*` 细粒度工具。
   *
   *  ⚠️ 本客户端**必须**用 full：唯一写入通道是 `mdcg_remember`（细粒度），
   *  kernel 面下该工具不存在 → 写入静默失败（角色/转录/自动记忆全部不落盘）。
   *  默认 'full'，勿改。 */
  surface?: 'kernel' | 'full'
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
 * 生命周期与桥一致：懒启动 + 自动重连；未就绪时调用会快速失败。
 * 未就绪的处置：互维 verify 走 fail-closed（见 index.ts 的注入），
 * 自动记忆静默跳过——**不再有"回退 aeis 能力库"路径**（该库已剥离）。
 */
export class MdcgClient {
  readonly bridge: LingshuBridge

  constructor(opts: MdcgOptions) {
    const env: Record<string, string> = {
      // ⚠️ 必须显式 utf-8：Windows 下 piped 子进程默认 gbk + surrogateescape，
      // Node 写出的 UTF-8 中文会被解成孤立代理字符（\udcXX），md_cg 在落盘 /
      // 回写 stdout 时抛 UnicodeEncodeError —— 中文记忆（本插件的主场景）全部失败。
      // md_cg 自带测试（test_p2_mcp.py）与 test/bridge.test.ts 均以
      // PYTHONIOENCODING=utf-8 启动子进程，此处对齐该约定；opts.env 可覆盖。
      PYTHONIOENCODING: 'utf-8',
      MDCG_ROOT: opts.root,
      // 工具面必须是 full：写入通道 mdcg_remember 属细粒度工具（见 MdcgOptions.surface）。
      MDCG_MCP_SURFACE: opts.surface ?? 'full',
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
    return this.bridge.waitReady()
  }

  /** 桥是否已握手就绪。
   *
   * ⚠️ 不可缓存 waitReady() 的结果：waitReady() 在**首次心跳失败**时会立即
   * resolve(false)（见 bridge.ts 的 failed 分支），但桥仍会后台重连成功——
   * 若把这次 false 缓存下来，isReady() 将永久为假，自动记忆 / 互维核验会在
   * 重连成功后静默失效。故一律以桥的实时状态为准。 */
  isReady(): boolean {
    return this.bridge.isReady()
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

  /** 认知图写入入口（MCP `mdcg_remember`）。
   *
   * ⚠️ 唯一写入通道：**不可**改用 `cg(op=write)`（那条路径会被 audit 拦住，
   * 见文件头「写入为什么不能走 cg(op=write)」）。gated=false 直写 `MdCG.add`
   * （默认 layer=knowledge），gated=true 走主动遗忘闸门。 */
  private writeNode(args: Record<string, unknown>): Promise<unknown> {
    return this.call('mdcg_remember', args)
  }

  /** 写入：新增/覆盖一个记忆节点（直写 `MdCG.add`，不经审核队列）。 */
  write(content: string, extra: Record<string, unknown> = {}): Promise<unknown> {
    return this.writeNode({ content, ...extra })
  }

  /** 记忆沉淀（AEIS `remember` 的对应物）：写入情景层并过**主动遗忘闸门**。
   *
   * `mdcg_remember(gated=true)` → `MdCG.remember_gated`：三问 → 四态，
   * ACCEPT 落盘 / MERGE 并入既有（= 去重强化，不新增节点）/ DROP 丢弃低熵
   * 噪音 / DEFER 待定；四种结果都写 `_forgetting.jsonl`，可审计。
   * `importance` 作为 importance_hint 传入（≥0.7 时保护优先、直接 ACCEPT）。
   *
   * layer 默认 contextual：md_cg 对 DSH 会话事件约定的落层就是 contextual，
   * role 取 user | assistant | tool-output（见 md_cg/sources.py 的
   * SESSION_LAYER / DSHSessionSource 事件映射）。 */
  remember(content: string, extra: Record<string, unknown> = {}): Promise<unknown> {
    return this.writeNode({ content, gated: true, layer: 'contextual', ...extra })
  }

  /** 语义召回（AEIS `recall` 的对应物）：`cg(op=read, query)` → md_cg 检索。
   *  读取会记 access log（复用观测），供 importance / scrub 陈旧度使用。 */
  recall(query: string, k = 5): Promise<unknown> {
    return this.read(query, { k })
  }

  /** 外部裁决回填：为已有节点写 confirmed/weakened/falsified。 */
  verify(nodeId: string, evidence: string, verdict: string): Promise<unknown> {
    return this.cg({ op: 'verify', node_id: nodeId, evidence, verdict })
  }

  /** 最近记忆。 */
  recent(limit = 20): Promise<unknown> {
    return this.cg({ op: 'recent', limit })
  }

  /** 最近记忆**时间线**（AEIS `timeline` 的对应物）：`stg(op=timeline)` →
   *  `{count, limit, items:[{id, layer, start, end, preview}]}`，按时间倒序。
   *
   *  只收录带时间区间的节点；而 `cg.add()` 在调用方未给 time_window 时会以
   *  **写入时刻**自动填充（见 mdcg.py 的 OBSERVATION_WINDOW_SEC 分支），故经
   *  本客户端写入的记忆都能进入时间线。
   *  要原始近期**事件**（未结构化对话窗口）请用 `recent()`。 */
  timeline(limit = 4, extra: Record<string, unknown> = {}): Promise<unknown> {
    return this.stg({ op: 'timeline', limit, desc: true, ...extra })
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
