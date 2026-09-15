# 认知图 MD 目录方案 · 设计文档

> 版本：v0.4（md 原生口径）| 2026-09-10 | 状态：**P0 25/25 + P1 37/37 全绿**
> 背景：用**结构化 md 文件 + 文件索引**替代 sqlite 存认知图。这不是"换存储引擎"，
> 而是让认知图回归它的**本征形态**——分层的条件注释目录。
> 依据：白箱智能五层记忆 + 条件代码图 CCG（三重注释范式）+ 第五篇"召回非全量/条件路由"。
>
> **v0.4 修订说明（去外部依赖）**：本仓库按「用新的 md 文档记忆库做验证」把
> `census`/`bench_p0`/`test_p0`/`test_p1` 全部改为 **md 原生**——不再依赖
> `wisdom-book-cloud-new.db` 与 `aeis.core`；数据来源统一为 `md_cg/corpus.py` 自建的
> 336 节点 md 语料（14 域 × 6 知识点 × 4 侧面）。因此 v0.2/v0.3 里的「3048 节点真实库」
> 数字（3037 桶 / 单例 99.9% / sqlite 对比）**已被同构自建库的实测替换**，
> 结论方向不变，量级按新库重标。被推翻的条款保留原文并标 `~~删除线~~`，便于追溯决策链。
> 代码位置 `md_cg/`（工作区顶层），验收 `python -m md_cg.test_p0` + `python -m md_cg.test_p1`。
>
> | v0.1 假设 | 实测结果（v0.4 自建 md 库：336 节点） | 修订处 |
> |---|---|---|
> | 四元组哈希分桶可用 | 336 桶/336 节点，单例桶 **100%**，等于全表扫 | §1 |
> | 桶内 LIKE 落空 → 桶内全扫即可 | 桶内全扫仍可能空，会**被分区误杀**返回空集 | §4 |
> | `_index.json` 读-改-写 + 全局锁 | 多进程实测**整批丢失 106/240 条**（v0.2 原库） | §6 |
> | 读节点时更新 access_count | 检索变写操作，破坏"检索只读"契约 | §7 |
>
> **v0.3 修订说明（P1 架构对齐）**：v0.2 只解决了「文件怎么存、怎么并发」，但对照白箱
> 四篇入门 + 第五篇记忆篇逐条审查，实现与认知图架构有 **9 处结构性错位**（v0.2 全部没有）：
>
> | v0.3 补全 | 依据 | 代码/验收 |
> |---|---|---|
> | CCG 5 要素（补**验证方式、不适用条件**） | 第 1 篇第 17 章；28%→88% 靠补不适用条件 | `nodefile.py` |
> | `verification_basis` 外部验证基底 | 第 2 篇第 7 章：能被验证才能被信任 | `nodefile.py` |
> | `rejected/` + `unresolved/` 负记忆目录 | 第 5 篇 L2「失败比成功值钱」/L5 | `mdcg.add_rejected/add_unresolved` |
> | 资格判定四态（ACCEPT/REJECT/DEFER/BLINDSPOT） | 第 1 篇核心：相似度不授予资格 | `judge_qualification` |
> | 指标改 Top-1/Top-5/盲区率 | 第 1 篇第 9 章（96/96） | `test_p1` 维度4 |
> | 两阶段并行收敛路由（14 大域→域内） | 第 3 篇第 4 章 56 学科卡→14 大域 | `routing.big_domain_classify` |
> | 信息差 D(t,C) 与 d²D/dt² | 第 4 篇 + 第 3 篇附录 | `reflect`/_reflection.jsonl |
> | 知识飞轮（误差→找漏条件→验证→更新） | 第 2 篇第 8 章 | `flywheel_step` |
> | 五大单元补齐（反思/验证/输出） | 第 3 篇第 13 章 | `reflect`/`verify` |

---

## 0. 核心判断

**认知图本来就该是"目录 + 条件注释"的文件结构，sqlite 是权宜（把它塞进关系表）。**
- 五层记忆（layer）→ 目录层级。
- 条件路由（召回非全量）→ 目录分区 = 条件索引。
- CCG 条件注释（5 要素：适用条件/子功能/执行/验证方式/不适用条件）→ 每个节点的统一格式。
- md 文件 → 可审计/diff/共享/零依赖（D-005）。

**md 替代 sqlite = 迁回认知图本征形态**，而非"换一个存储"。

---

## 1. 目录分层 Schema

```
<ROOT>/                      # 认知图根（如 ~/.agent-memory/ 或 AEIS/data/lingxu-cg/）
├── _index.json              # 自描述：schema_version、各层节点 id→相对路径 索引
├── anchor/                  # 锚点层（不可遗忘，保护）
│   ├── node_<id>.md
│   └── ...
├── structural/              # 结构层（协议/自我/信任）
├── knowledge/               # 知识层（经验学习，主检索层）
│   ├── condition_<hash>/    # ★ 条件分区（按 condition_space 键归一化分桶）
│   │   ├── node_<id>.md
│   │   └── ...
│   └── orphan/              # 无条件/未归桶的
├── rejected/               # v0.3 负记忆 L2：被证伪假设（importance=0，不参与正排打分）
├── unresolved/             # v0.3 负记忆 L5：未解问题清单（驱动主动探索，见 §2.2）
├── contextual/              # 情境层（短期，可衰减/淘汰）
└── self/                    # 自我层（自我模型/信任状态/盲区）
```

**分层原则**：layer → 目录；condition_space → 知识层内的条件分区子目录。
`rejected/` 与 `unresolved/` 在五层之外，**不参与正向评分**，只作覆盖标记 + 防御再犯（§2.2）。

### 1.1 分桶键：为什么不能用四元组哈希（实测证伪）

> ~~分区粒度：条件空间四元组 `(observation_position, observation_tool, time_window, existence_constraint)`
> → 归一化哈希 → `condition_<hash>/`。~~

在自建 md 库 336 个节点上做分桶键普查（`md_cg/census.py _md_cg_p0`），四元组哈希**完全退化**：

| 方案 | 分桶键 | 桶数 | 最大桶占比 | 单例桶率 | 期望扫描占比 |
|---|---|---|---|---|---|
| A | 原始四元组哈希（v0.1） | **336** | 0.3% | **100%** | 100% |
| B | 三元组（排除 time_window） | **336** | 0.3% | **100%** | 100% |
| C | 双元组（position + tool） | **336** | 0.3% | **100%** | 100% |
| D | **归一化域键（采用）** | **14** | 7.1% | **0.0%** | **7.1%** |

根因：`observation_position` 字段里嵌了**实例名**（如「知识点（二分查找）」），
取值数 ≈ 节点数，一个节点一个桶 = 每次检索都退化成全表扫，
"条件路由非全量"的收益归零。另三个字段则**信息量过低**、无法承担分区：
`observation_tool`/`existence_constraint` 100% 集中于单值、`time_window` 唯一率 57.7% 但仍是实例级取值。
（v0.2 在 3048 节点真实库上测得同一结论：A 方案 3037 桶 / 单例 99.9%，D 方案 90 桶 / 2.0%。）

**v0.2 分桶键**（`routing.route_key`）：
1. 优先取 `tags` 里的 `domain:` 前缀值（写入侧显式声明的领域）；
2. 回退到 `observation_position` **归一化后**的域名——剥离「知识点（xxx）」的实例名尾巴
   与「内容（按骨架填充）」类后缀，把 3033 种实例名收敛成 90 个域；
3. 都取不到 → `orphan/`。

目录名 = `cond_<可读域名>_<sha256短哈希>`（如 `cond_计算机科学_36855ea8`），
保留可读前缀便于人工审计，短哈希避免非法路径字符与重名。

### 1.2 分桶健康度必须是可自检指标

分桶键退化是**静默故障**——功能全对、只是慢，不会报错。因此把健康度做成
`MdCG.health()` 的常驻自检（`routing.bucket_health`），三条判据任一触发即判定退化：

- 巨桶：最大桶占比 > 30%（分区没起作用）
- 碎片化：单例桶率 > 50%（键含实例级字段，即 v0.1 的病）
- **期望扫描占比 `Σvᵢ²/n²` > 30%**（核心指标：随机一次查询的期望扫描比例）

期望扫描占比是唯一能同时抓住"巨桶"和"碎片化"两种退化的单一标量，
P0 验收直接断言它 < 10%（自建 md 库实测 7.1%；v0.2 真实库 2.0%）。
- 这是**条件路由的物理索引**：查询"当前情境满足什么条件"→ 直接进对应 `condition_<hash>/`，**非全量**。

---

## 2. 节点文件格式（单个 .md）

每个节点 = 一个 `.md`，**YAML frontmatter = 结构化字段，正文 = content（可带 CCG 注释）**。

```markdown
---
id: node_xxx
layer: knowledge            # anchor|structural|knowledge|contextual|self
modality: text
importance: 0.8
confidence: 0.6
condition_space:
  observation_position: 感知系统
  observation_tool: 图像识别
  time_window: [1788..., 1789...]
  existence_constraint: 协议实例运行中
tags: [vision, subpart, head]
spatial: {bbox: [217,51,605,310]}     # 可选
temporal: 1788612...
created_at: 1788612...
semantic_coordinates: {}              # 可选
state_attributes: {modality: image}   # 可选
entity_id: null
verification_basis: test              # v0.3：外部验证基底（compiler|test|measurement|formal_proof|data|other）
non_applicable_conditions: [ ... ]    # v0.3：能力级不适用条件（28%→88% 的关键）
access_count: 0
last_access: 0
---
# 功能名：head 部件识别
# 生效条件：白箱观测域含 subject=人物，view_distance=全身
# 子功能：bbox 定位 → 前景占比 → 白箱四态判定
# 执行：返回 {bbox, verdict, fg_ratio}
# 验证方式：由 vision 流水线测试记录验证
# 不适用条件：人物被遮挡 >70% 时
[正文 content ...]
```

**CCG 注释标记**（`MARKS`）：`功能名`/`生效条件`/`子功能`/`执行`/`验证方式`/`不适用条件`——
正文用 `# 功能名：...` 风格。**v0.3 由 4 要素补为第 1 篇第 17 章的标准 5 要素**
（适用条件/子功能/执行/验证方式/不适用条件），正文里的功能名行保留作人读标题。
`nodefile.ccg_completeness` 按 `CCG_REQUIRED` 校验完整度；完整度不全 → 检索资格判 **BLINDSPOT**。
注意：**功能名可以省略（条件隐含）**，但**不适用条件与验证方式不可省略**——反例缺失直接毁资格判定。

> 白箱视角：每个节点既是"可审计的条件注释"（CCG），又是"可检索的 md"。**
> 这是比竞争插件（deja-vu/noema 只是"存内容"）更强的理论根基。

**解析实现注意（`md_cg/nodefile.py`）**：frontmatter 与正文的分隔**只切第一个 `\n---\n`**。
朴素实现按 `---` 做 split，遇到正文里含 `---`（Markdown 分隔线，真实数据里很常见）
会把正文误当成 frontmatter 边界，**导致该节点所有字段静默丢光**。
另外 frontmatter 的值统一用 JSON 序列化（而非手写 YAML），避免中文、冒号、
嵌套 dict/list 的转义歧义——零依赖前提下这是唯一可靠的做法。

### 2.1 资格判定与性能 tier 正交（v0.3 核心，白箱第 1 篇）

v0.2 的检索只有 **tier（怎么找到的，性能维度）**；v0.3 补齐 **state（该不该用，资格维度）**。

```
资格四态（judge_qualification，与 tier 完全正交）：
  BLINDSPOT   CCG 要素不全 → 无法建立可靠归属，停止猜测
  REJECT      不适用条件命中 → 明确不适用
  DEFER       要素齐全但缺验证基底 → 信任根基不足，可继续寻找缺失条件
  ACCEPT      要素齐全 + 不适用条件未命中 + 验证基底已声明 → 有资格执行

性能 tier（怎么找到的）不变：T0 桶内 LIKE → T1 桶内扫描 → T2 全库 LIKE → T3 全库扫描
```

- 一条 REJECT 结果照样可以 tier=T0（性能上最快找到它）；一条 ACCEPT 结果也可能 tier=T3
  （兜底捞出来的）。**性能优化不能越过资格裁决**——这正是白箱与向量相似度检索的分野：
  相似度给出候选，资格给出"是否该执行"。
- 检索默认对每条结果做资格判定（`search(..., judge=True)`），调用方拿到 `(node, score, state)` 三元组。

### 2.2 负记忆目录（v0.3，白箱第 5 篇 L2/L5）

在五层之外加两类**负记忆**目录（它们不参与正排打分，只作为覆盖标记 + 防御再犯）：

```
rejected/      # L2 失败记录：被证伪的假设。MARKS：假设/否决原因/验证（importance=0，检索不优先）
unresolved/    # L5 未解问题清单：驱动主动探索。MARKS：问题/已知线索/目标
```

- `add_rejected` 按假设内容哈希去重 → **重复证伪幂等**，同一条负记忆不会越存越多。
- 检索时若查询词命中 rejected/unresolved 层 → meta 返回 `covered_neg`（该查询已被负记忆覆盖），
  提示调用方：这条路不用再试。
- `verify(node, evidence, verdict)`：`falsified` 裁决会把节点**移入 rejected/** 并删除原节点；
  `confirmed`/`weakened` 按非对称步长调 confidence（反例权重 > 正例，白箱第 5 篇纪律）。

### 2.3 两阶段并行收敛路由（v0.3，第 3 篇第 4 章）

`routing.big_domain_classify(terms)`：query 词对 **14 个大域**（数学/物理/化学/生物/计算机/
语言/历史/地理/艺术/经济/心理/医学/工程/通用）并行打分 → 收敛到 top-1；无命中词返回 None
（不强行收敛，走原桶路由）。`search` 的 meta 自报 `big_domain` + 完整打分明细，供白箱审计。

```
阶段1：query 词 → 14 大域并行评估 → 收敛 top-1（≈56 学科卡 → 14 大域）
阶段2：在该大域的情境键下路由桶 → 域内 KCCS 检索（桶内 LIKE → …）
```

### 2.4 认知循环单元（v0.3，第 3 篇第 13 章 + 第 2/4 篇）

sqlite 版只有"记录"；md 版补齐五大单元中缺失的四个：

- **反思 `reflect(query, results, feedback)`**：记录本次查询的信息差 D(t,C)
  `= 1 - ACCEPT 命中率`，写 `_reflection.jsonl`；同时计算 `dD/dt` 与二阶 `d²D/dt²`
  （= 白箱"情绪"信号，第 3 篇附录）。
- **验证 `verify(...)`**：见 §2.2。
- **输出 `search`**：调用方是最终裁决者，但白箱给出 `(score, state, basis)` 让它可审计地决定。
- **知识飞轮 `flywheel_step(error_report)`**：误差 → 把"可能漏掉的条件"解析为 unresolved 条目
  → 等外部验证 → 补条件分支（第 2 篇第 8 章的学习闭环）。

---

## 3. 边（edges）表达

认知图有边（part_of/causal/sequential/spatial/hierarchical/similar）。md 方案两种承载：

**方案 A：节点内引用（推荐，简单）**
每个节点 frontmatter 加：
```yaml
edges:                      # 出边
  - {target: node_y, type: part_of, confidence: 0.7, verified: 0}
  - {target: node_z, type: similar, confidence: 0.6, verified: 0}
```
**方案 B：独立边索引文件**（图查询强时用）
```
edges/<relation_type>/
  ├── node_x.md    # 内容 = [node_x 的所有出边列表]
  └── ...
```
认知图当前以节点为锚（part_of 树/联想），**方案 A 足够**（节点内引用即图的存储）。图遍历时
加载节点→读其 edges 字段→递归。

> 折中：节点内出边 + `_index.json` 建**反向引用索引**（target→source），图遍历/一致性校验用。

---

## 4. 条件路由索引（召回非全量，对齐现有 search_content）

现有 `search_content` 是：多词 OR LIKE 预筛 + 同义词 + 二元组 Jaccard + 层过滤 + 回退全表。
**md 版把它落地为文件索引**，保持"非全量"：

```
~~查询流程（v0.1，已修订）：
  query
    ↓ expand_query_terms（同义词扩展）
    ↓ 条件路由：当前情境 condition_space 归一化 → 定位 condition_<hash>/ 目录（★非全量）
    ↓ 文件索引：_index.json（node→path）+ 内存 dict
    ↓ content LIKE / tags 预筛（读候选目录的 md 文件，非全库）
    ↓ 降级：LIKE 落空 → condition_<hash>/ 全桶二元组 Jaccard（非全表）
    ↓ 评分：原查询二元组重叠率 (召回导向) 排序 → 取 top-k~~
```

### 4.1 情境从哪来：`context` 必须是显式入参

v0.1 写的是"当前情境 condition_space"，但**没说这个情境是谁给的**。
sqlite 版 `search_content(query, layers, limit)` 签名里根本没有情境位——
若由检索层"猜"当前情境（比如取最近一条 contextual 节点），就等于凭空引入了
一个不可解释的隐式过滤器，同一个查询在不同时刻返回不同结果，白箱可审计性直接破产。

**v0.2 定义**：`search(query, layer, k, context=None)`，`context` 由**调用方显式传入**。

| `context` | 行为 | 实测 |
|---|---|---|
| `None`（默认） | **不做条件路由**，直接走全量阶梯，语义与 sqlite 版完全一致 | `bucket=None`，recall@10 = 100% |
| `{"tags": [...]}` 或 condition_space | 路由到对应桶，桶内优先 | 扫 24/336 = 7.1% |

即：**条件路由是可选加速，不是默认语义**。不传情境时行为与旧版逐字节对齐——
这保证 P2 替换 sqlite 分支时是零风险的等价替换，加速是调用方主动选择的增量。

### 4.2 回退阶梯 T0–T3：分区绝不能误杀召回

v0.1 的降级只有一层（"桶内 LIKE 落空 → 桶内全扫"），**桶内全扫仍然可能为空**——
此时若返回空集，就把"条件分区"这个纯粹的性能优化，变成了会改变召回结果的语义过滤器。
一个本来能被 sqlite 召回的节点，只因为情境标签不匹配就查不到了，这是不可接受的。

**v0.2 四级阶梯**（`mdcg.MdCG.search`，结果自报命中层级 `meta["tier"]`）：

| tier | 范围 | 手段 |
|---|---|---|
| `T0_bucket_like` | 路由桶内 | 同义词扩展 + LIKE 预筛 |
| `T1_bucket_scan` | 路由桶内 | 全桶二元组 Jaccard |
| `T2_global_like` | **全库** | 同义词扩展 + LIKE 预筛 |
| `T3_global_scan` | **全库** | 全量二元组 Jaccard（兜底，永不返回空） |

三条硬性约束（均已进 P0 验收）：

1. **推进判据是「有效结果数」而非「候选数」**。按候选数判断会在 T1 停住：
   桶内全扫总有候选（整桶都是候选），但它们的 Jaccard 得分可能全是 0。
   必须以 `score > 0` 的结果数是否够 k 来决定是否继续下探。
2. **T2 的截断顺序不能改**。实现时若为省事先按 importance 取 top-500 再做 LIKE，
   recall@10 实测**从 100% 掉到 4%**——因为 LIKE 命中项大多不在 importance 前 500。
   必须在**全部候选**上先 LIKE、再截断，等价于 sqlite 的 `WHERE ... LIKE ... LIMIT`。
3. **每个结果自报 tier**。调用方（和审计者）必须能知道这条结果是路由命中的还是兜底捞的。

实测：路由桶不存在（`domain:根本不存在的域xyz`）时直接落 T2 并正常返回，不返回空；
桶内查不到的词（`量子色动力学夸克禁闭`）落到 T3 仍有结果。

### 4.3 性能实测（`md_cg/bench_p0.py`）

自建 md 库（336 节点，情境正确）三路对比（中位 ms）：

| 场景 | 耗时 | 相对 |
|---|---|---|
| T0 条件路由（桶内，扫 24/336） | **1.1 ms** | 基准 |
| T2 全量 LIKE（无 context） | 13.9 ms | **12.4x** 慢于 T0 |
| 朴素全库读盘扫描（无索引上界） | 7.1 ms | **6.3x** 慢于 T0 |
| 路由未命中（回退 T2） | 0.91x | 白付一次桶扫描 |
| 写入吞吐 | **1862 节点/秒** | — |
| 重建索引（336 节点） | 25.0 ms | — |

> 命中与未命中必须**分开统计**——混在一起算中位数会把 12x 的加速稀释成看不出来的数字。
> 小库（336 节点）上朴素读盘受 OS 页缓存保护（≈7 ms），索引收益被**低估**，结论要到大库复测才算数。
> （v0.2 在 3048 节点真实库上测得的旧口径：路由命中 18.4x、无 context 183ms vs sqlite 161ms、写入 1887 节点/秒。）
> 写入吞吐的关键是**默认不 `fsync`**（`atomic_write(durable=False)`）：崩溃一致性由
> `os.replace` 的原子 rename 保证，逐次 fsync 会把吞吐压到 17 节点/秒（慢 111 倍）。

**索引层**：
- `_index.json`：`{node_id: rel_path, tags: {...}, layer: {...}, cond_bucket: {...}}`——主索引（内存 dict）。
- 内容检索：读目标分区目录的 md → 内存中做 LIKE/二元组 Jaccard（分区内，非全库）。
- 层过滤 / 最近上下文：读 `contextual/` 目录按 `created_at` 排序（目录=天然层索引）。

**关键：召回优先走分区，但分区永不截断召回**——先条件路由（加速），命中不足自动下探到全量兜底。
这既是第五篇"不要把整个记忆塞给 AI"，也保证了不会因为分区而漏召回。

---

## 5. 数据来源与迁移

**v0.4 起本仓库不再内置 `migrate.py`**：验收改为直接用**新的 md 文档记忆库**，
不再读 `wisdom-book-cloud-new.db`。数据由 `md_cg/corpus.py` 生成——14 域 × 6 知识点 × 4 侧面
= 336 个节点，`corpus.seed(cg, marks=True)` 写入完整 CCG 正文（P0 用），
`marks=False` 写入纯叙述正文（P1 用，模拟"旧库迁移来的、只有正文没有 MARKS 的节点"）。
测试前 `corpus.reset_root(root)` 清空，保证「重跑 ≡ 首跑」。

未来若要真正从 sqlite 迁移，设计要点保留如下（不再依赖本仓库代码）：

```python
# 1. 读现有 sqlite nodes/edges
# 2. 对每 node：
#    a. 按 layer 定目录（anchor/structural/knowledge/contextual/self）
#    b. 按 routing.route_key 归一化域键 → knowledge/cond_<域>_<hash>/
#    c. 生成 .md（frontmatter 全字段 + CCG 正文）
# 3. edges → 写回各节点的 edges 字段（方案A）
# 4. 建 _index.json（node→path/tags/layer/cond_bucket）
# 5. 校验：节点数等价 + 【全量】字段等价（content/tags/importance/edges）
```

**幂等性**：迁移按 node id 原子覆盖写，可反复执行，**不需要先清空目录**。
（这不只是便利：清空目录依赖 `rmtree`，在有安全策略的环境下会被拦截，
而"必须先删除才能重跑"的迁移脚本本身就是个脆弱设计。）

**校验必须全量，不能抽样**：~~抽样 10 节点字段等价~~ → 应**逐个**比对
`content/tags/importance/edges`。迁移是一次性不可逆动作，
抽样 10 个只能证明"没有系统性错误"，证明不了没有个别节点损坏
（例如正文含 `---` 分隔符会让朴素的 frontmatter 解析器丢光所有字段——
这个缺陷要靠全量校验才暴露得出来，见 §2 注）。

---

## 6. 并发写（重点，灵枢多进程）

sqlite 已有"写锁"（多进程共享库）。md 方案需**文件锁**替代：
- 用 `fcntl.flock`（Unix）/ `msvcrt.locking`（Windows）做跨进程锁（`fsutil.FileLock`，超时 best-effort 放行）。
- 每个节点写入 = 唯一命名临时文件 + `os.replace` 原子 rename（Windows 下补短重试规避 `PermissionError`）。
- 节点文件可并行（不同节点不同文件）；**索引更新则不能用"锁 + 读-改-写"**，见下。
- **回滚**：md 是文件，改错可 git/备份回滚（比 sqlite 更利于审计）。

### 6.1 索引不能读-改-写：实测丢失 106/240 条

> ~~**写优先级**：`_index.json` 更新要串行（写锁），节点文件可并行。~~

v0.1 方案是"拿全局写锁 → 读 `_index.json` → 改 → 写回"。6 进程 × 40 条实测，
**索引整批丢失 106/240 条**，而节点 .md 文件一个不少。诊断钩子抓到根因：
两个进程在各自的锁临界区内读到了**同一份过期快照**（`disk_in=59`），
后写的那个把前一个的整批结果覆盖掉了。

锁保证了互斥，但保证不了"读到的是最新版本"——进程 A 在拿锁**之前**就把
内存索引载入了，拿到锁后写回的是"旧快照 + 自己的增量"，A 之后的 B 同理。
这是读-改-写模式的固有缺陷，**跟锁的正确性无关，加再多锁也修不好**。

**v0.2：索引改为 append-only + 派生物**
- 各进程只**追加**自己的增量条目，永不读回全量再覆写。
- `_index.json` 降级为**快照（可选加速）**，`_index_log/` 是增量日志，
  两者都是**派生物**——任何时候都能从 md 目录全量 `rebuild_index()` 重算。
- 快照缺失/损坏时走**无副作用**的 `_scan_nodes()` 自愈，落盘只由
  `rebuild_index()` / `compact_index()` 显式负责（见 6.3）。

### 6.2 单文件 append 在 Windows 上不是原子的

改成 append-only 后仍每轮稳定丢 ~1 条：Windows 的 `O_APPEND` 不保证多进程并发追加的原子性。

**解法 `fsutil.ShardedLog`**：每个进程写**自己独占的分片文件**（`_index_log/<pid>_<uuid>.jsonl`），
物理上不存在跨进程写冲突；读取时把所有分片按 `(时间戳, 序号)` 排序回放。
这把"并发写同一文件"退化成了"并发写不同文件"，从根上消除竞态而不是靠锁去调度它。

### 6.3 启动期自愈不能有副作用

修完上面两条后，首轮仍丢 27/240。根因：worker 启动时若发现快照缺失就调 `rebuild_index()`，
而 `rebuild_index` 会 `clear()` 掉增量日志——**它清掉的是其它进程正在写的分片**。

原则：**读路径永远不写盘**。`_load_index()` 只做无副作用的扫描，
日志清理只在显式的维护动作（`rebuild_index` / `compact_index`）里做。

### 6.4 实测结论

3 轮 × 6 进程 × 40 条，按 **id 集合**精确校验（比只比总数更严格，能定位到是谁丢的）：
连续跑 3 次共 9 轮，磁盘与索引**均零丢失**。跨进程锁另有最小复现测试
`md_cg/test_lock.py`（6 进程 × 50 次计数，实测 300/300）。

> D-005：全部为标准库实现（`msvcrt`/`fcntl`/`os.replace`），零第三方依赖。

---

## 7. 可信度/权重维护（对齐现有字段）

节点的 `importance/confidence/access_count/last_access`——这些是**白箱可信度**（每层判定）。
md 里 frontmatter 存这些字段，`importance/confidence` 的更新 = 读-改-写该节点 md 的 frontmatter
（低频、由显式调用触发，可接受）。
- importance 提升（保护：不可遗忘记入 anchor/ 且受保护标记）。

### 7.1 检索绝不能变成写操作

> ~~access_count/last_access 递增（读节点时更新）——写入 _index.json 或节点 md。~~

v0.1 让检索去改节点 frontmatter，代价是：**一次只读查询会重写几十个 .md 文件**。
后果不只是慢——
- 破坏了"检索只读"的契约：并发检索会与写入抢锁、互相踩踏；
- 污染 mtime 与 git diff，`git log` 里全是"查了一下"的噪声提交，
  而**可审计正是 md 方案存在的理由**，自己把它毁掉说不过去；
- 读路径写盘 = 只读介质、只读挂载、并发只读副本全部不可用。

**v0.2**：`record_access` 只**追加**一行到 append-only 的 `_access_log`（一次小追加，
不碰任何节点文件），计数在读取时聚合。落盘到 frontmatter 只在显式维护动作
`compact_access()` 里批量做一次。

P0 验收对此有硬断言（取 200 个节点比对 mtime）：一轮检索后
**节点 .md 的 mtime 全不变、索引快照不重写、索引日志不增长**，只有访问日志增长。
`search(..., record=False)` 可完全关闭访问记录（基线对比时用）。

---

## 8. 优劣与风险

### 优势
1. **白箱可审计**：每个节点是 .md，直接可读/diff/共享（deja-vu/noema 验证此路线可行）。
2. **回归本征形态**：分层目录 + 条件注释 = 认知图本就该是的结构。
3. **零依赖 D-005**：纯标准库文件操作，无 sqlite 驱动。
4. **条件路由非全量**：目录分区 = 条件索引，召回不读全库。
5. **跨工具共享**：md 文件天然可被其他 agent 读（学 deja-vu/noema import）。

### 代价/风险（v0.4：md 原生口径）
1. **性能**：无 SQL 索引，靠内存 dict + 分区目录。**✅ 已 benchmark（自建 md 库 336 节点）**：
   T0 桶内 1.1ms vs T2 全量 13.9ms（**12.4x**）、vs 朴素读盘 7.1ms（**6.3x**），写入 1862 节点/秒。
   前提是分桶键健康（§1.1），退化时性能收益归零 → 已做成常驻自检。
2. **一致性**：无 sqlite 事务。**✅ 已解决**：原子 rename + append-only 分片日志，
   9 轮 × 6 进程零丢失。**注意 v0.1 的"锁 + 读-改-写"方案实测是错的**（§6.1）。
3. **迁移成本**：不再依赖外部数据库（本仓库已去 `migrate.py`）；未来真正迁移时仍需全量字段等价校验。
4. **范围**：这是**灵枢核心存储**的大改——**必须小原型验证稳定后再全量**。P0 已通过 25/25。
5. **索引是单点**（v0.2 新增）：`_index.json` 损坏会全盘不可用。
   → 已把索引降级为**纯派生物**：删掉/写入非法 JSON 均能从 md 目录完整重建（已进验收）。

### 方法论教训

四条被推翻的假设有一个共同点：**在纸面上都是自洽的，只有跑在真实数据/真实并发上才暴露**。
- 分桶键退化：靠"看起来合理的四元组"推导，没看过 `observation_position` 的实际取值分布。
- 索引丢数据：锁的正确性推理是对的，但读-改-写的窗口不在锁能覆盖的范围内。
- 且这两个故障都是**静默**的——不报错、结果"看着对"。

所以 P0 的产出不只是代码，还有**能抓住静默故障的度量**：期望扫描占比、tier 自报、
id 集合级的并发校验、mtime 只读断言。没有这些指标，同样的错误会在 P2/P4 重新犯一遍。

---

## 9. 分阶段实施（稳健）

| 阶段 | 做什么 | 验证 | 状态 |
|---|---|---|---|
| **P0** | 小原型：md 目录 + 索引 + 条件路由检索 + 四风险处理 | 25 项验收（下表） | **✅ 25/25 通过** |
| P1 | 白箱认知架构 9 维度对齐（md 原生语料）| 37 项验收 | **✅ 37/37 通过** |
| P2 | 接入真实检索（替换 search_content 的 sqlite 分支）| **同查询集 recall@k 对比**，而非"结果一致" | **✅ 10 查询 avg recall@10 = 100%** |
| P3 | 并发锁 + benchmark + 回滚 | 多进程写零丢失 + 性能达标 | **✅ 9 轮×6 进程零丢失；12.4x/6.3x** |
| P4 | 全量切换（sqlite 可双写过渡）| 全量回归 | ⬜ 未开始 |

> **P2 验收标准修订**：v0.1 写的"检索结果与 sqlite 版一致"是不可达标的——
> 两套实现的浮点评分与排序 tie-break 不可能逐位相同，按字面执行会永远卡在 P2。
> 改为**同查询集的 recall@k 对比**（无 context 时应 ≥ 0.9，实测 100%），
> 这才是真正要保证的东西：不漏召回。

**P0 验收覆盖（`md_cg/test_p0.py`，25 项）**
- 风险1 分桶键：自建 md 语料完整落盘、分区健康度自检、期望扫描 < 10%、**原方案能被自检判定为退化**
- 风险2 情境入参：无 context 不路由 / 有 context 命中桶、扫描量 < 全库 10%、写查两侧路由键同构
- 风险3 回退阶梯：桶内落空不返回空、结果自报 tier、不存在的桶落到全量
- 风险4 只读契约：200 节点 mtime 不变、索引快照/日志不写、访问计数走 append-only、compact 后落盘并截断
- 附加：索引删除可重建、索引损坏可自愈、多进程磁盘与索引均无丢失、基线 recall@10

> **原则（大的修改要小心）**：P0 原型先证明"稳定+有效"，再逐阶段扩。真正切换时 **sqlite 保留做双写/回滚**，确认 md 稳定后才切。

---

## 11. 代码索引（P0+P1 实现）

| 文件 | 职责 |
|---|---|
| `md_cg/routing.py` | 分桶键归一化、桶目录命名、**分区健康度自检**、`route_key`/`big_domain_classify`（14 大域并行收敛，§2.3） |
| `md_cg/fsutil.py` | 原子写、跨进程锁、**ShardedLog** 分片追加日志 |
| `md_cg/nodefile.py` | frontmatter 序列化/解析、**CCG 五要素**完整度（`ccg_completeness`/`CCG_REQUIRED`）、`verification_basis` 校验 |
| `md_cg/mdcg.py` | `MdCG` 主类：add/get/search（T0–T3 阶梯 + 资格判定三元组）/judge_qualification 四态/add_rejected/add_unresolved/reflect（D 与 d²D）/verify（非对称步长）/flywheel_step/last_d/health/索引重建 |
| `md_cg/corpus.py` | **自建 md 语料**（14 域 × 6 知识点 × 4 侧面 = 336 节点；`seed(marks=True/False)`、`reset_root`；P0/P1 共用，去外部数据库） |
| `md_cg/census.py` | md 原生分桶键方案对比普查（A/B/C/D） |
| `md_cg/test_p0.py` | 25 项验收（含 `--worker` 并发子进程入口） |
| `md_cg/test_p1.py` | **37 项 P1 白箱架构验收**（9 维度：CCG5 要素/验证基础/负记忆/四态/指标/两阶段路由/信息差/飞轮/循环单元） |
| `md_cg/bench_p0.py` | md 原生性能基准（路由命中/未命中分开统计，对比 T2 全量与朴素读盘） |
| `md_cg/test_lock.py` | 跨进程锁最小复现 |

---

## 10. 与竞争项目对照（为什么这么做是对的）

| | deja-vu | dsh-noema | 本文案 (md认知图) |
|---|---|---|---|
| 存储 | Go 二进制索引 | 可检查 Markdown | **可检查 md + CCG 注释** |
| 非向量 | ✅ | ✅ | ✅ |
| 召回 | 索引检索（非全量）| 开工前 recall | **条件路由（分区命中，非全量）** |
| 可审计 | 索引 | ✅ 文件 | ✅ 文件 + 条件注释更强 |
| 理论根基 | 无 | 无 | **白箱五层 + 条件路由 + CCG** |

**本方案优势**：md 的可检查性（学 noema）+ 非向量轻量（学 deja-vu）+ **我们独有的条件路由/CCG 白箱根基**——这是竞争项目没有的理论深度。

---
*（v0.4：P0 25/25 + P1 37/37 全绿。跑法（md 原生，无外部数据库）：
`python -m md_cg.test_p0`（生成 `_md_cg_p0`）→ `python -m md_cg.census _md_cg_p0` →
`python -m md_cg.bench_p0` → `python -m md_cg.test_p1`。
P1 把 v0.2 的"文件存储/并发"实测扩展为**白箱认知架构 9 维对齐**：CCG 5 要素、验证基础、
负记忆目录、资格四态、Top-1/Top-5/盲区指标、14 大域并行路由、信息差 D 与 d²D、知识飞轮、
五大认知循环单元。下一步 P4 全量切换前，建议先做 sqlite/md 双写过渡期。）*
