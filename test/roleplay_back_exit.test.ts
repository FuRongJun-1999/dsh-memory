/**
 * issue #20 守卫 · `/roleplay` 页面必须有**可点击的返回出口**（返回 DSH 宿主页）。
 *
 * 缺陷（取证读数，修复前）：起 handler 打 GET /roleplay ⇒ STATUS 200 / LEN 24992，
 * 而页面里「返回」链接 `href="/"` 为 false、`history.back` 也为 false ⇒ 页面上
 * **确实没有任何出口**。背景：维护者称新版角色扮演「暂未开放」但代码在、页面在、
 * 就是出不去；且 **Electron 壳下没有浏览器后退按钮**，只靠 `history.back` 不可靠。
 *
 * 守卫口径（**不只断言字符串出现**）：把渲染出的 HTML 解析成元素，要求存在一个
 * **链接元素**（`<a>`，非按钮/非纯 JS 跳转）其 `href` 能**解析**为同源根路径 `/`
 * （即 DSH 宿主页），且该元素**可见可点**（非 hidden / 非 display:none / 有标签文字）。
 * 这同时钉住「形态是真实链接」（Electron 无后退键时仍可点出去）与「目标正确」。
 *
 * 定点变异自证：`node --import tsx test/roleplay_back_exit.test.ts --mutate A`
 *   —— 从 HTML 里抽掉该出口 ⇒ 守卫必红并**点名**到具体断言（BACK-EXIT-*）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installRoleplayWeb } from '../src/lib/roleplay_web.ts'

const BASE = 'http://dsh-host/roleplay'

/* ————— 服务端挂载 mock（照 verify_web.ts 形制） ————— */

function makeReq(method: string, url: string, headers: Record<string, string>, body = '') {
  const chunks = body ? [Buffer.from(body)] : []
  return {
    method, url, headers,
    [Symbol.asyncIterator]() {
      let i = 0
      return {
        next: async () => (i < chunks.length ? { value: chunks[i++], done: false } : { value: undefined, done: true }),
      }
    },
  }
}
function makeRes() {
  const state: { status: number; body: string } = { status: 200, body: '' }
  return {
    writeHead(s: number) { state.status = s; return this },
    end(b: string) { state.body = b || '' },
    _state: state,
  }
}

async function renderPage(): Promise<string> {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-rpback-'))
  let handler: any = null
  const ctx: any = {
    logger: { info: () => {}, warn: () => {} },
    get(key: string) { return key === 'webServer' ? this.webServer : undefined },
    webServer: { register(opts: any) { handler = opts.handler; return () => {} }, tapIndex() { return () => {} } },
  }
  await installRoleplayWeb(ctx, null, { dbPath: join(dir, 'test.db') }, [] as Array<() => void>)
  const res = makeRes()
  await handler(makeReq('GET', '/roleplay', {}), res)
  rmSync(dir, { recursive: true, force: true })
  return res._state.body
}

/* ————— 元素解析（无 DOM 依赖：按标签抓取 + 属性解析） ————— */

type El = { tag: string; attrs: Record<string, string>; text: string; raw: string }

function parseEls(html: string, tag: string): El[] {
  const out: El[] = []
  const re = new RegExp(`<${tag}\\b([^>]*)>([\\s\\S]*?)</${tag}>`, 'gi')
  let m: RegExpExecArray | null
  while ((m = re.exec(html))) {
    const attrs: Record<string, string> = {}
    const ar = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*"([^"]*)"/g
    let a: RegExpExecArray | null
    while ((a = ar.exec(m[1]))) attrs[a[1].toLowerCase()] = a[2]
    out.push({ tag, attrs, text: m[2].replace(/<[^>]*>/g, '').trim(), raw: m[0] })
  }
  return out
}

type ExitCheck = { ok: boolean; failures: string[] }

/** 返回出口判据：存在可点击链接，href 解析为同源根 `/`，且可见。 */
function checkBackExit(html: string): ExitCheck {
  const failures: string[] = []
  const anchors = parseEls(html, 'a')
  if (anchors.length === 0) {
    failures.push('BACK-EXIT-LINK 页面无任何 <a> 链接元素（返回出口必须是无 JS 依赖的真实链接）')
    return { ok: false, failures }
  }
  const resolved = anchors
    .filter((e) => typeof e.attrs.href === 'string')
    .map((e) => {
      let pathname = '', origin = '', ok = false
      try {
        const u = new URL(e.attrs.href as string, BASE)
        pathname = u.pathname
        origin = u.origin
        ok = true
      } catch { /* 不可解析 */ }
      return { e, pathname, origin, ok }
    })
  const toRoot = resolved.filter((r) => r.ok && r.pathname === '/' && r.origin === new URL(BASE).origin)
  if (toRoot.length === 0) {
    failures.push(
      `BACK-EXIT-TARGET 无链接解析到同源根 "/"（期望返回 DSH 宿主页）；实际 href=${JSON.stringify(
        resolved.map((r) => (r.e.attrs.href ?? null)))}`)
    return { ok: false, failures }
  }
  const visible = toRoot.filter(({ e }) => {
    const style = (e.attrs.style || '').replace(/\s+/g, '').toLowerCase()
    const hidden = 'hidden' in e.attrs || style.includes('display:none') || style.includes('visibility:hidden')
    return !hidden && e.text.length > 0
  })
  if (visible.length === 0) {
    failures.push('BACK-EXIT-VISIBLE 指向 "/" 的链接存在但不可见/无标签文字（hidden 或 display:none 或空文本）')
    return { ok: false, failures }
  }
  return { ok: true, failures: [] }
}

/* ————— 定点变异：抽掉出口 ⇒ 守卫必须红 ————— */

function stripBackExit(html: string): string {
  return html.replace(/<a\b[^>]*id="dshm-rp-back"[^>]*>[\s\S]*?<\/a>/gi, '')
}

/** 变异 B：出口还在，但目标改成页面自身（href="/roleplay"）——不再返回 DSH。 */
function retargetBackExit(html: string): string {
  return html.replace(/(<a\b[^>]*id="dshm-rp-back"[^>]*href=")\/(?=")/i, '$1/roleplay')
}

const MUTATIONS: Record<string, (h: string) => string> = { A: stripBackExit, B: retargetBackExit }

/* ————— 变异自证 CLI（`--mutate A|B`，照 python 侧 --mutate 范式） ————— */

if (process.argv.includes('--mutate')) {
  const idx = process.argv.indexOf('--mutate')
  const name = process.argv[idx + 1] || ''
  const apply = MUTATIONS[name]
  if (!apply) {
    console.log(`未知组名 ${JSON.stringify(name)}（可选 ${Object.keys(MUTATIONS).sort().join('/')}）`)
    process.exit(1)
  }
  const html = await renderPage()
  const base = checkBackExit(html)
  console.log(`!! #20 定点变异自证 · 组 ${name}：注入缺陷，要求守卫点名到具体断言\n`)
  console.log(`  未变异基线：ok=${base.ok} failures=${JSON.stringify(base.failures)}（应为 ok=true / []）`)
  const mutated = apply(html)
  console.log(`  变异：HTML 长度 ${html.length} → ${mutated.length}`)
  const red = checkBackExit(mutated)
  const named = red.failures.some((f) => f.startsWith('BACK-EXIT-'))
  const pass = base.ok && !red.ok && named
  console.log(`  [${pass ? 'OK' : 'BAD'}] 变异后：ok=${red.ok} failures=${JSON.stringify(red.failures)}（须 ok=false 且点名 BACK-EXIT-*）`)
  console.log(pass ? '\n变异自证通过：守卫因出口缺陷转红并点名' : '\n变异自证失败：守卫未如期转红')
  process.exit(pass ? 0 : 1)
}

/* ————— 正式守卫 ————— */

test('#20 /roleplay 页面含可点击返回出口（真实链接 → 同源根 "/"）', async () => {
  const html = await renderPage()
  const r = checkBackExit(html)
  assert.deepEqual(r.failures, [], `返回出口判据未通过：${JSON.stringify(r.failures)}`)
  // 反向对照：出口不得只靠 history.back（Electron 壳无后退键）——必须有真实 href 链接
  const anchors = parseEls(html, 'a')
  assert.ok(anchors.some((e) => e.attrs.href && e.attrs.href === '/'),
    '返回出口必须是 href="/" 的真实链接（不得只依赖 history.back）')
})

test('#20 守卫自身：抽掉出口后判据必红并点名（防守卫空转）', async () => {
  const html = await renderPage()
  assert.equal(checkBackExit(html).ok, true, 'sanity：原页面应通过')
  const red = checkBackExit(stripBackExit(html))
  assert.equal(red.ok, false, '抽掉出口后判据必须转红（否则守卫是摆设）')
  assert.ok(red.failures.some((f) => f.startsWith('BACK-EXIT-')),
    `红项必须点名到 BACK-EXIT-* 断言，实际：${JSON.stringify(red.failures)}`)
})
