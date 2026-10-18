/**
 * issue386_tilde_expand.test.ts · 路径环境变量的 `~` 形态在 Node 与 Python 两侧同落点
 *
 * 功能名：`expandHome()` 单点 + 四个 env 入口（MDCG_STATE_ROOT / MDCG_DATA_ROOT /
 *         MDCG_ROOT / MDCG_CHILD_CWD）接上它；Node 与 `md_cg.datapath` 落点同一性断言。
 * 生效条件：`node --import tsx --test test/issue386_tilde_expand.test.ts`
 *           （变异自证：`node --import tsx test/issue386_tilde_expand.test.ts --mutate A|B|C|D`）
 * 子功能：
 *   A 组 expandHome 单元口径（`~/x`、`~\x`、`~`、`~user/x` 原样、绝对/相对原样）；
 *   B 组 四个 env 入口在 `~` 形态下全部落到家目录下（不再落到 `<仓根>/~`）；
 *   C 组 与 Python `md_cg.datapath` 的**落点同一性**（同一 env、同一 HOME 下三路径逐字相等）；
 *   D 组 机制反证：不展开时的字面落点确实在解析 cwd 下（证明 B/C 有判别力）；
 *        探针 cwd 用临时目录，变异腿不会在仓库根留下 `./~/run` 脏目录。
 * 执行：子进程隔离 HOME 与全部 MDCG_* env，逐条取数；变异组把 expandHome 改回/改坏后
 *       指定项必须转红。
 * 验证方式：默认模式全部 PASS（退出码 0）；`--mutate` 下每组红项集合须与预期**逐项相符**。
 * 不适用条件：不判 `~user` 形态的跨语言一致性（Node 侧按 PR #385 裁定原样保留，
 *   Python 的 expanduser 会展开它——属已知残留分叉，已登记在单元 residual）；
 *   不判 paths.json 的 `~` 取值（两侧同为字面量，本 issue 不含它）；
 *   不判 Windows 保留设备名闸（属 datapath 既有判据，另有守卫）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const DATAPATH = join(REPO, 'src', 'lib', 'datapath.ts')
const PY = process.env['PYTHON'] || 'python'
const TSX = join(REPO, 'node_modules', 'tsx', 'dist', 'loader.mjs')

/** 期望的单元读数（与 Python `os.path.expanduser` 对 `~`/`~/x` 的口径一致）。 */
function expectedExpand(home: string): Record<string, string> {
  return {
    '~/x': join(home, 'x'),
    '~\\x': join(home, 'x'),
    '~': home,
    '~user/x': '~user/x',      // PR #385 裁定：`~user` 原样保留
    '/abs/x': '/abs/x',
    'rel/x': 'rel/x',
  }
}

/** 子进程：在给定 HOME/env 下取 datapath 的四路径与 expandHome 读数。
 *  cwd 用独立临时目录（不是仓库根）——变异腿里 `~` 不展开时 `resolve('~/run')`
 *  会真的 mkdir 出一个字面 `~` 目录；若 cwd 是仓库根，这就会在仓内留下
 *  `./~/run` 脏目录（复核意见 3）。cwd 落在临时目录时，同一条判别力断言
 *  改判「runRoot 不得落在解析用的 cwd 下」——语义不变（cwd 必须在包外），
 *  且不会污染仓库。 */
function probeNode(modulePath: string, home: string, cwd: string) {
  const values = ['~/x', '~\\x', '~', '~user/x', '/abs/x', 'rel/x']
  const code = [
    "import { pathToFileURL } from 'node:url'",
    // 先换 cwd（临时目录），再加载 datapath：`--import tsx` 已在启动时按仓库 cwd
    // 解析完毕，而 runRoot() 在调用时才读 process.cwd()——变异腿里未展开的
    // `~/run` 因此只会落在临时 cwd 下，不在仓库根留 `./~/run`。
    'if (process.env.U12_CWD) process.chdir(process.env.U12_CWD)',
    'const m = await import(pathToFileURL(process.env.U12_DATAPATH).href)',
    `const vals = ${JSON.stringify(values)}`,
    'const expand = {}',
    'for (const v of vals) expand[v] = m.expandHome(v)',
    'console.log("U12JSON " + JSON.stringify({',
    '  paths: { stateRoot: m.stateRoot(), dataRoot: m.dataRoot(),',
    '           mdcgRoot: m.mdcgRoot(), runRoot: m.runRoot() },',
    '  expand,',
    '}))',
  ].join('\n')
  const env: Record<string, string> = {}
  for (const [k, v] of Object.entries(process.env)) {
    if (v === undefined) continue
    if (k.startsWith('MDCG_') || k === 'DSH_HOME') continue
    env[k] = v
  }
  Object.assign(env, {
    HOME: home, USERPROFILE: home, U12_DATAPATH: modulePath, U12_CWD: cwd,
    MDCG_STATE_ROOT: '~/.dsh-memory', MDCG_DATA_ROOT: '~/data',
    MDCG_ROOT: '~/brain', MDCG_CHILD_CWD: '~/run',
  })
  // `--import tsx` 按 cwd 解析 ⇒ 启动 cwd 仍是仓库根；cwd 切换在探针代码里做。
  const r = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', code], {
    env, encoding: 'utf8', cwd: REPO, timeout: 60_000,
  })
  const line = (r.stdout || '').split('\n').find((l) => l.startsWith('U12JSON '))
  if (r.status !== 0 || !line) {
    throw new Error(`node 探针失败 rc=${r.status}：${(r.stderr || r.stdout || '').slice(-400)}`)
  }
  return JSON.parse(line.slice('U12JSON '.length)) as {
    paths: Record<string, string>
    expand: Record<string, string>
  }
}

/** 子进程：Python 侧同一 env 下的三路径。 */
function probePython(home: string): Record<string, string> {
  const code = ('import json\n'
    + 'from md_cg import datapath as d\n'
    + 'print("U12JSON " + json.dumps({"stateRoot": d.state_root(), '
      + '"dataRoot": d.data_root(), "mdcgRoot": d.mdcg_root()}))\n')
  const env: Record<string, string> = {}
  for (const [k, v] of Object.entries(process.env)) {
    if (v === undefined) continue
    if (k.startsWith('MDCG_') || k === 'DSH_HOME') continue
    env[k] = v
  }
  Object.assign(env, {
    HOME: home, USERPROFILE: home, PYTHONPATH: REPO, PYTHONUTF8: '1',
    MDCG_STATE_ROOT: '~/.dsh-memory', MDCG_DATA_ROOT: '~/data', MDCG_ROOT: '~/brain',
  })
  const r = spawnSync(PY, ['-X', 'utf8', '-c', code], { env, encoding: 'utf8', cwd: REPO })
  const line = (r.stdout || '').split('\n').find((l) => l.startsWith('U12JSON '))
  if (r.status !== 0 || !line) {
    throw new Error(`python 探针失败 rc=${r.status}：${(r.stderr || '').slice(-400)}`)
  }
  return JSON.parse(line.slice('U12JSON '.length)) as Record<string, string>
}

const norm = (p: string): string => (process.platform === 'win32' ? p.toLowerCase() : p)
const hasTildeSegment = (p: string): boolean =>
  p.split(/[\\/]+/).some((seg) => seg === '~')

/** 判据主体：返回红项名（空数组 = 全过）。 */
function evaluate(modulePath: string): string[] {
  const reds: string[] = []
  const home = mkdtempSync(join(tmpdir(), 'iss386_home_'))
  const cwd = mkdtempSync(join(tmpdir(), 'iss386_cwd_'))
  let node: ReturnType<typeof probeNode>
  try {
    node = probeNode(modulePath, home, cwd)
  } catch (e) {
    return [`probe_node:${(e as Error).message.slice(0, 120)}`]
  }
  const exp = expectedExpand(home)

  // A 组：expandHome 单元口径
  for (const [input, want] of Object.entries(exp)) {
    if (node.expand[input] !== want) {
      reds.push(input === '~user/x' ? 'expand_tilde_user' : `expand:${input}`)
    }
  }

  // B 组：四个 env 入口落点
  const want: Record<string, string> = {
    stateRoot: join(home, '.dsh-memory'),
    dataRoot: join(home, 'data'),
    mdcgRoot: join(home, 'brain'),
    runRoot: join(home, 'run'),
  }
  for (const [k, v] of Object.entries(want)) {
    if (norm(node.paths[k] ?? '') !== norm(v)) reds.push(k)
    if (hasTildeSegment(node.paths[k] ?? '')) reds.push(`${k}_literal_tilde`)
  }
  // 落点必须在包外（runRoot 的既有声明）：解析 cwd 就是「包根」的替身，
  // runRoot 若落在它下面，等于子进程 cwd 在包内（pnpm 更新时 rmdir 必 BUSY）。
  if (norm(node.paths['runRoot'] ?? '').startsWith(norm(cwd) + (process.platform === 'win32' ? '\\' : '/'))) {
    reds.push('runRoot_in_cwd')
  }
  // 临时 cwd 下不得出现字面 `~` 目录（变异腿的落点痕迹；仓库根同理）
  if (existsSync(join(cwd, '~'))) reds.push('cwd_literal_tilde_dir')

  // C 组：与 Python 落点同一性
  try {
    const py = probePython(home)
    for (const k of ['stateRoot', 'dataRoot', 'mdcgRoot']) {
      if (norm(node.paths[k] ?? '') !== norm(py[k] ?? '')) reds.push(`${k}_split`)
    }
  } catch (e) {
    reds.push(`probe_python:${(e as Error).message.slice(0, 100)}`)
  }

  // D 组：机制反证——不展开时的落点确实在仓根下（判别力前提）
  if (norm(resolve('~/data')) === norm(join(home, 'data'))) reds.push('no_discrimination')
  if (isAbsolute(node.paths['dataRoot'] ?? '') !== true) reds.push('dataRoot_not_absolute')
  return [...new Set(reds)]
}

test('#386 A/B/C：`~` 形态四入口与 Python 同落点', () => {
  const reds = evaluate(DATAPATH)
  assert.deepEqual(reds, [], `红项：${reds.join(', ')}`)
})

test('#386 源码锚点：expandHome 是唯一展开点且四入口都接上', () => {
  const src = readFileSync(DATAPATH, 'utf8')
  const anchors: Array<[string, boolean]> = [
    ['expandHome 定义', /export function expandHome\(/.test(src)],
    ['stateRoot 接 expandHome', /cachedStateRoot = resolve\(expandHome\(env\)\)/.test(src)],
    ['dataRoot 接 expandHome', /if \(env\) return anchor\(expandHome\(env\)\)/.test(src)],
    ['mdcgRoot 接 expandHome', /if \(env\) return anchor\(expandHome\(env\)\)/.test(src)],
    ['runRoot 接 expandHome', /candidates\.push\(resolve\(expandHome\(override\)\)\)/.test(src)],
  ]
  const missing = anchors.filter(([, ok]) => !ok).map(([name]) => name)
  assert.deepEqual(missing, [], `缺失锚点：${missing.join(', ')}`)
})

/* ————— 定点变异自证（`--mutate A|B|C|D`） ————— */

function patch(src: string, from: string, to: string): string {
  if (!src.includes(from)) throw new Error(`变异锚点未命中：${from.slice(0, 60)}`)
  return src.replace(from, to)
}

const MUTATIONS: Record<string, { desc: string; apply: (s: string) => string; reds: string[] }> = {
  A: {
    desc: 'expandHome 整体失效（return p）',
    apply: (s) => patch(s,
      'export function expandHome(p: string, home: string = homedir()): string {',
      'export function expandHome(p: string, home: string = homedir()): string { return p'),
    reds: ['stateRoot', 'dataRoot', 'mdcgRoot', 'runRoot', 'stateRoot_split', 'dataRoot_split',
      'mdcgRoot_split', 'expand:~/x', 'expand:~\\x', 'expand:~', 'cwd_literal_tilde_dir'],
  },
  B: {
    desc: 'stateRoot 退回不展开（其余三入口保持）',
    apply: (s) => patch(s, 'cachedStateRoot = resolve(expandHome(env))', 'cachedStateRoot = resolve(env)'),
    reds: ['stateRoot', 'stateRoot_split'],
  },
  C: {
    desc: '过度展开：`~user` 也被展开',
    apply: (s) => patch(s,
      "if (p === '~') return home",
      "if (p === '~' || p.startsWith('~')) return join(home, p.slice(1))"),
    reds: ['expand_tilde_user'],
  },
  D: {
    desc: 'runRoot 退回不展开',
    apply: (s) => patch(s, 'candidates.push(resolve(expandHome(override)))',
      'candidates.push(resolve(override))'),
    reds: ['runRoot', 'runRoot_literal_tilde', 'runRoot_in_cwd', 'cwd_literal_tilde_dir'],
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
  const dir = mkdtempSync(join(tmpdir(), 'iss386_mut_'))
  const target = join(dir, 'datapath_mut.ts')
  copyFileSync(DATAPATH, target)
  const mutated = mut.apply(readFileSync(target, 'utf8'))
  const { writeFileSync } = await import('node:fs')
  writeFileSync(target, mutated, 'utf8')

  const base = evaluate(DATAPATH)
  const red = evaluate(target)
  console.log(`!! #386 定点变异自证 · 组 ${name}：${mut.desc}\n`)
  console.log(`  未变异基线红项=${JSON.stringify(base)}（须为空）`)
  console.log(`  变异后红项=${JSON.stringify(red)}`)
  const expected = mut.reds.filter((r) => red.includes(r))
  const ok = base.length === 0 && red.length > 0 && expected.length === mut.reds.length
  console.log(`  预期红项 ${JSON.stringify(mut.reds)} → 命中 ${JSON.stringify(expected)}`)
  console.log(ok ? '\n变异自证通过：指定项逐项转红' : '\n变异自证失败：红项集合与预期不符')
  process.exit(ok ? 0 : 1)
}

void TSX
