//! 存储层：读已建库（`_index_log` 索引 + 各层 `.md` 节点）。
//!
//! 对齐 Python 侧：
//!   * 索引来源 `MdCG._load_index`：优先 `_index.json`，再用 `_index_log`
//!     按 `(_t, _s)` 顺序重放覆盖（`fsutil.ShardedLog.read_all`）；
//!   * 条目字段与 `MdCG._stage` 落盘的一致：path/layer/tags/importance/
//!     created_at/role/bucket/edges；
//!   * 正文 `nodefile.loads` → (frontmatter, content)。
//!
//! **候选顺序**（影响并列分数的名次，是唯一可能漂移的点）：
//!   * `Order::Scan`：模拟 `_scan_nodes` 的目录枚举序 → 文件名排序
//!     （NTFS 目录索引按 UTF-16 名序，ASCII 名等价于字节序），默认值；
//!   * `Order::Log` ：索引日志写入序（= 语料行序）。
//! 两种序在分数并列处会给出不同名次，`--order` 可切换做对拍。

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use crate::json::{self, Json};
use crate::text::parse_frontmatter;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Order {
    Scan,
    Log,
}

/// 索引条目（子集：只保留检索与过滤需要的字段）。
#[derive(Debug, Clone)]
pub struct Entry {
    pub id: String,
    pub path: String,
    pub layer: String,
    pub tags: Vec<String>,
    pub importance: f64,
    /// 对齐 `MdCG._stage` 落盘字段（评测链路暂未读取，保留以维持字段集一致）
    #[allow(dead_code)]
    pub created_at: f64,
    pub role: Option<String>,
    /// 同上：对齐 `_stage` 的 bucket（bucket 路需 context，评测不传 → 恒空）
    #[allow(dead_code)]
    pub bucket: Option<String>,
    /// P4-2①（设计稿 §7.2 卡点一）：访问计数与最后访问时刻——与 Python
    /// `_node_entry` / `add()` 的 `_stage` 条目同款入索引条目，
    /// 供刷新乘子**不读盘**取数。
    #[allow(dead_code)]
    pub access_count: f64,
    #[allow(dead_code)]
    pub last_access: f64,
    pub edges: Vec<String>,
    /// 退役纪律（《秤》v2.1 §5.2；2026-10-06 接线）：索引条目的
    /// `lifecycle_state`（对齐 `md_cg/lifecycle.py` 的 `STATE_FIELD`）。
    /// 缺键/非 "archived" ⇒ 照常参与候选（fail-open，与 Python 侧
    /// `lifecycle.is_archived` 同口径）；"archived" 在 `candidates` 剔除。
    pub lifecycle_state: Option<String>,
}

/// 内存文档：`lit` 是 `positive_body(content)`；口径 A 两者恒等 → 存 `None` 省内存。
/// `tags` 保留逐个元素（`_path_entity` / `tag_bonus` 用），`tags_joined` 对齐 `_like`
/// 的 `" ".join(tags)`；`stripped` 是抹空白后的 content，供打分层的 bigram 子串匹配。
///
/// R-2（2026-09-29）：`like_body_lower` / `tags_joined_lower` 是 `_like` 预筛两个
/// 被包含判定文本的**预存小写形态**——建库（载入）时算一次，热路径直接引用。
/// 为什么必须预存：`_like` 是「每查询 × 每候选」的最内层判定，原先每次调用对整串
/// 各做一次 `to_lowercase()`（整串新分配；Codex 实测 20000 文档语料 search 156ms
/// 中 152ms 在此）。文档内容建库后不变 ⇒ 派生物不变，与 `stripped` / `db_len` 同款
/// 「预计算一次」先例（Python 侧 readcache 常驻 `_doc_norm_bigrams` 同一理论）。
/// **等价变换**：表达式逐字不变（同一实现、同一输入），只把求值时机从每查询前移
/// 到建库——分数逐位不变由 crate 内单测 `r2_like_lower_is_precomputed` 与
/// `r2_like_scores_unchanged` 双钉。
pub struct Doc {
    pub id: String,
    pub importance: f64,
    pub tags: Vec<String>,
    pub tags_joined: String,
    /// `like_body()` 的小写形态（建库时算一次；`_like` 热路径直接引用）。
    pub like_body_lower: String,
    /// `tags_joined` 的小写形态（建库时算一次；`_like` 热路径直接引用）。
    pub tags_joined_lower: String,
    pub content: String,
    pub stripped: String,
    /// `stripped` 的去重二元组势 `|db|`（Jaccard 归一化用；建库时算一次）
    pub db_len: usize,
    pub lit: Option<String>,
    pub edges: Vec<String>,
    /// P4（设计稿 §七）：刷新/衰减乘子的取数面——与 Python `_score` 的乘子
    /// 同源同义（`created_at` / `access_count` / `last_access` / `protected`）。
    /// `importance` 已在结构里（乘子的 rehearsal/degrade 门槛要用）。
    pub created_at: f64,
    pub access_count: f64,
    pub last_access: f64,
    pub protected: bool,
}

impl Doc {
    /// LIKE 预筛用的召回文本（对齐 `_like` 的 `body`，及其与 tags 的 `or`）。
    #[inline]
    pub fn like_body(&self) -> &str {
        self.lit.as_deref().unwrap_or(&self.content)
    }
}

/// 对齐 `mdcg.LAYERS`（决定 `_scan_nodes` 的层遍历顺序）。
const LAYERS: [&str; 8] = [
    "anchor",
    "structural",
    "knowledge",
    "contextual",
    "self",
    "rejected",
    "unresolved",
    "goals",
];

/// 对齐 `mdcos.WORK_ROLES`。
const WORK_ROLES: [&str; 3] = ["tool-output", "command", "edit"];
/// 对齐 `mdcos._candidates` 的层黑名单。
const SKIP_LAYERS: [&str; 3] = ["rejected", "unresolved", "goals"];

fn entry_from_json(id: &str, e: &Json) -> Entry {
    let path = e.get("path").and_then(|v| v.as_str()).unwrap_or(id).to_string();
    let layer = e
        .get("layer")
        .and_then(|v| v.as_str())
        .unwrap_or("contextual")
        .to_string();
    Entry {
        id: id.to_string(),
        path,
        layer,
        tags: e.get("tags").map(|v| v.as_str_vec()).unwrap_or_default(),
        importance: e.get("importance").and_then(|v| v.as_f64()).unwrap_or(0.0),
        created_at: e.get("created_at").and_then(|v| v.as_f64()).unwrap_or(0.0),
        role: e.get("role").and_then(|v| v.as_str()).map(|s| s.to_string()),
        bucket: e.get("bucket").and_then(|v| v.as_str()).map(|s| s.to_string()),
        access_count: e.get("access_count").and_then(|v| v.as_f64()).unwrap_or(0.0),
        last_access: e.get("last_access").and_then(|v| v.as_f64()).unwrap_or(0.0),
        edges: extract_edges(e.get("edges")),
        // 退役纪律：与 md_cg/lifecycle.py 的 STATE_FIELD 同键名（"lifecycle_state"）。
        lifecycle_state: e
            .get("lifecycle_state")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
    }
}

/// `edges` 既可能是 `[{"target": "x"}]` 也可能是 `["x"]`（对齐 `_path_graph`）。
fn extract_edges(v: Option<&Json>) -> Vec<String> {
    let arr = match v.and_then(|j| j.as_arr()) {
        Some(a) => a,
        None => return Vec::new(),
    };
    arr.iter()
        .filter_map(|item| match item {
            Json::Obj(_) => item
                .get("target")
                .and_then(|t| t.as_str())
                .map(|s| s.to_string()),
            Json::Str(s) => Some(s.clone()),
            _ => None,
        })
        .collect()
}

/// 递归收集 `*.md` 节点文件，跳过下划线开头的内部目录。
/// 对齐 `mdcg._scan_nodes`：按 `LAYERS` 顺序、每层 `os.walk` 枚举序收集 `.md`。
fn collect_md(root: &Path, dir: &Path, out: &mut Vec<PathBuf>) {
    let rd = match std::fs::read_dir(dir) {
        Ok(rd) => rd,
        Err(_) => return,
    };
    // 对齐 os.walk(topdown=True)：先产出本层文件（scandir 序），再依次下钻子目录。
    let mut files: Vec<PathBuf> = Vec::new();
    let mut subdirs: Vec<PathBuf> = Vec::new();
    for ent in rd.flatten() {
        let name = ent.file_name().to_string_lossy().to_string();
        let p = ent.path();
        match ent.file_type() {
            Ok(t) if t.is_dir() => subdirs.push(p),
            _ => {
                if name.ends_with(".md") {
                    files.push(p);
                }
            }
        }
    }
    let _ = root;
    for f in files {
        out.push(f);
    }
    for d in subdirs {
        collect_md(root, &d, out);
    }
}

/// 载入索引。返回按候选顺序排好的条目列表。
pub fn load_index(root: &Path, order: Order) -> Result<Vec<Entry>, String> {
    // 1) 元数据源：_index.json（若存在）与 _index_log 重放
    let mut map: Vec<(String, Entry)> = Vec::new();
    let mut pos: HashMap<String, usize> = HashMap::new();

    let put = |id: String, e: Entry, map: &mut Vec<(String, Entry)>,
               pos: &mut HashMap<String, usize>| {
        match pos.get(&id) {
            // 对齐 dict 语义：已存在则原位覆盖，不改变顺序
            Some(&i) => map[i].1 = e,
            None => {
                pos.insert(id.clone(), map.len());
                map.push((id, e));
            }
        }
    };

    let idx_json = root.join("_index.json");
    if idx_json.is_file() {
        let raw = std::fs::read_to_string(&idx_json)
            .map_err(|e| format!("读 _index.json 失败: {e}"))?;
        let j = json::parse(&raw).map_err(|e| format!("解析 _index.json 失败: {e}"))?;
        if let Some(nodes) = j.get("nodes").and_then(|n| n.as_obj()) {
            for (nid, ev) in nodes.iter() {
                put(nid.clone(), entry_from_json(nid, ev), &mut map, &mut pos);
            }
        }
    }

    let log_dir = root.join("_index_log");
    if log_dir.is_dir() {
        // read_all：跨分片按 (_t,_s) 全局排序后重放
        let mut recs: Vec<(f64, f64, String, Entry)> = Vec::new();
        let mut files: Vec<PathBuf> = Vec::new();
        collect_log_files(&log_dir, &mut files);
        for f in &files {
            let raw = match std::fs::read_to_string(f) {
                Ok(r) => r,
                Err(_) => continue,
            };
            for line in raw.lines() {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }
                let v = match json::parse(line) {
                    Ok(v) => v,
                    Err(_) => continue, // 对齐 read_jsonl 坏行跳过
                };
                let Some(id) = v.get("id").and_then(|x| x.as_str()) else {
                    continue;
                };
                let Some(ev) = v.get("e") else { continue };
                let t = v.get("_t").and_then(|x| x.as_f64()).unwrap_or(0.0);
                let s = v.get("_s").and_then(|x| x.as_f64()).unwrap_or(0.0);
                recs.push((t, s, id.to_string(), entry_from_json(id, ev)));
            }
        }
        recs.sort_by(|a, b| {
            a.0.partial_cmp(&b.0)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
        });
        for (_, _, id, e) in recs {
            put(id, e, &mut map, &mut pos);
        }
    }

    if map.is_empty() {
        return Err(format!(
            "索引为空：{} 下既无 _index.json 也无可用 _index_log",
            root.display()
        ));
    }

    // 2) 候选顺序
    let mut entries: Vec<Entry> = map.into_iter().map(|(_, e)| e).collect();
    if order == Order::Scan {
        // 对齐 `_scan_nodes`：LAYERS 序 → 每层 os.walk 枚举序。
        // 这是 Python `_load_index` 在无 `_index.json` 时的真实节点顺序；
        // 排序稳定性使得同分并列名次完全一致。
        let mut seq: Vec<PathBuf> = Vec::new();
        for layer in LAYERS {
            collect_md(root, &root.join(layer), &mut seq);
        }
        let mut rank: HashMap<String, usize> = HashMap::with_capacity(seq.len());
        for (i, p) in seq.iter().enumerate() {
            let rel = p
                .strip_prefix(root)
                .unwrap_or(p)
                .to_string_lossy()
                .replace('\\', "/");
            rank.entry(rel).or_insert(i);
        }
        // 走不到的（已删除的）条目排在末尾，等价于 dict 新键追加。
        entries.sort_by_key(|e| rank.get(&e.path).copied().unwrap_or(usize::MAX));
    }
    Ok(entries)
}

fn collect_log_files(dir: &Path, out: &mut Vec<PathBuf>) {
    if let Ok(rd) = std::fs::read_dir(dir) {
        for ent in rd.flatten() {
            let p = ent.path();
            if p.is_file() {
                out.push(p);
            }
        }
    }
    out.sort();
}

/// 对齐 `_candidates(layer=None, roles=None, include_work=False)`。
pub fn candidates(entries: &[Entry]) -> Vec<usize> {
    entries
        .iter()
        .enumerate()
        .filter(|(_, e)| {
            if SKIP_LAYERS.contains(&e.layer.as_str()) {
                return false;
            }
            // 退役纪律（《秤》v2.1 §5.2；2026-10-06 接线）：archived 不进候选
            // ——与 Python 侧 `lifecycle.is_archived` 同口径（缺键/非法=active，
            // fail-open；converged/demoted 是降权轴，仍参与）。
            if e.lifecycle_state.as_deref() == Some("archived") {
                return false;
            }
            match &e.role {
                Some(r) => !WORK_ROLES.contains(&r.as_str()),
                None => true,
            }
        })
        .map(|(i, _)| i)
        .collect()
}

fn read_doc(root: &Path, e: &Entry) -> Option<Doc> {
    let p = root.join(&e.path);
    let text = std::fs::read_to_string(&p).ok()?;
    let (fm, content) = parse_frontmatter(&text);

    let id = fm.get_str("id").unwrap_or_else(|| {
        // 对齐 `_path_graph` 的 path basename 推导
        e.path
            .rsplit('/')
            .next()
            .map(|s| s.trim_end_matches(".md").to_string())
            .unwrap_or_else(|| e.id.clone())
    });
    let importance = {
        let v = fm.get_f64("importance");
        if v != 0.0 {
            v
        } else {
            e.importance
        }
    };
    let tags: Vec<String> = {
        let t = fm.get_str_vec("tags");
        if t.is_empty() {
            e.tags.clone()
        } else {
            t
        }
    };
    let edges = {
        let t = extract_edges(fm.get_json("edges").as_ref());
        if t.is_empty() {
            e.edges.clone()
        } else {
            t
        }
    };
    let lit = crate::text::positive_body(&content);
    let lit = if lit == content { None } else { Some(lit) };
    // issue #29 对齐（2026-09-23）：文档侧打分文本走 normalize_en（英文小写/
    // 停用词/时态归一，中文不动）——Python `_score` 的 `nb =
    // bigrams(normalize_en(c))`。原先只抹空白，含英文的文档 bigram 集合与
    // Python 不同 → lexical 分数漂移 → RRF 连锁偏移（top-5 顺序 1/40 一致）。
    let stripped = crate::text::strip_ws(&crate::text::normalize_en(&content));
    let tags_joined = tags.join(" ");
    let db_len = crate::text::bigrams(&stripped).len();
    // R-2（2026-09-29）：`_like` 预筛的两个被包含判定文本在建库时预存小写——
    // 表达式与 retrieval::like 原先逐字相同（`like_body().to_lowercase()` /
    // `tags_joined.to_lowercase()`），只是把求值时机前移（等价变换，分数逐位
    // 不变）。必须在 `lit` 定形之后取，否则回落 content 的形态会与原先不同。
    let like_body_lower = lit.as_deref().unwrap_or(&content).to_lowercase();
    let tags_joined_lower = tags_joined.to_lowercase();
    // P4：刷新/衰减乘子的四个取数键（frontmatter 优先、条目回落——与 Python
    // `freshness.entry_weight(entry, fm=...)` 的取数优先级一致）。
    let created_at = {
        let v = fm.get_f64("created_at");
        if v != 0.0 { v } else { e.created_at }
    };
    let access_count = {
        let v = fm.get_f64("access_count");
        if v != 0.0 { v } else { e.access_count }
    };
    let last_access = {
        let v = fm.get_f64("last_access");
        if v != 0.0 { v } else { e.last_access }
    };
    let protected = matches!(
        fm.get_json("protected"),
        Some(crate::json::Json::Bool(true))
    );

    Some(Doc {
        id,
        importance,
        tags,
        tags_joined,
        like_body_lower,
        tags_joined_lower,
        content,
        stripped,
        db_len,
        lit,
        edges,
        created_at,
        access_count,
        last_access,
        protected,
    })
}

/// 并行载入全部节点正文；读取失败的槽位为 `None`（对齐 `_read` 返回 (None,None)）。
pub fn load_docs(root: &Path, entries: &[Entry], threads: usize) -> Vec<Option<Doc>> {
    let n = entries.len();
    let mut slots: Vec<Option<Doc>> = Vec::with_capacity(n);
    slots.resize_with(n, || None);
    if n == 0 {
        return slots;
    }
    let t = threads.max(1).min(n);
    let chunk = n.div_ceil(t);
    std::thread::scope(|scope| {
        for (ec, sc) in entries.chunks(chunk).zip(slots.chunks_mut(chunk)) {
            scope.spawn(move || {
                for (e, slot) in ec.iter().zip(sc.iter_mut()) {
                    *slot = read_doc(root, e);
                }
            });
        }
    });
    slots
}

/// 对齐 `_path_graph` 的 `by_id`：path 末段去 `.md` → 条目下标。
pub fn by_basename(entries: &[Entry]) -> HashMap<String, usize> {
    let mut m = HashMap::new();
    for (i, e) in entries.iter().enumerate() {
        let base = e
            .path
            .rsplit('/')
            .next()
            .map(|s| s.trim_end_matches(".md").to_string())
            .unwrap_or_else(|| e.id.clone());
        m.insert(base, i);
    }
    m
}

#[cfg(test)]
mod opt_batch1_tests {
    //! R-2（2026-09-29）：`Doc::like_body_lower` / `Doc::tags_joined_lower`
    //! 是 `_like` 预筛文本的建库期小写快照——本模块钉「快照 == 逐次计算的
    //! 同表达式」这一等价性，以及「LIKE 的大小写不敏感确实生效」这一行为。
    use super::*;

    fn temp_root(tag: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let d = std::env::temp_dir().join(format!("mdcg_r2_{tag}_{nanos}"));
        std::fs::create_dir_all(d.join("knowledge")).unwrap();
        d
    }

    fn entry(path: &str, id: &str, tags: &[&str]) -> Entry {
        Entry {
            id: id.to_string(),
            path: path.to_string(),
            layer: "knowledge".to_string(),
            tags: tags.iter().map(|s| s.to_string()).collect(),
            importance: 0.5,
            created_at: 0.0,
            role: None,
            bucket: None,
            access_count: 0.0,
            last_access: 0.0,
            edges: vec![],
            lifecycle_state: None,
        }
    }

    #[test]
    fn archived_entries_excluded_from_candidates() {
        // 退役纪律（2026-10-06 接线）：archived 剔除；converged（降权轴）与
        // 缺键（active，fail-open）仍参与——两侧都要钉住（防一刀切）。
        let mut a = entry("knowledge/a.md", "a", &[]);
        let b = entry("knowledge/b.md", "b", &[]);
        let mut c = entry("knowledge/c.md", "c", &[]);
        a.lifecycle_state = None;
        c.lifecycle_state = Some("converged".to_string());
        let mut arch = b;
        arch.lifecycle_state = Some("archived".to_string());
        let entries = vec![a, arch, c];
        let cand = candidates(&entries);
        assert_eq!(cand, vec![0, 2],
                   "archived 必须剔除；converged 与缺键必须保留（判据两侧）");
    }

    #[test]
    fn lifecycle_state_parsed_from_index_json() {
        // 走真实解析路径：键名与 md_cg/lifecycle.py 的 STATE_FIELD 同源
        // （"lifecycle_state"）——键名漂移会被本断言钉红。
        let j = json::parse(r#"{"path":"knowledge/x.md","layer":"knowledge",
                               "lifecycle_state":"archived"}"#).unwrap();
        let e = entry_from_json("x", &j);
        assert_eq!(e.lifecycle_state.as_deref(), Some("archived"));
        let j2 = json::parse(r#"{"path":"knowledge/y.md","layer":"knowledge"}"#).unwrap();
        let e2 = entry_from_json("y", &j2);
        assert_eq!(e2.lifecycle_state, None, "缺键必须是 None（fail-open 前提）");
    }

    #[test]
    fn r2_like_lower_is_precomputed_equivalent() {
        let root = temp_root("equiv");
        // 大小写混排正文 + 混排 tags：等价性断言对「是否真的小写」有判别力
        let body = "# 功能名：HotCache\n# 正文：BEES Compiler writes Tests 热缓存\n";
        std::fs::write(root.join("knowledge").join("a.md"),
                       format!("---\nid: \"a\"\ntags: [\"Probe\", \"BeEs\"]\nimportance: 0.5\n---\n{body}"))
            .unwrap();
        let e = entry("knowledge/a.md", "a", &["Probe", "BeEs"]);
        let d = read_doc(&root, &e).expect("节点可读");

        // 等价性（R-2 的核心契约）：预存值 == 原先每次现算的那个表达式
        assert_eq!(d.like_body_lower, d.like_body().to_lowercase());
        assert_eq!(d.tags_joined_lower, d.tags_joined.to_lowercase());
        // 判别力：预存值确实是小写形态（不是原文照抄）
        assert!(d.like_body_lower.contains("bees compiler writes tests"),
                "like_body_lower 必须是小写形态: {}", d.like_body_lower);
        assert!(!d.like_body_lower.contains("BEES"), "不得保留大写");
        assert_eq!(d.tags_joined_lower, "probe bees");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn r2_like_lower_follows_lit_branch() {
        let root = temp_root("lit");
        // 含「不适用条件」行 → positive_body != content ⇒ lit = Some(...)：
        // 预存值必须取 like_body()（= lit）的小写，而不是 content 的小写
        let body = "# 功能名：X\n# 正文：ZZZKeep\n# 不适用条件：DropMe\n";
        std::fs::write(root.join("knowledge").join("b.md"),
                       format!("---\nid: \"b\"\nimportance: 0.5\n---\n{body}"))
            .unwrap();
        let e = entry("knowledge/b.md", "b", &[]);
        let d = read_doc(&root, &e).expect("节点可读");
        assert!(d.lit.is_some(), "夹具前提：不适用条件行使 lit 与 content 分叉");
        assert_eq!(d.like_body_lower, d.like_body().to_lowercase());
        assert!(d.like_body_lower.contains("zzzkeep"));
        assert!(!d.like_body_lower.contains("dropme"),
                "lit 分支必须生效：不适用条件行不得留在 like_body_lower");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn r2_like_case_insensitive_recall() {
        let root = temp_root("recall");
        std::fs::write(
            root.join("knowledge").join("c.md"),
            "---\nid: \"c\"\nimportance: 0.5\n---\n# 正文：HOTCache 加速重复查询\n",
        )
        .unwrap();
        let e = entry("knowledge/c.md", "c", &[]);
        let docs = vec![read_doc(&root, &e)];
        let cand = vec![0usize];
        // 小写 term 命中大写正文（terms 已是 normalize_en 产物 = 全小写）
        let hits = crate::retrieval::lexical(&docs, &cand, "hotcache", 1e9, true);
        assert_eq!(hits.len(), 1, "大小写不同不得阻断 LIKE 预筛（R-2 行为面）");
        let _ = std::fs::remove_dir_all(&root);
    }
}
