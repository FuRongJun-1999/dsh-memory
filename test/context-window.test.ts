/**
 * context-window.test.ts · 短期会话窗口（滑动窗口）守卫
 *
 * 机制（2026-10-06；使用者痛点：「会话上下文满后的记忆丢失」）：
 *   短期记忆 = **运行态事件窗口**（灵枢 `_recent.jsonl` 滚动窗口，`cg(op=recent)`）。
 *   写侧：session/event 的 user/assistant 原文（经既有 sanitize）→ `recentAdd`
 *        （`cg(op=recent, action=add)`）；
 *   注入侧：system-prompt/assemble 注入**独立第二块**「【本会话近期对话】」
 *        （`sessionRecall` 的 recent 段，块名 `lingshu:session-window`）——
 *        宿主压缩后 retained 置空、重新投影时，该块随既有块一起自然重现。
 *
 * 与被守卫的两轨边界（关键，勿混）：
 *   · 知识面轨（`userMessage` / `assistantMessage`）管「消息沉淀成记忆节点」；
 *   · 窗口轨（`contextWindow.enabled/turns`）管「消息进运行态窗口」——
 *     **独立开关、互不替代**：知识面关掉时窗口照常工作（本文件 W4 只关窗口轨）。
 *
 * 被守卫的不变量
 * --------------
 *   W1 写侧：user/assistant 原文进窗口（role / meta.session / tags 正确）、
 *      tool 事件不写、无会话标识 → 显式 unassigned（不编造宿主 id）；
 *   W2 双闸：子代理会话（H1 会话级）/ relay 消息（H1 消息级）/ 注入类 kind
 *      一律不写（与自动记忆同口径）；
 *   W3 注入侧：两块齐（既有块 + 独立第二块）、取数参数面（session=sid /
 *      recent_limit=turns / budget_tokens）、条数 = min(turns, 返回数)、
 *      单条截断 ≤120、总长 ≤800、裁剪保最新且输出正序；
 *   W4 开关：`contextWindow.enabled=false` → 写侧零调用、注入侧无第二块
 *      （既有块不受影响）；
 *   W5 fail-soft：`sessionRecall` 抛错 → assemble 不抛、无第二块、既有块照常；
 *      `recentAdd` 抛错/**缺席** → session/event 处理不抛（只 warn）；
 *   W6 每步 push：同会话连续两步两块逐字节相同（与既有 ⑤ 同型）。
 *
 * 隔离纪律：auditPath 指向系统临时目录（沿 session-attribution.test.ts）——
 * 本守卫的会话事件不得写真实 ~/.dsh。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installMemoryHooks, type MemoryHooksOptions } from '../src/hooks.ts'

interface Assembly {
  contexts: Array<{ name: string; text: string }>
  variables: Record<string, string>
}
type AssembleHandler = (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>
type SessionEventHandler = (session: unknown, event: unknown) => void

interface RecentAddCall {
  role: string
  text: string
  meta: Record<string, unknown>
  tags: string[]
}
interface SessionRecallCall {
  session: string
  recentLimit: number
  budgetTokens: number
}

/** 窗口条目（服务端 `recent` 段形态：`{role, text, t}`；列表序 = 新→旧）。 */
const winItem = (role: string, text: string, t = 1): Record<string, unknown> => ({ role, text, t })

/** 最小 MdcgClient 形态：实现 hooks 用到的全部方法并记录调用。
 *  `omitRecentAdd` 腿模拟「旧替身缺该方法」——窗口写必须静默降级，不得炸会话流。 */
function makeGraph(opts: {
  sessionRecallThrows?: boolean
  recentAddThrows?: boolean
  omitRecentAdd?: boolean
  recentItems?: Array<Record<string, unknown>>
} = {}) {
  const timelineCalls: Array<Record<string, unknown>> = []
  const recentAddCalls: RecentAddCall[] = []
  const sessionRecallCalls: SessionRecallCall[] = []
  const graph: Record<string, unknown> = {
    isReady: (): boolean => true,
    async timeline(limit?: number, extra: Record<string, unknown> = {}) {
      timelineCalls.push({ limit, extra })
      return {
        count: 1, limit: limit ?? 4,
        items: [{ id: 'n1', layer: 'contextual', start: 1, end: 2, preview: '会话记忆预览' }],
      }
    },
    async sessionRecall(session: string, recentLimit: number, budgetTokens: number) {
      sessionRecallCalls.push({ session, recentLimit, budgetTokens })
      if (opts.sessionRecallThrows) throw new Error('session recall 模拟失败')
      return {
        ok: true,
        recent: opts.recentItems
          ?? [winItem('user', '近窗口条目一'), winItem('assistant', '近窗口条目二')],
      }
    },
    async remember() { return { ok: true } },
    async read() { return { ok: true } },
    async recall() { return { ok: true } },
  }
  if (!opts.omitRecentAdd) {
    graph.recentAdd = async (
      role: string, text: string,
      meta: Record<string, unknown> = {}, tags: string[] = [],
    ) => {
      recentAddCalls.push({ role, text, meta, tags })
      if (opts.recentAddThrows) throw new Error('recent add 模拟失败')
      return { ok: true }
    }
  }
  return { graph, timelineCalls, recentAddCalls, sessionRecallCalls }
}

function makeHarness(graph: object, overrides: Partial<MemoryHooksOptions> = {}) {
  const assembleHandlers: AssembleHandler[] = []
  const sessionHandlers: SessionEventHandler[] = []
  const warns: string[] = []
  const ctx = {
    logger: { info: () => {}, warn: (m: unknown) => { warns.push(String(m)) } },
    on(ev: string, fn: unknown) {
      if (ev === 'system-prompt/assemble') assembleHandlers.push(fn as AssembleHandler)
      else if (ev === 'session/event') sessionHandlers.push(fn as SessionEventHandler)
    },
  }
  installMemoryHooks(ctx as never, graph as never, {
    userMessage: true, assistantMessage: true, toolResult: true,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4, desensitize: false,
    // 落盘审计指向临时目录：本守卫的会话事件**绝不得**写真实 ~/.dsh。
    auditPath: join(tmpdir(), 'dsh-hook-audit-context-window.json'),
    ...overrides,
  })
  const assemble = async (hostCtx: unknown): Promise<Assembly> => {
    assert.ok(assembleHandlers[0], '应注册 system-prompt/assemble 监听')
    const a: Assembly = { contexts: [], variables: {} }
    await assembleHandlers[0]!(a, hostCtx, async () => a)
    return a
  }
  const send = (session: unknown, event: unknown): void => {
    assert.ok(sessionHandlers[0], '应注册 session/event 监听')
    for (const h of sessionHandlers) h(session, event)
  }
  return { assemble, send, warns }
}

const userEvent = (text: string, source: unknown = { kind: 'user' }) => ({
  type: 'user/message',
  data: { source, content: [{ type: 'text', text }] },
})
const assistantEvent = (text: string) => ({
  type: 'assistant/message',
  data: { message: { content: [{ type: 'text', text }] } },
})
const toolEvent = (text: string) => ({
  type: 'tool/result',
  data: { message: { content: [{ type: 'text', text }] } },
})

/** 取「不可信记忆边界」包裹内的载荷（renderUntrustedMemoryBlock 的固定形态：
 *  NOTICE → 开界 → 载荷 → 闭界）。用于对**载荷**（而非整块包装文本）做限幅断言。 */
function payloadOf(blockText: string): string {
  const open = '<untrusted-memory>\n'
  const i = blockText.indexOf(open)
  assert.ok(i >= 0, '注入块须含开界标记')
  const j = blockText.lastIndexOf('</untrusted-memory>')
  assert.ok(j > i, '注入块须含闭界标记')
  return blockText.slice(i + open.length, j - 1)
}

/** 取第二块的窗口行（首行为固定标题，其余为 `[role] 预览`）。 */
function windowRows(blockText: string): string[] {
  const payload = payloadOf(blockText)
  assert.ok(payload.startsWith('【本会话近期对话】'), '第二块须以固定标题开头')
  return payload.split('\n').slice(1).filter(Boolean)
}

const last = <T,>(arr: T[]): T => arr[arr.length - 1]!

// ---------------------------------------------------------------- W1 写侧

test('W1 写侧：user/assistant 原文进窗口（role/meta.session/tags），tool 不进', async () => {
  const { graph, recentAddCalls } = makeGraph()
  const { send } = makeHarness(graph)

  send({ id: 'sess_W' }, userEvent('我喜欢猫'))
  send({ id: 'sess_W' }, assistantEvent('好的，记住了'))
  send({ id: 'sess_W' }, toolEvent('工具结果：检索到 3 条'))
  await Promise.resolve()

  assert.equal(recentAddCalls.length, 2, 'user/assistant 各写一次；tool 事件不写窗口')
  assert.equal(recentAddCalls[0]!.role, 'user')
  assert.equal(recentAddCalls[0]!.text, '我喜欢猫', 'text = 原文（经既有 sanitize）')
  assert.equal(recentAddCalls[0]!.meta['session'], 'sess_W', 'meta.session = 当前会话（归因）')
  assert.deepEqual(recentAddCalls[0]!.tags, ['dsh', 'recent-window'])
  assert.equal(recentAddCalls[1]!.role, 'assistant')
  assert.equal(recentAddCalls[1]!.text, '好的，记住了')
  assert.equal(recentAddCalls[1]!.meta['session'], 'sess_W')

  // 无会话标识 → 沿既有 unassigned 占位纪律（不编造宿主 id、不落进程随机 sess_*）
  send({}, userEvent('没有会话标识的消息'))
  await Promise.resolve()
  assert.equal(recentAddCalls[2]!.meta['session'], 'unassigned')
})

// ---------------------------------------------------------------- W2 双闸

test('W2 双闸：子代理会话 / relay / 注入类 kind 一律不写窗口（H1 同口径）', async () => {
  const { graph, recentAddCalls } = makeGraph()
  const { send } = makeHarness(graph)

  send({ id: 'sess_sub', header: { origin: 'subagent' } }, userEvent('委派指令：帮我改这个文件'))
  send({ id: 'sess_A' }, userEvent('另一个 agent 的委派指令', { kind: 'user', form: 'relay' }))
  send({ id: 'sess_A' }, userEvent('插件注入的上下文', { kind: 'plugin', plugin: 'p', form: 'notice' }))
  await Promise.resolve()

  assert.equal(recentAddCalls.length, 0,
    '子代理会话（H1 会话级）/ relay（H1 消息级）/ 非 user kind 均不得进窗口')
})

// ---------------------------------------------------------------- W3 注入侧

test('W3 注入侧：两块齐 + 取数参数面 + 条数/单条截断', async () => {
  // 12 条（> 缺省 turns=10）；服务端序新→旧，第 1 条（最新）故意超长。
  const items = [
    winItem('assistant', '长'.repeat(300)),
    ...Array.from({ length: 11 }, (_, i) => winItem(i % 2 ? 'assistant' : 'user', `第${i + 2}条窗口内容`)),
  ]
  const { graph, sessionRecallCalls } = makeGraph({ recentItems: items })
  const { assemble } = makeHarness(graph)

  const a = await assemble({ agent: { session: { id: 'sess_A' } } })

  assert.equal(a.contexts.length, 2, '两块齐：既有块 + lingshu:session-window')
  assert.equal(a.contexts[0]!.name, 'lingshu:auto-recall', '第一块仍是既有块（一字未动）')
  assert.equal(a.contexts[1]!.name, 'lingshu:session-window', '第二块块名独立（不与既有块混）')
  assert.ok(a.contexts[1]!.text.includes('【本会话近期对话】'))

  // 取数参数面（兼容性核心）：session=sid、recent_limit=缺省 turns=10、budget_tokens=600
  assert.equal(sessionRecallCalls.length, 1)
  assert.deepEqual(sessionRecallCalls[0],
    { session: 'sess_A', recentLimit: 10, budgetTokens: 600 })

  const rows = windowRows(a.contexts[1]!.text)
  assert.equal(rows.length, 10, '条数 = min(turns=10, 返回数 12) = 10')
  for (const row of rows) {
    assert.match(row, /^\[(user|assistant)\] /, `行格式须为 [role] 预览：${row.slice(0, 40)}`)
  }
  // 单条截断：300 字 → 120 字 + 省略号
  const newest = last(rows)
  assert.ok(newest.startsWith('[assistant] 长'), '最新条目仍在（正序输出 → 末行）')
  const body = newest.slice('[assistant] '.length)
  assert.ok(body.length <= 121, '单条 ≤120 字（+省略号）')
  assert.ok(body.endsWith('…'), '超长条目被截断（带省略号）')
  // 总长 ≤800
  assert.ok(rows.join('\n').length <= 800, '窗口载荷总长 ≤800')
})

test('W3b 限幅保最新 + turns 透传：放不下的旧条目整条不放入、最新必须保留', async () => {
  // 10 条，每条 200 字（截断后 120+…）——总长必然超过 800，触发裁剪。
  const items = Array.from({ length: 10 }, (_, i) =>
    winItem(i % 2 ? 'assistant' : 'user', `第${i + 1}条：` + '内'.repeat(200)))
  const { graph, sessionRecallCalls } = makeGraph({ recentItems: items })
  const { assemble } = makeHarness(graph, { contextWindow: { enabled: true, turns: 4 } })

  const a = await assemble({ agent: { session: { id: 'sess_A' } } })
  assert.deepEqual(sessionRecallCalls[0],
    { session: 'sess_A', recentLimit: 4, budgetTokens: 600 }, 'turns 透传为 recent_limit')

  const rows = windowRows(a.contexts[1]!.text)
  assert.ok(rows.length <= 4, '条数 ≤ turns')
  assert.ok(rows.join('\n').length <= 800, '总长 ≤800')
  assert.ok(last(rows).includes('第1条：'), '最新条目保留且在最后（正序、保最新）')
})

test('W3c 裁剪保最新（>turns 且超长场景）：丢的是最旧条目', async () => {
  const items = Array.from({ length: 10 }, (_, i) =>
    winItem(i % 2 ? 'assistant' : 'user', `第${i + 1}条：` + '内'.repeat(200)))
  const { graph } = makeGraph({ recentItems: items })
  const { assemble } = makeHarness(graph)

  const a = await assemble({ agent: { session: { id: 'sess_A' } } })
  const rows = windowRows(a.contexts[1]!.text)
  assert.ok(rows.length < 10, '总长超限 → 条数被裁剪（保最新）')
  assert.ok(rows.join('\n').length <= 800, '总长 ≤800')
  assert.ok(last(rows).includes('第1条：'), '最新条目保留')
  assert.ok(!rows.some((r) => r.includes(`第${items.length}条：`)),
    '最旧条目被丢弃（裁剪保最新，而非保最旧）')
})

// ---------------------------------------------------------------- W4 开关

test('W4 开关：contextWindow.enabled=false → 写侧零调用、注入侧无第二块（既有块不受影响）', async () => {
  const { graph, recentAddCalls, sessionRecallCalls } = makeGraph()
  const { send, assemble } = makeHarness(graph,
    { contextWindow: { enabled: false, turns: 10 } })

  send({ id: 'sess_A' }, userEvent('用户消息'))
  send({ id: 'sess_A' }, assistantEvent('助手消息'))
  await Promise.resolve()
  assert.equal(recentAddCalls.length, 0, '写侧零调用')

  const a = await assemble({ agent: { session: { id: 'sess_A' } } })
  assert.equal(a.contexts.length, 1, '注入侧无第二块')
  assert.equal(a.contexts[0]!.name, 'lingshu:auto-recall', '既有块照常')
  assert.ok(a.contexts[0]!.text.includes('【灵枢最近记忆】'))
  assert.equal(sessionRecallCalls.length, 0, '窗口取数也不发起')
})

// ---------------------------------------------------------------- W5 fail-soft

test('W5a fail-soft：sessionRecall 抛错 → assemble 不抛、无第二块、既有块照常', async () => {
  const { graph } = makeGraph({ sessionRecallThrows: true })
  const { assemble } = makeHarness(graph)

  const a = await assemble({ agent: { session: { id: 'sess_A' } } })
  assert.equal(a.contexts.length, 1, '第二块不 push（取数失败静默）')
  assert.equal(a.contexts[0]!.name, 'lingshu:auto-recall', '既有块照常（不受第二块失败影响）')
})

test('W5b fail-soft：recentAdd 抛错 / 缺席 → session/event 处理不抛（只 warn）', async () => {
  // 腿一：方法存在但调用抛错
  const g1 = makeGraph({ recentAddThrows: true })
  const h1 = makeHarness(g1.graph)
  assert.doesNotThrow(() => h1.send({ id: 'sess_A' }, userEvent('用户消息')),
    '窗口写失败绝不冒泡进会话流')
  await new Promise((r) => setTimeout(r, 0))
  assert.ok(h1.warns.some((w) => w.includes('短期窗口写入失败')), '失败只记 warn')

  // 腿二：方法缺席（旧替身/降级实现）——同样只 warn，不得抛
  const g2 = makeGraph({ omitRecentAdd: true })
  const h2 = makeHarness(g2.graph)
  assert.doesNotThrow(() => h2.send({ id: 'sess_A' }, userEvent('用户消息')))
  await new Promise((r) => setTimeout(r, 0))
  assert.ok(h2.warns.some((w) => w.includes('短期窗口写入失败')), '缺席同样只 warn')
})

// ---------------------------------------------------------------- W6 每步 push

test('W6 每步 push：同会话连续两步两块逐字节相同（与既有 ⑤ 同型）', async () => {
  const { graph } = makeGraph()
  const { assemble } = makeHarness(graph)

  const first = await assemble({ agent: { session: { id: 'sess_A' } } })
  const second = await assemble({ agent: { session: { id: 'sess_A' } } })

  assert.equal(first.contexts.length, 2, '第一步两块齐')
  assert.equal(second.contexts.length, 2, '第二步仍须 push 两块（不许跳过 push）')
  assert.equal(first.contexts[0]!.text, second.contexts[0]!.text, '既有块逐字节相同')
  assert.equal(first.contexts[1]!.text, second.contexts[1]!.text,
    '窗口块逐字节相同 → 宿主不追加新快照')
})
