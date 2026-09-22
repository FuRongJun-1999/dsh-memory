//! 并发调度核心：领取 → worker 池执行 → 心跳 / 超时强杀 / kill → 终态。
//!
//! 零依赖并发模型（纯 std）：
//!   * 主循环（serve 线程）：扫描 pending 任务 → `claimed.lock` 原子领取 →
//!     投递 mpsc 队列；每拍写 serve 心跳（`_serve.json`）；
//!   * worker 池（`HIVE_WORKERS` 线程）：从共享队列领任务 → 拉起执行器
//!     子进程 → 1s 轮询（子进程退出 / kill 标志 / 超时）→ 写心跳与终态；
//!   * 停机语义（drain）：`stop` 置位后主循环停投、关闭队列；worker 把
//!     队列内已领任务跑完再退（最长一个 timeout_s）——不产孤儿，测试友好。
//!
//! 崩溃恢复：serve 启动时清理上次遗留——**产物说了算**（与 classify_exit 同判据，
//! 单一实现 `classify_result`）：claimed/running 若已有 result.json 则按产物定终态
//! done/error，不重跑；claimed 无产物删锁重投 pending；running 无产物诚实标 error
//! （其孤儿执行器若仍存活，写出的 result.json 宿主仍可读）。

use crate::exec;
use crate::job;
use crate::spec;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;

#[derive(Debug, Clone)]
pub struct ServeCfg {
    /// jobs 根目录。
    pub jobs: PathBuf,
    /// worker 并发度。
    pub workers: usize,
    /// 执行器脚本路径（默认 exec.py，测试可注入假执行器）。
    pub exec_py: PathBuf,
    /// 执行器形态（由 `exec_mode_of` 从 exec_py 推得，写进心跳供 doctor 判资格）。
    pub exec_mode: String,
    /// 主循环扫描间隔（毫秒）。
    pub poll_ms: u64,
}

/// 执行器形态判据：**文件名**（非内容探测，宁可保守）。
///
/// `exec_cmd.py` = 多态转发器——spec 带 command/commands 跑命令（零 LLM），
/// 不带时转发 exec.py（LLM 委托）；其余（含兜底 exec.py）= 仅 LLM 委托。
///
/// 诚实边界：这是启发式。确证形态的正路是提交一个带 `command` 的探针任务——
/// result.content 以「确定性执行」开头即证明该 serve 兼跑确定性任务。
pub fn exec_mode_of(exec_py: &Path) -> String {
    let stem = exec_py
        .file_stem()
        .map(|s| s.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    if stem == "exec_cmd" {
        "deterministic+llm".into()
    } else {
        "llm_only".into()
    }
}

impl ServeCfg {
    pub fn new(jobs: PathBuf, workers: usize, exec_py: PathBuf) -> Self {
        let exec_mode = exec_mode_of(&exec_py);
        ServeCfg {
            jobs,
            workers: workers.clamp(1, 64),
            exec_py,
            exec_mode,
            poll_ms: 400,
        }
    }
}

/// serve 主入口。阻塞直至 `stop` 置位且 worker drain 完毕。返回退出码。
pub fn serve(cfg: &ServeCfg, stop: Arc<AtomicBool>) -> i32 {
    std::fs::create_dir_all(&cfg.jobs).expect("建 jobs 目录失败");
    recover_orphans(cfg);

    let (tx, rx) = mpsc::channel::<String>();
    let rx = Arc::new(Mutex::new(rx));
    let mut handles = Vec::new();
    for _ in 0..cfg.workers {
        let rx = Arc::clone(&rx);
        let cfg = cfg.clone();
        handles.push(thread::spawn(move || loop {
            let id = { rx.lock().expect("worker 锁中毒").recv() };
            match id {
                Ok(id) => run_job(&cfg, &id),
                Err(_) => break, // 队列关闭且已清空 → worker 退出
            }
        }));
    }

    // 主循环：心跳 + 扫描领取
    while !stop.load(Ordering::SeqCst) {
        let _ = job::write_serve_heartbeat(&cfg.jobs, cfg.workers, &cfg.exec_py, &cfg.exec_mode);
        for id in job::list_jobs(&cfg.jobs) {
            let dir = job::job_dir(&cfg.jobs, &id);
            let st = match job::read_status(&dir) {
                Ok(s) => s,
                Err(_) => continue, // 正在写入的半成品 → 下拍再看
            };
            let state = st.get("state").and_then(|v| v.as_str()).unwrap_or("");
            if state != "pending" {
                continue;
            }
            // 依赖门禁（I-1）：全依赖 done 才领取；失败传播不执行
            match deps_gate(&cfg.jobs, &dir) {
                Err(reason) => {
                    let _ = job::patch_status(
                        &dir,
                        vec![
                            (
                                "state".to_string(),
                                crate::json::Json::Str("error".into()),
                            ),
                            (
                                "error".to_string(),
                                crate::json::Json::Str(reason),
                            ),
                        ],
                    );
                    continue;
                }
                Ok(false) => continue, // 有依赖未终态 → 等待
                Ok(true) => {}
            }
            if !job::claim(&dir) {
                continue; // 已被领取（原子锁失败）
            }
            let _ = job::patch_status(
                &dir,
                vec![("state".to_string(), crate::json::Json::Str("claimed".into()))],
            );
            if tx.send(id).is_err() {
                break; // worker 池已全部退出
            }
        }
        thread::sleep(Duration::from_millis(cfg.poll_ms));
    }

    drop(tx); // 关闭队列：worker 清空存量后自然退出（drain）
    for h in handles {
        let _ = h.join();
    }
    0
}

/// 崩溃恢复：**产物说了算**——claimed/running 先查 result.json（与 classify_exit
/// 同一判据、同一实现）；有产物按产物定终态，无产物才走旧路径（claimed 重投 /
/// running 标 error）。
///
/// 历史缺陷（2026-09-22 实锤，`D:\2_ai` C9/M1）：同一段代码两套判据——
/// `classify_exit`（正常退出）信产物，`recover_orphans`（崩溃恢复）不信产物——
/// serve 崩溃重启后，执行器已写完 result.json 的任务被重投重跑（claimed）或
/// 误标「serve 中断」（running）。修复 = 判据前移，不是引入新机制。
fn recover_orphans(cfg: &ServeCfg) {
    for id in job::list_jobs(&cfg.jobs) {
        let dir = job::job_dir(&cfg.jobs, &id);
        let Ok(st) = job::read_status(&dir) else { continue };
        let state = st.get("state").and_then(|v| v.as_str()).unwrap_or("");
        match state {
            "claimed" => match classify_result(&dir) {
                // 产物已产出 → 按产物定终态（删锁但绝不重投重跑）
                Some((final_state, err)) => {
                    let _ = std::fs::remove_file(dir.join("claimed.lock"));
                    let mut fields = vec![(
                        "state".to_string(),
                        crate::json::Json::Str(final_state),
                    )];
                    if let Some(e) = err {
                        fields.push(("error".to_string(), crate::json::Json::Str(e)));
                    }
                    let _ = job::patch_status(&dir, fields);
                }
                // 无产物 → 删锁回 pending 重投（原行为）
                None => {
                    let _ = std::fs::remove_file(dir.join("claimed.lock"));
                    let _ = job::patch_status(
                        &dir,
                        vec![(
                            "state".to_string(),
                            crate::json::Json::Str("pending".into()),
                        )],
                    );
                }
            },
            "running" => match classify_result(&dir) {
                // 孤儿执行器可能已写出产物 → 按产物定终态（不误标 serve 中断）
                Some((final_state, err)) => {
                    let mut fields = vec![(
                        "state".to_string(),
                        crate::json::Json::Str(final_state),
                    )];
                    if let Some(e) = err {
                        fields.push(("error".to_string(), crate::json::Json::Str(e)));
                    }
                    let _ = job::patch_status(&dir, fields);
                }
                // 无产物 → 诚实标 error（原行为）
                None => {
                    let _ = job::patch_status(
                        &dir,
                        vec![
                            (
                                "state".to_string(),
                                crate::json::Json::Str("error".into()),
                            ),
                            (
                                "error".to_string(),
                                crate::json::Json::Str("serve 中断：任务执行被重置".into()),
                            ),
                        ],
                    );
                }
            },
            _ => {}
        }
    }
}

/// worker 执行单个任务：拉起执行器 → 1s 轮询（退出 / kill / 超时）→ 终态。
fn run_job(cfg: &ServeCfg, id: &str) {
    let dir = job::job_dir(&cfg.jobs, id);

    // 读 spec（领取后重读校验：拿 timeout/model；坏 spec 直接 error 终态）
    let spec_json = match job::read_json(&dir.join("spec.json")) {
        Ok(v) => v,
        Err(e) => {
            let _ = job::patch_status(
                &dir,
                vec![
                    ("state".to_string(), crate::json::Json::Str("error".into())),
                    ("error".to_string(), crate::json::Json::Str(e)),
                ],
            );
            return;
        }
    };
    // worker 侧宽松校验（context 存在性 submit 已验；job 目录不是合法 base）
    let sp = match spec::validate_lenient(&spec_json) {
        Ok(s) => s,
        Err(e) => {
            let _ = job::patch_status(
                &dir,
                vec![
                    ("state".to_string(), crate::json::Json::Str("error".into())),
                    (
                        "error".to_string(),
                        crate::json::Json::Str(format!("spec 校验失败: {e}")),
                    ),
                ],
            );
            return;
        }
    };

    let started = job::now_ms();
    let _ = job::patch_status(
        &dir,
        vec![
            (
                "state".to_string(),
                crate::json::Json::Str("running".into()),
            ),
            ("started_ts".to_string(), crate::json::Json::Num(started as f64)),
            ("model".to_string(), crate::json::Json::Str(sp.model.clone())),
        ],
    );

    let mut child = match exec::spawn_executor(&cfg.exec_py, &dir) {
        Ok(c) => c,
        Err(e) => {
            let _ = job::patch_status(
                &dir,
                vec![
                    ("state".to_string(), crate::json::Json::Str("error".into())),
                    (
                        "error".to_string(),
                        crate::json::Json::Str(format!("拉起执行器失败: {e}")),
                    ),
                ],
            );
            return;
        }
    };
    let _ = job::patch_status(
        &dir,
        vec![("pid".to_string(), crate::json::Json::Num(child.id() as f64))],
    );

    let tick = Duration::from_millis(1000);
    let timeout = Duration::from_secs(sp.timeout_s);
    let t0 = std::time::Instant::now();
    let final_state: String;
    let mut final_err: Option<String> = None;

    loop {
        thread::sleep(tick);
        match child.try_wait() {
            Ok(Some(code)) => {
                let (state, err) = classify_exit(&dir, code);
                final_state = state;
                final_err = err;
                break;
            }
            Ok(None) => {
                if job::kill_requested(&dir) {
                    exec::kill_tree(&mut child); // 进程树回收（含孙进程），见 exec.rs
                    let _ = child.wait();
                    final_state = "killed".into();
                    break;
                }
                if t0.elapsed() >= timeout {
                    exec::kill_tree(&mut child); // 超时同样走进程树回收
                    let _ = child.wait();
                    final_state = "timeout".into();
                    break;
                }
                let _ = job::heartbeat(&dir, "running", started);
            }
            Err(_) => {
                final_state = "error".into();
                final_err = Some("子进程 wait 失败".into());
                break;
            }
        }
    }

    let mut fields = vec![
        ("state".to_string(), crate::json::Json::Str(final_state)),
        ("heartbeat_ts".to_string(), crate::json::Json::Num(job::now_ms() as f64)),
        (
            "elapsed_s".to_string(),
            crate::json::Json::Num(
                (t0.elapsed().as_millis() as f64 / 1000.0 * 100.0).round() / 100.0,
            ),
        ),
    ];
    if let Some(e) = final_err {
        fields.push(("error".to_string(), crate::json::Json::Str(e)));
    }
    let _ = job::patch_status(&dir, fields);
}

/// 产物判据（**唯一实现**）：读 result.json 定 (终态, error)。
/// 返回 None = 无产物文件；Some((state, err)) = 产物说了算（error 字段区分成败）。
/// `classify_exit`（正常退出）与 `recover_orphans`（崩溃恢复）共用——判据只此一处，
/// 勿再分叉出第二套（C9 根因即两套判据并存）。
fn classify_result(dir: &std::path::Path) -> Option<(String, Option<String>)> {
    let result_path = dir.join("result.json");
    if !result_path.is_file() {
        return None;
    }
    match job::read_json(&result_path) {
        Ok(r) => {
            let err = r
                .get("error")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            Some(match err {
                Some(e) => ("error".into(), Some(e)),
                None => ("done".into(), None),
            })
        }
        Err(e) => Some((
            "error".into(),
            Some(format!("result.json 解析失败: {e}")),
        )),
    }
}

/// 依赖门禁（I-1，中观任务 DAG 第一格）：
/// `Ok(true)` = 全依赖 done，可领取；`Ok(false)` = 有依赖未终态，等待；
/// `Err(原因)` = 依赖不完整或失败传播，任务直接终态 error（不执行）。
///
/// 七不变量对照（dsh-omc，设计稿 docs/hive/蜂巢迭代_宏观与群体调度_v0.1.md）：
/// 依赖完整 + 级联取消闭包在此落码；无环性由 job_id 时间序结构性保证
/// （无法引用提交时尚不存在的任务），无需运行时环检测。
fn deps_gate(jobs: &Path, dir: &Path) -> Result<bool, String> {
    let spec_json = match job::read_json(&dir.join("spec.json")) {
        Ok(v) => v,
        Err(_) => return Ok(true), // spec 读不到 → 交给领取路径的坏 spec 处理
    };
    let deps = match spec_json.get("depends_on").map(|x| x.as_str_vec()) {
        Some(d) if !d.is_empty() => d,
        _ => return Ok(true), // 无依赖 → 直接可领
    };
    for dep in deps {
        let ddir = jobs.join(&dep);
        if !ddir.is_dir() {
            return Err(format!("依赖不完整: {dep}（任务目录不存在）"));
        }
        let dst = job::read_status(&ddir)
            .map(|s| {
                s.get("state")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string()
            })
            .unwrap_or_default();
        match dst.as_str() {
            "done" => continue,
            "error" | "timeout" | "killed" => {
                return Err(format!("依赖失败传播: {dep} 终态 {dst}，本任务不执行"));
            }
            _ => return Ok(false), // pending/claimed/running → 等待
        }
    }
    Ok(true)
}

/// 子进程退出后的终态分类：以 result.json 为准（error 字段区分 API 错误）。
fn classify_exit(
    dir: &std::path::Path,
    code: std::process::ExitStatus,
) -> (String, Option<String>) {
    match classify_result(dir) {
        Some(x) => x,
        None if code.success() => (
            "error".into(),
            Some("执行器退出码 0 但未产出 result.json".into()),
        ),
        None => ("error".into(), Some(format!("执行器异常退出: {code}"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::parse;
    use std::fs;
    use std::path::PathBuf;

    /// 假执行器：sleep(user_prompt 浮点秒) 后写 result.json——测试专用语义。
    const FAKE_EXEC: &str = r#"
import sys, json, time, os
d = sys.argv[1]
with open(os.path.join(d, "spec.json"), encoding="utf-8") as f:
    spec = json.load(f)
time.sleep(float(spec.get("user_prompt") or 0))
with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
    json.dump({"ok": True, "content": "fake-ok", "usage": {"total_tokens": 1}}, f, ensure_ascii=False)
"#;

    fn tmpjobs(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("hive_sched_{tag}_{}", job::now_ms()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    fn write_fake_exec(dir: &PathBuf) -> PathBuf {
        let p = dir.join("fake_exec.py");
        fs::write(&p, FAKE_EXEC).unwrap();
        p
    }

    fn submit(jobs: &PathBuf, sleep_s: &str, timeout_s: u64) -> String {
        let spec = parse(&format!(
            r#"{{"model":"fake","user_prompt":"{sleep_s}","timeout_s":{timeout_s}}}"#
        ))
        .unwrap();
        job::init_job(jobs, &spec, timeout_s).unwrap()
    }

    fn read_state(jobs: &PathBuf, id: &str) -> String {
        let st = job::read_status(&job::job_dir(jobs, id)).unwrap();
        st.get("state").unwrap().as_str().unwrap().to_string()
    }

    #[test]
    fn e2e_done_and_heartbeat() {
        let tmp = tmpjobs("e2e");
        let jobs = tmp.join("jobs");
        let exec_py = write_fake_exec(&tmp);
        let a = submit(&jobs, "0.2", 60);
        let b = submit(&jobs, "0.2", 60);
        let cfg = ServeCfg::new(jobs.clone(), 2, exec_py);
        let stop = Arc::new(AtomicBool::new(false));
        let h = {
            let cfg = cfg.clone();
            let stop = Arc::clone(&stop);
            thread::spawn(move || serve(&cfg, stop))
        };
        let mut ok = false;
        for _ in 0..100 {
            if read_state(&jobs, &a) == "done" && read_state(&jobs, &b) == "done" {
                ok = true;
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        stop.store(true, Ordering::SeqCst);
        h.join().unwrap();
        assert!(ok, "任务未达 done");
        assert!(job::read_serve_heartbeat(&jobs).is_some());
        let r = job::read_json(&job::job_dir(&jobs, &a).join("result.json")).unwrap();
        assert_eq!(r.get("content").unwrap().as_str().unwrap(), "fake-ok");
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn timeout_kills() {
        let tmp = tmpjobs("timeout");
        let jobs = tmp.join("jobs");
        let exec_py = write_fake_exec(&tmp);
        let a = submit(&jobs, "30", 5); // 假执行器睡 30s，timeout=5s 最小档
        let cfg = ServeCfg::new(jobs.clone(), 1, exec_py);
        let stop = Arc::new(AtomicBool::new(false));
        let h = {
            let cfg = cfg.clone();
            let stop = Arc::clone(&stop);
            thread::spawn(move || serve(&cfg, stop))
        };
        let mut ok = false;
        for _ in 0..150 {
            if read_state(&jobs, &a) == "timeout" {
                ok = true;
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        stop.store(true, Ordering::SeqCst);
        h.join().unwrap();
        assert!(ok, "任务未达 timeout 终态");
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn kill_channel() {
        let tmp = tmpjobs("kill");
        let jobs = tmp.join("jobs");
        let exec_py = write_fake_exec(&tmp);
        let a = submit(&jobs, "30", 3600);
        let cfg = ServeCfg::new(jobs.clone(), 1, exec_py);
        let stop = Arc::new(AtomicBool::new(false));
        let h = {
            let cfg = cfg.clone();
            let stop = Arc::clone(&stop);
            thread::spawn(move || serve(&cfg, stop))
        };
        let mut ran = false;
        for _ in 0..50 {
            if read_state(&jobs, &a) == "running" {
                ran = true;
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        job::request_kill(&job::job_dir(&jobs, &a)).unwrap();
        let mut killed = false;
        for _ in 0..100 {
            if read_state(&jobs, &a) == "killed" {
                killed = true;
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        stop.store(true, Ordering::SeqCst);
        h.join().unwrap();
        assert!(ran, "任务未进入 running");
        assert!(killed, "kill 标志未生效");
        let _ = fs::remove_dir_all(&tmp);
    }

    /// M1 恢复判据前移（能红 + 反向对照）：recover_orphans 与 classify_exit 共用
    /// 产物判据——有 result.json 按产物定终态，无产物才走旧路径。
    /// 反向对照：注释 classify_result 前移逻辑（回退旧判据）时，a/d 两断言必红。
    #[test]
    fn recover_by_artifact() {
        let tmp = tmpjobs("recover");
        let jobs = tmp.join("jobs");
        let exec_py = write_fake_exec(&tmp);

        // a: claimed + 产物（无 error）→ done（旧行为重投 pending——反向对照可红）
        let a = submit(&jobs, "0", 60);
        let da = job::job_dir(&jobs, &a);
        fs::write(da.join("claimed.lock"), b"").unwrap();
        fs::write(da.join("result.json"), r#"{"ok":true,"content":"x"}"#).unwrap();
        let _ = job::patch_status(
            &da,
            vec![("state".to_string(), crate::json::Json::Str("claimed".into()))],
        );

        // b: claimed + 产物带 error → error（error 文本按产物透传）
        let b = submit(&jobs, "0", 60);
        let db = job::job_dir(&jobs, &b);
        fs::write(db.join("claimed.lock"), b"").unwrap();
        fs::write(db.join("result.json"), r#"{"ok":false,"error":"boom"}"#).unwrap();
        let _ = job::patch_status(
            &db,
            vec![("state".to_string(), crate::json::Json::Str("claimed".into()))],
        );

        // c: claimed + 无产物 → pending 重投（原行为保留；锁须被删）
        let c = submit(&jobs, "0", 60);
        let dc = job::job_dir(&jobs, &c);
        fs::write(dc.join("claimed.lock"), b"").unwrap();
        let _ = job::patch_status(
            &dc,
            vec![("state".to_string(), crate::json::Json::Str("claimed".into()))],
        );

        // d: running + 产物（无 error）→ done（旧行为一律「serve 中断」error——反向对照可红）
        let d = submit(&jobs, "0", 60);
        let dd = job::job_dir(&jobs, &d);
        fs::write(dd.join("result.json"), r#"{"ok":true,"content":"y"}"#).unwrap();
        let _ = job::patch_status(
            &dd,
            vec![("state".to_string(), crate::json::Json::Str("running".into()))],
        );

        // e: running + 无产物 → error 且文本含「serve 中断」（原行为保留）
        let e = submit(&jobs, "0", 60);
        let de = job::job_dir(&jobs, &e);
        let _ = job::patch_status(
            &de,
            vec![("state".to_string(), crate::json::Json::Str("running".into()))],
        );

        let cfg = ServeCfg::new(jobs.clone(), 1, exec_py);
        recover_orphans(&cfg);

        assert_eq!(read_state(&jobs, &a), "done", "claimed+产物应按产物定 done");
        assert_eq!(read_state(&jobs, &b), "error", "claimed+错误产物应定 error");
        let st_b = job::read_status(&db).unwrap();
        assert_eq!(st_b.get("error").unwrap().as_str().unwrap(), "boom");
        assert_eq!(read_state(&jobs, &c), "pending", "claimed+无产物应重投");
        assert!(!dc.join("claimed.lock").exists(), "重投须删锁");
        assert_eq!(read_state(&jobs, &d), "done", "running+产物应按产物定 done");
        assert_eq!(read_state(&jobs, &e), "error", "running+无产物应标 error");
        let st_e = job::read_status(&de).unwrap();
        assert!(
            st_e.get("error").unwrap().as_str().unwrap().contains("serve 中断"),
            "running+无产物的 error 文本须含 serve 中断"
        );
        let _ = fs::remove_dir_all(&tmp);
    }

    /// M2 进程树回收（能红 + 反向对照）：执行器派生孙进程后长睡，kill 后孙进程
    /// 必须被回收。反向对照：旧 `child.kill()` 路径（TerminateProcess 只杀直接
    /// 子进程）下孙进程仍存活——本测试在旧路径必红。Windows 限定（taskkill）。
    #[cfg(windows)]
    #[test]
    fn kill_tree_kills_grandchildren() {
        const TREE_EXEC: &str = r#"
import sys, json, os, time, subprocess
d = sys.argv[1]
with open(os.path.join(d, "spec.json"), encoding="utf-8") as f:
    json.load(f)
p = subprocess.Popen(
    ["cmd", "/c", "timeout", "/t", "300", "/nobreak"],
    creationflags=0x08000000,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
with open(os.path.join(d, "grandchild.pid"), "w") as f:
    f.write(str(p.pid))
time.sleep(30)  # 长睡保持执行器存活，触发 kill 路径
"#;
        let tmp = tmpjobs("killtree");
        let jobs = tmp.join("jobs");
        let exec_py = tmp.join("fake_exec_tree.py");
        fs::write(&exec_py, TREE_EXEC).unwrap();
        let a = submit(&jobs, "30", 3600);
        let cfg = ServeCfg::new(jobs.clone(), 1, exec_py);
        let stop = Arc::new(AtomicBool::new(false));
        let h = {
            let cfg = cfg.clone();
            let stop = Arc::clone(&stop);
            thread::spawn(move || serve(&cfg, stop))
        };

        // 等执行器产出孙进程 pid
        let gpath = job::job_dir(&jobs, &a).join("grandchild.pid");
        let mut gpid: u32 = 0;
        for _ in 0..100 {
            if let Ok(s) = fs::read_to_string(&gpath) {
                if let Ok(p) = s.trim().parse::<u32>() {
                    gpid = p;
                    break;
                }
            }
            thread::sleep(Duration::from_millis(100));
        }
        assert!(gpid > 0, "执行器未产出孙进程");

        // kill 执行器
        job::request_kill(&job::job_dir(&jobs, &a)).unwrap();
        let mut killed = false;
        for _ in 0..100 {
            if read_state(&jobs, &a) == "killed" {
                killed = true;
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        assert!(killed, "kill 未生效");

        // 孙进程须在 3s 内从进程表消失（旧 child.kill() 路径此处仍存活 → 必红）
        let mut gone = false;
        for _ in 0..30 {
            if !win_pid_alive(gpid) {
                gone = true;
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        stop.store(true, Ordering::SeqCst);
        h.join().unwrap();
        assert!(gone, "kill_tree 后孙进程 {} 仍存活（进程树回收失败）", gpid);
        let _ = fs::remove_dir_all(&tmp);
    }

    /// I-1 依赖门禁（能红 + 反向对照）：①依赖未终态 → 停留 pending 不领取；
    /// ②依赖 done → 正常执行；③依赖 error → 失败传播直接 error 不执行。
    /// 反向对照：删 deps_gate 调用 → c 会被执行成 done（必红）。
    #[test]
    fn dependency_gate() {
        let tmp = tmpjobs("deps");
        let jobs = tmp.join("jobs");
        let exec_py = write_fake_exec(&tmp);

        let a = submit(&jobs, "0.2", 60); // 上游（sleep 0.2，给 b 留 pending 观察窗）
        let b = submit(&jobs, "0", 60); // 依赖 a（spec 后补）
        let c = submit(&jobs, "0", 60); // 依赖 d（spec 后补）
        let d = submit(&jobs, "0", 60); // 上游失败者（spec 覆盖为非法 → 领取即 error）

        // 后补 depends_on：直接覆盖 spec.json（手写 JSON；h 前缀合法，
        // worker 侧 validate_lenient 可过；避开测试内 JSON 改写 API）
        let db = job::job_dir(&jobs, &b);
        fs::write(
            db.join("spec.json"),
            format!(
                r#"{{"model":"fake","user_prompt":"0","timeout_s":60,"depends_on":["{a}"]}}"#
            ),
        )
        .unwrap();
        let dc = job::job_dir(&jobs, &c);
        fs::write(
            dc.join("spec.json"),
            format!(
                r#"{{"model":"fake","user_prompt":"0","timeout_s":60,"depends_on":["{d}"]}}"#
            ),
        )
        .unwrap();
        // d 的 spec 覆盖为非法值（temperature 超界）→ worker 领取即 error
        let dd = job::job_dir(&jobs, &d);
        fs::write(
            dd.join("spec.json"),
            r#"{"model":"fake","user_prompt":"0","timeout_s":60,"temperature":3.5}"#,
        )
        .unwrap();

        // serve 启动后 200ms 观察窗：b 应停留 pending（a 未完成）——能红点①
        let cfg = ServeCfg::new(jobs.clone(), 2, exec_py);
        let stop = Arc::new(AtomicBool::new(false));
        let h = {
            let cfg = cfg.clone();
            let stop = Arc::clone(&stop);
            thread::spawn(move || serve(&cfg, stop))
        };
        // （观察窗弱断言：不做强时序断言，靠 c 的传播断言兜底）

        // 等 a、b 完成（a done → 依赖满足 → b 领取执行）
        let mut ab_done = false;
        for _ in 0..300 {
            if read_state(&jobs, &a) == "done" && read_state(&jobs, &b) == "done" {
                ab_done = true;
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        // 等 c 到终态（预期：d error → c 失败传播）
        let mut c_state = String::new();
        let mut c_err = String::new();
        for _ in 0..300 {
            let sc = job::read_status(&dc).unwrap();
            c_state = sc
                .get("state")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            c_err = sc
                .get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            if ["done", "error", "timeout", "killed"].contains(&c_state.as_str()) {
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        stop.store(true, Ordering::SeqCst);
        h.join().unwrap();

        assert!(ab_done, "a/b 应依次完成（依赖满足后领取）");
        assert_eq!(
            c_state, "error",
            "依赖 error 时 c 应失败传播（反向对照：删 deps_gate 必红）"
        );
        assert!(
            c_err.contains("依赖失败传播"),
            "c 的 error 文本应含「依赖失败传播」: {c_err}"
        );
        let _ = fs::remove_dir_all(&tmp);
    }

    /// Windows 进程表精确查询（CSV 列比对，防 pid 441 被 4410 命中——
    /// 与 serve_start._tasklist_row 同口径）。
    #[cfg(windows)]
    fn win_pid_alive(pid: u32) -> bool {
        let out = std::process::Command::new("tasklist")
            .args(["/FI", &format!("PID eq {}", pid), "/NH", "/FO", "CSV"])
            .output();
        let Ok(o) = out else { return false };
        let s = String::from_utf8_lossy(&o.stdout);
        for line in s.lines() {
            let cols: Vec<&str> = line.split("\",\"").collect();
            if cols.len() >= 2 && cols[1].trim().trim_matches('"') == pid.to_string() {
                return true;
            }
        }
        false
    }
}
