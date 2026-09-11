# LoCoMo-zh-500 · 中文记忆检索评测集

> 500 道中文查询 / 567 条被检索 turn / 0.6 MB
> 用于评测**记忆系统的中文检索能力**（hit@1 / hit@5 / MRR）
> 许可：**CC BY-NC 4.0**（署名 + 非商业性使用，见文末）

---

## 这是什么

从公开数据集 LoCoMo 派生的**中文检索评测集**。本仓库在上游英文语料之上注写了中文层（中文词项 + 条件空间四槽 + 摘要），并把被测池裁剪到 500 题的 gold 证据范围，使单次全量评测可以在数秒内跑完。

**它评测什么**：给定 500 道中文查询，记忆系统能否从 567 条候选中把 gold 证据 turn 排进前 k。

**它不评测什么**（务必先读）：

- **不是 QA 评测集**——`answer` 字段恒为 `null`，只有 `evidence_turns`（qrels），无法评测答案正确性。
- **不是自然语言对话评测**——`question` 是**中文关键词串**（如 `慈善跑 心理健康 发声 意识 意义`），不是问句。
- **不能当作端到端记忆能力分数**——被测池是零干扰的（见下方诚实边界第 1 条）。

---

## 为什么用它

| | 本集 | 上游 LoCoMo（原版） |
|---|---|---|
| 查询语言 | **中文** | 英文 |
| 题量 | 500 | 1976 |
| 被测池 | 567 条 | 5882 条 |
| 池内干扰项 | 无（全 gold） | 有 |
| 查询形态 | 中文关键词串 | 英文自然语言问句 |
| 条件空间四槽 | **有**（观测位置/观测工具/时间窗口/存在约束） | 无 |
| 体积 | 0.6 MB | ~2 MB |

选它的理由：**中文 + 极轻 + 可复现**。上游是英文语料，中文记忆系统缺公开可对照的中文检索基准；而原版 1976 题 × 5882 turn 的全量池体积与耗时都不适合做快速回归。

---

## 文件与字段

### `corpus567.jsonl` —— 记忆库（被检索池，567 行）

```json
{
  "id": "scene_0_session_2_turn_2",
  "text": "英文原始陈述（上游 LoCoMo 内容）",
  "speaker": "说话人（LoCoMo 中的虚构角色名）",
  "date": "会话日期",
  "zh": "本仓库生成的中文层扁平串：身份 / 时间 / 摘要 / 条件（四槽）/ 词",
  "zh_fields": {
    "identity": "身份槽",
    "time": "时间槽",
    "summary": "摘要槽",
    "condition": "条件空间（观测位置 / 观测工具 / 存在约束）",
    "terms": "中文词项"
  }
}
```

`id` 必须原样保留：它是与 `questions500.jsonl` 的 `evidence_turns` 对齐的唯一键。

### `questions500.jsonl` —— 查询 + qrels（500 行）

```json
{
  "qid": "scene_0_q_82",
  "qtype": "single_hop",
  "question": "慈善跑 心理健康 发声 意识 意义",
  "answer": null,
  "evidence_turns": ["scene_0_session_2_turn_2"]
}
```

题型分布（分层比例抽样自上游 1976 题，seed=7）：

| qtype | 本集 | 上游 | 抽样比 |
|---|---|---|---|
| single_hop | 213 | 840 | 42.5% → 42.6% |
| adversarial | 113 | 446 | 22.6% → 22.6% |
| temporal_reasoning | 81 | 321 | 16.2% → 16.2% |
| multi_hop | 71 | 280 | 14.2% → 14.2% |
| open_domain | 22 | 89 | 4.5% → 4.4% |
| **合计** | **500** | **1976** | — |

---

## 怎么用

把 `corpus567.jsonl` 灌进你的记忆库，用 `questions500.jsonl` 的 `question` 检索，检查 `evidence_turns` 是否落在前 k：

```python
import json

corpus = [json.loads(l) for l in open("corpus567.jsonl", encoding="utf-8")]
questions = [json.loads(l) for l in open("questions500.jsonl", encoding="utf-8")]

# 1) 灌库：id 必须原样保留，作为与 qrels 对齐的检索键
for turn in corpus:
    memory.add(id=turn["id"], text=turn["text"], zh=turn["zh"])

# 2) 评测：question 是中文关键词串，不是自然语言问句
hit1 = hit5 = 0
for q in questions:
    got = [h.id for h in memory.search(q["question"], k=5)]
    hit1 += bool(got and got[0] in q["evidence_turns"])
    hit5 += bool(set(got[:5]) & set(q["evidence_turns"]))

n = len(questions)
print(f"hit@1={hit1/n:.3f}  hit@5={hit5/n:.3f}")
```

数据集是自包含的：**不需要**再下载上游 LoCoMo 即可完成上述评测。只有需要英文原问句做对照时，才按 `VERSION.json` 里的 `upstream.revision` 取上游数据，用 `qid` 对应。

### 用灵枢系统复现（可选）

本仓库自带一个**零上游依赖**的复现入口，clone 后直接跑即可：

```bash
python -m md_cg.bench_locomo_zh_public
```

它把 `corpus567.jsonl` 灌入灵枢记忆库、用 `questions500.jsonl` 检索，打印
hit@1 / hit@5 / MRR 与分题型明细。下方「参考量级」的 93.6% / 97.6% 就是这条
命令的产出（池 567 / 题 500，jaccard 词法口径）。

> 这只是「**用作者的系统跑作者的数据集**」，是**自复现**，不是第三方复现；它
> 证明的是数据可跑通、参考量级可重放，**不构成横向对比声明**。请以你自己系统
> 跑出的数字为准。

---

## 参考量级

仅供建立量级感，**不是排行榜，也不是第三方复现结果**：

| 参考点 | hit@1 |
|---|---|
| 随机（每题平均 1.42 条 gold，池 567） | ≈ 0.25% |
| 灵枢系统自身口径：词法单路 | 93.6% |
| 灵枢系统自身口径：词法 + 同义扩展 | 97.6% |

> 上表后两行是**本仓库作者系统**在其自身检索口径下的实测（池 567 / 题 500）。**零干扰池下任何合理检索都容易得高分**，因此高数值不代表端到端记忆能力，也不可与有干扰基准横向比较。请以自己系统 + 自己口径跑出的数字为准。
>
> **口径性质**：该分数来自**写入侧结构化加工**后的检索（入库条目 = 身份 / 时间 / 摘要 / 词 / 条件四槽），而非对原始 turn 裸文本直读。这与主流记忆系统所用的**向量化嵌入、关键词/摘要压缩**属**同一类写入侧加工**——差异只在索引结构与检索算法，不在「是否对原文加工」。因此它可作为**同口径对照**的参考点。

---

## 诚实边界（必读）

1. **零干扰池**：567 条**全部**是 500 题的 gold 证据，池内不存在干扰项。因此"命中"远比真实场景容易——真实记忆库中绝大多数内容无关。**这一条最能限制结论外推。**
2. **查询是关键词串**，不是自然语言问句。它丢掉了原问句的语义意图（如 `What did the charity race raise awareness for?` → `慈善跑 心理健康 发声 意识 意义`），因此不适合评测意图理解、多轮改写等能力。
3. **无答案文本**：仅有 qrels，无法评测答案正确性。
4. **引用悬空**：`scene_3_q_58` 引用的 `scene_3_session_10_turn_19` 不在池中，故池为 567 而非 568 条。该题在池内无法被命中，属数据本身的已知缺陷。
5. **统计功效**：n=500 时单配置差异需约 **≥3.7%** 才超出抽样波动（题级命中率 CV 3.7%），更小的差异不显著，不要据此下结论。
6. **人物为虚构角色**：说话人来自 LoCoMo 原始数据集中的生成角色，非真实个人；但仍受上游许可约束。

---

## 许可与署名

本目录下全部数据文件适用 **CC BY-NC 4.0**（署名 — 非商业性使用）：
<https://creativecommons.org/licenses/by-nc/4.0/>

- 本集是 LoCoMo 的**派生作品**，因此**沿用上游许可**，**不适用本仓库根目录的 MIT 许可**。
- 商业性使用需要另行获得上游授权。
- 署名要求：请在使用、复制或分发时保留下列信息。

上游来源：

- LoCoMo — Maharana et al., *Evaluating Very Long-Term Conversational Memory of LLM Agents*, ACL 2024 (arXiv:2402.17753)
- 经 `mteb/LoCoMo`（BEIR 转制）获取，revision `02e2c3dea15d9fdfd1cd7a0f65f5f8ae2ed4c1ac`
- 中文派生层由本仓库生成

```bibtex
@inproceedings{maharana2024locomo,
  title     = {Evaluating Very Long-Term Conversational Memory of LLM Agents},
  author    = {Maharana, Adyasha and Lee, Dong-Ho and Tulyakov, Sergey and Bansal, Mohit and Barbieri, Francesco and Fang, Yuwei},
  booktitle = {Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics (ACL)},
  year      = {2024}
}
```

完整元数据（校验和 / 字段定义 / 抽样与复现说明）见同目录 [`VERSION.json`](VERSION.json)。
