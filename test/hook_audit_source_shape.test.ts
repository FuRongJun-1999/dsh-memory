/**
 * hook_audit_source_shape.test.ts · `source` 键名集合审计的守卫（issue #695 诊断面）
 *
 * 病灶（#695，报告人 YukiKaguraA）：外部桥接经 `sessions.prompt()` 注入的控制提示被当作
 * `user/message` 写入长期记忆。报告人明确指出关键缺口——
 * 「原始事件的 `source` 字段尚未从会话日志独立导出核验」。
 *
 * 而既有审计只记 `source.kind`（`kinds`），它只回答「以什么形式提交」，
 * 回答不了「source 到底带哪些字段」。本批加 `source_shapes`：**只记键名集合，绝不记值**。
 *
 * 钉住：
 *   A `sourceShapeOf` 的形态归一（undefined / not-object / empty / 键序无关）
 *   B `observeSourceShape` 计数累加并落盘
 *   C 旧审计文件（无 `source_shapes` 字段）读入不崩、不污染（向后兼容）
 *   D 隐私：只出现键名，**绝不出现键对应的值**（喂哨兵串验证）
 *
 * ⚠️ 测试一律用临时目录作 auditPath（绝不得写真实 ~/.dsh）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { HookAuditRecorder, sourceShapeOf } from '../src/lib/hook_audit.ts'

function tmpPath(): string {
  const dir = mkdtempSync(join(tmpdir(), "audit-shape-"))
  return join(dir, "audit.json")
}

function readState(p: string): any {
  return JSON.parse(readFileSync(p, "utf8"))
}

test("A sourceShapeOf：形态归一（只取键名，键序无关）", () => {
  assert.equal(sourceShapeOf(undefined), "undefined")
  assert.equal(sourceShapeOf(null), "undefined")
  assert.equal(sourceShapeOf("x"), "not-object")
  assert.equal(sourceShapeOf(42), "not-object")
  assert.equal(sourceShapeOf({}), "empty")
  assert.equal(sourceShapeOf({ kind: "user" }), "kind")
  assert.equal(sourceShapeOf({ kind: "user", form: "relay" }), "form+kind")
  // 键序无关：对象字面量顺序不同但键名集合相同 ⇒ 同一形状
  assert.equal(sourceShapeOf({ a: 1, b: 2 }), sourceShapeOf({ b: 2, a: 1 }))
})

test("B observeSourceShape：计数累加并落盘", async () => {
  const p = tmpPath()
  try {
    const rec = new HookAuditRecorder(p)
    rec.observeSourceShape({ kind: "user" })
    rec.observeSourceShape({ kind: "user" })
    rec.observeSourceShape({ kind: "user", form: "relay" })
    await new Promise((r) => setTimeout(r, 120))
    const st = readState(p)
    assert.ok(st.source_shapes, "状态里必须有 source_shapes 字段")
    assert.equal(st.source_shapes["kind"], 2, "同形状累加")
    assert.equal(st.source_shapes["form+kind"], 1, "不同形状分桶")
  } finally {
    rmSync(p, { force: true })
  }
})

test("C 旧审计文件无 source_shapes 字段：读入不崩、初始为空", async () => {
  const p = tmpPath()
  try {
    // 模拟旧版落盘（本批之前没有 source_shapes）
    writeFileSync(p, JSON.stringify({
      counts: { filtered: { subagent: 1, relay: 0, kind: 2 }, written: { user: 3, assistant: 0, tool: 0 }, skipped: { sanitized: 0, not_ready: 0, failed: 0 } },
      kinds: { user: 3 },
      last: [],
      updated_at: "2026-01-01T00:00:00.000Z",
    }), "utf8")
    const rec = new HookAuditRecorder(p)
    rec.observeSourceShape({ kind: "user" })
    await new Promise((r) => setTimeout(r, 120))
    const st = readState(p)
    assert.equal(st.source_shapes["kind"], 1, "新事件照常记账")
    assert.equal(st.counts.written.user, 3, "旧计数不得丢失")
    assert.equal(st.kinds.user, 3, "旧 kinds 不得丢失")
  } finally {
    rmSync(p, { force: true })
  }
})

test("D 隐私：只记键名，绝不记键对应的值", async () => {
  const p = tmpPath()
  const SENTINEL = "SENTINEL_SECRET_VALUE_9f3a"
  try {
    const rec = new HookAuditRecorder(p)
    rec.observeSourceShape({ kind: "user", token: SENTINEL, origin: SENTINEL })
    await new Promise((r) => setTimeout(r, 120))
    const raw = readFileSync(p, "utf8")
    assert.ok(raw.includes("kind+origin+token"), "键名必须被记下")
    assert.ok(!raw.includes(SENTINEL), "哨兵值绝不能出现在审计文件里")
  } finally {
    rmSync(p, { force: true })
  }
})