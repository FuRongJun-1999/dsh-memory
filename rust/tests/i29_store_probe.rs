//! issue #29 探针②：真实 store 链路（load_index/load_docs）下的
//! lexical 分数与排序——对照手构 Doc 探针。

use mdcg_eval::retrieval;
use mdcg_eval::store;

#[test]
fn probe_store_zh_tie() {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let root = std::env::var("I29_ROOT")
        .map(|p| std::path::PathBuf::from(p))
        .unwrap_or_else(|_| {
            let d = std::env::temp_dir().join(format!("mdcg_i29_store_{nanos}"));
            std::fs::create_dir_all(d.join("knowledge")).unwrap();
            d
        });
    println!("root = {}", root.display());
    let seeded = !root.join("_index.json").exists();
    if seeded {
        std::fs::write(
            root.join("_index.json"),
            r#"{"nodes":{"parity_zh_08":{"path":"knowledge/parity_zh_08.md","layer":"knowledge","tags":[],"importance":0.5,"edges":[]},"parity_zh_09":{"path":"knowledge/parity_zh_09.md","layer":"knowledge","tags":[],"importance":0.5,"edges":[]}}}"#,
        )
        .unwrap();
        let body08 = "蜂群调度器按 workers 上限领取任务 样本8";
        let body09 = "依赖门禁在领取前检查上游终态 样本9";
        std::fs::write(
            root.join("knowledge").join("parity_zh_08.md"),
            format!("---\nid: \"parity_zh_08\"\nimportance: 0.5\n---\n# 功能名：zh 样本 8\n# 正文：{body08} 样本8\n"),
        )
        .unwrap();
        std::fs::write(
            root.join("knowledge").join("parity_zh_09.md"),
            format!("---\nid: \"parity_zh_09\"\nimportance: 0.5\n---\n# 功能名：zh 样本 9\n# 正文：{body09} 样本9\n"),
        )
        .unwrap();
    }

    let cfg = mdcg_eval::engine::EngineConfig::default();
    let entries = store::load_index(&root, cfg.order).unwrap();
    let docs = store::load_docs(&root, &entries, 4);
    let cand = store::candidates(&entries);
    let hits = retrieval::lexical(&docs, &cand, "蜂群调度 依赖门禁", 1e9, false);
    for h in &hits {
        let d = docs[h.idx].as_ref().unwrap();
        let norm_eq = d.stripped.contains("蜂群调度");
        println!("  {} score={:?} norm_eq={}", d.id, h.score, norm_eq);
    }
    let mut hits = hits;
    retrieval::sort_path(&mut hits, &docs);
    print!("  sorted:");
    for h in &hits {
        print!(" {}", docs[h.idx].as_ref().unwrap().id);
    }
    println!();
    // 断言：Python 并列 + id 兜底 → zh_08 必须在 zh_09 前（issue #29 对齐）
    let ids: Vec<String> = hits
        .iter()
        .map(|h| docs[h.idx].as_ref().unwrap().id.clone())
        .collect();
    assert_eq!(ids, vec!["parity_zh_08".to_string(), "parity_zh_09".to_string()],
               "同分并列时 id 兜底应使 zh_08 在前");
}
