# fix(subgraph): 统一层级边校验并线性分析祖先环

2026-10-16

正反层级索引消费声明式子节点和显式 contains/part_of 等关系边，validate 却只看声明式子节点，真实关系边形成的环会被报告为 issues=0；逐节点重新上溯祖先也反复扫描公共尾链。max_scan 前缀还被误当全库节点集合，制造假的悬空子节点。

以一个层级方向/别名解析器供正索引、反索引和校验共用，统一去重关系；补报显式多父、悬空父与非法边容器。局部扫描仍以全节点快照判断端点存在性。用迭代记忆化分析首父投影的环和入口，保留旧声明式图的报告顺序、路径和缓冲上限。

| 实测 | 未改基线 | 本项修复 |
|---|---|---|
| 实际 2 文件关系环：检出 | False | True |
| 合成元数据链 N=100：源码行事件 | 23094 | 5587 |
| 合成元数据链 N=300：源码行事件 | 189294 | 16787 |
| 新增守卫 | 6 通过 / 6 失败 | 12 通过 / 0 失败 |

## 实际运行

原始基线 `4cc069b3c608ca68fd9efb249343f1c7c46d185d` 的未改副本与本项独立代码分别执行；未叠加另两项核心修复。两平台均 12/12 新增守卫、5/5 具名内存变异检出，恢复后再全绿，0 errors / 0 SKIP。方法计数不冒充生成用例总数。三项组合兼容运行另各 36/36 守卫、15/15 变异。

- windows：7 条完整通过、0 条含内部 SKIP、0 条整体 SKIP、0 失败；逐条原始输出见 results.json 和 ZIP logs。
- linux：7 条完整通过、0 条含内部 SKIP、0 条整体 SKIP、0 失败；逐条原始输出见 results.json 和 ZIP logs。

```bash
python -X utf8 tests/test_hierarchy_audit_graph.py --output fixed.json
python -X utf8 tests/test_hierarchy_audit_graph.py --mutate --output mutations.json
git worktree add --detach ../hierarchy_audit_graph-baseline 4cc069b3c608ca68fd9efb249343f1c7c46d185d
python -X utf8 scripts/replay_hierarchy_audit_graph.py --repo ../hierarchy_audit_graph-baseline --output baseline.json
python -X utf8 scripts/probe_hierarchy_audit_graph.py --repo . --case topology --output native.json
```

Windows 实际使用 `py -3.12 -X utf8`，Linux/WSL 为 `python3 -X utf8`（Python 3.13，原生 /tmp）。每条实际命令、退出码、源码 SHA256、初始失败和明确 SKIP 均保留。原版守卫退出 1 是缺陷复现，errors=0 / SKIP=0；修复/变异入口退出 0。原文兑现探针真实删除隔离库文件，精确故障时点由守卫控制；复杂度探针只有合成元数据，不冒充文件检索评测。

## 具名反面对照

- A1 omit explicit parent-to-child hierarchy edges → `Guards.test_real_edge_only_cycle_is_detected`，指定断言红、errors=0 / SKIP=0。
- A2 reverse historical part-of edge direction → `Guards.test_declared_and_explicit_inverse_agree`，指定断言红、errors=0 / SKIP=0。
- A3 do not memoize resolved ancestor tails → `Guards.test_resolved_tails_have_linear_source_line_work`，指定断言红、errors=0 / SKIP=0。
- A4 discard discovered cycles → `Guards.test_cycle_tail_enters_at_the_correct_member`，指定断言红、errors=0 / SKIP=0。
- A5 confuse the scan prefix with the entire graph → `Guards.test_scan_prefix_does_not_invent_a_dangling_child`，指定断言红、errors=0 / SKIP=0。

冻结旧声明式报告 oracle 只验证兼容性；新缺陷由真实 Markdown 关系环与独立工作量守卫证明。规范化方向、尾链记忆化和局部扫描的 5 个反面对照均由指定断言检出。 未放宽旧断言。变异仅替换内存 callable，源码字节未改；导入错误/异常崩溃不算杀死变异。

## 设计依据、范围与限制

建议 expert：修复的是三个消费面使用不同图模型造成的校验假阴性，同时以可证明终止的线性祖先分析替代反复回溯，并保持历史报告逐项兼容；包含显式边真实记忆库、历史报告 oracle 和具名复杂度退化变异。最终由维护者裁定。

独立于本批层级遍历 PR：本项消费并校验层级模型，不改 expand 的遍历算法；也不重复 PR #343 的缓存换代或生命周期写入修复。

环分析为 O(V)，规范化与整体校验为 O(V+E+R)，R 是实际缓冲的环路径输出长度。多父输入先报错，环诊断沿首父投影，不枚举所有简单环；max_scan 是局部审计。缺索引字段仍沿用既有读文件回退和失败边界，不宣称完整图的强审计证书。元数据行事件是工作量读数，不是端到端或百万性能测试。

共同 CI 前置只将 checkout 的 fetch-depth 设为 0，供既有历史负面对照取原提交；未删改旧断言、未降阈值，不作为独立贡献。新增代码只用 Python 标准库，保留 MIT 许可。

本报告的本地运行不等同 GitHub CI；以 PR 当前 head checks 为准，全部 CI 成功后才发布对应 bounty intake。维护者人审、最终定级与结算均待定。未声称正式榜单名次、百万端到端低延迟或真实私域问答改善。

ZIP 含本项冻结测试、回放/探针、读数、原始日志、MIT 许可和哈希；需配套源码检出，不是整仓离线镜像。
