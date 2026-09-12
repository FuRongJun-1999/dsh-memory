# 源码级架构审计 · GPT 批评逐条对照（可证伪清单）v1.0

> 目的：把第三方（GPT）对 dsh-memory 的 21 条评价逐条落到「代码有 / 半 / 无」的**可证伪**判定上，
> 替代 README 层判断。判定以仓库源码为准，README 与自评报告仅作参照。
>
> 审计方式：设计者视角（条件空间 + 白箱三问），检索核实 + 精读。
> 审计日期：2026-09-12｜被审版本：工作区 HEAD（v0.4.5 迭代中）
> **口径声明**：行号以本次审计时的工作区版本为准，仅供定位；符号名优先于行号。

---

## 0 审计结论速览

| 分类 | 条数 | 说明 |
|---|---:|---|
| GPT 判断**成立**且为真缺口 | 5 | 见 §3 |
| GPT 判断**部分成立**（机制在、闭环缺） | 3 | 见 §1、§4 |
| GPT 判断**误判**（源码可证伪） | 3 | 见 §2 |
| GPT 判断**成立但与项目自评一致**（非新发现） | 4 | 见 §1 |

**一句话**：GPT 的方向性判断大体正确，但有 3 处因**只读 README、未读源码**而误判——
其中最重要的一处是「建议加入 Prediction」，而本仓 `predict.py` **早已实现**完整预测引擎。

---

## 1 逐条对照表

| # | GPT 主张 | 代码落点 | 判定 | 证据 |
|---|---|---|---|---|
| 1 | 定位应是「AGI 记忆/认知架构实验平台」而非「已实现 AGI」 | `README.md` 自述 | **有**（与项目自述一致） | README 未宣称实现 AGI |
| 2 | 核心价值不是 KV，是 Node(conditions/subgraph/negative/execution) | `mdcos.py`、`cg` 节点模型 | **有** | 节点含 `conditions`/`subgraph`/`negative`/`execution`；条件级负路由进检索 |
| 3 | 认可「负记忆」（知道什么情况下不能用） | `md_cg/` 负记忆 + 冲突检测 | **有** | `rejected` 节点 + 条件级负路由 + 主动遗忘闸门 |
| 4 | 「知识飞轮」漂亮，但 Knowledge Evolution ≠ Learning | `refine.py` / `sustain.py` / `evolution.py` | **半**（成立） | 飞轮有闸门（`refine.py` `GATE_MIN_PASS_RATE=0.90`），`sustain.py` `auto_evolve=False` 显式**禁用自动固化**——是纪律选择，不是缺陷；但确实**缺**「预测误差→模型更新」这一环 |
| 5 | 「零 LLM 白箱」方向有价值 | `md_whitebox.py` / `whitebox_kb/` | **有** | 规则管线：条件识别→单元匹配→组合→自验证→固化，不依赖 LLM |
| 6 | 规则越多≠智能越强，需证明「出现新的可泛化能力」 | — | **有**（理论挑战） | 见 §3 缺口 5 |
| 7 | 元认知 7.5 分：机制 ≠ 能力，缺 calibrated self-model | `metacognition.py::calibration` | **半**（GPT 未读源码） | 已有 `expected vs actual accuracy` + `gap` + **ECE 公式** + 五档 verdict；缺的是「ECE 达标」与「回写自身」 |
| 8 | 世界模型 ≠ predictive world model（缺 S_t→A→S_{t+1}） | `stg.py`（纯只读关系/时间线/一致性查询） | **无**（GPT 判断正确） | 无写接口、无状态转移模拟；「世界模型」实为条件空间 + 结构化时空知识 |
| 9 | SELF Memory ≠ Self Model | `self_state.py`（薄自我 + 富索引） | **半**（本轮已推进） | 原为身份/状态卡；v1.0 本轮新增第九项「预测校准」，向 predictive self 迈出最小一步 |
| 10 | 安全设计给高分（权限/审计/tenant/payload-free/guardrail） | `security.py` / `protect.py` / `audit.py` / `signer.py` | **有** | 无凭据只读、写入门槛、密级、审计留痕 |
| 11 | Benchmark 值得肯定但不可照单全收（README 自陈局限） | `bench_locomo_zh*.py` / `bench_membench.py` | **有** | README 主动声明「只评检索命中，不评答案正确性，不能外推端到端」 |
| 12 | 作者自知「自评指标≠外部证明」 | `docs/AGI七维评分报告_md_cg_v2.0.md` + README §Gate | **有** | README §Gate 明确列 7 项未达标 |
| 13 | 缺点一：概念膨胀（每个热门概念一个模块） | — | **有**（成立） | 见 §3 缺口 4 |
| 14 | 缺点二：需要「失败实验」（1000 次任务 → 更新 → 是否变强） | — | **有**（成立） | 仅有机制 + 留痕，**无因果 A/B**；见 §3 缺口 5 |
| 15 | 缺点三：最需要「预测」，且预测须被未来事实验证 | **`predict.py`（D-001~D-006）** | **误判** | 见 §2 |
| 16 | 缺点四：需与 Mem0/Letta/GraphRAG 严格横评 | — | **有**（成立） | 见 §3 缺口 3 |

---

## 2 GPT 的三处事实误判（源码可证伪）

### 误判 1｜「把 Prediction 加进去」——**predict.py 早已实现**

GPT 将「加入 Prediction」列为「最重要的技术建议」，但仓库已有独立预测引擎：

| 能力 | 落点 | 说明 |
|---|---|---|
| D-001 局部路径预测 | `predict.py` | 基于认知图生成候选路径 |
| **D-002 伪因果过滤门** | `predict.py` | 过滤虚假因果，比 GPT 设想的更严谨 |
| 不确定性界 `uncertainty_bound` | `predict.py` | 预测自带不确定度 |
| 外推有效性 `extrapolation_validity` | `predict.py` | 判断预测是否超出可靠域 |
| T_pred 四维评分 | `predict.py` | 结构化预测打分 |
| 命中留痕 `_prediction.jsonl` | `predict.py` | 可审计、可回放 |
| **学习闭环 `learn_blindspots`** | `predict.py` | 盲区五态终态 honest |
| 动态阈值 `dynamic_hit_threshold` | `predict.py` | 命中率低于阈值 → `reflect=True` |

**结论**：GPT 建议的「保存 prediction_id / timestamp / conditions / probability /
prediction error」中的**前半段已存在**；真正缺的只有后半段——**误差回写 world/self**（见 §3 缺口 1，本轮已补 self 侧）。

### 误判 2｜「元认知还只是机制，没有 calibrated self-model」——**已有 ECE**

`metacognition.py::calibration` 已实现：
- `expected`（主观置信）× `actual`（证据核对）双轨；
- **ECE = Σ(证据占比 × |桶内实际 − 桶内自信|)**；
- 五档 verdict：`calibrated` / `overconfident` / `underconfident` / `insufficient_data`。

**结论**：缺的不是「校准机制」，而是「**ECE 达标**」（README §Gate：`T-TRUST` 需 ECE ≤ 0.15，当前 Lv2 封顶）。

### 误判 3｜引用「条件性 L4 → L5 路上」当作项目自身定位

仓库存在**两套并存标尺**：
- **七维评分标尺** → 判定 **L5 稳固段**（`docs/AGI七维评分报告_md_cg_v2.0.md`，综合 8.6）；
- **Gate / 外部行为门槛** → 写「条件性 L4 → L5 路上」（`README.md`）。

GPT 只引用了后者，据此推断「作者没敢宣布完成 L5」——**未看到前者**。两者口径不同，不可混用。

---

## 3 五项真缺口（与项目自身自评一致）

| # | 缺口 | 状态 | 严重度 |
|---|---|---|---|
| 1 | **预测误差未回写 self / world**：`predict.feedback` 原仅改边置信度 + 登记 rejected | **self 侧本轮已补**；world 侧无处可写（见 §5） | 高 |
| 2 | **世界模型无状态转移**：`stg.py` 只读，无 `S_t→A→S_{t+1}` 模拟 | 未补，需单独立项 | 高 |
| 3 | **无外部 baseline 横评**：自认「仅用于自评，不构成横评声明」 | 未补（方案见 `实验方案_学习闭环AB与横评_v1.0.md`） | 中 |
| 4 | **概念密度偏高**：GPT 建议砍 30% 概念、证因果 | 未动（与「抬最低维」策略等价） | 低 |
| 5 | **缺「记忆 → 提升」因果实验**：仅机制 + 留痕，无 A/B | 方案见 `实验方案_学习闭环AB与横评_v1.0.md` | 高 |
| 6 | **ECE 未达标**：`T-TRUST` Lv2 封顶，需 ≤ 0.15 | 长样本验证未完成 | 中 |

---

## 4 本轮已落地（v1.0）

| 改动 | 位置 | 验证 |
|---|---|---|
| 新增第九项自我信息「预测校准」（hit_rate/threshold/reflect/ECE） | `md_cg/self_state.py` | P16 通过 |
| `predict.feedback` → 回写自我模型（闭合「预测→事实→误差→自我更新」） | `md_cg/predict.py::feedback(sync_self=True)` | P17 通过 |
| 审计新增 `prediction_drift` 规则（自我模型是否跟上自身预测表现） | `md_cg/self_state.py::audit` | P16 M5 通过 |
| 透传 `sync_self`（MCP 可显式关闭闭环） | `md_cg/mdcos.py`、`md_cg/mcp_server.py` | P2MCP 通过 |

**验证汇总**：P16 51/51、P17 58/58、P45 30/30、P2MCP 63/63（202 项断言，0 失败）。

---

## 5 未落地与「不建议硬做」

- **world model 回写**：`stg.py` 是**纯只读**查询接口，没有状态转移语义，**无处可写**。
  硬塞预测字段会破坏其只读契约与一致性保证。正确做法是**单独立项**一个 predictive world model 模块，
  而不是在 `stg` 上打补丁。
- **砍 30% 概念**：与项目自身的「抬最低维」策略目标等价，但收益难量化、回归风险高，暂缓。

---

## 6 给第三方的复核入口

```text
python -m md_cg.test_p16_self_state   # 九项自我信息 + 预测校准面 + 审计
python -m md_cg.test_p17_predict      # 预测引擎 + 回写闭环
python -m md_cg.test_p45_session_identity
python -m md_cg.test_p2_mcp           # MCP 面
```
