import assert from 'node:assert/strict'
import { test } from 'node:test'
import { dedupeRepeatedItems, deltaBlock } from '../src/hooks.js'

const payload = (previews: string[]) => ({
  items: previews.map((p) => ({ layer: 'knowledge', preview: p })),
})

test('issue #739：同一会话内同一条最多注入 2 次', () => {
  const seen = new Map<string, number>()
  const p = payload(['A', 'B'])
  const rounds = [1, 2, 3, 4].map(() => {
    const out = dedupeRepeatedItems(p, seen, 2) as { items: Array<{ preview: string }> }
    return out.items.map((i) => i.preview).join(',')
  })
  assert.deepEqual(rounds, ['A,B', 'A,B', 'A', 'A'])
})

test('issue #739：全被滤掉时保留第一条（避免整块消失）', () => {
  const seen = new Map<string, number>([['knowledge|A', 2]])
  const out = dedupeRepeatedItems(payload(['A']), seen, 2) as { items: unknown[] }
  assert.equal(out.items.length, 1)
})

test('issue #739：新条目照常进入（去重不饿死新记忆）', () => {
  const seen = new Map<string, number>([['knowledge|A', 2]])
  const out = dedupeRepeatedItems(payload(['A', 'C']), seen, 2) as { items: Array<{ preview: string }> }
  assert.deepEqual(out.items.map((i) => i.preview), ['C'])
})

test('issue #739：deltaBlock 三种模式（full / delta / stub）', () => {
  const label = '【块】'
  const full = deltaBlock(undefined, 'A\\nB', label)
  assert.equal(full.mode, 'full')
  assert.ok(full.text.startsWith(label), 'full 带标题')
  assert.ok(full.text.includes('A'))

  const same = deltaBlock('A\\nB', 'A\\nB', label)
  assert.equal(same.mode, 'stub')
  assert.ok(same.text.startsWith(label), 'stub 仍带标题（块不消失）')
  assert.ok(same.text.includes('与上一轮相同'))
  assert.ok(!same.text.includes('A\\nB'), 'stub 不重复正文（复述原料去掉）')

  const grow = deltaBlock('A\\nB', 'A\\nB\\nC', label)
  assert.equal(grow.mode, 'delta')
  assert.ok(grow.text.includes('增量'))
  assert.ok(grow.text.includes('C'))
  assert.ok(!grow.text.includes('A'), 'delta 只贴新增部分')

  const rewrite = deltaBlock('A\\nB', 'X\\nY', label)
  assert.equal(rewrite.mode, 'full', '非前缀关系（改写）回 full，不猜')
})