//! vm.rs · 智能论字节码 VM（Rust 原生运行时）
//! 语义与同包 condition_vm.py 逐条对齐：
//!   ip + 值栈 + 符号表（以名举实）+ 条件空间栈 + 信任值寄存器 + 调用栈帧
//!   止(ZHI)/无为(WUWEI) 是语言语义（halt/yield）非错误；步数上限防死循环。

use std::collections::HashMap;
use std::fmt::Write as _;

use crate::pbc::{Arg, Instr};

// =============================================================================
// VM 内建名（与 compiler/condition_vm.py 同一契约；缺陷②③的 Rust 侧对齐）
// =============================================================================
// 背景：编译期名实校验（name_checker）把 信任值/条件空间/条件空间名 声明为合法
// 符号，但两台 VM 此前都未在运行期绑定它们 —— 编译期放行、运行期 NameError。
// 本表补齐运行时投影，使「名」与「实」指向同一处存储：
//   信任值   → trust_value 寄存器（读写）；德(DE) 改的正是它，故自动同步
//   条件空间 → 当前条件空间名（读）；赋值 = 切换
//   空间名   → 其自身（字符串），使「若 条件空间 为 伴侣」成为真实运行期比较
//   信任分量 → trust_parts 寄存器（默认 0.0）
const BUILTIN_TRUST_VALUE: &str = "信任值";
const BUILTIN_CONDITION_SPACE: &str = "条件空间";
const BUILTIN_TRUST_THRESHOLD: &str = "信任阈值";
const DEFAULT_TRUST_THRESHOLD: f64 = 0.7;
const DEFAULT_CONDITION_SPACE: &str = "默认";
const CONDITION_SPACE_NAMES: [&str; 5] = ["伴侣", "工作", "默认", "恢复默认", "default"];
const TRUST_COMPONENT_NAMES: [&str; 5] =
    ["P_trust", "T_pred", "T_context", "E_weight", "情感权重"];

/// 栈值/符号值。Int 保留整数算术语义（对齐 Python int/float 区分）。
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
}

#[derive(Debug, Clone, PartialEq)]
pub struct CondFrame {
    pub name: String,
    pub trust_at_create: f64,
}

struct CallFrame {
    ret_ip: usize,
    symbols: HashMap<String, Value>,
    trust: f64,
    cond: Vec<CondFrame>,
}

/// 执行终态（与 Python `run()` 返回结构同构，供双后端等价对照）
pub struct State {
    pub trust: f64,
    pub symbols: HashMap<String, Value>,
    pub condition_space: Vec<CondFrame>,
    pub stack: Vec<Value>,
    /// None=自然跑完；Some("halt")=止；Some("yield")=无为
    pub halt: Option<String>,
}

pub enum VmError {
    /// 止/无为：正常控制流（kind, 终态；Box 防 Err variant 过大）
    Halted(String, Box<State>),
    /// 名实不符/除零/步数超限/未知指令等真错误
    Error(String),
}

pub struct VM {
    pub ip: usize,
    stack: Vec<Value>,
    symbols: HashMap<String, Value>,
    condition_stack: Vec<CondFrame>,
    trust_value: f64,
    /// 信任分量寄存器（P_trust/T_pred/T_context/E_weight/情感权重 的运行时投影）
    trust_parts: HashMap<String, f64>,
    call_stack: Vec<CallFrame>,
}

/// Python VM `_truthy`: 仅 None / False / 0(0.0) 为假；空字符串为真（VM 语义，非 bool()）
fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Int(i) => *i != 0,
        Value::Float(f) => *f != 0.0,
        Value::Str(_) => true,
    }
}

/// Bool 参与数值运算/比较时按 0/1（对齐 Python False == 0 / True == 1）
fn is_num(v: &Value) -> bool {
    matches!(
        v,
        Value::Int(_) | Value::Float(_) | Value::Bool(_)
    )
}

fn as_f64(v: &Value) -> f64 {
    match v {
        Value::Int(i) => *i as f64,
        Value::Float(f) => *f,
        Value::Bool(b) => {
            if *b {
                1.0
            } else {
                0.0
            }
        }
        _ => f64::NAN,
    }
}

/// 数值相等（跨 Int/Float，对齐 Python 1 == 1.0）；Str 比 Str；Bool 同 Bool
fn values_eq(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Null, Value::Null) => true,
        (Value::Bool(x), Value::Bool(y)) => x == y,
        (Value::Str(x), Value::Str(y)) => x == y,
        _ if is_num(a) && is_num(b) => as_f64(a) == as_f64(b),
        _ => false,
    }
}

fn arith(op: &str, a: &Value, b: &Value) -> Result<Value, String> {
    if !is_num(a) || !is_num(b) {
        return Err(format!("算术 '{op}' 作用于非数值 {:?} / {:?}", a, b));
    }
    // DIV 恒真除（Python 语义）→ Float；其余同型保持 Int
    if op == "DIV" {
        let d = as_f64(b);
        if d == 0.0 {
            return Err("除零错误".into());
        }
        return Ok(Value::Float(as_f64(a) / d));
    }
    if let (Value::Int(x), Value::Int(y)) = (a, b) {
        let r = match op {
            "ADD" => x.checked_add(*y),
            "SUB" => x.checked_sub(*y),
            "MUL" => x.checked_mul(*y),
            _ => None,
        };
        if let Some(v) = r {
            return Ok(Value::Int(v));
        }
        // 溢出降级 Float（声明局限：Python 无限精度整数不模拟）
        let (fx, fy) = (*x as f64, *y as f64);
        return Ok(Value::Float(match op {
            "ADD" => fx + fy,
            "SUB" => fx - fy,
            _ => fx * fy,
        }));
    }
    let (x, y) = (as_f64(a), as_f64(b));
    Ok(Value::Float(match op {
        "ADD" => x + y,
        "SUB" => x - y,
        "MUL" => x * y,
        _ => return Err(format!("未知算术 '{op}'")),
    }))
}

fn compare(op: &str, a: &Value, b: &Value) -> Result<Value, String> {
    let ord = match (a, b) {
        _ if is_num(a) && is_num(b) => as_f64(a).partial_cmp(&as_f64(b)),
        (Value::Str(x), Value::Str(y)) => Some(x.cmp(y)),
        _ => None,
    };
    let ord = ord.ok_or_else(|| format!("比较 '{op}' 作用于不可比类型"))?;
    let r = match op {
        "CMP_GT" => ord == std::cmp::Ordering::Greater,
        "CMP_LT" => ord == std::cmp::Ordering::Less,
        "CMP_GE" => ord != std::cmp::Ordering::Less,
        "CMP_LE" => ord != std::cmp::Ordering::Greater,
        _ => return Err(format!("未知比较 '{op}'")),
    };
    Ok(Value::Bool(r))
}

/// 默认空环境（等价 [`VM::new`]）——VM 成为库公开 API 后需满足新式惯用法。
impl Default for VM {
    fn default() -> Self {
        Self::new()
    }
}

impl VM {
    pub fn new() -> Self {
        VM {
            ip: 0,
            stack: Vec::new(),
            symbols: HashMap::new(),
            condition_stack: Vec::new(),
            trust_value: 0.0,
            trust_parts: HashMap::new(),
            call_stack: Vec::new(),
        }
    }

    /// 当前条件空间名（栈空 → 默认）——对齐 Python `_condition_space_name`
    fn condition_space_name(&self) -> String {
        match self.condition_stack.last() {
            Some(f) if !f.name.is_empty() => f.name.clone(),
            _ => DEFAULT_CONDITION_SPACE.to_string(),
        }
    }

    /// 切换条件空间（使「条件空间切换」在 VM 上真正可执行，缺陷③）
    /// 恢复默认/默认 → 弹栈到根并置名默认；否则替换栈顶（栈空则压入）。
    fn switch_condition_space(&mut self, name: &str) {
        if name == "恢复默认" || name == DEFAULT_CONDITION_SPACE {
            if self.condition_stack.len() > 1 {
                self.condition_stack.truncate(1);
            }
            if let Some(f) = self.condition_stack.last_mut() {
                f.name = DEFAULT_CONDITION_SPACE.to_string();
                f.trust_at_create = self.trust_value;
            }
            return;
        }
        let frame = CondFrame {
            name: name.to_string(),
            trust_at_create: self.trust_value,
        };
        if self.condition_stack.is_empty() {
            self.condition_stack.push(frame);
        } else {
            let n = self.condition_stack.len();
            self.condition_stack[n - 1] = frame;
        }
    }

    /// 内建名取值；非内建名 → None——对齐 Python `_builtin_load`
    fn builtin_load(&self, name: &str) -> Option<Value> {
        if name == BUILTIN_TRUST_VALUE {
            return Some(Value::Float(self.trust_value));
        }
        if name == BUILTIN_CONDITION_SPACE {
            return Some(Value::Str(self.condition_space_name()));
        }
        if CONDITION_SPACE_NAMES.contains(&name) {
            // 空间名 → 自身（供「条件空间 为 X」比较）
            return Some(Value::Str(name.to_string()));
        }
        if name == BUILTIN_TRUST_THRESHOLD {
            return Some(Value::Float(DEFAULT_TRUST_THRESHOLD));
        }
        if let Some(v) = self.trust_parts.get(name) {
            return Some(Value::Float(*v));
        }
        None
    }

    fn state(&self) -> State {
        State {
            trust: (self.trust_value * 1000.0).round() / 1000.0,
            symbols: self.symbols.clone(),
            condition_space: self.condition_stack.clone(),
            stack: self.stack.clone(),
            halt: None,
        }
    }

    /// 执行字节码（语义对齐 ConditionVM.run：止/无为经 VmError::Halted 返回）
    pub fn run(
        &mut self,
        code: &[Instr],
        symbols: HashMap<String, Value>,
        trust: f64,
        condition_stack: Vec<CondFrame>,
        max_steps: u64,
    ) -> Result<State, VmError> {
        self.ip = 0;
        self.stack = Vec::new();
        // 内建名归一（对齐 Python ConditionVM.reset，缺陷②③）：
        // 符号表里的 信任值/条件空间/信任分量 视为**寄存器初值**而非普通符号，
        // 保证「名」与「实」只有一处存储（否则德 改寄存器、信任值 读符号，二者脱钩）。
        let mut symbols = symbols;
        let mut trust = trust;
        if let Some(v) = symbols.remove(BUILTIN_TRUST_VALUE) {
            if !is_num(&v) {
                return Err(VmError::Error(format!(
                    "名实不符：{} 初值需数值，得到 {:?}",
                    BUILTIN_TRUST_VALUE, v
                )));
            }
            trust = as_f64(&v);
        }
        let seed_space = symbols.remove(BUILTIN_CONDITION_SPACE);
        self.symbols = symbols;
        self.trust_parts = HashMap::new();
        for n in TRUST_COMPONENT_NAMES.iter() {
            if let Some(v) = self.symbols.remove(*n) {
                if is_num(&v) {
                    self.trust_parts.insert((*n).to_string(), as_f64(&v));
                }
            }
        }
        self.condition_stack = condition_stack;
        self.trust_value = trust;
        self.call_stack = Vec::new();
        if let Some(Value::Str(sp)) = seed_space {
            self.switch_condition_space(&sp);
        }
        let mut steps: u64 = 0;
        while self.ip < code.len() {
            steps += 1;
            if steps > max_steps {
                return Err(VmError::Error(format!(
                    "循环未终止（超出步数上限 {max_steps}）"
                )));
            }
            let instr = &code[self.ip];
            self.ip += 1;
            match self.exec(instr) {
                Ok(()) => {}
                Err(VmError::Halted(kind, mut st)) => {
                    st.halt = Some(kind);
                    return Ok(*st);
                }
                Err(e) => return Err(e),
            }
        }
        Ok(self.state())
    }

    fn pop(&mut self) -> Result<Value, VmError> {
        self.stack
            .pop()
            .ok_or_else(|| VmError::Error("栈空弹出（字节码栈不平衡）".into()))
    }

    fn exec(&mut self, instr: &Instr) -> Result<(), VmError> {
        let name = instr.op.as_str();
        match name {
            "PUSH_CONST" => {
                let v = match &instr.arg {
                    Arg::None => Value::Null,
                    Arg::Bool(b) => Value::Bool(*b),
                    Arg::Int(i) => Value::Int(*i),
                    Arg::Float(f) => Value::Float(*f),
                    Arg::Str(s) => Value::Str(s.clone()),
                    _ => return Err(VmError::Error("PUSH_CONST 参数类型非法".into())),
                };
                self.stack.push(v);
            }
            "LOAD_NAME" => {
                let key = expect_str(&instr.arg)?;
                if let Some(v) = self.symbols.get(key).cloned() {
                    self.stack.push(v);
                } else if let Some(v) = self.builtin_load(key) {
                    // 内建名（信任值/条件空间/空间名/信任分量）——缺陷②③修复点
                    self.stack.push(v);
                } else {
                    return Err(VmError::Error(format!("名实不符：'{key}' 未声明（以名举实）")));
                }
            }
            "STORE_NAME" => {
                let key = expect_str(&instr.arg)?.to_string();
                let v = self.pop()?;
                if key == BUILTIN_TRUST_VALUE {
                    if !is_num(&v) {
                        return Err(VmError::Error(format!(
                            "{} 只能写数值，得到 {:?}",
                            BUILTIN_TRUST_VALUE, v
                        )));
                    }
                    self.trust_value = as_f64(&v);
                } else if key == BUILTIN_CONDITION_SPACE {
                    match v {
                        Value::Str(s) => self.switch_condition_space(&s),
                        _ => {
                            return Err(VmError::Error(format!(
                                "{} 只能写空间名（字符串），得到 {:?}",
                                BUILTIN_CONDITION_SPACE, v
                            )))
                        }
                    }
                } else if let Some(slot) = self.trust_parts.get_mut(&key) {
                    // 信任分量写入（get_mut 而非 contains_key+insert：
                    // 后者触发 clippy map_entry 警告，测试要求零警告）
                    if !is_num(&v) {
                        return Err(VmError::Error(format!("{} 只能写数值", key)));
                    }
                    *slot = as_f64(&v);
                } else {
                    self.symbols.insert(key, v);
                }
            }
            "JUMP" => {
                self.ip = expect_int(&instr.arg)? as usize;
            }
            "JUMP_IF_FALSE" => {
                let v = self.pop()?;
                if !truthy(&v) {
                    self.ip = expect_int(&instr.arg)? as usize;
                }
            }
            "DAO" => {
                let name = expect_str(&instr.arg)?.to_string();
                self.condition_stack.push(CondFrame {
                    name,
                    trust_at_create: self.trust_value,
                });
            }
            "DE" => {
                let d = match &instr.arg {
                    Arg::Float(f) => *f,
                    Arg::Int(i) => *i as f64,
                    _ => return Err(VmError::Error("DE 参数需数值".into())),
                };
                self.trust_value += d;
            }
            "ZIRAN" => {
                // 恢复默认条件空间：弹栈到根（保留首帧；空栈保持空）
                if self.condition_stack.len() > 1 {
                    self.condition_stack.truncate(1);
                }
            }
            "WUWEI" => {
                return Err(VmError::Halted("yield".into(), Box::new(self.state())));
            }
            "ZHI" => {
                return Err(VmError::Halted("halt".into(), Box::new(self.state())));
            }
            "ZHIZU" => {
                let (threshold, addr) = expect_threshold(&instr.arg)?;
                if self.trust_value >= threshold {
                    self.ip = addr as usize;
                }
            }
            "CMP_EQ" => {
                let b = self.pop()?;
                let a = self.pop()?;
                self.stack.push(Value::Bool(values_eq(&a, &b)));
            }
            "CMP_NE" => {
                let b = self.pop()?;
                let a = self.pop()?;
                self.stack.push(Value::Bool(!values_eq(&a, &b)));
            }
            "CMP_GT" | "CMP_LT" | "CMP_LE" | "CMP_GE" => {
                let b = self.pop()?;
                let a = self.pop()?;
                let r = compare(name, &a, &b).map_err(VmError::Error)?;
                self.stack.push(r);
            }
            "ADD" | "SUB" | "MUL" | "DIV" => {
                let b = self.pop()?;
                let a = self.pop()?;
                let op = name.rsplit('_').next().unwrap_or(name);
                let r = arith(op, &a, &b).map_err(VmError::Error)?;
                self.stack.push(r);
            }
            "ENTER_SHUYUE" | "RETURN_STEP" => {
                // 作用域深度仅作语义标记（Python 侧计数，不影响控制流）
            }
            "CALL" => {
                let (entry, params) = expect_callsig(&instr.arg)?;
                if self.stack.len() < params.len() {
                    return Err(VmError::Error("CALL 实参不足".into()));
                }
                let mut args = Vec::with_capacity(params.len());
                for _ in 0..params.len() {
                    args.push(self.pop()?);
                }
                args.reverse();
                let frame = CallFrame {
                    ret_ip: self.ip,
                    symbols: self.symbols.clone(),
                    trust: self.trust_value,
                    cond: self.condition_stack.clone(),
                };
                self.call_stack.push(frame);
                for (pname, pval) in params.iter().zip(args) {
                    self.symbols.insert(pname.clone(), pval);
                }
                self.ip = entry as usize;
            }
            "RETURN" => {
                if let Some(fr) = self.call_stack.pop() {
                    self.symbols = fr.symbols;
                    self.trust_value = fr.trust;
                    self.condition_stack = fr.cond;
                    self.ip = fr.ret_ip;
                } else {
                    // 顶层 RETURN：无调用者 → 停止
                    return Err(VmError::Halted("halt".into(), Box::new(self.state())));
                }
            }
            other => {
                return Err(VmError::Error(format!("未知指令 {other}")));
            }
        }
        Ok(())
    }
}

fn expect_str(arg: &Arg) -> Result<&str, VmError> {
    match arg {
        Arg::Str(s) => Ok(s),
        _ => Err(VmError::Error(format!("期望字符串参数，得 {arg:?}"))),
    }
}

fn expect_int(arg: &Arg) -> Result<i64, VmError> {
    match arg {
        Arg::Int(i) => Ok(*i),
        _ => Err(VmError::Error(format!("期望整数参数，得 {arg:?}"))),
    }
}

fn expect_threshold(arg: &Arg) -> Result<(f64, i64), VmError> {
    match arg {
        Arg::Threshold(t, a) => Ok((*t, *a)),
        _ => Err(VmError::Error(format!("期望 (阈值,地址) 参数，得 {arg:?}"))),
    }
}

fn expect_callsig(arg: &Arg) -> Result<(i64, &[String]), VmError> {
    match arg {
        Arg::CallSig(e, p) => Ok((*e, p)),
        _ => Err(VmError::Error(format!("期望调用签名参数，得 {arg:?}"))),
    }
}

// ==================== 状态 JSON 输出（手写序列化，零依赖） ====================

fn json_escape(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// Rust `format!("{}", 2.0_f64)` 输出 "2"——JSON 数值直接可解析，对照用数值比较
fn json_value(v: &Value, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Int(i) => {
            let _ = write!(out, "{i}");
        }
        Value::Float(f) => {
            if f.is_finite() {
                let _ = write!(out, "{f}");
            } else {
                out.push_str("null"); // NaN/Inf 在 JSON 无表示
            }
        }
        Value::Str(s) => json_escape(s, out),
    }
}

/// 终态 → JSON（键序：halt/stack/symbols/trust/condition_space；结构与 Python run() 同构）
pub fn state_json(st: &State) -> String {
    let mut out = String::new();
    out.push('{');
    out.push_str("\"halt\":");
    match &st.halt {
        Some(k) => json_escape(k, &mut out),
        None => out.push_str("null"),
    }
    out.push_str(",\"stack\":[");
    for (i, v) in st.stack.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        json_value(v, &mut out);
    }
    out.push_str("],\"symbols\":{");
    let mut keys: Vec<&String> = st.symbols.keys().collect();
    keys.sort();
    for (i, k) in keys.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        json_escape(k, &mut out);
        out.push(':');
        json_value(&st.symbols[*k], &mut out);
    }
    out.push_str("},\"trust\":");
    json_value(&Value::Float(st.trust), &mut out);
    out.push_str(",\"condition_space\":[");
    for (i, c) in st.condition_space.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push_str("{\"name\":");
        json_escape(&c.name, &mut out);
        out.push_str(",\"trust_at_create\":");
        json_value(&Value::Float(c.trust_at_create), &mut out);
        out.push('}');
    }
    out.push_str("]}");
    out
}
