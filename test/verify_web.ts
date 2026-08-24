/**
 * verify_web.ts · 角色扮演网页安全修复验证（GPT 审查）
 * ① ROLEPLAY_EDIT_KEY 配置时写操作无 key → 403
 * ② 带 x-edit-key → 放行
 * ③ body > 1MB → 413
 * ④ 引擎导入失败（isError）→ ok:false（此前恒 ok:true）
 */
import { installRoleplayWeb } from '../src/roleplay_web.ts'
import { mkdtempSync, rmSync } from 'node:fs'
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
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-web-'))
  process.env.ROLEPLAY_EDIT_KEY = 'secret-test-key'
  let handler: ((req: any, res: any) => Promise<void>) | null = null
  let importCalls = 0
  const ctx: any = {
    logger: { info: () => {}, warn: () => {} },
    webServer: {
      register(opts: any) { handler = opts.handler; return () => {} },
      tapIndex() { return () => {} },
    },
  }
  const bridge: any = {
    async callTool(name: string) {
      if (name === 'role_import') {
        importCalls++
        return { content: [{ type: 'text', text: '{"ok": true}' }], isError: importCalls === 1 } // 第一次失败
      }
      return { content: [{ type: 'text', text: 'ok' }], isError: false }
    },
  }
  await installRoleplayWeb(ctx, bridge, { dbPath: join(dir, 'test.db') }, [] as Array<() => void>)
  if (!handler) { console.error('handler 未注册'); process.exit(1) }

  // ① 无 key 写角色 → 403
  const r1 = makeRes()
  await handler(makeReq('POST', '/roleplay/api/roles', {}, JSON.stringify({ id: 'x', name: 'X' })), r1)
  check('① 无编辑密钥写操作 → 403', r1._state.status === 403, `got ${r1._state.status}`)

  // ② 带 key → 放行（角色创建返回 ok）
  const r2 = makeRes()
  await handler(makeReq('POST', '/roleplay/api/roles', { 'x-edit-key': 'secret-test-key' }, JSON.stringify({ id: 'r', name: 'R' })), r2)
  const b2 = JSON.parse(r2._state.body || '{}')
  check('② 带 x-edit-key → 放行', r2._state.status === 200 && b2.ok === true, `status ${r2._state.status} ok ${b2.ok}`)

  // ③ body 过大 → 413
  const big = JSON.stringify({ id: 'r', name: 'B', scenario: 'x'.repeat(1_100_000) })
  const r3 = makeRes()
  await handler(makeReq('POST', '/roleplay/api/roles', { 'x-edit-key': 'secret-test-key' }, big), r3)
  check('③ 请求体 >1MB → 413', r3._state.status === 413, `got ${r3._state.status}`)

  // ④ 引擎导入失败 → ok:false
  const r4 = makeRes()
  await handler(makeReq('POST', '/roleplay/api/roles/r/import', { 'x-edit-key': 'secret-test-key' },
    JSON.stringify({ kind: 'memory', items: [{ content: '测试记忆' }] })), r4)
  const b4 = JSON.parse(r4._state.body || '{}')
  check('④ 引擎导入失败 → ok:false', b4.ok === false && importCalls === 1, `ok ${b4.ok}`)

  // ⑤ 第二次导入成功 → ok:true
  const r5 = makeRes()
  await handler(makeReq('POST', '/roleplay/api/roles/r/import', { 'x-edit-key': 'secret-test-key' },
    JSON.stringify({ kind: 'memory', items: [{ content: '测试记忆2' }] })), r5)
  const b5 = JSON.parse(r5._state.body || '{}')
  check('⑤ 引擎导入成功 → ok:true', b5.ok === true, `ok ${b5.ok}`)

  delete process.env.ROLEPLAY_EDIT_KEY
  rmSync(dir, { recursive: true, force: true })
  console.log(`\n网页安全验证: ${pass}/${pass + fail} 通过`)
  process.exit(fail > 0 ? 1 : 0)
}

main().catch((err) => { console.error('异常:', err); process.exit(1) })
