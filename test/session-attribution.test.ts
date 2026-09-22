/**
 * session-attribution.test.ts · 会话归属（写入带身份）+ 会话视图（读取不串台）回归守卫
 *
 * 设计口径（PR #21）
 * ------------------
 *   记忆写入**必须带会话身份**（区分不同会话的记忆）；同时读取要能看遍所有会话做了什么
 *   （显式 `session="*"`）。二者分工：
 *     · 写侧：`session/event` 的 user/assistant/tool 三路 remember 都打上 `session` 归属；
 *     · 读侧 autoRecall：**只注入本会话**的记忆（防多会话串台），想读全部请显式
 *       `stg(op=timeline, session="*")`。
 *
 * 被守卫的不变量
 * --------------
 *   ① 写入带身份：三路 remember 的 extra.session 来自宿主会话标识（`id` / `sessionId`）；
 *   ② 不编造：宿主未给出标识 → 不塞 session 键，回落内核进程身份（退回旧行为）；
 *   ③ 读取隔离：autoRecall 的 timeline 只带本会话；
 *   ④ **取值每步稳定**：本块按 v0.4.8 契约每步都 push，session 取值若中途翻转会白付
 *      两份快照 → 优先取 ctx 上的会话，其次回落「最近一次 session/event 的会话」；
 *   ⑤ 会话隔离不破坏「每步照旧 push」：同会话连续两步注入块逐字节相同。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { installMemoryHooks, type MemoryHooksOptions } from '../src/hooks.ts'

interface Assembly {
  contexts: Array<{ name: string; text: string }>
  variables: Record<string, string>
}
type AssembleHandler = (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>
type SessionEventHandler = (session: unknown, event: unknown) => void

interface TimelineCall { limit?: number; extra: Record<string, unknown> }
interface RememberCall { content: string; extra: Record<string, unknown> }

/** 最小 MdcgClient 形态：只实现 hooks 用到的四个方法，并记录调用。 */
function makeGraph() {
  const timelineCalls: TimelineCall[] = []
  const rememberCalls: RememberCall[] = []
  const graph = {
    isReady: (): boolean => true,
    async timeline(limit?: number, extra: Record<string, unknown> = {}) {
      timelineCalls.push({ limit, extra })
      return {
        count: 1, limit: limit ?? 4,
        items: [{ id: 'n1', layer: 'contextual', start: 1, end: 2, preview: '会话记忆预览' }],
      }
    },
    async remember(content: string, extra: Record<string, unknown> = {}) {
      rememberCalls.push({ content, extra })
      return { ok: true }
    },
    async recall() { return { ok: true } },
  }
  return { graph, timelineCalls, rememberCalls }
}

function makeHarness(graph: object, overrides: Partial<MemoryHooksOptions> = {}) {
  const assembleHandlers: AssembleHandler[] = []
  const sessionHandlers: SessionEventHandler[] = []
  const ctx = {
    logger: { info: () => {}, warn: () => {} },
    on(ev: string, fn: unknown) {
      if (ev === 'system-prompt/assemble') assembleHandlers.push(fn as AssembleHandler)
      else if (ev === 'session/event') sessionHandlers.push(fn as SessionEventHandler)
    },
  }
  installMemoryHooks(ctx as never, graph as never, {
    userMessage: true, assistantMessage: true, toolResult: true,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4, desensitize: false,
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
  return { assemble, send, assembleHandlerCount: () => assembleHandlers.length }
}

const userEvent = (text: string) => ({
  type: 'user/message',
  data: { source: { kind: 'user' }, content: [{ type: 'text', text }] },
})
const assistantEvent = (text: string) => ({
  type: 'assistant/message',
  data: { message: { content: [{ type: 'text', text }] } },
})
const toolEvent = (text: string) => ({
  type: 'tool/result',
  data: { message: { content: [{ type: 'text', text }] } },
})

test('① 写入带会话身份：user/assistant/tool 三路都打上 session 归属', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph)

  send({ id: 'sess_A' }, userEvent('我喜欢猫'))
  send({ id: 'sess_A' }, assistantEvent('好的，记住了'))
  send({ sessionId: 'sess_B' }, toolEvent('工具结果：检索到 3 条'))
  await Promise.resolve()

  assert.equal(rememberCalls.length, 3, '三路各写一次（user/assistant/tool）')
  assert.equal(rememberCalls[0]!.extra['session'], 'sess_A', 'user 路带 session')
  assert.equal(rememberCalls[1]!.extra['session'], 'sess_A', 'assistant 路带 session')
  assert.equal(rememberCalls[2]!.extra['session'], 'sess_B', 'sessionId 字段形态也应识别')
  // 归因与授权正交：session 不得挤掉既有 role 归属
  assert.equal(rememberCalls[0]!.extra['role'], 'user')
  assert.equal(rememberCalls[2]!.extra['role'], 'tool-output')
})

test('② 宿主未给出会话标识：不编造 session（退回旧行为）', async () => {
  const { graph, rememberCalls, timelineCalls } = makeGraph()
  const { send, assemble } = makeHarness(graph)

  send({}, userEvent('没有会话标识的消息'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1)
  assert.ok(!('session' in rememberCalls[0]!.extra), '无标识不得编造 session 键')

  await assemble(undefined)
  assert.deepEqual(timelineCalls[0]!.extra, {}, '自动召回无标识 → 不加过滤（向后兼容）')
})

test('③ 自动召回按会话隔离：只读 ctx 上标明的本会话', async () => {
  const { graph, timelineCalls } = makeGraph()
  const { assemble } = makeHarness(graph)

  await assemble({ agent: { session: { id: 'sess_A' } } })
  assert.deepEqual(timelineCalls[0]!.extra, { session: 'sess_A' })

  // 字段变体 + 两侧空白应被归一掉
  await assemble({ agent: { session: { sessionId: '  sess_B  ' } } })
  assert.deepEqual(timelineCalls[1]!.extra, { session: 'sess_B' })
})

test('④ 取值每步稳定：ctx 缺省回落最近会话，且不中途翻转', async () => {
  const { graph, timelineCalls } = makeGraph()
  const { send, assemble } = makeHarness(graph)

  // 先让宿主报一次会话（任意事件类型都会刷新 lastSession）
  send({ id: 'sess_S' }, { type: 'session/start', data: {} })

  await assemble(undefined)
  await assemble(undefined)
  assert.deepEqual(timelineCalls[0]!.extra, { session: 'sess_S' }, 'ctx 缺省 → 回落最近会话')
  assert.deepEqual(timelineCalls[1]!.extra, { session: 'sess_S' },
    '连续两步取值必须一致（否则宿主每步新增快照）')

  await assemble({ agent: { session: { id: 'sess_T' } } })
  assert.deepEqual(timelineCalls[2]!.extra, { session: 'sess_T' }, 'ctx 上的会话优先于回落值')
})

test('⑤ 会话隔离不破坏「每步照旧 push」：同会话连续两步注入块逐字节相同', async () => {
  const { graph } = makeGraph()
  const { assemble } = makeHarness(graph)

  const first = await assemble({ agent: { session: { id: 'sess_A' } } })
  const second = await assemble({ agent: { session: { id: 'sess_A' } } })

  assert.equal(first.contexts.length, 1, '应注入召回块')
  assert.equal(second.contexts.length, 1, '第二步仍须注入（不许跳过 push）')
  assert.ok(first.contexts[0]!.text.includes('【灵枢最近记忆】'))
  assert.equal(first.contexts[0]!.text, second.contexts[0]!.text,
    '同会话连续两步注入块须逐字节相同 → 宿主不追加新快照')
})

test('⑥ 开关尊重既有语义：关掉 autoRecall 则不注册自动召回监听', async () => {
  const { graph, timelineCalls } = makeGraph()
  const { assembleHandlerCount } = makeHarness(graph, { autoRecall: false })

  assert.equal(assembleHandlerCount(), 0, 'autoRecall=false 不应注册 system-prompt/assemble 监听')
  assert.equal(timelineCalls.length, 0, 'autoRecall=false 不应发起 timeline 调用')
})
