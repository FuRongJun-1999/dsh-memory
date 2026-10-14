/**
 * hook_receipt_audit.test.ts · 自动记忆钩子**读回执**守卫（issue #296）
 *
 * 病灶：工具面把「未落盘」的回执以 `ok:false` 返回（**不是** MCP `isError`，
 * 所以 `.catch` 收不到）。src/hooks.ts 的 `memorize()` 此前只接 `.catch`：
 *   ① 发起前先记 `audit.written(role)`（语义=「成功发起」，见 lib/hook_audit.ts:34）；
 *   ② 回执是 `ok:false` 时既不告警、也不记 `skipped.failed`。
 * 于是审计文件对一次「服务端明确说没写」的调用显示「已写入」，零告警——频率闸
 * DEFER（全库 60 秒内第 9 条起的自动记忆）、冲突 defer、#212 超限拒绝都走这条。
 *
 * 修复：`memorize()` 补读回执。`ok:false` 且 verdict 不是 MERGE/DROP（前者并入
 * 既有节点、后者零新信息，都不是失败）时记 `skipped.failed` 并 `ctx.logger.warn`；
 * 回执带 `proposed` 说明正文已转审核队列（有去向），只告警、不计 failed。
 * `written` 的语义（成功发起）**一字未改**。
 *
 * 红线（不改写入/过滤判定）：本批只加「读回执 + 留痕/告警」，不改任何写入参数、
 * 不改三处过滤、不改脱敏判定——G4/G5 钉住绿态与既有异常路径逐项不变。
 *
 * 守卫的有效性（定点变异自证，报告留痕）：
 *   ①删掉 `.then` 回执处理 → G1/G2/G5 转红；
 *   ②把 MERGE/DROP 也当失败 → G3 转红；
 *   ③`proposed` 分支也记 failed → G2 转红。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installMemoryHooks, type MemoryHooksOptions } from '../src/hooks.ts'

interface Assembly {
  contexts: Array<{ name: string; text: string }>
  variables: Record<string, string>
}
type AssembleHandler = (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>
type SessionEventHandler = (session: unknown, event: unknown) => void

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

/** 正文哨兵：审计文件与日志**全文**都不得出现它。 */
const SENTINEL = 'ZZ-正文哨兵-296-ZZ'

/** 造一个可注入回执 / 可注入异常的假 graph。 */
function makeGraph(o: { ready?: boolean; receipt?: unknown; fail?: boolean } = {}) {
  const rememberCalls: Array<{ content: string; extra: Record<string, unknown> }> = []
  const graph = {
    isReady: (): boolean => o.ready ?? true,
    async timeline() {
      return { count: 0, limit: 4, items: [] }
    },
    async remember(content: string, extra: Record<string, unknown> = {}) {
      rememberCalls.push({ content, extra })
      if (o.fail) throw new Error('boom')
      return o.receipt ?? { ok: true }
    },
    async read() { return { ok: true } },
    async recall() { return { ok: true } },
  }
  return { graph, rememberCalls }
}

function makeHarness(graph: object, overrides: Partial<MemoryHooksOptions> = {}) {
  const sessionHandlers: SessionEventHandler[] = []
  const infoLogs: string[] = []
  const warnLogs: string[] = []
  const ctx = {
    logger: {
      info: (m: string) => { infoLogs.push(String(m)) },
      warn: (m: string) => { warnLogs.push(String(m)) },
    },
    on(ev: string, fn: unknown) {
      if (ev === 'session/event') sessionHandlers.push(fn as SessionEventHandler)
    },
  }
  installMemoryHooks(ctx as never, graph as never, {
    userMessage: true, assistantMessage: true, toolResult: true,
    importance: 0.6, autoRecall: false, autoRecallLimit: 4, desensitize: false,
    // 短期窗口轨（contextWindow）与知识面写入独立成轨，本守卫只钉知识面回执：
    // 关掉它，避免它的 graph.recentAdd 告警混进 warnLogs。
    contextWindow: { enabled: false, turns: 10 },
    ...overrides,
  })
  const send = (session: unknown, event: unknown): void => {
    for (const h of sessionHandlers) h(session, event)
  }
  return { send, infoLogs, warnLogs }
}

const userEvent = (text: string) => ({
  type: 'user/message',
  data: { source: { kind: 'user' }, content: [{ type: 'text', text }] },
})

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0))

function tmpAuditDir(): { dir: string; auditPath: string } {
  const dir = mkdtempSync(join(tmpdir(), 'dsh-hook-receipt-'))
  return { dir, auditPath: join(dir, 'dsh-memory-hook-audit.json') }
}

function readAudit(path: string): AuditFile {
  assert.ok(existsSync(path), `审计文件未产生：${path}`)
  return JSON.parse(readFileSync(path, 'utf8')) as AuditFile
}

function cleanup(dir: string): void {
  try { rmSync(dir, { recursive: true, force: true }) } catch { /* 忽略 */ }
}

/** 跑一条真人 user 消息（正文含哨兵），返回审计与日志。 */
async function runOnce(receipt: unknown, o: { fail?: boolean } = {}) {
  const { dir, auditPath } = tmpAuditDir()
  const { graph, rememberCalls } = makeGraph({ receipt, fail: o.fail })
  const { send, warnLogs } = makeHarness(graph, { auditPath })
  send({ id: 'sess_A' }, userEvent('真人输入 ' + SENTINEL))
  await flush()
  const audit = readAudit(auditPath)
  const raw = readFileSync(auditPath, 'utf8')
  cleanup(dir)
  return { audit, warnLogs, raw, rememberCalls }
}

// ------------------------------------------------- G1 DEFER 回执必须留痕+告警

test('G1 ok:false + DEFER → 记 skipped.failed 并告警（修前两者皆无）', async () => {
  const { audit, warnLogs } = await runOnce({
    ok: false, verdict: 'DEFER',
    gate: { reason: 'ratelimit:contextual:user:>8in60s', limiter: 'rate' },
  })
  assert.deepEqual(audit.counts.skipped,
    { sanitized: 0, not_ready: 0, failed: 1 },
    'ok:false 的回执必须记一笔 skipped.failed（修前恒为 0）')
  const w = warnLogs.join(' | ')
  assert.match(w, /未写入/, '必须告警「未写入」：' + w)
  assert.match(w, /ratelimit:contextual:user:>8in60s/, '告警须带服务端 reason：' + w)
  const last = audit.last[audit.last.length - 1]
  assert.deepEqual({ action: last.action, reason: last.reason, role: last.role },
    { action: 'skipped', reason: 'failed', role: 'user' },
    'last 末条应是 skipped/failed/user')
})

// ------------------------------------------------- G2 已转审核队列：告警但不计 failed

test('G2 ok:false + proposed=true → 只告警「已转审核队列」，不计 failed', async () => {
  const { audit, warnLogs } = await runOnce({
    ok: false, verdict: 'DEFER', proposed: true,
    gate: { reason: 'ratelimit:contextual:user:>8in60s' },
  })
  assert.deepEqual(audit.counts.skipped,
    { sanitized: 0, not_ready: 0, failed: 0 },
    '正文有去向（审核队列）⇒ 不算失败')
  const w = warnLogs.join(' | ')
  assert.match(w, /已转审核队列/, '必须告警「已转审核队列」：' + w)
  assert.match(w, /ratelimit:contextual:user:>8in60s/, w)
})

// ------------------------------------------------- G3 MERGE/DROP 不是失败

test('G3 ok:false 但 verdict=MERGE/DROP → 不告警、不计 failed（不是失败）', async () => {
  for (const v of ['MERGE', 'DROP']) {
    const { audit, warnLogs } = await runOnce({ ok: false, verdict: v })
    assert.deepEqual(audit.counts.skipped,
      { sanitized: 0, not_ready: 0, failed: 0 },
      v + ' 不是失败，不得计入 skipped.failed')
    assert.equal(warnLogs.length, 0, v + ' 不应产生告警：' + warnLogs.join(' | '))
  }
})

// ------------------------------------------------- G4 绿态逐项不变（零变化面）

test('G4 ok:true → 无告警、无 failed、written 语义（成功发起）不变', async () => {
  const { audit, warnLogs } = await runOnce({ ok: true, id: 'n1', committed: true })
  assert.deepEqual(audit.counts.written, { user: 1, assistant: 0, tool: 0 },
    'written 仍按「成功发起」计（本批未改其语义）')
  assert.deepEqual(audit.counts.skipped, { sanitized: 0, not_ready: 0, failed: 0 })
  assert.equal(warnLogs.length, 0, '绿态不得产生告警')
})

// ------------------------------------------------- G5 既有异常路径不变

test('G5 抛异常 → 仍记 skipped.failed 并告警「失败」（.catch 路径不变）', async () => {
  const { audit, warnLogs } = await runOnce({ ok: true }, { fail: true })
  assert.deepEqual(audit.counts.skipped, { sanitized: 0, not_ready: 0, failed: 1 })
  assert.match(warnLogs.join(' | '), /失败: boom/, '既有异常告警文案不变')
})

// ------------------------------------------------- G6 隐私：告警与审计不含正文

test('G6 隐私：回执告警与审计文件全文均不含正文哨兵', async () => {
  const { audit, warnLogs, raw } = await runOnce({
    ok: false, verdict: 'DEFER',
    gate: { reason: 'ratelimit:contextual:user:>8in60s' },
  })
  assert.ok(!warnLogs.join(' | ').includes(SENTINEL), '告警不得含正文')
  assert.ok(!raw.includes(SENTINEL), '审计文件不得含正文')
  assert.ok(!JSON.stringify(audit).includes(SENTINEL), '审计结构不得含正文')
})

// ------------------------------------------------- G7 读预热（role=null）不计数

test('G7 role=null（读预热）的回执不计数', async () => {
  const { dir, auditPath } = tmpAuditDir()
  const { graph } = makeGraph({ receipt: { ok: false, verdict: 'DEFER' } })
  const { send } = makeHarness(graph, { auditPath })
  send({ id: 'sess_A' }, userEvent('真人输入 ' + SENTINEL))
  await flush()
  const audit = readAudit(auditPath)
  assert.equal(audit.counts.skipped.failed, 1,
    'role=null 的回执不得计数（应只有 user 那 1 次）')
  cleanup(dir)
})
