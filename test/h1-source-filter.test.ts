/**
 * h1-source-filter.test.ts · 来源判定守卫（H1）+ 会话槽显式传递（H2③）
 *
 * 病灶（H1）：自动记忆路径只按 `source.kind !== 'user'` 一条过滤，仓库内没有任何
 * 按委派/角色过滤的代码。子代理委派指令因此会被写成「用户记忆」，污染真人记忆。
 *
 * 修复：两条**来源判据**（均为「字段在场且取值匹配才拦」，缺字段一律不拦）：
 *   · 会话级：`SessionHeader.origin === 'subagent'` 或 `delegationDepth > 0`
 *     ⇒ 该子会话的自动记忆**整条会话**拦掉；
 *   · 消息级：`source.form === 'relay'`（「另一个 agent 发给本 agent 的消息」）
 *     ⇒ 该条不写。
 *
 * ⚠️ **观测面（2026-10-05 订正，不要把本文件读成「已验证委派会被拦住」）**：
 *   本机**已装** DSH 2.0（`dsh-0.2.0-rc.2`；profile `web` 内已装
 *   `@furongjun1999/dsh-memory` 0.7.2）；接口面已按实装包复核
 *   （dsh-session/lib/types/types.d.ts:81,87；dsh-llm/lib/types/message.d.ts:56,90；
 *   本仓 devDeps 0.1.0-rc.8 同字段为 :64,70 / :52），真实会话事件面亦已观测
 *   （19 场：会话头 delegationDepth=0 19/19 真实在写；270 条 user/message 的
 *   source.kind 分布 = user 80／roleplay-tasks 82／roleplay-context 72／
 *   runtime-context 19／skill-catalog 14／user-approval 2／goal 1，注入类均非 'user'、
 *   被既有 kind !== 'user' 判据设计滤除）。**仍未观测**的是 origin='subagent' /
 *   delegationDepth>0 / form='relay' 的真实出现。本守卫证明的是「判据在场即拦、
 *   缺失即不拦」这一可机械判定的性质，**不是**「真实委派一定被拦住」。
 *
 * 被守卫的不变量
 * --------------
 *   A 会话级判据：origin='subagent' / delegationDepth>0 被拦；深度 0、其它 origin
 *     值、字段缺失/形态不符一律**不拦**（安全退化）；
 *   B 消息级判据：form='relay' 被拦；其它 form / 无 form / 真人输入不受影响；
 *   C 退化不改既有行为：缺字段时三路 remember 的 role/tags/session 与旧口径一致；
 *   D 子代理会话不得污染 lastSession（否则顶层会话的自动召回会读错会话）；
 *   E H2③：语义召回显式带会话槽（可观测调用参数；无标识 → unassigned）。
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

interface RememberCall { content: string; extra: Record<string, unknown> }
interface ReadCall { query: string; extra: Record<string, unknown> }
interface TimelineCall { limit?: number; extra: Record<string, unknown> }

function makeGraph() {
  const rememberCalls: RememberCall[] = []
  const readCalls: ReadCall[] = []
  const timelineCalls: TimelineCall[] = []
  const graph = {
    isReady: (): boolean => true,
    async timeline(limit?: number, extra: Record<string, unknown> = {}) {
      timelineCalls.push({ limit, extra })
      return {
        count: 1, limit: limit ?? 4,
        items: [{ id: 'n1', layer: 'contextual', start: 1, end: 2, preview: '记忆预览' }],
      }
    },
    async remember(content: string, extra: Record<string, unknown> = {}) {
      rememberCalls.push({ content, extra })
      return { ok: true }
    },
    async read(query: string, extra: Record<string, unknown> = {}) {
      readCalls.push({ query, extra })
      return { ok: true }
    },
    async recall() { return { ok: true } },
  }
  return { graph, rememberCalls, readCalls, timelineCalls }
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
    // 落盘审计（issue #56）指向临时目录：本文件不测审计面，但**绝不得写真实 ~/.dsh**
    // （本文件的会话事件会触发审计记录，缺省路径是用户家目录）。
    auditPath: join(tmpdir(), 'dsh-hook-audit-h1.json'),
    ...overrides,
  })
  const assemble = async (hostCtx: unknown): Promise<Assembly> => {
    const a: Assembly = { contexts: [], variables: {} }
    await assembleHandlers[0]!(a, hostCtx, async () => a)
    return a
  }
  const send = (session: unknown, event: unknown): void => {
    assert.ok(sessionHandlers[0], '应注册 session/event 监听')
    for (const h of sessionHandlers) h(session, event)
  }
  return { assemble, send }
}

/** user/message 事件；`source` 可注入任意形态（含缺字段）。 */
const userEvent = (text: string, source: unknown = { kind: 'user' }) => ({
  type: 'user/message',
  data: { source, content: [{ type: 'text', text }] },
})

// ---------------------------------------------------------------- A 会话级判据

test('A1 会话级：origin=subagent ⇒ 整条会话的自动记忆被拦', async () => {
  const { graph, rememberCalls, readCalls } = makeGraph()
  const { send } = makeHarness(graph)
  send({ id: 'sess_sub', header: { origin: 'subagent' } }, userEvent('委派指令：帮我改这个文件'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 0, '子代理会话不得写入记忆')
  assert.equal(readCalls.length, 0, '子代理会话也不发起语义召回')
})

test('A2 会话级：delegationDepth>0 ⇒ 被拦（顶层会话缺省为零）', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph)
  send({ id: 'sess_child', header: { delegationDepth: 1 } }, userEvent('子会话首轮提示'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 0, 'depth=1（父深度+1）是子代理子会话')
})

test('A3 会话级退化：深度 0 / 其它 origin / 字段缺失 / 形态不符 ⇒ 不拦', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph)
  const cases: Array<[string, unknown]> = [
    ['深度 0（顶层会话）', { id: 'sess_top', header: { delegationDepth: 0 } }],
    ['origin 为其它值', { id: 'sess_x', header: { origin: 'root' } }],
    ['无 header', { id: 'sess_y' }],
    ['header 非对象', { id: 'sess_z', header: 'nope' }],
    ['depth 是字符串（形态不符）', { id: 'sess_s', header: { delegationDepth: '1' } }],
    ['depth 为 NaN', { id: 'sess_n', header: { delegationDepth: Number.NaN } }],
  ]
  for (const [, session] of cases) send(session, userEvent('真实用户输入'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, cases.length,
    '字段缺失/形态不符必须安全退化为**不过滤**（宁可多记，不可静默丢真人记忆）')
})

// ---------------------------------------------------------------- B 消息级判据

test('B1 消息级：form=relay ⇒ 该条不写（kind=user 形态也拦）', async () => {
  const { graph, rememberCalls, readCalls } = makeGraph()
  const { send } = makeHarness(graph)
  send({ id: 'sess_A' }, userEvent('另一个 agent 的委派指令', { kind: 'user', form: 'relay' }))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 0, 'relay（另一个 agent 发给本 agent 的消息）不写')
  assert.equal(readCalls.length, 0, 'relay 也不预热召回')
})

test('B2 消息级：其它 form / 无 form / 真人输入不受影响', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph)
  send({ id: 'sess_A' }, userEvent('真人输入一'))
  send({ id: 'sess_A' }, userEvent('通知类上下文', { kind: 'plugin', plugin: 'p', form: 'notice' }))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1, '只有真人输入落库（plugin/notice 仍由 kind 判据拦）')
  assert.equal(rememberCalls[0]!.content, '真人输入一')
})

test('B3 消息级：relay 判据先于 kind 判据 ⇒ kind=plugin+relay 同样被指名拦下', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph)
  send({ id: 'sess_A' }, userEvent('中继消息', { kind: 'plugin', plugin: 'relay-bridge', form: 'relay' }))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 0, 'relay 不写（不论走到哪条判据）')
})

test('B4 消息级退化：source 整个缺失也不抛错、不写（既有 kind 判据维持）', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph)
  // 注意：必须构造**不带 source 键**的事件（显式传 undefined 会触发默认参数 = {kind:'user'}）
  const noSource = { type: 'user/message', data: { content: [{ type: 'text', text: '无 source' }] } }
  assert.doesNotThrow(() => send({ id: 'sess_A' }, noSource))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 0, '缺 source → 仍按既有 kind 判据不写（行为不变）')
})

// ---------------------------------------------------------------- C 退化不改既有口径

test('C1 退化路径的写入口径与旧行为逐位一致（role/tags/importance/session）', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph)
  send({ id: 'sess_A' }, userEvent('真人输入'))
  await Promise.resolve()
  const extra = rememberCalls[0]!.extra
  assert.equal(extra['role'], 'user')
  assert.deepEqual(extra['tags'], ['dsh', 'user'])
  assert.equal(extra['importance'], 0.6)
  assert.equal(extra['session'], 'sess_A')
})

// ---------------------------------------------------------------- D 不污染 lastSession

test('D1 子代理会话不得刷新 lastSession（顶层会话的召回必须仍读自己的会话）', async () => {
  const { graph, timelineCalls } = makeGraph()
  const { send, assemble } = makeHarness(graph)
  send({ id: 'sess_top' }, { type: 'session/start', data: {} })
  send({ id: 'sess_sub', header: { origin: 'subagent' } }, userEvent('委派指令'))
  await Promise.resolve()
  await assemble(undefined)
  assert.deepEqual(timelineCalls[0]!.extra, { session: 'sess_top' },
    '子代理会话被拦后不得成为 lastSession（否则顶层会话召回读错会话）')
})

// ---------------------------------------------------------------- E H2③ 会话槽

test('E1 语义召回显式带会话槽（可观测调用参数，非源码断言）', async () => {
  const { graph, readCalls } = makeGraph()
  const { send } = makeHarness(graph)
  send({ id: 'sess_A' }, userEvent('真人输入'))
  await Promise.resolve()
  assert.equal(readCalls.length, 1)
  assert.equal(readCalls[0]!.extra['session'], 'sess_A', 'H2③：召回显式带本会话')
  assert.equal(readCalls[0]!.extra['k'], 3, '召回条数语义不变')
})

test('E2 无会话标识 → 召回带 unassigned（不落内核进程随机 sess_*）', async () => {
  const { graph, readCalls } = makeGraph()
  const { send } = makeHarness(graph)
  send({}, userEvent('没有会话标识'))
  await Promise.resolve()
  assert.equal(readCalls[0]!.extra['session'], 'unassigned',
    'H2③：显式常量占位，跨进程可辨认（不编造宿主 id）')
})
