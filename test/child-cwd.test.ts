/**
 * issue #18 回归：随包子进程的 cwd 必须落在**插件包目录之外**。
 *
 * 根因（Windows 实测）：某进程的 cwd 所指目录**不能被删除或改名**
 * （Python `rmtree` → errno=13 / WinError=32；Node `rmSync` → EPERM）。
 * DSH 插件按 hoisted 布局装在 `<profile>/node_modules/<pkg>`，而 pnpm 更新
 * 该包必须先把包目录 `rmdir` → 只要有任何随包子进程把包目录当作 cwd，
 * 应用内更新就必然 `ERR_PNPM_EBUSY`，且**旧版钉住时永不自愈**
 * （连升级回滚一起失败）。
 *
 * 三条不变量（钉成机械断言，防止将来有人把 cwd 改回 `repoRoot()`）：
 *   ① `runRoot()` 落点在包外、为绝对路径、且目录真实存在（cwd 目标消失会引出
 *      新的怪问题）；
 *   ② 端到端：`MdcgClient`（不传 cwd，即真实宿主形态）拉起的 md_cg 子进程，
 *      其**自报 cwd**（子进程自己报）不在插件仓内 —— 这正是「包目录可被 pnpm
 *      删除」的充分条件；
 *   ③ 缺陷机制（仅 Windows）：有进程以某目录为 cwd 时该目录不可删、进程退出后
 *      恢复可删，且 cwd 落包外时包目录可删 —— 证伪「cwd 落点无所谓」。
 *
 * ②消费 `md_cg/selfreport.py` 落的自报文件（`cwd` + `ppid` + `source_dir`），
 * 故只认「本测试进程拉起的那个子进程」，不受同机其它常驻 md_cg 干扰，
 * 也不依赖 Windows 专有的 PEB 读取。③在非 Windows 上诚实跳过而非假装通过。
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, isAbsolute, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { MdcgClient } from '../src/lib/mdcg_client.js'
import { repoRoot, runRoot } from '../src/lib/datapath.js'

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
/** 与 md_cg/selfreport.py 的 SELF_REPORT_DIR 同口径（同用户跨端一致）。 */
const SELF_REPORT_DIR = join(tmpdir(), 'md_cg_servers')
const WIN = process.platform === 'win32'

/** path 是否位于 dir 之内（含 dir 自身）。 */
function inside(dir: string, path: string): boolean {
  const rel = relative(dir, path)
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel))
}

/** 干净收尾：Windows 下 python 可能短暂持有句柄，清理失败不阻塞测试。 */
function safeCleanup(dir: string): void {
  try {
    rmSync(dir, { recursive: true, force: true })
  } catch {
    /* 句柄未释放，tmp 目录由系统清理 */
  }
}

/** 读取全部自报（坏文件跳过；目录不存在返回空）。 */
function readSelfReports(): Array<Record<string, unknown>> {
  let names: string[] = []
  try {
    names = readdirSync(SELF_REPORT_DIR)
  } catch {
    return []
  }
  const out: Array<Record<string, unknown>> = []
  for (const n of names) {
    if (!n.endsWith('.json')) continue
    try {
      const parsed = JSON.parse(readFileSync(join(SELF_REPORT_DIR, n), 'utf8')) as
        Record<string, unknown>
      if (typeof parsed['pid'] === 'number') out.push(parsed)
    } catch {
      /* 坏文件不影响整体 */
    }
  }
  return out
}

const wait = (ms: number): Promise<void> => new Promise((r) => { setTimeout(r, ms) })

test('issue #18 ①：runRoot() 是包外落点、绝对路径且目录存在', () => {
  const rr = runRoot()
  assert.ok(isAbsolute(rr), `runRoot 必须是绝对路径（实际 ${rr}）`)
  assert.ok(existsSync(rr), `runRoot 目录必须真实存在（cwd 目标消失会引出新的怪问题）：${rr}`)
  assert.equal(
    inside(repoRoot(), rr),
    false,
    `子进程 cwd 必须落在插件包目录之外（包目录=${repoRoot()}，实际 cwd=${rr}）`,
  )
})

test('issue #18 ②：MdcgClient 默认 cwd 拉起的子进程，自报 cwd 在包外', async () => {
  assert.ok(
    existsSync(SELF_REPORT_DIR),
    `自报目录不存在，无法核验子进程 cwd（md_cg/selfreport.py 未落盘？）：${SELF_REPORT_DIR}`,
  )

  const dir = mkdtempSync(join(tmpdir(), 'lingshu-issue18-'))
  // 真实宿主形态：不传 cwd（旧行为 = repoRoot()，即被钉住的包目录）
  const client = new MdcgClient({
    python: 'python',
    root: join(dir, 'mdcg'),
    env: { MDCG_LEGACY_ENV_AUTH: '1', MDCG_ACTOR: 'dsh-test' },
    timeoutMs: 15_000,
    maxRetryDelayMs: 5_000,
  })
  client.start()
  try {
    const ok = await client.waitReady()
    assert.equal(ok, true, 'MdcgClient 默认形态应完成握手')

    // 自报 ppid = 本测试进程 → 精确锁定本测试拉起的子进程（不受同机其它常驻进程干扰）
    const mine = readSelfReports().filter((r) => r['ppid'] === process.pid)
    assert.ok(
      mine.length >= 1,
      `应能读到本测试拉起的 md_cg 子进程自报（ppid=${process.pid}；`
      + `目录 ${SELF_REPORT_DIR} 现有 ${readSelfReports().length} 条）`,
    )
    for (const rec of mine) {
      const cwd = rec['cwd']
      const sourceDir = rec['source_dir']
      assert.equal(typeof cwd, 'string', `自报应含 cwd（实际 ${JSON.stringify(cwd)}）`)
      assert.equal(typeof sourceDir, 'string', `自报应含 source_dir（实际 ${JSON.stringify(sourceDir)}）`)
      assert.ok(cwd, '自报 cwd 不应为空串')
      // 自报加载源须为本仓 md_cg：证明这确实是随包子进程，而非环境里的其它 md_cg
      assert.equal(
        resolve(sourceDir as string),
        join(REPO_ROOT, 'md_cg'),
        `自报加载源应为本仓 md_cg（实际 ${String(sourceDir)}）`,
      )
      assert.equal(
        inside(repoRoot(), cwd as string),
        false,
        'issue #18：子进程 cwd 必须落在插件包外，否则 pnpm 更新包目录必然 '
        + `ERR_PNPM_EBUSY（自报 cwd=${String(cwd)}）`,
      )
    }
  } finally {
    client.dispose()
    safeCleanup(dir)
  }
})

test('issue #18 ③：目录被某进程当作 cwd 时不可删、进程退出后恢复可删',
  { skip: !WIN && 'POSIX 允许删除被当作 cwd 的目录，本机制仅 Windows 成立' },
  async () => {
    const base = mkdtempSync(join(tmpdir(), 'lingshu-cwdlock-'))
    const pkg = join(base, 'fake_pkg')      // 模拟插件包目录
    const outside = join(base, 'outside')   // 模拟修复后的落点
    const children: ChildProcess[] = []

    const spawnIn = (cwd: string): ChildProcess => {
      const child = spawn('python', ['-c', 'import time; time.sleep(30)'],
        { cwd, stdio: 'ignore', windowsHide: true })
      children.push(child)
      return child
    }

    try {
      mkdirSync(pkg, { recursive: true })
      mkdirSync(outside, { recursive: true })

      // 基线：无占用时可删
      const free = mkdtempSync(join(base, 'free_'))
      rmSync(free, { recursive: true, force: true })
      assert.equal(existsSync(free), false, '无占用目录应可删除（基线）')

      // 有子进程以 pkg 为 cwd → 不可删（缺陷机制：ERR_PNPM_EBUSY 即源自此）
      const child = spawnIn(pkg)
      await wait(1000)
      assert.throws(
        () => rmSync(pkg, { recursive: true }),
        (e: NodeJS.ErrnoException) =>
          e.code === 'EBUSY' || e.code === 'EPERM' || e.code === 'EACCES',
        'Windows 下「被当作 cwd 的目录」应拒绝删除',
      )
      assert.ok(existsSync(pkg), '删除被拒后目录应仍然存在')

      // 子进程退出 → 恢复可删
      child.kill()
      await new Promise<void>((r) => { child.on('exit', () => { r() }) })
      await wait(500)
      rmSync(pkg, { recursive: true, force: true })
      assert.equal(existsSync(pkg), false, '进程退出后目录应恢复可删')

      // 对照：cwd 落在包外时，包目录可删（修复后的性质）
      mkdirSync(pkg, { recursive: true })
      const child2 = spawnIn(outside)
      await wait(1000)
      rmSync(pkg, { recursive: true, force: true })
      assert.equal(existsSync(pkg), false, 'cwd 在包外时包目录应可删（修复后的性质）')
      child2.kill()
    } finally {
      for (const c of children) { try { c.kill() } catch { /* 已退出 */ } }
      safeCleanup(base)
    }
  })
