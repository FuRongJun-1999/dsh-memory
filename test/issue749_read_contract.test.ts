/**
 * 守卫 · issue #749 根因：`cg(op=read)` 两条路径的**返回契约不同**，注入面只认其中一条。
 *
 * 病象（0.10.4 实测，本机）：自动注入块只含 `[contextual]` 本会话裸消息；库内 184 个
 * knowledge 节点**零浮现**。同一 query 显式 `cg(op=read)` 能 rank 命中 ⇒ 检索没坏，
 * 是注入面读错了字段。
 *
 * 根因：`src/hooks.ts` 的 #749 接线写的是
 *   `const rawItems = (kr as {items?: unknown})?.items ?? kr`
 * 即按**热层形态** `{ items: [...] }` 取值。但 `op=read` 有两条返回路径：
 *
 *   · 热层命中 `_try_hot_first`（`md_cg/mcp_server.py:2696`）
 *       `{ ok, query, k, count, items: [{ id, layer, preview, score, source }], source: 'hot', meta }`
 *   · 主库检索（`md_cg/mcp_server.py:3339`）
 *       `{ meta, results: [{ node: { id, path, frontmatter, content, verification_state },
 *                            score, state, reason, usable? }] }`
 *
 * 而热层**在运行时从未被构建**：`md_cg/hottier.py` 的 `ensure()` / `build()` 在全包
 * 非测试代码里**零调用点**（只有 `load()` / `search()` 这两个只读入口），构建脚本
 * `scripts/sync_hot_tier.py` 又没进 `package.json` 的 `files` 白名单（npm 用户拿不到）。
 * ⇒ 恒走主库分支 ⇒ `kr.items` 恒 undefined ⇒ `rawItems = kr`（一个对象，非数组）
 * ⇒ `Array.isArray` 恒 false ⇒ `knowItems` 恒空 ⇒ 本块**从发布起就没工作过**。
 *
 * 本件锁三件事：
 *   R1 主库形态 `{ meta, results: [{ node }] }` 能浮现（本件靶心）
 *   R2 热层形态 `{ items: [...] }` 仍能浮现（不许为了修主库而回归热层）
 *   R3 主库形态里 `usable === false`（issue #722 条件闸判不可用）不进注入面
 *   R4 主库形态的 `layer` 取自 `frontmatter.layer`（顶层没有 layer 字段）
 *
 * 注：`test/issue749_cross_session_knowledge.test.ts` 早先按 `{ items: [...] }` 打桩，
 * 与实现共享了同一个错误假设，故 K1「knowledge 必须出现在注入块里」一直是**假绿**。
 * 本件同时把那份 mock 校正为主库形态。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { installMemoryHooks } from '../src/hooks.ts'

interface Assembly {
  contexts: Array<{ name: string; text: string }>
  variables: Record<string, string>
}

type ReadPayload = unknown

function makeCtx(readPayload: ReadPayload): {
  listeners: Map<string, (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>>
} {
  const listeners = new Map<string, never>()
  const ctx = {
    logger: { info: () => {}, warn: () => {} },
    on(ev: string, fn: never) { listeners.set(ev, fn as never) },
  } as never
  installMemoryHooks(ctx, {
    isReady: () => true,
    async timeline() {
      // 时间线**只有本会话 contextual**——正是病象形态，knowledge 只能靠查询式检索补
      return { count: 1, limit: 4, items: [
        { id: 'c1', layer: 'contextual', start: 1, end: 2, preview: '本会话流水：今天写了个测试' },
      ] }
    },
    async read() { return readPayload },
    async remember() { return { ok: true, id: 'n1' } },
    async write() { return { ok: true } },
  } as never, {
    userMessage: true, assistantMessage: false, toolResult: false,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4, desensitize: true,
  })
  return { listeners: listeners as never }
}

async function assemble(listeners: Map<string, never>): Promise<Assembly> {
  const onEvent = listeners.get('session/event') as unknown as (s: unknown, e: unknown) => void
  assert.ok(onEvent, '应注册 session/event 监听')
  onEvent({ id: 'sess-B', header: {} }, { type: 'user/message',
    data: { source: { kind: 'user' }, content: [{ type: 'text', text: '降熵定理是什么？' }] },
  })
  const handler = listeners.get('system-prompt/assemble')!
  const a: Assembly = { contexts: [{ name: 'clock', text: 't' }], variables: {} }
  await handler(a, { agent: { session: { id: 'sess-B' } } }, async () => a)
  return a
}

function recallBlock(a: Assembly): string {
  const blk = a.contexts.find((c) => c.name === 'lingshu:auto-recall')
  return blk ? blk.text : ''
}

/** 主库路径的真实返回体（字段取自 `md_cg/mcp_server.py:1392 _node_view` + `:3339`）。 */
function mainPathPayload(): ReadPayload {
  return {
    meta: { tier: 'RRF', paths: { bm25: 50 } },
    results: [
      {
        node: {
          id: 'mem_1',
          path: 'knowledge/orphan/mem_1.md',
          frontmatter: { layer: 'knowledge', importance: 0.8, tags: ['nginx'] },
          content: '# 功能名：nginx root 指错目录导致首页 404\n\n# 生效条件：改过 nginx.conf 的 root 指令',
          verification_state: 'unverified',
        },
        score: 0.371,
        state: 'ACCEPT',
        reason: null,
      },
    ],
  }
}

test('R1 主库形态 {meta, results:[{node}]} 的 knowledge 条目必须浮现', async () => {
  const { listeners } = makeCtx(mainPathPayload())
  const body = recallBlock(await assemble(listeners))
  assert.ok(body.includes('nginx root 指错目录'),
    '主库形态的 knowledge 必须出现在注入块里（旧实现此处恒空）：' + body)
  assert.ok(body.includes('[knowledge]'),
    'layer 应取自 frontmatter.layer：' + body)
})

test('R2 热层形态 {items:[...]} 仍须浮现（不许回归）', async () => {
  const { listeners } = makeCtx({ ok: true, count: 1, source: 'hot', items: [
    { id: 'hot1', layer: 'knowledge', preview: '热层命中：多线程 MPS 推理会崩', score: 3.1, source: 'hot' },
  ] })
  const body = recallBlock(await assemble(listeners))
  assert.ok(body.includes('多线程 MPS 推理会崩'), '热层形态必须继续可用：' + body)
})

test('R3 usable === false（条件闸判不可用）不进注入面', async () => {
  const payload = mainPathPayload()
  ;(payload as { results: Array<Record<string, unknown>> }).results[0]!['usable'] = false
  const { listeners } = makeCtx(payload)
  const body = recallBlock(await assemble(listeners))
  assert.ok(!body.includes('nginx root 指错目录'),
    '条件闸判不可用的条目不得注入：' + body)
})

test('R4 主库形态的 content 被压成 preview（渲染循环只认 preview 字段）', async () => {
  const { listeners } = makeCtx(mainPathPayload())
  const body = recallBlock(await assemble(listeners))
  // 主库没有 preview 字段，若不从 content 派生则渲染循环的 `if (!prev749) continue` 会整条丢弃
  assert.ok(body.includes('# 功能名：nginx root 指错目录'),
    'content 必须能派生 preview（否则渲染循环丢弃该条）：' + body)
  assert.ok(!body.includes('\n\n'),
    'preview 应压缩空白成单行：' + body)
})

test('R5 空返回体不炸（fail-soft）', async () => {
  for (const empty of [null, undefined, {}, { meta: {}, results: [] }, []]) {
    const { listeners } = makeCtx(empty)
    const body = recallBlock(await assemble(listeners))
    assert.ok(body.includes('本会话流水'), '空返回体时时间线照常注入：' + String(empty))
  }
})
