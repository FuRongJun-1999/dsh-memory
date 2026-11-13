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

test('P3 记忆页首屏不得自动检索（read 实测 24s）', () => {
  assert.ok(app.includes('setTimeout(()=>{void loadList(true)},350)'), '检索需防抖 350ms')
  assert.ok(app.includes("$('more').onclick"), '需要「加载更多」分页按钮')
  assert.ok(app.includes('limit+=20'), '分页按 20 递增，不得全量')
})

test('P4 同参数结果进客户端缓存（60s TTL）', () => {
  assert.ok(app.includes('const CACHE_TTL=60000'), '缺 TTL 缓存')
  assert.ok(app.includes('cacheGet(key)'), '列表要读缓存')
  assert.ok(app.includes('cacheSet(key'), '列表要写缓存')
})

test('P5 慢请求必须可中止（否则占住单进程 bridge 拖累会话）', () => {
  assert.ok(app.includes('AbortController'), '需要 AbortController')
  assert.ok(app.includes('signal:ctrl.signal'), 'call 需把 signal 传下去')
  assert.ok(app.includes('if(inflight)try{inflight.abort()}catch{}'), '新请求要先中止旧的')
})