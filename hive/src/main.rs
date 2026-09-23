//! `hive` CLI：serve / submit / poll / kill / doctor。
//!
//! ```text
//! hive serve   [--jobs DIR] [--workers N]          # 常驻：扫描领取 + 并发执行
//! hive submit  (--spec FILE | -) [--jobs DIR]      # 提交任务（- = stdin JSON）
//! hive poll    [JOB_ID] [--jobs DIR]               # 查状态（无 id = 全部摘要）
//! hive kill    JOB_ID [--jobs DIR]                 # 写 kill 标志（worker 检测强杀）
//! hive doctor  [--jobs DIR]                        # serve 存活 / 任务统计 / 环境检查
//! ```
//!
//! 默认 jobs 目录：`HIVE_JOBS_DIR` env → `<exe>/../../../jobs`（即 `hive/jobs`）→ `./jobs`。
//! 统一输出单行 JSON（`{"ok":true,...}` / `{"ok":false,"error":"..."}`），
//! 对齐 mdcg-eval serve 的响应风格。

use hive::job;
use hive::json::{parse, Json};
use hive::scheduler::{self, ServeCfg};
use hive::spec;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;

fn main() {
    let code = run();
    std::process::exit(code);
}

fn err_json(e: impl std::fmt::Display) -> String {
    Json::Obj(vec![
        ("ok".to_string(), Json::Bool(false)),
        ("error".to_string(), Json::Str(e.to_string())),
    ])
    .to_json_string()
}

fn ok_json(fields: Vec<(&str, Json)>) -> String {
    let mut kv = vec![("ok".to_string(), Json::Bool(true))];
    for (k, v) in fields {
        kv.push((k.to_string(), v));
    }
    Json::Obj(kv).to_json_string()
}

/// jobs 目录解析：env HIVE_JOBS_DIR → exe 锚定 hive/jobs → ./jobs。
fn default_jobs() -> PathBuf {
    if let Ok(d) = std::env::var("HIVE_JOBS_DIR") {
        if !d.trim().is_empty() {
            return PathBuf::from(d);
        }
    }
    // exe 在 <hive>/target/release/ → 上溯两级 = <hive>/ → jobs
    if let Ok(exe) = std::env::current_exe() {
        if let Some(hive) = exe.parent().and_then(|p| p.parent()).and_then(|p| p.parent()) {
            if hive.file_name().map(|n| n == "hive").unwrap_or(false) {
                return hive.join("jobs");
            }
        }
    }
    PathBuf::from("jobs")
}

/// exec.py 路径：env HIVE_EXEC_PY → exe 锚定 hive/exec.py → ./exec.py。
fn default_exec_py() -> PathBuf {
    if let Ok(p) = std::env::var("HIVE_EXEC_PY") {
        if !p.trim().is_empty() {
            return PathBuf::from(p);
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(hive) = exe.parent().and_then(|p| p.parent()).and_then(|p| p.parent()) {
            if hive.file_name().map(|n| n == "hive").unwrap_or(false) {
                return hive.join("exec.py");
            }
        }
    }
    PathBuf::from("exec.py")
}

fn arg_of(args: &[String], flag: &str) -> Option<String> {
    args.iter()
        .position(|a| a == flag)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

fn run() -> i32 {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = args.first() else {
        println!("{}", err_json("用法: hive <serve|submit|poll|kill|doctor> ..."));
        return 1;
    };
    let jobs = arg_of(&args, "--jobs")
        .map(PathBuf::from)
        .unwrap_or_else(default_jobs);

    match cmd.as_str() {
        "serve" => cmd_serve(&args, jobs),
        "submit" => cmd_submit(&args, jobs),
        "poll" => cmd_poll(&args, jobs),
        "kill" => cmd_kill(&args, jobs),
        "doctor" => cmd_doctor(jobs),
        other => {
            println!("{}", err_json(format!("未知子命令 {other}")));
            1
        }
    }
}

/// serve 心跳新鲜窗口（毫秒）——**必须与 `serve_start.py` 的 `FRESH_S = 15` 同口径**。
/// 两面用同一窗口判「serve 是否在跑」，否则同一个 serve 会得到两个结论
/// （本仓曾出现 CLI doctor 5000ms vs serve_start 15000ms 的真实口径冲突）。
const FRESH_MS: f64 = 15_000.0;

/// 单实例判据：心跳新鲜 **且** pid 存活 **且** 该 pid 是本程序（与
/// `serve_start.serve_alive()` 同口径）。返回在跑 serve 的 pid。
///
/// 第三层是 2026-09-17 第三方 v13 实测补上的：原判据只问「pid 号是否活着」，
/// 无关进程（如 sleep）复用该 pid 号即让 serve 被「假存活」挡住拒绝启动。
/// 三层缺一不可，且**三层都只说明「疑似在跑」，不构成授权**。
fn serve_running(jobs: &PathBuf) -> Option<u32> {
    let hb = job::read_serve_heartbeat(jobs)?;
    let ts = hb.get("ts").and_then(|x| x.as_f64()).unwrap_or(0.0);
    if job::now_ms() as f64 - ts >= FRESH_MS {
        return None;
    }
    hb.get("pid")
        .and_then(|x| x.as_f64())
        .map(|f| f as u32)
        .filter(|p| pid_alive(*p) && pid_is_self_program(*p))
}

fn cmd_serve(args: &[String], jobs: PathBuf) -> i32 {
    let workers = arg_of(args, "--workers")
        .and_then(|w| w.parse::<usize>().ok())
        .unwrap_or_else(|| {
            std::env::var("HIVE_WORKERS")
                .ok()
                .and_then(|w| w.parse::<usize>().ok())
                .unwrap_or(4)
        });
    // 单实例守卫：同一 jobs 目录至多一个 serve。CLI 裸起 serve 曾无此检查，与
    // `serve_start.start()`（有检查）形成「同一约束两种执行结果」的口径冲突——
    // 双实例会互覆 `_serve.json` 致 pid 判据漂移，`--stop` 只杀得掉一个。
    if !args.iter().any(|a| a == "--force") {
        if let Some(pid) = serve_running(&jobs) {
            println!(
                "{}",
                err_json(format!(
                    "serve 已在运行（pid={pid}，已核对进程身份）——同一 jobs 目录至多一个 serve。\
                     先 `python hive/serve_start.py --stop`；若确认无 serve 在跑（如心跳残留）请加 --force"
                ))
            );
            return 1;
        }
    }
    let exec_py = default_exec_py();
    // 执行器资格自检：env 未给 HIVE_EXEC_PY 时回退 exec.py（仅 LLM 委托），确定性执行
    // （spec.command / commands / orchestrate）在本 serve 上不可用。这正是「CLI 裸起
    // serve」与「MCP 拉起（serve_start 读 config.local.json 注入完整 env）」的能力差异
    // 点——**显式告警，不允许静默残缺**（静默残缺的后果是以为在跑确定性任务、实际走了
    // LLM 路径烧 token）。
    if std::env::var("HIVE_EXEC_PY")
        .map(|v| v.trim().is_empty())
        .unwrap_or(true)
    {
        eprintln!(
            "[hive serve] 警告：HIVE_EXEC_PY 未设置，执行器回退 {}（llm_only）——\
             确定性执行不可用。正路是 `python hive/serve_start.py`（读 config.local.json）；\
             或显式设 HIVE_EXEC_PY=<hive>/exec_cmd.py",
            exec_py.display()
        );
    }
    let cfg = ServeCfg::new(jobs, workers, exec_py).with_interop_identity();
    let stop = Arc::new(AtomicBool::new(false));
    // Ctrl+C 简易处理：不挂 handler（零依赖下跨平台信号处理受限），
    // 进程被终止时 claimed/running 由下次启动的 recover_orphans 清理。
    scheduler::serve(&cfg, stop)
}

fn cmd_submit(args: &[String], jobs: PathBuf) -> i32 {
    let text = match arg_of(args, "--spec") {
        Some(f) => std::fs::read_to_string(&f).unwrap_or_else(|e| {
            println!("{}", err_json(format!("读 spec 文件失败: {e}")));
            String::new()
        }),
        None => {
            let mut buf = String::new();
            use std::io::Read;
            let _ = std::io::stdin().read_to_string(&mut buf);
            buf
        }
    };
    if text.trim().is_empty() {
        return 1;
    }
    let v = match parse(&text) {
        Ok(v) => v,
        Err(e) => {
            println!("{}", err_json(format!("spec JSON 非法: {e}")));
            return 1;
        }
    };
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let sp = match spec::validate(&v, &cwd) {
        Ok(s) => s,
        Err(e) => {
            println!("{}", err_json(e));
            return 1;
        }
    };
    // 依赖完整检查（I-1）：depends_on 引用的任务必须已存在（提交侧 fail fast；
    // 无环性由 job_id 时间序结构性保证，见 scheduler::deps_gate 注释）
    let deps = v
        .get("depends_on")
        .map(|x| x.as_str_vec())
        .unwrap_or_default();
    for dep in &deps {
        if !jobs.join(dep).is_dir() {
            println!(
                "{}",
                err_json(format!(
                    "依赖不完整: {dep}（任务不存在，先提交上游任务）"
                ))
            );
            return 1;
        }
    }
    match job::init_job(&jobs, &v, sp.timeout_s) {
        Ok(id) => {
            println!(
                "{}",
                ok_json(vec![
                    ("job_id", Json::Str(id)),
                    ("jobs_dir", Json::Str(jobs.to_string_lossy().to_string())),
                    (
                        "hint",
                        Json::Str("poll 查状态；done 后读 result.json".into())
                    ),
                ])
            );
            0
        }
        Err(e) => {
            println!("{}", err_json(e));
            1
        }
    }
}

/// result 摘要（content 截断到 head 字符，防控制台/MCP 上下文爆炸）。
///
/// 交接面透出（v0.4 §5.3 换人续跑）：exec.py 达预算交回时写
/// `need_continue=true` + `completed=false` + `handoff` 卡——旧版此摘要只白名单
/// 抽 content/usage/result_path，把交接信号丢在 result.json 里，主代理 CLI
/// poll 面看不见、无法裁决续跑。故此处透出交接四字段 + 派生 handoff_ready
/// （need_continue==true 且 completed!=true，一眼可判；原始字段仍如实透传，
/// 缺失=Null 以区分「旧执行器/未标」与「显式 false」）。
fn result_summary(dir: &std::path::Path, head: usize) -> Json {
    let p = dir.join("result.json");
    if !p.is_file() {
        return Json::Null;
    }
    match job::read_json(&p) {
        Ok(r) => {
            let content = r.get("content").and_then(|v| v.as_str()).unwrap_or("");
            let truncated = content.chars().count() > head;
            let cut: String = content.chars().take(head).collect();
            let g = |k: &str| r.get(k).cloned().unwrap_or(Json::Null);
            let need = matches!(r.get("need_continue"), Some(Json::Bool(true)));
            let done = matches!(r.get("completed"), Some(Json::Bool(true)));
            Json::Obj(vec![
                ("content_head".to_string(), Json::Str(cut)),
                ("content_truncated".to_string(), Json::Bool(truncated)),
                (
                    "usage".to_string(),
                    r.get("usage").cloned().unwrap_or(Json::Null),
                ),
                (
                    "result_path".to_string(),
                    Json::Str(p.to_string_lossy().to_string()),
                ),
                ("completed".to_string(), g("completed")),
                ("need_continue".to_string(), g("need_continue")),
                (
                    "handoff_ready".to_string(),
                    Json::Bool(need && !done),
                ),
                ("handoff".to_string(), g("handoff")),
                ("tool_rounds".to_string(), g("tool_rounds")),
            ])
        }
        Err(e) => Json::Obj(vec![(
            "error".to_string(),
            Json::Str(format!("result.json 解析失败: {e}")),
        )]),
    }
}

fn one_job_view(jobs: &PathBuf, id: &str, head: usize) -> Json {
    let dir = job::job_dir(jobs, id);
    let mut view = match job::read_status(&dir) {
        Ok(st) => st,
        Err(e) => {
            return Json::Obj(vec![
                ("job_id".to_string(), Json::Str(id.to_string())),
                ("error".to_string(), Json::Str(e)),
            ])
        }
    };
    if let Json::Obj(kv) = &mut view {
        kv.push(("result".to_string(), result_summary(&dir, head)));
    }
    view
}

fn cmd_poll(args: &[String], jobs: PathBuf) -> i32 {
    let target = args.get(1).filter(|a| !a.starts_with("--")).cloned();
    match target {
        Some(id) => {
            let v = one_job_view(&jobs, &id, usize::MAX / 4); // 单查给全量
            println!("{}", Json::Obj(vec![("ok".to_string(), Json::Bool(true)), ("job".to_string(), v)]).to_json_string());
        }
        None => {
            let ids = job::list_jobs(&jobs);
            let items: Vec<Json> = ids.iter().map(|id| one_job_view(&jobs, id, 200)).collect();
            println!(
                "{}",
                Json::Obj(vec![
                    ("ok".to_string(), Json::Bool(true)),
                    ("count".to_string(), Json::Num(items.len() as f64)),
                    ("jobs".to_string(), Json::Arr(items)),
                ])
                .to_json_string()
            );
        }
    }
    0
}

fn cmd_kill(args: &[String], jobs: PathBuf) -> i32 {
    let Some(id) = args.get(1).filter(|a| !a.starts_with("--")) else {
        println!("{}", err_json("用法: hive kill <job_id>"));
        return 1;
    };
    let dir = job::job_dir(&jobs, id);
    if !dir.is_dir() {
        println!("{}", err_json(format!("任务不存在: {id}")));
        return 1;
    }
    match job::request_kill(&dir) {
        Ok(()) => {
            println!(
                "{}",
                ok_json(vec![
                    ("job_id", Json::Str(id.clone())),
                    ("hint", Json::Str("worker 检测到 kill 标志后强杀（≤1s）".into())),
                ])
            );
            0
        }
        Err(e) => {
            println!("{}", err_json(e));
            1
        }
    }
}

/// Windows：查该 pid 的 tasklist 行 → (映像名, pid 字符串)。查不到 → None。
///
/// 用 `/FO CSV` 后**按列精确比对**，不用子串包含——旧实现 `输出.contains(pid 字符串)`
/// 会让 pid=441 被 4410 命中（假存活）。
#[cfg(target_os = "windows")]
fn tasklist_row(pid: u32) -> Option<(String, String)> {
    let mut cmd = std::process::Command::new("tasklist");
    cmd.args(["/FI", &format!("PID eq {pid}"), "/NH", "/FO", "CSV"]);
    // 同一「不弹终端」纪律：serve 自身无控制台，裸 spawn console 子程序会新建可见控制台
    hive::exec::hide_window(&mut cmd);
    let out = cmd.output().ok()?;
    let s = String::from_utf8_lossy(&out.stdout);
    for line in s.lines() {
        // CSV 形如 "hive.exe","1234","Console","1","12,345 K"
        let cols: Vec<&str> = line.split("\",\"").collect();
        if cols.len() >= 2 {
            let pid_s = cols[1].trim_matches('"').trim();
            if pid_s == pid.to_string() {
                return Some((cols[0].trim_matches('"').trim().to_string(), pid_s.to_string()));
            }
        }
    }
    None
}

/// PID **号**存活探测（Windows tasklist 精确列比对 / unix `kill -0`）。
/// 零依赖下失败不致命——doctor 同时以心跳新鲜度为主判据。
/// 注意：只回答「这个号有没有进程」，**不足以判定「serve 还在跑」**，见 `pid_is_self_program`。
fn pid_alive(pid: u32) -> bool {
    #[cfg(target_os = "windows")]
    {
        tasklist_row(pid).is_some()
    }
    #[cfg(not(target_os = "windows"))]
    {
        std::process::Command::new("kill")
            .args(["-0", &pid.to_string()])
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }
}

/// 该 pid 是否**就是本程序**（同映像名）——pid 号会被无关进程复用。
///
/// 2026-09-17 第三方 v13 实测缺陷（新发现 A）：单实例守卫原判据只问「pid 号是否
/// 存在」，任何无关进程（如 sleep）复用该 pid 号都会让 serve 被「假存活」挡住拒绝
/// 启动，且文案引导运维去停一个并不存在的 serve。故加一层身份核对：
/// Windows 取 tasklist 映像名列，unix 读 `/proc/<pid>/cmdline` 首个 token 的 basename。
///
/// 零依赖边界：拿不到映像名返回 false（宁可放行启动，也不误报「已有 serve 在跑」）
/// ——存活与新鲜仍由另两层判据把守（三层全真才判活）。
fn pid_is_self_program(pid: u32) -> bool {
    let me = std::env::current_exe()
        .ok()
        .and_then(|p| p.file_name().map(|s| s.to_string_lossy().to_lowercase()))
        .unwrap_or_default();
    if me.is_empty() {
        return false;
    }
    #[cfg(target_os = "windows")]
    {
        tasklist_row(pid)
            .map(|(name, _)| name.to_lowercase() == me)
            .unwrap_or(false)
    }
    #[cfg(not(target_os = "windows"))]
    {
        match std::fs::read(format!("/proc/{pid}/cmdline")) {
            Ok(b) => {
                let s = String::from_utf8_lossy(&b);
                let first = s.split('\0').next().unwrap_or("");
                std::path::Path::new(first)
                    .file_name()
                    .map(|x| x.to_string_lossy().to_lowercase() == me)
                    .unwrap_or(false)
            }
            Err(_) => false,
        }
    }
}

/// 无 serve 心跳时的执行器资格兜底：按本进程 env 推导，并**如实标注来源**
/// （`doctor_env_or_default` ≠ serve 自报值——判资格时应优先看 `exec_source`）。
fn fallback_exec() -> (String, String, &'static str) {
    let p = default_exec_py();
    let mode = scheduler::exec_mode_of(&p);
    (p.to_string_lossy().to_string(), mode, "doctor_env_or_default")
}

fn cmd_doctor(jobs: PathBuf) -> i32 {
    std::fs::create_dir_all(&jobs).ok();
    let now = job::now_ms();
    // 执行器资格：**优先采信 serve 自报（心跳），无心跳才回退本进程 env 推导**。
    // 跨进程 env 不可反查，故心跳是唯一权威来源；用本进程 env 判资格必得错位结论
    // （本仓真实案例：CLI 裸起 serve 的执行器是 exec.py，doctor 进程 env 里却有
    //  指向 exec_cmd.py 的 HIVE_EXEC_PY，据此判资格会把「llm_only」看成「兼跑命令」）。
    let (serve_alive, serve_info) = match job::read_serve_heartbeat(&jobs) {
        Some(v) => {
            let ts = v.get("ts").and_then(|x| x.as_f64()).unwrap_or(0.0);
            let fresh = now as f64 - ts < FRESH_MS; // 与 serve_start.FRESH_S 同口径
            let pid = v.get("pid").and_then(|x| x.as_f64()).map(|f| f as u32);
            let pid_ok = pid.map(pid_alive).unwrap_or(false);
            // 第三层身份判据（v13 新发现 A）：pid 号存活 ≠ serve 存活——号会被复用。
            let pid_identity = pid.map(pid_is_self_program).unwrap_or(false);
            (
                fresh && pid_ok && pid_identity,
                Json::Obj(vec![
                    ("pid".to_string(), pid.map(|p| Json::Num(p as f64)).unwrap_or(Json::Null)),
                    ("heartbeat_age_ms".to_string(), Json::Num(now as f64 - ts)),
                    ("fresh".to_string(), Json::Bool(fresh)),
                    // 判活三层分开透出：排障时一眼看出「过期」「pid 不存在」还是「pid 不是 serve」
                    ("pid_alive".to_string(), Json::Bool(pid_ok)),
                    ("pid_is_self_program".to_string(), Json::Bool(pid_identity)),
                    (
                        "workers".to_string(),
                        v.get("workers").cloned().unwrap_or(Json::Null),
                    ),
                    // 执行器资格（serve 启动时固化 → 权威；旧版本心跳无此键时为 null）
                    (
                        "exec_py".to_string(),
                        v.get("exec_py").cloned().unwrap_or(Json::Null),
                    ),
                    (
                        "exec_mode".to_string(),
                        v.get("exec_mode").cloned().unwrap_or(Json::Null),
                    ),
                ]),
            )
        }
        None => (false, Json::Null),
    };

    // 顶层执行器资格汇总 + 来源标注（诚实：心跳缺失时说明是推导值而非 serve 自报值）。
    let (exec_py_eff, exec_mode_eff, exec_source) = match &serve_info {
        Json::Obj(kv) => {
            let f = |k: &str| {
                kv.iter()
                    .find(|(kk, _)| kk == k)
                    .and_then(|(_, v)| v.as_str())
                    .map(|s| s.to_string())
            };
            match f("exec_py") {
                Some(p) => (
                    p,
                    f("exec_mode").unwrap_or_else(|| "unknown".into()),
                    "serve_heartbeat",
                ),
                None => fallback_exec(),
            }
        }
        _ => fallback_exec(),
    };

    let mut counts: Vec<(String, u64)> = Vec::new();
    for id in job::list_jobs(&jobs) {
        let st = job::read_status(&job::job_dir(&jobs, &id));
        let state = st
            .ok()
            .and_then(|s| s.get("state").and_then(|v| v.as_str()).map(|x| x.to_string()))
            .unwrap_or_else(|| "unknown".into());
        match counts.iter_mut().find(|(k, _)| *k == state) {
            Some((_, c)) => *c += 1,
            None => counts.push((state, 1)),
        }
    }
    let counts_json: Vec<Json> = counts
        .into_iter()
        .map(|(k, c)| {
            Json::Obj(vec![
                ("state".to_string(), Json::Str(k)),
                ("count".to_string(), Json::Num(c as f64)),
            ])
        })
        .collect();

    println!(
        "{}",
        ok_json(vec![
            ("serve_alive", Json::Bool(serve_alive)),
            ("serve", serve_info),
            ("jobs_dir", Json::Str(jobs.to_string_lossy().to_string())),
            ("task_states", Json::Arr(counts_json)),
            // 执行器资格（判「本 serve 能否跑确定性任务」看这三项，**不看**下面的 env）
            ("exec_py", Json::Str(exec_py_eff)),
            ("exec_mode", Json::Str(exec_mode_eff)),
            ("exec_source", Json::Str(exec_source.into())),
            (
                "exec_note",
                Json::Str(
                    "exec_mode 判据=执行器文件名（exec_cmd.py=多态转发：带 command 跑命令、\
                     不带转 LLM；其余=仅 LLM 委托）。确证正路：提交带 command 的探针任务，\
                     result.content 以「确定性执行」开头即证明。"
                        .into(),
                ),
            ),
            (
                "env",
                Json::Obj(vec![
                    (
                        "note".to_string(),
                        Json::Str(
                            "本块=doctor 进程自身 env，**仅诊断**；它不是 serve 的 env。\
                             判 serve 资格请看上面的 exec_py/exec_mode（serve 自报）。"
                                .into(),
                        ),
                    ),
                    (
                        "api_key_set".to_string(),
                        Json::Bool(std::env::var("HIVE_API_KEY").map(|v| !v.is_empty()).unwrap_or(false)),
                    ),
                    (
                        "api_base".to_string(),
                        Json::Str(
                            std::env::var("HIVE_API_BASE")
                                .unwrap_or_else(|_| "https://open.bigmodel.cn/api/paas/v4".into()),
                        ),
                    ),
                    (
                        "workers".to_string(),
                        Json::Str(
                            std::env::var("HIVE_WORKERS").unwrap_or_else(|_| "4".into()),
                        ),
                    ),
                ]),
            ),
            (
                "start_cmd",
                Json::Str(
                    "python hive/serve_start.py（唯一推荐：读 config.local.json 注入完整 env）。\
                     裸 `hive serve` 不读配置——执行器回退 exec.py（llm_only），确定性执行不可用。"
                        .into(),
                ),
            ),
        ])
    );
    0
}

// ------------------------------------------------------------------ 单元测试

#[cfg(test)]
mod tests {
    use super::*;

    /// 唯一临时目录（std 无 tempdir；标签+pid+纳秒防并行同名）。
    fn tmpdir(tag: &str) -> PathBuf {
        let mut p = std::env::temp_dir();
        let ns = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        p.push(format!("hive_main_{}_{}_{}", tag, std::process::id(), ns));
        std::fs::create_dir_all(&p).expect("建临时目录");
        p
    }

    /// 存活判据第三层（v13 新发现 A）：pid 号存活 ≠ serve 存活。
    ///
    /// 正向：本进程映像名就是 current_exe → 身份层判真。
    /// 反向：拿一个必然存在但**不是本程序**的 pid 探测（Windows PID 4 = System；
    /// unix PID 1 = init）→ 必须判假，否则无关进程复用 pid 号就能冒充 serve
    /// （单实例守卫误挡启动的根因）。
    #[test]
    fn pid_identity_layer_rejects_foreign_process() {
        assert!(pid_alive(std::process::id()), "本进程必须判存活");
        assert!(
            pid_is_self_program(std::process::id()),
            "本进程映像名 == current_exe → 身份层须判真"
        );
        #[cfg(target_os = "windows")]
        let foreign = 4u32; // System：必然存在，映像名非 hive
        #[cfg(not(target_os = "windows"))]
        let foreign = 1u32; // init：必然存在，cmdline 非本 exe
        if pid_alive(foreign) {
            assert!(
                !pid_is_self_program(foreign),
                "无关进程不得被判成 serve（v13：pid 号复用致假存活）"
            );
        }
        assert!(!pid_alive(999_999), "超大 pid 号应为不存在");
    }

    /// 交回卡（达预算换人续跑）：交接四字段 + handoff_ready 派生须透出。
    #[test]
    fn result_summary_exposes_handoff() {
        let d = tmpdir("handoff");
        let body = concat!(
            r#"{"job_id":"j1","content":"进展摘要","completed":false,"#,
            r#""need_continue":true,"tool_rounds":12,"#,
            r#""handoff":{"steps_done":7,"next":"继续对齐 wm 白名单"},"#,
            r#""usage":{"total_tokens":200000}}"#
        );
        std::fs::write(d.join("result.json"), body).unwrap();
        let s = result_summary(&d, 1000);
        assert_eq!(s.get("need_continue"), Some(&Json::Bool(true)));
        assert_eq!(s.get("completed"), Some(&Json::Bool(false)));
        assert_eq!(s.get("handoff_ready"), Some(&Json::Bool(true)));
        assert_eq!(s.get("tool_rounds"), Some(&Json::Num(12.0)));
        assert_eq!(
            s.get("handoff").and_then(|h| h.get("steps_done")),
            Some(&Json::Num(7.0))
        );
        assert_eq!(
            s.get("handoff").and_then(|h| h.get("next")).and_then(|v| v.as_str()),
            Some("继续对齐 wm 白名单")
        );
        assert_eq!(
            s.get("usage").and_then(|u| u.get("total_tokens")),
            Some(&Json::Num(200000.0))
        );
        std::fs::remove_dir_all(&d).ok();
    }

    /// 正常终态：completed=true → handoff_ready=false（不误报需要续跑）。
    #[test]
    fn result_summary_completed_is_not_handoff() {
        let d = tmpdir("done");
        std::fs::write(
            d.join("result.json"),
            r#"{"content":"done","completed":true,"need_continue":false}"#,
        )
        .unwrap();
        let s = result_summary(&d, 1000);
        assert_eq!(s.get("handoff_ready"), Some(&Json::Bool(false)));
        assert_eq!(s.get("need_continue"), Some(&Json::Bool(false)));
        std::fs::remove_dir_all(&d).ok();
    }

    /// 旧执行器/未标字段：如实透传 Null，不伪造 false（区分「未标」与「显式否」）。
    #[test]
    fn result_summary_missing_fields_stay_null() {
        let d = tmpdir("legacy");
        std::fs::write(d.join("result.json"), r#"{"content":"legacy"}"#).unwrap();
        let s = result_summary(&d, 1000);
        assert_eq!(s.get("need_continue"), Some(&Json::Null));
        assert_eq!(s.get("completed"), Some(&Json::Null));
        assert_eq!(s.get("handoff"), Some(&Json::Null));
        assert_eq!(s.get("handoff_ready"), Some(&Json::Bool(false)));
        std::fs::remove_dir_all(&d).ok();
    }

    /// content 超 head 截断 + 标记；无 result.json → Null。
    #[test]
    fn result_summary_truncates_and_handles_absent() {
        let d = tmpdir("clip");
        std::fs::write(
            d.join("result.json"),
            r#"{"content":"abcdefghij","completed":true}"#,
        )
        .unwrap();
        let s = result_summary(&d, 4);
        assert_eq!(
            s.get("content_head").and_then(|v| v.as_str()),
            Some("abcd")
        );
        assert_eq!(s.get("content_truncated"), Some(&Json::Bool(true)));
        let empty = tmpdir("absent");
        assert_eq!(result_summary(&empty, 100), Json::Null);
        std::fs::remove_dir_all(&d).ok();
        std::fs::remove_dir_all(&empty).ok();
    }
}
