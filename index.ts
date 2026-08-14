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
import { LingshuBridge } from './bridge.js'
import { registerLingshuTools, type ToolSelection } from './tools.js'
import { installMemoryHooks, type MemoryHooksOptions } from './hooks.js'

export const name = 'dsh-memory'

/** 本插件依赖的工具注册服务。 */
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
    })
    .default({ userMessage: true, assistantMessage: false, toolResult: false, importance: 0.6 }),
  toolCallTimeoutMs: z.number().default(60_000),
  maxRetryDelayMs: z.number().default(30_000),
  failOnStartupError: z.boolean().default(false),
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
    if (config.failOnStartupError) throw new Error(message)
    ctx.logger.warn(`dsh-memory: ${message}，继续后台重试`)
  }

  const disposers: Array<() => void> = []
  try {
    // 工具注册（就绪后执行；未就绪时 tools/list 会报错，由重连机制兜底）
    if (ready) {
      disposers.push(
        await registerLingshuTools(ctx, bridge, {
          selection: config.tools,
          toolPrefix: `${config.serverName}_`,
        }),
      )
    }
    installMemoryHooks(ctx, bridge, config.memory)
  } catch (err) {
    bridge.dispose()
    throw err
  }

  ctx.effect(() => {
    return () => {
      for (const dispose of disposers) dispose()
      bridge.dispose()
      ctx.logger.info('dsh-memory: 已卸载（工具已注销，灵枢进程已退出）')
    }
  }, 'dsh-memory')
}
