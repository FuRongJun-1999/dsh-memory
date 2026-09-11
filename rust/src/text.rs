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

/// `expand_query_terms`：整句 + 分词（≥2 字符）+ 同义词组展开，去重保序。
pub fn expand_query_terms(query: &str) -> Vec<String> {
    let mut terms: Vec<String> = Vec::with_capacity(12);
    terms.push(query.to_string());

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

    // 对齐 `list(dict.fromkeys(terms))`：前面已逐处去重，此处保序即可。
    terms
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
        assert_eq!(t[0], "What did Caroline buy?");
        assert!(t.contains(&"What".to_string()));
        assert!(t.contains(&"Caroline".to_string()));
        assert!(t.contains(&"buy?".to_string()), "`?` 不是分隔符");
        assert!(t.contains(&"did".to_string()));
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
}
