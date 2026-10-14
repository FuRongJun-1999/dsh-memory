# 派生检索视图随元数据写入与重建换代

2026-10-15

append_edge 已成功落盘，但预热的因果邻接仍为空；相同查询命中旧热缓存并漏掉新关系目标。手动清空缓存后立即恢复。verification/lifecycle 元数据更新及 rebuild_index 也不一定经过 _set_index_entry，因此旧代缓存键未变化，能继续返回旧验证态、层级和依赖关系。

在 MdCG 基类收敛 O(1) 代际见证：节点映射的身份、脏集对象身份及单调 write_gen；保留强引用，以 is 比较，避免整字典比较和对象 id 复用。RRF 查询键、因果邻接、层级双向索引与依赖反查都校验该代际。既有显式失效保留，不在查询前全库哈希；未变化的读仍复用缓存。

| 观察项 | 未修改主线 | 本项修复 |
|---|---|---|
| 新增因果边后，预热链返回链数 | 0；手动清缓存后 1 | 直接 1 |
| 新增图关系后，同查询结果 | 仅 seed，cached=True | seed + tail，cached=False |
| 验证态更新后的热查询节点元数据 | unverified | verified |
| 12 个新增守卫 | 1 通过 / 11 失败 | 12 通过 / 0 失败 |

Windows Python 3.12、Linux/WSL Python 3.13 各 **12/12 守卫、5/5 定点变异**，0 errors / 0 SKIP；变异必须由表列断言失败捕获，导入异常、其他运行错误及跳过不计。变异只在内存替换目标实现，执行后重跑全部守卫、核对源码字节未变。

Windows 14/14、Linux 14/14 条定向回归命令通过，含旧代际守卫、读缓存精确失效、关系链变异、会话隔离、生命周期和运行时吊销。

## 复跑

原版固定为 `10bc96a28e742e04676556e1a6789f7c873ccdce`；只从本 PR 加载新增测试，生产模块来自另一份原版检出。

```bash
git worktree add --detach ../derived_cache_generations-baseline 10bc96a28e742e04676556e1a6789f7c873ccdce
python -X utf8 scripts/replay_derived_cache_generations.py --repo ../derived_cache_generations-baseline --output baseline.json
# 原版应退出 1；上表列出预期失败数，errors=0 / SKIP=0
python -X utf8 tests/test_derived_cache_generations.py --output fixed.json
python -X utf8 tests/test_derived_cache_generations.py --mutate --output mutations.json
# 修复后两条均退出 0
```

## 具名反面对照

- ignore dirty generation → `Guards.test_append_edge_refreshes_chain`
- ignore chain generation → `Guards.test_append_edge_refreshes_chain`
- omit query generation witness → `Guards.test_verification_change_refreshes_query`
- omit hierarchy generation → `Guards.test_rebuild_refreshes_both_hierarchy_directions`
- ignore dependency generation → `Guards.test_rebuild_refreshes_dependency_index`

## 独立性与可信边界

补足主线 #153/#153b 的代际机制：旧实现覆盖 _set_index_entry，本项覆盖元数据写及 rebuild，并约束图/依赖视图。不是重复提交已解决的新节点写入失效问题；不包含另两项的时间候选或传播算法修改。

涉及多个写入出口与多种派生视图的一致性契约，需同时覆盖元数据原地更新、索引整体重建、普通/安全读路径和热缓存命中率，避免用禁用缓存或全清掩盖问题。建议 expert，最终由维护者裁定。

受支持写路径必须推进 _dirty 或替换节点映射；不承诺检测绕过这些路径的任意内存篡改、未触发重载的外部文件编辑、读缓存既有跨进程可见性边界，或新增线程安全。写后第一次查询仍需重建被影响的派生视图；该修复没有改缓存 TTL、可见性裁决或真实准确率。

原始结果见 [results.json](results.json)。公开副本只规范化机器绝对路径及换行；断言、计数、失败/跳过状态保持。随附 [evidence.zip](evidence.zip) 含冻结测试、重放入口、读数与逐文件 SHA256；需要对应源码检出，不是完整仓库或免检出的离线安装包。当前 CI 状态以 PR 当前 head 的 Checks 为准；维护者人审、最终分类与结算待进行。
