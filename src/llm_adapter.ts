/**
 * llm_adapter.ts —— 白箱 LLM 服务商（WhiteboxLlmAdapter）
 *
 * 设计哲学：白箱本身就是 LLM 模型（对外完全对齐 dsh-llm 协议），内部白箱化。
 *  - provider: 'lingshu-whitebox'（设置页「模型」可见，可被 agent 默认选用）
 *  - stream(): 调灵枢 wisdom_chat（白箱 CCG 条件路由/组合生成/自校验）
 *  - token 计数：输入/输出/缓存命中（白箱直答 = 全部 cacheRead，零推理成本）
 *  - 降级：白箱无把握（route=llm / 桥未就绪）→ 可选 fallback（后续接 deepseek）
 *
 * 结构仿官方 @deepseek-ai/dsh-llm-deepseek adapter。
 */

import type { Context } from '@deepseek-ai/cordis'
import type { LingshuBridge } from './bridge.js'

// ---- dsh-llm 类型（运行时仅用结构；类型从包引入保持协议对齐）----
// 不 import 运行时符号，仅引用类型，避免强依赖 dsh-llm 未装时报错。
export interface LlmStreamChunk {
  type: 'block-start' | 'text-delta' | 'reasoning-delta' | 'tool-call-delta' | 'block-end' | 'usage' | 'finish'
  index?: number
  blockType?: string
  text?: string
  id?: string
  name?: string
  argumentsDelta?: string
  block?: { type: string; text?: string; [k: string]: unknown }
  usage?: { inputTokens: number; outputTokens: number; cacheReadTokens?: number; cacheWriteTokens?: number }
  reason?: string
  replayState?: unknown
}

export interface LlmGenerateOptions {
  provider: string
  model: string
  reasoningEffort?: string
  messages: Array<{ role: string; content?: Array<{ type?: string; text?: string; arguments?: string; [k: string]: unknown }> }>
  system?: string
  tools?: Array<{ name: string; description: string; parameters: Record<string, unknown> }>
  temperature?: number
  maxTokens?: number
  stop?: string[]
  signal?: AbortSignal
  sessionId?: string
  purpose?: 'compaction' | 'session-title'
}

// ---- token 估算（确定性启发式：CJK 0.6/字符，其余 /4）----
export function estimateTokens(text: string | undefined | null): number {
  if (!text) return 0
  let cjk = 0
  let other = 0
  for (const ch of text) {
    const code = ch.codePointAt(0)!
    if ((code >= 0x4e00 && code <= 0x9fff) || (code >= 0x3040 && code <= 0x30ff)) cjk++
    else other++
  }
  return Math.ceil(cjk * 0.6 + other / 4)
}

/** 从 GenerateOptions 汇总输入 token（system + messages 全部文本）。 */
export function countInputTokens(options: LlmGenerateOptions): number {
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

/** 把 DSH 会话消息折叠成白箱可读的对话文本。 */
export function serializeMessages(options: LlmGenerateOptions): string {
  const parts: string[] = []
  if (options.system) parts.push(`[系统] ${options.system}`)
  for (const msg of options.messages ?? []) {
    const text = (msg.content ?? [])
      .filter((b) => b?.type === 'text' && typeof b.text === 'string')
      .map((b) => b.text as string)
      .join('')
    if (!text) continue
    const role = msg.role === 'assistant' ? '灵枢' : msg.role === 'user' ? '用户' : msg.role
    parts.push(`[${role}] ${text}`)
  }
  return parts.join('\n')
}

/** 把一段完整文本包装成协议流（确定性整段生成 → 单次流）。 */
export async function* wrapTextStream(
  text: string,
  inputTokens: number,
  outputTokens: number,
  cacheReadTokens: number,
): AsyncIterable<LlmStreamChunk> {
  yield { type: 'block-start', index: 0, blockType: 'text' }
  yield { type: 'text-delta', index: 0, text }
  yield { type: 'block-end', index: 0, block: { type: 'text', text } }
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

/** 白箱 adapter 依赖注入。 */
export interface WhiteboxAdapterDeps {
  /** 灵枢桥（MCP stdio）——白箱引擎通道。 */
  bridge?: LingshuBridge
  /** 降级 LLM 调用器（占位；后续接 dsh-llm-deepseek 复用）。 */
  fallback?: { stream(o: LlmGenerateOptions): AsyncIterable<LlmStreamChunk> }
}

/** 白箱 LLM adapter —— 注册为 DSH 的 provider。 */
export class WhiteboxLlmAdapter {
  private readonly bridge?: LingshuBridge
  private readonly fallback?: WhiteboxAdapterDeps['fallback']

  constructor(deps: WhiteboxAdapterDeps = {}) {
    this.bridge = deps.bridge
    this.fallback = deps.fallback
  }

  providerInfo(provider: string): { id: string; name: string } {
    return { id: provider, name: '白箱灵枢 (lingshu-whitebox)' }
  }

  providerRetryPolicy(): undefined {
    return undefined
  }

  async listModels(): Promise<Array<{ provider: string; id: string; name: string }>> {
    return [
      { provider: 'lingshu-whitebox', id: 'whitebox-v1', name: '白箱引擎 v1 (CCG 条件路由)' },
      { provider: 'lingshu-whitebox', id: 'whitebox-wisdom', name: '白箱智慧之书' },
    ]
  }

  async resolveModel(provider: string, model: string): Promise<{ provider: string; id: string; name: string }> {
    return { provider, id: model, name: model }
  }

  /**
   * 核心：一次模型调用。白箱优先，无把握降级。
   * @param options 完全装配的请求（必须 honor options.signal）
   */
  async *stream(options: LlmGenerateOptions): AsyncIterable<LlmStreamChunk> {
    const inputTokens = countInputTokens(options)
    const conversation = serializeMessages(options)
    // 取最后一条用户文本作为白箱输入（完整对话太长时截尾）
    const lastUserText = [...(options.messages ?? [])]
      .reverse()
      .flatMap((m) => m.content ?? [])
      .filter((b) => b?.type === 'text')
      .map((b) => b.text as string)
      .join('')
      .slice(-2000)

    // ---- 白箱主路径：调灵枢 wisdom_chat ----
    let whitebox: { text: string; route: string } | null = null
    if (this.bridge?.isReady?.()) {
      try {
        const r = await this.bridge.callTool('wisdom_chat', {
          message: lastUserText || conversation.slice(-4000),
          session_id: (options.sessionId as string) ?? 'default',
        }, options.signal)
        const raw = (r?.content ?? []).map((c) => (c as { text?: string }).text ?? '').join('\n')
        // 白箱返回结构：{"reply": "...", "route": "self|llm", "hits": [...], "honest": bool}
        let text = raw
        let route = 'self'
        try {
          const parsed = JSON.parse(raw) as { route?: string; reply?: unknown }
          if (parsed.route) route = parsed.route
          if (typeof parsed.reply === 'string') text = parsed.reply
          else if (parsed.reply !== undefined) text = JSON.stringify(parsed.reply)
        }
        catch { /* 非 JSON = 纯文本回复 */ }
        if (route !== 'llm' && text && text.trim()) {
          whitebox = { text: text.trim(), route }
        }
      }
      catch (err) {
        // 白箱异常不阻塞——记日志后走降级
        console.warn('[whitebox-llm] 白箱调用失败，降级:', String(err))
      }
    }

    if (whitebox) {
      const outputTokens = estimateTokens(whitebox.text)
      // 白箱直答 = 全缓存命中（条件路由固化命中，零推理成本）
      yield* wrapTextStream(whitebox.text, inputTokens, outputTokens, inputTokens)
      return
    }

    // ---- 降级路径：白箱无把握 / 桥未就绪 ----
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

/** provider 路由名（设置页「模型」下拉可见）。 */
export const WHITEBOX_PROVIDER = 'lingshu-whitebox'

/**
 * 注册白箱 provider 到 DSH llm 服务（动态检测，不强依赖 llm 服务——
 * 最小 host 无 llm 时跳过，插件其余功能不受影响）。
 * @returns 注销函数；未注册返回 noop。
 */
export function installWhiteboxLlm(ctx: Context, bridge: LingshuBridge | undefined): () => void {
  // 动态检测 llm 服务（P1 模式：timer/webServer 同理）。
  // 注意：不能直接读 ctx.llm——Cordis 未声明 inject 的属性访问会抛
  // "cannot get property without inject"；ctx.get('llm') 安全返回 undefined。
  const llm = ctx.get('llm') as
    | { registerAdapter?: (p: string[], a: unknown) => { replace?: (p: string[]) => void }; registerConfigurableProviders?: (e: unknown[]) => void }
    | undefined
  if (!llm?.registerAdapter) {
    ctx.logger?.info?.('dsh-memory: llm 服务不可用，跳过白箱 provider 注册（最小 host）')
    return () => {}
  }

  const adapter = new WhiteboxLlmAdapter({ bridge })
  try {
    llm.registerConfigurableProviders?.([{
      provider: WHITEBOX_PROVIDER,
      displayName: '白箱灵枢 (Whitebox)',
      settingsNs: 'llm-whitebox',
      settingsPath: [],
    }])
    const registration = llm.registerAdapter([WHITEBOX_PROVIDER], adapter)
    ctx.logger?.info?.('dsh-memory: 白箱 LLM provider 已注册: %s', WHITEBOX_PROVIDER)
    return () => { try { registration?.replace?.([]) } catch { /* 忽略注销异常 */ } }
  }
  catch (err) {
    ctx.logger?.warn?.('dsh-memory: 白箱 provider 注册失败: %s', String(err))
    return () => {}
  }
}
