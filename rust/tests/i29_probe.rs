//! issue #29 临时探针：zh_08/zh_09 在 Rust lexical 路的分数与排序。

use mdcg_eval::retrieval::{self};
use mdcg_eval::store::Doc;

fn doc(id: &str, body: &str) -> Option<Doc> {
    let content = format!("---\nid: \"{id}\"\nimportance: 0.5\n---\n# 功能名：zh 样本\n# 正文：{body} 样本\n");
    let stripped = mdcg_eval_text_norm(&content);
    let db_len = mdcg_eval_text_bigrams(&stripped).len();
    // R-2（2026-09-29）：`like_body_lower` / `tags_joined_lower` 建库期预存——
    // 手工构造 Doc 的探针同样要按 `store::read_doc` 的同款口径填（此处
    // lit=None ⇒ like_body() 回落 content）。
    let like_body_lower = content.to_lowercase();
    Some(Doc {
        id: id.to_string(),
        importance: 0.5,
        tags: vec![],
        tags_joined: String::new(),
        like_body_lower,
        tags_joined_lower: String::new(),
        content,
        stripped,
        db_len,
        lit: None,
        edges: vec![],
        created_at: 0.0,
        access_count: 0.0,
        last_access: 0.0,
        protected: false,
    })
}

// text 层函数未在 lib 重导出时经由 pub use 使用
fn mdcg_eval_text_norm(s: &str) -> String {
    mdcg_eval::text::normalize_en(s)
}
fn mdcg_eval_text_bigrams(s: &str) -> Vec<String> {
    mdcg_eval::text::bigrams(s)
}

#[test]
fn probe_zh_tie() {
    let docs = vec![
        doc("parity_zh_08", "蜂群调度器按 workers 上限领取任务 样本8"),
        doc("parity_zh_09", "依赖门禁在领取前检查上游终态 样本9"),
    ];
    let cand: Vec<usize> = vec![0, 1];
    let hits = retrieval::lexical(&docs, &cand, "蜂群调度 依赖门禁", 1e9, false);
    for h in &hits {
        println!("  {} -> {:?}", docs[h.idx].as_ref().unwrap().id, h.score);
    }
    let mut hits = hits;
    retrieval::sort_path(&mut hits, &docs, false);
    println!("  sorted:");
    for h in &hits {
        println!("  {}", docs[h.idx].as_ref().unwrap().id);
    }
    assert_eq!(hits.len(), 2);
}
