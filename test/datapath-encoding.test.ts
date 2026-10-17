/**
 * datapath-encoding.test.ts · paths.json 必须严格 UTF-8 解码（issue #426-F）
 *
 * 缺陷（修前）：readFileSync(pf, 'utf8') 把 GBK/ANSI 存出的 paths.json 中的非法
 * 字节静默替换成 U+FFFD 后照常 JSON.parse —— 乱码路径被当成记忆根，插件侧新写入
 * 分叉进乱码空库；而同库 Python 侧（utf-8-sig 严格解码）抛 PathsConfigError。
 *
 * 修复语义：TextDecoder('utf-8', { fatal: true }) 与 Python 侧同口径——非法字节即抛
 * PathsConfigError（文案点名 UTF-8/ANSI/GBK）；BOM 仍正常读取；合法 UTF-8 与既有
 * 「坏 JSON 响亮失败」语义逐位不变。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const STATE = mkdtempSync(join(tmpdir(), 'lingshu-enc-'))
process.env.MDCG_STATE_ROOT = STATE
delete process.env.MDCG_ROOT
delete process.env.MDCG_DATA_ROOT

const dp = await import('../src/lib/datapath.ts')
const mdcgRoot = dp.mdcgRoot as (configured?: string) => string
const PathsConfigError = dp.PathsConfigError as new (m: string, p: string) => Error

const PATHS = join(STATE, 'paths.json')
const ROOT_VAL = process.platform === 'win32' ? 'D:/enc-test-root' : '/enc-test-root'

function writePaths(buf: Buffer) {
  writeFileSync(PATHS, buf)
}

test('编码守卫 · GBK/ANSI paths.json ⇒ PathsConfigError（不再静默乱码）', () => {
  writePaths(Buffer.concat([
    Buffer.from('{"root":"', 'utf8'),
    Buffer.from([0xb8, 0xf6]),                 // GBK「记」两字节：非法 UTF-8
    Buffer.from('"}', 'utf8'),
  ]))
  assert.equal(dp.pathsFile(), PATHS)
  assert.throws(() => mdcgRoot(), (e: unknown) => {
    assert.ok(e instanceof PathsConfigError, String(e))
    assert.match((e as Error).message, /不是 UTF-8 编码/)
    return true
  })
})

test('编码守卫 · UTF-8 paths.json 正常读取（对照）', () => {
  writePaths(Buffer.from(JSON.stringify({ root: ROOT_VAL }), 'utf8'))
  assert.equal(mdcgRoot(), ROOT_VAL)
})

test('编码守卫 · UTF-8 BOM paths.json 正常读取（对照）', () => {
  writePaths(Buffer.concat([
    Buffer.from([0xef, 0xbb, 0xbf]),
    Buffer.from(JSON.stringify({ root: ROOT_VAL }), 'utf8'),
  ]))
  assert.equal(mdcgRoot(), ROOT_VAL)
})

test('编码守卫 · 非法 JSON（合法 UTF-8）仍响亮失败（既有语义）', () => {
  writePaths(Buffer.from('{not json', 'utf8'))
  assert.throws(() => mdcgRoot(), (e: unknown) => {
    assert.ok(e instanceof PathsConfigError, String(e))
    return true
  })
})

test('编码守卫 · 清理临时状态根', () => {
  rmSync(STATE, { recursive: true, force: true })
})
