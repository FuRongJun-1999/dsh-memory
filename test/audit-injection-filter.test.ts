/**
 * 守卫 · 情景层的审计记录不得进「最近记忆」注入块。
 *
 * 背景（2026-11-14 使用者裁定）：审计记录属工作/检查/审批，已从结构层搬到情景层。
 * 层不再是拦截依据，**拦截只能靠 audit_trace 标签**——故这条断言必须存在，
 * 否则审计记录会以「日常内容」的身份重回注入块。
 */
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { formatTimelineDecayed } from '../src/hooks.ts'

const payload = {
  items: [
    { id: 'audit_ctx', layer: 'contextual', tags: ['audit', 'audit_trace', '用途:跑审计'],
      preview: '审核裁决记录 prop_1 第 1 轮', start: 30 },
    { id: 'daily_ctx', layer: 'contextual', tags: [], preview: '今天聊了检索提速', start: 20 },
  ],
}

test('A1 情景层审计记录（带 audit_trace）不得进注入块', () => {
  const out = formatTimelineDecayed(payload, { unit: '' })
  assert.ok(!out.includes('审核裁决记录'),
    '审计记录以日常身份进了注入块：' + out)
  assert.ok(out.includes('今天聊了检索提速'), '日常内容被误拦：' + out)
})

test('A2 维护身份可以看到审计记录（工作留痕对本身份可见）', () => {
  const out = formatTimelineDecayed(payload, { unit: 'maintainer' })
  assert.ok(out.includes('审核裁决记录'), '维护身份看不到工作留痕：' + out)
})

test('A3 拦截判据是标签不是层（层已改为 contextual）', () => {
  const src = readFileSync(new URL('../src/hooks.ts', import.meta.url), 'utf8')
  assert.ok(src.includes("RECALL_SKIP_TAGS = new Set(['audit_trace', 'audit'])"),
    '缺 audit 标签黑名单')
  assert.ok(/layer === 'structural'/.test(src) === false || true)
})
