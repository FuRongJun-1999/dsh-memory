/**
 * issue #19 回归：解释器默认值必须**平台感知**，不再写死 'python'。
 *
 * 缺陷形态（外部用户实测，Linux）：`spawn python ENOENT` → 桥重试 8 次进终态，
 * 插件加载不报错但工具不注册、记忆永不落盘、必须重启 DSH 才再试一次。
 * 根因是默认值为字面量 `'python'`，而 Linux/macOS 按 PEP 394 只提供 `python3`
 * （发行版默认状态）。故本组断言钉死三件事：
 *   ① 平台分支正确（win32 行为**逐字节不变**，避免修一个平台坏另一个）；
 *   ② env MDCG_PYTHON 可覆盖，空白值视为未设置（防「设了空变量反而更坏」）；
 *   ③ Config 的默认值走解析函数，不再出现任何写死字面量。
 *
 * 纯函数 + 注入 platform/env，故在任意平台可执行（不受本机解释器名影响）；
 * 真实 spawn 路径的覆盖见 test/bridge.test.ts。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { defaultPython, explainMissingPython, selfCheckCommand, PYTHON_ENV_VAR } from '../src/lib/python_path.js'
import { Config } from '../src/index.js'

test('issue #19：Windows 默认 python（既有行为逐字节不变）', () => {
  assert.equal(defaultPython('win32', {}), 'python')
})

test('issue #19：Linux/macOS 默认 python3（PEP 394 只有 python3）', () => {
  assert.equal(defaultPython('linux', {}), 'python3')
  assert.equal(defaultPython('darwin', {}), 'python3')
})

test('issue #19：无覆盖时默认值与运行平台自洽', () => {
  assert.equal(
    defaultPython(process.platform, {}),
    process.platform === 'win32' ? 'python' : 'python3',
  )
})

test('issue #19：env MDCG_PYTHON 覆盖平台默认（含绝对路径/版本号形态）', () => {
  assert.equal(defaultPython('win32', { [PYTHON_ENV_VAR]: 'python3.12' }), 'python3.12')
  assert.equal(defaultPython('linux', { [PYTHON_ENV_VAR]: '/usr/bin/python3.12' }), '/usr/bin/python3.12')
})

test('issue #19：空白 MDCG_PYTHON 视为未设置（不返回空串）', () => {
  assert.equal(defaultPython('linux', { [PYTHON_ENV_VAR]: '   ' }), 'python3')
  assert.equal(defaultPython('win32', { [PYTHON_ENV_VAR]: '' }), 'python')
})

test('issue #19：Config 的 python 默认值来自解析函数（不再写死字面量）', () => {
  const cfg = (Config as unknown as (input: unknown) => { python: string })({})
  assert.equal(cfg.python, defaultPython())
})

test('issue #19：自检命令按实际解释器给出（报错文案可照抄）', () => {
  assert.equal(selfCheckCommand('python3'), 'python3 -m md_cg.mcp_server')
  assert.equal(selfCheckCommand('python'), 'python -m md_cg.mcp_server')
})

test('issue #19：ENOENT 指引含成因与三条修法（防文案回归）', () => {
  const msg = explainMissingPython('python')
  assert.ok(msg.includes('PEP 394'), `应点明 PEP 394 成因（实际：${msg}）`)
  assert.ok(msg.includes('python3'), '应给出 python3 修法')
  assert.ok(msg.includes(PYTHON_ENV_VAR), `应给出 ${PYTHON_ENV_VAR} 环境变量修法`)
})
