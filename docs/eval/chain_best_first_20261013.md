# 关系链检索：弱分支耗尽预算导致强链漏召回

2026-10-13

默认 `search_rrf` 的 chain 路先用 DFS 枚举路径、再挑最强链。一个只有 **28 个节点**的合流图就能让弱分支的重复路径耗尽 500 条链预算，漏掉 `seed → strong_a → strong_target`。仅交换 seed 的出边声明顺序，强链就重新出现。

本次只修复这一处检索缺陷。`walk` / `explain` 的全路径枚举保持原实现；检索改用最大优先队列与深度/累积权重 Pareto 标签，优先处理强前缀，并合并重复状态。

## 冻结版本与复跑

- 改前：`23ac3f0456c768537ca341e102232b9522c442b5`。
- 改后测量版本：`b70e19dcf7059dbc907b9bd454ad5a8c7a667fd4`（已合入上述 main；功能提交 `bc23dad50f819b28cc8144ff56bdf479e89089fc`）。
- 平台：Windows / Python 3.12.10。全部数据由脚本生成，原生 Markdown 入库；无外部服务、私域数据或模型调用。
- 同一脚本、同一 fixture SHA256、相同深度/权重/预算；分别启动新进程，按基线→修复、修复→基线两轮测量。每轮每例预热后 60 次展开、10 次默认 RRF。表中展开 p50 合并两轮各 60 个样本；原始样本及 p95 保存在 JSON。

在本 PR checkout 根目录运行：

```bash
python -X utf8 tests/test_chain_best_first.py
python -X utf8 tests/test_chain_best_first.py --mutate

git worktree add --detach ../dsh-memory-chain-base 23ac3f0456c768537ca341e102232b9522c442b5
python -X utf8 scripts/bench_chain_best_first.py --repo ../dsh-memory-chain-base --expect-baseline-failure --output baseline.json
python -X utf8 scripts/bench_chain_best_first.py --repo . --output fixed.json
# 第二轮倒转上面两条测量命令的执行顺序，写入不同输出文件。
```

基线参数 `--expect-baseline-failure` 必须得到两个**指定断言失败**，而非异常或 SKIP：`strong_target starved`、`default production RRF must recall strong_target`；否则脚本退出失败。修复版必须通过这两项真实入口守卫。

## 改前 / 改后实跑读数

每例含两条强 causal 边与四层弱合流分支；宽度分别为 3 / 6 / 12。目标强链累积权重 `0.7225`，seed 分为 1 时检索分 `0.585225`。默认 RRF 使用全部默认路径，`k=20, judge=False, record=False`。

| 节点数 | seed 边顺序 | 默认 RRF 找到强目标：前→后 | 展开 p50 毫秒：前→后 | 边权计算次数：前→后 |
|---:|---|---|---:|---:|
| 16 | 强分支先声明 | 是→是 | 0.470→0.119 | 123→33 |
| 16 | 弱分支先声明 | 是→是 | 0.478→0.119 | 123→33 |
| 28 | 强分支先声明 | 否→是 | 2.126→0.321 | 500→117 |
| 28 | 弱分支先声明 | 是→是 | 2.129→0.325 | 501→117 |
| 52 | 强分支先声明 | 否→是 | 2.236→1.116 | 506→447 |
| 52 | 弱分支先声明 | 是→是 | 2.338→1.263 | 507→447 |

强目标召回：展开与默认生产 RRF 均为 **4/6 → 6/6**，两轮一致。16 节点例是原算法未耗尽预算的正向对照。改后命中的强目标链、逐跳条件和分数均有断言。计数在独立调用中以 `edge_weight` 包装器观测，不混入计时。

计时有系统噪声，例如 52 节点强分支先声明例的两轮基线 p50 为 4.001 / 2.125 毫秒；本报告保留两轮样本，不把单次计时当作稳定倍率承诺。

原始读数：[基线 A](chain_best_first_20261013/current-baseline-a.json)、[基线 B](chain_best_first_20261013/current-baseline-b.json)、[修复 A](chain_best_first_20261013/current-fixed-a.json)、[修复 B](chain_best_first_20261013/current-fixed-b.json)。记录包含 commit、源文件原始字节 SHA256、harness/helper SHA256、fixture SHA256、完整计时样本、RRF 候选与 provenance。源文件 SHA256 对应测量时的 Windows 工作树字节，跨平台换行可能不同，commit 固定实现版本。

## 正确性与反面对照

| 检查 | 实跑结果 |
|---|---|
| `python -X utf8 tests/test_chain_best_first.py` | **通过 14 / 失败 0**，0 SKIP |
| 其中独立穷举参照 | 固定随机种子的 **600 个有向小图**：最强分数/最短最优深度、真实边与条件、简单路径、六位舍入均对拍 |
| `python -X utf8 tests/test_chain_best_first.py --mutate` | **通过 9 / 失败 0**；九个变异均被指定断言捕获，0 异常 / 0 SKIP；源码字节不变，恢复后 14 项再绿 |
| 相关回归 | **12 个模块通过，0 失败**；包括真实读隔离、归档、RRF 资格/种子缓存/候选、排序口径、判据面覆盖、Hive 锚链 |

守卫还覆盖：1000 叶子的截断图先保留强链；深层强前缀不能剪掉还能继续向下的浅层弱前缀；环、自环、零权重/零种子/零衰减、多种子、层级开关、深度 0 / 64 / None、资源预算 0 / 1、非单调输入兼容回退。

九个变异：恢复旧 DFS、改为弱优先、撤掉支配剪枝、剪枝忽略深度、漏乘种子分、漏乘衰减、去掉关系过滤、去掉深度限制、清空边条件。每个变异只改生产源码一处，内存装载后执行指定守卫；导入失败、异常和跳过不算捕获。

原始日志：[14 项守卫](chain_best_first_20261013/guards-current.json)、[九项定点变异](chain_best_first_20261013/mutations-current.json)、[相关回归](chain_best_first_20261013/related-current.json)。相关回归逐模块命令及 stdout/stderr 均在 JSON。新工作树最初缺 Hive release 二进制，锚链测试曾 17 pass / 5 fail；构建真实二进制后复跑 22/22，通过依赖构建消除环境失败，未放宽断言。

## 算法与边界

1. 标签记录节点、已用深度、未中间舍入的边权乘积及真实 hops。较浅且不弱的标签可以支配同节点标签；较深强标签不能删除较浅弱标签。
   单调性依据：边权与衰减均不大于 1，去掉闭环可得到较浅且不弱的路径。若替代前缀包含后继节点，可从首次到达该后继的前缀继续；因此无需枚举每一种重复前缀来求每目标最强分数。等分 provenance 的字典序限制见第 4 项。
2. 沿用既有 `seed × round(边权乘积, 6) × decay^depth` 计分、唯一边权表、默认深度 5 / 硬上限 64、`max_nodes=500` / `max_chains=500` 数值。优先队列使用包含舍入误差的分数上界。预算计有效弹出标签，输出仍有每 seed 的 max_chains 上限。
3. 有限非负种子分、0≤decay≤1、边权在 [0,1] 时使用新搜索；不满足单调性前提则走原 `walk` 兼容路径。可选 `stats` 报告有效展开、边扫描、支配剪枝、待处理标签与 `complete`。预算用尽时只是已发现的最佳结果，不保证全图最优。
4. 等分候选在保留状态中优先短链、较大原始乘积与节点序。较强前缀可能支配字典序较早的弱前缀；零权边后的等分 provenance 不承诺是全体等分路径中字典序最小的一条，但必须是真实简单路径与真实条件。`walk` 全路径解释接口保留原行为。
5. 使用原 `adjacency` 的可见性/归档过滤和写入失效机制；不引入持久缓存或旁路读取。读隔离和退役回归实跑通过。

这是**合成图上的缺陷修复与局部热查询测量**。邻接冷建仍需遍历索引，单个高出度节点仍会扫描所有出边；预算不是边扫描或内存的硬上限。未测试百万节点、并发、私域语料或正式检索榜单，不主张全项目已达到任意规模低延迟。

全量 CI 的运行与结论以 PR 对应 head 的 GitHub Actions 为准，本地指定模块通过不替代全量 CI。
