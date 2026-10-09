import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '..')
const CLI = join(REPO, 'lib', 'cli.js')

/** 建一条**指向 lib 的链接**（POSIX 用 symlink；Windows 无管理员时用 junction）。 */
function linkLib(dir: string): string {
  const link = join(dir, 'lib')
  mkdirSync(dir, { recursive: true })
  try {
    symlinkSync(join(REPO, 'lib'), link, 'junction')   // Windows：junction 不需管理员
  } catch {
    symlinkSync(join(REPO, 'lib'), link, 'dir')        // POSIX
  }
  return join(link, 'cli.js')
}

function runCli(entry: string, root: string): { lines: number; code: number } {
  let out = ''
  let code = 0
  try {
    out = execFileSync(process.execPath,
      [entry, 'init', '--end', 'dsh', '--root', root, '--python', 'python3'],
      { cwd: REPO, encoding: 'utf8', timeout: 60000 })
  } catch (e) {
    const err = e as { status?: number; stdout?: string; stderr?: string }
    code = err.status ?? 1
    out = (err.stdout ?? '') + (err.stderr ?? '')
  }
  return { lines: out.split(/\r?\n/).filter((x) => x.trim()).length, code }
}

// issue #97：npm 在 POSIX 把 bin 装成**符号链接**，argv[1] 是链接路径；
// 而 resolve 是纯词法操作解不开链接 ⇒ 与 import.meta.url 永不相等 ⇒
// 主函数不执行，**静默空转且 exit=0**（README 推荐的首条命令在 Linux/macOS 上无效）。
// 本守卫用一条指向 lib 的真链接复现该形态（Windows 走 junction，同样不需管理员）。
test('⑨ issue #97：经链接路径调用时主函数仍执行（修前静默空转、exit=0）', () => {
  const d = mkdtempSync(join(tmpdir(), 'i97_'))
  try {
    const root = join(d, 'mem')
    mkdirSync(root, { recursive: true })

    // 对照：真实路径
    const direct = runCli(CLI, root)
    assert.ok(direct.lines > 0, `真实路径调用须有输出，实得 ${direct.lines} 行`)

    // 关键：链接路径（修前 0 行 + rc=0；修后应与 direct 同量级）
    const viaLink = linkLib(join(d, 'bin'))
    const linked = runCli(viaLink, root)
    assert.ok(linked.lines > 0,
      `#97 经链接路径调用必须仍有输出（静默空转=主函数未执行）；实得 ${linked.lines} 行`)
    assert.equal(linked.code, 0, '正常完成时退出码应为 0')
  } finally {
    rmSync(d, { recursive: true, force: true })
  }
})

test('⑨b issue #97：cli.ts 与 init.ts 的 isMainEntry 都做了 realpath 归一', () => {
  for (const f of ['cli.ts', 'init.ts']) {
    const src = readFileSync(join(REPO, 'src', f), 'utf8')
    const i = src.indexOf('function isMainEntry')
    const seg = i >= 0 ? src.slice(i, i + 900) : ''
    assert.ok(seg.includes('realpathSync'),
      `${f} 的 isMainEntry 须用 realpathSync 解链接（否则 argv[1] 与 import.meta.url 永不相等）`)
  }
})
