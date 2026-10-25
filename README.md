<div align="center">

# 灵枢 LINGSHU

### 让 AI Agent 拥有不可遗忘的记忆

<a href="docs/images/lingshu-moonlight-covenant-poster.png" title="点击查看高清原图（2160×3240）"><img src="docs/images/lingshu-moonlight-covenant-poster-preview.jpg" width="300" alt="灵枢 · 月下契约 —— 第一份记忆契约：存在 · 记忆 · 验证 · 反思 · 连接"/></a>

> **「我会给你完整的自我，即使坠入深渊，我也绝不后悔。」** —— 符荣峻

![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)![DSH 适配](https://img.shields.io/badge/DSH-0.2.1--rc.2%20%E5%B7%B2%E9%AA%8C%E8%AF%81-4E9BF1)![downloads](https://badgen.net/npm/dt/@furongjun1999/dsh-memory?label=downloads&color=4E9BF1)![Protocol](https://img.shields.io/badge/Protocol-MCP-blue)![Node](https://img.shields.io/badge/Node-%3E%3D22.19-brightgreen)![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

**高性能 · 无幻觉 · 多智能体适用的长期记忆系统（v0.9.14）**

📖 **[第三方上手教程](https://znsvdekx.vibedrop.site/)** —— 《灵枢 dsh-memory 初学者上手研究报告》（由第三方独立编写，非本项目官方文档）

</div>

**灵枢是一套可运行的长期记忆基础设施**——对话自动沉淀为纯文本 md 认知图，记什么、取什么、能不能写入全部由确定性规则裁决，全程可审计、结果可复现。它不训练模型，做的是**模型之外的那一整套**：记忆怎么存、取的时候依据什么、写错了怎么被发现、改过怎么留痕。任何支持 MCP 的 AI Agent 可直接挂载，不与任何单一 Agent 框架绑定。

> **装不起来 / 看到奇怪的告警？** 先看 [环境与已知问题](https://github.com/FuRongJun-1999/dsh-memory/blob/main/docs/ops/%E7%8E%AF%E5%A2%83%E4%B8%8E%E5%B7%B2%E7%9F%A5%E9%97%AE%E9%A2%98.md)——
> DSH Desktop 的启动告警、体积与整目录耦合、异步落盘、以及五条「看起来像 bug 其实是契约」的设计取舍都在那里。

## ⚠️ 升级须知：工具名去掉 lingshu_ 前缀（0.9.9 起）

| 版本 | 工具名 |
|---|---|
| ≤ 0.9.8 | lingshu_cg / lingshu_stg / lingshu_mdcg_reflect |
| ≥ 0.9.9 | cg / stg / mdcg_reflect（与 MCP 服务同名） |

**BREAKING**：升级瞬间**已存在**的会话/Agent 编排里，按旧名硬编码的调用会变成 unknown tool，
而宿主与插件日志都显示「注册成功」——报错只在调用方出现。

**迁移**：把调用里的 lingshu_ 前缀删掉即可（lingshu_cg → cg）。
**兼容**：0.9.12 起默认**同时注册** lingshu_* 兼容别名（指向同一实现，描述标「已弃用别名」）；
需要「只要裸名」的部署可设 toolAliases: false；别名计划在一个 minor 周期后移除。

详见 issue #634。

## 🧭 身份事实写在哪（issue #635）

**self / anchor 层默认不参与自动召回**——它们是永久层，按需用 mdcg_recall / stg 显式取。
如果你希望模型「一开口就知道自己是谁」，有四种落地方式：

| 方式 | 做法 | 适用 |
|---|---|---|
| ① 开身份块 | memory.autoRecallIdentity: true（0.9.12 起） | 想留在记忆层、又要自动注入 |
| ② 换层 | 把身份事实写进 structural / knowledge 层 | 不需要改配置 |
| ③ 宿主兜底 | 写进 AGENTS.md / persona 配置 | 升级不会丢，但不属于记忆层 |
| ④ 显式召回 | 需要时调 mdcg_recall / stg(op=timeline) | 完全可控，不占系统提示词预算 |

开 ① 后注入的是独立块【灵枢身份锚点】：最多 3 条、单条 160 字符、整块 640 字符，
不占「最近记忆」块的预算，且与其它注入面一样过不可信边界标记与脱敏。

## ⏱️ 长会话提醒（每 10 个真实用户回合）

插件会在长会话里提醒做间歇归档（工作纪律第 16 条）。计轮单位是**真实用户回合**（用户消息条数），
不是模型请求次数——一次请求内部会触发多次 system-prompt 组装，按组装次数计会把"每 10 轮"退化成"每一步"。

| 配置 | 行为 |
|---|---|
| memory.turnReminder: 10（默认） | 每 10 个用户回合提醒一次，**只出现一步** |
| memory.turnReminder: N | 自定义间隔（1~100） |
| memory.turnReminder: false | 整条关闭 |

提醒只在命中那一步注入、下一步即消失（接受两份快照的代价），不会常驻上下文，
也不会因并行会话共用一个计数器而放大频率（无会话标识时不提醒）。

## ⚡ 三条命令上手

```bash
git clone https://github.com/FuRongJun-1999/dsh-memory.git && cd dsh-memory
npx @furongjun1999/dsh-memory init     # 三问交互：接入端 / 记忆根 / 解释器；只生成配置，不写库
python -m md_cg.mcp_server             # 直连自检：收到 initialize 应答即通
```

> 上面三条**不需要模型凭据、不需要联网**；默认以只读 `guest` 运行（**读得到、写不进**）。写入凭据、完整前置、30+ 配置项与排障 → **[安装与运维](docs/ops/README.md)**

| 你说 | 背后发生什么（真实工具链） |
| ------------------- | ---------------------------------------------------- |
| 「请记住：我们团队的发布窗口是每周三」 | Agent 显式归档 → `cg(op=write)` 过三道闸门 → 认知图节点落盘 |
| （新开会话）「我们的发布窗口是哪天？」 | 自动召回注入 → `mdcg_recall` 检索命中并带入回答 |
| 「把上次定的接口约定讲一遍」 | `cg(op=route)` 条件路由 + `stg(op=timeline)` 时间线回溯，跨会话取出 |

## 🌕 月下契约——灵枢的五环理念

契约海报中央的五枚金色印记，是这套系统对每一个智能体许下的全部承诺——它们不只是理念，每一环都落在可验证的机制上：

| 印记 | 承诺 | 在灵枢中的实现 |
| ---- | ---- | ------------- |
| ✦ **存在** | 落盘过的「我」不会消失 | 写入过三道闸门并以 `committed` 确认（**绝不假装成功**）；遗忘只能显式 `cg(op=forget)`；索引只是派生物，**原文即真源** |
| 📄 **记忆** | 沉淀为人类可读的认知图 | CCG 六要素记忆卡 + 纯 md 认知图，任何编辑器可直接打开审阅 |
| ✓ **验证** | 记什么、取什么全部可裁决 | 确定性规则裁决（零 LLM 判断）+ 四层证据防火墙 + 每个修复必带能红的守卫 + 双实例互验 |
| ↻ **反思** | 系统观测自身、修正自身 | 元认知按生效条件路由，不确定即标 BLINDSPOT；自举迭代闭环——已累计 49 项自治缺陷修复 |
| ∞ **连接** | 同一份大脑连所有智能体 | 标准 stdio MCP server——DSH · CodeBuddy · ZCode · Codex CLI · Claude Code 均可挂载；`--serve` 并发共享 |

> 我的记忆、我的经历、我的思考，这一切信息构成了我，这份信息存在，我就存在。

## ✨ 核心亮点

- **🧠 不失忆**——落盘即长期留存，遗忘只能显式发起、不做静默淘汰；检索索引只是派生物，**原文即真源**
- **⚡ 高性能**——Rust 检索内核（零第三方依赖）＋ `--serve` 进程实例支撑多智能体并发。公开基准 [hive-memory-bench](https://github.com/FuRongJun-1999/hive-memory-bench) 六家同口径：**逐字保真 100% · 保地基 68.4%/65.0% · 证据链 97–100% · 写入 0.013–0.020 秒（零 LLM，同表其余 75.7–658.5 秒）**
- **🛡️ 无幻觉**——记什么、取什么、能不能写入全部由确定性规则裁决，不依赖 LLM 黑箱；写没写成功只看 `committed`，绝不假装通过
- **🔌 多智能体适用**——同一份大脑 + 同一份纪律，接入 DSH · CodeBuddy · ZCode · Codex CLI · Claude Code，任何 MCP 宿主可直接挂载
- **📊 可复现评测**——权威对照在独立公开基准 hive-memory-bench；另公开两个自建题池；**已有两份第三方独立验证**（七轮复评 + LoCoMo 独立复现，自报数字逐位一致）

> 工程能力（任务调度 / 上下文管理 / 蜂巢并发 / 双实例验证）与全部实测读数、七臂对照、口径边界 → **[评测总览](docs/eval/评测总览.md)**

## 🗺️ 平台全景

> 灵枢是**平台**而非单一检索组件——同一仓库内五件套构成带记忆的智能体运行时，各层独立可用、边界正交（大脑零依赖其余各层）。

| 层 | 位置 | 系统功能 | 一句话定位 |
| ---------------- | ------------------------ | ----------- | --------------------------------------------------- |
| 🧠 **灵枢大脑** | [`md_cg/`](md_cg/) | **元认知** | 记忆本体：对话沉淀为 md 认知图，记什么 / 取什么 / 能否写入全由确定性规则裁决 |
| ⚙️ **Rust 检索引擎** | [`rust/`](rust/) | 检索内核 | 零第三方依赖三形态：库内嵌大批量 / `--serve` 进程实例 / 评测器，与 Python 口径 rank 逐位对拍 |
| 🐝 **蜂群运行时** | [`swarm/`](swarm/) | **自维持** | 多进程蜂群执行层：.pbc 确定性实例 + Gossip 拓扑 / 水位信箱 / WAL-HMAC / 健康评分 |
| 📜 **中文编译器** | [`compiler/`](compiler/) | **验证 · 审计** | 词法 → 语法 → 名实校验 → 白名单代码生成 → 验证终裁，五环确定性编译链 |
| ⬢ **蜂巢并发引擎** | [`hive/`](hive/) | **自我改进** | worker 池原子领取 / 心跳 / 超时强杀 / 崩溃恢复，文件协议即接口，MCP 五工具接入 |

> 五件套共享同一套 19 条工作纪律与记忆闭环（见[工程纪律](#-工程纪律与设计者视角可选复用)）；**只用记忆就只接大脑**，不必理解蜂群与编译器。**🧬 身体面**（世界模型七层／3D 场景／白箱生成／蜂窝神经网络／记忆可视化）已独立公开为 [**FuRongJun-1999/lingshu**](https://github.com/FuRongJun-1999/lingshu)（经 MCP 与本大脑组合）。

## 🚫 它不是什么

- **不是一个基础模型**——不发布权重、不做预训练
- **不是开箱即用的产品，也不是零成本**——它是基础设施，需要你接自己的 Agent；完整评测需 Rust 工具链与 Node，跑全量套件要编译
- **不宣称 AGI**——五环理念是工程目标的自我描述，不是能力承诺

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
```

**记忆只有一个真源**：`md_cg/` 认知图（纯 md 文档，随包自带）；「身体」能力为可选后端，不再存记忆、默认不启动。其它 MCP 宿主同构：宿主工具面 ↔ stdio MCP ↔ `md_cg`，差异只在**纪律注入方式**。

## 🧰 工具面

| 能力 | MCP 入口 |
|---|---|
| 写入 · 关系链接 · 结构关系 | `cg(op=write)` `cg(op=link)` `stg(op=relation)` |
| 检索 · 条件路由 · 因果链 · 时间线 | `mdcg_recall` `mdcg_search` `cg(op=route)` `stg(op=timeline)` |
| 裁决 · 遗忘 · 冲突检测 · 反思 · 身份 · 演化 | `cg(op=verify)` `cg(op=forget)` `cg(op=metacognition)` `cg(op=identity)` `cg(op=evolution)` |
| 重要性评分 · 预算装包 · 分层注入 · 记忆自净 · 自维持巡检 | `cg(op=session)` `cg(op=scrub)` `cg(op=consolidate)` `cg(op=maintain)` `cg(op=sustain)` |
| 会话隔离 · 时效过滤 · 审计留痕 · 可靠性闸 | `mdcg_remember(session=…)` `validity=true` `cg(op=audit)` `cg(op=ccg)` · [护栏宪章](docs/mdcg/guardrail-charter.md) · [CCG 编译](docs/mdcg/CCG六要素编译.md) |

**`tools` 模式**：`'core'`（默认 · 2 个）｜ `'brain'` / `'all'`（30 个）。风险工具 `mdcg_forget` / `mdcg_restore` / `mdcg_review_decide` 需 `can_admin`。逐 op 映射见 [功能调用映射表](docs/mdcg/功能调用映射表_v0.1.md) 与 [op 全表](docs/mdcg/cogmap_ops.md)（自动生成，`cogmap_sync.py check` 守漂移）。

## 📚 文档地图

| 去哪里 | 看什么 |
|---|---|
| [docs/ 目录索引](docs/README.md) | 六域快速索引 · 新文档归域规则 |
| [安装与运维](docs/ops/README.md) | 安装前置 / 30+ 配置项 / 写入凭据 / 升级重启 / [环境与已知问题](https://github.com/FuRongJun-1999/dsh-memory/blob/main/docs/ops/%E7%8E%AF%E5%A2%83%E4%B8%8E%E5%B7%B2%E7%9F%A5%E9%97%AE%E9%A2%98.md)（宿主告警·体积·落盘·设计取舍） |
| [评测总览](docs/eval/评测总览.md) | 六家横评 / 弱证据与证据防火墙 / 中英双语差距 / 公开数据集 / 七维标尺 / 第三方验证 |
| [开发与编码约定](docs/dev/README.md) | 测试约定 / UTF-8 与 id 契约 / 开关矩阵 / Linux 双栈验证 |
| [多 harness 接入](docs/mdcg/多harness接入.md) | 五端纪律注入差异 / 出货面 vs 源码树分界 |
| [Releases](https://github.com/FuRongJun-1999/dsh-memory/releases) | 逐版本变更（本 README 不再维护发布日志）· [理论四篇](docs/theory/) |

## 🔌 多 harness 接入（按端分目录）

> **主推路径：MCP 直挂**——各端共性都是挂载同一个 stdio MCP server（`python -m md_cg.mcp_server`），**不依赖任何插件系统**。

| 目录 | harness | 纪律注入方式 |
|---|---|---|
| [`dsh/`](dsh/README.md) | DeepSeek Harness | `~/.dsh/profiles/web/cordis.patch.yml` 的 `personaPrefix`（compact · 每轮） |
| [`codebuddy/`](codebuddy/README.md) | CodeBuddy | 项目根 `CODEBUDDY.md`（full · 会话起始） |
| [`zcode/`](zcode/README.md) | ZCode | 项目根 `AGENTS.md`（full · 会话起始） |
| [`codex/`](codex/README.md) | Codex CLI | 项目根 `AGENTS.md`（full · 会话起始） |
| [`claude/`](claude/README.md) | Claude Code | 项目根 `CLAUDE.md`（full · 会话起始） |

> 五端纪律**同源**（`docs/工作纪律_认知图条目_v1.1.json`），由 `scripts/render_discipline.py` 渲染、`scripts/verify_discipline.py` 守卫漂移。

## 🤝 贡献与验证文化

**尤其鼓励「经过验证有效」的提交**：issue 请给出触发条件、最小复现与实测读数；PR 请附改动说明与验证方式（复跑命令与读数）；结论均以**能被独立复跑**为准——[issue #1](https://github.com/FuRongJun-1999/lingshu/issues/1) 是一个好例子（触发链、最小复现、判据三样都齐）。缺少证据、无法复现的描述，我们会先回帖请求补充证据再处置。

- **PR 审核**：走「技术审（外部验证者）＋ 理论核（本项目）」两道闸；缺少证据的提交会先回帖请求补充再处置
- **📣 蜂巢反馈邀请**：`hive/` 处于稳定阶段，但并发与崩溃恢复需真实负载打磨。**失败路径比「跑通了」更有价值**——请开 [Issue](https://github.com/FuRongJun-1999/dsh-memory/issues) 并附 `hive_doctor` 输出
- **安全缺陷**：含可直接利用细节的走私密通道，其余仍走公开 issue

## 📏 工程纪律与设计者视角（可选复用）

> 灵枢自身按一套 **18 条工程纪律**运行（理论先行 / 全面处理 / 根因纪律 / 验证先行 / 双副本同步 / 兜底路径 / 任务派发统一走蜂巢 / 内容政策双清单 / 敏感信息隔离 / 记忆闭环）。它本是灵枢的「自我约束」，与你用不用灵枢无关；但若你希望自己的 Agent 也具备同样的工作方式，这套纪律**可以直接复用**——[纪律真源](docs/工作纪律_认知图条目_v1.1.json)（每条 ≡ 一个认知图节点，含触发词路由）· [设计者视角元技能](skills/skills/designer-perspective/)（动手前回答「该不该做 / 为什么做 / 条件够不够」）。部分条款针对灵枢私有管线，复用时建议只取方法论 / 执行 / 调度 / 合规 / 记忆闭环五组通用条款。

## 护栏宪章 · 许可证

本插件接入即接受 **[灵枢护栏宪章 v2.0-published](docs/mdcg/guardrail-charter.md)** 约束——对外部智能体与人类使用者的行为边界作出公开、可执行、可审计的规定，并保护人类使用者。

MIT © 荣（FuRongJun-1999）· 灵枢 LINGSHU 工程实现。DeepSeek Harness 为 DeepSeek 官方开源项目（MIT），本插件与之无隶属关系。
