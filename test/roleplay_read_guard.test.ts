/**
 * V23 守卫 · 角色扮演网页读端点鉴权（issue #490）
 *
 * 缺陷（修前）：四个写 POST 都过 requireEditKey（P1-2 fail-closed），但三个 GET
 * 读端点（/api/roles/:id/items、/api/translate、/api/history）一个都没有——
 * 默认部署（未配 ROLEPLAY_EDIT_KEY）下任意本机 HTTP 客户端 200 取回三导入正文、
 * 完整转录、翻译表；roleplay_web 是唯一对浏览器开放的 HTTP 面。
 *
 * 修复：三个 GET 与写面同款 requireEditKey（未配置即 403 / 配置后校验
 * x-edit-key）；前端 history/translate/items 三处读请求统一带 apiHeaders()。
 *
 * 本测试只看行为与源码钉子，不起真实网络：复用 roleplay_edit_guard 的
 * makeReq/makeRes mock（同一安装入口 installRoleplayWeb）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { installRoleplayWeb } from '../src/lib/roleplay_web.ts'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC = join(__dirname, '..', 'src', 'lib', 'roleplay_web.ts')

function makeReq(method: string, url: string, headers: Record<string, string> = {}, body = '') {
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
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-rpread-'))
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

/** 三个读端点（名称 → URL）。断言消息里点名，便于定点变异逐名核对。 */
const READS: Array<[string, string]> = [
  ['items', '/roleplay/api/roles/r1/items?kind=memory'],
  ['translate', '/roleplay/api/translate?role_id=protocol-guide'],
  ['history', '/roleplay/api/history?role_id=protocol-guide'],
]

async function call(handler: any, method: string, url: string, headers: Record<string, string> = {}) {
  const res = makeRes()
  await handler(makeReq(method, url, headers), res)
  return res
}

function restoreEnv(prev: string | undefined) {
  if (prev === undefined) delete process.env.ROLEPLAY_EDIT_KEY
  else process.env.ROLEPLAY_EDIT_KEY = prev
}

test('默认部署（未配置 ROLEPLAY_EDIT_KEY）：items/translate/history 三个读端点一律 403', async () => {
  const prev = process.env.ROLEPLAY_EDIT_KEY
  delete process.env.ROLEPLAY_EDIT_KEY
  try {
    const { dir, handler } = await mount()
    try {
      for (const [name, url] of READS) {
        const res = await call(handler, 'GET', url)
        assert.equal(res._state.status, 403, `${name} 应 403（issue #490 读面漏闸）`)
        const body = JSON.parse(res._state.body)
        assert.equal(body.ok, false, `${name} 拒绝体应为 ok=false`)
        assert.match(String(body.error), /未开放|ROLEPLAY_EDIT_KEY/, `${name} 拒绝体应引导配置密钥`)
      }
      // 对照：页面与角色列表（元数据）不在本件范围，仍 200
      assert.equal((await call(handler, 'GET', '/roleplay'))._state.status, 200, '/roleplay 页面仍应 200（否则无法进页面设置密钥）')
      assert.equal((await call(handler, 'GET', '/roleplay/api/roles'))._state.status, 200, '/roleplay/api/roles 对照仍应 200（本件不动）')
    } finally { rmSync(dir, { recursive: true, force: true }) }
  } finally { restoreEnv(prev) }
})

test('配置 ROLEPLAY_EDIT_KEY：无 x-edit-key 403、带正确头 200（读面与写面同款）', async () => {
  const prev = process.env.ROLEPLAY_EDIT_KEY
  process.env.ROLEPLAY_EDIT_KEY = 'guard-key-490'
  try {
    const { dir, handler } = await mount()
    try {
      for (const [name, url] of READS) {
        assert.equal((await call(handler, 'GET', url))._state.status, 403, `${name} 无 x-edit-key 应 403`)
        const bad = await call(handler, 'GET', url, { 'x-edit-key': 'wrong' })
        assert.equal(bad._state.status, 403, `${name} 错误 x-edit-key 应 403`)
        const ok = await call(handler, 'GET', url, { 'x-edit-key': 'guard-key-490' })
        assert.equal(ok._state.status, 200, `${name} 带正确 x-edit-key 应 200`)
      }
    } finally { rmSync(dir, { recursive: true, force: true }) }
  } finally { restoreEnv(prev) }
})

test('源码钉子：三个 GET 分支各自在返回前调用 requireEditKey；三处前端读请求带 apiHeaders()', () => {
  const src = readFileSync(SRC, 'utf8')
  const markers = [
    "url.pathname.startsWith('/roleplay/api/roles/') && url.pathname.endsWith('/items')",
    "req.method === 'GET' && url.pathname === '/roleplay/api/translate'",
    "req.method === 'GET' && url.pathname === '/roleplay/api/history'",
  ]
  for (const m of markers) {
    const i = src.indexOf(m)
    assert.ok(i >= 0, `分支锚点存在：${m}`)
    const j = src.indexOf('if (req.method ===', i + m.length)
    const body = src.slice(i, j === -1 ? src.length : j)
    assert.match(body, /requireEditKey\(req\)/, `GET 分支须调用 requireEditKey：${m}`)
  }
  // 三处前端读请求（GET）：截取 URL 片段后 400 字符窗口，须出现 apiHeaders()
  const readCalls = [
    '/roleplay/api/history?',
    '/roleplay/api/translate?',
    "/roleplay/api/roles/' + encodeURIComponent(role) + '/items?",
  ]
  for (const r of readCalls) {
    const i = src.indexOf(r)
    assert.ok(i >= 0, `前端读请求存在：${r}`)
    const win = src.slice(i, i + 400)
    assert.match(win, /apiHeaders\(\)/, `前端读请求须带 apiHeaders()：${r}`)
  }
})
