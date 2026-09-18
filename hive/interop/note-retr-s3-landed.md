# 落地记录：S3 沿 edges 图扩散激活（独立 TIER_SPREAD 层）

- 候选分支：`task/iter-retr-s3`（tip `407b090`，3 个提交）
- 落地方式：**fast-forward 推送**（base == origin/main == `c3e93da`；+3 提交，**0 删除**）
- 落地后 origin/main：`407b090`；里程碑标签：`core-retr-s3`
- 落地判据：内部独立复核 ACCEPT ∧ 零删除 ∧ 干净树回归绿（`md_cg` 组 91/91，3 跳过）∧ 逐候选可回退提交

## 1. 做了什么（契约 §3 S3）

`edges` 此前只被写入、检索从不使用（审计偏差 1）。本阶段：

1. **扩散**：从词法命中节点沿 `edges` **双向**扩散 `MDCG_SPREAD_HOPS` 跳（默认 2），
   激活值 = `MDCG_SPREAD_DECAY`^跳数（默认 0.5）；邻居分数取
   `max(词法分, 激活值 × MDCG_SPREAD_GAIN)`（默认 0.2）。
2. **独立层**：扩散候选自成一个 tier `T2b_spread_activation`（`TIER_SPREAD`），便于审计与归因。
3. **不读文件**：邻接表只取索引快照的 `edges/target`（扩散本身零文件读）。
4. **硬约束**：扩散**只能**在已通过 S1/S2 门控的候选集合内进行——未过门控的节点不会被拉回。
5. **召回安全**：命中/扩散不足 `min_results` 时自然落回原 T2/T3 路径（行为不劣化）。

## 2. 开关（显式启用）

| 开关 | 默认 | 说明 |
| --- | --- | --- |
| `MDCG_RETRIEVAL_PIPELINE` | 0 | 总开关 |
| `MDCG_GATE_S3_SPREAD` | **0** | **必须显式 =1**（与 S1/S2 的「未设=开」有意不同：S3 会新增候选并引入新 tier，不能让「只开 S1/S2」的用户静默多出一层） |
| `MDCG_SPREAD_HOPS` / `MDCG_SPREAD_DECAY` / `MDCG_SPREAD_GAIN` | 2 / 0.5 / 0.2 | 扩散半径/衰减/激活增益 |

审计面：`meta.gates.s3 = {seeds, expanded, hops, decay, gain, valid}`（无邻接时为 `{seeds, expanded:0, reason:"no_edges"}`）。

## 3. 独立复核（3 轮，前 2 轮 REJECT 均为真问题）

| 轮 | 问题 | 修法 |
| --- | --- | --- |
| 1 | S3 子开关未设时默认被启用 → 开了总开关就多出一层结果 | 改为显式 `== "1"` |
| 2 | 我顺手把 S1/S2 的子开关语义也改成默认关 = **超出 S3 范围**（改动了已落地行为）；且缺幂等断言 | 回退 S1/S2 语义为落地版；补「重复检索 / 索引重建后同口径」幂等断言 |
| 3 | —— | **ACCEPT** |

## 4. 测试证据

- `python -X utf8 -m md_cg.test_retr_s3` → **17 断言全通过**（默认等价/子开关未设不生效/种子与扩散计数/tier/衰减有序/未连通节点不引入/S2 拦掉的邻居不得扩散引入/无 edges 回退/幂等两式/关→开→关等价）。
- `python -X utf8 -m md_cg.test_retr_s1` → **46 断言全通过**（S1/S2 未受影响）。
- `python -X utf8 scripts/run_tests.py md_cg --jobs 4` → **91/91 通过**（3 跳过）。

## 5. 回退

关掉 `MDCG_GATE_S3_SPREAD`（或总开关）即回原行为；或 `git revert` 本范围 3 个提交（`3e55bcb..407b090`）。
