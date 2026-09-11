//! 零依赖 JSON 解析 / 序列化。
//!
//! 为什么自己写：本仓 D-005 约定「零第三方依赖」，且评测机可能离线，
//! 取 crate 会引入构建期不确定性。语料与索引都是 Python `json.dumps`
//! （`ensure_ascii=False`）产物，语法是标准 JSON 的安全子集，自解析风险可控。
//!
//! 与 Python 语义对齐的要点：
//!   * 对象重复键取**最后一个**（`json.loads` 行为）；
//!   * 解析失败由调用方跳过该行（对齐 `fsutil.read_jsonl` 的坏行跳过）；
//!   * `\uXXXX` 支持代理对。

#[derive(Debug, Clone, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(Vec<(String, Json)>),
}

impl Json {
    /// 取键值；重复键返回最后一个（对齐 Python dict 覆盖语义）。
    pub fn get(&self, key: &str) -> Option<&Json> {
        match self {
            Json::Obj(kv) => kv.iter().rev().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Json::Num(n) => Some(*n),
            _ => None,
        }
    }

    pub fn as_arr(&self) -> Option<&[Json]> {
        match self {
            Json::Arr(a) => Some(a),
            _ => None,
        }
    }

    /// 对象键值表（保序，重复键按原序保留；查值请用 `get`）。
    pub fn as_obj(&self) -> Option<&[(String, Json)]> {
        match self {
            Json::Obj(kv) => Some(kv),
            _ => None,
        }
    }

    /// 字符串数组；非数组/非字符串项按 Python `str()` 兜底转文本。
    pub fn as_str_vec(&self) -> Vec<String> {
        match self {
            Json::Arr(a) => a
                .iter()
                .map(|v| match v {
                    Json::Str(s) => s.clone(),
                    Json::Num(n) => fmt_num(*n),
                    Json::Bool(b) => b.to_string(),
                    Json::Null => "None".to_string(),
                    other => other.to_json_string(),
                })
                .collect(),
            Json::Null => Vec::new(),
            other => vec![other.as_str().unwrap_or_default().to_string()],
        }
    }
}

/// 数字 → Python `str(float)` 近似（整数不带小数点，对齐 `str(t)` 的常见形态）。
pub fn fmt_num(n: f64) -> String {
    if n.fract() == 0.0 && n.abs() < 1e15 {
        format!("{}", n as i64)
    } else {
        let s = format!("{n}");
        s
    }
}

// ------------------------------------------------------------------ 解析

pub fn parse(input: &str) -> Result<Json, String> {
    let bytes = input.as_bytes();
    let mut p = Parser { b: bytes, i: 0 };
    p.skip_ws();
    let v = p.value()?;
    p.skip_ws();
    if p.i != bytes.len() {
        return Err(format!("尾部多余内容 @{}", p.i));
    }
    Ok(v)
}

struct Parser<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<u8> {
        self.b.get(self.i).copied()
    }

    fn skip_ws(&mut self) {
        while let Some(c) = self.peek() {
            if c == b' ' || c == b'\t' || c == b'\n' || c == b'\r' {
                self.i += 1;
            } else {
                break;
            }
        }
    }

    fn value(&mut self) -> Result<Json, String> {
        match self.peek() {
            None => Err("空输入".into()),
            Some(b'{') => self.object(),
            Some(b'[') => self.array(),
            Some(b'"') => Ok(Json::Str(self.string()?)),
            Some(b't') => self.lit("true", Json::Bool(true)),
            Some(b'f') => self.lit("false", Json::Bool(false)),
            Some(b'n') => self.lit("null", Json::Null),
            Some(_) => self.number(),
        }
    }

    fn lit(&mut self, word: &str, v: Json) -> Result<Json, String> {
        if self.b[self.i..].starts_with(word.as_bytes()) {
            self.i += word.len();
            Ok(v)
        } else {
            Err(format!("非法字面量 @{}", self.i))
        }
    }

    fn object(&mut self) -> Result<Json, String> {
        self.i += 1; // '{'
        let mut kv = Vec::new();
        self.skip_ws();
        if self.peek() == Some(b'}') {
            self.i += 1;
            return Ok(Json::Obj(kv));
        }
        loop {
            self.skip_ws();
            if self.peek() != Some(b'"') {
                return Err(format!("对象键非字符串 @{}", self.i));
            }
            let k = self.string()?;
            self.skip_ws();
            if self.peek() != Some(b':') {
                return Err(format!("缺冒号 @{}", self.i));
            }
            self.i += 1;
            self.skip_ws();
            let v = self.value()?;
            kv.push((k, v));
            self.skip_ws();
            match self.peek() {
                Some(b',') => {
                    self.i += 1;
                }
                Some(b'}') => {
                    self.i += 1;
                    return Ok(Json::Obj(kv));
                }
                _ => return Err(format!("对象未闭合 @{}", self.i)),
            }
        }
    }

    fn array(&mut self) -> Result<Json, String> {
        self.i += 1; // '['
        let mut out = Vec::new();
        self.skip_ws();
        if self.peek() == Some(b']') {
            self.i += 1;
            return Ok(Json::Arr(out));
        }
        loop {
            self.skip_ws();
            out.push(self.value()?);
            self.skip_ws();
            match self.peek() {
                Some(b',') => {
                    self.i += 1;
                }
                Some(b']') => {
                    self.i += 1;
                    return Ok(Json::Arr(out));
                }
                _ => return Err(format!("数组未闭合 @{}", self.i)),
            }
        }
    }

    fn string(&mut self) -> Result<String, String> {
        self.i += 1; // 开引号
        let mut out = String::new();
        loop {
            let c = *self.b.get(self.i).ok_or("字符串未闭合")?;
            self.i += 1;
            match c {
                b'"' => return Ok(out),
                b'\\' => {
                    let e = *self.b.get(self.i).ok_or("转义未闭合")?;
                    self.i += 1;
                    match e {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{8}'),
                        b'f' => out.push('\u{c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let cp = self.hex4()?;
                            if (0xD800..0xDC00).contains(&cp) {
                                // 代理对高位 → 尝试拼低位
                                if self.b.get(self.i) == Some(&b'\\')
                                    && self.b.get(self.i + 1) == Some(&b'u')
                                {
                                    self.i += 2;
                                    let lo = self.hex4()?;
                                    if (0xDC00..0xE000).contains(&lo) {
                                        let c = 0x10000
                                            + ((cp - 0xD800) << 10)
                                            + (lo - 0xDC00);
                                        out.push(
                                            char::from_u32(c).unwrap_or('\u{fffd}'),
                                        );
                                        continue;
                                    }
                                    out.push('\u{fffd}');
                                }
                                out.push('\u{fffd}');
                            } else {
                                out.push(char::from_u32(cp).unwrap_or('\u{fffd}'));
                            }
                        }
                        _ => return Err(format!("未知转义 \\{}", e as char)),
                    }
                }
                _ => {
                    // UTF-8 原样拷贝
                    let start = self.i - 1;
                    let len = utf8_len(c);
                    self.i = start + len;
                    let s = std::str::from_utf8(&self.b[start..self.i])
                        .map_err(|e| e.to_string())?;
                    out.push_str(s);
                }
            }
        }
    }

    fn hex4(&mut self) -> Result<u32, String> {
        if self.i + 4 > self.b.len() {
            return Err("\\u 不足 4 位".into());
        }
        let s = std::str::from_utf8(&self.b[self.i..self.i + 4])
            .map_err(|e| e.to_string())?;
        self.i += 4;
        u32::from_str_radix(s, 16).map_err(|e| e.to_string())
    }

    fn number(&mut self) -> Result<Json, String> {
        let start = self.i;
        while let Some(c) = self.peek() {
            if c.is_ascii_digit()
                || c == b'-'
                || c == b'+'
                || c == b'.'
                || c == b'e'
                || c == b'E'
            {
                self.i += 1;
            } else {
                break;
            }
        }
        let s = std::str::from_utf8(&self.b[start..self.i]).map_err(|e| e.to_string())?;
        s.parse::<f64>()
            .map(Json::Num)
            .map_err(|e| format!("坏数字 {s}: {e}"))
    }
}

fn utf8_len(b: u8) -> usize {
    if b < 0x80 {
        1
    } else if b >> 5 == 0b110 {
        2
    } else if b >> 4 == 0b1110 {
        3
    } else {
        4
    }
}

// ------------------------------------------------------------------ 序列化

impl Json {
    /// 输出标准 JSON（非 ASCII 原样保留，等价 Python `ensure_ascii=False`）。
    pub fn to_json_string(&self) -> String {
        let mut s = String::new();
        self.write(&mut s);
        s
    }

    fn write(&self, out: &mut String) {
        match self {
            Json::Null => out.push_str("null"),
            Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Json::Num(n) => {
                if n.is_finite() {
                    out.push_str(&fmt_num(*n));
                } else {
                    out.push_str("null");
                }
            }
            Json::Str(s) => write_str(s, out),
            Json::Arr(a) => {
                out.push('[');
                for (i, v) in a.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    v.write(out);
                }
                out.push(']');
            }
            Json::Obj(kv) => {
                out.push('{');
                for (i, (k, v)) in kv.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    write_str(k, out);
                    out.push(':');
                    v.write(out);
                }
                out.push('}');
            }
        }
    }
}

fn write_str(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}
