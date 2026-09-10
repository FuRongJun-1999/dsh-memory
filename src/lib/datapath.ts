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
import { existsSync, readFileSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'
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
