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
//!   * 打分 `sim = |qb ∩ db| / |qb ∪ db|`（**Rust 侧**缺省 `jaccard`；注意它与
//!     Python 侧产品缺省 `legacy`（`md_cg/mdcg.py:SCORE_MODE`）**不一致**——
//!     两侧缺省本就不同，R-7 订正，详见下方 `Cfg.jaccard` 处注释）+ tag_bonus(≤1.0)；
//!     `--score legacy` 切回 `|qb ∩ db| / |qb|`（只归一化查询侧，旧基线）
//!   * 指标 rank(1-based) / hit@1 / hit@k / MRR / 拒答线 = 正例 hit@1 题 Top-1 分 p10
//!
//! 唯一无法逐位保证的是**并列分数的名次**（Python `_scan_nodes` 依赖目录枚举序），
//! 故提供 `--order scan|log`，默认 `scan`（模拟文件名序）。

// 模块统一由 lib target（mdcg_eval）供给：单一编译源，避免 bin/lib 双编译
// 产生两个不同身份的同名类型（E0308）。评测逻辑与库共享同一份实现。
use mdcg_eval::{json, metrics, serve, store};

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::time::Instant;

use json::Json;
use metrics::{Row, Summary};
use mdcg_eval::engine::{search_ranked, EngineConfig, SearchEngine, SearchParams};
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
    /// `--graph-seeds sorted|raw`：graph 路种子取法。
    ///
    /// R-3（2026-09-29）：**缺省由 raw 改为 sorted**。Python `mdcos._lexical`
    /// 的返回序恒为相关度降序 ⇒ `_path_graph` 的 `seeds[:5]` 是相关度前 5；
    /// 原先的 raw 缺省让评测链路取「候选枚举序前 5」，与 Python 不同源。
    /// `raw` 仅作隔离「种子口径」与「边结构质量」的排查阀保留。
    graph_seeds_sorted: bool,
    /// query 统一归一层（R-1，2026-09-29）：`None` = 词表不可得或
    /// `MDCG_UNIFY_QUERY=0` → 无归一口径。**评测链路与库/serve 链路共用同一
    /// 实例语义**——此前评测链路完全不过归一层（`main.rs::search` 直用原始
    /// query），同 query 同语料两条路 top-1 不同。
    atoms: Option<mdcg_eval::atoms::Atoms>,
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
        // 缺省 jaccard（长度自惩罚）。**注意：与 Python 缺省不一致**——Python 侧产品
        // 缺省是 legacy（md_cg/mdcg.py:SCORE_MODE，|qb∩db|/|qb|），两侧缺省本就不同
        // （此处原注「与 Python 缺省一致」，与事实相反，2026-09-29 R-7 订正）。
        // CH-1 起 rank_parity 对拍两侧各自**显式钉住**口径（Python 走
        // md_cg/eval_common.py::use_jaccard()，Rust 走 argv --score 并回读 serve
        // info.score），故对拍读数不依赖本缺省值；本值只决定「不传 --score 时怎么打分」。
        jaccard: true, // 缺省 jaccard
        lib: None,
        qfile: None,
        // R-3：缺省 sorted（对齐 Python `_lexical` 的相关度降序返回序）
        graph_seeds_sorted: true,
        // R-1：归一层实例一次性载入（env `MDCG_EN_ZH_MAP` / `MDCG_UNIFY_QUERY`）
        atoms: mdcg_eval::atoms::Atoms::from_env(),
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
                // R-3：`sorted`（缺省）= 过 retrieval::sort_path 三键；
                // `raw` = 旧口径（直接取候选枚举序前 5），仅作排查阀。
                cfg.graph_seeds_sorted = !take(&mut i).eq_ignore_ascii_case("raw")
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
///
/// CH-1（2026-09-29）：标签映射收单点到 `engine::score_label`（`serve info.score`
/// 与启动 stderr 取同一份），本函数只做 `Cfg` → bool 的取用。
fn score_label(cfg: &Cfg) -> &'static str {
    mdcg_eval::engine::score_label(cfg.jaccard)
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
  --score MODE          词法打分：jaccard（**本进程缺省**，|qb∩db|/|qb∪db|，长度自惩罚）
                        | legacy（|qb∩db|/|qb|，只归一化查询侧，长文档占优）
                        `--serve` 亦接受本参数；被拉起进程的实际口径可经 info 请求
                        的 score 字段回读（CH-1）。
                        注意 Python 侧缺省是 legacy（md_cg/mdcg.py:SCORE_MODE），
                        两侧缺省不同 ⇒ 对拍必须两侧显式钉同一值。
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

/// 评测链路的检索入口——**只做参数搬运**，编排单点在
/// `engine::search_ranked`（R-1，2026-09-29）。
///
/// 修复前本函数是编排的**第二份实现**，且漏了两处与库/serve 链路不一致的口径：
///   1. 不做 query 统一归一（`engine` 侧 `atoms.unify`）⇒ 同 query 同语料
///      top-1 不同，违反 `rust/README.md` 与 `lib.rs` 自书的「两边一致」；
///   2. graph 种子按**只比 score** 排序（并列时路内顺序漂移），而 Python
///      `_lexical` 的返回序是**三键**（-score/-importance/id）相关度降序。
/// 两处一并由 `search_ranked` 收口：本函数不再自带任何判据。
fn search(
    docs: &[Option<store::Doc>],
    entries: &[Entry],
    cand: &[usize],
    query: &str,
    cfg: &Cfg,
) -> Vec<(usize, f64)> {
    search_ranked(
        docs,
        entries,
        cand,
        query,
        cfg.k,
        cfg.atoms.as_ref(),
        &SearchParams {
            paths: &cfg.paths,
            weights: &cfg.weights,
            fusion_max: cfg.fusion_max,
            jaccard: cfg.jaccard,
            graph_seeds_sorted: cfg.graph_seeds_sorted,
        },
    )
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
            "[serve] 就绪 docs={} 候选={} 路 [{}] score={} root={}",
            engine.doc_count(),
            engine.candidate_count(),
            engine.paths().join(","),
            // CH-1：启动行自报实际口径（与 info.score 同源单点）——对拍方与
            // 运维都能从进程自己嘴里读到「我按哪套词法公式打分」。
            mdcg_eval::engine::score_label(engine.jaccard()),
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

#[cfg(test)]
mod opt_batch1_tests {
    //! R-1（2026-09-29）：评测链路（`main.rs::search`）必须与库/serve 链路
    //! 走**同一份编排**且**同一份 query 归一口径**。
    //!
    //! 修复前 `main.rs::search` 是编排的第二份实现且完全不过统一归一层
    //! （直用原始 query）——同 query 同语料两条路 top-1 不同，违反
    //! `rust/README.md` / `lib.rs` 自书的「两边一致」。本用例钉住**行为面**：
    //! 英文 query 打中文语料，评测链路必须在归一层生效时命中中文节点。
    use super::*;

    fn tmp_root(tag: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let d = std::env::temp_dir().join(format!("mdcg_eval_bin_{tag}_{nanos}"));
        std::fs::create_dir_all(d.join("knowledge")).unwrap();
        d
    }

    /// 与 `parse_args` 同构的最小 Cfg（只给检索相关字段有意义的值）。
    fn test_cfg(atoms: Option<mdcg_eval::atoms::Atoms>) -> Cfg {
        let root = tmp_root("cfg");
        Cfg {
            root: root.clone(),
            dataset: "lc".into(),
            k: 5,
            threads: 1,
            order: Order::Scan,
            paths: vec![
                "lexical".into(),
                "bucket".into(),
                "entity".into(),
                "graph".into(),
            ],
            fusion_max: false,
            weights: std::collections::HashMap::new(),
            n: 0,
            out_dir: root,
            tag: "test".into(),
            dump: None,
            jaccard: true,
            lib: None,
            qfile: None,
            graph_seeds_sorted: true,
            atoms,
            serve: false,
        }
    }

    /// 语料：`beef`（中文正文「牛肉」）与 `tall`（无关但 importance 更高）。
    /// 无归一层时英文 query 的 LIKE 预筛全空 → 走 LIKE 兜底池（只按
    /// importance 定序）⇒ `tall` 反超；有归一层时命中 `beef`。
    fn unify_lib() -> PathBuf {
        let root = tmp_root("unifylib");
        std::fs::write(
            root.join("_index.json"),
            r#"{"nodes":{
                "beef":{"path":"knowledge/beef.md","layer":"knowledge","tags":[],"importance":0.3,"edges":[]},
                "tall":{"path":"knowledge/tall.md","layer":"knowledge","tags":[],"importance":0.9,"edges":[]}
            }}"#,
        )
        .unwrap();
        std::fs::write(
            root.join("knowledge").join("beef.md"),
            "---\nid: \"beef\"\nimportance: 0.3\n---\n# 正文：牛肉 烹饪 方法 zzcook\n",
        )
        .unwrap();
        std::fs::write(
            root.join("knowledge").join("tall.md"),
            "---\nid: \"tall\"\nimportance: 0.9\n---\n# 正文：无关 节点 zzcook\n",
        )
        .unwrap();
        root
    }

    fn top1(ranked: &[(usize, f64)], entries: &[Entry]) -> String {
        assert!(!ranked.is_empty(), "结果非空");
        entries[ranked[0].0].id.clone()
    }

    #[test]
    fn r1_eval_path_applies_query_unifier() {
        let root = unify_lib();
        let entries = store::load_index(&root, Order::Scan).unwrap();
        let cand = store::candidates(&entries);
        let docs = store::load_docs(&root, &entries, 1);
        let map = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../md_cg/semantic/en_zh_map.json");
        let atoms = mdcg_eval::atoms::Atoms::load(&map).expect("仓库内 en_zh_map.json 可载入");

        // 测评链路口径（R-1 修复后：atoms 在位 ⇒ query 先归一）
        let cfg_on = test_cfg(Some(atoms));
        let on = search(&docs, &entries, &cand, "I eat beef yesterday", &cfg_on);
        assert_eq!(top1(&on, &entries), "beef",
                   "评测链路必须过统一归一层（英文 query 命中中文「牛肉」节点）");

        // 无归一层（旧评测链路口径，`MDCG_UNIFY_QUERY=0` / 词表不可得）
        let cfg_off = test_cfg(None);
        let off = search(&docs, &entries, &cand, "I eat beef yesterday", &cfg_off);
        assert_ne!(top1(&off, &entries), "beef",
                   "无归一层时英文 query 与中文正文无词面交集（旧口径失配形态）");

        // 两条路的共同来源：`search` 只是 `search_ranked` 的参数搬运——
        // 同一参数直调必须逐位一致（单实现，R-1）
        let direct = search_ranked(
            &docs, &entries, &cand, "I eat beef yesterday", cfg_on.k,
            cfg_on.atoms.as_ref(),
            &SearchParams {
                paths: &cfg_on.paths,
                weights: &cfg_on.weights,
                fusion_max: cfg_on.fusion_max,
                jaccard: cfg_on.jaccard,
                graph_seeds_sorted: cfg_on.graph_seeds_sorted,
            },
        );
        assert_eq!(on.len(), direct.len());
        for (a, b) in on.iter().zip(direct.iter()) {
            assert_eq!(a.0, b.0, "同序同位");
            assert_eq!(a.1, b.1, "同分");
        }
        let _ = std::fs::remove_dir_all(&root);
        let _ = std::fs::remove_dir_all(&cfg_on.root);
    }

    #[test]
    fn r1_graph_seeds_default_is_sorted() {
        // R-3 的 CLI 缺省面：不改 --graph-seeds 时 cfg.graph_seeds_sorted 必须为真
        // （构造 `parse_args` 会读 std::env::args，故这里只钉缺省值本身；
        //  缺省字面量与 `--graph-seeds raw` 的反向解析在 parse_args 内）
        let cfg = test_cfg(None);
        assert!(cfg.graph_seeds_sorted, "缺省 sorted");
        assert!(cfg.atoms.is_none(), "测试夹具显式传 None");
    }
}
