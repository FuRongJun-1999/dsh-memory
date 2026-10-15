# fix(cache): 时效检索随当前时钟重新筛选并补足 Top-K

2026-10-15

validity=True 的结果仍写入 300 秒热缓存。截止点越过后基础层继续返回已过期 Top-1；安全包装层虽剔除过期项，却返回空列表，不能补入排在后面的有效记忆。

将 validity 查询纳入已有的双侧结果缓存绕行条件；每次按当前时钟构建候选、排序和选 Top-K，读缓存仍可复用。普通查询继续命中结果缓存。

| 测量 | 原始主线 | 修复后 |
|---|---|---|
| 真实时钟越过截止点后的 Top-1 | a_expiring（错误旧值） | z_stable |
| 安全包装层过期后 Top-1 | 空集（未补位） | z_stable |
| 普通查询热缓存 | 可命中 | 继续可命中 |
| 新增守卫 | 4 通过 / 5 失败 | 9 通过 / 0 失败 |

## 运行证据

- 基线 `fffa4f29572236d5a75cc592ea6e6edb7c0e10bf`；五个分支独立从该主线起步，未叠加另外四项功能。
- Windows Python 3.12 / Linux WSL Python 3.13，各 9/9 新增守卫通过、3/3 定点变异被指定断言检出；errors=0 / SKIP=0。恢复后守卫再次全绿。
- 变异在内存替换目标 callable，源码字节保持不变。每项记录锚点、具体断言、红项和源码 SHA256；不把异常崩溃算作成功杀死变异。
- native 对照实际创建临时记忆库和 Markdown 文件；时效对照使用真实墙钟跨越截止点，无模拟时钟。守卫中的精确边界案例另使用受控时钟，不混淆两类证据。
- windows: 6 / 6 条相关回归命令通过，失败 0，缺件 0。逐条命令、退出码、原始日志引用见 results.json。
- linux: 6 / 6 条相关回归命令通过，失败 0，缺件 0。逐条命令、退出码、原始日志引用见 results.json。

```bash
python -X utf8 tests/test_live_validity_cache.py
python -X utf8 tests/test_live_validity_cache.py --mutate
python -X utf8 scripts/replay_live_validity_cache.py --repo <untouched-baseline> --output baseline.json
python -X utf8 scripts/probe_live_validity_cache.py --repo . --output native-fixed.json
```

第一条命令期望退出码 0，9 通过 / 0 失败；变异入口期望 3 通过 / 0 失败。原版回放退出码 1 是预期缺陷复现，原始分项读数见 results.json。

## 资格、信任边界与范围

意图：validity=True 的结果仍写入 300 秒热缓存。截止点越过后基础层继续返回已过期 Top-1；安全包装层虽剔除过期项，却返回空列表，不能补入排在后面的有效记忆。 预期结果：将 validity 查询纳入已有的双侧结果缓存绕行条件；每次按当前时钟构建候选、排序和选 Top-K，读缓存仍可复用。普通查询继续命中结果缓存。

显式 validity 查询牺牲结果缓存命中率以保证当前时钟资格；读取缓存、BM25 词项缓存仍照常工作。未提供多线程一致时间快照，也不改变 not_yet 保留或截止点相等仍有效的既有规则。

独立于 PR #343 的元数据写入/重建代际：本项全过程文件与索引没有变化，唯一变化是时钟越过截止点。

建议 expert，依据是基础层、Secure 最终过滤层、BM25 候选缓存与结果缓存对同一时效资格的不同消费必须闭合；实际复现了“过滤掉旧结果仍无法补位”的跨层错答。修复行数较少，最终难度与影响由维护者裁定。

## 公共前置与尚待确认

共同 CI 前置：主线 fffa4f29 的 Python run 38728140166 实际为 501/509 通过、7 个入口 SKIP，8 个失败均是既有历史负面对照在浅克隆取不到原始提交。各分支仅将 checkout 的 fetch-depth 设为 0；沿用上一轮已经验证的完整历史修法，不删除断言、不降低阈值，不作为五项之外的新贡献申报。

当前提交的 GitHub CI 状态以 PR 的当前 head checks 为准；本报告的本地通过不等同 CI 通过。bounty intake 只在当前 head 全部 CI 通过后发布。第④闸维护者人审待定，未自行认证验收、授级或结算。

入口级 PASS 也不代表可选依赖的内部子分支全部执行；未运行正式外部榜单、生产宿主问答或百万节点端到端并发测试。

证据包 evidence.zip 包含冻结守卫、回放/探针、读数和哈希清单；需要配套源码检出及标准库运行环境，不是完整仓库的离线镜像。
