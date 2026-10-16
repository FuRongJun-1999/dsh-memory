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
    // Python `_like`：body 与 tags 双边小写化后做包含判定（terms 已是
    // normalize_en 产物，全小写/中文）。
    // R-2（2026-09-29）：两个小写形态改为**建库时预存**（`Doc::like_body_lower`
    // / `Doc::tags_joined_lower`）——本函数是「每查询 × 每候选」的最内层判定，
    // 原先每次调用对整串各做一次 `to_lowercase()`（整串新分配；Codex 实测
    // 20000 文档语料 search 156ms 中 152ms 在此）。等价变换：表达式逐字不变，
    // 只把求值时机前移（文档内容建库后不变 ⇒ 派生物不变）。
    let body = doc.like_body_lower.as_str();
    let tags = doc.tags_joined_lower.as_str();
    // issue #150（与 Python `_like` 同步）：**空词项会使 `body.contains("")` 恒真**
    // ⇒ LIKE 恒真、全库入池。两侧必须同时修，否则 parity 门禁立刻劈叉。
    terms
        .iter()
        .any(|t| !t.is_empty()
             && (body.contains(t.as_str()) || (!tags.is_empty() && tags.contains(t.as_str()))))
}

/// `_lexical`：LIKE 预筛 → 覆盖率打分。
///
/// `cap` 对齐 `GLOBAL_CAP`（评测侧 `unlock_global_cap()` 置 1e9 → 不截断）。
///
/// issue #363（与 Python `MdCG._score` + `mdcg.lexical_weights` 同步）：legacy
/// 口径（`jaccard == false`）改**池内 IDF + 功能词降权**——权重池 = **截断前**
/// 的 LIKE 命中全量（空命中时=完整候选集；PR #381 复核 P0-② 与 Python 的
/// 「当批全量」口径对齐，详见下方权重表构建处的互指注释）：
///   w(g) = ln(1 + (N - df + 0.5)/(df + 0.5)) × (g ∈ CN_FUNC_GRAMS 时 α)
/// 旧 `|qb ∩ db| / |qb|` 保留为 `MDCG_LEXICAL_IDF=0` 的回退分支（**且**作为
/// 权重表全等的退化池的逐位路径，PR #381 复核 P0-①——全等 ⇒ 无判别信息，
/// 与 Python `lexical_weights` 的 all_equal 跳过同判据）。jaccard 口径
/// **不加权**（两侧钉 jaccard 的 rank_parity 对拍逐位不变）。求和按 gram
/// 字典序（对齐 Python `lexical_sim_weighted` 的 sorted 序求和）。
pub fn lexical(
    docs: &[Option<Doc>],
    cand: &[usize],
    query: &str,
    cap: f64,
    jaccard: bool,
) -> Vec<Hit> {
    let terms = expand_query_terms(query);
    // issue #29：qb 必须与 Python 同口径 = bigrams(normalize_en(query))
    // （en_zh_bigrams 受 MDCG_EN_ATOMS 控制，默认关 → 空集，此处豁免）。
    // 原先用原始 query 取 bigram——英文查询与归一化文档侧交集错位、
    // 混合查询的分数系统性偏移。
    let qnorm = crate::text::normalize_en(query);
    let mut qb = bigrams(&qnorm);
    qb.sort();                        // 加权求和序对齐 Python（dict 序不可复算）
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

    // issue #363：legacy 口径的权重表（池内 IDF × 功能词降权）。None ⇒ 逐位
    // 走旧公式（jaccard / MDCG_LEXICAL_IDF=0 / 空池 / 权重全等的退化池）。
    //
    // PR #381 复核 P0-②（与 Python `mdcg.lexical_weights` docstring 互指）：
    // 权重池 = **截断前**的 LIKE 命中全量（空命中时=完整候选集）——Python 侧
    // `_lexical`/search T2 把「LIKE 预筛后的命中全量」交给 `_score`（GLOBAL_CAP
    // 截断发生在打分**之后**，N 不含截断效应），故本侧必须在
    // `hits.truncate(cap)` **之前**取池。旧实现取 `picked.len()`（截断后命中
    // 池），有限 cap 下 picked ⊊ 命中全量 ⇒ 两侧 IDF 权重劈叉（现役调用
    // cap=1e9 掩盖了它）。空命中兜底池的构成差异（Python 按 importance 取前
    // CAP vs 本侧 cand 序）是 #363 之前的既有面，不属本件靶区，注释留痕。
    //
    // PR #381 复核 P0-①：退化判据 = **权重表全等**（而非「df 全同」——df 全同
    // 但 qb 跨侧〔功能词×实词并存〕时 w 恰差 α 倍，不属退化，α 生效正是设计
    // 靶区）。全等 ⇒ 返回 None 逐位走旧公式：退化池分数与 Python 侧（all_equal
    // 跳过，见 `mdcg.lexical_weights` 尾部）及修前逐位一致——两侧判据必须
    // 同步，否则 rank_parity 在退化池上按位劈叉。
    let weights: Option<std::collections::HashMap<&str, f64>> =
        if !jaccard && qbl > 0.0
            && std::env::var("MDCG_LEXICAL_IDF").as_deref() != Ok("0")
        {
            let pool: &[usize] = if hits.is_empty() { cand } else { &hits };
            let n = pool.len() as f64;
            let mut w = std::collections::HashMap::with_capacity(qb.len());
            let mut all_equal = true;            // P0-①：权重全等 ⇒ 退化 ⇒ None
            let mut first: Option<f64> = None;
            for g in qb.iter() {
                let mut df = 0.0f64;
                for &i in pool.iter() {
                    if let Some(d) = docs[i].as_ref() {
                        if d.stripped.contains(g.as_str()) {
                            df += 1.0;
                        }
                    }
                }
                let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
                let mult = if crate::text::CN_FUNC_GRAMS.contains(&g.as_str()) {
                    crate::text::FUNC_GRAM_ALPHA
                } else {
                    1.0
                };
                let v = idf * mult;
                match first {
                    None => first = Some(v),
                    Some(f) if v != f => all_equal = false,
                    _ => {}
                }
                w.insert(g.as_str(), v);
            }
            if n > 0.0 && !all_equal {
                Some(w)
            } else {
                None
            }
        } else {
            None
        };
    // 分母对池内所有文档相同：循环外一次（对齐 Python lexical_sim_weighted
    // 的 sorted 序求和）。
    let w_den: f64 = weights.as_ref().map_or(0.0, |w| {
        let mut acc = 0.0;
        for g in qb.iter() {
            if let Some(v) = w.get(g.as_str()) {
                acc += *v;
            }
        }
        acc
    });

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
        // legacy+IDF（#363）：`Σw(qb ∩ db) / Σw(qb)`（功能词降权 + 池内 IDF）
        let sim = if jaccard {
            let denom = (qb.len() + d.db_len).saturating_sub(cap_hit);
            if denom > 0 {
                cap_hit as f64 / denom as f64
            } else {
                0.0
            }
        } else if let Some(w) = weights.as_ref() {
            if w_den > 0.0 {
                let mut num = 0.0;
                for g in qb.iter() {
                    if d.stripped.contains(g.as_str()) {
                        if let Some(v) = w.get(g.as_str()) {
                            num += *v;
                        }
                    }
                }
                num / w_den
            } else {
                0.0
            }
        } else if qbl > 0.0 {
            cap_hit as f64 / qbl
        } else {
            0.0
        };
        // 对齐 `any(str(t) and (str(t) in q or q in str(t)) for t in tags)`：逐个 tag
        // 判定，**做空串过滤**（issue #150，2026-10-11 与 Python 同步）。
        // 修前本处注释写的是「不做空串过滤（Python 里 `"" in q` 恒真，会触发 bonus）」
        // ——那是**显式保留**同一缺陷以维持两侧一致；本件把两侧一起修，
        // 该注释随之改写（保留此句以免后人以为可以只改一侧）。
        let tag_bonus = if !query.is_empty()
            && d.tags.iter().any(|t| {
                !t.is_empty() && (query.contains(t.as_str()) || t.contains(query))
            })
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

/// 对齐 `sorted(scored, key=lambda x: (-score, -importance, str(id)))`
/// （`mdcos._lexical` 三键排序；issue #29：第三键 id 缺失会让分数并列时
/// 路内顺序漂移 → RRF 名次连锁偏移）。
///
/// P4（设计稿 §七）：`apply_freshness=true` 时，**先**把每条的分数乘上刷新/衰减
/// 乘子（`crate::freshness::factor`，与 Python `MdCG._score` 同位同式），再排三键。
/// 为什么只在 lexical 路开（`fuse` 里仅传给 lexical）见 `freshness.rs` 头注：
/// Python 的 `_score` 只服务 lexical/bucket 两路，entity/graph 的分数在别处产生
/// ——若在 `sort_path` 里对每一路都乘一次，entity 路的两侧名次就会分叉。
pub fn sort_path(hits: &mut [Hit], docs: &[Option<Doc>], apply_freshness: bool) {
    if apply_freshness && crate::freshness::enabled() {
        let now = crate::freshness::now();
        for h in hits.iter_mut() {
            if let Some(d) = docs[h.idx].as_ref() {
                h.score *= crate::freshness::factor(
                    d.created_at, d.access_count, d.last_access,
                    d.importance, d.protected, now);
            }
        }
    }
    hits.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                let ia = docs[a.idx].as_ref().map(|d| d.importance).unwrap_or(0.0);
                let ib = docs[b.idx].as_ref().map(|d| d.importance).unwrap_or(0.0);
                ib.partial_cmp(&ia).unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                let ida = docs[a.idx].as_ref().map(|d| d.id.clone()).unwrap_or_default();
                let idb = docs[b.idx].as_ref().map(|d| d.id.clone()).unwrap_or_default();
                ida.cmp(&idb)
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
        // P4：乘子只对 **lexical** 路生效（Python `_score` 的对位面；见
        // `freshness.rs` 头注与 `sort_path` 的 docstring）。
        sort_path(&mut h, docs, *name == "lexical");
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
    // 对齐 `sorted(rrf.items(), key=lambda kv: (-kv[1], kv[0]))[:k]`
    // （mdcos.py:1300——id 兜底次键。issue #29 勘误：本注释原先只写
    // `-kv[1]`，与 Python 实际实现不符；该兜底虽非本 issue 现象成因，
    // 但注释与实现必须一致，避免下一个维护者按错注释实现）
    fused.sort_by(|a, b| {
        let ida = docs[a.0].as_ref().map(|d| d.id.clone()).unwrap_or_default();
        let idb = docs[b.0].as_ref().map(|d| d.id.clone()).unwrap_or_default();
        b.1.partial_cmp(&a.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| ida.cmp(&idb))
    });
    fused.truncate(k);
    fused
}
