/**
 * hook_audit_observability.test.ts · 自动记忆钩子的**落盘审计**守卫（issue #56）
 *
 * 病灶（报告人 jiamajie，v0.7.1 实测）：src/hooks.ts 的三处过滤分支（子代理会话 /
 * 中继消息 / `source.kind !== 'user'`）以 ctx.logger.info 收尾——宿主 logger 不落盘，
 * 盘面完全无痕。其它插件按设计注入的 role:"user" 消息（如 @michengai/dsh-pua 的
 * PUA_RUNTIME_V1 提示）不进记忆库时，从记忆侧只能看到「少了一条」，无法区分
 * 「被设计滤除」与「写入失败/漏记」。
 *
 * 修复：新增有界落盘审计 src/lib/hook_audit.ts（**诊断面**，不改写入语义）——
 *   缺省 `~/.dsh/logs/dsh-memory-hook-audit.json`（与 lingshu-bridge-debug.log /
 *   dsh-memory-apply-error.log 同目录同惯例，README.md:110）。
 *
 * 本守卫钉住的可观测面
 * --------------------
 *   A 绿态：子代理会话 / relay / kind='plugin' 三类过滤 + 一条真人写入 +
 *     一条脱敏置空 → counts / kinds / last 逐项正确（含 kinds 缺字段记 "undefined"）；
 *   B 有界性：推 25 条过滤事件 → last.length ≤ 20（无追加式增长；计数不受截断影响）；
 *   C 隐私：各路径（写入/过滤/跳过）喂独特哨兵串 → 审计文件**全文**不得出现该串；
 *   D 静默降级：auditPath 指向不可写位置 → 事件处理不抛错、记忆写入照常
 *     （rememberCalls 计数不变）；
 *   E 跳过三因留痕：not_ready（认知图未就绪）/ failed（写入失败）各自入账；
 *   F 既有三行 ctx.logger.info 保留（in-memory 实时视图与盘面审计并存）。
 *
 * 红线①（不改写入/过滤判定）的把守分工：判据本体（三处过滤的在场/缺失/退化面）
 * 由 test/h1-source-filter.test.ts 全套继续钉住（本批一字未改判据表达式）；
 * 本文件 A1 另断言「真人写入的内容/计数/召回照旧」，即审计**不改变**行为面。
 *
 * 守卫的有效性（定点变异自证，报告留痕）：
 *   ①删掉一类计数 / ②去掉 last 截断 / ③把消息内容写进 last —— 三处各须红。
 *
 * ⚠️ 测试一律用临时目录作 auditPath（**绝不得写真实 ~/.dsh**）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installMemoryHooks, type MemoryHooksOptions } from '../src/hooks.ts'

interface Assembly {
  contexts: Array<{ name: string; text: string }>
  variables: Record<string, string>
}
type AssembleHandler = (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>
type SessionEventHandler = (session: unknown, event: unknown) => void

interface RememberCall { content: string; extra: Record<string, unknown> }
interface ReadCall { query: string; extra: Record<string, unknown> }

interface AuditEntry { ts: string; action: string; reason?: string; kind?: string; role?: string }
interface AuditFile {
  counts: {
    filtered: Record<string, number>
    written: Record<string, number>
    skipped: Record<string, number>
  }
  kinds: Record<string, number>
  last: AuditEntry[]
  updated_at: string
}

function makeGraph(o: { ready?: boolean; failRemember?: boolean } = {}) {
  const rememberCalls: RememberCall[] = []
  const readCalls: ReadCall[] = []
  const graph = {
    isReady: (): boolean => o.ready ?? true,
    async timeline() {
      return { count: 0, limit: 4, items: [] }
    },
    async remember(content: string, extra: Record<string, unknown> = {}) {
      rememberCalls.push({ content, extra })
      if (o.failRemember) throw new Error('boom')
      return { ok: true }
    },
    async read(query: string, extra: Record<string, unknown> = {}) {
      readCalls.push({ query, extra })
      return { ok: true }
    },
    async recall() { return { ok: true } },
  }
  return { graph, rememberCalls, readCalls }
}

function makeHarness(graph: object, overrides: Partial<MemoryHooksOptions> = {}) {
  const assembleHandlers: AssembleHandler[] = []
  const sessionHandlers: SessionEventHandler[] = []
  const infoLogs: string[] = []
  const warnLogs: string[] = []
  const ctx = {
    logger: {
      info: (m: string) => { infoLogs.push(String(m)) },
      warn: (m: string) => { warnLogs.push(String(m)) },
    },
    on(ev: string, fn: unknown) {
      if (ev === 'system-prompt/assemble') assembleHandlers.push(fn as AssembleHandler)
      else if (ev === 'session/event') sessionHandlers.push(fn as SessionEventHandler)
    },
  }
  installMemoryHooks(ctx as never, graph as never, {
    userMessage: true, assistantMessage: true, toolResult: true,
    importance: 0.6, autoRecall: false, autoRecallLimit: 4, desensitize: false,
    ...overrides,
  })
  const send = (session: unknown, event: unknown): void => {
    assert.ok(sessionHandlers[0], '应注册 session/event 监听')
    for (const h of sessionHandlers) h(session, event)
  }
  return { send, infoLogs, warnLogs }
}

/** user/message 事件；`source` 可注入任意形态（含缺字段）。 */
const userEvent = (text: string, source: unknown = { kind: 'user' }) => ({
  type: 'user/message',
  data: { source, content: [{ type: 'text', text }] },
})

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0))

/** 建一个隔离的临时目录（auditPath 的父目录），返回 { dir, auditPath }。 */
function tmpAuditDir(): { dir: string; auditPath: string } {
  const dir = mkdtempSync(join(tmpdir(), 'dsh-hook-audit-'))
  return { dir, auditPath: join(dir, 'dsh-memory-hook-audit.json') }
}

/** 读审计文件；不存在即断言失败（点名「审计文件应在处理事件后产出」）。 */
function readAudit(path: string): AuditFile {
  assert.ok(existsSync(path), `审计文件未产生：${path}（三处过滤/写入/跳过路径必须落盘留痕）`)
  return JSON.parse(readFileSync(path, 'utf8')) as AuditFile
}

function cleanup(dir: string): void {
  try { rmSync(dir, { recursive: true, force: true }) } catch { /* 清理失败忽略 */ }
}

/** 断言条目除 ts 外的字段（ts 单独按 ISO 形态断言，避免时钟噪声）。 */
function expectEntry(entry: AuditEntry, expected: Omit<AuditEntry, 'ts'>): void {
  assert.match(entry.ts, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/, 'ts 应为 ISO 时间戳')
  const { ts: _ts, ...rest } = entry
  assert.deepEqual(rest, expected)
}

// ---------------------------------------------------------------- A 绿态

test('A1 绿态：三类过滤 + 真人写入 + 脱敏置空 → counts/kinds/last 逐项正确', async () => {
  const { dir, auditPath } = tmpAuditDir()
  try {
    const { graph, rememberCalls, readCalls } = makeGraph()
    const { send } = makeHarness(graph, { desensitize: true, auditPath })
    // ① 子代理会话（会话级过滤——不进消息级，故不进 kinds）
    send({ id: 'sess_sub', header: { origin: 'subagent' } }, userEvent('委派指令：帮我改这个文件'))
    // ② 中继消息（kind=user + form=relay）
    send({ id: 'sess_A' }, userEvent('另一个 agent 的委派', { kind: 'user', form: 'relay' }))
    // ③ 插件注入（kind=plugin；@michengai/dsh-pua 一类注入即此形态）
    send({ id: 'sess_A' }, userEvent('插件注入提示', { kind: 'plugin', plugin: 'dsh-pua' }))
    // ④ 真人写入
    send({ id: 'sess_A' }, userEvent('真人输入'))
    // ⑤ 脱敏置空（纯凭据消息 → 不写）
    send({ id: 'sess_A' }, userEvent('password: hunter2secret'))
    await flush()

    const audit = readAudit(auditPath)
    // counts 逐项
    assert.deepEqual(audit.counts.filtered, { subagent: 1, relay: 1, kind: 1 }, '三处过滤分支各计一次')
    assert.deepEqual(audit.counts.written, { user: 1, assistant: 0, tool: 0 }, '成功发起的写入按 role 计')
    assert.deepEqual(audit.counts.skipped, { sanitized: 1, not_ready: 0, failed: 0 }, '跳过按成因计')
    // kinds：进入消息级处理的每条事件的 source.kind 分布（含被滤与放行；子代理会话不进）
    assert.deepEqual(audit.kinds, { user: 3, plugin: 1 }, 'kind 分布覆盖被滤与放行（relay/user/真人各 1 + plugin 1）')
    // last：最近条目逐条（action ∈ filtered/written/skipped）
    assert.equal(audit.last.length, 5, '五类事件各留一条')
    expectEntry(audit.last[0]!, { action: 'filtered', reason: 'subagent' })
    expectEntry(audit.last[1]!, { action: 'filtered', reason: 'relay', kind: 'user' })
    expectEntry(audit.last[2]!, { action: 'filtered', reason: 'kind', kind: 'plugin' })
    expectEntry(audit.last[3]!, { action: 'written', role: 'user' })
    expectEntry(audit.last[4]!, { action: 'skipped', reason: 'sanitized', role: 'user' })
    assert.match(audit.updated_at, /^\d{4}-\d{2}-\d{2}T/, 'updated_at 应为 ISO 时间戳')
    // 红线①：审计不改变行为面——真人写入内容恰为原文，召回预热照旧一次
    assert.equal(rememberCalls.length, 1, '只有真人输入落库')
    assert.equal(rememberCalls[0]!.content, '真人输入', '写入内容照旧（审计不参与写入判定/内容）')
    assert.equal(readCalls.length, 1, '真人输入的语义召回预热照旧')
  } finally { cleanup(dir) }
})

test('A2 kinds 分布：source 缺字段/空串/非字符串一律记 "undefined"（不可辨认即无值）', async () => {
  const { dir, auditPath } = tmpAuditDir()
  try {
    const { graph } = makeGraph()
    const { send } = makeHarness(graph, { auditPath })
    // 缺 source 键（B4 形态：显式 undefined 会触发默认参数 = {kind:'user'}）
    send({ id: 'sess_A' }, { type: 'user/message', data: { content: [{ type: 'text', text: '无 source' }] } })
    send({ id: 'sess_A' }, userEvent('空 kind', { kind: '' }))
    send({ id: 'sess_A' }, userEvent('非字符串 kind', { kind: 42 }))
    await flush()
    const audit = readAudit(auditPath)
    assert.equal(audit.kinds['undefined'], 3, '缺字段/空串/非字符串同记 "undefined"')
    assert.equal(audit.counts.filtered.kind, 3, '三条都被 kind 判据拦下（行为不变）')
    expectEntry(audit.last[0]!, { action: 'filtered', reason: 'kind', kind: 'undefined' })
  } finally { cleanup(dir) }
})

// ---------------------------------------------------------------- B 有界性

test('B1 有界：推 25 条过滤事件 → last 截断到 ≤ 20（计数不受截断影响）', async () => {
  const { dir, auditPath } = tmpAuditDir()
  try {
    const { graph } = makeGraph()
    const { send } = makeHarness(graph, { auditPath })
    for (let i = 0; i < 25; i += 1) {
      send({ id: 'sess_A' }, userEvent(`插件注入 ${i}`, { kind: 'plugin' }))
    }
    await flush()
    const audit = readAudit(auditPath)
    assert.equal(audit.last.length, 20, `last 必须有界（≤20），实际 ${audit.last.length}`)
    assert.equal(audit.counts.filtered.kind, 25, '计数不受 last 截断影响')
    assert.equal(audit.kinds['plugin'], 25, 'kind 分布不受 last 截断影响')
    assert.equal(audit.last[0]!.reason, 'kind')
    assert.equal(audit.last[audit.last.length - 1]!.reason, 'kind')
  } finally { cleanup(dir) }
})

// ---------------------------------------------------------------- C 隐私

test('C1 隐私：各路径喂独特哨兵串 → 审计文件全文不得出现该串', async () => {
  const { dir, auditPath } = tmpAuditDir()
  try {
    const CANARY = 'AUDIT_CANARY_7f21c9'
    const { graph, rememberCalls } = makeGraph()
    const { send } = makeHarness(graph, { desensitize: true, auditPath })
    send({ id: 'sess_A' }, userEvent(`真人消息 ${CANARY}`))                       // 写入路径
    send({ id: 'sess_A' }, userEvent(`中继消息 ${CANARY}`, { kind: 'user', form: 'relay' })) // relay 过滤
    send({ id: 'sess_A' }, userEvent(`插件注入 ${CANARY}`, { kind: 'plugin' }))    // kind 过滤
    send({ id: 'sess_A' }, userEvent(`password: ${CANARY}123456`))                // 脱敏置空
    await flush()
    assert.equal(rememberCalls.length, 1, '真人消息照旧写入（审计不改变判定）')
    const raw = readFileSync(auditPath, 'utf8')
    assert.ok(!raw.includes(CANARY), '审计文件必须绝不记录消息内容（写入/过滤/跳过各路径）')
  } finally { cleanup(dir) }
})

// ---------------------------------------------------------------- D 静默降级

test('D1 静默降级：auditPath 不可写 → 事件处理不抛错、记忆写入照常', async () => {
  const { dir } = tmpAuditDir()
  try {
    // 构造「不可写」：auditPath 的父路径是**文件**（mkdir/写均必失败）
    const blocker = join(dir, 'blocker')
    writeFileSync(blocker, 'x', 'utf8')
    const auditPath = join(blocker, 'dsh-memory-hook-audit.json')
    const { graph, rememberCalls, readCalls } = makeGraph()
    const { send } = makeHarness(graph, { desensitize: true, auditPath })
    assert.doesNotThrow(() => {
      send({ id: 'sess_A' }, userEvent('真人输入一'))
      send({ id: 'sess_A' }, userEvent('插件注入', { kind: 'plugin' }))
      send({ id: 'sess_A' }, userEvent('password: topsecret123'))
    }, '审计失败必须静默降级——绝不冒泡进记忆路径')
    await flush()
    assert.equal(rememberCalls.length, 1, '记忆写入照常（计数不变）')
    assert.equal(readCalls.length, 1, '召回预热照常')
    assert.ok(!existsSync(auditPath), '不可写位置不应产生半截文件')
  } finally { cleanup(dir) }
})

test('D2 静默降级：审计文件被外部写成坏 JSON → 不抛错、按空态重建', async () => {
  const { dir, auditPath } = tmpAuditDir()
  try {
    writeFileSync(auditPath, '{ 这不是 JSON', 'utf8')
    const { graph, rememberCalls } = makeGraph()
    const { send } = makeHarness(graph, { auditPath })
    assert.doesNotThrow(() => {
      send({ id: 'sess_A' }, userEvent('真人输入'))
    })
    await flush()
    assert.equal(rememberCalls.length, 1, '记忆写入照常')
    const audit = readAudit(auditPath)
    assert.equal(audit.counts.written.user, 1, '坏文件按空态重建成合法 JSON')
  } finally { cleanup(dir) }
})

// ---------------------------------------------------------------- E 跳过三因

test('E1 not_ready：认知图未就绪 → skipped.not_ready 留痕、记忆不发起', async () => {
  const { dir, auditPath } = tmpAuditDir()
  try {
    const { graph, rememberCalls } = makeGraph({ ready: false })
    const { send, warnLogs } = makeHarness(graph, { auditPath })
    send({ id: 'sess_A' }, userEvent('真人输入'))
    await flush()
    assert.equal(rememberCalls.length, 0, '未就绪不发起写入')
    const audit = readAudit(auditPath)
    assert.equal(audit.counts.skipped.not_ready, 1)
    assert.equal(audit.counts.written.user, 0)
    expectEntry(audit.last[audit.last.length - 1]!, { action: 'skipped', reason: 'not_ready', role: 'user' })
    assert.ok(warnLogs.some((m) => m.includes('认知图未就绪')), '既有告警文案照旧')
  } finally { cleanup(dir) }
})

test('E2 failed：写入失败 → skipped.failed 留痕（written 记「成功发起」）', async () => {
  const { dir, auditPath } = tmpAuditDir()
  try {
    const { graph, rememberCalls } = makeGraph({ failRemember: true })
    const { send } = makeHarness(graph, { auditPath })
    send({ id: 'sess_A' }, userEvent('真人输入'))
    await flush()
    assert.equal(rememberCalls.length, 1, '写入已发起')
    const audit = readAudit(auditPath)
    assert.equal(audit.counts.written.user, 1, 'written = 成功发起的计数')
    assert.equal(audit.counts.skipped.failed, 1, '失败后补记 skipped.failed')
    expectEntry(audit.last[audit.last.length - 1]!, { action: 'skipped', reason: 'failed', role: 'user' })
  } finally { cleanup(dir) }
})

// ---------------------------------------------------------------- F 既有日志保留

test('F1 三处过滤分支的 ctx.logger.info 保留（in-memory 视图与盘面审计并存）', async () => {
  const { dir, auditPath } = tmpAuditDir()
  try {
    const { graph } = makeGraph()
    const { send, infoLogs } = makeHarness(graph, { auditPath })
    send({ id: 'sess_sub', header: { origin: 'subagent' } }, userEvent('委派指令'))
    send({ id: 'sess_A' }, userEvent('另一个 agent 的委派', { kind: 'user', form: 'relay' }))
    send({ id: 'sess_A' }, userEvent('插件注入', { kind: 'plugin' }))
    await flush()
    assert.ok(infoLogs.some((m) => m.includes('子代理会话的自动记忆被拦')), '子代理分支 logger.info 保留')
    assert.ok(infoLogs.some((m) => m.includes('委派/中继消息的自动记忆被拦')), 'relay 分支 logger.info 保留')
    assert.ok(infoLogs.some((m) => m.includes('user/message 事件被滤（source.kind=plugin）')),
      'kind 分支 logger.info 保留（沿用原格式：source.kind=<值>）')
    assert.equal(infoLogs.length, 3, '三处各一条 info（不多不少）')
  } finally { cleanup(dir) }
})

// ---------------------------------------------------------------- G 缺省路径（源码常量，行为不可测）

test('G1 缺省审计路径 = ~/.dsh/logs/dsh-memory-hook-audit.json（与桥探针同目录同惯例）', () => {
  // 缺省路径无法在测试中**触发**（绝不得写真实 ~/.dsh），故核对源码常量字面：
  // 目录段 .dsh/logs 与文件名 dsh-memory-hook-audit.json 必须同时在场。
  const src = readFileSync(new URL('../src/lib/hook_audit.ts', import.meta.url), 'utf8')
  assert.ok(src.includes("'.dsh'") && src.includes("'logs'"), '缺省目录须为 <家目录>/.dsh/logs（与 README.md:110 同惯例）')
  assert.ok(src.includes('dsh-memory-hook-audit.json'), '缺省文件名须为 dsh-memory-hook-audit.json')
  assert.ok(src.includes('homedir()'), '缺省路径须从用户家目录解析（不写死本机绝对路径）')
})
