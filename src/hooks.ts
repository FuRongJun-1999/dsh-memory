/**
 * 自动记忆钩子：把 DSH 的会话事件（经统一的 session/event 分发）沉淀进灵枢。
 *
 * 与 DSH 的 session-persistence 插件（保存会话日志）不同，这里是"语义沉淀"：
 * 用户消息写入灵枢知识层（带去重与重要性），agent 回复与工具结果可选开启。
 * 只记忆真实用户消息（source.kind === 'user'），过滤插件注入的噪音。
 */

import '@deepseek-ai/dsh-session'
import type { Context } from '@deepseek-ai/cordis'
import type { SessionEvent } from '@deepseek-ai/dsh-session'
import type { ContentBlock } from '@deepseek-ai/dsh-llm'
import type { LingshuBridge } from './bridge.js'

/** 自动记忆开关。 */
export interface MemoryHooksOptions {
  /** 用户消息 → remember（默认 true）。 */
  userMessage: boolean
  /** agent 回复 → remember（默认 false，防噪音）。 */
  assistantMessage: boolean
  /** 工具结果 → remember（默认 false，噪音大）。 */
  toolResult: boolean
  /** 写入记忆的重要性（0~1），默认 0.6。 */
  importance: number
}

/** 从 ContentBlock[] 提取纯文本。 */
function extractText(blocks: ContentBlock[]): string {
  const parts: string[] = []
  for (const block of blocks) {
    if (block && typeof block === 'object' && block.type === 'text' && typeof block.text === 'string') {
      parts.push(block.text)
    }
  }
  return parts.join('\n').trim()
}

/** 安装自动记忆钩子（effect 作用域内，随插件卸载自动移除）。 */
export function installMemoryHooks(ctx: Context, bridge: LingshuBridge, opts: MemoryHooksOptions): void {
  const memorize = (tool: string, args: Record<string, unknown>): void => {
    void bridge
      .callTool(tool, args)
      .catch((err: Error) => ctx.logger.warn(`dsh-memory: ${tool} 自动记忆失败: ${err.message}`))
  }

  ctx.on('session/event', (_session, event: SessionEvent) => {
    if (event.type === 'user/message' && opts.userMessage) {
      // 只记真实用户输入（kind='user'），跳过插件注入/系统上下文
      if (event.data.source?.kind !== 'user') return
      const text = extractText(event.data.content)
      if (!text) return
      memorize('remember', { content: text, importance: opts.importance, tags: ['dsh', 'user'] })
    } else if (event.type === 'assistant/message' && opts.assistantMessage) {
      const text = extractText(event.data.message.content)
      if (!text) return
      memorize('remember', { content: text, importance: opts.importance * 0.8, tags: ['dsh', 'assistant'] })
    } else if (event.type === 'tool/result' && opts.toolResult) {
      if (event.data.error) return
      const text = extractText(event.data.message.content)
      if (!text) return
      memorize('remember', { content: text, importance: opts.importance * 0.6, tags: ['dsh', 'tool'] })
    }
  })
}
