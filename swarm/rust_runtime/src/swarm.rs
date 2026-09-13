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
}

#[derive(Debug, Clone)]
pub struct Event {
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

/// G4b 收件箱：轮次 → 目标实例 → 来源 → (载荷, 投递时全局 seq)
type Inboxes = HashMap<u64, HashMap<String, HashMap<String, (String, u64)>>>;

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

    pub fn parse(s: &str) -> Result<Value, String> {
        let b: Vec<char> = s.chars().collect();
        let mut i = 0usize;
        let v = pv(&b, &mut i)?;
        Ok(v)
    }

    fn skip_ws(b: &[char], i: &mut usize) {
        while *i < b.len() && b[*i].is_whitespace() {
            *i += 1;
        }
    }

    fn pv(b: &[char], i: &mut usize) -> Result<Value, String> {
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
                            let v = pv(b, i)?;
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
                        _ => items.push(pv(b, i)?),
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

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn sign_event(key: &str, ev: &Event) -> String {
    // 签名串与 Python 侧 event_bus 约定一致：type|from|to|round|ts|payload
    let msg = format!(
        "{}|{}|{}|{}|{}|{}",
        ev.event_type, ev.from_id, ev.to_id, ev.round_no, ev.ts, ev.payload_json
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
}

/// 重放 WAL 重建状态（对照 langgraph 恢复语义：重建后走正常循环，无特殊路径）。
/// 完整性守卫：任何行 parse 失败或验签失败 → 停在该行（截断点），其前的行可信。
/// 单行 WAL → (Event, 原始 payload 字符串)；结构残缺返回 None（坏尾截断点）。
fn parse_event_line(line: &str) -> Option<(Event, String)> {
    let raw_payload = slice_raw_payload(line)?;
    let v = serde_json_like::parse(line).ok()?;
    let get_s = |k: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
    let ev = Event {
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

fn replay_wal(wal_path: &str, secret: &str) -> Result<WalReplay, String> {
    let mut rp = WalReplay {
        completed: None,
        events: Vec::new(),
        acks: HashSet::new(),
        inboxes: HashMap::new(),
        last_trust: HashMap::new(),
        last_states: HashMap::new(),
        kept_lines: Vec::new(),
        replayed_seq: 0,
    };
    let raw = match std::fs::read_to_string(wal_path) {
        Ok(r) => r,
        Err(_) => return Ok(rp), // 无 WAL = 首跑
    };
    // 第一遍：提交点 = 最后一个通过 HMAC 验签的快照行。
    // v0.6.1 修复：旧逻辑在事件行处做「超前轮截断」，而快照行 round 恒为
    // completed+1 → 快照被误伤截断，completed 永远停在 1，≥2 轮重入恒触发
    // 整段确定性重跑而非幂等聚合（重跑结果逐位一致，故 v0.6 全部测试未暴露）。
    // 快照 = 整轮持久化承诺：其前行（含快照与散事件）全部有效，其后散事件
    // （kill 落在快照写入前）按 B1 回滚——顺序流前缀性下只有「先扫提交点、
    // 再重建前缀」两遍扫描才正确，事件行自身无法预判后续是否有快照。
    let mut commit_idx: Option<usize> = None;
    for (idx, line) in raw.lines().enumerate() {
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
    for (idx, line) in raw.lines().enumerate() {
        if idx > commit_idx {
            break; // 未提交尾部散事件 → 回滚截断（B1 重跑重做）
        }
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
            } else if ev.to_id != "协调器" {
                // 路由事件：round 产生 → round+1 收件箱（与在线写入语义一致）。
                // G4b：重放计数保持 seq 全局单调（恢复后水位不断档）
                rp.replayed_seq += 1;
                rp.inboxes
                    .entry(ev.round_no + 1)
                    .or_default()
                    .entry(ev.to_id.clone())
                    .or_default()
                    .insert(ev.from_id.clone(), (raw_payload, rp.replayed_seq));
            }
        }
        rp.events.push(ev);
        rp.kept_lines.push(line.to_string());
    }
    Ok(rp)
}

struct InstanceProc {
    spec: InstanceSpec,
    child: Child,
    stdin: BufWriter<std::process::ChildStdin>,
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
        Ok(InstanceProc {
            spec: spec.clone(),
            child,
            stdin: BufWriter::new(stdin),
        })
    }

    /// 执行一轮：请求 = 初始环境（symbols/trust/condition_space）+ 收件箱
    fn run_round(
        &mut self,
        round_no: u64,
        inbox: &HashMap<String, String>,
    ) -> Result<serde_json_like::Value, String> {
        let mut symbols_parts: Vec<String> = Vec::new();
        // 每轮都带初始符号（VM 符号表不跨轮持久——每轮是完整环境；
        // 跨轮传递的数据只能走消息，这正是消息传递模型的语义）
        if !self.spec.symbols_json.is_empty() {
            symbols_parts.push(format!("\"初始符号\":{}", self.spec.symbols_json));
        }
        if !inbox.is_empty() {
            let msgs: Vec<String> = {
                let mut keys: Vec<&String> = inbox.keys().collect();
                keys.sort();
                keys.iter()
                    .map(|k| {
                        format!("{{\"from\":\"{}\",\"payload\":{}}}", k, inbox[*k])
                    })
                    .collect()
            };
            symbols_parts
                .push(format!("\"收件箱\":[{}]", msgs.join(",")));
            symbols_parts.push(format!("\"已收消息数\":{}", inbox.len()));
        }
        let req = format!(
            "{{\"symbols\":{{{}}},\"trust\":{},\"round_no\":{}}}\n",
            symbols_parts.join(","),
            self.spec.trust,
            round_no
        );
        self.stdin
            .write_all(req.as_bytes())
            .map_err(|e| format!("实例 {} 管道断裂: {e}", self.spec.id))?;
        self.stdin
            .flush()
            .map_err(|e| format!("实例 {} flush 失败: {e}", self.spec.id))?;
        let stdout = self
            .child
            .stdout
            .as_mut()
            .ok_or_else(|| "无法读取实例 stdout".to_string())?;
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        reader
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
    }

    // B1 断点恢复：先重放 WAL。有快照 → 从快照轮+1 续跑（append）；
    // 无快照 → 维持旧行为从轮 1 截断重跑；坏尾（半行/篡改）在重放处停住。
    let replay = replay_wal(wal_path, &cfg.shared_secret)?;
    let mut all_events: Vec<Event> = replay.events;
    let mut acks: HashSet<String> = replay.acks;
    let mut inboxes: Inboxes = replay.inboxes;
    let mut last_states: HashMap<String, serde_json_like::Value> = replay.last_states;
    let mut last_trust: HashMap<String, f64> = replay.last_trust;
    let start_round = replay.completed.map_or(1, |k| k + 1);
    // G3a：每实例轮次终态序列（在线窗口 = 本次执行的轮次），供健康评分
    let mut round_outcomes: HashMap<String, Vec<Option<bool>>> = HashMap::new();
    // G3b：gossip 水位记账（实例 → 实收 gossip 消息数）
    let mut gossip_sent: HashMap<String, usize> = HashMap::new();
    // G4b：全局消息 seq（单调）与实例消费水位
    let mut global_seq: u64 = replay.replayed_seq;
    let mut watermarks: HashMap<String, u64> = HashMap::new();
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
    let mut recalc_checked: u64 = 0;
    let mut recalc_mismatches: u64 = 0;

    if replay.completed.is_some() && start_round > rounds {
        // 目标轮数已全部持久化完成：不重启实例直接聚合（恢复幂等口径）。
        // 本会话无在线执行窗口 → round_outcomes 空 → health 为空对象。
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
        ));
    }

    let mut wal = if replay.completed.is_some() {
        // 恢复模式：好行重写（物理截断坏尾）→ append 续跑
        let mut f =
            std::fs::File::create(wal_path).map_err(|e| format!("WAL 打开失败: {e}"))?;
        for line in &replay.kept_lines {
            f.write_all(line.as_bytes())
                .map_err(|e| format!("WAL 重写失败: {e}"))?;
            f.write_all(b"\n").map_err(|e| format!("WAL 重写失败: {e}"))?;
        }
        f.flush().map_err(|e| format!("WAL flush 失败: {e}"))?;
        f.sync_all().map_err(|e| format!("WAL sync 失败: {e}"))?;
        std::fs::OpenOptions::new()
            .append(true)
            .open(wal_path)
            .map_err(|e| format!("WAL 追加打开失败: {e}"))?
    } else {
        std::fs::File::create(wal_path).map_err(|e| format!("WAL 创建失败: {e}"))?
    };

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
        // G-R3：verifier 本轮改为重放 primary 输入（复算），自身收件箱顺延一轮不丢失
        let primary_inbox = if protocol_mode {
            round_inboxes.get(&primary_id).cloned().unwrap_or_default()
        } else {
            Default::default()
        };
        if protocol_mode {
            if let Some(own) = round_inboxes.get(&verifier_id) {
                if !own.is_empty() {
                    let slot = inboxes.entry(round + 1).or_default().entry(verifier_id.clone()).or_default();
                    for (from, pv) in own {
                        slot.insert(from.clone(), pv.clone());
                    }
                }
            }
        }
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
                        let has_inbox = !inbox_raw.is_empty();
                        let inbox: HashMap<String, String> = inbox_raw
                            .iter()
                            .map(|(k, (v, _))| (k.clone(), v.clone()))
                            .collect();
                        let max_seq = inbox_raw
                            .values()
                            .map(|(_, s)| *s)
                            .max()
                            .unwrap_or(0);
                        Some(s.spawn(move || {
                            let attempt =
                                p.run_round(round, &inbox).map(|st| (st, has_inbox, max_seq));
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
                                    p.run_round(round, &inbox)
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
                        let mut sig = Event {
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
                let ev = Event {
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
                        let ev = Event {
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
                        let slot = inboxes
                            .entry(round + 1)
                            .or_default()
                            .entry(ev.to_id.clone())
                            .or_default();
                        slot.insert(p.spec.id.clone(), (payload.clone(), global_seq));
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
                "{{\"ts\":{},\"from\":\"{}\",\"to\":\"{}\",\"type\":\"{}\",\"round\":{},\"level\":{},\"hmac\":\"{}\",\"payload\":{}}}\n",
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
            let mut sig = Event {
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
                "{{\"ts\":{},\"from\":\"{}\",\"to\":\"{}\",\"type\":\"{}\",\"round\":{},\"level\":{},\"hmac\":\"{}\",\"payload\":{}}}\n",
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
        let mut snap = Event {
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
            "{{\"ts\":{},\"from\":\"{}\",\"to\":\"{}\",\"type\":\"{}\",\"round\":{},\"level\":{},\"hmac\":\"{}\",\"payload\":{}}}\n",
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
