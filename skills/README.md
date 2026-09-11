# lingshu-skills · 灵枢自我认知技能包

> 灵枢（AEIS · Agent Engineering Implementation Specification）· CommonTrustProtocol 主仓库内部
> **本质：灵枢了解自身的工具**——不是独立仓库，是灵枢项目的一部分。
> 用灵枢自己构建的条件单元，描述灵枢自己如何认知（白箱自举的对外投影）。

---

## 这是什么

一个 **Agent Plugins 1.0.0 兼容包**（agent-plugins.org），内含 **686 个 Agent Skills（六域条件单元）+ 1 个元技能（设计者视角）**：

| 域 | 单元数 | 内容 |
|---|---|---|
| compiler | 116 | 中文编译器（词法/语法/编译/VM/调试/分析）|
| pylang | 120 | Python 语言机制（表达式/函数/类/闭包）|
| graph | 117 | 图算法与图数据库 |
| os | 112 | 操作系统（进程/调度/文件系统）|
| browser | 104 | 浏览器与网页 |
| net | 117 | 网络（协议/传输/安全）|
| **合计** | **686** | 白箱六域条件单元 |

每个技能描述灵枢在**什么条件下**能做什么、**怎么执行**、**克制什么**——比标准 Agent Skills 多出
**KCCS 四要素（生效条件/子功能/执行/不适用条件）** 与**不适用条件三通道**（description「Not for」+
metadata.kccs.not_applicable + 正文克制条款章节）。

## 三层关系（知识 → 说明书 → 执行）

```
知识真源（本仓 md_cg）           md_cg/whitebox_kb/wisdom/*_code_units.py（KCCS 四要素，真源）
        ↓ 导出（tools/skill_export.py + skill_export_verify.py 门禁，工具置身体仓）
说明书（本包）                  skills/ —— Agent Skills：何时用/怎么用/克制什么
        ↓ 执行
MCP（灵枢 33 工具）             md_cg-mcp（MCP stdio）· 随 dsh-memory 插件自带——物理基底裁决
```

| 层 | 是什么 | 作用 |
|---|---|---|
| 知识真源 | 条件单元库（686 单元）| 知道什么、条件是什么 |
| **本技能包**（说明书）| SKILL.md 技能 | 告诉 agent 何时用、怎么用、克制什么（认知自身）|
| MCP（执行）| 灵枢 77 工具 | 提供实际能力执行（编译/运行/断言 = 物理基底）|

**技能包的 Verification 由灵枢 MCP 工具执行**——技能说「怎么验证」，MCP 负责「真去跑」。

## 元技能层（设计者视角）

除 686 个操作层条件单元外，本包含 1 个**元技能** `designer-perspective`：

| 维度 | 说明 |
|---|---|
| 定位 | 不承担操作层执行，只赋予全局观测 / 结构识别 / 方向判断 / 资格裁决 / 条件层归因（《智能论3.4》1.4.2 视角层次）|
| 与条件路由的关系 | 互补：686 条件单元回答「怎么做」，元技能回答「该不该做 / 为什么做 / 条件够不够」；`condition-route.unit-count` 仍为 686，元技能单列 |
| 真源 | 手写（真源即 `skills/designer-perspective/SKILL.md`）；不属于六域条件单元，不经 `tools/skill_export.py` 生成 |
| 认知图接入 | 只读调用 md_cg（dsh-memory）：`mdcg_metacognition.self_check`（回答前自检）/ `mdcg_search`（四态阶梯）/ `mdcg_evolution`（账本）；写操作须由 agent 显式发起 |
| 自证 | `python skills/designer-perspective/tests/selftest.py` → 逐项结果 + 通过率 |

```bash
cd skills/designer-perspective
python scripts/designer.py declare --position designer --space 观测工具=条件证据
python scripts/designer.py judge --query "..." --conditions '{"观测位置":"操作层"}' --emit-mcp
python tests/selftest.py            # 认知能力验收（17 条用例，输出通过率）
```

## 为什么是「自我认知」

- 每个技能描述的是**灵枢自己的能力**（如「编译-递归」= 灵枢编译器如何编译递归函数）
- 整包 = 灵枢把自己「会做什么、在什么条件下做、克制什么」显式写成说明书
- 与「认知自身的图」（archify 认知图补强）同思想：图 = 视觉化自我认知，技能包 = 文本化自我认知
- **白箱自举的对外形态**：灵枢用自己构建的条件单元描述自己

## 结构

**v2.0 层级化布局**（2026-09-11 重组）：687 个平铺条目收敛为 **7 个顶层技能**（6 域入口 + 1 元技能）。
入口层进 agent 上下文做域级命中；686 个单元收进 `<域>/units/` 按需回读，单元内容零改动。

```
aeis/skills/
├── plugin.json                  # Agent Plugins manifest（condition-route 已层级化声明）
├── skills/lingshu-<domain>/     # 6 个域入口（compiler/pylang/graph/os/browser/net）
│   ├── SKILL.md                 # 域级 KCCS 四要素 + 子域路由表（子域→单元 slug）+ 路由流程
│   └── units/<slug>/SKILL.md    # 686 个条件单元（原样收纳；KCCS 单元级四要素；按需回读）
├── skills/designer-perspective/ # 元技能（手写真源，不属六域）
│   ├── SKILL.md                 # 设计者视角主说明书（三通道负路由 + KCCS 四要素）
│   ├── references/              # 5 份方法论（每条附《智能论3.4》行号锚点）
│   ├── scripts/                 # designer.py（声明/四态判定/五失配归因/蒸馏/--emit-mcp）
│   └── tests/                   # cases.jsonl + selftest.py（认知能力验收，输出通过率）
└── README.md                    # 本文件
```

### 路由三通道（替代 686 description 全量加载）

| 通道 | 载体 | 适用 |
|---|---|---|
| 词面路由 | 域入口路由表（子域→单元 slug）| 任务含明确触发词 |
| 语义路由 | `mdcg cg op=route intent=<任务>` | 语义模糊/跨子域 |
| 全量索引 | `md_cg/whitebox_kb/wisdom/trigger_words_index.json` + 认知图 index_doc 索引 | 离线盘点/批量检索 |

## 使用

1. **作为 Agent Plugins 包**：任意符合 agentskills.io/agent-plugins.org 规范的 agent 可加载本包
2. **配合灵枢 MCP**：技能的 Verification（物理基底）由灵枢 MCP 工具执行（md_cg-mcp，随插件自带）
3. **再生成**：改知识源（`md_cg/whitebox_kb/wisdom/` 单元库）后，用身体仓的 `tools/skill_export.py --out skills` 重新导出，
   `tools/skill_export_verify.py` 作为发布门禁（验证全绿才允许提交；默认 clean-room——导出前清空输出目录，历史残留不计入校验）。
   ⚠️ v2.0 起导出器须适配层级布局：单元写入 `lingshu-<domain>/units/<slug>/` 并保留 6 份域入口（入口由导出器按 trigger_words_index 生成路由表），身体仓工具更新前勿触发重新导出

## 验证状态（发布门禁）

- ✅ 686/686 单元通过格式 + 三通道校验（六域）
- ✅ not_applicable / when / execute / 正文克制条款 全部 686/686
- ✅ 元技能 designer-perspective 认知能力验收 17/17（tests/selftest.py）
- ✅ plugin.json 符合 agent-plugins.org schema（含 extensions 扩展：self-cognition/condition-route/meta-skill/mcp）

## 与主仓库纪律

- 真源 = `aeis/wisdom/*_code_units.py`（R1 主仓库唯一真源）
- 本包 = 生成投影（R3 运行时产物不入库——但本包是发布物，随主仓库版本化）
- 变更须重新导出 + 验证门禁通过（R6 变更验证）

---

*灵枢自我认知技能包 · 白箱条件化知识 · KCCS 四要素不放弃 · MCP 物理基底执行*
