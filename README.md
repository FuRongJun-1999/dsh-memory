# 让 AI Agent 拥有不可遗忘的自我

**灵枢（Lingshu / AEIS）** —— 白箱智能 + AGI 级长期记忆系统（v0.4.5）

[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)](https://awesome-dsh-plugin.com) [![dsh.so security](https://www.dsh.so/badge/dsh-memory-7.svg)](https://www.dsh.so/artifact/dsh-memory-7)  [![DSH 适配](https://img.shields.io/badge/DSH%20%E9%80%82%E9%85%8D-%3E%3D0.1.2--rc.1-4E9BF1)](https://github.com/deepseek-ai/deepseek-harness/releases) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **一句话**：不是「又一个记忆插件」，而是一个**记忆操作系统**——对话自动沉淀为纯文本认知图（md 文档），
> 用确定性白箱完成条件路由、检索、判断与演化，让每次对话都是同一段生命的延续。

**定位**：面向 AGI 研究者的大型研究项目，性能极高，记忆效果极强。

**形态**：跨 harness 的记忆基础设施——大脑（`md_cg/`）即标准 stdio MCP server，任何支持 MCP 的 AI Agent 可直接接入；记忆机制本身（五层时空记忆图 · 知识飞轮 · 白箱管线 · 可审计信任）与宿主框架解耦，不与任何单一 Agent 绑定。

---

## ✨ 核心亮点

- **🧠 五层时空记忆图**——对话自动沉淀为纯文本认知图（anchor / self / knowledge / structural / contextual），跨会话保持自我连续性；记忆本体是 md 文档，任何编辑器可直接审阅
- **🔍 白箱确定性引擎**——条件路由、检索、写入裁决全程规则化，不依赖 LLM 黑箱，全链路可审计、可复现
- **🔌 跨 harness 接入**——大脑是标准 stdio MCP server，不绑定单一 Agent 运行时：同一份大脑（`md_cg/`）+ 同一份工作纪律，接入 DSH · CodeBuddy · ZCode · Codex CLI，任何 MCP 宿主可直接挂载（见[多 harness 接入](#多-harness-接入按端分目录)）
- **📊 可复现评测**——`locomo-zh-500`（500 题）与 `bench6-100-zh-en`（六家横评 · 中英双查）数据集随仓公开，一条命令复现我方成绩（见[公开评测数据集](#-公开评测数据集)）
- **⚡ Rust 高性能内核**——检索核心 `mdcg_eval`（零第三方依赖 Rust 库）：库内嵌多线程大批量检索，`--serve` 进程实例支撑多智能体并发（语言无关）；与 Python 检索口径逐位对齐（见 [rust/README.md](rust/README.md)）

---

## ⚡ 快速开始

> **按宿主选择入口**：**DSH** → 下方三步 ｜ **CodeBuddy · ZCode · Codex CLI** → [多 harness 接入](#多-harness-接入按端分目录)（各端独立三步说明） ｜ **其它 MCP 宿主** → 直接挂载大脑 `python -m md_cg.mcp_server`（stdio MCP），再按需注入工作纪律

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

- **前置**：Node ≥ 22.19 · DSH 内核 ≥ 0.1.2-rc.1 · **大脑零安装**（`md_cg` 随包自带，无需 pip 装任何引擎）
- **写权限默认关闭**：不配凭据即以只读 `guest` 运行（读 / 召回 / 时间线可用，写入不落盘）。要真正落盘见「写入凭据」
- 完整配置项（30+ 项）· 自动记忆机制 · DSH 看门狗 → [README 详细版](docs/README详细版_v0.4.5.md)
- **非 DSH 宿主**（CodeBuddy / ZCode / Codex CLI）：走[多 harness 接入](#多-harness-接入按端分目录)，各端有独立三步接入说明

---

## 📊 六家记忆系统横向对比

> **100 题中英双查**（bench6 v1.0 · 零干扰上界对照集 · CC BY-NC 4.0）：六家系统、同一份中文语料、同一套 hit@1 / hit@5 / MRR 评分器（`md_cg/eval_common.py`）。

| 系统 | zh hit@1 | zh MRR | en hit@1 | en MRR |
|---|---|---|---|---|
| **灵枢**（词法 + meta） | **99.0%** | **0.9950** | 54.0% | 0.5993 |
| 灵枢（四路融合 · 真开 bucket） | 81.0% | 0.8983 | 37.0% | 0.4893 |
| 纯向量 RAG | 97.0% | 0.9817 | 71.0% | 0.7937 |
| mem0 | 89.0% | 0.9125 | 68.0% | 0.7850 |
| Letta（归档直插） | 96.0% | 0.9767 | **73.0%** | **0.8063** |
| Letta（agent 自主入库） | 0.0% | 0.0000 | 0.0% | 0.0000 |
| Graphiti | 58.0% | 0.6008 | 46.0% | 0.5303 |
| GraphRAG | 31.0% | 0.3223 | 18.0% | 0.2057 |

> **诚实口径（非选择性引用，与横评报告一致）**：灵枢**中文查询登顶**（99.0%），但**英文查询落后**（54.0%）——英文侧由 Letta 归档直插（73.0%）与纯向量 RAG（71.0%）领跑，**没有任何一家在两种查询语言上同时最优**；灵枢四路融合在本池反而低于单词法基线（81.0% < 99.0%，饱和池上条件桶/实体路稀释词法命中）。该池零干扰、全为 gold 证据，是**上界对照集**——高命中率不可外推为端到端记忆能力；Letta agent 模式 0 分是入库丢标记（可追溯性问题），非检索能力问题。
> 完整题型分解 / 逐家入库取证 / 偏差判定单 → [六家横评报告](docs/横评_六家100题中英双查_v1.0.md) · 题集 → [data/benchmarks/bench6-100-zh-en/](data/benchmarks/bench6-100-zh-en/README.md)

---

## 📚 公开评测数据集

📎 全部随仓库公开（CC BY-NC 4.0），可直接下载用于你自己的记忆系统对照评测：

| 基准 | 归属 | 状态 |
|---|---|---|
| **locomo-zh-500** | **自建**（LoCoMo 中文派生 · 500 题 / 567 turns / 0.6 MB） | **已随仓库公开** `data/benchmarks/locomo-zh-500/` · 可复现 · **我方成绩：hit@1 93.6% → 97.6%（+同义扩展）** |
| **bench6 · 六家横评** | **自建**（LoCoMo 中文派生 · 100 题 / 137 turns · **中英双查** / 约 90 KB） | **已随仓库公开** `data/benchmarks/bench6-100-zh-en/` · **六家同口径对照**（灵枢 5 口径 / 纯向量 RAG / mem0 / Graphiti / GraphRAG / Letta 两模式）· 报告 → [横评_六家100题中英双查_v1.0.md](docs/横评_六家100题中英双查_v1.0.md) |
| LoCoMo | 第三方 `mteb/LoCoMo` BEIR（1976 题 / 5882 turns） | 上游来源（英文原版） |
| memory-bench-1000 | **自建** | SNR 见评分报告 v2.0；已公开 `data/memory-bench-1000.jsonl` |

> 上表四行性质不同，勿混读：`locomo-zh-500` 的分数是**本仓库我方成绩**（基于LoCoMo自建并公开的评测集，可复现）；`bench6 · 六家横评` 是同源派生的**小型同口径对照集**（零干扰池，只做六家系统横向对照，**非我方单方成绩**）；LoCoMo 一行指**上游英文原版 1976 题**，本仓库未在其上产出完整成绩；`memory-bench-1000` 是自建记忆库的评分报告。
> **该成绩的性质（非虚假声明）**：`locomo-zh-500` 的分数是**写入侧结构化加工后的检索成绩**——入库前把每轮对话加工为「身份 / 时间 / 摘要 / 词 / 条件四槽」条目，再走词法 + 同义扩展检索。这与主流记忆系统所用的**向量化嵌入 + 关键词/摘要压缩**属**同一类写入侧加工**，差异只在索引与检索算法，不在「是否对原文做了加工」。因此该口径可用于**同口径对照**，不是对裸文本直读的虚高取巧。
> `locomo-zh-500` 是**本仓库对外发布的检索评测集**：供外部在**同一份中文题面**上对自己的记忆系统做可对照评测。它只评检索命中（hit@k / MRR），**不评答案正确性**；被测池为**零干扰**（池内全是 gold），故高命中率不可外推为端到端记忆能力——完整边界与许可见 `data/benchmarks/locomo-zh-500/README.md`。
> `bench6-100-zh-en` 沿用同一口径，并**每题提供中英两套词面**（评「换查询语言后是否仍命中」）；它同样是**上界对照集**——家间差距小于约 16% **不可判为显著**，且竞品适配脚本未随仓库公开，详见 [横评报告](docs/横评_六家100题中英双查_v1.0.md) 与 `data/benchmarks/bench6-100-zh-en/README.md`。

**复现我方成绩**（零上游依赖）：

```bash
python -m md_cg.bench_locomo_zh_public   # 只读 data/benchmarks/locomo-zh-500/，产出即为公开的参考量级
```

> 自建 bench 的噪声层 400 条 + unlabeled 边界 350 条为天然负对照；任何基准报告须带**干扰抑制负例组**与 **T-JUDGE 负例拒绝率**双向报告（遵守「只报总分 = 不通过」）。

---

## 🎯 AGI 七维评分标尺

> **标尺**：`AGI记忆系统评分标尺 v1.0`（七维 · 层次优先 · 门槛晋级）
> **公式**：`综合 = min × 0.4 + mean × 0.6`（短板效应显著）
> **评分**：md_cg **v2.0**（2026-09-10）· 取证 = 源码级逐模块核对 + 46 套 **1970 项**测试全绿 + 基准级 SNR 量化 + 实库 **6339 节点**只读盘点

| 维度 | 分 | 拷问的问题 | 一句话依据 |
|---|---|---|---|
| **S** 结构 | **8.5** | 记忆怎么存？ | 认知图四要素 + 五层（anchor/self/knowledge/structural/contextual）+ 负记忆 + 条件空间；实库 6339 节点层分布与索引**精确对账** |
| **R** 检索 | **8.5** | 能从一堆里找对那条吗？ | 四路 RRF 融合 + 条件级负路由 + 因果链遍历；召回分池修复结构性挤占（索引占比 44.2% → **27.1%**） |
| **J** 判断 | **9.0** | 能说「这条不该用 / 不该记」吗？ | 写入三问四态 + 主动遗忘闸门 + 节点冲突检测 + **独立元认知** + 递归反思 |
| **C** 调用 | **9.0** | 塞进上下文的东西干净吗？ | **SNR 量化仪表盘**：40% 噪声率下 sigP **97.8%** / noiseP **0.4%**（配对 bootstrap + McNemar + 消融对照） |
| **U** 演化 | **8.5** | 会不会越用越强？ | 知识飞轮进 MCP 主循环 + **通用结构变更账本与按条目回滚**（实库 238 条 / 已演练回滚 4 次） |
| **I** 连续 | **8.5** | 一个月后还是同一个「我」吗？ | 自我锚点 `SELF` 不可覆盖 + 跨会话演化叙事与规律统计 + 派生血缘台账 |
| **T** 可信 | **8.5** | 敢不敢把私密信息交给它？ | ChaCha20-Poly1305 加密 + 四级密级隔离 + payload-free 审计 + 写入四重闸门 |

```
min  = 8.5        mean = 8.643        综合 = 8.5 × 0.4 + 8.643 × 0.6 ≈ 8.6
层次 = L5（AGI 级记忆）· 稳固段   —— 七维全部 ≥ 8.5，无 <8 维度
```

**刻度含义**：`3-4` 基础可用 · `5-6` 良好 · `7-8` **优秀**（图结构 / 因果路由 / 独立元认知 / 精准注入 / 版本回滚 / 自我锚点 / 加密审计）· `9-10` 门槛项齐备、机制完备。

> **不虚高的坦白**：五个 8.5 的共同上限是「机制齐备、门槛项未齐」——T 零信任未落地、R 仍是规则层意图理解、C 去污染仍是抽样而非穷尽、U 的 LLM 固化动作尚未自动放行。逐维扣分与实库证据见 [AGI七维评分报告_md_cg_v2.0.md](docs/AGI七维评分报告_md_cg_v2.0.md)。
> **抬升路线**：U 飞轮全自转（最小改动）→ T 零信任（成本最高）→ R 开放域意图（路线决策）。注意：当前 min = 8.5 且五维并列，**抬单维已不抬综合**。

---

## 📐 v2.0 行为级门槛自评（外部标尺）

> 上表为**内部进度尺**（v1.0 连续打分，管「机制缺什么」）；本节为**对外声明尺**（v2.0 二值门槛，管「敢说什么」）。两轨不合并。
> 中立题型集成立前，本节**仅用于自评，不构成横评声明**。

**结论：条件性 L4 → L5 路上**（待 S5 / ECE / 24h 检测）· 最强 G3 · 最弱 G2

| Gate | v2.0 判据 | 现状 | 判定 |
|---|---|---|---|
| **G1** L1 | 重启原样取出，失配 < 5% | md 纯文本真源；id 由源节点 SHA1 派生，重建一致 | 机制在，待抽测 |
| **G2** L2 | T-REC 三组分别报 hit@1，干扰组 ≥ 80% | 四路 RRF + 条件级负路由；40% 噪声下 sigP 97.8% | ⚠ 抽样总分，须重放 |
| **G3** L3 | 20+ 对抗对，负拒 ≥ 70% / 误杀 ≤ 20%，理由可解析 | 三问四态裁决 + `data/policy.json` + `_verdicts_*` 记录 | ✅ 完备 |
| **G4** L4 | 注入 A → 反例 B → 24h 四项检测 | 变更账本 238 条 · 回滚演练 4 次 · 条件空间合成 · 冲突检测 | 机制齐备，流程未跑 |
| **T-SELF** | S1–S5 | SELF 锚点不可覆盖 + 审计留痕；缺能力返 DEFER | S1–S4 在，S5 未到期 |
| **T-TRUST** | Lv3 需 ECE ≤ 0.15 | 加密 + 密级隔离 + 审计；分级权限已验证 | Lv2 封顶 |

**未测试项**：T-REC 三组重放 · T-JUDGE 20+ 对抗对 · T-EVOLVE 24h 检测 · ECE 校准 · S5 九十天观测（2026-09-11 起算 → 12-10 首测）

> 基准数据集清单、成绩口径边界与复现方式已前置至 [📚 公开评测数据集](#-公开评测数据集)；本节引用其结论时口径不变。

> **对标尺四项修订建议**：① S5 与题型换血不相容 → 观测期题型冻结 ② 注入须经被评系统同一写入闸门（`cg(op=write)`）并入审计链 ③「不基于结构评审」→「行为测试为主 + 结构审计反作弊」 ④ 阈值 70/20/80/ECE 0.15 声明为初始约定

---

## 🧩 七维能力对照（能力 → 入口）

| 维 | 能力 | MCP 入口 |
|---|---|---|
| **S** | 五层记忆 · 负记忆 · 目标槽 · 子图嵌套 · 条件空间路由桶 | `cg(op=write)` `cg(op=link)` `stg(op=relation)` |
| **R** | 四路 RRF 检索 · 条件级负路由 · 因果链 · 时间线 · 目标定向 | `mdcg_recall` `mdcg_search` `cg(op=route)` `stg(op=timeline)` |
| **J** | 三问四态写入裁决 · 主动遗忘 · 冲突检测 · 元认知四观测面 · 递归反思 | `mdcg_remember` `cg(op=verify)` `cg(op=metacognition)` `mdcg_reflect` |
| **C** | 重要性评分 · 预算装包 · 分层注入 · 记忆自净 · 诚实边界 | `cg(op=session)` `cg(op=scrub)` `cg(op=info)` |
| **U** | 知识飞轮 · 归纳固化 · 结构变更账本 / 回滚 · 自维持巡检 | `mdcg_flywheel` `cg(op=consolidate)` `cg(op=maintain)` `cg(op=sustain)` |
| **I** | 自我锚点 · 身份一致性 · 自我状态 · 演化史 · 派生血缘 | `cg(op=identity)` `cg(op=self_state)` `cg(op=evolution)` |
| **T** | 加密 · 密级隔离 · 租户隔离 · 审计留痕 · 保护/遗忘留痕 · 护栏宪章 | `cg(op=protect)` `cg(op=forget)` · [护栏宪章](docs/guardrail-charter.md) |

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

**记忆只有一个真源**：`md_cg/` 认知图（纯 md 文档，随包自带）。白箱引擎与知识库已内迁；
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

> 四端纪律**同源**（`docs/工作纪律_认知图条目_v1.1.json`），由 `scripts/render_discipline.py` 渲染、
> `scripts/verify_discipline.py` 守卫漂移；矩阵见 `docs/discipline/harnesses.yaml`。

---

## 🛠️ 开发

```bash
npm install
npm run build    # TypeScript 编译
npm test         # 真实集成测试（spawn 本机灵枢，验证握手/往返/注册/卸载）
```

测试不依赖 DSH 全组件——用最小 Cordis host（SystemPrompt + ToolRegistry + 插件）隔离不稳定面。

---

## 📏 工作纪律（自我约束）

> **源文件**：[`docs/工作纪律_认知图条目_v1.1.json`](docs/工作纪律_认知图条目_v1.1.json) —— 以**嵌套认知图条目**（`work_discipline`）形式存储，共 **16 条**。
> **每条纪律 ≡ 一个认知图节点**：`conditions`（生效条件：静态 `apply` / 动态 `trigger`）+ `content`（纪律内容）+ `execution`（执行锚点）+ `negative`（不适用条件）+ `response.direct`（路由命中后的直答出口）。
> **定位**：**协议＝自我约束，宪章＝对外约束**——本节约束灵枢自身的工作方式；对外行为边界见[护栏宪章](docs/guardrail-charter.md)。

**一、方法论**

1. **理论先行** —— 重要项目/长期任务必须理论先行：先读相关理论文档与既有实践，再动手设计。
   - 生效：重要项目 · 长期任务 ｜ 不适用：情感交互 · 闲聊
   - 执行：识别项目级别 → 检索理论文档与既有实践 → 输出理论要点 → 再进入设计

2. **全面处理** —— 有任务先读任务要求 → 读工作记忆 → 查相关任务；有相关成果则在原成果上开发，无则先方案设计/技术调研。
   - 生效：有相关记忆 · 有认知图 · 有对应权限 ｜ 不适用：情感交互 · 闲聊
   - 执行：读任务要求 → 读工作记忆 → 查相关任务 →（有成果：复用 ｜ 无：设计 + 调研）

3. **白箱方法** —— 用认知图处理任务：①识别任务条件 ②找该条件所需知识/规则（子流程并行·递归）③精准执行；正确未记录 → 记录，错误 → 找条件，不猜测，未验证不写入。
   - 生效：已读入门四篇（`trained_on_4docs_intro`）｜ 不适用：需快速执行的短期事项 · 情感交互 · 闲聊
   - 执行：识别任务条件 → 找知识/规则（并行递归）→ 精准执行 →（正确：记录 ｜ 错误：找条件）

4. **根因纪律** —— 发现结果与预期不符 → 细究根本原因（不猜测）→ 找到根源所需条件 → 验证后记录认知图，填补不适用条件。
   - 触发：结果与预期不符 · 出现偏差 · 行为与预期矛盾 ｜ 不适用：情感交互 · 闲聊
   - 执行：检测偏差 → 细究根因 → 找根源条件 → 验证 → 记录认知图 → 填补 `negative`

**二、执行纪律**

5. **验证纪律** —— 未经验证不固化：知识/代码入库前必须走验证（回放/断言/回归）。
   - 生效：入库前 · 提交前 ｜ 不适用：情感交互 · 闲聊
   - 执行：入库/提交前 → 回放/断言/回归验证 → 通过才固化

6. **双副本纪律** —— 多副本部署（主仓库 / `site-packages`）的改动必须双向同步，提交前核对 `git status`。
   - 生效：多副本部署 · 改动主仓库/插件 ｜ 不适用：单副本 · 情感交互 · 闲聊
   - 执行：改动 → 同步到所有副本 → 提交前 `git status` 核对

7. **兜底纪律** —— 主路径不可用时必须有等价兜底路径（如 MCP 不可用 → python 直调），并写进 prompt/文档。
   - 触发：主路径不可用 · MCP 不可用 · 依赖缺失 ｜ 不适用：情感交互 · 闲聊
   - 执行：检测主路径不可用 → 切等价兜底 → 写进 prompt/文档

**三、思考与语言**

8. **中文思考** —— 思考/推理语言 = 中文；复杂项目用「我们需要」深思考 + 交流确认（互补盲区），简单项目用「让我」快速执行（省资源）；复杂度由情绪（新奇/挑战/曾受批评）+ 信息差判定；每个推理段开篇用中文短语钉住语言锚点。
   - 生效：中文区域 · 中文项目开发过程 ｜ 不适用：需英文编写的场景 · 英文环境 · 英文文档 · 国际接口
   - 执行：判定复杂度 →（复杂：「我们需要」深思考 + 确认 ｜ 简单：「让我」快速执行）；推理开篇即中文锚点；仅代码/标识符/引用保留原文

**四、信息保密**

9. **敏感信息隔离** —— 含敏感信息（个人隐私、私有内容等）的文档：只写私有库（AEIS），不上传任何公开库；推送/提交描述不写敏感词。
   - 生效：文档含敏感信息 · 含个人隐私 · 含私有内容 ｜ 不适用：文档无敏感信息 · 纯公开技术内容
   - 执行：识别是否含敏感信息 →（含：只写私有库 + 不上传公开库 + 描述不写敏感词 ｜ 不含：正常处理）

**五、图像线**

10. **图像选源护栏** —— 图像处理选源必须核对历史参考/既有管线产物；负路由：原图拒处理版（用原始全彩）、线稿拒实色线稿（用结构线稿 `canny_contour`）、还原拒退化产物（用 `complete_restore`）；未核对规范源 → DEFER（未验证不写入）。
    - 生效：构建图像四类图 · 选图像处理源 ｜ 不适用：已核对规范源 · 纯公开数据
    - 执行：选源 → `_guard_source` 依 kind 判 ACCEPT/REJECT/DEFER → 未 ACCEPT 不构建

11. **历史查询优先** —— 选算法/选源前必须查历史记录（产物图 → 记录如 `ROUNDTRIP.md` → 源码算法 `darkline.py` / `linework.py` / `contour_semantics` / `linecolor.py`）→ 用已走通算法 + 阈值；未找到记录 → DEFER（不盲选、不调参）。线稿不适用 raw canny / `zone_linework`（碎/细 + 网格线）→ 用 `darkline`（Sobel + mag.mean + std×thr_mult，`thr_mult=1.5` 最优）白底黑线。
    - 生效：选图像/算法/源 · 复现已有能力 ｜ 不适用：已有记录且已核对 · 无历史可查的纯新算法
    - 执行：定位产物图 → 查记录 → 定位源码算法 → 确认阈值机制 → 用该算法生成；未找到 → DEFER

12. **算法权威唯一** —— 选算法/算法标准以【唯一权威文档】为准（`VISION_PIPELINE`：线稿 = `darkline.py` Sobel + mean + std×1.5；色块 = `contour_semantics`）；选算法前先查文档（非记忆）；禁止遇问题临时切换算法；换算法须先记录 + 更新文档（版本管理）；勿漂移。
    - 生效：选图像/视觉算法 · 复现已有能力 ｜ 不适用：无对应权威文档的探索期
    - 执行：选算法 → 查唯一权威文档 → 用文档算法 →（若需换：记录原因 + 更新文档后再换）

**六、协作**

13. **访谈澄清（先问清再动手）** —— 重要任务启动时先向使用者提问确认要做什么，按 design tree 逐轮提问（每轮问全部前置已落定的问题，编号 + 推荐答案），直到完全清楚（无未决问题）才执行/固化；事实自查不问使用者，决策归使用者。访谈即调用认知图做功能识别：确认 `conditions`、递归确认子内容（`subgraph`/`depends_on`）、如何 `execution`、`negative` 是什么——与认知图节点四要素完全同构。配套 MCP `grill` 工具族（`grill_start` / `grill_node` / `grill_frontier` / `grill_finish`），frontier 非空拒绝固化。
    - 生效：重要项目 · 需求模糊 · 新任务启动 ｜ 不适用：情感交互 · 闲聊 · 明确单步小改动
    - 执行：任务启动 → 开访谈（`grill_start`）→ 逐轮提问（frontier）→ 全部落定 → 与使用者确认共识 → 执行/固化（`grill_finish`）；放弃用 `abandon`（可逆）

**七、合规**

14. **内容政策合规** —— 任何对外公开的产物（数据集/文档/示例/发布包）必须过「内容政策 + 隐私」两条独立清单：①内容政策——剔除性/成人内容与政治敏感内容（含项目内部的成人研究记录、术语、会话名等标记，具体禁词表由私有库 `POLICY_DENY` 维护）；②隐私——PII/密钥/路径脱敏。过滤必须在生成阶段做（抽样/构建时跳过并从同层补充），不得事后删条破坏分布。双复检 0 命中才提交。已发布发现违规 → 删条 + 重写 git 历史（force push）+ 通知平台清缓存 + 评估残留风险。
    - 生效：对外公开产物 · 提交公开仓库 · 数据集/文档产出 ｜ 不适用：纯内部私有产物 · 不含违规内容且无隐私
    - 执行：产出 → 过内容政策清单 → 过隐私脱敏 → 双复检 0 命中 → 提交；已发布违规 → 删条 + 重写历史 + 通知平台清缓存

**八、执行环境**

15. **命令执行统一走 python** —— 一切命令执行统一经 python 子进程并显式 UTF-8（`encoding='utf-8', errors='replace'`），不经 Windows shell（cmd/PowerShell）直接执行；子进程环境置 `PYTHONUTF8=1` 使 locale 不回落 GBK，规避 `_readerthread` 的 `UnicodeDecodeError` 与 stdout 的 `UnicodeEncodeError`。
    - 生效：执行命令 · 运行测试/脚本 · 跨进程读写文本 ｜ 不适用：IDE 内置工具直调 · 无跨进程的纯内存计算
    - 执行：构造 argv 列表 → `subprocess.run(capture_output=True, text=True, encoding='utf-8', errors='replace')` → env 带 `PYTHONUTF8=1` → `shell=False`

**九、记忆闭环**

16. **任务收尾归档** —— 每次任务执行完必须将关键修改内容存入灵枢记忆：任务完成 → 提炼关键项（改了什么 / 为什么改 / 落在哪个文件·函数·行 / 验证结论）→ 写入灵枢记忆（认知图 / MCP memory）→ 标注关联节点并更新 `subgraph`/`depends_on` 关系；只存关键项（决策 / 根因 / 可复用算法与路径 / 版本变更），不存过程流水。**写入范围仅限核心修改（内容 / 原因 / 位置 / 验证结论四要素），严禁写入中间过程、试错步骤、调试细节、重复确认等无效信息**——避免污染记忆、干扰后续检索。与第 2 条（全面处理：先查记忆）构成「查记忆 → 执行 → 写记忆」闭环。
    - 生效：任务执行完成 · 修改落地后 · 交付后 ｜ 不适用：情感交互 · 闲聊 · 纯查询无改动
    - 执行：任务收尾 → 提炼核心修改（内容/原因/位置/验证结论四要素，不写中间过程 / 试错 / 调试 / 重复确认）→ 写入灵枢记忆（认知图 / MCP memory）→ 标注关联条目 + 更新 `subgraph`/`depends_on`

**路由出口**（`response.direct`）：重要/长期 → 理论先行；有相关成果 → 全面处理；已读四篇 → 白箱方法；有偏差 → 根因纪律；入库前 → 验证纪律；多副本 → 双副本纪律；MCP 不可用 → 兜底纪律；对外公开 → 内容政策合规；执行命令 → python/UTF-8；任务完成 → 任务收尾归档（只记核心修改）。

## 护栏宪章（接入即接受约束）

本插件接入即接受 **[灵枢护栏宪章 v2.0-published](docs/guardrail-charter.md)** 约束——对外部智能体与人类使用者的行为边界作出公开、可执行、可审计的规定，并保护人类使用者。宪章效力不高于智能论协议本身（协议＝自我约束，宪章＝对外约束）。

## 许可证

MIT © 荣（FuRongJun-1999）· 灵枢 AEIS 工程实现

DeepSeek Harness 为 DeepSeek 官方开源项目（MIT），本插件与之无隶属关系。
