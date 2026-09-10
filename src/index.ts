/**
 * @furongjun1999/dsh-memory —— 灵枢（AEIS）DeepSeek Harness 插件
 *
 * 把灵枢的时空记忆/知识飞轮/自我认知接入 DSH：
 * - 工具桥接：Agent 可调用 lingshu_remember / recall / search / think 等
 * - 自动记忆：DSH 对话自动沉淀进灵枢记忆库（去重+重要性）
 *
 * 用法（cordis.yml）：
 * ```yaml
 * - id: lingshu-memory
 *   name: '@furongjun1999/dsh-memory'
 *   config:
 *     dbPath: 'D:/path/to/lingshu.db'
 *     identity: '灵枢'
 *     memory:
 *       userMessage: true
 * ```
 */

import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import { appendFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { homedir } from 'node:os'
import { LingshuBridge, type McpCallResult } from './bridge.js'
import { registerLingshuTools, type ToolSelection } from './tools.js'
import { installMemoryHooks, type MemoryHooksOptions } from './hooks.js'
// LIB 本地库：角色扮演网页 / 互维维护 / 白箱 LLM 适配器统一收在 src/lib/。
import { installRoleplayWeb } from './lib/roleplay_web.js'
import { MdcgClient } from './lib/mdcg_client.js'

/**
 * 调试探针：记录 apply 失败到独立文件（绕过 DSH 日志系统）。
 * 路径从用户家目录动态解析（issue #5，与 bridge.ts 同因同修）。
 */
const APPLY_ERROR_LOG = join(homedir(), '.dsh', 'logs', 'dsh-memory-apply-error.log')
let applyLogDirReady = false
function probeApplyError(err: unknown): void {
  try {
    if (!applyLogDirReady) {
      mkdirSync(dirname(APPLY_ERROR_LOG), { recursive: true })
      applyLogDirReady = true
    }
    appendFileSync(APPLY_ERROR_LOG, `[${new Date().toISOString()}] apply failed: ${String(err)}\n${(err as Error).stack ?? ''}\n`)
  } catch { /* 探针失败忽略 */ }
}

export const name = 'dsh-memory'

/** P1 修复（GPT 审查）：MCP 调用的标准结果在 content[].text，
 * 代码此前误读不存在的 .result 字段导致互维拿不到 judgment/best/复核文本 */
function mcpText(r: McpCallResult): string {
  return (r.content ?? []).map((c) => c.text ?? '').join('\n')
}

/** 本插件依赖的工具注册服务。
 * P1 修复（GPT 审查）：timer/webServer 是可选增强（互维/角色网页），此前强声明
 * 导致最小 host（只有 tools）插件永远 PENDING 不激活。只强依赖 tools；
 * timer/webServer 在 apply 内动态检测（存在则启用，缺失则告警跳过）。 */
export const inject = ['tools']

/** 插件配置。 */
export interface Config {
  /** 工具命名空间前缀（默认 lingshu → lingshu_remember）。 */
  serverName: string
  /** Python 可执行文件（或 aeis-mcp console script）。 */
  python: string
  /** 传给 python 的参数（默认启动灵枢 MCP server）。 */
  moduleArgs: string[]
  /** 灵枢记忆库 SQLite 路径（目录自动创建）。 */
  dbPath: string
  /** 灵枢身份标识（写入记忆的自我模型）。 */
  identity: string
  /** 额外环境变量（BOCHA_API_KEY / AEIS_DESIGNER_KEY 等，可 !!js 注入）。 */
  env: Record<string, string>
  /** 暴露的工具集合：'core' | 'brain' | 'all' | 工具名数组。 */
  tools: ToolSelection
  /** 护栏宪章版本声明（接入即接受宪章约束，docs/guardrail-charter.md）。 */
  charter: string
  /** 自动记忆开关。 */
  memory: MemoryHooksOptions
  /** 单次工具调用超时（毫秒）。 */
  toolCallTimeoutMs: number
  /** 断线重连最大间隔（毫秒）。 */
  maxRetryDelayMs: number
  /** 启动失败是否让插件激活失败（否则告警后继续重试）。 */
  failOnStartupError: boolean
  /** 互维维护（Mutual Sustain Loop v1.1）：心跳写戳 + 守护 A + 任务验证。 */
  mutual: {
    enabled: boolean
    heartbeatMs: number
  }
  /** 认知图（md_cg）= 记忆唯一真源；AEIS 降为能力库。 */
  mdcg: {
    enabled: boolean
    root: string
    actor: string
    tenant: string
    clearance: string
  }
}

export const Config: z<Config> = z.object({
  serverName: z.string().default('lingshu'),
  python: z.string().default('python'),
  moduleArgs: z.array(String).default(['-m', 'aeis.mcp.server']),
  dbPath: z.string().default('data/lingshu.db'),
  identity: z.string().default('灵枢'),
  env: z.dict(String).default({}),
  tools: z.union([z.const('core'), z.const('brain'), z.const('all'), z.array(String)]).default('brain'),
  /** 护栏宪章版本声明（接入即接受宪章约束，docs/guardrail-charter.md）。 */
  charter: z.string().default('v2.0-published'),
  memory: z
    .object({
      userMessage: z.boolean().default(true),
      assistantMessage: z.boolean().default(false),
      toolResult: z.boolean().default(false),
      importance: z.number().default(0.6),
      autoRecall: z.boolean().default(true),
      autoRecallLimit: z.number().default(4),
      desensitize: z.boolean().default(true),
    })
    .default({ userMessage: true, assistantMessage: false, toolResult: false, importance: 0.6, autoRecall: true, autoRecallLimit: 4, desensitize: true }),
  toolCallTimeoutMs: z.number().default(60_000),
  maxRetryDelayMs: z.number().default(30_000),
  failOnStartupError: z.boolean().default(false),
  /** 角色扮演入口按钮（issue #8）：注入 dsh 首页右上角浮动入口；
   * 关闭后不注入（/roleplay 页面仍可直接访问）。按钮本身支持拖动，
   * 位置记忆在浏览器 localStorage。 */
  roleplayEntryButton: z.boolean().default(true),
  /** 互维维护（v1.1）：心跳 10min / 任务验证双通道。 */
  mutual: z
    .object({
      enabled: z.boolean().default(false),
      heartbeatMs: z.number().default(10 * 60 * 1000),
    })
    .default({ enabled: false, heartbeatMs: 10 * 60 * 1000 }),
  /** 认知图（md_cg）：记忆唯一真源。root 为 MDCG_ROOT（相对路径按工作目录解析）。
   *  tenant/actor 决定私有内容加解密的身份：与 migrate_roleplay 的
   *  --tenant/--actor 必须一致，否则读不到已迁移节点。 */
  mdcg: z
    .object({
      enabled: z.boolean().default(true),
      root: z.string().default('data/mdcg'),
      actor: z.string().default('dsh-memory'),
      tenant: z.string().default('default'),
      clearance: z.string().default('private'),
    })
    .default({ enabled: true, root: 'data/mdcg', actor: 'dsh-memory', tenant: 'default', clearance: 'private' }),
})

/**
 * 插件激活：启动灵枢子进程 → 注册工具 → 安装自动记忆钩子。
 * 卸载时清理全部资源（effect 作用域内自动回收）。
 */
export async function apply(ctx: Context, config: Config): Promise<void> {
  // 宪章宣告（接入即接受宪章约束——docs/guardrail-charter.md v2.0-published）
  ctx.logger.info(
    `dsh-memory: 灵枢插件激活（大脑模式）· 接受护栏宪章 ${config.charter} —— ` +
    '接入即接受宪章约束（公开/可执行/可审计/设计者终裁）',
  )
  const bridge = new LingshuBridge({
    python: config.python,
    args: config.moduleArgs,
    env: {
      AEIS_DB: config.dbPath,
      AEIS_IDENTITY: config.identity,
      ...config.env,
    },
    timeoutMs: config.toolCallTimeoutMs,
    maxRetryDelayMs: config.maxRetryDelayMs,
  })
  bridge.start()
  const ready = await bridge.waitReady()
  if (!ready) {
    const message = '灵枢进程无法启动（检查 python 是否可用、aeis 是否安装：pip install aeis）'
    if (config.failOnStartupError) {
      // P1 修复（GPT 审查）：启动失败抛错前必须 dispose——此前 throw 在 try 之前，
      // 桥接对象泄漏 + 后台重试计时器继续跑
      bridge.dispose()
      throw new Error(message)
    }
    ctx.logger.warn(`dsh-memory: ${message}，继续后台重试`)
  }

  // 认知图（md_cg）= 记忆唯一真源。AEIS 降为能力库（白箱 / 角色生成等）。
  // 插件侧唯一显式入口：src/lib/mdcg_client.ts（每个方法 = 一条 MCP 调用）。
  let mdcg: MdcgClient | null = null
  if (config.mdcg.enabled) {
    mdcg = new MdcgClient({
      python: config.python,
      root: config.mdcg.root,
      actor: config.mdcg.actor,
      tenant: config.mdcg.tenant,
      clearance: config.mdcg.clearance,
      identity: config.identity,
      env: config.env,
      timeoutMs: config.toolCallTimeoutMs,
      maxRetryDelayMs: config.maxRetryDelayMs,
    })
    mdcg.start()
    const mdcgReady = await mdcg.waitReady()
    if (mdcgReady) {
      ctx.logger.info(`dsh-memory: 认知图已就绪（MDCG_ROOT=${config.mdcg.root}）`)
    } else {
      ctx.logger.warn(
        `dsh-memory: 认知图未就绪（MDCG_ROOT=${config.mdcg.root}），`
        + '互维将回退 AEIS 能力库通道（迁移期兼容）',
      )
    }
  }

  const disposers: Array<() => void> = []
  let toolsPoll: NodeJS.Timeout | null = null
  try {
    // 工具注册：初始就绪立即注册；若启动时未就绪（python 暂不可用/aeis 未装等
    // 竞态），桥重连成功后自动补注册——修复"工具永久缺失"问题。
    let toolsRegistered = false
    const tryRegister = async () => {
      if (toolsRegistered || !bridge.isReady()) return
      try {
        const dispose = await registerLingshuTools(ctx, bridge, {
          selection: config.tools,
          toolPrefix: `${config.serverName}_`,
        })
        disposers.push(dispose)
        toolsRegistered = true
        // P1 修复（GPT 审查）：注册成功后清除轮询——此前 setInterval 永久保留
        if (toolsPoll) {
          clearInterval(toolsPoll)
          toolsPoll = null
        }
        ctx.logger.info('dsh-memory: 灵枢工具已注册（就绪后补注册）')
      }
      catch (err) {
        ctx.logger.warn(`dsh-memory: 工具注册失败，稍后重试: ${String(err)}`)
      }
    }
    if (ready) await tryRegister()
    if (!toolsRegistered) {
      toolsPoll = setInterval(() => { void tryRegister() }, 2000)
      disposers.push(() => { if (toolsPoll) clearInterval(toolsPoll) })
    }
    installMemoryHooks(ctx, bridge, config.memory)
    // 角色扮演网页（同源挂载 /roleplay，复用本插件 bridge）
    // mdcg：角色定义/对话转录显式落认知图（md_cg = 唯一真源）。
    await installRoleplayWeb(ctx, bridge, config, disposers, mdcg)

    // 白箱 LLM provider 已下线（2026-09-10）：功能尚不完善，不再注册
    // 'lingshu-whitebox' provider。适配器保留为 LIB 本地库
    // （src/lib/whitebox_llm.ts），白箱能力改由 md_cg 显式调用验证：
    //   MCP cg(op=whitebox, action=verify_encoding|verify_existing)
    // 见 docs/功能调用映射表_v0.1.md。

    // 互维维护（v1.1）：心跳写戳 + 守护 A + 任务验证双通道
    if (config.mutual.enabled) {
      // P1 修复（GPT 审查）：timer 是可选服务——缺失时告警跳过互维，
      // 不让插件因互维而阻塞（inject 已不再强声明 timer）。
      // 注意：不能直接读 ctx.timer——Cordis 未声明 inject 的属性访问会抛
      // "cannot get property without inject"（getter 严格）；ctx.get() 安全。
      const hasTimer = ctx.get('timer') !== undefined
      if (!hasTimer) {
        ctx.logger.warn('dsh-memory: timer 服务不可用，跳过互维维护（mutual.enabled=true 但无 timer）')
      } else {
        const { installMutualMaintenance } = await import('./lib/mutual.js')
        // 双通道 hooks：白箱 base_verify（走 bridge 调灵枢）+ DeepSeek 复核
        installMutualMaintenance(
          ctx as never,
          { heartbeatMs: config.mutual.heartbeatMs },
          {
            // memory 通道 → 认知图（md_cg = 唯一真源）。
            // 显式调用：MdcgClient.verifyClaim → cg(op=read) + 依据强度判定。
            // 认知图未就绪时回退 AEIS 能力库 wisdom_verify（迁移期兼容）。
            verify: async (claim: string) => {
              if (mdcg?.isReady()) {
                try {
                  return await mdcg.verifyClaim(claim)
                } catch (err) {
                  ctx.logger.warn(`dsh-memory: 认知图核验失败，回退能力库：${String(err)}`)
                }
              }
              const r = await bridge.callTool('wisdom_verify', { knowledge: claim, limit: 4 })
              // P1 修复（GPT 审查）：结果在 content[].text（JSON），非 .result
              const text = mcpText(r)
              let data: { judgment?: string; best?: { name?: string }; D_norm?: number; record_id?: string } = {}
              try {
                data = JSON.parse(text) as typeof data
              } catch { /* 非 JSON 时用默认 */ }
              return {
                judgment: data.judgment ?? '分析中',
                best: data.best?.name ?? '',
                d_norm: typeof data.D_norm === 'number' ? data.D_norm : -1,
                record_id: data.record_id ?? '',
              }
            },
            review: async (claim: string, w) => {
              // DeepSeek 复核（在白箱判定之上，不重复白箱工作）
              const reviewResult = await bridge.callTool('think', {
                query: `复核以下主张（白箱判定已给出，请独立评估是否同意）：${claim.slice(0, 200)}。白箱判定：${w.judgment}，best=${w.best}。只输出 同意/质疑/不同意 + 一句话理由`,
              })
              // P1 修复（GPT 审查）：文本在 content[].text；结论解析必须先查
              // 「不同意/不通过」再「质疑」再「同意」——「不同意」含子串「同意」，
              // 此前先匹配「同意」→ 不同意被误判为同意
              const text = mcpText(reviewResult)
              const conclusion = text.includes('不同意') || text.includes('不通过')
                ? '不同意'
                : text.includes('质疑') ? '质疑'
                : text.includes('同意') ? '同意' : '不同意'
              return { conclusion, reason: text.slice(0, 120) }
            },
          },
        )
        ctx.logger.info('dsh-memory: 互维维护已启用（心跳 10min + 守护 A + 任务验证双通道）')
      }
    }
  } catch (err) {
    // 探针：记录 apply 失败的具体错误（定位插件加载失败根因）
    probeApplyError(err)
    mdcg?.dispose()
    bridge.dispose()
    throw err
  }

  ctx.effect(() => {
    return () => {
      for (const dispose of disposers) dispose()
      mdcg?.dispose()
      bridge.dispose()
      ctx.logger.info('dsh-memory: 已卸载（工具已注销，灵枢/认知图进程已退出）')
    }
  }, 'dsh-memory')
}
