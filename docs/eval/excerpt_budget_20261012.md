# recall 摘录预算：保持估算口径，保留能容纳的最长前缀

意图声明：修复英文和混合正文被过早截断、预算内的证据仍遭丢弃的问题。

预期结果：按既有 `est_tokens` 口径计算完整「前缀 + 省略号」，保留可容纳的最长前缀，末尾空白仍裁掉；全文放得下时原样返回，空文本/非正预算返回空串。真实 recall 两种入口及 MCP 都保留预算内证据，资格、分数和溯源保持。

可信边界：修复的是项目的确定性 token **估算器**，不是任何模型的 tokenizer。五类合成文本和受控记忆验证预算机制，不代表 QA 或真实对话收益。没有改变候选、排名、信任状态或 recall 触发截断的条件。更充分使用预算可能压缩后续低排名记忆的空间。

## 缺陷及实现

原算法先按每字 0.6 token 估计可截字符数，仅会向下缩，不会为英文每字 0.25 的口径扩窗；又分别估算正文与省略号，重复扣除固定 +1。结果 80 token 预算的英文摘录只用 34 token。

新算法共享原有计数公式，线性扫描前缀，对完整「前缀 + …」只计一次固定项。遇到首个放不下的非空白字符即可停止，后续更长前缀不可能重新变小；尾空白按原 rstrip 语义处理。`est_tokens` 的 CJK 范围、浮点公式和空串行为不变。省略号 U+2026 按现有范围属于其他字符，修正原注释中把它称为 CJK 的错误。

## 冻结源码读数

基线 `c675858`、修复 `9de069b`；独立 Python 进程加载对应 checkout 的生产模块，不替换任何生产函数。先比五类正文、三个预算共 15 组，再分别实际写入记忆并走两种 recall 路径。每臂的 Markdown 与查询内容一致，写入时间不同不参与元数据相等判据。

| 80 token 预算 | 原摘录字符数（含 …） | 修后字符数 | 原估算 tokens | 修后 tokens |
|---|---:|---:|---:|---:|
| ASCII / 英文 | 132 | 319 | 34 | 80 |
| 中文 | 132 | 133 | 79 | 80 |
| 中英混合 | 132 | 281 | 38 | 80 |
| 日文 | 132 | 133 | 79 | 80 |
| 含多种空白的英文 | 132 | 319 | 34 | 80 |

实际 `MdCGOS.recall('anchorrecord', budget_tokens=80, max_item_tokens=80)`：

- `use_rrf=False` / `True` 两路：原 `tokens_used=34`、修后 `80`；原丢失 `evidenceKEEP42`、修后保留。
- 两路 id、原始 score、资格、metadata、provenance 逐项相等；metadata 中 `verification_state=doubted` 与 source 均保留，未提高可信状态。
- `skipped=[]`、`truncated=true`、预算没有越界。原始读数见 [excerpt_budget_bench_20261012.json](excerpt_budget_bench_20261012.json)。

## 守卫和反证

新增 6 个运行测试：400 组随机文本验证估算公式不变；英文预算和证据标记；87 类/实例文本 × 8 预算共 696 例与独立穷举前缀 oracle 相等；空串/非正预算/全文可放下；真实两路 recall；真实 stdio MCP。全部通过。

4/4 变异各在预定断言失败，0 非预期错误 / skip；原算法回注、忽略预算、丢省略号、吞非正预算均能被识别。未变异与恢复态各 3 个具名方法通过。证据：[excerpt_budget_mutations_20261012.json](excerpt_budget_mutations_20261012.json)。相关 recall 元数据、面守卫、MCP、#108 构词法和 #109 写入返回形状回归退出 0；全仓 CI 以 PR Checks 为准。

```text
python -X utf8 -m md_cg.test_excerpt_budget
python -X utf8 -m md_cg.test_excerpt_budget --mutate --output mutations.json
git worktree add --detach ../excerpt-baseline c675858
python -X utf8 -m md_cg.bench_excerpt_budget --baseline ../excerpt-baseline --workspace ../ --output excerpt-replay.json
```

可以从逐例原始输出检查：预算均未超过、保留字符数不减少；只有输入确实放不下时才带省略号。复跑不需要 LLM、远端服务或下载数据。这里没有声称延迟或并发收益。
