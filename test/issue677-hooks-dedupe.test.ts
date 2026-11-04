/**
 * issue677-hooks-dedupe.test.ts · 自动记忆写入带 `dedupe`（#677 @1）
 *
 * 病灶：写入是两级提交（节点文件 + 内存索引先落，应答在后），60s 超时后重试会新增一条
 * 同内容节点（#677 三条实证；本会话归档也复现过）。服务端 #776 已给 `mdcg_remember` 加
 * `dedupe`（同层同内容复用既有节点）——本守卫钉住**插件侧真的传了它**。
 *
 * 不变量：
 *   D1 缺省 ⇒ 三类自动记忆都带 `dedupe: true`；
 *   D2 `dedupe:false` ⇒ 不带该键（回逐位旧行为）；
 *   D3 assistant/tool 同样遵守。
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
    auditPath: join(tmpdir(), 'dsh-hook-audit-iss677d.json'),
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

test('D1 缺省：user 记忆带 dedupe=true', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph)
  send({ id: 'sess_A' }, userEvent('请记住：这条消息重试不应重复'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1)
  assert.equal(rememberCalls[0]!.extra.dedupe, true)
})

test('D2 dedupe:false ⇒ 不带该键（旧行为）', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { dedupe: false })
  send({ id: 'sess_A' }, userEvent('同内容各写一条'))
  await Promise.resolve()
  assert.equal(rememberCalls.length, 1)
  assert.equal('dedupe' in rememberCalls[0]!.extra, false)
})

test('D3 assistant/tool 同样带 dedupe', async () => {
  const { graph, rememberCalls } = makeGraph()
  const { send } = makeHarness(graph, { assistantMessage: true, toolResult: true })
  send({ id: 'sess_A' }, { type: 'assistant/message',
    data: { message: { content: [{ type: 'text', text: '助手回复' }] } } })
  send({ id: 'sess_A' }, { type: 'tool/result',
    data: { message: { content: [{ type: 'text', text: '工具结果' }] } } })
  await Promise.resolve()
  assert.equal(rememberCalls.length, 2)
  for (const c of rememberCalls) assert.equal(c.extra.dedupe, true)
})
