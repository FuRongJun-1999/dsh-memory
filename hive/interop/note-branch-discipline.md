# 分支纪律（使用者裁定 2026-09-19）：探索自由、完结即收、只留有效

## 1. 裁定

1. **分支不宜多**；以当前基线为一个**核心节点**（里程碑）——每个核心任务完成时在 `main` 上打 `core-*` 标签。
2. **探索器可自由开分支**，但**任务完成（落地或判废）后必须删除**。
3. 只保留**已确认、有效果**的主分支，总数 **≤10**。

## 2. 本次执行结果

| 项 | 数值 |
| --- | --- |
| 核心节点标签 | `core-2026-09-19` → `origin/main` `6adb9a44` |
| `task/*` 分支 | 622 → **9**（删除 613，失败 0） |
| 远端分支总数 | **10**（9 个 `task/*` + `main`） |
| `origin/main` | 未做任何改写（1497 提交） |

删除记录与可恢复 SHA 见 `hive/interop/_pruned_branches.tsv`；恢复方式：

```
git push origin <sha12 对应的完整 sha>:refs/heads/<branch>
```

## 3. 保留的 9 条 `task/*`（清单同步在 `_coord/_branch_keep.txt`）

| 分支 | 保留理由 |
| --- | --- |
| `task/iter-002-carrier-align` | 编外验证端（zcode）当前轮询的**互验锚点**（回执按其 tip 出） |
| `task/iter-349-batch-c349` | 最近一批**已落地**候选（对应 `校验和落地` 提交） |
| `task/iter-348-batch-c348` | 同上 |
| `task/iter-tailmulti-e-fix` | 同上（多文件批次，+5） |
| `task/iter-tailmulti-c-fix` | 同上（多文件批次，+7） |
| `task/iter-341-batch-c341` | 同上 |
| `task/iter-tailmulti-a` | 同上（多文件批次，+7） |
| `task/iter-tailmulti-b` | 同上（多文件批次，+5） |
| `task/iter-ccgc-c3` | 同上 |

## 4. 长期执行（防分支再膨胀）

`_coord/prune_branches.py`（每轮运行；`--dry` 先看清单）保留规则：

1. `main` 恒保留；
2. `_branch_keep.txt` 清单内的分支；
3. 账本 `_dispatch_ledger.tsv` 中状态**非终态**（`offered`/`claimed`/`escalated`/`internal-verified`）的分支；
4. 提交时间在 **30 分钟**内的新分支（在途探索，交下一轮再判）。

其余 `task/*` 一律删除，SHA 记入 `_coord/_pruned_branches_log.tsv`。
「任务完成」的判据 = 账本终态（`landed`/`stale`/`superseded`）或候选判废。

## 5. 边界

- 落地是「把候选重应用到当前 main」而非 merge 分支，因此**分支是否并入 main 与内容是否生效无关**：
  内容生效看 `main` 上的 `校验和落地 <iter>` 提交；分支只是探索过程物。
- 删除分支不影响 `main` 内容，也不影响已推送的候选提交对象（在远端对象仍被 `main` 引用时）。
