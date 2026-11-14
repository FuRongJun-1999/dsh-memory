/**
 * 守卫 · 身份档案必须说人话（使用者 2026-11-14 反馈截图：只显示内部 ID「self:lingshu」，
 * 还被塞进「未知时间」分组，行首一个孤零零的「—」）。
 *
 * 钉住三件事：
 *  S1 主体名要人话化（self:lingshu → 自我主体 · 灵枢），内部 ID 只作副标
 *  S2 无时间字段的面**不得**套时间分组（不出现「未知时间」）
 *  S3 列表页不预取详情；点「查看完整画像」才拉单个主体，且画像里有锚点正文
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const app = readFileSync(join(root, 'ui/minimal/payload/web/app.js'), 'utf8')

test('S1 主体名人类化（中文类型 + 名称，ID 只作副标）', () => {
  assert.ok(app.includes("const SUBJ_KIND={self:'自我主体'"), '缺中文类型映射')
  assert.ok(app.includes('function humanSubject('), '缺 humanSubject')
  const blk = app.slice(app.indexOf('    self_profile:'), app.indexOf('    self_state:'))
  assert.ok(blk.includes('humanSubject('), '身份档案未用人话名')
  assert.ok(blk.includes('主体 ID'), '内部 ID 应降为副标字段')
})

test('S2 无时间字段不得套时间分组（消除「未知时间」）', () => {
  assert.ok(app.includes('function plainFeed('), '缺 plainFeed 平铺回退')
  assert.ok(app.includes('if(!hasTime) return plainFeed(items)'), 'groupFeed 需按有无时间字段分流')
  const blk = app.slice(app.indexOf('    self_profile:'), app.indexOf('    self_state:'))
  assert.ok(!blk.includes('groupFeed('), '身份档案不该走时间分组')
})

test('S3 详情按需加载（列表不预取）', () => {
  assert.ok(app.includes('data-subject="'), '缺「查看完整画像」入口')
  assert.ok(app.includes("op:'identity',action:'profile',subject_id:sid"), '详情需带 subject_id 单独取')
  assert.ok(app.includes('锚点 ·'), '画像应展示锚点正文，而不是只列 ID')
})