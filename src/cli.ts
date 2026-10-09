#!/usr/bin/env node
/**
 * cli.ts —— `lingshu` 主命令入口（npx 兼容分发器）
 *
 * 为什么有三个 bin（package.json bin）：
 *   · `lingshu`       → 本文件：`lingshu init` 分发到 init.ts（未来其它子命令也挂这）；
 *   · `lingshu-init`  → lib/init.js：单命令直入（不想敲子命令的场景）；
 *   · `dsh-memory`    → 本文件：npx 的同名匹配规则——`npx @furongjun1999/dsh-memory init`
 *     在包有多个 bin 时，只会自动运行**与包名末段同名**的 bin（npm 官方口径），
 *     缺这个入口 npx 会因「多个 bin 且无同名」直接报错，一键配置命令即失效。
 *
 * 零运行时依赖：只用 Node 内置模块。
 */
import { resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { realpathSync } from 'node:fs'
import { runInit } from './init.js'

const USAGE = [
  '灵枢（Lingshu）命令行',
  '',
  '用法：lingshu <命令>',
  '',
  '命令：',
  '  init [选项]    一键配置生成器（交互三问；参数齐则跳过问答）',
  '                 选项：--end <dsh|claude|codex|generic> --root <dir> --python <interpreter>',
  '',
  '示例：',
  '  npx @furongjun1999/dsh-memory init',
  '  npx @furongjun1999/dsh-memory init -- --end claude --root D:/mem --python python3',
].join('\n')

/** 入口分发：argv 为去掉 node 与本脚本路径后的参数。仅导出供测试。 */
export async function main(argv: string[]): Promise<number> {
  const cmd = argv[0] ?? ''
  if (cmd === 'init') {
    await runInit(argv.slice(1))
    return 0
  }
  process.stdout.write(`${USAGE}\n`)
  if (cmd === '--help' || cmd === '-h' || cmd === 'help') return 0
  if (cmd !== '') process.stderr.write(`未知命令「${cmd}」。\n`)
  else process.stderr.write('缺少命令。\n')
  return 1
}

function isMainEntry(): boolean {
  const entry = process.argv[1]
  if (!entry) return false
  try {
    // issue #97（2026-10-09 DSH 端）：npm 在 POSIX 把 bin 装成**符号链接**
    // （node_modules/.bin/lingshu -> ../@furongjun1999/dsh-memory/lib/cli.js），
    // 此时 argv[1] 是**链接路径**，而 resolve 是纯词法操作、解不开链接
    // ⇒ 与 import.meta.url **永不相等** ⇒ 主函数不执行，**静默空转且 exit=0**
    // （README 推荐的首条命令在 Linux/macOS 上无效而用户与脚本都看不出失败）。
    // Windows 用 .cmd 传真实路径，故开发者在本机测不出来。
    // 修：比较前对**两侧**都做 realpathSync —— 当前模块自身也可能是链接
    // （npm link / 全局安装同样走软链）。
    const selfUrl = pathToFileURL(realpathSync(fileURLToPath(import.meta.url))).href
    const entryUrl = pathToFileURL(realpathSync(entry)).href
    return selfUrl === entryUrl
      || (process.platform === 'win32' && selfUrl.toLowerCase() === entryUrl.toLowerCase())
  } catch {
    return false
  }
}

if (isMainEntry()) {
  main(process.argv.slice(2))
    .then((code) => { process.exitCode = code })
    .catch((e: unknown) => {
      process.stderr.write(`lingshu：${e instanceof Error ? e.message : String(e)}\n`)
      process.exitCode = 1
    })
}
