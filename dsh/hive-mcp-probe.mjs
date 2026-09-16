#!/usr/bin/env node
/**
 * hive-mcp-probe.mjs —— 用 DSH 自带的 @modelcontextprotocol/sdk 直接连一次蜂巢 MCP server。
 *
 * 目的：在不动 DSH 进程的前提下，验证「DSH 的 mcp-client 会看到什么」。
 *   - 用与 dsh-mcp-client 同一个 SDK（版本一致）走 stdio 握手
 *   - tools/list → 工具名与入参 schema
 *   - tools/call hive_doctor → serve 存活与任务统计
 *   - （可选）tools/call hive_spawn → 真提交一个任务，证明写路径通
 *
 * 用法：node dsh/hive-mcp-probe.mjs [--spawn]
 * 依赖环境变量（可覆盖）：DSH_ROOT、HIVE_REPO、HIVE_LIB、MDCG_ROOT
 *   DSH_ROOT  = DSH 安装目录（其下含 node_modules/@modelcontextprotocol/sdk）
 *   HIVE_REPO = dsh-memory 仓绝对路径
 *   HIVE_LIB  = 认知图库仓绝对路径（追加进 PYTHONPATH）
 *   MDCG_ROOT = 认知图根
 * 四个值未设置且脚本内仍为占位符时直接报错退出——本仓是公开仓，不硬编码本机路径。
 */
const DSH_ROOT = (process.env.DSH_ROOT || '<REPLACE_WITH_DSH_INSTALL_DIR>').replace(/\\/g, '/')
const REPO = process.env.HIVE_REPO || '<REPLACE_WITH_ABSOLUTE_PATH_TO_dsh-memory>'
const LIB = process.env.HIVE_LIB || '<REPLACE_WITH_ABSOLUTE_PATH_TO_mdcg_lib>'
const MDCG_ROOT = process.env.MDCG_ROOT || '<REPLACE_WITH_ABSOLUTE_PATH_TO_MDCG_ROOT>'

const PH = { DSH_ROOT, HIVE_REPO: REPO, HIVE_LIB: LIB, MDCG_ROOT }
const missing = Object.entries(PH).filter(([, v]) => v.includes('REPLACE_WITH'))
if (missing.length) {
  console.error('[ABORT] 以下参数仍是占位符，请用同名环境变量覆盖后重跑：' + missing.map(([k]) => k).join(', '))
  process.exit(1)
}

const SDK = 'file:///' + DSH_ROOT + '/node_modules/@modelcontextprotocol/sdk/dist/esm'
const { Client } = await import(SDK + '/client/index.js')
const { StdioClientTransport } = await import(SDK + '/client/stdio.js')

const doSpawn = process.argv.includes('--spawn')

const transport = new StdioClientTransport({
  command: 'python',
  args: ['-m', 'hive.hive_mcp.mcp_server'],
  cwd: REPO,
  env: {
    ...process.env,
    PYTHONPATH: REPO + ';' + LIB,
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    MDCG_ROOT,
  },
})

const client = new Client({ name: 'dsh-hive-probe', version: '1.0.0' })
await client.connect(transport)
console.log('[OK] MCP 握手成功（stdio）')
console.log('serverInfo =', JSON.stringify(client.getServerVersion?.() ?? {}))

const listed = await client.listTools()
console.log('[OK] tools/list 返回 ' + listed.tools.length + ' 个工具：')
for (const t of listed.tools) {
  console.log('  - ' + t.name + '  参数：' + Object.keys(t.inputSchema?.properties ?? {}).join(', '))
}

const doc = await client.callTool({ name: 'hive_doctor', arguments: {} })
const docText = (doc.content ?? []).map((c) => c.text ?? '').join('')
console.log('[OK] hive_doctor →')
console.log('  ' + docText.slice(0, 900).replace(/\n/g, '\n  '))

if (doSpawn) {
  const tag = 'HIVE_MCP_OK_' + Date.now()
  const sp = await client.callTool({ name: 'hive_spawn', arguments: {
    model: 'deepseek-flash',
    user_prompt: 'Reply with exactly this token and nothing else: ' + tag,
    max_tokens: 2000,
  } })
  const spText = (sp.content ?? []).map((c) => c.text ?? '').join('')
  console.log('[OK] hive_spawn → ' + spText.slice(0, 400))
  const jobId = (spText.match(/h\d+_[0-9a-f]+/) || [])[0]
  if (jobId) {
    let last = ''
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 3000))
      const pl = await client.callTool({ name: 'hive_poll', arguments: { job_id: jobId } })
      const txt = (pl.content ?? []).map((c) => c.text ?? '').join('')
      const st = (txt.match(/"state"\s*:\s*"([a-z]+)"/) || [])[1]
      if (st !== last) { console.log('  poll ' + jobId + ' state=' + st); last = st }
      if (['done', 'error', 'timeout', 'killed'].includes(st)) {
        console.log('[RESULT] ' + txt.slice(0, 1200))
        console.log('[CHECK] 令牌往返 ' + (txt.includes(tag) ? '通过（content 含 ' + tag + '）' : '未在片段中看到令牌，读全文确认'))
        break
      }
    }
  }
}

await client.close()
console.log('[DONE] 探针结束')
