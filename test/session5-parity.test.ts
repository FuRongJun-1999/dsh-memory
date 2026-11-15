/**
 * 守卫 · 端侧会话五元组与 Python 真源**逐位一致**（可复算才是身份，不是标签）。
 * 对拍方式：把同一组输入分别喂 TS 与 python 的 make_session5，比较输出字符串。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { makeSession5, isSession5, parseSession5, slugWorkspace, digestMessage } from '../src/lib/session5.ts'

const cases = [
  { harness: 'dsh', unit: 'maintainer', workspace: 'D:\\4_ai', epoch: 1791340000, msg: '灵枢的记忆该怎么分类？' },
  { harness: 'dsh', unit: 'agent', workspace: '/home/x/y', epoch: 1791340001, msg: 'hi' },
  { harness: 'zcode', unit: 'verifier', workspace: 'C-proj-app', epoch: 1791340002, msg: '第一条消息' },
]

test('S1 端侧与 Python 真源逐位一致（跨端可复算）', () => {
  const py = [
    'import sys, json',
    'sys.path.insert(0, r"D:/program/dsh-memory-main")',
    'from md_cg.session5 import make_session5',
    'cases = json.loads(sys.argv[1])',
    'print(json.dumps([make_session5(c["harness"], c["unit"], c["workspace"], c["epoch"], c["msg"]) for c in cases], ensure_ascii=False))',
  ].join('\n')
  const out = execFileSync('python', ['-X', 'utf8', '-c', py, JSON.stringify(cases)], { encoding: 'utf8' })
  const want: string[] = JSON.parse(out)
  const got = cases.map((c) => makeSession5(c.harness, c.unit, c.workspace, c.epoch, c.msg))
  assert.deepEqual(got, want, '端侧与 Python 生成的会话标识不一致')
})

test('S2 形态可解析、非法形态返回 null（不猜）', () => {
  const s = makeSession5('dsh', 'maintainer', 'D:\\4_ai', 1791340000, 'x')
  assert.ok(isSession5(s))
  const p = parseSession5(s)
  assert.equal(p?.unit, 'maintainer')
  assert.equal(parseSession5('session-abc'), null)
  assert.equal(parseSession5('s5.dsh.agent'), null)
})

test('S3 工作区 slug 归一（两种写法同值）', () => {
  assert.equal(slugWorkspace('D:\\4_ai'), slugWorkspace('D-4_ai'))
  assert.equal(slugWorkspace('/home/x/y'), 'home_x_y')
})

test('S4 首条消息摘要取前 12 位十六进制', () => {
  assert.equal(digestMessage('abc'), digestMessage('abc'))
  assert.match(digestMessage('abc'), /^[0-9a-f]{12}$/)
})

test('S5 端侧接线开关缺省关闭（不改变既有行为）', () => {
  const src = readFileSync(new URL('../src/hooks.ts', import.meta.url), 'utf8')
  assert.ok(src.includes("process.env.MDCG_SESSION5 === '1'"), '开关必须是显式启用（缺省关闭）')
  assert.ok(src.includes('function s5For('), '缺端侧接线函数')
  assert.ok(src.includes('HOST_TO_S5'), '需记住「宿主标识 → 五元组」映射，保证同会话稳定')
  assert.ok(src.includes('已写入的旧标识不回填'), '需写明存量不回填纪律')
})

test('S6 开关关闭时 s5For 不产出五元组（不猜）', () => {
  const prev = process.env.MDCG_SESSION5
  delete process.env.MDCG_SESSION5
  try {
    const s = makeSession5('dsh', 'agent', '/x', 1791340000, 'm')
    assert.ok(isSession5(s))
    // s5For 未导出：以源码断言 + 开关语义为准（行为级验证需端侧集成）
    const src = readFileSync(new URL('../src/hooks.ts', import.meta.url), 'utf8')
    assert.ok(/if \(!on\) return ''/.test(src), '开关未启用时必须返回空串而不是编造标识')
  } finally {
    if (prev !== undefined) process.env.MDCG_SESSION5 = prev
  }
})
