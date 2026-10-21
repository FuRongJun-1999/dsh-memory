/**
 * init 片段落盘的「不覆盖」守卫（PR #575 回归）。
 *
 * 背景：`runInit` 原无条件 `writeFileSync(snippetPath, snippetJson)`。
 * 用户可能已在本目录手写过同名 `lingshu-mcp-snippet.json`（甚至已把真实
 * MDCG_TOKEN 填进去）；init 的文案只承诺「重跑输出一致」，没承诺「覆盖用户文件」。
 * 无条件写会把用户的令牌连同文件一起冲掉，且没有任何提示。
 *
 * 断言面：
 *   ① 已存在且内容**不同** → 不覆盖原文件，改写旁路文件，且返回的
 *      snippetPath 指向旁路文件（调用方能知道真实落点）
 *   ② 旁路文件名符合 `lingshu-mcp-snippet-new-<ts>.json` 形态
 *   ③ 原文件字节**逐字节未变**（用户令牌不丢）
 *   ④ 旁路文件内容 = 本次要写的片段（可用、可解析）
 *   ⑤ 已存在且内容**相同** → 覆盖原文件（保持幂等，不产生旁路垃圾）
 *   ⑥ 不存在 → 正常写入原文件名（首次使用路径不变）
 *   ⑦ 幂等承诺仍成立：同参数重跑两次，第二次不产生旁路文件
 *
 * 零副作用：全部落临时目录并清理；不 spawn python、不触碰真实记忆库。
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'node:stream'
import { runInit } from '../src/init.js'

const SNIPPET = 'lingshu-mcp-snippet.json'

function tmpCase(): { dir: string; cleanup: () => void } {
  const dir = mkdtempSync(join(tmpdir(), 'init-noclobber-'))
  return { dir, cleanup: () => rmSync(dir, { recursive: true, force: true }) }
}

/** 本目录下所有 snippet 文件（含旁路），按名字排序。 */
function snippetFiles(dir: string): string[] {
  return readdirSync(dir).filter((n) => n.endsWith('.json')).sort()
}

const argv = (dir: string): string[] => [
  '--end', 'claude', '--root', join(dir, 'mem'), '--python', 'python',
]

test('① 已存在且内容不同：不覆盖，改写旁路文件', async () => {
  const { dir, cleanup } = tmpCase()
  try {
    const path = join(dir, SNIPPET)
    // 模拟用户已手写过、且填了真实令牌的文件
    const userContent = JSON.stringify(
      { mcpServers: { mdcg: { env: { MDCG_TOKEN: 'REAL-USER-TOKEN-DO-NOT-LOSE' } } } },
      null, 2,
    )
    writeFileSync(path, userContent, 'utf8')

    const r = await runInit(argv(dir), { cwd: dir, output: new PassThrough() })

    // ① 不覆盖原文件
    assert.equal(readFileSync(path, 'utf8'), userContent,
      '① 原文件必须逐字节未变（用户令牌不能丢）')
    // 返回路径指向旁路
    assert.notEqual(r.snippetPath, path, '① snippetPath 应指向旁路文件而非原文件')
    assert.ok(existsSync(r.snippetPath), '① 旁路文件应已落盘')

    // ② 命名形态
    const base = r.snippetPath.slice(r.snippetPath.lastIndexOf('\\') + 1).split('/').pop() ?? ''
    // 判据重述（2026-10-21）：3225e5c5 起旁路名固定为 -new.json（幂等、不随时间堆积，
    // 见 src/init.ts 的 issue #1193 注释），故断言固定名而非时间戳名。
    assert.match(base, /^lingshu-mcp-snippet-new\.json$/,
      `② 旁路文件名应为 lingshu-mcp-snippet-new-<ts>.json，实际 ${base}`)

    // ③ 旁路内容 = 本次片段
    const parsed: unknown = JSON.parse(readFileSync(r.snippetPath, 'utf8'))
    assert.deepEqual(parsed, r.snippet, '③ 旁路文件内容应与返回片段一致')

    // 目录里应有两个 json：原文件 + 旁路
    assert.equal(snippetFiles(dir).length, 2,
      `① 应同时保留原文件与旁路文件（实际 ${snippetFiles(dir)}）`)
  } finally {
    cleanup()
  }
})

test('⑤ 已存在且内容相同：覆盖原文件，不产生旁路垃圾', async () => {
  const { dir, cleanup } = tmpCase()
  try {
    // 先跑一次，得到「正确内容」并落盘
    const r1 = await runInit(argv(dir), { cwd: dir, output: new PassThrough() })
    const path = join(dir, SNIPPET)
    assert.equal(r1.snippetPath, path, '⑤ 首次应写原文件名')

    // 再跑一次：内容相同，应原地覆盖、不新增文件
    const r2 = await runInit(argv(dir), { cwd: dir, output: new PassThrough() })
    assert.equal(r2.snippetPath, path, '⑤ 内容相同时 snippetPath 仍是原文件')
    assert.equal(snippetFiles(dir).length, 1,
      `⑤ 不应产生旁路文件（实际 ${snippetFiles(dir)}）`)
  } finally {
    cleanup()
  }
})

test('⑥ 不存在：正常写入原文件名', async () => {
  const { dir, cleanup } = tmpCase()
  try {
    const path = join(dir, SNIPPET)
    assert.equal(existsSync(path), false, '前置：文件尚不存在')
    const r = await runInit(argv(dir), { cwd: dir, output: new PassThrough() })
    assert.equal(r.snippetPath, path, '⑥ 首次使用路径不变')
    assert.ok(existsSync(path), '⑥ 文件已写入原文件名')
    assert.equal(snippetFiles(dir).length, 1, '⑥ 只应有一个文件')
  } finally {
    cleanup()
  }
})

test('⑦ 幂等承诺仍成立：重跑两次不产生旁路文件', async () => {
  const { dir, cleanup } = tmpCase()
  try {
    const a = await runInit(argv(dir), { cwd: dir, output: new PassThrough() })
    const f1 = readFileSync(a.snippetPath, 'utf8')
    const b = await runInit(argv(dir), { cwd: dir, output: new PassThrough() })
    const f2 = readFileSync(b.snippetPath, 'utf8')
    assert.equal(a.output, b.output, '⑦ 重跑打印应逐字节一致')
    assert.equal(f1, f2, '⑦ 重跑片段文件应逐字节一致')
    assert.equal(snippetFiles(dir).length, 1, '⑦ 不应累积旁路文件')
  } finally {
    cleanup()
  }
})

test('④ 旁路文件打印里如实给出真实落点（用户知道去哪儿找）', async () => {
  const { dir, cleanup } = tmpCase()
  try {
    const path = join(dir, SNIPPET)
    writeFileSync(path, '{"user":"handwritten"}', 'utf8')
    const r = await runInit(argv(dir), { cwd: dir, output: new PassThrough() })
    assert.ok(r.output.includes(r.snippetPath),
      '④ 打印文本应含真实写入路径（否则用户找不到旁路文件）')
    assert.ok(!r.output.includes(`片段已写入：${path}`) || r.snippetPath === path,
      '④ 不应谎称写入了原文件')
  } finally {
    cleanup()
  }
})
