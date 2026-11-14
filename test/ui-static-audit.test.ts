/**
 * 守卫 · 灵枢 Web 界面静态体检（#700 之后的界面修复批次）。
 *
 * 这里钉住的是**已经从代码里取证过**的缺陷，不是风格偏好：
 *  D1 排版错乱根因：`.node-button{display:block}` 覆盖了 `.row-item{display:flex}`
 *     —— 同一元素两条 display 规则，后者胜 ⇒ 圆点/时间/正文竖排。
 *  D2 「有数据却显示空」：rowsOf 的白名单缺 subjects/pending/hits 等键。
 *  D3 「点了没反应」：表单键盘提交时 e.submitter 可为 null ⇒ 旧 execute 直接抛错。
 *  D4 版本号硬编码 0.8.1（package.json 已 0.10.3）⇒ 由 meta 填充。
 *  D5 默认关的面（stg state_chain）必须**如实说明**是开关未开，而不是表现成故障。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const css = readFileSync(join(root, 'web/style.css'), 'utf8')
const app = readFileSync(join(root, 'web/app.js'), 'utf8')
const html = readFileSync(join(root, 'web/index.html'), 'utf8')

test('D1 .node-button 不得覆盖 .row-item 的 flex 布局', () => {
  assert.ok(!/\.node-button\{[^}]*display:\s*block/.test(css),
    '.node-button 里出现 display:block 会把 .row-item 的 flex 覆盖掉（排版错乱的根因）')
  assert.ok(/\.row-item\.node-button\{[^}]*display:\s*flex/.test(css),
    '需要 .row-item.node-button 显式兜底 flex，避免依赖书写顺序')
})

test('D2 rowsOf 覆盖真实回执里的列表键（subjects/pending/hits）', () => {
  for (const key of ['subjects', 'pending', 'hits']) {
    assert.ok(app.includes(`'${key}'`), `rowsOf 缺 ${key} ⇒ 该页有数据也显示空`)
  }
  assert.ok(app.includes('Object.keys(value)'),
    'rowsOf 需要「取对象里第一个数组值」的兜底，避免新 op 形状未登记就显示空')
})

test('D3 execute 对 null 按钮加固（e.submitter 可能为空）', () => {
  assert.ok(app.includes('const btn = button || null'),
    'execute 必须容忍 button 为 null，否则键盘提交时抛错表现为「点了没反应」')
  assert.ok(!/button\.disabled=true/.test(app), '不得再直接解引用 button')
})

test('D4 版本号不得硬编码（由 meta.version 填充）', () => {
  assert.ok(!/LINGSHU \/ \d+\.\d+\.\d+/.test(html), 'index.html 不得写死版本号')
  assert.ok(html.includes('id="version"'), '需要一个可被 app.js 填充的版本占位')
  assert.ok(app.includes("meta.version"), 'app.js 应从 meta.version 取版本')
})

test('D5 默认关的能力必须如实标注前置开关', () => {
  assert.ok(app.includes('MDCG_STG_STATE=1'),
    'state_chain 默认关，界面必须说明开关而不是让用户以为坏了')
  assert.ok(app.includes('function noteOf('), '需要 noteOf 渲染前置说明')
})

test('#929 注入面不得被审计留痕（structural/rev_*）占满', () => {
  const src = readFileSync(join(root, 'src/hooks.ts'), 'utf8')
  const m = src.match(/const RECALL_SKIP_LAYERS = new Set\(\[([^\]]+)\]\)/)
  assert.ok(m, '缺 RECALL_SKIP_LAYERS 定义')
  const set = m[1]
  for (const layer of ['structural', 'rejected']) {
    assert.ok(set.includes(`'${layer}'`), `注入面未跳过 ${layer}（审计/否证会挤占预算）`)
  }
  assert.ok(src.includes('issue #929'), '需留 #929 归因注释，防止后人回退')
})

test('#929 审计留痕按**标签**拦（层黑名单不够）', () => {
  const src = readFileSync(join(root, 'src/hooks.ts'), 'utf8')
  assert.ok(src.includes("RECALL_SKIP_TAGS = new Set(['audit_trace', 'audit'])"),
    '缺 audit 标签黑名单——审计件若落别的层仍会挤占注入预算')
  assert.ok(src.includes('function recallSkipItem('), '缺统一判据函数')
  assert.ok(/recallSkipItem\(it\)/.test(src), '注入过滤须走 recallSkipItem（不得只按 layer）')
  assert.ok(src.includes('_write_review_record'), '需注明判据来源（mdcos 写入点）')
})
