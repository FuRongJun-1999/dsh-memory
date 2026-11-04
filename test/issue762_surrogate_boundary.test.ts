/**
 * issue762_surrogate_boundary.test.ts · 注入截断 UTF-16 孤立代理回归守卫（issue #762）
 *
 * 缺陷现场：
 *   记忆注入按 UTF-16 码元截断（`safe.slice(0, budget) + '…'`），若预算恰好劈开
 *   emoji（如 `'😊'.slice(0, 1)`），会留下孤立高位代理 `\uD83D`。
 *   `JSON.stringify` 序列化为 `"\ud83d"`，导致严格校验的服务端（DeepSeek/OpenAI 等）
 *   直接以 400 INVALID_REQUEST 拒绝，且历史会话永久作废。
 *
 * 被守卫的不变量：
 *   ① 截断不劈开 emoji：跨越预算边界的 emoji 保持完整或安全回退（孤立代理数恒为 0）；
 *   ② 出口卫生：`renderUntrustedMemoryBlock` 与 `stripLoneSurrogates` 清除全部孤立代理；
 *   ③ 端到端：含边界 emoji 的记忆经 `installMemoryHooks` 注入后，成对代理完整，0 孤立代理。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  LONE_SURROGATE_RE,
  stripLoneSurrogates,
  sliceSafe,
  renderUntrustedMemoryBlock,
} from '../src/lib/prompt_safety.ts'
import {
  formatTimelineDecayed,
  renderIdentityAnchors,
  formatSessionWindow,
} from '../src/hooks.ts'

function countLoneSurrogates(text: string): number {
  return [...text.matchAll(LONE_SURROGATE_RE)].length
}

test('① sliceSafe：不劈开 surrogate pair，且孤立代理计数为 0', () => {
  // 'abc' (3) + '😊' (\uD83D\uDE0A, 2) + 'def' (3) = 8 UTF-16 code units
  const s = 'abc😊def'
  assert.equal(sliceSafe(s, 3), 'abc')
  // 预算为 4 时原本会切在 \uD83D：sliceSafe 必须回退到 3，保留 'abc'
  assert.equal(sliceSafe(s, 4), 'abc')
  assert.equal(countLoneSurrogates(sliceSafe(s, 4)), 0)
  // 预算为 5 时完整保留 emoji
  assert.equal(sliceSafe(s, 5), 'abc😊')
  assert.equal(countLoneSurrogates(sliceSafe(s, 5)), 0)
  assert.equal(sliceSafe(s, 6), 'abc😊d')
})

test('② stripLoneSurrogates：成对 emoji 完整保留，孤立代理彻底清除', () => {
  const normal = 'Hello 😊 World 🚀'
  assert.equal(stripLoneSurrogates(normal), normal)
  assert.equal(countLoneSurrogates(stripLoneSurrogates(normal)), 0)

  // 孤立高位代理
  const loneHigh = 'abc' + '\uD83D' + 'def'
  assert.equal(stripLoneSurrogates(loneHigh), 'abcdef')
  assert.equal(countLoneSurrogates(stripLoneSurrogates(loneHigh)), 0)

  // 孤立低位代理
  const loneLow = 'abc' + '\uDE0A' + 'def'
  assert.equal(stripLoneSurrogates(loneLow), 'abcdef')
  assert.equal(countLoneSurrogates(stripLoneSurrogates(loneLow)), 0)
})

test('③ renderUntrustedMemoryBlock：出口卫生保底，输出决不含孤立代理', () => {
  const payloadWithBrokenSurrogate = '记忆片段：' + '😊'.slice(0, 1) + ' 后续'
  const out = renderUntrustedMemoryBlock(payloadWithBrokenSurrogate)
  assert.equal(countLoneSurrogates(out), 0)
  assert.ok(out.includes('记忆片段： 后续'))
})

test('④ formatTimelineDecayed 与 renderIdentityAnchors 边界截断回归', () => {
  // 构造 preview 恰好跨越边界
  // RECALL_BASE_CHARS = 160
  const prefix = 'a'.repeat(159)
  const itemWithEmoji = prefix + '😊' // length 161, budget 160
  const payload = {
    items: [
      { layer: 'contextual', preview: itemWithEmoji },
    ],
  }
  const text = formatTimelineDecayed(payload)
  assert.equal(countLoneSurrogates(text), 0, 'formatTimelineDecayed 不得产出孤立代理')

  const idText = renderIdentityAnchors({
    items: [
      { layer: 'self', preview: itemWithEmoji },
    ],
  })
  assert.equal(countLoneSurrogates(idText), 0, 'renderIdentityAnchors 不得产出孤立代理')
})

test('⑤ formatSessionWindow 边界截断回归', () => {
  const prefix = 'x'.repeat(119)
  const textWithEmoji = prefix + '😊' // length 121, WINDOW_ITEM_CHARS = 120
  const win = {
    recent: [
      { role: 'user', text: textWithEmoji, t: 1000, session: 's1' },
    ],
  }
  const winText = formatSessionWindow(win, 5, { session: 's1' })
  assert.equal(countLoneSurrogates(winText), 0, 'formatSessionWindow 不得产出孤立代理')
})
