/**
 * issue695-session-exclusion.test.ts · 自动记忆的**会话级排除**（#695）
 *
 * 病灶：#695 —— 外部桥接经 `sessions.prompt()` 注入的控制提示，在 DSH 里是
 * `source.kind='user'` 的 user/message；灵枢把「kind='user'」当充分准入条件，
 * 整段控制提示被写成用户记忆并参与 autoRecall。
 *
 * 为什么不是「按事件形状判真人」：issue 内两组独立读数证明——桥接提示**也带**
 * `rpcId`（12/12），普通 Web 输入带 `clientTimeZone` 但该字段可选。任何凭形状
 * 判真人的闸都会被这条链路证伪；`source_shapes` 也只是边缘分布（无 kind×shape
 * 联合表）。故本仓给的是**按会话显式排除**的诚实兜底（opt-in，缺省关）。
 *
 * 被守卫的不变量：
 *   S1 命中的会话：user/message 不写知识面、不发起语义召回；
 *   S2 未命中的会话：行为与既有完全一致（真人输入照写）；
 *   S3 前缀通配（`sess_bridge_*`）生效；
 *   S4 **不做正文标记过滤**：真人消息里出现 `【会话令牌】` 这类字样仍照写
 *      （报告人明确要求：不能按文本标记杀真人记忆）；
 *   S5 配置形态不符（非数组 / 非字符串项）⇒ 不排除（安全退化）；
 *   S6 排除对整个会话生效（assistantMessage 也不写）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installMemoryHooks, type MemoryHooksOptions } from '../src/hooks.ts'

interface RememberCall { content: string; extra: Record<string, unknown> }
interface ReadCall { query: string; extra: Record<string, unknown> }
type SessionEventHandler = (session: unknown, event: unknown) => void

function makeGraph() {
  const rememberCalls: RememberCall[] = []
  const readCalls: ReadCall[] = []
  const recentCalls: Array<{ role: string; text: string }> = []
  const graph = {
    isReady: (): boolean => true,
    async recentAdd(role: string, text: string) {
      recentCalls.push({ role, text })
      return { ok: true }
    },
    async timeline(limit?: number, extra: Record<string, unknown> = {}) {
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
    async recall() { return { ok: true } },
  }
  return { graph, rememberCalls, readCalls, recentCalls }
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
    userMessage: true, assistantMessage: true, toolResult: true,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4, desensitize: false,
    auditPath: join(tmpdir(), 'dsh-hook-audit-iss695.json'),
    ...overrides,
  })
  const send = (session: unknown, event: unknown): void => {
    for (const h of sessionHandlers) h(session, event)
  }
  return { send }
}

const userEvent = (text: string, source: unknown = { kind: 'user' }) => ({
  type: 'user/message',
  data: { source, content: [{ type: 'text', text }] },
})

test('S1 命中的会话：user/message 不写知识面、不发起语义召回', async () => {
  const { graph, rememberCalls, readCalls } = makeGraph()
  const { send } = makeHarness(graph, { excludeSessions: ['sess_bridge'] })
  send({ id: 'sess_bridge' }, userEvent('【会话令牌】x\n【本次消息快照】{}\n请按桥接协议检查消息'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 0, '被排除会话不得写记忆')
  assert.equal(readCalls.length, 0, '被排除会话也不预热召回')
})

test('S2 未命中的会话：真人输入照写（既有行为不变）', async () => {
  const { graph, rememberCalls, readCalls } = makeGraph()
  const { send } = makeHarness(graph, { excludeSessions: ['sess_bridge'] })
  send({ id: 'sess_human' }, userEvent('请记住：项目代号是「白鹭」'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1)
  assert.equal(rememberCalls[0]!.content, '请记住：项目代号是「白鹭」')
  assert.equal(readCalls.length, 1)
})

test('S3 前缀通配：sess_bridge_* 命中 sess_bridge_01', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { excludeSessions: ['sess_bridge_*'] })
  send({ id: 'sess_bridge_01' }, userEvent('桥接控制提示'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 0)
})

test('S4 不做正文标记过滤：真人消息含【会话令牌】字样仍照写', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { excludeSessions: ['sess_bridge'] })
  send({ id: 'sess_human' }, userEvent('我在调试桥接，日志里出现了【会话令牌】这个词'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1, '不得按文本标记杀真人记忆')
})

test('S5 配置形态不符：不排除（安全退化）', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { excludeSessions: 'sess_bridge' as never })
  send({ id: 'sess_bridge' }, userEvent('真人输入'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1, '非数组配置必须退化为不排除')

  const second = makeGraph()
  const h2 = makeHarness(second.graph, { excludeSessions: [123 as never] })
  h2.send({ id: 'sess_bridge' }, userEvent('真人输入二'))
  await Promise.resolve()
  assert.equal(second.rememberCalls.length, 1, '非字符串项必须忽略')
})

test('S6 排除对整个会话生效：assistantMessage 也不写', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { excludeSessions: ['sess_bridge'] })
  send({ id: 'sess_bridge' }, { type: 'assistant/message',
    data: { message: { content: [{ type: 'text', text: '桥接代理的回复' }] } } })
  await Promise.resolve()
  assert.equal(rememberCalls.length, 0, '被排除会话的 assistant 回复也不得写')
})

test('S6b 反向对照：未排除会话的 assistant 回复照写（证明 S6 非恒 0）', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { excludeSessions: ['sess_bridge'] })
  send({ id: 'sess_human' }, { type: 'assistant/message',
    data: { message: { content: [{ type: 'text', text: '真人会话的回复' }] } } })
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1, '未排除会话的 assistant 回复应写入')
})

test('S7 窗口写侧不受排除影响（只门控知识面轨）', async () => {
  const { graph, rememberCalls, readCalls, recentCalls } = makeGraph()
  const { send } = makeHarness(graph, { excludeSessions: ['sess_bridge'] })
  send({ id: 'sess_bridge' }, userEvent('【本次消息快照】{}'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 0, '知识面不写')
  assert.equal(readCalls.length, 0, '不预热召回')
  assert.equal(recentCalls.length, 1, '窗口写侧照常（运行态、不进检索正排）')
})

test('S8 裸 "*" 被忽略：不会静默关闭全部会话', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { excludeSessions: ['*'] })
  send({ id: 'sess_human' }, userEvent('真人输入'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1, '裸 * 必须被忽略（否则一条配置静默全关）')
})
