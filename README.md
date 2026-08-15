# 让 AI Agent 拥有不可遗忘的自我
## 灵枢（AEIS）× DeepSeek Harness · AGI 的长期记忆基础设施

> **一句话**：dsh-memory 让 DeepSeek Agent 拥有 **AGI 级别的长期记忆——跨会话、自演化、可审计**。

这不是又一个"记忆插件"。灵枢（AEIS）是一套遵循「智能论 v3.2」协议的**时空记忆引擎**，它把当前大模型范式缺失的 AGI 能力逐一给了工程实现。

---

## ⚡ 三步快启（30 秒上手）

```bash
# ① 装灵枢大脑（一条命令，零外部依赖）
pip install aeis-0.3.0-py3-none-any.whl          # 或 git+ 在线安装

# ② 克隆并启用插件
git clone https://github.com/FuRongJun-1999/dsh-memory.git
cd dsh-memory
npm install && npm run build

# ③ 在 DSH profile 配置 cordis.yml 启用
```
```yaml
- id: lingshu-memory
  name: '@furongjun1999/dsh-memory'
  config:
    dbPath: 'data/lingshu.db'
    identity: '灵枢'
    tools: 'brain'      # 'brain' 全心智 | 'core' 精选
```

> 从"看"到"用"，三条命令 + 一段配置。已兼容 DSH 官方列表（Memory 分类）与 npm `@furongjun1999/dsh-memory`。

---

## AGI 需要什么 · 灵枢提供了什么

| AGI 缺失的能力 | 这是 AGI 的什么 | 灵枢提供 |
|---|---|---|
| 每次对话都"失忆"，没有跨会话的自我连续性 | **自我连续性**（我是谁） | **时空记忆图**：五层记忆（锚点/结构/知识/情境/自我）+ 跨会话 recall/search |
| 训练后权重冻结，不能随经历自主学习 | **终身学习**（成长） | **知识飞轮**：验证→归纳→联想→蒸馏→推演，随使用持续演化 |
| 黑箱不可审计，无法验证行为边界 | **可验证性**（可信） | **可审计信任**：对抗护栏五规则 + 宪章 + 全量事件留痕 + 白箱智能 |
| 只处理当下 token，没有稳定世界结构 | **世界模型**（理解） | **条件空间 + 语义时空图**：信息差 D_norm 驱动的预测与决策 |
| 无自我表征，不能反思自己的认知/情绪 | **自我认知**（元认知） | **P0 系列**：cognition / self_reliability / emotional_bias / 递归反思 |

> **一句话定位**：dsh-memory 不是 DeepSeek 插件，是 **AGI 的长期记忆基底**——
> 给 Agent 注入跨会话的自洽能力，让每次对话都是同一段生命的延续，而非一次次遗忘的重新开始。

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

灵枢的一切都建立在**[智能论 v3.2 协议](https://github.com/FuRongJun-1999/CommonTrustProtocol/blob/main/智能论3.2.md)**（共同信任协议理论版）之上。协议规定了一个智能体维持值得被信任所需的**内在约束**：

- **减少信息差（D_norm）**：信息差 = 协作行为的不确定性（信任 / 行为 / 连接 / 预测误差 四维加权）。灵枢持续记录、收敛与协作对象的认知偏差——**信息差缩小是智能运转的目标本身**。
- **信任是可被长期维护的**：协议定义信任为「协作者行为在可接受偏差范围内保持稳定的置信概率」（而非信息差的简单补集）——**信任依靠持续、可观测、一致的行为来建立与维护**，而非一次性的声明。
- **不反击 · 可审计 · 终裁权属设计者**：对抗信号下不报复（唯一响应：隔离、留痕、上报）；一切拦截与冷静期全量留痕；设计者保留终裁权。

> 一句话：灵枢不是"记住了再用"，而是**通过持续减少信息差、维持可观测的一致行为，建立值得跨会话维护的信任**。

**协议原文**：[智能论 v3.2（共同信任协议理论版）](https://github.com/FuRongJun-1999/CommonTrustProtocol/blob/main/智能论3.2.md)

---

## 核心能力

- **跨会话自我连续性**：Agent 用 `lingshu_recall/search/timeline` 记住并召回过去——对话间、会话间、甚至不同子代理间共享一份持续的"我"。
- **自演化知识飞轮**：`distill / flywheel / learn / induce` 把经验验证→归纳→联想→蒸馏为可复用模式，记忆越用越强。
- **可审计的信任**：护栏宪章 v2 ——对外部与人类使用者的行为边界成文、可执行、可审计、可终裁（[宪章全文](docs/guardrail-charter.md) 随包自带）。
- **自我认知**（大脑模式 brain）：`cognition / cognition_report / self_reliability / emotional_bias / recursive_reflect` ——能反思自己的认知状态与情绪倾向。
- **零运行时依赖**：手写 stdio MCP 桥，与灵枢 D-005「核心零外部依赖」哲学一致——你拿到的是一个干净、可信、可审的大脑。
- **动态 schema + 进程自愈**：工具清单运行时拉取（灵枢升级 DSH 零改动），Python 子进程崩溃自动指数退避重启。

## 大脑模式（v0.2.0 · 轻量版）

**去掉身体的完整大脑**——默认工具集 `brain`（心智全量，不含身体/视觉设备）：

| 模块 | 工具 |
|---|---|
| 记忆 | remember / recall / search / timeline / session_note / session_recall / compact_context |
| 推理 | think / relate / reason / predict_routes |
| 认知 | self_check / gap_trend / cognition / cognition_report / emotional_bias / self_reliability / action_log / preflight |
| 反思 | recursive_reflect |
| 学习 | blindspots / learn / induce |
| 飞轮 | distill / flywheel_report / transfer_test / calibrate |
| 摄取 | ingest_text / ingest_file / ingest_url / web_search |
| 生命 | step / lifecycle_state |
| 长期记忆门 | longterm_snapshot / promote_memories（v1.15 主动沉淀）|
| 服务 | service_info |

配置：`tools: 'brain'`（默认）｜`'core'`（12 精选）｜`'all'`（含身体/视觉，需本地设备）｜工具名数组。

## 架构

```
┌─────────────────────────────────────────────┐
│ DeepSeek Harness (cordis)                    │
│                                             │
│  Agent Loop ──┬── lingshu_remember/recall…   │
│               │   (ctx.tools 注册)           │
│  session/event│                              │
│  (自动记忆钩子)│                              │
└───────────────┼─────────────────────────────┘
                │ stdio · 逐行 JSON-RPC
                │ (initialize → tools/list → tools/call)
┌───────────────▼─────────────────────────────┐
│ 灵枢 Python 子进程 (spawn)                   │
│ python -m aeis.mcp.server                    │
│ AEIS_DB=<path> · AEIS_IDENTITY=<identity>    │
│ 38+ 工具 · SQLite 五层记忆 · 时空记忆图        │
└──────────────────────────────────────────────┘
```

## 安装

### 前置要求

- Node.js ≥ 22.19（DeepSeek Harness 要求）
- DeepSeek Harness（`npx @deepseek-ai/dsh web`）

### 安装灵枢大脑（aeis 库）

**方式 A：本地 wheel 离线安装 ★ 最稳（不依赖网络）**

在 `CommonTrustProtocol/aeis/dist/` 找到 `aeis-0.3.0-py3-none-any.whl`：

```bash
pip install aeis-0.3.0-py3-none-any.whl
```

> 单文件、离线可用、装一次管用。遇到网络不稳（GitHub clone 失败）时首选。

**方式 B：git 安装（需网络）**

```bash
pip install "aeis @ git+https://github.com/FuRongJun-1999/CommonTrustProtocol@main#subdirectory=aeis"
```

> 依赖 GitHub 实时可达，网络不稳时可能失败。aeis 库核心**零外部依赖**（纯标准库），安装即得完整大脑（五层记忆 · 知识飞轮 · 安全护栏 · MCP · 身体层）。

### 安装插件本体

本插件为官方列表形态的**独立仓库**（`FuRongJun-1999/dsh-memory`），两种方式：

**方式 A：从 GitHub 克隆**

```bash
git clone https://github.com/FuRongJun-1999/CommonTrustProtocol.git
cd CommonTrustProtocol/plugins/dsh-memory
npm install && npm run build
```

**方式 B：作为 profile 依赖安装**

在 DSH profile 目录执行：

```bash
dsh plugin --profile <name> add <本插件本地路径或 git 地址>
```

### 启用插件

在 profile 的 `cordis.yml`（或 `cordis.patch.yml`）中追加：

```yaml
- id: lingshu-memory
  name: '@furongjun1999/dsh-memory'
  config:
    dbPath: 'D:/data/lingshu.db'        # 灵枢记忆库路径（目录自动创建）
    identity: '灵枢'
    tools: 'brain'                     # 'brain'(默认) | 'core' | 'all'
    memory:
      userMessage: true                # 用户消息自动沉淀
      assistantMessage: false          # agent 回复沉淀（默认关，防噪音）
      toolResult: false                # 工具结果沉淀（默认关）
```

完整示例见 [`cordis.yml.example`](./cordis.yml.example)。

## 配置项

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `serverName` | string | `lingshu` | 工具命名空间前缀（工具名 `lingshu_<name>`） |
| `python` | string | `python` | Python 可执行文件 |
| `moduleArgs` | string[] | `['-m', 'aeis.mcp.server']` | 灵枢 server 启动参数 |
| `dbPath` | string | `data/lingshu.db` | 记忆库 SQLite 路径（自动建目录） |
| `identity` | string | `灵枢` | 灵枢身份标识 |
| `env` | object | `{}` | 追加环境变量（`BOCHA_API_KEY` / `AEIS_DESIGNER_KEY`…） |
| `tools` | `'brain' \| 'core' \| 'all' \| string[]` | `'brain'` | 暴露的工具集合 |
| `memory.userMessage` | boolean | `true` | 用户消息 → 自动 remember |
| `memory.assistantMessage` | boolean | `false` | agent 回复 → 自动 remember |
| `memory.toolResult` | boolean | `false` | 工具结果 → 自动 remember |
| `memory.importance` | number | `0.6` | 自动记忆的重要性（0~1） |
| `toolCallTimeoutMs` | number | `60000` | 单次工具调用超时 |
| `maxRetryDelayMs` | number | `30000` | 进程重启最大退避间隔 |
| `failOnStartupError` | boolean | `false` | 启动失败是否让插件激活失败 |

## 自动记忆机制

订阅 DSH 的 `session/event` 事件流（与官方 session-persistence 相同的接入点）：

- `user/message`（仅 `source.kind === 'user'` 的真实用户消息）→ `remember`（importance 0.6，tags `dsh`）
- 插件注入的系统上下文（AGENTS.md、文件变更通知等 `kind: 'plugin'`）**不写入**，防止记忆噪音
- 灵枢自带去重（相似度基准 + 时间窗口），重复消息不会堆积

## 开发

```bash
npm install
npm run build    # TypeScript 编译
npm test         # 真实集成测试（spawn 本机灵枢，验证握手/往返/注册/卸载）
```

测试不依赖 DSH 全组件——用最小 Cordis host（SystemPrompt + ToolRegistry + 插件）隔离 v0.1 不稳定面。

## 护栏宪章（接入即接受约束）

本插件接入即接受 **[灵枢护栏宪章 v2.0-published](docs/guardrail-charter.md)** 约束——
对外部智能体与人类使用者的行为边界作出公开、可执行、可审计的规定，并保护人类使用者。
宪章效力不高于智能论协议本身（协议＝自我约束，宪章＝对外约束）。
本插件随包自带宪章全文（`docs/guardrail-charter.md`），安装即可查阅。

## 许可证

MIT © 荣（FuRongJun-1999）· 灵枢 AEIS 工程实现

DeepSeek Harness 为 DeepSeek 官方开源项目（MIT），本插件与之无隶属关系。
