/**
 * 守卫 · 桥被处置/子进程退出后的状态面（issue #899）
 *
 * 缺陷（修复前实跑取证）：dispose() 只置 disposed 并关 stdin；exit 分支的结算被
 * if (!this.disposed) 挡住 ⇒ readyState 停在 'ok' ⇒ isReady() 恒 true（子进程已不可写）。
 * 宿主门控据此放行写入，callTool 立即抛「灵枢进程不可写」并被 .catch 记 failed：
 * 自动记忆 100% 失败而状态面显示正常（written/failed 一一配对、服务端零审计）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { LingshuBridge } from '../src/bridge.js'

const NL = String.fromCharCode(10)
const FAKE_MCP = [
  "const rl = require('node:readline').createInterface({ input: process.stdin });",
  "rl.on('line', (line) => {",
  "  let m = null; try { m = JSON.parse(line); } catch { return; }",
  "  if (m && m.id !== undefined && m.method === 'initialize') {",
  "    process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: m.id, result: { protocolVersion: '2024-11-05', capabilities: {}, serverInfo: { name: 'fake', version: '0' } } }) + " + JSON.stringify(NL) + ");",
  "  }",
  "});",
  "setTimeout(() => process.exit(0), 60000).unref();",
].join(NL)

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

async function waitFor(cond: () => boolean, ms: number, label: string): Promise<void> {
  const deadline = Date.now() + ms
  while (Date.now() < deadline) {
    if (cond()) return
    await sleep(20)
  }
  throw new Error('超时未满足：' + label)
}

function makeBridge(script: string): LingshuBridge {
  return new LingshuBridge({
    python: process.execPath,
    args: ['-e', script],
    env: {},
    timeoutMs: 10_000,
    maxRetryDelayMs: 50,
  } as never)
}

test('#899 处置后 isReady() 必须为 false（子进程已不可写不得报就绪）', async () => {
  const bridge = makeBridge(FAKE_MCP)
  bridge.start()
  try {
    await waitFor(() => bridge.isReady(), 8_000, '握手就绪')
    assert.equal(bridge.alive, true, '握手后进程应存活')
    bridge.dispose()
    assert.equal(bridge.isReady(), false, '处置后 isReady() 必须为 false')
    assert.equal(await bridge.waitReady(), false, '处置后 waitReady() 必须 resolve(false)')
  } finally {
    bridge.dispose()
  }
})

test('#899 子进程退出后 isReady() 必须转为 false', async () => {
  const quick = FAKE_MCP.replace('60000', '150')
  const bridge = makeBridge(quick)
  bridge.start()
  try {
    await waitFor(() => bridge.isReady(), 8_000, '握手就绪')
    await waitFor(() => !bridge.alive, 8_000, '子进程退出')
    await waitFor(() => !bridge.isReady(), 4_000, '状态面转 false')
    assert.equal(bridge.isReady(), false, '进程已退出时 isReady() 必须为 false')
  } finally {
    bridge.dispose()
  }
})