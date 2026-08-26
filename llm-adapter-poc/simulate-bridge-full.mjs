// simulate-bridge-full.mjs —— 完整模拟 bridge 时序，定位 python 退出点
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'

const python = 'C:/Users/FuRongJun/AppData/Local/Programs/Python/Python310/python.exe'
const proc = spawn(python, ['-m', 'aeis.mcp.server'], {
  env: {
    ...process.env,
    AEIS_DB: 'C:/Users/FuRongJun/.dsh/profiles/web/data/lingshu.db',
    AEIS_IDENTITY: '灵枢',
    AEIS_LIFECYCLE: '1',
    AEIS_LIFECYCLE_INTERVAL: '120',
  },
  cwd: 'C:/Users/FuRongJun',
  stdio: ['pipe', 'pipe', 'pipe'],
  windowsHide: true,
})

const rl = createInterface({ input: proc.stdout })
let step = 0

proc.stderr.on('data', (c) => console.error(`[stderr] ${c.toString().trim()}`))
proc.on('exit', (code, sig) => {
  console.log(`\n>>> python 退出 code=${code} signal=${sig}（在步骤 ${step} 后）`)
  process.exit(0)
})

// 步骤 1：立即写 initialize
step = 1
console.log('步骤1: 写 initialize')
proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 't', version: '0' } } }) + '\n')

rl.on('line', (line) => {
  const msg = JSON.parse(line)
  if (msg.id === 1) {
    step = 2
    console.log('步骤2: 收到 initialize 响应，写 initialized 通知')
    proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n')
    // 保持连接，观察 10 秒
    setTimeout(() => {
      step = 3
      console.log('步骤3: 10 秒观察期结束，python 仍存活 → 桥时序正常')
      proc.kill()
      process.exit(0)
    }, 10000)
  }
})

// 5 秒内没收到响应则报告
setTimeout(() => {
  if (step < 2) {
    console.log('>>> 5 秒未收到 initialize 响应（卡住或已退出）')
    if (proc.exitCode !== null) console.log('python 已退出')
  }
}, 5000)
