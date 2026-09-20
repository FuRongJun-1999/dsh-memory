/**
 * datapath.ts · 灵枢数据根解析（记忆写入路径可配置）
 *
 * 与 Python 侧 `md_cg/datapath.py` **同口径**——两侧读同一份
 * `<插件仓>/data/paths.json`，避免大脑与脚本对「记忆真源在哪」各持一说。
 *
 * 优先级（高 → 低）：
 *   1. 环境变量 `MDCG_DATA_ROOT`（数据根）／ `MDCG_ROOT`（认知图根）
 *   2. 用户可编辑配置 `<插件仓>/data/paths.json` 的 `data_root` / `root`
 *   3. 插件配置项 `mdcg.root`（可为空=未指定）
 *   4. 默认 `<插件仓>/data/mdcg`（**自身仓库**，与进程 cwd 解耦）
 *
 * 为什么默认不再取「相对 cwd 的 data/mdcg」：
 *   node 侧插件与 python 侧脚本的 cwd 不同，相对路径会漂移成
 *   `<cwd>/data/mdcg`。历史事故：宿主 cwd 落在 AEIS 时，记忆真源
 *   分裂到 `AEIS/data/mdcg`，与插件仓 `data/` 变成互不可见的两处。
 *   锚定 `package.json` 所在目录后，默认值稳定且可预期。
 */
import { existsSync, mkdirSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
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

/** 用户可编辑的路径配置文件（固定在插件仓 data/，不受 dataRoot 取值影响）。 */
export function pathsFile(): string {
  return join(repoRoot(), 'data', 'paths.json')
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

export function defaultDataRoot(): string {
  return join(repoRoot(), 'data')
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
 * 落点要求「稳定存在」：系统临时目录可能被清理，进程 CWD 消失会引出新的怪问题，
 * 故默认取 DSH home 下的固定目录（`DSH_HOME` 由宿主注入）。
 * 优先级：`MDCG_CHILD_CWD` → `$DSH_HOME/.dsh-memory/run` → 系统临时目录。
 *
 * 安全性：`python -m` 的模块解析由 `pythonPathValue()` 的 PYTHONPATH 独立保证，
 * 不依赖 cwd；已实测 cwd=包目录 与 cwd=包外 时，MCP initialize 握手与
 * tools/list 工具面（33 个工具）完全一致。
 */
export function runRoot(): string {
  if (cachedRunRoot) return cachedRunRoot
  const env = process.env[ENV_CHILD_CWD]
  const base = env
    ? resolve(env)
    : process.env['DSH_HOME']
      ? join(resolve(process.env['DSH_HOME'] as string), '.dsh-memory', 'run')
      : join(tmpdir(), 'dsh-memory-run')
  try {
    mkdirSync(base, { recursive: true })
    cachedRunRoot = base
  } catch {
    // 建不出来就退回系统临时目录（同样在包外），不让子进程因 cwd 缺失而启动失败
    const fallback = join(tmpdir(), 'dsh-memory-run')
    try { mkdirSync(fallback, { recursive: true }) } catch { /* 最终交给 spawn 报错 */ }
    cachedRunRoot = fallback
  }
  return cachedRunRoot
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
  let source = 'default(插件仓自身 data/)'
  if (process.env[ENV_DATA_ROOT]) source = `env:${ENV_DATA_ROOT}`
  else if (process.env[ENV_MDCG_ROOT]) source = `env:${ENV_MDCG_ROOT}`
  else if (typeof paths['data_root'] === 'string' || typeof paths['root'] === 'string') source = 'paths.json'
  else if (configured && configured.trim()) source = 'config.mdcg.root'
  return {
    repoRoot: repoRoot(),
    dataRoot: dr,
    mdcgRoot: mr,
    source,
    pathsFile: pathsFile(),
    isDefault: dr === defaultDataRoot(),
    dataRootExists: existsSync(dr),
    mdcgRootExists: existsSync(mr),
  }
}
