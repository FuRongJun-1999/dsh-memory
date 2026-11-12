import assert from 'node:assert/strict'
import { test } from 'node:test'
import { dedupeRepeatedItems } from '../src/hooks.js'

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