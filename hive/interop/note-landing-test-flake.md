# 缺陷与修正：落地环「一次测试红即终态」会永久丢弃已过复核的候选（并发抖动）

- 提出时间：2026-09-19 02:4x（环二第 540 轮）
- 处置：编外（本侧）自检 → 落地环加「失败重跑一次」守卫 → 回收被误标终态的候选 → 提交本说明
- 状态：待编外复核（Zero-Trust）。

## 1. 缺陷

`auto_land2` 在干净树跑组回归，**一次** `rc != 0` 就把该候选写成 `checksum-failed`（终态）并跳过。
但本环是并发环境：驱动与多条 lane 同时在创建 hive 作业，对 `hive/jobs` 目录敏感的测试会偶发红。

实测（2026-09-19，同一轮内两次）：

| 候选 | 失败测试 | 结果 |
| --- | --- | --- |
| `iter-predict-c1` | `md_cg.test_p15_scrub` | 被标 `TEST_FAIL`；随后重跑即绿并落地 |
| `iter-consistency-c1-fix-d1` | `md_cg.test_mr_m1` | 被标 `checksum-failed`（终态）→ **2 条已过独立复核 ACCEPT 的条件被永久丢弃** |

两者都是「先红后绿」的抖动，而非真实回归。

## 2. 修正（`C:\\Users\\FuRongJun\\.mdcg\\_coord\\auto_land2.py`）

1. 每组测试失败后**重跑一次**再判：两次都红才写 `checksum-failed`；
   日志区分 `attempt=1/2`。
2. 失败时把失败测试名写进台账备注（`校验和不通过：干净树上测试回归红（test_xxx）`），
   便于事后区分「真回归」与「抖动」。
3. 一次性回收：把历史上原因含「测试回归红」的 `checksum-failed` 行重置为 `offered` 重新入队。

## 3. 实测

- 回收 `iter-consistency-c1-fix-d1` → 02:47:25 `TEST ... rc=0 attempt=1` → 02:47:29 `LANDED +2`。
- 台账当前不再有 `checksum-failed` 行（`landed/stale/superseded/internal-verified` 四态）。
- 同轮 `CORE have 2353→2364`、`gap 169→158`。

## 4. 边界

- 重跑只有一次：真回归（例如注释插入导致语法/行为变化）仍会被正确拦下并标失败，不会因为重试而放行。
- 该守卫只影响「落地判据的执行」，不改变判据本身（内部独立复核 ACCEPT ∧ 零删除 ∧ 干净树回归绿）。
