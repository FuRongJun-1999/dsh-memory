/**
 * dsh-memory · 互维维护（Mutual Sustain Loop v1.1）——沙箱 B 侧
 *
 * 职责（与 A 侧 guardian.py 对称）：
 *   1. 心跳写戳：10min 写 ~/.lingxu_net/heartbeat.web.stamp（{ts,pid,task_running}）
 *   2. 守护 A：检测 harness 进程（wmic 特征）→ 不存在则 detached 拉起
 *      （python -m harness.guardian；幂等：拉起前确认不存在 + 60s 冷却）
 *   3. 任务验证：轮询 ~/.lingxu_net/tasks/task-*.json → 双通道验证
 *      （白箱 base_verify + DeepSeek 复核）→ 写回 result-<id>.json
 *
 * 协议：CommonTrustProtocol/docs/mutual-sustain-loop.md v1.1
 * 失联分级：25min 告警 / 35min 重启 / task_running 豁免 ×2=70min
 */
import { exec, spawn } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import * as os from 'node:os'

export interface MutualOptions {
  /** 心跳间隔（毫秒），默认 10min */
  heartbeatMs: number
  /** 失联告警阈值（毫秒），默认 25min */
  warnMs: number
  /** 失联重启阈值（毫秒），默认 35min */
  deadMs: number
  /** 任务中豁免倍数，默认 ×2 */
  workingFactor: number
  /** 拉起冷却（毫秒），默认 60s */
  restartCooldownMs: number
  /** 互维网络目录，默认 ~/.lingxu_net */
  netDir: string
}

const DEFAULTS: MutualOptions = {
  heartbeatMs: 10 * 60 * 1000,
  warnMs: 25 * 60 * 1000,
  deadMs: 35 * 60 * 1000,
  workingFactor: 2,
  restartCooldownMs: 60 * 1000,
  netDir: path.join(os.homedir(), '.lingxu_net'),
}

/** 互维网络目录定位 */
export function netDir(opts: MutualOptions = DEFAULTS): string {
  return opts.netDir
}

// ---------------------------------------------------------------------------
// 心跳（B 侧写戳）
// ---------------------------------------------------------------------------

export function writeHeartbeat(opts: MutualOptions = DEFAULTS, taskRunning = false): void {
  const dir = netDir(opts)
  fs.mkdirSync(dir, { recursive: true })
  const stamp = {
    ts: Date.now() / 1000,
    pid: process.pid,
    task_running: taskRunning,
  }
  fs.writeFileSync(path.join(dir, 'heartbeat.web.stamp'),
    JSON.stringify(stamp), 'utf-8')
}

export function readHeartbeat(which: 'a' | 'web', opts: MutualOptions = DEFAULTS): {
  ts: number; pid: number; task_running: boolean; ageMs: number
} | null {
  try {
    const raw = fs.readFileSync(path.join(netDir(opts), `heartbeat.${which}.stamp`), 'utf-8')
    const s = JSON.parse(raw)
    const ageMs = Date.now() - (s.ts as number) * 1000
    return { ts: s.ts, pid: s.pid, task_running: !!s.task_running, ageMs }
  } catch {
    return null
  }
}

/** 失联分级判定（纯函数，A 侧 judge_stamp 的 B 侧镜像） */
export function judgeStamp(stamp: { ageMs: number; task_running: boolean } | null,
                           opts: MutualOptions = DEFAULTS): 'alive' | 'alive_working' | 'warning' | 'dead' | 'no_stamp' {
  if (!stamp) return 'no_stamp'
  const threshold = stamp.task_running ? opts.deadMs * opts.workingFactor : opts.deadMs
  if (stamp.ageMs < opts.warnMs) return 'alive'
  if (stamp.task_running && stamp.ageMs < threshold) return 'alive_working'
  if (stamp.ageMs < threshold) return 'warning'
  return 'dead'
}

// ---------------------------------------------------------------------------
// 守护 A（检测 harness 进程 + 拉起）
// ---------------------------------------------------------------------------

const HARNESS_PROC = ['python', 'harness.guardian']  // wmic 特征

function execP(cmd: string): Promise<string> {
  return new Promise((resolve) => {
    exec(cmd, { windowsHide: true, timeout: 15_000 }, (err, stdout) => {
      resolve(err ? '' : String(stdout))
    })
  })
}

/** 检测 harness 进程是否存在（wmic） */
export async function harnessRunning(): Promise<boolean> {
  const out = await execP(
    `wmic process where "name='python.exe'" get commandline 2>nul`)
  return out.includes('harness.guardian') || out.includes('harness.main')
}

/** detached 拉起 A 侧 harness.guardian（幂等：先确认不存在） */
export async function ensureHarness(python = 'python',
                                    opts: MutualOptions = DEFAULTS): Promise<'started' | 'already' | 'failed'> {
  const running = await harnessRunning()
  if (running) return 'already'
  try {
    const child = spawn(python, ['-m', 'harness.guardian'], {
      windowsHide: true,
      detached: true,
      stdio: 'ignore',
    })
    child.unref()
    log(opts, `守护动作：拉起 harness.guardian（pid=${child.pid ?? '?'}）`)
    return 'started'
  } catch (e) {
    log(opts, `守护失败：${String(e)}`)
    return 'failed'
  }
}

// ---------------------------------------------------------------------------
// 任务验证邮箱（双通道：白箱 base_verify + DeepSeek 复核）
// ---------------------------------------------------------------------------

export interface VerifyTask {
  id: string
  type: 'verify' | 'knowledge_sync'
  from: 'A' | 'B'
  to: 'B' | 'A'
  payload: { claim: string; evidence?: string; expected?: string; source_ref?: string }
  status: 'pending' | 'processing' | 'done'
  created_at: number
}

export interface VerifyResult {
  task_id: string
  verdict: 'pass' | 'fail' | 'needs_revision'
  whitebox: { judgment: string; best: string; d_norm: number; record_id: string }
  llm_review: { conclusion: string; reason: string }
  reasons: string[]
  evidence: string[]
  verifier: 'B'
  at: number
}

/** 扫描互维目录里 A→B 的 pending 任务 */
export function scanTasks(opts: MutualOptions = DEFAULTS): VerifyTask[] {
  const dir = path.join(netDir(opts), 'tasks')
  if (!fs.existsSync(dir)) return []
  const out: VerifyTask[] = []
  for (const f of fs.readdirSync(dir)) {
    if (!f.startsWith('task-') || !f.endsWith('.json')) continue
    try {
      const t = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf-8'))
      if (t.to === 'B' && t.status === 'pending') out.push(t)
    } catch { /* 跳过坏文件 */ }
  }
  return out
}

/** 白箱通道：智慧之书 base_verify（通过 bridge 调用，或本地注入） */
export async function whiteboxVerify(claim: string,
                                     verifyFn: (c: string) => Promise<{ judgment: string; best: string; d_norm: number; record_id: string }>): Promise<VerifyResult['whitebox']> {
  try {
    return await verifyFn(claim)
  } catch (e) {
    return { judgment: `whitebox_error: ${String(e)}`, best: '', d_norm: -1, record_id: '' }
  }
}

/** 复核通道：DeepSeek 独立复核（在白箱判定之上） */
export async function llmReview(claim: string, whitebox: VerifyResult['whitebox'],
                                reviewFn: (c: string, w: VerifyResult['whitebox']) => Promise<{ conclusion: string; reason: string }>): Promise<VerifyResult['llm_review']> {
  try {
    return await reviewFn(claim, whitebox)
  } catch (e) {
    return { conclusion: `llm_error: ${String(e)}`, reason: '' }
  }
}

/** 综合 verdict（白箱优先） */
export function combineVerdict(w: VerifyResult['whitebox'],
                               l: VerifyResult['llm_review']): VerifyResult['verdict'] {
  const c = l.conclusion || ''
  if (w.judgment.startsWith('采纳')) {
    // 白箱采纳：复核质疑/不同意→needs_revision（白箱优先，记录分歧）；否则 pass
    return c.includes('质疑') || c.includes('不同意') || c.includes('不通过')
      ? 'needs_revision' : 'pass'
  }
  if (w.judgment.includes('fail') || w.judgment.includes('不成立')) return 'fail'
  // 证据不足/无法判断 → 白箱不确定，交给复核决定（「不同意」须排除「同意」子串）
  if (c.includes('不同意') || c.includes('不通过')) return 'needs_revision'
  if (c.includes('通过') || c.includes('同意') || c.includes('质疑')) return 'pass'
  return 'needs_revision'
}

/** 处理单个任务：双通道验证 → 写回 result */
export async function processTask(task: VerifyTask,
                                  verifyFn: (c: string) => Promise<{ judgment: string; best: string; d_norm: number; record_id: string }>,
                                  reviewFn: (c: string, w: VerifyResult['whitebox']) => Promise<{ conclusion: string; reason: string }>,
                                  opts: MutualOptions = DEFAULTS): Promise<VerifyResult> {
  const dir = path.join(netDir(opts), 'tasks')
  const taskPath = path.join(dir, `task-${task.id}.json`)
  // 标记 processing
  try {
    fs.writeFileSync(taskPath, JSON.stringify({ ...task, status: 'processing' }, null, 2), 'utf-8')
  } catch { /* 非阻塞 */ }

  const w = await whiteboxVerify(task.payload.claim, verifyFn)
  const l = await llmReview(task.payload.claim, w, reviewFn)
  const verdict = combineVerdict(w, l)
  const result: VerifyResult = {
    task_id: task.id,
    verdict,
    whitebox: w,
    llm_review: l,
    reasons: [
      `白箱判定：${w.judgment}（best=${w.best}，d_norm=${w.d_norm}）`,
      `复核结论：${l.conclusion}`,
    ],
    evidence: [task.payload.source_ref || ''].filter(Boolean),
    verifier: 'B',
    at: Date.now() / 1000,
  }
  fs.writeFileSync(path.join(dir, `result-${task.id}.json`), JSON.stringify(result, null, 2), 'utf-8')
  // 标记 done
  try {
    fs.writeFileSync(taskPath, JSON.stringify({ ...task, status: 'done' }, null, 2), 'utf-8')
  } catch { /* 非阻塞 */ }
  log(opts, `任务 ${task.id} 验证完成：${verdict}`)
  return result
}

// ---------------------------------------------------------------------------
// 日志 / last_contact
// ---------------------------------------------------------------------------

export function log(opts: MutualOptions, msg: string): void {
  try {
    const p = path.join(netDir(opts), 'mutual.log')
    fs.appendFileSync(p, `[B ${new Date().toISOString()}] ${msg}\n`, 'utf-8')
  } catch { /* 日志失败不阻塞 */ }
}

export function writeLastContact(opts: MutualOptions = DEFAULTS): void {
  try {
    fs.writeFileSync(path.join(netDir(opts), 'last_contact.json'),
      JSON.stringify({ last_contact_b: Date.now() / 1000 }), 'utf-8')
  } catch { /* 非阻塞 */ }
}

// ---------------------------------------------------------------------------
// 安装（ctx.effect 作用域内，卸载时清理）
// ---------------------------------------------------------------------------

export function installMutualMaintenance(
  ctx: { logger: { info(m: string): void }; interval(ms: number, fn: () => void): () => void; effect(fn: () => () => void, name?: string): void },
  config: Partial<MutualOptions> = {},
  hooks: {
    verify?: (c: string) => Promise<{ judgment: string; best: string; d_norm: number; record_id: string }>
    review?: (c: string, w: VerifyResult['whitebox']) => Promise<{ conclusion: string; reason: string }>
  } = {},
): void {
  const opts: MutualOptions = { ...DEFAULTS, ...config }

  // 1. 心跳写戳 + 守护 A（10min 周期）
  const heartbeatDispose = ctx.interval(opts.heartbeatMs, () => {
    try {
      writeHeartbeat(opts)
      // 守护 A：harness 不在 → 拉起
      ensureHarness('python', opts).then((r) => {
        if (r === 'started') ctx.logger.info(`mutual: 已拉起 A 侧 harness（${r}）`)
      })
      // 读 A 戳分级判定
      const a = readHeartbeat('a', opts)
      const verdict = judgeStamp(a, opts)
      if (verdict === 'warning') ctx.logger.info('mutual: A 侧心跳告警（>25min 未更新）')
      if (verdict === 'dead') ctx.logger.info('mutual: A 侧失联（>35min），等待 guardian 自愈或告警')
      writeLastContact(opts)
    } catch (e) { /* 单次失败不中断 */ }
  })

  // 2. 任务轮询（30s 周期，检查 A→B 任务）
  const taskDispose = ctx.interval(30_000, () => {
    try {
      const tasks = scanTasks(opts)
      for (const t of tasks) {
        if (!hooks.verify || !hooks.review) continue
        processTask(t, hooks.verify, hooks.review, opts).catch((e) => {
          log(opts, `任务 ${t.id} 处理异常：${String(e)}`)
        })
      }
    } catch (e) { /* 单次失败不中断 */ }
  })

  // 3. effect 作用域清理
  ctx.effect(() => {
    return () => {
      try {
        heartbeatDispose()
        taskDispose()
      } catch { /* 清理失败不阻塞 */ }
    }
  }, 'dsh-memory-mutual')
}

export default { installMutualMaintenance, writeHeartbeat, readHeartbeat, judgeStamp, scanTasks, processTask }
