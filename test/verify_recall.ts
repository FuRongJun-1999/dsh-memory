/**
 * verify_recall.ts · 自动 recall 注入验证（GPT 审查完善·记忆只写不读）
 * ① autoRecall 开启时：system-prompt/assemble 触发 → 注入灵枢最近记忆
 * ② 注入失败静默（不阻塞 next/不抛错）
 * ③ 关闭时：不注入
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

async function main(): Promise<void> {
  // ① autoRecall 开启 → 注入
  const listeners1 = new Map<string, (a: any, c: any, n: any) => Promise<any>>()
  const ctx1 = makeCtx(listeners1)
  const bridge1: any = {
    callCalls: 0,
    async callTool(name: string) {
      this.callCalls++
      return { content: [{ type: 'text', text: '记忆1：用户喜欢猫\n记忆2：上次聊了排序' }], isError: false }
    },
  }
  installMemoryHooks(ctx1 as any, bridge1, {
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
    check('①b 注入了最近记忆', !!injected && injected.text.includes('记忆1'), injected?.text.slice(0, 30))
    check('①c 调用了 timeline', (bridge1 as any).callCalls === 1)
    check('①d next 未被阻塞', nextCalled)
  }

  // ② 召回失败静默（bridge 抛错 → 不抛、next 照常）
  const listeners2 = new Map<string, (a: any, c: any, n: any) => Promise<any>>()
  const ctx2 = makeCtx(listeners2)
  const bridge2: any = { async callTool() { throw new Error('桥不可用') } }
  installMemoryHooks(ctx2 as any, bridge2, {
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
  installMemoryHooks(ctx3 as any, { async callTool() { return { content: [] } } } as any, {
    userMessage: true, assistantMessage: false, toolResult: false,
    importance: 0.6, autoRecall: false, autoRecallLimit: 4,
  })
  check('③ autoRecall 关闭 → 无 assemble 监听', !listeners3.has('system-prompt/assemble'))

  console.log(`\n自动 recall 注入验证: ${pass}/${pass + fail} 通过`)
  process.exit(fail > 0 ? 1 : 0)
}

main().catch((err) => { console.error('异常:', err); process.exit(1) })
