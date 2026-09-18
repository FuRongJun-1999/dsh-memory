# 缺陷与修正：驱动选靶用「总缺口」→ 反复开在结构性停滞文件上空烧（PASS 0 SKIP 5）

- 提出时间：2026-09-19 02:1x（环二第 538 轮）
- 处置：编外（本侧）自检 → 拆出「可转化缺口」口径并让驱动按它选靶 → 复测 → 提交本说明
- 状态：待编外复核（Zero-Trust）。

## 1. 缺陷

驱动按 `repo_gap.py` 的**总缺口**排序选靶，而总缺口里相当一部分是**结构性停滞**：
符号没有必需形参（类无 `__init__` 形参、函数零参或仅可选参），
`condition_anchor.judge` 永远判不出 `ANCHORED` → 该批 `PASS 0 SKIP n` → `EMPTY_PACKAGE`。

按发布线实测（2026-09-19 02:15，CORE 2522 符号）：

| 分类 | 数量 | 含义 |
| --- | --- | --- |
| 已覆盖 | 2338 | 已有 `# 生效条件：` |
| **可转化（有必需形参）** | **63** | 门禁可通过，是真正待写的工作面 |
| 结构性（无必需形参） | 115 | 现行判据下不可能过门禁 |
| 同名多定义 | 5 | 定位歧义（已剔除） |
| 片段超限 | 1 | 需更大 `--max-src` 单跑 |

实证空烧：`md_cg/mdcos.py`（总缺口 10，其中 7 个无 required）连续两批 `PASS 0 SKIP 5`；
`compiler/condition_vm.py`（6 个里 5 个无 required）同样 `PASS 0 SKIP 5`。

## 2. 修正

1. 新增 `_coord/_convertible_scan.py`：按发布线（`origin/main`）枚举未覆盖符号，
   经 `cond_facts` 取事实，写出缓存 `_coord/_convertible_targets.tsv`
   （`file / convertible / structural / ambiguous / truncated`）。
2. `auto_batches.gap_files()` 优先读该缓存（有效期 90 分钟），并按可转化数选靶；
   缓存过期或缺失时回退到原来的总缺口口径。
3. 选靶阈值随口径切换：总缺口口径 `<6` 不开批；可转化口径改为 `>=2`
   （否则 2~4 个可转化符号会被 `g>5` 全部过滤 → `NO_GAP_LEFT` 空转，已实测）。

## 3. 实测

- 修正前：`BATCH c313 md_cg/mdcos.py gap=10` → `PASS 0 SKIP 5`；`BATCH c314 compiler/condition_vm.py gap=6` → `PASS 0 SKIP 5`。
- 修正后：`BATCH c317 scripts/render_discipline.py gap=4`（可转化）→ **`PASS 4 SKIP 0`**。
- 同轮 lane：`iter-tasks-c1 +3`、`iter-subgraph-c1 +3` 落地；`CORE have 2338→2344`、`gap 184→178`。
- 落地环日志出现 `ALREADY_LANDED iter-tasks-c1 +3（按提交回填，跳过重复应用）` —— 上一轮加的
  防重复应用守卫得到实证。

## 4. 边界

- 「结构性 115」不是「已写」也不是「错误」：它们是**现行锚点判据下不可达**的符号。
  是否给它们写「无条件」类条件或标不适用，属**使用者裁决面**，本侧不擅自扩大。
- 缓存是快照（默认 90 分钟）：过期即回退总缺口口径，不会因缓存陈旧而长期误选。
