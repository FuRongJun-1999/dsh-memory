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
 *   ③ 密钥环 `~/.mdcg/token`（0600）—— 已签发过则复用；
 *   ④ 都没有 → **首启自动签发**一枚 designer 令牌并写入密钥环。
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
import { dirname, join } from 'node:path'

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
}

/** 默认密钥环路径：与 md_cg 的 `~/.mdcg/` 约定同目录（`_tokens.json` 亦在此）。 */
export function defaultKeyringPath(): string {
  return join(homedir(), '.mdcg', 'token')
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

/** 调 `python -m md_cg.tokens issue` 签一枚令牌（同步，仅首启一次）。 */
function issueToken(python: string, role: string, actor: string, clearance: string): IssueOutcome {
  let r
  try {
    r = spawnSync(
      python,
      ['-m', 'md_cg.tokens', 'issue',
        '--role', role, '--actor', actor, '--clearance', clearance],
      {
        encoding: 'utf-8',
        windowsHide: true,
        timeout: 15_000,
        // 与工作纪律第 15 条同源：显式 UTF-8 + PYTHONUTF8，规避 Windows GBK 解码异常
        env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
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
  const keyringPath = opts.keyringPath ?? defaultKeyringPath()

  const configured = (opts.configured ?? '').trim()
  if (configured) return { token: configured, source: 'config', keyringPath }

  const fromEnv = (process.env.MDCG_TOKEN ?? '').trim()
  if (fromEnv) return { token: fromEnv, source: 'process-env', keyringPath }

  const fromRing = readKeyring(keyringPath)
  if (fromRing) return { token: fromRing, source: 'keyring', keyringPath }

  if (opts.autoIssue === false) {
    return { source: 'disabled', keyringPath, note: '本场景未启用自动签发（autoIssue=false）' }
  }
  if (autoIssueDisabledByEnv()) {
    return { source: 'disabled', keyringPath, note: 'MDCG_AUTO_ISSUE 已关闭自动签发' }
  }

  const role = opts.role ?? 'designer'
  const actor = opts.actor ?? 'dsh-memory'
  const clearance = opts.clearance ?? 'internal'
  const r = issueToken(opts.python, role, actor, clearance)
  if (!r.token) {
    return { source: 'none', keyringPath, note: r.error }
  }
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
