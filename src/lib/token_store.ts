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
 *   ③ 密钥环 `~/.mdcg/token`（0600）—— **先复核再复用**（见下）；
 *   ④ 都没有 → **首启自动签发**一枚 designer 令牌并写入密钥环。
 *
 * 为什么密钥环可以自动签发（安全论证）
 * ------------------------------------------------
 * 能读到该文件的进程，本就以该用户身份运行，也就本就能读写该用户的全部文件
 * ——自动签发**不降低实际安全强度**。真正需要显式管理令牌的场景（多用户机 /
 * 想要权职分离 / 审计要求）用 `MDCG_AUTO_ISSUE=0` 关闭，改走手工签发。
 *
 * 密钥环必须**复核**（#224 的条件层根因）
 * ------------------------------------------------
 * 改前：密钥环有内容就原样复用（`if (fromRing) return …`），从不验吊销、不验
 * 租户、不验它是否在当前令牌文件里。而签发侧与运行侧读的**不是同一套 env**：
 *   · 签发子进程只拿 `process.env`，看不见 `config.env`（`MDCG_AUX_ROOT` /
 *     `MDCG_TOKEN_FILE`），于是令牌记录写进 `~/.mdcg/_tokens.json`；
 *   · MCP 子进程拿的是 `config.env` 叠加（`mdcgChildEnv`），去 aux 下找记录；
 *   · 签发参数没有 `--tenant`（`md_cg.tokens issue` 缺省 default），而
 *     `tokens.verify_token` 自 N62 起对「记录租户 ≠ 入参租户」fail-closed。
 * 三条叠加的结果：服务端 rc=3 拒启、桥 8 次后放弃、重启原样复用坏令牌永不自愈。
 *
 * 修复口径（同一条判据贯穿签发与复核）：
 *   · **签发/复核/运行共用同一套 env**：`process.env` 叠加 `config.env`
 *     （与 `mdcgChildEnv` 同一构造顺序），令牌文件位置因此一致；
 *   · **租户单点**：`effectiveTenant()` 与 `mdcgChildEnv` 共用（`config.env.
 *     MDCG_TENANT` 优先，其次 `config.mdcg.tenant`，再缺省 default）；
 *   · **密钥环先复核**：`python -m md_cg.tokens verify --token-file-in <密钥环>`
 *     （明文不进命令行），再把 `principal.tenant` 与当前租户比较；
 *   · 复核结论四分（ok / rebind / blocked / unknown）见 `checkKeyring()`。
 *
 * 与 `md_cg/tokens.py` 的对应
 * ------------------------------------------------
 * 密钥环与 `tokens.py` 的 `_tokens.json`（令牌记录）同目录，但**职责不同**：
 * 密钥环存**明文令牌**（给本机客户端用），`_tokens.json` 存**哈希与元数据**（校验用）。
 * 二者格式不做任何修改——本模块只是 `python -m md_cg.tokens` 的一层封装。
 */
import { spawnSync } from 'node:child_process'
import { chmodSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
// #386/#224：aux 根的 `~` 展开与记忆面共用同一单点（datapath.expandHome）——
// 否则 `MDCG_AUX_ROOT=~/.mdcg` 时 Node 侧密钥环落 `<仓根>/~/.mdcg/token`，而
// Python 侧令牌记录落 `<家目录>/.mdcg/_tokens.json`：密钥环被写进插件包目录，
// pnpm 更新整目录替换即丢失（下次启动重签新令牌，旧令牌仍在且未吊销）。
import { expandHome, pythonPathValue, runRoot } from './datapath.js'

/** 凭据来源（用于启动日志与故障定位）。 */
export type TokenSource =
  | 'config'       // config.env.MDCG_TOKEN（显式配置，原样尊重）
  | 'process-env'  // 插件进程 env 的 MDCG_TOKEN
  | 'keyring'      // 密钥环 ~/.mdcg/token（复核通过）
  | 'issued'       // 首启自动签发 / 密钥环换绑后重签并写入密钥环
  | 'disabled'     // 显式关闭自动签发，且无既有凭据
  | 'invalid'      // 密钥环中的令牌复核不过（吊销/过期/租户不符且不许重签）→ 只读 guest
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
  /** 密钥环路径覆盖（默认 `<aux 根>/token`）。 */
  keyringPath?: string
  /** 当前租户（`config.mdcg.tenant`）；`config.env.MDCG_TENANT` 优先。 */
  tenant?: string
  /** `config.env`：与 MCP 子进程**同一套** env（令牌文件位置 / 租户 / aux 根）。
   *  签发与复核都必须看见它，否则两侧会各读一个令牌文件（#224 触发 2）。 */
  env?: Record<string, string>
}

/** 当前生效租户（**单点**：签发、密钥环复核、MCP 子进程三处共用）。
 *
 * 优先级与 `mdcgChildEnv()` 的 env 叠加顺序同口径：
 *   `config.env.MDCG_TENANT` > `config.mdcg.tenant` > `default`。
 * 为什么要单点：N62 之后服务端对「记录租户 ≠ 入参租户」fail-closed，两侧各算
 * 一遍就必然分叉（#224 触发 1：签发按 default、运行按 work ⇒ rc=3）。 */
export function effectiveTenant(tenant?: string, env?: Record<string, string>): string {
  const fromEnv = String(env?.['MDCG_TENANT'] ?? '').trim()
  return fromEnv || String(tenant ?? '').trim() || 'default'
}

/** 辅助存储根（密钥/令牌/信任/理论/心跳）：与 md_cg 的 `datapath.aux_root()` 同口径。
 *
 *  默认 `~/.mdcg`（历史值，**逐字保留**——改默认会让存量密钥/令牌失联）；
 *  `MDCG_AUX_ROOT` 可把它们整体搬走（沙箱/多用户/与记忆真源同处的场景）。
 *  与 `config.mdcg.root`（记忆真源）有意分离：身份与信任不随认知图迁移。
 *
 *  `~` 形态经 `expandHome()` 展开（#386 的同一单点）：Python 侧
 *  `datapath.aux_root()` → `_abs_host_path()` → `os.path.expanduser`，两侧必须
 *  同落点；否则密钥环落进插件包目录（`<仓根>/~/…`），pnpm 更新即丢失。
 *
 *  @param env `config.env`——MCP 子进程会继承它，故密钥环与令牌记录必须落在
 *             同一 aux 根（否则签发侧写 `~/.mdcg`、运行侧读 aux ⇒「令牌不存在」）。 */
export function auxRoot(env?: Record<string, string>): string {
  const raw = (env?.['MDCG_AUX_ROOT'] ?? process.env.MDCG_AUX_ROOT ?? '').trim()
  return raw ? resolve(expandHome(raw)) : join(homedir(), '.mdcg')
}

/** 默认密钥环路径：与 md_cg 的 `_tokens.json` 同目录（aux 根下，见 auxRoot()）。 */
export function defaultKeyringPath(env?: Record<string, string>): string {
  return join(auxRoot(env), 'token')
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

interface CliOutcome {
  ok: boolean
  status: number | null
  stdout: string
  stderr: string
  /** 进程根本没能跑起来（python 不可执行 / 超时）。 */
  error?: string
}

/**
 * `python -m md_cg.tokens …` 的**唯一调用点**（签发与复核共用）。
 *
 * env 口径 = `process.env` 叠加 `config.env`，与 `mdcgChildEnv()` 同一顺序：
 * 令牌文件位置（`MDCG_AUX_ROOT` / `MDCG_TOKEN_FILE`）与租户因此与 MCP 子进程
 * 一致。`PYTHONPATH` 锚定随包 md_cg（不依赖 cwd）；cwd 取包外目录，否则
 * pnpm 更新本插件时 rmdir 包目录必报 ERR_PNPM_EBUSY（见 datapath.runRoot()）。
 *
 * 编码：与工作纪律第 15 条同源，显式 UTF-8 + PYTHONUTF8，规避 Windows GBK
 * 解码异常（`test/python-utf8-mode.test.ts` 的站点扫描要求本站点同时声明两条）。
 */
function runTokensCli(python: string, argv: string[],
                      extraEnv: Record<string, string>): CliOutcome {
  let r
  try {
    r = spawnSync(python, ['-m', 'md_cg.tokens', ...argv], {
      encoding: 'utf-8',
      windowsHide: true,
      timeout: 15_000,
      cwd: runRoot(),
      env: {
        ...process.env,
        PYTHONPATH: pythonPathValue(),
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
        ...extraEnv,
      },
    })
  } catch (e) {
    return {
      ok: false, status: null, stdout: '', stderr: '',
      error: `无法执行 ${python}：${e instanceof Error ? e.message : String(e)}`,
    }
  }
  if (r.error) {
    return {
      ok: false, status: null, stdout: '', stderr: '',
      error: `无法执行 ${python}：${r.error.message}`,
    }
  }
  return {
    ok: r.status === 0,
    status: r.status,
    stdout: r.stdout ?? '',
    stderr: r.stderr ?? '',
  }
}

interface IssueOutcome {
  token?: string
  tokenId?: string
  error?: string
}

/** 调 `python -m md_cg.tokens issue` 签一枚令牌（同步，仅首启/换绑时一次）。 */
function issueToken(python: string, role: string, actor: string, clearance: string,
                    tenant: string, env: Record<string, string>): IssueOutcome {
  const r = runTokensCli(python,
    ['issue', '--role', role, '--actor', actor, '--clearance', clearance,
      '--tenant', tenant], env)
  if (r.error) return { error: r.error }
  if (!r.ok) {
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

/** 密钥环复核结论（四分类，见 checkKeyring）。 */
type RingStatus = 'ok' | 'rebind' | 'blocked' | 'unknown'

interface RingCheck {
  status: RingStatus
  /** 人类可读原因（写日志；不含令牌明文）。 */
  reason: string
  /** 密钥环里那枚令牌的 id（诊断/日志用）。 */
  tokenId?: string
}

/**
 * 复核密钥环里的令牌：`tokens verify --token-file-in <密钥环>`（明文不进命令行）。
 *
 * 四分类（决定 resolveToken 的处置）：
 *   · `ok`      —— 校验通过且 `principal.tenant` 等于当前租户 → 原样复用；
 *   · `rebind`  —— 当前令牌文件里**没有这枚令牌**（换了 `MDCG_AUX_ROOT` /
 *                  `MDCG_TOKEN_FILE`，等同在新位置全新安装），或记录租户与当前
 *                  租户不一致 → 允许自动签发时按当前配置重签并替换密钥环；
 *   · `blocked` —— 已吊销 / 已过期 / 密钥或角色不匹配 / 令牌库损坏 → **不重签**
 *                  （吊销 = 用户有意收回写权；静默换一枚新写令牌等于让吊销失效），
 *                  以只读 guest 运行并说明恢复方法；
 *   · `unknown` —— 复核本身没跑成（python 不可执行 / 超时 / 输出不可解析）
 *                  → 按修复前行为原样使用，不因复核失败制造新的启动失败。
 *
 * ⚠️ 判据顺序：令牌库损坏的告警先于「令牌不存在」——`_load` 在库损坏时回落空表，
 * 若不先认告警，会把「库坏了」误判成 rebind 并试图重签（`_save` 随后拒绝写回）。
 */
function checkKeyring(python: string, keyringPath: string, tenant: string,
                      env: Record<string, string>): RingCheck {
  const r = runTokensCli(python,
    ['verify', '--token-file-in', keyringPath], env)
  if (r.error) return { status: 'unknown', reason: r.error }
  if (r.ok) {
    let out: { principal?: { tenant?: unknown; token_id?: unknown } }
    try {
      out = JSON.parse(r.stdout || '{}')
    } catch {
      return { status: 'unknown', reason: '复核输出不是合法 JSON' }
    }
    const p = out.principal ?? {}
    const tokenId = typeof p.token_id === 'string' ? p.token_id : undefined
    const recTenant = String(p.tenant ?? '').trim()
    if (!recTenant) return { status: 'unknown', reason: '复核输出缺少 principal.tenant' }
    if (recTenant !== tenant) {
      return {
        status: 'rebind',
        reason: `密钥环令牌按 tenant=${recTenant} 签发，当前 tenant=${tenant}`,
        tokenId,
      }
    }
    return { status: 'ok', reason: '', tokenId }
  }
  const detail = (r.stderr || r.stdout || '').trim().replace(/\s+/g, ' ').slice(0, 200)
  // 令牌库损坏：`_load` 回落空表后报「令牌不存在」，必须按告警先分出来（N198）。
  if (/令牌库损坏|令牌库不可读|拒绝整份写回/.test(detail)) {
    return { status: 'blocked', reason: `令牌库损坏：${detail}` }
  }
  if (/令牌不存在/.test(detail)) {
    return {
      status: 'rebind',
      reason: '当前令牌文件里没有这枚令牌（换了 MDCG_AUX_ROOT / MDCG_TOKEN_FILE 或新建了令牌库）',
    }
  }
  if (/已吊销|已过期|密钥不匹配|角色与记录不一致/.test(detail)) {
    return { status: 'blocked', reason: detail }
  }
  if (r.status === 2) {
    // tokens CLI 的 TokenError 统一 rc=2：无法归类的校验失败按 blocked 保守处理
    // （宁可只读 guest，也不重签一枚用户可能有意收回的凭据）。
    return { status: 'blocked', reason: detail || '令牌校验失败（未归类）' }
  }
  return { status: 'unknown', reason: detail || `verify 退出码 ${r.status}` }
}

/** `MDCG_AUTO_ISSUE` 是否显式关闭（0/false/no/off，忽略大小写）。
 *
 *  `config.env` 也算（与其余 env 同口径）：插件配置里写 `MDCG_AUTO_ISSUE: '0'`
 *  是文档化的关闭方式之一；只看 `process.env` 会让「密钥环已坏 + 配置里关了
 *  自动签发」仍试图重签（#224 的「开关救不了」残余面）。 */
function autoIssueDisabledByEnv(env?: Record<string, string>): boolean {
  const v = String(env?.['MDCG_AUTO_ISSUE'] ?? process.env.MDCG_AUTO_ISSUE ?? '')
    .trim().toLowerCase()
  return v === '0' || v === 'false' || v === 'no' || v === 'off'
}

/** 只读 guest 的恢复指引（blocked / rebind 且不许重签时写进日志）。 */
function recoveryHint(keyringPath: string): string {
  return `要恢复写入：确认后删除 ${keyringPath} 并重启 DSH（会按当前配置重新自动签发）；`
    + '或手工签发后经 config.env.MDCG_TOKEN 注入（见 dsh/cordis.yml.example）。'
}

/**
 * 解析写入凭据：显式配置 → 进程 env → 密钥环（**复核后**复用 / 换绑重签）→ 首启自动签发。
 *
 * 纯函数式（无模块级缓存）：一次插件激活只调用一次，且返回值须与当下磁盘
 * 状态一致，缓存反而会让「用户刚删了密钥环」的修复动作不生效。
 */
export function resolveToken(opts: ResolveTokenOptions): TokenResolution {
  const extraEnv = { ...(opts.env ?? {}) }
  const tenant = effectiveTenant(opts.tenant, extraEnv)
  const keyringPath = opts.keyringPath ?? defaultKeyringPath(extraEnv)

  const configured = (opts.configured ?? '').trim()
  if (configured) return { token: configured, source: 'config', keyringPath }

  const fromEnv = (process.env.MDCG_TOKEN ?? '').trim()
  if (fromEnv) return { token: fromEnv, source: 'process-env', keyringPath }

  const autoOff = opts.autoIssue === false
    ? '本场景未启用自动签发（autoIssue=false）'
    : autoIssueDisabledByEnv(extraEnv) ? 'MDCG_AUTO_ISSUE 已关闭自动签发' : ''

  const role = opts.role ?? 'designer'
  const actor = opts.actor ?? 'dsh-memory'
  const clearance = opts.clearance ?? 'internal'

  const fromRing = readKeyring(keyringPath)
  if (fromRing) {
    const chk = checkKeyring(opts.python, keyringPath, tenant, extraEnv)
    if (chk.status === 'ok') {
      return { token: fromRing, source: 'keyring', keyringPath }
    }
    if (chk.status === 'unknown') {
      // 复核没跑成不是「令牌坏」的证据：按修复前行为原样使用（不制造新失败源）。
      return {
        token: fromRing, source: 'keyring', keyringPath,
        note: `密钥环复核未跑成（${chk.reason}），按原样使用；若服务端拒启请检查令牌`,
      }
    }
    if (chk.status === 'blocked') {
      return {
        source: 'invalid', keyringPath,
        note: `密钥环中的令牌复核不过（${chk.reason}），不自动重签；${recoveryHint(keyringPath)}`,
      }
    }
    // rebind：令牌记录不在当前令牌文件里，或租户与当前配置不符。
    if (autoOff) {
      return {
        source: 'invalid', keyringPath,
        note: `密钥环中的令牌与当前配置不符（${chk.reason}），${autoOff}，不重签；`
          + recoveryHint(keyringPath),
      }
    }
    const r = issueToken(opts.python, role, actor, clearance, tenant, extraEnv)
    if (!r.token) {
      return {
        source: 'none', keyringPath,
        note: `密钥环中的令牌与当前配置不符（${chk.reason}），按当前配置重签失败：${r.error}`,
      }
    }
    writeKeyring(keyringPath, r.token)
    return {
      token: r.token,
      source: 'issued',
      keyringPath,
      note: `密钥环中的令牌与当前配置不符（${chk.reason}），已按当前配置重签`
        + `（tenant=${tenant}, token_id=${r.tokenId}`
        + `${chk.tokenId ? `，原 token_id=${chk.tokenId}` : ''}）。`
        + '原令牌若不再使用，可吊销：'
        + `python -m md_cg.tokens revoke --token-id ${chk.tokenId ?? '<原 token_id>'}。`,
    }
  }

  if (opts.autoIssue === false) {
    return { source: 'disabled', keyringPath, note: '本场景未启用自动签发（autoIssue=false）' }
  }
  if (autoIssueDisabledByEnv(extraEnv)) {
    return { source: 'disabled', keyringPath, note: 'MDCG_AUTO_ISSUE 已关闭自动签发' }
  }

  const r = issueToken(opts.python, role, actor, clearance, tenant, extraEnv)
  if (!r.token) {
    return { source: 'none', keyringPath, note: r.error }
  }
  writeKeyring(keyringPath, r.token)
  return {
    token: r.token,
    source: 'issued',
    keyringPath,
    note: `已自动签发认知图写入凭据（role=${role}, actor=${actor}, `
      + `clearance=${clearance}, tenant=${tenant}, token_id=${r.tokenId}），`
      + `明文存于 ${keyringPath}。`
      + '关闭自动签发：设 MDCG_AUTO_ISSUE=0；'
      + `吊销：python -m md_cg.tokens revoke --token-id ${r.tokenId}。`,
  }
}
