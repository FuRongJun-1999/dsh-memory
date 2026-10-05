/**
 * 守卫 · 复核通道异常必须 fail-closed（对应缺陷：src/lib/mutual.ts:262 查错字段，N268）
 *
 * 缺陷链条（修复前，本测实跑取证）：
 *  · `llmReview()` 的异常写在 **`l.conclusion`**（:253 `llm_error: …`），而
 *    `combineVerdict()` 的 fail-closed 判据（:262）查的是 `w.judgment`（该字段只可能由
 *    `whiteboxVerify()` 写 `whitebox_error`）——`llm_error` 分支是**死条件**；
 *  · 于是白箱「采纳」+ 复核通道抛异常时径直落到 `pass`（:268-269），:261 注释承诺的
 *    fail-closed 失效：复核通道不可用反而成了「通过」。
 *
 * 守卫取向：行为断言 + **生产者/消费者同源**——异常值由真实 `llmReview()` 产出（而非
 * 手抄字面量），再喂给 `combineVerdict()`/端到端 `processTask()`，把「写哪个字段」与
 * 「查哪个字段」绑在同一判据上（字段漂移即红）。样本值一律哑值。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  combineVerdict, llmReview, processTask,
  type MutualOptions, type VerifyResult, type VerifyTask,
} from '../src/lib/mutual.ts'

/** 复核通道异常（哑因）。 */
const REVIEW_BOOM = async (): Promise<{ conclusion: string; reason: string }> => {
  throw new Error('复核通道超时（哑值）')
}

const W_ADOPT: VerifyResult['whitebox'] =
  { judgment: '采纳', best: 'x', d_norm: 0.9, record_id: 'r1' }

const opts = (dir: string): MutualOptions =>
  ({ heartbeatMs: 0, warnMs: 0, deadMs: 0, workingFactor: 1, restartCooldownMs: 0, netDir: dir })

test('① 复核通道抛异常 → 判定链必须 fail-closed（llmReview 产出 ⟶ combineVerdict 认它）', async () => {
  const w = { ...W_ADOPT }
  const l = await llmReview('测试主张', w, REVIEW_BOOM)
  assert.ok(l.conclusion.startsWith('llm_error'),
    `sanity：复核异常应落 llm_error 前缀（实测 conclusion=${JSON.stringify(l.conclusion)}）`)
  const verdict = combineVerdict(w, l)
  assert.equal(verdict, 'needs_revision',
    `白箱采纳 + 复核通道异常 ⇒ 必须 needs_revision（实测 ${verdict}）——此前查错字段致 fail-closed 失效`)
})

test('② 判别力对照：同一白箱 + 复核「同意」仍判 pass（修正未过度收紧）', () => {
  const verdict = combineVerdict({ ...W_ADOPT }, { conclusion: '同意：证据充分', reason: '' })
  assert.equal(verdict, 'pass', `正常复核结论不得被本修正波及（实测 ${verdict}）`)
})

test('③ 边界：正文提及该异常标记、但结论非异常前缀 ⇒ 不误判 fail-closed（startsWith 口径）', () => {
  const verdict = combineVerdict({ ...W_ADOPT },
    { conclusion: '同意（备注：llm_error 是该通道历史上出现过的缺陷名）', reason: '' })
  assert.equal(verdict, 'pass',
    `异常标记只在结论**起首**时才算异常（实测 ${verdict}）——正文提及不是通道异常`)
})

test('④ 回归：白箱通道异常/证据不足仍 fail-closed（既有判据不动）', () => {
  assert.equal(combineVerdict({ judgment: 'whitebox_error: boom', best: '', d_norm: -1, record_id: '' },
    { conclusion: '同意', reason: '' }), 'needs_revision', '白箱异常不得因复核同意而 pass')
  assert.equal(combineVerdict({ judgment: '采纳', best: 'x', d_norm: -1, record_id: '' },
    { conclusion: '同意', reason: '' }), 'needs_revision', 'd_norm<0 仍是 fail-closed')
  assert.equal(combineVerdict({ ...W_ADOPT }, { conclusion: '不同意：方法不适用', reason: '' }),
    'needs_revision', '复核不同意仍 needs_revision')
})

test('⑤ 端到端：复核抛异常的任务，写回 result 的 verdict 必须 needs_revision', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-mutual-'))
  const tasksDir = join(dir, 'tasks')
  mkdirSync(tasksDir, { recursive: true })
  const task: VerifyTask = {
    id: 'llm-err', type: 'verify', from: 'A', to: 'B',
    payload: { claim: '测试主张' }, status: 'pending', created_at: Date.now() / 1000,
  }
  writeFileSync(join(tasksDir, 'task-llm-err.json'), JSON.stringify(task), 'utf8')
  try {
    const r = await processTask(task,
      async () => ({ judgment: '采纳', best: 'x', d_norm: 0.9, record_id: 'r1' }),
      REVIEW_BOOM, opts(dir))
    assert.ok(r, 'sanity：processTask 应产出结果')
    const onDisk = JSON.parse(readFileSync(join(tasksDir, 'result-llm-err.json'), 'utf8'))
    const readings = `实测 内存 verdict=${r!.verdict} 落盘 verdict=${onDisk.verdict} 复核结论=${JSON.stringify(r!.llm_review.conclusion)}`
    assert.ok(r!.llm_review.conclusion.startsWith('llm_error'), `sanity：本场景确是复核通道异常；${readings}`)
    assert.equal(r!.verdict, 'needs_revision', `端到端 verdict 必须 needs_revision；${readings}`)
    assert.equal(onDisk.verdict, 'needs_revision', `写回盘的 result 同样必须 needs_revision；${readings}`)
  }
  finally { rmSync(dir, { recursive: true, force: true }) }
})
