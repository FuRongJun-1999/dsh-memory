/**
 * python-utf8-mode.test.ts · 子进程「UTF-8 模式」注入的守卫与机制对照
 *
 * 背景（2026-09-20 现场）：桥子进程被注入 `PYTHONIOENCODING=utf-8`，其**后代**于是
 * 往管道写 UTF-8；但后代读 `subprocess.run(..., text=True)` 时的默认 text 编码取自
 * locale（Windows=cp936）→ 读线程崩死、诊断静默丢失：
 *
 *     [lingshu-bridge] Exception in thread Thread-N (_readerthread)
 *     UnicodeDecodeError: 'gbk' codec can't decode byte 0x82 in position 181
 *
 * 本文件三件事，缺一不可：
 *   ① 生产路径断言：`mdcgChildEnv()` 必须同时注入 `PYTHONIOENCODING=utf-8` 与
 *      `PYTHONUTF8=1`（去掉任一条即红——这是「修在物上」而非「修在文档上」）。
 *   ② 机制反证（P1）：不注入 UTF-8 模式时，同构调用**确实崩**（证明 ① 有判别力，
 *      不是「怎么写都过」的空断言）。locale 已是 UTF-8 的机器无从构造该现场 → skip。
 *   ③ 机制消除（P3）：注入 UTF-8 模式后同构调用成功，且**解码内容正确**（中文可读，
 *      而非 errors="replace" 的替换字符）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mdcgChildEnv } from '../src/lib/mdcg_client.js'

const PY = process.env['PYTHON'] || 'python'

/** 内层父进程：按 {CALL} 形态读一个往 stderr 写 UTF-8 中文的孙进程。 */
const GRANDCHILD =
  "import sys;sys.stderr.write('\\u4e2d\\u6587\\u9519\\u8bef\\uff1a'+'x'*160+'\\n');"
  + "sys.stdout.write('\\u4e2d\\u6587\\u8f93\\u51fa\\n')"

function innerCode(call: string): string {
  return [
    'import subprocess, sys',
    'PY = sys.executable',
    `GRAND = ${JSON.stringify(GRANDCHILD)}`,
    'try:',
    `    r = ${call}`,
    "    print('OK stdout_head=' + repr(r.stdout[:14]))",
    'except Exception as exc:',
    "    print('RAISED ' + repr(exc))",
  ].join('\n')
}

/** 在给定 env 下跑内层父进程，返回它的 stdout/stderr。 */
function runInner(call: string, env: Record<string, string>) {
  const r = spawnSync(PY, ['-c', innerCode(call)], {
    env: { ...process.env, ...env },
    encoding: 'utf8',
  })
  return { out: r.stdout ?? '', err: r.stderr ?? '', status: r.status }
}

/** 内层 python 的默认 locale 编码（构造现场的前提；非 gbk 系则无从复现）。 */
function innerLocale(): string | null {
  const r = spawnSync(PY, ['-c', 'import locale;print(locale.getpreferredencoding(False))'],
    { encoding: 'utf8' })
  if (r.status !== 0 || !r.stdout) return null
  return r.stdout.trim().toLowerCase()
}

test('① 生产路径：mdcgChildEnv 同时注入 PYTHONIOENCODING=utf-8 与 PYTHONUTF8=1', () => {
  const env = mdcgChildEnv({ root: '/tmp/root' })
  assert.equal(env['PYTHONIOENCODING'], 'utf-8', '子进程自身 stdio 必须 utf-8')
  assert.equal(env['PYTHONUTF8'], '1', '子进程后代默认 text 编码必须 utf-8（PEP 540）')
  assert.ok(env['PYTHONPATH'], 'PYTHONPATH 必须锚定随包 md_cg（issue #12 口径）')
  assert.equal(env['MDCG_ROOT'], '/tmp/root')
  // 显式覆盖优先（测试要构造非 UTF-8 现场时用得到）
  const overridden = mdcgChildEnv({ root: '/tmp/root', env: { PYTHONUTF8: '0' } })
  assert.equal(overridden['PYTHONUTF8'], '0')
})

test('② 机制反证：不注入 UTF-8 模式时，读 UTF-8 中文 stderr 必崩（有判别力）', (t) => {
  const loc = innerLocale()
  if (loc === null) return t.skip('本机无可用 python，跳过机制对照')
  if (loc.startsWith('utf-8') || loc === 'utf8') {
    return t.skip(`内层 locale 已是 ${loc}，无从构造 gbk 现场`)
  }
  const { out, err } = runInner("subprocess.run([PY, '-c', GRAND], capture_output=True,"
    + ' text=True)', { PYTHONIOENCODING: 'utf-8' })
  // 判据只认**语义**（异常类型 + 两条流任一），不认**打印位置/线程名**（2026-09-20 v15-10）：
  // 旧断言 `assert.match(err, /_readerthread/)` 钉住了「解码崩在读线程里」这一**旧 CPython
  // 形态**——3.11 起 `subprocess._communicate` 在主线程 `_translate_newlines` 完成解码，
  // `err` 为空；它还与同测试的 `assert.match(out, /RAISED/)`（主线程重抛形态）**形态互斥**，
  // 两者不可能同时成立，于是「证明守卫有判别力」的这条测试在 3.11 + 非 utf-8 locale 下必假红。
  // 形态只做记录（写进失败消息便于取证），不参与裁决。
  const combined = out + err
  const shape = err.includes('_readerthread') ? '读线程' : '主线程重抛'
  assert.match(combined, /UnicodeDecodeError/,
    `应复现解码崩溃（locale=${loc}，形态=${shape}）：${combined.slice(0, 200)}`)
  assert.match(out, /RAISED/, '调用方应看到异常而非静默成功')
})

test('③ 机制消除：注入 UTF-8 模式后成功，且解码内容正确', (t) => {
  const loc = innerLocale()
  if (loc === null) return t.skip('本机无可用 python，跳过机制对照')
  // 与生产同源：用 mdcgChildEnv 的编码约定（而非手写两个变量）
  const env = mdcgChildEnv({ root: '/tmp/root', env: { PYTHONIOENCODING: 'utf-8' } })
  const { out, err } = runInner("subprocess.run([PY, '-c', GRAND], capture_output=True,"
    + ' text=True)', {
    PYTHONIOENCODING: env['PYTHONIOENCODING'] as string,
    PYTHONUTF8: env['PYTHONUTF8'] as string,
  })
  assert.equal(/UnicodeDecodeError/.test(out + err), false,
    `不应再有解码崩溃：${(out + err).slice(0, 200)}`)
  assert.match(out, /^OK /, `应成功返回：${out}`)
  assert.match(out, /中文输出/, '解码结果必须是可读中文（非替换字符）')
})

// ---------------------------------------------------------------------------
// ④⑤ 「唯一构造点」站点扫描（2026-09-20 v15-9）
// ---------------------------------------------------------------------------
// `mdcgChildEnv()` 头注声明自己是「唯一构造点…勿在别处另拼 env」，但守卫此前**只
// import 构造函数并断言其输出**，没有任何断言扫描 spawn 调用点——声明的「唯一」无人守。
// v15b 结构扫描实测：Python 目标 spawn 站点 3 个、走构造点的 0 个、两条编码变量全缺 2 个。
// 本节把该主张变成**可机械裁决的不变量**：src/ 下每个 spawn 族调用点都必须「表态」。

/** src/ 下递归收集 .ts 文件。 */
function walkTs(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walkTs(p))
    else if (name.endsWith('.ts')) out.push(p)
  }
  return out
}

const SRC_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')
/** spawn 族调用（含 exec/execFile）。**不按目标语言过滤**——避免 v15b §8.3 自陈的
 *  「紧邻是否出现 python」启发式漏判；代价是每个站点一律需要表态。 */
const CALL_RX = /\b(spawnSync|spawn|execFileSync|execFile|execSync|exec)\s*\(/g
/** 单站点判定窗口（字符）：须覆盖到 env 对象（token_store 的 env 在调用后约 12 行处）。 */
const SITE_WINDOW = 900

interface SpawnSite { rel: string; line: number; code: string }

/** 剥离注释与字符串字面量（保留换行，维持行号与窗口语义）。
 *
 * 为什么必须剥离：这是守卫的**已知自伤形态**——文本窗口会把注释/文档样例里的调用
 * 当成真实调用点（`md_cg/test_subproc_encoding.py` 头注记录了同一教训，它因此改用
 * AST 判定）。TS 侧用轻量词法剥离达到等价效果：`src/lib/python_path.ts` 头注里的示例
 * 写法（`spawn('python')` 抛 ENOENT 的那句）不是调用点，剥离后不再被计入。
 */
function stripCommentsAndStrings(src: string): string {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const c = src[i]
    const c2 = src[i + 1]
    if (c === '/' && c2 === '/') {                    // 行注释
      while (i < n && src[i] !== '\n') { out += ' '; i++ }
      continue
    }
    if (c === '/' && c2 === '*') {                    // 块注释
      out += '  '
      i += 2
      while (i < n && !(src[i] === '*' && src[i + 1] === '/')) {
        out += src[i] === '\n' ? '\n' : ' '
        i++
      }
      if (i < n) { out += '  '; i += 2 }
      continue
    }
    if (c === "'" || c === '"' || c === '`') {        // 字符串 / 模板字面量
      const q = c
      out += ' '
      i++
      while (i < n && src[i] !== q) {
        if (src[i] === '\\') { out += '  '; i += 2; continue }
        out += src[i] === '\n' ? '\n' : ' '
        i++
      }
      if (i < n) { out += ' '; i++ }
      continue
    }
    out += c
    i++
  }
  return out
}

function scanSpawnSites(srcRoot: string): SpawnSite[] {
  const out: SpawnSite[] = []
  for (const file of walkTs(srcRoot)) {
    const text = stripCommentsAndStrings(readFileSync(file, 'utf8'))
    const rel = relative(srcRoot, file).split(sep).join('/')
    CALL_RX.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = CALL_RX.exec(text)) !== null) {
      out.push({
        rel,
        line: text.slice(0, m.index).split('\n').length,
        code: text.slice(m.index, m.index + SITE_WINDOW),
      })
    }
  }
  return out
}

/** 站点是否已表态：null = 合规；否则返回未表态原因。 */
function siteReason(code: string): string | null {
  if (code.includes('mdcgChildEnv(')) return null
  if (code.includes('PYTHONUTF8') && code.includes('PYTHONIOENCODING')) return null
  return '未引用 mdcgChildEnv()，也未同时显式声明 PYTHONUTF8 + PYTHONIOENCODING'
}

/** 显式豁免：**文件级 + 计数上限**——防止「文件内新增未表态站点」被整文件豁免掩盖。 */
const EXEMPT_SITES: Record<string, { max: number; why: string }> = {
  'bridge.ts': {
    max: 1,
    why: 'env 由调用方传入：MdcgClient 构造函数经 mdcgChildEnv() 构造后交给 LingshuBridge（本文件不自建 env）',
  },
  'lib/mutual.ts': {
    max: 1,
    why: 'exec(cmd) 为 wmic/powershell 系统查询（非 Python 目标、不经 Python 解码器）；本文件内的 Python 站点已显式注入两条编码变量',
  },
}

test('④ 站点扫描：「唯一构造点」是被守护的不变量（v15-9）', () => {
  const sites = scanSpawnSites(SRC_ROOT)
  // 防空转假绿：扫描范围坍塌（如路径变更）时站点数会骤降
  assert.ok(sites.length >= 3,
    `扫描到的 spawn 族站点过少（${sites.length}）——疑似扫描范围坍塌`)

  const perFile = new Map<string, number>()
  const offenders: string[] = []
  for (const s of sites) {
    if (siteReason(s.code) === null) continue
    offenders.push(`${s.rel}:${s.line}`)
    perFile.set(s.rel, (perFile.get(s.rel) ?? 0) + 1)
  }
  const over: string[] = []
  for (const [rel, n] of perFile) {
    const ex = EXEMPT_SITES[rel]
    if (!ex) over.push(`${rel}：${n} 个未表态站点，且不在豁免清单`)
    else if (n > ex.max) over.push(`${rel}：未表态 ${n} 个 > 豁免上限 ${ex.max}`)
  }
  assert.deepEqual(over, [],
    '存在未表态的 spawn 站点——须走 mdcgChildEnv()、或同时显式声明两条编码变量、'
    + '或登记豁免并写明理由：\n' + over.join('\n')
    + `\n（全部未表态站点：${offenders.join(', ')}）`)

  // 豁免清单防腐化：登记的每个文件必须真的仍有站点（否则该条目已过期，应删除）
  for (const rel of Object.keys(EXEMPT_SITES)) {
    assert.ok(sites.some((s) => s.rel === rel),
      `豁免清单里的 ${rel} 已无 spawn 站点——请移除该条目（防腐化）`)
  }
})

test('⑤ 站点扫描判据有判别力（合成反例必须被抓）', () => {
  const bare = "const c = spawn(python, ['-m', 'md_cg.mcp_server'], { env: { ...process.env } })"
  assert.notEqual(siteReason(bare), null, '裸 env（无任何编码变量）却未判违规——判据失效')
  assert.equal(siteReason("spawn(python, args, { env: mdcgChildEnv(opts) })"), null,
    '走构造点应判合规')
  assert.equal(
    siteReason("spawnSync(python, a, { env: { PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' } })"), null,
    '显式两条编码变量应判合规')
})
