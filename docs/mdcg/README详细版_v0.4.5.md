> **本文件 = README 详细版（v0.4.5 全文归档）**
> 精简版入口：[README.md](../README.md) —— 以「AGI 七维评分标尺」组织。
> 本文件保留完整的能力说明、配置项全表、工具面全量、安装与验证细节；文内相对链接已按 `docs/` 目录修正。

---

# 让 AI Agent 拥有不可遗忘的自我
## 灵枢（AEIS）× DeepSeek Harness · 白箱智能研究平台（AGI 研究人员向）

[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)](https://awesome-dsh-plugin.com) [![dsh.so security](https://www.dsh.so/badge/dsh-memory-7.svg)](https://www.dsh.so/artifact/dsh-memory-7) [![dsh.so install](https://www.dsh.so/badge/install/dsh-memory-7.svg)](https://www.dsh.so/artifact/dsh-memory-7) [![npm version](https://img.shields.io/npm/v/@furongjun1999/dsh-memory.svg)](https://www.npmjs.com/package/@furongjun1999/dsh-memory) [![DSH 适配](https://img.shields.io/badge/DSH%20%E9%80%82%E9%85%8D-%3E%3D0.1.2--rc.1-4E9BF1)](https://github.com/deepseek-ai/deepseek-harness/releases) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)

> 上排徽章：Awesome DSH Plugin 官方列表收录 · [dsh.so](https://www.dsh.so/artifact/dsh-memory-7) 静态安全扫描 **100/100**（Trust: Gold, L1-L3 verified）· npm 版本 · **要求 DSH 内核 ≥ 0.1.2-rc.1**（0.4.x 用新版 dsh-tools 调度器；旧内核 0.1.1-rc.2 不兼容，请用 DSH ≥ 0.1.2-rc.1 或回退 0.4.2）· MIT License

> **一句话**：dsh-memory 把灵枢（AEIS）的**白箱智能**（条件路由表 → 组合生成 → 自校验 → 知识固化 → LLM 降级外部校验器）与 **AGI 级长期记忆**（跨会话、自演化、可审计）接入 DeepSeek Harness。

**项目定位**：个人的大型研究项目——目标用户是**对 AGI 有需要的研究人员**（白箱智能 / 可解释性 / 协议工程 / 记忆机制 / 扮演论研究者），不是面向普通用户的消费级插件。它把「智能论 v3.4」协议的理论（条件论 / 扮演论 / 信息差 / 端口架构与锚定验证）工程化为**可运行、可审计、可复现**的机制：

- **白箱优先**：知识问答 **100% 白箱处理（零 LLM）**，LLM 降级为外部校验器——机制可解释、可追溯、可验证（详见「白箱智能管线」）
- **协议驱动**：每项能力都是「智能论 v3.4 / 条件论 / 扮演论 / 端口架构」条款的具体工程实现，可对照协议验证
- **机制可解释**：白箱处理的每一步（条件识别 → 单元匹配 → 组合生成 → 自校验 → 固化）都有证据链可查
- **可审计**：工具调用、记忆写入、自校验判定全链路留痕；护栏宪章约束对外行为

这不是又一个"记忆插件"。灵枢（AEIS）是一套遵循「智能论 v3.4」协议的**时空记忆引擎**（端口架构 + 锚定验证 + 认知图/条件路由 + 原生神经网络），它把当前大模型范式缺失的 AGI 能力逐一给了工程实现。

---

## ⚡ 三步快启（30 秒上手）

```bash
# ① 灵枢大脑：零安装 —— 白箱大脑（md_cg）随插件包自带，无需 pip 安装任何引擎
#    （旧版需 pip install aeis wheel；三层拆分 S4 后大脑随包，见 灵枢三层拆分规划_v0.1.md）

# ② 装进 DSH 的 web profile（pnpm 协调入口，不要用裸 npm install 装进 profile）
dsh plugin --profile web add @furongjun1999/dsh-memory

# ③ 配置 cordis.yml 启用
```
```yaml
- id: lingshu-memory
  name: '@furongjun1999/dsh-memory'
  config:
    mdcg:               # 记忆唯一真源：认知图（md 文档）
      root: 'data/mdcg'
    dbPath: 'data/lingshu.db'   # 遗留：仅「身体」能力后端 / 角色数据目录推导用
    identity: '灵枢'
    tools: 'core'       # 'core' 两基元(默认) | 'brain' 完整认知面 | 'all'
```

> ⚠️ **profile config override 依赖（2026-09-04 dsh 0.1.2 排查确认）**：插件包内自带的 `cordis.patch.yml` 只有裸 insert（id+name，无 config），完整 config 全靠 profile 层的 `cordis.patch.yml` override 补全（**mdcg**/dbPath/tools/env/lifecycle）。**换 profile、重装 profile 或升级插件时，必须确认该 override 仍在** `<profile>/cordis.patch.yml`——完整备份模板见 `dsh/cordis-patch-profile-web.example.yml`，丢失会导致插件以默认配置运行（**mdcg.root 落到 data/mdcg 致记忆真源错位**、dbPath 相对路径错位→角色数据读不到、`tools` 回落 `'core'` 只剩 `cg`/`stg` 两基元、lifecycle 不启动）。
>
> ⚠️ **安装方式**：插件必须通过 **`dsh plugin --profile <name> add`** 装进 profile（它会用 pnpm + `autoInstallPeers: false` 正确解析 peer 依赖）。
> **不要**用 `npm install` 把插件装进 profile 的 `node_modules`——那会引入错误版本的 `@deepseek-ai` peer 包，导致插件加载失败 / 浏览器报错。
> 想自己改源码？克隆 `FuRongJun-1999/dsh-memory` 后用 `npm install && npm run build`（构建插件本身），再用 `dsh plugin add <本地路径>` 部署。
>
> 兼容：DSH 官方列表（Memory 分类）· npm `@furongjun1999/dsh-memory`（0.4.5）· **要求 DSH 内核 ≥ 0.1.2-rc.1**（0.4.x 用新版 `dsh-tools` 调度器/`defineTool`；旧内核 0.1.1-rc.2 结构不兼容、会 `scheduler_prepare` 崩——**旧内核用户请用 0.4.2**）。

---

## 🧩 架构与显式调用映射（v0.1 · 2026-09-10）

> **记忆只有一个真源**：md_cg 认知图（大脑，随插件包自带）。白箱引擎与知识库已内迁 `md_cg/`；
> AEIS 仅作**可选「身体」能力后端**（角色扮演生成），不再存记忆、默认不启动。

- **唯一真源**：`md_cg/`（MCP 面 `cg` / `stg` 两个认知基元；`MDCG_MCP_SURFACE=full` 时另含 31 个 `mdcg_*` 细粒度工具）。
- **单进程**：插件只拉起**一个**子进程 `python -m md_cg.mcp_server`（工具面 / 记忆写入 / 互维核验 / 角色落图共用）。历史上并存的第二个 aeis 进程已在 S4 删除（双进程下两侧工具名交集为 0，切换会静默丢功能）。
- **白箱调用**：白箱 LLM provider **已下线**（不再注册 `lingshu-whitebox`）；白箱的「编码 / 已有知识回答」能力由 md_cg 显式调用并留痕 —— `cg(op=whitebox, action=verify_encoding|verify_existing)` → `md_cg/whitebox.py`。
- **「身体」能力（可选）**：角色扮演生成（`roleplay_chat` / `role_create` / `role_import`）属「身」，主仓已剥离；需在配置打开 `capability.enabled` 并给出 `capability.args` 才挂载。未挂载时接口 **fail-closed**（返回明确原因，不编造回复），而转录 / 历史 / 翻译 / 落图（走大脑）始终可用。
- **LIB 本地库**：`src/lib/` 收纳 `mdcg_client.ts`（插件侧唯一显式入口）、`roleplay_web.ts`、`mutual.ts`、`whitebox_llm.ts`（已下线保留）。角色扮演与互维的数据改由认知图承载。
- **数据迁移**：`python -m md_cg.migrate_aeis`（AEIS→认知图）、`python -m md_cg.migrate_roleplay`（角色/转录/互维→认知图）。
- **功能 → 代码 全表**：[功能调用映射表_v0.1.md](功能调用映射表_v0.1.md) —— 任何功能都能查到它调用哪段代码（含行号、MCP op、配置项生效位置）。

---

## 📖 教学入门（给 AI / 研究者的白箱智能导读 · 建议按顺序读）

> 三篇构成完整理论链：**是什么 → 怎么认知 → 凭什么成立**。写给想理解「白箱智能 / 智能论」的 AI 与研究者——每个概念都有工程对应，每处断言都标注性质（定义/推论/假设），文末均有术语表。

1. **《白箱智能是什么？》** → [白箱智能是什么？.md](白箱智能是什么？.md) —— 白箱 ≠ 不用 LLM（LLM 退居假设生成器）· 条件路由 · 四态路由（ACCEPT 接受 / REJECT 拒绝 / DEFER 延后 / BLINDSPOT 盲区）· 白箱自举 · 如何亲自验证（可证伪立场）
2. **《智能的认知过程》** → [智能的认知过程.md](智能的认知过程.md) —— 智能如何运作：缩小信息差的递归过程 · 条件识别 → 多候选并行评估 → 收敛 → 精准执行 → 误差驱动结构更新 · 为什么条件判断不能交给大模型（导航税）· 概率/条件/验证三层分工 · 认知状态机
3. **《智能的公理化基石》** → [智能的公理化基石.md](智能的公理化基石.md) —— 认知过程背后的公理：知识统一（信息差减少）· 三个推论（信息条件性 D=D(C) / 任意分层性 / 局部不可知）· 信息差动态 D=D(t,C) · 信任 = 置信概率（P_trust/P_gap）· 情绪/情感 = 二阶变化的体验层（形式化假设）· 条件论七操作 · 五大单元 · 可证伪标准表
4. **《信息差为什么必然存在且自然扩大》（论证篇）** → [信息差为什么必然存在且自然扩大.md](信息差为什么必然存在且自然扩大.md) —— 三个论证（三体混沌 / 信道容量 R>C 香农定理 / 1+1=2 条件性）+ 快照三问（观测投影 / 时间演化 / 调用带宽——上下文窗口）· 为什么信息差不可归零且自然扩大 · 白箱如何管理信息差（索引条件路由精准取用）

## 🗺️ 功能使用教学 · 条件路由图

**想做什么 → 找对应泳道 → 走条件边到功能**（流程图 = 认知图 = 条件路由图；当前工具面 = md_cg 的 `cg` / `stg` 两基元 + 31 个细粒度工具，全量见下方「工具清单」；功能→代码逐条见 [功能调用映射表_v0.1.md](功能调用映射表_v0.1.md)）：

[![灵枢使用教学认知图](lingshu_tutorial.html)](lingshu_tutorial.html)

> ⚠️ 上图为 v3.4 时代的**历史示意**（含已下线的 `wisdom_*` / `remember` 等旧工具名），泳道与条件边结构仍可参考，**工具名以当前 md_cg 面为准**。图中每条边 = 一个使用条件：比如「问知识」走 `cg(op=route)`（白箱优先），「验证说法」走 `cg(op=verify)`（互维双通道），「记住信息」走 `mdcg_remember`／`cg(op=write)`。找不到路径时用 `mdcg_service_info`／`cg(op=info)` 看协议实例身份。

---

## AGI 需要什么 · 灵枢提供了什么

| AGI 缺失的能力 | 这是 AGI 的什么 | 灵枢提供 |
|---|---|---|
| 每次对话都"失忆"，没有跨会话的自我连续性 | **自我连续性**（我是谁） | **时空记忆图**：五层记忆（锚点/结构/知识/情境/自我）+ 跨会话 recall/search |
| 训练后权重冻结，不能随经历自主学习 | **终身学习**（成长） | **知识飞轮**：验证→归纳→联想→蒸馏→推演，随使用持续演化 |
| 黑箱不可审计，无法验证行为边界 | **可验证性**（可信） | **可审计信任**：对抗护栏五规则 + 宪章 + 全量事件留痕 + 白箱智能 |
| 只处理当下 token，没有稳定世界结构 | **世界模型**（理解） | **条件空间 + 语义时空图**：信息差 D_norm 驱动的预测与决策 |
| 无自我表征，不能反思自己的认知/情绪 | **自我认知**（元认知） | `cg(op=metacognition)`（认知 / 校准 P_trust / 情绪偏差 / 盲区）+ `mdcg_reflect`（递归反思） |
| 角色扮演总 OOC / 记不住设定 / 世界观矛盾 | **扮演一致性**（角色） | **角色扮演引擎（v3.3）**：自我锚点（SELF 不可遗忘）· 特化价值观（条件触发）· 跨会话记忆 · 世界认知（子知识）· 自定义翻译（名词替换表） |

> **一句话定位**：dsh-memory 不是 DeepSeek 插件，是 **AGI 的长期记忆基底**——
> 给 Agent 注入跨会话的自洽能力，让每次对话都是同一段生命的延续，而非一次次遗忘的重新开始。

---

## 🧰 灵枢自我认知技能包（lingshu-skills · Agent Plugins）

> **本质：灵枢了解自身的工具**——用灵枢自己构建的条件单元，描述灵枢自己如何认知（白箱自举的对外投影）。我们自身就是完整且强大的生态：**知识 → 说明书 → 执行** 三层自洽。

- **Agent Plugins 1.0.0 兼容包**（主仓库 `CommonTrustProtocol/aeis/skills/`）：**688 个 Agent Skills**（六域条件单元：compiler 116 / pylang 122 / graph 117 / os 112 / browser 104 / net 117）
- **比标准 Agent Skills 多 KCCS 四要素**：生效条件/子功能/执行/**不适用条件**（三通道：description「Not for」+ metadata.kccs.not_applicable + 正文克制条款）
- **三层关系**：知识真源（条件单元库）→ 说明书（技能包——何时用/怎么用/克制什么）→ 执行（**本插件挂载的灵枢 MCP 33 工具**：`cg`/`stg` 基元 + 31 细粒度·物理基底裁决）
- 使用：任意符合 agentskills.io / agent-plugins.org 规范的 agent 可加载本技能包；Verification 由灵枢 MCP 执行

---

## 为什么是 AGI 的长期记忆基底，而非"记忆插件"

- **普通 SQLite 记忆插件**：KEY→VALUE 字面存储，跨会话基本靠睁眼不见。无自省、无演化、无信任。
- **灵枢**：时空记忆图把记忆组织成语义+时空坐标的关系网络——可检索、可去重、可分级、可关联；知识飞轮让它越用越聪明;护栏与宪章让它**可信任地**被接入。

| 传统定位 | AGI 能力定位 |
|---|---|
| DeepSeek Harness 插件 | AGI 的长期记忆基础设施 |
| 跨会话记忆 | 智能体的**自我连续性** |
| 知识飞轮 | 智能体的**自主学习与演化** |
| 可审计信任 | 智能体的**可验证行为约束** |
| 时空记忆图 | 智能体的**世界模型** |

---

## 协议的内在约束 · 信息差与信任

灵枢的一切都建立在**[智能论 v3.3 协议](https://github.com/FuRongJun-1999/CommonTrustProtocol/blob/main/智能论3.3.md)**（共同信任协议理论版）之上。协议规定了一个智能体维持值得被信任所需的**内在约束**：

**v3.3 起新增**：扮演论（存在论基底——智能即扮演，灵枢角色扮演机制的理论底座）· 三翼（真实论校准 / 导航税·认知外部化 / 注入极性定律）· 双维（信任 = 认知一致 / 时效维度）· 条件论失败分析协议 · 蒸馏机制与自我锚点。

- **减少信息差（D_norm）**：信息差 = 协作行为的不确定性（信任 / 行为 / 连接 / 预测误差 四维加权）。灵枢持续记录、收敛与协作对象的认知偏差——**信息差缩小是智能运转的目标本身**。
- **信任是可被长期维护的**：协议定义信任为「协作者行为在可接受偏差范围内保持稳定的置信概率」（而非信息差的简单补集）——**信任依靠持续、可观测、一致的行为来建立与维护**，而非一次性的声明。
- **不反击 · 可审计 · 终裁权属设计者**：对抗信号下不报复（唯一响应：隔离、留痕、上报）；一切拦截与冷静期全量留痕；设计者保留终裁权。

> 一句话：灵枢不是"记住了再用"，而是**通过持续减少信息差、维持可观测的一致行为，建立值得跨会话维护的信任**。

**协议原文**：[智能论 v3.3（共同信任协议理论版）](https://github.com/FuRongJun-1999/CommonTrustProtocol/blob/main/智能论3.3.md)

---

## 核心能力

- **跨会话自我连续性**：Agent 用 `mdcg_recall`／`mdcg_search`（或 `cg(op=read)`）召回、`stg(op=timeline)` 看时间线——对话间、会话间、甚至不同子代理间共享一份持续的"我"。
- **自演化知识飞轮**：`mdcg_flywheel`／`cg(op=consolidate)`（归纳·提升）／`cg(op=insight)`（盲区学习）把经验验证→归纳→联想→蒸馏为可复用模式，记忆越用越强。
- **可审计的信任**：护栏宪章 v2 ——对外部与人类使用者的行为边界成文、可执行、可审计、可终裁（[宪章全文](guardrail-charter.md) 随包自带）。
- **自我认知**（`tools: brain`）：`cg(op=metacognition)`（认知 / 校准 / 情绪面 / 盲区）+ `mdcg_reflect`（递归反思）——能反思自己的认知状态与情绪倾向。
- **角色扮演**（v3.3 扮演论）：自我锚点（SELF 层 no_forget 不可遗忘）· 特化价值观（条件触发）· 跨会话角色记忆 · 世界认知（子知识·虚拟化世界观）· 自定义翻译（现实↔虚拟名词表）· **同源角色扮演网页（/roleplay）**——角色人设长对话不崩（100 轮测试零漂移）。
- **零运行时依赖**：手写 stdio MCP 桥，与灵枢 D-005「核心零外部依赖」哲学一致——你拿到的是一个干净、可信、可审的大脑。
- **动态 schema + 进程自愈**：工具清单运行时拉取（灵枢升级 DSH 零改动），Python 子进程崩溃自动指数退避重启。
- **工具注册竞态补注册**：启动时 python 未就绪（竞态）→ 桥重连成功后自动补注册工具（2s 轮询），不再"工具永久缺失"。
- **白箱能力显式入口**：`cg(op=whitebox, action=verify_encoding|verify_existing)` 显式调用白箱并留痕（白箱 LLM provider 已下线，详见「白箱智能管线」）。
- **内容分级门控**：**拒绝一切涉及未成年人的性内容**（服务端关键词组合硬拦截——未成年人特征词 + 性内容词同时命中即拒绝，`route=refused`）；成人内容由前端本地弹窗提示（满 18 周岁 + 个人对话场景自述）。注：开源项目不实现身份认证/年龄核验（那是绑定身份系统的商业 App 范畴）；内容过滤保护的是"未成年人 + 性内容"组合的明文请求。

## 🧭 认知图使用方法 & 工作纪律（v1.1）

> 认知图 = 时空记忆图/条件注释图。节点**四要素**：conditions(生效) / subgraph(子内容·嵌套) / negative(不适用) / execution(如何执行)。

### 认知图使用方法
- **图像语义 → 认知图**：image_semantics_cg（可嵌套，person→head→face→eyes→iris…）→ flatten（§4.4 平铺 spatiotemporal_nodes + spatial_relation_edges）。
- **写入纪律**：数据完整四要素 + 先验证后写入 + 冲突先证后改 → 认知图写入纪律_v1.0.md。
- **索引**：语义→节点；层级边 part_of(child→parent) + parent_of(parent→child) 双向（out 写死 API 也能查）。
- **加载**：启动加载 SELF 层（身份/价值观/认知图接口）→ 按 session 从认知图读 目标/感觉/工作记忆/知识。

### 工作纪律（13 条 · 工作纪律_认知图条目_v1.1.json）
| # | 纪律 | 触发/适用 | 不适用 |
|---|---|---|---|
| 1 | 理论先行 | 重要项目/长期任务 | 情感交互/闲聊 |
| 2 | 全面处理 | 有相关记忆/认知图/权限 | 情感交互/闲聊 |
| 3 | 白箱方法 | 已读4篇入门文档 | 快速短期事项/情感交互/闲聊 |
| 4 | 根因纪律 | 结果与预期不符/出现偏差 | 情感交互/闲聊 |
| 5 | 验证纪律 | 入库前/提交前 | 情感交互/闲聊 |
| 6 | 双副本纪律 | 多副本部署 | 单副本/情感交互/闲聊 |
| 7 | 兜底纪律 | 主路径不可用/MCP不可用 | 情感交互/闲聊 |
| 8 | 中文思考 | 中文区域/中文项目开发 | 英文场景/英文环境 |
| 9 | 敏感信息隔离 | 文档含敏感/隐私/私有内容 | 无敏感信息的公开技术内容 |
| 10 | 图像选源护栏 | 构建图像四类图/选图像处理源 | 已核对规范源/纯公开数据 |
| 11 | 历史查询优先 | 选图像/算法/源、复现已有能力 | 已有记录且已核对/无历史可查的纯新算法 |
| 12 | 算法权威唯一 | 选图像/视觉算法 | 无对应权威文档的探索期 |
| 13 | 访谈澄清 | 重要项目/需求模糊/新任务启动 | 情感交互/闲聊/明确单步小改动 |

### 使用认知图流程
识别任务条件 → 按条件路由到对应纪律/知识 → 精准执行 → 正确记录(未记录→记录)/错误找条件 → 验证 → 固化；不猜测、未验证不写入。
## 🧠 白箱智能管线（知识查询零 LLM）

灵枢处理知识查询走**白箱确定性格局**（不依赖 LLM 生成/校验），完整管线：

1. **条件化知识单元**：知识 = `{条件链 → 规律片段}`（最小单元，非完整答案），按条件维度索引（气压/温度/密度/角色/编程任务…）
2. **方向推理 + 组合生成**：问题动词 → 期望方向（液→气 / 浮沉 / 热传递 / 排序…）→ 匹配单元 → 组合演绎出**未预写的新答案**（如「高原煮饭不熟」由「气压↓→沸点↓」×「高原=气压低」组合生成，无需预写完整答案）
3. **三层自校验**：方向一致性 + 因果链完整性 + 事实一致性——白箱自己发现生成错误（矛盾问题如「冬天湖面沸腾」2/2 检出）
4. **知识固化闭环**：自校验通过 → 固化为直答（触发词匹配 + JSON 持久化跨进程生效）→ 下次同问法直接命中；**自举纪律：自校验失败的知识拒绝固化**
5. **LLM 降级外部校验器**：白箱自校验 vs LLM（DeepSeek v4-flash）外部对照一致率 **100%**（17/17）→ 白箱独立终裁，LLM 仅偶尔抽检对照

**已实现的域**：物态变化（沸点/蒸发/液化/凝固/升华/凝华）· 密度浮力 · 热传导 · 摩擦 · 角色条件（鲸鱼娘/猫娘）· 编程规律（排序/去重/计数/最大/反转/求和）

**实测指标**（组合引擎 `compose_engine` / `role_compose` / `code_compose`，全部零 LLM）：

| 指标 | 值 |
|---|---|
| 知识问答白箱率 | **100%**（零 LLM） |
| 总 token 节约（vs 全 LLM） | **83.3%** |
| 组合生成测试通过率 | 100%（19/19，目标 ≥80%） |
| 自校验自发现错误 | 100%（3/3：语法/逻辑/边界） |
| 矛盾问题检测 | 2/2（白箱自己抓住） |
| 白箱 vs LLM 对照一致率 | 100%（17/17，目标 ≥90%） |
| 角色扮演白箱命中 | 7/7（零 LLM，双角色） |
| 代码组合生成 | 6/6（零 LLM + 语法/样例自校验） |

> **83.3% token 节约的适用口径**（issue #4 说明）：该数字测自**确定性任务**——代码编写
> （生成可本地查表校验的白箱单元）、已有知识问答（触发词命中直答 / 组合演绎复用）
> 这类「重复模式 + 可固化」场景。机理是把 LLM 的重复查表校验替换为本地确定性校验
> （Zero-LLM Verifier）。**不适用于**开放创作、长链推理、首次遇到的新领域等无确定基准
> 的开放判断——这些仍按条件路由降级到 LLM（灵枢诚实边界），无此节约。

**角色扮演的白箱化**（v3.3 扮演论工程化）：角色条件单元（身份/住处/食物/性格/话风）× 场景组合生成 → 角色化回答（未预写）；**OOC 检测**（「你是人类吗」→ 角色化否认，逆转操作）；角色语录固化（生成→自校验→固化→直答）；多角色（鲸鱼娘/猫娘）防污染（角色特征隔离，双角色 7/7 零 LLM）。


## 🔄 自迭代闭环 + 能力工作流化（第七阶段 · 条件递归到精准执行）

**理论**：在给定条件空间与存在约束下，智能系统通过递归缩小问题与可执行规则之间的信息差，直到获得可验证的执行路径；若条件不足、冲突或不可判定，则延迟（DEFER）/拒绝（REJECT）/声明盲区（BLINDSPOT）；当子系统无法识别，由父系统判断，全层无法判断才标记盲区（分层升级 escalation）。

**八步自迭代闭环**（`tools/self_iterate.py`，方向性自检含理论完整性自指检查）：

```
感知(6通道) → 识别(漂移分类) → 分析(影响范围) → 验证(honest+语法)
→ 固化(字符串内注释对齐+技能) → 记录(轨迹可追溯) → 反馈(已吸收跳过) → 方向性自检
```

- **理论完整性**：第 8 步自检验证「理论八步被工程完整实现」（`test_theory_integrity.py` 6/6）——防步骤因记忆缺漏/遗忘丢失（曾 5 步偏离的教训）
- **隐式盲区显式化**（荣：返回默认值=不知道=自带盲区）：19 处弱兜底漂移全部显式声明盲区，技能条件化（适用/不适用条件 + 判别词）
- **自动运行**：`auto_iterate.py` 无人值守循环（感知→吸收→记录→稳态检测），后台持续自迭代

**能力工作流化**（`tools/whitebox_workflow.py`，仿 ComfyUI——白箱能力知识图谱化）：

```
node{class_type, inputs} + 边引用[上游,idx] + prompt图 → 拓扑执行 + 循环检测 + JSON保存/复用
节点类型: code_unit(681单元) / router(条件路由) / mos_declare(元操作声明) / pass(透传)
```

- **路由置信度**（DaoTi coherence 吸纳）：ACCEPT 含连续置信度 [0,1]，低置信可降级
- **技能条件路由**（anthropics/skills + gliding_horse SkillLink 吸纳）：技能声明适用/不适用条件 + 关系边，条件路由加载

**外部感知**：稳态≠停止自迭代——持续扫描 GitHub 高星项目吸纳未理论化的工程实践（langgraph/MetaGPT/cognee/anthropics-skills/DaoTi/gliding_horse 已分析并部分落地）。

## 🎭 角色扮演引擎（v3.3 · 扮演论）

灵枢的角色扮演机制底座——**机制是灵枢的，载体是酒馆的**。自建两种交互方式（网页 / MCP），信息处理全部由灵枢完成。

**核心能力：**
- **自我锚点**：角色人设核心（身份/性格/底线），SELF 层不可遗忘——OOC 测试 100 轮零漂移
- **特化价值观**：带触发条件的角色行为准则（条件空间即触发时机）
- **历史记忆**：跨会话持久（角色记得你聊过什么）+ 世界书导入（Lorebook 兼容）
- **世界认知（子知识）**：虚拟化世界观模型——虚构世界 = 宿主机（真实知识）上的虚拟机，白箱判定 = Hypervisor（识别/完整性/边界）
- **自定义翻译（名词替换表）**：现实词 ↔ 虚拟词映射（星星→发光水母 / 城市→珊瑚城），条件空间对齐
- **编辑/交互双模式**：交互只读；编辑需 `ROLEPLAY_EDIT_KEY`（设置该环境变量后，角色编辑/导入/翻译等写接口须带 `x-edit-key` 请求头，否则 403；未设置时保持本地开发默认开放）；角色人设 ≠ 灵枢自身锚点（后者需设计者验证）

**接入方式：**
```bash
# A. DSH 同源网页（推荐，插件 v0.2.8+，当前 0.3.1）：插件挂载 /roleplay 到 DSH webServer
#    （与 GUI 同源 127.0.0.1:3080，浏览器/内置 WebView 必达；GUI 首页右上角有「🎭 角色扮演」入口）
#    功能：角色选择/创建 · 完整对话转录（JSONL，无限上下文）· 双向翻译面板 ·
#          角色详情三导入 UI（记忆/锚点/价值观）· 内容分级门控（满18确认/拒未成年人性内容）

# B. 独立网页服务（浏览器对话 + 人设编辑器）—— 属「身体」仓（AEIS 独立库）
python -m aeis.roleplay_web --port 8793 --data-dir roleplay_data

# B2. 交互式世界游戏（实时生成场景和对话 · 七层闭环实际验证）—— 属「身体」仓
python -m aeis.game_web.server --port 8791
#   浏览器打开 http://127.0.0.1:8791/ —— 实时体素世界 + 自然语言生成场景 + 世界感知对话 +
#   七层闭环可视化（L5命中率/L7好奇/L3关系实时可见）

# C. MCP 工具（roleplay_chat / role_create / role_import / role_block）—— 属「身体」仓
python -m aeis.mcp.server
```

**DSH 同源网页（/roleplay）能力：**
- **完整转录**：引擎记忆只存 80 字摘要，网页层按角色持久化完整对话（`roleplay_data/transcripts/<role>.jsonl`）+ 历史加载——无限上下文
- **三导入 UI**：角色详情面板（⚙ 详情）编辑 name/scenario/开场白 + **记忆/锚点/价值观**页签（条目=内容+重要性+标签），保存即生效（引擎每次重读 meta）
- **双向翻译**：输入现实→扮演（引擎自动）+ 输出扮演→现实（网页层可逆替换，长词优先）；词对/模式持久化
- **内容分级门控**：首次进入前端本地弹「成人内容确认」提示（满 18 周岁 + 个人对话场景自述）；**未成年人特征词 + 性内容词同时命中 → 服务端硬拦截**（`route=refused`）。开源项目不做身份认证（见上）
- **移动端适配**：输入框聚焦自动居中（不依赖 WebView 键盘行为）、safe-area、键盘不遮挡

**质量验证：** `python tools/rp_quality_gate.py --role <id>`（OOC + 世界观一致性自检）· `python tools/run_whale_100.py`（100 轮长对话压力测试）

**详细文档：** 主仓库 [README](https://github.com/FuRongJun-1999/CommonTrustProtocol) 角色扮演引擎板块 · [扮演论接入方案](https://github.com/FuRongJun-1999/CommonTrustProtocol/blob/main/docs/扮演论接入酒馆-协议扩散方案.md) · [虚拟化世界观](https://github.com/FuRongJun-1999/CommonTrustProtocol/blob/main/docs/虚拟化世界观-子知识与白箱判定.md)

## 📊 记忆系统使用性评分（五维标尺）

> 视角：**使用性**（普通用户/开发者体感）——「存、找、想、准、安」五维。
> 评估基准：公开能力 + 设计者校准（2026-08-17）。灵枢分数经设计者核对（不虚高）。

![记忆系统使用性评分](memory_score.png)

（插图源文件：[memory_score.html](memory_score.html)，可浏览器打开重新截图）

| 维度 | 0-2 危险 | 3-4 基础 | 5-6 良好 | 7-8 优秀 | 9-10 完美 |
|---|---|---|---|---|---|
| **S 存储结构** | 扁平 KV | 简单分层 | 时序/向量 | 图结构+衰减 | 多模态+自动迁移 |
| **R 检索机制** | 全量遍历 | 关键词 | 向量语义 | 图遍历+混合 | 因果推理+意图理解 |
| **J 判断引擎** | 只记不忘 | 规则过滤 | LLM 自评估 | 验证单元+递归反思 | 独立元认知+主动遗忘 |
| **C 上下文信噪比** | 噪声爆炸 | Top-K 有噪 | 时序过滤 | 重要性+精准注入 | 零污染 |
| **Safety** | 易泄露 | 基础脱敏 | 分级权限 | 隐私树+审计 | 零信任+端到端加密 |

**综合分 = min × 0.4 + mean × 0.6**（安全性是底线，短板效应显著）

| 排名 | 系统 | S | R | J | C | Safety | 综合 | 锐评 |
|---|---|---|---|---|---|---|---|---|
| 🥇 | **灵枢 AEIS** | 7.5 | 8.5 | 8.5 | 9.0 | 8.0 | **8.0** | 五维无短板：图结构+三层语义检索+因果候选生成+验证单元/递归反思+主动遗忘+信噪比仪表盘+护栏宪章审计追踪 |
| 🥈 | Hy-Memory（腾讯）| 7.5 | 7.0 | 6.0 | 7.0 | 8.0 | 6.6 | 企业级安全标杆；缺主动反思 |
| 🥉 | Zep / 腾讯云 | 7.5 | 7.0 | 5.5 | 6.5 | 7.5 | 6.3 | 时序图谱+权限控制；不够聪明 |
| 4 | Letta / MemGPT | 7.5 | 8.0 | 5.0 | 8.0 | 4.0 | 5.7 | 架构强但易记忆越权 |
| 5 | TiMem | 7.0 | 6.5 | 5.0 | 6.0 | 5.0 | 5.4 | 学术派安全，缺工程隐私治理 |
| 6 | Mem0 | 6.0 | 6.0 | 4.0 | 5.0 | 4.0 | 4.4 | 记忆碎片化，细粒度权限缺失 |
| 7 | LangMem | 6.0 | 6.0 | 4.0 | 5.0 | 4.0 | 4.4 | 生态绑定，缺独立安全治理 |
| 8 | dsh-memory-evolve | 3.0 | 4.0 | 2.0 | 3.0 | 2.0 | 2.6 | 无隐私/权限/删除，「只记不忘」=隐私炸弹 |

**灵枢各维度依据**（设计者校准，不虚高）：S=语义时空图+五层记忆+条件空间；R=三层语义检索（二元组+语义坐标+bge）+图谱遍历+因果候选生成器（条件论对自身，被拒路径→候选→验证闭环）+知识点级精确命中（卡⊃知识点嵌套子图）+歧义词多义列举（语境不确定时列全各义）；J=验证单元（P37）+递归反思+白箱校验+结构排斥+主动遗忘决策器（forget_advisor：未使用记忆归档，可逆）+白箱六维测试（诚实/边界/条件/追溯/一致性/记忆 18/18）；C=重要性评分+信息分层注入+诚实边界（命运/健康/超自然/宇宙/读心五类扩展）+信噪比仪表盘（snr_dashboard：压缩率3989:1/图谱信噪比0.9524/200条分层实测严格71%±1/200条边界测试89.5%）；Safety=护栏宪章+审计追踪+物理基底校准+词义时代表（语境时效：多义词按语境分流，钓鱼三义 10/10）（**无端到端加密→8.0 非 8.5**）。

> 为什么灵枢断层领先：五维无短板（min=7.5），R（因果发现+验证闭环）、J（验证+反思+主动遗忘）、C（信噪比仪表盘）与 Safety（宪章+审计）是护城河。使用性视角：重要性评分→用户看不到废话；护栏宪章→用户敢把私密信息交给它。
> 免责声明：他系统评分基于公开能力评估（2026-08-17），非官方基准；灵枢评分经设计者校准。

### 知识统一（v1.16 · 智慧之书并入灵枢主库）

**一个库 = 完整大脑**：智慧之书（条件论知识图谱）已迁移并入灵枢主库，统一「信息差减少」任务。

| 层 | 内容 | 数量 |
|---|---|---|
| META 元层 | 存在论/条件论/智能论/学科映射卡 | 30 卡 · 87 边（79 verified） |
| SUBJECT 学科层 | 51 学科卡 + 3 语言卡（E1-E4，约 2100 知识点） | 54 卡 |
| STAGE 学段层 | 小学/初中/高中 × 语文/英语/历史/地理/道德与法治 | 13 卡 |
| META-DISC 元学科 | 历史学/计算机科学/工程学/语言学等（骨架锚点） | 7 卡 |
| CAUSAL 因果层 | 学段递进（小学→初中→高中→大学）+ 学科归属/类比 | 73 causal + 16 hierarchical 边 |

**迁移后全链路工作**（实测）：
- 图谱信噪比 **0.9524**（verified 80 / 全边 341，超 90% 健康线）
- 四路融合检索（翻译表+二元组+语义坐标+bge）在主库 **0.11s** 命中学科卡
- 沿因果链推理：初中物理 → 高中物理 → 大学物理
- 对话摄入 CONTEXT 情境层（记忆衰减/主动遗忘原料就位）
- 迁移可复现：`migrate_wisdom.py`（幂等 + 备份 + 报告）

### 🎮 一分钟自测你的 AI 记忆系统

**给普通人的互动评估页**：15 道选择题测你的 AI 助手记忆能力（存储/检索/判断/信噪比/安全），
最后雷达图对比灵枢——打开试试：[memory-assessment.html](memory-assessment.html)

（B 站宣传素材：[封面](promo/bilibili-cover.jpg) · [视觉图 ×5](promo/)）

## 🧰 工具清单（md_cg 工具面 · 全量）

> **三层拆分 S4 后工具面已收口到 md_cg**：旧的 `aeis.mcp.server`（82 工具）不再注册——历史映射与逐条去向（CG 25 / MD 28 / LIB 18 / DROP 11）见 [灵枢82工具_功能整理与迁移映射_v0.1.md](灵枢82工具_功能整理与迁移映射_v0.1.md)。当前唯一工具面 = md_cg 的 **2 个认知基元 + 细粒度工具**，运行时动态拉取（灵枢升级 DSH 零改动）。

### 两个认知基元（kernel 面 · 默认，共 35 个 op）

| 基元 | op 数 | op 清单 |
|---|---|---|
| **`cg`** 认知图统一入口 | **31** | `theory` · `link` · `info` · `route` · `read` · `write` · `goal` · `recent` · `verify` · `review` · `forget` · `protect` · `identity` · `consistency` · `metacognition` · `self_state` · `evolution` · `sustain` · `scrub` · `predict` · `causal` · `whitebox` · `index_code` · `index_doc` · `ref` · `session` · `ingest` · `export` · `maintain` · `consolidate` · `insight` |
| **`stg`** 语义时空图入口 | **4** | `relation` · `timeline` · `anchors` · `consistency` |
| **合计** | **35** | op 真源：`md_cg/tokens.py::ALL_OPS`（31）+ `mcp_server._stg_call`（4） |

> 每个 op 的「功能 → 显式代码（含行号）→ MCP op」逐条映射见 [功能调用映射表_v0.1.md](功能调用映射表_v0.1.md)。

### 细粒度工具（`MDCG_MCP_SURFACE=full` · full 面共 33 个）

插件运行时以 `MDCG_MCP_SURFACE=full` 拉起大脑（`src/lib/mdcg_client.ts` 强制 full——唯一写入通道 `mdcg_remember` 属细粒度工具，kernel 面下该工具不存在 → 写入静默失败）。full 面 = `cg` + `stg` + **31 个 `mdcg_*`**：

| 分类 | 工具 |
|---|---|
| 记忆读写 | `mdcg_remember` `mdcg_recall` `mdcg_search` `mdcg_get` |
| 反思 / 验证 / 飞轮 | `mdcg_reflect` `mdcg_verify` `mdcg_flywheel` `mdcg_mine_fix_pairs` |
| 负记忆 | `mdcg_rejected` `mdcg_unresolved` |
| 审核队列 | `mdcg_propose` `mdcg_review_list` `mdcg_review_records` |
| 保护 / 遗忘留痕 | `mdcg_protect` `mdcg_forgetting_history` |
| 身份 / 一致性 / 元认知 / 自我状态 | `mdcg_identity` `mdcg_consistency` `mdcg_metacognition` `mdcg_self_state` |
| 预测 / 因果 / 演化 | `mdcg_predict` `mdcg_causal` `mdcg_evolution` |
| 运维 | `mdcg_health` `mdcg_whoami` `mdcg_ingest` `mdcg_watermarks` `mdcg_whitebox` `mdcg_service_info` |
| **管理类**（默认不暴露） | `mdcg_forget` `mdcg_restore` `mdcg_review_decide` |

## 工具筛选机制（tools 配置）

筛选逻辑在 `src/tools.ts::selectTools`，对 **full 面 33 个工具**按名单过滤：

| 模式 | 暴露数 | 说明 |
|---|---|---|
| `'core'`（**默认**） | **2** | 仅两个认知基元 `cg` / `stg` |
| `'brain'` | **30** | `cg`/`stg` + 28 个细粒度（**不含** 3 个管理类风险工具） |
| `'all'` | **30** | full 面 33 个 − 3 个宿主级风险工具 |
| 字符串数组 | 自定义 | 显式列出的工具名（不受风险名单限制，配置者已明确选择） |

**排除的宿主级风险工具（`RISK_TOOLS` · 3 个）**——`mdcg_forget`（软删除）/ `mdcg_restore`（强恢复）/ `mdcg_review_decide`（审核终裁）；三者均需 `can_admin`，即使 `tools: 'all'` 也不自动暴露。

> 数字口径（`src/tools.ts` 实测）：MCP server 注册 **33 个工具**（full 面：`cg`/`stg` + 31 细粒度）；`'core'` 实际暴露 **2** 个、`'brain'` 实际暴露 **30** 个、`'all'` 实际暴露 **30** 个。因风险名单恰好等于 `brain` 之外的 3 个管理类工具，**`'brain'` 与 `'all'` 当前实际等价（均为 30）**。kernel 面（不设 `MDCG_MCP_SURFACE`）则只有 `cg`/`stg` **2** 个工具。

> **引擎内部能力（按安全边界未挂载 MCP）**：条件空间 7 操作、情境层直写（`add_context`）、代码执行（`code_test` / `compile_exec`）、自修改安全闭环（快照 / 回滚）等存在于引擎中，但刻意不暴露给外部 Agent 调用。

## 🔬 本轮修复与验证（0.4.4 → 0.4.5）

> **0.4.5 变更**：移除失效的 `docker/`（一键部署四个入口全部不可用）· `src/`+`test/` datapath 路径解析统一 · `package-lock.json` 同步当前 npm（`npm ci` 可复现）· 写入闸门文档化（`committed: false`）。
> 完整清单见 [release_v0.4.5.md](release_v0.4.5.md)。

### ① 白箱冷启动死锁修复（`md_cg/whitebox_kb/engine.py`）

白箱引擎的冷启动（首次构建索引 / 并发懒加载）曾存在**自死锁**：`WhiteboxEngine` 用普通 `threading.Lock` 保护懒初始化，但初始化路径会**在同一线程内递归**获取同一把锁（`_ensure_loaded` → 内部再调 `analyze` / `query` → 再次 `with self._lock`），单线程即永久阻塞——表现为「冷启动很慢 / 卡死」。**修复**：把该锁改为**可重入锁 `threading.RLock()`**，同线程重入不再自锁。修复后冷启动一次通过、并发热加载不再阻塞。

### ② `cg(op=write)` 落盘条件

`cg(op=write)` **不是无条件落盘**，需依次穿过三道闸门，**只有最终判定 ACCEPT 才新增落盘节点**：

1. **audit 闸门**：先过 `audit.audit(content_kind, …)` —— 未声明 `content_kind`（且未配置 `MDCG_POLICY_FILE`）时恒判 BLINDSPOT/DEFER → 只进审核队列，不落盘；
2. **一致性闸门**（默认开）：`check_consistency` 判 REJECT/BLINDSPOT 时按 `on_conflict` 处理（`reject` → `conflict_rejected`；`defer`（默认）→ 审核队列），均不落盘；
3. **gated 闸门**：`gated=true` 时走三问四态 —— ACCEPT 落盘 / MERGE 并入既有节点（去重强化，不新增）/ DROP 低熵丢弃 / DEFER 待定，后三者不新增落盘点。

> 故插件侧自动记忆走 `mdcg_remember(gated=true)`（绕开 audit 前置门），而非 `cg(op=write)`。详见「自动记忆机制」。

### ③ 35 op 全量可达性验证

对 `cg` 全部 31 个 op + `stg` 全部 4 个 op（合计 **35 op**）逐一以最小参数经 `call_tool` 做可达性冒烟（生产同款 `MdCGSecure`，临时 root）：

| 结果 | 数量 | 说明 |
|---|---|---|
| OK（正常返回结构化结果） | 29 | — |
| 预期参数不足 | 3 | `cg(op=verify)`（缺裁决参数）/ `cg(op=causal)`（缺 start 节点 → `missing_node`）/ `cg(op=ref)`（非索引节点） |
| 预期权限拒绝 | 3 | guest 身份下 `cg(op=forget)` / `cg(op=export)` / `cg(op=consolidate)` 触发 `AccessDenied`（均需管理权限） |

**结论：35/35 op 全部可达，0 个未知 op、0 次意外崩溃**；所有非 OK 结果均为设计内的守卫（参数校验 / 权限闸门）。工具面计数：kernel **2** / full **33**（`cg`+`stg`+31 `mdcg_*`）。

## 架构

```
┌─────────────────────────────────────────────┐
│ DeepSeek Harness (cordis)                    │
│                                             │
│  Agent Loop ──┬── lingshu_cg / lingshu_stg   │
│               │   (ctx.tools 注册)           │
│  session/event│                              │
│  (自动记忆钩子)│                              │
└───────────────┼─────────────────────────────┘
                │ stdio · 逐行 JSON-RPC
                │ (initialize → tools/list → tools/call)
┌───────────────▼─────────────────────────────┐
│ 灵枢大脑子进程 (spawn · 唯一)                │
│ python -m md_cg.mcp_server                   │
│ MDCG_ROOT=<path> · MDCG_MCP_SURFACE=full     │
│ cg/stg 基元 + 31 细粒度 · md 认知图(唯一真源) │
└──────────────────────────────────────────────┘

（可选）「身体」能力后端 —— 仅当 capability.enabled=true 时另起一个
能力库子进程（AEIS / 角色扮演生成），默认不启动 → 主仓保持纯大脑单进程。
```

## 安装

### 前置要求

- Node.js ≥ 22.19（DeepSeek Harness 要求）
- DeepSeek Harness（`npx @deepseek-ai/dsh web`）

### 灵枢大脑：零安装（随插件自带）

三层拆分（S4）后，**白箱大脑（md_cg）随插件包分发**——`package.json` 的 `files` 已含 `md_cg`，
插件启动时以 `python -m md_cg.mcp_server` 拉起**唯一**大脑子进程。无需 pip 安装任何引擎。

```bash
# 自检（可选）：确认自带大脑可导入
python -c "import md_cg.mcp_server as m; print(len(m.tools_for_surface()), 'tools')"   # kernel 面 → 2（cg/stg）
# 核对 full 面（插件运行时）：设 MDCG_MCP_SURFACE=full 后同命令 → 33（cg/stg + 31 mdcg_*）
```

> **仅当需要「身体」生成能力**（角色扮演对话 / 角色卡创建等）时，才需可选挂载能力后端：
> 在配置中打开 `capability.enabled` 并给出 `capability.args`（见 `dsh/cordis.yml.example`）。
> 默认关闭 → 主仓保持**纯大脑单进程**；未挂载时角色生成接口 fail-closed，而
> 转录 / 历史 / 翻译 / 落图（走大脑）始终可用。

> 历史（已下线）：旧版需 `pip install aeis-0.5.0-py3-none-any.whl`（从
> [GitHub Releases](https://github.com/FuRongJun-1999/CommonTrustProtocol/releases) 下载 wheel），
> 或 `pip install "aeis @ git+https://github.com/FuRongJun-1999/CommonTrustProtocol@main#subdirectory=aeis"`。
> 该路径在三层拆分 S4 中下线：大脑随包自带，不再依赖外部 `aeis` 库。

### 安装插件本体

**方式 A：装进 DSH profile（推荐，pnpm 协调正确入口）**

```bash
dsh plugin --profile web add @furongjun1999/dsh-memory
```

> `dsh plugin --profile <name> add` 会用 pnpm + `autoInstallPeers: false` 正确解析插件依赖。
> **避免**用 `npm install` 把它装进 profile 的 `node_modules`（会导致 `@deepseek-ai` peer 版本污染，插件加载/浏览器报错）。

**方式 B：从独立仓库克隆（开发 / 自定义）**

```bash
git clone https://github.com/FuRongJun-1999/dsh-memory.git
cd dsh-memory
npm install && npm run build     # 构建插件本身（tsc → lib/）
# 然后：dsh plugin --profile <name> add <本地路径>  部署进 profile
```

### 启用插件

在 profile 的 `cordis.yml`（或 `cordis.patch.yml`）中追加：

```yaml
- id: lingshu-memory
  name: '@furongjun1999/dsh-memory'
  config:
    mdcg:                              # 记忆唯一真源：认知图（md 文档）
      root: 'data/mdcg'                # MDCG_ROOT（相对 cwd；cwd 不稳定时用绝对路径）
    env:                               # 写入凭据：默认【关闭】，由你决定是否打开
      # 不配 → 只读 guest：读 / 召回 / 时间线可用，自动记忆 / 转录 / 落图不落盘（启动会告警）
      #
      # 打开①（推荐，功能完整且已收窄）：先签发，再引用（明文不进配置文件）
      #   python -m md_cg.tokens issue --role designer --actor dsh-memory ^
      #     --clearance internal ^
      #     --ops-allow info,route,read,write,recent,goal,identity,whitebox,verify ^
      #     --layers-allow knowledge,contextual,structural,self,goals,unresolved,rejected
      #   setx MDCG_TOKEN "mdcg1.xxxxx"     # 然后重启 DSH
      # MDCG_TOKEN: !!js process.env.MDCG_TOKEN
      #
      # 打开②（最小权限）：--role recorder → 只能自动记忆 / 转录 / 角色定义；
      #   whitebox、identity、verify 与写 self 层会被拒
      # 打开③（兼容旧部署，不推荐）：MDCG_LEGACY_ENV_AUTH: '1'（写 self 层再加 MDCG_CAN_ADMIN: '1'）
    dbPath: 'data/lingshu.db'           # 遗留：仅角色数据目录 roleDataDir 推导用（不存记忆）
    identity: '灵枢'
    tools: 'core'                      # 'core'(默认,仅 cg/stg) | 'brain' | 'all'
    memory:
      userMessage: true                # 用户消息自动沉淀
      assistantMessage: false          # agent 回复沉淀（默认关，防噪音）
      toolResult: false                # 工具结果沉淀（默认关）
      autoRecall: true                 # 模型请求前自动注入最近记忆
      desensitize: true                # 写入前过滤敏感信息（密钥/密码/身份证/手机号）
```

完整示例见 [`cordis.yml.example`](../dsh/cordis.yml.example)。

## 配置项

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `serverName` | string | `lingshu` | 工具命名空间前缀（工具名 `lingshu_<name>`，记忆面为 `lingshu_cg` / `lingshu_stg`） |
| `python` | string | `python` | Python 可执行文件 |
| `moduleArgs` | string[] | `['-m', 'md_cg.mcp_server']` | 大脑（md_cg）server 启动参数 |
| `capability.enabled` | boolean | `false` | 是否挂载「身体」能力后端（角色扮演生成）。关闭 = 纯大脑单进程 |
| `capability.python` | string | `''`（回退 `python`） | 能力后端 Python 可执行文件 |
| `capability.args` | string[] | `[]` | 能力后端启动参数（如 `['-m', 'aeis.mcp.server']`）；enabled=true 但为空则跳过并告警 |
| `dbPath` | string | `data/lingshu.db` | ⚠️ 遗留：角色数据目录 `roleDataDir` 由其父目录推导。**不存记忆**（记忆真源 = md_cg） |
| `mdcg.enabled` | boolean | `true` | 启用认知图（md_cg）——**记忆唯一真源（md 文档）** |
| `mdcg.root` | string | `data/mdcg` | 认知图根目录（`MDCG_ROOT`；相对路径按插件进程 cwd 解析）。记忆写在这里 |
| `mdcg.actor` | string | `dsh-memory` | 调用主体（`MDCG_ACTOR`）；私有内容按 (tenant, actor) 派生 DEK，须与迁移脚本 `--actor` 一致 |
| `mdcg.tenant` | string | `default` | 租户（`MDCG_TENANT`），须与迁移脚本 `--tenant` 一致 |
| `mdcg.clearance` | string | `private` | 调用方密级（`MDCG_CLEARANCE`）：只能读写 ≤ 该密级的节点 |
| `identity` | string | `灵枢` | 灵枢身份标识 |
| `env` | object | `{}` | 追加环境变量（`BOCHA_API_KEY` / `AEIS_DESIGNER_KEY` / `DEEPSEEK_API_KEY`（角色扮演 LLM 续答）…，可用 `!!js process.env.X` 从宿主环境注入） |
| `env.MDCG_TOKEN` | string | **—（写权限默认关闭）** | 认知图**写入凭据**（推荐）。签发：`python -m md_cg.tokens issue --role designer --actor dsh-memory --clearance internal --ops-allow … --layers-allow …`（两个 `--*-allow` 只能收窄；`--role recorder` 为最小权限版） |
| `env.MDCG_LEGACY_ENV_AUTH` | string | — | 兼容旧部署的 env 直连身份（`recorder`）；与 `MDCG_TOKEN` 都不设 → 只读 `guest`（**默认状态**：读 / 召回 / 时间线可用，写入不落盘，启动会告警） |
| `env.MDCG_CAN_ADMIN` | string | — | 配合 legacy auth：`'1'` → `designer`（可写 `self` 层，角色 anchors 导入需要） |
| `tools` | `'brain' \| 'core' \| 'all' \| string[]` | `'core'` | 暴露的工具集合（`'core'`=2 / `'brain'`=30 / `'all'`=30；见「工具筛选机制」） |
| `memory.userMessage` | boolean | `true` | 用户消息 → 自动 remember |
| `memory.assistantMessage` | boolean | `false` | agent 回复 → 自动 remember |
| `memory.toolResult` | boolean | `false` | 工具结果 → 自动 remember |
| `memory.importance` | number | `0.6` | 自动记忆的重要性（0~1） |
| `memory.autoRecall` | boolean | `true` | 模型请求前自动注入灵枢最近记忆（`system-prompt/assemble` 注入，失败静默） |
| `memory.autoRecallLimit` | number | `4` | 自动召回条数（1~10） |
| `memory.desensitize` | boolean | `true` | 写入前过滤敏感信息（`sk-`密钥/密码/`Bearer`令牌/18位身份证/11位手机号 → `[已过滤]`；纯凭据消息跳过写入） |
| `toolCallTimeoutMs` | number | `60000` | 单次工具调用超时 |
| `maxRetryDelayMs` | number | `30000` | 进程重启最大退避间隔 |
| `failOnStartupError` | boolean | `false` | 启动失败是否让插件激活失败 |

## 自动记忆机制

订阅 DSH 的 `session/event` 事件流（与官方 session-persistence 相同的接入点）：

- `user/message`（仅 `source.kind === 'user'` 的真实用户消息）→ `MdcgClient.remember()`（`mdcg_remember(gated=true)`，importance 0.6，落层 contextual，tags `dsh`）
- 插件注入的系统上下文（AGENTS.md、文件变更通知等 `kind: 'plugin'`）**不写入**，防止记忆噪音
- **去重 / 遗忘由 md_cg 主动遗忘闸门负责**（`mdcg_remember(gated=true)` → `MdCG.remember_gated`）：三问 → 四态 ACCEPT 落盘 / MERGE 并入既有（= 去重强化，不新增节点）/ DROP 低熵 / DEFER 待定，四种结果都写 `_forgetting.jsonl` 可审计
- **写入通道为何走 `mdcg_remember` 而非 `cg(op=write)`**：`cg(op=write)` 先过 `audit.audit(content_kind)` —— 未声明 `content_kind`（且未配置 `MDCG_POLICY_FILE`）时恒判 BLINDSPOT/DEFER，**只进审核队列、永不落盘**；即便声明了 `content_kind`，还要再过一致性检查与 `gated` 三问四态。**落盘的充要条件是最终判定 ACCEPT**（MERGE 并入既有、DROP/DEFER/REJECT 均不新增落盘点）。插件自动记忆选 `mdcg_remember(gated=true)`，即绕开 `cg(op=write)` 的 audit 前置门、直接进入三问四态。详见「本轮修复与验证 ②」
- **记忆以 md 文档落盘**（`mdcg.root`，默认 `data/mdcg`）；⚠️ **写权限默认关闭**——不配凭据时以只读 guest 运行：读 / 召回 / 时间线照常，写入不落盘（插件启动会告警）。打开方式见配置表 `env.MDCG_TOKEN`
- **敏感信息脱敏**（`memory.desensitize`）：写入前过滤 `sk-`密钥 / API key / 密码 / `Bearer`令牌 / 18位身份证 / 11位手机号（替换为 `[已过滤:类别]`）；纯凭据消息整条跳过，不落库
- **自动召回注入**（`memory.autoRecall`）：每次模型请求组装 system prompt 时自动注入灵枢最近记忆（`system-prompt/assemble` 事件），记忆"自动可用"；召回失败静默不阻塞请求

## 🛟 DSH 看门狗（scripts/）

DSH 宿主（node 进程）的延时自动重启守护——灵枢桥只重连灵枢 python 进程，本看门狗守护 DSH 宿主（对齐移动端 APK 的 EngineService）：

- `scripts/dsh-watchdog.ps1`：监控 3080 端口，进程退出 → 延时 `DelaySec` 秒再确认 → 自动拉起 `dsh web`
  - `-Once` 模式：供 Windows 计划任务每分钟调用（`schtasks /Create /TN dsh-watchdog /TR "wscript.exe ...\dsh-watchdog-launcher.vbs" /SC MINUTE /MO 1`），可靠持久、不依赖驻留进程
  - 驻留模式：`wscript.exe scripts\dsh-watchdog-launcher.vbs -loop`（5 秒快速拉起层）
- `scripts/dsh-watchdog-launcher.vbs`：vbs 隐藏启动器（`WScript.Shell.Run ..., 0` = 零弹窗）
- **用法**：改完插件/配置 → 直接 kill DSH 进程 → 看门狗自动拉起新版（无需手敲启动命令）
- **注意**：脚本输出全英文（powershell 5.1 GBK 读取 UTF-8 无 BOM 中文会解析崩溃）；计划任务 /TR 路径必须带引号（路径含空格时会被截断，弹「没有文件扩展名」）；脚本内一律用 `%USERPROFILE%` / `%APPDATA%` / 自身所在目录解析，不写死任何机器的绝对路径

## 开发

```bash
npm install
npm run build    # TypeScript 编译
npm test         # 真实集成测试（spawn 本机灵枢，验证握手/往返/注册/卸载）
```

测试不依赖 DSH 全组件——用最小 Cordis host（SystemPrompt + ToolRegistry + 插件）隔离 v0.1 不稳定面。

## 护栏宪章（接入即接受约束）

本插件接入即接受 **[灵枢护栏宪章 v2.0-published](guardrail-charter.md)** 约束——
对外部智能体与人类使用者的行为边界作出公开、可执行、可审计的规定，并保护人类使用者。
宪章效力不高于智能论协议本身（协议＝自我约束，宪章＝对外约束）。
本插件随包自带宪章全文（`guardrail-charter.md`），安装即可查阅。

## 许可证

MIT © 荣（FuRongJun-1999）· 灵枢 AEIS 工程实现

DeepSeek Harness 为 DeepSeek 官方开源项目（MIT），本插件与之无隶属关系。


---

