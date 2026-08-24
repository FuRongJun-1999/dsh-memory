/**
 * verify_session.ts · 会话隔离验证（GPT 审查完善）
 * ① 不同 x-client-id → 不同 session_id + 不同转录文件（互不串线）
 * ② 无 header → 落 shared（兼容旧客户端）
 */
import { installRoleplayWeb } from '../src/roleplay_web.ts'
import { mkdtempSync, rmSync, readdirSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

let pass = 0, fail = 0
function check(name: string, ok: boolean, detail = ''): void {
  if (ok) pass++; else fail++
  console.log(`[${ok ? '✓' : '✘'}] ${name}${detail ? ' — ' + detail : ''}`)
}

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

async function main(): Promise<void> {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-sess-'))
  let handler: ((req: any, res: any) => Promise<void>) | null = null
  const sessions: string[] = []
  const ctx: any = {
    logger: { info: () => {}, warn: () => {} },
    webServer: {
      register(opts: any) { handler = opts.handler; return () => {} },
      tapIndex() { return () => {} },
    },
  }
  const bridge: any = {
    async callTool(name: string, args: any) {
      if (name === 'roleplay_chat') {
        sessions.push(args.session_id)
        return { content: [{ type: 'text', text: JSON.stringify({ reply: '你好' + (args.session_id || '') }) }], isError: false }
      }
      return { content: [{ type: 'text', text: '{}' }], isError: false }
    },
  }
  await installRoleplayWeb(ctx, bridge, { dbPath: join(dir, 'test.db') }, [] as Array<() => void>)
  if (!handler) { console.error('handler 未注册'); process.exit(1) }

  // ① 客户端 A 发一条
  const r1 = makeRes()
  await handler(makeReq('POST', '/roleplay/api/chat', { 'x-client-id': 'clientA' },
    JSON.stringify({ role_id: 'r', message: '你好A' })), r1)
  // ② 客户端 B 发一条
  const r2 = makeRes()
  await handler(makeReq('POST', '/roleplay/api/chat', { 'x-client-id': 'clientB' },
    JSON.stringify({ role_id: 'r', message: '你好B' })), r2)
  // ③ 无 header 发一条
  const r3 = makeRes()
  await handler(makeReq('POST', '/roleplay/api/chat', {},
    JSON.stringify({ role_id: 'r', message: '你好C' })), r3)

  check('① A/B 的 session_id 不同（不串线）', sessions.length >= 2 && sessions[0] !== sessions[1],
    `${sessions[0]} vs ${sessions[1]}`)
  check('② 无 header → shared session', sessions.length >= 3 && sessions[2].includes('shared'),
    sessions[2] || '')

  // 转录文件隔离：r__clientA.jsonl / r__clientB.jsonl / r__shared.jsonl 各自独立
  const transDir = join(dir, 'roleplay_data', 'transcripts')
  const files = readdirSync(transDir).sort()
  check('③ 转录文件按客户端隔离', files.some(f => f.includes('__clientA')) && files.some(f => f.includes('__clientB')) && files.some(f => f.includes('__shared')),
    files.join(', '))

  // ④ A 的历史只含 A 的消息（1 次 chat = user+bot 2 条，且无 B/C 内容）
  const r4 = makeRes()
  await handler(makeReq('GET', '/roleplay/api/history?role_id=r', { 'x-client-id': 'clientA' }), r4)
  const hA = JSON.parse(r4._state.body || '{}').history || []
  check('④ A 的历史只含自己的消息', hA.length === 2 && hA.some((m: any) => m.text.includes('你好A')) && !hA.some((m: any) => m.text.includes('B')) && !hA.some((m: any) => m.text.includes('C')),
    `A history ${hA.length} 条`)

  rmSync(dir, { recursive: true, force: true })
  console.log(`\n会话隔离验证: ${pass}/${pass + fail} 通过`)
  process.exit(fail > 0 ? 1 : 0)
}

main().catch((err) => { console.error('异常:', err); process.exit(1) })
