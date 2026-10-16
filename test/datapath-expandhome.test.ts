/**
 * datapath expandHome 测试 —— env 路径波浪线展开的同口径守卫（N117 / N167 / #352-D 族）。
 *
 * 覆盖面（与实现边界一一对应）：
 *   ① 判据表：~ / ~/x / ~\x / ~/a/../b / ~//x 展开到注入家目录——期望值由测试自己拼，
 *      home 经形参注入，不经被测实现推导；
 *   ② 过度收紧方向（反向变异）：~user / ~abc / ~ybyz/mem / 合法相对路径 / 绝对路径 /
 *      空串 / 中段波浪线一律原样返回，且不得被当 home 处理；
 *   ③ 四个 env 入口实跑：MDCG_STATE_ROOT / MDCG_CHILD_CWD / MDCG_DATA_ROOT /
 *      MDCG_ROOT 置为 ~/probe 时四个 getter 都落注入家目录下，且都不是
 *      「仓根/~/probe」（改前取值——回退即红锚点）；
 *   ④ 源码面「该判据只有一处实现」：递归扫 src/ 下全部 .ts，同判据命中文件必须恰为
 *      src/lib/datapath.ts；src/init.ts 必须委派（具名导入 expandHome、自身无同判据）；
 *   ⑤ 反例（断言有牙）：把第二处同判据实现放进临时目录，检测函数必须报出它；
 *      仅写在注释里的同判据不得被报出（钉住不误报方向）。
 *
 * 判据不自证：全部期望值在测试内以常量拼接独立写出，不调用 expandHome 反推。
 *
 * 零副作用：家目录以 HOME/USERPROFILE 注入 mkdtemp 临时目录并在 after 清理；
 * 不触碰真实家目录（runRoot 的 mkdir 亦落临时目录内）。
 */

import { test, after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  ENV_CHILD_CWD,
  ENV_DATA_ROOT,
  ENV_MDCG_ROOT,
  ENV_STATE_ROOT,
  dataRoot,
  expandHome,
  mdcgRoot,
  repoRoot,
  runRoot,
  stateRoot,
} from '../src/lib/datapath.js'

const TEST_DIR = dirname(fileURLToPath(import.meta.url))
const REPO = dirname(TEST_DIR)
const SRC = join(REPO, 'src')

/** 注入家目录：expandHome 的缺省 home 取自 os.homedir()，故先注 HOME/USERPROFILE。 */
const FAKE_HOME = mkdtempSync(join(tmpdir(), 'lingshu-expandhome-home-'))
process.env.HOME = FAKE_HOME
process.env.USERPROFILE = FAKE_HOME

after(() => {
  rmSync(FAKE_HOME, { recursive: true, force: true })
})

/** 反斜杠单字符（用变量拼，避免本文件自身出现转义歧义）。 */
const BS = '\\'

test('① 判据表：裸 ~ 与 ~/、~\\ 前缀展开到注入家目录（期望值独立写出）', () => {
  assert.equal(homedir(), FAKE_HOME, '家目录注入未生效 → 本组期望值失去意义')
  const cases: Array<[string, string, string]> = [
    ['裸 ~', '~', FAKE_HOME],
    ['~/x', '~/x', join(FAKE_HOME, 'x')],
    ['~/（空余段）', '~/', FAKE_HOME],
    ['~\\x（Windows 分隔符形态）', '~' + BS + 'x', join(FAKE_HOME, 'x')],
    ['~/a/b', '~/a/b', join(FAKE_HOME, 'a', 'b')],
    ['~/a/../b（归一）', '~/a/../b', join(FAKE_HOME, 'b')],
    ['~//x', '~//x', join(FAKE_HOME, 'x')],
    ['~/~（余段自身含波浪线）', '~/' + '~', join(FAKE_HOME, '~')],
    ['~\\user（分隔符形态，不是 ~user 形态）', '~' + BS + 'user', join(FAKE_HOME, 'user')],
  ]
  for (const [name, input, expected] of cases) {
    assert.equal(expandHome(input, FAKE_HOME), expected, name + '：' + JSON.stringify(input))
  }
})

test('② 过度收紧方向：非 home 形态一律原样，不得被当 home 处理', () => {
  const notHome = [
    '~user',
    '~abc',
    '~ybyz/mem',
    'mem/x',
    './mem',
    '../mem',
    '/abs/x',
    'a/~b',
    'x~',
    '~~',
    '',
  ]
  for (const input of notHome) {
    assert.equal(expandHome(input, FAKE_HOME), input, '应原样返回：' + JSON.stringify(input))
    assert.ok(
      !expandHome(input, FAKE_HOME).startsWith(FAKE_HOME),
      '不得被当 home 处理：' + JSON.stringify(input),
    )
  }
})

test('③ 四个 env 入口：~/probe 落注入家目录，不得落「仓根/~」字面目录（回退即红）', () => {
  const probe = 'lingshu-expandhome-env-probe'
  const expected = join(FAKE_HOME, probe)
  // 改前取值：node 侧不展开 ⇒ resolve/anchor 把 ~/probe 当相对段拼到插件仓根下。
  // 期望值独立写出（join 常量），不由 expandHome 反推。
  const preFix = join(repoRoot(), '~', probe)
  process.env[ENV_STATE_ROOT] = '~/' + probe
  process.env[ENV_CHILD_CWD] = '~/' + probe
  process.env[ENV_DATA_ROOT] = '~/' + probe
  process.env[ENV_MDCG_ROOT] = '~/' + probe
  const actual: Array<[string, string]> = [
    [ENV_STATE_ROOT, stateRoot()],
    [ENV_CHILD_CWD, runRoot()],
    [ENV_DATA_ROOT, dataRoot()],
    [ENV_MDCG_ROOT, mdcgRoot()],
  ]
  for (const [key, got] of actual) {
    assert.equal(got, expected, key + ' 应展开到注入家目录')
    assert.notEqual(got, preFix, key + ' 仍落「仓根/~」字面目录 ⇒ 未接线 expandHome')
  }
})

const JUDGEMENT_PREFIX = /startsWith\s*\(\s*['"]~[\\/]['"]\s*\)/
const JUDGEMENT_BARE = /==\s*['"]~['"]/

/** 去掉块注释与行注释，保留字符串字面量（判据写在字符串里，不能连字符串一起剥）。 */
function stripTsComments(src: string): string {
  let out = ''
  let quote = ''
  let i = 0
  while (i < src.length) {
    const c = src[i] ?? ''
    const n = src[i + 1] ?? ''
    if (quote) {
      out += c
      if (c === '\\') {
        out += n
        i += 2
        continue
      }
      if (c === quote) quote = ''
      i += 1
      continue
    }
    if (c === '"' || c === "'" || c === '\u0060') {
      quote = c
      out += c
      i += 1
      continue
    }
    if (c === '/' && n === '*') {
      const end = src.indexOf('*/', i + 2)
      i = end < 0 ? src.length : end + 2
      out += ' '
      continue
    }
    if (c === '/' && n === '/') {
      const end = src.indexOf('\n', i)
      i = end < 0 ? src.length : end
      out += ' '
      continue
    }
    out += c
    i += 1
  }
  return out
}

/** 递归收集 dir 下 .ts 文件（不含 .d.ts）。 */
function walkTs(dir: string): string[] {
  const out: string[] = []
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name)
    if (e.isDirectory()) out.push(...walkTs(p))
    else if (e.isFile() && e.name.endsWith('.ts') && !e.name.endsWith('.d.ts')) out.push(p)
  }
  return out
}

/** 同判据实现点：同时出现「~/ 或 ~\\ 前缀判据」与「裸 ~ 相等判据」的源文件。 */
function tildeJudgementSites(dir: string): string[] {
  const hits: string[] = []
  for (const file of walkTs(dir)) {
    const code = stripTsComments(readFileSync(file, 'utf8'))
    if (JUDGEMENT_PREFIX.test(code) && JUDGEMENT_BARE.test(code)) hits.push(file)
  }
  return hits.sort()
}

test('④ 源码面唯一实现：src/ 下同判据只允许一处，且必须是 src/lib/datapath.ts', () => {
  const sites = tildeJudgementSites(SRC).map((p) => p.slice(REPO.length + 1).replace(/\\/g, '/'))
  assert.deepEqual(
    sites,
    ['src/lib/datapath.ts'],
    '该判据必须只有一处实现（新增第二处即报红）：实测 ' + JSON.stringify(sites),
  )
  const initSrc = stripTsComments(readFileSync(join(SRC, 'init.ts'), 'utf8'))
  assert.ok(!JUDGEMENT_PREFIX.test(initSrc), 'src/init.ts 不得自带前缀判据（必须委派 expandHome）')
  assert.ok(!JUDGEMENT_BARE.test(initSrc), 'src/init.ts 不得自带裸 ~ 判据（必须委派 expandHome）')
  assert.match(
    initSrc,
    /import\s*\{[^}]*\bexpandHome\b[^}]*\}\s*from\s*'\.\/lib\/datapath\.js'/,
    'src/init.ts 必须具名导入 datapath.ts 的 expandHome（单点委派）',
  )
})

test('⑤ 反例：第二处同判据实现必须被报出；仅注释里的判据不得被报出', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'lingshu-expandhome-fake-src-'))
  try {
    mkdirSync(join(tmp, 'lib'), { recursive: true })
    writeFileSync(
      join(tmp, 'lib', 'datapath.ts'),
      stripTsComments(readFileSync(join(SRC, 'lib', 'datapath.ts'), 'utf8')),
    )
    // 人为加出的第二处实现（形态照抄真实实现）
    writeFileSync(
      join(tmp, 'second.ts'),
      'export function expandHomeAgain(p: string, home: string): string {\n'
        + "  if (p === '~') return home\n"
        + "  if (p.startsWith('~" + BS + BS + "') || p.startsWith('~/')) return join(home, p.slice(2))\n"
        + '  return p\n'
        + '}\n',
    )
    // 仅注释里提到判据的文件（不得被报出——钉住不误报方向）
    writeFileSync(
      join(tmp, 'comment_only.ts'),
      '// 同判据先例：p === "~" 与 p.startsWith("~/") 的展开见 datapath.ts\n'
        + '/* 另一形态：p === "~" 与 p.startsWith("~' + BS + BS + '") */\n'
        + 'export const NOT_A_JUDGEMENT = 1\n',
    )
    const hits = tildeJudgementSites(tmp).map((p) => p.slice(tmp.length + 1).replace(/\\/g, '/'))
    assert.deepEqual(
      hits,
      ['lib/datapath.ts', 'second.ts'],
      '第二处实现必须被报出：实测 ' + JSON.stringify(hits),
    )
    assert.ok(!hits.includes('comment_only.ts'), '注释里的判据不得被报出（防假阳性）')
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})
