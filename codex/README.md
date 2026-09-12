# Codex 端 · 灵枢接入配置

本目录 = **Codex CLI harness 专属配置**。Codex（OpenAI Codex CLI）在**会话起始读取项目根的
`AGENTS.md`**（另支持 `~/.codex/AGENTS.md` 全局注入），因此本端产物采用 `full` 变体，与 ZCode 同构。

## 目录内容

| 文件 | 作用 | 性质 |
|---|---|---|
| `AGENTS.md` | 16 条工作纪律全文（会话起始注入） | **渲染产物**，勿手改 |
| `config.toml.example` | 灵枢 MCP server 接入模板（合并进 `~/.codex/config.toml`） | 模板 |
| `README.md` | 本文件（接入说明 + 记忆策略） | 手写 |

## 三步接入

### 1. 接入记忆大脑（MCP）

把 `config.toml.example` 里的 `[mcp_servers.mdcg]` 与 `[mcp_servers.mdcg.env]` 两段合并进
`~/.codex/config.toml`，然后把 `PYTHONPATH` 的占位值
（`REPLACE_WITH_ABSOLUTE_PATH_TO_dsh-memory`）替换为**你本机 dsh-memory 仓库所在目录**。
此处须用可解析的绝对路径——Python 要据此定位仓库内的 `md_cg` 包，相对路径会随进程
工作目录漂移而失效。

工具面说明见 [`../codebuddy/README.md`](../codebuddy/README.md)：`MDCG_MCP_SURFACE=kernel`
只暴露 `cg` / `stg` 两个认知基元，`cg` 已覆盖 `route` / `read` / `write` 等全部 op，
**写入通道不缺**。`md_cg` 大脑随仓库自带，无需 pip 安装任何引擎。

### 2. 注入工作纪律

把 `codex/AGENTS.md` 复制到**你项目的根目录**（Codex 会话起始自动读取），新建会话即生效；
若想所有项目生效，可放入 `~/.codex/AGENTS.md`（全局注入，影响所有会话，慎用）。

> 本仓库刻意把产物放在 `codex/` 子目录而**不落根**——仓库根的 `AGENTS.md`
> 是本地私有载体（含本机运维注记，已被 `.gitignore` 忽略），落根会覆盖它。

### 3. 重启会话

纪律在**会话开始时全文注入一次**，改动后须新建会话才生效。

## 记忆策略：只记重要内容，不记流水

同 CodeBuddy / ZCode 端：**只记核心修改（内容 / 原因 / 位置 / 验证结论）+ 对话记录**，
严禁写入中间过程 / 试错步骤 / 调试细节。Codex 侧没有会话 hook 自动记忆，
记忆沉淀由纪律第 16 条显式归档驱动（`cg(op=write, gated=true)` 过三问四态闸门）。
详见 [`../codebuddy/README.md`](../codebuddy/README.md) 的「记忆策略」一节。

## 写入凭据（决定能否真正落盘）

`md_cg` 是 **fail-closed**：不配令牌时以**只读 guest** 运行——读取 / 召回 / 时间线照常，
但记忆写入**不落盘**。签发令牌（designer 为唯一可管理角色，`clearance_cap=secret`）：

```bash
python -m md_cg.tokens issue --role designer --actor codex
```

把返回的明文令牌填进 `~/.codex/config.toml` 的 `[mcp_servers.mdcg.env]`：

```toml
MDCG_TOKEN = "<签发返回的明文令牌>"
```

> **别把 `ok: true` 当写成功**：未落盘时返回体形如
> `{"ok": true, "committed": false, "moved_to": "review_queue"}`——是否落盘**只看 `committed`**。

## 与其它端并存

Codex / ZCode 都读项目根 `AGENTS.md`，二者内容同源（同一真源渲染），复制其一即可；
CodeBuddy 读根目录 `CODEBUDDY.md`，Claude Code 读根目录 `CLAUDE.md`——各端文件名
互不冲突，可与前者并存互不干扰。

## 维护（面向灵枢维护者）

- `AGENTS.md` 由 `scripts/render_discipline.py` 从**唯一真源** `docs/工作纪律_认知图条目_v1.1.json`
  渲染生成，矩阵见 `docs/discipline/harnesses.yaml`（`codex` 槽位）。
- 改纪律 → 改真源 → `python scripts/render_discipline.py --target codex --write`
  → `python scripts/verify_discipline.py --target codex` 通过 → 提交。
- **手改本目录的 `AGENTS.md` 会被 `verify_discipline.py` 判为漂移**。
