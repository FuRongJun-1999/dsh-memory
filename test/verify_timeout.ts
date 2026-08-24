/**
 * verify_timeout.ts · P0 验证——桥接超时不再挂死（GPT 审查修复）
 * 场景：子进程收到 tools/call 但永不响应（slow_tool）→ 应在 timeoutMs 后 reject
 * 同时验证正常工具仍可调用（回归）。
 */
import { LingshuBridge } from '../src/bridge.ts'
import { join } from 'node:path'

const MOCK = join(process.cwd(), 'test', 'mock_mcp.py')

async function main(): Promise<void> {
  const bridge = new LingshuBridge({
    python: 'python',
    args: [MOCK],
    env: {},
    cwd: process.cwd(),
    timeoutMs: 300,
    maxRetryDelayMs: 2000,
  })
  bridge.start()
  const ready = await bridge.waitReady()
  console.log(`握手就绪: ${ready}`)
  if (!ready) {
    console.error('✘ 握手失败')
    process.exit(1)
  }

  // ① 正常工具应 resolve
  const t0 = Date.now()
  const normal = await bridge.callTool('normal_tool', {})
  const normalMs = Date.now() - t0
  console.log(`① 正常工具: resolve in ${normalMs}ms, content=${JSON.stringify(normal.content).slice(0, 40)}`)

  // ② slow 工具应在 ~300ms reject（修复前：永久 hung）
  const t1 = Date.now()
  let timedOut = false
  try {
    await bridge.callTool('slow_tool', {})
    console.log('✘ slow_tool 竟然 resolve（超时未生效）')
  } catch (err) {
    timedOut = true
    const ms = Date.now() - t1
    const inWindow = ms >= 250 && ms <= 1500
    console.log(`② slow_tool: reject in ${ms}ms: ${(err as Error).message.slice(0, 60)}`)
    console.log(`   超时窗口(250-1500ms): ${inWindow ? '✔' : '✘'}`)
  }

  // ③ 超时后桥仍可继续工作（重连/后续调用）
  const t2 = Date.now()
  const again = await bridge.callTool('normal_tool', {})
  console.log(`③ 超时后桥仍可用: resolve in ${Date.now() - t2}ms ✔`)

  bridge.dispose()
  const pass = ready && timedOut && again.content.length > 0
  console.log(`\nP0 验证: ${pass ? '✔ 通过（超时 reject + 桥不挂死）' : '✘ 失败'}`)
  process.exit(pass ? 0 : 1)
}

main().catch((err) => {
  console.error('验证脚本异常:', err)
  process.exit(1)
})
