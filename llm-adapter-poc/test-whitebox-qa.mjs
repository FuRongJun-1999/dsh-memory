// test-whitebox-qa.mjs —— 走灵枢途径向白箱提问（验证白箱引擎本身能否正常回答）
// 用真实桥调 wisdom_chat，检查回答是否自然（非卡片格式）
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

const questions = [
  '你好，请介绍一下你自己',
  '今天天气怎么样？',
  '什么是 TypeScript？',
  '地球是圆的吗？',
  '你能帮我写一段 Python 代码吗？',
]

for (const q of questions) {
  console.log(`\n【提问】${q}`)
  try {
    const r = await bridge.callTool('wisdom_chat', { message: q, session_id: 'qa-test' })
    const raw = (r?.content ?? []).map((c) => c.text ?? '').join('\n')
    let reply = raw, route = '?'
    try {
      const p = JSON.parse(raw)
      reply = p.reply ?? raw
      route = p.route ?? '?'
    } catch {}
    console.log(`route=${route} | 回答(${reply.length}字): ${reply.slice(0, 180)}`)
  } catch (e) { console.log('异常:', String(e)) }
}

bridge.dispose()
console.log('\n== 完成 ==')
