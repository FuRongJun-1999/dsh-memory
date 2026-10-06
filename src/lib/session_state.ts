/**
 * session_state.ts —— 插件侧「运行期会话状态」单点（观测 → 写归因注入）
 *
 * 为什么有这个模块（B 治本批，2026-10-06）
 * ----------------------------------------
 * DSH 单进程多会话：宿主的会话标识只经 `session/event` 到达插件。此前它只被
 * 用在 hooks 面（自动记忆的 remember / read 带 extra.session）；**agent 直调
 * 工具面**（src/tools.ts 的 execute → bridge.callTool）转发时**不带会话**——
 * 而部署侧 `MDCG_SESSION` env 一旦取消/为空，`md_cg/mcp_server.py` 的
 * `_declared_session`（:3823-3850）就以**请求声明**为归因来源
 * （优先级：env > 请求声明 > 进程身份），不传即落回进程身份——md_cg 的
 * `Principal.__init__` 会为假值 session 生成**进程级随机** `sess_<hex>`
 * （md_cg/security.py:117）：归属在审计上既读不出是谁、跨进程也对不上，
 * 是静默的归属丢失。
 *
 * 本模块把「观测会话」与「写归因注入」收成**单点**：
 *   · hooks 面：每收到 session/event 就 `noteSession(sid)`——调用点仍在 H1
 *     子代理闸**之后**（子代理会话不得污染会话状态的位置不变量保持）；
 *   · 工具面：写归因调用注入 `currentSession() || UNASSIGNED_SESSION`
 *     （判据矩阵见 `attributeSession`，只注入写面；读面一律不注入）。
 *
 * 模块级状态（`lastSession`）是**进程级**的：同一进程内多个会话共享它，
 * 「最近一次观测」即当前活动会话——与 hooks 面的既有口径一致（见
 * test/session-attribution.test.ts ④「取值每步稳定」）。
 */

/** 会话归属未知时的**显式占位**（H2③，2026-09-30；原定义在 src/hooks.ts，
 *  B 治本批迁入本单点——注释要点保真搬迁）。
 *
 *  ⚠️ 不可退回「不传 session 键」：md_cg 的 `Principal.__init__` 在 session 为假值时
 *  生成**进程级随机** `sess_<hex>`（md_cg/security.py:117）——插件不传，等于让一个
 *  进程内所有「宿主未给标识」的会话共用一个**不可辨认**的随机桶：归属在审计上既
 *  读不出是谁、跨进程也对不上，是静默的归属丢失。
 *  本常量把这一态写成**显式值**：跨进程一致、可辨认、可审计，且不是伪造的宿主
 *  会话 id（非 DSH 形态，服务端 `_normalize_session` 原样采用、不会被改写成别的桶）。
 *  要读这个桶：`stg(op=timeline, session="unassigned")`。 */
export const UNASSIGNED_SESSION = 'unassigned'

/** 最近一次观测到的宿主会话标识（空串 = 未观测到会话）。
 *
 *  ⚠️ 本状态是**模块级（进程级）单点**：hooks 面观测写入（src/hooks.ts 的
 *  session/event），工具面读它做写归因注入（src/tools.ts 的转发面）——两处必须
 *  同源，否则注入的会话与写入的归属对不上（B 治本批的目的即在此）。
 *
 *  「本实例是否观测过」的**实例级门不在本模块**，在 src/hooks.ts 的
 *  installMemoryHooks 内（局部 `observedSession`）：即「本实例观测到会话之后」
 *  才用本单点值回落召回过滤。这是**经 owner 裁定的契约字面偏离（dwfq-7b3a555e-1）**
 *  ——契约建议的形态是 hooks 侧字面 `|| currentSession()`，但字面形态与硬边界
 *  「test/session-attribution.test.ts 逐字未动且全绿」互斥（该守卫 ② 以
 *  「新建 harness = 未观测」为前提，字面回落会读成前一实例的 sess_B）。保留
 *  实例门的两条理由：
 *    ① 「新实例 = 干净状态」是原闭包变量 `lastSession` 的**有意属性**（新装的钩子
 *       在观测到会话前，自动召回不加过滤）——实例隔离语义在测试面被真实保留；
 *    ② 与既有冻结守卫 ② 相容（守卫逐字未动且全绿是本批硬边界）。
 *  真机单实例下两者**逐位等价**：唯一差异窗口是「本实例未观测 ∧ 模块单点非空」，
 *  而模块值只由本实例的 hooks 观测写入，单实例下该窗口不可达；HMR 重载场景下新
 *  实例回落 '' 而非上一会话值，属更保守的防御行为（已由 owner 裁定接受）。 */
let lastSession = ''

/** 记录一次会话观测（H2③ 观测面单点）。
 *
 *  trim 后非空才写入——空串/纯空白**不覆盖**旧值（否则「宿主给了一次空标识」
 *  会把已观测到的真会话抹掉，后续注入退化为 unassigned）。 */
export function noteSession(sid: string): void {
  const s = sid.trim()
  if (s) lastSession = s
}

/** 当前运行期会话标识（空串 = 未观测到；调用方按 `|| UNASSIGNED_SESSION` 兜底）。 */
export function currentSession(): string {
  return lastSession
}

/** 写归因面判据：本次调用是否属于「要注入运行期会话」的写归因调用。
 *
 *  **恰两条命中路径**（不得放宽、不得收窄出契约外）：
 *    ① `mdcg_remember` —— md_cg 细粒度写入口（插件侧自动记忆/落图的写通道）；
 *    ② `cg` 且 `op === 'write'` —— 认知图基元的带审核写路径。
 *
 *  为什么**只**这两个面（判据出处：md_cg/mcp_server.py）：
 *    · **读面一律不注入**——`mdcg_recall` / `mdcg_search` / `mdcg_get` / `stg`
 *      以及 `cg` 的其它 op，其 `session` 是**视图过滤**：服务端 schema 描述原文
 *      「会话归属过滤（frontmatter.session；…缺省不过滤）」
 *      （md_cg/mcp_server.py:218-219 / :251-252 / :908-912 / :1074-1077）。
 *      注入会把文档化的「缺省跨会话」翻转成「本会话视图」——那是功能收窄，
 *      不是本批目标（读面要跨会话视图请显式 `stg(op=timeline, session="*")`）。
 *    · **op 特化语义不动**——`cg` 的 `sustain`/`session` 等 op 的 `session` 是
 *      特化语义（resume/note 的**目标会话**），注入即污染其目标参数。
 *    · 归因与授权正交（issue #35 定稿）：`call_tool` 的请求级 session **只做
 *      归因**（写入归属/`_attribution` 取它），**不**改 `principal.session`
 *      （md_cg/mcp_server.py:3261-3264）——绑定档（private/secret）的读授权
 *      锚定连接级身份，调用方自报的会话不构成看他人 private 的授权。
 *      绑定档可见性判定 `MdCGSecure._readable`（md_cg/mdcos.py:5009-5053）
 *      的会话绑定分支恒用 `nsess == self.principal.session`（:5051-5052），
 *      can_admin（设计者）豁免（:5045）——故本注入对绑定档无回归。
 *
 *  ⚠️ 禁止把本判据放宽成「所有带 session 参数的工具」：那会把上面两类语义
 *  （读面视图过滤 / op 特化目标）一并改写，属越权改契约。
 */
function isWriteAttributionCall(toolName: string, args: Record<string, unknown>): boolean {
  if (toolName === 'mdcg_remember') return true
  return toolName === 'cg' && args['op'] === 'write'
}

/** 请求是否已显式声明会话（string 且 trim 后非空 → 保留调用方声明，绝不覆盖）。 */
function hasDeclaredSession(args: Record<string, unknown>): boolean {
  const v = args['session']
  return typeof v === 'string' && v.trim() !== ''
}

/** 把**运行期会话**注入**写归因调用**（args 的 session 键不可用时才注入）。
 *
 *  注入条件：`session` 键缺失 / 非 string 类型 / trim 后空串 ⇒ 注入
 *  （`null`/`''`/空白一律视为「未声明」——服务端 `_declared_session` 对假值
 *  同样解析为无归属声明，原样转发只会落回进程级随机 sess_* 兜底桶）；
 *  显式非空声明一律**不覆盖**（调用方自报优先——插件不替调用方改归属）。
 *
 *  注入值：`currentSession() || UNASSIGNED_SESSION`（未观测到会话时用
 *  'unassigned' 显式占位——与 hooks 面 H2③ 同口径）。
 *
 *  命中且需注入 → 返回**新对象** `{ ...args, session: v }`（绝不 mutate 输入）；
 *  否则**原样返回**（同一引用）——未命中的调用零开销、零可观察差异。 */
export function attributeSession(toolName: string, args: Record<string, unknown>): Record<string, unknown> {
  if (!isWriteAttributionCall(toolName, args)) return args
  if (hasDeclaredSession(args)) return args
  return { ...args, session: currentSession() || UNASSIGNED_SESSION }
}
