# fix(reach): 损坏派生快照先完整校验再原子装载

2026-10-15

ReachIndex.load 只校验版本和 JSON 根，随后直接 .items/list/float；同版本快照中的错误容器或时间戳让正常 search 抛 AttributeError/ValueError，字符串还会被拆成逐字符路径。

在装载任何状态之前校验 post/adj/hashes/sem 的容器与成员、有限时间戳和指纹类型；拒绝文件后由既有路径重建或回退全量。失败装载保留实例原状态，覆盖极大整数时间戳。

| 测量 | 原始主线 | 修复后 |
|---|---|---|
| post 错容器后的真实检索 | AttributeError | 命中 a，无异常 |
| built_at 错类型后的真实检索 | ValueError | 命中 a，无异常 |
| 非法快照装载后实例 | 可部分覆盖/抛异常 | 拒绝且原状态保留 |
| 新增守卫 | 3 通过 / 10 失败 | 13 通过 / 0 失败 |

## 运行证据

- 基线 `fffa4f29572236d5a75cc592ea6e6edb7c0e10bf`；五个分支独立从该主线起步，未叠加另外四项功能。
- Windows Python 3.12 / Linux WSL Python 3.13，各 13/13 新增守卫通过、4/4 定点变异被指定断言检出；errors=0 / SKIP=0。恢复后守卫再次全绿。
- 变异在内存替换目标 callable，源码字节保持不变。每项记录锚点、具体断言、红项和源码 SHA256；不把异常崩溃算作成功杀死变异。
- native 对照实际创建临时记忆库和 Markdown 文件；时效对照使用真实墙钟跨越截止点，无模拟时钟。守卫中的精确边界案例另使用受控时钟，不混淆两类证据。
- windows: 5 / 5 条相关回归命令通过，失败 0，缺件 0。逐条命令、退出码、原始日志引用见 results.json。
- linux: 5 / 5 条相关回归命令通过，失败 0，缺件 0。逐条命令、退出码、原始日志引用见 results.json。

```bash
python -X utf8 tests/test_reach_snapshot_admission.py
python -X utf8 tests/test_reach_snapshot_admission.py --mutate
python -X utf8 scripts/replay_reach_snapshot_admission.py --repo <untouched-baseline> --output baseline.json
python -X utf8 scripts/probe_reach_snapshot_admission.py --repo . --output native-fixed.json
```

第一条命令期望退出码 0，13 通过 / 0 失败；变异入口期望 4 通过 / 0 失败。原版回放退出码 1 是预期缺陷复现，原始分项读数见 results.json。

## 资格、信任边界与范围

意图：ReachIndex.load 只校验版本和 JSON 根，随后直接 .items/list/float；同版本快照中的错误容器或时间戳让正常 search 抛 AttributeError/ValueError，字符串还会被拆成逐字符路径。 预期结果：在装载任何状态之前校验 post/adj/hashes/sem 的容器与成员、有限时间戳和指纹类型；拒绝文件后由既有路径重建或回退全量。失败装载保留实例原状态，覆盖极大整数时间戳。

只保证派生快照结构准入与安全回退，不把快照当作经签名的权威数据。结构合法但被有意改写的 postings 不由本项认证；不承诺抵御同权限本地文件篡改或消除 JSON 全量读取成本。

独立于 PR #238 的主 _index.json 快照准入：本项修复可选 reach 的 _reach_index.json，消费入口和失效/重建实现均独立。

建议 expert，依据是检索加速器的持久化准入、实例状态原子性和全量回退契约共同闭合，并用真实生产 search 和原始快照文件证明失败不会升级为检索中断；最终档位由维护者裁定。

## 公共前置与尚待确认

共同 CI 前置：主线 fffa4f29 的 Python run 38728140166 实际为 501/509 通过、7 个入口 SKIP，8 个失败均是既有历史负面对照在浅克隆取不到原始提交。各分支仅将 checkout 的 fetch-depth 设为 0；沿用上一轮已经验证的完整历史修法，不删除断言、不降低阈值，不作为五项之外的新贡献申报。

当前提交的 GitHub CI 状态以 PR 的当前 head checks 为准；本报告的本地通过不等同 CI 通过。bounty intake 只在当前 head 全部 CI 通过后发布。第④闸维护者人审待定，未自行认证验收、授级或结算。

入口级 PASS 也不代表可选依赖的内部子分支全部执行；未运行正式外部榜单、生产宿主问答或百万节点端到端并发测试。

证据包 evidence.zip 包含冻结守卫、回放/探针、读数和哈希清单；需要配套源码检出及标准库运行环境，不是完整仓库的离线镜像。
