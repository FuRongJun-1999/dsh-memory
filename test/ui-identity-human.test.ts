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

test('S4 通用价值观直接引自《智能论 3.4》§2.1（防双副本漂移）', () => {
  const theory = readFileSync(join(root, 'docs/theory/智能论3.4.md'), 'utf8')
  const quote = '通过熵管理维持自身结构完整，在适当条件下缩小或扩大信息差，以建立并维持值得信任的协作关系。'
  assert.ok(theory.includes(quote), '理论文档里找不到该句——引用已漂移，需同步更新界面文案')
  assert.ok(app.includes(quote), '界面未引用该句')
  assert.ok(app.includes('universalValuesCard'), '自我认知页缺通用价值观卡')
  assert.ok(theory.includes('保持对未知的好奇') && app.includes('保持对未知的好奇'),
    '第一定律需两侧都在')
})

test('S5 锚点正文按字段拆行（价值观不埋在整段里）', () => {
  const blk = app.slice(app.indexOf('    self_profile:'), app.indexOf('    self_state:'))
  assert.ok(blk.includes('/;'), '锚点正文需按分号拆字段')
  assert.ok(blk.includes('eyebrow'), '字段需小标题而非一整段')
})

test('S6 状态值说人话（unknown → 未登记），节点数标明口径', () => {
  assert.ok(app.includes('function humanState('), '缺 humanState')
  assert.ok(app.includes("unknown:'未登记'"), '缺 unknown → 未登记 映射')
  const blk = app.slice(app.indexOf('    self_profile:'), app.indexOf('    self_state:'))
  assert.ok(blk.includes('humanState(s.position)'), '列表态位置需人话化')
  assert.ok(blk.includes('身份面节点'), '节点数字段需写明是身份面口径')
})

test('S7 展示名从数据取（锚点里的「身份=X」），不硬编码', () => {
  assert.ok(app.includes('function displayNameFromAnchor('), '缺 displayNameFromAnchor')
  const blk = app.slice(app.indexOf('    self_profile:'), app.indexOf('    self_state:'))
  assert.ok(blk.includes('displayNameFromAnchor('), '画像标题应优先用锚点里的身份名')
  assert.ok(!/lingshu['\"]?s*:s*['\"]灵枢/.test(app), '不得硬编码 lingshu→灵枢 映射')
})

test('S8 结果卡标题不与命令面板重复', () => {
  const blk = app.slice(app.indexOf('    self_profile:'), app.indexOf('    self_state:'))
  assert.ok(blk.includes("'读取结果 · 身份档案'"), '结果卡标题应区别于命令面板')
})
