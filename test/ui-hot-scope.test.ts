/**
 * 守卫 · UI 首屏/检索默认走热层（性能回归护栏）。
 *
 * 实测（2026-11-14，35,300 节点真实库）：
 *   cg read   全库 29.31s  /  热层 0.27s
 *   cg route  全库 15–21s  /  热层 0.38s
 *   stg relation 全库 20–22s / 热层 0.14s
 * 故 UI 的检索必须默认 scope=hot，全库只能是用户显式选择。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('../ui/minimal/payload/web/app.js', import.meta.url), 'utf8')

test('H1 检索默认带 scope=hot（由范围选择器决定）', () => {
  assert.ok(app.includes("const scopeHot = $('hist-scope') ? $('hist-scope').value !== 'full' : true"),
    '未按范围选择器决定是否走热层')
  assert.ok(/scope:\s*'hot'/.test(app) || /scope: 'hot'/.test(app) || app.includes("scope:'hot'"),
    '检索调用未透传 scope=hot')
})

test('H2 范围选择器存在，且缺省是热层', () => {
  assert.ok(app.includes('id="hist-scope"'), '缺少检索范围选择器')
  const i = app.indexOf('id="hist-scope"')
  const seg = app.slice(i, i + 300)
  assert.ok(seg.includes('value="hot"') && seg.includes('value="full"'), '范围选项不完整')
  assert.ok(seg.indexOf('value="hot"') < seg.indexOf('value="full"'), '热层必须是第一项（缺省选中）')
})

test('H3 结果标题如实标注范围（不得把热层结果说成全库）', () => {
  assert.ok(app.includes("检索结果${scopeHot?'（热层）':'（全库）'}"),
    '结果标题未标注热层/全库')
})

test('H4 文案不再宣称“全库检索”为唯一入口', () => {
  assert.ok(!app.includes('全库检索（手动、较慢，约 10–25 秒）'), '旧文案仍在（会误导用户以为只能全库）')
  assert.ok(app.includes('热层检索约 0.3 秒'), '缺少热层耗时说明')
})
