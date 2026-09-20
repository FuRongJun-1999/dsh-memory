# D_task / D_meta 工程化方案 v0.2

> 目的：将智能论3.4 信息差公理中的 `D_task/D_meta` 分离从理论声明推进到可执行工程，
> 回应缺口矩阵 #31/#33（🔴 未投影 / 无对象）。
>
> **v0.2 说明（2026-09-20）**：本版是 v0.1 的定点修订版——v0.1 原文逐字保留（凡修订处标注
> `✅ v0.2 修订`），本文件为**唯一真源**；已实现部分以本文件与代码为准，v0.1 仅作历史留存。

## 0-A. v0.2 变更单（先读本节）

### A. 三处原文偏差的处置（依据=代码条件证据，非偏好）

| # | v0.1 原文 | 偏差为何 | v0.2 处置 |
|---|-----------|----------|-----------|
| a | §2.1 `unmodeled_growth` 数据源 = `_neg_coverage` 命中 + `unresolved` 增长率 + `blindspots` 项数 | `_neg_coverage` 是 **query-relative**（需现场 query+results），当"全局增长率"用属语义错位；且全库正文 `_read` 会拖垮热路径 | **改为库侧 query 无关口径**：`0.5×存量饱和率(rejected+unresolved / 100) + 0.5×反思窗口未消化率(BLINDSPOT+DEFER)`；query-relative 的 `_neg_coverage` 命中留在 `reflect`（彼处有现场） |
| b | §2.5 要求把 `outcomes[bid]` 扩展为 dict（terminal/d_meta_before/d_meta_after） | 会同时打破 `test_gain_gate ⑤b` 的终态字符串守卫与 `autonomy.gain_gate` 的 `str(oc[bid])` 停滞集比对——dict 字串永不属停滞集 → **σ 恒 1.0，增益门槛静默报废** | **`outcomes[bid]` 契约不动**（终态字符串）；D_meta 维度**并列新增** `meta_outcomes`（before/prev_before/delta/proxy/enabled） |
| c | §2.3 第五维 `meta_pressure` 与 §4.1"不合成单一数值"并存 | v0.1 未给 `meta_pressure` 的构造式，若取三代理加权即违反 DEV-002a | **只允许取单一指定代理**（`PREDICTION_META_PROXY`，缺省 `unmodeled_growth`），**禁三代理加权合成**；代码内以 `d_meta.pressure(vec, key)` 强制该访问模式 |

### B. 行为变更单（默认是否生效，逐条可回退）

| 变更 | 默认 | 回退开关 | 影响面 |
|------|------|----------|--------|
| `mdcg.reflect` 新增 `d_meta` / `d_meta_delta` 两键 | **生效** | `MDCG_D_META=0`（三值恒 0.0、delta=None） | 反思留痕字段（既有键不动） |
| `autonomy.proposals` 叠加 D_meta 排序加分 | **生效（W_DMETA=0.1）** | `MDCG_D_META=0` → 加分退化 0 | 只进 `sort_score` 与 `reason`；`score`/资格/σ 不变 |
| `autonomy.explore` 新增 `meta_outcomes` | **生效** | `MDCG_D_META=0` → 记录 `enabled:false` | 并列新增，`outcomes` 值类型不变 |
| `autonomy.gain_gate` 新增「停滞+压力扩大」冷却分支 | **生效** | 缺 `meta_outcomes` 键即不触发（旧留痕兼容） | 仅"冷却已过且压力仍扩大"这一新条件下改判 σ=0 |
| `predict.score_route` 第五维 `meta_pressure` | **关闭（opt-in）** | `PREDICTION_META_DIM=0`（默认） | 默认不落键、不改 composite、SORT_KEYS 不扩张 |
| `self_state` 预测面新增 `d_meta_trend` + 状态卡一行 | **生效** | `MDCG_D_META=0` → 回落 0.0 | 状态卡指纹随内容变化（仍为日志确定性函数） |
| MCP `cg(op=metacognition, action="d_meta")` | **生效（只读）** | — | 新增只读观测面 |

### C. 开关名统一（消除 v0.1 内两套命名冲突）

- `MDCG_D_META`：D_meta **计算总闸**，默认开启；置 `0/false/off/no` 显式回退。
- `W_DMETA = 0.1`：`autonomy.proposals` **排序加分**权重（§2.4 优先于 §3 阶段表的"权重 0"）。
- `PREDICTION_META_DIM` / `PREDICTION_META_PROXY`：`predict.score_route` **第五维**数值权重（默认 0）与所取单一代理。

### D. 阶段状态（本轮交付 1–5；6 交使用者）

阶段 1–5 已交付（模块 + 5 处接入 + 测试 + 文档 + 矩阵状态）；**阶段 6（生产库开启 + 48h 轨迹审计）不在本轮执行**，
开启动作与观测交使用者（`MDCG_D_META` 默认已开启，生产库如需显式关闭：置 `0`）。

## 0. 理论约束（必须先遵守）

| 条款 | 内容 | 工程含义 |
|------|------|----------|
| DEV-002 | `D_task` = 图上操作性距离；`D_meta` = 未被建模的现实总量 | 两者对象不同，不能数值打通 |
| DEV-002a | `D_task` 可分化多个工程化身，对象同一、数值不互换 | 可新增 `D_meta` 投影链路，但不能并入 `D_task` 计算公式 |
| 增定律 | `d(D_meta)/dt ≥ 0`（结构性论证） | `D_meta` 不能做「缩小」运算，只能观测其压力趋势 |
| 统一变量边界 | 审美/创造/非任务探索不由 `ΔD·σ(Gain)` 定价 | D_meta 只做排序加分，不改变资格筛选 |

## 1. 现有代码的半成品盘点

| 能力 | 位置 | 现状 |
|------|------|------|
| D_task 一阶数值 | `md_cg/mdcg.py:_compute_d` | `D = max(0, 1 − ACCEPT/候选数)`，已有口径声明 |
| D 时间序列 | `md_cg/mdcg.py:reflect` | `_reflection.jsonl` 落 `d_prev/d_curr/d_delta/d2` |
| D 二阶差分 | `md_cg/mdcg.py:reflect` | `d2 = (d_curr−d_prev) − (d_prev−_d_prev2())` |
| 预测闭环 | `md_cg/predict.py:feedback` | `_prediction.jsonl` + `_boost_incoming` + `dynamic_hit_threshold` |
| 通道贝叶斯 | `md_cg/predict.py:beta_posterior` | 已可产出 `mean/ci95`，但不回流 D |
| 信息差提案 | `md_cg/autonomy.py:proposals` | 按 `|d2| + BLINDSPOT×2 + DEFER×1` 评分 |
| 增益筛选 | `md_cg/autonomy.py:gain_gate` | 读 `_explore.jsonl` outcomes 实现值 |
| 探索闭环 | `md_cg/autonomy.py:explore` | 提案 → `predict.learn_blindspots` 五态 → 回写 gap_hint |

**核心缺口**：
- `D_meta` 完全无对象（缺口矩阵 #33）。
- `U_behavior` 零对应（行为偏差只存文本无量化）。
- `U_prediction_error` 不回流 D（预测误差只进 self 校准面）。
- 情绪 `d²D/dt²` 在实库恒 0（D 序列无变化能力）。
- `D_task/D_meta` 分离未投影到任何数据结构或 API。

## 2. 推荐方案：D_meta 结构性投影（不引入新数值）

### 2.1 新增 `md_cg/d_meta.py`（D_meta 代理指标模块）

**定位**：D_meta 不做数值等价，只产出「边界压力向量」`{events_pressure, unmodeled_growth, boundary_violation_rate}`，三个字段各自有可观测代理。

| D_meta 代理 | 理论对应 | 工程代理变量（v0.1 原文） | 数据源（v0.1 原文） |
|-------------|----------|--------------|--------|
| `events_pressure` | 未被建模的现实总量 | 单位时间内新增未消化事件数（recent_events + 未路由 hits） | `_explore.jsonl` outcomes + `recent_events` |
| `unmodeled_growth` | 未建模信号持续增长 | `_neg_coverage` 命中数 + `unresolved` 层增长率 + `blindspots` 项数 | `_neg_coverage` + `metacognition.blindspots` |
| `boundary_violation_rate` | 边界违反速率 | `non_applicable_conditions` 命中数 / 查询数 + `REJECT` 率 | `_candidates` + `judge_qualification` 结果 |

**关键设计**：三个代理各自返回 `[0, 1]` 归一化值，**不合成单一 D_meta 数值**，以向量形式供上层消费。这样遵守「D_meta 不参与数值计算」的硬约束，同时给系统提供「外部压力有多大」的可观测信号。

**✅ v0.2 修订（已实现口径，逐条可复算；对应变更单 A.a）**：

| 代理 | 实现口径（`md_cg/d_meta.py`） | 归一化 |
|------|------------------------------|--------|
| `events_pressure` | `(recent 尾窗条数 + explore 尾窗条数) / (2×window)` | 天然 `[0,1]`（尾窗各自 ≤ window） |
| `unmodeled_growth` | `0.5×min(1, stock/100) + 0.5×((BLINDSPOT+DEFER)/全部资格态)`；`stock` = 索引中 `rejected`/`unresolved` 两层条目数（**零正文 IO**） | clamp `[0,1]` |
| `boundary_violation_rate` | `(REJECT+BLINDSPOT) / 全部资格态`（反思窗口 `states` 分布） | `[0,1]` |

- 尾窗读盘用 `d_meta.tail_jsonl(path, window)`（反向分块，读盘量 ≈ O(window)，不扫全文件）。
- 进程内缓存 key = `(root, 反思条数, 层存量, recent 条数, explore 条数, window)`；无后台线程、无网络、无嵌入调用。
- 全部数据来自**已落盘留痕与索引**；`blindspots 项数` 的等价可观测量取反思窗口的 `BLINDSPOT` 计数（同一分布，避免重复全扫描）。
- **叶子只读模块纪律**：不 import `mdcg` / `mdcos`（防循环依赖）；`metacognition` 惰性导入；**无任何写路径**。

### 2.2 修改 `mdcg.reflect`：双 D 同步落盘

在现有 `reflection` 记录里新增 `d_meta` 三字段：

```python
# mdcg.py reflect() 内新增
reflection["d_meta"] = d_meta   # {events_pressure, unmodeled_growth, boundary_violation_rate}
reflection["d_meta_delta"] = ...
```

`d_meta` 由 `d_meta.compute(self, query, results)` 纯函数产出，不改变 `_compute_d` 的既有语义。

**✅ v0.2 修订（实现细节）**：`d_meta` 只落**三代理三键**（`PROXY_KEYS`）；`d_meta_delta = d_meta.diff(上一条反思的 d_meta, 本次向量)`，**首条为 `None`**；`MDCG_D_META=0` 时三代理恒 0.0 且 `d_meta_delta=None`（**回退留痕，不是缺键**）。`_compute_d` 与其 docstring **一字未动**。

### 2.3 修改 `predict.score_route`：四维变五维（opt-in）

现有 D-004 四维：`trend / boundary / verification / balance`。  
新增第五维 `meta_pressure`（来自 d_meta 向量），权重初始为 0（默认关闭），由 `PREDICTION_META_DIM=1` 显式启用。

```python
W_META = getattr(env, "PREDICTION_META_DIM", 0.0)  # 0=关闭，默认零变更
composite += W_META * meta_pressure
```

**✅ v0.2 修订**：环境变量读的是**权重值**（`PREDICTION_META_DIM=0.2` → `W_META=0.2`；`1` 亦合法），非法值按 0 处理（不炸导入）；第五维取值 = `d_meta.pressure(d_meta.compute(cg), PREDICTION_META_PROXY)`，**单一代理、禁加权合成**（变更单 A.c）。关闭时**不落 `meta_pressure` 键、`weights` 与 `SORT_KEYS` 均不扩张**（默认返回与四维时代逐字节一致）；开启时 `catalog().weights` 同步扩张（防文档漂移）。导入期读一次环境变量。

### 2.4 修改 `autonomy.proposals`：ΔD_task × σ(Gain) 保留，D_meta 只做排序加分

现有评分：`score = W_D2*|d2| + W_BLINDSPOT*blindspot + W_DEFER*defer`。  
新增 D_meta 加分项（非定价，只做排序微调）：

```python
# autonomy.py proposals() 内
meta = d_meta.compute(cg, query, results) if query else {}
meta_score = meta.get("unmodeled_growth", 0.0) * W_DMETA  # W_DMETA 初始 0.1
a["score"] = round(score + meta_score, 4)
```

**边界**：D_meta 加分只影响排序，不影响 `gain_gate` 的 σ 资格筛选（后者只读 outcomes 实现值）。

**✅ v0.2 修订（实现形态与口径诚实标注）**：

- `a["score"]` **不再被改写**（仍是纯 ΔD 定价器）；加分落在**新键** `a["d_meta_bonus"]` 与 `a["sort_score"] = score + bonus`，排序键改用 `(-sort_score, -last_t)`。理由：`score` 是定价器口径，回归断言与下游都按它比对，混合会把"定价"与"排序"两个语义压在一个字段上。
- 加分**每轮一次**（循环外 `mv = d_meta.compute(cg, window)`）并在循环内复用，**禁止 N× 扫描**；`reason` 追加 `D_meta 排序加分 +x（proxy=y，三代理不合成；不改资格/σ(Gain)）`，同时保留 `d2` / `BLINDSPOT` 既有子串。
- **资格判据先于加分**：`score <= 0 → continue` 保持在加分之前（无信号不提案，D_meta 不构成资格）。
- **当前口径下排序不变**（诚实标注）：代理取库侧 query 无关量，同轮各提案加分**同值** → 排序与旧版逐位一致；区分性须待 query-relative 口径（`_neg_coverage`）在 `reflect` 侧落盘后才生效——**不提前编造区分性**。

### 2.5 修改 `autonomy.gain_gate`：实现值增加 D_meta 维度

当前 outcomes 只记 terminal（`carried/unresolved/...`），扩展为：

```python
outcomes = {
    bid: {
        "terminal": step["terminal"],
        "d_meta_before": step.get("d_meta_before"),
        "d_meta_after": step.get("d_meta_after"),
    }
}
```

`gain_gate` 读取时新增 `d_meta_delta = after - before`，若连续多轮 `d_meta_delta > 0` 且 terminal 停滞，则 `sigma = 0`（D_meta 持续扩大 → 无增益，冷却）。

**✅ v0.2 修订（契约保护，对应变更单 A.b）**：**上述 dict 化被否决**——`outcomes[bid]` 保持**终态字符串**（`test_gain_gate ⑤b` 的五态守卫 + `gain_gate` 的停滞集比对都依赖它；dict 化会让 σ 静默恒 1.0）。D_meta 维度**并列**落在 `explore` 留痕新键：

```python
"meta_outcomes": {"before": {...三代理...}, "prev_before": {...} | None,
                  "delta": diff(prev_before, before), "proxy": ..., "enabled": ...}
```

`delta` 是**跨轮压力增量**（本轮 before − 上一条 explore 的 before，含上轮 apply 效果），`gain_gate` 取与该 bid 相关轮次的 `delta[proxy]` 求均值：

- 均值 > 0 且终态全停滞且**冷却已过** → `sigma = 0`（`DEFER_EXHAUSTED_UNDER_PRESSURE`，`meta_rising=True`）：压力扩大而终态停滞 = 重复探索不再产生增益，**冷却期延长**。
- 均值 ≤ 0 或 `meta_outcomes` 键缺失 → **不触发**（既有 ①–④ 行为逐字不变，旧留痕天然兼容）。

### 2.6 修改 `predict.feedback`：sync_self 侧增加 D_meta 审计

`self_state.refresh` 当前已刷新 `prediction_hit_rate` 等字段，新增 `d_meta_trend`（最近 N 轮 `d_meta.unmodeled_growth` 均值），供自我模型观测「边界压力趋势」。

**✅ v0.2 修订（落点澄清）**：实现落在 `self_state._prediction_face` 的 `d_meta_trend`（**由 `self_state.refresh` 聚合进状态卡**，故 `predict.feedback → sync_self → refresh` 链路自然带着它），`predict.feedback` 本体不改。`_d_meta_trend(cg, window=20)` 是**反思日志的确定性函数**（无留痕时回落当前单代理值，不可用为 `None`）；`_render` 状态卡新增一行「D_meta：边界压力趋势」（人可读观测面）。

## 3. 最小侵入实现路线图（不改既有默认行为）

| 阶段 | 文件 | 改动 | 默认行为 | 验证 |
|------|------|------|----------|------|
| 1 | `md_cg/d_meta.py`（新） | 三代理纯函数 + `compute()` | 零变更 | `test_d_meta.py` 20 断言 |
| 2 | `mdcg.py` reflect | 落 `d_meta/d_meta_delta` | 零变更（新增字段） | `test_p12` 回归 |
| 3 | `predict.py` score_route | 第五维 meta_pressure（权重 0） | 零变更 | `test_predict_beta` 回归 |
| 4 | `autonomy.py` proposals | D_meta 加分（权重 0） | 零变更 | `test_autonomy` 回归 |
| 5 | `autonomy.py` gain_gate | outcomes 扩展 d_meta 维度 | 零变更 | `test_gain_gate` 回归 |
| 6 | 生产库运行 | `MDCG_D_META=1` 开启 | 默认关闭 | 48h 轨迹审计 |

**✅ v0.2 修订（实际交付与偏差）**：

- 阶段 3/4 的「权重 0」与 §2.4「W_DMETA=0.1」冲突 → 按 **§2.4 优先**：`W_DMETA=0.1` **默认生效**；`PREDICTION_META_DIM` 仍为 **opt-in（默认 0）**。
- 阶段 5 的「outcomes 扩展」改为「并列 `meta_outcomes`」（见 §2.5 修订）。
- 阶段 6 的开关语义：**默认开启**（`MDCG_D_META` 未设即生效），置 `0` 显式回退——与 v0.1「默认关闭」相反，理由：本轮只交付结构性投影且全部可回退，默认关闭会使"交付即不可观测"。
- **实际交付状态（2026-09-20）**：阶段 1–5 完成；`test_d_meta.py` 实际 **66 断言**（>20）；全组 `md_cg` 回归 **113/113**、`gain_gate` 21/21、`autonomy` 14/14；阶段 6 未执行。

## 4. 关键诚实边界（必须写进代码注释/文档）

1. **D_meta 不合成单一数值**：它是三指标向量，任何把三指标加权为单一 `D_meta` 数值的企图都违反 DEV-002a。
2. **D_meta 不参与 D_task 的计算**：`_compute_d` 不动，`D_task` 口径零变更。
3. **D_meta 代理是诚实估计**：`events_pressure` 只计「进入系统但未被消化的事件」，不是「世界真实未发生事件」——后者不可观测。
4. **统一变量边界**：审美/创造/非任务探索的 `bypass_gain=True` 已存在，D_meta 只做排序加分不改变资格筛选，不侵犯边界条款。
5. **✅ v0.2 新增｜第五维不得加权合成**：`meta_pressure` 只允许取**单一指定代理**（`d_meta.pressure(vec, key)` 为该访问模式的唯一入口）；三代理加权即违反 DEV-002a。
6. **✅ v0.2 新增｜区分性诚实标注**：`W_DMETA` 加分在当前库侧 query 无关口径下**同轮同值**，排序不产生区分；区分性依赖 query-relative 口径（`_neg_coverage`）未来在 `reflect` 侧落盘，**现阶段不宣称**。
7. **✅ v0.2 新增｜增定律只被观测不被运算**：模块不含任何「缩小 D_meta」的运算路径；`d_meta_delta > 0` 仅用于冷却判定（不因压力上升去"优化"压力）。

## 5. 关联

- 缺口矩阵：`docs/theory/理论_机制_代码_实验_缺口矩阵_v0.1.md` #31/#33
- 理论真源：`docs/智能论3.4.md` §2.7.0 DEV-002/DEV-002a、§2.9.3.1
- 既有桥接：`dnorm_bridge_and_boundary_clause`（#32/#39 收口）
- 依赖能力：`predict.py` / `autonomy.py` / `mdcg.py` reflect
- **✅ v0.2 新增｜实现与验证入口**：
  - 模块：`md_cg/d_meta.py`（`compute` / `pressure` / `diff` / `tail_jsonl` / `catalog`）
  - 观测面：`cg(op=metacognition, action="d_meta")`、`mdcos.metacognition_d_meta(window)`
  - 自检：`python -m md_cg.test_d_meta`（66 断言）；回归：`python scripts/run_tests.py md_cg`
