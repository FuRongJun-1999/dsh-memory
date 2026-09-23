//! 文本层：与 `md_cg/mdcg.py` + `md_cg/nodefile.py` 逐函数对齐。
//!
//! 本模块是「口径一致性」的第一现场——任何一处偏离都会让 Rust 分数漂移：
//!   * `expand_query_terms` ≈ mdcg.py:113
//!   * `bigrams`            ≈ mdcg.py:128
//!   * `positive_body`      ≈ nodefile.py:163
//!   * `parse_frontmatter`  ≈ nodefile.py:78 (`loads`)

/// 与 `mdcg.SYNONYM_GROUPS` 逐字对齐（顺序按源码书写序；Python 侧是 set，
/// 迭代序不定，但 terms 只用于 `any(t in body ...)` 的包含判定，与顺序无关）。
pub const SYNONYM_GROUPS: &[&[&str]] = &[
    &["视觉", "图像", "画面", "图片", "影像", "视像"],
    &["语义", "含义", "意思", "意义", "概念"],
    &["识别", "检测", "感知", "探测", "发现"],
    &["转换", "转化", "映射", "变换"],
    &["实验", "试验", "集成", "实现", "验证", "测试"],
    &["评测", "评估", "跑分", "基准", "benchmark", "评审", "考核"],
    &["记忆", "记录", "库"],
    &["智能", "智能体", "灵枢", "AI"],
    &["语音", "声音", "音频", "说话"],
    &["对话", "聊天", "交流"],
];

/// 对齐 Python `re.split(r"[\s、，。；：,;.:/\\|]+", query)` 的分隔符判定。
#[inline]
pub fn is_split_char(c: char) -> bool {
    if c.is_whitespace() {
        return true;
    }
    matches!(c, '、' | '，' | '。' | '；' | '：' | ',' | ';' | '.' | ':' | '/' | '\\' | '|')
}

/// `expand_query_terms`：归一化整句 + 分词（≥2 字符）+ 同义词组展开 +
/// 中文 2-gram 召回扩展，去重保序。
///
/// issue #29 对齐修正（2026-09-23）：Python 版在分词**之前**先做
/// `normalize_en(query)`（英文小写/停用词/时态归一，中文不动），并在尾部
/// 追加 `cn_recall_grams`（连续中文 ≥4 切 2-gram 召回键，MDCG_CN_GRAMS=0
/// 关）。此前 Rust 版缺这两段——同库同 query 的 terms 集合与 Python 不一致，
/// LIKE 预筛候选与 lexical 打分连锁漂移（top-5 顺序 1/40 一致的根因之一）。
pub fn expand_query_terms(query: &str) -> Vec<String> {
    let query = normalize_en(query);
    let mut terms: Vec<String> = Vec::with_capacity(12);
    terms.push(query.clone());

    for w in query.split(is_split_char) {
        let w = w.trim();
        if w.chars().count() >= 2 && !terms.iter().any(|t| t == w) {
            terms.push(w.to_string());
        }
    }

    for group in SYNONYM_GROUPS {
        for w in group.iter() {
            if query.contains(w) {
                for g in group.iter() {
                    if !terms.iter().any(|t| t == g) {
                        terms.push((*g).to_string());
                    }
                }
                break;
            }
        }
    }

    // 构词法 v1：中文连续串 2-gram 召回扩展（只增召回，不改打分口径）
    for g in cn_recall_grams(&query) {
        if !terms.iter().any(|t| t == &g) {
            terms.push(g);
        }
    }

    // en_zh_terms（英→中语素，MDCG_EN_ATOMS=1 显式开启）：默认关闭 →
    // 默认链路无此项，Rust 侧暂不移植（Python mdcg.py:257 默认返回 []）。

    // 对齐 `list(dict.fromkeys(terms))`：前面已逐处去重，此处保序即可。
    terms
}

/// 中文连续串 2-gram 召回扩展（对齐 `mdcg.cn_recall_grams`，min_run=4，
/// cap=16，MDCG_CN_GRAMS=0 关闭；`CN_STOP_GRAMS` 纯语法组合剔除）。
pub fn cn_recall_grams(query: &str) -> Vec<String> {
    if std::env::var("MDCG_CN_GRAMS").as_deref() == Ok("0") {
        return Vec::new();
    }
    fn is_zh(c: char) -> bool {
        ('\u{4e00}'..='\u{9fff}').contains(&c)
    }
    let chars: Vec<char> = query.chars().collect();
    let mut out: Vec<String> = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        if !is_zh(chars[i]) {
            i += 1;
            continue;
        }
        let start = i;
        while i < chars.len() && is_zh(chars[i]) {
            i += 1;
        }
        let run_len = i - start;
        if run_len >= 4 {
            for k in start..=(start + run_len - 2) {
                let g: String = [chars[k], chars[k + 1]].iter().collect();
                if CN_STOP_GRAMS.contains(&g.as_str()) || out.contains(&g) {
                    continue;
                }
                out.push(g);
                if out.len() >= 16 {
                    return out;
                }
            }
        }
    }
    out
}

/// 中文高频功能 bigram（召回扩展时剔除：纯语法组合，召回价值低）。
pub const CN_STOP_GRAMS: &[&str] = &[
    "的了", "是一", "的在", "有个", "就是", "不是", "没有", "这个", "那个",
    "我们", "你们", "可以", "一个", "的话", "来说", "关于", "对于", "还是",
];

/// 英文停用词（对齐 `mdcg.EN_STOPWORDS` frozenset）。
pub const EN_STOPWORDS: &[&str] = &[
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "will", "would", "could",
    "should", "may", "might", "of", "to", "in", "on", "at", "for", "with",
    "by", "from", "up", "about", "into", "over", "after", "and", "or",
    "but", "not", "no", "so", "if", "then", "than", "also", "very",
    "what", "which", "who", "how", "why", "when", "where",
    "this", "that", "these", "those", "it", "its", "as", "there",
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "they", "them", "their",
];

/// 不规则时态映射（对齐 `mdcg.EN_IRREGULAR`）。
pub const EN_IRREGULAR: &[(&str, &str)] = &[
    ("ate", "eat"), ("eaten", "eat"), ("went", "go"), ("gone", "go"),
    ("saw", "see"), ("seen", "see"), ("wrote", "write"), ("written", "write"),
    ("took", "take"), ("taken", "take"), ("made", "make"), ("ran", "run"),
    ("bought", "buy"), ("brought", "bring"), ("thought", "think"),
    ("taught", "teach"), ("caught", "catch"), ("sought", "seek"),
    ("fought", "fight"), ("sold", "sell"), ("told", "tell"), ("felt", "feel"),
    ("fell", "fall"), ("sent", "send"), ("spent", "spend"), ("built", "build"),
    ("lost", "lose"), ("met", "meet"), ("paid", "pay"), ("led", "lead"),
    ("won", "win"), ("sat", "sit"), ("stood", "stand"),
    ("understood", "understand"), ("heard", "hear"),
    ("spoke", "speak"), ("spoken", "speak"), ("broke", "break"),
    ("broken", "break"),
    ("chose", "choose"), ("chosen", "choose"), ("drew", "draw"),
    ("drawn", "draw"),
    ("drove", "drive"), ("driven", "drive"), ("grew", "grow"),
    ("grown", "grow"),
    ("knew", "know"), ("known", "know"), ("gave", "give"), ("given", "give"),
    ("was", "be"), ("were", "be"), ("been", "be"), ("had", "have"),
    ("has", "have"),
    ("did", "do"), ("done", "do"), ("said", "say"), ("got", "get"),
    ("left", "leave"), ("kept", "keep"), ("held", "hold"),
    ("slept", "sleep"), ("swept", "sweep"), ("meant", "mean"),
    ("dealt", "deal"), ("lent", "lend"), ("bent", "bend"),
];

/// 英文时态/复数归零（对齐 `mdcg.strip_tense_en`：宁可少剥不可误剥）。
pub fn strip_tense_en(w: &str) -> String {
    if let Some((_, v)) = EN_IRREGULAR.iter().find(|(k, _)| *k == w) {
        return (*v).to_string();
    }
    // -ous 结尾 = 形容词不是复数（courageous/famous/various）
    if w.ends_with("ous") || w.ends_with("us") || w.ends_with("is") {
        return w.to_string();
    }
    if w.ends_with("ing") && w.len() > 5 {
        return w[..w.len() - 3].to_string();
    }
    if w.ends_with("ed") && w.len() > 4 {
        return w[..w.len() - 2].to_string();
    }
    if w.ends_with("ies") && w.len() > 4 {
        return format!("{}y", &w[..w.len() - 3]);
    }
    // -es 只剥真复数（boxes→box, watches→watch），对齐 `(ch|sh|ss|x|z)o?es$`
    if w.len() > 4
        && [
            "ches", "choes", "shes", "shoes", "sses", "xes", "xoes", "zes",
            "zoes",
        ]
        .iter()
        .any(|e| w.ends_with(e))
    {
        return w[..w.len() - 2].to_string();
    }
    // -s 剥离（motivates→motivate, pets→pet）
    if w.ends_with('s') && !w.ends_with("ss") {
        return w[..w.len() - 1].to_string();
    }
    w.to_string()
}

/// 英文归一化（对齐 `mdcg.normalize_en`）：小写 + 去停用词 + 去时态复数。
/// 中文部分不动。
///
/// 三步（与 Python 逐行同构）：
///   1. 清标点：非[中文 | 空白 | 字母 | 数字] → 空格；
///   2. `[a-zA-Z]{2,}` 词段：小写化 → 停用词整词剔除 → 时态/复数归零
///      （单字母段不处理，保留原样）；
///   3. 空白压缩（Unicode 空白 → 单空格）并去首尾。
pub fn normalize_en(text: &str) -> String {
    let cleaned: String = text
        .chars()
        .map(|c| {
            if ('\u{4e00}'..='\u{9fff}').contains(&c)
                || c.is_whitespace()
                || c.is_ascii_alphanumeric()
            {
                c
            } else {
                ' '
            }
        })
        .collect();

    let chars: Vec<char> = cleaned.chars().collect();
    let mut out = String::with_capacity(chars.len());
    let mut i = 0;
    while i < chars.len() {
        if chars[i].is_ascii_alphabetic() {
            let start = i;
            while i < chars.len() && chars[i].is_ascii_alphabetic() {
                i += 1;
            }
            if i - start >= 2 {
                let w: String = chars[start..i]
                    .iter()
                    .collect::<String>()
                    .to_lowercase();
                if EN_STOPWORDS.contains(&w.as_str()) {
                    continue; // 停用词整词剔除（两侧空格保留，后续压缩）
                }
                out.push_str(&strip_tense_en(&w));
            } else {
                out.push(chars[start]); // 单字母段：Python 正则不匹配，原样保留
            }
        } else {
            out.push(chars[i]);
            i += 1;
        }
    }
    out.split_whitespace().collect::<Vec<&str>>().join(" ")
}

/// `bigrams(s)`：先抹掉所有空白，再取全部相邻二元组（去重）。
/// `s` 长度 ≤1 时 Python 返回 `{s}`（单元素集合）。
pub fn bigrams(s: &str) -> Vec<String> {
    let chars: Vec<char> = s.chars().filter(|c| !c.is_whitespace()).collect();
    if chars.len() <= 1 {
        return vec![chars.iter().collect::<String>()];
    }
    let mut seen: std::collections::HashSet<String> =
        std::collections::HashSet::with_capacity(chars.len());
    let mut out: Vec<String> = Vec::with_capacity(chars.len() - 1);
    for i in 0..chars.len() - 1 {
        let g: String = [chars[i], chars[i + 1]].iter().collect();
        if seen.insert(g.clone()) {
            // 去重：Python 是 set，`|qb ∩ nb|` 只关心去重后的势
            out.push(g);
        }
    }
    out
}

/// 抹掉全部空白（对齐 Python `"".join(s.split())`）。用于 `bigrams` 与打分。
#[inline]
pub fn strip_ws(s: &str) -> String {
    s.chars().filter(|c| !c.is_whitespace()).collect()
}

/// `|qb ∩ bigrams(content)|`：qb 是**去重**集合，故等价于「qb 中有多少个
/// 二元组是 `strip_ws(content)` 的子串」。这避免为每个文档构集合，是性能关键路径。
///
/// 等价性论证：`bigrams(content)` = 对 `s = strip_ws(content)` 取相邻对。
/// 二元组 g（去空白后长度 2）∈ bigrams(content) ⇔ 存在 i 使 s[i..i+2]==g
/// ⇔ g 是 s 的子串。注意**必须**在 s（而非原始 content）上匹配：原始文本里
/// 跨空格的字符对（如 "a b" 的 "ab"）在 s 中相邻，是 bigrams 的合法元素。
/// 边界：|s|≤1 时 bigrams={s}，contains 判定同样给出正确结果。
#[inline]
pub fn overlap_count(qb: &[String], stripped: &str) -> usize {
    qb.iter().filter(|g| stripped.contains(g.as_str())).count()
}

/// `positive_body`：剥离 `# 不适用条件：` 行（负条件不作召回键）。
pub fn positive_body(content: &str) -> String {
    let mut keep: Vec<&str> = Vec::new();
    for ln in content.split('\n') {
        let s = ln.trim();
        if s.starts_with('#')
            && s.trim_start_matches('#').trim().starts_with("不适用条件")
        {
            continue;
        }
        keep.push(ln);
    }
    keep.join("\n")
}

/// 单个 frontmatter 值 → 文本（对齐 `loads` 的 `json.loads(v)` / 回退原文）。
pub fn parse_fm_value(v: &str) -> String {
    match crate::json::parse(v) {
        Ok(crate::json::Json::Str(s)) => s,
        Ok(crate::json::Json::Num(n)) => crate::json::fmt_num(n),
        Ok(crate::json::Json::Bool(b)) => b.to_string(),
        Ok(crate::json::Json::Null) => String::new(),
        Ok(other) => other.to_json_string(),
        // `json.loads` 抛 ValueError 时 Python 保留原文
        Err(_) => v.to_string(),
    }
}

pub struct Frontmatter {
    pub kv: Vec<(String, String)>,
}

impl Frontmatter {
    pub fn get(&self, key: &str) -> Option<&str> {
        self.kv.iter().rev().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
    }

    /// 取数组型字段（如 `tags` / `edges`）：优先 JSON 解析，失败回退空。
    pub fn get_json(&self, key: &str) -> Option<crate::json::Json> {
        self.get(key).and_then(|v| crate::json::parse(v).ok())
    }

    pub fn get_f64(&self, key: &str) -> f64 {
        self.get_json(key).and_then(|j| j.as_f64()).unwrap_or(0.0)
    }

    pub fn get_str(&self, key: &str) -> Option<String> {
        self.get(key).map(parse_fm_value)
    }

    pub fn get_str_vec(&self, key: &str) -> Vec<String> {
        match self.get_json(key) {
            Some(j) => j.as_str_vec(),
            None => Vec::new(),
        }
    }
}

/// `nodefile.loads`：返回 (frontmatter, content)。
///
/// 用「按行找 `---` 分界」实现而非字节偏移，对 `\n` / `\r\n` 都可容错；
/// 正文的行结构保持一致（行内正文里 \r 的差异不影响 bigrams，因为空白被抹掉）。
pub fn parse_frontmatter(text: &str) -> (Frontmatter, String) {
    let delim = "---";
    let lines: Vec<&str> = text.split('\n').collect();
    let empty = Frontmatter { kv: Vec::new() };

    if lines.is_empty() || lines[0].trim_end_matches('\r') != delim {
        return (empty, text.to_string());
    }
    let mut end = None;
    for (i, ln) in lines.iter().enumerate().skip(1) {
        if ln.trim_end_matches('\r') == delim {
            end = Some(i);
            break;
        }
    }
    let end = match end {
        Some(i) => i,
        None => return (empty, text.to_string()),
    };

    let mut kv = Vec::new();
    for line in &lines[1..end] {
        if !line.contains(':') {
            continue;
        }
        let (k, v) = match line.split_once(':') {
            Some(x) => x,
            None => continue,
        };
        let k = k.trim();
        let v = v.trim();
        // 存原文（对齐 Python `loads`：值保持 JSON 字面量，取用时才解析）
        kv.push((k.to_string(), v.to_string()));
    }
    // 对齐 Python `rest[end + len(_DELIM) + 2:]`：分界行之后的内容（保留尾随换行）
    let content = lines[end + 1..].join("\n");
    (Frontmatter { kv }, content)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terms_basic() {
        let t = expand_query_terms("What did Caroline buy?");
        // issue #29 口径对齐：首项 = normalize_en 整句（Python :310 在分词前
        // 先归一化——旧断言「首项=未归一原句」是悬空期行为，测试跟上）
        assert_eq!(t[0], "caroline buy");
        assert!(t.contains(&"caroline".to_string()));
        assert!(t.contains(&"buy".to_string()));
        assert!(!t.iter().any(|x| x == "What"), "停用词 What 已被归一化剔除");
    }

    #[test]
    fn bigrams_dedup() {
        let b = bigrams("aaa");
        assert_eq!(b, vec!["aa".to_string()]);
        let b2 = bigrams("ab");
        assert_eq!(b2, vec!["ab".to_string()]);
    }

    #[test]
    fn neg_line_stripped() {
        let body = "正文一\n# 不适用条件：X\n正文二";
        assert_eq!(positive_body(body), "正文一\n正文二");
        // 普通句子以「不适用条件」开头但不是 CCG 行 → 不剥离
        let body2 = "不适用条件：这是普通句子";
        assert_eq!(positive_body(body2), body2);
    }

    #[test]
    fn fm_roundtrip() {
        let text = "---\nid: \"a1\"\ntags: [\"x\", \"y\"]\nimportance: 0.5\n---\n正文\n";
        let (fm, c) = parse_frontmatter(text);
        assert_eq!(fm.get_str("id").unwrap(), "a1");
        assert_eq!(fm.get_str_vec("tags"), vec!["x", "y"]);
        assert_eq!(fm.get_f64("importance"), 0.5);
        assert_eq!(c, "正文\n");
    }

    /// issue #29 golden 对拍：期望值由 Python `md_cg.mdcg` 实测产出
    /// （normalize_en / cn_recall_grams / expand_query_terms 前六项）。
    /// 任何一侧口径改动都必须同步更新——这正是「逐位对齐」的守卫形态。
    #[test]
    fn golden_python_alignment() {
        // 英文归一化：小写 + 停用词整词剔除 + 时态/复数归零（ate→eat）
        assert_eq!(
            normalize_en("The Cats were running quickly, and ate fish!"),
            "cat runn quickly eat fish"
        );
        // 专有词保留原名 + 问号清为空格
        assert_eq!(normalize_en("What did Caroline buy?"), "caroline buy");
        // 中文不动 + 英文词保留（大小写归一）
        assert_eq!(
            normalize_en("灵枢的 hotcache 设计说明"),
            "灵枢的 hotcache 设计说明"
        );
        // 时态/复数链：running→runn / pets→pet / dogs→dog /
        // chased→chas（-ed 剥）/ balls→ball；The 剔除
        assert_eq!(
            normalize_en("Running pets! The dogs chased balls"),
            "runn pet dog chas ball"
        );

        // 中文 2-gram 召回扩展（≥4 字连续中文 run，CN_STOP_GRAMS 剔除）
        assert_eq!(
            cn_recall_grams("慈善跑 心理健康 发声 意识 意义"),
            vec!["心理".to_string(), "理健".to_string(), "健康".to_string()]
        );
        assert_eq!(
            cn_recall_grams("灵枢的 hotcache 设计说明"),
            vec!["设计".to_string(), "计说".to_string(), "说明".to_string()]
        );
        assert!(cn_recall_grams("Running pets! The dogs chased balls").is_empty());

        // expand_query_terms 首项 = normalize_en 整句，分词跟上
        let t = expand_query_terms("What did Caroline buy?");
        assert_eq!(t.first().map(String::as_str), Some("caroline buy"));
        assert!(t.contains(&"caroline".to_string()) && t.contains(&"buy".to_string()));
    }
}
