# 落地记录：S1b 细口径桶收敛（query 侧推断候选桶）

- 候选分支：`task/iter-retr-s1b`（tip `9811848`，3 个提交）
- 落地方式：**fast-forward 推送**（+3 提交，**0 删除**）；落地后 origin/main：`9811848`；标签：`core-retr-s1b`
- 判据：内部独立复核 **3 轮**（前 2 轮 REJECT → 修复 → ACCEPT）∧ 零删除 ∧ 干净树回归绿（`md_cg` 组 95/95，3 跳过）

## 1. 为什么做（实测依据，见 docs/hive/检索收敛实测与S1b设计_v0.1.md）

| 口径 | 覆盖率 | 收敛强度 |
| --- | --- | --- |
| 粗：14 大域（S1，已落地） | 已标注 58.3% | 域内 ∪ 未标注 ≈ 44–52%（**≈2 倍**） |
| **细：路由桶（S1b）** | **91.1% 节点有非 orphan 桶** | **期望扫描 2.1%**（1,066 桶，最大桶 10.1%） |

`search()` 本就有 T0/T1 桶路，但**只在调用方传 `context` 时可用**；普通 `search(q)` 无 context 只能全表扫描。
S1b 就是把这层细口径收敛在 query 侧自己推断出来。

## 2. 做了什么

1. `routing.bucket_key_readable()`：桶目录名 → 可读键（`cond_感知系统_d94e90d2` → `感知系统`；`orphan`/空 → `''`），与 `bucket_dir` 互逆（丢哈希段）。
2. `search()` 内 S1b 阶段（**只读索引，不读文件**）：
   - 桶规模表 `bucket → 节点数`；
   - query 扩展词 × 桶可读键的 `domain_similarity`，取 top-k（`MDCG_BUCKET_TOPK` 默认 3，`MDCG_BUCKET_MIN_SIM` 默认 0.34）；
   - 候选 = 命中桶 ∪ **orphan/无桶节点**（召回安全）；命中不足 `min_results` → **回退全量**。
3. 审计 `meta.gates.s1b = {keys, sims, in, out, sizes[, would_keep, fallback]}`；开关 `MDCG_GATE_S1B_BUCKET` 默认 0、显式 =1。

## 3. 独立复核（3 轮，前 2 轮均为真问题）

| 轮 | 问题 | 修法 |
| --- | --- | --- |
| 1 | ①复核认为 S1b 被嵌进 S4 块（仅 S4 开时才生效）；②测试含自证式断言 `g.get("in")==g.get("in")` | ①开关与参数**就地定义**在阶段正上方（消除嵌套误读），并**加测试**「S4 显式关闭时 S1b 仍生效」直接证伪该判断；②改为与「S1b 关」同参数对照逐条比较 |
| 2 | ①`_kept < min_results` 回退分支未被测试覆盖；②回退时 `gates.s1b.out` 记 `len(_kept)` 与真实输出不一致（审计误导） | ①新增专属小库用例（两桶各 1 节点、无 orphan、`min_results=3`）覆盖回退；②回退时 `out` 记**真实输出规模**，另存 `would_keep` |
| 3 | —— | **ACCEPT** |

## 4. 测试证据

`python -X utf8 -m md_cg.test_retr_s1b` → **23 断言全通过**：key 解析三态 / 写入侧确实落桶 / 默认关无 `gates` /
子开关未设不生效 / 推断出正确桶 / 收敛 `out<in` / **不引入任何新节点（⊆ 默认关结果集）** / **orphan 恒留兜底** /
异桶被丢 / 无键命中不收敛且与关闭时结果一致 / **S4 显式关闭时 S1b 仍生效** / topk=0 关闭 / topk=2 取两桶 /
min_sim=1.0 部分匹配不入选 / min_sim=0.34 部分匹配入选 / **候选不足回退全量（含审计口径）** / 幂等两式 / 关→开→关等价。
另：`scripts/run_tests.py md_cg --jobs 4` → **95/95**（3 跳过）。

## 5. 回退

关掉 `MDCG_GATE_S1B_BUCKET`（或总开关）即回原行为；或 `git revert a1540f9 13391b7 9811848`。

## 6. 进度

S1 ✅ → S2 ✅（`core-retr-s1`）→ S3 ✅（`core-retr-s3`）→ S4 ✅（`core-retr-s4`）→ S5 ✅（`core-retr-s5`）
→ S6 ✅（`core-retr-s6`）→ **S1b 细口径收敛 ✅（`core-retr-s1b`）**。
下一步候选：把 S1/S1b 的实测收益在**真实库**上落成端到端数字（需你批准回填/启用），或继续按需扩展收敛口径。
