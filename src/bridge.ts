/**
 * 灵枢 MCP stdio 桥：管理大脑（md_cg）Python 子进程的生命周期，
 * 通过逐行 JSON-RPC 完成握手、工具发现与调用。
 *
 * 与官方 @deepseek-ai/dsh-mcp-client 不同，本桥零运行时依赖（不引入
 * @modelcontextprotocol/sdk），直接实现灵枢 server 使用的 2024-11-05 协议
 * 子集——与灵枢库 D-005「核心零外部依赖」的工程哲学一致。
 */

import { spawn, type ChildProcess } from 'node:child_process'
import { createInterface } from 'node:readline'
import { mkdirSync, appendFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { homedir } from 'node:os'
// issue #19：自检命令文案按平台给出（Windows python / 其它 python3）、
// 并在 ENOENT 时把「解释器名不匹配」这一第一因直接写进日志。
import { explainMissingPython, selfCheckCommand } from './lib/python_path.js'

/**
 * 调试探针：记录桥生命周期到独立文件（绕过 DSH 日志系统，便于定位启动问题）。
 * 路径从用户家目录动态解析（issue #5）——此前硬编码作者本机绝对路径，
 * 其他用户机器上目录不存在且无权限，探针静默失效，恰在排查启动问题时失明。
 */
const DEBUG_LOG = join(homedir(), '.dsh', 'logs', 'lingshu-bridge-debug.log')
let debugLogDirReady = false
function probe(msg: string): void {
  try {
    if (!debugLogDirReady) {
      mkdirSync(dirname(DEBUG_LOG), { recursive: true })
      debugLogDirReady = true
    }
    appendFileSync(DEBUG_LOG, `[${new Date().toISOString()}] ${msg}\n`)
  } catch { /* 探针失败忽略 */ }
}

/** 灵枢 MCP server 暴露的原始工具（tools/list 结果项）。 */
export interface McpTool {
  name: string
  description: string
  inputSchema?: Record<string, unknown>
}

/** 一次 tools/call 的标准化结果。 */
export interface McpCallResult {
  content: Array<{ type: string; text?: string; [key: string]: unknown }>
  isError: boolean
}

/** 启动灵枢子进程的配置。 */
export interface BridgeOptions {
  /** Python 可执行文件（或 md_cg-mcp console script），默认 python。 */
  python: string
  /** 传给 python 的参数，默认 ['-m', 'md_cg.mcp_server']。 */
  args: string[]
  /** 追加到子进程的环境变量（MDCG_* / MDCG_MCP_SURFACE / 密钥等）。 */
  env: Record<string, string>
  /** 子进程工作目录。 */
  cwd?: string
  /** 单次工具调用超时（毫秒），默认 60s。 */
  timeoutMs: number
  /** 断线重连的最大间隔（毫秒），默认 30s。 */
  maxRetryDelayMs: number
}

interface PendingCall {
  resolve: (value: unknown) => void
  reject: (reason: Error) => void
  timer: NodeJS.Timeout
}

/**
 * 连续启动失败的最大重试次数（issue #6）：指数退避到 maxRetryDelayMs 后
 * 若无上限，python 环境损坏时会以 30s 间隔永久空转（假激活 + 资源浪费）。
 * 达到上限即进入 failed 终态并停止调度；后续所有请求快速失败并给出
 * 明确的修复指引。握手成功后计数归零——运行期偶发崩溃重启不受影响。
 */
const MAX_RETRIES = 8

export class LingshuBridge {
  private readonly options: BridgeOptions
  private proc: ChildProcess | null = null
  private rl: ReturnType<typeof createInterface> | null = null
  private nextId = 1
  private pending = new Map<number, PendingCall>()
  private started = false
  private disposed = false
  private retryDelayMs = 1000
  private retries = 0
  private retryTimer: NodeJS.Timeout | null = null
  private bootQueue: Array<(ok: boolean) => void> = []
  private readyState: 'pending' | 'ok' | 'failed' = 'pending'
  /** issue #7：当前子进程启动时间（计算 uptime，区分秒退与长存后外部关闭） */
  private procStartedAt = 0
  /** issue #7：运行期反复退出的滑动窗口（时间戳列表）——防无限重启刷屏 */
  private unexpectedExits: number[] = []

  constructor(options: BridgeOptions) {
    this.options = options
  }

  /**
   * 启动灵枢进程并完成握手（initialize → notifications/initialized）。
   * 进程崩溃后自动指数退避重启，并重新握手。
   */
  start(): void {
    if (this.started || this.disposed) return
    this.started = true
    this.spawnAndHandshake()
  }

  /** 拉取灵枢的全部工具清单（每次实时请求，不缓存）。 */
  async listTools(): Promise<McpTool[]> {
    const result = await this.request('tools/list', {})
    const tools = result as { tools?: McpTool[] }
    return tools.tools ?? []
  }

  /** 调用灵枢的一个工具，返回标准化 MCP 结果。 */
  async callTool(name: string, args: Record<string, unknown>,
                 signal?: AbortSignal): Promise<McpCallResult> {
    const result = await this.request('tools/call', { name, arguments: args }, signal)
    return result as McpCallResult
  }

  /** 关闭进程并释放资源（写 stdin EOF 优雅退出，超时兜底 kill）。 */
  dispose(): void {
    this.disposed = true
    if (this.retryTimer) clearTimeout(this.retryTimer)
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    try {
      proc.stdin?.end()
    } catch {
      /* 已关闭则忽略 */
    }
    const killer = setTimeout(() => proc.kill(), 2000)
    killer.unref()
  }

  /** 进程是否存活。 */
  get alive(): boolean {
    return this.proc !== null && this.proc.exitCode === null
  }

  /** 桥是否已握手就绪（工具注册用；防止轮询访问 private readyState）。 */
  isReady(): boolean {
    return this.readyState === 'ok'
  }

  /** 是否已达放弃终态（连续启动失败超上限，不再自动重启）。 */
  get gaveUp(): boolean {
    return this.retries >= MAX_RETRIES
  }

  /** 等待握手完成（用于 apply 阶段同步就绪）。 */
  waitReady(): Promise<boolean> {
    if (this.readyState === 'ok') return Promise.resolve(true)
    if (this.readyState === 'failed') return Promise.resolve(false)
    return new Promise((resolve) => this.bootQueue.push(resolve))
  }

  /**
   * V23 修复（缺陷 :284）：清理上一个仍存活的子进程。
   * 握手超时/启动失败重试时直接 spawn 新进程并覆盖 this.proc（:182），
   * 旧进程若仍存活（卡死但不退出的服务端）既不 kill 也不关 stdin——
   * 引用被覆盖后永远无人清理 = 僵尸进程泄漏（最多 MAX_RETRIES 个并存，
   * dispose 也只收尾最后一个）。换代前统一回收：stdin EOF 优雅退出 + kill 兜底。
   * 幂等：已退出（exitCode/signalCode 非 null）的进程跳过。
   */
  private killStaleProc(): void {
    const old = this.proc
    this.proc = null                    // 先摘引用：旧进程随后的 exit 事件走 stale 早退分支
    if (!old || old.exitCode !== null || old.signalCode !== null) return
    try {
      old.stdin?.end()
    } catch {
      /* 已关闭则忽略 */
    }
    try {
      old.kill()
    } catch {
      /* 已退出则忽略 */
    }
  }

  private spawnAndHandshake(): void {
    if (this.disposed) return
    // V23：重试路径先回收上一个仍存活的子进程（防换代泄漏僵尸进程）
    this.killStaleProc()
    this.procStartedAt = Date.now()
    const { python, args, env, cwd } = this.options
    const childEnv = { ...process.env, ...env }
    // 确保 DB 目录存在（灵枢 server 也会防御性创建，这里提前为可读错误）
    const dbPath = env['AEIS_DB']
    if (dbPath && dbPath !== ':memory:') {
      try {
        mkdirSync(dirname(dbPath), { recursive: true })
      } catch {
        /* 目录创建失败由灵枢侧兜底 */
      }
    }
    const proc = spawn(python, args, {
      env: childEnv,
      cwd,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    })
    this.proc = proc
    this.rl = createInterface({ input: proc.stdout!, crlfDelay: Infinity })

    proc.stderr?.on('data', (chunk: Buffer) => {
      // stderr 透传日志（灵枢把日志写在 stderr，避免污染协议流）
      const text = chunk.toString('utf8').trim()
      if (text) console.error(`[lingshu-bridge] ${text}`)
    })

    this.rl.on('line', (line: string) => {
      if (!line.trim()) return
      let msg: Record<string, unknown>
      try {
        msg = JSON.parse(line)
      } catch {
        console.error(`[lingshu-bridge] 非 JSON 输出: ${line.slice(0, 200)}`)
        return
      }
      if (typeof msg['id'] === 'number') {
        this.settle(msg['id'] as number, msg)
      }
    })

    proc.on('error', (err) => {
      // 进程无法启动（python 不存在等）——响亮失败
      if (!this.disposed) {
        console.error(`[lingshu-bridge] 灵枢进程启动失败: ${err.message}`)
        // issue #19：ENOENT 的第一因通常不是「环境损坏」，而是解释器名与平台不匹配
        // （Linux/macOS 按 PEP 394 只有 python3）。把成因与修法写进同一条日志——
        // 原始日志把该缺陷伪装成「调用超时」，用户按超时方向排查只会白耗一轮。
        if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
          console.error(`[lingshu-bridge] ${explainMissingPython(python)}`)
        }
        probe(`spawn error: ${String(err)}`)
        this.readyState = 'failed'
        this.flushBootQueue(false)
        this.scheduleRetry()
      }
    })

    proc.on('exit', (code, signal) => {
      // V23：被换代清理的旧进程退出（this.proc 已指向新一代或为 null）——
      // 不动当前进程的 rl/pending/重试状态机，只留探针；否则旧 exit 会
      // close 新进程的 readline、误拒新进程的挂起请求并多触发一轮重试。
      if (proc !== this.proc) {
        probe(`stale proc exit code=${code} signal=${signal}（换代已回收，不影响当前进程）`)
        return
      }
      // 探针：写独立文件记录退出（绕过 DSH 日志系统，便于定位）
      const uptimeS = this.procStartedAt
        ? Math.round((Date.now() - this.procStartedAt) / 1000)
        : -1
      probe(`exit code=${code} signal=${signal} disposed=${this.disposed} ready=${this.readyState} started=${this.started} uptime=${uptimeS}s`)
      console.error(`[lingshu-bridge] 灵枢进程退出 code=${code} signal=${signal}（存活 ${uptimeS}s）`)
      this.rl?.close()
      this.rl = null
      this.rejectAll(new Error(`灵枢进程已退出（code=${code} signal=${signal ?? 'none'}）`))
      if (!this.disposed) {
        // issue #7：长存后 code=0 退出 = stdin 被外部关闭（非崩溃）。
        // 记录滑动窗口（10 分钟内 ≥3 次）→ 进入冷却，防「外部反复关闭 +
        // 无限重启」刷屏；冷却结束自动恢复，不进入放弃终态。
        this.unexpectedExits = this.unexpectedExits.filter(
          (t) => Date.now() - t < 600_000,
        )
        this.unexpectedExits.push(Date.now())
        if (uptimeS >= 0 && uptimeS < 5) {
          console.error(
            `[lingshu-bridge] 进程启动后 5 秒内即退出——请检查 ${python} 可执行文件与 md_cg 依赖。` +
            `自检 \`${selfCheckCommand(python)}\` 须在插件包根目录运行` +
            '（插件已自动锚定 cwd 与 PYTHONPATH，issue #12）。')
        } else if (this.unexpectedExits.length >= 3) {
          console.error(
            `[lingshu-bridge] 10 分钟内已意外退出 ${this.unexpectedExits.length} 次，` +
            '冷却 5 分钟后自动恢复。若持续出现，请检查是否有多个插件/脚本'
            + '同时管理灵枢进程（重复 spawn 会互相关闭对方子进程的 stdin）。')
          probe(`cooldown: ${this.unexpectedExits.length} unexpected exits in 10min`)
          this.retryTimer = setTimeout(() => {
            this.retryTimer = null
            this.unexpectedExits = []
            if (!this.disposed) this.spawnAndHandshake()
          }, 300_000)
          this.retryTimer.unref()
          return
        }
        // 有挂起请求的失败是异常的；仅启动失败的等待者得到 false
        this.readyState = 'failed'
        this.flushBootQueue(false)
        this.scheduleRetry()
      }
    })

    void this.handshake()
  }

  private async handshake(): Promise<void> {
    try {
      await this.request('initialize', {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: { name: 'dsh-memory', version: '0.1.0' },
      })
      // 初始化通知：无 id、无响应
      this.writeRaw({ jsonrpc: '2.0', method: 'notifications/initialized' })
      // 握手成功：重置退避与失败计数（issue #6）——运行期偶发崩溃重启
      // 不累积启动失败；只有「从未握手成功的连续失败」才走向放弃终态
      this.retryDelayMs = 1000
      this.retries = 0
      this.readyState = 'ok'
      this.flushBootQueue(true)
    } catch (err) {
      if (!this.disposed) {
        console.error(`[lingshu-bridge] 握手失败: ${(err as Error).message}`)
        probe(`handshake failed: ${String(err)}`)
        this.readyState = 'failed'
        this.flushBootQueue(false)
        this.scheduleRetry()
      }
    }
  }

  private scheduleRetry(): void {
    if (this.disposed || this.retryTimer || this.gaveUp) return
    this.retries += 1
    if (this.gaveUp) {
      // issue #6：放弃机制——明确终态，停止后台空转；请求方收到清晰错误而非超时
      this.readyState = 'failed'
      this.flushBootQueue(false)
      console.error(
        `[lingshu-bridge] 连续启动失败 ${this.retries} 次，已停止自动重启（不再后台空转）。` +
        `请检查 ${this.options.python} 可执行文件与 md_cg 依赖；` +
        `自检 \`${selfCheckCommand(this.options.python)}\` 须在插件包根目录运行` +
        '（插件已自动锚定 cwd 与 PYTHONPATH，issue #12），修复后在 DSH 中重新启用 dsh-memory 插件。')
      probe(`give up: ${this.retries} consecutive failures, entering failed terminal state`)
      return
    }
    const delay = this.retryDelayMs
    this.retryDelayMs = Math.min(this.retryDelayMs * 2, this.options.maxRetryDelayMs)
    console.error(`[lingshu-bridge] 将进行第 ${this.retries}/${MAX_RETRIES} 次重试（${delay}ms 后）`)
    probe(`schedule retry ${this.retries}/${MAX_RETRIES} in ${delay}ms`)
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      if (!this.disposed) this.spawnAndHandshake()
    }, delay)
    this.retryTimer.unref()
  }

  private writeRaw(msg: Record<string, unknown>): void {
    const proc = this.proc
    if (!proc || !proc.stdin?.writable) {
      throw new Error('灵枢进程不可写')
    }
    proc.stdin.write(JSON.stringify(msg) + '\n')
  }

  private request(method: string, params: Record<string, unknown>,
                  signal?: AbortSignal): Promise<unknown> {
    // issue #6：放弃终态下快速失败——之前进程不在且不再重启，请求只能白等超时
    if (this.gaveUp) {
      return Promise.reject(new Error(
        '灵枢进程不可用：连续启动失败已达上限，已停止重试。' +
        `请检查 ${this.options.python} 可执行文件与 md_cg 依赖` +
        `（自检 \`${selfCheckCommand(this.options.python)}\` 须在插件包根目录运行），` +
        '修复后重新启用 dsh-memory 插件。'))
    }
    const id = this.nextId++
    const timeout = this.options.timeoutMs
    // P0 修复（GPT 审查）：定时器直接调 settle——settle 内部会 delete + clearTimeout
    // 并 reject。此前先 pending.delete(id) 再 settle()，settle 找不到 entry 直接
    // return，Promise 永不 resolve/reject（超时逻辑完全失效，子进程挂死时插件永久挂住）。
    const timer = setTimeout(() => {
      this.settle(id, {
        error: { code: -32000, message: `灵枢调用超时（${timeout}ms）：${method}` },
      })
    }, timeout)
    if (signal?.aborted) {
      clearTimeout(timer)
      return Promise.reject(new Error(`已取消：${method}`))
    }
    const onAbort = (): void => {
      this.settle(id, { error: { code: -32800, message: `已取消：${method}` } })
    }
    signal?.addEventListener('abort', onAbort, { once: true })
    const promise = new Promise<unknown>((resolve, reject) => {
      this.pending.set(id, { resolve, reject, timer })
    })
    // settle 后移除 abort 监听，避免内存积累
    promise.finally(() => {
      signal?.removeEventListener('abort', onAbort)
    }).catch(() => { /* finally 链的 catch 防未处理拒绝 */ })
    try {
      this.writeRaw({ jsonrpc: '2.0', id, method, params })
    } catch (err) {
      clearTimeout(timer)
      this.pending.delete(id)
      signal?.removeEventListener('abort', onAbort)
      return Promise.reject(err)
    }
    return promise
  }

  private settle(id: number, msg: Record<string, unknown>): void {
    const entry = this.pending.get(id)
    if (!entry) return
    this.pending.delete(id)
    clearTimeout(entry.timer)
    if (msg['error']) {
      const err = msg['error'] as { message?: string; code?: number }
      entry.reject(new Error(`灵枢错误 ${err.code ?? ''}: ${err.message ?? 'unknown'}`))
    } else {
      entry.resolve(msg['result'])
    }
  }

  private rejectAll(reason: Error): void {
    for (const [, entry] of this.pending) {
      clearTimeout(entry.timer)
      entry.reject(reason)
    }
    this.pending.clear()
  }

  private flushBootQueue(ok: boolean): void {
    const queue = this.bootQueue
    this.bootQueue = []
    for (const cb of queue) cb(ok)
  }
}
