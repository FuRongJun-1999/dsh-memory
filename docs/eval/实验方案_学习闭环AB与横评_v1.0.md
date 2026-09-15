# 实验方案 · 学习闭环 A/B 与外部横评 v1.0

> 目的：回应 GPT 的两条核心批评——
> ①「Knowledge Evolution ≠ Learning」（缺「记忆→提升」的**因果**证据）；
> ②「自定义指标多、缺外部 baseline」（缺**横评**）。
>
> 本文件是**方案设计**，不含实验结论。执行前需先确认算力/标注资源与数据集授权。
> 例外：§E 是**先行冒烟实测记录**（环境可行性小样），不构成 §B 的对外横评数字。
> 日期：2026-09-12

---

## A. 学习闭环 A/B（证明 Memory → Learning → Improvement）

### A.1 设计（因果要求）

```text
同一初始状态
   ├── 实验组 A：记忆系统开启（mdcg 正常写读）
   └── 对照组 B：记忆系统关闭（等价于纯上下文 / 无长期记忆）
        │
   同任务集：训练批（进记忆） + 测试批（不进记忆，只评估）
   分批推进：10 批 × 100 任务 = 1000 任务
        │
   每批后评估：测试批上的能力是否提升？
```

**关键纪律（防自欺）**：
- **测试批严禁写入记忆**——否则是「记住答案」而非「泛化能力提升」；
- A/B 用**同一模型、同一 token budget、同一采样参数**，仅记忆开关不同；
- 任务与指标需**预先注册**，不允许事后挑指标。

### A.2 指标与判据

| 能力 | 指标 | 基线（批 0） | 判据（1000 任务后） |
|---|---|---|---|
| 检索 | hit@1 | 记录 | 提升，且 A 组显著高于 B 组 |
| 推理 | 正确率 | 记录 | ↑ |
| 冲突处理 | 矛盾识别率 | 记录 | ↑ |
| **自我校准** | **ECE** | 记录 | **↓ 至 ≤ 0.15**（对齐 README §Gate） |
| 新任务泛化 | 测试批正确率 | 记录 | ↑（**核心判据**） |
| 记忆污染 | 错误知识留存率 | 记录 | ↓ |

**核心判据**：新任务泛化的 **A 组提升量显著 > B 组**（如配对检验 p < 0.05）。
若 A 组仅在「已见任务」上提升、测试批无提升 → 说明只是记忆回放，**Learning 不成立**（诚实结论）。

### A.3 最小可行版本（低成本先跑）

若 1000 任务成本过高，可先跑 **10 批 × 20 任务 = 200 任务** 的最小版本，
仅测「新任务泛化」与「ECE」两项，用于**证伪**（若连方向都没有，则不必做大）。

---

## B. 外部横评（vs 其它记忆系统）

### B.1 Baseline 清单

```text
Mem0          Letta(Zep)     GraphRAG
普通 Vector RAG    纯 Context Window（无记忆）
```

### B.2 控制变量

同一数据集 + 同一底层模型 + 同一 token budget + 同一上下文预算 + 同一任务集。

数据集（复用现有）：
- `LoCoMo-zh-500`
- `memory-bench-1000`

### B.3 指标矩阵

| 维度 | 指标 |
|---|---|
| 检索 | Recall / Precision / MRR |
| 答案 | Answer Accuracy |
| 鲁棒 | Contradiction Handling / Temporal Reasoning |
| 长期 | Memory Pollution / Long-term Drift |
| 成本 | Cost / Latency |

**诚实声明（沿用 README 立场）**：本仓现有自评指标**不构成横评声明**；
只有上述同条件对照产出的数字，才可作为对外比较依据。

---

## C. 复用现有 bench（避免重复造轮子）

| 脚本 | 用途 |
|---|---|
| `md_cg/bench_locomo_zh*.py` | LoCoMo-zh 检索命中 |
| `md_cg/bench_membench.py` | memory-bench |
| `md_cg/bench_longmem.py` | 长期漂移 |
| `md_cg/bench_task_ab*.py` | 任务级 A/B（**优先扩展此脚本承载 §A**） |

---

## D. 执行顺序建议（按性价比）

1. **A.3 最小闭环**（200 任务）——先证伪，成本最低，直接回应批评 ①；
2. **ECE 长样本验证**——把 `T-TRUST` 从 Lv2 推向 Lv3（缺口 6）；
3. **B 横评**——说服力最高、成本最高，放最后；
4. 概念精简（缺口 4）——收益难量化，暂缓。

---

## E. 先行冒烟实测记录（2026-09-12）

> 性质说明：本节是**环境可行性冒烟**——用 1 组中文对话语料（3 条事实）跑通「写入 → 检索」。
> **样本量不足以支撑任何对外横评数字**（§B 的指标矩阵仍需 LoCoMo-zh-500 等数据集）。
> 它解决的是另一件事：**前提确认**——四家能否在同一 embedding / LLM 条件下真实跑起来，
> 以及各自的「默认配置」里有哪些会直接毁掉中文记忆的坑。
>
> 脚本：`_eval/smoke_{mem0,graphiti,graphrag,letta}.py`（`_eval` 位于 `_competitor/`）。

### E.1 环境与口径

| 项 | 取值 |
|---|---|
| LLM | `deepseek-chat`（DeepSeek 官方端点；Letta 需绕行，见 E.4 ④） |
| Embedding | LM Studio 本地 `text-embedding-bge-m3`（1024 维，`http://127.0.0.1:1234/v1`） |
| 语料 | `_eval/corpus.py` 的 `DIALOG`（6 轮）/ `QUERIES`（fact / preference / relation 各 1 条） |
| 命中口径 | 返回文本**字面**含期望中文关键词（`corpus.judge`）；另人工复核**语义**正确性 |
| 版本 | mem0 2.0.20 / Graphiti 0.30.2 / GraphRAG（monorepo, uv workspace）/ Letta 0.16.8 |
| 基础设施 | Neo4j 5（Graphiti）、PostgreSQL 16 + pgvector（Letta） |

### E.2 结果

| 系统 | 写入 | 抽取产物 | 字面命中 | 语义正确 | 检索耗时 |
|---|---|---|---|---|---|
| mem0（默认） | 2.71s | 3 条，**全英文改写** | **1/3** | 3/3 | 0.03s |
| mem0（+中文锁定） | 2.51s | 3 条，全中文 | **3/3** | 3/3 | 0.03s |
| Graphiti | 4.09 / 4.52s | 4 实体，**2～3 条事实边** | **2/3 ~ 3/3** | 3/3 | 0.03–0.07s |
| GraphRAG · local | 索引 17.4s | 4 实体 / 3 关系 / 1 社区报告 | **3/3** | 3/3 | 1.16–2.16s |
| GraphRAG · global | — | 同上（仅用社区报告） | **2/3** | 2/3 | 1.11–2.83s |
| Letta | 3 轮对话 | human 块 3 条事实 | **3/3** | 3/3 | 0.06–0.11s |

### E.3 四条与选型直接相关的失败模式（本节主要产出）

1. **mem0 默认把中文事实翻译成英文** → 抽取产物为 `Zhang Wei` / `seafood` / `Xinggui`，
   中文关键词检索全部失效（字面 1/3）。语义仍正确，故**不是检索坏了，是保真坏了**；
   注入 `custom_instructions` 锁定中文后 3/3。→ 横评若不做语言控制，mem0 会被系统性低估。
2. **Graphiti 对「偏好 / 过敏」类事实的抽取不稳定，且会失真**。两次复跑：
   第一次「海鲜」只作为**实体**存在、无事实边（2/3）；第二次抽出边，但 fact 为
   「星轨项目与海鲜无直接关联，但用户提及对海鲜过敏」——**命中却语义扭曲**。
   → 比 miss 更危险；横评必须跑多次取分布，并人工审 fact 而非只看命中率。
3. **GraphRAG global 丢偏好**：社区报告只覆盖项目 / 会议类信息，`global` 因此答不出过敏问题；
   `local` 靠原始 text_unit 兜住。→ 两档检索能力不等价，横评需分档报告。
4. **Letta 的记忆落在 core memory block**，archival（passages）为空；core 读取极快（0.06s）
   但有容量上限。→ 与「向量库检索」不是同一机制，不宜只按延迟同台比较。

### E.4 复现所需条件（踩坑结论，均为反证确认）

1. **GraphRAG 社区报告**：DeepSeek 拒绝 `response_format.type=json_schema`（400
   `This response_format type is unavailable now`），而 `community_reports_extractor.py`
   原用 pydantic 模型 → 索引在 `create_community_reports` 崩溃（下游显现为 `KeyError: 'community'`）。
   已改为 `response_format_json_object=True` + 本地结构化解析。
2. **Letta 服务端硬依赖 Postgres + pgvector**：`letta/server/db.py` 模块级 engine 取
   `settings.letta_pg_uri`（**带默认值**），故 `database_engine=SQLITE` 也不能启动 REST 服务端；
   需 `alembic upgrade head` 先建表，且容器内要有 `vector` 扩展（缺 `pg8000` 同步驱动也会失败）。
3. **Letta agent 必须显式挂载 `memory_blocks`**：0.16.8 不再默认附带 persona / human，
   缺省时 `memory_insert` 报 `Block field human does not exist (available sections = )`，
   agent 沦为「无记忆体」（`blocks_agents` 与 `archival_passages` 均为 0）。
4. **Letta LLM 需显式 `llm_config`**：DeepSeek `/v1/models` 现仅返回 `deepseek-flash` /
   `deepseek-v4-pro`，句柄式 `deepseek/deepseek-chat` 解析失败（`available_handles=[]`）；
   显式 `llm_config` 可绕过 `provider_models` 句柄表直连。
5. **mem0 两组不可并发**：`~/.mem0/migrations_qdrant` 是固定路径的本地 qdrant，
   并发即加锁冲突（`Storage folder ... already accessed by another instance`）→ 双组须串行。

### E.5 与 §B 的衔接

本节把 §B「控制变量」清单补成可执行版：除模型 / 预算 / 任务集外，还须**控制并报告**
（a）记忆写入语言是否被改写；（b）抽取运行次数（取分布而非单次）；
（c）GraphRAG 的 local / global 分档；（d）各系统「记忆」的载体类型
（core block / 图谱边 / 向量库）——否则数字不可比较。
