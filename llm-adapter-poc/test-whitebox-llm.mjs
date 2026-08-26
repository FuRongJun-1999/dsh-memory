// whitebox-llm-adapter 单元测试（不依赖 DSH 环境，纯逻辑验证）
import {
  estimateTokens,
  countInputTokens,
  serializeMessages,
  wrapTextStream,
  WhiteboxLlmAdapter,
  PROVIDER,
} from './whitebox-llm-adapter.js'

let pass = 0, fail = 0
function check(name, ok, detail = '') {
  if (ok) pass++
  else fail++
  console.log(`[${ok ? '✓' : '✘'}] ${name}${detail ? ' — ' + detail : ''}`)
}

// ---- 1. token 估算 ----
const t1 = estimateTokens('你好世界 hello world')
check('CJK/ASCII 混合估算', t1 > 0 && Number.isInteger(t1), `tokens=${t1}`)
const t2 = estimateTokens('')
check('空文本 = 0', t2 === 0)

// ---- 2. 输入 token 汇总（system + messages） ----
const opts = {
  system: '你是白箱灵枢',
  messages: [
    { role: 'user', content: [{ type: 'text', text: '你好' }] },
    { role: 'assistant', content: [{ type: 'text', text: '你好，我是灵枢' }] },
    { role: 'user', content: [{ type: 'tool-result', toolCallId: 't1', content: [{ type: 'text', text: '结果' }] }] },
  ],
}
const inputTokens = countInputTokens(opts)
check('输入 token 汇总包含 system+全部消息', inputTokens > estimateTokens('你好'), `input=${inputTokens}`)

// ---- 3. 消息序列化 ----
const conv = serializeMessages(opts)
check('序列化含角色标记', conv.includes('[系统]') && conv.includes('[用户]') && conv.includes('[灵枢]'))
check('序列化忽略 tool-result 文本', !conv.includes('结果'), `conv=${conv.slice(0, 60)}`)

// ---- 4. 流式包装协议 ----
const chunks = []
for await (const c of wrapTextStream('回答内容', 100, 20, 80)) chunks.push(c)
const types = chunks.map((c) => c.type)
check('流顺序: block-start→text-delta→block-end→usage→finish',
  types.join(',') === 'block-start,text-delta,block-end,usage,finish', types.join(','))
check('usage 含 cacheReadTokens（缓存命中语义）',
  chunks[3].usage.cacheReadTokens === 80, JSON.stringify(chunks[3].usage))
check('finish reason=stop', chunks[4].reason === 'stop')

// ---- 5. 白箱 adapter：直答路径（mock bridge） ----
const mockBridge = {
  isReady: () => true,
  async callTool(name, args) {
    check('调用 wisdom_chat 而非外部 LLM', name === 'wisdom_chat', name)
    return { content: [{ type: 'text', text: '白箱直答：地球是圆的' }] }
  },
}
const adapter = new WhiteboxLlmAdapter({ bridge: mockBridge })
const streamOpts = {
  provider: PROVIDER,
  model: 'whitebox-v1',
  system: 'sys',
  messages: [{ role: 'user', content: [{ type: 'text', text: '地球是什么形状' }] }],
}
const outChunks = []
for await (const c of adapter.stream(streamOpts)) outChunks.push(c)
const outText = outChunks.filter((c) => c.type === 'text-delta').map((c) => c.text).join('')
check('白箱直答文本输出', outText.includes('白箱直答'), outText)
const usageChunk = outChunks.find((c) => c.type === 'usage')
check('直答 = 全缓存命中（cacheRead=input）',
  usageChunk.usage.cacheReadTokens === usageChunk.usage.inputTokens,
  JSON.stringify(usageChunk.usage))

// ---- 6. 降级路径：白箱 route=llm → fallback ----
const llmBridge = {
  isReady: () => true,
  async callTool(name, args) {
    return { content: [{ type: 'text', text: JSON.stringify({ route: 'llm', reply: '' }) }] }
  },
}
const fallbackCalled = []
const fallback = {
  async *stream(o) {
    fallbackCalled.push(o.provider)
    yield { type: 'text-delta', index: 0, text: '降级回复' }
    yield { type: 'finish', reason: 'stop' }
  },
}
const adapter2 = new WhiteboxLlmAdapter({ bridge: llmBridge, fallback })
const out2 = []
for await (const c of adapter2.stream(streamOpts)) out2.push(c)
check('白箱 route=llm → 降级 LLM', fallbackCalled.length === 1, `fallback=${fallbackCalled.join(',')}`)

// ---- 7. 无桥无降级 → 诚实声明 ----
const adapter3 = new WhiteboxLlmAdapter({})
const out3 = []
for await (const c of adapter3.stream(streamOpts)) out3.push(c)
const honest = out3.filter((c) => c.type === 'text-delta').map((c) => c.text).join('')
check('无降级时诚实声明（不编造）', honest.includes('诚实声明'), honest.slice(0, 40))

console.log(`\n== 结果: ${pass} 通过 / ${fail} 失败 ==`)
process.exit(fail ? 1 : 0)
