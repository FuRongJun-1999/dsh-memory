/**
 * V23 守卫 · 桥重试不泄漏子进程（对应缺陷：src/bridge.ts:284）
 *
 * 缺陷链条（修复前）：
 *  · initialize 握手超时 → handshake() catch → scheduleRetry() → 定时后
 *    spawnAndHandshake() 再次 spawn，:182 `this.proc = proc` 直接覆盖引用；
 *  · 旧进程若仍存活（卡死但不退出的服务端），既不 kill 也不关 stdin——
 *    引用被覆盖后永远无人清理 = 僵尸进程泄漏，最多累积 8 个并存；
 *  · dispose() 只收尾最后一个 this.proc（原报告动态复现：8 个泄漏、dispose 后剩 7）。
 *
 * 守卫（对修复前代码红）：spawn 真实「永不退出、不响应协议」的 node 子进程
 * （node -e 'setInterval(()=>{},1<<30)'）驱动握手超时重试换代，轮询收集每一代
 * this.proc 引用；达到重试上限后断言——除最后一代（由 dispose 的
 * 「stdin.end + 2s 兜底 kill」既有语义收尾）外，其余各代都已退出。
 * 旧代码这些代全部仍存活 → 红；修复后每代在换代时被回收 → 绿。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { LingshuBridge } from '../src/bridge.js'

/** 桥持有子进程的最少代数（达到 MAX_RETRIES 上限前的实际 spawn 数：1 + 7 次重试）。 */
const EXPECTED_GENERATIONS = 8

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

test('握手超时重试不泄漏子进程：换代旧进程全部被回收（最后一代归 dispose 收尾）', async () => {
  const bridge = new LingshuBridge({
    // 永不退出、不读 stdin 协议 → initialize 必然超时 → 逐次重试换代
    python: process.execPath,
    args: ['-e', 'setInterval(()=>{},1<<30)'],
    env: {},
    timeoutMs: 200,
    maxRetryDelayMs: 30,
  })
  const seen = new Set<any>()          // 每一代 this.proc（TS private 仅编译期，运行时可读）
  const killAll = () => {              // 兜底：红跑也不让测试泄漏进程
    bridge.dispose()
    for (const p of seen) {
      if (p && p.exitCode === null && p.signalCode === null) {
        try { p.stdin?.end() } catch { /* 已关闭 */ }
        try { p.kill() } catch { /* 已退出 */ }
      }
    }
  }
  try {
    bridge.start()
    // 轮询采样（10ms）直到放弃终态（retries 达 MAX_RETRIES=8）；上限 15s 防挂死
    const deadline = Date.now() + 15_000
    while (Date.now() < deadline) {
      const proc = (bridge as any).proc
      if (proc) seen.add(proc)
      if ((bridge as any).gaveUp) break
      await sleep(10)
    }
    assert.ok((bridge as any).gaveUp, '应在连续握手失败后进入放弃终态（sanity：重试机制本身正常）')
    // 再等一代采样，确保最后一次 spawn 的进程也被捕获
    await sleep(50)
    const last = (bridge as any).proc
    if (last) seen.add(last)
    assert.ok(seen.size >= EXPECTED_GENERATIONS,
      `应至少换代 ${EXPECTED_GENERATIONS} 代（实际 ${seen.size}）——否则未复现泄漏场景`)
    // 给换代 kill / exit 事件留时间后检查：除最后一代（当前 this.proc，由
    // dispose 的「stdin.end + 2s 兜底 kill」既有语义收尾）外，其余各代都应
    // 已被重试路径回收——旧代码这些代全部存活 = 泄漏主体。
    await sleep(500)
    const current = (bridge as any).proc
    const stale = [...seen].filter((p) => p !== current)
    const leaked = stale.filter(
      (p) => p.exitCode === null && p.signalCode === null,
    )
    assert.equal(leaked.length, 0,
      `重试换代的 ${stale.length} 个旧子进程中仍有 ${leaked.length} 个存活——` +
      '重试路径未清理上一个仍存活的子进程（僵尸泄漏）')
  } finally {
    killAll()
    // 兜底 kill 是异步生效，等一拍让测试进程退出时不携带孤儿
    await sleep(300)
  }
})
