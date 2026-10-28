/**
 * hook_audit.ts · 自动记忆钩子的**有界落盘审计**（issue #56，诊断面）
 *
 * 病灶（报告人 jiamajie，v0.7.1 实测）：src/hooks.ts 的三处过滤分支（子代理会话 /
 * 中继消息 / `source.kind !== 'user'`）只调 `ctx.logger.info`——宿主 logger 不落盘，
 * 盘面完全无痕。其它插件按设计注入的 `role:"user"` 消息（如 @michengai/dsh-pua 的
 * PUA_RUNTIME_V1 提示）不进记忆库时，从记忆侧只能看到「少了一条」，无法区分
 * 「被设计滤除」与「写入失败/漏记」。
 *
 * 本模块 = **诊断面**，不参与任何写入/过滤判定（红线：哪些消息进记忆一字不动）：
 *   ① 维护一份小 JSON 状态文件（缺省 `~/.dsh/logs/dsh-memory-hook-audit.json`，
 *      与 `lingshu-bridge-debug.log` / `dsh-memory-apply-error.log` 同目录同惯例，
 *      见 README.md:110）；
 *   ② 每事件只写计数与「最近条目」摘要（action/reason/kind/role），**绝不记录
 *      消息内容**（内容可能含隐私/凭据，审计文件是可被随手打开的诊断件）；
 *   ③ 原子写：同目录临时文件 + rename（读者永远不会看到半截 JSON）；
 *   ④ 有界：last 截断到 MAX_LAST=20（无追加式增长）；kinds 键数上限 MAX_KINDS，
 *      超限归并到 "other"（kind 值域理论上由宿主决定，防异常值把文件撑大）；
 *   ⑤ 静默降级：公共方法全部 try/catch 包死——审计失败绝不冒泡进记忆路径
 *      （审计是增益，记忆写入必须照常）。
 *
 * 为什么落盘采用**同步** fs：`session/event` 回调是同步的，异步落盘会引入
 * 「多事件并发写同一文件」的乱序与竞态；状态文件只有几 KB，一次同步读（仅首次）
 * 加一次全量重写的代价远小于它守护的诊断价值。
 *
 * 与 ctx.logger.info 的关系：hook 内三行 info 日志**保留不动**（in-memory 实时
 * 视图），本审计是**盘面**视图（宿主 logger 不落盘时仍可复盘）。
 *
 * 边界（如实）：
 *   · 状态是「进程内缓存 + 每次全量重写」，多进程同时写同一路径会互相覆盖
 *     （插件单实例部署下不构成问题；审计非关键路径，不做跨进程锁）；
 *   · 审计文件损坏/手改致形态不符时按空态重建（数值归零、last 逐条过滤），
 *     不抛错、不保留非法内容；
 *   · `written` 记的是「**成功发起**」的写入（fire-and-forget 的发起时刻），
 *     发起后失败另记 `skipped.failed`——与 hooks.ts 的 memorize 两段式对应。
 */
import { closeSync, mkdirSync, openSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { expandHome } from './datapath.js'
import { dirname, join } from 'node:path'

/** 三处过滤分支的成因（与 hooks.ts 一一对应：子代理会话 / 中继消息 / kind 非 user）。 */
export type HookFilterReason = 'subagent' | 'relay' | 'kind'
/** 写入路径的角色（与 md_cg 对 DSH 会话事件的 role 约定一致）。 */
export type HookWriteRole = 'user' | 'assistant' | 'tool'
/** 跳过写入的成因。 */
export type HookSkipReason = 'sanitized' | 'not_ready' | 'failed'

/** last 的一条摘要（**绝不含消息内容**——只有动作、成因、kind 与 role）。 */
export interface HookAuditEntry {
  ts: string
  action: 'filtered' | 'written' | 'skipped'
  reason?: HookFilterReason | HookSkipReason
  kind?: string
  role?: HookWriteRole
}

/** 审计状态（= 状态文件的结构）。 */
export interface HookAuditState {
  counts: {
    /** 三处过滤分支的计数。 */
    filtered: Record<HookFilterReason, number>
    /** 成功发起的写入计数（按 role 分解）。 */
    written: Record<HookWriteRole, number>
    /** 跳过写入的计数（脱敏置空 / 认知图未就绪 / 写入失败）。 */
    skipped: Record<HookSkipReason, number>
  }
  /** 进入消息级处理的 `source.kind` 分布（缺字段/空串/非字符串记 "undefined"）。 */
  kinds: Record<string, number>
  /** `source` 的**键名集合**分布（issue #695：只记键名，绝不记值）。
   *  为什么需要：`kind` 只说明「以什么形式提交」，不说明「谁提交的」。
   *  外部桥接经 `sessions.prompt()` 注入的控制提示同样以 kind="user" 通过，
   *  只看 kind 无法区分；而**键名集合**（如 `kind` / `form+kind` / `kind+origin`）
   *  能直接回答「这条事件的 source 到底带哪些字段」，是排查来源归因缺口的第一读数。 */
  source_shapes: Record<string, number>
  /** 最近 ≤MAX_LAST 条摘要。 */
  last: HookAuditEntry[]
  updated_at: string
}

/** 缺省审计文件：与桥探针 / apply 探针同目录同惯例（README.md:110）。 */
/**
 * 审计根：优先 `DSH_HOME`（隔离/多 home 安装必须显式给），否则 `~/.dsh`。
 * issue #554 §7：此前恒用 homedir，隔离 home 下审计写到生产 home，与 brain 分离。
 * 兼容 `~` 与 `~/x` 形态；其余按字面路径处理（不做 shell 展开）。
 */
function defaultHookAuditPath(): string {
  const raw = (process.env.DSH_HOME ?? '').trim()
  // 唯一实现：路径展开复用 datapath.expandHome（禁止第二处判据，见 test/datapath-expandhome）。
  const root = raw ? expandHome(raw) : join(homedir(), '.dsh')
  return join(root, 'logs', 'dsh-memory-hook-audit.json')
}

export const DEFAULT_HOOK_AUDIT_PATH = defaultHookAuditPath()

/** last 条数上限（有界性单点——没有它 audit 文件会随会话无限增长）。 */
const MAX_LAST = 20
/** kinds 键数上限（超限归并到 OTHER_KIND，防宿主 kind 值域异常撑大文件）。 */
const MAX_KINDS = 32
/** kinds 归并桶。 */
const OTHER_KIND = 'other'

const FILTER_REASONS: HookFilterReason[] = ['subagent', 'relay', 'kind']
const WRITE_ROLES: HookWriteRole[] = ['user', 'assistant', 'tool']
const SKIP_REASONS: HookSkipReason[] = ['sanitized', 'not_ready', 'failed']

/** `source.kind` 的规范化取值：非字符串（含缺字段）或空串一律记 "undefined"
 *  （不可辨认即无值——空串与缺字段在排障上同义）。 */
export function kindOf(source: unknown): string {
  const k = (source as { kind?: unknown } | null | undefined)?.kind
  return typeof k === 'string' && k.length > 0 ? k : 'undefined'
}

/** `source` 的键名集合（排序后 join '+'）：空对象记 "empty"，非对象记 "not-object"。
 *  只取 `Object.keys`——**绝不读值**，因此不含任何内容/凭据。 */
export function sourceShapeOf(source: unknown): string {
  if (source === null || source === undefined) return 'undefined'
  if (typeof source !== 'object') return 'not-object'
  const keys = Object.keys(source as Record<string, unknown>).sort()
  return keys.length ? keys.join('+') : 'empty'
}

function nowIso(): string {
  return new Date().toISOString()
}

function emptyState(): HookAuditState {
  return {
    counts: {
      filtered: { subagent: 0, relay: 0, kind: 0 },
      written: { user: 0, assistant: 0, tool: 0 },
      skipped: { sanitized: 0, not_ready: 0, failed: 0 },
    },
    kinds: {},
    source_shapes: {},
    last: [],
    updated_at: nowIso(),
  }
}

/** 计数位：只认有限非负整数，其余归零（防手改/坏文件把计数变成 NaN）。 */
function countOf(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0
}

/** 摘要只接受完整的非负安全整数桶；坏盘面不伪装成零计数。 */
function sumCounts(bucket: unknown, keys: readonly string[]): number | null {
  if (!bucket || typeof bucket !== 'object' || Array.isArray(bucket)) return null
  let total = 0
  for (const key of keys) {
    const value = (bucket as Record<string, unknown>)[key]
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) return null
    total += value
    if (!Number.isSafeInteger(total)) return null
  }
  return total
}

/** 盘面内容 → 状态：逐字段归并，形态不符的字段一律丢弃（不信任盘面内容）。 */
function mergeState(raw: unknown): HookAuditState {
  const s = emptyState()
  if (!raw || typeof raw !== 'object') return s
  const r = raw as { counts?: unknown; kinds?: unknown; source_shapes?: unknown; last?: unknown }
  if (r.counts && typeof r.counts === 'object') {
    const c = r.counts as { filtered?: unknown; written?: unknown; skipped?: unknown }
    const buckets: Array<[Record<string, number>, string[], unknown]> = [
      [s.counts.filtered as Record<string, number>, FILTER_REASONS, c.filtered],
      [s.counts.written as Record<string, number>, WRITE_ROLES, c.written],
      [s.counts.skipped as Record<string, number>, SKIP_REASONS, c.skipped],
    ]
    for (const [dst, keys, src] of buckets) {
      if (!src || typeof src !== 'object') continue
      for (const key of keys) dst[key] = countOf((src as Record<string, unknown>)[key])
    }
  }
  if (r.kinds && typeof r.kinds === 'object') {
    for (const [k, v] of Object.entries(r.kinds as Record<string, unknown>)) {
      if (typeof v === 'number' && Number.isFinite(v) && v > 0) s.kinds[k] = Math.floor(v)
    }
  }
  if (r.source_shapes && typeof r.source_shapes === 'object') {
    for (const [k, v] of Object.entries(r.source_shapes as Record<string, unknown>)) {
      if (typeof v === 'number' && Number.isFinite(v) && v > 0) s.source_shapes[k] = Math.floor(v)
    }
  }
  if (Array.isArray(r.last)) {
    for (const e of r.last) {
      if (!e || typeof e !== 'object') continue
      const entry = e as Partial<HookAuditEntry>
      if (typeof entry.ts !== 'string') continue
      if (entry.action !== 'filtered' && entry.action !== 'written' && entry.action !== 'skipped') continue
      s.last.push(entry as HookAuditEntry)
    }
    if (s.last.length > MAX_LAST) s.last = s.last.slice(-MAX_LAST)
  }
  return s
}

/**
 * 有界落盘审计记录器（**静默降级**：任何公共方法都不会抛错）。
 *
 * 用法（hooks.ts 内）：`new HookAuditRecorder(opts.auditPath)`，随后在
 * 三处过滤分支与写入/跳过路径各调一次对应方法。审计失败只影响审计自身。
 */
export class HookAuditRecorder {
  /** 实际生效的审计文件路径（构造时定死，供日志/测试核对）。 */
  readonly path: string
  /** 进程内状态缓存（首次记录时从盘面载入，此后只增量改内存 + 全量重写）。 */
  #state: HookAuditState | null = null
  /** 本进程持有的锁 token；null 表示当前未持锁。 */
  #lockToken: string | null = null

  constructor(path?: string) {
    this.path = typeof path === 'string' && path.trim() ? path.trim() : DEFAULT_HOOK_AUDIT_PATH
  }

  /** #606：收尾时只读最新盘面，返回一行累计计数；缺失/损坏/不可读均静默。
   * written 沿用“成功发起”口径，不能当成成功落库数；不读取 last/kinds 等文本进日志。 */
  summary(): string | null {
    try {
      const raw: unknown = JSON.parse(readFileSync(this.path, 'utf8'))
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
      const counts: unknown = (raw as { counts?: unknown }).counts
      if (!counts || typeof counts !== 'object' || Array.isArray(counts)) return null
      const buckets = counts as Record<string, unknown>
      const written = sumCounts(buckets.written, WRITE_ROLES)
      const filtered = sumCounts(buckets.filtered, FILTER_REASONS)
      const skipped = sumCounts(buckets.skipped, SKIP_REASONS)
      if (written === null || filtered === null || skipped === null) return null
      return `dsh-memory: 自动记忆审计（累计）written=${written} filtered=${filtered} skipped=${skipped}`
    } catch {
      return null
    }
  }

  /** 一条**被设计滤除**的消息（三处过滤分支各调一次）。 */
  filtered(reason: HookFilterReason, kind?: string): void {
    this.#mutate((s) => {
      s.counts.filtered[reason] += 1
      s.last.push(kind === undefined
        ? { ts: nowIso(), action: 'filtered', reason }
        : { ts: nowIso(), action: 'filtered', reason, kind })
    })
  }

  /** `source.kind` 分布（每条**进入消息级处理**的事件调一次，含被滤与放行）。 */
  observeKind(kind: string): void {
    this.#mutate((s) => {
      const key = this.#boundedKindKey(s, kind)
      s.kinds[key] = (s.kinds[key] ?? 0) + 1
    })
  }

  /** `source` 的键名集合分布（issue #695）：只记**键名**，不记任何值。
   *
   *  与 `observeKind` 的分工：kind 回答「以什么形式提交」，本方法回答「source 带哪些字段」。
   *  两者都不参与写入判定（本模块是诊断面，红线不动）。
   */
  observeSourceShape(source: unknown): void {
    const shape = sourceShapeOf(source)
    this.#mutate((s) => {
      s.source_shapes[shape] = (s.source_shapes[shape] ?? 0) + 1
    })
  }

  /** 成功**发起**的写入（按 role；发起后失败另记 skipped.failed）。 */
  written(role: HookWriteRole): void {
    this.#mutate((s) => {
      s.counts.written[role] += 1
      s.last.push({ ts: nowIso(), action: 'written', role })
    })
  }

  /** 跳过写入（脱敏置空 / 认知图未就绪 / 写入失败）。 */
  skipped(reason: HookSkipReason, role?: HookWriteRole): void {
    this.#mutate((s) => {
      s.counts.skipped[reason] += 1
      s.last.push(role === undefined
        ? { ts: nowIso(), action: 'skipped', reason }
        : { ts: nowIso(), action: 'skipped', reason, role })
    })
  }

  /** 键数有界：已见键原样用；新键在未达上限时收录，达限后统一归并到 "other"。 */
  #boundedKindKey(s: HookAuditState, kind: string): string {
    if (Object.prototype.hasOwnProperty.call(s.kinds, kind)) return kind
    return Object.keys(s.kinds).length >= MAX_KINDS ? OTHER_KIND : kind
  }

  /** 读改写 + 原子落盘；整段 try/catch——审计失败静默降级（绝不冒泡进记忆路径）。 */
  #mutate(fn: (s: HookAuditState) => void): void {
    // #563④：审计文件被同用户的多个 DSH 进程共用；此前 #state 只在首次载入、写回整份 rename 覆盖
    // ⇒ 并发时后写者用内存态盖掉他人计数（实测 400→201 / 400→311）。现改为锁内 重读→改→写。
    if (!this.#acquireLock()) return
    try {
      const s = this.#load()
      fn(s)
      if (s.last.length > MAX_LAST) s.last = s.last.slice(-MAX_LAST)
      s.updated_at = nowIso()
      this.#save(s)
      this.#state = s
    } catch { /* 审计失败静默降级：记忆路径必须照常 */ }
    finally { this.#releaseLock() }
  }

  /** 跨进程排他锁：独占创建 `${path}.lock`；陈旧锁（>5s）清掉；超时返回 false（静默降级）。 */
  #acquireLock(timeoutMs = 800): boolean {
    const lock = `${this.path}.lock`
    const token = `${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    const t0 = Date.now()
    for (;;) {
      try {
        closeSync(openSync(lock, 'wx'))
        // #563④补（ABA）：把归属 token 写进锁文件，释放时据此判断锁是否仍是自己的。
        // 不加 token 时：A 的锁被 B 判陈旧清掉 → B 建新锁 → A 在 finally 无条件 unlink，
        // 把 B 的锁删掉，互斥窗口重新打开（回到本函数要修的丢计数问题）。
        try { writeFileSync(lock, token) } catch {
          // 写不进归属 token ⇒ 不持有无法验证归属的锁，立即归还（否则 releaseLock 比对失败会漏删）
          try { unlinkSync(lock) } catch { /* 已被他人清理 */ }
          return false
        }
        this.#lockToken = token
        return true
      } catch {
        try { if (Date.now() - statSync(lock).mtimeMs > 5000) unlinkSync(lock) } catch { /* 已释放 */ }
        if (Date.now() - t0 > timeoutMs) return false
        const until = Date.now() + 5
        while (Date.now() < until) { /* 自旋 5ms */ }
      }
    }
  }

  #releaseLock(): void {
    // #563④补（ABA）：只删自己的锁。锁可能已被他人判陈旧清掉并重建——
    // 无条件 unlink 会删掉别人的锁，互斥窗口重新打开。
    const token = this.#lockToken
    this.#lockToken = null
    if (!token) return
    try {
      if (readFileSync(`${this.path}.lock`, 'utf8') !== token) return
      unlinkSync(`${this.path}.lock`)
    } catch { /* 已清理 */ }
  }

  /** 盘面 → 状态；不存在/不可读/坏 JSON/形态不符 → 空态重建（不抛）。 */
  #load(): HookAuditState {
    try {
      return mergeState(JSON.parse(readFileSync(this.path, 'utf8')) as unknown)
    } catch {
      return emptyState()
    }
  }

  /** 原子写：同目录临时文件 + rename（临时文件在 rename 失败时清理）。 */
  #save(s: HookAuditState): void {
    const dir = dirname(this.path)
    mkdirSync(dir, { recursive: true })
    const tmp = `${this.path}.${process.pid.toString(36)}.${Date.now().toString(36)}.tmp`
    writeFileSync(tmp, `${JSON.stringify(s, null, 2)}\n`, 'utf8')
    try {
      renameSync(tmp, this.path)
    } catch (err) {
      try { unlinkSync(tmp) } catch { /* 清理失败忽略：残留 .tmp 不影响读路径 */ }
      throw err
    }
  }
}
