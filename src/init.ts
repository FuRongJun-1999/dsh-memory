#!/usr/bin/env node
/**
 * init.ts —— 灵枢一键配置生成器（独立 CLI 入口：`lingshu-init`）
 *
 * 用户痛点：部署灵枢要手工做多步——选记忆根目录、手写各端 mcp.json 的
 * env（MDCG_ROOT / MDCG_PYTHON 等）、理解令牌签发。本命令把「生成配置」
 * 这一步自动化：三问（接入端 / 记忆根目录 / Python 解释器）后打印所选端
 * 的 mcp.json 配置片段、把片段落盘成可复制的文件、并给出各端后续步骤
 * （片段放哪 / 令牌签发命令——后者指向 README「写入凭据」节）。
 *
 * 边界（刻意设计，勿越界）：
 *   · init **只生成配置**——不创建记忆目录、不启动 md_cg 服务、不写库；
 *     重跑（同参数）输出逐字节一致（无时间戳等易变内容），可放心重复执行。
 *   · 与插件运行时的数据根缺省（`~/.dsh/.dsh-memory/data/mdcg`，见
 *     `src/lib/datapath.ts`）不同，本命令的缺省记忆根是 `~/.lingshu/memory`
 *     ——它会被**显式写进**片段的 MDCG_ROOT，两侧不靠默契、无歧义。
 *
 * env 片段口径与 `mdcgChildEnv()`（src/lib/mdcg_client.ts）对齐：
 *   PYTHONIOENCODING/PYTHONUTF8 两条编码注入是硬约束（中文记忆场景，
 *   详见该函数头注的 2026-09-20 读线程崩溃现场）；MDCG_MCP_SURFACE=kernel
 *   与各端 mcp.json 样例（claude/lingshu-memory/mcp.json.example 等）同口径。
 *   MDCG_PYTHON 对直挂端是文档性键（解释器由 command 决定），对 DSH 插件端
 *   真实生效（`defaultPython()` 读它，src/lib/python_path.ts:42）。
 *
 * 零运行时依赖：只用 Node 内置模块（node:readline/promises / node:fs /
 * node:path）——与全仓「CLI 不加第三方依赖」纪律一致。
 */

import { writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { createInterface } from 'node:readline/promises'
import type { Readable, Writable } from 'node:stream'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { repoRoot } from './lib/datapath.js'
import { defaultPython } from './lib/python_path.js'

/** 接入端：1=DSH 插件 2=Claude Code 3=Codex CLI 4=通用 MCP。 */
export type InitEnd = 'dsh' | 'claude' | 'codex' | 'generic'

interface EndSpec {
  id: InitEnd
  /** 问答菜单里的展示名。 */
  label: string
  /** MDCG_ACTOR（与既有各端样例/插件配置同口径；私有内容按 (tenant, actor) 派生 DEK）。 */
  actor: string
  /** 片段该放到哪（打印给用户）。 */
  configTarget: string
  /** 令牌签发指引里说明的角色语境（保持 README 口径，仅按端换 actor）。 */
  tokenActor: string
}

const ENDS: ReadonlyArray<EndSpec> = [
  {
    id: 'dsh',
    label: 'DSH 插件',
    actor: 'dsh-memory',
    configTarget: 'DSH 无全局 mcp.json——推荐走插件形态（下方指引②）；下方 JSON 为 MCP 直挂等价形态',
    tokenActor: 'dsh-memory',
  },
  {
    id: 'claude',
    label: 'Claude Code',
    actor: 'claude-code',
    configTarget: '项目根 .mcp.json（把片段的 mcpServers 并入；或 ~/.claude.json 全局）',
    tokenActor: 'claude-code',
  },
  {
    id: 'codex',
    label: 'Codex CLI',
    actor: 'codex',
    configTarget: '~/.codex/config.toml 的 [mcp_servers.mdcg] 段（TOML 形态见 codex/config.toml.example：env 为 [mcp_servers.mdcg.env] 表）',
    tokenActor: 'codex',
  },
  {
    id: 'generic',
    label: '通用 MCP 宿主',
    actor: 'generic',
    configTarget: '宿主的 MCP server 配置处（command/args/env 三元组，按宿主文档挂载 stdio server）',
    tokenActor: 'generic',
  },
]

/** --end 的宽松别名（含菜单数字）。未知值报错并列出允许集。 */
function matchEnd(value: string): EndSpec | null {
  const v = value.trim().toLowerCase()
  for (const e of ENDS) {
    if (v === e.id || v === e.label) return e
  }
  const aliases: Record<string, InitEnd> = {
    '1': 'dsh', dsh: 'dsh',
    '2': 'claude', claude: 'claude', 'claude-code': 'claude', claudecode: 'claude',
    '3': 'codex', codex: 'codex',
    '4': 'generic', generic: 'generic', mcp: 'generic',
  }
  const id = aliases[v]
  return id ? ENDS.find((e) => e.id === id) ?? null : null
}

/** 缺省记忆根：<home>/.lingshu/memory（home 可注入，供测试）。 */
export function defaultMemoryRoot(home: string = homedir()): string {
  return join(home, '.lingshu', 'memory')
}

/**
 * N167：根入口波浪线展开——`~` / `~/x`（含 `~\x`）前缀按 home 展开，缺省
 * os.homedir()。与大脑侧 md_cg/datapath.py 的 expanduser+abspath 同口径：
 * 帮助文案与 :264 自带示例都写着「--root ~/.lingshu/memory」，不展开就会把
 * 记忆根解析成宿主 cwd 下的字面 ~ 目录——落错位且随 cwd 漂移分裂。
 * 边界：`~user` 形态 Node 无便携语义（POSIX pwd 查询不可用），原样保留。
 */
function expandHomeTilde(p: string, home: string = homedir()): string {
  if (p === '~') return home
  if (p.startsWith('~/') || p.startsWith('~\\')) return join(home, p.slice(2))
  return p
}

/** 生成的 mcp.json 片段（键序固定 → 序列化稳定 → 幂等）。 */
export function buildSnippet(end: EndSpec, root: string, python: string): {
  mcpServers: { mdcg: { command: string, args: string[], env: Record<string, string> } }
} {
  return {
    mcpServers: {
      mdcg: {
        command: python,
        args: ['-m', 'md_cg.mcp_server'],
        env: {
          // 随包 md_cg 的绝对路径（本包 files 自带 md_cg/）：python -m 的模块
          // 解析不依赖 cwd，靠 PYTHONPATH（口径同 src/lib/datapath.ts pythonPathValue，
          // 此处为静态配置故取纯包根、不拼进程既有 PYTHONPATH）。
          PYTHONPATH: repoRoot(),
          PYTHONIOENCODING: 'utf-8',
          PYTHONUTF8: '1',
          MDCG_ROOT: root,
          // 直挂端文档性键（解释器由 command 决定）；DSH 插件端真实生效。
          MDCG_PYTHON: python,
          MDCG_MCP_SURFACE: 'kernel',
          MDCG_ACTOR: end.actor,
          MDCG_TENANT: 'default',
          MDCG_CLEARANCE: 'private',
          MDCG_TOKEN: '',
        },
      },
    },
  }
}

/** 令牌签发命令文案（与 README「写入凭据」节逐字同口径，仅按端换 actor）。 */
function tokenCommand(python: string, tokenActor: string, comment: string): string[] {
  return [
    `${comment}令牌签发（需 Python 环境 + 本包 md_cg；签发后把输出填进片段 MDCG_TOKEN，详见 README「写入凭据」节）：`,
    `  ${python} -m md_cg.tokens issue --role designer --actor ${tokenActor} --clearance internal ^`,
    `    --ops-allow info,route,read,write,recent,goal,identity,whitebox,verify ^`,
    `    --layers-allow knowledge,contextual,structural,self,goals,unresolved,rejected`,
    `  （bash 把行尾 ^ 换成 \\；--role recorder 为最小权限版）`,
  ]
}

/** 各端后续步骤（片段放哪 / 纪律注入 / 自检）。 */
function nextSteps(end: EndSpec, python: string): string[] {
  const selfCheck = `大脑自检：${python} -m md_cg.mcp_server 收到 initialize 应答即通（README「装后验证」）`
  switch (end.id) {
    case 'dsh':
      return [
        '② 推荐插件形态（README「快速开始」三步）：git clone 本仓 → `dsh plugin --profile <name> add .` →',
        '   cordis.yml 启用 lingshu-memory；对应关系：config.python = 上面选的解释器，',
        '   config.mdcg.root = 上面选的记忆根（覆盖优先级 env MDCG_ROOT > paths.json > 本项，见 src/lib/datapath.ts）。',
        `③ 纪律注入：~/.dsh/profiles/<name>/cordis.patch.yml 的 personaPrefix（样例 dsh/cordis.patch.yml）。`,
        `④ ${selfCheck}`,
      ]
    case 'claude':
      return [
        `② 纪律注入：项目根 CLAUDE.md（样例 claude/CLAUDE.md；插件形态可 /plugin marketplace add FuRongJun-1999/dsh-memory）。`,
        `③ ${selfCheck}`,
      ]
    case 'codex':
      return [
        `② 纪律注入：项目根 AGENTS.md（样例 codex/AGENTS.md）。`,
        `③ ${selfCheck}`,
      ]
    default:
      return [
        `② 纪律注入：按需把 docs/工作纪律 渲染产物放进系统提示（各端样例见 codebuddy/ zcode/ claude/ codex/）。`,
        `③ ${selfCheck}`,
      ]
  }
}

/** runInit 可注入的 IO（测试注入；缺省 = 真实 stdin/stdout/cwd/home/平台）。 */
export interface InitOptions {
  /** 交互模式的 stdin（注入 PassThrough 即可 mock）。 */
  input?: Readable
  /** 输出收集处（缺省 process.stdout）。 */
  output?: Writable
  /** 片段文件落盘目录（缺省 process.cwd()）。 */
  cwd?: string
  /** 缺省记忆根的 home（缺省 os.homedir()）。 */
  home?: string
  /** 平台缺省解释器判定（缺省 process.platform）。 */
  platform?: NodeJS.Platform
  /** 覆盖 TTY 判定（缺省 process.stdin.isTTY）：决定「无参数时」走交互还是
   *  报错。测试注入 false 即可确定性触发非交互分支，不依赖测试宿主的 stdin
   *  形态（管道/终端两态都会让测试结果漂移——显式注入消除这个自由度）。 */
  tty?: boolean
}

export interface InitResult {
  end: InitEnd
  endLabel: string
  root: string
  python: string
  snippetPath: string
  snippet: ReturnType<typeof buildSnippet>
  /** 本次打印到 output 的完整文本（幂等断言用）。 */
  output: string
  /** 片段文件字节（= JSON.stringify(snippet, null, 2) + 换行）。 */
  snippetFile: string
}

const SNIPPET_FILENAME = 'lingshu-mcp-snippet.json'

class InitError extends Error {}

/** 从 argv 解析 --flag value / --flag=value（未知 flag 报错，防拼写静默走默认）。 */
function parseFlags(argv: string[]): { end?: string, root?: string, python?: string } {
  const out: { end?: string, root?: string, python?: string } = {}
  // npx 传参惯例：`npx <pkg> init -- --end x` 的 `--` 是「npx 自己的 flag 到此为止」，
  // 不是本命令的参数——跳过一个前导 `--`（其后仍是本命令的 flag）。
  const rest = argv[0] === '--' ? argv.slice(1) : argv
  const known = new Set(['--end', '--root', '--python'])
  for (let i = 0; i < rest.length; i += 1) {
    const arg = rest[i] ?? ''
    const eq = arg.indexOf('=')
    const name = arg.startsWith('--') && eq > 0 ? arg.slice(0, eq) : arg
    if (!known.has(name)) {
      throw new InitError(`未知参数「${arg}」。支持：--end <dsh|claude|codex|generic> --root <dir> --python <interpreter>`)
    }
    const value = eq > 0 ? arg.slice(eq + 1) : rest[i + 1]
    if (value === undefined || value === '' || (eq < 0 && String(value).startsWith('--'))) {
      throw new InitError(`参数 ${name} 缺值。示例：${name} <值>`)
    }
    if (eq < 0) i += 1
    out[name.slice(2) as 'end' | 'root' | 'python'] = String(value)
  }
  return out
}

/**
 * 一键配置主流程：非交互（参数齐）跳过问答；无参数走交互三问。
 * 只生成配置（打印 + 片段落盘），不创建目录、不启动服务、不写库。
 */
export async function runInit(argv: string[], opts: InitOptions = {}): Promise<InitResult> {
  const out = opts.output ?? process.stdout
  const cwd = opts.cwd ?? process.cwd()
  let collected = ''
  const say = (line = ''): void => {
    collected += `${line}\n`
    out.write(`${line}\n`)
  }

  const flags = parseFlags(argv)
  let end: EndSpec | undefined = flags.end ? matchEnd(flags.end) ?? undefined : undefined
  if (flags.end && !end) {
    throw new InitError(`--end「${flags.end}」无法识别。允许：dsh | claude | codex | generic（或菜单号 1-4）`)
  }
  let root: string | undefined = flags.root
  let python: string | undefined = flags.python

  if (!end || !root || !python) {
    // 交互模式。stdin 非 TTY（且未注入 input）时直接报错——宁缺毋滥，
    // 不挂死等一行永远不会来的输入。
    const interactive = opts.input !== undefined || (opts.tty ?? process.stdin.isTTY === true)
    if (!interactive) {
      const missing = [!end && '--end', !root && '--root', !python && '--python'].filter(Boolean)
      throw new InitError(
        `非交互环境（stdin 非 TTY）必须给齐参数：${missing.join(' ')}。`
        + '示例：lingshu-init --end claude --root ~/.lingshu/memory --python python3',
      )
    }
    const rl = createInterface({ input: opts.input ?? process.stdin })
    try {
      const ask = async (prompt: string): Promise<string> => (await rl.question(prompt)).trim()
      say('灵枢（Lingshu）一键配置——只生成配置：不创建记忆目录、不启动服务、不写库。')
      if (!end) {
        const picked = await ask('① 接入端 [1=DSH 插件 2=Claude Code 3=Codex CLI 4=通用 MCP]（默认 1）：')
        const fallback = picked === '' ? '1' : picked
        end = matchEnd(fallback) ?? undefined
        if (!end) throw new InitError(`接入端「${fallback}」无法识别（允许 1-4）。`)
      }
      if (!root) {
        const given = await ask(`② 记忆根目录 MDCG_ROOT（留空 = ${defaultMemoryRoot(opts.home)}）：`)
        root = given === '' ? defaultMemoryRoot(opts.home) : given
      }
      if (!python) {
        const given = await ask(`③ Python 解释器（留空 = 按平台 ${defaultPython(opts.platform)}）：`)
        python = given === '' ? defaultPython(opts.platform) : given
      }
    } finally {
      rl.close()
    }
  }

  const endSpec = end as EndSpec
  // N167：flag（--root）与交互手输两条入口在此汇合，展开一次即双路覆盖
  const rootAbs = resolve(cwd, expandHomeTilde(root as string, opts.home))
  const pythonName = (python as string).trim()
  if (pythonName === '') throw new InitError('--python 不能为空串')

  const snippet = buildSnippet(endSpec, rootAbs, pythonName)
  const snippetJson = `${JSON.stringify(snippet, null, 2)}\n`
  const snippetPath = join(cwd, SNIPPET_FILENAME)
  writeFileSync(snippetPath, snippetJson, 'utf8')

  say()
  say(`灵枢（Lingshu）一键配置 · 端=${endSpec.label}`)
  say(`  记忆根目录 MDCG_ROOT：${rootAbs}`)
  say(`  Python 解释器：${pythonName}`)
  say()
  say(`① 把下面的 mcp.json 片段放到：${endSpec.configTarget}`)
  say(snippetJson.trimEnd())
  say()
  for (const line of nextSteps(endSpec, pythonName)) say(line)
  for (const line of tokenCommand(pythonName, endSpec.tokenActor, '')) say(line)
  say()
  say(`片段已写入：${snippetPath}（mcpServers 键直接复制即可）`)
  say('提示：PYTHONPATH 当前指向本命令所在包——若是 npx 临时包，建议换成 git clone 的常驻仓库绝对路径（免疫 npx 缓存清理）。')
  say('init 只生成配置：未创建目录、未启动服务、未写库；重跑输出一致。')

  return {
    end: endSpec.id,
    endLabel: endSpec.label,
    root: rootAbs,
    python: pythonName,
    snippetPath,
    snippet,
    output: collected,
    snippetFile: snippetJson,
  }
}

/** 直跑判定（node lib/init.js / npx 场景；import 作库时为 false）。 */
function isMainEntry(): boolean {
  const entry = process.argv[1]
  if (!entry) return false
  try {
    const entryUrl = pathToFileURL(resolve(entry)).href
    return import.meta.url === entryUrl
      || (process.platform === 'win32' && import.meta.url.toLowerCase() === entryUrl.toLowerCase())
  } catch {
    return false
  }
}

if (isMainEntry()) {
  runInit(process.argv.slice(2))
    .then(() => { process.exitCode = 0 })
    .catch((e: unknown) => {
      process.stderr.write(`lingshu-init：${e instanceof Error ? e.message : String(e)}\n`)
      process.exitCode = 1
    })
}
