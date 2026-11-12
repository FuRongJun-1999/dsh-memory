/**
 * console_web_connection.test.ts · #699 守卫：宿主鉴权服务**后到**时必须自愈
 *
 * 病灶（#699，imFelixYang 在 DSH 0.2.1-rc.3 实测）：`createConsoleHandler(...)` 在**挂载时**
 * 取一次 `ctx.get('connection')`，而 cordis 的 `Context.get(name, strict=true)` 在服务 fiber
 * 未就绪时返回 undefined；空值被闭包固化 ⇒ 此后每个请求都命中 503「宿主鉴权不可用」，
 * 宿主就绪也不自愈（连静态资源都 503）。
 *
 * 修法：第 4 参改为**取值函数**，handler 每次请求实时取（非函数则包成常量，向后兼容）。
 *
 * 钉住：
 *   A 连接此刻不存在 ⇒ 503，且文案是「尚未就绪」（可重试语义）
 *   B **连接随后就绪 ⇒ 同一 handler 立刻 200（自愈）** — 正是病灶点
 *   C 传值（旧调用方式）仍按常量处理（向后兼容）
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
// @ts-ignore —— console_web.mjs 是 build_ui 铺出的产物（JS，无类型声明）；本测试面向其运行时行为
import { createConsoleHandler } from '../lib/lib/console_web.mjs'

type FakeRes = { out: { status: number; body: string }; setHeader: (k: string, v: string) => void; writeHead: (c: number) => void; end: (c?: unknown) => void }

const ASSETS: Record<string, [string, string]> = {
  "/lingshu": ["<html>ok</html>", "text/html; charset=utf-8"],
}

function fakeRes(): FakeRes {
  const out = { status: 0, body: "" }
  return {
    out,
    setHeader() {},
    writeHead(code: number) { out.status = code },
    end(chunk?: unknown) { if (chunk) out.body += String(chunk) },
  }
}

const OK_ADMIT = { admit: () => ({ ok: true }) }

test("A 连接此刻不存在 ⇒ 503 且文案是「尚未就绪」（可重试语义）", async () => {
  let conn: unknown
  const h = (createConsoleHandler as any)({}, {}, ASSETS, () => conn)
  const res = fakeRes()
  await h({ url: "/lingshu", method: "GET", headers: {} }, res)
  assert.equal(res.out.status, 503)
  assert.ok(res.out.body.includes("尚未就绪"), "文案应表达可重试：" + res.out.body)
})

test("B **连接随后就绪 ⇒ 同一 handler 立刻 200（自愈）**", async () => {
  let conn: unknown                // 挂载时确实拿不到（模拟 fiber 未就绪）
  const h = (createConsoleHandler as any)({}, {}, ASSETS, () => conn)
  const r1 = fakeRes()
  await h({ url: "/lingshu", method: "GET", headers: {} }, r1)
  assert.equal(r1.out.status, 503, "第一次请求应 503（尚未就绪）")
  conn = OK_ADMIT                 // ← 服务就绪（rc.3 上的真实时序）
  const r2 = fakeRes()
  await h({ url: "/lingshu", method: "GET", headers: {} }, r2)
  assert.equal(r2.out.status, 200, "服务就绪后必须自愈，不得恒 503（#699 病灶）")
  assert.equal(r2.out.body, "<html>ok</html>")
})

test("D 服务根本没注入 ⇒ reason=not_injected（第二层诊断）", async () => {
  const h = (createConsoleHandler as any)({}, {}, ASSETS, () => undefined,
    () => ({ ready: false, any: false }))
  const res = fakeRes()
  await h({ url: "/lingshu", method: "GET", headers: {} }, res)
  assert.equal(res.out.status, 503)
  assert.ok(res.out.body.includes("not_injected"), "应区分「没注入」：" + res.out.body)
})

test("F 服务存在但不提供 admit ⇒ reason=not_admit（服务名撞车/版本不兼容的指纹）", async () => {
  const h = (createConsoleHandler as any)({}, {}, ASSETS, () => ({}))
  const res = fakeRes()
  await h({ url: "/lingshu", method: "GET", headers: {} }, res)
  assert.equal(res.out.status, 503)
  assert.ok(res.out.body.includes("not_admit"), "应识别第三态：" + res.out.body)
})

test("G 探针异常 ⇒ reason=probe_failed（不默认退回 not_ready）", async () => {
  const h = (createConsoleHandler as any)({}, {}, ASSETS, () => undefined, () => { throw new Error("probe boom") })
  const res = fakeRes()
  await h({ url: "/lingshu", method: "GET", headers: {} }, res)
  assert.equal(res.out.status, 503)
  assert.ok(res.out.body.includes("probe_failed"), "诊断失败必须可观测：" + res.out.body)
})

test("A′ 旧调用（4 参）503 的 reason 保守落 not_ready", async () => {
  const h = (createConsoleHandler as any)({}, {}, ASSETS, () => undefined)
  const res = fakeRes()
  await h({ url: "/lingshu", method: "GET", headers: {} }, res)
  assert.equal(res.out.status, 503)
  assert.ok(res.out.body.includes("not_ready"), "缺省 probe 时不得误报：" + res.out.body)
})

test("E 已注册但未就绪 ⇒ reason=not_ready（可重试）", async () => {
  const h = (createConsoleHandler as any)({}, {}, ASSETS, () => undefined,
    () => ({ ready: false, any: true }))
  const res = fakeRes()
  await h({ url: "/lingshu", method: "GET", headers: {} }, res)
  assert.equal(res.out.status, 503)
  assert.ok(res.out.body.includes("not_ready"), "应区分「未就绪」：" + res.out.body)
})

test("C 旧调用方式（直接传值）仍按常量处理——向后兼容", async () => {
  const h = (createConsoleHandler as any)({}, {}, ASSETS, OK_ADMIT)
  const res = fakeRes()
  await h({ url: "/lingshu", method: "GET", headers: {} }, res)
  assert.equal(res.out.status, 200, "传值时应立即可用（与旧版一致）")
})