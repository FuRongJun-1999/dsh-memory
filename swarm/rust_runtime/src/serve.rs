//! serve.rs · VM 实例化多轮模式（蜂群实例基座）
//! stdin 逐行 JSON 请求 → 执行 program.pbc → stdout 终态 JSON（一行一响应）。
//! 请求: {"symbols": {...}, "trust": 0.5, "condition_space": [...], "round_no": 1}
//! 响应: 与单次模式同构的终态 JSON + "instance"/"round_no" 回显。
//! 进程保持存活 = 协调器眼中的「实例」（消息传递语义：每轮初始环境即收到的消息）。

use std::io::{BufRead, Write};

use crate::pbc;
use crate::vm::{CondFrame, Value, VM};

/// 初始条件空间帧解析（JSON: [{"name":..., "trust_at_create":...}]）
fn parse_cond_frames(v: &serde_like::Value) -> Vec<CondFrame> {
    let mut out = Vec::new();
    if let serde_like::Value::List(items) = v {
        for it in items {
            if let serde_like::Value::Obj(m) = it {
                let name = m
                    .get("name")
                    .and_then(|x| x.as_str())
                    .unwrap_or("无名帧")
                    .to_string();
                let trust = m
                    .get("trust_at_create")
                    .and_then(|x| x.as_f64())
                    .unwrap_or(0.0);
                out.push(CondFrame {
                    name,
                    trust_at_create: trust,
                });
            }
        }
    }
    out
}

/// 极简 JSON 解析（复用 main.rs 的标量/字符串解析；此处独立小实现避免循环依赖）
mod serde_like {
    use std::collections::HashMap;

    #[derive(Debug, Clone)]
    pub enum Value {
        Null,
        Bool(bool),
        Num(f64),
        Str(String),
        List(Vec<Value>),
        Obj(HashMap<String, Value>),
    }

    impl Value {
        pub fn as_str(&self) -> Option<&str> {
            match self {
                Value::Str(s) => Some(s),
                _ => None,
            }
        }
        pub fn as_f64(&self) -> Option<f64> {
            match self {
                Value::Num(f) => Some(*f),
                _ => None,
            }
        }
        pub fn to_vm_value(&self) -> Option<super::Value> {
            Some(match self {
                Value::Null => super::Value::Null,
                Value::Bool(b) => super::Value::Bool(*b),
                Value::Num(f) => {
                    if f.fract() == 0.0 && f.is_finite() && f.abs() < 9e15 {
                        super::Value::Int(*f as i64)
                    } else {
                        super::Value::Float(*f)
                    }
                }
                Value::Str(s) => super::Value::Str(s.clone()),
                _ => return None,
            })
        }
    }

    pub fn parse(s: &str) -> Result<Value, String> {
        let b: Vec<char> = s.chars().collect();
        let mut i = 0usize;
        let v = parse_value(&b, &mut i)?;
        skip_ws(&b, &mut i);
        Ok(v)
    }

    fn skip_ws(b: &[char], i: &mut usize) {
        while *i < b.len() && b[*i].is_whitespace() {
            *i += 1;
        }
    }

    fn parse_value(b: &[char], i: &mut usize) -> Result<Value, String> {
        skip_ws(b, i);
        match b.get(*i) {
            Some('{') => {
                *i += 1;
                let mut m = HashMap::new();
                loop {
                    skip_ws(b, i);
                    match b.get(*i) {
                        Some('}') => {
                            *i += 1;
                            return Ok(Value::Obj(m));
                        }
                        Some(',') => {
                            *i += 1;
                        }
                        Some('"') => {
                            let (k, ni) = parse_str(b, *i)?;
                            *i = ni;
                            skip_ws(b, i);
                            if b.get(*i) != Some(&':') {
                                return Err("对象缺 ':'".into());
                            }
                            *i += 1;
                            let v = parse_value(b, i)?;
                            m.insert(k, v);
                        }
                        _ => return Err("对象结构非法".into()),
                    }
                }
            }
            Some('[') => {
                *i += 1;
                let mut items = Vec::new();
                loop {
                    skip_ws(b, i);
                    match b.get(*i) {
                        Some(']') => {
                            *i += 1;
                            return Ok(Value::List(items));
                        }
                        Some(',') => {
                            *i += 1;
                        }
                        _ => items.push(parse_value(b, i)?),
                    }
                }
            }
            Some('"') => {
                let (s, ni) = parse_str(b, *i)?;
                *i = ni;
                Ok(Value::Str(s))
            }
            Some(_) => {
                let start = *i;
                while *i < b.len()
                    && !b[*i].is_whitespace()
                    && !matches!(b[*i], ',' | '}' | ']')
                {
                    *i += 1;
                }
                let raw: String = b[start..*i].iter().collect();
                Ok(match raw.as_str() {
                    "true" => Value::Bool(true),
                    "false" => Value::Bool(false),
                    "null" => Value::Null,
                    _ => Value::Num(
                        raw.parse::<f64>()
                            .map_err(|_| format!("非法数值 {raw}"))?,
                    ),
                })
            }
            None => Err("JSON 意外结束".into()),
        }
    }

    fn parse_str(b: &[char], start: usize) -> Result<(String, usize), String> {
        let mut out = String::new();
        let mut i = start + 1;
        while i < b.len() {
            match b[i] {
                '"' => return Ok((out, i + 1)),
                '\\' => {
                    i += 1;
                    match b.get(i) {
                        Some('"') => out.push('"'),
                        Some('\\') => out.push('\\'),
                        Some('n') => out.push('\n'),
                        Some('t') => out.push('\t'),
                        _ => return Err("不支持的转义".into()),
                    }
                }
                c => out.push(c),
            }
            i += 1;
        }
        Err("字符串未闭合".into())
    }
}

/// serve 主循环：逐行请求 → 逐行响应；EOF/quit 退出
pub fn serve(code: &[pbc::Instr], instance_id: &str) -> i32 {
    let stdin = std::io::stdin();
    let mut out = std::io::stdout();
    let mut vm = VM::new();
    let mut handled = 0u64;
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let line = line.trim().to_string();
        if line.is_empty() {
            continue;
        }
        if line == "quit" {
            break;
        }
        let resp = match serde_like::parse(&line) {
            Ok(req) => {
                let mut symbols = std::collections::HashMap::new();
                let mut trust = 0.0f64;
                let mut cond = Vec::new();
                let mut round_no: u64 = handled + 1;
                if let serde_like::Value::Obj(m) = &req {
                    if let Some(serde_like::Value::Obj(sm)) = m.get("symbols") {
                        for (k, v) in sm {
                            if k == "初始符号" {
                                // 初始符号表：展平注入（协调器包裹的初始环境，非普通符号）
                                if let serde_like::Value::Obj(base) = v {
                                    for (bk, bv) in base {
                                        if let Some(bvv) = bv.to_vm_value() {
                                            symbols.insert(bk.clone(), bvv);
                                        }
                                    }
                                }
                            } else if let Some(vv) = v.to_vm_value() {
                                symbols.insert(k.clone(), vv);
                            }
                        }
                    }
                    trust = m
                        .get("trust")
                        .and_then(|x| x.as_f64())
                        .unwrap_or(0.0);
                    if let Some(cv) = m.get("condition_space") {
                        cond = parse_cond_frames(cv);
                    }
                    if let Some(serde_like::Value::Num(n)) = m.get("round_no") {
                        if *n >= 1.0 {
                            round_no = *n as u64;
                        }
                    }
                }
                match vm.run(code, symbols, trust, cond, 100_000) {
                    Ok(st) => compose_response(&st, instance_id, round_no),
                    Err(crate::vm::VmError::Halted(kind, st)) => {
                        let mut st = *st;
                        st.halt = Some(kind);
                        compose_response(&st, instance_id, round_no)
                    }
                    Err(crate::vm::VmError::Error(e)) => format!(
                        "{{\"error\":\"{}\",\"instance\":\"{}\",\"round_no\":{}}}",
                        escape_json(&e),
                        escape_json(instance_id),
                        round_no
                    ),
                }
            }
            Err(e) => format!("{{\"error\":\"请求 JSON 非法: {}\"}}", escape_json(&e)),
        };
        handled += 1;
        if writeln!(out, "{resp}").is_err() || out.flush().is_err() {
            break; // 协调器关闭管道 → 实例退出
        }
    }
    0
}

fn escape_json(s: &str) -> String {
    let mut out = String::new();
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out
}

/// 终态 JSON + 实例/轮次回显（state_json 末尾 } 换成扩展字段）
fn compose_response(
    st: &crate::vm::State,
    instance_id: &str,
    round_no: u64,
) -> String {
    format!(
        "{},\"instance\":\"{}\",\"round_no\":{}}}",
        crate::vm::state_json(st).trim_end_matches('}'),
        escape_json(instance_id),
        round_no
    )
}
