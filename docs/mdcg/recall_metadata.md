# Recall 核心状态与来源信息

`mdcg_recall` 和带 `budget_tokens` 的 `cg(op="read")` 返回的每个
`pack` 条目新增 `metadata`，方便调用方直接读取少量关键状态信息。
原有 `id`、`score`、`state`、`tokens`、`content`、`frontmatter`、
`provenance` 和按需返回的 `truncated` 保持原值与含义。

| 字段 | 来源与含义 |
|---|---|
| `state` | 本次检索已有的资格裁决，如 `ACCEPT`、`DEFER`、`REJECT`、`BLINDSPOT`；描述记忆对当前查询/情境的适用性，不代表事实已获确认。 |
| `reason` | 本次资格裁决已有的理由；没有理由时为 `null`。 |
| `verification_state` | 通过现有 `trust.state_of(frontmatter)` 读取持久验证状态：`unverified`、`verified`、`doubted`、`rechecking`、`expired`。缺失或非法状态按已有规则视为 `unverified`，不代表完成过验证。 |
| `verification_basis` | 原有 frontmatter 中声明的验证依据类别；声明了依据不代表已经验证通过。 |
| `check_strength` | 原有 frontmatter 中声明的检查强度。 |
| `derived_from`、`derived_relation` | 原有 frontmatter 中声明的来源记忆及派生关系。 |
| `source` | 仅透传 frontmatter 中明确记录的来源；不根据角色或会话推断。 |

后三行及 `verification_basis`、`check_strength` 仅在字段存在且值非
`null` 时返回；保留已记录的空字符串、空列表、`false` 或 `0`。
`metadata` 不新增可靠性评分，不复制 `confidence`，也不汇总完整审核日志、
验证历史或所有版本。已有 `frontmatter` 仍保留，以兼容原调用方。

例如，某条记忆对当前查询适用，但尚未经过验证，会同时返回
`state: "ACCEPT"` 和 `verification_state: "unverified"`。
上层 AI 应把它理解为“可供当前任务参考的未验证记忆”。
没有来源记录时，不返回 `source`；不要将“未记录”理解为“用户直接提供”。

原有 `provenance` 表示检索路径和排名，不是事实来源，因此不复制进
`metadata`。`score` 仍是原检索分数，也不能当作事实可信概率。

该摘要只在最终装包时使用已经读取的数据，不增加存储读写。候选、检索路径、
RRF、排序、资格裁决、正文截断和原有 token 预算计算均不改变。
`tokens` / `tokens_used` 继续按正文（以及可选近期事件正文）计数，
不表示整个 JSON 响应的序列化 token 数。可选 `recent` 事件窗口保持原结构。

验证方式：

```sh
python -X utf8 -m md_cg.test_recall_metadata
python -X utf8 -m md_cg.test_p2_mcp
```
