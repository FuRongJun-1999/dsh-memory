/**
 * session-injection.test.ts · B 治本批守卫（2026-10-06）
 * 「运行期会话 → 写归因调用」注入的判据矩阵 + 接线闭环
 *
 * 背景（双链根因的插件侧一环）
 * ----------------------------
 *   DSH 单进程多会话。宿主的会话标识只经 `session/event` 到达插件；此前它只被
 *   用在 hooks 面（自动记忆带 extra.session）。**agent 直调工具面**
 *   （src/tools.ts 的 execute → bridge.callTool）转发时不带会话——而部署侧
 *   `MDCG_SESSION` env 一旦取消/为空，`md_cg/mcp_server.py` 的
 *   `_declared_session` 就以**请求声明**为归因来源（env > 请求声明 > 进程身份），
 *   不传即落回 Principal 的**进程级随机** sess_* 兜底桶（归属不可辨认）。
 *   修复 = src/lib/session_state.ts（单点）+ src/tools.ts 转发面注入。
 *
 * 被守卫的不变量（矩阵逐条）
 * --------------------------
 *   a. 写归因面注入：观测到 sess_X 后，`cg(op=write)` 与 `mdcg_remember` 均注入；
 *   b. `cg` 的非写 op 不注入：read / 无 op / sustain；
 *   c. 读面不注入（视图过滤语义不动）：stg / mdcg_recall / mdcg_search / mdcg_get
 *      ——服务端 schema 原文「会话归属过滤（frontmatter.session；…缺省不过滤）」；
 *   d. 显式声明不覆盖：'mine' 保留；'' / '   ' / null（非 string / 空白 / 缺失）
 *      视为未声明 → 注入；
 *   e. 未观测 → 'unassigned' 显式占位；noteSession('') / ('   ') 不覆盖旧值；
 *   f. 不 mutate：注入返回新对象，传入对象保持无 session 键；
 *   g. 接线闭环：hooks 观测（makeHarness 形态）→ 工具面注入同源。
 *
 * ⚠️ 本文件不 import 既有测试文件：makeGraph / makeHarness 为同形态自建
 * （参照 test/session-attribution.test.ts；auditPath 指向 tmpdir——
 * 绝不得写真实 ~/.dsh）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installMemoryHooks, type MemoryHooksOptions } from '../src/hooks.ts'
import {
  UNASSIGNED_SESSION,
  attributeSession,
  currentSession,
  noteSession,
} from '../src/lib/session_state.ts'

interface Assembly {
  contexts: Array<{ name: string; text: string }>
  variables: Record<string, string>
}
type AssembleHandler = (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>
type SessionEventHandler = (session: unknown, event: unknown) => void

interface TimelineCall { limit?: number; extra: Record<string, unknown> }
interface RememberCall { content: string; extra: Record<string, unknown> }
interface ReadCall { query: string; extra: Record<string, unknown> }

/** 最小 MdcgClient 形态（与既有守卫同形，自建不 import）。 */
function makeGraph() {
  const timelineCalls: TimelineCall[] = []
  const rememberCalls: RememberCall[] = []
  const readCalls: ReadCall[] = []
  const graph = {
    isReady: (): boolean => true,
    async timeline(limit?: number, extra: Record<string, unknown> = {}) {
      timelineCalls.push({ limit, extra })
      return { count: 0, limit: limit ?? 4, items: [] }
    },
    async remember(content: string, extra: Record<string, unknown> = {}) {
      rememberCalls.push({ content, extra })
      return { ok: true }
    },
    async read(query: string, extra: Record<string, unknown> = {}) {
      readCalls.push({ query, extra })
      return { ok: true }
    },
    async recall() { return { ok: true } }
  }
  return { graph, timelineCalls, rememberCalls, readCalls }
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
    // 落盘审计（issue #56）指向临时目录：本文件不测审计面，但**绝不得写真实 ~/.dsh**。
    auditPath: join(tmpdir(), 'dsh-hook-audit-session-injection.json'),
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
  return { assemble, send }
}

const userEvent = (text: string) => ({
  type: 'user/message',
  data: { source: { kind: 'user' }, content: [{ type: 'text', text }] },
})

// ---------------------------------------------------------------- e1 未观测（必须在最前）

// ⚠️ 顺序不变量：本用例必须是**文件内第一个触碰会话状态的用例**。模块级状态
// （lib/session_state.ts 的 lastSession）在进程启动时为空（未观测）；node:test
// 的顶层用例在文件内**顺序执行**，故把本用例置于最前即「测试开头先清态」。
// 前置断言把这一前提显式钉住——顺序若被改动，此处立即红（而不是静默按已观测
// 态断言出一个假绿）。
test('e1 未观测 → 注入 unassigned 显式占位（不落进程级随机 sess_*）', () => {
  assert.equal(currentSession(), '', '前置：此刻必须未观测到任何会话（模块级状态进程启动时为空）')
  assert.equal(UNASSIGNED_SESSION, 'unassigned', '占位常量与 H2③ 口径一致（跨进程可辨认）')
  assert.equal(attributeSession('mdcg_remember', {})['session'], 'unassigned')
  assert.equal(attributeSession('cg', { op: 'write' })['session'], 'unassigned')
})

// ---------------------------------------------------------------- a 写归因面注入

test('a 观测 sess_X 后：cg(op=write) 与 mdcg_remember 均注入 session=sess_X', () => {
  noteSession('sess_X')
  const cgWrite = attributeSession('cg', { op: 'write', content: 'x' })
  assert.equal(cgWrite['session'], 'sess_X', 'cg(op=write) 是写面 → 注入')
  assert.equal(cgWrite['op'], 'write', '其余参数原样保留')
  assert.equal(cgWrite['content'], 'x')

  const remember = attributeSession('mdcg_remember', { content: 'x' })
  assert.equal(remember['session'], 'sess_X', 'mdcg_remember 是写面 → 注入')
  assert.equal(remember['content'], 'x')
})

// ---------------------------------------------------------------- b cg 非写 op 不注入

test('b cg 的非写 op 不注入：{op:read} / 无 op / {op:sustain}', () => {
  noteSession('sess_X')
  // 收集式（不首条早退）：一次列出全部漏点，便于变异自证时看全判别力。
  const bad: string[] = []
  const cases: Array<Record<string, unknown>> = [{ op: 'read' }, {}, { op: 'sustain' }]
  for (const args of cases) {
    const out = attributeSession('cg', args)
    if ('session' in out) bad.push(`cg ${JSON.stringify(args)} 注入了 session=${String(out['session'])}`)
    else if (out !== args) bad.push(`cg ${JSON.stringify(args)} 未命中却返回了新对象（应原样透传）`)
  }
  assert.deepEqual(bad, [], 'cg 的非写 op 一律不得注入 session（非写归因面；未命中必须原样返回同一引用）')
})

// ---------------------------------------------------------------- c 读面不注入

test('c 读面不注入（视图过滤语义不动）：stg / mdcg_recall / mdcg_search / mdcg_get', () => {
  noteSession('sess_X')
  const cases: Array<[string, Record<string, unknown>]> = [
    ['stg', { op: 'timeline' }],
    ['mdcg_recall', { query: 'q' }],
    ['mdcg_search', { query: 'q' }],
    ['mdcg_get', { node_id: 'n1' }],
  ]
  const bad: string[] = []
  for (const [name, args] of cases) {
    const out = attributeSession(name, args)
    if ('session' in out) bad.push(`${name} 注入了 session=${String(out['session'])}`)
    else if (out !== args) bad.push(`${name} 未命中却返回了新对象（应原样透传）`)
  }
  assert.deepEqual(bad, [],
    '读面（服务端 schema：frontmatter.session 视图过滤，缺省不过滤）一律不得注入，且未命中须原样透传')
})

// ---------------------------------------------------------------- d 显式声明不覆盖

test('d 显式声明不覆盖；空串/空白/非 string 视为未声明 → 注入', () => {
  noteSession('sess_X')
  assert.equal(attributeSession('mdcg_remember', { session: 'mine' })['session'], 'mine',
    '显式非空声明一律不覆盖（调用方自报优先，插件不替调用方改归属）')
  assert.equal(attributeSession('mdcg_remember', { session: '' })['session'], 'sess_X',
    '空串 = 未声明 → 注入')
  assert.equal(attributeSession('mdcg_remember', { session: '   ' })['session'], 'sess_X',
    '纯空白 = 未声明 → 注入')
  assert.equal(attributeSession('mdcg_remember', { session: null })['session'], 'sess_X',
    '非 string（null） = 未声明 → 注入（原样转发只会落回进程级随机 sess_*）')
})

// ---------------------------------------------------------------- e2 空观测不覆盖

test('e2 noteSession 空串/纯空白不覆盖旧值；非空观测写入前 trim', () => {
  noteSession('sess_keep')
  assert.equal(currentSession(), 'sess_keep')
  noteSession('')
  assert.equal(currentSession(), 'sess_keep', '空串观测不覆盖旧值')
  noteSession('   ')
  assert.equal(currentSession(), 'sess_keep', '纯空白观测不覆盖旧值')
  noteSession('  sess_trim  ')
  assert.equal(currentSession(), 'sess_trim', '非空观测写入前 trim')
})

// ---------------------------------------------------------------- f 不 mutate

test('f 不 mutate：注入返回新对象，传入对象保持无 session 键', () => {
  noteSession('sess_X')
  const args: Record<string, unknown> = { op: 'write', content: 'x' }
  const out = attributeSession('cg', args)
  assert.ok(!('session' in args), '传入的原对象不得被 mutate（不得出现 session 键）')
  assert.notEqual(out, args, '注入必须返回**新对象**')
  assert.equal(out['session'], 'sess_X')
  assert.equal(out['content'], 'x', '新对象在注入键之外与输入逐键相同')
})

// ---------------------------------------------------------------- g 接线闭环

test('g 接线闭环：hooks 观测（session/event）→ 工具面写归因注入同源', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph)

  send({ id: 'sess_X' }, userEvent('闭环'))
  await Promise.resolve()

  assert.equal(rememberCalls.length, 1, 'hooks 面照旧写入（既有行为不回归）')
  assert.equal(rememberCalls[0]!.extra['session'], 'sess_X', 'hooks 面写入带本会话')
  assert.equal(attributeSession('mdcg_remember', {})['session'], 'sess_X',
    '同一次观测必须原样出现在工具面注入——观测与注入同源（lib/session_state.ts 单点）')
})
