# 状态投影：按查询实际需要构造结果

`stg.state_chain()` 的缺省参数是 `history=True, limit=50`。旧路径读入整个
`_state_events.jsonl`，保留原始事件列表和分组列表，为全部命中单元构造结果及
七字段历史，再截取前 50 条。只查询现值或统计时，也保留了全部事件。

## 实现与边界

- `state_events.iter_read()` 与 `read()` 共用解析、过滤和坏行诊断。
  `read()` 的返回类型与 limit 切片语义保持原样，包括负数。
- 现值投影按 `(subject, slot)` 保存事件计数、最后有值事件的必要字段与最终
  撤回端点；撤回后释放旧值。统计只保存主体/槽位集合和每单元最后撤回标记。
- 完整历史查询使用迭代读取分组，避免额外原始事件总列表；回放一组即释放其
  原始记录。被剔除的退役单元不构造历史。
- `project_page()` 返回 `(total, items)`，按原稳定排序只为前 limit 条单元
  构造结果及历史。`project()` 仍返回全量列表；`state_chain()` 使用分页入口。
  `total` 是截断前精确总数，未返回的单元仍参与计数。
- 所有路径完整消费一次台账，包括 limit=0：文件尾坏行仍告警和累计。
  无缓存、无派生文件、无新增依赖；追加事件在下一次查询立即可见。

事件数为 N，单元数为 S。现值查询的保留空间为 O(S + 返回值大小)，统计为
O(S)。完整历史路径仍需 O(N) 原始事件分组空间，也仍需读取和解析全部 N 条
事件；本改动不提供索引。只减少重复驻留、未返回历史及未返回结果的构造工作。
完整历史必须返回的内容本身所占内存无法省去。大型单行仍需完整解析。

本功能的 MCP 读面仍受 `MDCG_STG_STATE=1` 控制，缺省关闭；CLI 不受该开关
限制。这里的默认查询指启用后 `state_chain()` 的参数缺省路径，不代表所有
记忆召回请求。MCP 现有 `limit=0` 会归一为 50；直接 `state_chain(limit=0)`
则只返回计数，本改动保留这两种既有行为。

## 复现

使用 Python 标准库，在两个同版本基线 checkout 间比较，例如：

```text
git worktree add --detach ../state-baseline 5cd2b43ffb50f552a94cf516f1cd970156ff7397
python -X utf8 -m unittest md_cg.test_state_projection_streaming
python -X utf8 -m md_cg.test_state_slots --mutate
python -X utf8 -m md_cg.test_issue375_state_slot_retire --mutate
python -X utf8 scripts/benchmark_state_projection.py --baseline ../state-baseline --cases large_dense large_unique minimal_retired_unique --rounds 11
```

不并行运行基准。时间为正常 GC、暖文件缓存、随机 A/B 顺序的配对批次，计入
结果释放；OS 进程峰值由各自全新子进程首个查询测量，tracemalloc 另测。
返回结果的完整 SHA256 必须一致。输出 JSON 保留每轮耗时及候选源码校验值。
可省略 `--cases` 执行 16 种负载；`--rounds 41` 用于复核可疑项。

配对 bootstrap 区间描述该次机器与夹具上的不确定性，不代表跨环境安全概率。
合成夹具不能代表所有真实流量；微小请求、几乎无匹配的筛选、大返回值可能
收益有限或略慢。合并前应按使用场景评估，无需为本优化改变 history 缺省值。

## 测量记录

脱敏后的原始配对样本、返回值 SHA256、两种内存读数及定点 41 轮确认保存在
[`benchmarks/state_projection_results.json`](benchmarks/state_projection_results.json)。
夹具均为脚本生成的合成数据；记录不包含本机路径、账号、主机标识或命令日志。
Windows 与 WSL2 在同一物理机器上运行。源文件校验值同时记录测量时的原始字节
与统一换行后的内容，便于区分 checkout 行尾差异。
