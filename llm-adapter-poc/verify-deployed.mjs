// verify-deployed.mjs —— 验证部署到 profile 的 adapter 可加载且方法齐全
import { pathToFileURL } from 'node:url'

const pkg = 'C:/Users/FuRongJun/.dsh/profiles/web/node_modules/@furongjun1999/dsh-memory'
const m = await import(pathToFileURL(`${pkg}/lib/llm_adapter.js`).href)
console.log('✅ llm_adapter.js 加载成功')
console.log('导出:', Object.keys(m).join(', '))
console.log('WHITEBOX_PROVIDER:', m.WHITEBOX_PROVIDER)

const a = new m.WhiteboxLlmAdapter({})
console.log('providerInfo:', JSON.stringify(a.providerInfo('lingshu-whitebox')))
console.log('listModels:', JSON.stringify(await a.listModels()))
console.log('resolveModel:', JSON.stringify(await a.resolveModel('lingshu-whitebox', 'whitebox-v1')))

const chunks = []
for await (const c of a.stream({ provider: 'lingshu-whitebox', model: 'whitebox-v1', messages: [] })) chunks.push(c.type)
console.log('stream chunks(无桥→诚实声明):', chunks.join(','))

// 验证 token 计数
console.log('estimateTokens(你好世界):', m.estimateTokens('你好世界'))
const opts = { system: 's', messages: [{ role: 'user', content: [{ type: 'text', text: 'hello' }] }] }
console.log('countInputTokens:', m.countInputTokens(opts))

console.log('\n✅ 全部验证通过')
