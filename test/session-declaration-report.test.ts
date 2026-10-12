/**
 * session-declaration-report.test.ts · issue #128 守卫（TS 侧）：空 catch 已消失
 *
 * 病灶（2026-10-12 复核）：`src/hooks.ts` 的 `system-prompt/assemble` 处理器里有
 * **两处空 catch**（窗口取数 `catch { /* 静默 *\/ }` 与召回 `catch { /* 静默 *\/ }`）。
 * 自动召回块「从未注入成功」（issue #128 的 P0 现象）正是被这两处吞成无痕——
 * 盘面与日志面都看不出「取数失败了」，与「本会话确实没有记忆」不可分辨。
 *
 * 修法（只改回报面，不改控制流）：两处 catch 改为 `ctx.logger.warn(...)`——
 * 失败仍**不抛**（绝不越过会话流边界、不阻塞模型请求），但必须留痕。
 *
 * 本守卫断言：
 *   ① 召回取数失败 ⇒ 有 warn 回报（含「自动召回注入失败」），且不抛；
 *   ② 窗口取数失败 ⇒ 有 warn 回报（含「本会话窗口注入失败」），且不抛；
 *   ③ 源级：`src/hooks.ts` 不再含空 catch（`catch {` 紧跟空体/注释体）；
 *   ④ 正对照：成功路径不产生任何 warn（不滥报）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { installMemoryHooks, type MemoryHooksOptions } from '../src/hooks.ts'

interface Assembly {
  contexts: Array<{ name: string; text: string }>
  variables: Record<string, string>
}
type AssembleHandler = (a: Assembly, c: unknown, n: () => Promise<unknown>) => Promise<unknown>

function makeHarness(graph: object, overrides: Partial<MemoryHooksOptions> = {}) {
  const assembleHandlers: AssembleHandler[] = []
  const warns: string[] = []
  const ctx = {
    logger: { info: () => {}, warn: (m: string) => warns.push(m) },
    on(ev: string, fn: unknown) {
      if (ev === 'system-prompt/assemble') assembleHandlers.push(fn as AssembleHandler)
    },
  }
  installMemoryHooks(ctx as never, graph as never, {
    userMessage: true, assistantMessage: true, toolResult: true,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4, desensitize: false,
    auditPath: join(tmpdir(), 'dsh-hook-audit-session-declaration-report.json'),
    ...overrides,
  })
  const assemble = async (hostCtx: unknown): Promise<Assembly> => {
    assert.ok(assembleHandlers[0], '应注册 system-prompt/assemble 监听')
    const a: Assembly = { contexts: [], variables: {} }
    await assembleHandlers[0]!(a, hostCtx, async () => a)
    return a
  }
  return { assemble, warns }
}

const HOST_CTX = { agent: { session: { id: 'sess_A' } } }

test('① 召回取数失败：显式 warn 回报（不再空 catch 吞掉），且不抛', async () => {
  const graph = {
    isReady: (): boolean => true,
    async timeline(): Promise<never> {
      throw new Error('BOOM-timeline-128')
    },
  }
  const { assemble, warns } = makeHarness(graph)
  const a = await assemble(HOST_CTX)
  assert.equal(a.contexts.length, 0, '取数失败 ⇒ 不注入块（行为不变）')
  assert.ok(warns.some((w) => w.includes('自动召回注入失败')),
    `应有「自动召回注入失败」warn，实得 ${JSON.stringify(warns)}`)
  assert.ok(warns.some((w) => w.includes('BOOM-timeline-128')),
    '回报须带原始错误信息（可诊断）')
})

test('② 窗口取数失败：显式 warn 回报，且不影响既有召回块', async () => {
  const graph = {
    isReady: (): boolean => true,
    async timeline() {
      return {
        count: 1, limit: 4,
        items: [{ id: 'n1', layer: 'contextual', start: 1, end: 2, preview: '预览' }],
      }
    },
    async sessionRecall(): Promise<never> {
      throw new Error('BOOM-window-128')
    },
  }
  const { assemble, warns } = makeHarness(graph, {
    contextWindow: { enabled: true, turns: 10 },
  })
  const a = await assemble(HOST_CTX)
  assert.equal(a.contexts.length, 1, '既有召回块照旧注入（窗口失败不影响它）')
  assert.ok(warns.some((w) => w.includes('本会话窗口注入失败')),
    `应有「本会话窗口注入失败」warn，实得 ${JSON.stringify(warns)}`)
  assert.ok(warns.some((w) => w.includes('BOOM-window-128')),
    '回报须带原始错误信息')
})

test('③ 源级：src/hooks.ts 不再含空 catch（catch 后紧跟空体/纯注释体）', () => {
  const raw = readFileSync(new URL('../src/hooks.ts', import.meta.url), 'utf8')
  // 先去注释再判（否则「修复说明」注释里引用的旧形态字面量会自伤——
  // 本守卫实测踩到过：注释里的 `catch { /* 静默 *\/ }` 被当成了真实空 catch）。
  const src = raw
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/[^\n]*$/gm, '')
    .replace(/\s\/\/[^\n]*$/gm, '')
  // 空 catch 形态：`catch {` 之后只有空白直到 `}`（或带参数 `catch (e) {}`）。
  const emptyCatch = /catch\s*(?:\([^)]*\))?\s*\{\s*\}/g
  const hits = src.match(emptyCatch) ?? []
  assert.deepEqual(hits, [], `不应再有空 catch，实得 ${JSON.stringify(hits)}`)
  // 正对照：两处回报文案在位（防「删了空 catch 却没接回报」）。
  assert.ok(src.includes('自动召回注入失败'), '召回失败回报文案在位')
  assert.ok(src.includes('本会话窗口注入失败'), '窗口失败回报文案在位')
})

test('④ 正对照：成功路径不产生 warn（不滥报）', async () => {
  const graph = {
    isReady: (): boolean => true,
    async timeline() {
      return {
        count: 1, limit: 4,
        items: [{ id: 'n1', layer: 'contextual', start: 1, end: 2, preview: '预览' }],
      }
    },
    async sessionRecall() {
      return { recent: [], notes: [], goals: [], tasks: { active: [], done: [] } }
    },
  }
  const { assemble, warns } = makeHarness(graph, {
    contextWindow: { enabled: true, turns: 10 },
  })
  await assemble(HOST_CTX)
  assert.deepEqual(warns, [], `成功路径不应有 warn，实得 ${JSON.stringify(warns)}`)
})
