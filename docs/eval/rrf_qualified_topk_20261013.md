# 按资格补足精确 Top-K，以得分上界安全停止

2026-10-13

原 judge_ranking 只审查前 max(2k,10) 个融合候选：前 12 个被拒绝时，第 13 个安全节点永远到不了 k=1 结果；前排 DEFER 被折半时，也可能漏掉后面的 ACCEPT。现在维护资格通过后的最佳 K 项，只有后续候选的最高可能得分连 ID 并列规则都无法胜过第 K 项时才停止。

在既有融合池内做有界精确选择。ACCEPT 保持原分，DEFER 沿用 ×0.5，REJECT/BLINDSPOT 排除；上界 max(fs,fs×0.5) 配合原始降序和 ID 顺序证明提前停止。没有放宽任何资格判据。

## 同输入实际结果

| 观察项 | 未改原始代码 | 本项修复 |
|---|---|---|
| 12 次 REJECT 后的安全第 13 项，k=1 | 空结果 | zsafe |
| 前 35 项 ACCEPT、k=3：judge 调用数 | 10 | 3 |
| 新守卫测试方法 | 3 通过 / 5 失败 | 8 通过 / 0 失败 |

原始代码冻结于 `efa2ee2ba4986c02ad204f05a99712c226d0023d`；最新共同基线为 `4169c5bd`，包含其后独立的 CI 前置修复 `cbf43fe289c9e81cd9beb14cd77ca902e4058535`。本项测量代码提交 `c9d7e153d89ac17daf6faa54412ed90cc5787c59`，逐文件 SHA256 在证据 ZIP 的 identity.json，分别记录运行时 CRLF 字节与 LF 归一源码，便于跨平台检出核对。五个核心分支不互相包含对方的修复。

Windows Python 3.12.10、Linux / WSL Python 3.13.12：各 **8 项守卫通过 / 0 失败 / 0 异常 / 0 SKIP**；各 **4 项定点变异被指定断言捕获**，异常和跳过均为 0，源码未改写；恢复后 8 项再绿。这里按测试方法与变异计数，不把子断言或恢复轮重复相加。

```bash
python -X utf8 tests/test_rrf_qualified_topk.py
python -X utf8 tests/test_rrf_qualified_topk.py --mutate
```

## 未改代码复现与反面对照

从本 PR 检出目录执行（守卫用临时合成库，不读在役库）：

```bash
python -m zipfile -e docs/eval/rrf_qualified_topk_20261013/raw-evidence.zip proof
git worktree add --detach ../baseline efa2ee2ba4986c02ad204f05a99712c226d0023d
python -X utf8 proof/repro_baseline.py --baseline ../baseline --fixed . --module md_cg.test_rrf_qualified_topk
# 预期退出 1：8 个测试中 5 个测试方法失败，0 异常 / 0 SKIP。
```

此命令只把新守卫加入原始包的测试搜索路径，生产模块仍全部来自未改的 baseline。没有靠禁用新开关或注入错误冒充旧代码。

| 单点变异 | 必红断言 | Windows / Linux 实际结果 |
|---|---|---|
| restore fixed oversampling window | `Guards.test_refill_after_twelve_rejections` | 1 项断言失败 / 0 异常 / 0 SKIP |
| stop when unqualified ranks fill k | `Guards.test_defer_penalty_does_not_hide_later_accept` | 1 项断言失败 / 0 异常 / 0 SKIP |
| remove bound early exit | `Guards.test_early_bound_avoids_unnecessary_judgments` | 1 项断言失败 / 0 异常 / 0 SKIP |
| remove defer discount | `Guards.test_defer_penalty_does_not_hide_later_accept` | 1 项断言失败 / 0 异常 / 0 SKIP |

变异只在内存编译副本替换目标函数/方法。每项要求恰好执行指定测试、至少一项 AssertionError、0 导入或运行异常、0 SKIP，并核对源文件 SHA256 恢复不变。

```bash
python -X utf8 proof/native_pair_probe.py --repo ../baseline --slug topk
python -X utf8 proof/native_pair_probe.py --repo . --slug topk
```

## 相关回归与 CI

相关回归 **11/11 个模块最终通过**，逐条命令与 stdout/stderr/退出码见 ZIP 的 regressions.json。

- `python -X utf8 -m md_cg.test_issue130_rrf_rank_credibility`
- `python -X utf8 -m md_cg.test_issue197_rank_credibility_property`
- `python -X utf8 -m md_cg.test_bm25`
- `python -X utf8 -m md_cg.test_c8_search_rrf_gates`
- `python -X utf8 -m md_cg.test_recall_face_guards`
- `python -X utf8 -m md_cg.test_neg_condition_hits`
- `python -X utf8 -m md_cg.test_boundary_hit`
- `python -X utf8 -m md_cg.test_policy_required_ccg`
- `python -X utf8 -m md_cg.test_p33_ccg_wiring`
- `python -X utf8 -m md_cg.test_role_views`
- `python -X utf8 -m md_cg.test_validity_filter`

共用 CI 前置：[PR #233](https://github.com/FuRongJun-1999/dsh-memory/pull/233)。它恢复干净 runner 的 Node 构建及两处 Linux 夹具，原安全阈值、断言与发布件判据不变；生态路径补丁与 #188 相同，本项不重复认领成果。完整 Ubuntu 全量 CI 以本 PR 当前 head 的 Actions 记录为准，不把上述定向回归称作全量 CI。

## 独立范围与评审依据

与唯一投票 PR 根因不同：本件只修资格过滤之后的排名窗口；不改变投票或条件语义。关联 #232 的语义判据设计仍由另一工作项处理。

建议按 expert 评审的依据：需要同时满足资格降权后的精确排名、候选补足和提前终止证明，覆盖 REJECT/DEFER/ACCEPT 混合以及独立全扫描 oracle；不能用单纯扩倍窗口保证正确性。最终难度、影响与结算均由维护者裁定；不凭代码行数或测试数量自行定档。

## 限制

精确性只覆盖已生成并按既有路径上限截断的融合池，不等于全库全局 Top-K。全部被拒时必须审查整个池；既有显式 early_stop_threshold 快路继续按原语义运行。未修正 #232 讨论的条件语义判定。本项无真实私域数据、外部模型调用或正式榜单成绩；不改变删除/权限/密钥接口。

[原始公开证据 ZIP](rrf_qualified_topk_20261013/raw-evidence.zip)（主机路径归一，断言与数值保留；CRC 与逐项 SHA256 已核对）。证据目录用自身 .npmignore 排除，不增加 npm 分发体积。代码与合成 fixtures 按本仓 MIT 许可。
