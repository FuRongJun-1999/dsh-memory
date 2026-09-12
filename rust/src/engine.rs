//! 检索引擎库层：把评测 CLI 的四路 RRF 编排包装成可嵌入的 `SearchEngine`。
//!
//! **口径承诺**：`search()` 的编排与 `main.rs::search` 逐行一致——
//! 路插入序 lexical → bucket → entity → graph、`unlock_global_cap`（cap=1e9）、
//! 融合后 `round(s, 6)`。任何口径改动必须两边同步，否则评测分数与线上检索漂移。
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
    /// graph 路种子是否先按分排序再取 top-5（对齐 `--graph-seeds sorted`）。
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
            graph_seeds_sorted: false,
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
        let mut ranked: Vec<(&str, Vec<Hit>)> = Vec::new();
        let has = |p: &str| self.paths.iter().any(|x| x == p);

        // 插入序对齐 search_rrf：lexical → bucket → entity → graph
        let lex_raw: Vec<Hit> = if has("lexical") {
            let h = retrieval::lexical(&self.docs, &self.cand, query, 1e9, self.jaccard);
            ranked.push(("lexical", h.clone()));
            h
        } else {
            Vec::new()
        };
        if has("bucket") {
            // 与评测链路一致：不传 context → bucket 路恒空
            ranked.push(("bucket", retrieval::bucket(&self.entries, &self.cand, false)));
        }
        if has("entity") {
            ranked.push(("entity", retrieval::entity(&self.docs, &self.cand, query)));
        }
        if has("graph") {
            let seeds: Vec<Hit> = if self.graph_seeds_sorted {
                let mut v = lex_raw.clone();
                v.sort_by(|a, b| {
                    b.score
                        .partial_cmp(&a.score)
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
                v
            } else {
                lex_raw.clone()
            };
            ranked.push(("graph", retrieval::graph(
                &self.docs,
                &self.entries,
                &self.cand,
                &seeds,
            )));
        }

        let mut fused = retrieval::fuse(&ranked, &self.docs, k, &self.weights, self.fusion_max);
        for (_, s) in fused.iter_mut() {
            *s = (*s * 1e6).round() / 1e6; // 对齐 round(s, 6)
        }

        fused.into_iter()
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
}
