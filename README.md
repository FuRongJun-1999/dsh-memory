# 让 AI Agent 拥有不可遗忘的记忆

**灵枢（Lingshu）** —— 高性能 · 无幻觉 · 多智能体适用的长期记忆系统（v0.4.5）

[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)](https://awesome-dsh-plugin.com) [![dsh.so security](https://www.dsh.so/badge/dsh-memory-7.svg)](https://www.dsh.so/artifact/dsh-memory-7)  [![DSH 适配](https://img.shields.io/badge/DSH%20%E9%80%82%E9%85%8D-%3E%3D0.1.2--rc.1-4E9BF1)](https://github.com/deepseek-ai/deepseek-harness/releases) [![Protocol](https://img.shields.io/badge/Protocol-MCP-blue)](#多-harness-接入按端分目录) [![Node](https://img.shields.io/badge/Node-%3E%3D22.19-brightgreen)](package.json) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

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
- **📊 可复现评测**——`locomo-zh-500`（500 题）与 `bench6-100-zh-en`（六家横评 · 中英双查）数据集随仓公开，一条命令复现我方成绩（见[公开评测数据集](#-公开评测数据集)）；**已有第三方独立验证**：七轮复评（统一评分 v7 · 灵枢 9.258）与 LoCoMo 独立复现（自报数字逐位一致 · 见[第三方复评](#第三方复评七轮独立评估)）

---

## 🗺️ 平台全景

> 灵枢是**平台**而非单一检索组件——同一仓库内五件套构成带记忆的智能体运行时，各层独立可用、边界正交（大脑零依赖其余各层）：

| 层 | 位置 | 一句话定位 | 文档入口 |
|---|---|---|---|
| 🧠 **灵枢大脑** | [`md_cg/`](md_cg/) | 记忆系统本体：对话沉淀为 md 认知图，记什么 / 取什么 / 能否写入全由确定性规则裁决，四层证据防火墙白箱剔除弱证据干扰 | [README 详细版](docs/mdcg/README详细版_v0.4.5.md) |
| ⚙️ **Rust 检索引擎** | [`rust/`](rust/) | 只读侧检索核心：零第三方依赖三形态（库内嵌大批量 / `--serve` 多智能体进程实例 / 评测器），与 Python 口径逐位对齐 | [rust/README.md](rust/README.md) |
| 🐝 **蜂群运行时** | [`swarm/`](swarm/) | 多进程蜂群执行层：.pbc 确定性实例 + Gossip 拓扑 / 水位信箱 / WAL-HMAC / 信任聚合 / 健康评分（Rust 纯 std 零依赖） | [功能说明 v0.6](docs/swarm/蜂群多智能体_功能说明_v0.6.md) |
| 📜 **中文编译器** | [`compiler/`](compiler/) | 术数编译器：词法 → 语法 → 名实校验 → 白名单代码生成 → 验证终裁，五环确定性编译链 + 封闭指令集结构性沙箱 | `python -m compiler.cli`（模块内文档） |
| ⬢ **蜂巢并发引擎** | [`hive/`](hive/) | 蜂群多智能体并发调度：Rust 纯 std 零依赖 worker 池（原子领取 / 心跳 / 超时强杀 / kill / 崩溃恢复），文件协议即接口，LLM 调用委托零依赖 Python 执行器子进程，MCP 四工具接入 —— **逐步稳定中** | [hive/README.md](hive/README.md) |

五件套共享同一套 17 条工作纪律与记忆闭环（见文末[工程纪律](#-工程纪律与设计者视角可选推荐)），接入方式互不牵动——只用记忆就只接大脑，不必理解蜂群与编译器。

> **📣 蜂巢反馈邀请**：`hive/` 是五件套里最新的一层，目前处于**逐步稳定阶段**——调度生命周期已闭环（原子领取 / 心跳 / 超时强杀 / kill / 崩溃恢复）并通过回归验证，但并发与崩溃恢复这类路径只有在**真实任务、真实机器**上跑得足够多才会真正稳定，因此这一层会持续迭代。我们特别**欢迎下载试用后反馈**：拉起失败、任务卡住、心跳异常、平台差异、kill 不生效等失败路径，对我们比「跑通了」更有价值。请开 [Issue](https://github.com/FuRongJun-1999/dsh-memory/issues) 并附 `hive_doctor` 输出（serve 存活 / 任务统计 / env 检查）。

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
- 完整配置项（30+ 项）· 自动记忆机制 · DSH 看门狗 → [README 详细版](docs/mdcg/README详细版_v0.4.5.md)
- **非 DSH 宿主**（CodeBuddy / ZCode / Codex CLI / Claude Code）：走[多 harness 接入](#多-harness-接入按端分目录)，各端有独立三步接入说明
- **装后验证**：重启 DSH 后对 Agent 说「列出你的记忆工具」应看到 `cg` / `stg`（`tools: 'all'` 时还有 `mdcg_*`）；大脑直连验证：`python -m md_cg.mcp_server`（stdio JSON-RPC）收到 initialize 应答即通，更多细节见 [README 详细版](docs/mdcg/README详细版_v0.4.5.md)

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
> 完整题型分解 / MRR 全表 / 逐家入库取证 / 偏差判定单 → [六家横评报告](docs/eval/横评_六家100题中英双查_v1.0.md) · 题集 → [data/benchmarks/bench6-100-zh-en/](data/benchmarks/bench6-100-zh-en/README.md)

---

## 🧪 弱证据会干扰检索：三分离与证据防火墙（实证）

> **外部源码级评审（GPT）与四臂弱语义噪声注入实验共同实证的一个反直觉结论**：**语义完整度 ≠ 证据强度 ≠ 召回价值**——语义高度省略的「弱证据」语料恰恰是最需要被召回的 episodic 事实；而**条件判断层（负条件 / 否定反事实）的弱证据节点会冒充正确答案，干扰检索**。

- **实证语料「我在喝水」**：语义上高度省略（谁在喝？在哪喝？均未说），但作为 episodic 事实承诺明确。当提问是「你刚才在干什么？」时，问句与语料**词面零重叠**——纯词法检索 top1 命中 **0/8**（省略式 episodic 全部漏召），而语义路作为候选生成器把 **8/8** 拉进 top10。词法满格的前提（词面共享）在事件类记忆上不成立。
- **条件判断的弱证据干扰检索**：同一实验中 8 个否定反事实节点（「我没喝水」）与 gold 词面高度相似，无防线时冒充前排；灵枢四层证据防火墙（召回前负条件路由 → 候选生成排除 → `judge_ranking` 白箱终排 → 资格标注）将其 **8/8 全部 REJECT 剔除**，top10 无冒充。
- **可复现**：`python -m md_cg.test_sem_noise`（42 节点确定性语料，四臂 A_lex / B_sem / C_fusion / D_firewall 对照，7 断言）。

---

## 🌐 中英双语检索差距：我们用中文语义归一化解决英文检索（实证）

> **直接回答**：英文检索问题，我们用**中文翻译 + 语义归一化**解决——英文 query 经 AI 语义归一化为中文标准关键词（归一主体=AI，系统只供词表真源），再经中→英字级原子映射与双语原子库匹配，返回英文原文。同一份 500 题语料上，**给定中文标准关键词时检索效果 hit@10 = 99.8%**（hit@1 96.8%；检索侧上界口径——AI 归一环节的质量未纳入该评测，机械归一的端到端下界见下表 ④）。三条对照边界：不做归一化、拿英文原题直接词面匹配只有 78.2-81.2%（同义词鸿沟硬边界）；机械词典查表归一端到端实测仅 57.6%；而 ②路对归一噪声高度鲁棒——漏 20% 关键词 / 错译 20% / 混入噪词，hit@10 仍稳在 99.2-99.8%。**结论：路线成立且不要求 AI 归一完美，只需大致方向对；99.8 是检索侧上界，端到端真实水平由 AI 归一质量决定（机械下界 57.6，AI 上界趋近 99.8）**。

**第三方独立验证（2026-09-15，[报告全文](docs/eval/第三方验证报告_LoCoMo_灵枢_.md)）**：上述关键数字已被第三方独立复现——②路 96.8/99.8/99.8 **逐位一致**，中文 96.4→96.8（噪声内）；并实证该 99.8 由**中文摘要层**挣得（去英文处理层 hit@10 反为 100.0%），英文标准归一化组件自身端到端为 81.0%（写入侧机械归一口径，较不归一 +58pp），检索失败 100% 归因归一化丢词/错译而非排序。本节口径标注与该实证一致：99.8 是「给定中文标准关键词」的检索侧上界，不声称英文机械归一化独立达到该水平。

**测试报告**（灵枢公开仓评测，方法学与口径真源 → [`md_cg/semantic/REPRODUCE.md`](md_cg/semantic/REPRODUCE.md)）：

| 方法 | hit@1 | hit@5 | hit@10 | 语料 |
|---|---|---|---|---|
| ① 中文原子语义（md_cg 主链路：char-bigram + 四路 RRF + 同义扩展 + terms） | 94.6% | 99.2% | **99.2%** | locomo-zh-500 · 500 题（中文题面） |
| ② **英文检索 · 中文语义归一化桥接（主路线）**：AI 归一为中文关键词 → 字级英文原子映射 × 双语原子库 Jaccard（**给定关键词的检索侧上界**） | **96.8%** | **99.8%** | **99.8%** | locomo-zh-500 · 500 题（同 qids） |
| ③ 英文原题直接原子匹配（不做归一化的对照） | 50.0% | 74.6% | **81.2%** | locomo-zh-500 · 500 题（同 qids 英文原题） |
| ④ 英文问句 → 机械词表归一端到端（②链路的机械化对照：归一不借助 AI 的真实下界） | 24.6% | 46.2% | **57.6%** | locomo-zh-500 · 500 题（同 qids 英文原题；2026-09-15 第三方错译暴露面修正后 24.0/46.0/57.2→本行，CEDICT 层低置信标记已落地） |
| 英文反事实：硬套中文 char-bigram 主链路（默认态） | 27% | 45% | 56% | bench6 · 100 题（口径不同，只看量级） |

> ②③是**同一评测集上的隔离实验**：② 的 query 走中文关键词语义链（AI 归一化的输出形态），③ 连归一化也不做、直接拿英文自由表达提取原子——②③ 之差（99.8 vs 81.2）=「关键词级语义链」与「自由英文词面」两种 query 输入形态在检索链路里的效果差（同义词鸿沟 + 归一化桥接的合并贡献）。**AI 归一环节本身的质量未单独评测**——其机械替代的端到端下界由 ④ 给出（57.6%）。②路鲁棒性实测（query 确定性扰动后走同一 ② 链路）：漏 20% 关键词 ⑤=99.4 / 插 3 噪词 ⑥=99.8 / 错译 20% 关键词 ⑦=99.2（hit@10）——归一结果只要过半正确，hit@10 即稳 99%+，**AI 归一的实际门槛远低于完美归一**。doc 侧各臂相同（中文五槽加工面的字级原子映射 ∪ 英文正文归一词，与 ① 同属写入侧加工口径）。历史沿革：早期无加工面语料口径测得 ②=87-88、③=79.0（dsh 端文档口径），方法学真源见 REPRODUCE.md；机械词级归一→纯中文库（u2，33.6% 上界）已裁定排除并归档证据链。

**差距三层归因（按权重排序）**：

1. **同义词鸿沟（根本原因，语言固有属性）**。中文「概念 → 表达」约 **1:1~1:2**（95 个同义词对），字面重叠天然命中，词面匹配几乎不打折；英文每概念平均 **5.2 种**表达（CC-CEDICT 语料统计，8,493 汉字展开出 172,950 个英义对，**1,820 倍**于中文）。上表 ② vs ③ 就是这道鸿沟的**直接隔离实验**：同一语料，query 侧做中文语义归一化得 99.8%，不做归一化直接英文词面匹配即降至 81.2%——鸿沟真实存在，但**在查询侧做一次语义归一化即可闭合**，不需要向量嵌入。
2. **归一化是正解，机械归一是死路（主路线裁定的依据）**。机械词典查表翻译端到端实测仅 **57.6%**（④臂：英文问句 → CEDICT 28294 键词表直译 → ②同链路），且低于「完全不归一」的 81.2%（③臂）——机械直译把可译词错译为错误原子（race→人种），反而毁掉原本有效的词面贡献；更早的机械词级归一→纯中文库口径上界也只有 33.6%（已排除）。根因是英文自然问句的信息密度远低于标注关键词（词面交集 p50=1 vs 8），机械替换无法补足信息差；查询侧归一化由 **AI 完成**（理解式归一，如 take up a hobby → 培养爱好），系统只供词表真源与字级映射——②的 99.8%（上界）与机械路 57.6%（下界）之间的空间，就是 AI 归一要填的部分；⑤⑥⑦证明这个要求只需「大致方向对」。
3. **架构非对称（设计裁定）**。中文链路的四路 RRF / 同义扩展 / terms 字段全部建立在「字面=语义」的中文前提上，直接跑英文实测劣于独立路（反事实 56%）——英文按裁定走「归一化桥接 + 原子 Jaccard」独立路，不硬套中文 char-bigram 管线，是**有意的取舍**而非遗漏。中→英字级映射覆盖 6,319 字（97.2%），长尾派生词（happy/happiness）不折叠——残余失配由查询侧 AI 归一化吸收，这正是 ② 反超 ③ 21.6pp 的来源。

**要不要上语义向量检索？** 向量嵌入可以弥合同义鸿沟，但会引入嵌入模型依赖与索引体积，与灵枢「零重依赖、纯词面可复现」的公开仓原则冲突，**当前明确不做**；归一化桥接已把检索侧上界做到 hit@10 99.8%（鲁棒性：归一不完美时仍 99%+），满足「答案在候选池」的记忆系统主用途。

**渐进式语义检索（Progressive Semantic Retrieval，正式机制 v0）**。查询不是固定语义结构，而是**不断收紧的约束集合**——语义解析的完整性与检索的必要性不是同一个问题：从最小可靠语义（部分归一原子）开始宽检索，再按候选间区分度逐步增加条件使语义收敛；DEFER ≠ 失败，=「当前语义分辨率不足，继续获取条件」，与证据防火墙四态天然衔接。同一份 500 题实测：一次性全原子 96.8/99.8/99.8（=②锚点）；只宽检 50% 核心原子 85.2/95.8/97.0；**宽检索→区分性条件渐进收紧（平均 +2.97 个条件）收敛到 93.6/98.8/99.0**——与一次性差 0.8pp，实证「不必一句话完成语义理解」。受控干扰池进一步实证排序面消歧（top1 稳 gold、渐进不引入新冒充），并如实暴露边界：条件面冒充（生效条件被伪造为 gold 同款）不被内容词渐进消除——词面条件确认必要非充分，真伪判据=证据基底分离（另案）。控制器 `md_cg/progressive.py`（纯函数、确定性、评分器注入式），实验 `md_cg/bench_progressive.py`。

---

## 📚 公开评测数据集

📎 全部随仓库公开（CC BY-NC 4.0），可直接下载用于你自己的记忆系统对照评测：

| 基准 | 归属 | 状态 |
|---|---|---|
| **locomo-zh-500** | **自建**（LoCoMo 中文派生 · 500 题 / 567 turns / 0.6 MB） | **已随仓库公开** `data/benchmarks/locomo-zh-500/` · 可复现 · **我方成绩：中文 hit@1 94.6% · hit@5 / hit@10 99.2%（md_cg 完整主链路）；英文（语义归一化桥接）hit@10 99.8%——见上[中英双语检索差距](#-中英双语检索差距我们用中文语义归一化解决英文检索实证)①② 行** · **第三方独立复现：中文 96.8/99.6（自报 96.4/99.8 噪声内）、英文主路线 96.8/99.8/99.8 逐位一致** → [第三方验证报告](docs/eval/第三方验证报告_LoCoMo_灵枢_.md) |
| **bench6 · 六家横评** | **自建**（LoCoMo 中文派生 · 100 题 / 137 turns · **中英双查** / 约 90 KB） | **已随仓库公开** `data/benchmarks/bench6-100-zh-en/` · **六家同口径对照**（灵枢 5 口径 / 纯向量 RAG / mem0 / Graphiti / GraphRAG / Letta 两模式）· 报告 → [横评_六家100题中英双查_v1.0.md](docs/eval/横评_六家100题中英双查_v1.0.md) |
| LoCoMo | 第三方 `mteb/LoCoMo` BEIR（1976 题 / 5882 turns） | 上游来源（英文原版） |
| memory-bench-1000 | **自建** | SNR 见评分报告 v2.0；已公开 `data/memory-bench-1000.jsonl` |

> 上表四行性质不同，勿混读：`locomo-zh-500` 的分数是**本仓库我方成绩**（基于LoCoMo自建并公开的评测集，可复现）；`bench6 · 六家横评` 是同源派生的**小型同口径对照集**（零干扰池，只做六家系统横向对照，**非我方单方成绩**）；LoCoMo 一行指**上游英文原版 1976 题**，本仓库未在其上产出完整成绩；`memory-bench-1000` 是自建记忆库的评分报告。
> **该成绩的性质（非虚假声明）**：`locomo-zh-500` 的分数是**写入侧结构化加工后的检索成绩**——入库前把每轮对话加工为「身份 / 时间 / 摘要 / 词 / 条件四槽」条目，再走词法 + 同义扩展检索。这与主流记忆系统所用的**向量化嵌入 + 关键词/摘要压缩**属**同一类写入侧加工**，差异只在索引与检索算法，不在「是否对原文做了加工」。因此该口径可用于**同口径对照**，不是对裸文本直读的虚高取巧。
> `locomo-zh-500` 是**本仓库对外发布的检索评测集**：供外部在**同一份中文题面**上对自己的记忆系统做可对照评测。它只评检索命中（hit@k / MRR），**不评答案正确性**；被测池为**零干扰**（池内全是 gold），故高命中率不可外推为端到端记忆能力——完整边界与许可见 `data/benchmarks/locomo-zh-500/README.md`。
> `bench6-100-zh-en` 沿用同一口径，并**每题提供中英两套词面**（评「换查询语言后是否仍命中」）；它同样是**上界对照集**——家间差距小于约 16% **不可判为显著**；评测入口已随仓库公开（`run_bench.py`：零依赖口径复现 + Adapter 协议接入你自己的系统），接入任意llm和向量方法都可复现，详见 [横评报告](docs/eval/横评_六家100题中英双查_v1.0.md) 与 `data/benchmarks/bench6-100-zh-en/README.md`。

**复现我方成绩**（零上游依赖）：

```bash
python -m md_cg.bench_locomo_zh_public   # 中文：只读 data/benchmarks/locomo-zh-500/，产出公开词法口径参考量级（hit@1 93.6% 单路 / 97.6% +同义扩展）；上表 94.6/99.2 为 md_cg 完整主链路（四路 RRF + 同义扩展 + terms）成绩
python -m md_cg.bench_en_atoms_public    # 英文：语义归一化桥接七臂（② 96.8/99.8/99.8 主路线·检索侧上界 · ③ 81.2 不归一对照 · ③a 78.2 纯正文对照 · ④ 57.6 机械归一端到端下界 · ⑤⑥⑦ ②路鲁棒性 99.2-99.8）；英文原题面为上游派生不入库，自备后即可全量复现
python -m md_cg.bench_progressive        # 渐进式语义检索双实验（G0 96.8/99.8/99.8 =②锚点自校验 · 只宽检 85.2/97.0 · 渐进收敛 93.6/99.0 · 受控池排序面消歧+条件冒充边界）
# 第三方独立评测脚本（第三方交付物原样入库；脚本内 REPO 为第三方沙箱路径，复现需改为本机仓库路径）
python test/locomo_independent_eval.py   # MdCG 引擎口径五臂（A 中文五槽 / B 英文原文 / C 标准归一化 / D 双语并集 / F 语义摘要路 + 随机基线）
python test/locomo_jaccard_probe.py      # 主路线 Jaccard 口径拆解（J2_full 完整版 / J2_zh 仅中文层 / J2_body 仅英文归一词 / J0_raw 英文原词）
```

> 自建 bench 的噪声层 400 条 + unlabeled 边界 350 条为天然负对照；任何基准报告须带**干扰抑制负例组**与 **T-JUDGE 负例拒绝率**双向报告（遵守「只报总分 = 不通过」）。

---

## 🎯 能力自评（内部标尺，非横评声明）

> 项目维护者按内部七维标尺（结构 / 检索 / 判断 / 调用 / 演化 / 连续 / 可信）自评 **综合 8.6 / 10**（全部维度 ≥ 8.5），并按外部行为级门槛自评为**条件性 L4 → L5 路上**——含未完成项与扣分理由的逐维证据，见 [AGI 七维评分报告 v2.0](docs/eval/AGI七维评分报告_md_cg_v2.0.md)。
> **不虚高的坦白**：五个 8.5 的共同上限是「机制齐备、门槛项未齐」——T 零信任未落地、R 仍是规则层意图理解、C 去污染仍是抽样而非穷尽、U 的 LLM 固化动作尚未自动放行。

### 第三方复评（七轮独立评估）

> 独立评估者（非项目方）以「统一评分 v7」对灵枢与 deja-vu 做同权重八维对照（检索中英 / 可复现性 / 工程测试 / 架构独立性 / 诚实度 / 生态适配 / 部署运维）：**灵枢 9.258 / deja-vu 9.119（+0.139，七轮首次为正——评审者声明该差距在评审噪声以内）**，收敛轨迹 `7.79→8.29→8.57→8.72→9.13→9.133→9.258`；v7 含对自身四条建议全撤回的勘误（§三点五：所称「缺失能力」经复核均早已有之，含 `cg(op=ingest)` 后向索引通道）
> 报告全文→ [第三方验证报告_灵枢_vs_dejavu_统一评分_v7.md](docs/eval/第三方验证报告_灵枢_vs_dejavu_统一评分_v7.md) · 评估日期 2026-09-15，被评灵枢基线 `38412c4`
>
> **LoCoMo 第三方独立验证**（同日另一份独立报告，评测全流程从零实现、不调用灵枢任何 `bench_*` 脚本）：中文 96.8/99.6 独立复现（自报 96.4/99.8，噪声内）；英文主路线 ② 96.8/99.8/99.8 **逐位一致**；并给出更严格归因——99.8 由中文摘要层挣得（去英文层 hit@10 反为 100.0%）、英文标准归一化端到端真实水平 81.0%（写入侧机械归一口径，较不归一 +58pp）、检索失败 100% 归因归一化丢词/错译而非排序；同时确认数据集区分度（query 对 gold 覆盖 0.875 vs 非 gold 最佳 0.469）与 OOV 如实透出。报告全文→ [第三方验证报告_LoCoMo_灵枢_.md](docs/eval/第三方验证报告_LoCoMo_灵枢_.md) · 配图 → [第三方验证报告_LoCoMo_灵枢_.png](docs/eval/第三方验证报告_LoCoMo_灵枢_.png) · 独立评测脚本 `test/locomo_independent_eval.py`、`test/locomo_jaccard_probe.py`（第三方交付物原样入库，`REPO` 变量为第三方沙箱路径，复现需改为本机仓库路径）
>
> **口径声明**：两份报告均为外部独立口径，与上方内部七维自评（8.6）是**多套独立口径，分数不可互比**；LoCoMo 报告同时验证了数字可复现性与归因边界，其归因发现已如实吸收进[中英双语检索差距](#-中英双语检索差距我们用中文语义归一化解决英文检索实证)一节。

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
| 加密 · 密级隔离 · 审计留痕 · 保护/遗忘 | `cg(op=protect)` `cg(op=forget)` · [护栏宪章](docs/mdcg/guardrail-charter.md) |
| 记忆可靠性闸（对话→六要素候选→编外复核→落库） | `cg(op=ccg)` |

> **索引链**：能力 → op（本表）→ 实现模块（下方[工具面](#-工具面)认知图）→ 行号级代码映射（[功能调用映射表](docs/mdcg/功能调用映射表_v0.1.md)）——每一步都可从 README 一跳到达源码，一致性由 `scripts/cogmap_sync.py check` 守卫。

### 🧱 记忆可靠性闸：CCG 六要素编译（`cg(op=ccg)`）

把对话记录编译成可检索的 CCG 六要素条目（`# 功能名 / # 生效条件 / # 子功能 / # 执行 / # 验证方式 / # 不适用条件`），且**编译者不得自证**——LLM 产出的候选必须经**认知图之外的编外单元**复核才准落库（机械拒绝码 `E041`，不依赖 prompt 自觉）。候选以内容摘要绑定暂存（`_ccgc_pending/`，索引不可见），三次独立调用间防篡改。

| 步骤 | 调用 | 结果 |
|---|---|---|
| ① 编译 | `cg(op=ccg, action=compile, node_id=…, dialog=…)` | 六要素候选 + 名实门校验（每个写入值必须是原文子串），**不当场写库** |
| ② 复核 | `cg(op=ccg, action=review, node_id=…, blocking=true)` | 编外单元裁决：蜂巢 `reflect`/`verify` 优先；蜂巢不可用则**返回配置指引**（不假装可用），显式 `allow_degrade` 才降级为子代理 |
| ③ 落库 | `cg(op=ccg, action=link, node_id=…, apply=true)` | 摘要校验 + 签章准入通过才写入 |

错误码：`E040` 无签章 · `E041` 自证拒绝 · `E042` 复核未通过 · `E043` 只允许修正四槽（`action=recalibrate`）。`action=catalog` 自描述全部动作，`action=units` 体检复核通道（三态：蜂巢 / 待配置 / 子代理降级）。

---

## 🧰 工具面

<!-- COGMAP:BEGIN (scripts/cogmap_sync.py 自动生成 · 真源 md_cg/mcp_server.py · 勿手改段内) -->

**两个认知基元 · 38 个 op**（`kernel` 面）——下列 op 清单、实现模块与全部链接行号由 [cogmap_sync](scripts/cogmap_sync.py) 从真源自动提取，`check` 门禁守卫漂移；**点击任意名字直达源码对应行**：

| 基元 | op 数 | op 清单（点击直达实现分支） |
|---|---|---|
| **[`cg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L496)** 认知图统一入口 | 34 | [`help`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1708) [`theory`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1714) [`link`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1731) [`info`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1840) [`route`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1857) [`read`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1877) [`write`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1898) [`goal`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1906) [`task`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1925) [`recent`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1928) [`verify`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1940) [`review`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1944) [`forget`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1960) [`protect`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1966) [`identity`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1969) [`consistency`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1972) [`metacognition`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1975) [`self_state`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1978) [`evolution`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1981) [`sustain`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1984) [`scrub`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1987) [`predict`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1990) [`causal`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1993) [`whitebox`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1996) [`index_code`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1999) [`index_doc`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2031) [`ref`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2067) [`session`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2070) [`ingest`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2073) [`export`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2076) [`maintain`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2079) [`consolidate`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2082) [`insight`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2085) [`ccg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2088) |
| **[`stg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L871)** 语义时空图入口 | 4 | [`relation`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2592) [`timeline`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2594) [`anchors`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2598) [`consistency`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2601) |

**op → 实现模块**（认知图投影：功能在哪段代码，一眼可达）：

| op（点击直达实现分支） | 实现模块（点击直达源码） |
|---|---|
| [`help`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1708) [`route`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1857) [`goal`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1906) [`task`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1925) [`recent`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1928) [`verify`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1940) [`review`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1944) [`forget`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1960) [`protect`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1966) [`identity`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1969) [`consistency`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1972) [`metacognition`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1975) [`self_state`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1978) [`evolution`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1981) [`sustain`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1984) [`scrub`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1987) [`predict`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1990) [`causal`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1993) [`whitebox`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1996) [`ref`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2067) [`session`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2070) [`ingest`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2073) [`export`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2076) [`maintain`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2079) [`consolidate`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2082) [`insight`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2085) [`ccg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2088) | [`_cg_dispatch` 内联](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1705) |
| [`read`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1877) [`index_code`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1999) [`index_doc`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2031) | [`refindex`](md_cg/refindex.py) |
| [`info`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1840) | [`audit`](md_cg/audit.py), [`links`](md_cg/links.py), [`nodefile`](md_cg/nodefile.py), [`theory`](md_cg/theory.py) |
| [`link`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1731) | [`evidence`](md_cg/evidence.py), [`links`](md_cg/links.py), [`provenance`](md_cg/provenance.py), [`signer`](md_cg/signer.py) |
| [`theory`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1714) | [`theory`](md_cg/theory.py) |
| [`write`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1898) | [`writepipe`](md_cg/writepipe.py) |
| [`relation`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2592) [`timeline`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2594) [`anchors`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2598) [`consistency`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2601) | [`_stg_call` 内联](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2588) |

**细粒度面**（`MDCG_MCP_SURFACE=full`，插件运行时使用）：[`cg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L496) + [`stg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L871) + **31 个 `mdcg_*`** = **33 个工具**：

[`mdcg_remember`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L97) [`mdcg_recall`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L118) [`mdcg_search`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L151) [`mdcg_get`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L160) [`mdcg_reflect`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L165) [`mdcg_verify`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L171) [`mdcg_flywheel`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L179) [`mdcg_mine_fix_pairs`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L184) [`mdcg_rejected`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L189) [`mdcg_unresolved`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L195) [`mdcg_propose`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L201) [`mdcg_review_list`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L209) [`mdcg_review_decide`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L214) [`mdcg_review_records`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L226) [`mdcg_forget`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L234) [`mdcg_protect`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L242) [`mdcg_forgetting_history`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L252) [`mdcg_identity`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L258) [`mdcg_consistency`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L284) [`mdcg_metacognition`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L304) [`mdcg_self_state`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L323) [`mdcg_predict`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L361) [`mdcg_causal`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L389) [`mdcg_evolution`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L406) [`mdcg_restore`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L429) [`mdcg_health`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L434) [`mdcg_whoami`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L439) [`mdcg_ingest`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L444) [`mdcg_watermarks`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L453) [`mdcg_whitebox`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L458) [`mdcg_service_info`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L479)

逐个 op 的「功能 → 代码 → op」行号级映射另见[功能调用映射表](docs/mdcg/功能调用映射表_v0.1.md)。

<!-- COGMAP:END -->

| `tools` 模式 | 暴露数 | 说明 |
|---|---|---|
| `'core'`（**默认**） | **2** | 仅 `cg` / `stg` |
| `'brain'` | **30** | `cg`/`stg` + 28 细粒度 |
| `'all'` | **30** | full 面 33 − 3 个宿主级风险工具 |

> 风险工具 `mdcg_forget` / `mdcg_restore` / `mdcg_review_decide` 需 `can_admin`，即使 `tools: 'all'` 也不自动暴露。
> 35 op 已逐一冒烟验证：**35/35 可达，0 未知 op、0 意外崩溃**。
> 历史 82 工具（旧 aeis 引擎）去向见 [迁移映射](docs/mdcg/灵枢82工具_功能整理与迁移映射_v0.1.md)。

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
| **[docs/ 目录索引](docs/README.md)** | 六域快速索引（mdcg / swarm / hive / theory / eval / plans）· 新文档归域规则 |
| [README 详细版](docs/mdcg/README详细版_v0.4.5.md) | 完整能力说明 · 配置项全表 · 安装与验证细节 |
| [发布说明 v0.4.5](docs/mdcg/release_v0.4.5.md) | 本版变更 / 兼容性 / 升级指引 |
| [AGI 七维评分报告 v2.0](docs/eval/AGI七维评分报告_md_cg_v2.0.md) | 逐维得分依据 / 扣分项 / 实库证据 / 诚实边界 |
| [第三方复评 · 统一评分 v7](docs/eval/第三方验证报告_灵枢_vs_dejavu_统一评分_v7.md) | 独立评估者七轮对照（灵枢 vs deja-vu）：八维加权 / 收敛轨迹 7.79→9.258 / 评审偏差声明 / 自身建议全撤回勘误 |
| [第三方验证 · LoCoMo 独立复现](docs/eval/第三方验证报告_LoCoMo_灵枢_.md) | 独立实现评测全流程：自报数字逐位复现 / 归因拆解（中文摘要层 vs 英文归一化 81.0%）/ 静默错译样本 / 数据集区分度证伪检查（配图 `第三方验证报告_LoCoMo_灵枢_.png`） |
| [功能调用映射表](docs/mdcg/功能调用映射表_v0.1.md) | 任何功能 → 调用哪段代码（含行号、MCP op） |
| [护栏宪章 v2.0](docs/mdcg/guardrail-charter.md) | 对外部智能体与人类使用者的行为边界 |
| 教学四篇 | [白箱智能是什么？](docs/theory/白箱智能是什么？.md) · [智能的认知过程](docs/theory/智能的认知过程.md) · [智能的公理化基石](docs/theory/智能的公理化基石.md) · [信息差为什么必然存在](docs/theory/信息差为什么必然存在且自然扩大.md) |
| [工作纪律·认知图条目 v1.1](docs/工作纪律_认知图条目_v1.1.json) | 自我约束的 17 条工作纪律（嵌套认知图条目 `work_discipline`） |
| [六家记忆系统横评 v1.0](docs/eval/横评_六家100题中英双查_v1.0.md) | 100 题 · **中英双查** · 六家同口径对照；含判定单 / 条件层归因 / 诚实边界（题集 → [data/benchmarks/bench6-100-zh-en/](data/benchmarks/bench6-100-zh-en/README.md)） |
| [Rust 检索库](rust/README.md) | `mdcg_eval` 三形态：库内嵌大批量检索 / `--serve` 多智能体进程实例 / 公开数据集评测器（零依赖 · 与 Python 口径逐位对齐） |
| [蜂群多智能体](docs/swarm/蜂群多智能体_功能说明_v0.6.md) | `swarm/` 多进程蜂群执行层（2026-09-13 自 protocol-compiler 迁入，大脑核心内部能力）：.pbc 确定性实例 + Gossip/拓扑/水位信箱/WAL-HMAC/信任聚合/健康评分（Rust 纯 std 零依赖 · 159 断言回归全绿） |

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

### Python 测试约定（必须 `python -m`）

`md_cg/` 等包内测试普遍使用**包内相对导入**，必须以模块方式从**仓库根**运行；直接 `python md_cg/test_xxx.py` 会 ImportError（59/61 踩坑实测）。一键入口已固化该约定：

```bash
python scripts/run_tests.py                  # 全量（md_cg + compiler + swarm）
python scripts/run_tests.py md_cg -k p44     # 按组 / 关键字过滤
python scripts/run_tests.py --jobs 1         # 串行（默认并发 4）
```

单测等价写法：`python -m md_cg.test_p44_md_whitebox`（cwd=仓库根）。退出码 0/1 可直接接提交前门禁。

---

## 📏 工程纪律与设计者视角（可选推荐）

> **这段话是什么**：灵枢自身按一套 **17 条工程纪律** 运行——方法论（理论先行 / 全面处理 / 根因纪律）、执行（验证先行 / 双副本同步 / 兜底路径）、执行调度（任务派发统一走蜂巢：执行留痕 / 统一调度面）、合规（内容政策双清单 / 敏感信息隔离）、记忆闭环（查记忆 → 执行 → 写记忆）。它原本是灵枢的「自我约束」，与你要不要用灵枢无关；但如果你希望自己的 Agent 也具备同样的工作方式，这套纪律与配套元技能**都可以直接复用**。

**两个可复用入口**：

| 入口 | 内容 | 位置 |
|---|---|---|
| **工程纪律（17 条）** | 每条 ≡ 一个认知图节点（生效条件 / 执行锚点 / 不适用条件 / 直答出口），含触发词路由 | 真源：[`docs/工作纪律_认知图条目_v1.1.json`](docs/工作纪律_认知图条目_v1.1.json) · 全文投影：[`AGENTS.md`](AGENTS.md) |
| **设计者视角（元技能）** | 在动手前回答「该不该做 / 为什么做 / 条件够不够」：条件空间声明 → 四态资格裁决（ACCEPT/REJECT/DEFER/BLINDSPOT）→ 失配归因；附自检 17/17 | [`skills/skills/designer-perspective/`](skills/skills/designer-perspective/)（`tests/selftest.py` 可自行验收） |

> **按需裁剪**：17 条中部分条款针对灵枢私有管线（如图像选源线），复用时建议只取方法论 / 执行 / 执行调度 / 合规 / 记忆闭环五组通用条款。多 harness 渲染与防漂移守卫见 [多 harness 接入](#多-harness-接入按端分目录)。

## 护栏宪章（接入即接受约束）

本插件接入即接受 **[灵枢护栏宪章 v2.0-published](docs/mdcg/guardrail-charter.md)** 约束——对外部智能体与人类使用者的行为边界作出公开、可执行、可审计的规定，并保护人类使用者。

## 许可证

MIT © 荣（FuRongJun-1999）· 灵枢 AEIS 工程实现

DeepSeek Harness 为 DeepSeek 官方开源项目（MIT），本插件与之无隶属关系。
