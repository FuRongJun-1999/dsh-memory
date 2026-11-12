# 启动与压实共用索引快照准入，恢复真实节点

2026-10-13

合法 JSON 不等于可用快照：nodes=null/list/number 或条目 None/list 会使启动报错，空条目还会让假节点取代真实节点池。加载和 compact 现在共用 schema、容器、条目 path/bucket 的形态检查；拒绝整份不可用派生快照后，回到已有 Markdown 扫描与日志重放。

派生索引只有通过完整准入才可参与重放；Markdown 节点仍是真源。启动与 compact 使用同一判断，避免一处恢复、另一处再次丢池。

## 同输入实际结果

| 观察项 | 未改原始代码 | 本项修复 |
|---|---|---|
| 6 种损坏形态重新打开并恢复 survivor | 0/6 | 6/6 |
| 空条目形态中的可见节点 | 仅 invalid | survivor |
| 新守卫测试方法 | 1 通过 / 7 失败 | 8 通过 / 0 失败 |

原始代码冻结于 `efa2ee2ba4986c02ad204f05a99712c226d0023d`；最新共同基线为 `4169c5bd`，包含其后独立的 CI 前置修复 `cbf43fe289c9e81cd9beb14cd77ca902e4058535`。本项测量代码提交 `ec07a8612e21a2fbd2da398fb776c7cf797996ef`，逐文件 SHA256 在证据 ZIP 的 identity.json，分别记录运行时 CRLF 字节与 LF 归一源码，便于跨平台检出核对。五个核心分支不互相包含对方的修复。

Windows Python 3.12.10、Linux / WSL Python 3.13.12：各 **8 项守卫通过 / 0 失败 / 0 异常 / 0 SKIP**；各 **4 项定点变异被指定断言捕获**，异常和跳过均为 0，源码未改写；恢复后 8 项再绿。这里按测试方法与变异计数，不把子断言或恢复轮重复相加。

```bash
python -X utf8 tests/test_index_snapshot_shape.py
python -X utf8 tests/test_index_snapshot_shape.py --mutate
```

## 未改代码复现与反面对照

从本 PR 检出目录执行（守卫用临时合成库，不读在役库）：

```bash
python -m zipfile -e docs/eval/index_snapshot_shape_20261013/raw-evidence.zip proof
git worktree add --detach ../baseline efa2ee2ba4986c02ad204f05a99712c226d0023d
python -X utf8 proof/repro_baseline.py --baseline ../baseline --fixed . --module md_cg.test_index_snapshot_shape
# 预期退出 1：8 个测试中 7 个测试方法失败，0 异常 / 0 SKIP。
```

此命令只把新守卫加入原始包的测试搜索路径，生产模块仍全部来自未改的 baseline。没有靠禁用新开关或注入错误冒充旧代码。

| 单点变异 | 必红断言 | Windows / Linux 实际结果 |
|---|---|---|
| accept malformed container | `Guards.test_load_container_shapes_recover` | 1 项断言失败 / 0 异常 / 0 SKIP |
| skip entry validation | `Guards.test_entry_shapes_recover` | 1 项断言失败 / 0 异常 / 0 SKIP |
| compact bypasses shape gate | `Guards.test_compact_container_shapes_recover` | 1 项断言失败 / 0 异常 / 0 SKIP |
| allow unhashable bucket | `Guards.test_unhashable_bucket_recovers` | 1 项断言失败 / 0 异常 / 0 SKIP |

变异只在内存编译副本替换目标函数/方法。每项要求恰好执行指定测试、至少一项 AssertionError、0 导入或运行异常、0 SKIP，并核对源文件 SHA256 恢复不变。

```bash
python -X utf8 proof/native_pair_probe.py --repo ../baseline --slug snapshot
python -X utf8 proof/native_pair_probe.py --repo . --slug snapshot
```

## 相关回归与 CI

相关回归 **9/9 个模块最终通过**，逐条命令与 stdout/stderr/退出码见 ZIP 的 regressions.json。

- `python -X utf8 -m md_cg.test_index_durability`
- `python -X utf8 -m md_cg.test_index_crossprocess_reload`
- `python -X utf8 -m md_cg.test_n225_nonobject_load`
- `python -X utf8 -m md_cg.test_n230_dirty_replay`
- `python -X utf8 -m md_cg.test_n195_writepath_reload`
- `python -X utf8 -m md_cg.test_issue80_residual_flush`
- `python -X utf8 -m md_cg.test_p38_concurrent_flush`
- `python -X utf8 -m md_cg.test_corrupt_utf8_read_surfaces`
- `python -X utf8 -m md_cg.test_p0`

共用 CI 前置：[PR #233](https://github.com/FuRongJun-1999/dsh-memory/pull/233)。它恢复干净 runner 的 Node 构建及两处 Linux 夹具，原安全阈值、断言与发布件判据不变；生态路径补丁与 #188 相同，本项不重复认领成果。完整 Ubuntu 全量 CI 以本 PR 当前 head 的 Actions 记录为准，不把上述定向回归称作全量 CI。

## 独立范围与评审依据

补足既有顶层非对象恢复：旧检查只看 dict/schema，本件检查其 nodes 容器和可消费条目，并同步 compact。不是 CSRE/NPZ 来源修复的重复申报。

建议按 expert 评审的依据：涉及派生快照、磁盘真源与增量日志的恢复顺序；需要同时保证 startup、compact、快照快路径与原文不变，不能只加一个类型异常捕获。最终难度、影响与结算均由维护者裁定；不凭代码行数或测试数量自行定档。

## 限制

准入遍历节点表为 O(N)，发生在加载/压实而非每次温检索；拒绝时需全库扫描。不会检测形态合法但内容陈旧或被恶意篡改的元数据，也没有改变既有新鲜度政策。本项无真实私域数据、外部模型调用或正式榜单成绩；不改变删除/权限/密钥接口。

[原始公开证据 ZIP](index_snapshot_shape_20261013/raw-evidence.zip)（主机路径归一，断言与数值保留；CRC 与逐项 SHA256 已核对）。证据目录用自身 .npmignore 排除，不增加 npm 分发体积。代码与合成 fixtures 按本仓 MIT 许可。
