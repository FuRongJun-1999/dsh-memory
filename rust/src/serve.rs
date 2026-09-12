//! serve 模式：stdin 逐行 JSON 请求 → stdout 逐行 JSON 响应；进程存活 = 实例。
//!
//! 模式参照 protocol-compiler `rust_runtime/src/serve.rs`（蜂群实例基座）：
//! 协调器 spawn 多个 `mdcg-eval --serve` 进程即得多个检索实例——索引只读共享、
//! OS 页缓存复用，语言无关（Python/Node/Rust 宿主均可经 stdin/stdout 驱动）。
//!
//! 协议（一行一请求，一行一响应）：
//!   请求  `{"op":"search","query":"...","k":5}`  → 命中列表
//!         `{"op":"info"}`                        → 引擎元信息
//!         `{"op":"ping"}`                        → 存活探测
//!         文本行 `quit` 或 EOF                   → 实例退出
//!   响应  `{"ok":true,...}` / `{"ok":false,"error":"..."}`

use std::io::{BufRead, Write};
use std::time::Instant;

use crate::engine::SearchEngine;
use crate::json::Json;

/// serve 主循环。引擎已由调用方载入；EOF / `quit` / 管道断裂时返回 0。
pub fn run(engine: SearchEngine) -> i32 {
    let stdin = std::io::stdin();
    let mut out = std::io::stdout();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break, // 管道关闭 → 实例退出
        };
        let line = line.trim().to_string();
        if line.is_empty() {
            continue;
        }
        if line == "quit" {
            break;
        }
        let resp = handle(&engine, &line);
        if writeln!(out, "{resp}").is_err() || out.flush().is_err() {
            break; // 协调器关闭管道 → 实例退出
        }
    }
    0
}

fn handle(engine: &SearchEngine, line: &str) -> String {
    let req = match crate::json::parse(line) {
        Ok(v) => v,
        Err(e) => return err(format!("请求 JSON 非法: {e}")),
    };
    let op = req.get("op").and_then(|v| v.as_str()).unwrap_or("");
    match op {
        "ping" => Json::Obj(vec![
            ("ok".to_string(), Json::Bool(true)),
            ("pong".to_string(), Json::Bool(true)),
        ])
        .to_json_string(),
        "info" => Json::Obj(vec![
            ("ok".to_string(), Json::Bool(true)),
            ("root".to_string(), Json::Str(engine.root().to_string_lossy().to_string())),
            ("docs".to_string(), Json::Num(engine.doc_count() as f64)),
            ("candidates".to_string(), Json::Num(engine.candidate_count() as f64)),
            (
                "paths".to_string(),
                Json::Arr(engine.paths().iter().map(|p| Json::Str(p.clone())).collect()),
            ),
        ])
        .to_json_string(),
        "search" => {
            let Some(query) = req.get("query").and_then(|v| v.as_str()) else {
                return err("search 缺 query 字段".to_string());
            };
            let k = req
                .get("k")
                .and_then(|v| v.as_f64())
                .map(|f| f as usize)
                .unwrap_or(5)
                .max(1);
            let t0 = Instant::now();
            let hits = engine.search(query, k);
            let took_ms = t0.elapsed().as_millis() as f64;
            let hits_json: Vec<Json> = hits
                .iter()
                .map(|h| {
                    Json::Obj(vec![
                        ("id".to_string(), Json::Str(h.id.clone())),
                        ("path".to_string(), Json::Str(h.path.clone())),
                        ("layer".to_string(), Json::Str(h.layer.clone())),
                        ("score".to_string(), Json::Num(h.score)),
                    ])
                })
                .collect();
            let count = hits_json.len() as f64;
            Json::Obj(vec![
                ("ok".to_string(), Json::Bool(true)),
                ("count".to_string(), Json::Num(count)),
                ("took_ms".to_string(), Json::Num(took_ms)),
                ("hits".to_string(), Json::Arr(hits_json)),
            ])
            .to_json_string()
        }
        other => err(format!("未知 op: {other}")),
    }
}

fn err(msg: String) -> String {
    Json::Obj(vec![
        ("ok".to_string(), Json::Bool(false)),
        ("error".to_string(), Json::Str(msg)),
    ])
    .to_json_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::EngineConfig;

    fn mini_engine() -> SearchEngine {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("mdcg_eval_serve_test_{nanos}"));
        std::fs::create_dir_all(root.join("knowledge")).unwrap();
        std::fs::write(
            root.join("_index.json"),
            r#"{"nodes":{"mem_a":{"path":"knowledge/mem_a.md","layer":"knowledge","tags":["评测"],"importance":0.6,"edges":[]}}}"#,
        )
        .unwrap();
        std::fs::write(
            root.join("knowledge").join("mem_a.md"),
            "---\nid: \"mem_a\"\ntags: [\"评测\"]\nimportance: 0.6\n---\n评测复现数据集。\n",
        )
        .unwrap();
        SearchEngine::open(&root, &EngineConfig::default()).unwrap()
    }

    #[test]
    fn search_op_roundtrip() {
        let eng = mini_engine();
        let resp = handle(&eng, r#"{"op":"search","query":"评测复现","k":3}"#);
        let v = crate::json::parse(&resp).unwrap();
        assert!(matches!(v.get("ok"), Some(crate::json::Json::Bool(true))));
        assert_eq!(v.get("count").and_then(|x| x.as_f64()), Some(1.0));
        let hits = v.get("hits").unwrap().as_arr().unwrap();
        assert_eq!(hits[0].get("id").and_then(|x| x.as_str()), Some("mem_a"));
    }

    #[test]
    fn bad_requests_report_error() {
        let eng = mini_engine();
        for line in [
            "not json",
            r#"{"op":"search"}"#,
            r#"{"op":"nope"}"#,
        ] {
            let v = crate::json::parse(&handle(&eng, line)).unwrap();
            assert!(
                matches!(v.get("ok"), Some(crate::json::Json::Bool(false))),
                "{line}"
            );
            assert!(v.get("error").is_some(), "{line}");
        }
    }
}
