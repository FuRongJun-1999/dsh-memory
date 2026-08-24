/**
 * verify_fixes.ts · P1 修复验证（GPT 审查后修改）
 * ① signal 取消 → bridge callTool reject（不等待）
 * ② combineVerdict：质疑→needs_revision / whitebox_error→fail-closed / 不同意→needs_revision
 * ③ safeTaskId：路径穿越拒绝
 * ④ ensureHarness：错误 python 路径 → failed（不崩 Node）
 * ⑤ isToolConcurrencySafe：只读 true / 写操作 false
 */
import { LingshuBridge } from '../src/bridge.ts'
import { combineVerdict, safeTaskId, ensureHarness, type VerifyResult } from '../src/mutual.ts'
import { isToolConcurrencySafe } from '../src/tools.ts'
import { join } from 'node:path'
import * as os from 'node:os'
import * as path from 'node:path'

const MOCK = join(process.cwd(), 'test', 'mock_mcp.py')
let pass = 0, fail = 0
function check(name: string, ok: boolean, detail = ''): void {
  if (ok) pass++; else fail++
  console.log(`[${ok ? '✓' : '✘'}] ${name}${detail ? ' — ' + detail : ''}`)
}

async function main(): Promise<void> {
  // ① signal 取消
  const bridge = new LingshuBridge({
    python: 'python', args: [MOCK], env: {}, cwd: process.cwd(),
    timeoutMs: 5000, maxRetryDelayMs: 2000,
  })
  bridge.start()
  await bridge.waitReady()
  const ac = new AbortController()
  const call = bridge.callTool('slow_tool', {}, ac.signal)
  setTimeout(() => ac.abort(), 100)
  const t0 = Date.now()
  let cancelled = false
  try {
    await call
  } catch (err) {
    cancelled = (err as Error).message.includes('取消')
  }
  const cancelMs = Date.now() - t0
  check('① signal 取消 → reject（不等待 slow_tool）', cancelled && cancelMs < 3000, `in ${cancelMs}ms`)
  bridge.dispose()

  // ② combineVerdict
  const wBase: VerifyResult['whitebox'] = { judgment: '采纳', best: 'x', d_norm: 0.9, record_id: 'r1' }
  check('②a 白箱采纳+复核质疑 → needs_revision',
    combineVerdict({ ...wBase }, { conclusion: '质疑：证据不足', reason: '' }) === 'needs_revision')
  check('②b 白箱采纳+复核同意 → pass',
    combineVerdict({ ...wBase }, { conclusion: '同意', reason: '' }) === 'pass')
  check('②c 白箱采纳+复核不同意 → needs_revision（不同意含「同意」子串不误判）',
    combineVerdict({ ...wBase }, { conclusion: '不同意：方法不适用', reason: '' }) === 'needs_revision')
  check('②d 白箱 whitebox_error → fail-closed（needs_revision，不因复核同意而 pass）',
    combineVerdict({ judgment: 'whitebox_error: boom', best: '', d_norm: -1, record_id: '' },
      { conclusion: '同意', reason: '' }) === 'needs_revision')
  check('②e 白箱不确定+复核质疑 → needs_revision（质疑是分歧非通过）',
    combineVerdict({ judgment: '证据不足', best: '', d_norm: -1, record_id: '' },
      { conclusion: '质疑', reason: '' }) === 'needs_revision')

  // ③ safeTaskId
  check('③a 正常 id 通过', safeTaskId('task-abc_123.4') === true)
  check('③b 路径穿越拒绝', safeTaskId('/../../../outside') === false)
  check('③c 含 .. 拒绝', safeTaskId('a..b') === false)
  check('③d 超长拒绝', safeTaskId('x'.repeat(100)) === false)

  // ④ ensureHarness 错误路径不崩 Node
  const badPy = 'C:/definitely-not-a-python-binary'
  const r = await ensureHarness(badPy, { heartbeatMs: 0, warnMs: 0, deadMs: 0, workingFactor: 1, restartCooldownMs: 0, netDir: path.join(os.tmpdir(), `lingxu-verify-${Date.now()}`) })
  check('④ 错误 python → failed（不崩 Node）', r === 'failed', `got ${r}`)

  // ⑤ 并发安全分类
  check('⑤a 读工具 search → 并发安全', isToolConcurrencySafe('search') === true)
  check('⑤b 写工具 remember → 不并发', isToolConcurrencySafe('remember') === false)
  check('⑤c 写工具 relate → 不并发', isToolConcurrencySafe('relate') === false)
  check('⑤d 读工具 think → 并发安全', isToolConcurrencySafe('think') === true)

  console.log(`\nP1 验证: ${pass}/${pass + fail} 通过`)
  process.exit(fail > 0 ? 1 : 0)
}

main().catch((err) => { console.error('异常:', err); process.exit(1) })
