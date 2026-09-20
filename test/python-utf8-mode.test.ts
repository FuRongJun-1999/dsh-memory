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
  assert.match(err, /_readerthread/, `应复现读线程崩溃（locale=${loc}）：${err.slice(0, 200)}`)
  assert.match(out, /RAISED/, '读线程崩死后调用方应看到异常而非静默成功')
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
  assert.equal(err.includes('_readerthread'), false, `不应再有读线程崩溃：${err.slice(0, 200)}`)
  assert.match(out, /^OK /, `应成功返回：${out}`)
  assert.match(out, /中文输出/, '解码结果必须是可读中文（非替换字符）')
})
