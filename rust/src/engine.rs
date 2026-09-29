//! 检索引擎库层：把评测 CLI 的四路 RRF 编排包装成可嵌入的 `SearchEngine`。
//!
//! **口径承诺**（R-1，2026-09-29）：`search()` 的编排与 `main.rs::search` **同一
//! 实现**——`search_ranked`（本模块）是唯一编排点，两侧只传 `SearchParams`，
//! 分叉面从「两份逐行对齐的代码」收敛成「一处参数」。口径内容：路插入序
//! lexical → bucket → entity → graph、query 先过 `prepare_query` 统一归一层
//! （R-1 前评测 CLI 漏此步）、`unlock_global_cap`（cap=1e9）、graph 种子过
//! `retrieval::sort_path` 三键（R-3）、融合后 `round(s, 6)`。
//!
//! 并发约定：`SearchEngine` 持有全 owned 数据（`Vec`/`String`/`HashMap`），
//! `search(&self)` 是纯读 → 自动满足 `Send + Sync`，宿主可任意共享。

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use crate::retrieval::{self, Hit};
use crate::store::{self, Doc, Entry, Order};

/// 引擎级配置（与评测 CLI `Cfg` 的检索相关子集对应）。
#[derive(Debug, Clone)]
pub struct EngineConfig {
    /// 参与融合的检索路；`None` = 全部四路（lexical/bucket/entity/graph）。
    pub paths: Option<Vec<String>>,
    /// 路权重覆盖；空表 = 融合器内建默认（与 Python `search_rrf` 默认一致）。
    pub weights: HashMap<String, f64>,
    /// `true` = 每路先取分前 `PATH_TAKE`(50) 再 RRF（对齐 `--fusion max`）。
    pub fusion_max: bool,
    /// 相似度口径：`true` = jaccard（默认，长度自惩罚），`false` = legacy 查询侧归一。
    pub jaccard: bool,
    /// graph 路种子是否先按 `retrieval::sort_path`（**三键**：-score/-importance/id）
    /// 排序再取 top-5。
    ///
    /// R-3（2026-09-29）：**默认由 false 改为 true**。原缺省 false 让 seeds 直接取
    /// 「候选枚举序前 5」（目录枚举序，与查询相关性脱钩），而 Python 侧
    /// `mdcos._lexical` 的返回序**恒为相关度降序**（该函数 docstring 明载：原实现
    /// 仅超 GLOBAL_CAP 时排序，下游 seed/融合拿到无语义依据的顺序，已修）——
    /// 即 Rust 这条腿是**旧口径的残留移植**，两侧对同 query 同语料的 graph 腿
    /// 种子集合不同。`false` 保留为隔离「种子口径」与「边结构质量」的排查阀。
    pub graph_seeds_sorted: bool,
    /// 候选顺序：`Scan` = 目录枚举序（默认，对齐 Python `_scan_nodes`），`Log` = 索引日志序。
    pub order: Order,
    /// 载入正文的工作线程数；`0` = 自动（CPU 核数）。
    pub threads: usize,
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            paths: None,
            weights: HashMap::new(),
            fusion_max: false,
            jaccard: true,
            graph_seeds_sorted: true,
            order: Order::Scan,
            threads: 0,
        }
    }
}

/// 单条检索结果。
#[derive(Debug, Clone)]
pub struct SearchHit {
    /// 节点 id（frontmatter `id`，缺失时回退 path basename）。
    pub id: String,
    /// 相对 root 的路径（`/` 分隔）。
    pub path: String,
    /// 认知图层（anchor/self/knowledge/structural/contextual/…）。
    pub layer: String,
    /// 融合得分（已 `round(_, 6)`）。
    pub score: f64,
}

/// 已载入内存的只读检索引擎。
///
/// 多智能体并发两条路：
///   1. **库内**：宿主持一个引擎，多线程并发调 `search`（零拷贝共享）；
///   2. **进程间**：`serve` 模式每智能体一进程，索引只读、OS 页缓存复用
///      （协议见 `serve.rs`，模式参照 protocol-compiler 蜂群实例基座）。
pub struct SearchEngine {
    root: PathBuf,
    entries: Vec<Entry>,
    docs: Vec<Option<Doc>>,
    cand: Vec<usize>,
    paths: Vec<String>,
    weights: HashMap<String, f64>,
    fusion_max: bool,
    jaccard: bool,
    graph_seeds_sorted: bool,
    /// 批次 15 统一归一层（None = 词表不可得或开关关 → 原口径）。
    atoms: Option<crate::atoms::Atoms>,
}

impl SearchEngine {
    /// 打开并预载一个认知图库（`root` = 灵枢记忆库目录，含 `_index.json`
    /// 或 `_index_log` 与各层 `.md` 节点）。
    pub fn open(root: impl Into<PathBuf>, cfg: &EngineConfig) -> Result<Self, String> {
        let root = root.into();
        let entries = store::load_index(&root, cfg.order)?;
        let cand = store::candidates(&entries);
        let threads = if cfg.threads == 0 {
            std::thread::available_parallelism()
                .map(|v| v.get())
                .unwrap_or(4)
        } else {
            cfg.threads.max(1)
        };
        let docs = store::load_docs(&root, &entries, threads);
        let paths = cfg.paths.clone().unwrap_or_else(|| {
            vec![
                "lexical".to_string(),
                "bucket".to_string(),
                "entity".to_string(),
                "graph".to_string(),
            ]
        });
        Ok(Self {
            root,
            entries,
            docs,
            cand,
            paths,
            weights: cfg.weights.clone(),
            fusion_max: cfg.fusion_max,
            jaccard: cfg.jaccard,
            graph_seeds_sorted: cfg.graph_seeds_sorted,
            // 批次 15：统一归一层（env 探测词表；不可得 = None 原口径）
            atoms: crate::atoms::Atoms::from_env(),
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// 已成功载入正文的节点数。
    pub fn doc_count(&self) -> usize {
        self.docs.iter().filter(|d| d.is_some()).count()
    }

    /// 检索候选数（层黑名单与工作角色过滤后）。
    pub fn candidate_count(&self) -> usize {
        self.cand.len()
    }

    /// 参与融合的路名。
    pub fn paths(&self) -> &[String] {
        &self.paths
    }

    /// 四路 RRF 检索，返回 top-`k`（编排与评测 CLI 一致）。
    pub fn search(&self, query: &str, k: usize) -> Vec<SearchHit> {
        let fused = search_ranked(
            &self.docs,
            &self.entries,
            &self.cand,
            query,
            k,
            self.atoms.as_ref(),
            &SearchParams {
                paths: &self.paths,
                weights: &self.weights,
                fusion_max: self.fusion_max,
                jaccard: self.jaccard,
                graph_seeds_sorted: self.graph_seeds_sorted,
            },
        );

        fused
            .into_iter()
            .map(|(idx, score)| {
                let e = &self.entries[idx];
                let id = self
                    .docs
                    .get(idx)
                    .and_then(|d| d.as_ref())
                    .map(|d| d.id.clone())
                    .unwrap_or_else(|| e.id.clone());
                SearchHit {
                    id,
                    path: e.path.clone(),
                    layer: e.layer.clone(),
                    score,
                }
            })
            .collect()
    }
}

/// 融合编排的可调口径（与 `EngineConfig` 的检索相关子集一一对应）。
///
/// R-1（2026-09-29）：本结构的存在理由是**消除双实现**——编排此前有两份
/// （`SearchEngine::search` 与 `main.rs::search`），两者对「query 是否过统一
/// 归一层」的答案不一致（前者 `atoms.unify`，后者直接用原始 query），
/// 同 query 同语料 top-1 不同，违反 `rust/README.md` 与 `lib.rs` 自书的
/// 「两边一致」。现编排单点在 `search_ranked`，两侧只传参数。
pub struct SearchParams<'a> {
    /// 参与融合的路名（缺省四路由调用方自行构造）。
    pub paths: &'a [String],
    /// 路权重覆盖；空表 = 融合器内建默认。
    pub weights: &'a HashMap<String, f64>,
    /// `true` = 每路先取分前 `PATH_TAKE`(50) 再 RRF。
    pub fusion_max: bool,
    /// 相似度口径：`true` = jaccard，`false` = legacy 查询侧归一。
    pub jaccard: bool,
    /// graph 路种子是否先过 `retrieval::sort_path` 再取 top-5。
    pub graph_seeds_sorted: bool,
}

/// query 统一归一层单点（R-1）：`atoms` 为 `None`（词表不可得/开关关）时
/// **原样返回**——与改动前的无归一口径逐位一致。
#[inline]
pub fn prepare_query(atoms: Option<&crate::atoms::Atoms>, query: &str) -> String {
    match atoms {
        Some(a) => a.unify(query),
        None => query.to_string(),
    }
}

/// 四路 RRF 融合编排的**唯一实现**（R-1）。
///
/// `SearchEngine::search`（库内嵌 / `--serve`）与 `main.rs::search`（评测 CLI）
/// 都调本函数——口径承诺（路插入序 lexical → bucket → entity → graph、
/// `unlock_global_cap`(cap=1e9)、融合后 `round(s, 6)`）由单一实现保证，
/// 「任何口径改动必须两边同步」只剩一处可改。
///
/// 返回 `(doc_idx, 融合分)`，已按分数降序，长度 ≤ k。
pub fn search_ranked(
    docs: &[Option<Doc>],
    entries: &[Entry],
    cand: &[usize],
    query: &str,
    k: usize,
    atoms: Option<&crate::atoms::Atoms>,
    p: &SearchParams<'_>,
) -> Vec<(usize, f64)> {
    // 批次 15 统一口径：query → 标准原子序列（与 Python unify_query 同口径；
    // 词表不可得/开关关 → 原样）。R-1：**两条路共用本行**，评测 CLI 不再
    // 漏过归一层。
    let query = prepare_query(atoms, query);
    let query = query.as_str();

    let mut ranked: Vec<(&str, Vec<Hit>)> = Vec::new();
    let has = |x: &str| p.paths.iter().any(|y| y == x);

    // 插入序对齐 search_rrf：lexical → bucket → entity → graph
    let lex_raw: Vec<Hit> = if has("lexical") {
        let h = retrieval::lexical(docs, cand, query, 1e9, p.jaccard);
        ranked.push(("lexical", h.clone()));
        h
    } else {
        Vec::new()
    };
    if has("bucket") {
        // 评测链路不传 context → bucket 路恒空
        ranked.push(("bucket", retrieval::bucket(entries, cand, false)));
    }
    if has("entity") {
        ranked.push(("entity", retrieval::entity(docs, cand, query)));
    }
    if has("graph") {
        // 种子口径（R-3）：Python `mdcos._lexical` 的返回序**恒为相关度降序**
        // ⇒ `_path_graph` 的 `seeds[:5]` 是**相关度前 5**。故此处排序必须与
        // `_lexical` 同一把尺子——`retrieval::sort_path` 的**三键**
        // （-score/-importance/id），而不是只比 score（并列时路内顺序会漂，
        // 与 issue #29 的第三键教训同源）。
        let seeds: Vec<Hit> = if p.graph_seeds_sorted {
            let mut v = lex_raw.clone();
            retrieval::sort_path(&mut v, docs);
            v
        } else {
            lex_raw.clone()
        };
        ranked.push(("graph", retrieval::graph(docs, entries, cand, &seeds)));
    }

    let mut fused = retrieval::fuse(&ranked, docs, k, p.weights, p.fusion_max);
    for (_, s) in fused.iter_mut() {
        *s = (*s * 1e6).round() / 1e6; // 对齐 round(s, 6)
    }
    fused
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_root(tag: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let d = std::env::temp_dir().join(format!("mdcg_eval_test_{tag}_{nanos}"));
        std::fs::create_dir_all(d.join("knowledge")).unwrap();
        d
    }

    fn write(p: &Path, s: &str) {
        std::fs::write(p, s).unwrap();
    }

    /// 微型库：2 节点（评测/记忆 vs 视觉），零外部数据依赖。
    fn mini_lib() -> PathBuf {
        let root = temp_root("engine");
        write(
            &root.join("_index.json"),
            r#"{"nodes":{
                "mem_a":{"path":"knowledge/mem_a.md","layer":"knowledge","tags":["评测","记忆"],"importance":0.6,"edges":[]},
                "mem_b":{"path":"knowledge/mem_b.md","layer":"knowledge","tags":["视觉"],"importance":0.5,"edges":[]}
            }}"#,
        );
        write(
            &root.join("knowledge").join("mem_a.md"),
            "---\nid: \"mem_a\"\ntags: [\"评测\", \"记忆\"]\nimportance: 0.6\n---\n灵枢评测：六家记忆系统横向对比的复现脚本与数据集。\n",
        );
        write(
            &root.join("knowledge").join("mem_b.md"),
            "---\nid: \"mem_b\"\ntags: [\"视觉\"]\nimportance: 0.5\n---\n视觉图像识别的实验记录。\n",
        );
        root
    }

    #[test]
    fn search_hits_expected_doc() {
        let root = mini_lib();
        let eng = SearchEngine::open(&root, &EngineConfig::default()).unwrap();
        assert_eq!(eng.doc_count(), 2);
        assert_eq!(eng.candidate_count(), 2);
        let hits = eng.search("评测复现", 5);
        assert!(!hits.is_empty());
        assert_eq!(hits[0].id, "mem_a", "评测查询应首命中 mem_a");
        assert_eq!(hits[0].layer, "knowledge");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn concurrent_search_is_thread_safe() {
        let root = mini_lib();
        let eng = SearchEngine::open(&root, &EngineConfig::default()).unwrap();
        let (r1, r2) = std::thread::scope(|s| {
            let h1 = s.spawn(|| eng.search("记忆评测", 3));
            let h2 = s.spawn(|| eng.search("视觉识别", 3));
            (h1.join().unwrap(), h2.join().unwrap())
        });
        assert!(!r1.is_empty());
        assert!(!r2.is_empty());
        let _ = std::fs::remove_dir_all(&root);
    }

    // ================= R-1 / R-3 守卫（opt-batch1，2026-09-29） =============

    /// 语料：6 个词法同分候选（同正文同 tags ⇒ 分数逐位相同）+ 6 个只被
    /// graph 路可达的目标（t1..t6，正文与 query 无关）。
    ///
    /// 关键构造：**文件名序（候选枚举序）与 importance 序刻意相反**——
    /// a1..a6 的 importance 递增（0.1…0.6），故：
    ///   · 种子按候选枚举序取前 5（旧口径 raw） ⇒ 种子 = a1..a5，目标 t6 不可达；
    ///   · 种子按三键 sort_path 取前 5（新口径） ⇒ 种子 = a6..a2，目标 t1 不可达。
    /// 于是「最终结果里有没有 t6 / t1」就是种子口径的**可观测判别面**。
    fn seed_rank_lib() -> PathBuf {
        let root = temp_root("seedrank");
        let mut idx = String::from(r#"{"nodes":{"#);
        let mut first = true;
        for i in 1..=6 {
            if !first {
                idx.push(',');
            }
            first = false;
            idx.push_str(&format!(
                r#""a{i}":{{"path":"knowledge/a{i}.md","layer":"knowledge","tags":["种子"],"importance":{imp},"edges":["t{i}"]}}"#,
                i = i,
                imp = 0.1 * (i as f64)
            ));
        }
        for i in 1..=6 {
            idx.push_str(&format!(
                r#","t{i}":{{"path":"knowledge/t{i}.md","layer":"knowledge","tags":[],"importance":0.5,"edges":[]}}"#,
                i = i
            ));
        }
        idx.push_str("}}");
        write(&root.join("_index.json"), &idx);
        for i in 1..=6 {
            // 同正文 ⇒ 同 lexical 分（LIKE 命中同一 term，bigram 覆盖一致）
            write(
                &root.join("knowledge").join(format!("a{i}.md")),
                &format!(
                    "---\nid: \"a{i}\"\ntags: [\"种子\"]\nimportance: {imp}\nedges: [\"t{i}\"]\n---\n# 正文：种子节点共同正文 zzseed zzseed\n",
                    i = i,
                    imp = 0.1 * (i as f64)
                ),
            );
            write(
                &root.join("knowledge").join(format!("t{i}.md")),
                &format!("---\nid: \"t{i}\"\nimportance: 0.5\n---\n# 正文：图扩展目标 {i}\n", i = i),
            );
        }
        root
    }

    fn ids_of(hits: &[SearchHit]) -> Vec<String> {
        hits.iter().map(|h| h.id.clone()).collect()
    }

    /// R-3：种子必须过 `retrieval::sort_path`（三键），而不是「候选枚举序前 5」。
    #[test]
    fn r3_graph_seeds_use_three_key_sort_path() {
        let root = seed_rank_lib();
        let sorted = SearchEngine::open(&root, &EngineConfig::default()).unwrap();
        let raw = SearchEngine::open(
            &root,
            &EngineConfig {
                graph_seeds_sorted: false,
                ..EngineConfig::default()
            },
        )
        .unwrap();

        let hs = ids_of(&sorted.search("zzseed", 20));
        let hr = ids_of(&raw.search("zzseed", 20));

        // 相关度最高（importance 0.6）的 a6 在两种口径下都是种子，故 t6 可达
        // ——等等：raw 取枚举序前 5（a1..a5），a6 **不是**种子 ⇒ t6 只在新口径可达。
        assert!(hs.contains(&"t6".to_string()),
                "新口径：a6（相关度最高）应为种子 ⇒ t6 可达；实际 {hs:?}");
        assert!(!hr.contains(&"t6".to_string()),
                "旧口径：枚举序前 5 不含 a6 ⇒ t6 不可达；实际 {hr:?}");
        // 反向面：a1（importance 最低）在旧口径是种子、新口径被挤出 ⇒ t1 反转
        assert!(hr.contains(&"t1".to_string()),
                "旧口径：a1 在枚举序前 5 内 ⇒ t1 可达；实际 {hr:?}");
        assert!(!hs.contains(&"t1".to_string()),
                "新口径：a1 被三键排序挤出前 5 ⇒ t1 不可达；实际 {hs:?}");
        let _ = std::fs::remove_dir_all(&root);
    }

    /// R-3 的判别力自证：把三键排序换成**只比 score**（旧实现），同分并列下
    /// `sort_by` 是稳定排序 ⇒ 顺序与候选枚举序一致 ⇒ 与 raw 同形（t6 不可达）。
    /// 本用例证明上一条断言红的是「三键 vs 单键」，不是别的。
    #[test]
    fn r3_score_only_sort_degenerates_to_enumeration_order() {
        let root = seed_rank_lib();
        let eng = SearchEngine::open(&root, &EngineConfig::default()).unwrap();
        let docs = store::load_docs(&root, &eng.entries, 1);
        let mut hits = retrieval::lexical(&docs, &eng.cand, "zzseed", 1e9, true);
        assert!(hits.len() >= 2, "夹具前提：词法命中 ≥2");
        // 六条候选分数逐位相同（同正文同 tags）——这正是三键存在的理由
        let s0 = hits[0].score;
        assert!(hits.iter().all(|h| h.score == s0),
                "夹具前提：候选分数并列（三键才可分辨）");
        hits.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let top5: Vec<String> = hits
            .iter()
            .take(5)
            .map(|h| docs[h.idx].as_ref().unwrap().id.clone())
            .collect();
        assert_eq!(
            top5,
            vec!["a1", "a2", "a3", "a4", "a5"],
            "只比 score 的排序在并列处退化为枚举序（R-3 判别力自证）"
        );
        let mut three = hits.clone();
        retrieval::sort_path(&mut three, &docs);
        let top5b: Vec<String> = three
            .iter()
            .take(5)
            .map(|h| docs[h.idx].as_ref().unwrap().id.clone())
            .collect();
        assert_eq!(
            top5b,
            vec!["a6", "a5", "a4", "a3", "a2"],
            "三键排序按 -score/-importance/id 定序（R-3 修复后的口径）"
        );
        let _ = std::fs::remove_dir_all(&root);
    }

    /// R-1：编排单点——`SearchEngine::search` 与直接调 `search_ranked`
    /// （同一参数 + 同一 atoms）**逐位一致**；并覆盖 `prepare_query` 的两条
    /// 分支（有词表 → 归一；无词表 → 原样）。
    #[test]
    fn r1_search_ranked_is_the_single_orchestration_point() {
        let root = mini_lib();
        let eng = SearchEngine::open(&root, &EngineConfig::default()).unwrap();
        let via_engine = eng.search("评测复现", 5);
        let via_ranked = search_ranked(
            &eng.docs,
            &eng.entries,
            &eng.cand,
            "评测复现",
            5,
            eng.atoms.as_ref(),
            &SearchParams {
                paths: &eng.paths,
                weights: &eng.weights,
                fusion_max: eng.fusion_max,
                jaccard: eng.jaccard,
                graph_seeds_sorted: eng.graph_seeds_sorted,
            },
        );
        assert_eq!(via_engine.len(), via_ranked.len());
        for (h, (idx, sc)) in via_engine.iter().zip(via_ranked.iter()) {
            assert_eq!(&h.id, &eng.entries[*idx].id, "同序同位（R-1 单实现）");
            assert_eq!(h.score, *sc, "同分（R-1 单实现）");
        }
        // prepare_query 两条分支
        assert_eq!(prepare_query(None, "I eat beef"), "I eat beef");
        assert_eq!(prepare_query(None, ""), "");
        let _ = std::fs::remove_dir_all(&root);
    }

    /// R-1 的行为面：评测链路（无归一层时）与库链路（有归一层时）对**同一
    /// 英文 query / 中文语料**必须给出不同结果——这正是 main.rs 漏接归一层时
    /// 的失配形态；两条路现在共用 `search_ranked`，故只在**显式传参差异**下才
    /// 分叉（`atoms` 的有无）。
    #[test]
    fn r1_unifier_changes_cross_lingual_result() {
        let root = temp_root("unify");
        write(
            &root.join("_index.json"),
            r#"{"nodes":{
                "beef":{"path":"knowledge/beef.md","layer":"knowledge","tags":[],"importance":0.3,"edges":[]},
                "tall":{"path":"knowledge/tall.md","layer":"knowledge","tags":[],"importance":0.9,"edges":[]}
            }}"#,
        );
        write(
            &root.join("knowledge").join("beef.md"),
            "---\nid: \"beef\"\nimportance: 0.3\n---\n# 正文：牛肉 烹饪 方法 zzcook\n",
        );
        write(
            &root.join("knowledge").join("tall.md"),
            "---\nid: \"tall\"\nimportance: 0.9\n---\n# 正文：无关 节点 zzcook\n",
        );
        let eng = SearchEngine::open(&root, &EngineConfig::default()).unwrap();
        let atoms = crate::atoms::Atoms::load(
            &Path::new(env!("CARGO_MANIFEST_DIR")).join("../md_cg/semantic/en_zh_map.json"),
        )
        .expect("仓库内 en_zh_map.json 可载入");
        let p = SearchParams {
            paths: &eng.paths,
            weights: &eng.weights,
            fusion_max: eng.fusion_max,
            jaccard: eng.jaccard,
            graph_seeds_sorted: eng.graph_seeds_sorted,
        };
        // 带归一层：英文 query 归一到「我 吃 牛肉 昨天」→ 命中牛肉节点
        let on = search_ranked(&eng.docs, &eng.entries, &eng.cand,
                               "I eat beef yesterday", 5, Some(&atoms), &p);
        assert!(!on.is_empty());
        assert_eq!(eng.entries[on[0].0].id, "beef",
                   "归一层生效时英文 query 应命中中文「牛肉」节点");
        // 不带归一层（旧评测链路口径）：英文词面 LIKE 全空 ⇒ 走 LIKE 兜底池，
        // 定序只看 importance ⇒ 高 importance 的无关节点反超
        let off = search_ranked(&eng.docs, &eng.entries, &eng.cand,
                                "I eat beef yesterday", 5, None, &p);
        assert!(!off.is_empty());
        assert_ne!(eng.entries[off[0].0].id, "beef",
                   "无归一层时英文 query 不得命中中文节点（旧口径的失配形态）");
        let _ = std::fs::remove_dir_all(&root);
    }
}
