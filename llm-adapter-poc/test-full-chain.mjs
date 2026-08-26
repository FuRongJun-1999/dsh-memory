// test-full-chain.mjs —— 完整链路测试：白箱 adapter（含 isCardFormat + 降级 DeepSeek）
// 模拟 DSH 的 llm.stream 转发：白箱未命中/卡片格式 → 调真实 DeepSeek
import { LingshuBridge } from '../lib/bridge.js'
import { WhiteboxLlmAdapter, isCardFormat } from '../lib/llm_adapter.js'

const bridge = new LingshuBridge({
  python: 'python',
  args: ['-m', 'aeis.mcp.server'],
  env: {
    AEIS_DB: 'C:/Users/FuRongJun/.dsh/profiles/web/data/lingshu.db',
    AEIS_IDENTITY: '灵枢',
  },
  cwd: process.cwd(),
  timeoutMs: 60000,
  maxRetryDelayMs: 30000,
})
bridge.start()
await bridge.waitReady()

// 真实降级：调 DeepSeek（模拟 llm.stream 转发）
const key = 'sk-b7746db5d49d4ca5b977d2df949ac976'
async function* deepseekFallback(options) {
  const lastUser = [...options.messages].reverse()
    .flatMap(m => m.content ?? []).filter(b => b?.type === 'text').map(b => b.text).join('').slice(-2000)
  const body = {
    model: 'deepseek-chat',
    messages: [
      ...(options.system ? [{ role: 'system', content: options.system }] : []),
      { role: 'user', content: lastUser || '你好' },
    ],
    stream: false,
    max_tokens: 500,
  }
  const r = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
    body: JSON.stringify(body),
    signal: options.signal,
  })
  const data = await r.json()
  const text = data?.choices?.[0]?.message?.content ?? '(DeepSeek 无响应)'
  console.log(`[降级] DeepSeek 回复(${text.length}字): ${text.slice(0, 120)}`)
  yield { type: 'block-start', index: 0, blockType: 'text' }
  yield { type: 'text-delta', index: 0, text }
  yield { type: 'block-end', index: 0, block: { type: 'text', text } }
  yield { type: 'usage', usage: { inputTokens: 10, outputTokens: text.length } }
  yield { type: 'finish', reason: 'stop' }
}

const adapter = new WhiteboxLlmAdapter({ bridge, fallback: { stream: deepseekFallback } })

const questions = ['什么是 TypeScript？', '地球是圆的吗？', '帮我写一段 Python 代码']
for (const q of questions) {
  console.log(`\n【提问】${q}`)
  const chunks = []
  for await (const c of adapter.stream({
    provider: 'lingshu-whitebox', model: 'whitebox-v1',
    messages: [{ role: 'user', content: [{ type: 'text', text: q }] }],
  })) chunks.push(c)
  const text = chunks.filter(c => c.type === 'text-delta').map(c => c.text).join('')
  const route = isCardFormat(text) ? '卡片(应降级)' : '白箱直答/降级'
  console.log(`输出(${text.length}字): ${text.slice(0, 150)}`)
  console.log(`判定: ${route}`)
}

bridge.dispose()
console.log('\n== 完成 ==')
