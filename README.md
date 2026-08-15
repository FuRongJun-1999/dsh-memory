# @furongjun1999/dsh-memory

**灵枢（AEIS）× DeepSeek Harness 插件**：把灵枢的时空记忆/知识飞轮/自我认知接入 DSH，
让 Agent 拥有跨会话的长期记忆与认知能力。

> 灵枢（AEIS）是一个遵循「智能论 v3.2」协议的时空记忆引擎：五层记忆（锚点/结构/知识/情境/自我）、
> 知识飞轮（验证→归纳→联想→蒸馏→推演）、自我认知循环（P0 系列）、外部知识摄取。
> 本插件是它在 DeepSeek Harness 生态中的桥。

## 特性

- **工具桥接**：Agent 可直接调用 `lingshu_remember / recall / search / think` 等灵枢能力
  （默认精选 12 个核心工具，可切换全部或自定义集合）
- **自动记忆**：DSH 对话自动沉淀进灵枢记忆库——用户消息带重要性写入、去重，随会话累积
- **动态 schema**：工具清单运行时从灵枢 `tools/list` 实时拉取，灵枢升级新增工具 DSH 侧零改动
- **零运行时依赖**：手写 stdio MCP 桥（不依赖 MCP SDK），与灵枢 D-005「核心零外部依赖」工程哲学一致
- **进程自愈**：灵枢 Python 子进程崩溃自动指数退避重启（1s→30s），插件卸载优雅退出

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
│ 38 工具 · SQLite 五层记忆                    │
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
    tools: 'core'
    memory:
      userMessage: true                # 用户消息自动沉淀
      assistantMessage: false          # agent 回复沉淀（默认关，防噪音）
      toolResult: false                # 工具结果沉淀（默认关）
    env:
      BOCHA_API_KEY: !!js process.env.BOCHA_API_KEY   # 可选：网络搜索能力
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
| `tools` | `'core' \| 'all' \| string[]` | `'core'` | 暴露的工具集合 |
| `memory.userMessage` | boolean | `true` | 用户消息 → 自动 remember |
| `memory.assistantMessage` | boolean | `false` | agent 回复 → 自动 remember |
| `memory.toolResult` | boolean | `false` | 工具结果 → 自动 remember |
| `memory.importance` | number | `0.6` | 自动记忆的重要性（0~1） |
| `toolCallTimeoutMs` | number | `60000` | 单次工具调用超时 |
| `maxRetryDelayMs` | number | `30000` | 进程重启最大退避间隔 |
| `failOnStartupError` | boolean | `false` | 启动失败是否让插件激活失败 |

## 工具清单（core 集合）

| 工具 | 说明 |
|------|------|
| `lingshu_remember` | 写入记忆（内容/重要性/标签/实体） |
| `lingshu_recall` | 组合联想召回（相似+重要性+近因加权） |
| `lingshu_search` | 内容检索（二元组 Jaccard） |
| `lingshu_timeline` | 记忆时间线 |
| `lingshu_think` | 推理前记忆注入（检索相关记忆构造上下文） |
| `lingshu_relate` | 建立关系边（causal/similar/sequential…） |
| `lingshu_predict_routes` | 生成式预测（未来路线集合） |
| `lingshu_ingest_text` | 外部知识摄取（文本） |
| `lingshu_ingest_url` | URL 页面摄取 |
| `lingshu_session_note` | 会话要点外部化 |
| `lingshu_self_check` | 完整性自检 |
| `lingshu_service_info` | 灵枢服务状态 |

配置 `tools: 'all'` 可暴露全部 38 个工具（含视觉/自我认知/设计者裁决等）。

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

## 许可证

MIT © 荣（FuRongJun-1999）· 灵枢 AEIS 工程实现

DeepSeek Harness 为 DeepSeek 官方开源项目（MIT），本插件与之无隶属关系。

## 大脑模式（v0.2.0 · 轻量版）

**去掉身体的完整大脑**——默认工具集为 `brain`（心智全量，不含身体/视觉设备）：

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
| 长期记忆门 | longterm_snapshot / promote_memories（v1.15 主动沉淀） |
| 服务 | service_info |

配置：`tools: 'brain'`（默认）｜`'core'`（12 精选）｜`'all'`（含身体/视觉，需本地设备）｜工具名数组。

## 护栏宪章（接入即接受约束）

本插件接入即接受 **[灵枢护栏宪章 v2.0-published](docs/guardrail-charter.md)** 约束——
对外部智能体与人类使用者的行为边界作出公开、可执行、可审计的规定，并保护人类使用者。
宪章效力不高于智能论协议本身（协议＝自我约束，宪章＝对外约束）。
本插件随包自带宪章全文（`docs/guardrail-charter.md`），安装即可查阅。
