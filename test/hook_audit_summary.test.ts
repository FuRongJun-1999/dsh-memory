/**
 * #606：关闭/更新时的一行审计计数。作者：fladyck。
 * 临时目录隔离盘面；真实 Cordis 覆盖卸载/更新，故障样本覆盖静默降级。
 */
import { test, type TestContext } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import { installMemoryHooks } from '../src/hooks.ts'

const EXPECTED = 'dsh-memory: 自动记忆审计（累计）written=6 filtered=15 skipped=24'
function state() {
  return {
    counts: {
      written: { user: 1, assistant: 2, tool: 3 },
      filtered: { subagent: 4, relay: 5, kind: 6 },
      skipped: { sanitized: 7, not_ready: 8, failed: 9 },
    },
    last: [{ text: 'PRIVATE_BODY_SENTINEL\n伪造日志', kind: 'PRIVATE_KIND_SENTINEL' }],
    extra: 'PRIVATE_EXTRA_SENTINEL',
  }
}
function fixture(t: TestContext) {
  const dir = mkdtempSync(join(tmpdir(), 'dsh-audit-summary-'))
  t.after(() => rmSync(dir, { recursive: true, force: true }))
  return join(dir, 'audit.json')
}
function mount(auditPath: string, info: (message: string) => void = () => {}, graph: object | null = {}) {
  return installMemoryHooks({
    logger: { info, warn: () => {} },
    on: () => {},
  } as never, graph as never, {
    userMessage: true, assistantMessage: false, toolResult: false, importance: 0.6,
    autoRecall: false, autoRecallLimit: 4, desensitize: true, auditPath,
    contextWindow: { enabled: false, turns: 10 },
  })
}

test('S1 有效盘面：运行时安静，收尾恰一行、只含三项计数且不改文件', (t) => {
  const file = fixture(t)
  const raw = JSON.stringify(state())
  writeFileSync(file, raw, 'utf8')
  const logs: string[] = []
  const close = mount(file, (message) => logs.push(message))
  assert.deepEqual(logs, [])
  assert.equal(typeof close, 'function', '自动记忆钩子应返回收尾函数')
  close()
  assert.deepEqual(logs, [EXPECTED])
  assert.equal(logs.join('').includes('PRIVATE_'), false)
  assert.equal(logs[0]!.split(/\r?\n/).length, 1)
  assert.equal(readFileSync(file, 'utf8'), raw, '读取摘要不得改写盘面')
  close()
  assert.deepEqual(logs, [EXPECTED], '重复收尾不得重复输出')
})

test('S2 收尾重读最新盘面，路径与记录器一致（去首尾空白）', (t) => {
  const file = fixture(t)
  writeFileSync(file, JSON.stringify(state()), 'utf8')
  const logs: string[] = []
  const close = mount('  ' + file + '  ', (message) => logs.push(message))
  const newer = state()
  newer.counts.written.user = 10
  writeFileSync(file, JSON.stringify(newer), 'utf8')
  close()
  assert.deepEqual(logs, [EXPECTED.replace('written=6', 'written=15')])
})

const invalid: Array<[string, unknown]> = [
  ['根为 null', null], ['根为数组', []], ['缺 counts', {}],
  ['缺 bucket', { counts: { written: {} } }],
  ['bucket 为数组', { counts: { ...state().counts, written: [1, 2, 3] } }],
]
for (const [label, bad] of [
  ['负数', -1], ['小数', 1.5], ['字符串', '4'], ['布尔', true],
  ['null', null], ['溢出整数', Number.MAX_SAFE_INTEGER + 1],
] as const) {
  const data = state()
  ;(data.counts.written as Record<string, unknown>).user = bad
  invalid.push([label, data])
}
const overflow = state()
overflow.counts.written.user = Number.MAX_SAFE_INTEGER
invalid.push(['合计溢出', overflow])
for (const [label, data] of invalid) {
  test('S3 坏计数安静降级：' + label, (t) => {
    const file = fixture(t)
    writeFileSync(file, JSON.stringify(data), 'utf8')
    const logs: string[] = []
    const close = mount(file, (message) => logs.push(message))
    assert.doesNotThrow(() => close())
    assert.deepEqual(logs, [])
  })
}

test('S4 文件缺失、坏 JSON 和不可读路径均不抛错、不提示', (t) => {
  const file = fixture(t)
  for (const kind of ['missing', 'json', 'directory']) {
    if (kind === 'json') writeFileSync(file, '{broken', 'utf8')
    const logs: string[] = []
    const target = kind === 'directory' ? join(file, '..') : file
    const close = mount(target, (message) => logs.push(message))
    assert.doesNotThrow(() => close(), kind)
    assert.deepEqual(logs, [], kind)
  }
})

test('S5 零计数正常显示；关闭认知图时不展示陈旧文件', (t) => {
  const file = fixture(t)
  const zero = state()
  for (const bucket of Object.values(zero.counts)) {
    for (const key of Object.keys(bucket)) (bucket as Record<string, number>)[key] = 0
  }
  writeFileSync(file, JSON.stringify(zero), 'utf8')
  const logs: string[] = []
  mount(file, (message) => logs.push(message))()
  assert.deepEqual(logs, [EXPECTED.replace('written=6 filtered=15 skipped=24', 'written=0 filtered=0 skipped=0')])
  mount(file, (message) => logs.push(message), null)()
  assert.equal(logs.length, 1)
})

test('S6 日志输出失败不得阻断收尾', (t) => {
  const file = fixture(t)
  writeFileSync(file, JSON.stringify(state()), 'utf8')
  const close = mount(file, () => { throw new Error('日志不可用') })
  assert.doesNotThrow(() => close())
})

test('S7 真实 Cordis：卸载、重装更新、宿主关闭均各输出一行', async (t) => {
  const file = fixture(t)
  writeFileSync(file, JSON.stringify(state()), 'utf8')
  const root = new Context()
  t.after(() => root.fiber.dispose())
  const plugin = {
    name: 'audit-summary-lifecycle',
    apply(ctx: Context) {
      const close = installMemoryHooks(ctx, {} as never, {
        userMessage: false, assistantMessage: false, toolResult: false, importance: 0.6,
        autoRecall: false, autoRecallLimit: 4, desensitize: true, auditPath: file,
      })
      ctx.effect(() => close)
    },
  }
  const summaries = () => root.logger.buffer.filter((m) => m.args[0] === EXPECTED)
  const first = await root.plugin(plugin)
  assert.equal(summaries().length, 0)
  await first.dispose()
  await first.dispose()
  assert.equal(summaries().length, 1)
  const updated = await root.plugin(plugin)
  assert.equal(summaries().length, 1, '更新重新加载时不主动输出')
  await updated.dispose()
  assert.equal(summaries().length, 2)
  await root.plugin(plugin)
  await root.fiber.dispose()
  assert.equal(summaries().length, 3, '宿主关闭时也应收尾')
})
