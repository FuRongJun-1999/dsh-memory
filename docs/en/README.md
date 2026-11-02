> [!NOTE]
> **This is a reference translation.** The English docs may lag behind or omit content; **the Chinese documentation is the single source of truth**. When they disagree, the Chinese version wins. Every page here has a Chinese source pair in [TRANSLATION_MANIFEST.json](TRANSLATION_MANIFEST.json), and its language header links back to that source. See [TRANSLATION.md](TRANSLATION.md) for the policy.

> **Languages:** [中文](../README.md) · English

# docs/ directory index

> Directories are split by engineering domain and correspond to the five-part platform overview in the repository README. A new document joins a domain first and is then registered in the matching list on this page; cross-domain items stay at the top level. Before changing the path of the discipline source of truth, check every reference surface (AGENTS.md / the rendering pipeline / md_cg comments).

## Directory structure

```
docs/
├── ops/       安装与运维（安装前置 / 写入凭据 / 升级重启 / FAQ）
├── dev/       开发与编码约定（测试约定 / 编码契约 / 开关矩阵）
├── mdcg/      灵枢大脑 md_cg 工程（架构/工具表/发布/教程/护栏）
├── swarm/     蜂群运行时 swarm/
├── hive/      蜂巢并发引擎 hive/
├── world_model/  世界模型神经网络底层架构（hex 系列台账）
├── theory/    智能论与白箱智能理论（跨工程）
├── eval/      评测与第三方验证报告
├── plans/     项目计划 / 交接文档 / 实验规格（跨工程）
├── discipline/  工作纪律渲染管线（模板 / harness 矩阵）
├── promo/     宣传物料
├── experiments/ 实验区（gitignored，可重跑再生产物）
└── 工作纪律_认知图条目_v1.1.json   ← 全局真源（横切面，不属单一工程）
```

## mdcg/ · LINGSHU Brain md_cg project

| Document | Content |
|---|---|
| [README detailed edition](../mdcg/README详细版_v0.4.10.md) | Full capability reference · complete configuration key table |
| [Release notes v0.3.0](../mdcg/release_v0.3.0.md) / [v0.4.5](../mdcg/release_v0.4.5.md) / [v0.4.11](../mdcg/release_v0.4.11.md) | Changes per release / upgrade guidance |
| [Tool table v0.3.0](../mdcg/tool_table_v0.3.0.md) | MCP tool list |
| [Feature call mapping table v0.1](../mdcg/功能调用映射表_v0.1.md) | Feature → source line numbers (pipeline generated; do not hand-write line numbers) |
| [LINGSHU MCP tool master table v3.4](../mdcg/灵枢MCP工具总表_v3.4.md) | Tool parameters and invocation rules |
| [LINGSHU 82-tool migration mapping v0.1](../mdcg/灵枢82工具_功能整理与迁移映射_v0.1.md) | **Historical**: the 82 tools belong to the tool surface of the **legacy aeis engine** (not this repository's md_cg); the mapping goal is to keep the two primitive surfaces `cg` and `stg` and to **register no more** of the 82 standalone tools |
| [LINGSHU self layer definition](../mdcg/灵枢_自我层定义.md) | Self layer behavior rules (line-level references from test_p16) |
| [Three-layer split plan v0.1](../mdcg/灵枢三层拆分规划_v0.1.md) | Architecture layering plan |
| [Memory operating system MdCGOS and MCP integration v0.1](../mdcg/记忆操作系统_MdCGOS与MCP接入_v0.1.md) | Core architecture design |
| [Recall core state and provenance metadata](mdcg/recall-metadata.md) | Field provenance, state semantics, and compatibility of the metadata returned by Recall |
| [Cognitive map MD directory plan v0.1](../mdcg/认知图_MD目录方案_v0.1.md) | Directory plan (the acceptance target of test_p27) |
| [Cognitive map indexing and engineering normalization plan v0.1](../mdcg/认知图_索引与工程规范化_计划_v0.1.md) | Index engineering |
| [Cognitive map condition space composition and effective condition measurement basis v0.1](../mdcg/认知图_条件空间合成与生效条件口径_v0.1.md) | Condition theory measurement basis |
| [Cognitive map G4-G8 gap adjudication sheet v0.1](../mdcg/认知图_G4-G8缺口裁定单_v0.1.md) | Record of gap adjudications |
| [Cognitive map as a memory operating system: evaluation and route v0.1](../mdcg/认知图作为记忆操作系统_评估与路线_v0.1.md) | Roadmap |
| [Unit self-anchor system prompt standard v0.3](../mdcg/单元自我锚点_系统提示词标准_v0.3.md) | Prompt anchor standard |
| [Gap sheet P0 closeout v0.1](../mdcg/缺口单_P0收口_v0.1.md) | P0 gap list |
| [Source-level architecture audit: GPT critique comparison v1.0](../mdcg/源码级架构审计_GPT批评对照_v1.0.md) | External audit evidence |
| [Guardrail Charter v2.0](mdcg/guardrail-charter.md) | Behavior boundaries for external agents and humans |
| [memory_score](../mdcg/memory_score.html) ([png](../mdcg/memory_score.png)) · [memory-assessment](../mdcg/memory-assessment.html) · [tutorial](../mdcg/lingshu_tutorial.html) | Scoring / evaluation / tutorial |
| [Release gate chain v0.1](../mdcg/发布门禁链_v0.1.md) | Three-layer gate (pre-commit auto re-hook / prepublishOnly check / CI backstop) and installation |
| [Sleep cycle: operational prerequisites and maintenance guide v1.0](../mdcg/睡眠周期_运维前提与维护指南_v1.0.md) | git prerequisites of the sleep cycle / repository location / maintenance actions (view history, view changes, revert-only rollback, conflict parking) / switches and automation boundaries |
| [D_meta engineering plan v0.2](../mdcg/D_meta_工程化方案_v0.2.md) | Engineering plan for separating D_task and D_meta |
| [Code review and conditional comments contract v0.1](../mdcg/代码评审与条件化注释_契约_v0.1.md) | Review and conditional comment contract |
| [Repository-wide code review and conditional comments plan v0.1](../mdcg/全库代码评审与条件化注释_计划_v0.1.md) | Repository-wide review execution plan |
| [LINGSHU memory verb protocol v1.0 (draft)](../mdcg/灵枢记忆动词协议_v1.0-draft.md) | Draft memory verb protocol |
| [Cycle two: white-box fill pipeline v0.1](../mdcg/环二_白箱填充流水线_v0.1.md) | White-box fill pipeline (recorded during testing) |
| [Cross-end verification and sync protocol v0.1](../mdcg/跨端验证与同步协议_v0.1.md) | Cross-end verification and sync protocol |
| [Memory system architecture optimization: delivery-layer bottleneck theory and design v0.1](../mdcg/记忆系统架构优化_交付层瓶颈理论与设计_v0.1.md) | A unified principle from two papers (DeliverMem / GroundingPI) → comparison against the current state of the five LINGSHU principles → four-layer rework direction → experiment specs that locate the bottleneck (two oracles); a theory document with no implementation patch |
| [External submission verification: state chain track v0.2 (TanPowasd)](../mdcg/外部提交核验_状态链轨v0.2_TanPowasd_20261011.md) | **Independent recomputation** record for the external answers to issue #110/#111: our official scorer plus the submitter's answer sheet → ten main-arm readings reproduced digit by digit, four calibration gates `passed=True`; includes five qualifications and one self-correction |
| [State chain track v0.2: LINGSHU arm A/B full measurement](../mdcg/状态链轨_灵枢臂A-B全量实测_20261012.md) | A 625-question comparison under the official measurement basis harness in which **for the same adapter, only `created_at` differs**: B (fact_time) shows +0.53 current value and -0.40 staleness, yet -0.27 history, -0.18 four-state, and -0.16 rationale, so **B is not a net improvement**; the work also exposed a coverage defect in the harness change chain (both groups at about 0) |

## swarm/ · Swarm runtime

| Document | Content |
|---|---|
| [Feature description v0.6](../swarm/蜂群多智能体_功能说明_v0.6.md) | Deterministic .pbc instances + Gossip/WAL/trust aggregation |
| [Usage report 2026-09-13](../swarm/蜂群多智能体_使用报告_20260913.md) | Measurement record |
| [Swarm interconnection v0.1](../swarm/蜂群互联_v0.1.md) | Multi-swarm interconnection protocol |
| [Swarm blind-spot marking v1.0](../swarm/蜂群盲区标记_v1.0.md) | Cooperative blind-spot marking |
| [Swarm same-error detection experiment protocol v0.1](../swarm/蜂群同错检测实验协议_v0.1.md) | Same-error detection experiment design |

## hive/ · Hive concurrency engine

| Document | Content |
|---|---|
| [Hive working memory: project plan](../hive/蜂巢工作记忆_项目计划.md) | hive working memory plan |
| [Hive design: theory alignment v0.1](../hive/蜂巢设计_理论对齐_v0.1.md) | Three-way alignment among intelligence theory 3.4, the hive source, and external research: 20 anchor mappings / 6 design adjudications / grouped adjudication of the candidate list / four-phase route / honest boundaries |
| [Hive iteration: macro and collective scheduling v0.1](../hive/蜂巢迭代_宏观与群体调度_v0.1.md) | Three-layer scheduling (micro process already closed loop / meso task DAG this cycle / macro collective planning) + comparison against the seven dsh-omc invariants + construction details of the I-1 dependency gate |
| [Main agent and subagent memory architecture design](../hive/主代理子代理记忆架构设计.md) | Memory division across agents (three-layer memory / session isolation / card backflow) |
| [Subagent configuration standard v0.5](../hive/子代理配置标准_v0.5.md) | Runtime role topology, six positions (section 8: deputy agent = Designer perspective) / unified execution defaults (section 0) / dispatch / deterministic execution (section 7) / reuse / artifact lifecycle (section 5.4) |
| [Token and role authority separation v0.1](../hive/令牌与角色权职分离_v0.1.md) | Permission model |
| [Token semantics correction: arbitration seat v0.1](../hive/令牌语义修正_仲裁位_v0.1.md) | Design draft: new orchestr role (projection of the 3.9 arbitration instance) + split gates for adjudication power and management power + migration order and red-capability criteria |
| [Multi-end harness communication contract v0.1](../hive/多端harness通信契约_v0.1.md) | Multi-end harness communication contract |
| [Hive dual-instance cross-verification: design final](../hive/蜂巢双实例互验_设计定稿.md) | Engineering form of dual-instance cross-verification that breaks the self-reference paradox (design final) |
| [Retrieval path and cognitive structure contract v0.1](../hive/检索路径与认知结构契约_v0.1.md) | Retrieval path and cognitive structure contract |
| [Retrieval convergence measurement (agreed basis) and S1b design v0.1](../hive/检索收敛实测与S1b设计_v0.1.md) | Retrieval convergence measurement on the agreed basis (real library, 12,149 nodes, read-only) and S1b design |
| [Real-library end-to-end measurement: S1b benefit and recall tradeoff v0.1](../hive/真实库端到端实测_S1b与召回权衡_v0.1.md) | Measurement of S1b benefit and recall tradeoff |
| [Real-library end-to-end measurement: S7 inverted candidate layer v0.1](../hive/真实库端到端实测_S7倒排候选层_v0.1.md) | Measurement of the S7 inverted candidate layer (in-candidate speedup with zero recall loss) |

## world_model/ · World model neural network foundation

| Document | Content |
|---|---|
| [World model: neural network foundation v1.0](../world_model/世界模型_神经网络底层架构_v1.0.md) | hex series engineering ledger (11 components / backprop semantics / Rust backend / cognitive map integration surface / verification baseline and red lines) |

## theory/ · Intelligence theory

| Document | Content |
|---|---|
| [What is white-box intelligence?](../theory/白箱智能是什么？.md) | Lesson one |
| [The cognitive process of intelligence](../theory/智能的认知过程.md) | Lesson two |
| [Axiomatic foundations of intelligence](../theory/智能的公理化基石.md) | Lesson three |
| [Why the information gap necessarily exists and naturally widens](../theory/信息差为什么必然存在且自然扩大.md) | Lesson four |
| [White-box intelligence series, part five: giving AI real memory](../theory/白箱智能系列·第五篇：让AI真正装上记忆.md) | Series continuation |
| [Intelligence theory 3.4](../theory/智能论3.4.md) | Main theory document |
| [Necessity of concurrency theory v0.2](../theory/并发必然性理论_v0.2.md) | Argument for the necessity of a concurrent architecture |
| [Single thread and attention focus v1.0](../theory/单线程与注意力集中_无争议理论文档_v1.0.md) | Undisputed theory document (includes a verification evidence table) |
| [Concept hierarchy alignment table v0.1](../theory/概念分层对齐表_v0.1.md) | Concept level alignment |
| [Cognitive agents and convergence structure: condition theory reconstruction v0.1](../theory/认知代理与收敛结构_条件论重构_v0.1.md) | Condition theory |
| [Theory, mechanism, code, experiment, gap matrix v0.1](../theory/理论_机制_代码_实验_缺口矩阵_v0.1.md) | Panorama matrix |
| [Unreliability theorems and fail-first framework v0.3](../theory/不可靠定理与失效优先框架_v0.3.md) | Fail-First Theorems: derivation chain of the T0 failure theorem (T0-T14/A1-A4) · a 14-row theory x mechanism x code matrix (engineering verification 2026-09-26) · a landing checklist that includes a v0.1 carry-over section |
| [Theory repository split and white-box knowledge base migration v0.1](../theory/理论仓拆分与白箱知识库内迁_v0.1.md) | Split plan |
| [Insufficient context and memory system isomorphism: principle analysis v0.1](../theory/上下文不足_LLM与记忆系统同构_原理分析_v0.1.md) | Triple isomorphism between LLM architecture and memory systems (function, problem, solution); derives from T4 + T5 that the four capabilities require explicit representation; P1-P4 falsifiable predictions |
| [Deriving memory system tuning from the LLM inference framework v0.1](../theory/LLM推理框架原理_向记忆系统移植_v0.1.md) | Eight transferable principles (stage separation / asymmetric resources / cache layering / compute-storage partitioning / bounded replay / two-level hit / marginal return / one-tick async latency) + strict transfer criteria + a clear decision not to transfer three layers; includes the honest boundary that we lack a 155-trillion-token-per-day calibration bench |

## eval/ · Evaluation and third-party verification

> **How to read this (check the measurement basis before the numbers)**: the evaluations in this directory use **several independent rulers**: (1) **seven-dimension tier judgment** (six vendors on one ruler, v3.1, the primary measurement basis, **gives a tier rather than a single score**); (2) **external independent eight-dimension weighting** (unified score v7, **only two vendors compared, and the gap is inside the noise**); (3) this repository's own question pool (historical measurement basis, kept for reproducibility). **The three are not comparable with each other**; cite the measurement basis together with the number.

| Document | Content |
|---|---|
| [AGI seven-dimension scoring report v3.1 (six vendors on one ruler, plus single-vendor U/I self-test)](../eval/AGI七维评分报告_六家记忆系统同尺实测_v3.1.md) | Seven dimensions x six vendors measured / live single-vendor U and I self-test (▲) / mapping rules / honest boundaries |
| [Relationship chain retrieval: weak-branch budget starvation fix](../eval/chain_best_first_20261013.md) | Before/after comparison of changing the native Markdown default (RRF), an independent exhaustive guard, targeted mutation, and resource boundaries |
| [DSH closeout audit counts: #606 delivery record](../eval/hook_audit_summary_20261021.md) | Cumulative summary on close/update, silent degradation, 73 regressions, and 5 targeted mutation groups |
| [AGI seven-dimension scoring report v1.0](../eval/AGI七维评分报告_md_cg_v1.0.md) / [v2.0](../eval/AGI七维评分报告_md_cg_v2.0.md) (historical) | Single-vendor self-assessment (structural evidence measurement basis) |
| [Third-party re-evaluation, unified score v7](../eval/第三方验证报告_灵枢_vs_dejavu_统一评分_v7.md) | Seven rounds of comparison (**external independent ruler, only two vendors, not comparable with the seven-dimension tier judgment**): LINGSHU 9.258 / deja-vu 9.119; **the reviewer states that the gap is within review noise**, and v7 contains an erratum that **fully withdraws** all four of its own recommendations |
| [Third-party verification, independent LoCoMo reproduction](../eval/第三方验证报告_LoCoMo_灵枢_.md) ([png](../eval/第三方验证报告_LoCoMo_灵枢_.png)) | Full end-to-end reproduction of the independent evaluation |
| [Six-vendor cross-comparison, 100 questions with Chinese and English lookups v1.0](../eval/横评_六家100题中英双查_v1.0.md) | Six vendors under one measurement basis |
| [Experiment plan: learning loop A/B and cross-comparison v1.0](../eval/实验方案_学习闭环AB与横评_v1.0.md) | Experiment design |

## ops/ · Installation and operations

| Document | Content |
|---|---|
| [ops/ index](ops/README.md) | Entry point for the two pages in this domain |
| [Installation and prerequisites](ops/install.md) | One-command setup / manual three steps / prerequisites / verified environments / post-install verification / troubleshooting clues |
| [Operations and troubleshooting](ops/operations-troubleshooting.md) | An upgrade requires restarting the long-running process (proxy verification) / write credentials and `committed` semantics / FAQ |

## dev/ · Development and coding conventions

| Document | Content |
|---|---|
| [dev/ index](dev/README.md) | Entry point for the two pages in this domain |
| [Coding and testing conventions](dev/coding-testing.md) | Build / Python tests must use -m / everything UTF-8 with entry-point guarantees / id contract v2 / Linux dual-stack verification |
| [Switch matrix](dev/switch-matrix.md) | Retrieval and normalization env switches, their defaults, and the history of their adjudication |

## plans/ · Project plans, handoffs, and specs

| Document | Content |
|---|---|
| [Naming governance: project plan](../plans/命名治理_项目计划.md) | Naming convention governance |
| [Knowledge graph project: handoff document 2026-09-14](../plans/知识图谱项目_交接文档_20260914.md) | Project handoff |
| [GridWorld minimal closed loop spec v0.1](../plans/GridWorld最小闭环规格_v0.1.md) | Experiment spec |
| [Multi-subject world model: alignment evaluation and landing design v0.1](../plans/多主体世界模型_对齐评估与落地设计_v0.1.md) | Five-layer alignment evaluation plus an A to B to C construction baseline (33 review findings adjudicated) |
| [Semantic spatiotemporal graph completion, world model endpoint design v0.1](../plans/语义时空图补全_世界模型功能端_设计_v0.1.md) | Current-state inventory (four ops plus the L0 ledger) plus L2 slot schema direction plus corpus pipeline and acceptance measurement basis (pending sign-off) |
| [LINGSHU collaboration architecture design v0.1](../plans/灵枢协作架构_设计_v0.1.md) | Swarm x project management x resource allocation x group chat x team memory: unified task lifecycle (one state machine with two authoritative surfaces) plus three-layer isomorphic nesting plus phased red-capability criteria (design draft, with 6 open adjudications) |
| [LINGSHU trust wiring design spec v0.1](../plans/灵枢信任接线_设计规格_v0.1.md) | Wires the existing trust value (p_trust in links.py) into resource allocation: three read-side gates, a write-side closed loop, and a tier table, plus ten red-capability criteria (the basis for starting P2, with 5 open adjudications) |
| [Relative time anchoring design v0.1](../plans/相对时间锚定_设计_v0.1.md) | `MDCG_TIME_ANCHOR` (off by default): relative times in prose become derived event intervals `temporal_anchor`; a question that names a date takes the `time_anchor` route plus an intersection precondition; LoCoMo readings, a contamination statement, and a lower bound |

## Bounty board · now its own repository

The bounty board (rules / state machine / ledger / honor roll / release template) has moved to the standalone repository [`FuRongJun-1999/dsh-bounty`](https://github.com/FuRongJun-1999/dsh-bounty); this repository no longer maintains its implementation. The design draft remains as a one-page pointer at [the bounty board design draft](../plans/悬赏板设计_v0.1.md).

## Top-level cross-cutting handoff documents (stay at the docs/ root, not in a subdomain)

Learning handoffs and master documents that span projects or endpoints stay at the docs/ root by convention (the L3 convention):

| Document | Content |
|---|---|
| [GBrain borrowables: LINGSHU landing handoff 20260919](../GBrain可借鉴点_灵枢落点交接_20260919.md) | GBrain borrowables and their LINGSHU landing points |
| [Pi learnable strengths: LINGSHU Brain improvement handoff 20260915](../Pi可学习优点_灵枢大脑改进交接_20260915.md) | Handoff for absorbing Pi strengths |
| [Compute-in-memory architecture study: external theory comparison and route handoff 20260916](../存算一体架构学习_外部理论对照与路线交接_20260916.md) | Compute-in-memory external theory comparison |
| [Compute-in-memory neural network architecture: master plan and handoff 20260916](../存算一体神经网络架构_总纲与交接_20260916.md) | Compute-in-memory master plan |
| [LINGSHU self-improvement work plan: absorbing the external research series v1 20260919](../灵枢自我改进工作计划_外部研究系列吸收_v1_20260919.md) | Self-improvement work plan |
| [White-box program: three-project learning architecture and Ghidra handoff 20260916](../白箱化纲领_三项目学习总架构与Ghidra交接_20260916.md) | White-box program master plan |
| [Memory review system: project initiation design and construction handoff 20260915](../记忆评审系统_立项设计与施工交接_20260915.md) | Memory review initiation handoff |
| [Scale: multi-subject world model evaluation spec v2.1 (frozen)](../秤_记忆系统评测规范_v2.1.md) | Memory system evaluation spec: dual track / six conditions / four-state judgment / calibration zero precondition gate (cross-cutting evaluation spec, added 2026-10-05) |
| [Release artifact retrospective note v0.1](../发布件回溯说明_v0.1.md) | Release artifact retrospective |

## Domain assignment rules (where a new document goes)

1. **Engineering documents** go to the matching engineering domain (`mdcg/`, `swarm/`, `hive/`, `world_model/`; when rust or compiler gets dedicated documents, add a directory at the same level).
2. **Cross-project theory** goes to `theory/`; **evaluation and third-party reports** go to `eval/`; **plans, handoffs, and specs** go to `plans/`.
3. **Cross-cutting global items** (such as the discipline source of truth) stay at the top level; before moving one, check every reference surface and rewrite all of them.
4. After a document joins a domain, register one line for it in the matching list on this page; existing conventions for `discipline/`, `experiments/`, and `promo/` are unchanged.

- [Memory-RSI five rounds of work and commit scope (round five in progress)](../eval/memory-rsi-work-summary-20261012.md)
