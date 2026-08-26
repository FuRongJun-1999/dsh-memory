// diag-wisdom.mjs —— 诊断 wisdom_chat 返回（为什么 DSH 里回答重复）
import { LingshuBridge } from '../lib/bridge.js'

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
const ready = await bridge.waitReady()
console.log('握手:', ready)
if (!ready) process.exit(1)

// 测试用例：模拟 DSH 会发的内容（含 system + 多轮）
const cases = [
  { name: '简单提问', message: 'TypeScript 是什么？' },
  { name: '重复提问(同session)', message: 'TypeScript 是什么？', session: 'diag-test' },
  { name: '带上下文', message: '请继续解释 TypeScript 和 JavaScript 的区别', session: 'diag-test' },
]

for (const c of cases) {
  console.log(`\n=== ${c.name} ===`)
  console.log('输入:', JSON.stringify(c.message).slice(0, 80))
  try {
    const r = await bridge.callTool('wisdom_chat', {
      message: c.message,
      session_id: c.session ?? 'default',
    })
    const text = (r?.content ?? []).map((x) => x.text ?? '').join('\n')
    console.log('原始返回 (前 500):', text.slice(0, 500))
    // 尝试解析 JSON
    try {
      const parsed = JSON.parse(text)
      console.log('JSON 解析: reply =', JSON.stringify(parsed.reply).slice(0, 300))
      console.log('route =', parsed.route, '| hits =', parsed.hits?.length ?? 0, '| honest =', parsed.honest, '| chitchat =', parsed.chitchat)
    } catch { console.log('(非 JSON 纯文本)') }
  } catch (e) { console.log('调用异常:', String(e)) }
}

bridge.dispose()
console.log('\n== 完成 ==')
