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
- **🛡️ 无幻觉**——记什么、取什么、能不能写入，全部由确定性规则裁决，不依赖 LLM 黑箱判断；写没写成功看 `committed` 字段，绝不假装通过；全链路审计留痕、结果可复现
- **🔌 多智能体适用**——同一份大脑（`md_cg/`）+ 同一份纪律，接入 DSH · CodeBuddy · ZCode · Codex CLI，任何 MCP 宿主可直接挂载（见[多 harness 接入](#多-harness-接入按端分目录)）
- **😊 轻松使用**——三步接入，装完像往常一样对话即可；记忆本体是纯 md 文档，任何编辑器可直接打开审阅
- **📊 可复现评测**——`locomo-zh-500`（500 题）与 `bench6-100-zh-en`（六家横评 · 中英双查）数据集随仓公开，一条命令复现我方成绩（见[公开评测数据集](#-公开评测数据集)）

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
<summary><b>CodeBuddy / ZCode / Codex CLI 等其它宿主也能用吗？</b></summary>

能。大脑 <code>md_cg/</code> 是标准 stdio MCP server（<code>python -m md_cg.mcp_server</code>），任何支持 MCP 的宿主可直接挂载；四端接入差异只在纪律注入方式，见<a href="#-多-harness-接入按端分目录">多 harness 接入</a>。
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
