# Claude Code 端 · 灵枢接入配置

本目录 = **Claude Code（Anthropic）harness 专属配置**。Claude Code 在**会话起始读取项目根的
`CLAUDE.md`**（另支持 `~/.claude/CLAUDE.md` 全局注入、`CLAUDE.local.md` 私有附加），
因此本端产物采用 `full` 变体，与 ZCode / Codex 端同构。

## 目录内容

| 文件 | 作用 | 性质 |
|---|---|---|
| `CLAUDE.md` | 16 条工作纪律全文（会话起始注入） | **渲染产物**，勿手改 |
| `mcp.json.example` | 灵枢 MCP server 接入模板（另存为项目根 `.mcp.json`） | 模板 |
| `README.md` | 本文件（接入说明 + 记忆策略） | 手写 |

## 三步接入

### 1. 接入记忆大脑（MCP）

把 `mcp.json.example` 复制到你项目的根目录并**改名为 `.mcp.json`**，然后把 `env.PYTHONPATH`
的占位值（`REPLACE_WITH_ABSOLUTE_PATH_TO_dsh-memory`）替换为**你本机 dsh-memory 仓库所在
目录**。此处须用可解析的绝对路径——Python 要据此定位仓库内的 `md_cg` 包，相对路径会随进程
工作目录漂移而失效。

也可以用 Claude Code 自带命令注册（效果等同）：

```bash
claude mcp add mdcg --env PYTHONPATH=<本机 dsh-memory 绝对路径> --env MDCG_MCP_SURFACE=kernel \
  --env MDCG_ACTOR=claude-code -- python -m md_cg.mcp_server
```

工具面说明见 [`../codebuddy/README.md`](../codebuddy/README.md)：`MDCG_MCP_SURFACE=kernel`
只暴露 `cg` / `stg` 两个认知基元，`cg` 已覆盖 `route` / `read` / `write` 等全部 op，
**写入通道不缺**。`md_cg` 大脑随仓库自带，无需 pip 安装任何引擎。

### 2. 注入工作纪律

把 `claude/CLAUDE.md` 复制到**你项目的根目录**（Claude Code 会话起始自动读取），
新建会话即生效；若想所有项目生效，可放入 `~/.claude/CLAUDE.md`（全局注入，影响所有会话，慎用）。

> 本仓库刻意把产物放在 `claude/` 子目录而**不落根**——仓库根的 `AGENTS.md` 是本地私有载体
> （含本机运维注记，已被 `.gitignore` 忽略）；且 Claude Code 只认 `CLAUDE.md`、不读
> `AGENTS.md`，与 CodeBuddy（`CODEBUDDY.md`）/ Codex（`AGENTS.md`）端文件名互不冲突，
> 多端可在同一项目根并存、互不覆盖。

### 3. 重启会话

纪律在**会话开始时全文注入一次**，改动后须新建会话才生效。

## 记忆策略：只记重要内容，不记流水

同 CodeBuddy / Codex 端：**只记核心修改（内容 / 原因 / 位置 / 验证结论）+ 对话记录**，
严禁写入中间过程 / 试错步骤 / 调试细节。Claude Code 侧没有会话 hook 自动记忆，
记忆沉淀由纪律第 16 条显式归档驱动（`cg(op=write, gated=true)` 过三问四态闸门）。
详见 [`../codebuddy/README.md`](../codebuddy/README.md) 的「记忆策略」一节。

## 写入凭据（决定能否真正落盘）

`md_cg` 是 **fail-closed**：不配令牌时以**只读 guest** 运行——读取 / 召回 / 时间线照常，
但记忆写入**不落盘**。签发令牌（designer 为唯一可管理角色，`clearance_cap=secret`）：

```bash
python -m md_cg.tokens issue --role designer --actor claude-code
```

把返回的明文令牌填进项目根 `.mcp.json` 的 `env`：

```json
"MDCG_TOKEN": "<签发返回的明文令牌>"
```

> **别把 `ok: true` 当写成功**：未落盘时返回体形如
> `{"ok": true, "committed": false, "moved_to": "review_queue"}`——是否落盘**只看 `committed`**。

## 与其它端并存

Claude Code 读项目根 `CLAUDE.md`，CodeBuddy 读 `CODEBUDDY.md`，Codex / ZCode 读
`AGENTS.md`——三者文件名互不冲突，可并存于同一项目根；内容同源（同一真源渲染），复制其一即可。

## 维护（面向灵枢维护者）

- `CLAUDE.md` 由 `scripts/render_discipline.py` 从**唯一真源** `docs/工作纪律_认知图条目_v1.1.json`
  渲染生成，矩阵见 `docs/discipline/harnesses.yaml`（`claude-code` 槽位）。
- 改纪律 → 改真源 → `python scripts/render_discipline.py --target claude-code --write`
  → `python scripts/verify_discipline.py --target claude-code` 通过 → 提交。
- **手改本目录的 `CLAUDE.md` 会被 `verify_discipline.py` 判为漂移**。
