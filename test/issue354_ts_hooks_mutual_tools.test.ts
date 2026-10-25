/**
 * 守卫 · issue #354 TS 面（P1-4 / P1-5 / P1-12 / P1-13 / P1-14 / P2-15）
 *
 * 功能名：互验判定 fail-closed、claim 盘上真源、会话窗口预算、日志与注入面脱敏、
 *         工具参数表原型防护。
 * 生效条件：`node --import tsx --test test/issue354_ts_hooks_mutual_tools.test.ts`；
 *          变异自证 `--mutate M1|M2|M3|M4|M5|M6`。
 * 子功能：
 *   P1-4  combineVerdict：NaN/±Inf/字符串/undefined/空结论/死代码倒挂/零宽/间隔号/
 *         缺 record_id 一律不得 pass（阴性对照：正常「同意」仍 pass）；
 *   P1-5  processTask：rename 后必须按**盘上** claim 送审；盘上坏 JSON 不得被消费；
 *   P1-12 formatSessionWindow：恶意超长 role 不得突破 800 字预算、不得挤出后续历史；
 *   P1-13 写入失败 warn：异常消息里的凭据原文必须被替换（且不受 desensitize 开关影响）；
 *   P1-14 auto-recall / session-window 注入面：库内凭据不得原样进模型上下文；
 *   P2-15 schemaToParameters：`__proto__` 属性必须是自有键，不得替换 spec 原型。
 * 执行：默认模式全部 PASS（退出码 0）；`--mutate` 把判据改回缺陷形态到**镜像树**
 *       （临时目录里的 src 副本）后重跑本文件，指定项必须逐项转红。
 * 验证方式：默认模式 PASS；变异模式下未变异基线 0 红、变异后指定红项全部出现。
 * 不适用条件：不覆盖 processTask 的多实例竞态（既有 rename claim 语义未改）；
 *   不判 record_id 的业务取值是否「正确」（只判存在性）；不覆盖 Rust 侧 WAL/store
 *   （另有 md_cg/test_issue354_rust_* 守卫）；TS 侧只做源码/运行期判据，不替代
 *   宿主 DSH 的真实 system-prompt 装配（本文件用桩 ctx 模拟 assemble 事件）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cpSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(REPO, 'src')
const SELF = fileURLToPath(import.meta.url)
const TSX = join(REPO, 'node_modules', 'tsx', 'dist', 'loader.mjs')

const { combineVerdict, processTask } = await import(pathToFileURL(join(SRC, 'lib', 'mutual.ts')).href) as
  typeof import('../src/lib/mutual.ts')
const { installMemoryHooks } = await import(pathToFileURL(join(SRC, 'hooks.ts')).href) as
  typeof import('../src/hooks.ts')
const { schemaToParameters } = await import(pathToFileURL(join(SRC, 'tools.ts')).href) as
  typeof import('../src/tools.ts')

const W_ADOPT = { judgment: '采纳', best: 'x', d_norm: 0.9, record_id: 'r1' }
const W_WEAK = { judgment: '证据不足', best: '', d_norm: 0.9, record_id: 'r1' }
const CRED = 'token: ABCDEFGH12345678'     // 命中「密钥」规则（标签: 值）
const CRED_SECRET = 'ABCDEFGH12345678'
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

const tmpOpts = (dir: string) => ({
  heartbeatMs: 0, warnMs: 0, deadMs: 0, workingFactor: 1, restartCooldownMs: 0, netDir: dir,
})

type AssembleHandler = (a: any, c: unknown, n: () => Promise<unknown>) => Promise<unknown>
type SessionHandler = (session: unknown, event: unknown) => void

function makeHarness(o: {
  timelinePreview: string
  rememberThrows: boolean
  recent: Array<Record<string, unknown>>
  desensitize?: boolean
  /** 以任意值拒绝（复核意见 2：Promise 可携带非 Error 值）。 */
  rejectWith?: unknown
}) {
  const assembleHandlers: AssembleHandler[] = []
  const sessionHandlers: SessionHandler[] = []
  const warns: string[] = []
  const ctx = {
    logger: { info: () => {}, warn: (m: unknown) => { warns.push(String(m)) } },
    on(ev: string, fn: unknown) {
      if (ev === 'system-prompt/assemble') assembleHandlers.push(fn as AssembleHandler)
      else if (ev === 'session/event') sessionHandlers.push(fn as SessionHandler)
    },
  }
  const graph = {
    isReady: () => true,
    async timeline() {
      return { count: 1, limit: 4, items: [{ id: 'n1', layer: 'contextual', start: 1, end: 2, preview: o.timelinePreview }] }
    },
    async sessionRecall() { return { ok: true, recent: o.recent } },
    async recentAdd() { return { ok: true } },
    async remember() {
      if ('rejectWith' in o) throw (o as { rejectWith: unknown }).rejectWith
      if (o.rememberThrows) throw new Error(`upstream rejected (${CRED})`)
      return { ok: true }
    },
    async read() { return { ok: true } },
    async recall() { return { ok: true } },
  }
  installMemoryHooks(ctx as never, graph as never, {
    userMessage: true, assistantMessage: true, toolResult: true,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4,
    desensitize: o.desensitize ?? true,
    auditPath: join(tmpdir(), `u20-hook-audit-${process.pid}.json`),
  })
  const assemble = async (): Promise<any> => {
    assert.ok(assembleHandlers[0], '应注册 system-prompt/assemble 监听')
    const a: any = { contexts: [], variables: {} }
    for (const h of assembleHandlers) await h(a, {}, async () => a)
    return a
  }
  return { assemble, sessionHandlers, warns }
}

/** 取不可信边界包裹内的载荷（只对载荷做限幅断言）。 */
function payloadOf(blockText: string): string {
  const open = '<untrusted-memory>\n'
  const i = blockText.indexOf(open)
  const j = blockText.lastIndexOf('</untrusted-memory>')
  return i >= 0 && j > i ? blockText.slice(i + open.length, j) : blockText
}

/* ————————————————— P1-4 combineVerdict ————————————————— */

test('P1-4 白箱距离非有限数值一律 needs_revision（NaN/Inf/字符串/undefined）', () => {
  const cases: Array<[string, unknown]> = [
    ['NaN', NaN], ['+Infinity', +Infinity], ['字符串 "0.5"', '0.5'], ['undefined', undefined],
  ]
  for (const [name, d] of cases) {
    const v = combineVerdict({ ...W_ADOPT, d_norm: d as number }, { conclusion: '同意', reason: '' })
    assert.equal(v, 'needs_revision', `d_norm=${name} 实测 ${v}`)
  }
})

test('P1-4 空复核结论不得 pass', () => {
  assert.equal(combineVerdict({ ...W_ADOPT }, { conclusion: '', reason: '' }), 'needs_revision')
})

test('P1-4 负向/分歧信号优先于正向词（死代码倒挂）', () => {
  assert.equal(combineVerdict({ ...W_WEAK }, { conclusion: '通过？仍有质疑', reason: '' }), 'needs_revision')
  assert.equal(combineVerdict({ ...W_ADOPT }, { conclusion: '通过？仍有质疑', reason: '' }), 'needs_revision')
})

test('P1-4 零宽字符与间隔号不得切断关键词', () => {
  assert.equal(combineVerdict({ ...W_ADOPT }, { conclusion: '质\u200b疑', reason: '' }), 'needs_revision')
  assert.equal(combineVerdict({ ...W_WEAK }, { conclusion: '不·同意', reason: '' }), 'needs_revision')
  assert.equal(combineVerdict({ ...W_ADOPT }, { conclusion: '不\ufeff同意', reason: '' }), 'needs_revision')
})

test('P1-4 缺 record_id 不得放行', () => {
  assert.equal(combineVerdict({ ...W_ADOPT, record_id: '' }, { conclusion: '同意', reason: '' }), 'needs_revision')
  assert.equal(combineVerdict({ ...W_ADOPT, record_id: '   ' }, { conclusion: '同意', reason: '' }), 'needs_revision')
})

test('P1-4 阴性对照：正常采纳 + 同意仍 pass', () => {
  assert.equal(combineVerdict({ ...W_ADOPT }, { conclusion: '同意：证据充分', reason: '' }), 'pass')
})

/* ————————————————— P1-5 processTask 盘上真源 ————————————————— */

test('P1-5 送审对象必须是盘上 claim（内存篡改不得生效）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'u20-p15-'))
  const tasksDir = join(dir, 'tasks')
  mkdirSync(tasksDir, { recursive: true })
  const onDisk = {
    id: 'forge', type: 'verify', from: 'A', to: 'B',
    payload: { claim: '盘上真实主张A', source_ref: 'ref-disk' }, status: 'pending', created_at: 1,
  }
  writeFileSync(join(tasksDir, 'task-forge.json'), JSON.stringify(onDisk), 'utf8')
  const inMemory = { ...onDisk, payload: { claim: '内存篡改主张B', source_ref: 'ref-mem' } }
  const seen: string[] = []
  const r = await processTask(inMemory as never,
    async (c: string) => { seen.push(c); return { judgment: '采纳', best: 'x', d_norm: 0.9, record_id: 'r1' } },
    async () => ({ conclusion: '同意', reason: '' }), tmpOpts(dir) as never)
  assert.equal(seen[0], '盘上真实主张A', `实测送审对象 ${JSON.stringify(seen[0])}`)
  assert.deepEqual(r!.evidence, ['ref-disk'], '证据面同样取自盘上 claim')
})

test('P1-5 盘上坏 JSON 不得被消费（不写 done、不返回结果）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'u20-p15bad-'))
  const tasksDir = join(dir, 'tasks')
  mkdirSync(tasksDir, { recursive: true })
  writeFileSync(join(tasksDir, 'task-bad.json'), '{not json', 'utf8')
  const bad = {
    id: 'bad', type: 'verify', from: 'A', to: 'B',
    payload: { claim: 'x' }, status: 'pending', created_at: 1,
  }
  await assert.rejects(processTask(bad as never,
    async () => ({ judgment: '采纳', best: 'x', d_norm: 0.9, record_id: 'r1' }),
    async () => ({ conclusion: '同意', reason: '' }), tmpOpts(dir) as never),
  '坏盘件必须抛错（claim 会 rename 回 task 供重试）')
  assert.throws(() => readFileSync(join(tasksDir, 'done-bad.json')), '不得写 done 标记')
})

/* ————————————————— P1-12 会话窗口 ————————————————— */

test('P1-12 超长 role 不得突破窗口预算、不得挤出后续历史', async () => {
  const h = makeHarness({
    timelinePreview: '正常记忆预览', rememberThrows: false,
    recent: [{ role: 'x'.repeat(3000), text: '第一条' }, { role: 'user', text: '第二条正常历史' }],
  })
  const a = await h.assemble()
  const block = a.contexts.find((c: any) => c.name === 'lingshu:session-window')?.text ?? ''
  const payload = payloadOf(block)
  assert.ok(payload.length <= 800, `窗口载荷 ${payload.length} 字（上限 800）`)
  assert.ok(payload.includes('第二条正常历史'), '后续正常历史不得被恶意条目挤出')
})

test('P1-12 阴性对照：正常窗口条目照常注入（判据非恒假）', async () => {
  const h = makeHarness({
    timelinePreview: '正常记忆预览', rememberThrows: false,
    recent: [{ role: 'user', text: '条目一' }, { role: 'assistant', text: '条目二' }],
  })
  const a = await h.assemble()
  const payload = payloadOf(a.contexts.find((c: any) => c.name === 'lingshu:session-window')?.text ?? '')
  assert.ok(payload.includes('[user] 条目一') && payload.includes('[assistant] 条目二'), `实测 ${payload}`)
})

/* ————————————————— P1-13 日志脱敏 ————————————————— */

test('P1-13 写入失败 warn 不得外泄异常消息里的凭据', async () => {
  const h = makeHarness({ timelinePreview: 'x', rememberThrows: true, recent: [] })
  h.sessionHandlers[0]!({ id: 's1' }, {
    type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text: '请记住这条' }] },
  })
  await sleep(150)
  const joined = h.warns.join(' | ')
  assert.ok(h.warns.length > 0, 'sanity：确有 warn 落面')
  assert.ok(!joined.includes(CRED_SECRET), `warn 外泄凭据原文：${joined}`)
  assert.ok(joined.includes('[已过滤:密钥]'), `应保留类别占位：${joined}`)
})

test('P1-13 日志脱敏不受 desensitize=false 影响（诊断面 fail-closed）', async () => {
  const h = makeHarness({ timelinePreview: 'x', rememberThrows: true, recent: [], desensitize: false })
  h.sessionHandlers[0]!({ id: 's2' }, {
    type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text: '请记住这条' }] },
  })
  await sleep(150)
  assert.ok(!h.warns.join(' | ').includes(CRED_SECRET), `desensitize=false 时日志仍不得泄漏：${h.warns.join(' | ')}`)
})

test('P1-13 非 Error 拒绝值（字符串/undefined）不得让错误处理路径抛出', async () => {
  // Promise 可以以任意值拒绝：`err.message` 为 undefined 时，旧实现把它交给
  // desensitize（内部 text.replace）⇒ TypeError 抛在 .catch 回调内（不在任何 try 里）
  // ⇒ unhandled rejection（Node 默认终止进程）。修后一律先安全转字符串。
  for (const rejection of ['boom-string', undefined, 42]) {
    const h = makeHarness({
      timelinePreview: 'x', rememberThrows: false, recent: [],
      rejectWith: rejection as never,
    })
    h.sessionHandlers[0]!({ id: `nr-${String(rejection)}` }, {
      type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text: '请记住这条' }] },
    })
    await sleep(120)
    const joined = h.warns.join(' | ')
    assert.ok(joined.includes('失败'), `拒绝值 ${String(rejection)}：应有 warn 落面（实测 ${joined}）`)
    assert.ok(!joined.includes('TypeError'), `拒绝值 ${String(rejection)}：不得出现 TypeError（实测 ${joined}）`)
  }
})

/* ————————————————— P1-14 注入面脱敏 ————————————————— */

test('P1-14 auto-recall 注入块不得回显库内凭据', async () => {
  const h = makeHarness({ timelinePreview: `历史记忆里含凭据 ${CRED}`, rememberThrows: false, recent: [] })
  const a = await h.assemble()
  const block = a.contexts.find((c: any) => c.name === 'lingshu:auto-recall')?.text ?? ''
  assert.ok(block.length > 0, 'sanity：auto-recall 块应存在')
  assert.ok(!block.includes(CRED_SECRET), `注入块外泄凭据：${block.slice(0, 200)}`)
  assert.ok(block.includes('[已过滤:密钥]'), '应保留类别占位')
})

test('P1-14 诚实边界：渲染文本带前缀 ⇒ 整条皆凭据时仍注入，但凭据一律被替换', async () => {
  // 复核意见 3：desensitize 的入参是**渲染后的正文**（timeline 带 `- [layer] `、
  // 窗口带 `[role] `），残渣恒非空 ⇒ 「整条皆凭据时不注入」在真实链路上不成立。
  // 真实不变量是「凭据原文不进上下文」——本断言把它钉死，避免注释再夸大。
  const h = makeHarness({
    timelinePreview: CRED, rememberThrows: false,
    recent: [{ role: 'user', text: CRED }],
  })
  const a = await h.assemble()
  const names = a.contexts.map((c: any) => c.name)
  assert.ok(names.includes('lingshu:auto-recall') && names.includes('lingshu:session-window'),
    `渲染带前缀 ⇒ 两块照常注入（实测 ${JSON.stringify(names)}）`)
  for (const n of ['lingshu:auto-recall', 'lingshu:session-window']) {
    const t = a.contexts.find((c: any) => c.name === n)?.text ?? ''
    assert.ok(!t.includes(CRED_SECRET), `${n} 外泄凭据：${t.slice(0, 200)}`)
    assert.ok(t.includes('[已过滤:密钥]'), `${n} 应保留类别占位：${t.slice(0, 200)}`)
  }
})

test('P1-14 session-window 注入块同样脱敏', async () => {
  const h = makeHarness({
    timelinePreview: '普通预览', rememberThrows: false,
    recent: [{ role: 'user', text: `窗口里也有凭据 ${CRED}` }],
  })
  const a = await h.assemble()
  const block = a.contexts.find((c: any) => c.name === 'lingshu:session-window')?.text ?? ''
  assert.ok(block.length > 0, 'sanity：窗口块应存在')
  assert.ok(!block.includes(CRED_SECRET), `窗口块外泄凭据：${block.slice(0, 200)}`)
})

test('P1-14 阴性对照：无凭据的记忆原样注入（不误伤正文）', async () => {
  const h = makeHarness({ timelinePreview: '记忆1：用户喜欢猫', rememberThrows: false, recent: [] })
  const a = await h.assemble()
  const block = a.contexts.find((c: any) => c.name === 'lingshu:auto-recall')?.text ?? ''
  assert.ok(block.includes('记忆1：用户喜欢猫'), `正常正文不得被改写：${block.slice(0, 200)}`)
})

/* ————————————————— P2-15 原型防护 ————————————————— */

test('P2-15 __proto__ 必须是自有键，不得替换参数表原型', () => {
  const schema = JSON.parse(`{
    "type": "object",
    "properties": {
      "normal": {"type": "string"},
      "__proto__": {"type": "string", "description": "poison"},
      "constructor": {"type": "number"}
    },
    "required": ["normal"]
  }`)
  const spec: any = schemaToParameters(schema)
  const keys = Object.keys(spec)
  assert.ok(keys.includes('normal') && keys.includes('__proto__') && keys.includes('constructor'),
    `实测键集 ${JSON.stringify(keys)}`)
  assert.equal(Object.getPrototypeOf(spec), null,
    `参数表原型必须为空（实测 ${JSON.stringify(Object.getPrototypeOf(spec))}）`)
  assert.ok(!(('polluted' in ({} as any))), '全局 Object.prototype 不得被污染')
})

/* ————————————————— 定点变异自证 ————————————————— */

type Mut = { desc: string; file: string; patches: Array<[string, string]>; reds: string[] }

const MUTATIONS: Record<string, Mut> = {
  M1: {
    desc: 'P1-4 白箱距离退回只判 d_norm < 0（NaN/Inf/字符串/undefined 穿透）',
    file: join('lib', 'mutual.ts'),
    patches: [[
      "if (typeof w.d_norm !== 'number' || !Number.isFinite(w.d_norm) || w.d_norm < 0) {",
      'if (w.d_norm < 0) {',
    ]],
    reds: ['P1-4 白箱距离非有限数值一律 needs_revision（NaN/Inf/字符串/undefined）'],
  },
  M2: {
    desc: 'P1-5 退回信任内存 payload（不读盘上 claim）',
    file: join('lib', 'mutual.ts'),
    patches: [[
      "const claim = (actual && typeof actual === 'object' && actual.payload\n      && typeof actual.payload.claim === 'string') ? actual.payload.claim : ''",
      'const claim = task.payload.claim',
    ]],
    reds: ['P1-5 送审对象必须是盘上 claim（内存篡改不得生效）'],
  },
  M3: {
    // 缺陷形态 = 「role 不截断」+「首条绕过总预算」两处同时存在（两处都是本修复
    // 的落点：任一保留即可挡住该攻击），故变异腿必须把两处**一起**退回修前形态。
    desc: 'P1-12 role 不截断 + 首条绕过总预算（两处一起退回修前形态）',
    file: 'hooks.ts',
    patches: [
      ["const role = String(it['role'] ?? '').trim().slice(0, WINDOW_ROLE_CHARS) || 'user'",
        "const role = String(it['role'] ?? '').trim() || 'user'"],
      ['if (next > WINDOW_MAX_CHARS) {\n      if (used === 0) continue\n      break\n    }',
        'if (used > 0 && next > WINDOW_MAX_CHARS) break'],
    ],
    reds: ['P1-12 超长 role 不得突破窗口预算、不得挤出后续历史'],
  },
  M4: {
    desc: 'P1-13 warn 退回拼接原始 err.message',
    file: 'hooks.ts',
    patches: [[
      'ctx.logger.warn(`dsh-memory: 自动记忆 ${label} 失败: ${redactForLog(err)}`)',
      'ctx.logger.warn(`dsh-memory: 自动记忆 ${label} 失败: ${err.message}`)',
    ]],
    reds: ['P1-13 写入失败 warn 不得外泄异常消息里的凭据',
      'P1-13 日志脱敏不受 desensitize=false 影响（诊断面 fail-closed）'],
  },
  M5: {
    desc: 'P1-14 auto-recall 退回未脱敏原文',
    file: 'hooks.ts',
    patches: [[
      "const recallBody = desensitize(text.slice(0, RECALL_MAX_CHARS))",
      "const recallBody = text.slice(0, RECALL_MAX_CHARS)",
    ]],
    reds: ['P1-14 auto-recall 注入块不得回显库内凭据'],
  },
  M6: {
    desc: 'P2-15 参数表退回普通对象字面量',
    file: 'tools.ts',
    patches: [[
      'const spec = Object.create(null) as Record<string, ParameterPropertySpec>',
      'const spec = {} as Record<string, ParameterPropertySpec>',
    ]],
    reds: ['P2-15 __proto__ 必须是自有键，不得替换参数表原型'],
  },
  M7: {
    desc: 'P1-13 redactForLog 退回只收 string + 调用点传 err.message（非 Error 拒绝值穿透）',
    file: 'hooks.ts',
    patches: [
      [
        'export function redactForLog(value: unknown): string {',
        'export function redactForLog(text: string): string {',
      ],
      [
        `  let text: string
  if (typeof value === 'string') {
    text = value
  } else if (value instanceof Error) {
    text = value.message
  } else if (value && typeof value === 'object'
      && typeof (value as { message?: unknown }).message === 'string') {
    text = (value as { message: string }).message
  } else {
    text = String(value)
  }
`,
        '',
      ],
      [
        'ctx.logger.warn(`dsh-memory: 短期窗口写入失败: ${redactForLog(err)}`))',
        'ctx.logger.warn(`dsh-memory: 短期窗口写入失败: ${redactForLog(err.message)}`))',
      ],
      [
        'ctx.logger.warn(`dsh-memory: 自动记忆 ${label} 失败: ${redactForLog(err)}`)',
        'ctx.logger.warn(`dsh-memory: 自动记忆 ${label} 失败: ${redactForLog(err.message)}`)',
      ],
    ],
    reds: ['P1-13 非 Error 拒绝值（字符串/undefined）不得让错误处理路径抛出'],
  },
}

function patch(src: string, from: string, to: string): string {
  // 复核意见 1：被测源文件在 Windows 工作树里是 CRLF，而锚点按 \n 写就——
  // 直接 includes 必然失配（变异腿整条失效）。故先把源文本归一化成 LF 再匹配，
  // 镜像树里按 LF 写回（只影响临时镜像，工作树不动）。
  const lf = src.replace(/\r\n/g, '\n')
  const fromLf = from.replace(/\r\n/g, '\n')
  if (!lf.includes(fromLf)) throw new Error(`变异锚点未命中：${from.slice(0, 70)}`)
  return lf.replace(fromLf, to.replace(/\r\n/g, '\n'))
}

if (process.argv.includes('--mutate')) {
  const idx = process.argv.indexOf('--mutate')
  const name = process.argv[idx + 1] || ''
  const mut = MUTATIONS[name]
  if (!mut) {
    console.log(`未知变异组 ${JSON.stringify(name)}（可选 ${Object.keys(MUTATIONS).join('/')}）`)
    process.exit(1)
  }
  const run = (root: string): { rc: number; reds: string[]; out: string } => {
    const pr = spawnSync(process.execPath, ['--import', 'tsx', '--test-reporter=tap', '--test', join(root, 'test', 'issue354_ts_hooks_mutual_tools.test.ts')],
      { cwd: REPO, encoding: 'utf8', timeout: 600000 })
    const out = `${pr.stdout ?? ''}${pr.stderr ?? ''}`
    const reds = out.split(/\r?\n/).filter((l) => l.startsWith('not ok')).map((l) => l.replace(/^not ok \d+ - /, '').trim())
    return { rc: pr.status ?? 1, reds, out }
  }
  const mirror = (): string => {
    const root = mkdtempSync(join(tmpdir(), 'u20-354ts-'))
    cpSync(SRC, join(root, 'src'), { recursive: true })
    mkdirSync(join(root, 'test'), { recursive: true })
    cpSync(SELF, join(root, 'test', 'issue354_ts_hooks_mutual_tools.test.ts'))
    // 镜像树须自带 `"type": "module"`：否则 tsx/esbuild 按 cjs 转译，本文件的
    // 顶层 await 直接报「Top-level await is currently not supported」——那不是
    // 被测缺陷，而是镜像环境缺失（实测红项会退化成「整个文件失败」）。
    writeFileSync(join(root, 'package.json'), JSON.stringify({ type: 'module' }), 'utf8')
    return root
  }
  const base = mirror()
  const mutRoot = mirror()
  try {
    const b = run(base)
    const p = join(mutRoot, 'src', mut.file)
    let text = readFileSync(p, 'utf8')
    for (const [from, to] of mut.patches) text = patch(text, from, to)
    writeFileSync(p, text, 'utf8')
    const r = run(mutRoot)
    console.log(`!! #354 TS 定点变异自证 · 组 ${name}：${mut.desc}\n`)
    console.log(`  未变异镜像基线：rc=${b.rc} 红项=${JSON.stringify(b.reds)}（须 rc=0 且 0 红）`)
    if (b.rc !== 0) console.log(b.out.slice(-2500))
    console.log(`  变异后：rc=${r.rc} 红项=${JSON.stringify(r.reds)}`)
    const hit = mut.reds.filter((x) => r.reds.includes(x))
    console.log(`  预期红项 ${JSON.stringify(mut.reds)} → 命中 ${JSON.stringify(hit)}`)
    const ok = b.rc === 0 && b.reds.length === 0 && r.reds.length > 0 && hit.length === mut.reds.length
    console.log(ok ? '\n变异自证通过：指定项逐项转红' : '\n变异自证失败：红项集合与预期不符')
    process.exit(ok ? 0 : 1)
  } finally {
    rmSync(base, { recursive: true, force: true })
    rmSync(mutRoot, { recursive: true, force: true })
  }
}
