//! main.rs · 智能论字节码 Rust 原生执行入口
//! program.pbc 由 swarm/rust_codegen.py 编译期嵌入（include_bytes!）。
//! 用法：
//!   protocol_vm                       空初始环境执行
//!   protocol_vm --trust 0.5           初始信任值
//!   protocol_vm --symbols '{"计数":0}' 初始符号表（JSON 对象）
//!   protocol_vm --serve               VM 实例化多轮模式（蜂群实例基座，
//!                                     stdin 逐行请求 → stdout 逐行终态）
//!   protocol_vm swarm --config swarm.json [--wal events.jsonl]
//!                                     蜂群协调器（多进程：spawn N 实例 +
//!                                     事件路由 + WAL + ACK + 信任聚合）
//! 输出：终态 JSON（与 Python ConditionVM.run() 返回结构同构）——
//!   双后端语义等价验收即对照此输出。

use std::collections::HashMap;
use std::process::ExitCode;

use protocol_vm::{load_program, pbc, serve, swarm, vm};
use vm::{Value, VM};

/// 载入并反序列化字节码：显式 `--pbc` 路径优先，其次编译期嵌入。
fn load_code(pbc_path: Option<&str>) -> Result<Vec<pbc::Instr>, String> {
    let bytes = load_program(pbc_path)?;
    pbc::deserialize(&bytes)
}

/// 单次执行的初始环境：`(符号表, 信任值, 字节码路径)`。
type Env = (HashMap<String, Value>, f64, Option<String>);

fn parse_env(args: &[String]) -> Result<Env, String> {
    let mut symbols = HashMap::new();
    let mut trust = 0.0f64;
    let mut pbc_path: Option<String> = None;
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--trust" => {
                i += 1;
                trust = args
                    .get(i)
                    .and_then(|s| s.parse().ok())
                    .ok_or("--trust 需数值参数")?;
            }
            "--symbols" => {
                i += 1;
                let raw = args.get(i).ok_or("--symbols 需 JSON 参数")?;
                symbols = parse_symbols_json(raw)?;
            }
            "--pbc" => {
                i += 1;
                pbc_path = Some(args.get(i).ok_or("--pbc 需文件路径")?.clone());
            }
            other => return Err(format!("未知参数 {other}")),
        }
        i += 1;
    }
    Ok((symbols, trust, pbc_path))
}

/// 取 `--pbc <值>`（不改动 argv；供 `--serve` / `swarm` 分支复用）。
fn take_pbc(args: &[String]) -> Option<String> {
    let mut i = 0;
    while i + 1 < args.len() {
        if args[i] == "--pbc" {
            return Some(args[i + 1].clone());
        }
        i += 1;
    }
    None
}

/// 极简 JSON 对象解析（仅支持 {"名": 数值|字符串|true|false|null}——符号表初始环境足够）
fn parse_symbols_json(raw: &str) -> Result<HashMap<String, Value>, String> {
    let s = raw.trim();
    if !s.starts_with('{') || !s.ends_with('}') {
        return Err("符号表 JSON 须为对象".into());
    }
    let inner = &s[1..s.len() - 1];
    let mut map = HashMap::new();
    let mut pos = 0usize;
    let bytes = inner.as_bytes();
    while pos < bytes.len() {
        // 跳过逗号与空白
        while pos < bytes.len() && (bytes[pos] == b',' || bytes[pos].is_ascii_whitespace()) {
            pos += 1;
        }
        if pos >= bytes.len() {
            break;
        }
        // 键：字符串
        if bytes[pos] != b'"' {
            return Err("符号表键须为字符串".into());
        }
        let (key, next) = parse_json_string(inner, pos)?;
        pos = next;
        while pos < bytes.len() && bytes[pos].is_ascii_whitespace() {
            pos += 1;
        }
        if pos >= bytes.len() || bytes[pos] != b':' {
            return Err("符号表缺 ':'".into());
        }
        pos += 1;
        while pos < bytes.len() && bytes[pos].is_ascii_whitespace() {
            pos += 1;
        }
        let (value, next) = parse_json_scalar(inner, pos)?;
        map.insert(key, value);
        pos = next;
    }
    Ok(map)
}

fn parse_json_string(s: &str, start: usize) -> Result<(String, usize), String> {
    let b = s.as_bytes();
    let mut out = String::new();
    let mut i = start + 1;
    while i < b.len() {
        match b[i] {
            b'"' => return Ok((out, i + 1)),
            b'\\' => {
                i += 1;
                match b.get(i) {
                    Some(b'"') => out.push('"'),
                    Some(b'\\') => out.push('\\'),
                    Some(b'n') => out.push('\n'),
                    Some(b't') => out.push('\t'),
                    _ => return Err("不支持的转义".into()),
                }
            }
            _ => {
                let ch = s[i..].chars().next().ok_or("UTF-8 截断")?;
                out.push(ch);
                i += ch.len_utf8() - 1;
            }
        }
        i += 1;
    }
    Err("字符串未闭合".into())
}

fn parse_json_scalar(s: &str, start: usize) -> Result<(Value, usize), String> {
    let b = s.as_bytes();
    let end = start
        + s[start..]
            .find([',', '}'])
            .unwrap_or(s.len() - start);
    let raw = s[start..end].trim();
    if raw.is_empty() {
        return Err("空标量".into());
    }
    let v = if raw.starts_with('"') {
        let (s2, _) = parse_json_string(s, start)?;
        Value::Str(s2)
    } else if raw == "true" {
        Value::Bool(true)
    } else if raw == "false" {
        Value::Bool(false)
    } else if raw == "null" {
        Value::Null
    } else if let Ok(i) = raw.parse::<i64>() {
        Value::Int(i)
    } else {
        Value::Float(raw.parse::<f64>().map_err(|_| format!("非法数值 {raw}"))?)
    };
    let _ = b;
    Ok((v, end))
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();

    // ---- 子命令分发：serve / swarm / 默认单次执行 ----
    if args.get(1).map(String::as_str) == Some("--serve") {
        let code = match load_code(take_pbc(&args).as_deref()) {
            Ok(c) => c,
            Err(e) => {
                eprintln!(".pbc 载入失败: {e}");
                return ExitCode::from(2);
            }
        };
        let id = std::env::var("PROTOCOL_VM_INSTANCE").unwrap_or_else(|_| "无名实例".into());
        let rc = serve::serve(&code, &id);
        return if rc == 0 { ExitCode::SUCCESS } else { ExitCode::from(1) };
    }
    if args.get(1).map(String::as_str) == Some("swarm") {
        return cmd_swarm(&args[2..]);
    }

    let (symbols, trust, pbc_path) = match parse_env(&args) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("参数错误: {e}");
            return ExitCode::from(2);
        }
    };
    let code = match load_code(pbc_path.as_deref()) {
        Ok(c) => c,
        Err(e) => {
            eprintln!(".pbc 载入失败: {e}");
            return ExitCode::from(2);
        }
    };
    let mut vm = VM::new();
    // run() 将 止/无为(Halted) 归一为 Ok(带 halt 标记)，Err 仅剩真错误
    match vm.run(&code, symbols, trust, Vec::new(), 100_000) {
        Ok(st) => {
            println!("{}", vm::state_json(&st));
            ExitCode::SUCCESS
        }
        Err(vm::VmError::Halted(kind, st)) => {
            let mut st = *st;
            st.halt = Some(kind);
            println!("{}", vm::state_json(&st));
            ExitCode::SUCCESS
        }
        Err(vm::VmError::Error(e)) => {
            eprintln!("VM 执行错误: {e}");
            ExitCode::from(1)
        }
    }
}

/// swarm 子命令：配置 JSON → 多进程蜂群运行 → 报告 JSON
///
/// 配置格式（由 swarm/rust_swarm.py 生成）:
/// {
///   "shared_secret": "...", "rounds": 3,
///   "instances": [{"id":"实例甲","role":"worker","trust":0.1,"symbols":{...}}, ...],
///   "routes": [{"from":"实例甲","event_type":"信任同步","to":"实例乙",
///               "payload":"@trust", "level":0}]
/// }
fn cmd_swarm(args: &[String]) -> ExitCode {
    let mut config_path: Option<&String> = None;
    let mut wal_path = String::from("events.jsonl");
    let mut pbc_path: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--config" => {
                i += 1;
                config_path = args.get(i);
            }
            "--wal" => {
                i += 1;
                wal_path = args.get(i).cloned().unwrap_or(wal_path);
            }
            "--pbc" => {
                i += 1;
                pbc_path = args.get(i).cloned();
            }
            other => {
                eprintln!("swarm 未知参数 {other}");
                return ExitCode::from(2);
            }
        }
        i += 1;
    }
    let Some(cfg_path) = config_path else {
        eprintln!("swarm 需要 --config swarm.json");
        return ExitCode::from(2);
    };
    let raw = match std::fs::read_to_string(cfg_path) {
        Ok(r) => r,
        Err(e) => {
            eprintln!("配置读取失败: {e}");
            return ExitCode::from(2);
        }
    };
    let cfg_json = match swarm::serde_json_like::parse(&raw) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("配置 JSON 非法: {e}");
            return ExitCode::from(2);
        }
    };
    let secret = cfg_json
        .get("shared_secret")
        .and_then(|x| x.as_str())
        .unwrap_or("蜂群默认密钥")
        .to_string();
    let rounds = cfg_json
        .get("rounds")
        .and_then(|x| x.as_f64())
        .unwrap_or(1.0)
        .max(1.0) as u64;
    let mut instances = Vec::new();
    if let Some(swarm::serde_json_like::Value::List(items)) = cfg_json.get("instances") {
        for it in items {
            let id = it
                .get("id")
                .and_then(|x| x.as_str())
                .unwrap_or("无名实例")
                .to_string();
            let role = it
                .get("role")
                .and_then(|x| x.as_str())
                .unwrap_or("worker")
                .to_string();
            let trust = it.get("trust").and_then(|x| x.as_f64()).unwrap_or(0.0);
            let symbols_json = it
                .get("symbols")
                .map(swarm::serde_json_like::stringify)
                .unwrap_or_default();
            instances.push(swarm::InstanceSpec {
                id,
                role,
                trust,
                symbols_json,
            });
        }
    }
    if instances.is_empty() {
        eprintln!("配置无实例");
        return ExitCode::from(2);
    }
    let mut routes = Vec::new();
    if let Some(swarm::serde_json_like::Value::List(items)) = cfg_json.get("routes") {
        for it in items {
            routes.push(swarm::Route {
                from_id: it
                    .get("from")
                    .and_then(|x| x.as_str())
                    .unwrap_or("")
                    .to_string(),
                event_type: it
                    .get("event_type")
                    .and_then(|x| x.as_str())
                    .unwrap_or("消息")
                    .to_string(),
                to_id: it
                    .get("to")
                    .and_then(|x| x.as_str())
                    .unwrap_or("")
                    .to_string(),
                payload_json: it
                    .get("payload")
                    .map(swarm::serde_json_like::stringify)
                    .unwrap_or_else(|| "null".into()),
                level: it
                    .get("level")
                    .and_then(|x| x.as_f64())
                    .unwrap_or(0.0) as u8,
            });
        }
    }
    let exe = std::env::current_exe()
        .map(|p| p.display().to_string())
        .unwrap_or_else(|_| "protocol_vm".into());
    // G-R2 条件空间卡：声明即校验（四要素缺一不可 → 拒绝运行，负路由）
    let condition_space = match swarm::validate_condition_space(cfg_json.get("condition_space")) {
        Ok(cs) => cs,
        Err(e) => {
            eprintln!("条件空间卡校验失败: {e}");
            return ExitCode::from(2);
        }
    };
    let cfg = swarm::SwarmConfig {
        shared_secret: secret,
        instances,
        routes,
        // G4a 拓扑：缺省 "" = 未指定（角色保持用户声明）
        topology: cfg_json
            .get("topology")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string(),
        condition_space,
    };
    match swarm::run_swarm(&exe, &cfg, rounds, &wal_path, pbc_path.as_deref()) {
        Ok(rep) => {
            println!("{}", swarm::report_json(&rep));
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("蜂群运行失败: {e}");
            ExitCode::from(1)
        }
    }
}
