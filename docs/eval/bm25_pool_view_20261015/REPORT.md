# perf(bm25): 热检索借用只读候选视图，去掉全池复制

2026-10-15

候选池虽已缓存且 BM25 可复用词项统计，内部每次查询仍用 _PoolEntries 复制 N 个候选引用；百万规模的热查询因此保留 O(N) 容器分配成本。

内部检索借用带 pool_key 的只读 Sequence 视图，缓存命中借用为 O(1)；公开 candidate_pool 继续返回可独立修改的 list，保留 #153 的防别名污染边界。写入/角色/时间资格仍沿用原失效判据。

| 测量 | 原始主线 | 修复后 |
|---|---|---|
| 1000 个真实 Markdown 节点，9 次热查复制引用 | 9000 | 0 |
| 百万候选元数据：借用中位 | 15.7014 ms | 0.0033 ms |
| 百万候选元数据：单次额外分配峰值 | 8,000,892 bytes | 1,316 bytes |
| 新增守卫 | 5 通过 / 3 失败 | 8 通过 / 0 失败 |

## 运行证据

- 原始开发基线 fffa4f29；五个独立分支随后同步 `5cd2b43ffb50f552a94cf516f1cd970156ff7397`，再在其未修改副本重放对照。未叠加另外四项核心功能，上游的新增修复不计入本项收益。
- Windows Python 3.12 / Linux WSL Python 3.13，各 8/8 新增守卫通过、4/4 定点变异被指定断言检出；errors=0 / SKIP=0。恢复后守卫再次全绿。
- 变异在内存替换目标 callable，源码字节保持不变。每项记录锚点、具体断言、红项和源码 SHA256；不把异常崩溃算作成功杀死变异。
- native 对照实际创建临时记忆库和 Markdown 文件；时效对照使用真实墙钟跨越截止点，无模拟时钟。守卫中的精确边界案例另使用受控时钟，不混淆两类证据。
- windows: 6 / 6 条相关回归命令通过，失败 0，缺件 0。逐条命令、退出码、原始日志引用见 results.json。
- linux: 6 / 6 条相关回归命令通过，失败 0，缺件 0。逐条命令、退出码、原始日志引用见 results.json。

```bash
python -X utf8 tests/test_bm25_pool_view.py
python -X utf8 tests/test_bm25_pool_view.py --mutate
python -X utf8 scripts/replay_bm25_pool_view.py --repo <untouched-baseline> --output baseline.json
python -X utf8 scripts/probe_bm25_pool_view.py --repo . --output native-fixed.json
```

第一条命令期望退出码 0，8 通过 / 0 失败；变异入口期望 4 通过 / 0 失败。原版回放退出码 1 是预期缺陷复现，原始分项读数见 results.json。

## 资格、信任边界与范围

意图：候选池虽已缓存且 BM25 可复用词项统计，内部每次查询仍用 _PoolEntries 复制 N 个候选引用；百万规模的热查询因此保留 O(N) 容器分配成本。 预期结果：内部检索借用带 pool_key 的只读 Sequence 视图，缓存命中借用为 O(1)；公开 candidate_pool 继续返回可独立修改的 list，保留 #153 的防别名污染边界。写入/角色/时间资格仍沿用原失效判据。

百万测量只覆盖合成元数据的热候选容器借用，不含文件 I/O、打分、融合或端到端检索；冷过滤仍 O(N)，公开可变 list API 仍有 O(N) 防御性复制。1000 个真实文件热查只观察到微小差异，不宣称端到端千倍提升。元素 dict 沿用只读约定；视图不构成线程安全或深不可变对象。

独立于已合入的 BM25 稀疏词项/块上界算法：本项不改打分、剪枝或词项统计，也未启用其他可选默认开关。

建议 expert，依据是把百万规模热路径从全量分配改为常数时间借用，同时保留外部可变 API、统计缓存身份、访问范围和写入代际的兼容性；提供工作量断言、分配读数与不同规模配对。最终由维护者裁定。

## 公共前置与尚待确认

共同 CI 前置：主线 fffa4f29 的 Python run 38728140166 实际为 501/509 通过、7 个入口 SKIP，8 个失败均是既有历史负面对照在浅克隆取不到原始提交。各分支仅将 checkout 的 fetch-depth 设为 0；沿用上一轮已经验证的完整历史修法，不删除断言、不降低阈值，不作为五项之外的新贡献申报。

当前提交的 GitHub CI 状态以 PR 的当前 head checks 为准；本报告的本地通过不等同 CI 通过。bounty intake 只在当前 head 全部 CI 通过后发布。第④闸维护者人审待定，未自行认证验收、授级或结算。

入口级 PASS 也不代表可选依赖的内部子分支全部执行；未运行正式外部榜单、生产宿主问答或百万节点端到端并发测试。

证据包 evidence.zip 包含冻结守卫、回放/探针、读数和哈希清单；需要配套源码检出及标准库运行环境，不是完整仓库的离线镜像。

百万池微基准：`python -X utf8 scripts/bench_bm25_pool_view.py --repo . --output pool-bench.json`。需与原始源码分别进程运行，语料 SHA256 相同。分配峰值为 Python tracemalloc 的单次额外分配，不是系统 RSS。

旧 Windows BM25 全套变异初跑 180 秒超时，原记录保留为 initial_attempts；使用 900 秒限时的完整复跑结果单列，未放宽内部断言或阈值。
