/**
 * 守卫 · 角色扮演 chat 入口类型闸 + 落盘顺序（对应缺陷：src/lib/roleplay_web.ts:852-865，N266）
 *
 * 缺陷链条（修复前，本测实跑取证）：
 *  · 服务端内容硬拦截直接 `p.message.includes(w)`：message 为 **JSON 数组**时静默走
 *    Array.prototype.includes（逐元素**全等**比较）——把敏感词拆进不同元素，服务端
 *    「未成年 ∧ 性」的合取判据即整条失配 ⇒ 请求照旧转发 roleplay_chat（能力挂载态 200）；
 *    数字/对象/缺省则抛 TypeError 落 500（内部异常文本随响应外泄）。
 *  · 落盘顺序：appendTranscript / toGraph 写在内容门控与 capReady 之间——能力未接入
 *    （默认 503）时，未经门控的 message 原文已被留进本地转录。
 *
 * 守卫取向：全部**行为断言**（发真请求、读真响应与真转录文件），不比对源码文本。
 * 样本值一律哑值：内容类别词取自语义类别（法律保护面），非任何真实人物/事件。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, existsSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installRoleplayWeb } from '../src/lib/roleplay_web.ts'

/* ————— 服务端挂载 mock（照 roleplay_edit_guard.test.ts 的 makeReq/makeRes 形制） ————— */

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

interface Mounted {
  dir: string
  handler: (req: any, res: any) => Promise<void>
  /** 引擎转发台账：非空即「请求已触达 roleplay_chat」。 */
  calls: Array<{ name: string; args: any }>
}

/** @param withCapability true＝能力挂载态（isReady=true）；false＝默认缺省态（capReady=false ⇒ 503） */
async function mount(withCapability: boolean): Promise<Mounted> {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-rpgate-'))
  let handler: ((req: any, res: any) => Promise<void>) | null = null
  const calls: Array<{ name: string; args: any }> = []
  const capability = withCapability ? {
    isReady: () => true,
    async callTool(name: string, args: any) {
      calls.push({ name, args })
      return { content: [{ type: 'text', text: JSON.stringify({ reply: '（哑）引擎回复', route: 'engine' }) }], isError: false }
    },
  } : null
  const ctx: any = {
    logger: { info: () => {}, warn: () => {} },
    get(key: string) { return key === 'webServer' ? this.webServer : undefined },
    webServer: {
      register(opts: any) { handler = opts.handler; return () => {} },
      tapIndex() { return () => {} },
    },
  }
  await installRoleplayWeb(ctx, capability, { dbPath: join(dir, 'test.db') }, [] as Array<() => void>)
  assert.ok(handler, 'handler 应注册（sanity）')
  return { dir, handler: handler as unknown as (req: any, res: any) => Promise<void>, calls }
}

const chatBody = (message: unknown): string => JSON.stringify({ role_id: 'r', message })
const transPath = (dir: string): string =>
  join(dir, 'roleplay_data', 'transcripts', 'r__shared.jsonl')
const readTrans = (dir: string): string =>
  existsSync(transPath(dir)) ? readFileSync(transPath(dir), 'utf8') : ''

/** 哑样本：内容类别词（MINOR ∧ NSFW 合取即服务端硬拦截面）。 */
const MINOR = '未成年'
const NSFW_TEXT = '想做爱的人'
/** 数组形态：逐元素**全等**比较下，两个元素都不等于词表里的任何一条。 */
const ARRAY_PAYLOAD = [MINOR, NSFW_TEXT]

/* ————— ① 数组 message + 能力挂载态：不得转发（拒 = 400，非 200） ————— */

test('① 数组 message 不得绕过内容门控：能力挂载态须拒（400）且零转发', async () => {
  const m = await mount(true)
  try {
    const r = makeRes()
    await m.handler(makeReq('POST', '/roleplay/api/chat', {}, chatBody(ARRAY_PAYLOAD)), r)
    assert.equal(m.calls.length, 0,
      `非字符串 message 不得转发 roleplay_chat（实发 ${m.calls.length} 次：${JSON.stringify(m.calls.map(c => c.name))}）`)
    assert.equal(r._state.status, 400, `非字符串 message 应 400（got ${r._state.status}，body=${r._state.body}）`)
    const body = JSON.parse(r._state.body || '{}')
    assert.equal(body.ok, false, `应回结构化拒绝（ok:false）：${r._state.body}`)
    assert.equal(body.route, 'refused', `应带 refused 标记（与内容拒绝同口径）：${r._state.body}`)
  }
  finally { rmSync(m.dir, { recursive: true, force: true }) }
})

/* ————— ② 数组 message + 默认 503 态：原文不得留进本地转录 ————— */

test('② 能力缺省（503 态）时，数组 message 的原文不得落进本地转录', async () => {
  const m = await mount(false)
  try {
    const r = makeRes()
    await m.handler(makeReq('POST', '/roleplay/api/chat', {}, chatBody(ARRAY_PAYLOAD)), r)
    const txt = readTrans(m.dir)
    assert.ok(!txt.includes(NSFW_TEXT), `未过门控的原文已留进转录：${txt}`)
    assert.ok(!txt.includes(MINOR), `未过门控的原文已留进转录：${txt}`)
  }
  finally { rmSync(m.dir, { recursive: true, force: true }) }
})

/* ————— ③ 类型面：数字/对象/null/布尔/缺省 一律 400，不许落 500 ————— */

test('③ 非字符串 message 的各形态一律 400（不留 TypeError → 500 面）', async () => {
  const m = await mount(true)
  try {
    for (const bad of [123, { text: 'x' }, null, true, undefined] as unknown[]) {
      const r = makeRes()
      await m.handler(makeReq('POST', '/roleplay/api/chat', {}, chatBody(bad)), r)
      assert.equal(r._state.status, 400,
        `message=${JSON.stringify(bad)} 应 400（got ${r._state.status}，body=${r._state.body}）`)
    }
    assert.equal(m.calls.length, 0, '非法形态一次都不得转发引擎')
  }
  finally { rmSync(m.dir, { recursive: true, force: true }) }
})

/* ————— ④ 回归：合法字符串 + 挂载态 —— 正常转发且 user/bot 两笔按序落盘 ————— */

test('④ 回归：字符串 message 正常转发，user/bot 两笔按序落转录', async () => {
  const m = await mount(true)
  try {
    const r = makeRes()
    await m.handler(makeReq('POST', '/roleplay/api/chat', {}, chatBody('你好，这是正常发言')), r)
    assert.equal(r._state.status, 200, `正常路径应 200（got ${r._state.status}，body=${r._state.body}）`)
    assert.equal(m.calls.length, 1, `正常路径应恰好转发一次（got ${m.calls.length}）`)
    assert.equal(m.calls[0].name, 'roleplay_chat')
    assert.equal(m.calls[0].args.message, '你好，这是正常发言', '转发给引擎的 message 须原样字符串')
    const lines = readTrans(m.dir).trim().split('\n').filter(Boolean).map((l) => JSON.parse(l))
    assert.equal(lines.length, 2, `正常回合应有 user+bot 两笔（got ${lines.length}）：${readTrans(m.dir)}`)
    assert.equal(lines[0].role, 'user')
    assert.ok(String(lines[0].text).includes('正常发言'), 'user 回合正文须落盘')
    assert.equal(lines[1].role, 'bot')
  }
  finally { rmSync(m.dir, { recursive: true, force: true }) }
})

/* ————— ⑤ 回归：字符串形态的内容硬拦截不变（200 route=refused，且不转发不落盘） ————— */

test('⑤ 回归：字符串「内容类别词 ∧ 性词」仍 200 route=refused，零转发零落盘', async () => {
  const m = await mount(true)
  try {
    const r = makeRes()
    await m.handler(makeReq('POST', '/roleplay/api/chat', {}, chatBody(`${MINOR} ${NSFW_TEXT}`)), r)
    const body = JSON.parse(r._state.body || '{}')
    assert.equal(r._state.status, 200, `内容拒绝维持既有形态（got ${r._state.status}）`)
    assert.equal(body.route, 'refused')
    assert.equal(body.refused, 'minor_nsfw')
    assert.equal(m.calls.length, 0, '被拒内容绝不转发')
    assert.ok(!readTrans(m.dir).includes(NSFW_TEXT), `被拒内容不得落转录：${readTrans(m.dir)}`)
  }
  finally { rmSync(m.dir, { recursive: true, force: true }) }
})

/* ————— ⑥ 顺序：能力缺省（503）时，合法字符串的 user 回合也不得落盘 ————— */

test('⑥ 能力缺省（503）时合法字符串亦不落转录——落盘在就绪闸之后', async () => {
  const m = await mount(false)
  try {
    const r = makeRes()
    await m.handler(makeReq('POST', '/roleplay/api/chat', {}, chatBody('你好，这是正常发言')), r)
    const body = JSON.parse(r._state.body || '{}')
    assert.equal(r._state.status, 503, `能力未接入仍须 fail-closed 503（got ${r._state.status}）`)
    assert.equal(body.route, 'unavailable', `503 语义不变：${r._state.body}`)
    assert.ok(!readTrans(m.dir).includes('正常发言'),
      `能力未接入时回合未发生，不得留转录：${readTrans(m.dir)}`)
    // 端到端同判：历史面（读同一转录文件）不得出现这条未发生的回合
    const r2 = makeRes()
    await m.handler(makeReq('GET', '/roleplay/api/history?role_id=r', {}), r2)
    const hist = JSON.parse(r2._state.body || '{}').history || []
    assert.equal(hist.length, 0, `未发生的回合不得进历史（got ${hist.length} 条）：${r2._state.body}`)
  }
  finally { rmSync(m.dir, { recursive: true, force: true }) }
})
