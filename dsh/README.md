# DSH 端 · 灵枢插件配置

本目录 = **DeepSeek Harness（DSH）harness 专属配置**。与 `codebuddy/`、`zcode/` 平级，
共享层（`md_cg/` 大脑、`data/`、`docs/`、`scripts/`）在仓库根。

## 目录内容

| 文件 | 作用 |
|---|---|
| `cordis.patch.yml` | 插件 **bundle 入口**（`package.json` 的 `dsh.bundle.patch` 指向本文件；裸 insert 声明） |
| `cordis.yml.example` | 插件配置示例（30+ 项：mdcg / memory / mutual / capability …） |
| `cordis-patch-profile-web.example.yml` | profile `web` 的 config override **备份模板**（换 profile / 重装 / 升级后须核对仍在） |
| `dsh-web-start.bat` | DSH web 宿主启动脚本（带 8GB heap 保护，防启动 OOM） |
| `update-lingshu.ps1` / `update-lingshu.bat` | 灵枢插件一键更新：放行 pnpm 发布龄闸门 → 同步 lockfile → 停 DSH（释放目录锁）→ 安装并校验 → 重启。详见脚本头部注释 |
| `hive-mcp.example.yml` | **蜂巢 MCP 接入样例**（追加进 `<profile>/cordis.patch.yml`）：把 `hive_spawn`/`hive_poll`/`hive_kill`/`hive_doctor` 以 `mcp__hive__*` 暴露给 DSH 模型。含 env 清洗、insert 形态、密钥传递等实测要点 |
| `hive-mcp-probe.mjs` | 蜂巢 MCP server 探针：用 DSH 自带的 `@modelcontextprotocol/sdk` 直接握手 + `tools/list` + `hive_doctor`（`--spawn` 可跑一次真任务），**不动 DSH 进程**即可验证 server 侧 |

## 安装

```bash
git clone https://github.com/FuRongJun-1999/dsh-memory.git
cd dsh-memory
npm install && npm run build          # tsc → lib/
dsh plugin --profile web add .        # 必须走 dsh plugin，勿用裸 npm install 装进 profile
```

再参照 `cordis.yml.example` 在 `<profile>/cordis.yml` 启用配置。

## 蜂巢（hive）MCP 接入（任务调度 + 多智能体并发）

把 `hive/hive_mcp/mcp_server.py` 作为 MCP 服务器接进 DSH，模型即可直接调用 4 个工具：
`mcp__hive__hive_spawn` / `mcp__hive__hive_poll` / `mcp__hive__hive_kill` / `mcp__hive__hive_doctor`。

完整配置见 [`hive-mcp.example.yml`](hive-mcp.example.yml)（**必须用 `- insert:` 形态**追加到
`<profile>/cordis.patch.yml`；模板内 4 个 `<REPLACE_WITH_...>` 占位符换成你自己的绝对路径）。
三条最容易踩的点：

1. **env 会被清洗**：`dsh-mcp-client` 只继承 12 个系统变量，`PYTHONPATH` / `PYTHONUTF8` /
   `DEEPSEEK_API_KEY` 都得在配置里显式写出，否则 `python -m hive.hive_mcp.mcp_server` 起不来。
2. **密钥要传下去**：serve 未存活时 `hive_spawn` 会自动拉起它，而 `hive/config.local.json` 里
   `HIVE_API_KEY` 取自宿主环境变量 `DEEPSEEK_API_KEY`；漏传 ⇒ 拉起一个「没钥匙的 serve」。
3. **重启才生效**：profile 的 `patchReload` 默认 `startup`。

验证（两步，都不需要动正在跑的 DSH；探针脚本内是占位符，用环境变量传入）：

```bash
set DSH_ROOT=<DSH 安装目录>
set HIVE_REPO=<dsh-memory 仓的绝对路径>
set HIVE_LIB=<认知图库仓的绝对路径>
set MDCG_ROOT=<认知图根的绝对路径>
node dsh/hive-mcp-probe.mjs              # 直接连 server：握手 + tools/list + hive_doctor
node dsh/hive-mcp-probe.mjs --spawn      # 再真跑一个任务，验证写路径
dsh --profile web --dump-config | findstr mcp-hive   # 确认配置确实进了组合后的插件树
```

重启后在 DSH 里调用 `mcp__hive__hive_doctor` 应报 serve 存活；`hive_spawn` 一个最小任务
（如「回复 HIVE_DSH_MCP_OK」）再 `hive_poll` 到 `done` 即端到端通。

## 纪律注入（personaPrefix 受管块）

DSH 端的 16 条工作纪律**不走独立文件**，而是以 `compact` 变体写入
`~/.dsh/profiles/web/cordis.patch.yml` 的 `personaPrefix` 键，用受管标记块 `lingshu:discipline`
原地修订（保留注释）：

```
python scripts/render_discipline.py --target dsh --write
python scripts/verify_discipline.py --target dsh
```

> DSH 的 `personaPrefix` 是**每轮注入**的系统提示槽位，因此用 `compact` 变体；
> CodeBuddy / ZCode 是**会话起始注入**，用 `full` 变体。三角色同源于
> `docs/工作纪律_认知图条目_v1.1.json`，矩阵见 `docs/discipline/harnesses.yaml`。

## 与「三层拆分规划」的关系

本目录是**按 harness 维度**（DSH / CodeBuddy / ZCode）归置配置；
[`../docs/mdcg/灵枢三层拆分规划_v0.1.md`](../docs/mdcg/灵枢三层拆分规划_v0.1.md) 讨论的是**另一种正交维度**
（灵 / 脑 / 身 三仓职责分离，目标是主仓瘦身）。

二者在 `dsh-web-start.bat` 上存在**归属分歧**：三层规划拟将其移出主仓至「身体仓（宿主启动）」，
而本目录按 harness 维度将其收拢。该分歧**留待三层规划 Phase 裁决收敛**——本目录为其当前的
可追踪落点，不改变三层规划的结论。
