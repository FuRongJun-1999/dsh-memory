//! pbc.rs · .pbc 字节码反序列化（Rust 侧）
//! 格式与同包 pbc.py 严格对齐：
//!   [op: len2B(u16 LE)+utf8][arg_tag: 1B][arg_data...]
//!   tag: 0=None, 1=bool, 2=int(i64 LE), 3=float(f64 LE),
//!        4=str(len2B+utf8), 5=tuple(f64+i64)[ZHIZU], 6=(i64+str列表)[CALL]

#[derive(Debug, Clone, PartialEq)]
pub enum Arg {
    None,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    /// ZHIZU: (阈值 f64, 跳转地址 i64)
    Threshold(f64, i64),
    /// CALL: (入口 ip i64, 参数名列表)
    CallSig(i64, Vec<String>),
}

#[derive(Debug, Clone)]
pub struct Instr {
    pub op: String,
    pub arg: Arg,
}

fn u16_le(data: &[u8], i: usize) -> Result<usize, String> {
    if i + 2 > data.len() {
        return Err("截断：缺 u16".into());
    }
    Ok(u16::from_le_bytes([data[i], data[i + 1]]) as usize)
}

fn i64_le(data: &[u8], i: usize) -> Result<i64, String> {
    if i + 8 > data.len() {
        return Err("截断：缺 i64".into());
    }
    let mut b = [0u8; 8];
    b.copy_from_slice(&data[i..i + 8]);
    Ok(i64::from_le_bytes(b))
}

fn f64_le(data: &[u8], i: usize) -> Result<f64, String> {
    if i + 8 > data.len() {
        return Err("截断：缺 f64".into());
    }
    let mut b = [0u8; 8];
    b.copy_from_slice(&data[i..i + 8]);
    Ok(f64::from_le_bytes(b))
}

pub fn deserialize(data: &[u8]) -> Result<Vec<Instr>, String> {
    let mut code = Vec::new();
    let mut i = 0usize;
    while i < data.len() {
        let n = u16_le(data, i)?;
        i += 2;
        if i + n > data.len() {
            return Err("截断：op 名越界".into());
        }
        let op = String::from_utf8(data[i..i + n].to_vec())
            .map_err(|_| "op 名非 UTF-8".to_string())?;
        i += n;
        if i >= data.len() {
            return Err("截断：缺 arg tag".into());
        }
        let tag = data[i];
        i += 1;
        let arg = match tag {
            0 => Arg::None,
            1 => {
                if i >= data.len() {
                    return Err("截断：缺 bool".into());
                }
                let b = data[i] == 1;
                i += 1;
                Arg::Bool(b)
            }
            2 => {
                let v = i64_le(data, i)?;
                i += 8;
                Arg::Int(v)
            }
            3 => {
                let v = f64_le(data, i)?;
                i += 8;
                Arg::Float(v)
            }
            4 => {
                let m = u16_le(data, i)?;
                i += 2;
                if i + m > data.len() {
                    return Err("截断：字符串越界".into());
                }
                let s = String::from_utf8(data[i..i + m].to_vec())
                    .map_err(|_| "字符串非 UTF-8".to_string())?;
                i += m;
                Arg::Str(s)
            }
            5 => {
                let t = f64_le(data, i)?;
                let a = i64_le(data, i + 8)?;
                i += 16;
                Arg::Threshold(t, a)
            }
            6 => {
                let entry = i64_le(data, i)?;
                i += 8;
                let n_params = u16_le(data, i)?;
                i += 2;
                let mut params = Vec::with_capacity(n_params);
                for _ in 0..n_params {
                    let m = u16_le(data, i)?;
                    i += 2;
                    if i + m > data.len() {
                        return Err("截断：参数名越界".into());
                    }
                    params.push(
                        String::from_utf8(data[i..i + m].to_vec())
                            .map_err(|_| "参数名非 UTF-8".to_string())?,
                    );
                    i += m;
                }
                Arg::CallSig(entry, params)
            }
            other => return Err(format!("未知 arg tag {other}")),
        };
        code.push(Instr { op, arg });
    }
    Ok(code)
}
