/**
 * paths.json 取值面的波浪线判据 —— 「只给 env 覆盖值接 expandHome」的负向钉子。
 *
 * 口径（与 md_cg/datapath.py 同）：两侧对 paths.json 的取值都是「相对值（含 ~/...）
 * 先拼插件仓根、再归一」——拼过仓根之后波浪线已不在串首，**两侧都不展开** ⇒ 同为
 * 字面目录。本件只给 env 覆盖值接 expandHome；若有人顺手把展开也接到配置文件取值上，
 * 本文件即报红（过度展开方向）。
 *
 * 期望值独立写出：全部由 join 常量拼出，不调用 dataRoot 反推。
 *
 * 零副作用：状态根与家目录都注入 mkdtemp 临时目录并在 after 清理。
 */

import { test, after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  ENV_DATA_ROOT,
  ENV_MDCG_ROOT,
  ENV_STATE_ROOT,
  dataRoot,
  mdcgRoot,
  pathsFile,
  repoRoot,
} from '../src/lib/datapath.js'

const STATE = mkdtempSync(join(tmpdir(), 'lingshu-pathsfile-state-'))
const HOME_PROBE = mkdtempSync(join(tmpdir(), 'lingshu-pathsfile-home-'))

process.env.HOME = HOME_PROBE
process.env.USERPROFILE = HOME_PROBE
delete process.env[ENV_DATA_ROOT]
delete process.env[ENV_MDCG_ROOT]
delete process.env['DSH_HOME']
process.env[ENV_STATE_ROOT] = STATE
writeFileSync(
  join(STATE, 'paths.json'),
  JSON.stringify({ data_root: '~/dprobe', root: '~/mprobe' }),
  'utf8',
)

after(() => {
  rmSync(STATE, { recursive: true, force: true })
  rmSync(HOME_PROBE, { recursive: true, force: true })
})

test('paths.json 取值：相对值锚插件仓根且不展开波浪线（两侧同口径）', () => {
  assert.equal(pathsFile(), join(STATE, 'paths.json'), '生效中的配置文件应为用户级新位置')
  assert.equal(dataRoot(), join(repoRoot(), '~', 'dprobe'), 'data_root 取值应锚插件仓根')
  assert.equal(mdcgRoot(), join(repoRoot(), '~', 'mprobe'), 'root 取值应锚插件仓根')
  assert.notEqual(
    dataRoot(),
    join(HOME_PROBE, 'dprobe'),
    'paths.json 的 data_root 不得被当 env 展开（过度展开方向）',
  )
  assert.notEqual(
    mdcgRoot(),
    join(HOME_PROBE, 'mprobe'),
    'paths.json 的 root 不得被当 env 展开（过度展开方向）',
  )
})
