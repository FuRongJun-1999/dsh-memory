# 状态投影性能基准（#396）

## 这份文档为什么是「怎么跑」而不是「读数」

`#396` 的实现与守卫已在 `f3b998ad` 恢复（流式归约：值按槽聚合、统计只累加需要的字段、
完整历史按组释放、`project_page()` 精确计数）。

**而读数与两份产物（`docs/benchmarks/state_projection_results.json`、本文件原版）在 `e81caab0` 中被一并删除，
我没有恢复它们的旧值 —— 因为**旧读数与当前机器/当前 main 不可比**，写一份比不出来源的数字比留空更坏。**

## 怎么重新生成（paired benchmark）

脚本本身是**成对比较器**：它需要一个「未改动基线检出」和一个「候选检出」，
而不是「在同一个树里跑两次」。

```bash
# 1) 基线检出（#396 之前）
git worktree add --detach /tmp/sp-baseline 0bee3c9a^

# 2) 候选检出（当前 main，含 #396 的流式归约）
git worktree add --detach /tmp/sp-candidate origin/main

# 3) 跑（在候选树里跑，因为它自带基准脚本）
cd /tmp/sp-candidate
python -X utf8 scripts/benchmark_state_projection.py \
    --baseline /tmp/sp-baseline \
    --output-dir /tmp/sp-out \
    --rounds 5 \
    --label "$(git rev-parse --short HEAD)"
```

输出目录会给出 `state_projection_results.json`（逐用例、逐模式的配对数与耗时）与一份 markdown 摘要。
把它粘回 `docs/benchmarks/state_projection_results.json` 时，**必须同时记录**：

- `git rev-parse HEAD`（被测提交）；
- Python 版本与平台（脚本是 stdlib-only，故这两个就是全部环境变量）；
- `--rounds` 的值；
- 是否 `--memory-worker`（内存口径还是时间口径）。

## 设计要点（读代码时容易忽略的三处）

1. **值按槽聚合**：`state_slots` 不再把每个事件物化成一条完整记录，只在需要时取该槽的当前值。
2. **统计只累加需要的字段**：`status()` 的计数不依赖完整历史，故历史可以逐组释放。
3. **`project_page()` 精确计数**：`stg` 走它而不是先建全表再切片，所以只构造**实际返回的**那一页。

⇒ 这三条合起来才是「流式归约」；少任何一条，内存峰值都会回到全量物化。

## 与 `--mutate` 的关系

`md_cg/test_state_projection_streaming.py`（136 行，`f3b998ad` 恢复）是这条实现的行为守卫，
它的变异自证不依赖本基准；基准只回答「快了多少 / 省了多少」，不回答「对不对」。