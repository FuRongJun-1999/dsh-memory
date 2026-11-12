> **Languages:** [中文](../../ops/安装与前置.md) · English

# Install and prerequisites

> This page was split from the original `README.md` (source: the "⚡ Quick start" section of the original README (L50–L116)).


## One-command setup (recommended)

### One-command setup (recommended)

```bash
npx @furongjun1999/dsh-memory init
```

After three interactive questions (**① entry point** 1=DSH plugin / 2=Claude Code / 3=Codex CLI / 4=generic MCP · **② memory root directory** (default `~/.lingshu/memory`) · **③ Python interpreter** (default `python`/`python3` depending on platform)), it produces:

1. The **mcp.json config snippet** for the chosen entry point (with `MDCG_ROOT` / `MDCG_PYTHON` / the `command + args` command form, printed to the terminal);
2. The snippet file **`lingshu-mcp-snippet.json`** (written to the current directory; copy the `mcpServers` key straight into the host configuration);
3. **Next-step guidance**: where the snippet belongs (differs per host: cordis.yml / `.mcp.json` / `~/.codex/config.toml`), the [token issuance command](operations-troubleshooting.md#-write-credentials-make-memory-actually-persist) (requires a Python environment + this package's `md_cg`), discipline injection, and a brain self-check.

No appetite for questions? With all parameters supplied, run non-interactively (arguments after `--` go straight to the command):

```bash
npx @furongjun1999/dsh-memory init -- --end claude --root /path/to/memory --python python3
```

> init **only generates configuration** — it does not create directories, start a service, or write to the store; reruns produce identical output (idempotent). Global command forms: `lingshu init` / `lingshu-init`. **Or continue with the manual steps below.**

## Choosing an entry point per host

> **Choose an entry point per host**: **DSH** -> the three steps below | **CodeBuddy · ZCode · Codex CLI · Claude Code** -> [Multi-harness integration](../mdcg/multi-harness.md#multi-harness-integration-directories-per-endpoint) (independent three-step instructions per host) | **Other MCP hosts** -> mount the brain directly with `python -m md_cg.mcp_server` (Windows) / `python3 -m md_cg.mcp_server` (Linux·macOS) (stdio MCP), then inject Engineering Discipline as needed

## Manual three steps (DSH plugin form)

```bash
# ① 克隆并构建插件本体
git clone https://github.com/FuRongJun-1999/dsh-memory.git
cd dsh-memory
npm install && npm run build          # tsc → lib/

# ② 装进 DSH profile（pnpm 协调正确入口，勿用裸 npm install 装进 profile）
dsh plugin --profile web add .

# ③ 在 <profile>/cordis.yml 启用（配置示例见 dsh/cordis.yml.example）
```

```yaml
- id: furongjun1999-dsh-memory
  name: '@furongjun1999/dsh-memory'
  config:
    mdcg:
      # 记忆唯一真源（md 认知图）。留空 = 用户级默认位置
      # ~/.dsh/.dsh-memory/data/mdcg（更新插件不丢）；换位置请填**绝对路径**。
      # 勿填包内相对路径（如 'data/mdcg'）——那会把记忆写进插件包目录，
      # pnpm 更新该包时连目录一起删掉（详见 dsh/cordis.yml.example 头注）。
      root: ''
    identity: '灵枢'
    tools: 'core'            # 'core'(默认, 仅 cg/stg) | 'brain' | 'all'
```

## Prerequisites, verified environments, and troubleshooting leads

- **Prerequisites**: Node ≥ 22.19 · DSH kernel ≥ 0.1.2-rc.1 · **verified up to DSH 0.17.2** · **the DSH 2.0 (`0.2.0-rc.2`) interface surface has been rechecked against the installed package, and real session event surfaces have been observed** (real occurrences of `origin='subagent'` / `delegationDepth>0` / `form='relay'` have still not been observed; see the [detailed version](../../mdcg/README详细版_v0.4.10.md)) · **zero-install brain** (`md_cg` ships with the package; no engine to pip install) · **a Python interpreter** (the plugin picks one per platform: Windows `python` / Linux·macOS `python3`; override with `MDCG_PYTHON` when the interpreter name is unusual)
- **Python versions (verified)**: **3.12.10 / 3.13.14 / 3.14.7 (Windows) pass this repository's own runs** · **no third-party runtime dependencies** (pure standard library, zero pip dependencies)
- **Full-suite prerequisites (six groups)**: the Rust toolchain plus `cd rust && cargo build --release` (evaluator cross-check surface) and `cd hive && cargo build --release` (Hive serve/routing surface); the suite discovers six groups by existence (`md_cg` / `compiler` / `swarm` / `scripts` / `hive` / `test`), **the target count changes with the checked-out content**; check it yourself with `python scripts/run_tests.py --list` (local run on 2026-10-05: 357 total)
- **Write permission is off by default**: without credentials it runs as a read-only `guest` (read / recall / timeline work; writes do not persist). To actually persist, see "Write credentials"
- Full configuration options (30+) · automatic memory mechanism · DSH watchdog -> [detailed README version](../../mdcg/README详细版_v0.4.10.md)
- **Non-DSH hosts** (CodeBuddy / ZCode / Codex CLI / Claude Code): use [Multi-harness integration](../mdcg/multi-harness.md#multi-harness-integration-directories-per-endpoint); each host has its own three-step integration instructions
- **Post-install verification**: after restarting DSH, tell the Agent "list your memory tools"; you should see `cg` / `stg` (plus `mdcg_*` when `tools: 'all'`); direct brain check: `python -m md_cg.mcp_server` (Windows) / `python3 -m md_cg.mcp_server` (Linux·macOS) (stdio JSON-RPC) is up as soon as it answers initialize; **if the tools never register and the logs keep printing `灵枢调用超时`**, first check the bridge probe `~/.dsh/logs/lingshu-bridge-debug.log` for `spawn … ENOENT` — that is the first cause (interpreter name mismatched with the platform); "call timed out" is only a secondary symptom. For more detail see the [detailed README version](../../mdcg/README详细版_v0.4.10.md)
- **Scope of automatic injection** (issue #554 §2/§4): automatic injection covers only **this session's recent timeline** (`stg(op=timeline, session=<当前会话>)`); **it does not recall across sessions**; use explicit `cg(op=route)` / `cg(op=read)`. Isolated or multi-`DSH_HOME` installs must explicitly set `MDCG_DSH_SESSIONS_ROOT=<该 home>/sessions`, otherwise node sessions degrade to `anonymous` and automatic injection finds no data.
- **Automatic memory troubleshooting** (issue #56): the three filter branches (subagent sessions / relay messages / `source.kind !== 'user'`) and the write/skip paths each leave an **on-disk** trace: the bounded on-disk audit at `~/.dsh/logs/dsh-memory-hook-audit.json` (same directory and conventions as the bridge probe above): which messages were filtered by design, the `source.kind` distribution, write/skip counts (redacted to empty / cognitive map not ready / write failed), and the most recent ≤20 summaries (only action/reason/kind/role, **never message content**). When "it was clearly said in the conversation but memory does not have it", look there first: filtered by design is recorded as `filtered`, write failure or a missed record as `skipped`
