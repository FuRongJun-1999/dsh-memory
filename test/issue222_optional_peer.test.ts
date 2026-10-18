/**
 * issue222_optional_peer.test.ts · 干净安装后本包必须可 import（optional peer 不得静态导入）
 *
 * 功能名：包入口的**运行时依赖闭包**判据——`@deepseek-ai/schemastery` 声明为
 *         `dependencies`，其余 `@deepseek-ai/*` 保持 optional peer 且**不得**被
 *         静态（值）导入（只允许 `import type` 或动态 `await import`）。
 * 生效条件：`node --import tsx --test test/issue222_optional_peer.test.ts`
 *           （变异自证：`node --import tsx test/issue222_optional_peer.test.ts --mutate M1|M2|M3`）
 * 子功能：
 *   A 结构：package.json 的 schemastery 在 dependencies、不在 peerDependencies /
 *     peerDependenciesMeta；其余 optional peer 声明不变；
 *   B 运行时导入闭包：src/ 与 lib/ 里**静态值导入**的裸包名 ⊆ dependencies
 *     （`import type` / 动态 `import()` 不算）；lib 产物只允许 node: 内建与依赖闭包；
 *   C 干净安装模拟：按 package.json 的 dependencies 闭包复制依赖 + 本包 lib/，
 *     `import()` 必须成功（对应 install-verify 的 ESM import check）；
 *   D 机制反证：把 schemastery 从闭包里去掉时 C 必失败（证明 C 有判别力）。
 * 执行：B/C 全部在临时目录里跑，不触网络、不改仓库。
 * 验证方式：默认模式全部 PASS（退出码 0）；`--mutate` 下指定红项须逐项出现。
 * 不适用条件：不判真实 registry 安装（网络/发布面，install-verify 工作流负责；
 *   本守卫用 dependencies 闭包模拟同一判据）；不判 DSH 宿主内的工具注册（那需要
 *   真实 dsh-tools，属宿主面）；不判 peer 版本范围协商（npm 解析层）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve, sep } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const PKG = join(REPO, 'package.json')
const SRC = join(REPO, 'src')
const LIB = join(REPO, 'lib')

interface Pkg {
  dependencies?: Record<string, string>
  peerDependencies?: Record<string, string>
  peerDependenciesMeta?: Record<string, { optional?: boolean }>
}

/** 递归收集目录下的文件（按扩展名过滤）。 */
function walk(dir: string, ext: string): string[] {
  const out: string[] = []
  if (!existsSync(dir)) return out
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walk(p, ext))
    else if (name.endsWith(ext)) out.push(p)
  }
  return out
}

/** 一条 import/export 语句的解析结果。 */
interface Spec {
  pkg: string
  kind: 'value' | 'type' | 'dynamic'
}

const NODE_BUILTIN = /^(node:|[a-z]+$)/

/** 从 TS/JS 源码提取裸包导入（相对路径与 node: 内建不计）。 */
function collectSpecs(text: string): Spec[] {
  const out: Spec[] = []
  const push = (raw: string, kind: Spec['kind']): void => {
    if (!raw || raw.startsWith('.') || raw.startsWith('/') || raw.startsWith('file:')) return
    if (raw.startsWith('node:')) return
    out.push({ pkg: raw, kind })
  }
  // import type ... from 'pkg'  /  import type {} from 'pkg'
  for (const m of text.matchAll(/^\s*import\s+type\s[^'"]*?from\s*['"]([^'"]+)['"]/gm)) {
    push(m[1] as string, 'type')
  }
  // import 'pkg'（副作用）
  for (const m of text.matchAll(/^\s*import\s*['"]([^'"]+)['"]/gm)) {
    push(m[1] as string, 'value')
  }
  // import x / import { } / import * as ns from 'pkg'（非 type、非副作用）
  // `(?!['"])` 排除副作用导入行；`(?!\bimport\b)` 防跨到下一条 import 才找到 from
  // （否则 `import 'pkg'` 后跟 `import type {...} from 'pkg2'` 会把 pkg2 误判为值导入）。
  for (const m of text.matchAll(/^\s*import\s+(?!type\s)(?!['"])(?:(?!\bimport\b)[\s\S])*?\bfrom\s*['"]([^'"]+)['"]/gm)) {
    push(m[1] as string, 'value')
  }
  // export type ... from 'pkg'（编译期擦除，不产生运行时解析）
  for (const m of text.matchAll(/^\s*export\s+type\s[^'"]*?from\s*['"]([^'"]+)['"]/gm)) {
    push(m[1] as string, 'type')
  }
  // export ... from 'pkg'（值再导出；同样不得跨到下一条 export）
  for (const m of text.matchAll(/^\s*export\s+(?!type\s)(?:(?!\bexport\b)[\s\S])*?\bfrom\s*['"]([^'"]+)['"]/gm)) {
    push(m[1] as string, 'value')
  }
  // 动态 import('pkg')
  for (const m of text.matchAll(/\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g)) {
    push(m[1] as string, 'dynamic')
  }
  return out
}

const pkgName = (spec: string): string =>
  spec.startsWith('@') ? spec.split('/').slice(0, 2).join('/') : spec.split('/')[0] as string

/** 判据主体：返回红项名（空数组 = 全过）。 */
function evaluate(over: { pkgText?: string; srcText?: Record<string, string>; libText?: Record<string, string> } = {}): string[] {
  const reds: string[] = []
  const push = (name: string, cond: boolean): void => { if (!cond) reds.push(name) }

  const pkg = JSON.parse(over.pkgText ?? readFileSync(PKG, 'utf8')) as Pkg
  const deps = pkg.dependencies ?? {}
  const peers = pkg.peerDependencies ?? {}
  const peerMeta = pkg.peerDependenciesMeta ?? {}

  // A 结构
  push('schemastery_is_dependency', Boolean(deps['@deepseek-ai/schemastery']))
  push('schemastery_not_peer', !('@deepseek-ai/schemastery' in peers))
  push('schemastery_not_optional_peer', !('@deepseek-ai/schemastery' in peerMeta))
  push('other_peers_stay_optional',
    ['@deepseek-ai/cordis', '@deepseek-ai/dsh-tools', '@deepseek-ai/dsh-session',
      '@deepseek-ai/dsh-system-prompt', '@deepseek-ai/dsh-llm']
      .every((p) => peerMeta[p]?.optional === true))

  // B 运行时导入闭包
  const depNames = new Set(Object.keys(deps).map(pkgName))
  const scan = (files: string[], label: string, textOverride?: Record<string, string>): void => {
    for (const file of files) {
      const rel = file.slice(REPO.length + 1).split(sep).join('/')
      const text = textOverride?.[rel] ?? readFileSync(file, 'utf8')
      for (const spec of collectSpecs(text)) {
        const name = pkgName(spec.pkg)
        if (spec.kind === 'value') push(`${label}:static:${name}`, depNames.has(name))
      }
    }
  }
  scan(walk(SRC, '.ts'), 'src', over.srcText)
  // 产物面必须真的被扫到（防空转假绿）：lib/ 被 .gitignore 忽略，未构建时
  // 这里会是 0 文件——显式判红，而不是静默少扫一半判据。
  const libFiles = walk(LIB, '.js')
  push('lib_not_built', existsSync(join(LIB, 'index.js')) && libFiles.length > 0)
  scan(libFiles, 'lib', over.libText)

  // C 干净安装模拟：只装 dependencies 闭包（npm 对 optional peer 不自动安装）
  const consumer = mkdtempSync(join(tmpdir(), 'iss222_consumer_'))
  const pkgDir = join(consumer, 'node_modules', '@furongjun1999', 'dsh-memory')
  mkdirSync(pkgDir, { recursive: true })
  writeFileSync(join(pkgDir, 'package.json'), over.pkgText ?? readFileSync(PKG, 'utf8'), 'utf8')
  cpSync(LIB, join(pkgDir, 'lib'), { recursive: true })
  for (const dep of Object.keys(deps)) {
    const from = join(REPO, 'node_modules', dep)
    if (!existsSync(from)) { reds.push(`dep_missing_locally:${dep}`); continue }
    cpSync(from, join(consumer, 'node_modules', dep), { recursive: true })
    // 传递依赖（本仓 node_modules 已是扁平布局：按包自身 dependencies 复制一层）
    const sub = JSON.parse(readFileSync(join(from, 'package.json'), 'utf8')) as Pkg
    for (const td of Object.keys(sub.dependencies ?? {})) {
      const tfrom = join(REPO, 'node_modules', td)
      const tto = join(consumer, 'node_modules', td)
      if (existsSync(tfrom) && !existsSync(tto)) cpSync(tfrom, tto, { recursive: true })
    }
  }
  const code = "import('@furongjun1999/dsh-memory')"
    + ".then(m=>console.log('ESM OK'))"
    + ".catch(e=>{console.error('ESM FAIL',e.code);process.exit(1)})"
  const env: Record<string, string> = {}
  for (const [k, v] of Object.entries(process.env)) {
    if (v !== undefined && !k.startsWith('MDCG_')) env[k] = v
  }
  const r = spawnSync(process.execPath, ['--input-type=module', '-e', code], {
    cwd: consumer, env, encoding: 'utf8', timeout: 60_000,
  })
  push('clean_install_import', r.status === 0)

  // D 机制反证：把 dependencies 清空后同一模拟必失败（否则 C 无判别力）
  if (Object.keys(deps).length > 0) {
    const emptyPkg = JSON.parse(JSON.stringify(pkg)) as Pkg
    emptyPkg.dependencies = {}
    const c2 = mkdtempSync(join(tmpdir(), 'iss222_consumer_neg_'))
    const d2 = join(c2, 'node_modules', '@furongjun1999', 'dsh-memory')
    mkdirSync(d2, { recursive: true })
    writeFileSync(join(d2, 'package.json'), JSON.stringify(emptyPkg), 'utf8')
    cpSync(LIB, join(d2, 'lib'), { recursive: true })
    const r2 = spawnSync(process.execPath, ['--input-type=module', '-e', code], {
      cwd: c2, env, encoding: 'utf8', timeout: 60_000,
    })
    push('discrimination_negative_control', r2.status !== 0)
  }

  return [...new Set(reds)]
}

test('#222 干净安装可 import（optional peer 不静态导入）', () => {
  const reds = evaluate()
  assert.deepEqual(reds, [], `红项：${reds.join(', ')}`)
})

test('#222 解析器判据：export type 不算静态值导入，export 值再导出算', () => {
  const typeOnly = collectSpecs(
    "export type { X } from '@deepseek-ai/dsh-tools'\n"
    + "export type * from '@deepseek-ai/dsh-session'\n")
  assert.deepEqual(typeOnly.map((s) => s.kind), ['type', 'type'])
  const value = collectSpecs("export { Y } from '@deepseek-ai/dsh-tools'\n")
  assert.deepEqual(value.map((s) => s.kind), ['value'])
})

/* ————— 定点变异自证 ————— */

function patch(src: string, from: string, to: string): string {
  const text = src.replace(/\r\n/g, '\n')
  if (!text.includes(from)) throw new Error(`变异锚点未命中：${from.slice(0, 70)}`)
  return text.split(from).join(to)
}

interface Mutation {
  desc: string
  pkg?: Array<[string, string]>
  src?: Array<[string, string, string]>   // [rel, from, to]
  reds: string[]
}

const MUTATIONS: Record<string, Mutation> = {
  M1: {
    desc: 'schemastery 退回 optional peer（回到 #222 原缺陷）',
    pkg: [
      ['"dependencies": {\n    "@deepseek-ai/schemastery": "^3.18.1"\n  },\n', ''],
      ['    "@deepseek-ai/dsh-tools": {\n      "optional": true\n    }\n',
        '    "@deepseek-ai/dsh-tools": {\n      "optional": true\n    },\n'
        + '    "@deepseek-ai/schemastery": {\n      "optional": true\n    }\n'],
      ['    "@deepseek-ai/dsh-tools": ">=0.1.0-rc.6"\n',
        '    "@deepseek-ai/dsh-tools": ">=0.1.0-rc.6",\n'
        + '    "@deepseek-ai/schemastery": ">=3.0.0"\n'],
    ],
    reds: ['schemastery_is_dependency', 'schemastery_not_peer', 'schemastery_not_optional_peer',
      'src:static:@deepseek-ai/schemastery', 'lib:static:@deepseek-ai/schemastery',
      'clean_install_import'],
  },
  M2: {
    desc: 'tools.ts 的 dsh-tools 退回静态值导入',
    src: [['src/tools.ts',
      "import type { ParameterPropertySpec, ParameterSchemaSpec, ValueSchemaSpec } from '@deepseek-ai/dsh-tools'",
      "import { defineTool, type ParameterPropertySpec, ParameterSchemaSpec, ValueSchemaSpec } from '@deepseek-ai/dsh-tools'"]],
    reds: ['src:static:@deepseek-ai/dsh-tools'],
  },
  M3: {
    desc: 'hooks.ts 的两个 optional peer 退回副作用值导入',
    src: [
      ['src/hooks.ts', "import type {} from '@deepseek-ai/dsh-session'", "import '@deepseek-ai/dsh-session'"],
      ['src/hooks.ts', "import type {} from '@deepseek-ai/dsh-system-prompt'", "import '@deepseek-ai/dsh-system-prompt'"],
    ],
    reds: ['src:static:@deepseek-ai/dsh-session', 'src:static:@deepseek-ai/dsh-system-prompt'],
  },
}

if (process.argv.includes('--mutate')) {
  const idx = process.argv.indexOf('--mutate')
  const name = process.argv[idx + 1] || ''
  const mut = MUTATIONS[name]
  if (!mut) {
    console.log(`未知变异组 ${JSON.stringify(name)}（可选 ${Object.keys(MUTATIONS).join('/')}）`)
    process.exit(1)
  }
  let pkgText = readFileSync(PKG, 'utf8')
  for (const [from, to] of mut.pkg ?? []) pkgText = patch(pkgText, from, to)
  const srcText: Record<string, string> = {}
  for (const [rel, from, to] of mut.src ?? []) {
    srcText[rel] = patch(srcText[rel] ?? readFileSync(join(REPO, rel), 'utf8'), from, to)
  }
  const base = evaluate()
  const red = evaluate({ pkgText, srcText })
  console.log(`!! #222 定点变异自证 · 组 ${name}：${mut.desc}\n`)
  console.log(`  未变异基线红项=${JSON.stringify(base)}（须为空）`)
  console.log(`  变异后红项=${JSON.stringify(red)}`)
  const hit = mut.reds.filter((x) => red.includes(x))
  const ok = base.length === 0 && red.length > 0 && hit.length === mut.reds.length
  console.log(`  预期红项 ${JSON.stringify(mut.reds)} → 命中 ${JSON.stringify(hit)}`)
  console.log(ok ? '\n变异自证通过：指定项逐项转红' : '\n变异自证失败：红项集合与预期不符')
  process.exit(ok ? 0 : 1)
}

void pathToFileURL
void NODE_BUILTIN
