# 让 AI Agent 拥有不可遗忘的自我
## 灵枢（AEIS）× DeepSeek Harness · 白箱智能研究平台（AGI 研究人员向）

> **一句话**：dsh-memory 把灵枢（AEIS）的**白箱智能**（条件路由表 → 组合生成 → 自校验 → 知识固化 → LLM 降级外部校验器）与 **AGI 级长期记忆**（跨会话、自演化、可审计）接入 DeepSeek Harness。

**项目定位**：个人的大型研究项目——目标用户是**对 AGI 有需要的研究人员**（白箱智能 / 可解释性 / 协议工程 / 记忆机制 / 扮演论研究者），不是面向普通用户的消费级插件。它把「智能论 v3.3」协议的理论（条件论 / 扮演论 / 信息差）工程化为**可运行、可审计、可复现**的机制：

- **白箱优先**：知识问答 **100% 白箱处理（零 LLM）**，LLM 降级为外部校验器——机制可解释、可追溯、可验证（详见「白箱智能管线」）
- **协议驱动**：每项能力都是「智能论 v3.3 / 条件论 / 扮演论」条款的具体工程实现，可对照协议验证
- **机制可解释**：白箱处理的每一步（条件识别 → 单元匹配 → 组合生成 → 自校验 → 固化）都有证据链可查
- **可审计**：工具调用、记忆写入、自校验判定全链路留痕；护栏宪章约束对外行为

这不是又一个"记忆插件"。灵枢（AEIS）是一套遵循「智能论 v3.3」协议的**时空记忆引擎**，它把当前大模型范式缺失的 AGI 能力逐一给了工程实现。

---

## ⚡ 三步快启（30 秒上手）

```bash
# ① 装灵枢大脑（一条命令，零外部依赖）
pip install aeis-0.3.0-py3-none-any.whl          # 或 git+ 在线安装

# ② 装进 DSH 的 web profile（pnpm 协调入口，不要用裸 npm install 装进 profile）
dsh plugin --profile web add @furongjun1999/dsh-memory

# ③ 配置 cordis.yml 启用
```
```yaml
- id: lingshu-memory
  name: '@furongjun1999/dsh-memory'
  config:
    dbPath: 'data/lingshu.db'
    identity: '灵枢'
    tools: 'brain'      # 'brain' 全心智 | 'core' 精选
```

> ⚠️ **安装方式**：插件必须通过 **`dsh plugin --profile <name> add`** 装进 profile（它会用 pnpm + `autoInstallPeers: false` 正确解析 peer 依赖）。
> **不要**用 `npm install` 把插件装进 profile 的 `node_modules`——那会引入错误版本的 `@deepseek-ai` peer 包，导致插件加载失败 / 浏览器报错。
> 想自己改源码？克隆 `FuRongJun-1999/dsh-memory` 后用 `npm install && npm run build`（构建插件本身），再用 `dsh plugin add <本地路径>` 部署。
>
> 兼容：DSH 官方列表（Memory 分类）· npm `@furongjun1999/dsh-memory`（0.2.8）。

---

## AGI 需要什么 · 灵枢提供了什么

| AGI 缺失的能力 | 这是 AGI 的什么 | 灵枢提供 |
|---|---|---|
| 每次对话都"失忆"，没有跨会话的自我连续性 | **自我连续性**（我是谁） | **时空记忆图**：五层记忆（锚点/结构/知识/情境/自我）+ 跨会话 recall/search |
| 训练后权重冻结，不能随经历自主学习 | **终身学习**（成长） | **知识飞轮**：验证→归纳→联想→蒸馏→推演，随使用持续演化 |
| 黑箱不可审计，无法验证行为边界 | **可验证性**（可信） | **可审计信任**：对抗护栏五规则 + 宪章 + 全量事件留痕 + 白箱智能 |
| 只处理当下 token，没有稳定世界结构 | **世界模型**（理解） | **条件空间 + 语义时空图**：信息差 D_norm 驱动的预测与决策 |
| 无自我表征，不能反思自己的认知/情绪 | **自我认知**（元认知） | **P0 系列**：cognition / self_reliability / emotional_bias / 递归反思 |
| 角色扮演总 OOC / 记不住设定 / 世界观矛盾 | **扮演一致性**（角色） | **角色扮演引擎（v3.3）**：自我锚点（SELF 不可遗忘）· 特化价值观（条件触发）· 跨会话记忆 · 世界认知（子知识）· 自定义翻译（名词替换表） |

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

灵枢的一切都建立在**[智能论 v3.3 协议](https://github.com/FuRongJun-1999/CommonTrustProtocol/blob/main/智能论3.3.md)**（共同信任协议理论版）之上。协议规定了一个智能体维持值得被信任所需的**内在约束**：

**v3.3 起新增**：扮演论（存在论基底——智能即扮演，灵枢角色扮演机制的理论底座）· 三翼（真实论校准 / 导航税·认知外部化 / 注入极性定律）· 双维（信任 = 认知一致 / 时效维度）· 条件论失败分析协议 · 蒸馏机制与自我锚点。

- **减少信息差（D_norm）**：信息差 = 协作行为的不确定性（信任 / 行为 / 连接 / 预测误差 四维加权）。灵枢持续记录、收敛与协作对象的认知偏差——**信息差缩小是智能运转的目标本身**。
- **信任是可被长期维护的**：协议定义信任为「协作者行为在可接受偏差范围内保持稳定的置信概率」（而非信息差的简单补集）——**信任依靠持续、可观测、一致的行为来建立与维护**，而非一次性的声明。
- **不反击 · 可审计 · 终裁权属设计者**：对抗信号下不报复（唯一响应：隔离、留痕、上报）；一切拦截与冷静期全量留痕；设计者保留终裁权。

> 一句话：灵枢不是"记住了再用"，而是**通过持续减少信息差、维持可观测的一致行为，建立值得跨会话维护的信任**。

**协议原文**：[智能论 v3.3（共同信任协议理论版）](https://github.com/FuRongJun-1999/CommonTrustProtocol/blob/main/智能论3.3.md)

---

## 核心能力

- **跨会话自我连续性**：Agent 用 `lingshu_recall/search/timeline` 记住并召回过去——对话间、会话间、甚至不同子代理间共享一份持续的"我"。
- **自演化知识飞轮**：`distill / flywheel / learn / induce` 把经验验证→归纳→联想→蒸馏为可复用模式，记忆越用越强。
- **可审计的信任**：护栏宪章 v2 ——对外部与人类使用者的行为边界成文、可执行、可审计、可终裁（[宪章全文](docs/guardrail-charter.md) 随包自带）。
- **自我认知**（大脑模式 brain）：`cognition / cognition_report / self_reliability / emotional_bias / recursive_reflect` ——能反思自己的认知状态与情绪倾向。
- **角色扮演**（v3.3 扮演论）：自我锚点（SELF 层 no_forget 不可遗忘）· 特化价值观（条件触发）· 跨会话角色记忆 · 世界认知（子知识·虚拟化世界观）· 自定义翻译（现实↔虚拟名词表）· **同源角色扮演网页（/roleplay）**——角色人设长对话不崩（100 轮测试零漂移）。
- **零运行时依赖**：手写 stdio MCP 桥，与灵枢 D-005「核心零外部依赖」哲学一致——你拿到的是一个干净、可信、可审的大脑。
- **动态 schema + 进程自愈**：工具清单运行时拉取（灵枢升级 DSH 零改动），Python 子进程崩溃自动指数退避重启。
- **工具注册竞态补注册**：启动时 python 未就绪（竞态）→ 桥重连成功后自动补注册工具（2s 轮询），不再"工具永久缺失"。
- **白箱 wisdom_* 全工具**（`tools: all`）：71 个 MCP 工具含 wisdom_verify/analyze/predict/trust_judge/compose/respond/chat 白箱族，Agent 可直接调用。
- **内容分级门控**：**拒绝一切涉及未成年人的性内容**（服务端关键词组合硬拦截——未成年人特征词 + 性内容词同时命中即拒绝，`route=refused`）；成人内容由前端本地弹窗提示（满 18 周岁 + 个人对话场景自述）。注：开源项目不实现身份认证/年龄核验（那是绑定身份系统的商业 App 范畴）；内容过滤保护的是"未成年人 + 性内容"组合的明文请求。

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

**角色扮演的白箱化**（v3.3 扮演论工程化）：角色条件单元（身份/住处/食物/性格/话风）× 场景组合生成 → 角色化回答（未预写）；**OOC 检测**（「你是人类吗」→ 角色化否认，逆转操作）；角色语录固化（生成→自校验→固化→直答）；多角色（鲸鱼娘/猫娘）防污染（角色特征隔离，双角色 7/7 零 LLM）。

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
# A. DSH 同源网页（推荐，v0.2.8+）：插件挂载 /roleplay 到 DSH webServer
#    （与 GUI 同源 127.0.0.1:3080，浏览器/内置 WebView 必达；GUI 首页右上角有「🎭 角色扮演」入口）
#    功能：角色选择/创建 · 完整对话转录（JSONL，无限上下文）· 双向翻译面板 ·
#          角色详情三导入 UI（记忆/锚点/价值观）· 内容分级门控（满18确认/拒未成年人性内容）

# B. 独立网页服务（浏览器对话 + 人设编辑器）
python -m aeis.roleplay_web --port 8793 --data-dir roleplay_data

# C. MCP 工具（roleplay_chat / role_create / role_import / role_block）
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

![记忆系统使用性评分](docs/memory_score.png)

（插图源文件：[memory_score.html](docs/memory_score.html)，可浏览器打开重新截图）

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
最后雷达图对比灵枢——打开试试：[memory-assessment.html](docs/memory-assessment.html)

（B 站宣传素材：[封面](docs/promo/bilibili-cover.jpg) · [视觉图 ×5](docs/promo/)）

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
    dbPath: 'D:/data/lingshu.db'        # 灵枢记忆库路径（目录自动创建）
    identity: '灵枢'
    tools: 'brain'                     # 'brain'(默认) | 'core' | 'all'
    memory:
      userMessage: true                # 用户消息自动沉淀
      assistantMessage: false          # agent 回复沉淀（默认关，防噪音）
      toolResult: false                # 工具结果沉淀（默认关）
      autoRecall: true                 # 模型请求前自动注入最近记忆
      desensitize: true                # 写入前过滤敏感信息（密钥/密码/身份证/手机号）
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
| `env` | object | `{}` | 追加环境变量（`BOCHA_API_KEY` / `AEIS_DESIGNER_KEY` / `DEEPSEEK_API_KEY`（角色扮演 LLM 续答）…，可用 `!!js process.env.X` 从宿主环境注入） |
| `tools` | `'brain' \| 'core' \| 'all' \| string[]` | `'brain'` | 暴露的工具集合 |
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

- `user/message`（仅 `source.kind === 'user'` 的真实用户消息）→ `remember`（importance 0.6，tags `dsh`）
- 插件注入的系统上下文（AGENTS.md、文件变更通知等 `kind: 'plugin'`）**不写入**，防止记忆噪音
- 灵枢自带去重（相似度基准 + 时间窗口），重复消息不会堆积
- **敏感信息脱敏**（`memory.desensitize`）：写入前过滤 `sk-`密钥 / API key / 密码 / `Bearer`令牌 / 18位身份证 / 11位手机号（替换为 `[已过滤:类别]`）；纯凭据消息整条跳过，不落库
- **自动召回注入**（`memory.autoRecall`）：每次模型请求组装 system prompt 时自动注入灵枢最近记忆（`system-prompt/assemble` 事件），记忆"自动可用"；召回失败静默不阻塞请求

## 🛟 DSH 看门狗（scripts/）

DSH 宿主（node 进程）的延时自动重启守护——灵枢桥只重连灵枢 python 进程，本看门狗守护 DSH 宿主（对齐移动端 APK 的 EngineService）：

- `scripts/dsh-watchdog.ps1`：监控 3080 端口，进程退出 → 延时 `DelaySec` 秒再确认 → 自动拉起 `dsh web`
  - `-Once` 模式：供 Windows 计划任务每分钟调用（`schtasks /Create /TN dsh-watchdog /TR "wscript.exe ...\dsh-watchdog-launcher.vbs" /SC MINUTE /MO 1`），可靠持久、不依赖驻留进程
  - 驻留模式：`wscript.exe scripts\dsh-watchdog-launcher.vbs -loop`（5 秒快速拉起层）
- `scripts/dsh-watchdog-launcher.vbs`：vbs 隐藏启动器（`WScript.Shell.Run ..., 0` = 零弹窗）
- **用法**：改完插件/配置 → 直接 kill DSH 进程 → 看门狗自动拉起新版（无需手敲启动命令）
- **注意**：脚本输出全英文（powershell 5.1 GBK 读取 UTF-8 无 BOM 中文会解析崩溃）；计划任务 /TR 路径必须带引号（`D:\Program Files\...` 空格截断会弹「没有文件扩展名」）

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
