/**
 * LingshuBridge 真实集成测试：spawn 本机 AEIS，验证握手、工具发现、
 * remember → recall 数据往返、错误处理与 dispose。
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { LingshuBridge } from '../src/bridge.js'

/** AEIS 库源码目录（未安装时靠 PYTHONPATH 解析）。 */
const AEIS_DIR = 'D:\\Program Files\\2_ai\\AEIS'

/** Windows 下 python 进程可能短暂持有 DB 句柄，清理失败不阻塞测试。 */
function safeCleanup(dir: string): void {
  try {
    safeCleanup(dir)
  } catch {
    /* 句柄未释放，tmp 目录由系统清理 */
  }
}

function createBridge(dbPath: string): LingshuBridge {
  return new LingshuBridge({
    python: 'python',
    args: ['-m', 'aeis.mcp.server'],
    env: {
      AEIS_DB: dbPath,
      AEIS_IDENTITY: 'dsh-test',
      PYTHONPATH: AEIS_DIR,
      PYTHONIOENCODING: 'utf-8',
    },
    cwd: AEIS_DIR,
    timeoutMs: 15_000,
    maxRetryDelayMs: 5_000,
  })
}

test('握手：进程启动并完成 initialize 握手', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'test.db'))
  bridge.start()
  try {
    const ok = await bridge.waitReady()
    assert.equal(ok, true, 'waitReady 应返回 true')
    assert.equal(bridge.alive, true, '子进程应存活')
  } finally {
    bridge.dispose()
    safeCleanup(dir)
  }
})

test('工具发现：listTools 返回灵枢全部工具（含 remember/recall）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'test.db'))
  bridge.start()
  try {
    await bridge.waitReady()
    const tools = await bridge.listTools()
    assert.ok(tools.length >= 38, `工具数应 >= 38（实际 ${tools.length}）`)
    const names = new Set(tools.map((t) => t.name))
    for (const expected of ['remember', 'recall', 'search', 'think', 'service_info']) {
      assert.ok(names.has(expected), `应包含工具 ${expected}`)
    }
  } finally {
    bridge.dispose()
    safeCleanup(dir)
  }
})

test('数据往返：remember → recall 命中写入的记忆', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'test.db'))
  bridge.start()
  try {
    await bridge.waitReady()
    const content = '灵枢 DSH 插件集成测试的唯一标记语'
    const write = await bridge.callTool('remember', {
      content,
      importance: 0.9,
      tags: ['dsh-test'],
    })
    assert.equal(write.isError, false, 'remember 不应报错')

    const read = await bridge.callTool('recall', { query: '唯一标记语', limit: 3 })
    assert.equal(read.isError, false, 'recall 不应报错')
    const text = read.content.map((b) => b.text ?? '').join('')
    assert.ok(text.includes('唯一标记语'), `recall 应命中写入内容（实际: ${text.slice(0, 120)}）`)
  } finally {
    bridge.dispose()
    safeCleanup(dir)
  }
})

test('错误处理：调用不存在的工具应报错', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'test.db'))
  bridge.start()
  try {
    await bridge.waitReady()
    await assert.rejects(() => bridge.callTool('no_such_tool', {}), /灵枢错误/)
  } finally {
    bridge.dispose()
    safeCleanup(dir)
  }
})

test('dispose：进程优雅退出', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'test.db'))
  bridge.start()
  await bridge.waitReady()
  bridge.dispose()
  // 给进程留退出时间
  await new Promise((resolve) => setTimeout(resolve, 500))
  assert.equal(bridge.alive, false, 'dispose 后进程应退出')
  rmSync(dir, { recursive: true, force: true })
})
