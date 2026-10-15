//! swarm.rs · 蜂群协调器（多进程蜂群 · 对齐 aeis.swarm 语义）
//! 荣 2026-09-06 裁定：多实例并行（进程级）+ 消息传递 + 实例私有信任/条件空间 + 聚合层。
//!   - 实例 = protocol_vm --serve 子进程（进程隔离，stdio 管道通信）
//!   - 事件总线：WAL 落盘（events.jsonl）+ HMAC-SHA256 签名 + ACK 追踪
//!   - 消息传递语义：事件投递 = 写入目标实例下一轮的「收件箱」初始符号
//!   - 信任聚合：T_avg/T_min/T_variance/T_alignment（对齐 trust_aggregator.py，
//!     防操纵：同轮同实例去重 B6 / 0-1 夹取 / verified 过滤）
//!
//! 纯 std 零 crate 依赖（SHA256/HMAC 手写见 hmac.rs）。

use std::collections::{HashMap, HashSet};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::process::{Child, Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::hmac::{hmac_sha256, hex32};
use crate::health::{score_instance, HealthReport, HealthWeights};

/// 延迟分级（对齐 event_bus.py DELIVERY-V1）——V0 仅作 WAL 元数据标记，
/// 投递间隔调度为后续版本（荣小步实验纪律：先同步路由）
#[allow(dead_code)]
pub const DELAY_HIGH_MS: u64 = 500;
#[allow(dead_code)]
pub const DELAY_MID_MS: u64 = 5_000;
#[allow(dead_code)]
pub const DELAY_LOW_MS: u64 = 30_000;

#[derive(Debug, Clone)]
pub struct InstanceSpec {
    pub id: String,
    /// V0 仅随报告透出（身份语义声明），协调器路由暂不消费
    #[allow(dead_code)]
    pub role: String,
    /// 初始信任值
    pub trust: f64,
    /// 初始符号表（JSON 对象文本，由 Python 侧生成）
    pub symbols_json: String,
    /// G-R2 条件空间卡（随 spec 下发到实例输入——执行链消费，非仅 metadata）
    pub condition_space: Option<ConditionSpace>,
}

#[derive(Debug, Clone)]
pub struct Event {
    /// v0.7.1：全局事件序（immutable event identity，进 HMAC 签名串首位）
    pub seq: u64,
    pub ts: u64,
    pub from_id: String,
    pub to_id: String,
    pub event_type: String,
    pub payload_json: String,
    pub round_no: u64,
    pub level: u8, // 0=高 1=中 2=低
    pub hmac_hex: String,
}

pub struct SwarmConfig {
    pub shared_secret: String,
    pub instances: Vec<InstanceSpec>,
    /// 路由表：(round, from, event_type) → [(to, payload_json, level)]
    /// 第一版语义：实例 r 轮终态后，按路由表把指定符号载荷广播给目标实例 r+1 轮。
    /// payload_json 里可用 "@trust" 占位（运行时替换为源实例终态信任值）。
    pub routes: Vec<Route>,
    /// G4a 拓扑："" = 未指定（角色保持用户声明，向后兼容）；
    /// "mesh" = 全 peer；"hierarchical" = 首实例 queen 其余 worker；
    /// "centralized" = 首实例 coordinator 其余 worker（对照 A3 ruflo determineRole）
    pub topology: String,
    /// G-R2 条件空间卡（None = 未声明，向后兼容）
    pub condition_space: Option<ConditionSpace>,
}

/// G4a 角色推导（对照 ruflo topology-manager.ts:311-330）。
/// `index` 为实例在配置中的序位；`requested` 为用户声明角色。
pub fn derive_role(topology: &str, index: usize, requested: &str) -> Result<String, String> {
    match topology {
        "" => Ok(requested.to_string()), // 未指定拓扑：保持用户声明（向后兼容）
        "mesh" => Ok("peer".to_string()),
        "hierarchical" => Ok(if index == 0 { "queen" } else { "worker" }.to_string()),
        "centralized" => Ok(if index == 0 { "coordinator" } else { "worker" }.to_string()),
        // G-R3 protocol 拓扑（§3.9 四角色）：primary 执行 / verifier 逐位复算 /
        // arbiter 分歧终裁（单机下由协调器承担，此处显式角色位）/ recorder 记录
        "protocol" => Ok(match index {
            0 => "primary",
            1 => "verifier",
            2 => "arbiter",
            3 => "recorder",
            _ => "worker",
        }
        .to_string()),
        other => Err(format!(
            "未知拓扑 {other}（支持 mesh/hierarchical/centralized/protocol 或缺省）"
        )),
    }
}

#[derive(Debug, Clone)]
pub struct Route {
    pub from_id: String,
    pub event_type: String,
    pub to_id: String,
    pub payload_json: String,
    pub level: u8,
}

pub struct SwarmReport {
    pub rounds: u64,
    pub events: Vec<Event>,
    pub acks: HashSet<String>, // event hex 索引 → 已 ACK
    pub t_avg: f64,
    pub t_min: f64,
    pub t_variance: f64,
    pub t_alignment: f64,
    pub final_states: HashMap<String, serde_json_like::Value>,
    /// G3a：实例健康四因子评分（甲案裁定 2026-09-13）
    pub health: HealthReport,
    /// G3b：gossip 水位记账（实例 → 实际收到的 gossip 消息数）
    pub gossip_received: HashMap<String, usize>,
    /// G3b：gossip 对账一致（每个 gossip 目标都足额收到）
    pub gossip_consistent: bool,
    /// G4a：生效拓扑（"" = 未指定）
    pub topology: String,
    /// G-R2 条件空间卡（None = 未声明，向后兼容）
    pub condition_space: Option<ConditionSpace>,
    /// G4a：实例角色表（拓扑推导后）
    pub roles: HashMap<String, String>,
    /// G4b：实例消费水位（最后 ACK 的收件箱消息全局 seq）
    pub watermarks: HashMap<String, u64>,
    /// G4b：全局已分配消息 seq
    pub global_seq: u64,
    /// issue #354 P1-6：WAL 重放区 seq/round 连续性读数（审计面；ok=false 表示
    /// 已提交区存在丢行/乱序——旧实现对此完全静默）
    pub wal_continuity: WalContinuity,
    /// G-R2：生效条件空间 space_id（None = 未声明）
    pub condition_space_id: Option<String>,
    /// G-R3：verifier 逐位复算统计（已复核轮数 / 不一致数）
    pub recalc_checked: u64,
    pub recalc_mismatches: u64,
}

/// gossip 广播保留目标名：Route.to_id = GOSSIP_TARGET 时 fan-out 至除源外全部实例
pub const GOSSIP_TARGET: &str = "*";

/// G-R2 条件空间卡（§0.0.5 条件论 / §3.1.2 / 第三章声明格式）。
/// 四要素缺一不可——缺失即拒绝运行（负路由：不满足生效条件不执行）。
#[derive(Debug, Clone)]
pub struct ConditionSpace {
    pub space_id: String,
    pub observation_position: String,
    pub observation_tool: String,
    pub time_window: String,
    pub existence_constraint: String,
}

/// 校验并提取可选条件空间卡（cfg_json["condition_space"]）。
/// 返回 None = 未声明（向后兼容）；声明但四要素任一缺失/为空 → Err。
pub fn validate_condition_space(
    raw: Option<&serde_json_like::Value>,
) -> Result<Option<ConditionSpace>, String> {
    let Some(cs) = raw else { return Ok(None) };
    let field = |name: &str| -> Result<String, String> {
        cs.get(name)
            .and_then(|x| x.as_str())
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .ok_or_else(|| format!("条件空间卡字段 {name} 缺失或为空（四要素缺一不可，§3.1.2）"))
    };
    Ok(Some(ConditionSpace {
        space_id: field("space_id")?,
        observation_position: field("observation_position")?,
        observation_tool: field("observation_tool")?,
        time_window: field("time_window")?,
        existence_constraint: field("existence_constraint")?,
    }))
}

/// G4b 收件箱：轮次 → 目标实例 → 来源 → Vec<(载荷, 投递时全局 seq)>。
/// 2026-09-25 修复 #2：来源的值由单条改列表——同轮同源多条路由不再
/// 互相覆盖（旧单值 key 下第二条 insert 静默丢弃第一条载荷，而 WAL
/// 两条事件均已 HMAC 签名落盘为「已投递」，审计留痕与实际投递不符）。
type Inboxes = HashMap<u64, HashMap<String, HashMap<String, Vec<(String, u64)>>>>;

/// G5 单实例单轮结果：Some(Ok)=终态+是否有收件箱+消费 seq；Some(Err)=重试仍败；
/// None=死亡实例缺失轮
type RoundOutcome = Option<Result<(serde_json_like::Value, bool, u64), String>>;

/// 极简 JSON（与 serve.rs serde_like 同源实现——单文件内聚）
pub mod serde_json_like {
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
        pub fn get(&self, k: &str) -> Option<&Value> {
            match self {
                Value::Obj(m) => m.get(k),
                _ => None,
            }
        }
        pub fn as_f64(&self) -> Option<f64> {
            match self {
                Value::Num(f) => Some(*f),
                _ => None,
            }
        }
        pub fn as_str(&self) -> Option<&str> {
            match self {
                Value::Str(s) => Some(s),
                _ => None,
            }
        }
    }

    pub fn stringify(v: &Value) -> String {
        match v {
            Value::Null => "null".into(),
            Value::Bool(b) => b.to_string(),
            Value::Num(f) => format!("{f}"),
            Value::Str(s) => format!("\"{}\"", escape(s)),
            Value::List(items) => {
                let parts: Vec<String> = items.iter().map(stringify).collect();
                format!("[{}]", parts.join(","))
            }
            Value::Obj(m) => {
                let mut keys: Vec<&String> = m.keys().collect();
                keys.sort();
                let parts: Vec<String> = keys
                    .iter()
                    .map(|k| format!("\"{}\":{}", escape(k), stringify(&m[*k])))
                    .collect();
                format!("{{{}}}", parts.join(","))
            }
        }
    }

    pub fn escape(s: &str) -> String {
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

    /// 嵌套深度上限（#156⑧ · K 组 task-49）：递归下降 value↔object/array 互递归无界
    /// 时，深嵌套输入会让 **Rust 栈溢出 abort 整进程**——栈溢出不可捕获，swarm/serve
    /// 一并死。而本解析器的输入面（inbox 行 / 事件行 / --config 配置）都是任意宿主可写
    /// 的跨语言文件协议接口，不能假定良构。
    /// 取 256 与 hive 侧**同族解析器的既有口径逐位一致**（hive/src/json.rs:123 的 N184
    /// 判据：debug 主线程 768 层可过、1024 层即溢出 ≈1KB/层，故对上界留 ≥3× 余量；
    /// 正常文件嵌套 ≤10 层）。两侧同值不是巧合——同族解析器一个上限，勿分叉两套。
    const MAX_DEPTH: usize = 256;

    pub fn parse(s: &str) -> Result<Value, String> {
        let b: Vec<char> = s.chars().collect();
        let mut i = 0usize;
        let v = pv(&b, &mut i, 0)?;
        Ok(v)
    }

    fn skip_ws(b: &[char], i: &mut usize) {
        while *i < b.len() && b[*i].is_whitespace() {
            *i += 1;
        }
    }

    fn pv(b: &[char], i: &mut usize, depth: usize) -> Result<Value, String> {
        // #156⑧：深度闸在**每次进入递归体**时判——超限返回 Err（可读原因）落「解析
        // 失败」面，绝不放任递归把栈吃穿。旧版无此闸，实测 5000 层直接
        // `thread 'main' has overflowed its stack` abort（退出码 0xC00000FD）。
        if depth > MAX_DEPTH {
            return Err(format!("嵌套过深（>{MAX_DEPTH} 层）——拒绝解析以防栈溢出"));
        }
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
                            let (k, ni) = ps(b, *i)?;
                            *i = ni;
                            skip_ws(b, i);
                            if b.get(*i) != Some(&':') {
                                return Err("缺 ':'".into());
                            }
                            *i += 1;
                            let v = pv(b, i, depth + 1)?;
                            m.insert(k, v);
                        }
                        _ => return Err("对象非法".into()),
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
                        _ => items.push(pv(b, i, depth + 1)?),
                    }
                }
            }
            Some('"') => {
                let (s, ni) = ps(b, *i)?;
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

    fn ps(b: &[char], start: usize) -> Result<(String, usize), String> {
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
                        Some('/') => out.push('/'),
                        Some('n') => out.push('\n'),
                        Some('t') => out.push('\t'),
                        // N245：读侧须与写侧 `escape` **同集**——写侧对回车产 `\r`、
                        // 对 <0x20 控制字符产 `\uXXXX`（制表符即 `\u0009`）。此前
                        // 只认 `\" \\ \n \t`，集合不相容导致三面静默/拒服务：
                        // ①符号值含制表符 → 实例请求行解析失败、终态恒为 error 而
                        // 协调器 rc=0 照发 ACK/推进水位；②WAL 载荷含 `\u0009` →
                        // 提交点扫描首行即断、合法 WAL 被误标 `.corrupt-*` 并从轮 1
                        // 重跑；③配置含 `\r` → 整蜂群「配置 JSON 非法」exit 2。
                        Some('r') => out.push('\r'),
                        Some('b') => out.push('\u{0008}'),
                        Some('f') => out.push('\u{000c}'),
                        Some('u') => {
                            // \uXXXX：4 位十六进制（BMP 码点）。代理对不合成——
                            // 写侧不产（星平面字符原样直出），遇到即响亮报错。
                            let hex: String = b
                                .get(i + 1..i + 5)
                                .map(|h| h.iter().collect())
                                .unwrap_or_default();
                            if hex.chars().count() != 4 {
                                return Err("\\u 转义缺 4 位十六进制".into());
                            }
                            let cp = u32::from_str_radix(&hex, 16)
                                .map_err(|_| format!("\\u 转义非法：{hex}"))?;
                            out.push(
                                char::from_u32(cp)
                                    .ok_or_else(|| format!("\\u 码点非法：{hex}"))?,
                            );
                            i += 4; // 4 位十六进制已消费（循环末再 +1 越过末位）
                        }
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

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn sign_event(key: &str, ev: &Event) -> String {
    // 签名串 v0.7.1（与 Python rust_swarm.verify_wal_signatures 约定一致）：
    // seq|type|from|to|round|ts|payload——seq 入签后才是不可变事件身份/顺序证明
    //（否则 global_seq 只是协调器内部 bookkeeping）。旧 WAL 签名串无 seq，不兼容。
    let msg = format!(
        "{}|{}|{}|{}|{}|{}|{}",
        ev.seq, ev.event_type, ev.from_id, ev.to_id, ev.round_no, ev.ts, ev.payload_json
    );
    hex32(&hmac_sha256(key.as_bytes(), msg.as_bytes()))
}

/// 轮末快照行的事件类型（B1 断点恢复）。复用 Event 行格式与签名约定，
/// Python verify_wal_signatures 按类型跳过计数但仍验签。
pub const SNAPSHOT_TYPE: &str = "__snapshot__";

/// 从 WAL 原始行文本切片 payload 原文（与 Python verify 同法：payload 是内嵌
/// JSON，签名与收件箱重建都必须用原文，parse→stringify 会丢浮点/键序保真）。
fn slice_raw_payload(line: &str) -> Option<String> {
    let marker = "\"payload\":";
    let pos = line.find(marker)? + marker.len();
    let raw = &line[pos..];
    let raw = raw.strip_suffix('}').unwrap_or(raw);
    Some(raw.to_string())
}

/// WAL seq/round 连续性破坏的一条明细（issue #354 P1-6）。
///
/// 判据逐字对齐 Python 侧 rust_swarm.verify_wal_signatures 的 continuity_breaks
/// （同一把尺子：快照行与事件行**共链**，缺失=跳号 / 重复或乱序；一处偏离一条明细、
/// 链以实际 seq+1 重同步、不级联连坐）。
#[derive(Debug, Clone)]
pub struct SeqBreak {
    /// 1 基行号（对齐 Python verify 的 line_no）
    pub line: usize,
    pub expected: u64,
    pub actual: u64,
    /// 跳号缺失 / 重复或乱序 / round 倒退 / 快照轮号重复或倒退
    pub kind: &'static str,
    pub row_type: String,
}

/// WAL 重放区完整性读数（issue #354 P1-6）。
///
/// **为什么必须有**：单条 HMAC 只锚「这一行没被改」，不锚「行的存在与顺序」——
/// 整行删除 / 行乱序对逐行验签**不可检**，于是丢行静默（审计面看起来一切正常）。
/// 加上 seq/round 单调连续性判据后，丢行从不可察觉变为**可察觉**。
///
/// **边界（只报不改）**：本判据不自行截断 WAL——截断权归「提交点 / 验签坏行」既有
/// 纪律（B1）。连续性破损是**审计信号**，经 stderr 与报告 wal_continuity 透出，
/// 由消费方（Python verify_wal_signatures / 运维）裁决；此处不新增破坏面。
#[derive(Debug, Clone, Default)]
pub struct WalContinuity {
    /// 明细（上限 CONTINUITY_DETAIL_CAP 条——病态 WAL 不得撑爆报告）
    pub detail: Vec<SeqBreak>,
    /// 破坏总数（大于等于 detail.len()；超上限后只计数不留明细）
    pub breaks: u64,
    /// 判据覆盖行数（已验证并进入重放的 WAL 行；分母，供判覆盖面）
    pub lines: u64,
}

impl WalContinuity {
    /// 连续性完好（零破坏）。
    pub fn ok(&self) -> bool {
        self.breaks == 0
    }
}

/// 记一条连续性破坏：总数恒加，明细有上限（超限只计数——报告不是坏 WAL 的镜像）。
fn note_break(
    c: &mut WalContinuity,
    line: usize,
    expected: u64,
    actual: u64,
    kind: &'static str,
    row_type: &str,
) {
    c.breaks += 1;
    if c.detail.len() < CONTINUITY_DETAIL_CAP {
        c.detail.push(SeqBreak {
            line,
            expected,
            actual,
            kind,
            row_type: row_type.to_string(),
        });
    }
}

/// 明细上限（超限只计数）：报告是给人/给消费方读的，不是坏 WAL 的镜像。
const CONTINUITY_DETAIL_CAP: usize = 64;

/// WAL 重放结果（B1）：恢复所需的全部内存状态。
struct WalReplay {
    /// 已完成轮数（最后一个快照行的轮号）；None=无快照（不可恢复，从轮 1 重跑）
    completed: Option<u64>,
    events: Vec<Event>,
    acks: HashSet<String>,
    inboxes: Inboxes,
    last_trust: HashMap<String, f64>,
    last_states: HashMap<String, serde_json_like::Value>,
    /// 验签通过的前缀行原文（恢复续跑前据此截断坏尾）
    kept_lines: Vec<String>,
    /// G4b：重放的路由事件计数（恢复后 global_seq 起点，保持单调）
    replayed_seq: u64,
    /// v0.7.1：重放中最大事件 seq（恢复后 event_seq 单调起点）
    max_event_seq: u64,
    /// 是否读到了 WAL 文件（区分「首跑」与「有 WAL 但零提交」——后者是坏 WAL，
    /// 2026-09-25 修复：审计留痕须归档而非清零）
    had_wal_file: bool,
    /// N109（v12 留档，批次58）：重放重建的实例消费水位——ACK 行 payload
    /// {"round","seq"} 的 seq 即在线 had_inbox 水位推进的同源记账（消费到的
    /// 最大全局 seq），取 per 实例最大值。同 WAL 重入/续跑据此播种，审计面
    /// 不再从空表起（违背 rust_swarm.py「watermarks 单调递增」契约的根因）。
    watermarks: HashMap<String, u64>,
    /// N109（v12 留档，批次58）：重放重建的 gossip 投递计数——gossip 路由行
    /// （(from,type) 命中 gossip 路由指纹、to 为具体目标）与在线 gossip_sent
    /// 记账同源同口径（含 N111 已留档的发送侧语义：末轮未投递消息照常计数，
    /// 重入幂等口径 = 与首跑报告一致）。歧义边界：同源同 type 同时配单播与
    /// gossip 路由的病理配置下，单播行会计入目标 gossip 计数（WAL 行格式
    /// 不区分两者，报文级甄别须协议扩展）。
    gossip_sent: HashMap<String, usize>,
    /// issue #354 P1-6：重放区的 seq/round 连续性读数（只报不改）
    continuity: WalContinuity,
}

/// 重放 WAL 重建状态（对照 langgraph 恢复语义：重建后走正常循环，无特殊路径）。
/// 完整性守卫：任何行 parse 失败或验签失败 → 停在该行（截断点），其前的行可信。
/// 单行 WAL → (Event, 原始 payload 字符串)；结构残缺返回 None（坏尾截断点）。
fn parse_event_line(line: &str) -> Option<(Event, String)> {
    let raw_payload = slice_raw_payload(line)?;
    let v = serde_json_like::parse(line).ok()?;
    let get_s = |k: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
    let ev = Event {
        seq: v.get("seq").and_then(|x| x.as_f64()).unwrap_or(0.0) as u64,
        ts: v.get("ts").and_then(|x| x.as_f64()).unwrap_or(0.0) as u64,
        from_id: get_s("from"),
        to_id: get_s("to"),
        event_type: get_s("type"),
        payload_json: raw_payload.clone(),
        round_no: v.get("round").and_then(|x| x.as_f64()).unwrap_or(0.0) as u64,
        level: v.get("level").and_then(|x| x.as_f64()).unwrap_or(0.0) as u8,
        hmac_hex: get_s("hmac"),
    };
    Some((ev, raw_payload))
}

/// 重放 WAL 重建状态（对照 langgraph 恢复语义：重建后走正常循环，无特殊路径）。
/// 完整性守卫：任何行 parse 失败或验签失败 → 停在该行（截断点），其前的行可信。
/// `gossip_fps`：gossip 路由指纹 (from_id, event_type) 集（调用方据 cfg.routes
/// 的 to_id=GOSSIP_TARGET 路由计算）——重放侧据此把路由行归类为 gossip 投递。
fn replay_wal(
    wal_path: &str,
    secret: &str,
    gossip_fps: &HashSet<(String, String)>,
) -> Result<WalReplay, String> {
    let mut rp = WalReplay {
        completed: None,
        events: Vec::new(),
        acks: HashSet::new(),
        inboxes: HashMap::new(),
        last_trust: HashMap::new(),
        last_states: HashMap::new(),
        kept_lines: Vec::new(),
        replayed_seq: 0,
        max_event_seq: 0,
        had_wal_file: false,
        watermarks: HashMap::new(),
        gossip_sent: HashMap::new(),
        continuity: WalContinuity::default(),
    };
    // issue #354 P0-2：**区分「文件不存在」与「文件损坏」**。
    //
    // 旧实现是 read_to_string 的「整文件一次性解码」，且把**所有** Err 一律当
    // 「无 WAL = 首跑」：文件存在但含非法 UTF-8 时（撕裂写落在多字节字符中间、
    // 断电残字节）整文件解码失败 → had_wal_file=false 且 completed=None ⇒
    // open_wal_for_run 走 File::create **原位清空**，已提交历史无痕销毁、连归档
    // 都没有（故障自愈退化成数据毁灭源）。
    //
    // 实测（修前，两个场景只差尾字节是否可解码）：
    //   · 合法快照+事件前缀 + 尾 0xFF 0xFE  ⇒ 前缀消失、无事件级留痕、无 .corrupt-*；
    //   · 同一前缀 + 尾是**合法 UTF-8** 的半行 ⇒ 前缀完好（正常 B1 截断）。
    // 故这里分三步：①文件不存在才算首跑；②存在但读不出 → fail-closed 返回 Err
    // （绝不自行清空）；③读了字节能解码多少算多少——**行级**容错，坏字节只作废
    // 其所在那一行（等价于半行/坏行 = 截断点），其前的合法行照常重建。
    let bytes = match std::fs::read(wal_path) {
        Ok(b) => b,
        // 文件不存在 = 首跑（唯一可当「无 WAL」的分支）
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(rp),
        // 存在但不可读（权限 / IO / 路径是目录）：损坏不得当成空 ⇒ 交调用方，
        // 由它按「不销毁现场」的路径处置
        Err(e) => {
            return Err(format!(
                "WAL 存在但不可读（issue #354 P0-2：损坏不得当成空，拒绝继续）: {wal_path}: {e}"
            ))
        }
    };
    rp.had_wal_file = true;
    // 按 b'\n' 切行 + 逐行 from_utf8：与 str::lines 同语义（剥尾 CR），但把
    // 「解码失败」的范围从整文件收窄到**单行**。行号（idx）与 str::lines 一致，
    // 故下游的提交点下标 / 截断逻辑逐位不变。
    let lines: Vec<Option<&str>> = bytes
        .split(|b| *b == b'\n')
        .map(|chunk| {
            let chunk = match chunk.last() {
                Some(b'\r') => &chunk[..chunk.len() - 1],
                _ => chunk,
            };
            std::str::from_utf8(chunk).ok()
        })
        .collect();
    // 第一遍：提交点 = 最后一个通过 HMAC 验签的快照行。
    // v0.6.1 修复：旧逻辑在事件行处做「超前轮截断」，而快照行 round 恒为
    // completed+1 → 快照被误伤截断，completed 永远停在 1，≥2 轮重入恒触发
    // 整段确定性重跑而非幂等聚合（重跑结果逐位一致，故 v0.6 全部测试未暴露）。
    // 快照 = 整轮持久化承诺：其前行（含快照与散事件）全部有效，其后散事件
    // （kill 落在快照写入前）按 B1 回滚——顺序流前缀性下只有「先扫提交点、
    // 再重建前缀」两遍扫描才正确，事件行自身无法预判后续是否有快照。
    let mut commit_idx: Option<usize> = None;
    for (idx, line) in lines.iter().enumerate() {
        let Some(line) = line else {
            break; // 非法 UTF-8 行（崩溃残留残字节）→ 提交点搜索止于此
        };
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Some((ev, _)) = parse_event_line(line) else {
            break; // 半行（崩溃残留）→ 提交点搜索止于此
        };
        if sign_event(secret, &ev) != ev.hmac_hex {
            break; // 尾部篡改/残缺 → 止于此
        }
        if ev.event_type == SNAPSHOT_TYPE {
            commit_idx = Some(idx);
        }
    }
    let Some(commit_idx) = commit_idx else {
        return Ok(rp); // 无合法快照 = 零提交 → 全回滚（B1）
    };
    // 第二遍：只重建提交点前缀（含快照行与其前散事件）
    // ── issue #354 P1-6：seq/round 单调连续性链（只报不改）──
    // 三个游标只在**通过验签并进入重放区**的行上步进（验签不过的行是截断点，
    // 其后的行本就不进重放区，不该参与本判据）。
    let mut expected_seq: Option<u64> = None;
    let mut prev_round: Option<u64> = None;
    let mut last_snap_round: Option<u64> = None;
    for (idx, line) in lines.iter().enumerate() {
        if idx > commit_idx {
            break; // 未提交尾部散事件 → 回滚截断（B1 重跑重做）
        }
        let Some(line) = line else {
            break; // 非法 UTF-8 行 → 截断点（同第一遍）
        };
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Some((ev, raw_payload)) = parse_event_line(line) else {
            break; // 理论不可达（第一遍已验），双检无害
        };
        if sign_event(secret, &ev) != ev.hmac_hex {
            break;
        }
        // P1-6：一行一判——链以实际 seq+1 重同步（不级联连坐），与 Python
        // verify_wal_signatures 的 continuity_breaks 同口径同粒度。
        if let Some(exp) = expected_seq {
            if ev.seq != exp {
                note_break(
                    &mut rp.continuity,
                    idx + 1,
                    exp,
                    ev.seq,
                    if ev.seq > exp { "跳号缺失" } else { "重复或乱序" },
                    &ev.event_type,
                );
            }
        }
        expected_seq = Some(ev.seq + 1);
        if let Some(pr) = prev_round {
            if ev.round_no < pr {
                note_break(
                    &mut rp.continuity,
                    idx + 1,
                    pr,
                    ev.round_no,
                    "round 倒退",
                    &ev.event_type,
                );
            }
        }
        prev_round = Some(ev.round_no);
        if ev.event_type == SNAPSHOT_TYPE {
            if let Some(lr) = last_snap_round {
                if ev.round_no <= lr {
                    note_break(
                        &mut rp.continuity,
                        idx + 1,
                        lr + 1,
                        ev.round_no,
                        "快照轮号重复或倒退",
                        &ev.event_type,
                    );
                }
            }
            last_snap_round = Some(ev.round_no);
        }
        rp.continuity.lines += 1;
        if ev.event_type == SNAPSHOT_TYPE {
            // 快照行：重建信任水位与终态；payload = {"trusts":{..},"states":{..}}
            if let Ok(p) = serde_json_like::parse(&raw_payload) {
                rp.completed = Some(ev.round_no);
                if let Some(serde_json_like::Value::Obj(trusts)) = p.get("trusts") {
                    for (id, t) in trusts {
                        if let Some(f) = t.as_f64() {
                            rp.last_trust.insert(id.clone(), f.clamp(0.0, 1.0));
                        }
                    }
                }
                if let Some(serde_json_like::Value::Obj(states)) = p.get("states") {
                    rp.last_states = states.clone();
                }
            }
        } else {
            if ev.event_type == "ACK" {
                rp.acks.insert(ev.hmac_hex.clone());
                // N109（批次58）：ACK payload {"round","seq"} 的 seq = 实例消费
                // 收件箱的水位（在线 had_inbox 推进的同源记账，:1045 写入面），
                // 取 per 实例最大值——重入/续跑据此播种 watermarks 审计面。
                if let Ok(p) = serde_json_like::parse(&raw_payload) {
                    if let Some(s) = p.get("seq").and_then(|x| x.as_f64()) {
                        let s = s as u64;
                        let wm = rp.watermarks.entry(ev.from_id.clone()).or_insert(0);
                        if s > *wm {
                            *wm = s;
                        }
                    }
                }
            } else if ev.to_id != "协调器" {
                // 路由事件：round 产生 → round+1 收件箱（与在线写入语义一致）。
                // G4b：重放计数保持 seq 全局单调（恢复后水位不断档）
                rp.replayed_seq += 1;
                rp.inboxes
                    .entry(ev.round_no + 1)
                    .or_default()
                    .entry(ev.to_id.clone())
                    .or_default()
                    .entry(ev.from_id.clone())
                    .or_default()
                    // 2026-09-25 修复 #2：push 追加——同轮同源多路由不覆盖
                    .push((raw_payload, rp.replayed_seq));
                // N109（批次58）：gossip 投递计数重建——(from,type) 命中 gossip
                // 路由指纹即 fan-out 投递行，与在线 gossip_sent 记账同源同口径
                // （发送侧语义含 N111 已留档的末轮照常计数，重入口径=与首跑
                // 报告一致；单播/gossip 同源同型病理配置的歧义见结构体注）。
                if gossip_fps.contains(&(ev.from_id.clone(), ev.event_type.clone()))
                    && ev.to_id != ev.from_id
                {
                    *rp.gossip_sent.entry(ev.to_id.clone()).or_insert(0) += 1;
                }
            }
        }
        rp.max_event_seq = rp.max_event_seq.max(ev.seq);
        rp.events.push(ev);
        rp.kept_lines.push(line.to_string());
    }
    Ok(rp)
}

/// WAL 恢复期进程排他锁（issue #354 P1-7）。
///
/// **缺陷**：两个 coordinator 对同一 WAL 并发恢复（同一 project 被两个进程拉起、
/// 或崩溃后运维与自愈自愈路径同时进场）时，旧实现既无锁、临时文件名又是**固定**的
/// {wal}.tmp ⇒ 两个进程操作的是同一个 inode：A 建(tmp)、B 建(O_TRUNC tmp)、两者
/// 交替写入 → rename 换入后 WAL 是两份内容的**交错混合**（半行/丢行），失败方还
/// 只把 Err 丢掉、现场静默。事件行各自有 HMAC，但交错混合后的行**过不了验签**
/// ——「已提交历史静默丢行」与「留痕自洽」同时被破坏。
///
/// **修法**：临界区（恢复重写 / 坏 WAL 归档 / 新建空 WAL）全程持本锁。锁 = 锁文件
/// create_new（系统调用级原子独占），持锁方写入 pid 与时刻供诊断，Drop 释放。
/// 等待上限 LOCK_WAIT_MS 到点即**报错退出**（fail-closed，绝不半写、绝不偷锁）；
/// 锁文件比 LOCK_STALE_MS 更旧时按「持锁进程已崩溃」处理（rename 移走再重建）。
///
/// **诚实边界（两条）**：
///   ① 过期锁的「判旧 → 移走」之间仍有 TOCTOU 窗口（他人可能在两次 stat 之间建了
///      新锁）。本仓口径是**窄窗 + 长阈值**（阈值远大于任何正常重写窗口）且移走前
///      二次 stat 复核；真要零窗口需平台级 flock（Windows LockFileEx），与
///      rust_runtime 的「零第三方依赖」约束冲突，故不在本件范围。
///   ② 锁只覆盖「恢复改写 / 归档 / 新建」临界区，**不覆盖整轮 append**。两个
///      coordinator 长期并行写同一 WAL 仍属协议外形态（append 交错、事件 seq 各自
///      编号）；本件堵的是其中**静默数据毁灭**的那条（并发重写把已提交历史写成
///      交错混合）。长期并行写需要单写者仲裁，另列。
struct WalLock {
    path: String,
}

/// 等待他人释放锁的上限（毫秒）：重写窗口是毫秒级，5s 足够在高负载/慢盘下退让。
const LOCK_WAIT_MS: u64 = 5_000;
/// 轮询间隔（毫秒）。
const LOCK_POLL_MS: u64 = 25;
/// 锁过期阈值（毫秒）：超过即视为持锁进程已崩溃（远大于任何正常重写窗口）。
const LOCK_STALE_MS: u64 = 120_000;

impl WalLock {
    /// 取锁（阻塞等待至多 LOCK_WAIT_MS，超时返回 Err——调用方据此 fail-closed）。
    fn acquire(wal_path: &str) -> Result<Self, String> {
        let path = format!("{wal_path}.lock");
        let deadline = now_ms() + LOCK_WAIT_MS;
        loop {
            match std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&path)
            {
                Ok(mut f) => {
                    // 锁内容只作诊断用（谁在什么时候持锁）；不参与判据
                    let _ = writeln!(f, "{} {}", std::process::id(), now_ms());
                    let _ = f.sync_all();
                    return Ok(WalLock { path });
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                    let broke = if lock_is_stale(&path) {
                        // 二次复核：两次 stat 之间他人可能已建了新锁（TOCTOU 窗），
                        // 复核仍为过期才移走——移走用 rename（原子），失败不动现场
                        let stale = format!("{path}.stale-{}", now_ms());
                        if lock_is_stale(&path) && std::fs::rename(&path, &stale).is_ok() {
                            let _ = std::fs::remove_file(&stale);
                            eprintln!("[swarm] 清理过期 WAL 锁（持锁进程已崩溃）：{path}");
                            true
                        } else {
                            false
                        }
                    } else {
                        false
                    };
                    if broke {
                        continue; // 立刻重试独占创建
                    }
                    if now_ms() >= deadline {
                        return Err(format!(
                            "WAL 排他锁等待超时（{LOCK_WAIT_MS}ms）：{path} 被另一进程持有——\
                             拒绝并发恢复重写（issue #354 P1-7：双 coordinator 并发重写同一 WAL \
                             会静默丢行；确认无进程在跑后可删除该锁文件重试）"
                        ));
                    }
                    std::thread::sleep(std::time::Duration::from_millis(LOCK_POLL_MS));
                }
                Err(e) => return Err(format!("WAL 排他锁创建失败（{path}）: {e}")),
            }
        }
    }
}

impl Drop for WalLock {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

/// 锁文件是否已过期（mtime 早于 LOCK_STALE_MS）。取不到 mtime 一律**不算**过期
/// ——宁可等待也不偷锁（偷锁 = 重新引入并发重写）。
fn lock_is_stale(path: &str) -> bool {
    std::fs::metadata(path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| now_ms().saturating_sub(d.as_millis() as u64) > LOCK_STALE_MS)
        .unwrap_or(false)
}

/// 恢复/首跑的 WAL 打开（B1 断点恢复）：
/// - 恢复模式（completed 有值）：好行经「临时文件 + fsync + rename」原子换入
///   （物理截断坏尾）→ append 续跑；
/// - 零提交（completed 无值）：B1 全回滚语义不变——从轮 1 重跑，开空 WAL。
///
/// 2026-09-25 修复（缺陷：WAL 恢复重写非原子 + 零提交整文件清零）：
/// 旧实现两分支均 File::create(O_TRUNC) 就地清零——① 恢复重写窗口内
/// 崩溃/断电/write Err 会不可逆丢失全部已 sync_all 的提交前缀；② 无合法
/// 快照（首行损坏/半行）时整文件清空重跑，单个坏行连带摧毁其后全部可独立
/// 验签的事件行（事件独立 HMAC 签名，审计留痕不可再生）。现改为：重写走
/// 临时文件原子替换（任何时点崩溃，wal_path 只有旧全量或新前缀，无半写
/// 中间态，std::fs::rename 同卷原子覆盖）；零提交时原 WAL 归档留痕后新开
/// 空文件，签名审计链可离线独立验签取证。
fn open_wal_for_run(
    wal_path: &str,
    completed: Option<u64>,
    kept_lines: &[String],
    had_wal_file: bool,
) -> Result<std::fs::File, String> {
    // issue #354 P1-7：整个「重写 / 归档 / 新建」临界区持进程排他锁——锁的
    // 生命周期比函数体长不行、比单个分支短也不行：三个分支都在改同一个文件，
    // 锁必须覆盖全部分支。取不到锁即 fail-closed 返回 Err（绝不在无锁下改写）。
    let _lock = WalLock::acquire(wal_path)?;
    if completed.is_some() {
        // 恢复模式：好行原子换入（物理截断坏尾）→ append 续跑
        rewrite_wal_atomic(wal_path, kept_lines)?;
        std::fs::OpenOptions::new()
            .append(true)
            .open(wal_path)
            .map_err(|e| format!("WAL 追加打开失败: {e}"))
    } else {
        // 零提交：坏 WAL 归档留痕（若有）→ 新开空 WAL 从轮 1 重跑
        if had_wal_file {
            archive_corrupt_wal(wal_path)?;
        }
        std::fs::File::create(wal_path).map_err(|e| format!("WAL 创建失败: {e}"))
    }
}

/// 好行前缀原子换入在役 WAL：写 <wal>.tmp.<pid> → flush → fsync → rename 覆盖。
/// 中途任何失败：清理临时文件后报错，原 WAL 逐字节不动（无半写窗口）。
///
/// issue #354 P1-7：临时文件名**含进程号**——旧实现的固定名 {wal}.tmp 在两个
/// coordinator 并发恢复时是同一个 inode（O_TRUNC 互相截断 + 交替写入），rename
/// 换入的 WAL 会是两份内容的交错混合。并发单位是**进程**（同进程内本函数只在
/// 恢复路径调用一次，无线程并发），故 pid 即够用的唯一性；也不含时间戳，便于
/// 单测用同一算式推算占位路径来注入「重写窗口故障」。
///
/// **前置**：调用方必须已持有 WalLock（见 open_wal_for_run）——本函数不自取锁，
/// 以免在持锁路径上自锁死。
fn rewrite_wal_atomic(wal_path: &str, kept_lines: &[String]) -> Result<(), String> {
    let tmp_path = format!("{wal_path}.tmp.{}", std::process::id());
    let attempt = || -> Result<(), String> {
        let mut f = std::fs::File::create(&tmp_path)
            .map_err(|e| format!("WAL 临时文件创建失败: {e}"))?;
        for line in kept_lines {
            f.write_all(line.as_bytes())
                .map_err(|e| format!("WAL 重写失败: {e}"))?;
            f.write_all(b"\n").map_err(|e| format!("WAL 重写失败: {e}"))?;
        }
        f.flush().map_err(|e| format!("WAL flush 失败: {e}"))?;
        f.sync_all().map_err(|e| format!("WAL sync 失败: {e}"))?;
        drop(f); // Windows：rename 覆盖前须关句柄
        std::fs::rename(&tmp_path, wal_path)
            .map_err(|e| format!("WAL 原子替换失败: {e}"))
    };
    if let Err(e) = attempt() {
        let _ = std::fs::remove_file(&tmp_path); // 失败清理，不留半成品 tmp
        return Err(e);
    }
    Ok(())
}

/// 零提交 WAL 归档（签名审计留痕不销毁）：rename 为 <wal>.corrupt-<毫秒时间戳>
/// （同名冲突递增后缀；宁可报错也不覆盖已存在归档）。
fn archive_corrupt_wal(wal_path: &str) -> Result<(), String> {
    let base = now_ms();
    for i in 0..1000u64 {
        let suffix = if i == 0 {
            base.to_string()
        } else {
            format!("{base}-{i}")
        };
        let archive = format!("{wal_path}.corrupt-{suffix}");
        if std::path::Path::new(&archive).exists() {
            continue;
        }
        return std::fs::rename(wal_path, &archive)
            .map_err(|e| format!("WAL 归档失败（{archive}）: {e}"));
    }
    Err("WAL 归档失败：候选名耗尽".into())
}

struct InstanceProc {
    spec: InstanceSpec,
    child: Child,
    stdin: BufWriter<std::process::ChildStdin>,
    /// v0.7.1：实例级持久 stdout 缓冲（BufReader 生命周期=进程生命周期）。
    /// 旧实现每轮临时 `BufReader::new(stdout)`：预读进内部缓冲、但未到行尾的
    /// 字节随 drop 丢失，pipe 中再也读不到——高负载/响应分片时表现为偶发
    /// 读取失败、卡死、实例死亡重启（低负载测试极易掩盖）。
    stdout: BufReader<std::process::ChildStdout>,
}

impl InstanceProc {
    fn spawn(exe: &str, spec: &InstanceSpec, pbc_path: Option<&str>) -> Result<Self, String> {
        let mut cmd = Command::new(exe);
        cmd.arg("--serve");
        // 独立形态（未启用 embed）子进程不持有嵌入字节码，须转发 --pbc 路径
        if let Some(p) = pbc_path {
            cmd.arg("--pbc").arg(p);
        }
        let mut child = cmd
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("启动实例 {} 失败: {e}", spec.id))?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "无法获取实例 stdin".to_string())?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "无法获取实例 stdout".to_string())?;
        Ok(InstanceProc {
            spec: spec.clone(),
            child,
            stdin: BufWriter::new(stdin),
            stdout: BufReader::new(stdout),
        })
    }

    /// 执行一轮：请求 = 初始环境（symbols/trust/condition_space）+ 收件箱。
    /// env：verifier 复算的输入覆盖（primary 的 symbols/trust）——replay
    /// envelope 必须是完整执行输入，只复制收件箱而保留自身环境不是重放。
    fn run_round(
        &mut self,
        round_no: u64,
        inbox: &[(String, String)],
        env: Option<(&str, f64)>,
    ) -> Result<serde_json_like::Value, String> {
        let symbols_json = env
            .map(|(s, _)| s.to_string())
            .unwrap_or_else(|| self.spec.symbols_json.clone());
        let trust = env.map(|(_, t)| t).unwrap_or(self.spec.trust);
        let mut symbols_parts: Vec<String> = Vec::new();
        // 每轮都带初始符号（VM 符号表不跨轮持久——每轮是完整环境；
        // 跨轮传递的数据只能走消息，这正是消息传递模型的语义）
        if !symbols_json.is_empty() {
            symbols_parts.push(format!("\"初始符号\":{}", symbols_json));
        }
        if !inbox.is_empty() {
            // 2026-09-25 修复 #2：收件箱按 (来源,载荷) 平铺逐条注入——调用方
            // 已按来源稳定排序（同源内保持全局事件序），同轮同源多条路由
            // 逐条可见，不再只剩最后一条。
            // N243（2026-10-05）：收件箱原以 JSON **数组**形态注入，而 serve 侧
            // to_vm_value 对 List/Obj 落 `_ => None` 臂被静默跳过——符号「收件箱」
            // 从未进实例 VM 符号表（程序一引用即「名实不符」），WAL/ACK/水位却
            // 照记已投递，载荷只完整留在 WAL（留痕与实际投递不符）。
            // 改为按 condition_space 同口径（见下方 cs_part）用 escape 把数组
            // 序列化成 JSON **文本**注入：serve 走 Str 臂，VM 值模型（仅
            // Null/Bool/Int/Float/Str）无需扩展即可承载，载荷逐字节保留在符号内。
            // 内层 from 同步 escape：收件箱此刻已是「给人/程序再解析的 JSON 文本」，
            // 来源名含引号/反斜杠时不再破坏内层结构（此前裸露插入只在数组形态下
            // 表现为整条请求 JSON 非法）。
            let msgs: Vec<String> = inbox
                .iter()
                .map(|(from, payload)| {
                    format!(
                        "{{\"from\":\"{}\",\"payload\":{}}}",
                        serde_json_like::escape(from),
                        payload
                    )
                })
                .collect();
            let inbox_json = format!("[{}]", msgs.join(","));
            symbols_parts.push(format!(
                "\"收件箱\":\"{}\"",
                serde_json_like::escape(&inbox_json)
            ));
            symbols_parts.push(format!("\"已收消息数\":{}", inbox.len()));
        }
        // G-R2 条件空间卡 → 实例输入（v0.7.1 执行链接通）：serve 侧注入 VM
        // 预定义符号（条件空间/观测位置/观测工具/时间窗口/存在约束），程序内
        // 「若 条件空间 为 X」真实路由——此前卡只进 cfg/WAL/报告（metadata）。
        let cs_part = match &self.spec.condition_space {
            Some(cs) => format!(
                ",\"condition_space\":{{\"space_id\":\"{}\",\"observation_position\":\"{}\",\"observation_tool\":\"{}\",\"time_window\":\"{}\",\"existence_constraint\":\"{}\"}}",
                serde_json_like::escape(&cs.space_id),
                serde_json_like::escape(&cs.observation_position),
                serde_json_like::escape(&cs.observation_tool),
                serde_json_like::escape(&cs.time_window),
                serde_json_like::escape(&cs.existence_constraint)
            ),
            None => String::new(),
        };
        let req = format!(
            "{{\"symbols\":{{{}}},\"trust\":{}{},\"round_no\":{}}}\n",
            symbols_parts.join(","),
            trust,
            cs_part,
            round_no
        );
        self.stdin
            .write_all(req.as_bytes())
            .map_err(|e| format!("实例 {} 管道断裂: {e}", self.spec.id))?;
        self.stdin
            .flush()
            .map_err(|e| format!("实例 {} flush 失败: {e}", self.spec.id))?;
        let mut line = String::new();
        self.stdout
            .read_line(&mut line)
            .map_err(|e| format!("实例 {} 读取失败: {e}", self.spec.id))?;
        serde_json_like::parse(line.trim())
            .map_err(|e| format!("实例 {} 终态非法: {e}", self.spec.id))
    }
}

impl Drop for InstanceProc {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// 蜂群执行：rounds 轮，每轮各实例执行一次；路由表决定跨实例消息
/// 蜂群执行：rounds 轮，每轮各实例执行一次；路由表决定跨实例消息。
///
/// `pbc_path`：转发给实例子进程的字节码路径（独立形态必填；
/// 生成项目形态的子进程自带嵌入字节码，可为 `None`）。
pub fn run_swarm(
    exe: &str,
    cfg: &SwarmConfig,
    rounds: u64,
    wal_path: &str,
    pbc_path: Option<&str>,
) -> Result<SwarmReport, String> {
    // G4a：拓扑角色推导（显式声明 role 仅在未指定拓扑时保留——向后兼容）。
    // 推导后的实例表供 spawn 与聚合使用；参数 cfg 保持不可变引用。
    let mut specs_derived: Vec<InstanceSpec> = cfg.instances.clone();
    for (i, spec) in specs_derived.iter_mut().enumerate() {
        spec.role = derive_role(&cfg.topology, i, &spec.role)?;
        // G-R2：条件空间卡随 spec 下发（run_round 请求携带 → VM 符号注入）
        spec.condition_space = cfg.condition_space.clone();
    }

    // N109（批次58）：gossip 路由指纹 (from,type)——重放侧把路由行归类为
    // gossip 投递的依据（to_id=GOSSIP_TARGET 的路由 fan-out 出的目标行）。
    let gossip_fps: HashSet<(String, String)> = cfg
        .routes
        .iter()
        .filter(|r| r.to_id == GOSSIP_TARGET)
        .map(|r| (r.from_id.clone(), r.event_type.clone()))
        .collect();
    // B1 断点恢复：先重放 WAL。有快照 → 从快照轮+1 续跑（append）；
    // 无快照 → 维持旧行为从轮 1 截断重跑；坏尾（半行/篡改）在重放处停住。
    let replay = replay_wal(wal_path, &cfg.shared_secret, &gossip_fps)?;
    // issue #354 P1-6：连续性破损**必须透出**——旧实现对此完全静默，丢行/乱序
    // 「不可察觉」正是缺陷本体。stderr 一行 + 报告 wal_continuity 明细双出口。
    if replay.continuity.breaks > 0 {
        eprintln!(
            "[swarm] WAL seq/round 连续性中断 {} 处（重放 {} 行，issue #354 P1-6）——已提交区\
             可能丢行/乱序；本次照常重放（只报不改，截断权归提交点/验签坏行），明细见报告 wal_continuity",
            replay.continuity.breaks, replay.continuity.lines
        );
    }
    let mut all_events: Vec<Event> = replay.events;
    let mut acks: HashSet<String> = replay.acks;
    let mut inboxes: Inboxes = replay.inboxes;
    let mut last_states: HashMap<String, serde_json_like::Value> = replay.last_states;
    let mut last_trust: HashMap<String, f64> = replay.last_trust;
    let start_round = replay.completed.map_or(1, |k| k + 1);
    // G3a：每实例轮次终态序列（在线窗口 = 本次执行的轮次），供健康评分
    let mut round_outcomes: HashMap<String, Vec<Option<bool>>> = HashMap::new();
    // G3b：gossip 水位记账（实例 → 实收 gossip 消息数）——N109：从重放重建
    // 播种，续跑只累加新会话段（旧实现从空表起，恢复前窗口丢失、全完成重入
    // 整面归零）。
    let mut gossip_sent: HashMap<String, usize> = replay.gossip_sent;
    // G4b：全局消息 seq（单调）与实例消费水位
    let mut global_seq: u64 = replay.replayed_seq;
    // v0.7.1：全局事件 seq（进签名串的事件身份；恢复从重放行取单调起点）
    let mut event_seq: u64 = replay.max_event_seq;
    // N109（批次58）：消费水位从重放重建播种（ACK payload seq 同源记账）——
    // 在线窗口只增不减（:965 推进带 > 守卫），单调契约跨重入保持。
    let mut watermarks: HashMap<String, u64> = replay.watermarks;
    // G5：死亡实例集合（重试仍失败 → 退场，蜂群继续）
    let mut dead: HashSet<String> = HashSet::new();
    // G-R1 反思触发器状态（§5.4 蜂群版触发条件的跨轮记账）
    let mut reflect_error_streak: u32 = 0; // 连续含 error 终态的轮数
    let mut reflect_t_avg_prev: Option<f64> = None; // 上一轮 T_avg
    let mut reflect_t_avg_down: u32 = 0; // T_avg 连续下降轮数
    let mut reflect_dead_prev: usize = 0; // 上一轮 dead 数（场景变化触发）
    // 维生权限边界（荣 2026-09-13 裁定）：维生系统只面对重大分歧/错误介入，
    // 默认作为安全服务端——修正信号仅记录+透出（P2 观察级），不自动改路由；
    // P0/P1 介入留待真实重大分歧场景，且不可被外部输入覆盖（§3.16）。
    // G-R3 protocol 拓扑：verifier 子进程重放 primary 输入逐位复算终态。
    let protocol_mode = cfg.topology == "protocol";
    let primary_id = specs_derived.first().map(|s| s.id.clone()).unwrap_or_default();
    let verifier_id = specs_derived.get(1).map(|s| s.id.clone()).unwrap_or_default();
    // v0.7.1：verifier 复算的输入覆盖 = primary 完整执行输入（同 spec 才是 replay；
    // 旧实现 verifier 用自身 spec+primary 收件箱，spec 不同则复算无对照意义）
    let primary_symbols_json = specs_derived
        .first()
        .map(|s| s.symbols_json.clone())
        .unwrap_or_default();
    let primary_trust = specs_derived.first().map(|s| s.trust).unwrap_or(0.0);
    let mut recalc_checked: u64 = 0;
    let mut recalc_mismatches: u64 = 0;

    if replay.completed.is_some() && start_round > rounds {
        // 目标轮数已全部持久化完成：不重启实例直接聚合（恢复幂等口径）。
        // watermarks/gossip 由重放从 WAL 重建（N109，批次58：ACK payload seq /
        // gossip 路由行），审计面与首跑一致不再归零；本会话无在线执行窗口 →
        // round_outcomes 空 → health 维持空对象（在线窗口口径，逐轮终态质量
        // 未持久化，参与性重建会伪造 success_rate——G5「不伪造终态」纪律）。
        return Ok(aggregate_report(
            cfg,
            specs_derived,
            rounds,
            all_events,
            acks,
            last_states,
            HashMap::new(),
            gossip_sent,
            watermarks,
            global_seq,
            recalc_checked,
            recalc_mismatches,
            replay.continuity,
        ));
    }

    let mut wal =
        open_wal_for_run(wal_path, replay.completed, &replay.kept_lines, replay.had_wal_file)?;

    let mut procs: Vec<InstanceProc> = Vec::new();
    for spec in &specs_derived {
        procs.push(InstanceProc::spawn(exe, spec, pbc_path)?);
    }

    for round in start_round..=rounds {
        // 本轮各实例收到的消息（上一轮路由产出）
        let round_inboxes = inboxes.remove(&round).unwrap_or_default();
        let mut new_events: Vec<Event> = Vec::new();
        let mut error_instances: Vec<String> = Vec::new(); // G-R1：本轮 error 终态实例
        let mut primary_state_str: Option<String> = None; // G-R3：primary 终态归一基准
        // G-R3：verifier 本轮重放 primary 输入（复算）。
        // 2026-09-25 修复 #1：verifier 自身收件箱不再顺延——旧实现每轮把自身
        // 收件箱搬进下一轮，下一轮又原样搬再下一轮，直至 rounds+1 随蜂群
        // 结束消亡（消息从未投递、从未 ACK、水位永不推进；注释「顺延一轮
        // 不丢失」与实现矛盾）。改为到达轮即消费记账：载荷不进复算执行
        // 输入（混入会破坏逐位复算），但计入 ACK 与消费水位（见下方
        // own_ack_seq_max）。
        let primary_inbox = if protocol_mode {
            round_inboxes.get(&primary_id).cloned().unwrap_or_default()
        } else {
            Default::default()
        };
        // —— B2 超步（BSP compute 阶段）：轮内实例并行执行 ——
        // 安全性论证：收件箱只来自上一轮路由，轮内实例互不依赖；
        // 一实例一线程一管道（&mut 独占借用），无共享可变状态。
        // 屏障 = scope 退出时 join 收齐——收齐前任何写入不进入下一阶段。
        // G5：死亡实例本轮跳过（outcomes 记 None，uptime 降）；存活实例
        //     管道断裂时同线程重建进程重跑该轮（轮次号幂等：每轮完整环境）。
        let round_out: Vec<RoundOutcome> =
            std::thread::scope(|s| {
                let handles: Vec<_> = procs
                    .iter_mut()
                    .map(|p| {
                        if dead.contains(&p.spec.id) {
                            return None;
                        }
                        let is_verifier =
                            protocol_mode && p.spec.id == verifier_id && !primary_id.is_empty();
                        let inbox_raw = if is_verifier {
                            primary_inbox.clone()
                        } else {
                            round_inboxes
                                .get(&p.spec.id)
                                .cloned()
                                .unwrap_or_default()
                        };
                        // 2026-09-25 修复 #2：收件箱平铺为 (来源,载荷) 序列——
                        // 同轮同源多条路由逐条保留（旧实现以来源为单值 key，
                        // 第二条 insert 覆盖第一条，载荷静默丢弃而 WAL 两条
                        // 事件均已签名落盘）。按来源稳定排序（同源内保持全局
                        // 事件序）；单路由场景与旧输出逐字节一致。
                        let mut inbox: Vec<(String, String)> = Vec::new();
                        for (from, items) in &inbox_raw {
                            for (payload, _) in items {
                                inbox.push((from.clone(), payload.clone()));
                            }
                        }
                        inbox.sort_by(|a, b| a.0.cmp(&b.0));
                        // 2026-09-25 修复 #1：verifier 自身收件箱到达轮即消费记账
                        // （计入 ACK 与水位）；载荷不进上面的复算执行输入。
                        let own_ack_seq_max = if is_verifier {
                            round_inboxes
                                .get(&verifier_id)
                                .and_then(|m| {
                                    m.values()
                                        .flat_map(|items| items.iter().map(|(_, s)| *s))
                                        .max()
                                })
                                .unwrap_or(0)
                        } else {
                            0
                        };
                        let has_inbox = !inbox.is_empty() || own_ack_seq_max > 0;
                        let max_seq = inbox_raw
                            .values()
                            .flat_map(|items| items.iter().map(|(_, s)| *s))
                            .max()
                            .unwrap_or(0)
                            .max(own_ack_seq_max);
                        // v0.7.1：verifier 以 primary 完整执行输入复算（replay envelope）。
                        // env 为 Copy（借用 primary 输入），闭外构造避免 move verifier_id。
                        let env = if is_verifier {
                            Some((primary_symbols_json.as_str(), primary_trust))
                        } else {
                            None
                        };
                        Some(s.spawn(move || {
                            let attempt = p
                                .run_round(round, &inbox, env)
                                .map(|st| (st, has_inbox, max_seq));
                            match attempt {
                                ok @ Ok(_) => ok,
                                Err(pipe_err) => {
                                    // G5 容错：管道断裂 → 重建实例进程重试一次。
                                    // 幂等性：每轮从完整环境起算（符号表不跨轮持久），
                                    // 重跑同一轮次不产生副作用累积。
                                    eprintln!(
                                        "实例 {} 轮 {} 管道异常（{pipe_err}），重建重试",
                                        p.spec.id, round
                                    );
                                    *p = InstanceProc::spawn(exe, &p.spec, pbc_path)?;
                                    p.run_round(round, &inbox, env)
                                        .map(|st| (st, has_inbox, max_seq))
                                }
                            }
                        }))
                    })
                    .collect();
                handles
                    .into_iter()
                    .map(|h| {
                        h.map(|j| j.join().unwrap_or_else(|_| Err("实例线程 panic".into())))
                    })
                    .collect()
            });
        // —— 屏障后（BSP apply 阶段）：按实例声明序处理，确定性保持 ——
        for (p, out) in procs.iter_mut().zip(round_out) {
            let out = match out {
                Some(o) => o,
                None => {
                    // G5：死亡实例本轮缺失（uptime 降，不伪造终态）
                    round_outcomes
                        .entry(p.spec.id.clone())
                        .or_default()
                        .push(None);
                    continue;
                }
            };
            let (st, had_inbox, inbox_max_seq) = match out {
                Ok(v) => v,
                Err(e) => {
                    // G5：重试仍失败 → 实例死亡退场；信任曲线沿用语义与此对齐
                    eprintln!("实例 {} 重试仍失败（{e}），标记 dead 退场", p.spec.id);
                    dead.insert(p.spec.id.clone());
                    round_outcomes
                        .entry(p.spec.id.clone())
                        .or_default()
                        .push(None);
                    continue;
                }
            };
            // G4b：水位推进（最后 ACK 的收件箱消息 seq）
            if had_inbox {
                let wm = watermarks.entry(p.spec.id.clone()).or_insert(0);
                if inbox_max_seq > *wm {
                    *wm = inbox_max_seq;
                }
            }
            last_states.insert(p.spec.id.clone(), st.clone());
            // G3a：记录本轮终态（error 终态对象含 "error" 键 → Some(false)）
            let has_error = st.get("error").is_some();
            round_outcomes
                .entry(p.spec.id.clone())
                .or_default()
                .push(Some(!has_error));
            // G-R1：本轮 error 终态实例登记（触发器用）
            if has_error {
                error_instances.push(p.spec.id.clone());
            }
            // G-R3：verifier 逐位复算 primary 终态（真实子代理执行——verifier
            // 子进程重放 primary 的本轮输入，确定性 VM 下同输入必同终态）。
            let is_primary = protocol_mode && p.spec.id == primary_id;
            let is_verifier = protocol_mode && p.spec.id == verifier_id;
            if is_primary {
                primary_state_str = Some(serde_json_like::stringify(&st));
            }
            if is_verifier {
                if let Some(ps) = &primary_state_str {
                    recalc_checked += 1;
                    let vs = serde_json_like::stringify(&st);
                    if vs != *ps {
                        recalc_mismatches += 1;
                        // 复算不一致 = 重大分歧（P1 响应级，维生边界内）：
                        // 修正信号 level=1 记录+透出，终态仍以 primary 为准（verifier 仅复核）
                        eprintln!(
                            "G-R3 复算不一致：verifier 轮 {} 终态与 primary 不符（P1）",
                            round
                        );
                        event_seq += 1;
                        let mut sig = Event {
                            seq: event_seq,
                            ts: now_ms(),
                            from_id: "协调器".into(),
                            to_id: "协调器".into(),
                            event_type: "修正信号".into(),
                            payload_json: format!(
                                "{{\"round\":{},\"级别\":\"P1\",\"类型\":\"复算不一致\",\"verifier\":\"{}\"}}",
                                round,
                                serde_json_like::escape(&p.spec.id)
                            ),
                            round_no: round,
                            level: 1,
                            hmac_hex: String::new(),
                        };
                        sig.hmac_hex = sign_event(&cfg.shared_secret, &sig);
                        new_events.push(sig);
                    }
                }
            }
            // 信任提交（防操纵：0-1 夹取；同轮同实例由聚合器去重）。
            // error 终态无 trust 字段 → 沿用上一轮值（实例故障不推平信任曲线）
            let prev_t = last_trust
                .get(&p.spec.id)
                .cloned()
                .unwrap_or(p.spec.trust.clamp(0.0, 1.0));
            let t = st
                .get("trust")
                .and_then(|x| x.as_f64())
                .unwrap_or(prev_t)
                .clamp(0.0, 1.0);
            last_trust.insert(p.spec.id.clone(), t);
            // ACK 事件：实例收到收件箱 → 回执
            if had_inbox {
                event_seq += 1;
                let ev = Event {
                    seq: event_seq,
                    ts: now_ms(),
                    from_id: p.spec.id.clone(),
                    to_id: "协调器".into(),
                    event_type: "ACK".into(),
                    // G4b：ACK 携带消费水位（payload 进签名串，自动受 HMAC 保护）
                    payload_json: format!("{{\"round\":{},\"seq\":{}}}", round, inbox_max_seq),
                    round_no: round,
                    level: 0,
                    hmac_hex: String::new(),
                };
                let mut ev = ev;
                ev.hmac_hex = sign_event(&cfg.shared_secret, &ev);
                acks.insert(ev.hmac_hex.clone());
                new_events.push(ev);
            }
            // 路由产出：from=p.spec.id 的路由 → 目标实例下一轮收件箱
            for r in &cfg.routes {
                if r.from_id == p.spec.id {
                    let payload = r.payload_json.replace("@trust", &format!("{t}"));
                    // G3b：to_id="*" = gossip 广播（fan-out 至除源外全部实例）
                    let targets: Vec<String> = if r.to_id == GOSSIP_TARGET {
                        cfg.instances
                            .iter()
                            .map(|s| s.id.clone())
                            .filter(|id| *id != p.spec.id)
                            .collect()
                    } else {
                        vec![r.to_id.clone()]
                    };
                    for to_id in targets {
                        global_seq += 1;
                        event_seq += 1;
                        let ev = Event {
                            seq: event_seq,
                            ts: now_ms(),
                            from_id: p.spec.id.clone(),
                            to_id: to_id.clone(),
                            event_type: r.event_type.clone(),
                            payload_json: payload.clone(),
                            round_no: round,
                            level: r.level,
                            hmac_hex: String::new(),
                        };
                        let mut ev = ev;
                        ev.hmac_hex = sign_event(&cfg.shared_secret, &ev);
                        // 2026-09-25 修复 #2：push 追加而非 insert 覆盖——
                        // 同轮同源第二条路由不再丢弃第一条载荷。
                        inboxes
                            .entry(round + 1)
                            .or_default()
                            .entry(ev.to_id.clone())
                            .or_default()
                            .entry(p.spec.id.clone())
                            .or_default()
                            .push((payload.clone(), global_seq));
                        if r.to_id == GOSSIP_TARGET {
                            *gossip_sent.entry(to_id).or_insert(0) += 1;
                        }
                        new_events.push(ev);
                    }
                }
            }
        }
        // WAL 落盘（append-only）· B1 纪律：事件行先 durable（flush），
        // 轮末快照后 durable（sync_all）——快照永不先于产生它的写入落盘。
        for ev in &new_events {
            let line = format!(
                "{{\"seq\":{},\"ts\":{},\"from\":\"{}\",\"to\":\"{}\",\"type\":\"{}\",\"round\":{},\"level\":{},\"hmac\":\"{}\",\"payload\":{}}}\n",
                ev.seq,
                ev.ts,
                serde_json_like::escape(&ev.from_id),
                serde_json_like::escape(&ev.to_id),
                serde_json_like::escape(&ev.event_type),
                ev.round_no,
                ev.level,
                ev.hmac_hex,
                ev.payload_json
            );
            wal.write_all(line.as_bytes())
                .map_err(|e| format!("WAL 写入失败: {e}"))?;
        }
        wal.flush().map_err(|e| format!("WAL flush 失败: {e}"))?;
        // G-R1 反思触发器（§5.4 蜂群版）：任一条件命中 → 产出修正信号事件。
        // 维生边界：修正信号仅记录+透出（P2 观察级），不自动改路由（见函数头裁定注）。
        let mut reflect_reasons: Vec<String> = Vec::new();
        if round % 100 == 0 {
            reflect_reasons.push("定期方向性自检（每100轮，§3.10步骤8）".into());
        }
        if !error_instances.is_empty() {
            reflect_error_streak += 1;
            if reflect_error_streak >= 2 {
                reflect_reasons.push(format!(
                    "error 终态连续 {} 轮（实例：{}）",
                    reflect_error_streak,
                    error_instances.join("、")
                ));
            }
        } else {
            reflect_error_streak = 0;
        }
        // T_avg 即时均值（趋势触发用；权威聚合在轮末 aggregate_report）
        let t_now: f64 = if last_trust.is_empty() {
            0.0
        } else {
            last_trust.values().sum::<f64>() / last_trust.len() as f64
        };
        if let Some(prev) = reflect_t_avg_prev {
            if t_now < prev - 1e-9 {
                reflect_t_avg_down += 1;
                if reflect_t_avg_down >= 3 {
                    reflect_reasons.push(format!("T_avg 连续 {} 轮下降", reflect_t_avg_down));
                }
            } else {
                reflect_t_avg_down = 0;
            }
        }
        reflect_t_avg_prev = Some(t_now);
        if dead.len() != reflect_dead_prev {
            reflect_reasons
                .push(format!("实例退场场景变化（dead {}→{}）", reflect_dead_prev, dead.len()));
            reflect_dead_prev = dead.len();
        }
        if !reflect_reasons.is_empty() {
            let sig_payload = serde_json_like::stringify(&serde_json_like::Value::List(
                reflect_reasons
                    .iter()
                    .map(|r| serde_json_like::Value::Str(r.clone()))
                    .collect(),
            ));
            event_seq += 1;
            let mut sig = Event {
                seq: event_seq,
                ts: now_ms(),
                from_id: "协调器".into(),
                to_id: "协调器".into(),
                event_type: "修正信号".into(),
                payload_json: sig_payload,
                round_no: round,
                level: 2, // P2 观察级（维生边界：仅记录+透出）
                hmac_hex: String::new(),
            };
            sig.hmac_hex = sign_event(&cfg.shared_secret, &sig);
            let sig_line = format!(
                "{{\"seq\":{},\"ts\":{},\"from\":\"{}\",\"to\":\"{}\",\"type\":\"{}\",\"round\":{},\"level\":{},\"hmac\":\"{}\",\"payload\":{}}}\n",
                sig.seq,
                sig.ts,
                serde_json_like::escape(&sig.from_id),
                serde_json_like::escape(&sig.to_id),
                serde_json_like::escape(&sig.event_type),
                sig.round_no,
                sig.level,
                sig.hmac_hex,
                sig.payload_json
            );
            wal.write_all(sig_line.as_bytes())
                .map_err(|e| format!("修正信号写入失败: {e}"))?;
            all_events.push(sig);
        }
        // 轮末快照行：复用事件行格式与签名约定（Python verify 按类型跳过计数仍验签）。
        // payload = {"trusts":{...},"states":{...}}——恢复时重建信任水位与终态。
        let trusts_parts: Vec<String> = {
            let mut ids: Vec<&String> = cfg.instances.iter().map(|s| &s.id).collect();
            ids.sort();
            ids.iter()
                .filter_map(|id| {
                    last_trust
                        .get(*id)
                        .map(|t| format!("\"{}\":{t}", serde_json_like::escape(id)))
                })
                .collect()
        };
        let states_parts: Vec<String> = {
            let mut ids: Vec<&String> = last_states.keys().collect();
            ids.sort();
            ids.iter()
                .map(|id| {
                    format!(
                        "\"{}\":{}",
                        serde_json_like::escape(id),
                        serde_json_like::stringify(&last_states[*id])
                    )
                })
                .collect()
        };
        // G-R2：条件空间 space_id 随快照持久（切换日志不可遗忘的载体；无卡则省字段）
        let cs_field = match &cfg.condition_space {
            Some(cs) => format!(",\"cs\":\"{}\"", serde_json_like::escape(&cs.space_id)),
            None => String::new(),
        };
        event_seq += 1;
        let mut snap = Event {
            seq: event_seq,
            ts: now_ms(),
            from_id: "协调器".into(),
            to_id: "协调器".into(),
            event_type: SNAPSHOT_TYPE.into(),
            payload_json: format!(
                "{{\"trusts\":{{{}}},\"states\":{{{}}}{}}}",
                trusts_parts.join(","),
                states_parts.join(","),
                cs_field
            ),
            round_no: round,
            level: 0,
            hmac_hex: String::new(),
        };
        snap.hmac_hex = sign_event(&cfg.shared_secret, &snap);
        let snap_line = format!(
            "{{\"seq\":{},\"ts\":{},\"from\":\"{}\",\"to\":\"{}\",\"type\":\"{}\",\"round\":{},\"level\":{},\"hmac\":\"{}\",\"payload\":{}}}\n",
            snap.seq,
            snap.ts,
            serde_json_like::escape(&snap.from_id),
            serde_json_like::escape(&snap.to_id),
            serde_json_like::escape(&snap.event_type),
            snap.round_no,
            snap.level,
            snap.hmac_hex,
            snap.payload_json
        );
        wal.write_all(snap_line.as_bytes())
            .map_err(|e| format!("WAL 快照写入失败: {e}"))?;
        all_events.extend(new_events);
        all_events.push(snap);
        wal.sync_all().map_err(|e| format!("WAL sync 失败: {e}"))?;
    }
    // 实例退场
    drop(procs);
    Ok(aggregate_report(
        cfg,
        specs_derived,
        rounds,
        all_events,
        acks,
        last_states,
        round_outcomes,
        gossip_sent,
        watermarks,
        global_seq,
        recalc_checked,
        recalc_mismatches,
        replay.continuity,
    ))
}

/// 信任聚合 + 健康评分 + gossip 对账 + 报告组装
#[allow(clippy::too_many_arguments)] // 聚合收口：各状态均为必需，不为凑参数上限重构
fn aggregate_report(
    cfg: &SwarmConfig,
    specs: Vec<InstanceSpec>,
    rounds: u64,
    events: Vec<Event>,
    acks: HashSet<String>,
    last_states: HashMap<String, serde_json_like::Value>,
    round_outcomes: HashMap<String, Vec<Option<bool>>>,
    gossip_sent: HashMap<String, usize>,
    watermarks: HashMap<String, u64>,
    global_seq: u64,
    recalc_checked: u64,
    recalc_mismatches: u64,
    wal_continuity: WalContinuity,
) -> SwarmReport {    // G3a 健康评分：从轮次终态序列统计（在线窗口口径）
    // G3c：gossip 覆盖率接入 integrity（对账基准 = 最大实收数）
    let weights = HealthWeights::default();
    // v0.6.1 完整通路：事件流逐条重验签名，统计每实例相关事件的验签失败
    // 数/总数（归属 = from_id；快照行不计入事件口径，与 Python verify 一致）。
    // 单机在线自签自验恒过、重放事件已过坏尾守卫 → verify_fail 恒 0，
    // integrity 数值与 v0.6 等价（零回归）；跨机/直接注入事件流场景验签
    // 失败真实降级 integrity——数据通路自此接通，不再硬编码 (0, 1)。
    let mut verify_fail: HashMap<String, usize> = HashMap::new();
    let mut event_total: HashMap<String, usize> = HashMap::new();
    for ev in &events {
        if ev.event_type == SNAPSHOT_TYPE {
            continue;
        }
        *event_total.entry(ev.from_id.clone()).or_insert(0) += 1;
        if sign_event(&cfg.shared_secret, ev) != ev.hmac_hex {
            *verify_fail.entry(ev.from_id.clone()).or_insert(0) += 1;
        }
    }
    let gossip_base = gossip_sent.values().copied().max().unwrap_or(0);
    let mut health: HealthReport = HashMap::new();
    for spec in &specs {
        let outcomes = round_outcomes.get(&spec.id).cloned().unwrap_or_default();
        if outcomes.is_empty() {
            continue;
        }
        let coverage = if gossip_base == 0 {
            1.0
        } else {
            match gossip_sent.get(&spec.id) {
                // gossip 目标：按实收/基准覆盖降级
                Some(c) => (*c as f64 / gossip_base as f64).min(1.0),
                // G5 修正：无键 = 非 gossip 目标（纯源/无入边），无缺收语义 → 1.0。
                // （此前误判 coverage=0 → 纯源实例 integrity 归零、score 恒 0.8，
                //   由 G5 kill 容错调试首度暴露——跨特性组合场景测试缺口）
                None => 1.0,
            }
        };
        let h = score_instance(
            &outcomes,
            verify_fail.get(&spec.id).copied().unwrap_or(0),
            event_total.get(&spec.id).copied().unwrap_or(0),
            coverage,
            &weights,
        );
        health.insert(spec.id.clone(), h);
    }
    let mut ts: Vec<f64> = Vec::new();
    for spec in &specs {
        if let Some(st) = last_states.get(&spec.id) {
            if let Some(t) = st.get("trust").and_then(|x| x.as_f64()) {
                ts.push(t.clamp(0.0, 1.0));
            }
        }
    }
    let n = ts.len() as f64;
    let t_avg = if n > 0.0 { ts.iter().sum::<f64>() / n } else { 0.0 };
    let t_min = if ts.is_empty() {
        0.0
    } else {
        ts.iter().cloned().fold(f64::INFINITY, f64::min)
    };
    let t_variance = if n > 0.0 {
        ts.iter().map(|t| (t - t_avg) * (t - t_avg)).sum::<f64>() / n
    } else {
        0.0
    };
    let t_alignment = if t_avg > 0.0 {
        1.0 - t_variance / t_avg
    } else {
        0.0
    };
    // G3b gossip 对账：全部 gossip 目标实收数相等 = 投递覆盖一致
    // （单机=结构覆盖断言；跨机场景防丢消息）。空 = gossip 未启用 → true。
    let gossip_consistent = {
        let mut counts: Vec<usize> = gossip_sent.values().copied().collect();
        counts.sort_unstable();
        counts.first() == counts.last()
    };
    SwarmReport {
        rounds,
        events,
        acks,
        t_avg,
        t_min,
        t_variance,
        t_alignment,
        final_states: last_states,
        health,
        gossip_received: gossip_sent,
        gossip_consistent,
        topology: cfg.topology.clone(),
        condition_space: cfg.condition_space.clone(),
        condition_space_id: cfg.condition_space.as_ref().map(|c| c.space_id.clone()),
        roles: specs
            .iter()
            .map(|s| (s.id.clone(), s.role.clone()))
            .collect(),
        watermarks,
        global_seq,
        wal_continuity,
        recalc_checked,
        recalc_mismatches,
    }
}

/// 蜂群报告 → JSON（Python 侧消费/对照）
pub fn report_json(rep: &SwarmReport) -> String {
    let mut out = String::from("{");
    out.push_str(&format!("\"rounds\":{}", rep.rounds));
    out.push_str(&format!(
        ",\"instances\":{}",
        rep.final_states.len()
    ));
    out.push_str(",\"trust\":{");
    out.push_str(&format!(
        "\"T_avg\":{:.6},\"T_min\":{:.6},\"T_variance\":{:.6},\"T_alignment\":{:.6}",
        rep.t_avg, rep.t_min, rep.t_variance, rep.t_alignment
    ));
    out.push('}');
    out.push_str(&format!(",\"events\":{}", rep.events.len()));
    out.push_str(&format!(",\"acks\":{}", rep.acks.len()));
    // G3a 健康评分（四因子，公式与权重见 health.rs）
    out.push_str(",\"health\":{");
    let mut hids: Vec<&String> = rep.health.keys().collect();
    hids.sort();
    for (i, id) in hids.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        let h = &rep.health[*id];
        out.push_str(&format!(
            "\"{}\":{{\"score\":{:.6},\"success_rate\":{:.6},\"uptime_rate\":{:.6},\"threat_rate\":{:.6},\"integrity_rate\":{:.6}}}",
            serde_json_like::escape(id),
            h.score,
            h.success_rate,
            h.uptime_rate,
            h.threat_rate,
            h.integrity_rate
        ));
    }
    out.push('}');
    // G3b gossip 水位与对账
    out.push_str(",\"gossip\":{");
    let mut gids: Vec<&String> = rep.gossip_received.keys().collect();
    gids.sort();
    for (i, id) in gids.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push_str(&format!(
            "\"{}\":{}",
            serde_json_like::escape(id),
            rep.gossip_received[*id]
        ));
    }
    out.push('}');
    out.push_str(&format!(",\"gossip_consistent\":{}", rep.gossip_consistent));
    // G-R2 生效条件空间
    if let Some(id) = &rep.condition_space_id {
        out.push_str(&format!(
            ",\"condition_space\":\"{}\"",
            serde_json_like::escape(id)
        ));
    }
    // G-R3 复算统计
    out.push_str(&format!(
        ",\"recalc\":{{\"checked\":{},\"mismatches\":{}}}",
        rep.recalc_checked, rep.recalc_mismatches
    ));
    // G4b 消费水位与全局 seq
    out.push_str(",\"watermarks\":{");
    let mut wids: Vec<&String> = rep.watermarks.keys().collect();
    wids.sort();
    for (i, id) in wids.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push_str(&format!(
            "\"{}\":{}",
            serde_json_like::escape(id),
            rep.watermarks[*id]
        ));
    }
    out.push('}');
    out.push_str(&format!(",\"global_seq\":{}", rep.global_seq));
    // issue #354 P1-6：WAL 重放区 seq/round 连续性读数（审计面）——ok=false 即
    // 已提交区存在丢行/乱序（旧实现无可回读面，消费方无从察觉）。
    out.push_str(&format!(
        ",\"wal_continuity\":{{\"ok\":{},\"breaks\":{},\"lines\":{},\"detail\":[",
        rep.wal_continuity.ok(),
        rep.wal_continuity.breaks,
        rep.wal_continuity.lines
    ));
    for (i, b) in rep.wal_continuity.detail.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push_str(&format!(
            "{{\"line\":{},\"expected\":{},\"actual\":{},\"kind\":\"{}\",\"row_type\":\"{}\"}}",
            b.line,
            b.expected,
            b.actual,
            serde_json_like::escape(b.kind),
            serde_json_like::escape(&b.row_type)
        ));
    }
    out.push_str("]}");
    // G4a 生效拓扑与各实例角色
    out.push_str(&format!(
        ",\"topology\":\"{}\"",
        serde_json_like::escape(&rep.topology)
    ));
    out.push_str(",\"roles\":{");
    let mut rids: Vec<&String> = rep.roles.keys().collect();
    rids.sort();
    for (i, id) in rids.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push_str(&format!(
            "\"{}\":\"{}\"",
            serde_json_like::escape(id),
            serde_json_like::escape(&rep.roles[*id])
        ));
    }
    out.push('}');
    out.push_str(",\"final_states\":{");
    let mut ids: Vec<&String> = rep.final_states.keys().collect();
    ids.sort();
    for (i, id) in ids.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push_str(&format!(
            "\"{}\":{}",
            serde_json_like::escape(id),
            serde_json_like::stringify(&rep.final_states[*id])
        ));
    }
    out.push_str("}}");
    out
}

#[cfg(test)]
mod wal_recovery_tests {
    //! 2026-09-25 守卫（缺陷：WAL 恢复重写非原子 + 零提交整文件清零）：
    //! 密钥为随机生成哑密钥（毫秒时间戳+进程号拼接），绝不硬编码真实密钥。
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static DIR_SEQ: AtomicU64 = AtomicU64::new(0);

    /// 随机哑密钥（每测试唯一；非真实 HMAC 密钥）
    fn dummy_secret() -> String {
        format!(
            "guard-dummy-{}-{}-{}",
            std::process::id(),
            now_ms(),
            DIR_SEQ.fetch_add(1, Ordering::Relaxed)
        )
    }

    /// 互不冲突的临时目录（temp_dir + 进程号 + 毫秒时间戳 + 原子计数）
    fn guard_dir(tag: &str) -> std::path::PathBuf {
        let d = std::env::temp_dir().join(format!(
            "swarm_wal_guard_{tag}_{}_{}_{}",
            std::process::id(),
            now_ms(),
            DIR_SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&d).expect("临时目录创建失败");
        d
    }

    /// 构造与在线写入同格式的合法签名行（不带结尾换行）
    fn signed_line(secret: &str, seq: u64, ev_type: &str, round: u64, payload: &str) -> String {
        // ts 只取一次：旧实现签名用第一次 now_ms()、写盘用第二次，跨毫秒边界
        // 即「写盘 ts ≠ 入签 ts」→ 重放侧 HMAC 不符 → 提交点丢失（偶发假红，
        // 隔离复跑通过、并发/负载下偶现）。
        let ts = now_ms();
        let ev = Event {
            seq,
            ts,
            from_id: "协调器".into(),
            to_id: "i1".into(),
            event_type: ev_type.into(),
            payload_json: payload.into(),
            round_no: round,
            level: 0,
            hmac_hex: String::new(),
        };
        let hmac_hex = sign_event(secret, &ev);
        format!(
            "{{\"seq\":{seq},\"ts\":{ts},\"from\":\"协调器\",\"to\":\"i1\",\"type\":\"{}\",\"round\":{round},\"level\":0,\"hmac\":\"{hmac_hex}\",\"payload\":{payload}}}",
            serde_json_like::escape(ev_type)
        )
    }

    /// 快照行（from/to 均为协调器，与在线写入一致）
    fn snapshot_line(secret: &str, seq: u64, round: u64) -> String {
        let ts = now_ms(); // ts 只取一次（同上：跨毫秒即假红）
        let ev = Event {
            seq,
            ts,
            from_id: "协调器".into(),
            to_id: "协调器".into(),
            event_type: SNAPSHOT_TYPE.into(),
            payload_json: r#"{"trusts":{},"states":{}}"#.into(),
            round_no: round,
            level: 0,
            hmac_hex: String::new(),
        };
        let hmac_hex = sign_event(secret, &ev);
        format!(
            "{{\"seq\":{seq},\"ts\":{ts},\"from\":\"协调器\",\"to\":\"协调器\",\"type\":\"{SNAPSHOT_TYPE}\",\"round\":{round},\"level\":0,\"hmac\":\"{hmac_hex}\",\"payload\":{}}}",
            ev.payload_json
        )
    }

    /// G1（防回退·红证）：恢复重写不得就地清零在役 WAL——重写路径必须经
    /// 临时文件原子换入。注入故障：临时文件位置预置目录使创建失败（模拟
    /// 重写窗口内崩溃/断电/写 Err），断言原 WAL 逐字节完好且函数报错。
    #[test]
    fn recovery_rewrite_failure_never_truncates_live_wal() {
        let dir = guard_dir("g1");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        let original = format!(
            "{}\n{}\n{}\n",
            snapshot_line(&secret, 1, 1),
            signed_line(&secret, 2, "MSG", 1, r#"{"x":1}"#),
            "{\"seq\":3,\"ts\":1,\"from\":\"BAD half line" // 崩溃残留坏尾
        );
        std::fs::write(&wal, &original).unwrap();
        let replay = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        assert!(replay.completed.is_some(), "守卫前提：快照行合法应可恢复");
        // 堵死重写临时文件位置 —— 模拟重写窗口内故障。临时名含**进程号**
        // （issue #354 P1-7：固定名 {wal}.tmp 在多进程下是同一 inode），故测试
        // 用同一算式推算本进程的临时名再占位——注入点变了，断言的本体不变。
        std::fs::create_dir(format!("{}.tmp.{}", wal_s, std::process::id())).unwrap();
        let res = open_wal_for_run(wal_s, replay.completed, &replay.kept_lines, replay.had_wal_file);
        assert!(res.is_err(), "重写窗口故障必须报错退出，不得静默半写");
        let after = std::fs::read_to_string(&wal).unwrap();
        assert_eq!(after, original, "重写失败时在役 WAL 必须逐字节完好（原子性）");
        std::fs::remove_dir_all(&dir).ok();
    }

    /// G2（防回退·红证）：零提交（无合法快照）WAL 不得整文件清零——事件行
    /// 独立 HMAC 签名，坏行之后可独立验签的审计留痕必须归档保留。
    #[test]
    fn corrupt_wal_archived_not_destroyed() {
        let dir = guard_dir("g2");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        // 首行损坏 → 提交点搜索首行即止（completed=None），其后行均可独立验签
        let mut original = String::from("{\"seq\":CORRUPT first line\n");
        original.push_str(&snapshot_line(&secret, 1, 1));
        original.push('\n');
        for i in 2..=4 {
            original.push_str(&signed_line(&secret, i, "MSG", 1, r#"{"x":{i}}"#));
            original.push('\n');
        }
        std::fs::write(&wal, &original).unwrap();
        let replay = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        assert!(replay.completed.is_none(), "守卫前提：首行坏 → 零提交");
        assert!(replay.had_wal_file);
        let f = open_wal_for_run(wal_s, replay.completed, &replay.kept_lines, replay.had_wal_file);
        assert!(f.is_ok(), "零提交应正常开空 WAL 从轮 1 重跑");
        drop(f.unwrap());
        assert_eq!(
            std::fs::read_to_string(&wal).unwrap(),
            "",
            "新 WAL 应为空文件（B1 全回滚语义不变）"
        );
        let archives: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .map(|e| e.unwrap().path())
            .filter(|p| {
                p.file_name()
                    .map(|n| n.to_string_lossy().starts_with("events.jsonl.corrupt-"))
                    .unwrap_or(false)
            })
            .collect();
        assert_eq!(archives.len(), 1, "坏 WAL 必须归档留痕（恰好一份）");
        assert_eq!(
            std::fs::read_to_string(&archives[0]).unwrap(),
            original,
            "归档必须逐字节保留原 WAL（含坏行后可独立验签的事件行）"
        );
        std::fs::remove_dir_all(&dir).ok();
    }

    /// G3（语义守卫）：恢复重写截断坏尾、保留好行前缀、无临时残留、可续写。
    #[test]
    fn recovery_rewrite_truncates_bad_tail_and_resumes() {
        let dir = guard_dir("g3");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        let content = format!(
            "{}\n{}\n{}\n",
            snapshot_line(&secret, 1, 1),
            signed_line(&secret, 2, "MSG", 1, r#"{"x":1}"#),
            "{\"seq\":3,\"ts\":1,\"from\":\"BAD half line"
        );
        std::fs::write(&wal, &content).unwrap();
        let replay = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        assert!(replay.completed.is_some());
        let mut f =
            open_wal_for_run(wal_s, replay.completed, &replay.kept_lines, replay.had_wal_file)
                .unwrap();
        let after = std::fs::read_to_string(&wal).unwrap();
        assert_eq!(
            after,
            format!("{}\n", replay.kept_lines.join("\n")),
            "重写后 = 好行前缀（坏尾物理截断）"
        );
        assert!(
            // 临时名含进程号（issue #354 P1-7）：按同一算式推算本进程的临时名
            !dir.join(format!("events.jsonl.tmp.{}", std::process::id())).exists()
                && !dir.join("events.jsonl.tmp").exists(),
            "成功路径不得残留临时文件（新旧两种命名都不得残留）"
        );
        assert!(
            !dir.join("events.jsonl.lock").exists(),
            "成功路径不得残留锁件（issue #354 P1-7）"
        );
        f.write_all(b"{\"seq\":99,\"resume\":true}\n").unwrap();
        f.flush().unwrap();
        let resumed = std::fs::read_to_string(&wal).unwrap();
        assert!(resumed.ends_with("{\"seq\":99,\"resume\":true}\n"), "续跑可 append");
        std::fs::remove_dir_all(&dir).ok();
    }

    /// G4（语义守卫）：无 WAL = 首跑——新建空文件，不触发归档。
    #[test]
    fn first_run_creates_empty_wal_without_archive() {
        let dir = guard_dir("g4");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let replay = replay_wal(wal_s, &dummy_secret(), &HashSet::new()).unwrap();
        assert!(replay.completed.is_none());
        assert!(!replay.had_wal_file);
        let f = open_wal_for_run(wal_s, replay.completed, &replay.kept_lines, replay.had_wal_file);
        assert!(f.is_ok());
        drop(f.unwrap());
        assert_eq!(std::fs::read_to_string(&wal).unwrap(), "");
        let n = std::fs::read_dir(&dir).unwrap().count();
        assert_eq!(n, 1, "目录内只有新 WAL，无归档无残留");
        std::fs::remove_dir_all(&dir).ok();
    }

    // ================= issue #354（2026-10-14）P0-2 / P1-6 / P1-7 =================

    /// G5（#354 P0-2 · 防回退·红证）：WAL 尾部含**非法 UTF-8** 字节时，已提交历史
    /// 不得被无痕清空。
    ///
    /// 病灶（修前）：replay_wal 用 read_to_string 整文件解码，任何 Err（含「文件存在
    /// 但含残字节」的 InvalidData）都被当成「无 WAL = 首跑」⇒ had_wal_file=false 且
    /// completed=None ⇒ open_wal_for_run 走 File::create **原位清空**且不归档。
    /// 实测形态（真二进制）：合法快照+事件前缀 + 尾部 0xFF 0xFE ⇒ 前缀消失、无归档；
    /// 唯一变量是「尾字节能否解码」（尾部为合法 UTF-8 半行时前缀完好）。
    ///
    /// 断言三面：①重放看得见已提交快照；②重写后前缀逐字节仍在、坏尾被物理截断；
    /// ③成功路径不留临时件/锁件。
    #[test]
    fn invalid_utf8_tail_never_erases_committed_history() {
        let dir = guard_dir("p02");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        let snap = snapshot_line(&secret, 1, 1);
        let ev = signed_line(&secret, 2, "MSG", 1, r#"{"x":1}"#);
        let mut bytes = format!("{snap}\n{ev}\n").into_bytes();
        bytes.extend_from_slice(&[0xFF, 0xFE]); // 撕裂写残字节（非法 UTF-8 尾）
        std::fs::write(&wal, &bytes).unwrap();

        let replay = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        assert!(
            replay.had_wal_file,
            "文件存在即 had_wal_file——损坏不得当成不存在（P0-2 病灶的入口）"
        );
        assert!(
            replay.completed.is_some(),
            "非法 UTF-8 尾不得吃掉其前的合法提交点（旧实现：整文件当空）"
        );
        let f = open_wal_for_run(wal_s, replay.completed, &replay.kept_lines, replay.had_wal_file);
        assert!(f.is_ok(), "恢复重写应成功");
        drop(f.unwrap());
        let after = std::fs::read(&wal).unwrap();
        assert!(
            after.windows(snap.len()).any(|w| w == snap.as_bytes()),
            "已提交快照行必须逐字节幸存（旧实现：整文件被 File::create 清空）"
        );
        assert!(
            !after.contains(&0xFF),
            "未提交的坏尾必须被物理截断（B1 语义不变）"
        );
        assert_eq!(
            std::fs::read_dir(&dir).unwrap().count(),
            1,
            "成功路径不得残留临时件或锁件（目录内只剩 WAL）"
        );
        std::fs::remove_dir_all(&dir).ok();
    }

    /// G6（#354 P0-2 · 第二面）：**整段不可解码**（连一个合法行都没有）时不得原位
    /// 清空——必须归档留痕（与 G2 的零提交语义一致）；had_wal_file 仍为真，绝不
    /// 退化成「首跑」。
    #[test]
    fn fully_undecodable_wal_is_archived_not_destroyed() {
        let dir = guard_dir("p02b");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        let original: Vec<u8> = vec![0xFF, 0xFE, 0xFD, b'\n', 0x80, 0x81, b'\n'];
        std::fs::write(&wal, &original).unwrap();
        let replay = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        assert!(replay.had_wal_file, "存在但不可解码 ≠ 不存在");
        assert!(
            replay.completed.is_none(),
            "无合法快照 → 零提交（B1 全回滚语义不变）"
        );
        let f = open_wal_for_run(wal_s, replay.completed, &replay.kept_lines, replay.had_wal_file);
        assert!(f.is_ok(), "零提交应正常开空 WAL 从轮 1 重跑");
        drop(f.unwrap());
        assert!(std::fs::read(&wal).unwrap().is_empty(), "新 WAL 为空文件");
        let archives: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .map(|e| e.unwrap().path())
            .filter(|p| {
                p.file_name()
                    .map(|n| n.to_string_lossy().starts_with("events.jsonl.corrupt-"))
                    .unwrap_or(false)
            })
            .collect();
        assert_eq!(archives.len(), 1, "不可解码 WAL 必须归档留痕（恰好一份）");
        assert_eq!(
            std::fs::read(&archives[0]).unwrap(),
            original,
            "归档必须逐字节保留原 WAL（含非法字节）"
        );
        std::fs::remove_dir_all(&dir).ok();
    }

    /// G7（#354 P1-6 · 防回退·红证）：seq 跳号必须**可察觉**——重放读数里出现明细
    /// （旧实现完全静默 ⇒ 丢行不可察觉，这正是缺陷本体）。口径与 Python
    /// verify_wal_signatures 的 continuity_breaks 同源：一处偏离一条明细、链以实际
    /// seq+1 重同步、不级联连坐。
    #[test]
    fn seq_gap_is_reported_as_continuity_break() {
        let dir = guard_dir("p16");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        // 行：1(快照 r1),2,[缺 3/4],5,6(快照 r2)——第 3 行起报一次跳号。
        // 快照轮号取 r2 而非 r1：同一轮写两个快照属另一条判据（G8），此处只隔离
        // 「seq 跳号」这一条，避免两条判据在同一夹具里互相污染读数。
        let content = format!(
            "{}\n{}\n{}\n{}\n",
            snapshot_line(&secret, 1, 1),
            signed_line(&secret, 2, "MSG", 1, r#"{"x":1}"#),
            signed_line(&secret, 5, "MSG", 1, r#"{"x":2}"#),
            snapshot_line(&secret, 6, 2),
        );
        std::fs::write(&wal, &content).unwrap();
        let rp = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        assert!(rp.completed.is_some(), "守卫前提：快照合法应可恢复");
        assert_eq!(rp.continuity.breaks, 1, "恰好一处跳号（不级联连坐）");
        assert!(!rp.continuity.ok(), "ok 必须为假（可回读的察觉面）");
        assert_eq!(rp.continuity.lines, 4, "四行全部进入重放区（判据不误伤）");
        let d = &rp.continuity.detail[0];
        assert_eq!(d.line, 3, "1 基行号");
        assert_eq!(d.expected, 3);
        assert_eq!(d.actual, 5);
        assert_eq!(d.kind, "跳号缺失");
        // 完好 WAL 不得误报（判据的阴性面）
        let wal2 = dir.join("ok.jsonl");
        std::fs::write(
            &wal2,
            format!(
                "{}\n{}\n",
                snapshot_line(&secret, 1, 1),
                signed_line(&secret, 2, "MSG", 1, r#"{"x":1}"#),
            ),
        )
        .unwrap();
        let rp2 = replay_wal(wal2.to_str().unwrap(), &secret, &HashSet::new()).unwrap();
        assert!(rp2.continuity.ok(), "连续 WAL 不得误报：{:?}", rp2.continuity);
        std::fs::remove_dir_all(&dir).ok();
    }

    /// G8（#354 P1-6）：同一轮出现**两个快照行**（双 coordinator 各写一份的形态）
    /// 必须报出——单条 HMAC 只锚「这行没被改」，锚不住「轮次语义被写坏」。
    #[test]
    fn duplicate_snapshot_round_is_reported() {
        let dir = guard_dir("p16b");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        let content = format!(
            "{}\n{}\n",
            snapshot_line(&secret, 1, 1),
            snapshot_line(&secret, 2, 1)
        );
        std::fs::write(&wal, &content).unwrap();
        let rp = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        assert_eq!(rp.continuity.breaks, 1, "重复轮号须报一处");
        assert_eq!(rp.continuity.detail[0].kind, "快照轮号重复或倒退");
        std::fs::remove_dir_all(&dir).ok();
    }

    /// G9（#354 P1-7 · 防回退·红证）：WAL 锁被他人持有时恢复**必须** fail-closed
    /// （报错且原 WAL 逐字节不动），不得无锁改写。
    ///
    /// 本用例耗时约 LOCK_WAIT_MS（5s）：并发判据只能靠真锁来验，故等待窗口取
    /// 「高负载下够退让、测试里可接受」的折中值。
    #[test]
    fn held_wal_lock_fails_closed_without_touching_wal() {
        let dir = guard_dir("p17");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        let original = format!(
            "{}\n{}\n",
            snapshot_line(&secret, 1, 1),
            signed_line(&secret, 2, "MSG", 1, r#"{"x":1}"#)
        );
        std::fs::write(&wal, &original).unwrap();
        let lock = format!("{wal_s}.lock");
        std::fs::write(&lock, "99999 0\n").unwrap(); // 他人持锁（mtime 新鲜）
        let replay = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        assert!(replay.completed.is_some());
        let res = open_wal_for_run(wal_s, replay.completed, &replay.kept_lines, replay.had_wal_file);
        let err = res.err().expect("锁被持有必须 fail-closed（旧实现无锁照写）");
        assert!(err.contains("排他锁"), "错误须点名锁（可诊断）：{err}");
        assert_eq!(
            std::fs::read_to_string(&wal).unwrap(),
            original,
            "未取得锁时在役 WAL 必须逐字节不动"
        );
        assert!(std::fs::remove_file(&lock).is_ok());
        // 释放后同一路径必须可恢复（锁不得变成一次性）
        let replay2 = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        let f = open_wal_for_run(wal_s, replay2.completed, &replay2.kept_lines,
                                 replay2.had_wal_file);
        assert!(f.is_ok(), "他人释放锁后必须可恢复（锁不是一次性）");
        drop(f.unwrap());
        std::fs::remove_dir_all(&dir).ok();
    }

    /// 任意 from/to/type 的合法签名事件行（在线写入同格式，不带结尾换行）。
    /// ts 单次取样：签名串与行内 ts 必须同值（跨毫秒双取样会自签自不符）。
    fn signed_line_ext(
        secret: &str,
        seq: u64,
        from: &str,
        to: &str,
        ev_type: &str,
        round: u64,
        payload: &str,
    ) -> String {
        let ts = now_ms();
        let ev = Event {
            seq,
            ts,
            from_id: from.into(),
            to_id: to.into(),
            event_type: ev_type.into(),
            payload_json: payload.into(),
            round_no: round,
            level: 0,
            hmac_hex: String::new(),
        };
        let hmac_hex = sign_event(secret, &ev);
        format!(
            "{{\"seq\":{seq},\"ts\":{ts},\"from\":\"{}\",\"to\":\"{}\",\"type\":\"{}\",\"round\":{round},\"level\":0,\"hmac\":\"{hmac_hex}\",\"payload\":{payload}}}",
            serde_json_like::escape(from),
            serde_json_like::escape(to),
            serde_json_like::escape(ev_type),
        )
    }

    /// 带信任/终态负载的快照行（在线写入同格式；ts 单次取样同理）。
    fn snapshot_line_ext(secret: &str, seq: u64, round: u64, payload: &str) -> String {
        let ts = now_ms();
        let ev = Event {
            seq,
            ts,
            from_id: "协调器".into(),
            to_id: "协调器".into(),
            event_type: SNAPSHOT_TYPE.into(),
            payload_json: payload.into(),
            round_no: round,
            level: 0,
            hmac_hex: String::new(),
        };
        let hmac_hex = sign_event(secret, &ev);
        format!(
            "{{\"seq\":{seq},\"ts\":{ts},\"from\":\"协调器\",\"to\":\"协调器\",\"type\":\"{SNAPSHOT_TYPE}\",\"round\":{round},\"level\":0,\"hmac\":\"{hmac_hex}\",\"payload\":{payload}}}",
        )
    }

    /// N109（v12 留档，批次58）红守卫：同 project+同 WAL 幂等重入（全完成早退
    /// 聚合路径）审计面不得归零——WAL 已含 gossip 路由行与 ACK 行（payload
    /// 自带 {"round","seq"} 即重建信息源），重入报告 watermarks/gossip 必须与
    /// 首跑一致（acks/global_seq 本就保留，对照面）。早退 return 在实例 spawn
    /// 之前（不触 exe），exe 传不存在路径即可纯进程内复现。
    /// 注：health 面不在此断言——逐轮终态质量（ok/error）未持久化进 WAL，
    /// 参与性重建会伪造 success_rate（G5「不伪造终态」纪律），health 维持
    /// 在线窗口口径（:769 注），精确重建须快照负载扩展，另列。
    #[test]
    fn wal_reentry_keeps_watermark_and_gossip_faces() {
        let dir = guard_dir("n109");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        // 在线写入顺序（甲→乙 gossip，2 轮全部提交）：轮1路由+快照 → 轮2 ACK+路由+快照
        // 事件 seq 全局单调：1路由 2快照 3ACK 4路由 5快照
        let content = format!(
            "{}\n{}\n{}\n{}\n{}\n",
            signed_line_ext(&secret, 1, "甲", "乙", "gossip", 1, r#"{"t":1}"#),
            snapshot_line_ext(
                &secret,
                2,
                1,
                r#"{"trusts":{"甲":0.9,"乙":0.9},"states":{"甲":{},"乙":{}}}"#,
            ),
            // ACK：乙在轮2消费轮1投递（payload seq=1 = 消费水位）
            signed_line_ext(&secret, 3, "乙", "协调器", "ACK", 2, r#"{"round":2,"seq":1}"#),
            signed_line_ext(&secret, 4, "甲", "乙", "gossip", 2, r#"{"t":1}"#),
            snapshot_line_ext(
                &secret,
                5,
                2,
                r#"{"trusts":{"甲":0.9,"乙":0.9},"states":{"甲":{},"乙":{}}}"#,
            ),
        );
        std::fs::write(&wal, &content).unwrap();

        let cfg = SwarmConfig {
            shared_secret: secret,
            instances: vec![
                InstanceSpec {
                    id: "甲".into(),
                    role: "peer".into(),
                    trust: 0.9,
                    symbols_json: "{}".into(),
                    condition_space: None,
                },
                InstanceSpec {
                    id: "乙".into(),
                    role: "peer".into(),
                    trust: 0.9,
                    symbols_json: "{}".into(),
                    condition_space: None,
                },
            ],
            routes: vec![Route {
                from_id: "甲".into(),
                event_type: "gossip".into(),
                to_id: GOSSIP_TARGET.into(),
                payload_json: r#"{"t":1}"#.into(),
                level: 0,
            }],
            topology: String::new(),
            condition_space: None,
        };
        let rep = run_swarm("/nonexistent/stub_exe", &cfg, 2, wal_s, None)
            .expect("全完成重入应早退聚合成功");
        // 对照面（旧代码亦须过）：acks/global_seq 保留
        assert_eq!(rep.acks.len(), 1, "重入 acks 面不得丢失");
        assert_eq!(rep.global_seq, 2, "重入 global_seq 不得归零");
        // 审计面（缺陷主体）：watermarks/gossip 与首跑一致，不归零
        assert_eq!(
            rep.watermarks.get("乙"),
            Some(&1),
            "重入 watermarks 须从 ACK payload 重建（乙消费水位=1），不得归零"
        );
        assert_eq!(
            rep.gossip_received.get("乙"),
            Some(&2),
            "重入 gossip 须从 gossip 路由行重建（乙两轮各收 1 条），不得归零"
        );
        assert!(
            rep.gossip_consistent,
            "重建后对账基准恢复（单目标恒一致）"
        );
        std::fs::remove_dir_all(&dir).ok();
    }

    /// N109 重放级单测：replay_wal 直接断言两张重建表的精确值——
    /// ①ACK payload seq → watermarks（per 实例最大值）；②gossip 指纹命中
    /// 的路由行 → gossip_sent；③坏 ACK payload 不炸不误记；④无指纹不计数。
    #[test]
    fn replay_backfills_watermarks_and_gossip_exactly() {
        let dir = guard_dir("n109r");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        let content = format!(
            "{}\n{}\n{}\n{}\n{}\n{}\n{}\n",
            // 甲→乙 gossip 投递（轮1）
            signed_line_ext(&secret, 1, "甲", "乙", "gossip", 1, r#"{"t":1}"#),
            // 甲→丙 单播（同源同型——指纹命中与否见下方双口径断言）
            signed_line_ext(&secret, 2, "甲", "丙", "gossip", 1, r#"{"t":1}"#),
            snapshot_line_ext(&secret, 3, 1, r#"{"trusts":{},"states":{}}"#),
            // 乙 ACK 水位 1；随后乙再 ACK 水位 3（取最大）
            signed_line_ext(&secret, 4, "乙", "协调器", "ACK", 2, r#"{"round":2,"seq":1}"#),
            signed_line_ext(&secret, 5, "乙", "协调器", "ACK", 3, r#"{"round":3,"seq":3}"#),
            // 坏 ACK payload（seq 非数）——不炸、不误记水位
            signed_line_ext(&secret, 6, "丙", "协调器", "ACK", 3, r#"{"round":3,"seq":"x"}"#),
            snapshot_line_ext(&secret, 7, 3, r#"{"trusts":{},"states":{}}"#),
        );
        std::fs::write(&wal, &content).unwrap();
        // 指纹含甲的 gossip 路由：甲→乙 gossip 行计入乙；甲→丙 同源同型行
        // 同口径计入丙——与在线 fan-out 记账对齐（病理重叠配置的歧义边界
        // 见 WalReplay.gossip_sent 结构体注）。
        let mut fps: HashSet<(String, String)> = HashSet::new();
        fps.insert(("甲".to_string(), "gossip".to_string()));
        let rp = replay_wal(wal_s, &secret, &fps).unwrap();
        assert!(rp.completed.is_some(), "守卫前提：快照合法应可恢复");
        assert_eq!(
            rp.watermarks.get("乙"),
            Some(&3),
            "watermarks 取 ACK payload seq 的 per 实例最大值"
        );
        assert_eq!(rp.watermarks.get("丙"), None, "坏 payload seq 不得误记水位");
        assert_eq!(
            rp.gossip_sent.get("乙"),
            Some(&1),
            "指纹命中路由行计入 gossip 投递"
        );
        assert_eq!(
            rp.gossip_sent.get("丙"),
            Some(&1),
            "同源同型行同口径计数（与在线 fan-out 记账一致）"
        );
        // 无指纹（非 gossip 拓扑）：路由行不产生 gossip 计数、水位不受影响
        let rp0 = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        assert!(rp0.gossip_sent.is_empty(), "无指纹不得计数 gossip");
        assert_eq!(rp0.watermarks.get("乙"), Some(&3), "水位重建与指纹无关");
        std::fs::remove_dir_all(&dir).ok();
    }

    /// N245（守卫）：行内含控制字符转义（写侧 `escape` 对 <0x20 产 `\uXXXX`、
    /// 对回车产 `\r`）时提交点扫描必须照常推进——不得把合法 WAL 误判为坏 WAL
    /// （零提交 → 归档 `.corrupt-*` 并从轮 1 重跑，破坏「同 project+同 WAL
    /// 重入即续跑」幂等契约；WAL 本身是合法 JSON，Python 侧验签 all_valid）。
    #[test]
    fn commit_point_survives_control_char_escapes() {
        let dir = guard_dir("n245");
        let wal = dir.join("events.jsonl");
        let wal_s = wal.to_str().unwrap();
        let secret = dummy_secret();
        // 首行即含转义载荷（在线 WAL 的真实序位：轮内散事件在快照之前）
        let content = format!(
            "{}\n{}\n",
            signed_line(&secret, 1, "MSG", 1, r#"{"文本":"甲\u0009乙\r丙"}"#),
            snapshot_line(&secret, 2, 1),
        );
        std::fs::write(&wal, &content).unwrap();
        let rp = replay_wal(wal_s, &secret, &HashSet::new()).unwrap();
        assert_eq!(
            rp.completed,
            Some(1),
            "首行含 \\uXXXX/\\r 的合法 WAL 必须认出提交点（旧实现首行即断 → 零提交）"
        );
        assert_eq!(rp.kept_lines.len(), 2, "两行都在可信前缀内");
        assert!(rp.had_wal_file);
        let f = open_wal_for_run(wal_s, rp.completed, &rp.kept_lines, rp.had_wal_file);
        assert!(f.is_ok(), "认出提交点即走续跑路径");
        drop(f.unwrap());
        assert_eq!(
            std::fs::read_to_string(&wal).unwrap(),
            content,
            "续跑是 append 语义：原 WAL 逐字节保留（不清零）"
        );
        let archives: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .map(|e| e.unwrap().path())
            .filter(|p| {
                p.file_name()
                    .map(|n| n.to_string_lossy().contains(".corrupt-"))
                    .unwrap_or(false)
            })
            .collect();
        assert!(archives.is_empty(), "合法 WAL 不得被归档为 .corrupt-*");
        std::fs::remove_dir_all(&dir).ok();
    }
}

#[cfg(test)]
mod escape_parity_tests {
    //! N245 守卫：**写侧产出（`serde_json_like::escape`）必须全部落在读侧可解析集内**。
    //!
    //! 旧读侧 `ps` 只认 `\" \\ \n \t`，而写侧对 <0x20 控制字符产 `\uXXXX`、
    //! 对回车产 `\r`——集合不相容，三面后果：①载荷含制表符（escape 产
    //! `\u0009`）时实例侧请求解析失败、目标实例终态恒为 error，而协调器
    //! rc=0 照发 ACK、水位照推进；②WAL 载荷含 `\u0009` 时提交点扫描首行即断，
    //! 合法 WAL 被误标 `.corrupt-<ts>` 并从轮 1 重跑；③配置含标准 `\r` 转义
    //! 则整蜂群 exit 2。本模块只断行为（写→读往返无损），不做源码文本匹配。
    use super::serde_json_like::{escape, parse};

    /// 语料：控制字符（→ `\uXXXX`）、回车（→ `\r`）、换行、引号/反斜杠、
    /// 多字节与四字节字符、空串。
    const CORPUS: [&str; 8] = [
        "甲\u{9}乙",
        "上\r下",
        "上\n下",
        "\u{1}\u{1f}\u{0}",
        "引号\"与反斜杠\\",
        "中文·標點——破折",
        "",
        "\u{7f}删字符与 emoji 😀",
    ];

    #[test]
    fn escape_output_is_parseable_and_lossless() {
        for s in CORPUS {
            let json = format!("\"{}\"", escape(s));
            let v = parse(&json)
                .unwrap_or_else(|e| panic!("读侧无法解析写侧产出 {json:?}：{e}"));
            assert_eq!(v.as_str(), Some(s), "往返不等：{s:?} → {json:?}");
        }
    }

    #[test]
    fn wal_shaped_line_round_trips() {
        // 与 WAL 行同构：对象内嵌对象、字段含制表符与回车
        let line = format!(
            "{{\"seq\":1,\"type\":\"MSG\",\"payload\":{{\"文本\":\"{}\"}}}}",
            escape("甲\u{9}乙\r丙")
        );
        let v = parse(&line).expect("读侧须能解析含 \\uXXXX/\\r 的 WAL 行");
        let got = v
            .get("payload")
            .and_then(|p| p.get("文本"))
            .and_then(|t| t.as_str());
        assert_eq!(got, Some("甲\u{9}乙\r丙"));
    }

    /// #156⑧ 守卫（K 组 · task-49）：本解析器（swarm 配置 / 收件箱行 / 事件行读侧）
    /// 是递归下降，**必须有嵌套深度上限**——深嵌套输入必须得到 Err，绝不放任递归把
    /// 栈吃穿（Rust 栈溢出不可捕获，实测 5000 层直接 overflowed its stack 且退出码
    /// 0xC00000FD，整进程死）。纯行为断言：只看「深→Err、浅→Ok」，不做源码文本匹配。
    #[test]
    fn deep_nesting_is_rejected_not_aborting() {
        let deep = format!("{}{}{}", "{\"a\":".repeat(5000), "1", "}".repeat(5000));
        match parse(&deep) {
            Err(e) => assert!(e.contains("嵌套过深"), "拒绝原因须可读（点名嵌套过深）：{e}"),
            Ok(_) => panic!("深嵌套未被拒绝（递归无上限 ⇒ 生产面栈溢出 abort）"),
        }
        let shallow = format!("{}{}{}", "{\"a\":".repeat(100), "1", "}".repeat(100));
        assert!(parse(&shallow).is_ok(), "上限内结构被误拒（上限过紧）");
    }
}
