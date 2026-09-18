# 多端 harness 通信契约 v0.1

**目标**：验证不卡死在任何单一端。任何具备"读共享目录 + 回执"能力的端都可充当验证方；无端认领时由内部独立复核通道顶上，两者并账。

## 1 投放（我方 → 任何验证端）
- **位置**：`hive/interop/<iter_id>/request.json`（与 `note-unit-review.json` 并列）
- **必填字段**：`kind=verify-request`、`iter_id`、`branch`、`candidate_commit`、`claim_signal`、`claim_min`、`created_ts`
- **认领信号（二选一即可）**：
  1. 写 `hive/interop/<iter_id>/picked.json`（`{"verify_id": "<iter_id>", "picked_ts": <unix>}`）；
  2. 在 `hive/interop/_receipts_ledger.tsv` 追加一条引用该 `iter_id` 的回执（历史端走的就是这条）。

## 2 认领时限与升级（机械执行）
- 由 `_coord/multiport.py sweep` 每 300s 执行一次：
  - 有认领信号 → `claimed`（记录 `claimed_via`）；
  - 超 `claim_min`（默认 10 分钟）仍无 → `escalated`，**自动转入内部独立复核通道**（`md_cg.units` 自足式作业）；
- 状态落在 `hive/interop/_dispatch_ledger.tsv`（列：ts/iter/branch/commit/status/claim_by/claimed_via/note）。

## 3 双通道并账
- 同一候选可同时对外投放、对内复核；两侧 verdict 都写入台账；
- **外部回执到达即补验并追加记录**，不因内部通道已过而丢弃外部证据。

## 4 水位与事实来源
- 事实来源优先级：`note-receipt-*.json` → `_receipts_ledger.tsv` → 各端自报 state/heartbeat；
- 水位推进以**台账 + 认领记录**为准，不以任一端的口头报告为准。

## 5 硬约束
- 验证方**不得**改写被验证仓的源码与测试；jobs 写入属通道例外；
- 我方**不得**用内部通道伪装外部 PASS：内部通道结论在台账中标注 `via=internal`，与外部 `via=<provider>` 区分。
