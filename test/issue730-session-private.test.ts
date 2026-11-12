/**
 * issue730-session-private.test.ts · 会话记忆标 `private`（#730 G）
 *
 * 「读各归各」的正解是既有密级机制：`_readable` 里 `private` = **仅归属会话
 * （frontmatter.session）可见**。本守卫钉住插件侧的唯一动作——开启
 * `memory.sessionPrivate` 后，自动写入的三类记忆都带 `sensitivity: "private"`；
 * 缺省关（跨会话连续性是既有默认，#749 的跨会话召回仍是待定产品决策）。
 *
 * 不变量：
 *   P1 开启 ⇒ user 记忆带 sensitivity=private；
 *   P2 缺省关 ⇒ 不带该键（既有行为逐位不变）；
 *   P3 无归属会话（unassigned）⇒ 即使开启也不标 private（private 无归属 ⇒ 仅设计者可见，
 *      等于把用户记忆写成谁都读不到）；
 *   P4 assistant 记忆同样遵守（assistantMessage 开启时）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installMemoryHooks, type MemoryHooksOptions } from '../src/hooks.ts'

interface RememberCall { content: string; extra: Record<string, unknown> }
type SessionEventHandler = (session: unknown, event: unknown) => void

function makeGraph() {
  const rememberCalls: RememberCall[] = []
  const graph = {
    isReady: (): boolean => true,
    async timeline() { return { count: 0, limit: 4, items: [] } },
    async remember(content: string, extra: Record<string, unknown> = {}) {
      rememberCalls.push({ content, extra })
      return { ok: true }
    },
    async read() { return { ok: true } },
    async recall() { return { ok: true } },
    async recentAdd() { return { ok: true } },
  }
  return { graph, rememberCalls }
}

function makeHarness(graph: object, overrides: Partial<MemoryHooksOptions> = {}) {
  const sessionHandlers: SessionEventHandler[] = []
  const ctx = {
    logger: { info: () => {}, warn: () => {} },
    on(ev: string, fn: unknown) {
      if (ev === 'session/event') sessionHandlers.push(fn as SessionEventHandler)
    },
  }
  installMemoryHooks(ctx as never, graph as never, {
    userMessage: true, assistantMessage: false, toolResult: false,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4, desensitize: false,
    auditPath: join(tmpdir(), 'dsh-hook-audit-iss730.json'),
    ...overrides,
  })
  const send = (session: unknown, event: unknown): void => {
    for (const h of sessionHandlers) h(session, event)
  }
  return { send }
}

const userEvent = (text: string) => ({
  type: 'user/message',
  data: { source: { kind: 'user' }, content: [{ type: 'text', text }] },
})

test('P1 开启 sessionPrivate：user 记忆带 sensitivity=private', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { sessionPrivate: true })
  send({ id: 'sess_A' }, userEvent('我是这条会话的专属记忆'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1)
  assert.equal(rememberCalls[0]!.extra.sensitivity, 'private')
})

test('P2 缺省关：不写 sensitivity 键（既有行为不变）', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph)
  send({ id: 'sess_A' }, userEvent('跨会话可见的既有默认'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1)
  assert.equal('sensitivity' in rememberCalls[0]!.extra, false)
})

test('P3 无归属会话：即使开启也不标 private', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { sessionPrivate: true })
  send({}, userEvent('没有会话 id 的消息'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1)
  assert.equal('sensitivity' in rememberCalls[0]!.extra, false,
    'private 无归属 ⇒ 仅设计者可见，等于写丢')
})

test('P3b 会话 id 恰为占位哨兵 unassigned：同样不标 private', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { sessionPrivate: true })
  send({ id: 'unassigned' }, userEvent('宿主把哨兵当 id 传进来'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1)
  assert.equal('sensitivity' in rememberCalls[0]!.extra, false,
    'private + 归属=哨兵 ⇒ 仅设计者可见，等于写丢')
})

test('P4 assistant 记忆同样遵守 sessionPrivate', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { sessionPrivate: true, assistantMessage: true })
  send({ id: 'sess_A' }, { type: 'assistant/message',
    data: { message: { content: [{ type: 'text', text: '助手回复' }] } } })
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1)
  assert.equal(rememberCalls[0]!.extra.sensitivity, 'private')
})
