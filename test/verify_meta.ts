/**
 * verify_meta.ts · meta 嵌套格式读写一致验证（GPT 审查完善）
 * 场景（GPT 复现）：文件 {meta:{r:{name:'Nested'}}} → POST /meta 改名 →
 * 此前写根对象 {r:{name:'Changed'}} 但 GET 列表读嵌套旧值 Nested。
 * 修复后：写保持嵌套结构 → GET 读到 Changed。
 */
import { installRoleplayWeb } from '../src/roleplay_web.ts'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'

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
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-meta-'))
  // 预置嵌套格式 _roles.json：{meta:{r:{name:'Nested'}}}
  const metaFile = join(dir, 'roleplay_data', 'roleplay', '_roles.json')
  mkdirSync(dirname(metaFile), { recursive: true })
  writeFileSync(metaFile, JSON.stringify({ meta: { r: { name: 'Nested', created_at: 1 } } }), 'utf8')

  let handler: ((req: any, res: any) => Promise<void>) | null = null
  const ctx: any = {
    logger: { info: () => {}, warn: () => {} },
    webServer: {
      register(opts: any) { handler = opts.handler; return () => {} },
      tapIndex() { return () => {} },
    },
  }
  const bridge: any = { async callTool() { return { content: [{ type: 'text', text: '{}' }], isError: false } } }
  await installRoleplayWeb(ctx, bridge, { dbPath: join(dir, 'test.db') }, [] as Array<() => void>)
  if (!handler) { console.error('handler 未注册'); process.exit(1) }

  // ① 改名（写 meta，嵌套格式应保持嵌套）
  const r1 = makeRes()
  await handler(makeReq('POST', '/roleplay/api/roles/r/meta', {}, JSON.stringify({ name: 'Changed' })), r1)
  check('① 写 meta 返回 200', r1._state.status === 200)

  // ② 文件仍是嵌套结构且新值在 meta 内（不是根对象重复）
  const raw = JSON.parse(readFileSync(metaFile, 'utf8'))
  check('② 保持嵌套结构', raw.meta && raw.meta.r && raw.meta.r.name === 'Changed',
    `meta.r.name=${raw.meta?.r?.name}, 根有r=${'r' in raw}`)

  // ③ GET 列表读到新值（不再旧值 Nested）
  const r2 = makeRes()
  await handler(makeReq('GET', '/roleplay/api/roles', {}), r2)
  const roles = JSON.parse(r2._state.body || '{}').roles || []
  const r = roles.find((x: any) => x.id === 'r')
  check('③ 列表读到新值 Changed', r && r.name === 'Changed', `got ${r?.name}`)

  // ④ 追加翻译也保持嵌套（写路径一致）
  const r3 = makeRes()
  await handler(makeReq('POST', '/roleplay/api/translate', {}, JSON.stringify({ role_id: 'r', pairs: [{ real: '手机', virtual: '神之眼终端' }] })), r3)
  const raw2 = JSON.parse(readFileSync(metaFile, 'utf8'))
  check('④ 翻译写嵌套内一致', raw2.meta && Array.isArray(raw2.meta.r.translations) && raw2.meta.r.translations.length === 1,
    `translations=${raw2.meta?.r?.translations?.length}`)

  rmSync(dir, { recursive: true, force: true })
  console.log(`\nmeta 一致性验证: ${pass}/${pass + fail} 通过`)
  process.exit(fail > 0 ? 1 : 0)
}

main().catch((err) => { console.error('异常:', err); process.exit(1) })
