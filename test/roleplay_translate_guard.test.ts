/**
 * 守卫 · POST /roleplay/api/translate 非法 role_id 假成功
 * （对应缺陷：src/lib/roleplay_web.ts POST translate 分支）
 *
 * 缺陷链条（修复前）：
 *  · `const role = p.role_id || 'protocol-guide'` 提取后**无 validRoleId 校验**，
 *    随即调 setTranslations（其内部白名单不匹配**静默 return**，词对永不落盘）、
 *    `settings[role] = { mode }` 直接对象键赋值，最后仍回 `{ ok: true }`；
 *  · 中文 id（'纳西妲'）→ setTranslations 静默拒写 → GET 回读 pairs=[]，
 *    词对全部丢失，前端却收到成功；
 *  · '__proto__' id → settings['__proto__'] 走原型 setter 不产生 own 属性，
 *    translate_settings.json 落盘为空对象 → GET 连 mode 都丢回 input_only；
 *  · 同文件 /meta（roles/:id/meta）与 /chat 均已有同款 validRoleId → 400
 *    先例，唯独 translate POST 漏卡。
 *
 * 守卫（对修复前代码红）：
 *  ① 中文 role_id POST → 400 + ok:false（旧代码 200 + ok:true 假成功）
 *  ② '__proto__' role_id POST → 400 + ok:false（旧代码 200 + ok:true，mode 丢失）
 *  ③ 合法 role_id 正常路径不回归：200 + ok:true + GET 回读 pairs/mode 落盘
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, existsSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installRoleplayWeb } from '../src/lib/roleplay_web.ts'

/* ————— 服务端挂载 mock（照 roleplay_edit_guard.test.ts 形制） ————— */

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

/** 挂载（install 前设 ROLEPLAY_EDIT_KEY——EDIT_KEY 在 install 时闭包捕获）。 */
async function mount() {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-rptrans-'))
  let handler: ((req: any, res: any) => Promise<void>) | null = null
  const ctx: any = {
    logger: { info: () => {}, warn: () => {} },
    get(key: string) { return key === 'webServer' ? this.webServer : undefined },
    webServer: {
      register(opts: any) { handler = opts.handler; return () => {} },
      tapIndex() { return () => {} },
    },
  }
  process.env.ROLEPLAY_EDIT_KEY = 'test-key'
  await installRoleplayWeb(ctx, null, { dbPath: join(dir, 'test.db') }, [] as Array<() => void>)
  const h = (req: any, res: any) => (handler as any)(req, res)
  return {
    dir,
    handler: h,
    roleMetaFile: join(dir, 'roleplay_data', 'roleplay', '_roles.json'),
    transSettingsFile: join(dir, 'roleplay_data', 'transcripts', 'translate_settings.json'),
  }
}

const AUTH = { 'x-edit-key': 'test-key', 'content-type': 'application/json' }
const PAIRS = [{ real: '手机', virtual: '神之眼终端', note: '' }]

async function postTranslate(m: ReturnType<Awaited<ReturnType<typeof mount>> extends never ? never : any>, roleId: string | undefined) {
  const r = makeRes()
  await m.handler(makeReq('POST', '/roleplay/api/translate', AUTH,
    JSON.stringify({ role_id: roleId, pairs: PAIRS, mode: 'bidirectional' })), r)
  return { status: r._state.status, body: JSON.parse(r._state.body || '{}') }
}
async function getTranslate(m: any, roleId: string) {
  const r = makeRes()
  await m.handler(makeReq('GET', `/roleplay/api/translate?role_id=${encodeURIComponent(roleId)}`, AUTH), r)
  return JSON.parse(r._state.body || '{}')
}

/* ————— ① 中文 role_id：拒收而非假成功 ————— */

test('① 中文 role_id POST translate → 400 + ok:false（旧代码 200 假成功、词对静默丢失）', async () => {
  const prevKey = process.env.ROLEPLAY_EDIT_KEY
  const m = await mount()
  try {
    const { status, body } = await postTranslate(m, '纳西妲')
    assert.equal(status, 400, `非法角色 id 应 400（got ${status}）`)
    assert.equal(body.ok, false, 'ok 必须为 false——词对未落盘却回 true 即虚假成功')
    assert.ok(String(body.error || '').includes('角色'), '400 文案应说明角色 id 非法')
    // GET 回读：词对不得以任何形态落盘
    const back = await getTranslate(m, '纳西妲')
    assert.deepEqual(back.pairs, [], '非法 id 的词对不应落盘')
  } finally {
    if (prevKey !== undefined) process.env.ROLEPLAY_EDIT_KEY = prevKey
    else delete process.env.ROLEPLAY_EDIT_KEY
    rmSync(m.dir, { recursive: true, force: true })
  }
})

/* ————— ② '__proto__' role_id：原型污染向量拒收 ————— */

test('② __proto__ role_id POST translate → 400 + ok:false（旧代码 200、mode 经原型 setter 丢失）', async () => {
  const prevKey = process.env.ROLEPLAY_EDIT_KEY
  const m = await mount()
  try {
    const { status, body } = await postTranslate(m, '__proto__')
    assert.equal(status, 400, `__proto__ 应 400（got ${status}）`)
    assert.equal(body.ok, false)
    // settings 文件不得被写入危险键（own 属性形态）
    if (existsSync(m.transSettingsFile)) {
      const raw = JSON.parse(readFileSync(m.transSettingsFile, 'utf8'))
      assert.ok(!Object.prototype.hasOwnProperty.call(raw, '__proto__'),
        'translate_settings.json 不得含 __proto__ own 键')
    }
  } finally {
    if (prevKey !== undefined) process.env.ROLEPLAY_EDIT_KEY = prevKey
    else delete process.env.ROLEPLAY_EDIT_KEY
    rmSync(m.dir, { recursive: true, force: true })
  }
})

/* ————— ③ 合法路径回归保护（旧代码即绿，修复不得误伤） ————— */

test('③ 合法 role_id POST translate → 200 + ok:true + GET 回读词对与 mode 落盘', async () => {
  const prevKey = process.env.ROLEPLAY_EDIT_KEY
  const m = await mount()
  try {
    const { status, body } = await postTranslate(m, 'naxiaoda')
    assert.equal(status, 200, `合法 id 应 200（got ${status}）`)
    assert.equal(body.ok, true, '合法 id 必须成功')
    assert.equal(body.mode, 'bidirectional')
    // 落盘验证：_roles.json 与 translate_settings.json 均写入
    const meta = JSON.parse(readFileSync(m.roleMetaFile, 'utf8'))
    const metaDict = meta.meta && typeof meta.meta === 'object' ? meta.meta : meta
    assert.equal(metaDict.naxiaoda?.translations?.length, 1, '词对应写入 _roles.json')
    const settings = JSON.parse(readFileSync(m.transSettingsFile, 'utf8'))
    assert.equal(settings.naxiaoda?.mode, 'bidirectional', 'mode 应写入 translate_settings.json')
    // GET 回读一致
    const back = await getTranslate(m, 'naxiaoda')
    assert.equal(back.pairs.length, 1, 'GET 回读词对不丢')
    assert.equal(back.mode, 'bidirectional')
  } finally {
    if (prevKey !== undefined) process.env.ROLEPLAY_EDIT_KEY = prevKey
    else delete process.env.ROLEPLAY_EDIT_KEY
    rmSync(m.dir, { recursive: true, force: true })
  }
})

/* ————— ④ 非法 id 被拒后，已有角色的翻译配置不受殃及 ————— */

test('④ 非法 id 被拒不影响已落盘的合法角色配置', async () => {
  const prevKey = process.env.ROLEPLAY_EDIT_KEY
  const m = await mount()
  try {
    const ok1 = await postTranslate(m, 'naxiaoda')
    assert.equal(ok1.status, 200, 'sanity：合法写入应成功')
    const bad = await postTranslate(m, 'constructor')
    assert.equal(bad.status, 400, 'constructor 应 400')
    const back = await getTranslate(m, 'naxiaoda')
    assert.equal(back.pairs.length, 1, '合法角色词对不应被非法请求破坏')
    assert.equal(back.mode, 'bidirectional')
  } finally {
    if (prevKey !== undefined) process.env.ROLEPLAY_EDIT_KEY = prevKey
    else delete process.env.ROLEPLAY_EDIT_KEY
    rmSync(m.dir, { recursive: true, force: true })
  }
})
