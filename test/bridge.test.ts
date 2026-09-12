/**
 * LingshuBridge 真实集成测试：spawn **本仓自带**的 md_cg
 * （`python -m md_cg.mcp_server`），验证握手、工具发现（kernel/full 双面）、
 * `cg` 基元数据往返、错误处理与 dispose。
 *
 * 三层拆分 S4 之后不再依赖外部 AEIS 仓——大脑随插件自带
 * （见 docs/灵枢三层拆分规划_v0.1.md、docs/功能调用映射表_v0.1.md）。
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { LingshuBridge } from '../src/bridge.js'

/** 本仓根目录：md_cg 随仓库自带，靠 PYTHONPATH 解析（无需 pip 安装）。 */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/** Windows 下 python 进程可能短暂持有 DB 句柄，清理失败不阻塞测试。 */
function safeCleanup(dir: string): void {
  try {
    rmSync(dir, { recursive: true, force: true })
  } catch {
    /* 句柄未释放，tmp 目录由系统清理 */
  }
}

/** 构造指向本仓 md_cg 的桥；surface 决定工具面（kernel=cg/stg，full=+细粒度）。 */
function createBridge(root: string, surface: 'kernel' | 'full' = 'full'): LingshuBridge {
  return new LingshuBridge({
    python: 'python',
    args: ['-m', 'md_cg.mcp_server'],
    env: {
      PYTHONPATH: REPO_ROOT,
      PYTHONIOENCODING: 'utf-8',
      MDCG_ROOT: root,
      MDCG_MCP_SURFACE: surface,
      // 集成测试用 legacy 身份（recorder：可写 contextual/knowledge/structural），
      // 省去签发令牌；真实部署推荐 MDCG_TOKEN（见 dsh/cordis.yml.example）。
      MDCG_LEGACY_ENV_AUTH: '1',
      MDCG_ACTOR: 'dsh-test',
      MDCG_TENANT: 'default',
      MDCG_CLEARANCE: 'private',
    },
    cwd: REPO_ROOT,
    timeoutMs: 15_000,
    maxRetryDelayMs: 5_000,
  })
}

test('握手：进程启动并完成 initialize 握手', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'mdcg'))
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

test('工具发现（kernel）：默认面只有 cg / stg 两个认知基元', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'mdcg'), 'kernel')
  bridge.start()
  try {
    await bridge.waitReady()
    const tools = await bridge.listTools()
    const names = tools.map((t) => t.name).sort()
    assert.deepEqual(names, ['cg', 'stg'], `kernel 面应只有 cg/stg（实际 ${names.join(',')}）`)
  } finally {
    bridge.dispose()
    safeCleanup(dir)
  }
})

test('工具发现（full）：cg/stg 基元 + mdcg_* 细粒度工具（33）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'mdcg'), 'full')
  bridge.start()
  try {
    await bridge.waitReady()
    const tools = await bridge.listTools()
    const names = new Set(tools.map((t) => t.name))
    assert.equal(tools.length, 33, `full 面应有 33 个工具（实际 ${tools.length}）`)
    for (const expected of ['cg', 'stg', 'mdcg_remember', 'mdcg_recall', 'mdcg_service_info']) {
      assert.ok(names.has(expected), `应包含工具 ${expected}`)
    }
  } finally {
    bridge.dispose()
    safeCleanup(dir)
  }
})

test('数据往返：mdcg_remember → mdcg_search 命中写入的记忆', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'mdcg'), 'full')
  bridge.start()
  try {
    await bridge.waitReady()
    const content = '灵枢 DSH 插件集成测试的唯一标记语'
    const write = await bridge.callTool('mdcg_remember', {
      content,
      layer: 'knowledge',
    })
    assert.equal(write.isError, false, 'mdcg_remember 不应报错')

    const read = await bridge.callTool('mdcg_search', { query: '唯一标记语', limit: 3 })
    assert.equal(read.isError, false, 'mdcg_search 不应报错')
    const text = read.content.map((b) => b.text ?? '').join('')
    assert.ok(text.includes('唯一标记语'), `检索应命中写入内容（实际: ${text.slice(0, 200)}）`)
  } finally {
    bridge.dispose()
    safeCleanup(dir)
  }
})

test('错误处理：调用不存在的工具以 isError 软错误返回（不抛异常）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'mdcg'))
  bridge.start()
  try {
    await bridge.waitReady()
    // md_cg 契约：工具异常在 tools/call 内被捕获，以 isError 结果返回（非 JSON-RPC error）。
    const res = await bridge.callTool('no_such_tool', {})
    assert.equal(res.isError, true, '未知工具应返回 isError=true')
    const text = res.content.map((b) => b.text ?? '').join('')
    assert.ok(text.includes('no_such_tool'), `错误内容应包含工具名（实际: ${text}）`)
  } finally {
    bridge.dispose()
    safeCleanup(dir)
  }
})

test('dispose：进程优雅退出', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-bridge-'))
  const bridge = createBridge(join(dir, 'mdcg'))
  bridge.start()
  await bridge.waitReady()
  bridge.dispose()
  // 给进程留退出时间
  await new Promise((resolve) => setTimeout(resolve, 500))
  assert.equal(bridge.alive, false, 'dispose 后进程应退出')
  rmSync(dir, { recursive: true, force: true })
})
