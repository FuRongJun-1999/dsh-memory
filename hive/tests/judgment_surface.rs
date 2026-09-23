//! 判据面集成测试（批次8b，互验定稿 §7.6 判据面重定义）。
//!
//! 定位：本文件属于**判据面**（A3「判据面文件集合 hash==冻结值」的覆盖对象），
//! 被测代码属于**候选面**（hive/src/）——物理分离后，候选弱化本文件任一
//! 承重断言（反向对照测试）时，判据面 hash 不变而候选 hash 变，验证实例以
//! 判据面覆盖候选面跑全量，弱化必红（批次8b 前 25 个测试内联在候选面 src，
//! A3 盖不住——zcode 外评 break#3）。
//!
//! 迁移记录：recover_by_artifact / rerun_on_recover_escape_hatch /
//! kill_tree_kills_grandchildren 三测试自 src/scheduler.rs 内联测试迁入
//! （判据只增不减只在边界前进——本次=承重断言从候选面迁入判据面）。
//! 自包含：不依赖 src 内任何测试 helper。

use hive::json::parse;
use hive::job;
use hive::scheduler::{recover_orphans, serve, ServeCfg};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

fn tmpjobs(tag: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!(
        "hive_judgment_{tag}_{}",
        job::now_ms()
    ));
    let _ = fs::remove_dir_all(&d);
    fs::create_dir_all(&d).unwrap();
    d
}

fn submit(jobs: &PathBuf, sleep_s: &str, timeout_s: u64) -> String {
    let spec = parse(&format!(
        r#"{{"model":"fake","user_prompt":"{sleep_s}","timeout_s":{timeout_s}}}"#
    ))
    .unwrap();
    job::init_job(jobs, &spec, timeout_s).unwrap()
}

fn read_state(jobs: &Path, id: &str) -> String {
    let st = job::read_status(&job::job_dir(jobs, id)).unwrap();
    st.get("state").unwrap().as_str().unwrap().to_string()
}

/// Windows 进程表精确查询（CSV 列比对，防 pid 441 被 4410 命中）。
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

/// 承重断言 1（M1 恢复判据前移，能红 + 反向对照）：recover_orphans 与
/// classify_exit 共用产物判据——有 result.json 按产物定终态，无产物走旧路径。
/// 弱化本测试（如删 a/d 断言）= 弱化判据面 → A3 红 / 验证实例跑本文件必红。
#[test]
fn recover_by_artifact() {
    let tmp = tmpjobs("recover");
    let jobs = tmp.join("jobs");

    let mk = |id_tag: &str, state: &str, result: Option<&str>| -> (String, PathBuf) {
        let id = submit(&jobs, "0", 60);
        let dir = job::job_dir(&jobs, &id);
        if let Some(r) = result {
            fs::write(dir.join("result.json"), r).unwrap();
        }
        if state == "claimed" {
            fs::write(dir.join("claimed.lock"), b"").unwrap();
        }
        let _ = job::patch_status(
            &dir,
            vec![("state".to_string(), hive::json::Json::Str(state.into()))],
        );
        (id, dir)
    };

    let (a, da) = mk("a", "claimed", Some(r#"{"ok":true,"content":"x"}"#));
    let (b, db) = mk("b", "claimed", Some(r#"{"ok":false,"error":"boom"}"#));
    let (c, dc) = mk("c", "claimed", None);
    let (d, _dd) = mk("d", "running", Some(r#"{"ok":true,"content":"y"}"#));
    let (e, de) = mk("e", "running", None);

    let cfg = ServeCfg::new(jobs.clone(), 1, tmp.join("fake_exec.py"));
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

/// 承重断言 2（M1 逃生门，批次7，能红 + 反向对照）：spec 显式
/// rerun_on_recover 时恢复不采信旧产物——更名留痕 + 强制重投；
/// 缺省必须维持产物判据（反向对照：误做成无条件重投时 b 必红）。
#[test]
fn rerun_on_recover_escape_hatch() {
    let tmp = tmpjobs("rerun");
    let jobs = tmp.join("jobs");

    let a = submit(&jobs, "0", 60);
    let da = job::job_dir(&jobs, &a);
    fs::write(
        da.join("spec.json"),
        r#"{"model":"fake","user_prompt":"0","rerun_on_recover":true}"#,
    )
    .unwrap();
    fs::write(da.join("claimed.lock"), b"").unwrap();
    fs::write(da.join("result.json"), r#"{"ok":true,"content":"stale"}"#).unwrap();
    let _ = job::patch_status(
        &da,
        vec![("state".to_string(), hive::json::Json::Str("claimed".into()))],
    );

    let b = submit(&jobs, "0", 60);
    let db = job::job_dir(&jobs, &b);
    fs::write(db.join("claimed.lock"), b"").unwrap();
    fs::write(db.join("result.json"), r#"{"ok":true,"content":"fresh"}"#).unwrap();
    let _ = job::patch_status(
        &db,
        vec![("state".to_string(), hive::json::Json::Str("claimed".into()))],
    );

    let c = submit(&jobs, "0", 60);
    let dc = job::job_dir(&jobs, &c);
    fs::write(
        dc.join("spec.json"),
        r#"{"model":"fake","user_prompt":"0","rerun_on_recover":true}"#,
    )
    .unwrap();
    fs::write(dc.join("result.json"), r#"{"ok":false,"error":"poisoned"}"#).unwrap();
    let _ = job::patch_status(
        &dc,
        vec![("state".to_string(), hive::json::Json::Str("running".into()))],
    );

    let cfg = ServeCfg::new(jobs.clone(), 1, tmp.join("fake_exec.py"));
    recover_orphans(&cfg);

    assert_eq!(read_state(&jobs, &a), "pending", "逃生门应强制重投 claimed");
    assert!(!da.join("claimed.lock").exists(), "重投须删锁");
    assert!(!da.join("result.json").exists(), "旧产物须让位（不采信）");
    let archived_a = fs::read_dir(&da)
        .unwrap()
        .filter_map(|e| e.ok())
        .any(|e| e.file_name().to_string_lossy().starts_with("result.json.recovered-"));
    assert!(archived_a, "旧产物须以 recovered-<ts> 留痕");

    assert_eq!(read_state(&jobs, &b), "done", "缺省必须维持产物判据（反向对照）");

    assert_eq!(read_state(&jobs, &c), "pending", "逃生门应覆盖 running 态");
    assert!(
        fs::read_dir(&dc)
            .unwrap()
            .filter_map(|e| e.ok())
            .any(|e| e
                .file_name()
                .to_string_lossy()
                .starts_with("result.json.recovered-")),
        "running 态旧产物同样须留痕"
    );
    let _ = fs::remove_dir_all(&tmp);
}

/// 承重断言 3（M2 进程树回收，Windows，能红 + 反向对照）：执行器派生孙进程
/// 后长睡，kill 后孙进程必须被回收。旧 child.kill() 路径下孙进程仍存活必红。
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
time.sleep(30)
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
