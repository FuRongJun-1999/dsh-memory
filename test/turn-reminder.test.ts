import { test } from 'node:test'
import assert from 'node:assert/strict'
import { shouldRemindTurn, formatTurnReminder } from '../src/hooks.ts'

// 纪律第 16 条「长会话节奏」：每 10 轮提醒一次间歇归档。
// zcode 端由 scripts/zcode_window_hook.py 实现；DSH 端此前没有 → 本组回归。
test('逢十轮判定：9/11 不提醒，10/20 提醒', () => {
  for (const n of [1, 9, 11, 19]) assert.equal(shouldRemindTurn(n), false, `n=${n} 不应提醒`)
  for (const n of [10, 20, 30]) assert.equal(shouldRemindTurn(n), true, `n=${n} 应提醒`)
})

test('非有限值不提醒（防 NaN 触发）', () => {
  assert.equal(shouldRemindTurn(Number.NaN), false)
  assert.equal(shouldRemindTurn(Number.POSITIVE_INFINITY), false)
})

test('提醒文本含六要素/读回/id 三要件', () => {
  const s = formatTurnReminder(10)
  assert.ok(s.includes('间歇归档'), '应点名间歇归档')
  assert.ok(s.includes('第 16 条'), '应引用纪律条号')
  assert.ok(s.includes('读回'), '应要求读回确认')
  assert.ok(s.includes('id'), '应要求给出节点 id 作为证据')
})