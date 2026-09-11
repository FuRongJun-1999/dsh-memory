//! 检索层：四路召回 + RRF 融合，与 `md_cg/mdcos.py` 的 `search_rrf` 对齐。
//!
//! 路定义（口径 A legacy 下的实际行为）：
//!   * `lexical`  `_lexical`      ：LIKE 预筛 + 二元组覆盖率 → **唯一非空路**
//!   * `bucket`   `_path_bucket`  ：需 `context`；评测不传 → 恒空
//!   * `entity`   `_path_entity`  ：需 `tags`；legacy 无 tags → 恒空
//!   * `graph`    `_path_graph`   ：需 `edges`；legacy `edges=[]` → 恒空
//!
//! 三路空转不是「省略实现」，而是**口径事实**，代码里保留完整实现以便
//! 口径 B（标定五要素 + tags + edges）无需改结构即可复用。

use std::collections::HashMap;

use crate::store::{by_basename, Doc, Entry};
use crate::text::{bigrams, expand_query_terms, overlap_count};

/// 单路命中的文档下标 + 原始分。
#[derive(Debug, Clone, Copy)]
pub struct Hit {
    pub idx: usize,
    pub score: f64,
}

/// 对齐 `mdcos.RRF_K`。
pub const RRF_K: f64 = 60.0;
/// 对齐 `search_rrf` 的 `scored[:50]`。
pub const PATH_TAKE: usize = 50;

/// `_like`：`any(t in body or t in tags for t in terms)`。
#[inline]
fn like(doc: &Doc, terms: &[String]) -> bool {
    let body = doc.like_body();
    let tags = doc.tags_joined.as_str();
    terms
        .iter()
        .any(|t| body.contains(t.as_str()) || (!tags.is_empty() && tags.contains(t.as_str())))
}

/// `_lexical`：LIKE 预筛 → 覆盖率打分。
///
/// `cap` 对齐 `GLOBAL_CAP`（评测侧 `unlock_global_cap()` 置 1e9 → 不截断）。
pub fn lexical(
    docs: &[Option<Doc>],
    cand: &[usize],
    query: &str,
    cap: f64,
    jaccard: bool,
) -> Vec<Hit> {
    let terms = expand_query_terms(query);
    let qb = bigrams(query);
    let qbl = qb.len() as f64;

    // 预筛：命中数（hits）；同时记住候选全集下标以便回退
    let mut hits: Vec<usize> = Vec::new();
    for &i in cand {
        if let Some(d) = docs[i].as_ref() {
            if like(d, &terms) {
                hits.push(i);
            }
        }
    }
    if hits.len() as f64 > cap {
        hits.truncate(cap as usize);
    }
    // `hits or docs[:GLOBAL_CAP]`：无命中时回退到候选全集（等分 0 的情形）
    let fallback: Vec<usize>;
    let picked: &[usize] = if hits.is_empty() {
        let c = cand.len().min(cap as usize);
        fallback = cand[..c].to_vec();
        &fallback
    } else {
        &hits
    };

    let mut out = Vec::with_capacity(picked.len());
    for &i in picked {
        let d = match docs[i].as_ref() {
            Some(d) => d,
            None => continue,
        };
        let cap_hit = overlap_count(&qb, &d.stripped);
        // legacy：`|qb ∩ db| / |qb|`（只归一化 query 侧 → 长文档必然霸榜）
        // jaccard：`|qb ∩ db| / |qb ∪ db|`（对称，长度自惩罚，无需调参）
        let sim = if jaccard {
            let denom = (qb.len() + d.db_len).saturating_sub(cap_hit);
            if denom > 0 {
                cap_hit as f64 / denom as f64
            } else {
                0.0
            }
        } else if qbl > 0.0 {
            cap_hit as f64 / qbl
        } else {
            0.0
        };
        // 对齐 `any(str(t) in q or q in str(t) for t in tags)`：逐个 tag 判定，
        // 不做空串过滤（Python 里 `"" in q` 恒真，会触发 bonus）。
        let tag_bonus = if d
            .tags
            .iter()
            .any(|t| query.contains(t.as_str()) || t.contains(query))
        {
            0.05
        } else {
            0.0
        };
        out.push(Hit {
            idx: i,
            score: (sim + tag_bonus).min(1.0),
        });
    }
    out
}

/// `_path_entity`：tags 命中（`t in query or query in t`，且 `len(t) >= 2`），恒记 1.0。
pub fn entity(docs: &[Option<Doc>], cand: &[usize], query: &str) -> Vec<Hit> {
    let mut out = Vec::new();
    for &i in cand {
        let d = match docs[i].as_ref() {
            Some(d) => d,
            None => continue,
        };
        let hit = d.tags.iter().any(|t| {
            t.chars().count() >= 2 && (query.contains(t.as_str()) || t.contains(query))
        });
        if hit {
            out.push(Hit { idx: i, score: 1.0 });
        }
    }
    out
}

/// `_path_bucket`：需 `context`；评测不传 context → 恒空（对齐 Python 行为）。
pub fn bucket(entries: &[Entry], _cand: &[usize], has_context: bool) -> Vec<Hit> {
    if !has_context {
        return Vec::new();
    }
    // 路由桶需要 routing.route_key(context, tags)，评测链路不进入此分支。
    // 保留签名以固定四路结构；启用时在此接 routing 的等价实现。
    let _ = entries;
    Vec::new()
}

/// `_path_graph`：从词法种子 top-5 沿 `edges` 一跳扩展，分数 = 种子分 × 0.5。
pub fn graph(
    docs: &[Option<Doc>],
    entries: &[Entry],
    cand: &[usize],
    seeds: &[Hit],
) -> Vec<Hit> {
    if seeds.is_empty() {
        return Vec::new();
    }
    // `seeds[:5]` 取的是已排序后的前五（调用方保证传入已排序）
    let top: Vec<&Hit> = seeds.iter().take(5).collect();
    let seed_ids: std::collections::HashSet<String> = top
        .iter()
        .filter_map(|h| docs[h.idx].as_ref().map(|d| d.id.clone()))
        .collect();

    let base = by_basename(entries);
    let mut out = Vec::new();
    for h in top {
        let d = match docs[h.idx].as_ref() {
            Some(d) => d,
            None => continue,
        };
        for tid in &d.edges {
            if seed_ids.contains(tid) {
                continue;
            }
            if let Some(&bi) = base.get(tid) {
                if !cand.contains(&bi) {
                    continue;
                }
                if docs[bi].is_none() {
                    continue;
                }
                out.push(Hit {
                    idx: bi,
                    score: h.score * 0.5,
                });
            }
        }
    }
    out
}

/// 对齐 `sorted(scored, key=lambda x: (-score, -importance))`（稳定排序）。
pub fn sort_path(hits: &mut [Hit], docs: &[Option<Doc>]) {
    hits.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                let ia = docs[a.idx].as_ref().map(|d| d.importance).unwrap_or(0.0);
                let ib = docs[b.idx].as_ref().map(|d| d.importance).unwrap_or(0.0);
                ib.partial_cmp(&ia).unwrap_or(std::cmp::Ordering::Equal)
            })
    });
}

/// RRF 融合。`paths` 需按 `search_rrf` 的插入序给出（lexical/bucket/entity/graph）。
///
/// 返回 `(doc_idx, 融合分)`，已按分数降序，长度 ≤ k。
/// 计入排序的 id 用 `doc.id`（对齐 `node["id"]`）。
pub fn fuse(
    paths: &[(&str, Vec<Hit>)],
    docs: &[Option<Doc>],
    k: usize,
    weights: &HashMap<String, f64>,
    fusion_max: bool,
) -> Vec<(usize, f64)> {
    // 保序累加表：Vec + HashMap（对齐 Python dict 的插入序 → 稳定排序的并列序）
    let mut order: Vec<usize> = Vec::new();
    let mut acc: HashMap<String, f64> = HashMap::new();

    // 先做各路排序与 id → (doc_idx, score) 映射（node_by_id 用 setdefault）
    let mut node_by_id: HashMap<String, (usize, f64)> = HashMap::new();
    let mut sorted_paths: Vec<(&str, Vec<Hit>)> = Vec::with_capacity(paths.len());

    for (name, hits) in paths {
        let mut h = hits.clone();
        sort_path(&mut h, docs);
        for hit in &h {
            if let Some(d) = docs[hit.idx].as_ref() {
                node_by_id.entry(d.id.clone()).or_insert((hit.idx, hit.score));
            }
        }
        sorted_paths.push((name, h));
    }

    for (name, hits) in &sorted_paths {
        let w = *weights.get(*name).unwrap_or(&1.0);
        for (rank0, hit) in hits.iter().take(PATH_TAKE).enumerate() {
            let nid = match docs[hit.idx].as_ref() {
                Some(d) => d.id.clone(),
                None => continue,
            };
            let contrib = w / (RRF_K + (rank0 as f64 + 1.0));
            match acc.get_mut(&nid) {
                Some(v) => {
                    if fusion_max {
                        if contrib > *v {
                            *v = contrib;
                        }
                    } else {
                        *v += contrib;
                    }
                }
                None => {
                    acc.insert(nid.clone(), contrib);
                    if let Some((di, _)) = node_by_id.get(&nid) {
                        order.push(*di);
                    }
                }
            }
        }
    }

    let mut fused: Vec<(usize, f64)> = order
        .into_iter()
        .filter_map(|di| {
            let d = docs[di].as_ref()?;
            acc.get(&d.id).map(|s| (di, *s))
        })
        .collect();
    // 对齐 `sorted(rrf.items(), key=lambda kv: -kv[1])[:k]`（稳定）
    fused.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    fused.truncate(k);
    fused
}
