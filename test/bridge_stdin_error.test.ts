/**
 * N119 守卫 · stdin 写/端必须挂 error 监听（对应缺陷：src/bridge.ts:354-360 writeRaw）
 *
 * 缺陷链条（修复前）：
 *  · writeRaw 的 proc.stdin.write 与 dispose/killStaleProc 的 stdin.end() 全文件
 *    零 error 监听（grep `.on(` 仅 stderr/rl/proc error/proc exit 四处）；
 *  · 大消息（超管道缓冲）写入后滞留在 Node 写缓冲区（背压），此刻子进程恰好
 *    死亡（崩溃 / kill / 换代），在途冲刷即以 'error'（EPIPE / write after end）
 *    事件发射——无监听 → uncaughtException → DSH 宿主进程整体崩溃；
 *  · :356 的 writable 守卫只挡调用瞬间，挡不住在途冲刷失败。
 *    （v13 材料同款竞态实验 3/3 轮复现 'write EPIPE'。）
 *
 * 守卫两断言（对修复前代码红）：
 *  1. 结构：spawn 后子进程 stdin 必须已挂 'error' 监听（旧代码 listenerCount=0 → 红）；
 *  2. 行为：1MB 大消息写入（子进程不读 stdin，必然背压滞留）+ 立即 kill 子进程，
 *     进程级 uncaughtException 不得捕获到 stdin 流写错误（旧代码捕获 → 红）。
 *     测试进程靠临时 uncaughtException 监听存活以观察宿主视角——生产无监听即崩溃。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { LingshuBridge } from '../src/bridge.js'

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

/** 桥持有一个活着但不读 stdin、不应答协议的 node 子进程（initialize 只会等超时）。 */
function createBridge(): LingshuBridge {
  return new LingshuBridge({
    python: process.execPath,
    args: ['-e', 'setInterval(()=>{},1<<30)'],
    env: {},
    // 测试窗口内不触发握手超时重试，避免换代噪声（子进程由测试自行 kill）
    timeoutMs: 60_000,
    maxRetryDelayMs: 30_000,
  })
}

/** stdin 流写错误的形态（EPIPE / write after end / destroyed / EOF）。 */
function isStreamWriteError(err: Error): boolean {
  const code = (err as NodeJS.ErrnoException).code ?? ''
  const msg = String((err as NodeJS.ErrnoException).message ?? err)
  return code === 'EPIPE' ||
    /EPIPE|write after end|destroyed|EOF/i.test(msg)
}

test('N119：stdin 挂 error 监听——大消息滞留+子进程死亡不产生 uncaughtException', async () => {
  const escaped: Error[] = []
  const onUncaught = (err: Error): void => { escaped.push(err) }
  // 临时接住进程级未捕获异常（宿主视角：无监听者时这一下就是整体崩溃）
  process.on('uncaughtException', onUncaught)

  const bridge = createBridge()
  try {
    bridge.start()
    const proc = (bridge as any).proc as import('node:child_process').ChildProcess
    assert.ok(proc, 'sanity：start() 后子进程应已 spawn')
    assert.ok(proc.stdin, 'sanity：子进程 stdin 应为 pipe')

    // 断言 1（结构）：stdin 必须挂有 error 监听——这是「在途冲刷失败不逃逸」的充要前提
    assert.ok(proc.stdin!.listenerCount('error') >= 1,
      '子进程 stdin 应挂有 error 监听——否则在途冲刷失败直接以 uncaughtException 打崩宿主')

    // 断言 2（行为）：大消息（1MB >> 管道缓冲）写入背压滞留 + 立即杀子进程
    const big = {
      jsonrpc: '2.0', id: 999, method: 'tools/call',
      params: { name: 'x', arguments: { blob: 'A'.repeat(1024 * 1024) } },
    }
    ;(bridge as any).writeRaw(big)
    proc.kill()
    // 给在途冲刷失败（EPIPE/destroyed）与 exit 收尾留时间
    await sleep(800)
    const streamErrs = escaped.filter(isStreamWriteError)
    assert.equal(streamErrs.length, 0,
      `stdin 流写错误逃逸到 uncaughtException ${streamErrs.length} 次` +
      `（${streamErrs.map((e) => e.message).join('; ')}）——生产宿主会整体崩溃`)
  } finally {
    process.removeListener('uncaughtException', onUncaught)
    bridge.dispose()
    // dispose 的兜底 kill 异步生效，等一拍不让测试进程携带孤儿退出
    await sleep(200)
  }
})
