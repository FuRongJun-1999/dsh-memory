// issue #563 ①：注入面必须**先脱敏、后截断**——截断残片不得绕过脱敏。
//
// 病象（报告，0.9.4）：`formatTimelineDecayed` / `formatSessionWindow` 先按预算截断
// preview，调用方才对整个块 `desensitize`；证件号/手机号被截断后残片不再命中规则
// （身份证 17+1 位、手机 11 位），原样进入系统提示词。
//
// 判据：把号码放在**截断边界之内、但会被切线切开**的位置（余下 ≥11 位残片），
// 格式化结果里不得出现 ≥11 位连续数字；且凭据被替换成 `[已过滤:…]` 占位。
import test from 'node:test'
import assert from 'node:assert/strict'
import { formatSessionWindow, formatTimelineDecayed } from '../src/hooks.js'

const ID = '110105199003071234' // 非真实样例（报告同款）
const PHONE = '13800138000'
const DIGIT_RUN = /\d{11,}/g

function payload(preview: string): unknown {
  return { items: [{ layer: 'contextual', preview }] }
}

function windowPayload(text: string): unknown {
  return { recent: [{ role: 'user', text }] }
}

function padTo(n: number): string {
  return 'x'.repeat(n)
}

// auto-recall 的档位预算从 160 起、每档 ×0.9（160/144/129…）；号码起点放在
// 「会用掉 14 位余量」的位置，修前必然留下 ≥11 位残片。
test('auto-recall：身份证跨 160 预算边界时不出残片', () => {
  const text = padTo(145) + ' 身份证 ' + ID + ' 结束'
  const out = formatTimelineDecayed(payload(text))
  assert.equal((out.match(DIGIT_RUN) ?? []).length, 0, '不得残留 ≥11 位数字串：' + out.slice(140))
  assert.ok(out.includes('[已过滤:身份证号]'), '占位应在预算内可见：' + out.slice(140))
})

test('auto-recall：手机号跨衰减档位（第二档 144）边界时不出残片', () => {
  // 两条：第一条占掉第一档位，第二条落在第二档（144）
  const p = { items: [
    { layer: 'contextual', preview: padTo(10) + ' 普通内容一' },
    { layer: 'contextual', preview: padTo(130) + ' 电话 ' + PHONE + ' 结束' },
  ] }
  const out = formatTimelineDecayed(p)
  assert.equal((out.match(DIGIT_RUN) ?? []).length, 0, '不得残留 ≥11 位数字串：' + out.slice(120))
  assert.ok(out.includes('[已过滤:手机号]'), '占位应在档位内可见：' + out.slice(120))
})

test('session-window：身份证跨 120 边界时不出残片', () => {
  const text = padTo(105) + ' 身份证 ' + ID + ' 结束'
  const out = formatSessionWindow(windowPayload(text), 10)
  assert.equal((out.match(DIGIT_RUN) ?? []).length, 0, '不得残留 ≥11 位数字串：' + out.slice(100))
  assert.ok(out.includes('[已过滤:身份证号]'), '占位应在单条上限内可见：' + out.slice(100))
})

test('session-window：手机号跨 120 边界时不出残片', () => {
  const text = padTo(105) + ' 电话 ' + PHONE + ' 结束'
  const out = formatSessionWindow(windowPayload(text), 10)
  assert.equal((out.match(DIGIT_RUN) ?? []).length, 0, '不得残留 ≥11 位数字串：' + out.slice(100))
  assert.ok(out.includes('[已过滤:手机号]'), '占位应在单条上限内可见：' + out.slice(100))
})

test('对照：不截断（短文本）时凭据同样被替换', () => {
  const out = formatSessionWindow(windowPayload('身份证 ' + ID + ' 电话 ' + PHONE), 10)
  assert.ok(out.includes('[已过滤:身份证号]'), '身份证应被替换')
  assert.ok(out.includes('[已过滤:手机号]'), '手机号应被替换')
  assert.equal((out.match(DIGIT_RUN) ?? []).length, 0)
})

test('对照：无凭据的普通文本不被改动（不误伤）', () => {
  const out = formatSessionWindow(windowPayload('今天把任务清单过了一遍，明天继续'), 10)
  assert.equal(out, '[user] 今天把任务清单过了一遍，明天继续')
})
