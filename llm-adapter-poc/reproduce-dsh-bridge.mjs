// reproduce-dsh-bridge.mjs —— 复现 DSH 环境下的灵枢桥启动（同参数）
// 目标：确认为什么 DSH 里灵枢进程启动后立即退出
import { LingshuBridge } from '../lib/bridge.js'

const bridge = new LingshuBridge({
  python: 'python',
  args: ['-m', 'aeis.mcp.server'],
  env: {
    AEIS_DB: 'C:/Users/FuRongJun/.dsh/profiles/web/data/lingshu.db',
    AEIS_IDENTITY: '灵枢',
    // 复制 DSH patch 的环境（关键差异点）
    AEIS_LIFECYCLE: '1',
    AEIS_LIFECYCLE_INTERVAL: '120',
    BOCHA_API_KEY: process.env.BOCHA_API_KEY ?? '',
    AEIS_DESIGNER_KEY: process.env.AEIS_DESIGNER_KEY ?? '',
    DEEPSEEK_API_KEY: process.env.DEEPSEEK_API_KEY ?? '',
  },
  // DSH 没有显式 cwd——用 DSH 可能的 cwd
  cwd: 'C:/Users/FuRongJun',
  timeoutMs: 60000,
  maxRetryDelayMs: 30000,
})

console.log('启动桥（DSH 同参数）...')
bridge.start()
const ready = await bridge.waitReady()
console.log('握手:', ready)
if (!ready) {
  console.error('❌ 握手失败——复现了 DSH 的问题')
  // 等 3 秒看进程状态
  await new Promise((r) => setTimeout(r, 3000))
  console.log('alive:', bridge.alive, 'readyState 见日志')
  bridge.dispose()
  process.exit(1)
}
console.log('✅ 握手成功——DSH 参数下桥正常（问题在别处）')
const tools = await bridge.listTools()
console.log('工具数:', tools.length)
bridge.dispose()
console.log('完成')
