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
use std::path::{Path, PathBuf};
use std::sync::atomic::AtomicBool;
use std::sync::Arc;

/// 生效条件（CLI 入口）：进程退出码 = run() 的返回——0 全部成功、1 用法/失败。
fn main() {
    let code = run();
    std::process::exit(code);
}

/// 生效条件：错误消息 → `{"ok":false,"error":<msg>}` JSON 文本（CLI 错误统一形态）。
fn err_json(e: impl std::fmt::Display) -> String {
    Json::Obj(vec![
        ("ok".to_string(), Json::Bool(false)),
        ("error".to_string(), Json::Str(e.to_string())),
    ])
    .to_json_string()
}

/// 生效条件：字段表 → `{"ok":true, ...fields}` JSON 文本（CLI 成功统一形态）。
fn ok_json(fields: Vec<(&str, Json)>) -> String {
    let mut kv = vec![("ok".to_string(), Json::Bool(true))];
    for (k, v) in fields {
        kv.push((k.to_string(), v));
    }
    Json::Obj(kv).to_json_string()
}

/// jobs 目录解析：env HIVE_JOBS_DIR → exe 锚定 hive/jobs → ./jobs。
/// 生效条件：--jobs 显式 → 取之；否则 exe 锚定（exe 在 <hive>/target/{debug,
/// release}/ 上溯至 <hive>/ → jobs）；再否则相对 "jobs"——三段回退链。
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
/// 生效条件：env HIVE_EXEC_PY 非空 → 取之；否则 exe 锚定 <hive>/exec.py；
/// 再否则相对 "exec.py"——三段回退（serve 启动时的执行器路径决策点）。
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

/// 生效条件：args 中出现 `--flag` 且存在下一参数 → Some(下一参数)；否则 None。
fn arg_of(args: &[String], flag: &str) -> Option<String> {
    args.iter()
        .position(|a| a == flag)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

/// 生效条件：子命令分派入口——serve/submit/poll/kill/doctor 五路；未知子命令
/// → err_json 退出 1；jobs 根 = --jobs > exe 锚定 > 相对 "jobs" 三段回退。
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
/// 生效条件：_serve.json 的 pid 存活且经 pid_is_self_program 核验同映像 →
/// Some(pid)；否则 None——单实例守卫的判据（pid 复用防护）。
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

/// 生效条件：serve 子命令——workers（--workers/env HIVE_WORKERS/缺省 4）、
/// 单实例守卫（serve_running 命中即拒绝，--force 可越）、执行器资格自检
/// （HIVE_EXEC_PY 缺失显式告警 llm_only 回退）齐备后进入 scheduler::serve
/// 阻塞主循环（退出码透传）。
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
    // P11 结果完整性锚（批次53）：密钥取 hive 既有配置/令牌面（serve_start 已把
    // config.local.json 注入本进程 env）。Some = 锚判据生效（stderr 显式声明，不静默）；
    // None = 锚判据不启用（零配置部署行为不变——但锚预期任务将按 fail-closed 判
    // needs_review，见 classify_result）。
    let result_key = hive::keyres::resolve_key_from_env();
    match &result_key {
        Some(k) => eprintln!(
            "[hive serve] 结果完整性锚：已启用（密钥来源=hive 既有配置/令牌面 env，\
             {} 字符）",
            k.chars().count()
        ),
        None => eprintln!(
            "[hive serve] 结果完整性锚：未启用（HIVE_ORCH_TOKEN / \
             HIVE_ORCH_TOKEN_FILE / HIVE_API_KEY 均缺）——锚预期任务将判 needs_review"
        ),
    }
    let cfg = ServeCfg::new(jobs, workers, exec_py)
        .with_result_key(result_key)
        .with_interop_identity();
    let stop = Arc::new(AtomicBool::new(false));
    // Ctrl+C 简易处理：不挂 handler（零依赖下跨平台信号处理受限），
    // 进程被终止时 claimed/running 由下次启动的 recover_orphans 清理。
    scheduler::serve(&cfg, stop)
}

/// P0-2 幂等键扫描（批次53）：jobs 目录内 status.json 带 `content_hash` 且
/// state ∈ {pending, claimed, running} 的最老任务 → Some(job_id)。
/// 读失败/无 hash（旧格式任务）/终态（done|error|timeout|killed）→ 跳过——
/// 终态不拦（重跑语义不变）、旧格式不参与去重（向后兼容）。
/// 生效条件：hash 给定 → 按 list_jobs 名升序（=提交时间序）扫描返回首个
/// 活跃同哈希任务；池空/全不匹配 → None。
fn find_active_by_hash(jobs: &Path, hash: &str) -> Option<String> {
    for id in job::list_jobs(jobs) {
        let st = match job::read_status(&job::job_dir(jobs, &id)) {
            Ok(s) => s,
            Err(_) => continue, // 坏/缺 status：不参与去重（无害跳过）
        };
        let h = match st.get("content_hash").and_then(|x| x.as_str()) {
            Some(h) => h,
            None => continue,
        };
        let active = match st.get("state").and_then(|x| x.as_str()) {
            Some(s) => matches!(s, "pending" | "claimed" | "running"),
            None => false,
        };
        if h == hash && active {
            return Some(id);
        }
    }
    None
}

/// 生效条件：--spec 文件或 stdin 给出 spec JSON → validate → init_job 落盘
/// → 打印 job_id；spec 非法/依赖缺失 → err_json 退出 1（fail fast 在进队列前）。
/// 锚预期（P11 批次53）：提交面解析到锚密钥时附带 result_nonce（响应
/// result_anchor=on），否则旧格式（result_anchor=off）——判据面差异显式透出。
/// 幂等键（P0-2 批次53）：spec canonical json（json.rs::to_canonical_string，
/// 键序/空白不敏感）的 sha256 为 content_hash——同哈希**活跃**任务存在时
/// 返回既有 job_id + deduplicated=true 不新建（响应新增 deduplicated/
/// content_hash 两字段）；终态任务不拦（重跑语义不变）。
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
    // P0-2 幂等键（批次53）：canonical json sha256 → 活跃同哈希任务去重。
    // 置于依赖检查之后：幂等不豁免 spec 合法性（无效 spec 照旧 fail fast）。
    let content_hash =
        hive::hmac::hex32(&hive::hmac::sha256(v.to_canonical_string().as_bytes()));
    if let Some(existing) = find_active_by_hash(&jobs, &content_hash) {
        println!(
            "{}",
            ok_json(vec![
                ("job_id", Json::Str(existing)),
                ("deduplicated", Json::Bool(true)),
                ("content_hash", Json::Str(content_hash)),
                ("jobs_dir", Json::Str(jobs.to_string_lossy().to_string())),
                (
                    "hint",
                    Json::Str("同内容活跃任务已在池（幂等去重不新建）；poll 查状态".into())
                ),
            ])
        );
        return 0;
    }
    // P11 结果完整性锚（批次53）：提交面解析到锚密钥（hive 既有配置/令牌面 env）
    // 即生成 nonce 落 status.json——任务自此声明锚预期（serve 侧校验见
    // scheduler::classify_result）。无密钥 = 旧格式提交（result_anchor=off，
    // 存量判据零变更）。锚开关在提交响应显式透出，不静默降级。
    let result_key = hive::keyres::resolve_key_from_env();
    let nonce = result_key.as_ref().map(|_| job::new_result_nonce());
    match job::init_job_with_anchor(&jobs, &v, sp.timeout_s, nonce.as_deref()) {
        Ok(id) => {
            // 幂等键落盘（init 后 patch 补写：不动 init_job 单写者写序契约；
            // 补写失败仅损去重能力不损任务本体——诚实取舍不回滚）。
            let _ = job::patch_status(
                &job::job_dir(&jobs, &id),
                vec![(
                    "content_hash".to_string(),
                    Json::Str(content_hash.clone()),
                )],
            );
            println!(
                "{}",
                ok_json(vec![
                    ("job_id", Json::Str(id)),
                    ("deduplicated", Json::Bool(false)),
                    ("content_hash", Json::Str(content_hash)),
                    ("jobs_dir", Json::Str(jobs.to_string_lossy().to_string())),
                    (
                        "result_anchor",
                        Json::Str(if nonce.is_some() { "on" } else { "off" }.into()),
                    ),
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
/// 生效条件：result.json 存在 → 摘要视图（ok 凭证 + content_head 截断/usage/
/// 交接四字段 +handoff_ready 派生）；不存在 → Json::Null；坏文件 → error 视图
/// （如实透出不静默）。
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
                // ok 凭证位（R02，批次58）：观测面此前只透 content/usage，凭证
                // 字段不可见——矛盾裁决（error 终态 × ok=true）无从在 poll 面成立。
                ("ok".to_string(), g("ok")),
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

/// 生效条件：job 存在 → status 全量 + result 摘要（head 截断）合体视图；
/// status 不可读 → 含 error 的最小视图（poll 的单查/列表共用渲染单元）。
/// 矛盾裁决（R02，批次58）：status.state=error 终态与 result.ok=true 并存时
/// 透出 conflict="late_result_after_error"——serve 被硬杀后 recover_orphans
/// 按无产物标 error（scheduler.rs），error 落入 `match _ => {}` 永不回看，孤儿
/// 执行器补写的 ok 产物遂与记账面矛盾固化。观测面不静默翻转 state、不静默吞
/// result：两张脸同屏 + 矛盾位显式置起，裁决权交给消费面（wm.py 凭证闸拒放行/
/// 主代理人工裁决）；其余状态组合不置位（done+ok 正常路径零扰动）。
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
        let summary = result_summary(&dir, head);
        let state_error = matches!(
            kv.iter().rev().find(|(k, _)| k == "state"),
            Some((_, Json::Str(s))) if s == "error"
        );
        if state_error && matches!(summary.get("ok"), Some(Json::Bool(true))) {
            kv.push((
                "conflict".to_string(),
                Json::Str("late_result_after_error".into()),
            ));
        }
        kv.push(("result".to_string(), summary));
    }
    view
}

/// 生效条件：目标 job_id 给定 → 单查全量视图；缺省 → 列出全部任务摘要视图
/// （head 截断防上下文爆炸）——拉取式观测面，不阻塞。
fn cmd_poll(args: &[String], jobs: PathBuf) -> i32 {
    let target = args.get(1).filter(|a| !a.starts_with("--")).cloned();
    match target {
        Some(id) => {
            // 路径穿越防线（2026-09-25 缺陷）：外部 job_id 先过结构闸再拼路径——
            // `poll ../victim` 曾因裸 join + is_dir 逃出 jobs 池，读回任意目录的
            // status/result 全文（单查 head=usize::MAX/4，全文透出）。
            if !job::valid_job_id(&id) {
                println!(
                    "{}",
                    err_json(format!("job_id 非法: {id}（须为 h 开头且不含路径成分）"))
                );
                return 1;
            }
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

/// 生效条件：目标 job_id 给定 → request_kill 写 kill 标志（幂等）并打印回执；
/// 缺目标 → 用法错误退出 1。
fn cmd_kill(args: &[String], jobs: PathBuf) -> i32 {
    let Some(id) = args.get(1).filter(|a| !a.starts_with("--")) else {
        println!("{}", err_json("用法: hive kill <job_id>"));
        return 1;
    };
    // 路径穿越防线（2026-09-25 缺陷）：`kill ..` 曾可在 jobs 池外创建 kill 文件
    // （is_dir 对 `..`/`../victim` 恒真，kill 文件名固定可投递到任意已存在目录）
    // ——结构闸先行，存在性检查在后。
    if !job::valid_job_id(id) {
        println!(
            "{}",
            err_json(format!("job_id 非法: {id}（须为 h 开头且不含路径成分）"))
        );
        return 1;
    }
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
/// 生效条件：Windows 下 tasklist /FI 查询 pid → Some((映像名, pid 列))（精确
/// 列比对防 pid 441 被 4410 命中——假存活）；查询失败 → None。
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
/// 生效条件：pid 在进程表中 → true；不存在/查询失败 → false（单实例判据的
/// 第一道：pid 存活性）。
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
/// 生效条件：pid 对应进程映像名与本程序一致 → true——pid 号会被无关进程
/// 复用，存活≠就是 serve（单实例守卫的第二道：映像核验）。
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
/// 生效条件：HIVE_EXEC_PY 缺失时兜底执行器（exe 锚定 hive/exec.py，仅 LLM
/// 委托），并按本进程 env 如实标注 exec_source（doctor_env_or_default ≠ serve
/// 自报值——判资格应优先读心跳的 exec_source）。
fn fallback_exec() -> (String, String, &'static str) {
    let p = default_exec_py();
    let mode = scheduler::exec_mode_of(&p);
    (p.to_string_lossy().to_string(), mode, "doctor_env_or_default")
}

/// 生效条件：零参数调用 → 输出 serve 存活性/任务状态分布/执行器资格三要素
/// （exec_py/exec_mode/exec_source——读心跳不读自身 env，跨进程 env 不可反查
/// 的既定口径）→ 诊断退出码。
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

    /// P0-2 幂等键（批次53）：活跃同哈希任务去重——命中/终态不拦/异哈希不拦。
    #[test]
    fn dedup_scan_active_only() {
        let jobs = tmpdir("dedup");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let canon = spec.to_canonical_string();
        let hash = hive::hmac::hex32(&hive::hmac::sha256(canon.as_bytes()));
        // 空池：无命中
        assert_eq!(find_active_by_hash(&jobs, &hash), None);
        // 活跃任务（pending + content_hash）：命中
        let id = job::init_job(&jobs, &spec, 60).unwrap();
        job::patch_status(
            &job::job_dir(&jobs, &id),
            vec![("content_hash".to_string(), Json::Str(hash.clone()))],
        )
        .unwrap();
        assert_eq!(find_active_by_hash(&jobs, &hash), Some(id.clone()));
        // 终态（done）：不拦（重跑语义不变）
        job::patch_status(
            &job::job_dir(&jobs, &id),
            vec![("state".to_string(), Json::Str("done".to_string()))],
        )
        .unwrap();
        assert_eq!(find_active_by_hash(&jobs, &hash), None);
        // 异哈希：不命中
        let other = hive::hmac::hex32(&hive::hmac::sha256(b"other"));
        assert_eq!(find_active_by_hash(&jobs, &other), None);
        std::fs::remove_dir_all(&jobs).ok();
    }

    /// 幂等键规范化：键序不同的同内容 spec → 同一 content_hash。
    #[test]
    fn content_hash_canonical_insensitive() {
        let a = parse(r#"{"model":"m","user_prompt":"x","timeout_s":60}"#).unwrap();
        let b = parse(r#"{ "user_prompt" : "x" , "timeout_s":60,"model":"m" }"#).unwrap();
        let ha = hive::hmac::hex32(&hive::hmac::sha256(a.to_canonical_string().as_bytes()));
        let hb = hive::hmac::hex32(&hive::hmac::sha256(b.to_canonical_string().as_bytes()));
        assert_eq!(ha, hb, "同内容异键序必须同哈希");
        let c = parse(r#"{"model":"m","user_prompt":"不同内容","timeout_s":60}"#).unwrap();
        let hc = hive::hmac::hex32(&hive::hmac::sha256(c.to_canonical_string().as_bytes()));
        assert_ne!(ha, hc, "不同内容必须不同哈希");
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

    /// R02 矛盾态守卫（批次58）：state=error 终态与孤儿执行器补写的
    /// result.ok=true 同屏时，poll 合体面必须透出矛盾裁决字段——
    /// 两张脸都如实保留（不静默翻转 state、不静默吞 result），由消费面
    /// （wm.py 凭证闸/主代理）裁决，而非观测面替天做主。
    #[test]
    fn one_job_view_flags_late_result_after_error() {
        let jobs = tmpdir("conflict");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let id = job::init_job(&jobs, &spec, 60).unwrap();
        let dir = job::job_dir(&jobs, &id);
        // 与 scheduler.rs recover_orphans 无产物分支逐字同字段：error 终态
        job::patch_status(
            &dir,
            vec![
                ("state".to_string(), Json::Str("error".into())),
                (
                    "error".to_string(),
                    Json::Str("serve 中断：任务执行被重置".into()),
                ),
            ],
        )
        .unwrap();
        // 孤儿执行器补写 ok=true 产物（attack 形态）
        std::fs::write(
            dir.join("result.json"),
            r#"{"ok":true,"content":"孤儿补写","completed":true}"#,
        )
        .unwrap();
        let v = one_job_view(&jobs, &id, 200);
        assert_eq!(
            v.get("conflict").and_then(|c| c.as_str()),
            Some("late_result_after_error"),
            "矛盾态必须透出 conflict 裁决字段"
        );
        // 不静默翻转：error 终态原样保留
        assert_eq!(v.get("state"), Some(&Json::Str("error".into())));
        // 不静默合体：补写产物原样透出（result.ok 可见，矛盾双方同屏可裁决）
        assert_eq!(
            v.get("result").and_then(|r| r.get("ok")),
            Some(&Json::Bool(true))
        );
        std::fs::remove_dir_all(&jobs).ok();
    }

    /// R02 负例面（不误报）：done+ok / error+ok=false / error+无产物 均非矛盾态。
    #[test]
    fn one_job_view_no_conflict_without_contradiction() {
        let jobs = tmpdir("noconflict");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        // 负例①：done 终态 + ok=true（正常成功路径）
        let id = job::init_job(&jobs, &spec, 60).unwrap();
        let dir = job::job_dir(&jobs, &id);
        job::patch_status(&dir, vec![("state".to_string(), Json::Str("done".into()))]).unwrap();
        std::fs::write(
            dir.join("result.json"),
            r#"{"ok":true,"content":"正常成功"}"#,
        )
        .unwrap();
        assert_eq!(one_job_view(&jobs, &id, 200).get("conflict"), None);
        // 负例②：error 终态 + ok=false（凭证门本来就会拒，无矛盾）
        let id2 = job::init_job(&jobs, &spec, 60).unwrap();
        let dir2 = job::job_dir(&jobs, &id2);
        job::patch_status(&dir2, vec![("state".to_string(), Json::Str("error".into()))]).unwrap();
        std::fs::write(dir2.join("result.json"), r#"{"ok":false,"error":"x"}"#).unwrap();
        assert_eq!(one_job_view(&jobs, &id2, 200).get("conflict"), None);
        // 负例③：error 终态 + 无产物（recover_orphans 刚标完、孤儿还没写完）
        let id3 = job::init_job(&jobs, &spec, 60).unwrap();
        let dir3 = job::job_dir(&jobs, &id3);
        job::patch_status(&dir3, vec![("state".to_string(), Json::Str("error".into()))]).unwrap();
        assert_eq!(one_job_view(&jobs, &id3, 200).get("conflict"), None);
        std::fs::remove_dir_all(&jobs).ok();
    }
}
