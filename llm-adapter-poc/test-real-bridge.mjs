// 真实桥连通测试：连电脑端灵枢（aeis 0.3.0 + 白箱 wisdom_chat）
// 验证：①桥握手 ②wisdom_chat 白箱返回结构 ③adapter 流式输出
import { LingshuBridge } from '../lib/bridge.js'
import { WhiteboxLlmAdapter, PROVIDER } from './whitebox-llm-adapter.js'

const bridge = new LingshuBridge({
  python: 'python',
  args: ['-m', 'aeis.mcp.server'],
  env: {
    AEIS_DB: 'C:/Users/FuRongJun/.dsh/lingshu.db',
    AEIS_IDENTITY: '灵枢',
  },
  cwd: process.cwd(),
  timeoutMs: 60000,
  maxRetryDelayMs: 30000,
})

console.log('桥启动...')
bridge.start()
const ready = await bridge.waitReady()
console.log('握手:', ready)
if (!ready) { console.error('握手失败'); process.exit(1) }

// 1) 直接调 wisdom_chat（看白箱返回结构）
console.log('\n=== wisdom_chat 直接调用 ===')
try {
  const r = await bridge.callTool('wisdom_chat', { message: '你好，请介绍一下你自己', session_id: 'poc-test' })
  const text = (r?.content ?? []).map((c) => c.text ?? '').join('\n')
  console.log('返回类型:', typeof text, '长度:', text.length)
  console.log('内容前 300 字:', text.slice(0, 300))
  console.log('\n完整 JSON:', JSON.stringify(r).slice(0, 800))
} catch (e) { console.log('wisdom_chat 异常:', String(e)) }

// 2) 通过 adapter 走完整流（白箱 provider 语义）
console.log('\n=== adapter.stream（白箱 provider 语义） ===')
const adapter = new WhiteboxLlmAdapter({ bridge })
const chunks = []
for await (const c of adapter.stream({
  provider: PROVIDER,
  model: 'whitebox-v1',
  system: '你是白箱灵枢，遵循智能论协议。',
  messages: [{ role: 'user', content: [{ type: 'text', text: '什么是条件空间？' }] }],
})) chunks.push(c)

const types = chunks.map((c) => c.type)
console.log('chunk 类型序列:', types.join(','))
const text = chunks.filter((c) => c.type === 'text-delta').map((c) => c.text).join('')
console.log('adapter 输出前 300 字:', text.slice(0, 300))
const usage = chunks.find((c) => c.type === 'usage')?.usage
console.log('usage:', JSON.stringify(usage))

bridge.dispose()
console.log('\n== 完成 ==')
