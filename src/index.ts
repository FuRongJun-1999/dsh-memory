/**
 * @furongjun1999/dsh-memory —— 灵枢 DeepSeek Harness 插件
 * （大脑唯一真源 = md_cg 认知图；aeis 能力库已下线）
 *
 * 把灵枢的时空记忆/知识飞轮/自我认知接入 DSH：
 * - 记忆唯一真源：**md_cg 认知图（md 文档）**，插件侧唯一显式入口
 *   `src/lib/mdcg_client.ts`（每个方法 = 一条 MCP cg / stg 调用）
 * - 工具桥接：Agent 可调用工具，经**唯一的大脑桥**（同一 md_cg 子进程）从
 *   **md_cg.mcp_server** 拉取（`MDCG_MCP_SURFACE=full`：`cg` / `stg` 基元 +
 *   `mdcg_*` 细粒度全家，再由 `config.tools` 选择表筛），注册为 `lingshu_<name>`
 * - 自动记忆：DSH 对话经**认知图**自动沉淀（主动遗忘闸门去重 + 重要性 + 脱敏）
 * - 使命分离：理论仓（CTP）只留方法论文档，工程代码全部在主仓 md_cg
 *
 * 用法（cordis.yml）：
 * ```yaml
 * - id: lingshu-memory
 *   name: '@furongjun1999/dsh-memory'
 *   config:
 *     mdcg:                              # 记忆真源：认知图（md 文档）
 *       # root = 记忆写入路径（用户可改）。缺省 = 插件仓自身 data/mdcg。
 *       # 覆盖优先级：env MDCG_ROOT > <插件仓>/data/paths.json > 本项 > 默认
 *       # root: 'D:/somewhere/mdcg'        # 例：把记忆库放到别处
 *       actor: 'dsh-memory'
 *     env:                               # 写入凭据：默认【关闭】，由你决定是否打开
 *       # 不配 → 只读 guest：读/召回/时间线可用，自动记忆/转录/落图不落盘（启动会告警）
 *       # 打开①推荐：先签发再引用（明文不进配置文件）
 *       #   python -m md_cg.tokens issue --role designer --actor dsh-memory \
 *       #     --clearance internal \
 *       #     --ops-allow info,route,read,write,recent,goal,identity,whitebox,verify \
 *       #     --layers-allow knowledge,contextual,structural,self,goals,unresolved,rejected
 *       # MDCG_TOKEN: !!js process.env.MDCG_TOKEN
 *       # 打开②最小权限：--role recorder（无 whitebox/identity/verify，不能写 self 层）
 *       # 打开③兼容旧部署（不推荐）：MDCG_LEGACY_ENV_AUTH: '1'
 *     dbPath: '/path/to/legacy.db'       # 遗留：仅角色数据目录推导用（不存记忆）
 *     capability:                        # 可选「身体」后端（默认关 → 单进程纯大脑）
 *       enabled: false
 *       args: ['-m', 'aeis.mcp.server']
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
import { describeDataPaths, mdcgRoot } from './lib/datapath.js'
// 写入凭据密钥环（首启引导）：显式配置 → ~/.mdcg/token → 首启自动签发。
import { resolveToken, type TokenResolution } from './lib/token_store.js'

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
  /** Python 可执行文件（或 md_cg-mcp console script）。 */
  python: string
  /** 传给 python 的参数（默认启动 md_cg MCP server）。 */
  moduleArgs: string[]
  /** ⚠️ 遗留项：SQLite 库文件路径（经 `AEIS_DB` 传给子进程），目录自动创建。
   * 大脑真源已统一到 `mdcg`（认知图）；此项仅供角色数据目录 roleDataDir
   * （由它的父目录推导）使用，**不再存记忆**，md_cg server 也不读取它。 */
  dbPath: string
  /** 灵枢身份标识（写入记忆的自我模型）。 */
  identity: string
  /** 额外环境变量（BOCHA_API_KEY / AEIS_DESIGNER_KEY 等，可 !!js 注入）。 */
  env: Record<string, string>
  /** 暴露的工具集合：'core'（默认，仅 cg/stg 两基元）| 'brain'（完整认知面）
   *  | 'all' | 工具名数组。 */
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
  /** 「身体」能力后端（可选）：角色扮演生成等「身」的生成能力。
   *
   *  默认**不挂载** —— 主仓保持纯大脑单进程（只起 md_cg）。配置 enabled 后
   *  额外起一个能力库子进程（如 AEIS），仅角色扮演生成使用；记忆真源仍是
   *  md_cg（大脑），本后端不存记忆。未挂载时角色生成接口 fail-closed。 */
  capability: {
    enabled: boolean
    python: string
    args: string[]
  }
}

export const Config: z<Config> = z.object({
  serverName: z.string().default('lingshu'),
  python: z.string().default('python'),
  moduleArgs: z.array(String).default(['-m', 'md_cg.mcp_server']),
  dbPath: z.string().default('data/lingshu.db'),
  identity: z.string().default('灵枢'),
  env: z.dict(String).default({}),
  tools: z.union([z.const('core'), z.const('brain'), z.const('all'), z.array(String)]).default('core'),
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
   * **默认关闭**：该功能尚未开放，右上角浮动按钮会遮挡 GUI 侧边栏；
   * 显式设 true 才注入；/roleplay 页面仍可直接访问。按钮支持拖动，
   * 位置记忆在浏览器 localStorage。 */
  roleplayEntryButton: z.boolean().default(false),
  /** 互维维护（v1.1）：心跳 10min / 任务验证双通道。 */
  mutual: z
    .object({
      enabled: z.boolean().default(false),
      heartbeatMs: z.number().default(10 * 60 * 1000),
    })
    .default({ enabled: false, heartbeatMs: 10 * 60 * 1000 }),
  /** 认知图（md_cg）：记忆唯一真源。
   *  root 为**记忆写入路径**（用户可改）。缺省空串 = 未指定，按优先级解析：
   *    ① env MDCG_ROOT ② `<插件仓>/data/paths.json` 的 root
   *    ③ 本项 ④ 默认 `<插件仓>/data/mdcg`
   *  相对路径一律相对**插件仓根**解析——历史教训：相对 cwd 的相对路径随
   *  宿主 cwd 漂移，cwd 落在别仓时记忆真源分裂成互不可见的两处。
   *  tenant/actor 决定私有内容加解密的身份：与 migrate_roleplay 的
   *  --tenant/--actor 必须一致，否则读不到已迁移节点。 */
  mdcg: z
    .object({
      enabled: z.boolean().default(true),
      root: z.string().default(''),
      actor: z.string().default('dsh-memory'),
      tenant: z.string().default('default'),
      clearance: z.string().default('private'),
    })
    .default({ enabled: true, root: '', actor: 'dsh-memory', tenant: 'default', clearance: 'private' }),
  /** 「身体」能力后端（可选）：默认关闭 → 单进程纯大脑。
   *  开启需同时给出 args（能力库启动参数），否则跳过并告警。 */
  capability: z
    .object({
      enabled: z.boolean().default(false),
      python: z.string().default(''),
      args: z.array(String).default([]),
    })
    .default({ enabled: false, python: '', args: [] }),
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
  // ═══ 大脑进程：md_cg（主仓自带）——**唯一**子进程 ═══
  // 工具面 / 记忆写入 / 互维核验 / 角色落图共用这一个桥。S4（2026-09-10）已删除
  // 历史上并存的第二个 aeis 进程：双进程方案下两侧工具名互不交集（86 vs 33，
  // 交集为 0），切换时会静默丢功能；收敛为单进程后由 MDCG_MCP_SURFACE=full
  // 提供完整认知面。插件侧唯一显式入口：src/lib/mdcg_client.ts（一方法 = 一条 MCP 调用）。
  let mdcg: MdcgClient | null = null
  let brainReady = false
  /** 写入凭据解析结果（首启引导；诊断与启动日志用）。 */
  let cred: TokenResolution | null = null
  /** 记忆真源解析结果（「新写入去哪」）——用户可改：env > paths.json > 配置 > 默认自身仓 data/。 */
  const resolvedRoot = mdcgRoot(config.mdcg.root)
  if (config.mdcg.enabled) {
    // ── 写入凭据解析（首启引导）：显式配置 → 密钥环 → 首启自动签发 ──
    // 为什么需要：md_cg 无令牌即降级只读 guest，自动记忆 / 转录 / 角色落图
    // **静默不落盘**——「装好了插件，但记忆永远是空的」是最难定位的失效形态。
    // 解析顺序与「自动签发不降低实际安全强度」的论证见 lib/token_store.ts 文件头。
    // legacy env 认证本就等价于「已显式授权」→ 不再签发，避免多签一枚无用令牌。
    const legacyAuth = config.env.MDCG_LEGACY_ENV_AUTH ?? process.env.MDCG_LEGACY_ENV_AUTH
    const resolution = resolveToken({
      python: config.python,
      configured: config.env.MDCG_TOKEN,
      actor: config.mdcg.actor,
      clearance: config.mdcg.clearance,
      autoIssue: !legacyAuth,
    })
    cred = resolution
    // 注入子进程 env：显式配置与密钥环都在此汇合成**唯一**的 MDCG_TOKEN。
    const mdcgEnv: Record<string, string> = { ...config.env }
    if (resolution.token) mdcgEnv.MDCG_TOKEN = resolution.token
    mdcg = new MdcgClient({
      python: config.python,
      args: config.moduleArgs,
      root: resolvedRoot,
      actor: config.mdcg.actor,
      tenant: config.mdcg.tenant,
      clearance: config.mdcg.clearance,
      identity: config.identity,
      env: mdcgEnv,
      timeoutMs: config.toolCallTimeoutMs,
      maxRetryDelayMs: config.maxRetryDelayMs,
    })
    mdcg.start()
    // 启动留痕：把「记忆真源在哪、由谁决定、路径是否存在」写进可审计日志，
    // 避免再次出现「以为在记忆、其实写到了别仓」的静默分裂（历史事故）。
    const dp = describeDataPaths(config.mdcg.root)
    ctx.logger.info(
      `dsh-memory: 记忆真源路径 = ${dp.mdcgRoot}（来源 ${dp.source}，`
      + `dataRoot=${dp.dataRoot}，存在=${dp.mdcgRootExists ? '是' : '否（首次写入将创建）'}，`
      + `用户可改：${dp.pathsFile}）`,
    )
    brainReady = await mdcg.waitReady()
    if (brainReady) {
      ctx.logger.info(`dsh-memory: 认知图已就绪（MDCG_ROOT=${resolvedRoot}）`)
    } else {
      ctx.logger.warn(
        `dsh-memory: 认知图未就绪（MDCG_ROOT=${resolvedRoot}），`
        + '核验按白箱纪律 fail-closed；桥将后台重连并在就绪后补注册工具。',
      )
    }
    // 写入凭据检查（fail-closed）：凭据来源已由 token_store 解析（见上）。
    // ① 显式配置 / 密钥环 / 首启自动签发 → 可写；② 都不行 → 只读 guest，必须告警。
    // 告警仍是硬要求：guest 下读 / 召回 / 时间线照常，但自动记忆、转录、
    // 角色落图**不落盘**——不吭声就是「看起来在记忆、其实没落盘」。
    const authEnv: Record<string, string | undefined> = { ...process.env, ...config.env }
    if (!cred.token && !authEnv.MDCG_LEGACY_ENV_AUTH) {
      ctx.logger.warn(
        'dsh-memory: 认知图写入凭据不可用，以只读 guest 运行——'
        + '读 / 召回 / 时间线可用，但自动记忆、转录、角色落图不会落盘。'
        + (cred.note ? `原因：${cred.note}。` : '')
        + '要打开：签发令牌 MDCG_TOKEN 经 config.env 注入（见 cordis.yml.example），'
        + '或删除密钥环后重启以重新自动签发。')
    } else if (cred.source === 'issued') {
      // 首启引导：自动签发是**改变用户可写权限**的动作，必须留痕（含关闭/吊销方式）。
      ctx.logger.info(`dsh-memory: ${cred.note}`)
    } else {
      ctx.logger.info(
        `dsh-memory: 认知图写入凭据来源=${cred.source}（密钥环 ${cred.keyringPath}）`
        + '——自动记忆 / 转录 / 角色落图已开启')
    }
  } else {
    ctx.logger.warn('dsh-memory: mdcg.enabled=false —— 大脑（认知图）未启动，工具与自动记忆不可用')
  }

  /** 大脑桥：工具面 + 互维 + 角色落图共用的唯一 md_cg 通道（mdcg 关闭时为 null）。 */
  const bridge = mdcg?.bridge ?? null
  if (!brainReady) {
    const message = '灵枢大脑（md_cg）未就绪（检查 python 是否可用、md_cg 是否可导入：python -m md_cg.mcp_server）'
    if (config.failOnStartupError && config.mdcg.enabled) {
      // P1 修复（GPT 审查）：启动失败抛错前必须 dispose——此前 throw 在 try 之前，
      // 桥接对象泄漏 + 后台重试计时器继续跑
      mdcg?.dispose()
      throw new Error(message)
    }
    ctx.logger.warn(`dsh-memory: ${message}，继续后台重试`)
  }

  // ═══ 「身体」能力后端（可选）—— 角色扮演生成等「身」的生成能力 ═══
  // 默认**不挂载**：主仓保持纯大脑单进程（只起 md_cg）。开启后额外起一个能力库
  // 子进程（如 AEIS），**仅**角色扮演生成使用；记忆真源仍是 md_cg（大脑）。
  // 未挂载时角色生成接口 fail-closed（返回明确原因，不编造回复）。
  let capability: LingshuBridge | null = null
  if (config.capability.enabled) {
    if (!config.capability.args.length) {
      ctx.logger.warn('dsh-memory: capability.enabled=true 但未配置 capability.args，跳过身体能力后端')
    } else {
      capability = new LingshuBridge({
        python: config.capability.python || config.python,
        args: config.capability.args,
        env: {
          // 能力库的旧版数据目录约定（AEIS_* 为遗留名，md_cg 不读）。
          AEIS_DB: config.dbPath,
          AEIS_IDENTITY: config.identity,
          ...config.env,
        },
        timeoutMs: config.toolCallTimeoutMs,
        maxRetryDelayMs: config.maxRetryDelayMs,
      })
      capability.start()
      if (!(await capability.waitReady())) {
        ctx.logger.warn('dsh-memory: 身体能力后端未就绪，角色生成接口将 fail-closed（不编造回复）')
      }
    }
  }

  const disposers: Array<() => void> = []
  let toolsPoll: NodeJS.Timeout | null = null
  try {
    // 工具注册：初始就绪立即注册；若启动时未就绪（python 暂不可用等
    // 竞态），桥重连成功后自动补注册——修复"工具永久缺失"问题。
    let toolsRegistered = false
    const tryRegister = async () => {
      if (toolsRegistered || !bridge?.isReady()) return
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
    if (brainReady) await tryRegister()
    if (!toolsRegistered) {
      toolsPoll = setInterval(() => { void tryRegister() }, 2000)
      disposers.push(() => { if (toolsPoll) clearInterval(toolsPoll) })
    }
    // 自动记忆：沉淀进 md_cg 认知图（记忆唯一真源）。mdcg=null 时整体停用。
    installMemoryHooks(ctx, mdcg, config.memory)
    // 角色扮演网页（同源挂载 /roleplay）：生成能力走可选「身体」后端（capability），
    // 转录/历史/翻译/落图走大脑（mdcg）。capability=null 时生成接口 fail-closed。
    await installRoleplayWeb(ctx, capability, config, disposers, mdcg)

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
        // 双通道 hooks：白箱 base_verify（mdcg.verifyClaim 走认知图）+ 宿主 LLM 复核
        installMutualMaintenance(
          ctx as never,
          { heartbeatMs: config.mutual.heartbeatMs },
          {
            // memory 通道 → 认知图（md_cg = 唯一真源）。
            // 显式调用：MdcgClient.verifyClaim → cg(op=read) + 依据强度判定。
            // 回退通道已下线（aeis 能力库随进程剥离；md_cg 是唯一大脑）：
            // 认知图不可用时按白箱纪律 fail-closed，不编造判定。
            verify: async (claim: string) => {
              if (mdcg?.isReady()) {
                try {
                  return await mdcg.verifyClaim(claim)
                } catch (err) {
                  ctx.logger.warn(`dsh-memory: 认知图核验失败，按 fail-closed 处理：${String(err)}`)
                }
              } else {
                ctx.logger.warn('dsh-memory: 认知图未就绪，核验按 fail-closed 处理')
              }
              return { judgment: '无法核验', best: '', d_norm: -1, record_id: '' }
            },
            review: async (claim: string, w) => {
              // 复核通道改走**宿主 LLM**（aeis 的 think 工具随进程下线）。
              // 取 llm 服务：Cordis 未 inject 的属性访问会抛，ctx.get 安全返回 undefined。
              const llm = ctx.get('llm') as
                | {
                  stream?: (o: Record<string, unknown>) => AsyncIterable<{ type?: string; text?: string }>
                  listProviders?: () => Array<{ id?: string; model?: string }>
                }
                | undefined
              const prov = llm?.listProviders?.()
                ?.find((p) => p?.id && p.id !== 'lingshu-whitebox')
              if (!llm?.stream || !prov?.id) {
                ctx.logger.warn('dsh-memory: 宿主 LLM 不可用，复核按 fail-closed 处理（不编造结论）')
                return { conclusion: '不同意', reason: '复核通道不可用（宿主 LLM 未就绪）' }
              }
              let text = ''
              try {
                const stream = llm.stream({
                  provider: prov.id,
                  model: prov.model ?? prov.id,
                  messages: [{
                    role: 'user',
                    content: [{
                      type: 'text',
                      text: `复核以下主张（白箱判定已给出，请独立评估是否同意）：${claim.slice(0, 200)}。白箱判定：${w.judgment}，best=${w.best}。只输出 同意/质疑/不同意 + 一句话理由`,
                    }],
                  }],
                  maxTokens: 256,
                })
                for await (const chunk of stream) {
                  if (typeof chunk?.text === 'string' && chunk.type !== 'reasoning-delta') text += chunk.text
                }
              } catch (err) {
                ctx.logger.warn(`dsh-memory: 复核 LLM 调用失败，按 fail-closed 处理：${String(err)}`)
                return { conclusion: '不同意', reason: '复核调用失败（fail-closed）' }
              }
              // 结论解析：必须先查「不同意/不通过」再「质疑」再「同意」——「不同意」
              // 含子串「同意」，颠倒顺序会把不同意误判为同意（P1 修复，勿回退）。
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
    capability?.dispose()
    throw err
  }

  ctx.effect(() => {
    return () => {
      for (const dispose of disposers) dispose()
      mdcg?.dispose()
      capability?.dispose()
      ctx.logger.info('dsh-memory: 已卸载（工具已注销，md_cg 大脑 / 可选身体后端进程已退出）')
    }
  }, 'dsh-memory')
}
