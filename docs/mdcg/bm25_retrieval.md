# 可选 BM25 检索

`search_rrf` 增加显式的 `bm25` 路，默认检索路径保持原有配置。需要精确词频排序、尤其是英文长文本时可单独启用：

```python
from md_cg.mdcos import MdCGSecure

cg = MdCGSecure("your-memory-root")
rows, meta = cg.search_rrf(
    "memory retrieval", paths=("bm25",), k=20, record=False)
cg.close()
```

MCP `mdcg_recall` 传 `{"query":"memory retrieval","bm25":true}`，会用 BM25 替换原词法路。桶、实体、图、因果与时间路仍按原参数配置参与；图和因果路可以使用 BM25 排名作为种子。Python 可以同时传多条路径，由现有 RRF 融合。

默认 MCP 工具面可调用 `cg`，参数为 `{"op":"read","query":"memory retrieval","bm25":true}`。本入口显式选 BM25 单路；加 `budget_tokens` 时走记忆包装包，返回结构仍与各自原读面一致。`node_id` 的精确读取优先级保持不变。

BM25 使用词频饱和、正 IDF 和长度归一化，固定 `k1=1.2, b=0.75`。英文及其他非汉字词按 Unicode 字母数字序列转小写；汉字采用单字和相邻双字。不做词干化、停用词删除或模型推理。内容面为剥除不适用条件声明后的正文与标签。只有命中分词项的文档参与排名；无命中返回空，不以零分文档填满结果。中文单字可以产生部分匹配，本路也不提供跨语言翻译或完整条件语义匹配；需要这些能力时可组合既有路径。

本路评分仅采用 BM25，不叠加原词法路的域权重、S4 层级加分或时效乘子；候选资格与最终裁决仍由共用入口控制。元数据独有的后置条件/拒绝域索引键不在本路词频面，需要此类召回时应同时保留 `lexical` 路。

词频倒排表和长度信息仅驻留当前实例内存，统计量只来自本次可见性与门控后的候选池。跨会话、角色、层、时间窗或门控改变时会移除不再合格的文档。加密内容仍走现有解密入口；派生索引和本路结果缓存区分身份及密钥状态。写代际使改动节点失效；删除、重建、跨进程索引重载和 `readcache.clear(cg)` 会触发相应更新。关闭生产读缓存时每次重建，避免持有无代际保证的旧词频。

首次调用需要读取合格文档并建索引。后续评分只遍历查询词的倒排项，并用有界堆选前 50 个节点；卡片再经生产读入口水合。元数据候选枚举与同步检查仍为 O(N)，高频词评分仍随命中规模增长，不能据此宣称百万级并发服务已达标。继承原 RRF 每路前 50 的上限，`k=100` 不会把本路放宽到 100；因此单路 Recall@100 与 Recall@50 相同。

`meta["bm25"]` 给出 `build_reads` / `update_reads`、可用文档数、`posting_visits`、`matched`、`hydrated` 和 `unavailable`。读数表示入口调用数，不等同物理磁盘 I/O。派生索引发生异常时清空并回退原词法评分，明确标记 `fallback="lexical_index_error"`；评测应检查该标记及 `unavailable`，不能把回退当作 BM25 成功。

评测适配器 `python -X utf8 -m md_cg.bench_beir_bm25 --help` 支持官方 BEIR SciFact 与 NFCorpus 的完整 corpus 和指定 split。先在 dev 上检查并固定方案，再跑 test。它调用真实 `search_rrf`，关闭结果缓存和可选语义/门控开关，保留原始查询与 title+abstract，以官方 BEIR evaluator 计分。结果属于官方任务的本地评测；未提交排行榜时不提供榜单名次。

参数及 IDF 参考 [Lucene BM25Similarity](https://lucene.apache.org/core/9_9_1/core/org/apache/lucene/search/similarities/BM25Similarity.html)；数据集和校验值见 [BEIR 官方清单](https://github.com/beir-cellar/beir#beers-available-datasets)。Python 实现、分词和索引存储不同于 Lucene，不能视为 Anserini/Lucene 排行榜行的复现。
