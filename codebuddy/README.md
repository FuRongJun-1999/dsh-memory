# CodeBuddy 端 · 灵枢接入配置

本目录 = **CodeBuddy harness 专属配置**（灵枢 = Lingshu 记忆系统）。与 `dsh/`、`zcode/` 平级，
共享层（`md_cg/` 大脑、`data/`、`docs/`、`scripts/`）在仓库根，不属任何单端。

## 目录内容

| 文件 | 作用 | 性质 |
|---|---|---|
| `CODEBUDDY.md` | 16 条工作纪律全文（会话起始注入） | **渲染产物**，勿手改 |
| `mcp.json` | 灵枢接入模板：`mdcg`（记忆大脑）+ `hive`（蜂巢并发）两条 MCP server（复制进 CodeBuddy 设置） | 模板 |
| `README.md` | 本文件（接入说明 + 记忆策略） | 手写 |

## 三步接入

### 1. 接入记忆大脑（MCP）

把 `mcp.json` 里的 `mcpServers.mdcg` 一段合并进 CodeBuddy 的 MCP 配置，然后把
`PYTHONPATH` 的占位值（`REPLACE_WITH_ABSOLUTE_PATH_TO_dsh-memory`）替换为**你本机
dsh-memory 仓库所在目录**。此处须用可解析的绝对路径——Python 要据此定位仓库内的 `md_cg`
包，相对路径会随进程工作目录漂移而失效。

`md_cg` 大脑随仓库自带，**无需 pip 安装任何引擎**；只需本机有 Python 与 Node ≥ 22.19。

> **工具面 `MDCG_MCP_SURFACE=kernel`**（与 `md_cg/mcp_server.py` 的默认值一致）：只暴露 `cg` /
> `stg` 两个认知基元；`cg` 已覆盖 `route` / `read` / `write` 等全部 op，**写入通道不缺**。
> 细粒度 `mdcg_*` 工具仅在 `full` 面可见，属兼容 / 调试用途，日常接入无需开启。

#### 1b. 接入蜂巢（多智能体并发 + 任务上下文管理）

`mcp.json` 里同源的第二条 `mcpServers.hive` 一并合并——四工具 `hive_spawn` / `hive_poll` /
`hive_kill` / `hive_doctor`，提供**跨 harness 通用的并发执行**与**任务上下文管理**
（`context_files` 注入、预算交回续跑、进展卡观察）。语义与边界见
[`../hive/README.md`](../hive/README.md) 的「各 harness 注册」。

> 依赖 Rust 侧 `hive.exe` 与 `hive/config.local.json`（执行器密钥）。未构建时先
> `cd hive && cargo build --release`；`cargo` 不在 PATH 时改用绝对路径
> `"%USERPROFILE%\.cargo\bin\cargo.exe" build --release --manifest-path hive/Cargo.toml`；
> 首次 `hive_spawn` 会自动以 detached 方式拉起 `serve`。
> **确定性任务（跑命令 / 测试）不在 MCP 面**，走 CLI：
> `hive/target/release/hive.exe submit --spec <spec.json>`。

### 2. 注入工作纪律

把 `CODEBUDDY.md` 复制到**你项目的根目录**。

> CodeBuddy 规则优先级：根目录存在 `CODEBUDDY.md` 时会**忽略 `AGENTS.md`**。
> 本仓库刻意把产物放在 `codebuddy/` 子目录而**不落根**——因为仓库根的 `AGENTS.md`
> 是本地私有载体（含本机运维注记，已被 `.gitignore` 忽略）。子目录放置既让外部用户可直接取用，
> 又不屏蔽本地纪律。

### 3. 重启会话

纪律在**会话开始时全文注入一次**，改动后须新建会话才生效。

## 记忆策略：只记重要内容，不记流水

灵枢是记忆系统，但**什么都记等于什么都不记**——因此写入侧有两道机制化过滤，而非靠人自觉：

| 层 | 内容 | 落点 | 过滤方式 |
|---|---|---|---|
| **重要内容** | 核心修改：内容 / 原因 / 位置 / 验证结论 | `knowledge` / `self` 层 | `cg(op=write, gated=true)` 过**三问四态闸门**，非 `ACCEPT` 不落盘 |
| **对话记录** | 会话转录 | `contextual` 层 | 主动遗忘闸门按重要性阈值自动 `DROP` 低熵噪音 |

- **纪律第 16 条**要求每次任务收尾主动归档核心修改——这是「对话 → 长期记忆」的闭环入口。
- **严禁**写入中间过程 / 试错步骤 / 调试细节 / 重复确认；这类内容会污染检索、干扰后续召回。
- CodeBuddy 侧**没有** DSH 那样的会话 hook 自动记忆，故记忆沉淀由纪律驱动（Agent 在收尾显式调用
  `cg(op=write, gated=true)`），而非进程自动抓取。

## 写入凭据（决定能否真正落盘）

`md_cg` 是 **fail-closed**：不配凭据时插件以**只读 guest** 运行——读取 / 召回 / 时间线照常，
但记忆写入**不落盘**。要落盘请签发令牌：

```bash
python -m md_cg.tokens issue --role designer --actor codebuddy --clearance internal ^
  --ops-allow info,route,read,write,recent,goal,identity,whitebox,verify ^
  --layers-allow knowledge,contextual,structural,self,goals,unresolved,rejected
```

然后把 `MDCG_TOKEN` 填进 `mcp.json` 的 `env`（或设系统环境变量后引用）。

> **别把 `ok: true` 当写成功**：未落盘时返回体形如
> `{"ok": true, "committed": false, "moved_to": "review_queue"}`——是否落盘**只看 `committed`**。

## 维护（面向灵枢维护者）

- `CODEBUDDY.md` 由 `scripts/render_discipline.py` 从**唯一真源** `docs/工作纪律_认知图条目_v1.1.json`
  渲染生成，矩阵见 `docs/discipline/harnesses.yaml`（`codebuddy` 槽位）。
- 改纪律 → 改真源 → `python scripts/render_discipline.py --target codebuddy --write`
  → `python scripts/verify_discipline.py --target codebuddy` 通过 → 提交。
- **手改本目录的 `CODEBUDDY.md` 会被 `verify_discipline.py` 判为漂移**。
