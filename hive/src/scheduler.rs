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
//! 崩溃恢复：serve 启动时清理上次遗留——claimed 重投 pending（删锁），
//! running 标 error（其孤儿执行器若仍存活，写出的 result.json 宿主仍可读）。

use crate::exec;
use crate::job;
use crate::spec;
use std::path::PathBuf;
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
    /// 主循环扫描间隔（毫秒）。
    pub poll_ms: u64,
}

impl ServeCfg {
    pub fn new(jobs: PathBuf, workers: usize, exec_py: PathBuf) -> Self {
        ServeCfg {
            jobs,
            workers: workers.clamp(1, 64),
            exec_py,
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
        let _ = job::write_serve_heartbeat(&cfg.jobs, cfg.workers);
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

/// 崩溃恢复：claimed 重投（删锁回 pending）；running 标 error。
fn recover_orphans(cfg: &ServeCfg) {
    for id in job::list_jobs(&cfg.jobs) {
        let dir = job::job_dir(&cfg.jobs, &id);
        let Ok(st) = job::read_status(&dir) else { continue };
        let state = st.get("state").and_then(|v| v.as_str()).unwrap_or("");
        match state {
            "claimed" => {
                let _ = std::fs::remove_file(dir.join("claimed.lock"));
                let _ = job::patch_status(
                    &dir,
                    vec![(
                        "state".to_string(),
                        crate::json::Json::Str("pending".into()),
                    )],
                );
            }
            "running" => {
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
                    let _ = child.kill();
                    let _ = child.wait();
                    final_state = "killed".into();
                    break;
                }
                if t0.elapsed() >= timeout {
                    let _ = child.kill();
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

/// 子进程退出后的终态分类：以 result.json 为准（error 字段区分 API 错误）。
fn classify_exit(
    dir: &std::path::Path,
    code: std::process::ExitStatus,
) -> (String, Option<String>) {
    let result_path = dir.join("result.json");
    if result_path.is_file() {
        match job::read_json(&result_path) {
            Ok(r) => {
                let err = r
                    .get("error")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                match err {
                    Some(e) => ("error".into(), Some(e)),
                    None => ("done".into(), None),
                }
            }
            Err(e) => ("error".into(), Some(format!("result.json 解析失败: {e}"))),
        }
    } else if code.success() {
        (
            "error".into(),
            Some("执行器退出码 0 但未产出 result.json".into()),
        )
    } else {
        ("error".into(), Some(format!("执行器异常退出: {code}")))
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
}
