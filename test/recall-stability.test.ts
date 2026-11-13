/**
 * recall-stability.test.ts · 自动召回注入的「快照不累加」回归守卫
 *
 * 判据取自**宿主真函数**与**宿主真语义**：
 *   · `renderContextSections` / `renderContextSnapshot`（@deepseek-ai/dsh-system-prompt）
 *     是 `assembly.contexts` 的真实消费者；
 *   · 宿主 `RuntimeContextProjection.project()`（dsh-agent-loop，见下方 `project` 注释）
 *     按**渲染后的整段文本**去重：文本相同 → 不提交任何快照；不同 → 在会话里 append 一条
 *     新的 user/message（append 语义，旧快照不会被替换或移除）。
 *
 * 被守卫的不变量（本文件存在的理由）：
 *   记忆内容没变时，注入块**必须仍然被 push**，从而渲染出的快照文本逐字节不变 → 宿主
 *   一步都不追加。v0.4.8 的旧实现「内容没变就不 push，靠每 8 步强制补一次自愈」会让
 *   渲染文本在「有块 / 无块」之间来回跳，每一步都追加一份 ~250 tok 的快照，
 *   长会话里每请求 inject 随步数线性涨到 30k+ tok（实测）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { renderContextSnapshot } from '@deepseek-ai/dsh-system-prompt'
import { installMemoryHooks } from '../src/hooks.ts'

/** 宿主渲染面最小形态：renderContextSections/renderContextSnapshot 只读 contexts 与 variables。 */
interface Assembly {
  contexts: Array<{ name: string; text: string }>
  variables: Record<string, string>
}

/** 与宿主 `RuntimeContextProjection.project()` 等价的去重谓词（真源：dsh-agent-loop
 *  的 `if (this.retained?.text === snapshot) return;`）：返回 true = 会话里新增一份快照。 */
function hostAppends(previousText: string | undefined, current: string): boolean {
  return previousText !== current
}

function makeCtx(): {
  listeners: Map<string, (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>>
} {
  const listeners = new Map<string, (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>>()
  const ctx = {
    logger: { info: () => {}, warn: () => {} },
    on(ev: string, fn: never) { listeners.set(ev, fn as never) },
  } as never
  installMemoryHooks(ctx, {
    isReady: () => true,
    async timeline() { return payload },
    // 用户回合会触发自动记忆写入（memorize → remember + 读回），mock 补齐。
    async remember() { return { ok: true, id: 'n1' } },
    async read() { return { ok: true, content: 'x', frontmatter: {} } },
    async write() { return { ok: true } },
  } as never, {
    userMessage: true, assistantMessage: false, toolResult: false,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4, desensitize: true,
  })
  return { listeners }
}

/** 可变记忆真源：同一个 client 反复 timeline() 读它。 */
let payload: unknown = {
  count: 2, limit: 4,
  items: [
    { id: 'n1', layer: 'contextual', start: 1, end: 2, preview: '记忆1：用户喜欢猫' },
    { id: 'n2', layer: 'knowledge', start: 3, end: 4, preview: '记忆2：上次聊了排序' },
  ],
}

test('① 记忆不变时：注入块每步照旧 push，渲染文本逐字节相同 → 宿主不追加任何快照', async () => {
  const { listeners } = makeCtx()
  const handler = listeners.get('system-prompt/assemble')
  assert.ok(handler, '应注册 system-prompt/assemble 监听')

  // 宿主侧的「已提交快照文本」——先放一条与本插件无关的基线，模拟会话里已有的上下文。
  const base: Assembly = { contexts: [{ name: 'clock', text: '当前时间 12:00' }], variables: {} }
  let retained: string | undefined = renderContextSnapshot(base)
  let appends = 0

  for (let step = 0; step < 12; step++) {
    const assembly: Assembly = { contexts: [{ name: 'clock', text: '当前时间 12:00' }], variables: {} }
    await handler(assembly, {}, async () => assembly)
    const rendered = renderContextSnapshot(assembly)
    if (hostAppends(retained, rendered)) { appends++; retained = rendered }
    assert.ok(rendered.includes('【灵枢最近记忆】'), `第 ${step} 步应注入召回块`)
  }

  // 判据重述（2026-10-23，issue #645）：提醒的计轮单位改成**真实用户回合**后，
  // 没有新用户消息的 12 次 assemble 不会再插提醒 ⇒ 只追加首份快照。
  // issue #739（2026-11-06）：注入面加了**会话内去重**（同一条最多 2 次），于是第 3 步
  // 起条目从 2 条收缩到 1 条 —— 那一次收缩**必然**产生一份新快照（文本变了），之后恢复稳定。
  // 代价是被限界的：每个条目一生只触发**一次**收缩；换来的是旧会话里「18 条被贴 362 次、
  // 单条 ×62」的复述式退化（实测 --D-6_ai--/session-c28c8589…）。
  // issue #739：注入面加了会话内去重（同一条最多 2 次）后，本用例不再恒为 1 份快照：
  // 首份 + 若干次「条目到期收缩」。收缩次数上界 = 条目数（每条一生只掉一次），
  // 此后文本恒定、宿主不再追加 —— 要钉的是**有界性**，不是某个精确数字（实测在 2~3 间浮动，
  // 取决于 timeline 每步返回的条目数）。
  // issue #739（2026-11-12）块级去重：同一批每轮原样重贴会诱发整段复述，故第二轮起改贴
  // **占位**（正文不再重复）。这引入一次额外快照（full → stub 的文本变化，+1），
  // 之后占位恒定不再追加。故上界 = 首份 + 条目收缩次数 + 1（stub 切换）。
  assert.ok(appends >= 1 && appends <= 5,
    `去重后的追加次数应有界（实测 ${appends}，上界=首份+条目数+1(stub切换)）`)

  // 正对照：走满 10 个真实用户回合后，**下一次** assemble 会带来一次功能性变化
  // （提醒块出现），之后不再重复（不 sticky）。
  const onEvent = listeners.get('session/event') as unknown as
    (session: unknown, event: unknown) => void
  assert.ok(onEvent, '应注册 session/event 监听')
  for (let turn = 1; turn <= 10; turn++) {
    onEvent({ id: 'sess-1', header: {} }, {
      type: 'user/message',
      data: { source: { kind: 'user' }, content: [{ type: 'text', text: '第' + turn + '轮' }] },
    })
  }
  const stepOnce = async (): Promise<void> => {
    const assembly: Assembly = { contexts: [{ name: 'clock', text: '当前时间 12:00' }], variables: {} }
    await handler(assembly, { agent: { session: { id: 'sess-1', header: {} } } }, async () => assembly)
    const rendered = renderContextSnapshot(assembly)
    if (hostAppends(retained, rendered)) { appends++; retained = rendered }
  }
  // issue #739（2026-11-06）：注入去重会让「文本何时变化」不再是固定的步数点（收缩步可能与
  // 提醒步重合），因此这里**不再断言 appends 的精确增量**，改为直接断言**功能面**：
  // 提醒块出现一次、下一步消失（不 sticky）。这正是 #645 要保证的性质，且不受注入去重影响。
  const ctxNames = (a: Assembly): string[] => (a.contexts ?? []).map((c) => c.name)
  const stepCtx = async (): Promise<string[]> => {
    const assembly: Assembly = { contexts: [{ name: 'clock', text: '当前时间 12:00' }], variables: {} }
    await handler(assembly, { agent: { session: { id: 'sess-1', header: {} } } }, async () => assembly)
    const rendered = renderContextSnapshot(assembly)
    if (hostAppends(retained, rendered)) { appends++; retained = rendered }
    return ctxNames(assembly)
  }
  const firstTurn = await stepCtx()
  assert.ok(firstTurn.includes('lingshu:turn-reminder'), '第 10 回合后的首次 assemble 应带提醒块')
  const secondTurn = await stepCtx()
  assert.ok(!secondTurn.includes('lingshu:turn-reminder'), '提醒只出现一步（不 sticky）')
})

test('② 记忆真变了才追加：内容变化 → 恰好多一份；之后再次稳定', async () => {
  payload = {
    count: 2, limit: 4,
    items: [
      { id: 'n1', layer: 'contextual', start: 1, end: 2, preview: '记忆1：用户喜欢猫' },
      { id: 'n2', layer: 'knowledge', start: 3, end: 4, preview: '记忆2：上次聊了排序' },
    ],
  }
  const { listeners } = makeCtx()
  const handler = listeners.get('system-prompt/assemble')!
  const run = async (): Promise<string> => {
    const assembly: Assembly = { contexts: [{ name: 'clock', text: '当前时间 12:00' }], variables: {} }
    await handler(assembly, {}, async () => assembly)
    return renderContextSnapshot(assembly)
  }

  let retained: string | undefined = undefined
  let appends = 0
  const step = (text: string): void => { if (hostAppends(retained, text)) { appends++; retained = text } }

  step(await run())                      // 首份
  step(await run())                      // 第二遍：同一批 => 占位（文本变了，+1）
  // issue #739：首轮 full、次轮 stub —— 这一次文本变化是**设计内**的（去掉复述原料），
  // 之后占位恒定不再追加。故此处为 2 而非 1。
  assert.equal(appends, 2, '首轮 full + 次轮 stub 各一份；之后不应再追加')

  payload = {
    count: 1, limit: 4,
    items: [{ id: 'n3', layer: 'knowledge', start: 9, end: 9, preview: '记忆3：新写入的知识节点' }],
  }
  step(await run())                      // 变了
  assert.equal(appends, 3, '记忆变化应恰好多一份快照（在 full+stub 之后 +1）')
  assert.ok(retained?.includes('记忆3'), '新快照应含最新记忆')

  step(await run())                      // 再次稳定
  step(await run())
  // 变化后的第一次 full（+1）+ 紧接的 stub 切换（+1）= 共 4；此后占位恒定。
  assert.equal(appends, 4, '稳定后不应继续追加（full + 一次 stub 切换后恒定）')
})

test('③ 对照：跳过 push 的旧策略会把快照数翻倍（证明「照旧 push」是必需的而非装饰）', async () => {
  // 复刻 v0.4.8 旧实现：内容未变则跳过 push，每 8 步强制补一次（RECALL_REPUSH_EVERY=8）。
  const blockText = (): string => '【灵枢最近记忆】\n- [contextual] 记忆1：用户喜欢猫'
  let retained: string | undefined
  let appends = 0
  let lastText = ''
  let skippedSincePush = 0
  const oldPush = (text: string): boolean => {
    if (!text) return false
    if (text !== lastText) return true
    return skippedSincePush >= 8
  }

  for (let step = 0; step < 16; step++) {
    let pushed = false
    if (oldPush(blockText())) { lastText = blockText(); skippedSincePush = 0; pushed = true } else { skippedSincePush += 1 }
    const assembly: Assembly = {
      contexts: [
        { name: 'clock', text: '当前时间 12:00' },
        ...(pushed ? [{ name: 'lingshu:auto-recall', text: blockText() }] : []),
      ],
      variables: {},
    }
    const rendered = renderContextSnapshot(assembly)
    if (hostAppends(retained, rendered)) { appends++; retained = rendered }
  }
  // 旧策略：每次自愈 = 「补上」+「下一步又跳过」两份快照；16 步至少 3 次跳变。
  assert.ok(appends >= 3, `旧策略在 16 步内应产生多次快照追加（实测 ${appends} 次）`)
})

test('④ 记忆为空 / 召回失败：不注入、不抛错、next 照常', async () => {
  payload = { count: 0, limit: 4, items: [] }
  const { listeners } = makeCtx()
  const handler = listeners.get('system-prompt/assemble')!
  const assembly: Assembly = { contexts: [{ name: 'clock', text: '当前时间 12:00' }], variables: {} }
  let nextCalled = false
  await handler(assembly, {}, async () => { nextCalled = true; return assembly })
  assert.equal(assembly.contexts.length, 1, '空记忆不应注入块')
  assert.ok(nextCalled, 'next 必须被调用')

  const listeners2 = new Map<string, (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>>()
  const ctx2 = {
    logger: { info: () => {}, warn: () => {} },
    on(ev: string, fn: never) { listeners2.set(ev, fn as never) },
  } as never
  installMemoryHooks(ctx2, {
    isReady: () => true,
    async timeline() { throw new Error('认知图不可用') },
  } as never, {
    userMessage: true, assistantMessage: false, toolResult: false,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4, desensitize: true,
  })
  const assembly2: Assembly = { contexts: [], variables: {} }
  let next2 = false
  await listeners2.get('system-prompt/assemble')!(assembly2, {}, async () => { next2 = true; return assembly2 })
  assert.equal(assembly2.contexts.length, 0, '失败时不应注入')
  assert.ok(next2, '失败时 next 仍须被调用')
})
