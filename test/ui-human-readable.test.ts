/**
 * 守卫 · 自我认知 / 审核与维护 两个页面必须**人类可读**（不是甩 JSON）。
 *
 * 使用者裁定（2026-11-14）：这两个功能返回的都是 JSON，对人类不友好；改成显示 md 文档风格，
 * 只显示核心内容，按会话/时间区分。
 *
 * 约束：
 *  H1 两组预设都挂 view，且 view 有对应渲染器
 *  H2 渲染器按「时间→会话」分组（groupFeed），不是直接把对象打到页面上
 *  H3 原始回执只能折叠在 <details> 里（不隐藏、不篡改）
 *  H4 写操作（裁决 / 核验）保留原样回执——它们是机器面契约，不做美化
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const app = readFileSync(join(root, 'ui/minimal/payload/web/app.js'), 'utf8')

test('H1 自我认知与审核维护的读预设都挂 view，且有渲染器', () => {
  const views = ['self_profile', 'self_state', 'meta_report', 'whitebox',
    'review_pending', 'review_records', 'protect_stats', 'evolution', 'sustain']
  for (const v of views) {
    assert.ok(app.includes(`'${v}'`), `预设未挂 view=${v}`)
    assert.ok(new RegExp(`${v}\\s*:\\s*v?=>`).test(app), `缺渲染器 ${v}`)
  }
})

test('H2 渲染器按「时间→会话」两级分组', () => {
  assert.ok(app.includes('function groupFeed('), '缺 groupFeed')
  assert.ok(app.includes("dayOf(it?.t||it?.ts||it?.created_at)"), '缺按天分组')
  assert.ok(app.includes('sessOf(it)'), '缺按会话分组')
  assert.ok(app.includes("'今天'") && app.includes("'昨天'"), '天标签需给人话（今天/昨天/日期）')
})

test('H3 原始回执折叠而非丢弃', () => {
  assert.ok(app.includes('原始回执（机器面，未改写）'), '缺原始回执折叠区')
  assert.ok(/RENDERERS\[view/.test(app), 'execute 需按 view 选渲染器')
})

test('H4 写操作保留原样回执（不美化裁决/核验）', () => {
  const from = app.indexOf('review: {title:')
  const to = app.indexOf('};', from)
  const block = app.slice(from, to > 0 ? to : from + 4000)
  assert.ok(block.includes("op:'review',action:'decide'"), '抽段失败：没找到裁决预设')
  assert.ok(!block.includes("'review_decide'"), '裁决回执不得走人类可读渲染器（会丢机器字段）')
  assert.ok(block.includes("op:'verify'"), '核验预设应仍在同组')
})