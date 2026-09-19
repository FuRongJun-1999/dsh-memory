# 落地记录：S6 一致性交叉验证 + 「检索重接」六阶段里程碑

- 候选分支：`task/iter-retr-s6`（tip `6625ee8`，1 个提交）
- 落地方式：**fast-forward 推送**（+1 提交，**0 删除**）；落地后 origin/main：`6625ee8`；标签：`core-retr-s6`
- 判据：内部独立复核 **首轮 ACCEPT** ∧ 零删除 ∧ 干净树回归绿（`md_cg` 组 94/94，3 跳过）

## 1. S6 做了什么（契约 §3 S6）

只读复用 `md_cg/crosscheck.py` 的「赛道 × 来源执照」判定，对 **top-k** 逐个给出：

- `track`（`classify_track`：science / humanities / undetermined）；
- `basis`（frontmatter `verification_basis`）与 `licensed`（`basis_licensed`：理科要可复现依据、文科要一致性依据）；
- `claims`（`extract_claims` 条数）。

**点名规则**：仅当「赛道已定 ∧ 声明了依据 ∧ 依据不被该赛道许可」时进 `flagged`（赛道未定不点名 → 信息不足放行）。
**绝不进主排序**：`scored`/`out` 次序一律不动（有「结果与默认关逐条一致」断言）。
**只读保证**：不产生 `_crosscheck.jsonl`（有断言）。
审计：`meta.gates.s6 = {checked, by_track, flagged, rows}`。开关 `MDCG_GATE_S6_CROSSCHECK` 默认 0、显式 =1。

测试：`md_cg.test_retr_s6` **12/12**（默认关/子开关未设/审计齐备/排序不变/点名规则三态/只读/幂等两式/关→开→关等价）。

## 2. 「检索重接」六阶段总览（对应外部审计五条偏差）

| 阶段 | 内容 | 落地标签 | 关键开关 | 探针 |
| --- | --- | --- | --- | --- |
| S1 | 大域先验收敛候选集（节点侧新增 `big_domain` + 回填器） | `core-retr-s1` | `MDCG_GATE_S1_DOMAIN` | test_retr_s1 |
| S2 | `condition_space` 前置门控（不匹配不进候选） | `core-retr-s1` | `MDCG_GATE_S2_COND` | test_retr_s1 |
| S3 | 沿 `edges` 双向扩散激活（独立 `TIER_SPREAD` 层） | `core-retr-s3` | `MDCG_GATE_S3_SPREAD` | test_retr_s3 |
| S4 | 五层激活优先级（anchor/self 先；加成非过滤） | `core-retr-s4` | `MDCG_GATE_S4_LAYER` | test_retr_s4 |
| S5 | 负记忆抑制信号（相关正候选 ×(1-λ)） | `core-retr-s5` | `MDCG_GATE_S5_NEG` | test_retr_s5 |
| S6 | 一致性交叉验证（只读 verdict 摘要） | `core-retr-s6` | `MDCG_GATE_S6_CROSSCHECK` | test_retr_s6 |

**统一纪律**：总开关 `MDCG_RETRIEVAL_PIPELINE` 默认 0；子开关默认 0、**必须显式 =1**；
开关关时 `results`/`meta` 与改动前等价（逐条断言）；每阶段独立分支、独立复核、零删除、回归绿后
fast-forward 落地并打 `core-*` 标签（`core-retr-s1/s3/s4/s5/s6`）。

**独立复核累计 16 轮**（S1/S2 八轮、S3 三轮、S4 一轮、S5 两轮、S6 一轮），其中 12 轮 REJECT 全部为真问题
（默认口径被改、门控读错字段、回填未持久化、测试自证、超范围改动、配置未生效…），逐条修复后 ACCEPT。

## 3. 如何启用与测量（运维口径）

```
set MDCG_RETRIEVAL_PIPELINE=1            # 总开关
set MDCG_GATE_S1_DOMAIN=1                # 逐阶段显式开（S1..S6 各自一个变量）
python -X utf8 -m md_cg.backfill_bigdomain --root <库根> --dry-run   # 先预览存量补齐量
python -X utf8 -m md_cg.backfill_bigdomain --root <库根>             # 真补齐（幂等；总开关关时是 no-op）
```
测量口径：对比开关关/开时 `search()` 的 `meta.scanned`（读取节点数）与 `meta.gates`
（`s1.dropped`、`s2.dropped`、`s3.expanded`、`s4.boosts`、`s5.suppressed`、`s6.flagged`）。

## 3b. 真实库实测（只读，2026-09-19）

真实库 = `D:/Program Files/2_ai/AEIS/data/mdcg`，**12,149 个节点**（1.38 GB，未做任何写入）：

| 观测 | 数值 |
| --- | --- |
| 已有 `big_domain` 的节点 | **0** → 启用 S1 前必须先回填（回填写库，属使用者裁决） |
| 域标签覆盖率（240 节点抽样，二值分类器） | 已标注 ≈58.3%，**无域信号 ≈41.7%** |
| S1 实际保留面（域内 ∪ 未标注，召回安全口径） | 工程类查询 ≈**43.3%**（5,264 节点）、语言类 ≈**52.1%**（6,327）、数学类 ≈**50.8%**（6,175） |

**结论（如实）**：S1 单阶段在真实库上的即时收敛约 **2 倍**（不是审计里「1/14」的理想值）——
因为 42% 节点没有任何域关键词、按召回安全必须留在兜底池。要拿到审计预期的量级，
下一步应是**提升域标签覆盖率**（加权/模糊分类器、或写入侧更强的域推断），而非放松兜底规则。
S2（条件门控）、S3（图扩散只碰邻域）、S5（负记忆抑制）各自在域内再收敛，端到端收益需在
「启用 + 回填」后按 `meta.scanned` 实测。

## 4. 回退

任一阶段关掉对应子开关（或总开关）即回原行为；整链回退：`git revert` 各 `core-retr-*` 对应提交。
