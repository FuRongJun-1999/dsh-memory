//! 灵枢记忆系统 · 公开数据集评测器（Rust）
//!
//! 用 Rust 直接读「已建库」的公开数据集语料跑评测：LoCoMo 子集 500 题
//! + LongMemEval-S 500 题（口径 A legacy、四路 RRF）。
//! **注**：LongMemEval-S 本地副本已移除（本仓库不再对其产出成绩），`lm`
//! 半程需按 `data/external/longmemeval/VERSION.json` 自行重下数据后才能跑；
//! 默认可直接跑通的是 LoCoMo 子集（`--dataset lc`）。
//!
//! 与 Python 侧（`bench_locomo.py` / `bench_longmem.py` / `eval_common.py`）
//! **逐项对齐**：
//!   * 候选集 `_candidates`：跳 rejected/unresolved/goals，排除 WORK_ROLES
//!   * 四路 lexical/bucket/entity/graph + `RRF_K=60` + 每路取 50
//!   * 打分 `sim = |qb ∩ db| / |qb ∪ db|`（缺省 jaccard，与 Python
//!     mdcg.SCORE_MODE 缺省一致）+ tag_bonus(≤1.0)；
//!     `--score legacy` 切回 `|qb ∩ db| / |qb|`（只归一化查询侧，旧基线）
//!   * 指标 rank(1-based) / hit@1 / hit@k / MRR / 拒答线 = 正例 hit@1 题 Top-1 分 p10
//!
//! 唯一无法逐位保证的是**并列分数的名次**（Python `_scan_nodes` 依赖目录枚举序），
//! 故提供 `--order scan|log`，默认 `scan`（模拟文件名序）。

// 模块统一由 lib target（mdcg_eval）供给：单一编译源，避免 bin/lib 双编译
// 产生两个不同身份的同名类型（E0308）。评测逻辑与库共享同一份实现。
use mdcg_eval::{json, metrics, retrieval, serve, store};

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::time::Instant;

use json::Json;
use metrics::{Row, Summary};
use mdcg_eval::engine::{EngineConfig, SearchEngine};
use retrieval::Hit;
use store::{Entry, Order};

// ---------------------------------------------------------------- 配置

struct Cfg {
    root: PathBuf,
    dataset: String,
    k: usize,
    threads: usize,
    order: Order,
    paths: Vec<String>,
    fusion_max: bool,
    weights: HashMap<String, f64>,
    n: usize,
    out_dir: PathBuf,
    tag: String,
    dump: Option<PathBuf>,
    jaccard: bool,
    lib: Option<PathBuf>,
    qfile: Option<PathBuf>,
    /// `--graph-seeds sorted`：按 `_path_graph` 文档语义先排序再取 top-5 种子。
    /// 缺省 false = 现状（传未排序词法输出），保持与 Python `search_rrf` 逐位对齐。
    graph_seeds_sorted: bool,
    /// `--serve`：进入进程实例模式（stdin/stdout 逐行 JSON），不跑评测。
    serve: bool,
}

fn default_threads() -> usize {
    std::thread::available_parallelism().map(|v| v.get()).unwrap_or(4)
}

fn parse_args() -> Cfg {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."));
    let out_dir = root.join("data").join("external").join("eval_results");
    let mut cfg = Cfg {
        root,
        // 默认 lc：公开可跑通的那半程。lm（LongMemEval-S）本地副本已移除，
        // 需自备数据后显式 `--dataset lm|both`，故不再作为默认（曾致外部
        // 直接 `cargo run` 因数据缺失 exit(1)）。
        dataset: "lc".into(),
        k: 5,
        threads: default_threads(),
        order: Order::Scan,
        paths: vec![
            "lexical".into(),
            "bucket".into(),
            "entity".into(),
            "graph".into(),
        ],
        fusion_max: false,
        weights: HashMap::new(),
        n: 0,
        out_dir,
        tag: "rust".into(),
        dump: None,
        jaccard: true, // 缺省 jaccard（长度自惩罚），与 Python SCORE_MODE 缺省一致
        lib: None,
        qfile: None,
        graph_seeds_sorted: false,
        serve: false,
    };

    let argv: Vec<String> = std::env::args().skip(1).collect();
    let mut i = 0usize;
    while i < argv.len() {
        let a = argv[i].clone();
        let take = |i: &mut usize| -> String {
            *i += 1;
            argv.get(*i).cloned().unwrap_or_default()
        };
        match a.as_str() {
            "--dataset" => cfg.dataset = take(&mut i),
            "--k" => cfg.k = take(&mut i).parse().unwrap_or(5),
            "--threads" => {
                cfg.threads = take(&mut i).parse().unwrap_or_else(|_| default_threads())
            }
            "--order" => {
                cfg.order = match take(&mut i).as_str() {
                    "log" => Order::Log,
                    _ => Order::Scan,
                }
            }
            "--paths" => {
                let ps: Vec<String> = take(&mut i)
                    .split(',')
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect();
                if !ps.is_empty() {
                    cfg.paths = ps;
                }
            }
            "--fusion" => cfg.fusion_max = take(&mut i) == "max",
            "--weights" => {
                for p in take(&mut i).split(',') {
                    if let Some((k, v)) = p.split_once(':') {
                        if let Ok(f) = v.trim().parse::<f64>() {
                            cfg.weights.insert(k.trim().to_string(), f);
                        }
                    }
                }
            }
            "--n" => cfg.n = take(&mut i).parse().unwrap_or(0),
            "--out" => cfg.out_dir = PathBuf::from(take(&mut i)),
            "--root" => cfg.root = PathBuf::from(take(&mut i)),
            "--tag" => cfg.tag = take(&mut i),
            "--dump" => cfg.dump = Some(PathBuf::from(take(&mut i))),
            "--score" => cfg.jaccard = take(&mut i).eq_ignore_ascii_case("jaccard"),
            "--lib" => cfg.lib = Some(PathBuf::from(take(&mut i))),
            "--qfile" => cfg.qfile = Some(PathBuf::from(take(&mut i))),
            "--graph-seeds" => {
                cfg.graph_seeds_sorted = take(&mut i).eq_ignore_ascii_case("sorted")
            }
            "--serve" => cfg.serve = true,
            "--help" | "-h" => {
                print_help();
                std::process::exit(0);
            }
            other => {
                eprintln!("未知参数：{other}（--help 查看用法）");
                std::process::exit(2);
            }
        }
        i += 1;
    }
    cfg
}

/// 当前词法口径标签——输出标题必须跟随 `--score`（缺省 jaccard），
/// 否则切 legacy 时标题仍写 jaccard，读数会被误导。
fn score_label(cfg: &Cfg) -> &'static str {
    if cfg.jaccard {
        "jaccard"
    } else {
        "legacy"
    }
}

fn print_help() {
    println!(
        "mdcg-eval —— 灵枢公开数据集评测器（Rust，四路 RRF）

用法：mdcg-eval [选项]
  --dataset lc|lm|both  跑哪个数据集（默认 lc = LoCoMo 子集 500 题；
                        lm=LongMemEval-S 500 题，需自备本地副本）
  --k N                 Top-K（默认 5）
  --threads N           并行线程数（默认 CPU 核数）
  --order scan|log      候选顺序：scan=模拟目录枚举序（默认）/ log=索引日志序
  --paths a,b,c         召回路，默认 lexical,bucket,entity,graph
  --fusion sum|max      RRF 融合方式（默认 sum）
  --weights k:1,m:0.2   路权重覆盖
  --n N                 每组题量上限（0=全部；注意与 Python 的随机抽样不同）
  --out DIR             结果 JSON 目录
  --root DIR            工作区根（默认 cargo 清单上级目录）
  --tag NAME            结果文件名后缀（默认 rust）
  --dump FILE           逐题明细（qid/qtype/rank/top-k id）追加写入，供诊断
  --score MODE          词法打分：jaccard（默认，|qb∩db|/|qb∪db|，长度自惩罚）
                        | legacy（|qb∩db|/|qb|，只归一化查询侧，长文档占优）
  --lib DIR             显式指定评测库（覆盖数据集默认；zh_mad 消融臂逐个指定）
  --qfile FILE          显式指定题库 jsonl（覆盖数据集默认）
  --help                显示本帮助"
    );
}

// ---------------------------------------------------------------- 题库

#[derive(Clone)]
struct Question {
    qid: String,
    qtype: String,
    question: String,
    evidence: HashSet<String>,
}

fn load_questions(path: &Path) -> Result<Vec<Question>, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut out = Vec::new();
    for (lineno, line) in raw.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let v = json::parse(line)
            .map_err(|e| format!("{}:{} 解析失败: {e}", path.display(), lineno + 1))?;
        out.push(Question {
            qid: v.get("qid").and_then(|x| x.as_str()).unwrap_or("").to_string(),
            qtype: v.get("qtype").and_then(|x| x.as_str()).unwrap_or("").to_string(),
            question: v
                .get("question")
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string(),
            evidence: v
                .get("evidence_turns")
                .map(|x| x.as_str_vec().into_iter().collect())
                .unwrap_or_default(),
        });
    }
    Ok(out)
}

/// 分组映射，与 `bench_locomo.GROUPS` / `bench_longmem.GROUPS` 逐项一致（保序）。
fn groups_of(ds: &str) -> Vec<(&'static str, Vec<&'static str>)> {
    match ds {
        "lc" => vec![
            ("precise", vec!["single_hop"]),
            ("temporal", vec!["temporal_reasoning"]),
            ("interference", vec!["multi_hop"]),
            ("negative", vec!["adversarial"]),
            ("reference", vec!["open_domain"]),
        ],
        _ => vec![
            (
                "precise",
                vec![
                    "single-session-user",
                    "single-session-assistant",
                    "single-session-preference",
                ],
            ),
            ("temporal", vec!["temporal-reasoning"]),
            ("interference", vec!["knowledge-update"]),
            ("reference", vec!["multi-session"]),
        ],
    }
}

const POS_GROUPS: [&str; 3] = ["precise", "temporal", "interference"];

// ---------------------------------------------------------------- 检索

fn has_path(cfg: &Cfg, p: &str) -> bool {
    cfg.paths.iter().any(|x| x == p)
}

fn search(
    docs: &[Option<store::Doc>],
    entries: &[Entry],
    cand: &[usize],
    query: &str,
    cfg: &Cfg,
) -> Vec<(usize, f64)> {
    let mut ranked: Vec<(&str, Vec<Hit>)> = Vec::new();

    // 插入序对齐 search_rrf：lexical → bucket → entity → graph
    let lex_raw: Vec<Hit> = if has_path(cfg, "lexical") {
        let h = retrieval::lexical(docs, cand, query, 1e9, cfg.jaccard); // unlock_global_cap
        ranked.push(("lexical", h.clone()));
        h
    } else {
        Vec::new()
    };
    if has_path(cfg, "bucket") {
        // 评测链路不传 context（run_query 未传）→ 恒空
        ranked.push(("bucket", retrieval::bucket(entries, cand, false)));
    }
    if has_path(cfg, "entity") {
        ranked.push(("entity", retrieval::entity(docs, cand, query)));
    }
    if has_path(cfg, "graph") {
        // Python 传的是**未排序**的词法输出（ranked.get("lexical")），
        // `_path_graph` 内部取 seeds[:5]；口径 A 下 edges 恒空 → 此路恒空。
        // ⚠ 种子口径耦合：`_lexical` 仅在 LIKE 命中 > GLOBAL_CAP(500) 时才排序，
        // 故候选 ≤500 时 seeds[:5] 退化为**索引枚举序前 5 条**（与查询相关性脱钩）。
        // `--graph-seeds sorted` 改为按 `_path_graph` 文档语义（「已排序种子」）
        // 先排序再取种，用于隔离「种子口径缺陷」与「边结构质量」两类失配。
        let seeds: Vec<Hit> = if cfg.graph_seeds_sorted {
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
        ranked.push(("graph", retrieval::graph(docs, entries, cand, &seeds)));
    }

    let mut fused = retrieval::fuse(&ranked, docs, cfg.k, &cfg.weights, cfg.fusion_max);
    for (_, s) in fused.iter_mut() {
        *s = (*s * 1e6).round() / 1e6; // 对齐 round(s, 6)
    }
    fused
}

fn eval_group(
    docs: &[Option<store::Doc>],
    entries: &[Entry],
    cand: &[usize],
    qs: &[&Question],
    cfg: &Cfg,
) -> Vec<Row> {
    let n = qs.len();
    if n == 0 {
        return Vec::new();
    }
    let t = cfg.threads.max(1).min(n);
    let chunk = n.div_ceil(t);
    let mut out: Vec<Row> = Vec::with_capacity(n);
    out.resize_with(
        n,
        || Row {
            qid: String::new(),
            qtype: String::new(),
            rank: 0,
            top1_score: 0.0,
            n_res: 0,
            top: Vec::new(),
            top_scores: Vec::new(),
        },
    );
    std::thread::scope(|scope| {
        for (qc, rc) in qs.chunks(chunk).zip(out.chunks_mut(chunk)) {
            scope.spawn(move || {
                for (q, slot) in qc.iter().zip(rc.iter_mut()) {
                    let res = search(docs, entries, cand, &q.question, cfg);
                    let ids: Vec<String> = res
                        .iter()
                        .filter_map(|(i, _)| docs[*i].as_ref().map(|d| d.id.clone()))
                        .collect();
                    let take = cfg.k.min(ids.len());
                    let top: Vec<String> = ids[..take].to_vec();
                    let top_scores: Vec<f64> = res[..take].iter().map(|(_, s)| *s).collect();
                    *slot = Row {
                        qid: q.qid.clone(),
                        qtype: q.qtype.clone(),
                        rank: metrics::first_evidence_rank(&ids, &q.evidence),
                        top1_score: res.first().map(|(_, s)| *s).unwrap_or(0.0),
                        n_res: res.len(),
                        top,
                        top_scores,
                    };
                }
            });
        }
    });
    out
}

// ---------------------------------------------------------------- 报表

fn print_table(title: &str, groups: &[(&str, Summary)], k: usize) {
    println!("\n== {title}（证据命中口径，k={k}）==");
    println!(
        "{:<28}{:>6}{:>9}{:>9}{:>8}",
        "组",
        "n",
        "hit@1",
        format!("hit@{k}"),
        "MRR"
    );
    println!("{}", "-".repeat(62));
    for (name, s) in groups {
        if s.n == 0 {
            println!("{:<28}{:>6}   -", name, 0);
            continue;
        }
        println!(
            "{:<28}{:>6}{:>9}{:>9}{:>8.3}",
            name,
            s.n,
            metrics::pct(s.hit1),
            metrics::pct(s.hitk),
            s.mrr
        );
        for (qt, st) in &s.by_qtype {
            println!(
                "  ├ {:<24}{:>6}{:>9}{:>9}{:>8.3}",
                qt,
                st.n,
                metrics::pct(st.hit1),
                metrics::pct(st.hitk),
                st.mrr
            );
        }
    }
}

fn summary_json(s: &Summary, k: usize) -> Json {
    let by = s
        .by_qtype
        .iter()
        .map(|(qt, st)| {
            (
                qt.clone(),
                Json::Obj(vec![
                    ("n".into(), Json::Num(st.n as f64)),
                    ("hit@1".into(), Json::Num(st.hit1)),
                    (format!("hit@{k}"), Json::Num(st.hitk)),
                    ("mrr".into(), Json::Num(st.mrr)),
                ]),
            )
        })
        .collect();
    Json::Obj(vec![
        ("n".into(), Json::Num(s.n as f64)),
        ("hit@1".into(), Json::Num(s.hit1)),
        (format!("hit@{k}"), Json::Num(s.hitk)),
        ("mrr".into(), Json::Num(s.mrr)),
        ("score_p10".into(), Json::Num(s.score_p10)),
        ("score_p50".into(), Json::Num(s.score_p50)),
        ("by_qtype".into(), Json::Obj(by)),
    ])
}

fn pretty(j: &Json, indent: usize) -> String {
    let pad = " ".repeat(indent);
    match j {
        Json::Arr(a) => {
            if a.is_empty() {
                return "[]".into();
            }
            let inner: Vec<String> = a
                .iter()
                .map(|v| format!("{}{}", " ".repeat(indent + 2), pretty(v, indent + 2)))
                .collect();
            format!("[\n{}\n{}]", inner.join(",\n"), pad)
        }
        Json::Obj(kv) => {
            if kv.is_empty() {
                return "{}".into();
            }
            let inner: Vec<String> = kv
                .iter()
                .map(|(k, v)| {
                    format!(
                        "{}{}: {}",
                        " ".repeat(indent + 2),
                        Json::Str(k.clone()).to_json_string(),
                        pretty(v, indent + 2)
                    )
                })
                .collect();
            format!("{{\n{}\n{}}}", inner.join(",\n"), pad)
        }
        other => other.to_json_string(),
    }
}

fn save_result(out_dir: &Path, name: &str, payload: &Json) -> Result<PathBuf, String> {
    std::fs::create_dir_all(out_dir).map_err(|e| e.to_string())?;
    let p = out_dir.join(name);
    std::fs::write(&p, pretty(payload, 0)).map_err(|e| e.to_string())?;
    println!("  结果 → {}", p.display());
    Ok(p)
}

// ---------------------------------------------------------------- 单数据集

fn run_dataset(ds: &str, cfg: &Cfg, all_rows: &mut Vec<Row>) -> Result<Summary, String> {
    let (lib, qfile, title, dsname, caliber) = match ds {
        "lc" => (
            cfg.root.join("_md_cg_eval_locomo"),
            cfg.root
                .join("data")
                .join("external")
                .join("locomo")
                .join("locomo_questions.jsonl"),
            "LoCoMo T-REC 三组 + 负例组",
            "LoCoMo (mteb/LoCoMo BEIR)",
            "A-legacy（裸 turn，四路基线）",
        ),
        "mad" => (
            cfg.root.join("_md_cg_eval_zhprobe_a0_base"),
            cfg.root
                .join("data")
                .join("external")
                .join("zh_probe")
                .join("questions20.jsonl"),
            "中文多维探针 4 组（20 条 gold turn）",
            "zh_mad（LongMemEval-S gold turn：中文层 + 英文原文，池 20 条）",
            "B-mad（写入侧四轴消融：实体规范化/指代消解/意图抽象/关系图遍历）",
        ),
        _ => (
            cfg.root.join("_md_cg_eval_longmem"),
            cfg.root
                .join("data")
                .join("external")
                .join("longmemeval")
                .join("lme_s_questions.jsonl"),
            "LongMemEval-S T-REC 三组",
            "LongMemEval-S (xiaowu0162/LongMemEval)",
            "A-legacy（裸 turn，四路基线）",
        ),
    };
    // 消融臂逐个换库：默认走数据集内置路径，显式传入则覆盖。
    let lib = cfg.lib.clone().unwrap_or(lib);
    let qfile = cfg.qfile.clone().unwrap_or(qfile);
    let sampling = if cfg.n == 0 {
        "full".to_string()
    } else {
        cfg.n.to_string()
    };
    println!(
        "== {} {}（k={}，口径 {}，{}）==",
        ds_label(ds),
        "T-REC 复跑",
        cfg.k,
        score_label(cfg),
        if cfg.n == 0 {
            "全量".to_string()
        } else {
            format!("每组≤{}", cfg.n)
        }
    );

    let t0 = Instant::now();
    let entries = store::load_index(&lib, cfg.order)?;
    let cand = store::candidates(&entries);
    if !lib.is_dir() {
        return Err(format!("评测库不存在：{}", lib.display()));
    }
    println!(
        "  索引：{} 条目（候选 {}），{:.1}s",
        entries.len(),
        cand.len(),
        t0.elapsed().as_secs_f64()
    );
    let t1 = Instant::now();
    let docs = store::load_docs(&lib, &entries, cfg.threads);
    let nok = docs.iter().filter(|d| d.is_some()).count();
    if nok != entries.len() {
        println!("  [警告] {} 个节点正文读取失败（Python 侧同样跳过）", entries.len() - nok);
    }
    println!(
        "  正文：{} 节点，{} 线程，{:.1}s",
        nok,
        cfg.threads,
        t1.elapsed().as_secs_f64()
    );

    let qs = load_questions(&qfile)?;
    let mut summaries: Vec<(&str, Summary)> = Vec::new();
    let mut rows_by: BTreeMap<String, Vec<Row>> = BTreeMap::new();
    let t2 = Instant::now();
    for (gname, qtypes) in groups_of(ds) {
        let mut sel: Vec<&Question> = qs
            .iter()
            .filter(|q| qtypes.iter().any(|t| *t == q.qtype))
            .collect();
        if cfg.n > 0 {
            sel.truncate(cfg.n);
        }
        println!("  [{}] {} 题 …", gname, sel.len());
        let rows = eval_group(&docs, &entries, &cand, &sel, cfg);
        let s = metrics::summarize(&rows, cfg.k);
        rows_by.insert(gname.to_string(), rows);
        summaries.push((gname, s));
    }
    println!("  查询耗时 {:.1}s", t2.elapsed().as_secs_f64());

    // 对拍明细：逐题 qid/qtype/rank/top-k id
    if let Some(dp) = &cfg.dump {
        let mut buf = String::new();
        for (gname, _) in groups_of(ds) {
            if let Some(rows) = rows_by.get(gname) {
                for r in rows {
                    let line = Json::Obj(vec![
                        ("qid".into(), Json::Str(r.qid.clone())),
                        ("qtype".into(), Json::Str(r.qtype.clone())),
                        ("rank".into(), Json::Num(r.rank as f64)),
                        (
                            "top".into(),
                            Json::Arr(r.top.iter().map(|s| Json::Str(s.clone())).collect()),
                        ),
                        (
                            "scores".into(),
                            Json::Arr(r.top_scores.iter().map(|s| Json::Num(*s)).collect()),
                        ),
                    ])
                    .to_json_string();
                    buf.push_str(&line);
                    buf.push('\n');
                }
            }
        }
        use std::io::Write;
        match std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(dp)
        {
            Ok(mut f) => {
                let _ = f.write_all(buf.as_bytes());
                println!("  对拍明细 → {}", dp.display());
            }
            Err(e) => eprintln!("  [警告] 写对拍明细失败：{e}"),
        }
    }

    // 正例合并（POS_GROUPS）→ 拒答线
    let pos_rows: Vec<Row> = POS_GROUPS
        .iter()
        .flat_map(|g| rows_by.get(*g).cloned().unwrap_or_default())
        .collect();
    let line = metrics::calibrate_line(&pos_rows);
    let pos_false_refusal = metrics::false_refusal_rate(&pos_rows, line);
    let neg = rows_by.get("negative").map(|r| metrics::refusal_metrics(r, line));

    print_table(
        &format!("{title}（口径 {}）", score_label(cfg)),
        &summaries,
        cfg.k,
    );
    println!("\n拒答线（正例 hit@1 题 Top-1 分 p10）：{line:.6}");
    if let Some((n, refused, rate)) = neg {
        println!(
            "负例组（adversarial）拒答率：{}（{refused}/{n}）",
            metrics::pct(rate)
        );
    }
    println!("正例误拒率（Top-1 分 < 线）：{}", metrics::pct(pos_false_refusal));

    let interference_hit1 = summaries
        .iter()
        .find(|(g, _)| *g == "interference")
        .map(|(_, s)| s.hit1)
        .unwrap_or(0.0);
    let pass = interference_hit1 >= 0.80;
    println!("干扰组 gate（≥80%）：{}", if pass { "PASS" } else { "FAIL" });

    // 结果 JSON（文件名带 tag，默认不与 Python 结果互相覆盖）
    let mut payload = vec![
        ("dataset".to_string(), Json::Str(dsname.to_string())),
        ("caliber".to_string(), Json::Str(caliber.to_string())),
        (
            "metric_caliber".to_string(),
            Json::Str("evidence-hit（数据集标注命中），非 LLM-judge".to_string()),
        ),
        ("engine".to_string(), Json::Str("rust (mdcg-eval)".to_string())),
        (
            "paths".to_string(),
            Json::Arr(cfg.paths.iter().map(|p| Json::Str(p.clone())).collect()),
        ),
        ("k".to_string(), Json::Num(cfg.k as f64)),
        ("sampling".to_string(), Json::Str(sampling)),
        (
            "candidate_order".to_string(),
            Json::Str(
                match cfg.order {
                    Order::Scan => "scan",
                    Order::Log => "log",
                }
                .to_string(),
            ),
        ),
        (
            "groups".to_string(),
            Json::Obj(
                summaries
                    .iter()
                    .map(|(g, s)| (g.to_string(), summary_json(s, cfg.k)))
                    .collect(),
            ),
        ),
        (
            "false_refusal_pos".to_string(),
            Json::Num(pos_false_refusal),
        ),
        (
            "gate".to_string(),
            Json::Obj(vec![
                ("interference_hit1".to_string(), Json::Num(interference_hit1)),
                ("interference_pass".to_string(), Json::Bool(pass)),
                ("calibrated_line".to_string(), Json::Num(line)),
            ]),
        ),
        (
            "group_mapping".to_string(),
            Json::Obj(
                groups_of(ds)
                    .iter()
                    .map(|(g, q)| {
                        (
                            g.to_string(),
                            Json::Arr(q.iter().map(|x| Json::Str(x.to_string())).collect()),
                        )
                    })
                    .collect(),
            ),
        ),
    ];
    if let Some((n, refused, rate)) = neg {
        payload.push((
            "negative".to_string(),
            Json::Obj(vec![
                ("n".to_string(), Json::Num(n as f64)),
                ("refusal_rate".to_string(), Json::Num(rate)),
                ("refused".to_string(), Json::Num(refused as f64)),
                ("line".to_string(), Json::Num(line)),
            ]),
        ));
    }
    let name = format!("trec_{}_{}.json", ds_slug(ds), cfg.tag);
    save_result(&cfg.out_dir, &name, &Json::Obj(payload))?;

    for rows in rows_by.values() {
        all_rows.extend(rows.iter().cloned());
    }
    Ok(metrics::summarize(&rows_of(&rows_by), cfg.k))
}

fn rows_of(rows_by: &BTreeMap<String, Vec<Row>>) -> Vec<Row> {
    rows_by.values().flat_map(|v| v.iter().cloned()).collect()
}

fn ds_label(ds: &str) -> &'static str {
    match ds {
        "lc" => "LoCoMo",
        "mad" => "zh_mad",
        _ => "LongMemEval-S",
    }
}

fn ds_slug(ds: &str) -> &'static str {
    match ds {
        "lc" => "locomo",
        "mad" => "zh_mad",
        _ => "longmem",
    }
}

fn main() {
    let cfg = parse_args();

    // serve 模式：进程存活 = 检索实例（参照 protocol-compiler 蜂群实例基座）。
    // 索引只读共享 → 多智能体并发 = 协调器 spawn 多个本进程。
    if cfg.serve {
        let ecfg = EngineConfig {
            paths: Some(cfg.paths.clone()),
            weights: cfg.weights.clone(),
            fusion_max: cfg.fusion_max,
            jaccard: cfg.jaccard,
            graph_seeds_sorted: cfg.graph_seeds_sorted,
            order: cfg.order,
            threads: cfg.threads,
        };
        let engine = match SearchEngine::open(&cfg.root, &ecfg) {
            Ok(e) => e,
            Err(msg) => {
                eprintln!("[serve] 载入失败: {msg}");
                std::process::exit(1);
            }
        };
        eprintln!(
            "[serve] 就绪 docs={} 候选={} 路 [{}] root={}",
            engine.doc_count(),
            engine.candidate_count(),
            engine.paths().join(","),
            cfg.root.display()
        );
        std::process::exit(serve::run(engine));
    }

    println!(
        "灵枢公开数据集评测（Rust）· k={} · 线程 {} · 候选序 {} · 路 [{}] · 融合 {}",
        cfg.k,
        cfg.threads,
        match cfg.order {
            Order::Scan => "scan",
            Order::Log => "log",
        },
        cfg.paths.join(","),
        if cfg.fusion_max { "max" } else { "sum" }
    );

    let mut all_rows: Vec<Row> = Vec::new();
    let mut combined: Vec<(&str, Summary)> = Vec::new();
    let run_lc = cfg.dataset == "both" || cfg.dataset == "lc";
    let run_lm = cfg.dataset == "both" || cfg.dataset == "lm";
    let run_mad = cfg.dataset == "mad";

    if run_lc {
        match run_dataset("lc", &cfg, &mut all_rows) {
            Ok(s) => combined.push(("LoCoMo", s)),
            Err(e) => {
                eprintln!("\n[失败] LoCoMo：{e}");
                std::process::exit(1);
            }
        }
    }
    if run_lm {
        match run_dataset("lm", &cfg, &mut all_rows) {
            Ok(s) => combined.push(("LongMemEval-S", s)),
            Err(e) => {
                eprintln!("\n[失败] LongMemEval-S：{e}");
                std::process::exit(1);
            }
        }
    }
    if run_mad {
        match run_dataset("mad", &cfg, &mut all_rows) {
            Ok(s) => combined.push(("zh_mad", s)),
            Err(e) => {
                eprintln!("\n[失败] zh_mad：{e}");
                std::process::exit(1);
            }
        }
    }

    if run_lc && run_lm {
        let total = metrics::summarize(&all_rows, cfg.k);
        print_table(
            &format!("合计 1000 题（口径 {}，四路 RRF）", score_label(&cfg)),
            &[("合计", total)],
            cfg.k,
        );
    }
}
