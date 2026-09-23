# 蜂巢 M6 ingest 实施计划 v0.1

> 真源：`D:\2_ai\蜂巢记忆架构设计.md` §5（M6 规格已细化到可施工）+ §5.5 层归属纪律。
> 本计划 = 施工蓝图 + 判定单。开工依据：使用者指令（2026-09-23，P2 接线开工）。

## 〇 条件空间声明

| 维 | 值 |
|---|---|
| 观测位置 | 主代理（CodeBuddy），融合裁决位 |
| 观测工具 | 设计稿 §5 规格 + `md_cg/sources.py` 既有管线（Source/Ingestor/mine_fix_pairs）+ hive/jobs 真实数据面 |
| 时间窗口 | 2026-09-23 批次 4 |
| 存在约束 | 复用既有管线（不重造 watermark）；ingest 产物只落 contextual（§5.5 硬性）；knowledge 层零污染 |

## 一、任务分解与判定单

### T1 HiveJobsSource（sources.py 注册蜂巢事件源）

- **依据**：§5.1 事件源注册表（source_id=hive_jobs；progress.jsonl 五类条目 + result.json 终态权威确认；job_id 名升序=时间序）。
- **条件**：复用 `Source` 基类协议（events() → {t, seq, role, text, session, cwd}，t=epoch 秒）；session=`hive:<job_id>`（ingest 去重键）。
- **错后**：progress 解析失败跳过该行并计入 skipped（不终杀批次）；result.json 缺失任务按 progress 现状处理（不伪造终态）。
- **裁决**：ACCEPT。
- **映射**（§5.3）：start→任务开始事件｜tool→跳过（防流水账爆炸）｜final/handoff/error→事件｜result 终态→权威确认（progress 缺 final 时补位）。error 终态 text 前缀「任务失败」保证 fix-pair 启发式命中。

### T2 层归属与密级（§5.5 硬性）

- **依据**：ingest 产物只落 contextual；valid_from=事件时间；密级默认 internal。
- **条件**：`Ingestor(cg, layer="contextual")`；knowledge 层节点数在 ingest 前后不变（反向对照判据）。
- **错后**：error 节点建议 private 的 per-event 密级——Ingestor 现不支持事件级密级，**DEFER**（诚实边界，不硬凑）。
- **裁决**：ACCEPT（含一项 DEFER）。

### T3 验收回放（§5.6 四条）

1. 失败→重试成功任务：contextual 出现事件节点 + fix-pair 产出 + **knowledge 层节点数不变**；
2. 中断重跑：watermark 断点续跑，无重复节点；
3. 强杀任务：result.json 终态补位；
4. 真实 jobs 目录回放（`hive/jobs/` 现存 50+ 任务即真实语料）。

### T4 MCP/CLI 暴露口

- **裁决**：DEFER 到下一小批——先以 Python API + 测试闭环（`Ingestor(cg, layer="contextual").ingest(HiveJobsSource(root))`），MCP `ingest` 面接入需动 `mcp_server` 工具 schema（独立改动面），不与本批耦合。

## 二、验证判据

- 单测：事件映射/终态补位/watermark 幂等/contextual-only（新建 `md_cg/test_hive_ingest.py`）；
- 真实回放：本机 `hive/jobs/`（50+ 任务含 12 error）全量 ingest dry-run 与实跑对照；
- gate 全绿 + 提交点（回滚边界）。
