# 失效传播全局封顶，并按入边生成溯源

2026-10-15

propagate 的 max_nodes 只在每个父节点的内层循环末尾 break，下一父节点仍能继续纳入节点。6 个失效根、每根 1 个孩子、上限 7 时，原版实际访问 12 个、改写 6 个。每个新计划还反扫所有父节点的子列表寻找 via，稀疏图也产生平方级成员比较。

在纳入每个新节点前检查全局预算，跨父节点停止；根节点同样计入预算，并明确返回 visited、roots_admitted、truncated。保持 BFS 深度、doubted 中继可穿过且不重复改写、默认只预演。via 直接读取当前节点已有的 depends_on 入边并与已访问集合相交，替代每条结果对全局邻接的反扫。

| 观察项 | 未修改主线 | 本项修复 |
|---|---|---|
| 6 根 + 6 子，上限 7：实际改写孩子数 | 6 | 1 |
| 同场景唯一访问节点数 | 12 | 7，truncated=True |
| 5001 节点 / 5000 边预演中位 | 152.76 ms | 11.76 ms（约 13.0 倍） |
| 10 个新增守卫 | 3 通过 / 7 失败 | 10 通过 / 0 失败 |

Windows Python 3.12、Linux/WSL Python 3.13 各 **10/10 守卫、4/4 定点变异**，0 errors / 0 SKIP；变异必须由表列断言失败捕获，导入异常、其他运行错误及跳过不计。变异只在内存替换目标实现，执行后重跑全部守卫、核对源码字节未变。

Linux 原生临时目录 8/8 条回归命令通过。Windows 7/8：旧 coldverify 的 fsync 入队耗时超过 5 ms；未改原版同样失败。WSL/NTFS 首轮还因 Windows worktree git 路径与落盘耗时失败，未计通过；用原生临时目录并显式映射 Git 元数据后 8/8 通过，未修改旧断言或放宽阈值。

共同 CI 前置（不单独申报、不重复计入三项核心成果）：主线 run 38586582948 为 490/499、7 SKIP，其中 8 个历史反例守卫在浅检出中取不到引入提交父版本；本轮将 Python CI 的 checkout 改为 fetch-depth: 0。另一个失败来自 issue323 测试夹具的档位环境键，维护者随后已在新主线 96be12cf 修复；本轮合并主线并采用维护者版本，不重复申报该修复。未修改任何断言、历史反例或性能阈值；自治守卫 177/177、issue323 的 5 处旧变异通过，完整历史的 Linux 原生临时目录复核，上述 9 个旧失败入口全部通过。

## 复跑

原版固定为 `10bc96a28e742e04676556e1a6789f7c873ccdce`；只从本 PR 加载新增测试，生产模块来自另一份原版检出。

```bash
git worktree add --detach ../trust_bounded_frontier-baseline 10bc96a28e742e04676556e1a6789f7c873ccdce
python -X utf8 scripts/replay_trust_bounded_frontier.py --repo ../trust_bounded_frontier-baseline --output baseline.json
# 原版应退出 1；上表列出预期失败数，errors=0 / SKIP=0
python -X utf8 tests/test_trust_bounded_frontier.py --output fixed.json
python -X utf8 tests/test_trust_bounded_frontier.py --mutate --output mutations.json
# 修复后两条均退出 0
```

## 具名反面对照

- remove cross-parent cap → `Guards.test_budget_applies_across_parents`
- erase provenance parents → `Guards.test_convergent_parent_provenance`
- stop at doubted bridge → `Guards.test_doubted_bridge_remains_traversable`
- restore quadratic provenance scan → `Guards.test_sparse_provenance_work_is_linear`

## 独立性与可信边界

与旧 PR #168 的 best-first 关系链检索及本轮缓存修复独立：本项是验证态失效的 BFS 巡检，不改检索排序、不改依赖缓存准入；三分支均独立从同一主线开始。

需要同时定义全局资源预算与 BFS 的可达/溯源语义，处理多根、多父收敛、环、doubted 中继、零预算及只降不升的持久化结果，并以工作量断言和同语料配对实跑证明消除平方级扫描。建议 expert，最终由维护者裁定。

max_nodes 限制唯一纳入节点，不是整次调用的 CPU/内存硬配额；定位失效根与冷建依赖索引仍须 O(N+E)，父依赖/根的稳定排序也有排序成本。截断不提供续跑游标；重复以同一预算启动可能命中同一前缀。约 13 倍仅是 5001 节点合成星型图的预演微基准，不是端到端召回/问答或正式榜单成绩。

原始结果见 [results.json](results.json)。公开副本只规范化机器绝对路径及换行；断言、计数、失败/跳过状态保持。随附 [evidence.zip](evidence.zip) 含冻结测试、重放入口、读数与逐文件 SHA256；需要对应源码检出，不是完整仓库或免检出的离线安装包。当前 CI 状态以 PR 当前 head 的 Checks 为准；维护者人审、最终分类与结算待进行。
