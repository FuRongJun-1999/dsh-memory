/**
 * WhiteboxLlmAdapter — POC：把灵枢白箱引擎注册为 DSH 的 LLM 服务商。
 *
 * 设计哲学：白箱本身就是 LLM 模型（对外完全对齐 dsh-llm 协议），内部白箱化。
 *  - provider: 'lingshu-whitebox'
 *  - stream(): 调灵枢 wisdom_chat/think（白箱 CCG 条件路由/组合生成/自校验）
 *  - token 计数：输入/输出/缓存命中（直答命中 = 全部 cacheRead，零推理成本）
 *  - 降级：白箱无把握（route=llm / error）→ 转调外部 LLM（占位，后续接 deepseek）
 *
 * 结构仿 dsh-llm-deepseek（官方 adapter 模板）。
 */

// ---- token 估算（确定性启发式：白箱侧同样按字符/4 估算，与 DSH 计量一致）----
/** 粗略 token 数：CJK 按 1 token/字符 的 0.6 系数，其余按 /4。 */
export function estimateTokens(text) {
  if (!text) return 0
  let cjk = 0, other = 0
  for (const ch of text) {
    const code = ch.codePointAt(0)
    if ((code >= 0x4e00 && code <= 0x9fff) || (code >= 0x3040 && code <= 0x30ff)) cjk++
    else other++
  }
  return Math.ceil(cjk * 0.6 + other / 4)
}

/** 从 GenerateOptions 汇总输入 token（system + messages 全部文本）。 */
export function countInputTokens(options) {
  let total = 0
  if (options.system) total += estimateTokens(options.system)
  for (const msg of options.messages ?? []) {
    for (const block of msg.content ?? []) {
      if (typeof block?.text === 'string') total += estimateTokens(block.text)
      if (typeof block?.arguments === 'string') total += estimateTokens(block.arguments)
    }
  }
  return total
}

// ---- 消息→白箱 prompt 序列化（对齐 GenerateOptions.messages）----
/** 把 DSH 会话消息折叠成白箱可读的对话文本。 */
export function serializeMessages(options) {
  const parts = []
  if (options.system) parts.push(`[系统] ${options.system}`)
  for (const msg of options.messages ?? []) {
    const text = (msg.content ?? [])
      .filter((b) => b?.type === 'text' && typeof b.text === 'string')
      .map((b) => b.text)
      .join('')
    if (!text) continue
    const role = msg.role === 'assistant' ? '灵枢' : msg.role === 'user' ? '用户' : msg.role
    parts.push(`[${role}] ${text}`)
  }
  return parts.join('\n')
}

// ---- StreamChunk 流式包装（block-start → text-delta → block-end → usage → finish）----
/** 把一段完整文本包装成协议流（确定性整段生成 → 单次流）。 */
export async function* wrapTextStream(text, inputTokens, outputTokens, cacheReadTokens) {
  const index = 0
  yield { type: 'block-start', index, blockType: 'text' }
  // 协议允许一次 text-delta 携带全文（无强制分片要求）
  yield { type: 'text-delta', index, text }
  yield {
    type: 'block-end',
    index,
    block: { type: 'text', text },
  }
  yield {
    type: 'usage',
    usage: {
      inputTokens,
      outputTokens,
      ...(cacheReadTokens > 0 ? { cacheReadTokens } : {}),
    },
  }
  yield { type: 'finish', reason: 'stop' }
}

// ---- 白箱 adapter 主类 ----
export class WhiteboxLlmAdapter {
  /**
   * @param {object} deps
   * @param {import('../src/bridge.ts').LingshuBridge} deps.bridge 灵枢桥
   * @param {object} [deps.fallback] 降级 LLM 调用器（占位）
   */
  constructor({ bridge, fallback } = {}) {
    this.bridge = bridge
    this.fallback = fallback
  }

  providerInfo(provider) {
    return { id: provider, name: '白箱灵枢 (lingshu-whitebox)' }
  }

  providerRetryPolicy() {
    return undefined // 用默认重试策略
  }

  async listModels() {
    return [
      { provider: 'lingshu-whitebox', id: 'whitebox-v1', name: '白箱引擎 v1 (CCG 条件路由)' },
      { provider: 'lingshu-whitebox', id: 'whitebox-wisdom', name: '白箱智慧之书' },
    ]
  }

  async resolveModel(provider, model) {
    return { provider, id: model, name: model }
  }

  /**
   * 核心：一次模型调用。白箱优先，无把握降级。
   * @param {import('@deepseek-ai/dsh-llm').GenerateOptions} options
   */
  async *stream(options) {
    const inputTokens = countInputTokens(options)
    const conversation = serializeMessages(options)
    const lastUserText = [...(options.messages ?? [])]
      .reverse()
      .flatMap((m) => m.content ?? [])
      .filter((b) => b?.type === 'text')
      .map((b) => b.text)
      .join('')
      .slice(-2000)

    // ---- 白箱主路径：调灵枢 wisdom_chat（CCG 条件路由 + 组合生成 + 自校验）----
    let whitebox = null
    if (this.bridge?.isReady?.()) {
      try {
        const r = await this.bridge.callTool('wisdom_chat', {
          message: lastUserText || conversation.slice(-4000),
          session_id: options.sessionId ?? 'default',
        }, options.signal)
        const raw = (r?.content ?? []).map((c) => c.text ?? '').join('\n')
        // 白箱返回结构：{"reply": "...", "route": "self|llm", "hits": [...], "honest": bool}
        let text = raw
        let route = 'self'
        try {
          const parsed = JSON.parse(raw)
          if (parsed.route) route = parsed.route
          if (typeof parsed.reply === 'string') text = parsed.reply
          else if (parsed.reply !== undefined) text = JSON.stringify(parsed.reply)
        } catch { /* 非 JSON = 纯文本回复 */ }
        if (route !== 'llm' && text && text.trim()) {
          whitebox = { text: text.trim(), route }
        }
      } catch (err) {
        // 白箱异常不阻塞——记日志后走降级
        console.warn('[whitebox-llm] 白箱调用失败，降级:', String(err))
      }
    }

    if (whitebox) {
      const outputTokens = estimateTokens(whitebox.text)
      // 白箱直答 = 全缓存命中（条件路由固化命中，零推理成本）
      const cacheReadTokens = inputTokens
      yield* wrapTextStream(whitebox.text, inputTokens, outputTokens, cacheReadTokens)
      return
    }

    // ---- 降级路径：白箱无把握 / 桥未就绪 → 外部 LLM ----
    if (this.fallback) {
      console.warn('[whitebox-llm] 白箱未命中，转降级 LLM')
      yield* this.fallback.stream(options)
      return
    }
    // 无降级可用：诚实声明（盲区 28：未来承诺不可检验——不假装回答）
    const honest = '（白箱引擎未命中且降级 LLM 未配置——按白箱纪律，我诚实声明不知道，不编造答案。）'
    yield* wrapTextStream(honest, inputTokens, estimateTokens(honest), 0)
  }
}

// ---- 注册入口（仿 dsh-llm-deepseek 的 apply）----
export const name = 'llm-whitebox'
export const PROVIDER = 'lingshu-whitebox'

export function apply(ctx, config = {}) {
  const bridge = ctx.get('lingshu')?.bridge ?? config.bridge
  const adapter = new WhiteboxLlmAdapter({ bridge, fallback: config.fallback })
  ctx.llm.registerConfigurableProviders([{
    provider: PROVIDER,
    displayName: '白箱灵枢 (Whitebox)',
    settingsNs: 'llm-whitebox',
    settingsPath: [],
  }])
  const registration = ctx.llm.registerAdapter([PROVIDER], adapter)
  ctx.logger?.info?.('[whitebox-llm] 白箱 provider 已注册: %s', PROVIDER)
  return () => registration()
}
