# 修复增量日志水位越过尚未提交的记录

2026-10-13

读到半条 JSON 或半个 UTF-8 字符后，旧水位推进至 EOF；写方随后补完这条记录，四个 inbox/decisions 增量缓存仍永久漏掉它，而从头读取能看见。现在仅消费最后一个换行之前的完整行，以其真实字节位置续读。完整坏行仍跳过并推进，既有崩溃重同步换行仍能接续。

将日志换行定义为提交边界，缓存的读水位跟随已消费的完整记录，而不是文件当前大小。四个调用方共用读函数，不增加新缓存或新持久格式。

## 同输入实际结果

| 观察项 | 未改原始代码 | 本项修复 |
|---|---|---|
| 部分 UTF-8 写入后补完：增量缓存记录数 | 0 | 1 |
| 同一日志从头读取记录数 | 1 | 1 |
| 新守卫测试方法 | 3 通过 / 5 失败 | 8 通过 / 0 失败 |

原始代码冻结于 `efa2ee2ba4986c02ad204f05a99712c226d0023d`；最新共同基线为 `4169c5bd`，包含其后独立的 CI 前置修复 `cbf43fe289c9e81cd9beb14cd77ca902e4058535`。本项测量代码提交 `0efbf09597e7eef3e6b040be8d30ca9c2aabab20`，逐文件 SHA256 在证据 ZIP 的 identity.json，分别记录运行时 CRLF 字节与 LF 归一源码，便于跨平台检出核对。五个核心分支不互相包含对方的修复。

Windows Python 3.12.10、Linux / WSL Python 3.13.12：各 **8 项守卫通过 / 0 失败 / 0 异常 / 0 SKIP**；各 **3 项定点变异被指定断言捕获**，异常和跳过均为 0，源码未改写；恢复后 8 项再绿。这里按测试方法与变异计数，不把子断言或恢复轮重复相加。

```bash
python -X utf8 tests/test_jsonl_commit_watermark.py
python -X utf8 tests/test_jsonl_commit_watermark.py --mutate
```

## 未改代码复现与反面对照

从本 PR 检出目录执行（守卫用临时合成库，不读在役库）：

```bash
python -m zipfile -e docs/eval/jsonl_commit_watermark_20261013/raw-evidence.zip proof
git worktree add --detach ../baseline efa2ee2ba4986c02ad204f05a99712c226d0023d
python -X utf8 proof/repro_baseline.py --baseline ../baseline --fixed . --module md_cg.test_jsonl_commit_watermark
# 预期退出 1：8 个测试中 5 个测试方法失败，0 异常 / 0 SKIP。
```

此命令只把新守卫加入原始包的测试搜索路径，生产模块仍全部来自未改的 baseline。没有靠禁用新开关或注入错误冒充旧代码。

| 单点变异 | 必红断言 | Windows / Linux 实际结果 |
|---|---|---|
| advance beyond pending bytes | `Guards.test_inbox_commit_becomes_visible` | 1 项断言失败 / 0 异常 / 0 SKIP |
| publish JSON before newline | `Guards.test_json_without_commit_newline_is_pending` | 1 项断言失败 / 0 异常 / 0 SKIP |
| reset incremental watermark | `Guards.test_incremental_watermark_keeps_prefix` | 1 项断言失败 / 0 异常 / 0 SKIP |

变异只在内存编译副本替换目标函数/方法。每项要求恰好执行指定测试、至少一项 AssertionError、0 导入或运行异常、0 SKIP，并核对源文件 SHA256 恢复不变。

```bash
python -X utf8 proof/native_pair_probe.py --repo ../baseline --slug jsonl
python -X utf8 proof/native_pair_probe.py --repo . --slug jsonl
```

## 相关回归与 CI

相关回归 **9/9 个模块最终通过**，逐条命令与 stdout/stderr/退出码见 ZIP 的 regressions.json。

- `python -X utf8 -m md_cg.test_tail_watermark_race`
- `python -X utf8 -m md_cg.test_review_queue_index`
- `python -X utf8 -m md_cg.test_review_queue_batch`
- `python -X utf8 -m md_cg.test_review_onepass`
- `python -X utf8 -m md_cg.test_propose_tail_index`
- `python -X utf8 -m md_cg.test_twophase`
- `python -X utf8 -m md_cg.test_writepipe`
- `python -X utf8 -m md_cg.test_units_poll`
- `python -X utf8 -m md_cg.test_state_events`

共用 CI 前置：[PR #233](https://github.com/FuRongJun-1999/dsh-memory/pull/233)。它恢复干净 runner 的 Node 构建及两处 Linux 夹具，原安全阈值、断言与发布件判据不变；生态路径补丁与 #188 相同，本项不重复认领成果。完整 Ubuntu 全量 CI 以本 PR 当前 head 的 Actions 记录为准，不把上述定向回归称作全量 CI。

## 独立范围与评审依据

与旧水位竞态守卫区分：旧件处理 stat/read 窗口里已经完整追加的行被重复消费；本件处理 reader 到达 EOF 时写方尚未完成一行而导致永久丢失。

建议按 expert 评审的依据：需要判定并发追加的提交边界、真实读取位置和四种缓存的共同契约，覆盖 UTF-8 每个切分点、决定账与 inbox、坏行恢复和去重；不是用重启重扫掩盖丢账。最终难度、影响与结算均由维护者裁定；不凭代码行数或测试数量自行定档。

## 限制

仅处理既有 append-only 日志契约下的完整行水位。没有新增跨进程写锁、日志轮转或非合作截断协议。缺少结尾换行的 JSON 会保持 pending，完整坏行仍沿用原容错政策。本项无真实私域数据、外部模型调用或正式榜单成绩；不改变删除/权限/密钥接口。

[原始公开证据 ZIP](jsonl_commit_watermark_20261013/raw-evidence.zip)（主机路径归一，断言与数值保留；CRC 与逐项 SHA256 已核对）。证据目录用自身 .npmignore 排除，不增加 npm 分发体积。代码与合成 fixtures 按本仓 MIT 许可。
