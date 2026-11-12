# 检索派生文本复用：冻结源码三臂对照

意图声明：降低常驻 Markdown 检索重复去空白、转小写的成本，保持候选、评分、资格和溯源语义。

预期结果：暖态只归一化查询一次；未写文档复用派生文本；写一个节点只重算该节点；显式 clear/rebuild 可见新内容；关闭既有读缓存时回到即算即弃。结果内容、顺序、分数及资格/溯源须与冻结源码一致。

可信边界：本机 Windows / Python 3.12，独立 worker 进程、逐题轮换三臂顺序，实际调用 `MdCGOS.search` 和 `search_rrf(paths=('lexical',))`。结果缓存关闭，文档缓存开启，freshness/英文原子/语义/候选加速关闭；计时不含序列化和比对，不使用 profiler 或替换生产函数。暖态固定 legacy；另核对两种评分模式。这里测串行暖查询，不测并发、吞吐、QA、生产 SLO 或跨产品优劣。

## 结果

三个独立进程读相同字节的 Markdown 副本；基线 `c675858`，仅精确文本缓存 `8f5623e`，两类缓存 `80bb35d`，三臂均包含同一份最新 main 的 #108 分段预算修复及 #109 MCP 协议修复。此前对旧 main 的预跑不作为下表证据。三个生产文件的 Git blob 记录在 JSON 的 `source_identity`。

| 暖查询场景 | 冻结原版均值 ms | 仅精确文本均值 ms | 两类缓存均值 ms | 原版 → 两类缓存 P95 ms |
|---|---:|---:|---:|---:|
| 合成 1,000 长文 / RRF / 每臂 40 次 | 172.882 | 64.143 | 13.816 | 268.500 → 22.899 |
| 合成 1,000 长文 / search / 每臂 40 次 | 197.622 | 65.182 | 15.890 | 341.783 → 22.640 |
| 公开 567 短文 / RRF / 每臂 500 次 | 5.674 | 4.954 | 4.188 | 7.648 → 5.382 |
| 公开 567 短文 / search / 每臂 500 次 | 5.819 | 5.120 | 4.343 | 7.782 → 5.797 |

长文 RRF 均值下降 92.0%（12.51×），公开短文下降 26.2%（1.35×）。后者是仓库自带 locomo-zh-500 关键词检索池，567 条均为 gold、缺少干扰，不可外推为真实记忆 QA。

每组包括冷查询、预热、暖查询、两种评分模式复核，共 2,138 次配对请求、6,414 次实际调用。全量结果卡片及语义元数据的 SHA256 三臂逐条一致；计数/耗时等运行字段不参与比对。另有 4 次实际 add+flush 和 4 次写后查询，写后 freshversion 标记均被召回。写后比对含 id/content/score/资格/溯源，排除各进程本来就不同的写入时间字段。

### 成本和失败边界

- 长文进程 RSS 77.79 → 117.66 MiB，增加约 39.86 MiB。两个缓存保留的字符串值分别 20,282,000 / 20,308,000 B，合计约 38.71 MiB，未含字典/元组开销。
- 公开短文 RSS 42.01 → 42.95 MiB；字符串值合计约 0.64 MiB。RSS 包含整个 Python 进程，并非缓存净占用。
- 长文首次查询 3079.68 → 2630.42 ms，为每臂单次冷读数，存在初始化成本，不能宣称冷启动提速。
- 4 次 add+flush 均值 17.93 → 16.83 ms；写后查询 65.87 → 9.78 ms。样本少，只作为失效正确性和成本观察。
- 新缓存按实例、路径及现有 dirty generation 失效；内存随被访问正文总量增长。内存受限或需要每次读盘时，可用既有 `MDCG_READ_CACHE=0`。跨进程/直接修改文件仍需明确 rebuild/clear；没有新增跨进程一致性承诺。
- 精确判据保持大小写敏感、去 Unicode 空白；LIKE 保持原正向正文与标签语义，拒绝条件行不变。没有改变存储、默认路由或评分公式。

## 守卫和反证

新增运行守卫 12/12：冻结判据与生产入口、两种评分模式、Unicode/大小写、暖态查询仅一次归一化、写谁失效谁、clear 返回计数、短查询不投影文档、退出阀、实例隔离、重复装配、直接写文件后 rebuild、正向正文条件。

7/7 定点变异恰好在预定运行断言失败，0 非预期错误、0 skip；未变异与恢复态各 6 个具名方法通过：取消去空白、擅自小写精确判据、取消暖缓存、精确缓存陈旧、小写缓存陈旧、遗漏 clear、重复装配后旧缓存残留。重复装配守卫先预热全部派生缓存再 clear；此次复现并修复旧 `_positive_body` / `_doc_norm_bigrams` 包装层被再次包装、隐含缓存未清的问题。原 #89 同分裁决 4/4 变异仍精确命中原预期红项；只调整新增参数的 fault stub 及源码锚点。

相关模块 readcache 生产路径（20 项）、精确失效、默认装配、RRF 候选（13 tests）、recall 元数据/面守卫、MCP（68 项）、密钥轮换、密文健康哈希、热缓存路径均退出 0。全仓 CI 结果以 PR Checks 为准，相关回归不等于全仓零跳过。

## 复现

在当前仓库安装依赖，另准备基线和可选中间臂的 Git worktree；所有临时副本只在给定 workspace 内创建并清理。

```text
git worktree add --detach ../projection-baseline c675858
python -X utf8 -m md_cg.test_exact_text_cache
python -X utf8 -m md_cg.test_text_projection_mutations --output projection-mutations.json
python -X utf8 -m md_cg.test_issue89a_score_cap_tiebreak --mutate A
python -X utf8 -m md_cg.bench_text_projections --baseline ../projection-baseline --workspace ../ --nodes 1000 --repeats 5 --output projection-replay.json
```

可选 `--stage-one` 指向 JSON 中 `published_equivalent_stage_one_commit` 的检出，复现三臂。JSON 保留全部配对时延、顺序、签名、查询和源文件身份；机器差异允许时延变化，结果签名一致、写后标记可见是硬断言。

原始读数：[text_projections_bench_20261012.json](text_projections_bench_20261012.json)。变异读数：[text_projection_mutations_20261012.json](text_projection_mutations_20261012.json)。
