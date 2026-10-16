# fix(bm25): 读源失效后重算语料并补足可读 Top-K

2026-10-16

BM25 先取前 50 名再读取原文。原文在两步之间消失时，只删除失效索引项并直接返回余下 49 条；明明仍有足够匹配记忆，却不能在本次查询补位，幸存项分数也仍来自旧语料统计。

把排名与原文读取收口为有限的重算过程：剔除本轮不可读文档，更新语料文档数、平均长度与 IDF，再求 Top-K；成功读取的本轮候选可复用，每轮只保留当前榜单至多 LIMIT 份载荷。每次重试至少移除一个文档，无进展则走既有词法回退。

| 实测 | 未改基线 | 本项修复 |
|---|---|---|
| 53 文件中排名后删除 1 个原文：本次返回 | 49 | 50 |
| 与重新打开库的 50 条 oracle 一致 | False | True |
| 该故障场景 posting_visits（代价） | 106 | 210 |
| 新增守卫 | 3 通过 / 9 失败 | 12 通过 / 0 失败 |

## 实际运行

原始基线 `4cc069b3c608ca68fd9efb249343f1c7c46d185d` 的未改副本与本项独立代码分别执行；未叠加另两项核心修复。两平台均 12/12 新增守卫、5/5 具名内存变异检出，恢复后再全绿，0 errors / 0 SKIP。方法计数不冒充生成用例总数。三项组合兼容运行另各 36/36 守卫、15/15 变异。

- windows：8 条完整通过、0 条含内部 SKIP、0 条整体 SKIP、0 失败；逐条原始输出见 results.json 和 ZIP logs。
- linux：7 条完整通过、1 条含内部 SKIP、0 条整体 SKIP、0 失败；逐条原始输出见 results.json 和 ZIP logs。

```bash
python -X utf8 tests/test_bm25_hydration_refill.py --output fixed.json
python -X utf8 tests/test_bm25_hydration_refill.py --mutate --output mutations.json
git worktree add --detach ../bm25_hydration_refill-baseline 4cc069b3c608ca68fd9efb249343f1c7c46d185d
python -X utf8 scripts/replay_bm25_hydration_refill.py --repo ../bm25_hydration_refill-baseline --output baseline.json
python -X utf8 scripts/probe_bm25_hydration_refill.py --repo . --case hydrate --output native.json
```

Windows 实际使用 `py -3.12 -X utf8`，Linux/WSL 为 `python3 -X utf8`（Python 3.13，原生 /tmp）。每条实际命令、退出码、源码 SHA256、初始失败和明确 SKIP 均保留。原版守卫退出 1 是缺陷复现，errors=0 / SKIP=0；修复/变异入口退出 0。原文兑现探针真实删除隔离库文件，精确故障时点由守卫控制；复杂度探针只有合成元数据，不冒充文件检索评测。

## 具名反面对照

- H1 stop after the first incomplete payload batch → `Guards.test_native_rrf_refills_top_fifty`，指定断言红、errors=0 / SKIP=0。
- H2 retain old corpus scores for surviving winners → `Guards.test_winners_use_recomputed_corpus_scores`，指定断言红、errors=0 / SKIP=0。
- H3 discard already hydrated successful payloads → `Guards.test_payloads_already_hydrated_are_reused`，指定断言红、errors=0 / SKIP=0。
- H4 disable the monotone progress defense → `Guards.test_stuck_index_uses_existing_fallback_once`，指定断言红、errors=0 / SKIP=0。
- H5 leave unavailable winners in term statistics → `Guards.test_block_max_refill_equals_exhaustive_live_oracle`，指定断言红、errors=0 / SKIP=0。

初轮有 2 个变异存活，暴露了故障注入的类身份盲点：变异 callable 构造了另一模块中的索引类。夹具现明确绑定真实生产索引，再真实删除原文；最终 5 个变异都在故障确实发生后由指定断言检出。旧记录在 ZIP history，未计通过。 未放宽旧断言。变异仅替换内存 callable，源码字节未改；导入错误/异常崩溃不算杀死变异。

Windows 既有 BM25 增量变异套件初次外部 240 秒超时（rc=124），不计通过；同一未改源码给足 900 秒后，实际 238.907 秒完整结束、退出 0。初跑原始记录随包保留，未改内部断言或阈值。

## 设计依据、范围与限制

建议 expert：必须证明读取资格、BM25 全语料统计、块上界剪枝及回退/终止条件闭合，直接追加旧榜单下一项并不正确；具备真实删文件竞争、独立新开库 oracle、块剪枝对拍及有限进展反证。最终难度与影响由维护者裁定。

独立于 PR #240 的 RRF 资格终排与 PR #393 的候选容器借用：本项在 BM25 原文兑现阶段，judge=False 仍复现，不改变打分公式、RRF 资格定义或既有块上界算法。

读失败会增加重排名工作，未宣称延迟提升；本次实测 posting_visits 从 106 增至 210，原文读取批次从 1 增至 2。正常无故障路径仍一次排名/一次载荷批次。保证相对于本次已观察到的不可读源补位，不提供跨查询/跨进程或并发写入的原子时间快照；已经读取的载荷仍遵循现有读缓存边界。

共同 CI 前置只将 checkout 的 fetch-depth 设为 0，供既有历史负面对照取原提交；未删改旧断言、未降阈值，不作为独立贡献。新增代码只用 Python 标准库，保留 MIT 许可。

本报告的本地运行不等同 GitHub CI；以 PR 当前 head checks 为准，全部 CI 成功后才发布对应 bounty intake。维护者人审、最终定级与结算均待定。未声称正式榜单名次、百万端到端低延迟或真实私域问答改善。

ZIP 含本项冻结测试、回放/探针、读数、原始日志、MIT 许可和哈希；需配套源码检出，不是整仓离线镜像。
