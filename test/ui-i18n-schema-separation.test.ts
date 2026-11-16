/**
 * 守卫 · 工具说明的翻译层不许写回 schema（issue #970 使用者裁定）。
 *
 * 裁定原文（2026-11-15）：工具描述与参数说明**不在原文上改**——schema 里的中文是给模型看的，
 * 为了「别的语言也能读」而把说明翻一倍，等于给每次调用加 token，语言一多就翻倍。
 * 因此：翻译只挂在**界面**（TOOL_I18N + tTool/tOp），schema 与 tool_face.py 保持单一中文源。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('../ui/minimal/payload/web/app.js', import.meta.url), 'utf8')
const face = readFileSync(new URL('../md_cg/tool_face.py', import.meta.url), 'utf8')

test('T1 界面侧存在翻译表，且按语言分键（加语言=加一个键）', () => {
  assert.ok(app.includes('const TOOL_I18N = {'), '缺少界面侧翻译表')
  assert.ok(/TOOL_I18N\s*=\s*\{[^}]*en\s*:/.test(app), 'en 语言键缺失')
  assert.ok(app.includes('// 未来语言在此追加'), '缺少后续语言的扩展锚点说明')
})

test('T2 工具描述渲染走 tTool（缺译回退原文），不直接显示 schema 原文', () => {
  assert.ok(app.includes("$('tool-description').textContent=tTool(name, tool.description)"),
    '工具描述未走翻译层（或回退逻辑丢了）')
  assert.ok(/const tTool = \(name, original\) =>/.test(app), 'tTool 定义缺失')
  assert.ok(app.includes("|| original"), '缺译必须回退原文，不得显示空')
})

test('T3 schema 侧不得出现英文说明（原文保持单一中文源）', () => {
  // tool_face.py 里若出现成段英文说明，说明有人把译文写回了 schema
  assert.ok(!/TOOL_BRIEFS_EN|brief_en|_EN_BRIEF/.test(face),
    'tool_face.py 出现英文说明层——翻译必须留在界面侧')
})

test('T4 操作下拉只翻显示文本，value 仍是原 op 名', () => {
    const hasOpValue = app.includes('<option value="${esc(op)}">')
  const hasOpLabel = app.includes('${esc(tOp(op))}</option>')
  assert.ok(hasOpValue && hasOpLabel, 'op 选项：value 用原 op 名，显示走 tOp')
})
