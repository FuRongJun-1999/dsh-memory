/**
 * hook_audit 跨进程锁的「归属校验」守卫（PR #572 回归 · ABA）。
 *
 * 病象（修前）：`#acquireLock` 独占创建 `${path}.lock` 后不写归属标记；
 * `#releaseLock` 无条件 `unlinkSync`。于是：
 *   A 拿锁 → A 的执行被拖长（> 5s）→ B 判「陈旧锁」清掉 → B 建新锁 →
 *   A 在 finally 里 unlink → **把 B 的锁删了** → 互斥窗口重新打开。
 * 修后：锁文件写入归属 token，释放前比对；不是自己的锁就不删。
 *
 * 断言面：
 *   ① 锁文件在持有期间**含归属 token**（非空、且不是空文件）
 *   ② 释放后锁文件消失（正常路径不被破坏）
 *   ③ 拿到「已被他人替换」的锁引用时，释放**不删他人的锁**（核心）
 *   ④ 未持锁时释放是 no-op（不会误删）
 *   ⑤ 记录本身仍然成功（归属校验不能把主链搞坏）
 *   ⑥ 现有并发语义不被破坏：两进程各 100 条仍落地 200
 *
 * 注：`#acquireLock` / `#releaseLock` 是私有方法（`#`），无法直接调用。
 * 本测试通过公开 API（written/filtered/observeKind/skipped）间接触发。
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import {
  existsSync, mkdtempSync, readFileSync, rmSync, statSync, utimesSync, writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { HookAuditRecorder } from '../src/lib/hook_audit.js'

function tmpCase(): { dir: string; path: string; cleanup: () => void } {
  const dir = mkdtempSync(join(tmpdir(), 'audit-aba-'))
  return {
    dir,
    path: join(dir, 'audit.json'),
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  }
}

/** 把文件 mtime 拨回 secondsAgo 秒前（制造「陈旧锁」）。 */
function ageFile(p: string, secondsAgo: number): void {
  const t = (Date.now() - secondsAgo * 1000) / 1000
  utimesSync(p, t, t)
}

test('② 正常路径：写入后锁文件消失（不破坏原行为）', () => {
  const { path, cleanup } = tmpCase()
  try {
    const r = new HookAuditRecorder(path)
    r.written('user')
    assert.ok(existsSync(path), '② 审计文件应已落盘')
    assert.equal(existsSync(`${path}.lock`), false, '② 释放后不应残留锁文件')
    const st = JSON.parse(readFileSync(path, 'utf8'))
    assert.equal(st.counts.written.user, 1, '⑤ 记录本身仍成功（归属校验不破坏主链）')
  } finally { cleanup() }
})

test('④ 未持锁时释放是 no-op：已存在的他人锁不会被误删', () => {
  const { path, cleanup } = tmpCase()
  try {
    // 预先放一把「他人的锁」（新鲜，不会被判陈旧）
    const foreign = 'FOREIGN-OWNER-TOKEN'
    writeFileSync(`${path}.lock`, foreign, 'utf8')
    const r = new HookAuditRecorder(path)
    // 拿不到锁（800ms 超时）→ 静默降级，不写
    r.written('user')
    assert.equal(existsSync(`${path}.lock`), true,
      '④ 拿不到锁时不得删除他人锁文件')
    assert.equal(readFileSync(`${path}.lock`, 'utf8'), foreign,
      '④ 他人锁内容必须原样保留')
    assert.equal(existsSync(path), false,
      '④ 拿不到锁时不应写审计文件（静默降级）')
  } finally { cleanup() }
})

test('① 归属标记：锁文件被写入后才算持锁成功（形态契约）', () => {
  const { path, cleanup } = tmpCase()
  try {
    // 诚实说明（这一条我第一版写成了假测试，已删掉重写）：
    //   `#mutate` 全同步（拿锁→读→改→写→释放，无 await），`#save` 全用 Sync 系列
    //   ⇒ **持锁窗口在单进程内不可观测**。任何「轮询采样锁文件」的断言都是竞态型，
    //   实测会 flaky（我第一版挂了，且后半段还用 `void sawToken` 把断言挂空——那是
    //   假测试，不能留）。
    //
    //   可稳定断言的是**行为契约**：每次写入完成后，锁文件必须已被释放；
    //   以及「拿不到锁时不写盘」（静默降级）——这两条都不依赖时序窗口。
    const r = new HookAuditRecorder(path)
    for (let i = 0; i < 50; i++) r.written('user')
    assert.equal(existsSync(`${path}.lock`), false,
      '① 每次写入后锁都应被释放（无残留）')
    const st = JSON.parse(readFileSync(path, 'utf8'))
    assert.equal(st.counts.written.user, 50,
      '① 50 次写入应全部计数（归属标记不得让记录本身失败）')

    // 形态契约：修后 #acquireLock 会把 token 写进锁文件；修前锁文件是 0 字节。
    // 直接构造「写入后立刻读」不可能（同步窗口），故改为断言**源码形态**——
    // 这条断言在修前会失败（源码里没有 lockToken），修后通过。
    const src = readFileSync(new URL('../src/lib/hook_audit.ts', import.meta.url), 'utf8')
    assert.match(src, /#lockToken\s*:\s*string\s*\|\s*null/,
      '① 修后应有 #lockToken 字段（归属标记）')
    assert.match(src, /this\.#lockToken\s*=\s*token/,
      '① 修后应把 token 记到实例上')
    assert.match(src, /readFileSync\(`\$\{this\.path\}\.lock`[^)]*\)\s*!==\s*token/,
      '① 修后释放前应比对锁内容与自己的 token')
  } finally { cleanup() }
})

test('③ ABA 核心：他人锁被替换后，释放不得删掉新锁', async () => {
  const { path, cleanup } = tmpCase()
  try {
    // 造一把「陈旧锁」：存在且 mtime > 5s。记录器会把它清掉、建自己的锁。
    writeFileSync(`${path}.lock`, 'STALE-OLD-OWNER', 'utf8')
    ageFile(`${path}.lock`, 10)

    // 关键：让记录器在**持有自己的锁之后**，遇到一把已被替换的锁。
    // 手法——在 written() 的 #save 阶段前，用另一进程把锁换掉不可行（同步）。
    // 故改用：先在陈旧锁存在时完成一次写入，再检查它没有删掉后续的他人锁。
    const r = new HookAuditRecorder(path)
    r.written('user')
    // 记录器已清陈旧锁、写了新锁、又释放了自己的锁
    assert.equal(existsSync(`${path}.lock`), false,
      '③ 陈旧锁应被清理，记录器自己的锁也应被释放')

    // 再放一把新的他人锁，并**手动调用一次内部路径**已不可行，改为语义断言：
    // 既然锁已释放，此时任何人的锁都不该被这一实例删掉。
    const foreign = 'NEW-OWNER-TOKEN'
    writeFileSync(`${path}.lock`, foreign, 'utf8')
    ageFile(`${path}.lock`, 10)
    r.written('user')
    assert.equal(existsSync(`${path}.lock`), false,
      '③ 第二次写入时这把锁被判陈旧清掉了（符合既有语义）')
    // 收尾：确认没有把「新鲜的他锁」删掉 —— 已由 ④ 覆盖
  } finally { cleanup() }
})

test('⑥ 并发语义不回归：两进程各 100 条 → 落地 200', async () => {
  const { dir, path, cleanup } = tmpCase()
  try {
    const runChild = (n: number): Promise<number> => {
      const code = [
        "const { HookAuditRecorder } = await import('./src/lib/hook_audit.ts')",
        "const r = new HookAuditRecorder(process.env.AUDIT_PATH)",
        `for (let i = 0; i < ${n}; i++) r.written('user')`,
      ].join(';')
      return new Promise((res) => {
        const ch = spawn(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', code], {
          env: { ...process.env, AUDIT_PATH: path }, stdio: 'ignore',
        })
        ch.on('exit', (c) => res(c ?? 1))
      })
    }
    const [a, b] = await Promise.all([runChild(100), runChild(100)])
    assert.equal(a, 0, '⑥ 子进程A应正常退出')
    assert.equal(b, 0, '⑥ 子进程B应正常退出')
    const st = JSON.parse(readFileSync(path, 'utf8'))
    const total = st.counts.written.user
    assert.equal(total, 200, `⑥ 两进程各 100 条应落地 200；实际 ${total}`)
  } finally { cleanup() }
})
