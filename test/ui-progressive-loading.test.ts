/**
 * 守卫 · 界面渐进加载（性能）：不要把重活放在首屏。
 *
 * 实测（本机 3.5 万节点库，python 直调 mcp_server）：
 *   info(无 full)      0.09s      info(full=true)  13.94s   ← health_os 全库扫描
 *   stg timeline 30    0.62s      recent 20        0.00s
 *   cg read k=30      24.29s      cg read k=5      24.15s   ← 与 k 无关：成本在检索本体
 * 故：概览页不得用 full=true；检索不得在进页面时自动发；列表必须分页 + 缓存 + 可中止。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const app = readFileSync(join(root, 'ui/minimal/payload/web/app.js'), 'utf8')

test('P1 概览不得调 info(full=true)（实测 13.94s）', () => {
  assert.ok(!/op:\s*'info'[^}]*full:\s*true/.test(app), '概览仍在用 full=true')
  assert.ok(/op:\s*'info'/.test(app), '仍需调用 info（快照面 0.09s）')
})

test('P2 概览统计走各自最便宜的 op（并行、容错）', () => {
  for (const snippet of ["op:'goal',action:'list'", "op:'review',action:'list'", "op:'protect',action:'stats'"]) {
    assert.ok(app.includes(snippet), `缺 ${snippet} —— 统计卡会用 14s 的 full 面`)
  }
  assert.ok(app.includes('Promise.allSettled'), '三张统计卡需要并行且单个失败不拖垮整页')
})

test('P3 记忆页首屏不得自动检索（read 实测 24s）——改为历史区手动入口', () => {
  const mem = app.slice(app.indexOf('  async function memory(token, compose) {'), app.indexOf('  const presets = {'))
  const head = mem.slice(0, mem.indexOf("$('load-older')"))
  assert.ok(!head.includes("op:'read'"), '首屏不得发 read')  // 24s
  assert.ok(!head.includes("op:'timeline'"), '首屏不得发 timeline')  // 历史必须手动
  assert.ok(mem.includes("$('hist-search').onsubmit"), '全库检索必须是手动入口')  // 无自动检索
})

test('P4 同参数结果进客户端缓存（60s TTL）', () => {
  assert.ok(app.includes('const CACHE_TTL=60000'), '缺 TTL 缓存')
  assert.ok(app.includes('cacheGet(key)'), '列表要读缓存')
  assert.ok(app.includes('cacheSet(key'), '列表要写缓存')
})

test('P5 慢请求可中止且**不覆盖调用方信号**（issue #925）', () => {
  assert.ok(app.includes('AbortController'), '需要 AbortController')
  assert.ok(app.includes('AbortSignal.any([controller.signal, options.signal])'),
    '调用方 signal 必须与内部超时 signal **合并**（覆盖 → 取消无效）')
  assert.ok(!/signal:controller\.signal \}/.test(app),
    '不得再出现「展开 options 后直接赋 signal」的覆盖写法')
  assert.ok(app.includes('signal:histCtrl.signal'), '历史/检索请求需把 signal 传下去')
  assert.ok(app.includes('histCtrl.abort()'), '新请求要先中止旧的')
})