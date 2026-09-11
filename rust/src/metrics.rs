//! 指标层：与 `md_cg/eval_common.py` 的 `first_evidence_rank` / `summarize` /
//! `calibrate_line` / `refusal_metrics` / `false_refusal_rate` 逐式对齐。
//! 分位取法照抄（`top1[len // 10]`，非插值分位）。

use std::collections::BTreeMap;

/// 单题明细（对齐 `evaluate_group` 的 row）。
#[derive(Debug, Clone)]
pub struct Row {
    pub qid: String,
    pub qtype: String,
    /// 首个证据 turn 的 1-based 名次；未命中为 0
    pub rank: usize,
    pub top1_score: f64,
    pub n_res: usize,
    /// Top-K 结果节点 id（诊断用，不参与统计）
    pub top: Vec<String>,
    /// Top-K 融合分（与 `top` 同序）
    pub top_scores: Vec<f64>,
}

/// 对齐 `first_evidence_rank`。
pub fn first_evidence_rank(ids: &[String], evidence: &std::collections::HashSet<String>) -> usize {
    if evidence.is_empty() {
        return 0;
    }
    for (i, id) in ids.iter().enumerate() {
        if evidence.contains(id) {
            return i + 1;
        }
    }
    0
}

/// 单组统计（对齐 `summarize` 的一项）。
#[derive(Debug, Clone, Default)]
pub struct Stat {
    pub n: usize,
    pub hit1: f64,
    pub hitk: f64,
    pub mrr: f64,
}

impl Stat {
    fn of(rows: &[&Row], k: usize) -> Stat {
        let n = rows.len();
        if n == 0 {
            return Stat::default();
        }
        let hit1 = rows.iter().filter(|r| r.rank == 1).count() as f64 / n as f64;
        let hitk = rows.iter().filter(|r| r.rank > 0 && r.rank <= k).count() as f64 / n as f64;
        let mrr = rows
            .iter()
            .filter(|r| r.rank > 0)
            .map(|r| 1.0 / r.rank as f64)
            .sum::<f64>()
            / n as f64;
        Stat {
            n,
            hit1,
            hitk,
            mrr,
        }
    }
}

/// 一组题的全量统计（对齐 `summarize`）。
#[derive(Debug, Clone, Default)]
pub struct Summary {
    pub n: usize,
    pub hit1: f64,
    pub hitk: f64,
    pub mrr: f64,
    pub score_p10: f64,
    pub score_p50: f64,
    pub by_qtype: BTreeMap<String, Stat>,
}

pub fn summarize(rows: &[Row], k: usize) -> Summary {
    if rows.is_empty() {
        return Summary::default();
    }
    let all: Vec<&Row> = rows.iter().collect();
    let s = Stat::of(&all, k);

    let mut top1: Vec<f64> = rows.iter().map(|r| r.top1_score).collect();
    top1.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let p10 = top1[top1.len() / 10];
    let p50 = top1[top1.len() / 2];

    let mut by: BTreeMap<String, Vec<&Row>> = BTreeMap::new();
    for r in rows {
        by.entry(r.qtype.clone()).or_default().push(r);
    }
    let by_qtype = by
        .into_iter()
        .map(|(qt, g)| (qt, Stat::of(&g, k)))
        .collect();

    Summary {
        n: s.n,
        hit1: s.hit1,
        hitk: s.hitk,
        mrr: s.mrr,
        score_p10: p10,
        score_p50: p50,
        by_qtype,
    }
}

/// 对齐 `calibrate_line`：正例 hit@1 题 Top-1 分的 10 分位。
pub fn calibrate_line(pos_rows: &[Row]) -> f64 {
    let mut scores: Vec<f64> = pos_rows
        .iter()
        .filter(|r| r.rank == 1)
        .map(|r| r.top1_score)
        .collect();
    scores.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    if scores.is_empty() {
        0.0
    } else {
        scores[scores.len() / 10]
    }
}

/// 对齐 `refusal_metrics`：Top-1 分 < line 记为拒答。
pub fn refusal_metrics(rows: &[Row], line: f64) -> (usize, usize, f64) {
    let n = rows.len();
    if n == 0 {
        return (0, 0, 0.0);
    }
    let refused = rows.iter().filter(|r| r.top1_score < line).count();
    (n, refused, refused as f64 / n as f64)
}

/// 对齐 `false_refusal_rate`：正例被误杀的占比。
pub fn false_refusal_rate(rows: &[Row], line: f64) -> f64 {
    let n = rows.len();
    if n == 0 {
        return 0.0;
    }
    rows.iter().filter(|r| r.top1_score < line).count() as f64 / n as f64
}

/// 对齐 `pct`。
pub fn pct(x: f64) -> String {
    format!("{:.1}%", x * 100.0)
}
