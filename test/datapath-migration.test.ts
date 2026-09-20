/**
 * datapath-migration.test.ts · 数据面迁出插件包**端到端**回归（issue #18 相邻问题）
 *
 * 为什么必须在沙箱里跑：迁移函数的三条触发条件之一是「旧位置 = 插件包内 data/」，
 * 而插件包位置由 `repoRoot()`（本文件所在模块向上找 package.json）决定——在仓内
 * 无法把「旧位置」换成临时目录。故本用例把**构建产物** `lib/` + `package.json`
 * 复制成 `<tmp>/pkg`（模拟 `node_modules/<pkg>` 布局），在子进程里以
 * `MDCG_STATE_ROOT=<tmp>/state` 运行真实的 `lib/lib/datapath.js`。
 *
 * 断言的不变量（任一被破坏即红）：
 *   ① 默认数据根落在**包外**（`<state>/data`），`pathsFile()` 兼容读包内旧件
 *   ② 迁移把旧包内数据（含子目录）**复制**到用户级根：新增件在、旧件仍在（不删除）
 *   ③ `paths.json` 属配置，**不随数据面搬运**
 *   ④ 目标已有内容 → 不覆盖（旧件后改的内容不得回流覆盖新库）
 *   ⑤ 幂等：第二次调用不再搬（ran=false）
 *   ⑥ 数据根为显式配置（`MDCG_DATA_ROOT`）→ **不动作**（不越权搬运用户真源）
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, relative, isAbsolute, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/** 与子进程里 `migrateLegacyData()` 的返回结构对应（只取断言用字段）。 */
type Migration = { ran: boolean; reason: string; from: string; to: string; copied: number; failed: string[] }
type Probe = {
  first: Migration
  second: Migration
  stateRoot: string
  defaultDataRoot: string
  legacyDataRoot: string
  pathsFile: string
  pathsFileSource: string
}

/** 在沙箱包目录里跑一次真实构建产物；返回它自报的解析结果与两次迁移结果。 */
function probeSandbox(opts: { pkg: string; state: string; dataRoot?: string }): Probe {
  // ESM 动态 import 只收 file:// URL（Windows 盘符路径会被 ERR_UNSUPPORTED_ESM_URL_SCHEME 拒掉）
  const entry = pathToFileURL(join(opts.pkg, 'lib', 'lib', 'datapath.js')).href
  const script = `
    const m = await import(${JSON.stringify(entry)})
    const first = m.migrateLegacyData()
    const second = m.migrateLegacyData()
    console.log(JSON.stringify({
      first, second,
      stateRoot: m.stateRoot(),
      defaultDataRoot: m.defaultDataRoot(),
      legacyDataRoot: m.legacyDataRoot(),
      pathsFile: m.pathsFile(),
      pathsFileSource: m.pathsFileSource(),
    }))
  `
  const env: Record<string, string> = { MDCG_STATE_ROOT: opts.state }
  for (const k of ['PATH', 'Path', 'SystemRoot', 'TEMP', 'TMP', 'USERPROFILE', 'HOME', 'APPDATA']) {
    const v = process.env[k]
    if (v) env[k] = v
  }
  if (opts.dataRoot) env['MDCG_DATA_ROOT'] = opts.dataRoot
  const r = spawnSync(process.execPath, ['--input-type=module', '-e', script],
    { cwd: opts.pkg, env, encoding: 'utf8' })
  assert.equal(r.status, 0, `沙箱子进程失败：${r.stderr || r.stdout}`)
  return JSON.parse(r.stdout.trim().split('\n').pop() as string) as Probe
}

/** 复制构建产物与 package.json 成 `<tmp>/pkg`（node_modules/<pkg> 形态）。 */
function makeSandboxPackage(base: string): string {
  const pkg = join(base, 'pkg')
  mkdirSync(pkg, { recursive: true })
  cpSync(join(REPO, 'package.json'), join(pkg, 'package.json'))
  assert.ok(existsSync(join(REPO, 'lib', 'lib', 'datapath.js')),
    '需要构建产物 lib/lib/datapath.js（npm test 会先 npm run build）')
  cpSync(join(REPO, 'lib'), join(pkg, 'lib'), { recursive: true })
  return pkg
}

const read = (p: string) => readFileSync(p, 'utf8')

test('issue #18 相邻：默认数据根在包外 + 旧包内数据一次性复制到用户级根', () => {
  const base = mkdtempSync(join(tmpdir(), 'dsh-datapath-'))
  try {
    const pkg = makeSandboxPackage(base)
    const state = join(base, 'state')
    // 旧版落点：包内 data/（含记忆库子目录、账本、配置）
    mkdirSync(join(pkg, 'data', 'mdcg'), { recursive: true })
    writeFileSync(join(pkg, 'data', 'mdcg', 'mem.md'), 'MEM-1')
    writeFileSync(join(pkg, 'data', 'ledger.jsonl'), '{"op":"write"}\n')
    writeFileSync(join(pkg, 'data', 'paths.json'), '{}')

    const p = probeSandbox({ pkg, state })

    // ① 落点在包外；旧件被兼容读
    assert.equal(p.defaultDataRoot, join(state, 'data'))
    const rel = relative(pkg, p.defaultDataRoot)
    assert.ok(rel.startsWith('..') || isAbsolute(rel),
      `默认数据根必须在插件包之外（包=${pkg}，根=${p.defaultDataRoot}）`)
    assert.equal(p.pathsFile, join(pkg, 'data', 'paths.json'))
    assert.equal(p.pathsFileSource, 'legacy')

    // ② 数据被复制（含子目录），旧件仍在
    assert.equal(p.first.ran, true, JSON.stringify(p.first))
    assert.ok(p.first.copied >= 2, `应至少搬 mdcg/ 与 ledger.jsonl：${JSON.stringify(p.first)}`)
    assert.equal(read(join(state, 'data', 'mdcg', 'mem.md')), 'MEM-1')
    assert.ok(existsSync(join(state, 'data', 'ledger.jsonl')))
    assert.equal(read(join(pkg, 'data', 'mdcg', 'mem.md')), 'MEM-1', '只复制不删除')

    // ③ 配置不随数据面搬运
    assert.equal(existsSync(join(state, 'data', 'paths.json')), false)

    // ④ 不覆盖：旧件后改的内容不得回流覆盖新库
    writeFileSync(join(pkg, 'data', 'mdcg', 'mem.md'), 'MEM-2')
    probeSandbox({ pkg, state })
    assert.equal(read(join(state, 'data', 'mdcg', 'mem.md')), 'MEM-1')

    // ⑤ 幂等：第二次不再搬
    assert.equal(p.second.ran, false, JSON.stringify(p.second))

    // ⑥ 显式配置的数据根 → 不动作
    const explicit = join(base, 'explicit')
    const q = probeSandbox({ pkg, state, dataRoot: explicit })
    assert.equal(q.first.ran, false, JSON.stringify(q.first))
    assert.match(q.first.reason, /显式配置/)
    assert.equal(existsSync(join(explicit, 'mdcg')), false)
  } finally {
    rmSync(base, { recursive: true, force: true })
  }
})
