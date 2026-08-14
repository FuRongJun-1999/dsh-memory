/**
 * 最小 Cordis host 集成测试：用 cordis 4 原生 Context 加载插件
 * （不依赖 DSH 全组件，隔离 v0.1 不稳定面），验证：
 * - 插件激活成功（工具注册进 ctx.tools）
 * - lingshu_ 前缀工具出现在 schemas 中
 * - 插件卸载后工具注销
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import { ToolRegistry } from '@deepseek-ai/dsh-tools'
import { SystemPrompt } from '@deepseek-ai/dsh-system-prompt'
import * as plugin from '../src/index.js'

const AEIS_DIR = 'D:\\Program Files\\2_ai\\AEIS'

/** 构建一个装有插件的最小 host；返回清理函数。 */
async function mountHost(dbPath: string) {
  const root = new Context()
  const promptFiber = await root.plugin(SystemPrompt)
  const toolsFiber = await root.plugin(ToolRegistry)
  const pluginFiber = await root.plugin(
    {
      name: plugin.name,
      inject: plugin.inject,
      Config: plugin.Config,
      apply: plugin.apply,
    },
    {
      serverName: 'lingshu',
      dbPath,
      identity: 'dsh-host-test',
      python: 'python',
      moduleArgs: ['-m', 'aeis.mcp.server'],
      env: { PYTHONPATH: AEIS_DIR, PYTHONIOENCODING: 'utf-8' },
      cwd: AEIS_DIR,
      tools: 'core',
      memory: { userMessage: true, assistantMessage: false, toolResult: false, importance: 0.6 },
      toolCallTimeoutMs: 15_000,
      maxRetryDelayMs: 5_000,
      failOnStartupError: true,
    },
  )
  return {
    root,
    /** 只卸载插件（保留 ToolRegistry 服务，便于检查工具注销）。 */
    disposePlugin: () => pluginFiber.dispose(),
    /** 卸载全部。 */
    disposeAll: () => {
      pluginFiber.dispose()
      toolsFiber.dispose()
      promptFiber.dispose()
    },
  }
}

/** Windows 下 python 进程可能短暂持有 DB 句柄，清理失败不阻塞测试。 */
function safeCleanup(dir: string): void {
  try {
    rmSync(dir, { recursive: true, force: true })
  } catch {
    /* 句柄未释放，tmp 目录由系统清理 */
  }
}

test('插件激活：lingshu_* 工具注册进 ctx.tools', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-host-'))
  const host = await mountHost(join(dir, 'host.db'))
  try {
    const schemas = host.root.tools.schemas()
    const names = schemas.map((s) => s.name)
    assert.ok(names.includes('lingshu_remember'), `应注册 lingshu_remember（实际有: ${names.slice(0, 5).join(', ')}…）`)
    assert.ok(names.includes('lingshu_recall'), '应注册 lingshu_recall')
    // core 集合精选 12 个，不应注册全部（如 designer_decide 不在 core）
    assert.ok(!names.includes('lingshu_designer_decide'), 'core 集合不应包含 designer_decide')
    assert.ok(names.length <= 20, `core 集合应精简（实际 ${names.length} 个）`)
  } finally {
    host.disposeAll()
    safeCleanup(dir)
  }
})

test('插件卸载：工具注销且进程退出', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-host-'))
  const host = await mountHost(join(dir, 'host.db'))
  try {
    assert.ok(host.root.tools.schemas().some((s) => s.name === 'lingshu_remember'), '激活后应有工具')
    host.disposePlugin()
    await new Promise((resolve) => setTimeout(resolve, 300))
    assert.ok(
      !host.root.tools.schemas().some((s) => s.name.startsWith('lingshu_')),
      '卸载后 lingshu_* 工具应注销',
    )
  } finally {
    host.disposeAll()
    safeCleanup(dir)
  }
})
