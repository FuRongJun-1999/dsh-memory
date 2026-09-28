/**
 * N219 守卫 · stdout 行处理器必须校验 JSON.parse 结果类型（对应 src/bridge.ts:231-243）
 *
 * 缺陷链条（修复前）：
 *  · `this.rl.on('line', ...)` 只 catch「非 JSON」一种失败（JSON.parse 抛 SyntaxError），
 *    解析结果本身**零类型校验**，直接声明为 Record<string, unknown> 后读 `msg['id']`；
 *  · 子进程 stdout 出现一行 `null`（崩溃残留、第三方写管道、新版打印）→ JSON.parse
 *    合法返回 null → `msg['id']` 抛 TypeError「Cannot read properties of null」；
 *  · 抛出点在 readline 的 'line' 事件回调内且无 try——异常沿 EventEmitter 逃逸为
 *    进程级 uncaughtException，**宿主 DSH 进程整体死亡**（每行都在监听、无需凭据、
 *    记忆面随宿主一起不可用）。
 *
 * 守卫断言（对修复前代码红）：
 *  1. 行为：哑子进程先写一行 `null`（其余 JSON 标量形态逐一覆盖），再写一行合法
 *     响应——宿主 uncaughtException 钩子不得捕获到任何异常（修复前 null 一行即命中）；
 *  2. 行为：`null` 之后写入的合法响应仍必须被正常结算（不因一行坏输出而丢消息 / 断流）；
 *  3. 结构（防回归）：桥源码的行处理器对 parse 结果存在类型闸（typeof 判定）。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { LingshuBridge } from '../src/bridge.js'

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

/**
 * 哑 DSH 侧子进程：按顺序打印坏行（JSON 标量与数组形态），然后**常驻**并在
 * 收到 stdin 上一行请求后回一个合法 JSON-RPC 响应——用于验证坏行之后协议面
 * 仍然可用（不丢流）。
 */
const FAKE_SERVER = [
  'const bad = process.argv[1];',
  'let done = false;',
  'process.stdout.write(bad + "\\n");',
  'process.stdin.on("data", (chunk) => {',
  '  for (const line of String(chunk).split("\\n")) {',
  '    if (!line.trim()) continue;',
  '    const m = JSON.parse(line);',
  '    if (m.method === "initialize" && !done) {',
  '      done = true;',
  '      process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: m.id, result: { ok: true } }) + "\\n");',
  '    }',
  '  }',
  '});',
  'setInterval(() => {}, 1 << 30);',
].join('')

/** 造桥：以 node 自身当「python」，坏行由 argv 传入。 */
function createBridge(badLine: string): LingshuBridge {
  return new LingshuBridge({
    python: process.execPath,
    args: ['-e', FAKE_SERVER, badLine],
    env: {},
    timeoutMs: 4000,
    maxRetryDelayMs: 1000,
  })
}

test('N219：stdout 一行 null 不得杀宿主、且其后协议面仍可用', async () => {
  const escaped: Error[] = []
  const onUncaught = (err: Error): void => { escaped.push(err) }
  // 宿主视角：无监听者时这一下就是进程整体崩溃
  process.on('uncaughtException', onUncaught)

  const bridge = createBridge('null')
  try {
    bridge.start()
    // 握手请求（initialize）在 spawn 后立即发出；坏行先于响应到达
    const ready = await bridge.waitReady().catch(() => false)
    await sleep(300)
    assert.equal(escaped.length, 0,
      `未捕获异常逃逸到宿主 ${escaped.length} 次：` +
      `${escaped.map((e) => e.message).join('; ')}——生产宿主会整体死亡`)
    // 断言 2：一行坏输出不得断流——其后合法响应仍须结算
    assert.equal(ready, true, 'null 行之后的 initialize 响应未结算（协议面被一行坏输出打断）')
  } finally {
    process.removeListener('uncaughtException', onUncaught)
    bridge.dispose()
    await sleep(200)
  }
})

test('N219：其余 JSON 标量/数组形态同样不得杀宿主', async () => {
  const escaped: Error[] = []
  const onUncaught = (err: Error): void => { escaped.push(err) }
  process.on('uncaughtException', onUncaught)
  try {
    for (const bad of ['{}', '[]', '123', '"x"', 'true', 'false', '0']) {
      const bridge = createBridge(bad)
      try {
        bridge.start()
        await sleep(250)
        assert.equal(escaped.length, 0,
          `形态 ${bad} 触发未捕获异常：${escaped.map((e) => e.message).join('; ')}`)
      } finally {
        bridge.dispose()
        await sleep(100)
      }
    }
  } finally {
    process.removeListener('uncaughtException', onUncaught)
  }
})

test('N219：结构断言——行处理器对 parse 结果存在类型闸（防回归）', () => {
  const src = readFileSync(resolve(REPO_ROOT, 'src', 'bridge.ts'), 'utf8')
  const handler = src.slice(src.indexOf("this.rl.on('line'"))
  const body = handler.slice(0, handler.indexOf('proc.on('))
  assert.match(body, /typeof\s+\w+\s*!==\s*'object'/,
    "行处理器须对 JSON.parse 结果做 typeof !== 'object' 类型闸——" +
    '否则 null 等标量一行即打崩宿主进程')
})
