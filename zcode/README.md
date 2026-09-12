# ZCode 端 · 灵枢接入配置

本目录 = **ZCode harness 专属配置**。ZCode 与 CodeBuddy 同构：在**会话起始读取项目根的 `AGENTS.md`**
全文注入，因此本端产物同样采用 `full` 变体。

## 目录内容

| 文件 | 作用 | 性质 |
|---|---|---|
| `AGENTS.md` | 16 条工作纪律全文（会话起始注入） | **渲染产物**，勿手改 |
| `README.md` | 本文件（接入说明） | 手写 |

## 接入

把 `zcode/AGENTS.md` 复制到**你项目的根目录**，新建会话即生效。

ZCode 侧的记忆访问复用同一套 MCP 大脑，配置方式与 CodeBuddy 一致
（见 [`../codebuddy/mcp.json`](../codebuddy/mcp.json) 与 [`../codebuddy/README.md`](../codebuddy/README.md)），
只需把 `MDCG_ACTOR` 改为 `zcode`。

## 与 CodeBuddy 并存

两者互不干扰——CodeBuddy 读根目录 `CODEBUDDY.md`，ZCode 读根目录 `AGENTS.md`；
若项目同时使用两端，各自放入对应文件即可（内容同源，均为真源渲染产物）。

## 记忆策略

同 CodeBuddy 端：**只记重要内容（核心修改：内容/原因/位置/验证结论）+ 对话记录**，
其余一律经写入闸门过滤。详见 [`../codebuddy/README.md`](../codebuddy/README.md) 的「记忆策略」一节。

## 维护（面向灵枢维护者）

- `AGENTS.md` 由 `scripts/render_discipline.py` 从**唯一真源** `docs/工作纪律_认知图条目_v1.1.json`
  渲染生成，矩阵见 `docs/discipline/harnesses.yaml`（`zcode` 槽位）。
- 改纪律 → 改真源 → `python scripts/render_discipline.py --target zcode --write`
  → `python scripts/verify_discipline.py --target zcode` 通过 → 提交。
- **手改本目录的 `AGENTS.md` 会被 `verify_discipline.py` 判为漂移**。
