> **Languages:** [中文](../../../dsh/README.md) · English

# DSH side · LINGSHU plugin configuration

This directory = **DeepSeek Harness (DSH) harness-specific configuration**. It is a peer of `codebuddy/` and `zcode/`;
the shared layer (`md_cg/` brain, `data/`, `docs/`, `scripts/`) lives at the repository root.

## Directory contents

| File | Purpose |
|---|---|
| `cordis.patch.yml` | Plugin **bundle entry point** (`dsh.bundle.patch` in `package.json` points here; a bare insert declaration) |
| `cordis.yml.example` | Plugin configuration example (30+ entries: mdcg / memory / mutual / capability ...) |
| `cordis-patch-profile-web.example.yml` | **Backup template** for the profile `web` config override (verify it is still present after switching profile, reinstalling, or upgrading) |
| `dsh-web-start.bat` | DSH web host start script (with 8GB heap protection to prevent startup OOM) |
| `update-lingshu.ps1` / `update-lingshu.bat` | One-click LINGSHU plugin update: clear the pnpm release-age gate -> sync the lockfile -> stop DSH (release the directory lock) -> install and verify -> restart. See the header comment in the script for details |
| `hive-mcp.example.yml` | **Hive MCP integration example** (append to `<profile>/cordis.patch.yml`): exposes `hive_spawn`/`hive_poll`/`hive_kill`/`hive_doctor` to DSH models as `mcp__hive__*`. Includes tested notes on env scrubbing, the insert form, and key propagation |
| `hive-mcp-probe.mjs` | Hive MCP server probe: uses the `@modelcontextprotocol/sdk` bundled with DSH to perform a direct handshake + `tools/list` + `hive_doctor` (`--spawn` runs one real task), verifying the server side **without touching the DSH process** |

## Installation

```bash
git clone https://github.com/FuRongJun-1999/dsh-memory.git
cd dsh-memory
npm install && npm run build          # tsc → lib/
dsh plugin --profile web add .        # 必须走 dsh plugin，勿用裸 npm install 装进 profile
```

Then enable the configuration in `<profile>/cordis.yml` as described in `cordis.yml.example`.

## Hive MCP integration (task scheduling + multi-agent concurrency)

Connect `hive/hive_mcp/mcp_server.py` to DSH as an MCP server, and models can call four tools directly:
`mcp__hive__hive_spawn` / `mcp__hive__hive_poll` / `mcp__hive__hive_kill` / `mcp__hive__hive_doctor`.

See [`hive-mcp.example.yml`](../../../dsh/hive-mcp.example.yml) for the complete configuration (**it must be appended in the `- insert:` form** to
`<profile>/cordis.patch.yml`; replace the four `<REPLACE_WITH_...>` placeholders in the template with your own absolute paths).
Three things that are easiest to get wrong:

1. **The env is scrubbed**: `dsh-mcp-client` inherits only 12 system variables, so `PYTHONPATH` / `PYTHONUTF8` /
   `DEEPSEEK_API_KEY` must all be written explicitly in the configuration; otherwise `python -m hive.hive_mcp.mcp_server` will not start.
2. **The key must be passed down**: when serve is not running, `hive_spawn` starts it automatically, and `HIVE_API_KEY` in
   `hive/config.local.json` comes from the host environment variable `DEEPSEEK_API_KEY`; if it is missing, you get a serve without a key.
3. **A restart is required**: the profile `patchReload` defaults to `startup`.

Verification (two steps, neither touches the running DSH; the probe script uses placeholders that you pass through environment variables):

```bash
set DSH_ROOT=<DSH 安装目录>
set HIVE_REPO=<dsh-memory 仓的绝对路径>
set HIVE_LIB=<认知图库仓的绝对路径>
set MDCG_ROOT=<认知图根的绝对路径>
node dsh/hive-mcp-probe.mjs              # 直接连 server：握手 + tools/list + hive_doctor
node dsh/hive-mcp-probe.mjs --spawn      # 再真跑一个任务，验证写路径
dsh --profile web --dump-config | findstr mcp-hive   # 确认配置确实进了组合后的插件树
```

After a restart, calling `mcp__hive__hive_doctor` in DSH should report that serve is alive; spawn a minimal task with `hive_spawn`
(such as replying `HIVE_DSH_MCP_OK`), then poll with `hive_poll` until `done` and the path works end to end.

## Discipline injection (managed personaPrefix block)

The 19 engineering discipline rules on the DSH side **do not use a separate file**. Instead, the `compact` variant is written to
the `personaPrefix` key in `~/.dsh/profiles/web/cordis.patch.yml` and revised in place with the managed marker block `lingshu:discipline`
(comments preserved):

```
python scripts/render_discipline.py --target dsh --write
python scripts/verify_discipline.py --target dsh
```

> DSH `personaPrefix` is a system prompt slot injected **on every turn**, so the `compact` variant is used;
> CodeBuddy / ZCode inject **at session start**, so they use the `full` variant. All three roles render from
> `docs/工作纪律_认知图条目_v1.1.json`; see `docs/discipline/harnesses.yaml` for the matrix.

## Relationship to the three-layer split plan

This directory organizes configuration **by harness** (DSH / CodeBuddy / ZCode);
[`../docs/mdcg/灵枢三层拆分规划_v0.1.md`](../../../docs/mdcg/灵枢三层拆分规划_v0.1.md) discusses **a different, orthogonal dimension**
(separating responsibilities across three repositories - spirit / brain / body - with the goal of slimming down the main repository).

The two have an **ownership disagreement** over `dsh-web-start.bat`: the three-layer plan intends to move it out of the main repository into the 'body repository (host startup)',
while this directory keeps it here under the harness dimension. That disagreement **is left to the three-layer plan Phase to adjudicate and converge**; this directory is its current
traceable landing point and does not change the conclusions of the three-layer plan.
