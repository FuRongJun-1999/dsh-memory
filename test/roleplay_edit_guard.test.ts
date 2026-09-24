/**
 * V22 守卫 · 角色扮演网页编辑闭环（对应缺陷：src/lib/roleplay_web.ts:338）
 *
 * 缺陷链条（修复前）：
 *  · 服务端 requireEditKey fail-closed（未配置 ROLEPLAY_EDIT_KEY = 拒绝全部写），
 *    配置了又要求 x-edit-key 头——但网页既没有输入密钥的途径，四个写 POST
 *    （saveRoleDetail meta/import、saveTrans、createRole）又全用裸
 *    {'Content-Type': 'application/json'}——全部编辑操作恒 403 不可用；
 *  · saveRoleDetail 的 meta POST 响应完全不检查（fetch 对 403 不 reject），
 *    import 的 r.ok 也不看——服务端 403 在写盘之前 return，数据从未落盘，
 *    前端却无条件 addMsg「已保存」= 虚假成功反馈。
 *
 * 守卫（对修复前代码红）：
 *  ① 页面提供编辑密钥输入途径：setEditKey（🔑 → localStorage）+ apiHeaders 注入 x-edit-key
 *  ② saveRoleDetail / saveTrans / createRole 的写 POST 统一走 apiHeaders()（携带 x-edit-key）
 *  ③ saveRoleDetail 逐段检查响应 ok：403 响应绝不显示「已保存」、不关闭面板、alert 服务端原因
 *  ④ 服务端侧回归防线：无 key POST meta → 403 且 _roles.json 不落盘
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installRoleplayWeb } from '../src/lib/roleplay_web.ts'

/* ————— 服务端挂载 mock（照 verify_web.ts 的 makeReq/makeRes 形制） ————— */

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

async function mount() {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-rpedit-'))
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

/* ————— 浏览器沙箱：把页面 <script> 在 mock DOM/localStorage/fetch 下求值 ————— */

function makeEl(): any {
  const el: any = {
    value: '', textContent: '', innerHTML: '', className: '', checked: false,
    style: {}, children: [],
    classList: { toggle() {}, add() {}, remove() {} },
    appendChild(c: any) { el.children.push(c); return c },
    addEventListener() {},
    querySelector: () => makeEl(),
    scrollTop: 0, scrollHeight: 0, selectedOptions: [],
  }
  return el
}

/** 挂载 → GET /roleplay 拿页面 HTML → 求值脚本，返回可操纵的沙箱句柄。 */
async function setupPage() {
  const { dir, handler } = await mount()
  const res = makeRes()
  await handler(makeReq('GET', '/roleplay', {}), res)
  const html = res._state.body
  const start = html.indexOf('<script>')
  const end = html.indexOf('</script>')
  assert.ok(start >= 0 && end > start, '页面应内嵌 <script>')
  // 末尾追加导出钩子（typeof 守卫：旧代码缺 setEditKey 也能求值，导出 undefined → 断言红而非崩溃）
  const code = html.slice(start + '<script>'.length, end)
    + '\n;globalThis.__RP__ = {'
    + ' apiHeaders: typeof apiHeaders === "function" ? apiHeaders : undefined,'
    + ' saveRoleDetail: typeof saveRoleDetail === "function" ? saveRoleDetail : undefined,'
    + ' saveTrans: typeof saveTrans === "function" ? saveTrans : undefined,'
    + ' createRole: typeof createRole === "function" ? createRole : undefined,'
    + ' setEditKey: typeof setEditKey === "function" ? setEditKey : undefined };'

  const els = new Map<string, any>()
  const store = new Map<string, string>()
  const localStorageMock = {
    getItem: (k: string) => (store.has(k) ? store.get(k) : null),
    setItem: (k: string, v: string) => { store.set(k, String(v)) },
    removeItem: (k: string) => { store.delete(k) },
  }
  const documentMock = {
    getElementById: (id: string) => {
      if (!els.has(id)) els.set(id, makeEl())
      return els.get(id)
    },
    createElement: () => makeEl(),
    querySelector: () => makeEl(),
    querySelectorAll: (sel: string) =>
      sel === '#rd_items .rd-row' ? sandbox.rdRows.slice()
        : sel === '#tp_rows .tp-row' ? sandbox.tpRows.slice()
          : sel === 'input[name="tpmode"]' ? []
          : [],
  }
  const fetchLog: Array<{ url: string; method: string; headers: any }> = []
  let respond: (url: string) => any = () => ({ roles: [] })
  const fetchMock = (url: string, init: any = {}) => {
    fetchLog.push({ url, method: (init && init.method) || 'GET', headers: (init && init.headers) || {} })
    return Promise.resolve({ json: async () => respond(url) })
  }
  const alerts: string[] = []
  let promptReply = ''

  const sandbox: any = {
    dir, els, store, fetchLog, alerts,
    // 统一取元素入口：els 惰性填充，直接 Map.get 未访问过的 id 会是 undefined
    el: (id: string) => documentMock.getElementById(id),
    get respond() { return respond },
    set respond(fn: (url: string) => any) { respond = fn },
    setPrompt(v: string) { promptReply = v },
    rdRows: [] as any[],
    tpRows: [] as any[],
    RP: {} as any,
  }
  const run = new Function('document', 'window', 'localStorage', 'fetch', 'alert', 'prompt', code)
  run(documentMock, { addEventListener() {} }, localStorageMock, fetchMock,
    (m: string) => alerts.push(String(m)), () => promptReply)
  sandbox.RP = (globalThis as any).__RP__
  delete (globalThis as any).__RP__
  // 顶层 refreshRoles() 是 fire-and-forget async——flush 掉再测，避免污染 fetchLog
  await new Promise((r) => setTimeout(r, 10))
  fetchLog.length = 0
  return sandbox
}

/** 造一行「角色详情」条目（textarea/.rd-imp/.rd-tags 三个查询点）。 */
function rdRow(content: string): any {
  const row: any = makeEl()
  row.querySelector = (s: string) =>
    s === 'textarea' ? { value: content }
      : s === '.rd-imp' ? { value: '0.6' }
        : { value: '' }
  return row
}

/* ————— ① 编辑密钥输入途径存在 ————— */

test('① 页面 apiHeaders 注入 x-edit-key（localStorage 编辑密钥）', async () => {
  const s = await setupPage()
  assert.equal(typeof s.RP.apiHeaders, 'function', 'apiHeaders 应存在（sanity）')
  s.store.set('lingshu_edit_key', 'k1')
  const h = s.RP.apiHeaders()
  assert.equal(h['x-edit-key'], 'k1', '设置密钥后 apiHeaders 必须携带 x-edit-key（否则配置了 ROLEPLAY_EDIT_KEY 也无法编辑）')
})

test('① 页面提供 setEditKey（🔑 输入 → localStorage 持久化）', async () => {
  const s = await setupPage()
  assert.equal(typeof s.RP.setEditKey, 'function', '应存在 setEditKey 密钥输入函数')
  s.setPrompt('k2')
  s.RP.setEditKey()
  assert.equal(s.store.get('lingshu_edit_key'), 'k2', 'prompt 输入的密钥应写入 localStorage')
})

/* ————— ③ saveRoleDetail：403 响应绝不虚假成功 ————— */

test('③ saveRoleDetail 在 meta/import 均 403 时：alert 错误、不显示「已保存」、不关闭面板', async () => {
  const s = await setupPage()
  assert.equal(typeof s.RP.saveRoleDetail, 'function', 'saveRoleDetail 应存在（sanity）')
  // 未设置编辑密钥（服务端 ROLEPLAY_EDIT_KEY 场景由 mock 响应模拟：403 体 {ok:false,...}，fetch 不 reject）
  s.respond = () => ({ ok: false, error: '编辑未开放：服务端需配置环境变量 ROLEPLAY_EDIT_KEY，请求需带 x-edit-key 头（P1-2 fail-closed）' })
  s.el('rd_role').textContent = 'naxiaoda'
  s.el('rd_name').value = '纳西妲'
  s.el('rd_scenario').value = '场景'
  s.el('rd_first').value = ''
  s.el('rd_nsfw_chk').checked = false
  s.rdRows.push(rdRow('测试记忆'))
  await s.RP.saveRoleDetail()
  const chatMsgs = s.el('chat').children.map((c: any) => String(c.textContent))
  assert.ok(!chatMsgs.some((t: string) => t.includes('已保存')),
    `服务端拒绝（403 未落盘）时不得显示「已保存」（实际消息：${JSON.stringify(chatMsgs)}）——虚假成功反馈`)
  assert.ok(s.alerts.length >= 1, `失败必须 alert 服务端原因（实际 alerts：${JSON.stringify(s.alerts)}）`)
  assert.ok(s.alerts.some((t) => t.includes('ROLEPLAY_EDIT_KEY') || t.includes('编辑')),
    'alert 文案应携带服务端给出的原因')
  assert.notEqual(s.el('roledetail').style.display, 'none', '失败时不应关闭详情面板（用户需看到未保存状态）')
})

test('③ saveRoleDetail 配置密钥后成功：请求带 x-edit-key、显示「已保存」', async () => {
  const s = await setupPage()
  s.store.set('lingshu_edit_key', 'secret-key')
  s.respond = (url: string) =>
    url.includes('/meta') ? { ok: true }
      : url.includes('/import') ? { ok: true, kind: 'memory', items: [] }
        : { roles: [] }
  s.el('rd_role').textContent = 'naxiaoda'
  s.el('rd_name').value = '纳西妲'
  s.el('rd_scenario').value = ''
  s.el('rd_first').value = ''
  s.el('rd_nsfw_chk').checked = false
  s.rdRows.push(rdRow('测试记忆'))
  await s.RP.saveRoleDetail()
  const metaReq = s.fetchLog.find((e) => e.method === 'POST' && e.url.includes('/meta'))
  const importReq = s.fetchLog.find((e) => e.method === 'POST' && e.url.includes('/import'))
  assert.ok(metaReq, 'meta POST 应发出')
  assert.equal(metaReq?.headers['x-edit-key'], 'secret-key', 'meta POST 必须携带 x-edit-key（走 apiHeaders）')
  assert.equal(importReq?.headers['x-edit-key'], 'secret-key', 'import POST 必须携带 x-edit-key（走 apiHeaders）')
  const chatMsgs = s.el('chat').children.map((c: any) => String(c.textContent))
  assert.ok(chatMsgs.some((t: string) => t.includes('已保存')), '成功路径应显示已保存')
})

/* ————— ② saveTrans / createRole 写请求携带密钥 ————— */

test('② saveTrans / createRole 的写 POST 走 apiHeaders（携带 x-edit-key）', async () => {
  const s = await setupPage()
  assert.equal(typeof s.RP.saveTrans, 'function', 'saveTrans 应存在（sanity）')
  assert.equal(typeof s.RP.createRole, 'function', 'createRole 应存在（sanity）')
  s.store.set('lingshu_edit_key', 'secret-key')
  s.respond = (url: string) =>
    url === '/roleplay/api/translate' ? { ok: true, pairs: [], mode: 'input_only' }
      : url === '/roleplay/api/roles' ? { ok: true }
        : { roles: [] }
  // saveTrans
  const tp: any = makeEl()
  tp.querySelector = (sel: string) => ({ value: sel === '.tp-real' ? '手机' : sel === '.tp-virtual' ? '神之眼终端' : '' })
  s.tpRows.push(tp)
  s.el('roleSel').value = 'protocol-guide'
  await s.RP.saveTrans()
  const transReq = s.fetchLog.find((e) => e.method === 'POST' && e.url === '/roleplay/api/translate')
  assert.equal(transReq?.headers['x-edit-key'], 'secret-key', 'saveTrans POST 必须携带 x-edit-key（走 apiHeaders）')
  // createRole
  s.fetchLog.length = 0
  s.el('nr_id').value = 'tester'
  s.el('nr_name').value = '测试角色'
  s.el('nr_scenario').value = ''
  s.el('nr_first').value = ''
  await s.RP.createRole()
  const createReq = s.fetchLog.find((e) => e.method === 'POST' && e.url === '/roleplay/api/roles')
  assert.equal(createReq?.headers['x-edit-key'], 'secret-key', 'createRole POST 必须携带 x-edit-key（走 apiHeaders）')
})

/* ————— ④ 服务端侧回归防线：403 时不落盘 ————— */

test('④ 服务端：无编辑密钥 POST meta → 403 且 _roles.json 未写盘', async () => {
  const prevKey = process.env.ROLEPLAY_EDIT_KEY
  delete process.env.ROLEPLAY_EDIT_KEY  // fail-closed：未配置 = 拒绝全部写
  const { dir, handler } = await mount()
  try {
    const r = makeRes()
    await handler(makeReq('POST', '/roleplay/api/roles/naxiaoda/meta', {},
      JSON.stringify({ name: '纳西妲', scenario: 'x' })), r)
    const body = JSON.parse(r._state.body || '{}')
    assert.equal(r._state.status, 403, `无密钥写 meta 应 403（got ${r._state.status}）`)
    assert.equal(body.ok, false)
    assert.ok(String(body.error || '').includes('ROLEPLAY_EDIT_KEY'), '403 文案应引导配置')
    assert.equal(existsSync(join(dir, 'roleplay_data', 'roleplay', '_roles.json')), false,
      '403 在写盘之前 return——数据确实未落盘（前端若报成功即为虚假反馈）')
  } finally {
    if (prevKey !== undefined) process.env.ROLEPLAY_EDIT_KEY = prevKey
    rmSync(dir, { recursive: true, force: true })
  }
})
