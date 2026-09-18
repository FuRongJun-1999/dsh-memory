# 分支清理记录（2026-09-19 03:4x，使用者批准）

## 操作

- 批准口径：①删除已并入 `origin/main` 的 `task/*` 分支；②未并入分支中账面为 `stale`/`superseded` 的删除；
  其余（在途 / 账面 `landed` 但未并入 / 无台账行）**保留**。
- 执行结果：远端 `task/*` 由 **842 → 615**（删除 **227** = 已并入 104 + stale/superseded 123），失败 0。
- `origin/main` 未做任何改写（仍是 1497 提交，tip 见下）。

## 可恢复性

每个被删分支的 SHA 记在 `hive/interop/_pruned_branches.tsv`（`branch<TAB>sha12<TAB>reason`）。
需要恢复任一条：

```
git push origin <sha>:refs/heads/<branch>
# 例：git push origin 83aef1c9def4:refs/heads/task/iter-002-carrier-align
```

## 保留说明（615 条）

| 类别 | 数量 | 为何保留 |
| --- | --- | --- |
| 账面 `landed` 但分支未并入 main | 124 | 落地是「重应用到当前 main」而非 merge 分支，故分支天然不是 main 的祖先；其内容已在 main，但未在本轮批准口径内，留待二次确认 |
| 无台账行 | 491 | 多为候选的中间链（`-fix`/`-d1`/`-dual`）或早期分支；无法据账面判定，按「不明确即保留」处理 |

## 待办（需使用者二次确认）

- 上表 124 + 491 的清理口径；
- 本地 `main` 快进到 `origin/main`（当时落后 78 个提交，属陈旧工作树引用，不影响内容）。
