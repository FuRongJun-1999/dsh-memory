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
import { mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
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
  /** 最近 ≤MAX_LAST 条摘要。 */
  last: HookAuditEntry[]
  updated_at: string
}

/** 缺省审计文件：与桥探针 / apply 探针同目录同惯例（README.md:110）。 */
export const DEFAULT_HOOK_AUDIT_PATH = join(homedir(), '.dsh', 'logs', 'dsh-memory-hook-audit.json')

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
    last: [],
    updated_at: nowIso(),
  }
}

/** 计数位：只认有限非负整数，其余归零（防手改/坏文件把计数变成 NaN）。 */
function countOf(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0
}

/** 盘面内容 → 状态：逐字段归并，形态不符的字段一律丢弃（不信任盘面内容）。 */
function mergeState(raw: unknown): HookAuditState {
  const s = emptyState()
  if (!raw || typeof raw !== 'object') return s
  const r = raw as { counts?: unknown; kinds?: unknown; last?: unknown }
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

  constructor(path?: string) {
    this.path = typeof path === 'string' && path.trim() ? path.trim() : DEFAULT_HOOK_AUDIT_PATH
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
    try {
      const s = this.#state ?? (this.#state = this.#load())
      fn(s)
      if (s.last.length > MAX_LAST) s.last = s.last.slice(-MAX_LAST)
      s.updated_at = nowIso()
      this.#save(s)
    } catch { /* 审计失败静默降级：记忆路径必须照常 */ }
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
