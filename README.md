# 让 AI Agent 拥有不可遗忘的记忆

**灵枢（Lingshu）** —— 高性能 · 无幻觉 · 多智能体适用的长期记忆系统（v0.4.5）

[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)](https://awesome-dsh-plugin.com) [![dsh.so security](https://www.dsh.so/badge/dsh-memory-7.svg)](https://www.dsh.so/artifact/dsh-memory-7)  [![DSH 适配](https://img.shields.io/badge/DSH%20%E9%80%82%E9%85%8D-%3E%3D0.1.2--rc.1-4E9BF1)](https://github.com/deepseek-ai/deepseek-harness/releases) [![Protocol](https://img.shields.io/badge/Protocol-MCP-blue)](#-多-harness-接入按端分目录) [![Node](https://img.shields.io/badge/Node-%3E%3D22.19-brightgreen)](package.json) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **一句话**：让 AI Agent 拥有跨会话的长期记忆——对话自动沉淀为纯文本 md 认知图，
> 规则化检索引擎决定「记什么、取什么」，全过程可审计、结果可复现。

**定位**：为追求高性能、无幻觉、多智能体适用、轻松使用的开发者打造——三步接入，装完即用，无需理解任何理论。

**形态**：跨 harness 的记忆基础设施——大脑（`md_cg/`）即标准 stdio MCP server，任何支持 MCP 的 AI Agent 可直接接入，不与任何单一 Agent 框架绑定。

---

## ✨ 核心亮点

- **⚡ 高性能**——Rust 检索内核（零第三方依赖）：库内嵌多线程大批量检索，`--serve` 进程实例支撑多智能体并发（语言无关）；中文检索 hit@1 99.0%，六家横评同口径登顶（见[六家横评](#-六家记忆系统横向对比)）
- **🛡️ 无幻觉**——记什么、取什么、能不能写入，全部由确定性规则裁决，不依赖 LLM 黑箱判断；条件层弱证据的检索干扰由四层证据防火墙白箱剔除（见[弱证据实证](#-弱证据会干扰检索三分离与证据防火墙实证)）；写没写成功看 `committed` 字段，绝不假装通过；全链路审计留痕、结果可复现
- **🔌 多智能体适用**——同一份大脑（`md_cg/`）+ 同一份纪律，接入 DSH · CodeBuddy · ZCode · Codex CLI · Claude Code，任何 MCP 宿主可直接挂载（见[多 harness 接入](#多-harness-接入按端分目录)）
- **😊 轻松使用**——三步接入，装完像往常一样对话即可；记忆本体是纯 md 文档，任何编辑器可直接打开审阅
- **📊 可复现评测**——`locomo-zh-500`（500 题）与 `bench6-100-zh-en`（六家横评 · 中英双查）数据集随仓公开，一条命令复现我方成绩（见[公开评测数据集](#-公开评测数据集)）

---

## ⚡ 快速开始

> **按宿主选择入口**：**DSH** → 下方三步 ｜ **CodeBuddy · ZCode · Codex CLI · Claude Code** → [多 harness 接入](#多-harness-接入按端分目录)（各端独立三步说明） ｜ **其它 MCP 宿主** → 直接挂载大脑 `python -m md_cg.mcp_server`（stdio MCP），再按需注入工作纪律

```bash
# ① 克隆并构建插件本体
git clone https://github.com/FuRongJun-1999/dsh-memory.git
cd dsh-memory
npm install && npm run build          # tsc → lib/

# ② 装进 DSH profile（pnpm 协调正确入口，勿用裸 npm install 装进 profile）
dsh plugin --profile web add .

# ③ 在 <profile>/cordis.yml 启用（配置示例见 dsh/cordis.yml.example）
```

```yaml
- id: lingshu-memory
  name: '@furongjun1999/dsh-memory'
  config:
    mdcg:
      root: 'data/mdcg'      # 记忆唯一真源（md 认知图）
    identity: '灵枢'
    tools: 'core'            # 'core'(默认, 仅 cg/stg) | 'brain' | 'all'
```

**装完即可对话，无需理解任何理论**——DSH 端自动记忆钩子已挂 session/event，你只管像往常一样对话（其它宿主可直接让 Agent 调用同一批工具）：

| 你说 | 背后发生什么（真实工具链） |
|---|---|
| 「请记住：我们团队的发布窗口是每周三」 | 自动记忆钩子沉淀 → `cg(op=write)` 过三道闸门 → 认知图节点落盘 |
| （新开会话）「我们的发布窗口是哪天？」 | 自动召回注入 → `mdcg_recall` 检索命中并带入回答 |
| 「把上次定的接口约定讲一遍」 | `cg(op=route)` 条件路由 + `stg(op=timeline)` 时间线回溯，跨会话取出 |

> 首次使用记忆库为空，召回返回空结果属正常现象；未配写入凭据时以只读 `guest` 运行（**读得到、写不进**），要真正落盘见[写入凭据](#-写入凭据让记忆真正落盘)。

- **前置**：Node ≥ 22.19 · DSH 内核 ≥ 0.1.2-rc.1 · **大脑零安装**（`md_cg` 随包自带，无需 pip 装任何引擎）
- **写权限默认关闭**：不配凭据即以只读 `guest` 运行（读 / 召回 / 时间线可用，写入不落盘）。要真正落盘见「写入凭据」
- 完整配置项（30+ 项）· 自动记忆机制 · DSH 看门狗 → [README 详细版](docs/README详细版_v0.4.5.md)
- **非 DSH 宿主**（CodeBuddy / ZCode / Codex CLI / Claude Code）：走[多 harness 接入](#多-harness-接入按端分目录)，各端有独立三步接入说明

---

## 📊 六家记忆系统横向对比

> **100 题中英双查**（bench6 v1.0 · 零干扰上界对照集 · CC BY-NC 4.0）：六家系统、同一份中文语料、同一套 hit@1 / hit@5 / MRR 评分器（`md_cg/eval_common.py`）。**下表按「英→中查询提升幅度」降序**：

| 系统 | en hit@1 | zh hit@1 | 英→中提升 |
|---|---|---|---|
| **灵枢**（词法 + meta） | 54.0% | **99.0%** | **+45.0pp** |
| 灵枢（四路融合 · 真开 bucket） | 37.0% | 81.0% | +44.0pp |
| 纯向量 RAG | 71.0% | 97.0% | +26.0pp |
| Letta（归档直插） | 73.0% | 96.0% | +23.0pp |
| mem0 | 68.0% | 89.0% | +21.0pp |
| GraphRAG | 18.0% | 31.0% | +13.0pp |
| Graphiti | 46.0% | 58.0% | +12.0pp |
| Letta（agent 自主入库） | 0.0% | 0.0% | （入库丢标记壳臂） |

> **核心结论**：**将查询由英文换为中文（同一份英文语料、记忆系统均不变）：六家已有记忆系统的检索命中全部大幅提升（+12 ~ +45pp），无一例外**；**灵枢是最佳**——中文查询 hit@1 **99.0% 全表登顶**，英→中提升幅度 **+45pp 亦居本表之首**（双语入库在中文查询下同时拿到最高命中与最大提升）。
> **诚实口径（非选择性引用，与横评报告一致）**：英文查询侧由 Letta 归档直插（73.0%）与纯向量 RAG（71.0%）领跑，灵枢四路融合在本池低于单词法基线（81.0% < 99.0%，饱和池上条件桶/实体路稀释词法命中）；中文提升混合了「查询语言」与「查询形态」双因素（`question_zh` 为关键词串、`question_en` 为自然问句），归因须谨慎。该池零干扰、全为 gold 证据，是**上界对照集**——高命中率不可外推为端到端记忆能力；Letta agent 模式 0 分是入库丢标记（可追溯性问题），非检索能力问题。
> 完整题型分解 / MRR 全表 / 逐家入库取证 / 偏差判定单 → [六家横评报告](docs/横评_六家100题中英双查_v1.0.md) · 题集 → [data/benchmarks/bench6-100-zh-en/](data/benchmarks/bench6-100-zh-en/README.md)

---

## 🧪 弱证据会干扰检索：三分离与证据防火墙（实证）

> **外部源码级评审（GPT）与四臂弱语义噪声注入实验共同实证的一个反直觉结论**：**语义完整度 ≠ 证据强度 ≠ 召回价值**——语义高度省略的「弱证据」语料恰恰是最需要被召回的 episodic 事实；而**条件判断层（负条件 / 否定反事实）的弱证据节点会冒充正确答案，干扰检索**。

- **实证语料「我在喝水」**：语义上高度省略（谁在喝？在哪喝？均未说），但作为 episodic 事实承诺明确。当提问是「你刚才在干什么？」时，问句与语料**词面零重叠**——纯词法检索 top1 命中 **0/8**（省略式 episodic 全部漏召），而语义路作为候选生成器把 **8/8** 拉进 top10。词法满格的前提（词面共享）在事件类记忆上不成立。
- **条件判断的弱证据干扰检索**：同一实验中 8 个否定反事实节点（「我没喝水」）与 gold 词面高度相似，无防线时冒充前排；灵枢四层证据防火墙（召回前负条件路由 → 候选生成排除 → `judge_ranking` 白箱终排 → 资格标注）将其 **8/8 全部 REJECT 剔除**，top10 无冒充。
- **可复现**：`python -m md_cg.test_sem_noise`（42 节点确定性语料，四臂 A_lex / B_sem / C_fusion / D_firewall 对照，7 断言）。

---

## 🌐 中英双语检索差距：英文为什么没中文好（实证）

> **直接回答**：同一份 500 题语料上的三层原子语义实证（hit@10）——**中文原子语义 99 > 中文原子语义直接映射的英文原子语义 87 > 英文提取原子语义 79**。87 vs 79 的 8 个百分点是**同义词鸿沟的直接隔离证据**：query 侧沿用中文关键词（与语料同一条原子语义链）只换词面编码时几乎无损，换成英文自由表达即损失 8pp；差距的**根本原因是语言固有属性，不是工程缺陷**。英文检索已按「双语双路」架构做到词面系方法的当前最优（硬套中文管线只有 27%，独立路提升至 87%），剩余差距来自英文每概念多表达的本质，无法靠词面匹配消除。

**测试报告**（灵枢公开仓评测，方法学与口径真源 → [`md_cg/semantic/REPRODUCE.md`](md_cg/semantic/REPRODUCE.md)）：

| 方法 | hit@1 | hit@5 | hit@10 | 语料 |
|---|---|---|---|---|
| ① 中文原子语义（md_cg 主链路：char-bigram + 四路 RRF + 同义扩展 + terms） | 94.6% | 99.2% | **99.2%** | locomo-zh-500 · 500 题（中文题面） |
| ② 中文原子语义 → 直接映射的英文原子语义（中文关键词经字级原子映射转英文原子检索） | 52-53% | 79-81% | **87-88%** | locomo-zh-500 · 500 题（同 qids，中文关键词→英文原子） |
| ③ 英文提取原子语义（英文原题归一化 → 英文原子 + Jaccard，本仓复现） | 48.8% | 73.8% | **79.0%** | locomo-zh-500 · 500 题（同 qids 英文原题） |
| 英文反事实：硬套中文 char-bigram 主链路（默认态） | 27% | 45% | 56% | bench6 · 100 题（口径不同，只看量级） |

> ①②③是**同一原子语义空间的三个层级**，按「语义链保持程度」递减：② 与 ① 共用中文关键词这条语义链，仅把词面编码从中文原子换成英文原子（中→英字级映射）；③ 则连 query 侧也换成英文自由文本再提取原子，跨过了同义改写鸿沟。② 为 dsh 端文档口径，③ 为本仓同源词表/归一器独立复现；反事实行为 bench6 100 题口径，仅作架构取舍的量级对照。

**差距三层归因（按权重排序）**：

1. **同义词鸿沟（根本原因，语言固有属性）**。中文「概念 → 表达」约 **1:1~1:2**（95 个同义词对），字面重叠天然命中，词面匹配几乎不打折；英文每概念平均 **5.2 种**表达（CC-CEDICT 语料统计，8,493 汉字展开出 172,950 个英义对，**1,820 倍**于中文）。上表 ② vs ③ 就是这道鸿沟的**直接隔离实验**：同一条中文关键词语义链，仅把词面编码换成英文原子得 87-88%，连 query 侧也换成英文自由表达再提取原子即降至 79%——英文 query 与目标 content 极可能选用**不同措辞**（take away / learn / gain / get out），任何词面系匹配（含 Jaccard）都会在这类改写上失配。② 的 87-88% hit@10 说明答案多在候选池内，③ 的损失集中在**排序**，不是召回不到。
2. **架构非对称（设计裁定，已是最优解）**。中文链路的四路 RRF / 同义扩展 / terms 字段全部建立在「字面=语义」的中文前提上，直接跑英文实测**劣于**独立路（约 27% vs 87%，见上表反事实行与 ② 行）——英文按架构裁定走独立的语义原子 + Jaccard 单路（双语双路），不享受多路互补，是**有意的取舍**而非遗漏。
3. **归一化/映射的有损性（工程天花板，99 vs 87 的主体）**。中→英字级映射覆盖 6,319 字（97.2%），173 个纯音缀字（玻/璃/葡/萄）无独立语义被排除，专名与音译词不进映射链；英文侧原子是**语义整词/词组单元**（`word` 不拆为 `wo`，已知概念折叠为规范词组原子，如 beef → cow_meat），屈折归一只覆盖规则变化（-ed/-ing/-s）+ 有限不规则表，且按「宁少剥不误剥」保守原则（courageous 不剥 -s）；派生词（happy/happiness）不折叠——长尾表达保留为不同原子，进一步稀释 Jaccard。

**要不要上语义向量检索？** 向量嵌入可以弥合同义鸿沟，但会引入嵌入模型依赖与索引体积，与灵枢「零重依赖、纯词面可复现」的公开仓原则冲突，**当前明确不做**；英文路保持确定性词面匹配的诚实边界，其 87-88% 的 hit@10 已满足「答案在候选池」的记忆系统主用途。

---

## 📚 公开评测数据集

📎 全部随仓库公开（CC BY-NC 4.0），可直接下载用于你自己的记忆系统对照评测：

| 基准 | 归属 | 状态 |
|---|---|---|
| **locomo-zh-500** | **自建**（LoCoMo 中文派生 · 500 题 / 567 turns / 0.6 MB） | **已随仓库公开** `data/benchmarks/locomo-zh-500/` · 可复现 · **我方成绩：hit@1 94.6% · hit@5 / hit@10 99.2%（md_cg 完整主链路，见上[中英双语检索差距](#-中英双语检索差距英文为什么没中文好实证)① 行）** |
| **bench6 · 六家横评** | **自建**（LoCoMo 中文派生 · 100 题 / 137 turns · **中英双查** / 约 90 KB） | **已随仓库公开** `data/benchmarks/bench6-100-zh-en/` · **六家同口径对照**（灵枢 5 口径 / 纯向量 RAG / mem0 / Graphiti / GraphRAG / Letta 两模式）· 报告 → [横评_六家100题中英双查_v1.0.md](docs/横评_六家100题中英双查_v1.0.md) |
| LoCoMo | 第三方 `mteb/LoCoMo` BEIR（1976 题 / 5882 turns） | 上游来源（英文原版） |
| memory-bench-1000 | **自建** | SNR 见评分报告 v2.0；已公开 `data/memory-bench-1000.jsonl` |

> 上表四行性质不同，勿混读：`locomo-zh-500` 的分数是**本仓库我方成绩**（基于LoCoMo自建并公开的评测集，可复现）；`bench6 · 六家横评` 是同源派生的**小型同口径对照集**（零干扰池，只做六家系统横向对照，**非我方单方成绩**）；LoCoMo 一行指**上游英文原版 1976 题**，本仓库未在其上产出完整成绩；`memory-bench-1000` 是自建记忆库的评分报告。
> **该成绩的性质（非虚假声明）**：`locomo-zh-500` 的分数是**写入侧结构化加工后的检索成绩**——入库前把每轮对话加工为「身份 / 时间 / 摘要 / 词 / 条件四槽」条目，再走词法 + 同义扩展检索。这与主流记忆系统所用的**向量化嵌入 + 关键词/摘要压缩**属**同一类写入侧加工**，差异只在索引与检索算法，不在「是否对原文做了加工」。因此该口径可用于**同口径对照**，不是对裸文本直读的虚高取巧。
> `locomo-zh-500` 是**本仓库对外发布的检索评测集**：供外部在**同一份中文题面**上对自己的记忆系统做可对照评测。它只评检索命中（hit@k / MRR），**不评答案正确性**；被测池为**零干扰**（池内全是 gold），故高命中率不可外推为端到端记忆能力——完整边界与许可见 `data/benchmarks/locomo-zh-500/README.md`。
> `bench6-100-zh-en` 沿用同一口径，并**每题提供中英两套词面**（评「换查询语言后是否仍命中」）；它同样是**上界对照集**——家间差距小于约 16% **不可判为显著**；评测入口已随仓库公开（`run_bench.py`：零依赖口径复现 + Adapter 协议接入你自己的系统），接入任意llm和向量方法都可复现，详见 [横评报告](docs/横评_六家100题中英双查_v1.0.md) 与 `data/benchmarks/bench6-100-zh-en/README.md`。

**复现我方成绩**（零上游依赖）：

```bash
python -m md_cg.bench_locomo_zh_public   # 只读 data/benchmarks/locomo-zh-500/，产出公开词法口径参考量级（hit@1 93.6% 单路 / 97.6% +同义扩展）；上表 94.6/99.2 为 md_cg 完整主链路（四路 RRF + 同义扩展 + terms）成绩
```

> 自建 bench 的噪声层 400 条 + unlabeled 边界 350 条为天然负对照；任何基准报告须带**干扰抑制负例组**与 **T-JUDGE 负例拒绝率**双向报告（遵守「只报总分 = 不通过」）。

---

## 🎯 能力自评（内部标尺，非横评声明）

> 项目维护者按内部七维标尺（结构 / 检索 / 判断 / 调用 / 演化 / 连续 / 可信）自评 **综合 8.6 / 10**（全部维度 ≥ 8.5），并按外部行为级门槛自评为**条件性 L4 → L5 路上**——含未完成项与扣分理由的逐维证据，见 [AGI 七维评分报告 v2.0](docs/AGI七维评分报告_md_cg_v2.0.md)。
> **不虚高的坦白**：五个 8.5 的共同上限是「机制齐备、门槛项未齐」——T 零信任未落地、R 仍是规则层意图理解、C 去污染仍是抽样而非穷尽、U 的 LLM 固化动作尚未自动放行。

---

## 🧩 能力速查（能力 → 入口）

| 能力 | MCP 入口 |
|---|---|
| 记忆写入 · 关系链接 · 结构关系 | `cg(op=write)` `cg(op=link)` `stg(op=relation)` |
| 多路融合检索 · 条件路由 · 因果链 · 时间线 | `mdcg_recall` `mdcg_search` `cg(op=route)` `stg(op=timeline)` |
| 写入裁决 · 主动遗忘 · 冲突检测 · 反思 | `mdcg_remember` `cg(op=verify)` `cg(op=metacognition)` `mdcg_reflect` |
| 重要性评分 · 预算装包 · 分层注入 · 记忆自净 | `cg(op=session)` `cg(op=scrub)` `cg(op=info)` |
| 知识固化 · 结构变更账本 / 回滚 · 自维持巡检 | `mdcg_flywheel` `cg(op=consolidate)` `cg(op=maintain)` `cg(op=sustain)` |
| 身份一致性 · 自我状态 · 演化史 | `cg(op=identity)` `cg(op=self_state)` `cg(op=evolution)` |
| 加密 · 密级隔离 · 审计留痕 · 保护/遗忘 | `cg(op=protect)` `cg(op=forget)` · [护栏宪章](docs/guardrail-charter.md) |

---

## 🧰 工具面

**两个认知基元 · 35 个 op**（`kernel` 面）：

| 基元 | op |
|---|---|
| **`cg`** 认知图统一入口 | **31**：`theory` `link` `info` `route` `read` `write` `goal` `recent` `verify` `review` `forget` `protect` `identity` `consistency` `metacognition` `self_state` `evolution` `sustain` `scrub` `predict` `causal` `whitebox` `index_code` `index_doc` `ref` `session` `ingest` `export` `maintain` `consolidate` `insight` |
| **`stg`** 语义时空图入口 | **4**：`relation` `timeline` `anchors` `consistency` |

**细粒度面**（`MDCG_MCP_SURFACE=full`，插件运行时使用）：`cg` + `stg` + **31 个 `mdcg_*`** = **33 个工具**。

| `tools` 模式 | 暴露数 | 说明 |
|---|---|---|
| `'core'`（**默认**） | **2** | 仅 `cg` / `stg` |
| `'brain'` | **30** | `cg`/`stg` + 28 细粒度 |
| `'all'` | **30** | full 面 33 − 3 个宿主级风险工具 |

> 风险工具 `mdcg_forget` / `mdcg_restore` / `mdcg_review_decide` 需 `can_admin`，即使 `tools: 'all'` 也不自动暴露。
> 35 op 已逐一冒烟验证：**35/35 可达，0 未知 op、0 意外崩溃**。
> 每个 op 的「功能 → 代码（含行号）→ MCP op」见 [功能调用映射表](docs/功能调用映射表_v0.1.md)；历史 82 工具去向见 [迁移映射](docs/灵枢82工具_功能整理与迁移映射_v0.1.md)。

---

## 🏗️ 架构（以 DSH 为例 · 其它 MCP 宿主同构）

```
DeepSeek Harness (cordis)
  Agent Loop ──┬── 工具面 ctx.tools（cg / stg / mdcg_*）
               └── session/event（自动记忆钩子 · 自动召回注入）
                     │ stdio · 逐行 JSON-RPC
┌────────────────────▼─────────────────────┐
│ 灵枢大脑子进程（spawn · 唯一）             │
│ python -m md_cg.mcp_server               │
│ cg/stg 基元 + 31 细粒度 · md 认知图真源    │
└──────────────────────────────────────────┘
（可选）「身体」能力后端：仅 capability.enabled=true 时另起一个能力库子进程，默认不启动
```

**记忆只有一个真源**：`md_cg/` 认知图（纯 md 文档，随包自带）。确定性规则引擎与知识库已内迁；
AEIS 仅作可选「身体」能力后端（角色扮演生成），不再存记忆、默认不启动。

> 其它 MCP 宿主同构：宿主工具面（`cg` / `stg` / `mdcg_*`）↔ stdio MCP ↔ `md_cg` 大脑；四端差异只在**纪律注入方式**（矩阵见[多 harness 接入](#多-harness-接入按端分目录)），大脑与记忆真源零改动。

---

## 🔑 写入凭据（让记忆真正落盘）

```bash
# 签发（明文不进配置文件）
python -m md_cg.tokens issue --role designer --actor dsh-memory --clearance internal ^
  --ops-allow info,route,read,write,recent,goal,identity,whitebox,verify ^
  --layers-allow knowledge,contextual,structural,self,goals,unresolved,rejected
setx MDCG_TOKEN "mdcg1.xxxxx"     # 然后重启 DSH
```

```yaml
    env:
      MDCG_TOKEN: !!js process.env.MDCG_TOKEN
```

> `--role recorder` 为最小权限版（只能自动记忆 / 转录；`whitebox`、`identity`、`verify` 会被拒）。
> **落盘充要条件 = 最终判定 ACCEPT**：`cg(op=write)` 需依次穿过 audit → 一致性 → gated 三问四态三道闸门，非 ACCEPT 均不新增落盘点。
> **别把 `ok: true` 当写成功**：未落盘时返回体形如 `{"ok": true, "committed": false, "moved_to": "review_queue"}`——`ok` 只表示请求被受理，**是否落盘只看 `committed`**。首次写入最常踩的坑：`content_kind` 省略或填 `text` 时，未配置规则库（`MDCG_POLICY_FILE`）的审核器一律判 `DEFER`（"缺能力返回 DEFER，绝不假装通过"），内容进审核队列而非落盘；要立刻落盘请用可验证类型，如 `content_kind: 'code'`（AST 解析通过即 `ACCEPT`）。

---

## ❓ 常见问题（FAQ）

<details>
<summary><b>为什么不能用裸 <code>npm install</code> 安装进 profile？</b></summary>

必须用 `dsh plugin --profile <name> add .` 安装：插件声明了 6 个 `peerDependencies`（cordis / dsh-llm / dsh-session / dsh-system-prompt / dsh-tools / schemastery），`dsh plugin add` 走 pnpm 正确解析宿主提供的 peer 版本；裸 `npm install` 会把错误版本的依赖装进 profile 导致加载失败。仓库根目录的 `npm install` 仅用于开发构建（`npm run build`）。
</details>

<details>
<summary><b>装完插件 / 配完凭据没有生效？</b></summary>

DSH 采用 Cordis bundle 机制，新增或更新插件后必须**重启 DSH 进程**（或刷新 Web UI 页面）才会重新加载；通过 `setx` 配置 `MDCG_TOKEN` 后同理，须重启才可见（见[写入凭据](#-写入凭据让记忆真正落盘)）。
</details>

<details>
<summary><b>怎么确认 Agent 真的把记忆写进去了？</b></summary>

看返回体的 <code>committed</code> 字段，<strong>别把 <code>ok: true</code> 当写成功</strong>——<code>{"ok": true, "committed": false, "moved_to": "review_queue"}</code> 表示请求被受理但<strong>未落盘</strong>（内容进了审核队列）。落盘充要条件 = 三道闸门最终判定 <code>ACCEPT</code>。
</details>

<details>
<summary><b>为什么我的写入没有落盘？</b></summary>

三个最常见原因：① 未配写入凭据 → 只读 <code>guest</code>，写入不落盘（配凭据见<a href="#-写入凭据让记忆真正落盘">写入凭据</a>）；② <code>content_kind</code> 省略或填 <code>text</code> 且未配置规则库（<code>MDCG_POLICY_FILE</code>）→ 审核器一律判 <code>DEFER</code>（"缺能力返回 DEFER，绝不假装通过"）→ 用 <code>content_kind: 'code'</code> 等可验证类型（AST 解析通过即 ACCEPT）；③ 未穿过 audit → 一致性 → gated 三问四态任一闸门。
</details>

<details>
<summary><b>CodeBuddy / ZCode / Codex CLI / Claude Code 等其它宿主也能用吗？</b></summary>

能。大脑 <code>md_cg/</code> 是标准 stdio MCP server（<code>python -m md_cg.mcp_server</code>），任何支持 MCP 的宿主可直接挂载；五端接入差异只在纪律注入方式，见<a href="#-多-harness-接入按端分目录">多 harness 接入</a>。
</details>

---

## 📚 文档导航

| 文档 | 内容 |
|---|---|
| [README 详细版](docs/README详细版_v0.4.5.md) | 完整能力说明 · 配置项全表 · 安装与验证细节 |
| [发布说明 v0.4.5](docs/release_v0.4.5.md) | 本版变更 / 兼容性 / 升级指引 |
| [AGI 七维评分报告 v2.0](docs/AGI七维评分报告_md_cg_v2.0.md) | 逐维得分依据 / 扣分项 / 实库证据 / 诚实边界 |
| [功能调用映射表](docs/功能调用映射表_v0.1.md) | 任何功能 → 调用哪段代码（含行号、MCP op） |
| [护栏宪章 v2.0](docs/guardrail-charter.md) | 对外部智能体与人类使用者的行为边界 |
| 教学四篇 | [白箱智能是什么？](docs/白箱智能是什么？.md) · [智能的认知过程](docs/智能的认知过程.md) · [智能的公理化基石](docs/智能的公理化基石.md) · [信息差为什么必然存在](docs/信息差为什么必然存在且自然扩大.md) |
| [工作纪律·认知图条目 v1.1](docs/工作纪律_认知图条目_v1.1.json) | 自我约束的 16 条工作纪律（嵌套认知图条目 `work_discipline`） |
| [六家记忆系统横评 v1.0](docs/横评_六家100题中英双查_v1.0.md) | 100 题 · **中英双查** · 六家同口径对照；含判定单 / 条件层归因 / 诚实边界（题集 → [data/benchmarks/bench6-100-zh-en/](data/benchmarks/bench6-100-zh-en/README.md)） |
| [Rust 检索库](rust/README.md) | `mdcg_eval` 三形态：库内嵌大批量检索 / `--serve` 多智能体进程实例 / 公开数据集评测器（零依赖 · 与 Python 口径逐位对齐） |

### 多 harness 接入（按端分目录）

共享层（`md_cg/` 大脑 · `data/` · `docs/` · `scripts/`）在仓库根；**harness 专属配置按端归置**：

| 目录 | harness | 接入文档 | 纪律注入方式 |
|---|---|---|---|
| [`dsh/`](dsh/README.md) | DeepSeek Harness | [dsh/README.md](dsh/README.md) | `~/.dsh/profiles/web/cordis.patch.yml` 的 `personaPrefix`（compact · 每轮） |
| [`codebuddy/`](codebuddy/README.md) | CodeBuddy | [codebuddy/README.md](codebuddy/README.md) | 项目根 `CODEBUDDY.md`（full · 会话起始） |
| [`zcode/`](zcode/README.md) | ZCode | [zcode/README.md](zcode/README.md) | 项目根 `AGENTS.md`（full · 会话起始） |
| [`codex/`](codex/README.md) | Codex CLI | [codex/README.md](codex/README.md) | 项目根 `AGENTS.md`（full · 会话起始） |
| [`claude/`](claude/README.md) | Claude Code | [claude/README.md](claude/README.md) | 项目根 `CLAUDE.md`（full · 会话起始） |

> 五端纪律**同源**（`docs/工作纪律_认知图条目_v1.1.json`），由 `scripts/render_discipline.py` 渲染、
> `scripts/verify_discipline.py` 守卫漂移；矩阵见 `docs/discipline/harnesses.yaml`。

### 插件生态形态（免手工复制，本仓自带双端 marketplace）

| 宿主 | 安装 | 插件位置 | 装后一步 |
|---|---|---|---|
| Claude Code | `/plugin marketplace add FuRongJun-1999/dsh-memory` → `/plugin install lingshu-memory@lingshu` | `claude/lingshu-memory/`（纪律以 skill 分发，`/lingshu-memory:linglu-discipline` 可显式调用） | 复制插件内 `mcp.json.example` 为项目根 `.mcp.json`，填 `PYTHONPATH` |
| Codex CLI | `codex plugin marketplace add <本仓路径>` → `codex plugin add lingshu-memory@lingshu` | `codex/lingshu-memory/`（skill 三级渐进加载；`.codex-plugin/plugin.json` 清单） | 把插件内 `config.toml.example` 两段合并进 `~/.codex/config.toml`，填 `PYTHONPATH` |

> marketplace 清单：Claude 端在仓根 `.claude-plugin/marketplace.json`，Codex 端在仓根
> `.agents/plugins/marketplace.json`。插件不含大脑本体（`md_cg/` 不随插件分发）——MCP 装好后
> 大脑仍是你本机的 dsh-memory 仓库；插件形态的纪律 skill 同样由真源渲染（`skill` 变体，
> 矩阵槽位 `claude-code-plugin-skill` / `codex-plugin-skill`），漂移由同一 `verify_discipline.py` 守卫。

---

## 🛠️ 开发

```bash
npm install
npm run build    # TypeScript 编译
npm test         # 真实集成测试（spawn 本机灵枢，验证握手/往返/注册/卸载）
```

测试不依赖 DSH 全组件——用最小 Cordis host（SystemPrompt + ToolRegistry + 插件）隔离不稳定面。

---

## 📏 工程纪律与设计者视角（可选推荐）

> **这段话是什么**：灵枢自身按一套 **16 条工程纪律** 运行——方法论（理论先行 / 全面处理 / 根因纪律）、执行（验证先行 / 双副本同步 / 兜底路径）、合规（内容政策双清单 / 敏感信息隔离）、记忆闭环（查记忆 → 执行 → 写记忆）。它原本是灵枢的「自我约束」，与你要不要用灵枢无关；但如果你希望自己的 Agent 也具备同样的工作方式，这套纪律与配套元技能**都可以直接复用**。

**两个可复用入口**：

| 入口 | 内容 | 位置 |
|---|---|---|
| **工程纪律（16 条）** | 每条 ≡ 一个认知图节点（生效条件 / 执行锚点 / 不适用条件 / 直答出口），含触发词路由 | 真源：[`docs/工作纪律_认知图条目_v1.1.json`](docs/工作纪律_认知图条目_v1.1.json) · 全文投影：[`AGENTS.md`](AGENTS.md) |
| **设计者视角（元技能）** | 在动手前回答「该不该做 / 为什么做 / 条件够不够」：条件空间声明 → 四态资格裁决（ACCEPT/REJECT/DEFER/BLINDSPOT）→ 失配归因；附自检 17/17 | [`skills/skills/designer-perspective/`](skills/skills/designer-perspective/)（`tests/selftest.py` 可自行验收） |

> **按需裁剪**：16 条中部分条款针对灵枢私有管线（如图像选源线），复用时建议只取方法论 / 执行 / 合规 / 记忆闭环四组通用条款。多 harness 渲染与防漂移守卫见 [多 harness 接入](#多-harness-接入按端分目录)。

## 护栏宪章（接入即接受约束）

本插件接入即接受 **[灵枢护栏宪章 v2.0-published](docs/guardrail-charter.md)** 约束——对外部智能体与人类使用者的行为边界作出公开、可执行、可审计的规定，并保护人类使用者。

## 许可证

MIT © 荣（FuRongJun-1999）· 灵枢 AEIS 工程实现

DeepSeek Harness 为 DeepSeek 官方开源项目（MIT），本插件与之无隶属关系。
