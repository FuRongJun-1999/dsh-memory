/**
 * issue224_token_store_bind.test.ts · 自动签发令牌与运行侧同租户 / 同令牌库，且密钥环先复核
 *
 * 功能名：`token_store.resolveToken` 的租户单点（`effectiveTenant`）、`config.env`
 *         透传、密钥环四分类复核（ok/rebind/blocked/unknown）、桥的退出码 3 提示分流。
 * 生效条件：`node --import tsx --test test/issue224_token_store_bind.test.ts`
 *           （变异自证：`node --import tsx test/issue224_token_store_bind.test.ts --mutate M1|M2|M3|M4|M5|M6|M7|M8|M9`）
 * 子功能：
 *   A 租户：`config.mdcg.tenant=work` ⇒ 令牌记录 tenant=work，md_cg 子进程 rc=0；
 *   B config.env：`MDCG_AUX_ROOT` 经 config.env 给出 ⇒ 令牌记录与密钥环都落 aux，
 *     子进程（同一 env）rc=0（改前记录落 ~/.mdcg、子进程报「令牌不存在」）；
 *   B2 `MDCG_AUX_ROOT='~/.mdcg-aux'`：Node 侧与 Python `datapath.aux_root()` 同口径
 *     展开 `~` ⇒ 密钥环与令牌记录同目录且都在 HOME 下（改前 Node 落字面 `~` 目录，
 *     与 Python 侧分叉——pnpm 更新后密钥环随之失联）；
 *   C 吊销：密钥环里的令牌被吊销后重启 ⇒ 不原样复用、不自动重签、以只读 guest 启动
 *     （rc=0 且库内有效令牌 0 枚）——「吊销 = 用户有意收回写权」不被静默作废；
 *   D 换绑：租户变更 ⇒ 按当前配置重签并替换密钥环，子进程 rc=0；
 *   E 关闭自动签发：密钥环缺记录时不得重签（source=disabled）；
 *   F 单点：`effectiveTenant` 优先级矩阵 + `mdcgChildEnv` 与签发侧同口径；
 *   G 源码锚点：签发带 `--tenant`、CLI 合并 config.env、密钥环必复核、index 透传；
 *     桥**行为面**：拉一个立刻以退出码 3 退出的子进程，提示须点名「令牌校验失败」
 *     且不得再把人引向 python/依赖（删掉分流分支即转红）。
 * 执行：子进程隔离 HOME 与全部 MDCG_* env；每个场景用全新临时 HOME。
 * 验证方式：默认模式全部 PASS（退出码 0）；`--mutate` 下每组指定红项须逐项出现。
 * 不适用条件：不判运行中吊销（#86）、不判 clearance 与配置不一致（服务端只告警）、
 *   不判显式 `MDCG_TOKEN` 被吊销后的行为（该路径保持 fail-closed，未改动）；
 *   不判 Windows 专有 ACL（密钥环 0600 尽力而为，与 tokens.py 同策略）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve, sep } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const TOKEN_STORE = join(REPO, 'src', 'lib', 'token_store.ts')
const MDCG_CLIENT = join(REPO, 'src', 'lib', 'mdcg_client.ts')
const INDEX_TS = join(REPO, 'src', 'index.ts')
const BRIDGE_TS = join(REPO, 'src', 'bridge.ts')
const PY = process.env['PYTHON'] || 'python'

const norm = (p: string): string => (process.platform === 'win32' ? p.toLowerCase() : p)

/** 隔离 env：剔掉宿主会话类变量（父 shell 导出的 MDCG_TOKEN 会污染一切）。 */
function cleanEnv(extra: Record<string, string> = {}): Record<string, string> {
  const env: Record<string, string> = {}
  for (const [k, v] of Object.entries(process.env)) {
    if (v === undefined) continue
    if (k.startsWith('MDCG_') || k === 'DSH_HOME') continue
    env[k] = v
  }
  return Object.assign(env, extra)
}

interface Resolution {
  source: string
  token: string | null
  note: string | null
  keyringPath: string
}

/** 子进程：在给定 HOME 下调用 resolveToken（模块路径可替换，供变异用）。 */
function resolveIn(modulePath: string, home: string, opts: Record<string, unknown>,
                   extraEnv: Record<string, string> = {}, chdir?: string): Resolution {
  const code = [
    "import { pathToFileURL } from 'node:url'",
    'const m = await import(pathToFileURL(process.env.U12_TOKEN_STORE).href)',
    'if (process.env.U12_CHDIR) process.chdir(process.env.U12_CHDIR)',
    'const opts = JSON.parse(process.env.U12_OPTS)',
    'const r = m.resolveToken({ python: process.env.U12_PYTHON, actor: "dsh-memory",',
    '  clearance: "private", ...opts })',
    'console.log("U12JSON " + JSON.stringify({ source: r.source, token: r.token ?? null,',
    '  note: r.note ?? null, keyringPath: r.keyringPath }))',
  ].join('\n')
  const env = cleanEnv({
    HOME: home, USERPROFILE: home, U12_TOKEN_STORE: modulePath,
    U12_PYTHON: PY, U12_OPTS: JSON.stringify(opts),
    ...(chdir ? { U12_CHDIR: chdir } : {}), ...extraEnv,
  })
  const r = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', code], {
    env, encoding: 'utf8', cwd: REPO, timeout: 90_000,
  })
  const line = (r.stdout || '').split('\n').find((l) => l.startsWith('U12JSON '))
  if (r.status !== 0 || !line) {
    throw new Error(`resolveToken 探针失败 rc=${r.status}：${(r.stderr || r.stdout || '').slice(-400)}`)
  }
  return JSON.parse(line.slice('U12JSON '.length)) as Resolution
}

/** md_cg 子进程 rc（令牌校验失败 ⇒ rc=3）。 */
function serverRc(home: string, token: string | null, tenant: string,
                  extraEnv: Record<string, string> = {}): number | string {
  const env = cleanEnv({
    HOME: home, USERPROFILE: home, PYTHONPATH: REPO,
    PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8',
    MDCG_ROOT: join(home, 'mem'), MDCG_DATA_ROOT: join(home, 'data'),
    MDCG_STATE_ROOT: join(home, 'state'), MDCG_TENANT: tenant,
    ...(token ? { MDCG_TOKEN: token } : {}), ...extraEnv,
  })
  const r = spawnSync(PY, ['-X', 'utf8', '-m', 'md_cg.mcp_server'], {
    env, encoding: 'utf8', cwd: REPO, input: '', timeout: 90_000,
  })
  return r.status === null ? 'timeout' : r.status
}

function records(home: string, aux?: string): { file: string | null; tenants: string[] } {
  const cands = [...(aux ? [join(aux, '_tokens.json')] : []), join(home, '.mdcg', '_tokens.json')]
  for (const p of cands) {
    if (!existsSync(p)) continue
    const d = JSON.parse(readFileSync(p, 'utf8')) as { tokens?: Record<string, { tenant?: string }> }
    const tokens = d.tokens ?? {}
    return { file: p, tenants: Object.values(tokens).map((v) => String(v.tenant ?? '')) }
  }
  return { file: null, tenants: [] }
}

function validTokenCount(home: string, aux?: string): number {
  const cands = [...(aux ? [join(aux, '_tokens.json')] : []), join(home, '.mdcg', '_tokens.json')]
  for (const p of cands) {
    if (!existsSync(p)) continue
    const d = JSON.parse(readFileSync(p, 'utf8')) as
      { tokens?: Record<string, { revoked_at?: number | null; expires_at?: number | null }> }
    const now = Date.now() / 1000
    return Object.values(d.tokens ?? {}).filter((v) =>
      !v.revoked_at && (!v.expires_at || Number(v.expires_at) > now)).length
  }
  return 0
}

function revoke(home: string, tokenId: string, aux?: string): number {
  const env = cleanEnv({
    HOME: home, USERPROFILE: home, PYTHONPATH: REPO, PYTHONUTF8: '1',
    ...(aux ? { MDCG_AUX_ROOT: aux } : {}),
  })
  const r = spawnSync(PY, ['-X', 'utf8', '-m', 'md_cg.tokens', 'revoke',
    '--token-id', tokenId], { env, encoding: 'utf8', cwd: REPO })
  return r.status ?? -1
}

/** Python 侧 `md_cg.datapath.aux_root()`（同 HOME、同 MDCG_AUX_ROOT）——
 *  Node 侧 auxRoot() 必须与它同口径（含 `~` 展开），否则密钥环与令牌记录分居。 */
function pyAuxRoot(home: string, aux: string): string {
  const env = cleanEnv({
    HOME: home, USERPROFILE: home, PYTHONPATH: REPO, PYTHONUTF8: '1',
    MDCG_AUX_ROOT: aux,
  })
  const r = spawnSync(PY, ['-X', 'utf8', '-c',
    'from md_cg.datapath import aux_root; print(aux_root())'],
  { env, encoding: 'utf8', cwd: REPO, timeout: 60_000 })
  if (r.status !== 0) {
    throw new Error(`aux_root 探针失败 rc=${r.status}：${(r.stderr || '').slice(-300)}`)
  }
  return (r.stdout || '').trim()
}

const firstTokenId = (home: string, aux?: string): string => {
  const file = records(home, aux).file
  if (!file) throw new Error('令牌记录文件不存在')
  const d = JSON.parse(readFileSync(file, 'utf8')) as { tokens: Record<string, unknown> }
  return Object.keys(d.tokens)[0] as string
}

/** 行为探针：让桥真的拉起一个「立刻以退出码 3 退出」的子进程，取回桥打到
 *  stderr 的启动失败提示。判据不靠源码字面（删掉 `if (exitCode === ...)` 分支
 *  必须转红），而是看用户实际看到的那句话。 */
function bridgeStartupStderr(bridgePath: string): string {
  const home = mkdtempSync(join(tmpdir(), 'iss224_bridge_'))
  const stub = join(home, 'exit3.mjs')
  writeFileSync(stub, 'process.exit(3)\n', 'utf8')
  const code = [
    "import { pathToFileURL } from 'node:url'",
    'const m = await import(pathToFileURL(process.env.U12_BRIDGE).href)',
    'const b = new m.LingshuBridge({ python: process.env.U12_STUB_PY,',
    '  args: [process.env.U12_STUB], env: {}, timeoutMs: 2000, maxRetryDelayMs: 5000 })',
    'b.start()',
    'await new Promise((r) => setTimeout(r, 1500))',
    'b.dispose()',
    'process.exit(0)',
  ].join('\n')
  const env = cleanEnv({
    HOME: home, USERPROFILE: home, U12_BRIDGE: bridgePath,
    U12_STUB_PY: process.execPath, U12_STUB: stub,
  })
  const r = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', code], {
    env, encoding: 'utf8', cwd: REPO, timeout: 60_000,
  })
  return `${r.stdout || ''}\n${r.stderr || ''}`
}

interface Overrides {
  tokenStorePath?: string
  mdcgClientPath?: string
  indexText?: string
  bridgeText?: string
  /** 行为探针实际加载的桥模块（变异副本；缺省为源码）。 */
  bridgePath?: string
}

/** 判据主体：返回红项名（空数组 = 全过）。 */
function evaluate(ov: Overrides = {}): string[] {
  const reds: string[] = []
  const store = ov.tokenStorePath ?? TOKEN_STORE
  const push = (name: string, cond: boolean): void => { if (!cond) reds.push(name) }

  // A 租户
  {
    const home = mkdtempSync(join(tmpdir(), 'iss224_tenant_'))
    const r = resolveIn(store, home, { tenant: 'work' })
    const rec = records(home)
    push('tenant_recorded', rec.tenants.length === 1 && rec.tenants[0] === 'work')
    push('tenant_server_ok', serverRc(home, r.token, 'work') === 0)
  }

  // B config.env.MDCG_AUX_ROOT
  {
    const home = mkdtempSync(join(tmpdir(), 'iss224_aux_'))
    const aux = mkdtempSync(join(tmpdir(), 'iss224_auxstore_'))
    const r = resolveIn(store, home, { tenant: 'default', env: { MDCG_AUX_ROOT: aux } })
    push('aux_keyring_in_aux', norm(r.keyringPath) === norm(join(aux, 'token')))
    push('aux_record_at_aux', norm(records(home, aux).file ?? '') === norm(join(aux, '_tokens.json')))
    push('aux_server_ok', serverRc(home, r.token, 'default', { MDCG_AUX_ROOT: aux }) === 0)
  }

  // B2 `~` 形式 aux：Node 侧与 Python 同口径展开（改前 Node 落字面 `~` 目录）
  {
    const home = mkdtempSync(join(tmpdir(), 'iss224_tilde_'))
    const spec = '~/.mdcg-aux'
    // chdir 到临时 HOME：变异副本若退回 resolve(raw)，字面 `~` 目录也只会落在
    // 临时目录里，绝不污染仓库根（本判据不依赖 cwd，展开正确时与 cwd 无关）。
    const r = resolveIn(store, home, { tenant: 'default', env: { MDCG_AUX_ROOT: spec } },
      {}, home)
    const want = pyAuxRoot(home, spec)
    push('tilde_keyring_matches_python', norm(dirname(r.keyringPath)) === norm(want))
    push('tilde_keyring_under_home', norm(r.keyringPath).startsWith(norm(home) + sep))
    push('tilde_no_literal_segment', !r.keyringPath.split(/[\\/]/).includes('~'))
    push('tilde_record_at_aux', norm(records(home, want).file ?? '') === norm(join(want, '_tokens.json')))
    // 判据核心：密钥环（Node 侧算）与令牌记录（Python 侧算）必须同目录。
    // 改前 Node 落 `<cwd>/~/.mdcg-aux/token`、记录落 `<HOME>/.mdcg-aux/_tokens.json`
    // ⇒ 签发侧与运行侧各读一处，pnpm 更新后密钥环失联。
    push('tilde_keyring_shares_aux_with_record',
      norm(dirname(r.keyringPath)) === norm(dirname(records(home, want).file ?? '')))
    push('tilde_server_ok', serverRc(home, r.token, 'default', { MDCG_AUX_ROOT: spec }) === 0)
  }

  // C 吊销：不复用、不重签、只读 guest 可启动
  {
    const home = mkdtempSync(join(tmpdir(), 'iss224_revoke_'))
    const first = resolveIn(store, home, { tenant: 'default' })
    const tid = firstTokenId(home)
    push('revoke_rc', revoke(home, tid) === 0)
    const second = resolveIn(store, home, { tenant: 'default' })
    push('revoked_not_reused', second.source === 'invalid' && second.token === null)
    push('revoked_no_valid_tokens', validTokenCount(home) === 0)
    push('revoked_note_names_cause', /吊销/.test(second.note ?? ''))
    push('revoked_guest_server_ok', serverRc(home, second.token, 'default') === 0)
  }

  // D 换绑：租户变更 ⇒ 重签
  {
    const home = mkdtempSync(join(tmpdir(), 'iss224_rebind_'))
    resolveIn(store, home, { tenant: 'default' })
    const second = resolveIn(store, home, { tenant: 'work' })
    const rec = records(home)
    push('rebind_reissued', second.source === 'issued' && rec.tenants.includes('work'))
    push('rebind_server_ok', serverRc(home, second.token, 'work') === 0)
  }

  // E 关闭自动签发：不得重签（进程 env 与 config.env 两种写法同口径）
  {
    const home = mkdtempSync(join(tmpdir(), 'iss224_autooff_'))
    const r = resolveIn(store, home, { tenant: 'default' }, { MDCG_AUTO_ISSUE: '0' })
    push('auto_off_disabled', r.source === 'disabled' && r.token === null)
  }
  {
    const home = mkdtempSync(join(tmpdir(), 'iss224_autooff_cfg_'))
    const r = resolveIn(store, home,
      { tenant: 'default', env: { MDCG_AUTO_ISSUE: '0' } })
    push('auto_off_via_config_env', r.source === 'disabled' && r.token === null)
  }

  // F 单点：租户优先级 + 子进程 env 与签发侧同口径
  {
    const code = [
      "import { pathToFileURL } from 'node:url'",
      'const t = await import(pathToFileURL(process.env.U12_TOKEN_STORE).href)',
      'const c = await import(pathToFileURL(process.env.U12_MDCG_CLIENT).href)',
      'const matrix = [',
      '  [t.effectiveTenant("work", {}), "work"],',
      '  [t.effectiveTenant("work", { MDCG_TENANT: "env-ten" }), "env-ten"],',
      '  [t.effectiveTenant(undefined, {}), "default"],',
      '  [t.effectiveTenant("  ", { MDCG_TENANT: "  " }), "default"],',
      ']',
      'const envWork = c.mdcgChildEnv({ root: "/r", tenant: "work" })',
      'const envOver = c.mdcgChildEnv({ root: "/r", tenant: "work", env: { MDCG_TENANT: "env-ten" } })',
      'console.log("U12JSON " + JSON.stringify({ matrix,',
      '  envWork: envWork.MDCG_TENANT, envOver: envOver.MDCG_TENANT }))',
    ].join('\n')
    const env = cleanEnv({ U12_TOKEN_STORE: store, U12_MDCG_CLIENT: ov.mdcgClientPath ?? MDCG_CLIENT })
    const r = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', code], {
      env, encoding: 'utf8', cwd: REPO, timeout: 60_000,
    })
    const line = (r.stdout || '').split('\n').find((l) => l.startsWith('U12JSON '))
    if (r.status !== 0 || !line) {
      reds.push(`probe_tenant:${(r.stderr || r.stdout || '').slice(-100)}`)
    } else {
      const out = JSON.parse(line.slice('U12JSON '.length)) as {
        matrix: Array<[string, string]>, envWork: string, envOver: string,
      }
      const bad = out.matrix.filter(([got, want]) => got !== want)
      push('tenant_priority', bad.length === 0)
      push('child_env_agrees', out.envWork === 'work' && out.envOver === 'env-ten')
    }
  }

  // G 源码锚点
  {
    const storeText = readFileSync(store, 'utf8')
    const clientText = ov.mdcgClientPath
      ? readFileSync(ov.mdcgClientPath, 'utf8')
      : readFileSync(MDCG_CLIENT, 'utf8')
    const indexText = ov.indexText ?? readFileSync(INDEX_TS, 'utf8')
    const bridgeText = ov.bridgeText ?? readFileSync(BRIDGE_TS, 'utf8')
    push('anchor_issue_has_tenant', /'--tenant', tenant/.test(storeText))
    push('anchor_cli_merges_env', /\.\.\.extraEnv,/.test(storeText))
    push('anchor_ring_check_used', /checkKeyring\(opts\.python, keyringPath, tenant, extraEnv\)/.test(storeText))
    push('anchor_child_env', /MDCG_TENANT: effectiveTenant\(opts\.tenant, opts\.env\)/.test(clientText))
    push('anchor_index_passes_config',
      /tenant: config\.mdcg\.tenant,\s*\n\s*env: config\.env,/.test(indexText))
    push('anchor_bridge_exit_code',
      /EXIT_TOKEN_REJECTED = 3/.test(bridgeText)
      && (bridgeText.match(/startupHint\([^)]*this\.lastExitCode\)/g) ?? []).length >= 2
      && /this\.lastExitCode = code/.test(bridgeText))

    // 行为面：退出码 3 的提示必须点名「令牌」，且不得再把人引向 python/依赖
    const hint = bridgeStartupStderr(ov.bridgePath ?? BRIDGE_TS)
    push('bridge_exit3_names_token', /退出码 3/.test(hint) && /令牌校验失败/.test(hint))
    push('bridge_exit3_not_blame_python', !/可执行文件与 md_cg 依赖/.test(hint))
  }

  return [...new Set(reds)]
}

test('#224 A–F：租户 / config.env / 吊销 / 换绑 / 关闭签发 / 单点', () => {
  const reds = evaluate()
  assert.deepEqual(reds, [], `红项：${reds.join(', ')}`)
})

/* ————— 定点变异自证 ————— */

function patch(src: string, from: string, to: string): string {
  // 源码是 CRLF（Windows 检出）：先归一为 LF，锚点才可写成与文件无关的形态。
  const text = src.replace(/\r\n/g, '\n')
  if (!text.includes(from)) throw new Error(`变异锚点未命中：${from.slice(0, 70)}`)
  return text.split(from).join(to)
}

/** 把相对 import 改写成绝对 file URL（供临时目录里的变异副本解析）。 */
function absolutizeImports(baseDir: string, text: string): string {
  return text.replace(/from '(\.{1,2}\/[^']+)'/g, (_m, rel: string) => {
    const abs = resolve(baseDir, rel).replace(/\.js$/, '.ts')
    return `from ${JSON.stringify(pathToFileURL(abs).href)}`
  })
}

interface Mutation {
  desc: string
  store?: Array<[string, string]>
  client?: Array<[string, string]>
  index?: Array<[string, string]>
  bridge?: Array<[string, string]>
  reds: string[]
}

const MUTATIONS: Record<string, Mutation> = {
  M1: {
    desc: '签发不带 --tenant（回到 #224 触发 1）',
    store: [[",\n      '--tenant', tenant]", ']']],
    reds: ['tenant_recorded', 'tenant_server_ok', 'rebind_reissued', 'rebind_server_ok'],
  },
  M2: {
    desc: '签发/复核 CLI 不合并 config.env（回到触发 2）',
    store: [['        ...extraEnv,\n', '']],
    reds: ['aux_record_at_aux', 'aux_server_ok'],
  },
  M3: {
    desc: '密钥环不复核（有内容就复用，回到触发 3）',
    store: [['const chk = checkKeyring(opts.python, keyringPath, tenant, extraEnv)',
      "const chk: RingCheck = { status: 'ok', reason: '' }"]],
    reds: ['revoked_not_reused', 'revoked_note_names_cause', 'revoked_guest_server_ok'],
  },
  M4: {
    desc: '租户不再单点（effectiveTenant 忽略 env + 子进程 env 另算）',
    store: [["const fromEnv = String(env?.['MDCG_TENANT'] ?? '').trim()", "const fromEnv = ''"]],
    client: [['MDCG_TENANT: effectiveTenant(opts.tenant, opts.env)',
      "MDCG_TENANT: opts.tenant ?? 'default'"]],
    reds: ['tenant_priority', 'child_env_agrees', 'anchor_child_env'],
  },
  M5: {
    desc: 'index.ts 不把 tenant/config.env 交给签发侧',
    index: [['      tenant: config.mdcg.tenant,\n      env: config.env,\n', '']],
    reds: ['anchor_index_passes_config'],
  },
  M6: {
    desc: '桥的提示不看退出码（一律指向 python/依赖）',
    bridge: [['startupHint(python, this.lastExitCode)',
      'startupHint(python, null)']],
    reds: ['bridge_exit3_names_token', 'bridge_exit3_not_blame_python'],
  },
  M7: {
    desc: '关闭自动签发只看 process.env（config.env 的开关被忽略）',
    store: [['autoIssueDisabledByEnv(extraEnv)', 'autoIssueDisabledByEnv()']],
    reds: ['auto_off_via_config_env'],
  },
  M8: {
    desc: 'auxRoot 不展开 ~（Node 侧落字面 ~ 目录，与 Python 分叉）',
    store: [['resolve(expandHome(raw))', 'resolve(raw)']],
    reds: ['tilde_keyring_matches_python', 'tilde_no_literal_segment',
      'tilde_keyring_shares_aux_with_record'],
  },
  M9: {
    desc: '删掉退出码 3 的分流分支本体（`if (exitCode === ...)` 短路为 false）',
    bridge: [['if (exitCode === EXIT_TOKEN_REJECTED) {', 'if (false) {']],
    reds: ['bridge_exit3_names_token', 'bridge_exit3_not_blame_python'],
  },
}

if (process.argv.includes('--mutate')) {
  const idx = process.argv.indexOf('--mutate')
  const name = process.argv[idx + 1] || ''
  const mut = MUTATIONS[name]
  if (!mut) {
    console.log(`未知变异组 ${JSON.stringify(name)}（可选 ${Object.keys(MUTATIONS).join('/')}）`)
    process.exit(1)
  }
  const dir = mkdtempSync(join(tmpdir(), 'iss224_mut_'))
  const storePath = join(dir, 'token_store_mut.ts')
  let storeText = readFileSync(TOKEN_STORE, 'utf8')
  for (const [from, to] of mut.store ?? []) storeText = patch(storeText, from, to)
  writeFileSync(storePath, absolutizeImports(join(REPO, 'src', 'lib'), storeText), 'utf8')

  const ov: Overrides = { tokenStorePath: storePath }
  if (mut.client) {
    let t = readFileSync(MDCG_CLIENT, 'utf8')
    for (const [from, to] of mut.client) t = patch(t, from, to)
    const clientPath = join(dir, 'mdcg_client_mut.ts')
    writeFileSync(clientPath, absolutizeImports(join(REPO, 'src', 'lib'), t), 'utf8')
    ov.mdcgClientPath = clientPath
  }
  if (mut.index) {
    let t = readFileSync(INDEX_TS, 'utf8')
    for (const [from, to] of mut.index) t = patch(t, from, to)
    ov.indexText = t
  }
  if (mut.bridge) {
    let t = readFileSync(BRIDGE_TS, 'utf8')
    for (const [from, to] of mut.bridge) t = patch(t, from, to)
    ov.bridgeText = t
    const bridgePath = join(dir, 'bridge_mut.ts')
    writeFileSync(bridgePath, absolutizeImports(join(REPO, 'src'), t), 'utf8')
    ov.bridgePath = bridgePath
  }

  const base = evaluate()
  const red = evaluate(ov)
  console.log(`!! #224 定点变异自证 · 组 ${name}：${mut.desc}\n`)
  console.log(`  未变异基线红项=${JSON.stringify(base)}（须为空）`)
  console.log(`  变异后红项=${JSON.stringify(red)}`)
  const hit = mut.reds.filter((r) => red.includes(r))
  const ok = base.length === 0 && red.length > 0 && hit.length === mut.reds.length
  console.log(`  预期红项 ${JSON.stringify(mut.reds)} → 命中 ${JSON.stringify(hit)}`)
  console.log(ok ? '\n变异自证通过：指定项逐项转红' : '\n变异自证失败：红项集合与预期不符')
  process.exit(ok ? 0 : 1)
}

void rmSync
