# STG 区间时间候选：补回包含与重叠记忆

2026-10-15

开启 MDCG_STG_INDEX 后，anchors 的时间候选只按起点落窗取数。观察区间 [100,300]、[100,205] 均应命中查询 [200,210]，但被候选层提前剔除；默认关闭的全量路径有 3 条，开启后只有 1 条。

保留既有起点分块索引；为非点区间增加按终点排序的块，并维护每块的最小起点。起点落窗的候选直接保留，再取 start<lo 且 end>=lo 的跨界区间；块的终点上界与最小起点共同剪枝。NaN/非有限终点保守纳入，最终仍由 stg.time_relation 精判，物理序、会话/层交集与 broken 回退保留。插删与块分裂/合并同步维护摘要，未引入第三方依赖。

| 观察项 | 未修改主线 | 本项修复 |
|---|---|---|
| 实际 anchors 返回条数（关闭→开启索引） | 3 → 1 | 3 → 3 |
| 5 万条、100 个窗口完整命中窗口数 | 0/100 | 100/100 |
| 同一合成语料命中总数 | 1100 / 应有 6031 | 6031 / 应有 6031 |
| 13 个新增守卫 | 3 通过 / 10 失败 | 13 通过 / 0 失败 |

Windows Python 3.12、Linux/WSL Python 3.13 各 **13/13 守卫、7/7 定点变异**，0 errors / 0 SKIP；变异必须由表列断言失败捕获，导入异常、其他运行错误及跳过不计。变异只在内存替换目标实现，执行后重跑全部守卫、核对源码字节未变。

Windows 最终 7/7 条回归命令；Linux 原生临时目录 7/7，含旧 STG 51 条断言与 17 处定点变异。初次 Windows 旧变异运行撞上源码修改窗口，结果作废；固定源码后 17/17 已重跑通过。WSL 直接在 NTFS 临时目录运行曾超时，未计通过。

共同 CI 前置（不单独申报、不重复计入三项核心成果）：主线 run 38586582948 为 490/499、7 SKIP，其中 8 个历史反例守卫在浅检出中取不到引入提交父版本；Python CI 的 checkout 改为 fetch-depth: 0。另一个失败来自 issue323 测试夹具重复写档位环境键，改为引用 autonomy_modes 的唯一键常量，未修改任何断言、历史反例或性能阈值；本地自治守卫已从 176/177 恢复到 177/177，issue323 的 5 处旧变异仍通过。

## 复跑

原版固定为 `10bc96a28e742e04676556e1a6789f7c873ccdce`；只从本 PR 加载新增测试，生产模块来自另一份原版检出。

```bash
git worktree add --detach ../stg_interval_candidates-baseline 10bc96a28e742e04676556e1a6789f7c873ccdce
python -X utf8 scripts/replay_stg_interval_candidates.py --repo ../stg_interval_candidates-baseline --output baseline.json
# 原版应退出 1；上表列出预期失败数，errors=0 / SKIP=0
python -X utf8 tests/test_stg_interval_candidates.py --output fixed.json
python -X utf8 tests/test_stg_interval_candidates.py --mutate --output mutations.json
# 修复后两条均退出 0
```

## 具名反面对照

- audit only endpoint keys → `Guards.test_endpoint_start_audit_checks_values`
- reverse block-start pruning → `Guards.test_native_contains_and_overlap`
- start-only subset → `Guards.test_native_contains_and_overlap`
- ignore long interval ends → `Guards.test_native_contains_and_overlap`
- omit endpoint insertion → `Guards.test_native_contains_and_overlap`
- retain stale interval end → `Guards.test_incremental_endpoint_replacement`
- drop uncertain endpoints → `Guards.test_nonfinite_endpoint_is_conservative`

## 独立性与可信边界

与原 PR #241 的平方根分块插删优化分开：本项改变时间候选的区间语义，原分块容器作为已在主线的前置能力使用，不重复申报旧性能成果。

需要证明候选是完整时间关系命中集的保守超集，同时维护双端点、分块摘要、动态增删、毫秒归一、非有限值、物理序及安全回退；不是扩大固定候选窗口。建议 expert，最终由维护者裁定。

这是正确性修复，不能声称比漏读版更快。5 万条微基准：建表中位 129.03→162.74 ms；100 次查询和精判中位 1.40→5.54 ms，修复版多处理了原先漏掉的 4931 个真命中。块剪枝最坏仍可能扫描全部区间；额外空间 O(I)，I 为非点区间数。默认索引开关未改，未测试百万条、线上并发、真实私域语料或正式榜单。

原始结果见 [results.json](results.json)。公开副本只规范化机器绝对路径及换行；断言、计数、失败/跳过状态保持。随附 [evidence.zip](evidence.zip) 含冻结测试、重放入口、读数与逐文件 SHA256；需要对应源码检出，不是完整仓库或免检出的离线安装包。当前 CI 状态以 PR 当前 head 的 Checks 为准；维护者人审、最终分类与结算待进行。
