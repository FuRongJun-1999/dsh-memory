# 落地记录 · iter-retr-postings（环二检索重接 S7：倒排候选层）

- 里程碑：**S7 倒排（发布表）候选层** —— 候选内加速 + 召回与全表扫描逐条一致
- 分支：`task/iter-retr-postings`（base `4744eb6`，tip `cd9cce0`，3 提交）
- 基线标签：`core-retr-s1` / `core-retr-s3` / `core-retr-s4` / `core-retr-s5` / `core-retr-s6` / `core-retr-s1b`
- 本里程碑标签：**`core-retr-s7`**
- 独立复核：编外验证单元（Zero-Trust，job `h1789774451537_4640e1`）→ **ACCEPT**
  （候选提交 `cd9cce0`；复核文本见 `hive/interop/iter-retr-postings/note-unit-review.json`）
- 前置轮次：同一 tip 前身 `3f7ffb1` 被判 REJECT（3 条），逐条修复后本轮 ACCEPT

## 落地判据（逐条核对）

| 判据 | 结果 |
| --- | --- |
| 内部复核 | 逐轮自检 + 反向证据（临时还原修复行，用例立即变红） |
| 独立复核 | ACCEPT（见上） |
| 零删除 | `git show --diff-filter=D --name-only origin/main..HEAD` → 空 |
| 干净树回归 | `scripts/run_tests.py --jobs 4` → **126/126 通过，3 跳过** |
| 模块级 | `md_cg` 组 96/96；`test_retr_s7` 41/41 |

## 改动（5 文件，零删除）

- `md_cg/postings.py`（新）：bigram 发布表 + 快照指纹（节点数 / 目录 mtime / 根级文件 mtime / 索引 mtime）
- `md_cg/build_postings.py`（新）：`--root/--stats/--limit/--if-stale` CLI
- `md_cg/mdcg.py`：S7 接线（T2 前窄化、原序保持、T3 还原全量并还原 scanned、语义路/S3 组合让位）
- `md_cg/test_retr_s7.py`（新）：41 断言
- `docs/hive/真实库端到端实测_S7倒排候选层_v0.1.md`（新）：真实库实测与局限

## 开关（默认全关，逐项显式）

| 环境变量 | 默认 | 作用 |
| --- | --- | --- |
| `MDCG_RETRIEVAL_PIPELINE` | 关 | 父开关 |
| `MDCG_GATE_S7_POSTINGS` | 关 | S7 子开关（必须显式 =1） |
| `MDCG_S7_FRESHNESS` | `auto` | `skip` 仅供离线对照实测 |

审计：`meta.gates.s7 = {cands, in, terms, reason, fallback, attempted}`。

## 真实库实测（12,150 节点 / 1,446 MB，直连，只写派生索引）

- 构建：6.5–11.2s / 201,514 词项 / 3,123,686 倒排条目 / 75.7 MB；快照校验 0.05s
- 逐条（id + 分 + 次序）一致 **6/6**（`skip` 与 `auto` 两种模式）
- `贝塞尔 曲线 工程 应力`：scanned 12,150→**723**，2.00s→**0.45s（4.4×）**
- `graphrag 图谱 检索`：12,150→**933**（1.4×）
- `whitebox 白箱 条件`：12,150→**11,499**（该查询含极常见 2-gram「条件」，候选本来就是真命中集）
- 单字词（同义词组展开出「库」）与语义路开启时：如实回退全量
- 默认关跨版本等价：真实库上 4 查询 `results+meta` 逐字节一致（digest `ff4b5d230ccf06ef`，对照 `origin/main`）

## 局限（已在文档中如实记录）

1. 无 IDF：常见词会把候选推到接近全库（`whitebox 白箱 条件` 只降 6%）。
2. 单字查询词 → 整查询回退（需字符级索引才能覆盖）。
3. 库被持续批量改写时快照秒级过期 → 自动回退基线（正确性优先）；
   要长期吃到加速需**写入路径增量维护（dirty 集）**，下一里程碑。
4. v1 不做写入增量：改写后重建（`--if-stale` 供守候环）。

## 恢复锚点

- tip：`cd9cce0bac7c7b62369c90da3b99cfe5a8b275c2`
- 中间提交：`3f7ffb1`（首版）、`7280ac7`（指纹 + 原序 + S3 组合）
