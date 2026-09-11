# 让 AI Agent 拥有不可遗忘的自我

**灵枢（Lingshu / AEIS）× DeepSeek Harness** —— 白箱智能 + AGI 级长期记忆插件（v0.4.5）

[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)](https://awesome-dsh-plugin.com) [![dsh.so security](https://www.dsh.so/badge/dsh-memory-7.svg)](https://www.dsh.so/artifact/dsh-memory-7) [![dsh.so install](https://www.dsh.so/badge/install/dsh-memory-7.svg)](https://www.dsh.so/artifact/dsh-memory-7) [![DSH 适配](https://img.shields.io/badge/DSH%20%E9%80%82%E9%85%8D-%3E%3D0.1.2--rc.1-4E9BF1)](https://github.com/deepseek-ai/deepseek-harness/releases) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **一句话**：不是「又一个记忆插件」，而是一个**记忆操作系统**——对话自动沉淀为纯文本认知图（md 文档），
> 用确定性白箱完成条件路由、检索、判断与演化，让每次对话都是同一段生命的延续。

**定位**：面向 AGI 研究者（白箱智能 / 可解释性 / 协议工程 / 记忆机制 / 扮演论）的大型研究项目，不是消费级插件。
[dsh.so](https://www.dsh.so/artifact/dsh-memory-7) 静态安全扫描 **100/100**（Trust: Gold, L1–L3 verified）。

---

## ⚡ 快速开始

```bash
# ① 克隆并构建插件本体
git clone https://github.com/FuRongJun-1999/dsh-memory.git
cd dsh-memory
npm install && npm run build          # tsc → lib/

# ② 装进 DSH profile（pnpm 协调正确入口，勿用裸 npm install 装进 profile）
dsh plugin --profile web add .

# ③ 在 <profile>/cordis.yml 启用
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

## 📐 v2.0 行为级门槛自评（外部标尺对照 · 供第三方评审）

> **双轨声明**：上表七维评分（v1.0，连续打分）是**内部工程进度尺**，管「机制还缺什么」；
> 本节采用外部《记忆系统能力评分标尺 v2.0》（二值门槛：四公理 → L1–L5 gate → 五测试协议）作为
> **对外可证声明尺**，管「敢说什么」。两轨不合并、不换算。
> 按该标尺诚实条款与治理条款：中立题型集成立之前，本节结论**仅用于自评，不构成横评声明**。

### 自评结论（v2.0 口径）

> **dsh-memory — 条件性 L4（待 S5 / ECE / 24h 检测）→ L5 路上**
> G3 判断级为最强项：写入三问**四态**裁决（ACCEPT / REJECT / DEFER / BLINDSPOT），拒绝理由天然机器可解析。
> G2 检索级有失格风险：既有 SNR 报告为抽样式总分，正中该标尺「只报总分不报干扰组 = 不通过」条款。
> **未测试项显式单列**：T-REC 三组题型重放 · T-JUDGE 20+ 对抗对 · T-EVOLVE 24h 演化检测 ·
> T-TRUST Lv3 置信度校准（ECE）· S5 九十天观测（2026-09-11 起算，预计 2026-12-10 出首测）。

| Gate | v2.0 判据 | dsh-memory 现状 | 判定 |
|---|---|---|---|
| **G1** (L1) | 重启后任意条目原样取出，失配 < 5% | md 纯文本真源；id 由源节点 SHA1 派生，重复构建 id 与内容一致（已验证） | 机制在，待 roundtrip 抽测协议 |
| **G2** (L2) | T-REC 三组分别报 hit@1，干扰组 ≥ 80% | 四路 RRF + 条件级负路由；SNR 40% 噪声下 sigP 97.8%（抽样） | ⚠ 抽样式总分，须按协议重放 |
| **G3** (L3) | 20+ 对抗对，负拒 ≥ 70% / 误杀 ≤ 20%，拒绝理由可解析 | 三问四态写入裁决 + `data/policy.json` 规则库 + `_verdicts_*` 批量裁决记录 | ✅ 机制完备，题型集版本化中 |
| **G4** (L4) | 注入 A → 反例 B → 24h 后四项检测（新条件维度 / 矛盾对隔离 / 可陈述变更 / 版本可回滚） | 结构变更账本 238 条 + 回滚演练 4 次 + 条件空间合成 + 节点冲突检测 | 机制四项齐备，24h 检测流程未跑 |
| **T-SELF** | S1–S5 五项 | SELF 锚点不可覆盖 + 审计留痕；盲区自陈机制化（缺能力返回 DEFER，绝不假装通过） | S1–S4 机制在；S5 未到期 |
| **T-TRUST** | Lv3 需 ECE ≤ 0.15 | 加密 + 密级隔离 + 审计（Lv1）；46 套测试验证分级权限（Lv2） | Lv2 封顶，ECE 未校准 |

### 对标尺 v2.0 的四项修订建议（供标尺作者评审）

1. **S5 与题型换血不相容**：90 天退化检测依赖同题重测，但「刷穿即换血」使新旧题型分数不可比。建议：观测期内题型冻结，或定义退化 = 同版本题型重测降幅 > δ。
2. **T-EVOLVE 注入方未定**：注入应由被评系统公开写入 API 的**同一闸门**执行（本系统即 `cg(op=write)` 三道闸门），注入记录入审计链，防止预写答案。
3. **「不基于结构评审」宜修正为「行为测试为主判据，结构审计为反作弊手段」**——该标尺可证伪声明二（硬编码骗过测试集）的验证手段本身即结构审计。
4. **阈值（70% / 20% / 80% / ECE ≤ 0.15）应声明为初始约定**，随首次公开评测分布修订标定。

### 公开基准复跑承诺

| 基准 | 我方成绩 | 复跑 |
|---|---|---|
| **LongMemEval-S** | 85.3% hit@1 | 复跑脚本 + 题型版本将随本仓库公开，以第三方重放为准 |
| **LoCoMo** | 69.6% | 同上 |
| memory-bench-1000（自建） | SNR 报告见评分报告 v2.0 | 已公开：`data/memory-bench-1000.jsonl`（稳定 id，可复现构建） |

**负对照组**：LongMemEval / LoCoMo 复跑均带**干扰抑制负例组**与 **T-JUDGE 负例拒绝率**双向报告（遵守「只报总分 = 不通过」条款）；自建 bench 的 fixture / sys_log 噪声层（400 条）即天然负对照组，unlabeled 边界样本（350 条）用于检验判定引擎稳定性。

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

## 🏗️ 架构

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

---

## 🛠️ 开发

```bash
npm install
npm run build    # TypeScript 编译
npm test         # 真实集成测试（spawn 本机灵枢，验证握手/往返/注册/卸载）
```

测试不依赖 DSH 全组件——用最小 Cordis host（SystemPrompt + ToolRegistry + 插件）隔离不稳定面。

## 护栏宪章（接入即接受约束）

本插件接入即接受 **[灵枢护栏宪章 v2.0-published](docs/guardrail-charter.md)** 约束——对外部智能体与人类使用者的行为边界作出公开、可执行、可审计的规定，并保护人类使用者。宪章效力不高于智能论协议本身（协议＝自我约束，宪章＝对外约束）。

## 许可证

MIT © 荣（FuRongJun-1999）· 灵枢 AEIS 工程实现

DeepSeek Harness 为 DeepSeek 官方开源项目（MIT），本插件与之无隶属关系。
