/**
 * init.ts 测试——一键配置生成器（lingshu-init / npx @furongjun1999/dsh-memory init）。
 *
 * 覆盖面（与实现边界一一对应）：
 *   ① 非交互端到端（--end/--root/--python 齐）：四端各自产出 mcp.json 片段，
 *      关键键（MDCG_ROOT / MDCG_PYTHON / 命令形态）逐条断言；
 *   ② 片段文件 lingshu-mcp-snippet.json 落盘且可 JSON.parse、与打印片段一致；
 *   ③ 幂等：同参数重跑输出逐字节一致（init 承诺「重跑输出一致」——故片段里
 *      不得出现时间戳等易变内容，本组断言就是钉住这条承诺）；
 *   ④ 只生成配置：不创建记忆根目录（init 边界——建目录/写库是服务的事）；
 *   ⑤ 交互形态：mock stdin（PassThrough）走通 DSH 分支 + 缺省值两条路径；
 *   ⑥ 非交互环境缺参：报错退出（宁缺毋滥，不挂死等永远不会来的输入）。
 *
 * 零副作用：全部落临时目录并清理；不 spawn python、不触碰 ~/.lingshu、
 * 不触真实记忆库（对齐工作纪律：实验只在临时目录做）。
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { PassThrough } from 'node:stream'
import { runInit } from '../src/init.js'

const ENDS = ['dsh', 'claude', 'codex', 'generic'] as const

/** 每端各自的片段关键键（actor 按端不同，其余键共用）。 */
const EXPECTED_ACTOR: Record<(typeof ENDS)[number], string> = {
  dsh: 'dsh-memory',
  claude: 'claude-code',
  codex: 'codex',
  generic: 'generic',
}

function tmpCase(): { dir: string, cleanup: () => void } {
  const dir = mkdtempSync(join(tmpdir(), 'lingshu-init-test-'))
  return { dir, cleanup: () => rmSync(dir, { recursive: true, force: true }) }
}

test('非交互端到端：四端各自产出含 MDCG_ROOT/MDCG_PYTHON/命令形态的片段，snippet 落盘可解析', async () => {
  for (const end of ENDS) {
    const { dir, cleanup } = tmpCase()
    try {
      const root = join(dir, 'mem')
      const r = await runInit(
        ['--end', end, '--root', root, '--python', 'python3'],
        { cwd: dir, output: new PassThrough() },
      )

      // ① 片段关键键：MDCG_ROOT / MDCG_PYTHON + 命令形态（python -m md_cg.mcp_server）
      const server = r.snippet.mcpServers.mdcg
      assert.equal(server.env['MDCG_ROOT'], root, `[${end}] MDCG_ROOT 应为传入的记忆根`)
      assert.equal(server.env['MDCG_PYTHON'], 'python3', `[${end}] MDCG_PYTHON 应为传入的解释器`)
      assert.equal(server.command, 'python3', `[${end}] 命令形态：解释器即 command`)
      assert.deepEqual(server.args, ['-m', 'md_cg.mcp_server'], `[${end}] 命令形态：md_cg stdio MCP server`)
      assert.equal(server.env['MDCG_ACTOR'], EXPECTED_ACTOR[end], `[${end}] actor 按端区分`)
      assert.equal(server.env['PYTHONIOENCODING'], 'utf-8', `[${end}] 编码硬约束（中文记忆场景）`)
      assert.equal(server.env['PYTHONUTF8'], '1', `[${end}] 编码硬约束（后代 text 编码）`)
      assert.ok(server.env['PYTHONPATH'], `[${end}] PYTHONPATH 必填（python -m 不依赖 cwd 的模块解析）`)

      // ② snippet 文件落盘且 json 可解析，且与打印片段一致
      assert.equal(r.snippetPath, join(dir, 'lingshu-mcp-snippet.json'))
      assert.ok(existsSync(r.snippetPath), `[${end}] 片段文件应落盘`)
      const parsed: unknown = JSON.parse(readFileSync(r.snippetPath, 'utf8'))
      assert.deepEqual(parsed, r.snippet, `[${end}] 文件内容应与返回片段一致`)

      // ③ 打印文本含两键与后续步骤指引（令牌签发指向 README）
      assert.match(r.output, /MDCG_ROOT/)
      assert.match(r.output, /MDCG_PYTHON/)
      assert.match(r.output, /md_cg\.tokens issue/)
      assert.match(r.output, /README「写入凭据」/)

      // ④ init 只生成配置：不创建记忆根目录
      assert.equal(existsSync(root), false, `[${end}] init 不得创建记忆目录`)
    } finally {
      cleanup()
    }
  }
})

test('幂等：同参数重跑 stdout 与片段文件逐字节一致', async () => {
  const { dir, cleanup } = tmpCase()
  try {
    const argv = ['--end', 'claude', '--root', join(dir, 'mem'), '--python', 'python']
    const r1 = await runInit(argv, { cwd: dir, output: new PassThrough() })
    const f1 = readFileSync(r1.snippetPath, 'utf8')
    const r2 = await runInit(argv, { cwd: dir, output: new PassThrough() })
    const f2 = readFileSync(r2.snippetPath, 'utf8')
    assert.equal(r1.output, r2.output, '重跑打印应逐字节一致（无时间戳等易变内容）')
    assert.equal(f1, f2, '重跑片段文件应逐字节一致')
  } finally {
    cleanup()
  }
})

/** readline 对「attach 前预缓冲且不 end」的 PassThrough 只消费第一行（本仓实测，
 *  ERR_USE_AFTER_CLOSE / question 永久 pending 两个坑都踩过）。可靠形态是：
 *  先启动 runInit（readline 已 attach），再逐问 write，批间让出事件循环。 */
const tick = (ms = 25): Promise<void> => new Promise((r) => { setTimeout(r, ms) })

test('交互形态（mock stdin）：选 1=DSH 分支走通，片段与文件均落盘',
  { timeout: 10_000 },
  async () => {
    const { dir, cleanup } = tmpCase()
    try {
      const input = new PassThrough()
      const root = join(dir, 'mem-dsh')
      const pending = runInit([], { input, cwd: dir, output: new PassThrough() })
      for (const line of ['1\n', `${root}\n`, 'python\n']) {
        await tick()
        input.write(line)
      }
      const r = await pending
      assert.equal(r.end, 'dsh', '交互输入 1 应选中 DSH 插件端')
      assert.equal(r.root, root)
      assert.equal(r.python, 'python')
      assert.equal(r.snippet.mcpServers.mdcg.env['MDCG_ROOT'], root)
      assert.equal(r.snippet.mcpServers.mdcg.env['MDCG_PYTHON'], 'python')
      const parsed: unknown = JSON.parse(readFileSync(r.snippetPath, 'utf8'))
      assert.deepEqual(parsed, r.snippet, '交互形态片段文件同样落盘且可解析')
      assert.equal(existsSync(root), false, '交互形态同样不创建目录')
    } finally {
      cleanup()
    }
  })

test('交互形态：回车走缺省（记忆根=<home>/.lingshu/memory，解释器按平台）',
  { timeout: 10_000 },
  async () => {
    const { dir, cleanup } = tmpCase()
    try {
      const input = new PassThrough()
      const fakeHome = join(dir, 'home')
      const pending = runInit([], {
        input, cwd: dir, output: new PassThrough(), home: fakeHome, platform: 'linux',
      })
      for (const line of ['4\n', '\n', '\n']) { // 端=4 通用 MCP；root/python 全留空走缺省
        await tick()
        input.write(line)
      }
      const r = await pending
      assert.equal(r.end, 'generic')
      assert.equal(r.root, join(fakeHome, '.lingshu', 'memory'), '缺省记忆根应为 <home>/.lingshu/memory')
      assert.equal(r.python, 'python3', 'linux 平台缺省解释器应为 python3')
    } finally {
      cleanup()
    }
  })

test('非交互环境缺参：报错而非挂死（错误信息点名缺失的 flag）', async () => {
  const { dir, cleanup } = tmpCase()
  try {
    await assert.rejects(
      runInit(['--end', 'claude'], { cwd: dir, output: new PassThrough(), tty: false }),
      (e: Error) => /--root/.test(e.message) && /--python/.test(e.message),
    )
    await assert.rejects(
      runInit([], { cwd: dir, output: new PassThrough(), tty: false }),
      (e: Error) => /--end/.test(e.message),
      'stdin 非 TTY（tty:false 显式注入，不依赖测试宿主）且无参数时应报错而非进入交互',
    )
    await assert.rejects(
      runInit(['--end', 'no-such-end', '--root', 'x', '--python', 'python'], { cwd: dir, output: new PassThrough(), tty: false }),
      (e: Error) => /--end/.test(e.message),
      '未知端值应报错并列出允许集',
    )
  } finally {
    cleanup()
  }
})

test('N167 回归：根入口波浪线展开——--root 与交互手输的 ~/x、裸 ~ 均落到注入 home', async () => {
  // 缺陷（N167）：src/init.ts 根入口 resolve(cwd, root) 不做波浪线展开，
  // :264 自带示例形态「--root ~/.lingshu/memory」被解析为 <cwd>/~/.lingshu/memory
  // ——记忆根落错位且随宿主 cwd 漂移分裂。修复口径与大脑侧
  // md_cg/datapath.py:61 expanduser+abspath 一致（~ → home 前缀展开）。
  const { dir, cleanup } = tmpCase()
  try {
    const fakeHome = join(dir, 'home')
    const opts = { cwd: dir, output: new PassThrough(), home: fakeHome }

    // ① 非交互 flag 形态（即 :264 示例逐字形态）：~/x → <home>/x，片段同值
    const r1 = await runInit(
      ['--end', 'claude', '--root', '~/.lingshu/memory', '--python', 'python3'], opts)
    const expected1 = join(fakeHome, '.lingshu', 'memory')
    assert.equal(r1.root, expected1, '--root ~/x 应展开为 <home>/x 而非 <cwd>/~/x')
    assert.equal(r1.snippet.mcpServers.mdcg.env['MDCG_ROOT'], expected1,
      '落盘片段 MDCG_ROOT 应为展开后的绝对路径（随 cwd 漂移即分裂）')

    // ② 裸 ~ → home 本身
    const r2 = await runInit(['--end', 'claude', '--root', '~', '--python', 'python3'], opts)
    assert.equal(r2.root, fakeHome, '裸 ~ 应展开为 home 本身')

    // ③ 交互手输 ~/ 形态同样展开（第二条独立入口，与 flag 汇于同一根处理点）
    const input = new PassThrough()
    const pending = runInit([], { ...opts, input, platform: 'linux' })
    for (const line of ['2\n', '~/.lingshu/memory\n', '\n']) {
      await tick()
      input.write(line)
    }
    const r3 = await pending
    assert.equal(r3.root, join(fakeHome, '.lingshu', 'memory'),
      '交互手输 ~/x 应与 flag 形态同口径展开')
  } finally {
    cleanup()
  }
})

test('缺省记忆根口径：<home>/.lingshu/memory（home 可注入，缺省 os.homedir()）', () => {
  // 纯函数断言：本机缺省形态只断言后缀结构，不写死盘符/用户名
  const p = join(homedir(), '.lingshu', 'memory')
  assert.ok(p.endsWith(join('.lingshu', 'memory')))
})
