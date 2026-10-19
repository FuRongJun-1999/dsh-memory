import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// #563④ 守卫：**真并发**两进程写同一审计文件，计数不得被整份 rename 覆盖吞掉。
// 病象（修前）：两进程各写 100 条，落地约 100（后写者用自己内存态整份覆盖）。
function runChild(path: string, n: number): Promise<number> {
  const code = [
    "const { HookAuditRecorder } = await import('./src/lib/hook_audit.ts')",
    `const r = new HookAuditRecorder(process.env.AUDIT_PATH)`,
    `for (let i = 0; i < ${n}; i++) r.written('user')`,
  ].join(';')
  return new Promise((resolve) => {
    const ch = spawn(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', code], {
      env: { ...process.env, AUDIT_PATH: path }, stdio: 'ignore',
    })
    ch.on('exit', (c) => resolve(c ?? 1))
  })
}

test('#563④ 并发写：两进程同时各 100 条 → 落地 200 条', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'audit-conc-'))
  const p = join(dir, 'a.json')
  try {
    const [a, b] = await Promise.all([runChild(p, 100), runChild(p, 100)])
    assert.equal(a, 0, '子进程A应正常退出')
    assert.equal(b, 0, '子进程B应正常退出')
    const st = JSON.parse(readFileSync(p, 'utf8'))
    const total = st.counts.written.user
    assert.equal(total, 200, `两进程各 100 条，落地应为 200；实际 ${total}（计数被吞）`)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})