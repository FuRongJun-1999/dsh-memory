/**
 * token_store.ts —— 灵枢写入凭据的**密钥环**（默认 `~/.mdcg/token`）
 *
 * 要解决的问题（首启静默失效）
 * ------------------------------------------------
 * 灵枢大脑（md_cg）用令牌做身份与权限判定：**无令牌即降级只读 guest**，
 * 此时自动记忆 / 对话转录 / 角色落图**全部不落盘**（`_build_principal` 的
 * guest 分支，且启动会告警）。对「不知道需要签发令牌」的用户，这表现为
 * **「装好了插件，但记忆永远是空的」**——一种没有任何报错的失效形态。
 *
 * 本模块把这条路径补齐，解析顺序（高 → 低）：
 *   ① `config.env.MDCG_TOKEN` —— 显式配置，原样尊重，**完全不介入**；
 *   ② 进程 env `MDCG_TOKEN` —— 同上；
 *   ③ 密钥环 `~/.mdcg/token`（0600）—— 已签发过则复用（复用前先 `tokens verify`
 *      复核，确证失效〔rc=2〕才换新——新签发成功后由 writeKeyring 覆写，签发
 *      失败则原文件保留——#224-③＋#368 复核必须 1/3，否则吊销后插件永久拒启）；
 *   ④ 都没有 → **首启自动签发**一枚 designer 令牌并写入密钥环（#224-①：非
 *      default 租户随 `--tenant` 透传进令牌记录）。
 *
 * 为什么密钥环可以自动签发（安全论证）
 * ------------------------------------------------
 * 能读到该文件的进程，本就以该用户身份运行，也就本就能读写该用户的全部文件
 * ——自动签发**不降低实际安全强度**。真正需要显式管理令牌的场景（多用户机 /
 * 想要权职分离 / 审计要求）用 `MDCG_AUTO_ISSUE=0` 关闭，改走手工签发。
 *
 * 与 `md_cg/tokens.py` 的对应
 * ------------------------------------------------
 * 密钥环与 `tokens.py` 的 `~/.mdcg/_tokens.json`（令牌记录）同目录，但**职责不同**：
 * 密钥环存**明文令牌**（给本机客户端用），`_tokens.json` 存**哈希与元数据**（校验用）。
 * 二者格式不做任何修改——本模块只是 `python -m md_cg.tokens issue` 的一层封装。
 */
import { spawnSync } from 'node:child_process'
import { chmodSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { pythonPathValue, runRoot } from './datapath.js'

/** 凭据来源（用于启动日志与故障定位）。 */
export type TokenSource =
  | 'config'       // config.env.MDCG_TOKEN（显式配置，原样尊重）
  | 'process-env'  // 插件进程 env 的 MDCG_TOKEN
  | 'keyring'      // 密钥环 ~/.mdcg/token
  | 'issued'       // 首启自动签发并写入密钥环
  | 'disabled'     // 显式关闭自动签发，且无既有凭据
  | 'none'         // 签发不可用（如 Python 不可执行），md_cg 侧将降级只读 guest

export interface TokenResolution {
  /** 明文令牌；未解析到时为 undefined（md_cg 侧降级只读 guest）。 */
  token?: string
  source: TokenSource
  /** 人类可读的补充说明（写启动日志用，含关闭 / 吊销方式）。 */
  note?: string
  /** 密钥环路径（诊断用）。 */
  keyringPath: string
}

export interface ResolveTokenOptions {
  /** Python 可执行文件（与 md_cg 子进程同源，保证 import 环境一致）。 */
  python: string
  /** 显式配置的令牌（config.env.MDCG_TOKEN）。 */
  configured?: string
  /** 签发主体标识（写入令牌记录，默认 dsh-memory）。 */
  actor?: string
  /** 签发角色（默认 designer = 设计者载体；其它角色见 tokens.ROLE_SPECS）。 */
  role?: string
  /** 签发密级上限（默认 internal，与 md_cg 的 DEFAULT_SENSITIVITY 对齐）。 */
  clearance?: string
  /** 是否允许首启自动签发（默认 true；legacy env 认证场景应传 false）。 */
  autoIssue?: boolean
  /** 密钥环路径覆盖（默认 ~/.mdcg/token）。 */
  keyringPath?: string
  /** 租户标识（写入令牌记录；cordis.yml 的 mdcg.tenant 透传，#224）。
   *  非 default 时才传给 `tokens issue --tenant`——default 是 md_cg 侧缺省，显式传等值冗余。 */
  tenant?: string
  /** config.env 的键值（#224：MDCG_AUX_ROOT 等应读 config.env——与 resolveToken
   *  对 MDCG_TOKEN 的既有优先级同构：显式参数 > config.env > 进程 env > 缺省）。 */
  envOverride?: Record<string, string | undefined>
}

/** 辅助存储根（密钥/令牌/信任/理论/心跳）：与 md_cg 的 `datapath.aux_root()` 同口径。
 *
 *  默认 `~/.mdcg`（历史值，**逐字保留**——改默认会让存量密钥/令牌失联）；
 *  `MDCG_AUX_ROOT` 可把它们整体搬走（沙箱/多用户/与记忆真源同处的场景）。
 *  与 `config.mdcg.root`（记忆真源）有意分离：身份与信任不随认知图迁移。 */
export function auxRoot(envOverride?: Record<string, string | undefined>): string {
  // #224-②：config.env 的 MDCG_AUX_ROOT 优先于进程 env——密钥环路径须跟随
  // 配置覆盖（启动日志点名可用它搬走辅助根）；两级都缺才回落历史默认 ~/.mdcg。
  const fromConfig = (envOverride?.MDCG_AUX_ROOT ?? '').trim()
  if (fromConfig) return resolve(fromConfig)
  const env = (process.env.MDCG_AUX_ROOT ?? '').trim()
  return env ? resolve(env) : join(homedir(), '.mdcg')
}

/** 默认密钥环路径：与 md_cg 的 `_tokens.json` 同目录（aux 根下，见 auxRoot()）。 */
export function defaultKeyringPath(envOverride?: Record<string, string | undefined>): string {
  return join(auxRoot(envOverride), 'token')
}

/** 读取密钥环；不存在 / 不可读 / 空文件一律返回 undefined（不抛异常）。 */
function readKeyring(path: string): string | undefined {
  try {
    const t = readFileSync(path, 'utf-8').trim()
    return t || undefined
  } catch {
    return undefined
  }
}

/** 写入密钥环并尽力收紧权限。 */
function writeKeyring(path: string, token: string): void {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, token + '\n', { encoding: 'utf-8', mode: 0o600 })
  try {
    // Windows 上 chmod 仅能置只读位（真实保护来自用户目录 ACL），
    // 与 md_cg tokens._save 同策略：不可设则忽略，不因此中断签发。
    chmodSync(path, 0o600)
  } catch { /* 平台不支持则忽略 */ }
}

interface IssueOutcome {
  token?: string
  tokenId?: string
  error?: string
}

/** config.env 键值 → 子进程 env 覆盖层（#368 复核必须 2＝#224-② 的端到端半边）。
 *
 *  为什么签发/复核子进程也必须吃 config.env：MDCG_AUX_ROOT 只在 cordis.yml 的
 *  config.env 设过时，密钥环路径（插件侧 auxRoot(envOverride)）已去了 X，而
 *  `tokens issue` 子进程 env 里没有 MDCG_AUX_ROOT ⇒ 令牌记录仍写 ~/.mdcg——
 *  环与记录分居两处，从「一处错位」变成「两处错位」（值守端到端复现）。
 *  只收 string 值：undefined/null（config.env 的可选键）不得进子进程 env。
 *  展开序即优先级：process.env < 编码/PYTHONPATH 专用键 < config.env 显式
 *  覆盖——与 mdcgChildEnv 的「opts.env 最后展开、显式覆盖优先」同口径。 */
function configEnvOverlay(envOverride?: Record<string, string | undefined>): Record<string, string> {
  const overlay: Record<string, string> = {}
  if (envOverride) {
    for (const [k, v] of Object.entries(envOverride)) {
      if (typeof v === 'string') overlay[k] = v
    }
  }
  return overlay
}

/** 调 `python -m md_cg.tokens issue` 签一枚令牌（同步，仅首启一次）。 */
function issueToken(
  python: string, role: string, actor: string, clearance: string, tenant?: string,
  envOverride?: Record<string, string | undefined>,
): IssueOutcome {
  let r
  try {
    r = spawnSync(
      python,
      ['-m', 'md_cg.tokens', 'issue',
        '--role', role, '--actor', actor, '--clearance', clearance,
        // #224-①：租户透传——非 default 才传（default 是 md_cg 侧缺省值，
        // tokens.py p_i.add_argument("--tenant", default="default")）。
        ...(tenant && tenant !== 'default' ? ['--tenant', tenant] : [])],
      {
        encoding: 'utf-8',
        windowsHide: true,
        timeout: 15_000,
        // 与工作纪律第 15 条同源：显式 UTF-8 + PYTHONUTF8，规避 Windows GBK 解码异常。
        // 模块解析靠 PYTHONPATH 锚定随包 md_cg（不依赖 cwd）；cwd 取包外目录，
        // 否则 pnpm 更新本插件时 rmdir 包目录必报 ERR_PNPM_EBUSY。见 datapath.runRoot()。
        cwd: runRoot(),
        env: {
          ...process.env,
          PYTHONUTF8: '1',
          PYTHONIOENCODING: 'utf-8',
          PYTHONPATH: pythonPathValue(),
          // #368 必须 2：config.env 进签发子进程（缘由见 configEnvOverlay 头注）。
          ...configEnvOverlay(envOverride),
        },
      },
    )
  } catch (e) {
    return { error: `无法执行 ${python}：${e instanceof Error ? e.message : String(e)}` }
  }
  if (r.error) return { error: `无法执行 ${python}：${r.error.message}` }
  if (r.status !== 0) {
    const detail = (r.stderr || r.stdout || '').trim().replace(/\s+/g, ' ').slice(0, 200)
    return { error: `md_cg.tokens issue 退出码 ${r.status}${detail ? `：${detail}` : ''}` }
  }
  try {
    const out = JSON.parse(r.stdout || '{}') as { token?: string; token_id?: string }
    if (!out.token) return { error: '签发输出缺少 token 字段' }
    return { token: out.token, tokenId: out.token_id }
  } catch (e) {
    return { error: `签发输出不是合法 JSON：${e instanceof Error ? e.message : String(e)}` }
  }
}

/** 密钥环令牌的复核结论（#224-③，三态口径按 #368 复核必须 1 收紧）。
 *  - `ok`：verify 退出码 0，令牌仍有效，原样复用；
 *  - `invalid`：校验器**真的跑过**且明确拒绝——tokens.py 的退出码契约里**只有 2
 *    是 TokenError**（覆盖格式非法/无记录/已吊销/哈希不符/已过期）——可安全换新；
 *  - `unverifiable`：其余一切形态——退出码 1（校验器自身崩坏：未捕获异常）、
 *    3（拒启类守卫）、127（解释器找不到）、null（Python 不可执行/超时被杀）。
 *    令牌既不能证实也不能证伪，**不许据此动密钥环**（旧判据「非 0 即 invalid」
 *    会把校验器的一次崩溃当成真拒绝 ⇒ 仍有效的令牌被清空——值守端到端复现：
 *    密钥环 46 字节 → 0，DESTROYED）。 */
export type VerifyOutcome = 'ok' | 'invalid' | 'unverifiable'

/** 调 `python -m md_cg.tokens verify` 复核令牌仍有效（同步，仅密钥环路径用，#224-③）。
 *
 *  背景：用户吊销自动签发的令牌后，密钥环里的旧令牌每次被原样复用 ⇒
 *  md_cg 退出码 3 拒启 ⇒ 桥重试后放弃终态 ⇒ 整套插件永久不可用。
 *  修法：从密钥环读到令牌后先 verify；`invalid`（确证拒绝）才走换新，
 *  `unverifiable` 则既不清也不复用（fail-closed：落自动签发或降级，绝不带病返回）。
 */
export function verifyToken(
  python: string, token: string, envOverride?: Record<string, string | undefined>,
): VerifyOutcome {
  let r
  try {
    r = spawnSync(
      python,
      ['-m', 'md_cg.tokens', 'verify', '--token', token],
      {
        encoding: 'utf-8',
        windowsHide: true,
        timeout: 10_000,
        cwd: runRoot(),
        env: {
          ...process.env,
          PYTHONUTF8: '1',
          PYTHONIOENCODING: 'utf-8',
          PYTHONPATH: pythonPathValue(),
          // #368 必须 2：复核子进程与签发同口径吃 config.env——校验器读的
          // aux 根（令牌记录所在）必须与插件侧一致，否则「验的是另一套记录」。
          ...configEnvOverlay(envOverride),
        },
      },
    )
  } catch {
    return 'unverifiable'
  }
  if (r.error) return 'unverifiable' // 无法执行 / 超时被杀：status 为 null
  if (r.status === 0) return 'ok'
  // #368 必须 1：退出码契约（md_cg/tokens.py main）——2 是唯一的 TokenError。
  // 1＝校验器自身崩坏、3＝拒启类守卫、127＝解释器找不到：这些「没跑成」的
  // 形态一律 unverifiable，绝不并入 invalid。
  if (r.status === 2) return 'invalid'
  return 'unverifiable'
}

/** `MDCG_AUTO_ISSUE` 是否显式关闭（0/false/no/off，忽略大小写）。 */
function autoIssueDisabledByEnv(): boolean {
  const v = (process.env.MDCG_AUTO_ISSUE ?? '').trim().toLowerCase()
  return v === '0' || v === 'false' || v === 'no' || v === 'off'
}

/**
 * 解析写入凭据：显式配置 → 进程 env → 密钥环 → 首启自动签发。
 *
 * 纯函数式（无模块级缓存）：一次插件激活只调用一次，且返回值须与当下磁盘
 * 状态一致，缓存反而会让「用户刚删了密钥环」的修复动作不生效。
 */
export function resolveToken(opts: ResolveTokenOptions): TokenResolution {
  // #224-②：config.env 的 MDCG_AUX_ROOT 进密钥环路径解析（auxRoot 接受 envOverride）
  const keyringPath = opts.keyringPath ?? defaultKeyringPath(opts.envOverride)

  const configured = (opts.configured ?? '').trim()
  if (configured) return { token: configured, source: 'config', keyringPath }

  const fromEnv = (process.env.MDCG_TOKEN ?? '').trim()
  if (fromEnv) return { token: fromEnv, source: 'process-env', keyringPath }

  const fromRing = readKeyring(keyringPath)
  if (fromRing) {
    // #224-③：密钥环令牌先复核——吊销后不再原样复用（否则插件永久拒启）。
    // #368 必须 3：invalid（确证失效）与 unverifiable（没跑成）都**不在此清环**。
    //   旧实现是「先清后签」：清完旧令牌再签新，签发一失败密钥环就永久空了
    //   （值守复现：rc=2 且签发失败 ⇒ 环 46 字节 → 0）。现改为**唯一落点覆写**：
    //   只有下方「新令牌签发成功后 writeKeyring」才替换环内容——签成功才换，
    //   签失败则原文件原样保留，下次启动重新复核/重签，绝不丢掉仅剩的凭据。
    //   unverifiable 同样不带病返回（fail-closed）：落自动签发；签发成功会覆写
    //   密钥环，签发失败则原文件保留待下次启动重试。
    const verdict = verifyToken(opts.python, fromRing, opts.envOverride)
    if (verdict === 'ok') return { token: fromRing, source: 'keyring', keyringPath }
  }

  if (opts.autoIssue === false) {
    return { source: 'disabled', keyringPath, note: '本场景未启用自动签发（autoIssue=false）' }
  }
  if (autoIssueDisabledByEnv()) {
    return { source: 'disabled', keyringPath, note: 'MDCG_AUTO_ISSUE 已关闭自动签发' }
  }

  const role = opts.role ?? 'designer'
  const actor = opts.actor ?? 'dsh-memory'
  const clearance = opts.clearance ?? 'internal'
  const r = issueToken(opts.python, role, actor, clearance, opts.tenant, opts.envOverride)
  if (!r.token) {
    return { source: 'none', keyringPath, note: r.error }
  }
  // #368 必须 3 的「签成功才替换」半边：这是密钥环的唯一覆写点（旧 invalid
  // 令牌到此才被新令牌顶掉；失败路径在上面已提前返回，环原样保留）。
  writeKeyring(keyringPath, r.token)
  return {
    token: r.token,
    source: 'issued',
    keyringPath,
    note: `已自动签发认知图写入凭据（role=${role}, actor=${actor}, `
      + `clearance=${clearance}, token_id=${r.tokenId}），明文存于 ${keyringPath}。`
      + '关闭自动签发：设 MDCG_AUTO_ISSUE=0；'
      + `吊销：python -m md_cg.tokens revoke --token-id ${r.tokenId}。`,
  }
}
