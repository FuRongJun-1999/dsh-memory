// rpc-probe.mjs —— 通过 DSH WebSocket RPC 查询已注册的 LLM providers
// 连接 http://127.0.0.1:3080/rpc，探测 llm 服务的 provider 列表
const WS_URL = 'ws://127.0.0.1:3080/rpc'

// 用 Node 原生 WebSocket（Node 22+ 内置）
const ws = new WebSocket(WS_URL)
const timeout = setTimeout(() => { console.error('超时'); process.exit(1) }, 15000)

let msgId = 0
const pending = new Map()

function send(channel, method, payload = {}) {
  const id = String(++msgId)
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    ws.send(JSON.stringify({ id, channel, method, payload }))
  })
}

ws.onopen = async () => {
  console.log('已连接 /rpc')
  try {
    // 尝试多个候选调用（不同 RPC 风格）
    const candidates = [
      ['llm', 'listProviders', {}],
      ['dsh-llm', 'listProviders', {}],
      ['llm', 'providers', {}],
      ['llm', 'listModels', { provider: 'lingshu-whitebox' }],
    ]
    for (const [ch, method, payload] of candidates) {
      try {
        const r = await send(ch, method, payload)
        console.log(`\n✅ ${ch}.${method} →`, JSON.stringify(r).slice(0, 800))
      } catch (e) {
        console.log(`✘ ${ch}.${method} → ${String(e)}`)
      }
    }
  } catch (e) { console.error('探测失败:', e) }
  ws.close()
  clearTimeout(timeout)
  process.exit(0)
}

ws.onmessage = (ev) => {
  let data
  try { data = JSON.parse(ev.data) } catch { return }
  if (data.id && pending.has(data.id)) {
    const { resolve, reject } = pending.get(data.id)
    pending.delete(data.id)
    if (data.error) reject(new Error(JSON.stringify(data.error)))
    else resolve(data.result ?? data)
  }
}

ws.onerror = (e) => { console.error('WS 错误:', e.message || e); clearTimeout(timeout); process.exit(1) }
