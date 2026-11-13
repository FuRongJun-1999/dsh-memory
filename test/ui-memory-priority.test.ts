/**
 * 守卫 · 记忆页「先看近的与待办的，历史手动加载」（使用者裁定 2026-11-14）。
 *
 * 实测（3.5 万节点库，python 直调 mcp_server）：
 *   self_state snapshot 0.02s | review list 0.15s | recent 100 0.00s | timeline 100 0.62s
 *   cg read k=30 24.29s（且 k=5 亦 24.15s ⇒ 成本在检索本体）
 * ⇒ 首屏必须只含前四者；read / timeline 只能在**手动点击**后发起。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const app = readFileSync(join(root, 'ui/minimal/payload/web/app.js'), 'utf8')
const memStart = app.indexOf('  async function memory(token, compose) {')
const memEnd = app.indexOf('  const presets = {')
const mem = app.slice(memStart, memEnd)

test('M1 记忆页首屏含四个优先区块（自我层/待裁决/今日对话/最近100）', () => {
  for (const id of ['sec-self', 'sec-review', 'sec-today', 'sec-recent']) {
    assert.ok(mem.includes(`id="${id}"`), `缺区块 ${id}`)
  }
  assert.ok(mem.includes("op:'self_state',action:'snapshot'"), '自我层用 self_state snapshot')
  assert.ok(mem.includes("op:'review',action:'list'"), '待裁决用 review list')
  assert.ok(mem.includes("op:'recent',action:'list',limit:100"), '最近 100 条用 recent limit=100')
})

test('M2 首屏绝不发 read / timeline（历史与检索必须手动）', () => {
  // 只判**调用**（op:'xxx'），不判提示文案里出现的词（hint 里写着 read≈24s 是允许的）
  const beforeHistory = mem.slice(0, mem.indexOf("$('load-older')"))
  assert.ok(!beforeHistory.includes("op:'read'"), '首屏出现 read 调用 ⇒ 会拖 24s')
  assert.ok(!beforeHistory.includes("op:'timeline'"), '首屏出现 timeline 调用 ⇒ 历史必须手动')
  assert.ok(mem.includes("$('hist-search').onsubmit"), '全库检索也必须是手动入口')
  assert.ok(mem.includes("$('load-older').onclick"), '需要手动「加载更早的对话」按钮')
  assert.ok(mem.includes("$('cancel-load').onclick"), '手动加载必须可取消')
})

test('M3 今日对话按本地零点过滤（不是再发一次请求）', () => {
  assert.ok(mem.includes('setHours(0,0,0,0)'), '今日边界应用本地零点')
  assert.ok(mem.includes('todayTs'), '需要 todayTs 用于过滤')
})

test('M4 待裁决渲染上限 20（240 条不一次铺 DOM）', () => {
  assert.ok(mem.includes('pd.slice(0,20)'), '待裁决需分片渲染')
  assert.ok(mem.includes('还有 ${pd.length-20} 条'), '需要明示未展示条数')
})

test('M5 三个优先区块并行且互不阻塞', () => {
  assert.ok(mem.includes('Promise.allSettled([selfP,reviewP,recentP])'), '三块应并行')
  assert.ok(mem.includes('.catch('), '单块失败不得拖垮整页')
})