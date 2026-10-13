# RRF 同一路径按节点唯一投票，避免图收敛重复加权

2026-10-13

多个图种子收敛或边重复时，同一节点在同一路 graph 中占据多个名次，每个名次都贡献一票，还能挤满路径候选上限。现在先按原排序保留每个节点的最强记录，再计算可信度、截断、排名与投票；来自不同路径的真实多票仍保留。

稳定地以节点 ID 去重每一路排序结果，保留最强出现。RRF 仍沿用 1/(K+rank)、原路径权重、阈值与融合方式，路径之间不互相去重。

## 同输入实际结果

| 观察项 | 未改原始代码 | 本项修复 |
|---|---|---|
| 实际 BM25+graph 收敛例：linked 的 graph 票数 | 8 | 1 |
| linked 的 RRF 分数 | 0.124188 | 0.016393 |
| 新守卫测试方法 | 1 通过 / 7 失败 | 8 通过 / 0 失败 |

原始代码冻结于 `efa2ee2ba4986c02ad204f05a99712c226d0023d`；最新共同基线为 `4169c5bd`，包含其后独立的 CI 前置修复 `cbf43fe289c9e81cd9beb14cd77ca902e4058535`。本项测量代码提交 `66285ac3974c9f534314f62667a6e30d0f24be45`，逐文件 SHA256 在证据 ZIP 的 identity.json，分别记录运行时 CRLF 字节与 LF 归一源码，便于跨平台检出核对。五个核心分支不互相包含对方的修复。

Windows Python 3.12.10、Linux / WSL Python 3.13.12：各 **8 项守卫通过 / 0 失败 / 0 异常 / 0 SKIP**；各 **3 项定点变异被指定断言捕获**，异常和跳过均为 0，源码未改写；恢复后 8 项再绿。这里按测试方法与变异计数，不把子断言或恢复轮重复相加。

```bash
python -X utf8 tests/test_rrf_unique_votes.py
python -X utf8 tests/test_rrf_unique_votes.py --mutate
```

## 未改代码复现与反面对照

从本 PR 检出目录执行（守卫用临时合成库，不读在役库）：

```bash
python -m zipfile -e docs/eval/rrf_unique_votes_20261013/raw-evidence.zip proof
git worktree add --detach ../baseline efa2ee2ba4986c02ad204f05a99712c226d0023d
python -X utf8 proof/repro_baseline.py --baseline ../baseline --fixed . --module md_cg.test_rrf_unique_votes
# 预期退出 1：8 个测试中 7 个测试方法失败，0 异常 / 0 SKIP。
```

此命令只把新守卫加入原始包的测试搜索路径，生产模块仍全部来自未改的 baseline。没有靠禁用新开关或注入错误冒充旧代码。

| 单点变异 | 必红断言 | Windows / Linux 实际结果 |
|---|---|---|
| restore per-copy votes | `Guards.test_native_convergence_one_vote` | 1 项断言失败 / 0 异常 / 0 SKIP |
| raw rows leak into recall-only cap | `Guards.test_recall_only_cap_is_unique` | 1 项断言失败 / 0 异常 / 0 SKIP |
| deduplicate globally instead of per path | `Guards.test_distinct_paths_still_each_vote` | 1 项断言失败 / 0 异常 / 0 SKIP |

变异只在内存编译副本替换目标函数/方法。每项要求恰好执行指定测试、至少一项 AssertionError、0 导入或运行异常、0 SKIP，并核对源文件 SHA256 恢复不变。

```bash
python -X utf8 proof/native_pair_probe.py --repo ../baseline --slug votes
python -X utf8 proof/native_pair_probe.py --repo . --slug votes
```

初跑 10/11 模块通过，Rust parity 因 release 二进制未构建失败；随后实际执行 `cargo build --release --manifest-path rust/Cargo.toml` 并重跑 `python -X utf8 -m md_cg.test_rank_parity_score_mode`，40 条断言通过 / 0 失败 / 0 SKIP。保留初次失败与修复依赖后的日志，最终 11/11 个模块通过。

## 相关回归与 CI

相关回归 **11/11 个模块最终通过**，逐条命令与 stdout/stderr/退出码见 ZIP 的 regressions.json。

- `python -X utf8 -m md_cg.test_issue130_rrf_rank_credibility`
- `python -X utf8 -m md_cg.test_issue197_rank_credibility_property`
- `python -X utf8 -m md_cg.test_rrf_candidates`
- `python -X utf8 -m md_cg.test_bm25`
- `python -X utf8 -m md_cg.test_chain_best_first`
- `python -X utf8 -m md_cg.test_chain_read_isolate`
- `python -X utf8 -m md_cg.test_c8_search_rrf_gates`
- `python -X utf8 -m md_cg.test_rrf_graph_seed_cache`
- `python -X utf8 -m md_cg.test_role_views`
- `python -X utf8 -m md_cg.test_validity_filter`
- `python -X utf8 -m md_cg.test_rank_parity_score_mode`

共用 CI 前置：[PR #233](https://github.com/FuRongJun-1999/dsh-memory/pull/233)。它恢复干净 runner 的 Node 构建及两处 Linux 夹具，原安全阈值、断言与发布件判据不变；生态路径补丁与 #188 相同，本项不重复认领成果。完整 Ubuntu 全量 CI 以本 PR 当前 head 的 Actions 记录为准，不把上述定向回归称作全量 CI。

## 独立范围与评审依据

与 #130/#197 名次可信度分开：它们判定路径分数是否有判别力；本件判定同一路同一节点能投几票。与 qualified-topk 分开：本件不改资格判定或终排窗口。

建议按 expert 评审的依据：修正检索融合的投票单位，同时保持候选上限、recall-only、max/sum 融合、不同路径独立性及原唯一候选排序；必须避免全局去重误删合法跨路证据。最终难度、影响与结算均由维护者裁定；不凭代码行数或测试数量自行定档。

## 限制

仍会生成原图路径中的重复项，修复发生在融合入口，不宣称图遍历成本已经消失。得分归一是正确性收益，不是公开数据上的准确率或榜单胜出；已因常量分而弃权的路径不产生本件的正票收益。本项无真实私域数据、外部模型调用或正式榜单成绩；不改变删除/权限/密钥接口。

[原始公开证据 ZIP](rrf_unique_votes_20261013/raw-evidence.zip)（主机路径归一，断言与数值保留；CRC 与逐项 SHA256 已核对）。证据目录用自身 .npmignore 排除，不增加 npm 分发体积。代码与合成 fixtures 按本仓 MIT 许可。
