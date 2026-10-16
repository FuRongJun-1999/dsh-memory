/**
 * #490 守卫 · roleplay_web **读面**鉴权（SEC P0）
 *
 * 缺陷（修复前）：四个写端点全部过 requireEditKey（P1-2），三个**读**端点一个都没有——
 * 默认部署（ROLEPLAY_EDIT_KEY 未设）下任意本机 HTTP 客户端可 200 取回：
 *   GET /roleplay/api/roles/:id/items → 三导入副本正文（私有）
 *   GET /roleplay/api/translate      → 自定义翻译表
 *   GET /roleplay/api/history        → 完整对话转录
 * 即「写保护了、读没保护」的同族不对称。
 *
 * 本守卫三条腿：
 *   A（服务端·真 handler 实跑）：未配置 key ⇒ 三个读全 403；配置 key 但无头 ⇒ 403；
 *     带对头 ⇒ 200 且**私有正文确实回得来**（证明修复不是一刀切挡死）。
 *   K（过度收紧腿）：/roleplay/api/roles（首屏角色列表）在未配置 key 时仍 200 ——
 *     否则页面**在任何鉴权输入之前**就起不来。
 *     ★**这条腿不判别**「首屏角色列表是否也该鉴权」——那是维护者裁定项（纳入就必须把
 *     页面首屏改成先鉴权、属可用性面变更），本守卫只登记现状、不定性。
 *
 * 【登记·已核、不属本件修复面】GET /roleplay/api/roles（首屏角色列表）：
 *   · 本件标题与影响面三项（items / translate / history）都不含它，故未纳入；
 *   · 它回 {id, name, scenario, first_mes}（角色列表）；
 *   · **若维护者日后要把它一并纳入鉴权：前端必须同步改 `refreshRoles()` 那一处 read fetch**
 *     （当前不带 apiHeaders()）——**漏改就与「只改服务端」同型误伤，页面首屏直接起不来**；
 *     该配套改动点写在此处，防止下一个人只改服务端。
 *   F（前端配对腿 · **结构面**）：判据＝服务端**实际吐出的 HTML 内脚本**里，三个读请求的
 *     fetch 必须都带 headers: apiHeaders()。
 *     ⚠️ 如实登记：这条腿是**结构判据（对服务端吐出的脚本做形态断言），不是执行判据**
 *     （未在 mock DOM 里真跑那三个函数）；它存在的理由是修前实测发现 issue 正文的
 *     「前端零改动」不成立——三个读请求里只有 history 那一处带了 apiHeaders()，另外两处
 *     没带；只改服务端会把「已配置 ROLEPLAY_EDIT_KEY」的部署打成 403 误伤。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { installRoleplayWeb } from '../src/lib/roleplay_web.ts'

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

/** 挂载（与 test/roleplay_edit_guard.test.ts 同形制）。可提前写 _roles.json 造私有数据。 */
async function mount(seed?: (dir: string) => void) {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-rpread-'))
  if (seed) seed(dir)
  let handler: ((req: any, res: any) => Promise<void>) | null = null
  const ctx: any = {
    logger: { info: () => {}, warn: () => {} },
    get(key: string) { return key === 'webServer' ? this.webServer : undefined },
    webServer: {
      register(opts: any) { handler = opts.handler; return () => {} },
      tapIndex() { return () => {} },
    },
  }
  await installRoleplayWeb(ctx, null, { dbPath: join(dir, 'test.db') }, [] as Array<() => void>)
  return { dir, handler: handler as unknown as (req: any, res: any) => Promise<void> }
}

const READS = [
  ['items', '/roleplay/api/roles/r1/items?kind=memory'],
  ['translate', '/roleplay/api/translate?role_id=r1'],
  ['history', '/roleplay/api/history?role_id=r1'],
] as const

const KEY = 'read-guard-key'

function withKey<T>(v: string | undefined, fn: () => Promise<T>): Promise<T> {
  const prev = process.env.ROLEPLAY_EDIT_KEY
  if (v === undefined) delete process.env.ROLEPLAY_EDIT_KEY
  else process.env.ROLEPLAY_EDIT_KEY = v
  return fn().finally(() => {
    if (prev !== undefined) process.env.ROLEPLAY_EDIT_KEY = prev
    else delete process.env.ROLEPLAY_EDIT_KEY
  })
}

/* ————— A01：未配置 ROLEPLAY_EDIT_KEY（默认部署）⇒ 三个读全 403 ————— */

test('A01 默认部署（key 未配置）：三个读端点全 403，且文案引导配置', async () => {
  await withKey(undefined, async () => {
    const { dir, handler } = await mount()
    try {
      for (const [name, url] of READS) {
        const r = makeRes()
        await handler(makeReq('GET', url, {}), r)
        assert.equal(r._state.status, 403, `${name} 未配置 key 必须 403（got ${r._state.status}）`)
        const body = JSON.parse(r._state.body || '{}')
        assert.equal(body.ok, false, `${name} 403 体应为 ok:false`)
        assert.ok(String(body.error || '').includes('ROLEPLAY_EDIT_KEY'),
          `${name} 403 文案应引导配置（got ${body.error}）`)
      }
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })
})

/* ————— A02/A03：配置了 key ⇒ 无头 403 / 带头 200 且私有正文回得来 ————— */

test('A02/A03 配置 key：无 x-edit-key 头 ⇒ 403；带对头 ⇒ 200 且私有正文仍可读', async () => {
  await withKey(KEY, async () => {
    const secret = 'PRIVATE-MEMORY-ANCHOR-正文'
    const { dir, handler } = await mount((d) => {
      const p = join(d, 'roleplay_data', 'roleplay')
      mkdirSync(p, { recursive: true })
      writeFileSync(join(p, '_roles.json'),
        JSON.stringify({ meta: { r1: { name: 'r1', memory_items: [{ content: secret }] } } }), 'utf8')
    })
    try {
      for (const [name, url] of READS) {
        const r = makeRes()
        await handler(makeReq('GET', url, {}), r)
        assert.equal(r._state.status, 403, `${name} 配置了 key 但无头必须 403（got ${r._state.status}）`)
      }
      // 带对头：三个读都要 200
      for (const [name, url] of READS) {
        const r = makeRes()
        await handler(makeReq('GET', url, { 'x-edit-key': KEY }), r)
        assert.equal(r._state.status, 200, `${name} 带对头必须 200（got ${r._state.status}）`)
      }
      // ★私有正文确实回得来（证明修复不是一刀切挡死）
      const r = makeRes()
      await handler(makeReq('GET', '/roleplay/api/roles/r1/items?kind=memory', { 'x-edit-key': KEY }), r)
      assert.ok(r._state.body.includes(secret), '带对头时三导入正文必须仍可读回（非一刀切）')
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })
})

/* ————— K：过度收紧腿 — 首屏角色列表必须仍可无 key 取 ————— */

test('K01 【过度收紧腿】未配置 key 时 /roleplay/api/roles 仍 200（否则页面起不来）', async () => {
  await withKey(undefined, async () => {
    const { dir, handler } = await mount()
    try {
      const r = makeRes()
      await handler(makeReq('GET', '/roleplay/api/roles', {}), r)
      assert.equal(r._state.status, 200,
        '首屏角色列表必须仍可无 key 取（页面在任何鉴权输入之前就要渲染选择器）')
      assert.ok(JSON.parse(r._state.body || '{}').roles, '应回 {roles:[...]}')
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })
})

/* ————— F：前端配对腿（结构面，判据＝服务端实际吐出的脚本） ————— */

test('F01 【前端配对腿·结构面】服务端吐出的脚本里，三个读请求都带 apiHeaders()', async () => {
  const { dir, handler } = await mount()
  try {
    const r = makeRes()
    await handler(makeReq('GET', '/roleplay', {}), r)
    const html = r._state.body
    const start = html.indexOf('<script>')
    const end = html.indexOf('</script>')
    assert.ok(start >= 0 && end > start, '页面应内嵌 <script>')
    const code = html.slice(start + '<script>'.length, end)
    const probes: Array<[string, RegExp]> = [
      ['items', /fetch\('\/roleplay\/api\/roles\/'[^\n]*\/items\?kind=[^\n]*\{ headers: apiHeaders\(\) \}/],
      ['translate', /fetch\('\/roleplay\/api\/translate\?role_id='[^\n]*\{ headers: apiHeaders\(\) \}/],
      ['history', /fetch\('\/roleplay\/api\/history\?role_id='[^\n]*\{ headers: apiHeaders\(\) \}/],
    ]
    for (const [name, re] of probes) {
      assert.ok(re.test(code),
        `${name} 读请求必须带 headers: apiHeaders()（否则配置了 ROLEPLAY_EDIT_KEY 的部署会 403 误伤）`)
    }
  } finally { rmSync(dir, { recursive: true, force: true }) }
})