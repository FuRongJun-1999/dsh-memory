# fix(subgraph): 按最短层级遍历并在入队前约束节点预算

2026-10-16

限深 DFS 只按节点 id 标记访问，先经长路见到共享节点后，会屏蔽后来的短路，漏掉仍在深度范围内的后代；节点预算检查前已把全部子节点压栈并登记边，预算为 1 仍返回指向未返回节点的边。

以 FIFO 按层遍历，首次接纳即为最短层级；入队前占用节点预算，边的两端接纳后才登记。内部借用已有子节点邻接，不先复制整条高扇出列表；节点/深度受限时标记 truncated。节点预算按 int 归一，拒绝 NaN/Infinity。

| 实测 | 未改基线 | 本项修复 |
|---|---|---|
| 深度 3 内的 tail | False | True |
| tail 的层级路径 | None | r/b/c/tail |
| 节点预算 1 的悬空边 | 2 | 0 |
| 新增守卫 | 6 通过 / 6 失败 | 12 通过 / 0 失败 |

## 实际运行

原始基线 `4cc069b3c608ca68fd9efb249343f1c7c46d185d` 的未改副本与本项独立代码分别执行；未叠加另两项核心修复。两平台均 12/12 新增守卫、5/5 具名内存变异检出，恢复后再全绿，0 errors / 0 SKIP。方法计数不冒充生成用例总数。三项组合兼容运行另各 36/36 守卫、15/15 变异。

- windows：6 条完整通过、0 条含内部 SKIP、0 条整体 SKIP、0 失败；逐条原始输出见 results.json 和 ZIP logs。
- linux：6 条完整通过、0 条含内部 SKIP、0 条整体 SKIP、0 失败；逐条原始输出见 results.json 和 ZIP logs。

```bash
python -X utf8 tests/test_subgraph_bounded_bfs.py --output fixed.json
python -X utf8 tests/test_subgraph_bounded_bfs.py --mutate --output mutations.json
git worktree add --detach ../subgraph_bounded_bfs-baseline 4cc069b3c608ca68fd9efb249343f1c7c46d185d
python -X utf8 scripts/replay_subgraph_bounded_bfs.py --repo ../subgraph_bounded_bfs-baseline --output baseline.json
python -X utf8 scripts/probe_subgraph_bounded_bfs.py --repo . --case traverse --output native.json
```

Windows 实际使用 `py -3.12 -X utf8`，Linux/WSL 为 `python3 -X utf8`（Python 3.13，原生 /tmp）。每条实际命令、退出码、源码 SHA256、初始失败和明确 SKIP 均保留。原版守卫退出 1 是缺陷复现，errors=0 / SKIP=0；修复/变异入口退出 0。原文兑现探针真实删除隔离库文件，精确故障时点由守卫控制；复杂度探针只有合成元数据，不冒充文件检索评测。

## 具名反面对照

- B1 use a LIFO frontier again → `Guards.test_depth_limited_shared_child_uses_shorter_route`，指定断言红、errors=0 / SKIP=0。
- B2 ignore the node admission budget → `Guards.test_node_budget_is_never_exceeded`，指定断言红、errors=0 / SKIP=0。
- B3 copy the whole child list before checking budget → `Guards.test_frontier_does_not_copy_a_wide_child_list`，指定断言红、errors=0 / SKIP=0。
- B4 admit an edge before its child node → `Guards.test_edges_are_closed_over_admitted_nodes`，指定断言红、errors=0 / SKIP=0。
- B5 expand one layer past the depth boundary → `Guards.test_depth_boundary_does_not_include_grandchildren`，指定断言红、errors=0 / SKIP=0。

初轮 LIFO 变异在单一声明顺序下先遇短路，仍能通过。守卫现同时验证两种子节点顺序及穷举短游走，不依赖碰巧的遍历顺序；最终 5 个变异均被检出。旧记录在 ZIP history，未计通过。 未放宽旧断言。变异仅替换内存 callable，源码字节未改；导入错误/异常崩溃不算杀死变异。

## 设计依据、范围与限制

建议 expert：需同时建立限深可达性、最短层级、节点入队预算与结果边闭合不变量，覆盖 DAG 合流、环、扇出与截断，并用穷举短游走 oracle 和工作量守卫排除只修例子的方案。最终档位与影响由维护者裁定。

独立于 PR #168 的最强因果链和 PR #391 的候选资格子图：本项是嵌套层级展开/flatten 的深度与预算算法，不改链置信分数或授权规则。

输出顺序改为按层，同层保留声明顺序；依赖旧 DFS 顺序的外部调用方需确认。限制的是已有邻接上的遍历前沿与返回端点，冷邻接构建仍沿用既有全图成本；返回路径字符串的字节成本另计。预算截断时返回闭合但可能不完整的边集，不承诺包含所有已接纳节点间的边；不提供共享实例并发修改保证。

共同 CI 前置只将 checkout 的 fetch-depth 设为 0，供既有历史负面对照取原提交；未删改旧断言、未降阈值，不作为独立贡献。新增代码只用 Python 标准库，保留 MIT 许可。

本报告的本地运行不等同 GitHub CI；以 PR 当前 head checks 为准，全部 CI 成功后才发布对应 bounty intake。维护者人审、最终定级与结算均待定。未声称正式榜单名次、百万端到端低延迟或真实私域问答改善。

ZIP 含本项冻结测试、回放/探针、读数、原始日志、MIT 许可和哈希；需配套源码检出，不是整仓离线镜像。
