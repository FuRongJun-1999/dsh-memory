/**
 * 守卫 · 桥「冷却分支」的状态面结算（对应缺陷：src/bridge.ts:301-313，N267）
 *
 * 缺陷链条（修复前，本测实跑取证）：
 *  · exit 分支的「10 分钟内第 3 次意外退出 → 冷却 5 分钟」路径在 :313 直接
 *    `return`，**跳过**了同分支尾部的 `readyState='failed'` + `flushBootQueue(false)`
 *    （:316-317）——只有 `scheduleRetry` 是刻意跳过（冷却定时器 :307 已安排重试）；
 *  · 于是冷却期内子进程已死而 `isReady()` 仍为 true、`waitReady()` 立即 resolve(true)：
 *    该值经 MdcgClient 一行直通（src/lib/mdcg_client.ts:209-211）→ 宿主门控据此
 *    放行，调用错误被空 catch 静默吞（src/hooks.ts:442，N265 注释插入后现 :451）
 *    ——宿主状态面失真（alive:false / isReady:true）。
 *
 * 守卫取向：真实子进程（node -e 假 MCP：应答 initialize 后按参数自退）+ 真实 exit
 * 事件驱动分支；断言只打**公开面**（isReady / waitReady / alive）与控制台结算日志。
 * 窗口预置 2 条＝「10 分钟窗口内已两次意外退出」的历史态（本测只驱动第 3 次 exit，
 * 与真实触发路径同形；窗口计数的自身逻辑不在本测判据面）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { LingshuBridge } from '../src/bridge.js'

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

/** 假 MCP 服务：应答 initialize（握手成功），此后 argv[1] 毫秒自退（code=0＝外部关闭形态）。 */
const FAKE_MCP = `
const rl = require('node:readline').createInterface({ input: process.stdin });
let armed = false;
rl.on('line', (line) => {
  let m = null;
  try { m = JSON.parse(line); } catch { return; }
  if (m && m.id !== undefined && m.method === 'initialize') {
    process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: m.id, result: { protocolVersion: '2024-11-05', capabilities: {}, serverInfo: { name: 'fake-mcp', version: '0' } } }) + '\\n');
    if (!armed) { armed = true; setTimeout(() => process.exit(0), Number(process.argv[1] || 300)); }
  }
});
setTimeout(() => process.exit(0), 60000).unref();
`

/** @param exitAfterReplyMs 握手应答后的存活毫秒数（≥5000 ⇒ 走「长存后退出」分支） */
function createBridge(exitAfterReplyMs: number): LingshuBridge {
  return new LingshuBridge({
    python: process.execPath,
    args: ['-e', FAKE_MCP, String(exitAfterReplyMs)],
    env: {},
    timeoutMs: 10_000,
    maxRetryDelayMs: 50,
  })
}

/** 采集桥的结算日志（都走 console.error）；原样转发，失败现场不丢。 */
function captureErr(): { lines: string[]; restore: () => void } {
  const lines: string[] = []
  const orig = console.error.bind(console)
  console.error = (...args: unknown[]) => { lines.push(args.map((a) => String(a)).join(' ')); orig(...(args as string[])) }
  return { lines, restore: () => { console.error = orig } }
}

async function waitFor(cond: () => boolean, ms: number, label: string): Promise<void> {
  const deadline = Date.now() + ms
  while (Date.now() < deadline) {
    if (cond()) return
    await sleep(20)
  }
  throw new Error(`等待超时：${label}`)
}

test('① 冷却分支必须结算状态面：子进程已死，isReady()/waitReady() 不得仍报就绪（N267）', async () => {
  const cap = captureErr()
  const bridge = createBridge(5500)     // 握手后存活 >5s ⇒ 「长存后退出」⇒ 冷却分支前置条件
  try {
    // 窗口预置 2 条＝10 分钟内已两次意外退出的历史态（下一次 exit 即第 3 次 ⇒ 冷却）
    ;(bridge as any).unexpectedExits = [Date.now() - 2000, Date.now() - 1000]
    bridge.start()
    assert.equal(await bridge.waitReady(), true, 'sanity：假 MCP 应答 initialize ⇒ 应握手就绪')
    assert.equal(bridge.isReady(), true, 'sanity：就绪态是缺陷场景的起点')

    await waitFor(() => cap.lines.some((l) => l.includes('冷却 5 分钟后自动恢复')), 20_000,
      '进入冷却分支（第 3 次意外退出）')
    await sleep(80)     // 让该分支的同步收尾跑完

    // 三条读数先采样再断言（失败消息里带上全部实测值，红/绿读数一次可查）
    const aliveAfter = bridge.alive
    const readyAfter = bridge.isReady()
    const waitAfter = await bridge.waitReady()
    const readings = `实测 alive=${aliveAfter} isReady=${readyAfter} waitReady=${waitAfter}`
    assert.equal(aliveAfter, false, `子进程应已退出（冷却期内不 spawn）；${readings}`)
    assert.equal(readyAfter, false,
      `冷却分支后 isReady() 必须为 false——此前恒 true（子进程已死仍报就绪，宿主门控据此放行）；${readings}`)
    assert.equal(waitAfter, false,
      `冷却分支后 waitReady() 必须立即结算 false——此前立即 resolve(true)；${readings}`)
    assert.ok((bridge as any).retryTimer, '冷却定时器须仍在（只跳过 scheduleRetry，不跳过冷却重试）')
    const proc = (bridge as any).proc
    assert.ok(proc && (proc.exitCode !== null || proc.signalCode !== null),
      '冷却期内不得立即换代：this.proc 仍是那个已退出的进程')
  }
  finally {
    cap.restore()
    bridge.dispose()
    await sleep(200)
  }
})

test('② 回归：未达冷却阈值的退出仍走原结算并排重试（冷却分支不得被误触）', async () => {
  const cap = captureErr()
  const bridge = createBridge(300)      // 握手后短存即退（uptime < 5s）⇒ 原结算路径 :316-318
  try {
    bridge.start()
    assert.equal(await bridge.waitReady(), true, 'sanity：握手就绪')
    await waitFor(() => cap.lines.some((l) => l.includes('次重试')), 10_000, '排重试调度')
    assert.ok(!cap.lines.some((l) => l.includes('冷却 5 分钟后自动恢复')),
      '未达 3 次阈值不得进入冷却分支')
    assert.equal(bridge.isReady(), false, '退出后 isReady() 应为 false（原结算路径）')
    assert.equal(bridge.alive, false, '退出后进程不可存活')
    // 重试照常换代：首轮 delay=1000ms（maxRetryDelayMs=50 只压低后续轮）
    await waitFor(() => {
      const p = (bridge as any).proc
      return !!p && p.exitCode === null && p.signalCode === null
    }, 5000, '重试换代出新进程')
  }
  finally {
    cap.restore()
    bridge.dispose()
    await sleep(200)
  }
})
