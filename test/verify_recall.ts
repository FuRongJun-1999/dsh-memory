/**
 * verify_recall.ts · 自动 recall 注入验证（GPT 审查完善·记忆只写不读）
 *
 * 记忆真源已统一为 md_cg 认知图：注入走 MdcgClient.timeline() → stg(op=timeline)。
 * ① autoRecall 开启时：system-prompt/assemble 触发 → 注入认知图最近记忆
 * ② 注入失败静默（不阻塞 next/不抛错）
 * ③ 关闭时：不注入
 * ④ 认知图未启用（mdcg=null）→ 自动记忆整体停用（不注册任何监听）
 */
import { installMemoryHooks } from '../src/hooks.ts'

let pass = 0, fail = 0
function check(name: string, ok: boolean, detail = ''): void {
  if (ok) pass++; else fail++
  console.log(`[${ok ? '✓' : '✘'}] ${name}${detail ? ' — ' + detail : ''}`)
}

interface AssembleMock { contexts: Array<{ name: string; text: string }> }
interface CtxMock {
  logger: { info: () => void; warn: () => void }
  on(ev: string, fn: (assembly: AssembleMock, ctx: unknown, next: () => Promise<unknown>) => Promise<unknown>): void
  [k: string]: unknown
}

function makeCtx(listeners: Map<string, (a: any, c: any, n: any) => Promise<any>>): CtxMock {
  return {
    logger: { info: () => {}, warn: () => {} },
    on(ev: string, fn: any) { listeners.set(ev, fn); },
  } as CtxMock
}

/** MdcgClient 假体：钩子只用到 isReady / timeline 两个成员。
 *  返回的 calls 记录每次 timeline 的 limit，用于断言调用发生。 */
function makeMdcg(timelineImpl: (limit: number) => Promise<unknown>): { client: any; calls: number[] } {
  const calls: number[] = []
  return {
    calls,
    client: {
      isReady: () => true,
      async timeline(limit: number) {
        calls.push(limit)
        return timelineImpl(limit)
      },
    },
  }
}

async function main(): Promise<void> {
  // ① autoRecall 开启 → 注入
  const listeners1 = new Map<string, (a: any, c: any, n: any) => Promise<any>>()
  const ctx1 = makeCtx(listeners1)
  const m1 = makeMdcg(async () => ({
    count: 2, limit: 4,
    items: [
      { id: 'n1', layer: 'contextual', start: 1, end: 2, preview: '记忆1：用户喜欢猫' },
      { id: 'n2', layer: 'knowledge', start: 3, end: 4, preview: '记忆2：上次聊了排序' },
    ],
  }))
  installMemoryHooks(ctx1 as any, m1.client, {
    userMessage: true, assistantMessage: false, toolResult: false,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4,
  })
  const fn1 = listeners1.get('system-prompt/assemble')
  check('①a 注册了 assemble 监听', !!fn1)
  if (fn1) {
    let nextCalled = false
    const assembly: AssembleMock = { contexts: [] }
    await fn1(assembly, {}, async () => { nextCalled = true; return assembly })
    const injected = assembly.contexts.find((c) => c.name === 'lingshu:auto-recall')
    check('①b 注入了最近记忆', !!injected && injected.text.includes('记忆1'), injected?.text.slice(0, 40))
    check('①c 调用了 stg(op=timeline)（一次）', m1.calls.length === 1)
    check('①d 层号带出（[contextual]）', !!injected && injected.text.includes('[contextual]'))
    check('①e next 未被阻塞', nextCalled)
  }

  // ② 召回失败静默（认知图抛错 → 不抛、不注入、next 照常）
  const listeners2 = new Map<string, (a: any, c: any, n: any) => Promise<any>>()
  const ctx2 = makeCtx(listeners2)
  const m2 = makeMdcg(async () => { throw new Error('认知图不可用') })
  installMemoryHooks(ctx2 as any, m2.client, {
    userMessage: true, assistantMessage: false, toolResult: false,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4,
  })
  const fn2 = listeners2.get('system-prompt/assemble')!
  const assembly2: AssembleMock = { contexts: [] }
  let next2 = false
  await fn2(assembly2, {}, async () => { next2 = true; return assembly2 })
  check('② 召回失败静默（无注入、next 照常、不抛错）',
    assembly2.contexts.length === 0 && next2)

  // ③ autoRecall 关闭 → 不注入
  const listeners3 = new Map<string, (a: any, c: any, n: any) => Promise<any>>()
  const ctx3 = makeCtx(listeners3)
  const m3 = makeMdcg(async () => ({ items: [] }))
  installMemoryHooks(ctx3 as any, m3.client, {
    userMessage: true, assistantMessage: false, toolResult: false,
    importance: 0.6, autoRecall: false, autoRecallLimit: 4,
  })
  check('③ autoRecall 关闭 → 无 assemble 监听', !listeners3.has('system-prompt/assemble'))

  // ④ 认知图未启用（mdcg=null）→ 自动记忆整体停用，不注册任何监听
  const listeners4 = new Map<string, (a: any, c: any, n: any) => Promise<any>>()
  const ctx4 = makeCtx(listeners4)
  installMemoryHooks(ctx4 as any, null, {
    userMessage: true, assistantMessage: true, toolResult: true,
    importance: 0.6, autoRecall: true, autoRecallLimit: 4,
  })
  check('④ mdcg=null → 整体停用（无 assemble / session-event 监听）',
    !listeners4.has('system-prompt/assemble') && !listeners4.has('session/event'))

  console.log(`\n自动 recall 注入验证: ${pass}/${pass + fail} 通过`)
  process.exit(fail > 0 ? 1 : 0)
}

main().catch((err) => { console.error('异常:', err); process.exit(1) })
