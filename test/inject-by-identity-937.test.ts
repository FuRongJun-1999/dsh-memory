/**
 * 守卫 · 注入面按会话身份取数（工作留痕只给工作身份看）。
 *
 * 判据来源：会话身份五元组 `s5.<端>.<身份>.<工作区>.<时间>.<摘要>` 的第二段。
 * 维护/设计/审计/验证等身份在做事，看得见裁决与决策留痕是本分；
 * 执行者/角色扮演/使用者/未登记只看日常——这就是「工作与日常分开」。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { formatTimelineDecayed } from '../src/hooks.ts'

const payload = {
  items: [
    { id: 'audit1', layer: 'structural', tags: ['audit', 'audit_trace'], preview: '审核裁决记录 第 1 轮', start: 10 },
    { id: 'daily1', layer: 'contextual', tags: [], preview: '今天聊了界面改造', start: 20 },
  ],
}

test('K1 日常身份（未登记）：注入块不得出现工作留痕', () => {
  const out = formatTimelineDecayed(payload, { unit: '' })
  assert.ok(!out.includes('审核裁决记录'), '日常身份收到了工作留痕：' + out)
  assert.ok(out.includes('今天聊了界面改造'), '日常内容被误拦：' + out)
})

test('K2 维护身份：工作留痕可见（不得因过滤丢失）', () => {
  const out = formatTimelineDecayed(payload, { unit: 'maintainer' })
  assert.ok(out.includes('审核裁决记录'), '维护身份看不到自己的工作留痕：' + out)
})

test('K3 角色扮演身份按日常处理', () => {
  const out = formatTimelineDecayed(payload, { unit: 'roleplay' })
  assert.ok(!out.includes('审核裁决记录'), '角色扮演会话收到了工作留痕：' + out)
})

test('K4 身份取自会话标识第二段（不新增维度）', () => {
  const src = readFileSync(new URL('../src/hooks.ts', import.meta.url), 'utf8')
  assert.ok(src.includes('function sessionUnitOf('), '缺身份解析函数')
  assert.ok(/parts\[2\]/.test(src), '身份必须取五元组第二段')
  assert.ok(src.includes('formatTimelineDecayed(dedupeRepeatedItems(timelinePayload, seenMap, 2),'), '注入侧需把身份传进渲染')
})
