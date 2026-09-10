/**
 * 最小 Cordis host 集成测试：用 cordis 4 原生 Context 加载插件
 * （不依赖 DSH 全组件，隔离 v0.1 不稳定面），验证：
 * - 插件激活成功（工具注册进 ctx.tools）
 * - lingshu_ 前缀工具出现在 schemas 中（记忆面已基元化：cg / stg）
 * - 插件卸载后工具注销
 *
 * 三层拆分 S4 之后，工具面真源是本仓自带 md_cg（`python -m md_cg.mcp_server`），
 * 不再依赖外部 AEIS 仓。
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Context } from '@deepseek-ai/cordis'
import { ToolRuntime } from '@deepseek-ai/dsh-tools'
import { SystemPrompt } from '@deepseek-ai/dsh-system-prompt'
import * as plugin from '../src/index.js'

/** 本仓根目录：md_cg 随仓库自带，靠 PYTHONPATH 解析（无需 pip 安装）。 */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/** 构建一个装有插件的最小 host；返回清理函数。 */
async function mountHost(dataDir: string) {
  const root = new Context()
  const promptFiber = await root.plugin(SystemPrompt)
  const toolsFiber = await root.plugin(ToolRuntime)
  const pluginFiber = await root.plugin(
    {
      name: plugin.name,
      inject: plugin.inject,
      Config: plugin.Config,
      apply: plugin.apply,
    },
    {
      serverName: 'lingshu',
      dbPath: join(dataDir, 'legacy.db'),
      identity: 'dsh-host-test',
      python: 'python',
      moduleArgs: ['-m', 'md_cg.mcp_server'],
      env: {
        PYTHONPATH: REPO_ROOT,
        PYTHONIOENCODING: 'utf-8',
        MDCG_MCP_SURFACE: 'full',
        // 集成测试用 legacy 身份（recorder），省去签发令牌。
        MDCG_LEGACY_ENV_AUTH: '1',
        MDCG_ACTOR: 'dsh-host-test',
        MDCG_TENANT: 'default',
        MDCG_CLEARANCE: 'private',
      },
      cwd: REPO_ROOT,
      mdcg: {
        enabled: true,
        root: join(dataDir, 'mdcg'),
        actor: 'dsh-host-test',
        tenant: 'default',
        clearance: 'private',
      },
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

/** 等待工具注册（适配竞态补注册：灵枢进程就绪后 2s 轮询补注册）。 */
async function waitForTool(host: unknown, name: string, timeoutMs = 8000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const schemas = (host as { root: { tools: { schemas(): Array<{ name: string }> } } }).root.tools.schemas()
      if (schemas.some((s) => s.name === name)) return true
    } catch {
      /* 宿主未就绪 */
    }
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  return false
}

test('插件激活：lingshu_* 工具注册进 ctx.tools（core = cg/stg 两基元）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-host-'))
  const host = await mountHost(dir)
  try {
    const ready = await waitForTool(host, 'lingshu_cg')
    assert.ok(ready, '等待补注册后应有 lingshu_cg（竞态补注册 2s 轮询）')
    const schemas = host.root.tools.schemas()
    const names = schemas.map((s) => s.name)
    assert.ok(names.includes('lingshu_stg'), '应注册 lingshu_stg')
    assert.deepEqual(
      names.filter((n) => n.startsWith('lingshu_')).sort(),
      ['lingshu_cg', 'lingshu_stg'],
      `core 集合应只有 cg/stg 两基元（实际 ${names.length} 个）`,
    )
  } finally {
    host.disposeAll()
    safeCleanup(dir)
  }
})

test('插件卸载：工具注销且进程退出', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-host-'))
  const host = await mountHost(dir)
  try {
    const ready = await waitForTool(host, 'lingshu_cg')
    assert.ok(ready, '等待补注册后激活应有工具')
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
