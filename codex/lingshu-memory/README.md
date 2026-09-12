# lingshu-memory · Codex CLI 插件

灵枢（Lingshu）长期记忆系统的 **Codex CLI 插件形态**：把「16 条工作纪律」做成随插件分发的
skill（`skills/linglu-discipline/`），并附灵枢大脑（stdio MCP server `mdcg`）的接入模板。

> 与手工路线（复制 `codex/AGENTS.md` 到项目根 + 合并 config.toml）的差别：插件把纪律装进
> skill 三级渐进加载（元数据常驻 context、正文触发时加载）；项目根 `AGENTS.md` 仍是会话起始
> 全文注入主通道，两者同源（同一真源渲染）、并存不冲突。

## 安装（插件市场）

本仓库根自带团队级 marketplace（`.agents/plugins/marketplace.json`）：

```bash
# 注册本仓为 marketplace（本地路径），随后安装
codex plugin marketplace add <本机 dsh-memory 仓库路径>
codex plugin add lingshu-memory@lingshu
codex plugin list   # 确认已安装
```

## 装后两步（缺一不可）

1. **接入记忆大脑（MCP）**：把本插件目录 `config.toml.example` 的 `[mcp_servers.mdcg]` 与
   `[mcp_servers.mdcg.env]` 两段合并进 `~/.codex/config.toml`，把 `PYTHONPATH` 占位值替换为
   **你本机 dsh-memory 仓库的绝对路径**（Python 据此定位 `md_cg` 包）。

   工具面说明：`MDCG_MCP_SURFACE=kernel` 只暴露 `cg` / `stg` 两个认知基元，
   `cg` 已覆盖 `route` / `read` / `write` 等全部 op，**写入通道不缺**。

2. **开新线程**：Codex 需新线程才加载插件与配置更新。首次对话可直接说
   「先查灵枢记忆：cg(op=route, intent=…)」验证通路。

## 写入凭据（决定能否真正落盘）

`md_cg` 是 **fail-closed**：不配令牌时以**只读 guest** 运行——读取 / 召回 / 时间线照常，
但记忆写入**不落盘**。签发令牌：

```bash
python -m md_cg.tokens issue --role designer --actor codex
```

把返回的明文令牌填进 `~/.codex/config.toml` 的 `[mcp_servers.mdcg.env]`：
`MDCG_TOKEN = "<明文令牌>"`。
**别把 `ok: true` 当写成功**：是否落盘**只看返回体的 `committed`** 字段。

## 目录内容

| 文件 | 作用 | 性质 |
|---|---|---|
| `.codex-plugin/plugin.json` | 插件清单（name 与文件夹一致 · interface 完整 · 无 hooks 字段） | 手写 |
| `skills/linglu-discipline/SKILL.md` | 16 条工作纪律 + 记忆操作规程 | **渲染产物**，勿手改 |
| `config.toml.example` | 灵枢 MCP 接入模板（与 `codex/config.toml.example` 同源） | 模板副本 |
| `README.md` | 本文件 | 手写 |

## 维护（面向灵枢维护者）

- `SKILL.md` 由 `scripts/render_discipline.py` 从唯一真源 `docs/工作纪律_认知图条目_v1.1.json`
  渲染生成，矩阵见 `docs/discipline/harnesses.yaml`（`codex-plugin-skill` 槽位，`skill` 变体）。
- 改纪律 → 改真源 → `python scripts/render_discipline.py --target codex-plugin-skill --write`
  → `python scripts/verify_discipline.py --target codex-plugin-skill` 通过 → 提交。
- 发新版：提升 `.codex-plugin/plugin.json` 的 `version`（严格 semver）。本地迭代重安装用
  cachebuster 戳（如 `0.1.0+codex.local-<时间戳>`），勿用递增版本号触发重安装。
