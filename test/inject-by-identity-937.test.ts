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

test('K5 未登记身份必须给出定义与文档链接（可排查）', () => {
  const src = readFileSync(new URL('../src/hooks.ts', import.meta.url), 'utf8')
  assert.ok(src.includes('IDENTITY_MISSING_HINT'), '缺未登记提示常量')
  assert.ok(src.includes('docs/architecture/会话身份与工作日常分离_v0.1.md'),
    '提示必须带文档路径，否则别人无从排查')
  assert.ok(src.includes('s5.<端>.<身份>.<工作区>'), '提示处需写明五元组定义')
  assert.ok(src.includes('已按「日常」处理'), '需说明当前降级行为')
  assert.ok(/identityHint\(sessionUnitOf\(sid\)\)/.test(src), '提示须按当前会话身份决定是否出现')
})

test('K6 未登记提示缺省静默、开关打开才出现、已登记时永不出现（issue #997）', async () => {
  const mod = await import('../src/hooks.ts')
  const saved = process.env.MDCG_IDENTITY_HINT
  try {
    delete process.env.MDCG_IDENTITY_HINT
    assert.equal(mod.identityHint(''), '', '缺省必须静默：日常会话解析不出身份是正常降级，不是故障')
    assert.equal(mod.identityHint('maintainer'), '')

    process.env.MDCG_IDENTITY_HINT = '1'
    assert.equal(mod.identityHint(''), mod.IDENTITY_MISSING_HINT, '开关打开时必须恢复排查提示')
    assert.equal(mod.identityHint('maintainer'), '', '已登记身份任何时候都不给提示')

    process.env.MDCG_IDENTITY_HINT = 'off'
    assert.equal(mod.identityHint(''), '', '非真值一律按关闭处理')
  } finally {
    if (saved === undefined) delete process.env.MDCG_IDENTITY_HINT
    else process.env.MDCG_IDENTITY_HINT = saved
  }
})
