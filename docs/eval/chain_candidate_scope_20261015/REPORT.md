# fix(chain): 因果检索全路径限制在本次候选子图内

2026-10-15

RRF chain 只在最终输出过滤候选，路径中间节点仍来自全图；隐藏分支、工作角色、过期记忆、其他层/会话能充当桥梁，把本不该经它们推导的终点带回主支。

把已有候选资格投影为诱导子图，限制起点、所有中继与终点；best-first 与旧回退路径共用该约束。直接因果/解释 API 缺省不加 scope，保留旧行为，查询投影不污染全图缓存。

| 测量 | 原始主线 | 修复后 |
|---|---|---|
| 主支真实 RRF 结果 | seed + tail（经隐藏 bridge） | 仅 seed |
| 显式选实验分支 | seed / bridge / tail | 三者继续可达 |
| 隐藏中继消耗边扫描/节点预算 | 可扫描/纳入 | 0 边 / 仅 seed |
| 新增守卫 | 4 通过 / 10 失败 | 14 通过 / 0 失败 |

## 运行证据

- 原始开发基线 fffa4f29；五个独立分支随后同步 `5cd2b43ffb50f552a94cf516f1cd970156ff7397`，再在其未修改副本重放对照。未叠加另外四项核心功能，上游的新增修复不计入本项收益。
- Windows Python 3.12 / Linux WSL Python 3.13，各 14/14 新增守卫通过、4/4 定点变异被指定断言检出；errors=0 / SKIP=0。恢复后守卫再次全绿。
- 变异在内存替换目标 callable，源码字节保持不变。每项记录锚点、具体断言、红项和源码 SHA256；不把异常崩溃算作成功杀死变异。
- native 对照实际创建临时记忆库和 Markdown 文件；时效对照使用真实墙钟跨越截止点，无模拟时钟。守卫中的精确边界案例另使用受控时钟，不混淆两类证据。
- windows: 7 / 7 条相关回归命令通过，失败 0，缺件 0。逐条命令、退出码、原始日志引用见 results.json。
- linux: 7 / 7 条相关回归命令通过，失败 0，缺件 0。逐条命令、退出码、原始日志引用见 results.json。

```bash
python -X utf8 tests/test_chain_candidate_scope.py
python -X utf8 tests/test_chain_candidate_scope.py --mutate
python -X utf8 scripts/replay_chain_candidate_scope.py --repo <untouched-baseline> --output baseline.json
python -X utf8 scripts/probe_chain_candidate_scope.py --repo . --output native-fixed.json
```

第一条命令期望退出码 0，14 通过 / 0 失败；变异入口期望 4 通过 / 0 失败。原版回放退出码 1 是预期缺陷复现，原始分项读数见 results.json。

## 资格、信任边界与范围

意图：RRF chain 只在最终输出过滤候选，路径中间节点仍来自全图；隐藏分支、工作角色、过期记忆、其他层/会话能充当桥梁，把本不该经它们推导的终点带回主支。 预期结果：把已有候选资格投影为诱导子图，限制起点、所有中继与终点；best-first 与旧回退路径共用该约束。直接因果/解释 API 缺省不加 scope，保留旧行为，查询投影不污染全图缓存。

直接 expand_from_seeds / walk 在 allowed_ids=None 时保留全图语义；本项只约束 RRF 已选候选，未新定义授权规则。全局邻接冷建仍 O(N+E)，预算用尽仍为 best effort，不声称全局最优证书或线程安全。

独立于 PR #168 的最强链排序和 PR #343 的缓存换代；本项改的是“哪些中继可以参与本次推理”，不改边权或置信评分。

建议 expert，依据是关系链检索资格必须对路径闭包成立，而非只对输出集合成立；需同时维持 best-first 支配/预算、逆向 walk、层级边及非单调兼容回退，并保留直接 API 的既有语义。最终由维护者裁定。

## 公共前置与尚待确认

共同 CI 前置：主线 fffa4f29 的 Python run 38728140166 实际为 501/509 通过、7 个入口 SKIP，8 个失败均是既有历史负面对照在浅克隆取不到原始提交。各分支仅将 checkout 的 fetch-depth 设为 0；沿用上一轮已经验证的完整历史修法，不删除断言、不降低阈值，不作为五项之外的新贡献申报。

当前提交的 GitHub CI 状态以 PR 的当前 head checks 为准；本报告的本地通过不等同 CI 通过。bounty intake 只在当前 head 全部 CI 通过后发布。第④闸维护者人审待定，未自行认证验收、授级或结算。

入口级 PASS 也不代表可选依赖的内部子分支全部执行；未运行正式外部榜单、生产宿主问答或百万节点端到端并发测试。

证据包 evidence.zip 包含冻结守卫、回放/探针、读数和哈希清单；需要配套源码检出及标准库运行环境，不是完整仓库的离线镜像。
