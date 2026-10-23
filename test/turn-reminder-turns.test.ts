import test from 'node:test'
import assert from 'node:assert/strict'

import { installMemoryHooks } from '../src/hooks.ts'

// issue #645：提醒的计轮单位与推送时机。
// 旧实现（0.9.10/0.9.12 早期）：turnSeq 按 system-prompt/assemble 次数计数（实测一步约 10 次），
// 且命中后 sticky 永久重推 ⇒ 提醒常驻上下文、agent 反复空转归档。
// 新实现：计数在「真实用户回合」上，命中时记一条 pending，assemble 只消费一次。

function makeHarness(opts = {}) {
  const events = new Map()
  const ctx = {
    logger: { info() {}, warn() {}, error() {} },
    on(name, fn) { events.set(name, fn); return () => {} },
    get() { return undefined },
  }
  const graph = {
    isReady: () => true,
    async timeline() { return { count: 0, limit: 4, items: [] } },
    async sessionRecall() { return { recent: [], notes: [], goals: [], tasks: { active: [], done: [] } } },
    async remember() { return { ok: true, id: 'n1' } },
    // memorize() 还会在写后做读回（纪律第 16 条），mock 补齐这两个方法。
    async read() { return { ok: true, content: 'x', frontmatter: {} } },
    async write() { return { ok: true } },
  }
  installMemoryHooks(ctx, graph, {
    userMessage: true, assistantMessage: false, toolResult: false, importance: 0.6,
    autoRecall: true, autoRecallLimit: 4, desensitize: true,
    ...opts,
  })
  const sid = 'sess-test'
  const session = { id: sid, header: {} }
  const userMsg = (text) => ({
    type: 'user/message',
    data: { source: { kind: 'user' }, content: [{ type: 'text', text }] },
  })
  const assemble = async () => {
    const assembly = { contexts: [] }
    await events.get('system-prompt/assemble')(assembly, { agent: { session } }, async () => {})
    return assembly.contexts.filter((c) => c.name === 'lingshu:turn-reminder')
  }
  const userTurn = (text) => events.get('session/event')(session, userMsg(text))
  return { assemble, userTurn, events }
}

test('① 同一回合内多次 assemble 只推一次提醒', async () => {
  const { assemble, userTurn } = makeHarness()
  for (let i = 1; i <= 10; i++) userTurn('第' + i + '轮')
  const first = await assemble()
  assert.equal(first.length, 1, '第 10 个用户回合的首次 assemble 应带提醒')
  const second = await assemble()
  assert.equal(second.length, 0, '同一回合的后续 assemble 不应再带提醒')
  const third = await assemble()
  assert.equal(third.length, 0, '仍然不带（不 sticky）')
})

test('② 第 9 个用户回合不提醒', async () => {
  const { assemble, userTurn } = makeHarness()
  for (let i = 1; i <= 9; i++) userTurn('第' + i + '轮')
  assert.equal((await assemble()).length, 0)
})

test('③ 自定义间隔：每 3 个用户回合', async () => {
  const { assemble, userTurn } = makeHarness({ turnReminder: 3 })
  userTurn('a'); userTurn('b')
  assert.equal((await assemble()).length, 0, '第 2 回合不提醒')
  userTurn('c')
  assert.equal((await assemble()).length, 1, '第 3 回合提醒')
})

test('④ turnReminder=false 整条关闭', async () => {
  const { assemble, userTurn } = makeHarness({ turnReminder: false })
  for (let i = 1; i <= 10; i++) userTurn('第' + i + '轮')
  assert.equal((await assemble()).length, 0)
})

test('⑤ 无会话标识时不提醒（旧实现回落 __no_sid__ 共用计数器）', async () => {
  const events = new Map()
  const ctx = {
    logger: { info() {}, warn() {}, error() {} },
    on(name, fn) { events.set(name, fn); return () => {} },
    get() { return undefined },
  }
  const graph = {
    isReady: () => true,
    async timeline() { return { count: 0, limit: 4, items: [] } },
    async sessionRecall() { return { recent: [], notes: [], goals: [], tasks: { active: [], done: [] } } },
    async remember() { return { ok: true, id: 'n1' } },
    async read() { return { ok: true, content: 'x', frontmatter: {} } },
    async write() { return { ok: true } },
  }
  installMemoryHooks(ctx, graph, {
    userMessage: true, assistantMessage: false, toolResult: false, importance: 0.6,
    autoRecall: true, autoRecallLimit: 4, desensitize: true,
  })
  const emptySession = { header: {} }
  for (let i = 1; i <= 10; i++) {
    events.get('session/event')(emptySession, {
      type: 'user/message',
      data: { source: { kind: 'user' }, content: [{ type: 'text', text: '第' + i + '轮' }] },
    })
  }
  const assembly = { contexts: [] }
  await events.get('system-prompt/assemble')(assembly, { agent: { session: emptySession } }, async () => {})
  assert.equal(assembly.contexts.filter((c) => c.name === 'lingshu:turn-reminder').length, 0)
})
