# STG 时间索引改用平方根有序块，降低建表与批量删除代价

2026-10-13

既有 STG 时间维保留扁平升序列表，每次 timed 删除都搬移后续节点，按时间批量摘除为 O(N²)。现在用有序块与块最大值目录做两层二分；局部插删、分裂合并和四倍规模变化时重建，批量建表改为一次排序。session/layer 等既有 swap-pop 桶不改。

零第三方依赖的平方根分块。叶规模约 sqrt(N)，动态更新的局部与目录搬移为 O(sqrt(N)) 摊还；批量时间建表 O(N log N)。保留闭区间、重复时间、物理序回排、非有限时间分桶及 broken 回退。

## 同输入实际结果

| 观察项 | 未改原始代码 | 本项修复 |
|---|---|---|
| 新守卫测试方法 | 7 通过 / 1 失败 | 8 通过 / 0 失败 |

原始代码冻结于 `efa2ee2ba4986c02ad204f05a99712c226d0023d`；最新共同基线为 `4169c5bd`，包含其后独立的 CI 前置修复 `cbf43fe289c9e81cd9beb14cd77ca902e4058535`。本项测量代码提交 `84a7ef97d6736f9fe4df9ae69ec4d99f2377619d`，逐文件 SHA256 在证据 ZIP 的 identity.json，分别记录运行时 CRLF 字节与 LF 归一源码，便于跨平台检出核对。五个核心分支不互相包含对方的修复。

Windows Python 3.12.10、Linux / WSL Python 3.13.12：各 **8 项守卫通过 / 0 失败 / 0 异常 / 0 SKIP**；各 **5 项定点变异被指定断言捕获**，异常和跳过均为 0，源码未改写；恢复后 8 项再绿。这里按测试方法与变异计数，不把子断言或恢复轮重复相加。

```bash
python -X utf8 tests/test_stg_time_blocks.py
python -X utf8 tests/test_stg_time_blocks.py --mutate
```

## 未改代码复现与反面对照

从本 PR 检出目录执行（守卫用临时合成库，不读在役库）：

```bash
python -m zipfile -e docs/eval/stg_time_blocks_20261013/raw-evidence.zip proof
git worktree add --detach ../baseline efa2ee2ba4986c02ad204f05a99712c226d0023d
python -X utf8 proof/repro_baseline.py --baseline ../baseline --fixed . --module md_cg.test_stg_time_blocks
# 预期退出 1：8 个测试中 1 个测试方法失败，0 异常 / 0 SKIP。
```

此命令只把新守卫加入原始包的测试搜索路径，生产模块仍全部来自未改的 baseline。没有靠禁用新开关或注入错误冒充旧代码。

| 单点变异 | 必红断言 | Windows / Linux 实际结果 |
|---|---|---|
| lose bulk failure fallback | `Guards.test_nonfinite_and_untimed_still_partition` | 1 项断言失败 / 0 异常 / 0 SKIP |
| exclude upper endpoint | `Guards.test_inclusive_range_ties` | 1 项断言失败 / 0 异常 / 0 SKIP |
| retain deleted time pair | `Guards.test_empty_and_reinsert` | 1 项断言失败 / 0 异常 / 0 SKIP |
| reverse update time | `Guards.test_random_updates_match_sorted_oracle` | 1 项断言失败 / 0 异常 / 0 SKIP |
| drop time range filtering | `Guards.test_inclusive_range_ties` | 1 项断言失败 / 0 异常 / 0 SKIP |

变异只在内存编译副本替换目标函数/方法。每项要求恰好执行指定测试、至少一项 AssertionError、0 导入或运行异常、0 SKIP，并核对源文件 SHA256 恢复不变。



同一确定性合成数据，种子 1337 随机插入、种子 47 的 120 个双端包含窗口、逐时间删除全部 timed 节点。两臂各 3 个独立进程，次序交替，中位数：

| 节点数 | 原建表 ms | 新建表 ms | 原删除 ms | 新删除 ms | 原 120 查询 ms | 新 120 查询 ms |
|---|---:|---:|---:|---:|---:|---:|
| 10,000 | 34.82 | 19.41 | 21.41 | 18.58 | 0.314 | 0.368 |
| 40,000 | 328.21 | 85.47 | 198.62 | 104.70 | 0.579 | 0.763 |
| 160,000 | 4384.63 | 413.77 | 2223.37 | 577.08 | 0.860 | 1.219 |

每个运行的 timed_before 等于 N、删除后剩余 0、broken 为 false；全部窗口结果 SHA256 与独立排序 oracle 一致。建表包含原生分类，删除包含原生摘除；不把 fixture 生成耗时算进去。初轮有其他守卫进程活动的配对读数另存 `initial-benchmark.json`，最终轮无其他本地测试进程并跑。

```bash
python -X utf8 scripts/bench_stg_time_blocks.py --repo ../baseline --output baseline-bench.json
python -X utf8 scripts/bench_stg_time_blocks.py --repo . --output fixed-bench.json
python -X utf8 -m md_cg.test_stgidx_index_parity --branch-baseline
python -X utf8 proof/probe_bulk_fallback.py --repo .
```

已有 STG 守卫实跑：51 条原断言通过，17/17 原变异按各自预期失败数点名变红；原断言与失败数量均未降低。新守卫在旧实现仅 1 项结构断言红，属于数据结构能力增强，性能收益由配对基准证明。

发布前追加的损坏输入复核发现第一版批量排序把比较异常移出了 add() 的保护范围：混入不可比较的节点 ID 时原版标记 broken，第一版却抛 TypeError。已在 finish() 处保留原回退边界，新增第五项定点变异「丢掉 bulk 失败回退」确保断言必红。这是本方案审阅中发现并修正的遗漏，不另申报为上游缺陷。三版真实执行与源码 SHA256 见 bulk-fallback-review.json。

## 相关回归与 CI

相关回归 **9/9 个模块最终通过**，逐条命令与 stdout/stderr/退出码见 ZIP 的 regressions.json。

- `python -X utf8 -m md_cg.test_stgidx_index_parity`
- `python -X utf8 -m md_cg.test_issue157b_index_remainder`
- `python -X utf8 -m md_cg.test_issue52_scan_condition_first`
- `python -X utf8 -m md_cg.test_p8_subgraph_chain`
- `python -X utf8 -m md_cg.test_p7_goals_recent`
- `python -X utf8 -m md_cg.test_role_views`
- `python -X utf8 -m md_cg.test_state_events`
- `python -X utf8 -m md_cg.test_state_slots`
- `python -X utf8 -m md_cg.test_retr_s8_time`

共用 CI 前置：[PR #233](https://github.com/FuRongJun-1999/dsh-memory/pull/233)。它恢复干净 runner 的 Node 构建及两处 Linux 夹具，原安全阈值、断言与发布件判据不变；生态路径补丁与 #188 相同，本项不重复认领成果。完整 Ubuntu 全量 CI 以本 PR 当前 head 的 Actions 记录为准，不把上述定向回归称作全量 CI。

## 独立范围与评审依据

闭合 #157 留下且代码已明确记录的 timed O(N²) 余项；不重复认领其 session/layer/untimed/nonfinite O(1) 摘除成果。原 STG 守卫仅更新 4 个已漂移/随实现变化的变异锚，51 条断言与 17 个预期失败计数不改。

建议按 expert 评审的依据：改变核心时间索引数据结构并维护增量分类与区间查询契约，需要随机更新 oracle、块结构不变量、原 STG 17 项定点变异以及同数据配对性能对照。最终难度、影响与结算均由维护者裁定；不凭代码行数或测试数量自行定档。

## 限制

这里是合成内存时间索引微基准，不能外推为端到端记忆检索、百万条、并发或正式榜单。小区间查询存在块遍历与 Python 调用开销，原始读数如实列出；实例仍沿用原串行使用假设，未增加线程安全。本项无真实私域数据、外部模型调用或正式榜单成绩；不改变删除/权限/密钥接口。

[原始公开证据 ZIP](stg_time_blocks_20261013/raw-evidence.zip)（主机路径归一，断言与数值保留；CRC 与逐项 SHA256 已核对）。证据目录用自身 .npmignore 排除，不增加 npm 分发体积。代码与合成 fixtures 按本仓 MIT 许可。
