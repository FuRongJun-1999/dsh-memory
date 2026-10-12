# BM25 写后稀疏同步：算法与架构优化

日期：2026-10-12。难度申报：expert（待维护者评审）。

少量记忆写入后，原实现仍遍历整个候选池进行资格过滤与 TF/DF/文档长度同步。本轮用**有界写入日志 + 原生资格重判 + 稀疏统计同步**消除普通覆盖/新增时的整池遍历，保留原 BM25 公式、排序与过滤语义。

这与已合并 #114 的块布局/词块增量维护是两处瓶颈：本轮基线 `dcb8fbf4` 已包含 #114。代码随后移植到 `68aef58a`，四个检索文件的 LF 源码与计时版本逐字节一致；回归与正式数据评测在移植后执行，校验值见 [验收回执](bm25_sparse_acceptance_20261012.json)。

## 实测收益

Windows / Ryzen 9 7945HX / 32 GB RAM / Python 3.12。两个独立完整源码进程，独立真实 Markdown 文件池，交替请求顺序；生产 `search_rrf(paths=("bm25",))`，关闭结果缓存与门控，写入耗时和首次建索引单列。每组数据 60 轮；P95 用 nearest-rank，小样本组不代表尾延迟 SLO。

| 场景 | 样本/臂 | 原版 P50 ms | 优化 P50 ms | P50 加速 | P95 ms（原→优） |
|---|---:|---:|---:|---:|---:|
| 10 万条：覆盖后常见词 | 15 | 138.12 | 5.05 | 27.36x | 146.92 → 5.93 |
| 10 万条：覆盖后稀有词 | 15 | 139.99 | 2.15 | 65.22x | 149.13 → 2.74 |
| 10 万条：覆盖后中文词 | 15 | 146.36 | 10.37 | 14.11x | 162.28 → 12.43 |
| 10 万条：新增后常见词 | 5 | 143.57 | 4.82 | 29.81x | 148.54 → 6.25 |
| 10 万条：稳态常见词 | 60 | 3.76 | 3.60 | 1.05x | 4.82 → 4.71 |
| 1 万条变长/变词频：覆盖后常见词 | 15 | 23.86 | 11.48 | 2.08x | 28.46 → 17.11 |
| 1 万条变长/变词频：覆盖后稀有词 | 15 | 13.50 | 1.29 | 10.43x | 16.25 → 1.93 |
| 1 万条变长/变词频：稳态常见词 | 60 | 10.33 | 10.38 | 0.99x | 13.49 → 14.54 |

**602 组前后对照 / 1,204 次实际生产查询，完整融合卡片、原始 top-50 分数与 matched 均零差异。** 120 次写后查询全部只检查 1 个改动文档。变长/变词频测试是新分布；该分布稳态 P95 13.49→14.54 ms，未改善，不能只展示写后加速。

十万条首次 BM25 建索引 147.34→146.65 秒（每臂 1 次，无加速结论）；两臂均实读 100,000 个 Markdown 文件。此组已预生成原生元数据快照，快照准备时间不计入查询。写入+flush P50 14.34→13.73 ms。末段进程 RSS 322.82→342.62 MiB；槽位表拥有对象浅层合计约 16.92 MiB，不含共享路径字符串。OS 文件缓存未清空；测试机观察到 Mem Reduct 运行，冷态与 RSS 仅为本机观察值。

原始数据：[1 万条变分布](bm25_sparse_10k_varied_20261012.json.gz) / [10 万条均匀分布](bm25_sparse_100k_uniform_20261012.json.gz)。JSON 无损 gzip 存档，标准库 `gzip.open(path, "rt", encoding="utf-8")` 可读；解压后 SHA256 见验收回执。

## 算法与不变量

- `_DirtyDict` 保存最多 4,096 次写入提示，普通 flush 后仍可回放，按首次写入顺序去重；原有 path/broad 代际与 N230 逐字见证继续决定失效。
- `MdCGOS` / `MdCGSecure` 的同一 `_candidates` 实现重判改动 ID，沿用层、角色、会话、身份权限和视图过滤；没有另造宽松过滤器。
- ID 槽位保存列表位置和旧路径，路由迁移先移除旧路径的词频贡献，再加入新路径；普通覆盖维持候选原序，新节点追加。
- BM25 只更新本次资格已证明的文档及其 TF/DF/长度；新旧代际衔接、完整读集合和候选列表身份必须一致，避免漏掉尚未消费的写入。
- 删除/广域失效、日志溢出、别名、权限或过滤变化、资格成员减少、复杂门控投影等继续走原全量路径；瞬时读失败下一次重试。`MDCG_BM25_POOL_CACHE=0` / `MDCG_READ_CACHE=0` 保持原退出路径。

**复杂度边界**：普通小批量写后的资格与统计检查由 O(N) 降为 O(Δ + 最多 4,096 条日志回放)，仍需分词改动正文、更新倒排和执行原排序。槽位表 O(N) 内存；冷建、保守回退及复杂词频分布下的排序仍可能 O(N)。默认检索路径未改，收益适用于显式 BM25 路径。

## 运行验证

| 验证 | 结果 | 证据边界 |
|---|---|---|
| BM25 原有 / 块增量 / 本轮新增 | 25 + 12 + 18 = 55 项通过，0 失败 | 真实入口、鲜建全量精确评分 oracle；新增覆盖安全、路径迁移、门控、重试、代际遗漏、溢出、随机写入 |
| 定点变异 | 23/23 检出（旧块剪枝 9、块维护 6、本轮 8） | 预先指定断言变红，错误/跳过不算检出；恢复后守卫通过；[本轮原始日志](bm25_sparse_mutations_20261012.json) |
| 相关回归 | 16 个存在的回归/变异入口退出码 0 | 含读缓存、N230、瞬时读失败、门控、角色、跨进程重载；H4 43 通过/0 失败/0 跳过 |
| 当前 CSRE 两条存储路径 | SQLite 回退、WB_MD_DIRECT=1 各 1 次真实 build_index 成功，矩阵/ID 相等 | 合成数据；另 2 次错名定点变异均 ImportError；不是历史上游检出复现；[记录](bm25_sparse_csre_paths_20261012.json) |
| 旧入口与语料面 | 旧 `md_cg.test_csre_import_contract` 不存在，调用失败；现有 `test_csre_index_import_guard` 4 检查通过（1 次 build 实跑） | `test_md_access_parity` 4 字面量断言通过，真实语料 SQL/解析对拍 **SKIP**，未算运行通过 |
| CI / 人审 | PR 创建后单独查询 CI；expert 为申报 | 本地验证不代替全量 CI 或维护者裁定 |

## 正式公开数据回归

使用 BEIR 官方数据与官方评分器，SciFact test 300 题 / NFCorpus test 323 题，每个版本各跑完整题集（合计 1,246 次生产查询，0 错误）。未向排行榜提交。参数固定 k1=1.2、b=0.75，原生每路 top-50；本轮目标是保持精度的提速，指标没有提升。

| 数据集 | 题数/版本 | nDCG@10 原→优 | Recall@10 原→优 | 一致性 |
|---|---:|---:|---:|---|
| scifact | 300 | 0.66168 → 0.66168 | 0.79094 → 0.79094 | 逐题排名、分数、matched 全相等 |
| nfcorpus | 323 | 0.30694 → 0.30694 | 0.14915 → 0.14915 | 逐题排名、分数、matched 全相等 |

逐题 runs：
[SciFact 原](bm25_sparse_scifact_before_20261012.run.json) / [优](bm25_sparse_scifact_after_20261012.run.json)；
[NFCorpus 原](bm25_sparse_nfcorpus_before_20261012.run.json) / [优](bm25_sparse_nfcorpus_after_20261012.run.json)。数据/评分器版本、哈希、全部命令与指标在验收回执中。

## 复跑

```powershell
git worktree add --detach ../bm25-frozen dcb8fbf4148f727a5b4de1bd0737e14000935857
python -X utf8 -m md_cg.test_bm25
python -X utf8 -m md_cg.test_bm25_incremental
python -X utf8 -m md_cg.test_bm25_sparse_sync
python -X utf8 -m md_cg.test_bm25_sparse_mutations --output ../sparse-mutations.json
python -X utf8 -m md_cg.bench_bm25_sparse_sync --baseline ../bm25-frozen --workspace ../sparse-100k --count 100000 --rounds 60 --distribution uniform --output ../sparse-100k.json
python -X utf8 -m md_cg.bench_bm25_sparse_sync --baseline ../bm25-frozen --workspace ../sparse-10k-varied --count 10000 --rounds 60 --distribution varied --output ../sparse-10k-varied.json
# BEIR 数据与官方评分器需另行备齐；两次分别在 frozen 和本分支执行：
python -X utf8 -m md_cg.bench_beir_bm25 --name scifact --split test --data ../beir-data/scifact --pool ../scifact-pool --output-dir ../scifact-result --beir-root ../beir-official --arms bm25
python -X utf8 -m md_cg.bench_beir_bm25 --name nfcorpus --split test --data ../beir-data/nfcorpus --pool ../nfcorpus-pool --output-dir ../nfcorpus-result --beir-root ../beir-official --arms bm25
```

每次使用新的 workspace、pool 和 output 路径。没有完成百万条、独立实例并发吞吐、共享实例并发读写或真实私有语料验收；这些不计为通过。
