/**
 * verify_mutual.ts · 互维任务竞态锁验证（GPT 审查完善）
 * 场景：多实例同时 scanTasks 读到同一 pending → 都 processTask。
 * 修复后：原子 rename claim——只有一方成功，另一方返回 null。
 * 断言：verifyFn 只执行一次（无重复处理）+ 只有一个 result 文件。
 */
import { processTask, type VerifyTask, type VerifyResult } from '../src/mutual.ts'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

let pass = 0, fail = 0
function check(name: string, ok: boolean, detail = ''): void {
  if (ok) pass++; else fail++
  console.log(`[${ok ? '✓' : '✘'}] ${name}${detail ? ' — ' + detail : ''}`)
}

async function main(): Promise<void> {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-mutual-'))
  const tasksDir = join(dir, 'tasks')
  mkdirSync(tasksDir, { recursive: true })
  const task: VerifyTask = {
    id: 't1', type: 'verify', from: 'A', to: 'B',
    payload: { claim: '测试主张' }, status: 'pending', created_at: Date.now() / 1000,
  }
  writeFileSync(join(tasksDir, 'task-t1.json'), JSON.stringify(task), 'utf8')

  let verifyCalls = 0
  const verifyFn = async (c: string) => {
    verifyCalls++
    await new Promise((r) => setTimeout(r, 50)) // 模拟耗时，放大竞态窗口
    return { judgment: '采纳', best: 'x', d_norm: 0.9, record_id: 'r1' }
  }
  const reviewFn = async () => ({ conclusion: '同意', reason: '' })

  // 两个「实例」同时处理同一任务
  const [r1, r2] = await Promise.all([
    processTask(task, verifyFn, reviewFn, { heartbeatMs: 0, warnMs: 0, deadMs: 0, workingFactor: 1, restartCooldownMs: 0, netDir: dir }),
    processTask(task, verifyFn, reviewFn, { heartbeatMs: 0, warnMs: 0, deadMs: 0, workingFactor: 1, restartCooldownMs: 0, netDir: dir }),
  ])

  const results = readdirSync(tasksDir)
  const resultFiles = results.filter((f) => f.startsWith('result-') && f.endsWith('.json'))
  const processed = results.filter((f) => f.startsWith('done-') || f.startsWith('result-'))

  check('① 只有一个实例 claim 成功（另一个 null）', (r1 !== null) !== (r2 !== null),
    `r1=${r1 !== null} r2=${r2 !== null}`)
  check('② verifyFn 只执行一次（无重复处理）', verifyCalls === 1, `calls=${verifyCalls}`)
  check('③ 只有一个 result 文件', resultFiles.length === 1, resultFiles.join(','))
  check('④ 处理产物完整（done+result）', processed.length === 2, processed.join(','))

  rmSync(dir, { recursive: true, force: true })
  console.log(`\n互维竞态锁验证: ${pass}/${pass + fail} 通过`)
  process.exit(fail > 0 ? 1 : 0)
}

main().catch((err) => { console.error('异常:', err); process.exit(1) })
