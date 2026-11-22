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
`tokens` 仍按正文（以及可选近期事件正文）计数，不表示整个 JSON 响应的序列化
token 数。可选 `recent` 事件窗口保持原结构。`tokens_used` 自 issue #1005 起
**含判读合同**（见下节）；合同关闭时与旧口径逐位一致。

## issue #1005：判读合同与覆盖缺口

检索只给材料、不给判读约束，也不报覆盖缺口——调用方无法判断「这是原话还是推断」
「材料够不够」。故 recall 的返回体新增三项：

| 字段 | 含义 |
|---|---|
| `reading_policy` | 判读合同正文（常量，见 `md_cg/reading_policy.py`）。缺省开；`MDCG_READING_POLICY=0` 关闭后为空串 |
| `coverage_gaps` | 本次检索的已知缺口，闭集三码：`anchor_missing` / `budget_truncated` / `raw_not_included` |
| `coverage_certified` | `coverage_gaps` 为空时为真。**未认证 ≠ 错**，只表示「该自己判断材料够不够」 |

缺口判据只用装包结果自带信号（不额外检索、不读盘）：

- `anchor_missing`：pack 为空；或**无一条目含查询词成分**且最高分处于单路基准分
  （`1/(RRF_K+1)`）量级——RRF 给每个被召回条目一个基准分，所以「分数 > 0」不能证明锚到了。
- `budget_truncated`：有条目因预算/超长被跳过（`skipped.reason`），或已用满预算。
- `raw_not_included`：pack 里有材料但**没有一条是原话轮次**（`profile-*` 卡或带
  `derived_from`/`source` 的派生材料）；正是「卡进了 pack、源轮次没进」。

预算口径：合同**计入** `budget_tokens`，不从预算外额外送。装包末尾按合同 token 数
从尾部（最低分）裁掉等量条目，但保底留 1 条；连「合同 + 1 条材料」都装不下时
（如 `budget_tokens=2` 的极端面）**丢掉合同并把 `meta.reading_policy_skipped`
记为 `budget_too_small`**——不许出现「合同没进包、材料却少了」的两头空。

注入面剔走 untrusted 条目后，`coverage_gaps` 会**重算**：原话轮次若正因 untrusted
被剔走，`raw_not_included` 就是此刻的真话。

验证方式：

```sh
python -X utf8 -m md_cg.test_recall_reading_policy
python -X utf8 -m md_cg.test_recall_metadata
python -X utf8 -m md_cg.test_p2_mcp
```
