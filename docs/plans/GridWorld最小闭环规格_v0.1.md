# GridWorld 最小闭环规格 v0.1

> 目的：回应外部评审两轮共识——系统最大缺口是「行动/环境落地」：预测→行动→世界变化→预测误差→模型更新的闭环不存在。缺口矩阵 `docs/theory/理论_机制_代码_实验_缺口矩阵_v0.1.md:51`（#25 三端口架构）已文档声明输出端口，但**专属具身场景测试**仍留白。本文件设计一个最小 Grid World 闭环实验，把「预测→行动→观测→误差→回灌→模型更新」焊成一条可跑通、可度量、可审计的链。
>
> **本文件是规格**：启动实现须使用者批准；本文不改任何代码。
>
> 诚实边界先行：自建玩具环境（确定性/全观测/可枚举/单目标）证据强度受限（GPT 评审已声明）——本实验证明的是**闭环机制存在且收敛**，不是「世界模型能力证明」（§8）。

---

## 1. 可复用资产清单（调研结论）

闭环所需零件仓内**全部已存在**，缺口只在「动作/环境」一段（§6）。逐条核对过的接口：

| 资产 | 位置 | 签名（核对过） | 闭环角色 |
|---|---|---|---|
| 每动作候选枚举 | `md_cg/predict.py:226` | `branch_candidates(cg, node_id, semantic=True) -> [{node_id, confidence, source, relation_type, condition}]` | **动作选择器**：当前状态节点出边枚举，`condition` 字段承载动作 |
| 多步路线预测 | `md_cg/predict.py:541` | `routes(cg, start_id=None, blindspot_id=None, horizon=3, max_branches=5, sort="composite", limit=0, semantic=True)` | 多步预测面（M3 规划评测）；route 含 `path/confidence/uncertainty_bound/score` |
| 预测反馈回灌 | `md_cg/predict.py:678` | `feedback(cg, predicted_node_id, actual_node_id=None, hit=None, note="", actor="predict", sync_self=True, channel=None)` | **模型更新落点**：hit→指向边置信度 +0.05（`_boost_incoming` `:599`）；miss→`add_rejected` 负记忆；`sync_self=True` 自动刷自我状态卡 |
| 命中率动态死区 | `md_cg/predict.py:655` | `dynamic_hit_threshold(cg, limit=200)`；常量 `MIN_SAMPLES=50`（`:40`）、`BASE_HIT_RATE=0.40`（`:41`）、`EDGE_BOOST=0.05`（`:43`）、`PRIOR_STRENGTH=20`（`:48`） | 自我校准：样本<50 不触发反思；threshold=max(BASE, mean−2σ) |
| 通道贝叶斯 | `md_cg/predict.py:319` / `:364` | `beta_posterior(hits, prior_k=20, base=0.40)`；`channel_posterior(cg, channel=None, limit=200)` | 可信度后验（置信度≠可信度）；`channel="gridworld"` 通道分离 |
| 预测统计 | `md_cg/predict.py:888` | `stats(cg, limit=20)` → `{calls, routes_generated, feedback_samples, hit_rate, beta, dynamic, recent}` | 指标读数口 |
| 盲区五态闭环 | `md_cg/predict.py:790` | `learn_blindspots(cg, blindspot_id=None, limit=8, horizon=3, max_branches=5, apply=False, actor="insight")`；五态 `unknowable/no_anchor/unresolved/carried/resolved`（`:797-801`）；`apply=True` 落 `gap_hint`（幂等，`:765`） | 元认知闭环：失败区域→待补线索；`_learn.jsonl` 留痕 |
| 因果可达验证 | `md_cg/predict.py:922` | `causal_path(cg, a_id, b_id, max_depth=5)` | M1 冒烟：验证播种图因果连通性 |
| 探索提案 | `md_cg/autonomy.py:95` | `proposals(cg, window=200, limit=3, enforce_gain=True)`；评分 `=W_D2·Σ\|d2\|+W_BLINDSPOT·BLINDSPOT+W_DEFER·DEFER`（权重 `:34`），score≤0 不提案 | 探索信号源；**只读 `_reflection.jsonl`**（缺口 G4） |
| 探索闭环 | `md_cg/autonomy.py:158` | `explore(cg, apply=False, limit=3, window=200, actor="autonomy", bypass_gain=False)`；P-T-40 四保护（`gain_gate` `:51`） | 元认知面：提案→五态验证→回写；`_explore.jsonl` 留痕 |
| 反思留痕 | `md_cg/mdcg.py:1472` | `MdCG.reflect(query, results, user_feedback=None)` → 记录 `{t, query, d_prev, d_curr, d_delta, d2, states, n_results, feedback}`（`:1487-1497`） | d2/BLINDSPOT 信号产生点，proposals 唯一输入 |
| 检索（带资格态） | `md_cg/mdcg.py:1247` | `MdCG.search(query, layer=None, k=20, context=None, min_results=1, record=True, include_neg=True, judge=True, pools=None, session=None)` | reflect 的 results 来源；`judge=True` 产出 qualification |
| 认知图构造 | `md_cg/mdcg.py:477` | `MdCG(root, autoflush=64)` | 实验用独立临时 root，不碰生产库 |
| 自我状态刷新 | `md_cg/self_state.py:438` | `refresh(cg, subject="self:lingshu", window=20, ..., actor="self_state", force=False, strict=False, session=None)`（幂等 fingerprint `:208`，版本链 `_self_state.jsonl`） | 指标④读数源；`snapshot` `:184` |
| 自我预测面 | `md_cg/self_state.py:235` | `_prediction_face(cg)` → `{hit_rate, beta_mean, beta_ci95, threshold, reflect, ece}` | 自我可靠性指标直读 |
| 元认知观测面 | `md_cg/metacognition.py:123` / `:248` / `:167` | `trace(cg, window=50)`、`blindspots(cg, limit=20, window=200)`、`calibration(cg, max_scan=2000)` | 情绪面/ECE 旁证 |
| mdcos 面板 | `md_cg/mdcos.py:2282` / `:2292` / `:2303` / `:1912-1924` | `predict_routes(...)`、`predict_feedback(predicted_node_id, actual_node_id=None, hit=None, note="", actor="predict", sync_self=True)`、`predict_stats(...)`、`insight(action="explore"/"learn")` | 高层入口；predict_feedback **无 channel 参数**（缺口 G5） |
| 输出端口对照 | `md_cg/sustain.py:230` / `:297` | `mutual_watch(cg, peer, *, restart_cmd=None, d=None, interval, restart_cooldown, fresh_timeout, poll=0.5, spawner=None)` | #25 既有最小具身形态；本实验是其**环境侧**补充，不替换 |

**账本同构约定**：既有 append-only jsonl——`_prediction.jsonl`（`md_cg/predict.py:62`）、`_learn.jsonl`（`:724`）、`_explore.jsonl`（`md_cg/autonomy.py:36`）、`_reflection.jsonl`（`md_cg/metacognition.py:105`）、`_self_state.jsonl`（`md_cg/self_state.py:74`）。统一形态：`type`/`t`/`actor` 前置字段 + `append_jsonl` 失败不阻塞（如 `md_cg/predict.py:86-90`）。本实验新增 **`_gridworld.jsonl`** 同构留痕（§5）。

---

## 2. 环境接口（零依赖，纯 python stdlib）

对齐零依赖纪律（`md_cg/predict.py:23` 同款声明）。建议形态 `md_cg/gridworld.py`（另案，本文只定接口）：

```python
class GridWorldEnv:
    """最小确定性网格世界：W×H（默认 5×5），单 agent 单目标，静态障碍。"""

    def __init__(self, width=5, height=5, start, goal,
                 obstacles=frozenset(), seed=None): ...
    def reset(self) -> str:
        """回起点，episode+1，返回初始 state_id（"gw_s_x_y"）。"""
    def actions(self, state_id) -> tuple:
        """合法动作：("up","down","left","right") 剔除出界项。"""
    def transition(self, state_id, action) -> str:
        """纯函数：确定性转移，可离线全量枚举。"""
    def step(self, state_id, action) -> tuple:
        """执行 → (next_state_id, reward, done)。"""
```

确定性规则（全部可机器断言，M1 验收项）：

| 规则 | 定义 |
|---|---|
| 确定性转移 | 同一 `(s, a)` 永远映射同一 `s'`（`transition` 纯函数，无随机项） |
| 碰撞 | 目标格是墙（出界）或障碍 → **原地不动**（可学的条件规则，非非法动作） |
| 奖励 | 到达 goal +1，其余 0；无折扣、无中间奖励 |
| 终止 | `done = (next_state_id == goal_id)` |
| 观测 | **全观测**：观测=状态本身，不做部分可观测（诚实边界内，§8） |

---

## 3. 状态 ↔ 认知图编码

世界模型落在认知图的「状态节点 + 动作条件边」，是 `branch_candidates` 的原生数据形态，**零改动**对接：

| 编码项 | 规格 | 依据 |
|---|---|---|
| 状态节点 id | `gw_s_<x>_<y>` | `_slug` 惯例（`md_cg/self_state.py:95`） |
| 层 | **必须 `knowledge`** | `_SAFE_LAYERS=("knowledge","contextual","structural")`（`md_cg/predict.py:592`）——hit 分支 `_boost_incoming`（`:615`）只改这三层，其他层**静默不改边**，模型更新闭环失效（缺口 G2） |
| 正文 | CCG 五行齐全：`# 功能名：格(x,y)` / `# 生效条件：…` / `# 执行：…` / `# 子功能：…` / `# 不适用条件：…` | `_is_settled`（`md_cg/predict.py:739-757`）判「知识层+五要素」为 resolved——五态闭环才能出 `resolved` 终态 |
| 边 | `edges=[{"target": s_next, "relation_type": "causal", "condition": "动作:上", "confidence": 0.5}]` | `CAUSAL_BRANCH_TYPES=("causal","sequential")`（`:50`）；`condition` 经 `chain.edge_condition` 透传进候选（`:239`）——**动作信息沿既有通道流动，无需新字段** |
| 初始置信度 | 0.5（无先验声明；上限 1.0 封顶，`:623`） | 诚实：播种即「未经验证」 |
| 标签 | `tags=["gridworld", "gw_pos:<x>_<y>"]` | 检索/审计隔离面 |
| 频道约定 | `feedback(..., channel="gridworld")` | `channel_posterior` 按面分层（`:364-375`），与既有通道零混淆 |

---

## 4. 闭环管线（observe→predict→execute→error→feedback→learn）

| # | 步骤 | 对接（签名见 §1） | 说明 |
|---|---|---|---|
| 1 | observe | `env.reset()` / `env.step()` → `state_id` | 全观测 |
| 2 | 候选动作 | `predict.branch_candidates(cg, state_id, semantic=False)` | **`semantic=False`**：玩具环境边即全集，关闭语义诱导防伪因果门噪声（D-002 门 `:169` 无增益） |
| 3 | 预测 | 首候选=预测终态 `predicted_node_id`；多步面（M3）：`predict_routes(start_id=state_id, horizon=3)` | 候选的 `condition` 即动作 |
| 4 | 决策+执行 | 解码 `condition`→`a`；`next_state, reward, done = env.step(state_id, a)` | 无候选（未播种邻域）→ ε-greedy uniform 探索（M2 固定 ε=0.2 占位；与 `gain_gate` 的探索资格协同属 M3 可选） |
| 5 | 误差计算 | `hit = (predicted_node_id == actual_next_node_id)` | **显式传 hit**，不依赖 feedback 内部 `pred==act` 字符串判定（`:693-694`；缺口 G3） |
| 6 | 误差回灌 | `predict.feedback(cg, predicted_node_id, actual_next_node_id, hit=hit, note=f"ep{e}/s{t}", actor="gridworld", channel="gridworld")` | hit→边置信度+0.05（**模型更新**）；miss→`add_rejected`（负证据）；`sync_self=True` 刷自我卡 |
| 7 | 反思留痕（必选步） | `results, _ = cg.search(状态描述, k=4)`；`cg.reflect(f"gw:ep{e}:{state_id}", results)` | 产 d2/states 信号——proposals 唯一输入（缺口 G4） |
| 8 | 元认知闭环（每 episode 末） | `predict.learn_blindspots(cg, apply=True)`；或 `autonomy.explore(cg, apply=True, limit=3)` | 失败区域→五态终判→`gap_hint`；`_explore.jsonl` outcomes 供下轮 `gain_gate` |
| 9 | 自我面（每 episode 末） | `self_state.refresh(cg, actor="gridworld")` | 幂等（fingerprint 不变跳过）；版本链留痕 |
| 10 | 留痕 | `_gridworld.jsonl`（§5） | 实验主账本 |

语义对应评审闭环：**observe(1)→predict(2-3)→execute(4)→世界变化→prediction error(5)→feedback(6)→模型更新（边置信度/负记忆）→下轮预测改变**。元认知支线（7-8）与自我支线（9）复用既有链路。

---

## 5. 审计留痕（`_gridworld.jsonl`）

```jsonc
// step（每步一条）
{"type": "step", "t": 0.0, "actor": "gridworld",
 "episode": 3, "step": 7, "state": "gw_s_1_2", "action": "up",
 "predicted": "gw_s_1_3", "actual": "gw_s_1_3", "hit": true,
 "reward": 0, "done": false, "n_candidates": 4, "channel": "gridworld"}
// episode_end（每 episode 一条）
{"type": "episode_end", "t": 0.0, "episode": 3, "steps": 18, "hits": 14,
 "reached_goal": true, "hit_rate": 0.7778, "n_rejected_new": 2,
 "edge_conf_sum": 41.35, "actor": "gridworld"}
```

同构纪律：`type`/`t`/`actor` 前置（对齐 `_explore.jsonl` 形态 `md_cg/autonomy.py:199-205`）；append 失败不阻塞；指标全部可从 `_gridworld.jsonl` + `predict.stats` + `self_state.snapshot` 重算（白箱可审计）。

---

## 6. 识别出的对接缺口

调研发现的真缺口（规格层裁定，均**不改既有代码**）：

| # | 缺口 | 取证 | 规格裁定 |
|---|---|---|---|
| G1 | **动作概念缺位**：predict 全链只认「节点+边」，无动作空间抽象；`routes` 是图内路径生成器不是动作选择器 | `md_cg/predict.py:477-520`（DFS 无动作参数） | 以「边 `condition` 字段承载动作」编码（§3）；选择器=branch_candidates 首候选解码。动作沿既有 `condition` 通道流动，零改动 |
| G2 | **层硬约束**：hit 分支 `_boost_incoming` 只改 `_SAFE_LAYERS` 三层，其余层静默不改边 | `md_cg/predict.py:592`、`:615` | 状态节点强制落 `knowledge` 层（§3）；M1 冒烟加断言：feedback 后边置信度确有上升 |
| G3 | hit 隐式判定是 `pred==act` 字符串相等 | `md_cg/predict.py:693-694` | 实验显式传 `hit=True/False`，不依赖字符串约定 |
| G4 | **盲区信号依赖 reflect**：`autonomy.proposals` 只读 `_reflection.jsonl`，闭环不调 `reflect()` 则零信号、五态闭环空转（「信号在记录、无人在听」防复发） | `md_cg/autonomy.py:107` | 管线第 7 步为**必选步**（§4），每步 search(record=True, judge=True)+reflect |
| G5 | **mdcos.predict_feedback 不透传 channel**（库层有，封装层无） | `md_cg/mdcos.py:2292-2293` vs `md_cg/predict.py:679` | 驱动器**直调库层** `predict.feedback(..., channel="gridworld")`；既有封装不动（面选择，非缺陷） |
| G6 | `dynamic_hit_threshold` 样本<50 不触发反思（MIN_SAMPLES=50） | `md_cg/predict.py:40`、`:662-665` | 不构成障碍：主判据读 `beta_posterior`（无门槛）；反思触发是滞后旁证非主判据 |

---

## 7. 验证指标与分阶段里程碑

### 7.1 验证指标（四类，全部可机器断言）

| 指标 | 定义 | 读数口 | 判据（M3） |
|---|---|---|---|
| ①预测误差随轮次下降 | 逐步误差=1−hit；episode 级=1−hit_rate；后验均值=β 后验 mean | `_gridworld.jsonl`、`predict.stats()["beta"]["all"]`（`md_cg/predict.py:888-901`） | 后 20% episodes 的后验均值 > 前 20% + 0.2；逐 episode 命中率回归斜率>0（误差单调下降，允许噪声） |
| ②策略稳定性 | 重复同状态同动作率；每 episode 步数（steps-to-goal） | `_gridworld.jsonl` step 聚合 | 确定性环境下最后 3 episodes 同状态动作一致率 ≥0.95；steps-to-goal 后段 < 前段 |
| ③条件模型变化 | 边置信度漂移 Σ\|Δconf\|；rejected 新增数；命中边集合收敛 | cg edges 直读 + `n_rejected_new` | EDGE_BOOST 累积集中在通往 goal 的边上；最后 N episodes rejected 新增=0、无新增命中边（模型停止变化=收敛） |
| ④自我可靠性 | hit_rate / beta_mean / beta_ci95 / reflect（脱离死区）随 episode 演化 | `self_state.snapshot()["prediction"]`（`md_cg/self_state.py:235`） | beta_ci95 收窄；reflect 由 True→False（≥50 样本且过动态阈值）；`refresh` 版本链可回放 |

对照组（M3 必配）：**未学习基线**——同环境同 episode 数，但不跑 feedback（边置信度恒 0.5）；两臂 hit rate 必须显著分离，否则①不成立。

### 7.2 里程碑（每阶段独立验收）

| 阶段 | 内容 | 验收判据（可独立断言） |
|---|---|---|
| **M1 环境冒烟** | GridWorldEnv 确定性断言（同一 `(s,a)` 复跑 100 次同 `s'`）；9~25 格状态节点+动作条件边播种到临时 root；`branch_candidates` 枚举无异常；`routes()` 返回 `status=ok` 且路径连续；`causal_path(start, goal)` 连通；G2 断言（feedback 后边置信度上升） | 环境与播种层全绿；**不涉及预测质量** |
| **M2 闭环跑通** | ≥10 episodes 端到端无异常；六账本（`_gridworld`/`_prediction`/`_reflection`/`_learn`/`_explore`/`_self_state`）均非空；至少一次到达 goal；`reflect` 留痕含 d2 | 闭环不死、账本可审计、管线第 7 步有产出 |
| **M3 指标显著** | 四类指标判据全过 + 对照组分离 | 数字入实验结论文档，判定「闭环机制验证通过」（非「世界模型能力证明」，§8） |

---

## 8. 诚实边界

- **玩具环境证据强度受限**（GPT 评审已声明，本规格如实继承）：确定性/全观测/可枚举/单目标——结论只支持「预测→行动→误差→更新→行为改善」的**闭环机制存在且收敛**；不支持「世界模型能力」主张（泛化、部分可观测、非平稳、组合泛化）。对外表述必须用前一句口径。
- **模型更新是确定性账本式更新**：EDGE_BOOST=0.05 线性增量（`md_cg/predict.py:43`），非参数梯度学习；D-006 口径=工程初值非协议承诺。
- **ε-greedy 是占位策略**：M2 固定 ε=0.2；探索的「资格裁决」（σ(Gain) 增益门槛）与本环 ε 的协同只列 M3 可选项，不作为 M2 验收面。
- **单目标奖励无折扣**：不引入 RL 复杂度；本实验不与任何 RL 基线比名次，只做自我前后对照。

---

## 9. 边界与实现前置

- 本文件是**规格**；启动实现须使用者批准。实现建议形态：`md_cg/gridworld.py`（env+runner）+ `md_cg/test_gridworld.py`（确定性断言+闭环端到端+指标断言），临时 root（`MdCG(root=<tempdir>)`，`md_cg/mdcg.py:477`），不碰生产库。
- 实现后归档按第 16 条纪律：只记核心修改（内容/原因/位置/验证结论），账本与断言数字入结论。

