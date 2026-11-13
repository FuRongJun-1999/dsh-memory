/**
 * 守卫 · issue #749 跨会话 knowledge 浮现（注入面接线）。
 *
 * 病象（0.9.22 实测）：自动注入块只含本会话 contextual 裸消息；knowledge 层 64 个节点零浮现，
 * 跨会话等于「完全记不住」。同一 query 显式 read 能 rank 命中 ⇒ 是注入面未接线，不是检索失效。
 *
 * 修法：assemble 侧用「最近一条用户消息」做一次查询式检索（不带 session 过滤 ⇒ 只取共享档），
 * 命中的非 contextual 条目并入「最近记忆」块（在时间线之前）。
 *
 * 断言：
 *  K1 时间线只有 contextual 时，knowledge 条目仍被注入（本件靶心）
 *  K2 knowledge 条目排在 contextual 之前（先知识后流水）
 *  K3 contextual 不重复出现（由 timeline 块负责，两条通路不各贴一遍）
 *  K4 read 抛错时不影响既有时间线块（fail-soft）
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { installMemoryHooks } from '../src/hooks.ts'

interface Assembly {
  contexts: Array<{ name: string; text: string }>
  variables: Record<string, string>
}

function makeCtx(opts: { readThrows?: boolean } = {}): {
  listeners: Map<string, (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>>
} {
  const listeners = new Map<string, never>()
  const ctx = {
    logger: { info: () => {}, warn: () => {} },
    on(ev: string, fn: never) { listeners.set(ev, fn as never) },
  } as never
  installMemoryHooks(ctx, {
    isReady: () => true,
    // 时间线：**只有本会话 contextual**（正是病象形态）
    async timeline() {
      return { count: 1, limit: 4, items: [
        { id: 'c1', layer: 'contextual', start: 1, end: 2, preview: '本会话流水：今天写了个测试' },
      ] }
    },
    // 查询式检索：返回跨会话 knowledge（模拟 A 会话写入、B 会话可读）
    async read() {
      if (opts.readThrows) throw new Error('read boom')
      return { items: [
        { id: 'k1', layer: 'knowledge', start: 9, end: 10, preview: '降熵定理：新结构必须自证降熵' },
      ] }
    },
    async remember() { return { ok: true, id: 'n1' } },
    async write() { return { ok: true } },
  } as never, {
    userMessage: true, assistantMessage: false, toolResult: false,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4, desensitize: true,
  })
  return { listeners: listeners as never }
}

async function turn(listeners: Map<string, never>): Promise<void> {
  // 先产生一条真实用户消息（assemble 侧据此做查询式检索）
  const onEvent = listeners.get('session/event') as unknown as (s: unknown, e: unknown) => void
  assert.ok(onEvent, '应注册 session/event 监听')
  onEvent({ id: 'sess-B', header: {} }, { type: 'user/message',
    data: { source: { kind: 'user' }, content: [{ type: 'text', text: '降熵定理是什么？' }] },
  })
}

function recallBlock(a: Assembly): string {
  const blk = a.contexts.find((c) => c.name === 'lingshu:auto-recall')
  return blk ? blk.text : ''
}

test('K1 时间线只有 contextual 时，跨会话 knowledge 仍被注入', async () => {
  const { listeners } = makeCtx()
  await turn(listeners)
  const handler = listeners.get('system-prompt/assemble')!
  const a: Assembly = { contexts: [{ name: 'clock', text: 't' }], variables: {} }
  await handler(a, { agent: { session: { id: 'sess-B' } } }, async () => a)
  const body = recallBlock(a)
  assert.ok(body.includes('降熵定理'), 'knowledge 条目必须出现在注入块里：' + body)
})

test('K2 knowledge 排在 contextual 之前', async () => {
  const { listeners } = makeCtx()
  await turn(listeners)
  const handler = listeners.get('system-prompt/assemble')!
  const a: Assembly = { contexts: [{ name: 'clock', text: 't' }], variables: {} }
  await handler(a, { agent: { session: { id: 'sess-B' } } }, async () => a)
  const body = recallBlock(a)
  assert.ok(body.indexOf('降熵定理') < body.indexOf('本会话流水'),
    'knowledge 应先于流水：' + body)
})

test('K3 contextual 不因两条通路重复出现', async () => {
  const { listeners } = makeCtx()
  await turn(listeners)
  const handler = listeners.get('system-prompt/assemble')!
  const a: Assembly = { contexts: [{ name: 'clock', text: 't' }], variables: {} }
  await handler(a, { agent: { session: { id: 'sess-B' } } }, async () => a)
  const body = recallBlock(a)
  const n = body.split('本会话流水').length - 1
  assert.equal(n, 1, 'contextual 只应由时间线块出现一次：' + body)
})

test('K4 read 失败不影响时间线块（fail-soft）', async () => {
  const { listeners } = makeCtx({ readThrows: true })
  await turn(listeners)
  const handler = listeners.get('system-prompt/assemble')!
  const a: Assembly = { contexts: [{ name: 'clock', text: 't' }], variables: {} }
  await handler(a, { agent: { session: { id: 'sess-B' } } }, async () => a)
  const body = recallBlock(a)
  assert.ok(body.includes('本会话流水'), '检索失败时时间线照常注入：' + body)
})