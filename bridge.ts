/**
 * 灵枢 MCP stdio 桥：管理灵枢（AEIS）Python 子进程的生命周期，
 * 通过逐行 JSON-RPC 完成握手、工具发现与调用。
 *
 * 与官方 @deepseek-ai/dsh-mcp-client 不同，本桥零运行时依赖（不引入
 * @modelcontextprotocol/sdk），直接实现灵枢 server 使用的 2024-11-05 协议
 * 子集——与灵枢库 D-005「核心零外部依赖」的工程哲学一致。
 */

import { spawn, type ChildProcess } from 'node:child_process'
import { createInterface } from 'node:readline'
import { mkdirSync } from 'node:fs'
import { dirname } from 'node:path'

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
  /** Python 可执行文件（或 aeis-mcp console script），默认 python。 */
  python: string
  /** 传给 python 的参数，默认 ['-m', 'aeis.mcp.server']。 */
  args: string[]
  /** 追加到子进程的环境变量（AEIS_DB / AEIS_IDENTITY / 密钥等）。 */
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

export class LingshuBridge {
  private readonly options: BridgeOptions
  private proc: ChildProcess | null = null
  private rl: ReturnType<typeof createInterface> | null = null
  private nextId = 1
  private pending = new Map<number, PendingCall>()
  private started = false
  private disposed = false
  private retryDelayMs = 1000
  private retryTimer: NodeJS.Timeout | null = null
  private bootQueue: Array<(ok: boolean) => void> = []
  private readyState: 'pending' | 'ok' | 'failed' = 'pending'

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
  async callTool(name: string, args: Record<string, unknown>): Promise<McpCallResult> {
    const result = await this.request('tools/call', { name, arguments: args })
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

  /** 等待握手完成（用于 apply 阶段同步就绪）。 */
  waitReady(): Promise<boolean> {
    if (this.readyState === 'ok') return Promise.resolve(true)
    if (this.readyState === 'failed') return Promise.resolve(false)
    return new Promise((resolve) => this.bootQueue.push(resolve))
  }

  private spawnAndHandshake(): void {
    if (this.disposed) return
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
        this.readyState = 'failed'
        this.flushBootQueue(false)
        this.scheduleRetry()
      }
    })

    proc.on('exit', (code, signal) => {
      console.error(`[lingshu-bridge] 灵枢进程退出 code=${code} signal=${signal}`)
      this.rl?.close()
      this.rl = null
      this.rejectAll(new Error(`灵枢进程已退出（code=${code} signal=${signal ?? 'none'}）`))
      if (!this.disposed) {
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
      this.retryDelayMs = 1000
      this.readyState = 'ok'
      this.flushBootQueue(true)
    } catch (err) {
      if (!this.disposed) {
        console.error(`[lingshu-bridge] 握手失败: ${(err as Error).message}`)
        this.readyState = 'failed'
        this.flushBootQueue(false)
        this.scheduleRetry()
      }
    }
  }

  private scheduleRetry(): void {
    if (this.disposed || this.retryTimer) return
    const delay = this.retryDelayMs
    this.retryDelayMs = Math.min(this.retryDelayMs * 2, this.options.maxRetryDelayMs)
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

  private request(method: string, params: Record<string, unknown>): Promise<unknown> {
    const id = this.nextId++
    const timeout = this.options.timeoutMs
    const timer = setTimeout(() => {
      this.pending.delete(id)
      this.settle(id, {
        error: { code: -32000, message: `灵枢调用超时（${timeout}ms）：${method}` },
      })
    }, timeout)
    const promise = new Promise<unknown>((resolve, reject) => {
      this.pending.set(id, { resolve, reject, timer })
    })
    try {
      this.writeRaw({ jsonrpc: '2.0', id, method, params })
    } catch (err) {
      clearTimeout(timer)
      this.pending.delete(id)
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
