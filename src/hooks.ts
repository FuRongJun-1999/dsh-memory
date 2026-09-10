/**
 * 自动记忆钩子：把 DSH 的会话事件（经统一的 session/event 分发）沉淀进灵枢。
 *
 * 记忆真源 = **md_cg 认知图（md 文档）**（2026-09-10 统一）：本钩子经
 * MdcgClient.remember() 调 MCP `mdcg_remember(gated=true)`（主动遗忘闸门：
 * ACCEPT 落盘 / MERGE 并入既有 = 去重强化 / DROP 低熵 / DEFER 待定），
 * 落层 contextual，role 取 user | assistant | tool-output —— 与 md_cg 对 DSH
 * 会话事件的约定一致（md_cg/sources.py 的 SESSION_LAYER / DSHSessionSource）。
 * ⚠️ 不用 `cg(op=write)`：那条路径先过 audit，未声明 content_kind 时永不落盘
 * （见 src/lib/mdcg_client.ts 文件头）。
 * 不再走 AEIS：AEIS 已降为能力库，不存记忆。
 *
 * ⚠️ 写入需凭据：md_cg fail-closed，无 MDCG_TOKEN / MDCG_LEGACY_ENV_AUTH=1
 * 时降级为只读 guest —— 本钩子的写入会失败（仅告警，不影响对话）。
 *
 * 与 DSH 的 session-persistence 插件（保存会话日志）不同，这里是"语义沉淀"：
 * 带去重（闸门 MERGE）与重要性，写入前脱敏；agent 回复与工具结果可选开启。
 * 只记忆真实用户消息（source.kind === 'user'），过滤插件注入的噪音。
 *
 * autoRecall：通过 system-prompt/assemble 事件（waterfall，异步允许）在每次
 * 模型请求组装 system prompt 时自动注入灵枢最近记忆
 * （`stg(op=timeline)`，最近记忆节点时间线），让记忆"自动可用"而不只依赖
 * Agent 主动调用 recall/think 工具。失败静默（不影响请求）。
 */

import '@deepseek-ai/dsh-session'
import '@deepseek-ai/dsh-system-prompt'
import type { Context } from '@deepseek-ai/cordis'
import type { SessionEvent } from '@deepseek-ai/dsh-session'
import type { ContentBlock } from '@deepseek-ai/dsh-llm'
import type { MdcgClient } from './lib/mdcg_client.js'

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
  /** 自动召回注入：模型请求前自动注入灵枢最近记忆（默认 true，失败静默）。 */
  autoRecall: boolean
  /** 自动召回条数（默认 4）。 */
  autoRecallLimit: number
  /** 自动记忆脱敏：写入前过滤敏感信息（密钥/密码/令牌/身份证/手机号，默认 true）。 */
  desensitize: boolean
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

/**
 * 敏感信息模式（GPT 审查·自动记忆脱敏）：写入认知图前过滤凭据/个人标识。
 * 命中 → 替换为 [已过滤:类别]（保留对话主体）；过滤后只剩占位符/空白 → 整条跳过。
 * 纯内容过滤，不涉及身份认证——开源场景下的隐私保护。
 */
const SENSITIVE_PATTERNS: Array<{ re: RegExp; label: string }> = [
  { re: /sk-[A-Za-z0-9_-]{8,}/g, label: 'API密钥' },
  { re: /\b(?:api[_-]?key|apikey|access[_-]?token)\b\s*[:=]\s*[^\s,，。;；]+/gi, label: 'API密钥' },
  { re: /\b(?:password|passwd|pwd)\b\s*[:=]\s*[^\s,，。;；]+/gi, label: '密码' },
  { re: /Bearer\s+[A-Za-z0-9._~+/=-]{8,}/gi, label: '令牌' },
  // 中文密码：值限定非中文连续串（凭据特征），避免误伤「密码是重要的安全概念」
  { re: /密码\s*[:：是]\s*[A-Za-z0-9_@#$%^&*!.-]{4,}/g, label: '密码' },
  { re: /\b\d{17}[\dXx]\b/g, label: '身份证号' },
  { re: /\b1[3-9]\d{9}\b/g, label: '手机号' },
]

/** 脱敏：替换敏感片段；返回 null 表示整条都是敏感内容（应跳过写入）。 */
export function desensitize(text: string): string | null {
  let out = text
  for (const { re, label } of SENSITIVE_PATTERNS) {
    out = out.replace(re, `[已过滤:${label}]`)
  }
  // 过滤后只剩占位符/空白 → 纯凭据消息，不写（或全部被替换）
  const residue = out.replace(/\[已过滤:[^\]]+\]/g, '').trim()
  if (!residue) return null
  return out
}

/** 时间线载荷 → 注入文本。
 *  `stg(op=timeline)` 返回 {count, limit, items:[{id, layer, start, end, preview}]}。 */
function formatTimeline(payload: unknown): string {
  const items = (payload && typeof payload === 'object'
    && Array.isArray((payload as { items?: unknown }).items))
    ? (payload as { items: Array<Record<string, unknown>> }).items
    : []
  return items
    .map((it) => {
      const preview = String(it['preview'] ?? '').replace(/\s+/g, ' ').trim()
      if (!preview) return ''
      const layer = it['layer'] ? `[${String(it['layer'])}] ` : ''
      return `- ${layer}${preview}`
    })
    .filter(Boolean)
    .join('\n')
}

/** 安装自动记忆钩子（effect 作用域内，随插件卸载自动移除）。
 *
 *  mdcg 为 null（config.mdcg.enabled=false）时自动记忆整体停用：记忆真源是
 *  认知图，没有它就没有可写的去处——**不会退回 AEIS**（AEIS 已不存记忆）。 */
export function installMemoryHooks(ctx: Context, mdcg: MdcgClient | null, opts: MemoryHooksOptions): void {
  if (!mdcg) {
    ctx.logger.warn('dsh-memory: 认知图未启用（config.mdcg.enabled=false），自动记忆已停用')
    return
  }
  const graph = mdcg

  /** 记忆沉淀（fire-and-forget）。认知图未就绪则跳过并告警（不退回 AEIS）。 */
  const memorize = (label: string, run: (g: MdcgClient) => Promise<unknown>): void => {
    if (!graph.isReady()) {
      ctx.logger.warn(`dsh-memory: 认知图未就绪，跳过自动记忆（${label}）`)
      return
    }
    void run(graph).catch((err: Error) =>
      ctx.logger.warn(`dsh-memory: 自动记忆 ${label} 失败: ${err.message}`))
  }

  // P1 完善（GPT 审查·自动记忆脱敏）：写入前过滤敏感信息（默认开启）。
  // 命中敏感模式 → 替换为 [已过滤:类别]；纯凭据消息 → 跳过写入（不落库）。
  const sanitize = (text: string): string | null => {
    if (!opts.desensitize) return text
    return desensitize(text)
  }

  // P1 完善（自动 recall 注入）：每次模型请求组装 system prompt 时，注入灵枢最近记忆。
  // 用 system-prompt/assemble 事件（waterfall）而非 llm/stream——后者请求 deep-frozen 不可改写。
  if (opts.autoRecall) {
    const recallLimit = Math.max(1, Math.min(10, opts.autoRecallLimit || 4))
    ctx.on('system-prompt/assemble', async (assembly, _ctx, next) => {
      try {
        // 异步取最近记忆节点（失败静默——不阻塞模型请求）
        if (graph.isReady()) {
          const text = formatTimeline(await graph.timeline(recallLimit))
          if (text) {
            assembly.contexts.push({
              name: 'lingshu:auto-recall',
              text: `【灵枢最近记忆】\n${text.slice(0, 600)}`,
            })
          }
        }
      }
      catch { /* 静默：召回失败不影响请求 */ }
      return next()
    })
  }

  ctx.on('session/event', (_session, event: SessionEvent) => {
    if (event.type === 'user/message' && opts.userMessage) {
      // 只记真实用户输入（kind='user'），跳过插件注入/系统上下文
      if (event.data.source?.kind !== 'user') {
        // T4 诊断（2026-08-30）：dsh 端对话零写入排查——记录被滤事件的实际
        // source.kind（若 dsh 新版改了 kind 值，此处日志可定位）
        ctx.logger.info(`dsh-memory: user/message 事件被滤（source.kind=${event.data.source?.kind ?? 'undefined'}）`)
        return
      }
      const text = extractText(event.data.content)
      if (!text) return
      const safe = sanitize(text)  // 脱敏：纯凭据消息 → null → 跳过写入
      if (safe === null) return
      memorize('user', (g) => g.remember(safe, {
        role: 'user', tags: ['dsh', 'user'], importance: opts.importance,
      }))
      // T4：用用户消息做一次语义召回——md_cg 的读取会记 access log（复用观测，
      // 供 importance / scrub 陈旧度使用），同时预热检索路径。
      // （AEIS 侧的 `_note_reuse` 在 md_cg 中不存在，其等价物就是这次记访问。）
      memorize('user-recall', (g) => g.recall(safe.slice(0, 200), 3))
    } else if (event.type === 'assistant/message' && opts.assistantMessage) {
      const text = extractText(event.data.message.content)
      if (!text) return
      const safe = sanitize(text)
      if (safe === null) return
      memorize('assistant', (g) => g.remember(safe, {
        role: 'assistant', tags: ['dsh', 'assistant'], importance: opts.importance * 0.8,
      }))
    } else if (event.type === 'tool/result' && opts.toolResult) {
      if (event.data.error) return
      const text = extractText(event.data.message.content)
      if (!text) return
      const safe = sanitize(text)
      if (safe === null) return
      memorize('tool', (g) => g.remember(safe, {
        role: 'tool-output', tags: ['dsh', 'tool'], importance: opts.importance * 0.6,
      }))
    }
  })
}
