/**
 * datapath.ts · 灵枢数据根解析（记忆写入路径可配置）
 *
 * 与 Python 侧 `md_cg/datapath.py` **同口径**——两侧读同一份
 * `<用户级状态根>/paths.json`（新位置；旧版 `<插件仓>/data/paths.json`
 * 仍兼容读），避免大脑与脚本对「记忆真源在哪」各持一说。
 *
 * 为什么默认不再取「插件仓自身 data/」（issue #18 相邻问题，数据丢失级）：
 *   DSH 插件按 hoisted 布局装在 `<profile>/node_modules/<pkg>`，`pnpm` 更新该包
 *   会**整个替换包目录**——运行时数据落在包内（`<pkg>/data`）时，每次更新成功
 *   即连目录一起删掉（贡献者实机实证：`data/` 54 文件 → 0，46 条记忆节点只能
 *   靠人工备份回填）；`paths.json` 同址，用户配置一并丢失。故默认数据根与配置
 *   文件一律落**用户级状态根**（见 `stateRoot()`），与包目录彻底解耦。
 *
 * 优先级（高 → 低）：
 *   1. 环境变量 `MDCG_DATA_ROOT`（数据根）／ `MDCG_ROOT`（认知图根）
 *   2. 用户可编辑配置 `paths.json` 的 `data_root` / `root`
 *      （位置：`<用户级状态根>/paths.json`；旧 `<插件仓>/data/paths.json` 兼容读）
 *   3. 插件配置项 `mdcg.root`（可为空=未指定）
 *   4. 默认 `<用户级状态根>/data/mdcg`
 *
 * 为什么默认不取「相对 cwd 的 data/mdcg」：
 *   node 侧插件与 python 侧脚本的 cwd 不同，相对路径会漂移成
 *   `<cwd>/data/mdcg`。历史事故：宿主 cwd 落在 AEIS 时，记忆真源
 *   分裂到 `AEIS/data/mdcg`，与插件仓 `data/` 变成互不可见的两处。
 *
 * 旧数据接手：`migrateLegacyData()` 在默认数据根生效且旧包内位置仍有内容时
 * 一次性**复制**（不删除、不覆盖）到用户级位置——见该函数注释。
 */
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { delimiter, dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const ENV_DATA_ROOT = 'MDCG_DATA_ROOT'
export const ENV_MDCG_ROOT = 'MDCG_ROOT'

let cachedRepoRoot: string | null = null

/** 插件仓根目录：自本模块所在目录向上找 package.json（对构建层级不敏感）。 */
export function repoRoot(): string {
  if (cachedRepoRoot) return cachedRepoRoot
  let dir = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i += 1) {
    if (existsSync(join(dir, 'package.json'))) {
      cachedRepoRoot = dir
      return dir
    }
    const up = dirname(dir)
    if (up === dir) break
    dir = up
  }
  // 兜底：lib/lib/x.js 或 lib/x.js → 均回到仓根
  cachedRepoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
  return cachedRepoRoot
}

export const ENV_STATE_ROOT = 'MDCG_STATE_ROOT'

let cachedStateRoot: string | null = null

/**
 * 用户级状态根（**插件包目录之外**）：路径配置与默认数据根的落点。
 * 优先级：`MDCG_STATE_ROOT` → `$DSH_HOME/.dsh-memory` → `~/.dsh/.dsh-memory`。
 * `DSH_HOME` **未必**由宿主注入（本仓 `dsh/dsh-web-start.bat` 自行 set），
 * 故家目录兜底；`~/.dsh` 是本插件既有约定（`bridge.ts` 调试日志同址）。
 */
export function stateRoot(): string {
  if (cachedStateRoot) return cachedStateRoot
  const env = process.env[ENV_STATE_ROOT]
  if (env) {
    cachedStateRoot = resolve(env)
    return cachedStateRoot
  }
  const dshHome = process.env['DSH_HOME']
  cachedStateRoot = dshHome
    ? join(resolve(dshHome), '.dsh-memory')
    : join(homedir(), '.dsh', '.dsh-memory')
  return cachedStateRoot
}

/** 旧版落点（插件包内 `data/`）——更新时会被整个替换，只作兼容读与迁移源。 */
export function legacyDataRoot(): string {
  return join(repoRoot(), 'data')
}

function samePath(a: string, b: string): boolean {
  return process.platform === 'win32' ? a.toLowerCase() === b.toLowerCase() : a === b
}

/**
 * 用户可编辑的路径配置文件：
 *   `<用户级状态根>/paths.json` → 不存在则回落**旧** `<插件仓>/data/paths.json`
 *   （兼容读）→ 都不存在返回新位置（首次写入时创建）。
 * 不做自动复制：配置文件是「谁说了算」的唯一真源，悄悄复制会让旧件的后续编辑
 * 静默失效——迁移只搬数据面，配置显式交给用户搬（或用 `set_user_root`）。
 */
export function pathsFile(): string {
  const current = join(stateRoot(), 'paths.json')
  if (existsSync(current)) return current
  const legacy = join(legacyDataRoot(), 'paths.json')
  return existsSync(legacy) ? legacy : current
}

/** 生效中的 paths.json 位置来源：`user`=用户级 / `legacy`=旧包内（兼容读）。 */
export function pathsFileSource(): 'user' | 'legacy' {
  return samePath(dirname(pathsFile()), stateRoot()) ? 'user' : 'legacy'
}

function readUserPaths(): Record<string, unknown> {
  try {
    const raw = readFileSync(pathsFile(), 'utf8')
    const parsed: unknown = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

/** 相对路径一律对「插件仓根」解析（不随宿主 cwd 漂移）。 */
function anchor(p: string): string {
  return isAbsolute(p) ? p : resolve(repoRoot(), p)
}

/** 默认数据根 = 用户级状态根下 `data/`（**插件包目录之外**，更新不触碰）。 */
export function defaultDataRoot(): string {
  return join(stateRoot(), 'data')
}

export interface LegacyMigration {
  /** 是否真的搬了（false 时 `reason` 说明为何没搬）。 */
  ran: boolean
  reason: string
  from: string
  to: string
  /** 复制成功的顶层条目数。 */
  copied: number
  /** 复制失败的顶层条目（权限/占用等，逐项吞掉不抛）。 */
  failed: string[]
}

/** dst 为「空目录」时 true（不存在/非目录/有内容均为 false）。 */
function isEmptyDir(p: string): boolean {
  try {
    return readdirSync(p).length === 0
  } catch {
    return false
  }
}

/**
 * 一次性迁移：把旧版留在**插件包内** `data/` 的数据面复制到用户级默认数据根。
 *
 * 触发条件（三条同时满足，缺一不动）：
 *   ① 数据根未被显式配置（env `MDCG_DATA_ROOT` / paths.json 的 `data_root` 都未设，
 *      即 `dataRoot()` 恰为默认值）——显式配置是用户的决定，越权搬运等于改他的真源；
 *   ② 旧位置存在；
 *   ③ 目标顶层条目不存在或为空目录（**不覆盖、不合并**已有数据）。
 *
 * 只复制不删除（旧目录随后由 pnpm 更新自然移除）；`paths.json` 不复制
 * （配置走 `pathsFile()` 兼容读，复制会制造「哪个文件说了算」的两说）。
 * 任何异常逐项吞掉并记入 `failed`——迁移是增益，不该成为启动失败源。
 *
 * 边界（如实）：pnpm 更新是**先替换包目录再启动新代码**，故旧数据在升级瞬间
 * 即已消失，本函数只能接手「旧位置那时仍在」的情形（手工安装、就地覆盖、
 * 或包目录未被清理）；已在升级中丢掉的数据无法由此恢复——发布说明须提示
 * 0.4.8 及更早用户升级前备份 `<profile>/node_modules/<pkg>/data/`。
 */
export function migrateLegacyData(): LegacyMigration {
  const from = legacyDataRoot()
  const to = defaultDataRoot()
  const out: LegacyMigration = { ran: false, reason: '', from, to, copied: 0, failed: [] }
  if (!samePath(dataRoot(), to)) {
    out.reason = '数据根为显式配置（env/paths.json），不迁移'
    return out
  }
  if (!existsSync(from)) {
    out.reason = '旧位置不存在（多为更新时已随包目录被替换）'
    return out
  }
  let entries: string[]
  try {
    entries = readdirSync(from)
  } catch {
    out.reason = '旧位置不可读'
    return out
  }
  const names = entries.filter((n) => n !== 'paths.json')
  if (!names.length) {
    out.reason = '旧位置无数据'
    return out
  }
  for (const name of names) {
    const src = join(from, name)
    const dst = join(to, name)
    // 新位置已有实质内容 → 跳过（宁可少搬，不可覆盖）
    if (existsSync(dst) && !isEmptyDir(dst)) continue
    try {
      mkdirSync(to, { recursive: true })
      cpSync(src, dst, { recursive: true, force: false, errorOnExist: false })
      out.copied += 1
    } catch {
      out.failed.push(name)
    }
  }
  out.ran = out.copied > 0
  if (!out.ran) out.reason = out.failed.length ? '目标不可写' : '新位置已有数据，未覆盖'
  return out
}

export const ENV_CHILD_CWD = 'MDCG_CHILD_CWD'

let cachedRunRoot: string | null = null

/**
 * 子进程的工作目录（**必须落在插件包目录之外**）。
 *
 * 为什么不能沿用 `repoRoot()`：Windows 不允许删除／改名「正被某进程当作 CWD」
 * 的目录。DSH 的插件按 hoisted 布局安装在 `<profile>/node_modules/<pkg>`，
 * 而 `pnpm` 每次更新该包都要先 `rmdir` 包目录 → 子进程一旦把包目录当 CWD，
 * 更新必然 `ERR_PNPM_EBUSY: resource busy or locked`（含升级回滚一起失败，
 * 应用内永远升不动这个插件）。注意落点也**不能**是 `<包>/data`——它仍在包内，
 * 实测同样 `err=32`。
 *
 * 落点要求「稳定存在」：进程 cwd 指向已消失的目录会引出新的怪问题，故按稳定度
 * 排候选目录，取**第一个能建成**的：
 *   1. `MDCG_CHILD_CWD`（显式覆盖）
 *   2. `$DSH_HOME/.dsh-memory/run`
 *   3. `~/.dsh/.dsh-memory/run` —— 家目录兜底：`DSH_HOME` **未必**由宿主注入
 *      （本仓 `dsh/dsh-web-start.bat` 是自行 `set DSH_HOME=%USERPROFILE%\.dsh`），
 *      而 `~/.dsh` 是本插件既有约定（`bridge.ts` 调试日志、`token_store` 密钥环同址）
 *   4. 系统临时目录（可能被清理，故排最后）
 * 全部建不成时不抛错，交给 spawn 报错——cwd 落点只是防呆，不该成为启动失败源。
 *
 * 安全性：`python -m` 的模块解析由 `pythonPathValue()` 的 PYTHONPATH 独立保证，
 * 不依赖 cwd；已实测 cwd=包目录 与 cwd=包外 时，MCP initialize 握手与
 * tools/list 工具面（33 个工具）完全一致。
 */
export function runRoot(): string {
  if (cachedRunRoot) return cachedRunRoot
  const candidates: string[] = []
  const override = process.env[ENV_CHILD_CWD]
  if (override) candidates.push(resolve(override))
  const dshHome = process.env['DSH_HOME']
  if (dshHome) candidates.push(join(resolve(dshHome), '.dsh-memory', 'run'))
  candidates.push(join(homedir(), '.dsh', '.dsh-memory', 'run'))
  candidates.push(join(tmpdir(), 'dsh-memory-run'))
  for (const dir of candidates) {
    try {
      mkdirSync(dir, { recursive: true })
      cachedRunRoot = dir
      return dir
    } catch {
      /* 该候选不可用（父目录只读等）→ 试下一个 */
    }
  }
  const last = candidates[candidates.length - 1] ?? tmpdir()
  cachedRunRoot = last
  return last
}

/** 数据根（记忆/账本/运行态的父目录）。 */
export function dataRoot(): string {
  const env = process.env[ENV_DATA_ROOT]
  if (env) return anchor(env)
  const cfg = readUserPaths()['data_root']
  if (typeof cfg === 'string' && cfg) return anchor(cfg)
  return defaultDataRoot()
}

/**
 * 认知图根（记忆唯一真源）。
 * @param configured 插件配置项 `mdcg.root`；空串/未给=None 表示未指定，走默认。
 */
export function mdcgRoot(configured?: string): string {
  const env = process.env[ENV_MDCG_ROOT]
  if (env) return anchor(env)
  const cfg = readUserPaths()['root']
  if (typeof cfg === 'string' && cfg) return anchor(cfg)
  if (configured && configured.trim()) return anchor(configured.trim())
  return join(dataRoot(), 'mdcg')
}

/**
 * Python 子进程的 PYTHONPATH 值（issue #12）。
 *
 * Python 启动 `-m` 时只把 **cwd** 注入 sys.path——DSH 宿主在插件仓外启动时
 * `python -m md_cg.mcp_server` / `python -m md_cg.tokens` 必然
 * ModuleNotFoundError。cwd 与 PYTHONPATH 双保险：后者不依赖 cwd，即使调用方
 * 显式覆盖了启动参数/工作目录也兜得住。顺序：仓根在前（优先随包 md_cg，
 * 防宿主环境同名旧包抢先），进程既有 PYTHONPATH 在后。
 */
export function pythonPathValue(): string {
  const prev = process.env.PYTHONPATH ?? ''
  const parts = [repoRoot()]
  if (prev && !prev.split(delimiter).includes(repoRoot())) parts.push(prev)
  return parts.join(delimiter)
}

/** 当前解析快照（供启动日志留痕——把「记忆真源在哪」写进可审计痕迹）。 */
export function describeDataPaths(configured?: string): Record<string, string | boolean> {
  const dr = dataRoot()
  const mr = mdcgRoot(configured)
  const paths = readUserPaths()
  const pfSource = pathsFileSource()
  let source = 'default(用户级状态根 data/)'
  if (process.env[ENV_DATA_ROOT]) source = `env:${ENV_DATA_ROOT}`
  else if (process.env[ENV_MDCG_ROOT]) source = `env:${ENV_MDCG_ROOT}`
  else if (typeof paths['data_root'] === 'string' || typeof paths['root'] === 'string') {
    source = pfSource === 'user' ? 'paths.json(用户级)' : 'paths.json(兼容读旧包内位置)'
  } else if (configured && configured.trim()) source = 'config.mdcg.root'
  return {
    repoRoot: repoRoot(),
    stateRoot: stateRoot(),
    dataRoot: dr,
    mdcgRoot: mr,
    source,
    pathsFile: pathsFile(),
    pathsFileSource: pfSource,
    isDefault: samePath(dr, defaultDataRoot()),
    legacyDataRoot: legacyDataRoot(),
    legacyDataExists: existsSync(legacyDataRoot()),
    dataRootExists: existsSync(dr),
    mdcgRootExists: existsSync(mr),
  }
}
