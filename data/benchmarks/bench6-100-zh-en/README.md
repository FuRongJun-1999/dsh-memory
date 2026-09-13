# bench6 · 六家记忆系统横评题集（100 题 · 中英双查）

> 100 道查询（每题**中英两套词面**）/ 137 条被检索 turn（**全部为 gold 证据**）/ 约 90 KB
> 用于在同一题面上对照**中英两种查询语言**下各记忆系统的检索命中（hit@1 / hit@5 / MRR）
> 许可：**CC BY-NC 4.0**（派生自 LoCoMo，见文末）

---

## 这是什么

从本仓库已公开的 [`locomo-zh-500`](../locomo-zh-500/) 派生的小型**中英双查**题集：

- 从 `locomo-zh-500` 的 500 题中按 `qtype` 分层抽样 100 题（最大余额法，`seed=7007`；配额 `single_hop 43 / adversarial 23 / temporal_reasoning 16 / multi_hop 14 / open_domain 4`）。
- 被检索池 = 这 100 题 gold 引用 turn 去重后的 **137 条**（悬空引用 0 条）。
- 每题给**两套查询词面**：`question_zh`（中文关键词串）与 `question_en`（英文自然问句），两套 `evidence_turns` **逐字一致**。

**它评测什么**：同一批 gold 证据、同一个池，换查询语言后，系统能否仍把证据 turn 排进前 k。

**它不评测什么**（务必先读）：

- **不是 QA 评测集**——无答案文本，只有 qrels，无法评测答案正确性。
- **不是端到端记忆能力分数**——池内零干扰（全是 gold），指标是**上界**。
- **不是榜单**——`results_v1.0.json` 是本仓库作者在自定口径下的实测快照，供核对数字，不构成第三方复现。

---

## 文件与字段

### `manifest.json` —— 口径元数据

抽样方法 / seed / 分层配额与实际 / 池规模与悬空引用 / 诚实边界。其中 `source` 均为**仓库内相对路径**。

### `pool.jsonl` —— 被检索池（137 行）

```json
{
  "id": "scene_0_session_11_turn_14",
  "speaker": "Caroline",
  "date": "02:24 PM on Monday 14 August, 2023",
  "text": "英文原始陈述（上游 LoCoMo 内容）",
  "ingest": "[<id>] 英文原始陈述 [会话时间]（六家逐字同源的写入文本）"
}
```

`id` 必须**原样保留**：它是与 `questions.jsonl` 的 `evidence_turns` 对齐的唯一检索键。

### `questions.jsonl` —— 查询 + qrels（100 行）

```json
{
  "qid": "scene_0_q_105",
  "qtype": "single_hop",
  "question_zh": "Becoming Nicole 简介 信仰 支持 希望",
  "question_en": "What did Caroline take away from the book \"Becoming Nicole\"?",
  "evidence_turns": ["scene_0_session_7_turn_13"]
}
```

### `results_v1.0.json` —— 六家实测快照（机器可读）

结构：`{k, arms:{<臂名>:{langs:{zh|en:{summary:{hit@1,hit@k,mrr},n_empty,n_unmapped,unmapped_rate,seconds,per_question:[...]}}}}, missing, by_qtype_zh}`。

臂名：`lingshu_lex` / `lingshu_rrf4` / `lingshu_rrf4_noref` / `lingshu_lex_meta` / `lingshu_rrf4_nometa` / `vector_rag` / `mem0` / `graphiti` / `graphrag` / `letta_archival` / `letta_agent`。
其中「灵枢」多行为**同一支系统在不同检索口径**下的对照，非多套系统；`letta_archival`（直插）与 `letta_agent`（自主入库）为 Letta 两种写入模式，**不得**互相代表。

### `run_bench.py` —— 公开测试脚本（零第三方依赖）

- `python run_bench.py`：打印**六家中英对比主表**（含 zh−en 提升幅度），并做**口径自证**——用 `results_v1.0.json` 存档的逐题 ranks 重算全部 summary，与本脚本指标函数逐位比对（lingshu 各变体与 vector_rag 存有逐题明细，可证同源；四家竞品臂发表时仅存 summary，显式 SKIP）。
- `python run_bench.py --demo`：内置字符 bigram 词面基线实跑双查，演示 Adapter 协议。
- `python run_bench.py --adapter your_mod.YourAdapter`：接入**你自己的记忆系统**（实现 `ingest(records)` / `search(query, k) -> [id,...]` / `name` 即可，零框架绑定）。

> 人类可读的完整报告（口径 / 主表 / 分题型 / 归因 / 诚实边界）见
> [`docs/横评_六家100题中英双查_v1.0.md`](../../../docs/横评_六家100题中英双查_v1.0.md)。

---

## 怎么用

**最简通路（推荐）**：直接用公开测试脚本——

```bash
python run_bench.py                       # 主表 + 口径自证（零依赖）
python run_bench.py --adapter my_bench.MyAdapter   # 评你自己的记忆系统
```

Adapter 只需两个方法（完整协议见脚本 docstring）：

```python
class MyAdapter:
    name = "my-system"
    def ingest(self, records): ...        # records = pool.jsonl 全部行
    def search(self, query, k): ...       # 返回 [id,...] 按相关性降序
```

手写口径（与 `run_bench.py` 内联实现逐字同源）：

```python
import json

pool = [json.loads(l) for l in open("pool.jsonl", encoding="utf-8")]
questions = [json.loads(l) for l in open("questions.jsonl", encoding="utf-8")]

# 1) 灌库：id 必须原样保留，作为与 qrels 对齐的检索键
for t in pool:
    memory.add(id=t["id"], text=t["ingest"])

# 2) 中英双查：同一批题、同一个池，只换查询词面
def hit1(lang):
    hit = 0
    for q in questions:
        got = [h.id for h in memory.search(q["question_" + lang], k=5)]
        hit += bool(got and got[0] in q["evidence_turns"])
    return hit / len(questions)

print("hit@1  zh=%.3f  en=%.3f" % (hit1("zh"), hit1("en")))
```

数据自包含：**不需要**再下载上游 LoCoMo 即可完成评测。

### 用灵枢系统复现主进程臂（可选）

```bash
python -m md_cg.bench6_common --force   # 固化口径层（幂等）
python -m md_cg.bench6_arms             # 灵枢 5 口径 + 纯向量 RAG 基线
python -m md_cg.bench6_competitors --k 5   # 六家统一评分出表
```

> 四家 LLM 竞品臂（mem0 / Graphiti / GraphRAG / Letta）的适配脚本运行在评测工作区（各自 venv 隔离），**未随本仓库公开**；本仓库公开的是**口径层 + 题集 + 六家结果**，竞品数字可由 `results_v1.0.json` 逐题核对。
> 这只是「**用作者的系统跑作者的题集**」，是**自复现**，不构成横向对比声明。请以你自己系统跑出的数字为准。

---

## 参考量级（v1.0 快照 · 按英→中查询提升幅度降序）

| 系统 | en hit@1 | zh hit@1 | 英→中提升 |
|---|---|---|---|
| **灵枢·单词法** | 47.0% | **99.0%** | **+52.0pp** |
| 灵枢·词法+meta | 54.0% | 99.0% | +45.0pp |
| 灵枢·四路（真开 bucket） | 37.0% | 81.0% | +44.0pp |
| 纯向量 RAG | 71.0% | 97.0% | +26.0pp |
| Letta·归档直插 | 73.0% | 96.0% | +23.0pp |
| mem0 | 68.0% | 89.0% | +21.0pp |
| GraphRAG | 18.0% | 31.0% | +13.0pp |
| Graphiti | 46.0% | 58.0% | +12.0pp |
| Letta·agent 自主 | 0.0% | 0.0% | （全零壳臂，未返回可映射结果） |

> 数字为准仅作量级参照；**零干扰池下任何合理检索都容易得高分**，不可外推为端到端记忆能力。

### 中英对照结论（本脚本复现的核心发现）

**将查询由英文换为中文（英文语料与记忆系统均不变）：所有已有记忆系统的检索命中全部大幅提升（+12 ~ +52pp），无一例外**（唯一零值 `letta_agent` 为全零壳臂，未返回可映射结果，无提升可言）。**灵枢是最佳**：中文查询 hit@1 **99.0% 全表登顶**，且英→中提升幅度 **+52pp 亦为全表最大**——双语入库（中文层+英文原文）在中文查询下同时拿到最高命中与最大提升。

- 提升排序见上表；运行 `python run_bench.py` 即可从 `results_v1.0.json` 复现。
- **这是「查询词面敏感性」的实测**：查询语言/形态变化对检索命中的影响（+12~+52pp），大于多数系统之间的绝对差距。
- 归因仍须谨慎（诚实边界 2）：`question_zh` 为关键词串（保留英文专名与日期词）、`question_en` 为自然问句——中文提升混合了**语言**与**查询形态**双因素；内置词面基线在纯英文库上 `--demo` 会得到反向的 en>zh，说明**查询语言的优势取决于系统如何处理语料**，本脚本暴露的正是这个变量。

---

## 诚实边界（必读）

1. **池内零干扰**：137 条**全部**是 gold 证据 → 指标是**上界**，真实场景存在大量干扰 turn。
2. **`question_zh` 是中文关键词串**而非自然语言问句 → 评检索命中，**非 QA**。
3. **n=100 时题级命中率 CV≈8.3%** → **家间差距小于约 16% 不可下结论**；大落差（如 99% vs 0%）方可结论。
4. **竞品行序为各家自身返回顺序**，非统一重排——差异部分来自各家排序口径本身。
5. **Letta 两模式必须分开读**：`letta_archival` 直插保留来源标记，`letta_agent` 自主入库经 LLM 改写后丢失标记、在 id 回溯口径下不可回收（是**可追溯性**差异，不是检索能力差异）。
6. **人物为虚构角色**：说话人来自 LoCoMo 数据集的生成角色，非真实个人；仍受上游许可约束。

---

## 许可与署名

本目录全部数据文件适用 **CC BY-NC 4.0**（署名 — 非商业性使用）：
<https://creativecommons.org/licenses/by-nc/4.0/>

- 本集是 LoCoMo 的**派生作品**（经本仓库 `locomo-zh-500` 再派生），故**沿用上游许可**，**不适用本仓库根目录的 MIT 许可**。
- 商业性使用需另行获得上游授权。

上游来源：

- LoCoMo — Maharana et al., *Evaluating Very Long-Term Conversational Memory of LLM Agents*, ACL 2024 (arXiv:2402.17753)
- 经 `mteb/LoCoMo`（BEIR 转制）获取，revision `02e2c3dea15d9fdfd1cd7a0f65f5f8ae2ed4c1ac`
- 中文层与抽样口径由本仓库生成
