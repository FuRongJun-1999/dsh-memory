# fix(time): 显式时区按绝对时刻解析并拒收非有限端点

2026-10-16

带 Z 的日期被当作本地时区，UTC+8 主机偏移 28800 秒；显式 offset 被当成不可解析，观察轴漏召回、效力轴失效期限变成 unknown。

在 trust.parse_time 这个统一读入口用标准库解析带时区 ISO 8601；无时区日期保留既有本地语义。数值归一先拒收 NaN/Infinity/float 溢出，允许合法别名继续回落。

| 测量 | 原始主线 | 修复后 |
|---|---|---|
| UTC+8 主机解析 Z 的偏移 | −28800 秒 | 0 秒 |
| offset 观察窗真实命中 | 0 | 1 |
| offset 截止点越过后 | unknown | expired |
| 新增守卫 | 3 通过 / 11 失败 | 14 通过 / 0 失败 |

## 运行证据

- 原始开发基线 fffa4f29；五个独立分支随后同步 `5cd2b43ffb50f552a94cf516f1cd970156ff7397`，再在其未修改副本重放对照。未叠加另外四项核心功能，上游的新增修复不计入本项收益。
- Windows Python 3.12 / Linux WSL Python 3.13，各 14/14 新增守卫通过、6/6 定点变异被指定断言检出；errors=0 / SKIP=0。恢复后守卫再次全绿。
- 变异在内存替换目标 callable，源码字节保持不变。每项记录锚点、具体断言、红项和源码 SHA256；不把异常崩溃算作成功杀死变异。
- native 对照实际创建临时记忆库和 Markdown 文件；时效对照使用真实墙钟跨越截止点，无模拟时钟。守卫中的精确边界案例另使用受控时钟，不混淆两类证据。
- windows: 7 / 7 条相关回归命令通过，失败 0，缺件 0。逐条命令、退出码、原始日志引用见 results.json。
- linux: 7 / 7 条相关回归命令通过，失败 0，缺件 0。逐条命令、退出码、原始日志引用见 results.json。

```bash
python -X utf8 tests/test_canonical_timezones.py
python -X utf8 tests/test_canonical_timezones.py --mutate
python -X utf8 scripts/replay_canonical_timezones.py --repo <untouched-baseline> --output baseline.json
python -X utf8 scripts/probe_canonical_timezones.py --repo . --output native-fixed.json
```

第一条命令期望退出码 0，14 通过 / 0 失败；变异入口期望 6 通过 / 0 失败。原版回放退出码 1 是预期缺陷复现，原始分项读数见 results.json。

## 资格、信任边界与范围

意图：带 Z 的日期被当作本地时区，UTC+8 主机偏移 28800 秒；显式 offset 被当成不可解析，观察轴漏召回、效力轴失效期限变成 unknown。 预期结果：在 trust.parse_time 这个统一读入口用标准库解析带时区 ISO 8601；无时区日期保留既有本地语义。数值归一先拒收 NaN/Infinity/float 溢出，允许合法别名继续回落。

无时区日期仍依赖宿主本地时区，避免静默改变旧数据语义；毫秒识别阈值沿用原口径。本项不迁移历史文件，不扩展日期自然语言理解。

独立于 PR #342 的 STG 区间候选集合；本项是时间值解析与非有限值准入，未采用该 PR 的索引改动。

建议 expert，依据是统一时间入口同时承载观察轴过滤、效力有效期、别名回落及跨平台时间语义，需要证明修 UTC 不能破坏本地旧格式或数值单位；最终档位与影响由维护者裁定。

## 公共前置与尚待确认

共同 CI 前置：主线 fffa4f29 的 Python run 38728140166 实际为 501/509 通过、7 个入口 SKIP，8 个失败均是既有历史负面对照在浅克隆取不到原始提交。各分支仅将 checkout 的 fetch-depth 设为 0；沿用上一轮已经验证的完整历史修法，不删除断言、不降低阈值，不作为五项之外的新贡献申报。

当前提交的 GitHub CI 状态以 PR 的当前 head checks 为准；本报告的本地通过不等同 CI 通过。bounty intake 只在当前 head 全部 CI 通过后发布。第④闸维护者人审待定，未自行认证验收、授级或结算。

入口级 PASS 也不代表可选依赖的内部子分支全部执行；未运行正式外部榜单、生产宿主问答或百万节点端到端并发测试。

证据包 evidence.zip 包含冻结守卫、回放/探针、读数和哈希清单；需要配套源码检出及标准库运行环境，不是完整仓库的离线镜像。

回归修复记录：初轮拒收非有限值令既有 STG 保守候选与扫描计数断言转红，已保留观察轴索引和扫描的原非有限不确定性规则，补 T5/T6 反证；查询入参与效力端点仍要求有限值。既有 test_stgidx_index_parity 断言保持不变并补入相关回归。旧时间核审计初跑 180 秒超时，按其文档给足 900 秒后通过，原超时未计通过。
