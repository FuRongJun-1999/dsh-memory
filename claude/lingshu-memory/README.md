# lingshu-memory · Claude Code 插件

灵枢（Lingshu）长期记忆系统的 **Claude Code 插件形态**：把「16 条工作纪律」做成随插件分发的
skill（`skills/linglu-discipline/`），并附灵枢大脑（stdio MCP server `mdcg`）的接入模板。

> 与手工路线（复制 `claude/CLAUDE.md` 到项目根）的差别：CLAUDE.md **不能随插件分发**，
> 故纪律注入改由 skill 承载——Claude 按 frontmatter `description` 在任务开始 / 命中触发词时
> 自动加载，也可用 `/lingshu-memory:linglu-discipline` 显式调用。两条路线同源（同一真源渲染），可并存。

## 安装（插件市场）

本仓库根自带 marketplace（`.claude-plugin/marketplace.json`）：

```bash
# Claude Code 会话内
/plugin marketplace add FuRongJun-1999/dsh-memory
/plugin install lingshu-memory@lingshu
```

本地开发调试可用：`claude --plugin-dir ./claude/lingshu-memory`。

## 装后两步（缺一不可）

1. **接入记忆大脑（MCP）**：把本插件目录的 `mcp.json.example` 复制到你项目的根目录并改名为
   `.mcp.json`，把 `env.PYTHONPATH` 占位值替换为**你本机 dsh-memory 仓库的绝对路径**
   （Python 据此定位 `md_cg` 包）。也可用命令注册：

   ```bash
   claude mcp add mdcg --env PYTHONPATH=<本机 dsh-memory 绝对路径> --env MDCG_MCP_SURFACE=kernel \
     --env MDCG_ACTOR=claude-code -- python -m md_cg.mcp_server
   ```

   工具面说明：`MDCG_MCP_SURFACE=kernel` 只暴露 `cg` / `stg` 两个认知基元，
   `cg` 已覆盖 `route` / `read` / `write` 等全部 op，**写入通道不缺**。

2. **新开会话**：首次对话可直接说「先查灵枢记忆：cg(op=route, intent=…)」验证通路；
   或显式调用 `/lingshu-memory:linglu-discipline` 加载纪律。

## 写入凭据（决定能否真正落盘）

`md_cg` 是 **fail-closed**：不配令牌时以**只读 guest** 运行——读取 / 召回 / 时间线照常，
但记忆写入**不落盘**。签发令牌：

```bash
python -m md_cg.tokens issue --role designer --actor claude-code
```

把返回的明文令牌填进 `.mcp.json` 的 `"MDCG_TOKEN"`。
**别把 `ok: true` 当写成功**：是否落盘**只看返回体的 `committed`** 字段。

## 目录内容

| 文件 | 作用 | 性质 |
|---|---|---|
| `.claude-plugin/plugin.json` | 插件清单 | 手写 |
| `skills/linglu-discipline/SKILL.md` | 16 条工作纪律 + 记忆操作规程 | **渲染产物**，勿手改 |
| `mcp.json.example` | 灵枢 MCP 接入模板（与 `claude/mcp.json.example` 同源） | 模板副本 |
| `README.md` | 本文件 | 手写 |

## 维护（面向灵枢维护者）

- `SKILL.md` 由 `scripts/render_discipline.py` 从唯一真源 `docs/工作纪律_认知图条目_v1.1.json`
  渲染生成，矩阵见 `docs/discipline/harnesses.yaml`（`claude-code-plugin-skill` 槽位，`skill` 变体）。
- 改纪律 → 改真源 → `python scripts/render_discipline.py --target claude-code-plugin-skill --write`
  → `python scripts/verify_discipline.py --target claude-code-plugin-skill` 通过 → 提交。
- 发新版：提升 `.claude-plugin/plugin.json` 与 `.claude-plugin/marketplace.json` 的 `version`
  （Claude 插件只有版本号提升用户才会收到更新）。
