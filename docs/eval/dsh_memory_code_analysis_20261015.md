# dsh-memory：代码、设计背景、理论与目的

## 1. 定位与目的

dsh-memory 为 AI Agent 提供跨会话长期记忆。Python 大脑保存和检索记忆，MCP（模型上下文协议）把能力交给宿主。DSH 插件负责启动大脑、注册工具和接入会话事件。

项目希望记忆能够被人读懂、被程序检索，并能说明使用条件与验证依据。设计目标见 [README：定位与五环理念](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/README.md#L22-L41>)。

## 2. 设计背景

早期设计记录列出三个问题：Python 库缺少服务接口；Markdown 与 SQLite 记忆并存；多智能体缺少统一的进程与权限模型。路线由此分为接口、统一存储、进程模型和数据源接入。

这段记录解释了当前架构的来源。MCP 承担服务接口，认知图保存记忆原文，宿主插件接入真实会话。背景见 [引擎到记忆操作系统的路线](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/docs/mdcg/认知图作为记忆操作系统_评估与路线_v0.1.md#L62-L83>)。

## 3. 为什么使用 Markdown 认知图

记忆节点由前置元数据和正文组成。前置元数据保存标识、层、条件与验证信息。正文采用人可以直接阅读的 Markdown。

设计把记忆层映射为目录，把条件分区映射为子目录。节点原文是存储真源，索引用于加速查找。索引可以从节点文件重建。依据见 [节点格式](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/nodefile.py#L2-L38>) 与 [rebuild_index](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/mdcg.py#L2363>)。

这种选择直接服务于人工审阅、版本差异比较和跨工具读取。作者的存储方案见 [目录与条件注释的设计理由](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/docs/mdcg/认知图_MD目录方案_v0.1.md#L40-L48>)。

## 4. 理论如何对应到代码

### 4.1 条件空间

作者主张知识需要声明成立的条件。代码把条件空间表示为四个槽位：

- `observation_position`：载体与观测位置。
- `time_window`：时间范围。
- `observation_tool`：观测方法。
- `existence_constraint`：存在约束。

四个槽位经统一函数合成为“生效条件”。定义见 [CONDITION_SLOTS](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/nodefile.py#L661-L685>)。字段和合成函数证明了工程映射存在，不能单独证明作者的普遍知识论命题。

### 4.2 六要素记忆卡

CCG（条件注释图）用六要素组织记忆卡。每个要素承担一个接口角色：

| 要素 | 代码定义的角色 |
|---|---|
| 功能名 | 签名与可读标识 |
| 生效条件 | 前置条件 |
| 子功能 | 分解与依赖 |
| 执行 | 调用 |
| 验证方式 | 后置条件与测试 |
| 不适用条件 | 拒绝域 |

这套结构把适用范围与操作方法放在同一张卡上。角色定义见 [六要素契约](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/nodefile.py#L46-L65>)。

### 4.3 相似度与执行资格分开

检索分数用于找到候选，资格规则决定候选如何使用。`judge_qualification` 按以下顺序判断：

1. 要素不全，返回 `BLINDSPOT`。
2. 命中不适用条件，返回 `REJECT`。
3. 适用条件未确认或缺少验证依据，返回 `DEFER`。
4. 其余情况返回 `ACCEPT`。

这是一套确定性的词面与结构规则。无查询情境时，代码允许跳过正条件确认，并在原因中说明。代码见 [四态资格判定](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/mdcg.py#L3920-L3994>)。

### 4.4 信息差与反思

代码中的信息差指标为：

```text
D = 1 - 有效候选数 / 真实候选数
有效候选：score > 0 且 state == ACCEPT
```

该指标度量一次检索的资格结果。负记忆覆盖提示不计入分母。空候选返回 1。代码见 [_compute_d](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/mdcg.py#L5110-L5134>)。

作者另有关于信息差、反思和智能的理论。仓库保留了理论到机制、代码和实验的映射。阅读时需要区分字段存在、测试通过和普遍命题成立。依据见 [理论映射矩阵](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/docs/theory/理论_机制_代码_实验_缺口矩阵_v0.1.md#L7-L34>)。

## 5. 核心代码流程

```text
宿主会话 / 显式工具调用
  → TypeScript 插件与 stdio 桥
  → Python MCP 分发
  → 写入 / 检索 / 状态查询
  → Markdown 节点与事件台账
  → 返回结果与来源
```

### 5.1 宿主与协议入口

插件桥管理 Python 子进程，并通过逐行 JSON-RPC 完成握手、工具发现和调用。代码见 [stdio 桥](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/src/bridge.ts#L1-L17>)。

默认工具面把认知图操作收敛到 `cg`，把时空关系查询收敛到 `stg`。细粒度工具面另由配置开启。入口见 [MCP 工具面](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/mcp_server.py#L633-L641>)。

### 5.2 写入

显式写入经拦截器链处理引用、依赖、内容审核、一致性、记忆门控与自治模式。任一环节可以返回结果并停止后续处理。链定义见 [writepipe](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/writepipe.py#L1082-L1130>)。

自动记忆使用另一个已存在的入口：`mdcg_remember(gated=true)`。因此，检查写入缺陷必须区分显式写入与自动记忆。宿主侧调用约定见 [MdcgClient](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/src/lib/mdcg_client.ts#L14-L37>)。

### 5.3 检索

默认融合召回包含六条路径：词法、条件桶、实体、图扩展、因果链和时间。因果链与时间路径需要相应的数据或查询条件。代码见 [search_rrf](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/mdcos.py#L1804-L1844>)。

排名采用倒数排名融合（RRF）：

```text
score(d) = Σ_path weight(path) / (RRF_K + rank_path(d))
```

每条路径先产生自己的排名，再由融合方式组合。可选的资格终排剔除或降权候选。检索评分和资格判断是两个步骤。定义见 [融合与资格终排](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/mdcos.py#L1845-L1859>)。

### 5.4 状态与时间

节点可以保存属性，但属性本身不足以说明变更过程。状态事件台账记录主体、槽位、旧值、新值、序号和证据。台账只追加。定义见 [状态事件](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/state_events.py#L2-L22>)。

槽位现值从事件台账回放得到。撤回事件使值失效，后续带值事件可以恢复槽位。查询不保存第二份现值。回放契约见 [状态槽位投影](<https://github.com/FuRongJun-1999/dsh-memory/blob/e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9/md_cg/state_slots.py#L2-L39>)。

这与事件溯源的工程模式对应：保留变更事实，再由事实计算当前视图。主体、槽位、时间区间和撤回语义因此是本次查错的重点。
