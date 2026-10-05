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

/// SEMANTICS.md §1 写面标「—」的只读内建名（N272）：写入 → `VmError::Error`。
/// 与 compiler/{name_checker,condition_vm}.py 的 `READONLY_BUILTIN_NAMES` 同集
/// ——编译期/运行期同判；修复前写入落 symbols 静默遮蔽内建读取（两 VM 皆漏）。
fn is_readonly_builtin(name: &str) -> bool {
    name == BUILTIN_TRUST_THRESHOLD || CONDITION_SPACE_NAMES.contains(&name)
}

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
    /// N244：跳转地址上界（`set_ip` 单点用；`run()` 置为 `len(code)`）。
    /// 与 Python 侧 `ConditionVM._code_len`（N239）同构——双后端同判据。
    code_len: usize,
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

/// 终态 trust 舍入**单点**（N246）：与 Python 侧 `round(x, 3)`
/// （condition_vm.py 的终态组装）同口径——十进制**半偶**（对精确二进制值
/// 正确舍入到 3 位小数，恰在并列点取偶）。
///
/// 旧实现 `(x * 1000.0).round() / 1000.0` 有两处偏差，都会破坏
/// compiler/SEMANTICS.md §5 双后端契约：①`f64::round` 是**半数远离零**——
/// 并列点（0.0625 等精确可表示的二进制小数）得 0.063 而 Python 得 0.062；
/// ②`x * 1000.0` 本身不精确，非并列点也分叉（实测 0.0155 → 0.016 而
/// Python 0.015、1.2345 → 1.235 而 Python 1.234）。
///
/// 实现取 `format!("{:.3}", x)`：Rust 定点格式先对二进制值做**精确**十进制
/// 展开再按半偶舍入（实测 4019 例语料与 CPython `round(x,3)` 逐位一致，含
/// 全部并列点、±0.0、NaN、±∞），parse 回 f64 即同一双精度值；解析异常时
/// 原值回退（行为确定，不 panic）。
fn round3(x: f64) -> f64 {
    format!("{:.3}", x).parse::<f64>().unwrap_or(x)
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
            code_len: 0,
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
            trust: round3(self.trust_value), // N246：与 Python round(x,3) 同口径
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
        self.code_len = code.len(); // N244：跳转地址上界（set_ip 单点用）
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

    /// 跳转地址校验**单点**（N244，对齐 Python 侧 N239 `_jump`）：越界即拒。
    ///
    /// 旧实现四处直接 `self.ip = … as usize`：负目标被折成巨大无符号数
    /// （`JUMP -1` → 2^64-1），`run` 的 `while self.ip < code.len()` 随即为假、
    /// `run()` 返回 Ok（halt=None）、二进制 exit 0——其后指令整段不执行且无
    /// 任何诊断（静默错误），且与 Python 侧已修的 N239 判据分叉。
    ///
    /// 目标须落在 `[0, code_len]`。上界取 **`<= code_len`** 而非 `<`：
    /// `== code_len` 是「跳到程序末尾」的**既有语义**——编译器自身就产出该
    /// 目标（知足标签与末尾 若/则 的 end 标签都落在此处）；`> code_len` 不可能
    /// 由编译器产出，属越界。
    ///
    /// 地址在**写入 `self.ip` 处**校验（四处写入点统一走本助手）——未发生的
    /// 跳转（如 `JUMP_IF_FALSE` 真值侧）不改变任何既有程序行为。
    fn set_ip(&mut self, target: i64) -> Result<(), VmError> {
        // 先判非负再转 u64：`as usize` 对负值折成巨大无符号数仍会通过上界比较
        if target >= 0 && (target as u64) <= self.code_len as u64 {
            self.ip = target as usize;
            return Ok(());
        }
        Err(VmError::Error(format!(
            "跳转目标越界：{target}（合法地址 0..={}）——负值不得回绕、超界不得静默结束",
            self.code_len
        )))
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
                } else if is_readonly_builtin(&key) {
                    // N272：SEMANTICS.md §1 写面「—」的只读内建名——写入即
                    // 结构化拒（修复前落 symbols 静默遮蔽内建读取；与 Python
                    // 侧 VMBuiltinError('readonly') 同判）。
                    return Err(VmError::Error(format!(
                        "{key} 是只读内建名，不可写入（SEMANTICS.md §1 写面「—」）"
                    )));
                } else {
                    self.symbols.insert(key, v);
                }
            }
            "JUMP" => {
                self.set_ip(expect_int(&instr.arg)?)?; // N244：地址校验单点
            }
            "JUMP_IF_FALSE" => {
                let v = self.pop()?;
                if !truthy(&v) {
                    self.set_ip(expect_int(&instr.arg)?)?; // N244
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
                    self.set_ip(addr)?; // N244
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
                self.set_ip(entry)?; // N244：入口地址同为跳转目标
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

#[cfg(test)]
mod jump_guard_tests {
    //! N244 守卫（缺陷：写入 `self.ip` 的跳转/调用入口目标全无范围校验——
    //! 负目标被 `as usize` 折成巨大无符号数，`while self.ip < code.len()`
    //! 随即为假、`run()` 返回 Ok（halt=None），其后指令整段静默不执行；
    //! 超界目标同样静默结束）。
    //! 纯行为断言（不做源码文本匹配）。判据对齐 Python 侧 N239 `_jump`：
    //! 目标须落在 `[0, len(code)]`；**上界取 `<=` 而非 `<`**——`== len(code)`
    //! 是编译器自身产出的「跳到程序末尾」既有语义（知足标签与末尾 若/则 的
    //! end 标签都落在此处），收紧成 `<` 会打红合法产物。
    use super::*;

    fn ins(op: &str, arg: Arg) -> Instr {
        Instr {
            op: op.to_string(),
            arg,
        }
    }

    fn run_sum(code: &[Instr], max_steps: u64) -> Result<State, VmError> {
        VM::new().run(code, HashMap::new(), 0.0, Vec::new(), max_steps)
    }

    /// 越界/负值目标必须得真错误——不是静默走完，也不是被当作正常控制流。
    fn expect_jump_error(tag: &str, code: &[Instr]) {
        match run_sum(code, 100_000) {
            Err(VmError::Error(e)) => assert!(
                e.contains("跳转目标越界"),
                "{tag}：错误未点明跳转越界（得到 {e}）"
            ),
            Err(VmError::Halted(k, _)) => {
                panic!("{tag}：得到 Halted({k})——越界目标不得被当作正常控制流")
            }
            Ok(st) => panic!(
                "{tag}：run() 返回 Ok（halt={:?}、symbols={:?}）——越界目标被静默走完",
                st.halt, st.symbols
            ),
        }
    }

    /// ① 负目标不得（折成大无符号数后）静默走完
    #[test]
    fn negative_targets_are_rejected() {
        expect_jump_error(
            "①a JUMP -1",
            &[
                ins("JUMP", Arg::Int(-1)),
                ins("PUSH_CONST", Arg::Int(42)),
                ins("STORE_NAME", Arg::Str("标记".into())),
                ins("ZHI", Arg::None),
            ],
        );
        expect_jump_error(
            "①b JUMP_IF_FALSE -1（取假分支）",
            &[
                ins("PUSH_CONST", Arg::Int(0)),
                ins("JUMP_IF_FALSE", Arg::Int(-1)),
                ins("ZHI", Arg::None),
            ],
        );
        expect_jump_error(
            "①c ZHIZU (0.0,-1)（达标跳负地址）",
            &[
                ins("ZHIZU", Arg::Threshold(0.0, -1)),
                ins("PUSH_CONST", Arg::Int(9)),
                ins("ZHI", Arg::None),
            ],
        );
        expect_jump_error(
            "①d CALL 入口 -1",
            &[
                ins("PUSH_CONST", Arg::Int(1)),
                ins("CALL", Arg::CallSig(-1, vec!["a".into()])),
                ins("ZHI", Arg::None),
            ],
        );
    }

    /// ② 超界目标不得静默结束（旧实现：`while ip < len` 直接为假）
    #[test]
    fn out_of_range_targets_are_rejected() {
        expect_jump_error(
            "②a JUMP 999（len=4）",
            &[
                ins("PUSH_CONST", Arg::Int(1)),
                ins("STORE_NAME", Arg::Str("甲".into())),
                ins("JUMP", Arg::Int(999)),
                ins("ZHI", Arg::None),
            ],
        );
        expect_jump_error(
            "②b JUMP_IF_FALSE 99（取假分支）",
            &[
                ins("PUSH_CONST", Arg::Int(0)),
                ins("JUMP_IF_FALSE", Arg::Int(99)),
                ins("ZHI", Arg::None),
            ],
        );
        expect_jump_error(
            "②c ZHIZU 超界地址",
            &[
                ins("ZHIZU", Arg::Threshold(0.0, 99)),
                ins("ZHI", Arg::None),
            ],
        );
        expect_jump_error(
            "②d CALL 入口超界",
            &[
                ins("PUSH_CONST", Arg::Int(1)),
                ins("CALL", Arg::CallSig(99, vec!["a".into()])),
                ins("ZHI", Arg::None),
            ],
        );
    }

    /// ③ 边界精确性：`len(code)` 合法（跳到末尾），`len(code)+1` 拒
    #[test]
    fn bound_is_inclusive_len_code() {
        // JUMP 目标 4 == len(code)（编译器产出的「跳到末尾」语义）→ 合法：
        // 甲 已写入、`止` 被跳过 → halt=None
        let at_end = [
            ins("PUSH_CONST", Arg::Int(1)),
            ins("STORE_NAME", Arg::Str("甲".into())),
            ins("JUMP", Arg::Int(4)),
            ins("ZHI", Arg::None),
        ];
        match run_sum(&at_end, 100_000) {
            Ok(st) => {
                assert_eq!(st.halt, None, "③a 跳到末尾：halt 应为 None（止 被跳过）");
                assert_eq!(
                    st.symbols.get("甲"),
                    Some(&Value::Int(1)),
                    "③a 跳到末尾：跳转前的指令须已执行"
                );
            }
            Err(VmError::Error(e)) => panic!("③a JUMP 到 len(code) 应合法，却报错：{e}"),
            Err(VmError::Halted(k, _)) => panic!("③a 被当作控制流提前收尾（{k}）"),
        }
        expect_jump_error(
            "③b JUMP 到 len(code)+1 拒",
            &[
                ins("PUSH_CONST", Arg::Int(1)),
                ins("STORE_NAME", Arg::Str("甲".into())),
                ins("JUMP", Arg::Int(5)),
                ins("ZHI", Arg::None),
            ],
        );
    }

    /// ④ 合法面一字不动：未发生的跳转不校验、自环仍走步数上限、CALL/RETURN 正常
    #[test]
    fn legal_jumps_unchanged() {
        // ④a 未取分支的越界目标不校验（地址在写入 self.ip 处校验——未发生的
        // 跳转不改变任何既有程序行为，与 Python N239 同口径）
        let not_taken = [
            ins("PUSH_CONST", Arg::Int(1)),
            ins("JUMP_IF_FALSE", Arg::Int(99)),
            ins("ZHI", Arg::None),
        ];
        assert!(
            matches!(run_sum(&not_taken, 100_000), Ok(_)),
            "④a 真值侧不跳：越界目标未被写入 ip，不应报错"
        );
        // ④b 自环 JUMP 0 仍由步数上限拦（既有契约不变，非新错误）
        let looped = [ins("JUMP", Arg::Int(0)), ins("ZHI", Arg::None)];
        match run_sum(&looped, 5) {
            Err(VmError::Error(e)) => assert!(
                e.contains("循环未终止"),
                "④b 自环应仍走步数上限，得到 {e}"
            ),
            Ok(_) => panic!("④b 自环应触发步数上限，却正常收尾"),
            Err(VmError::Halted(k, _)) => panic!("④b 自环应以步数上限报错，却 Halted({k})"),
        }
        // ④c 合法 CALL/RETURN 链路不受影响
        let called = [
            ins("PUSH_CONST", Arg::Int(1)),
            ins("CALL", Arg::CallSig(3, vec!["a".into()])),
            ins("ZHI", Arg::None),
            ins("LOAD_NAME", Arg::Str("a".into())),
            ins("STORE_NAME", Arg::Str("本地".into())),
            ins("RETURN", Arg::None),
        ];
        match run_sum(&called, 100_000) {
            Ok(st) => assert_eq!(st.halt.as_deref(), Some("halt"), "④c 返回后应执行 止"),
            Err(VmError::Error(e)) => panic!("④c 合法调用不应报错：{e}"),
            Err(VmError::Halted(k, _)) => panic!("④c 意外 Halted({k})"),
        }
    }
}

#[cfg(test)]
mod trust_round_tests {
    //! N246 守卫：终态 trust 的舍入口径必须与 Python 侧
    //! `round(self.trust_value, 3)`（condition_vm.py）一致——十进制**半偶**
    //! （half-to-even）。旧实现 `(x * 1000.0).round() / 1000.0` 是「半数远离零」：
    //! 并列点（0.0625 等精确可表示的二进制小数）Rust 读 0.063、Python 读 0.062，
    //! 破坏 compiler/SEMANTICS.md §5 双后端契约（test_rust_codegen 的
    //! `abs(差) < 1e-9` 等价判据判红）。
    //! 期望值 = CPython `round(x, 3)`（实测对照；语料 4019 例，见 N246 归档）。
    //! 纯行为断言：只驱动 VM 终态，不依赖实现内部形态（改码前后都编译）。
    use super::*;

    /// 空程序执行：终态 trust 即初值经单点舍入的结果（不掺 德/条件分支）
    fn terminal_trust(t: f64) -> f64 {
        match VM::new().run(&[], HashMap::new(), t, Vec::new(), 100_000) {
            Ok(st) => st.trust,
            Err(_) => panic!("空程序必成功（既不得报错、也不得中止）"),
        }
    }

    /// 并列点（精确可表示的二进制小数，×1000 恰为 k+0.5）→ 半偶
    #[test]
    fn ties_round_half_to_even_like_python() {
        for (x, want) in [
            (0.0625_f64, 0.062_f64),
            (0.3125, 0.312),
            (0.5625, 0.562),
            (0.8125, 0.812),
            (-0.0625, -0.062),
            (-0.3125, -0.312),
            (-0.5625, -0.562),
            (-0.8125, -0.812),
        ] {
            let got = terminal_trust(x);
            assert_eq!(got, want, "并列点 {x} 应半偶舍入为 {want}，得 {got}");
        }
    }

    /// 非并列点（含「看着像并列、二进制实际高于/低于」者）与特殊值
    #[test]
    fn non_ties_and_specials_match_python() {
        for (x, want) in [
            (0.0015_f64, 0.002_f64), // 二进制值高于并列点 → 进位
            (0.0155, 0.015),
            (0.1235, 0.123),
            (0.9995, 1.0),
            (2.675, 2.675),
            (1.2345, 1.234),
            (0.3 + 0.1, 0.4), // 0.4000000000000000222 → 0.4
            (0.1 + 0.8, 0.9), // 0.9000000000000000222 → 0.9
            (1.0, 1.0),
            (0.0, 0.0),
        ] {
            let got = terminal_trust(x);
            assert_eq!(got, want, "{x} 应舍入为 {want}，得 {got}");
        }
        assert!(terminal_trust(f64::NAN).is_nan(), "NaN 应保持 NaN");
        assert_eq!(terminal_trust(f64::INFINITY), f64::INFINITY, "∞ 应保持 ∞");
        assert!(
            terminal_trust(-0.0).is_sign_negative(),
            "负零应保持符号（round(-0.0,3) == -0.0）"
        );
    }
}
