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

fn cmd_serve(args: &[String], jobs: PathBuf) -> i32 {
    let workers = arg_of(args, "--workers")
        .and_then(|w| w.parse::<usize>().ok())
        .unwrap_or_else(|| {
            std::env::var("HIVE_WORKERS")
                .ok()
                .and_then(|w| w.parse::<usize>().ok())
                .unwrap_or(4)
        });
    let cfg = ServeCfg::new(jobs, workers, default_exec_py());
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

/// PID 存活探测（尽力而为：Windows tasklist / unix kill -0 等价形态）。
/// 零依赖下失败不致命——doctor 同时以心跳新鲜度为主判据。
fn pid_alive(pid: u32) -> bool {
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/NH"])
            .output()
            .map(|o| {
                let s = String::from_utf8_lossy(&o.stdout);
                s.contains(&pid.to_string())
            })
            .unwrap_or(false)
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

fn cmd_doctor(jobs: PathBuf) -> i32 {
    std::fs::create_dir_all(&jobs).ok();
    let now = job::now_ms();
    let (serve_alive, serve_info) = match job::read_serve_heartbeat(&jobs) {
        Some(v) => {
            let ts = v.get("ts").and_then(|x| x.as_f64()).unwrap_or(0.0);
            let fresh = now as f64 - ts < 5000.0;
            let pid = v.get("pid").and_then(|x| x.as_f64()).map(|f| f as u32);
            let pid_ok = pid.map(pid_alive).unwrap_or(false);
            (
                fresh && pid_ok,
                Json::Obj(vec![
                    ("pid".to_string(), pid.map(|p| Json::Num(p as f64)).unwrap_or(Json::Null)),
                    ("heartbeat_age_ms".to_string(), Json::Num(now as f64 - ts)),
                    ("fresh".to_string(), Json::Bool(fresh)),
                    (
                        "workers".to_string(),
                        v.get("workers").cloned().unwrap_or(Json::Null),
                    ),
                ]),
            )
        }
        None => (false, Json::Null),
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
            (
                "env",
                Json::Obj(vec![
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
                Json::Str("hive serve（或 cargo run -p lingshu-hive -- serve）".into()),
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
