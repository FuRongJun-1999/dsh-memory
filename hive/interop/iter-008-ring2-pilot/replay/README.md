# iter-008-ring2-pilot · 复现件

## 等效性声明
`replay/pilot_build.py`、`replay/pilot_review.py` 与主体侧实际运行的 `<coord>/pilot_build.py`、`<coord>/pilot_review.py`
**逻辑逐字一致**，唯一差异 = 路径来源由硬编码改为环境变量（避免本机绝对路径入公开仓）。

## 重放步骤
1. 建候选提示词（源级枚举，不依赖认知图）：
   `REPO=<仓根> COORD=<输出目录> python -X utf8 replay/pilot_build.py`
   预期输出含：`SAMPLED 60 EXAMINED 2001 CANDS 2001 FAMILIES 125` / `USABLE 10` / `PROMPT_LEN …`
2. LLM 生成（1 次调用；主体侧经蜂巢 LLM 通道，model=deepseek-flash，`max_tokens` 按文档值 200000）：
   用 `COORD/pilot_spec.json` 提交，或直接以 `COORD/pilot_prompt.txt` 为 user_prompt。
3. 机械自检：
   `REPO=<仓根> COORD=<输出目录> LLM_JOB_RESULT=<该 LLM 作业的 result.json> python -X utf8 replay/pilot_review.py`
   预期输出：`PROPOSALS 10 OK 10 BLINDSPOT 0 REJECT 0`

## 判据强度（诚实边界）
机械自检只拦两类：①元条件/合成话术（禁词表）②语义上完全无源码锚点者（标识符不重合）。
**它不能判定语义正确性**——这正是本次请求编外抽查 A1/A2/A3 的原因。

## 已知不可复现项
- `plan_sources` 的族轮转顺序依赖 `comment_gate` 的候选枚举实现（候选分支 `task/iter-007-cg-sources`，tip 97c2681）；
  在 main 面上该函数可能不存在，须先取该分支或等价实现。
