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

// --------------------------------------------------------------- P11 结果完整性锚

/// P11 锚测试共用常量/构造：nonce 手工指定（与 init_job_with_anchor 契约一致），
/// 密钥任意固定串；result.json 手写（注入者视角——不跑真实执行器）。
const ANCHOR_KEY: &str = "judgment-surface-anchor-key";
const ANCHOR_NONCE: &str = "0123456789abcdef";

fn submit_anchored(jobs: &Path, timeout_s: u64) -> (String, PathBuf) {
    let spec = parse(&format!(
        r#"{{"model":"fake","user_prompt":"0","timeout_s":{timeout_s}}}"#
    ))
    .unwrap();
    let id = job::init_job_with_anchor(jobs, &spec, 60, Some(ANCHOR_NONCE)).unwrap();
    let dir = job::job_dir(jobs, &id);
    (id, dir)
}

/// 承重断言 4（P11 结果完整性锚，批次53，能红 + 反向对照）：锚预期任务
/// （status 带 result_nonce）的产物在采信 done 前必须过完整性锚校验——
///   a. 诚实回写锚（HMAC 与预期一致）→ done（诚实执行器语义不变）；
///   b. 伪锚/挪锚（ 锚与预期不匹配）→ error 拒绝采信；
///   c. 旧格式产物（无 result_anchor）→ needs_review 不自动采信；
///   d. 无密钥 serve 对锚预期产物 → needs_review（fail-closed 不静默放行）；
///   e. 旧格式任务（无 nonce）+ 旧格式产物 → done（向后兼容基线）。
/// 反向对照：退回旧判据（删锚校验）则 b/c/d 全变 done，本测试必红；
/// 弱化任一断言 = 弱化判据面 → A3 红。
#[test]
fn result_anchor_gate() {
    let tmp = tmpjobs("anchor_gate");
    let jobs = tmp.join("jobs");

    // a. 诚实锚：按同一公式（hive::hmac 公共函数即盘面唯一公式实现）预写正确锚
    let (a, da) = submit_anchored(&jobs, 60);
    let spec_bytes = fs::read(da.join("spec.json")).unwrap();
    let good = hive::hmac::result_anchor_hex(ANCHOR_KEY, &spec_bytes, ANCHOR_NONCE);
    fs::write(
        da.join("result.json"),
        format!(r#"{{"ok":true,"content":"honest","result_anchor":"{good}"}}"#),
    )
    .unwrap();
    let _ = job::patch_status(
        &da,
        vec![("state".to_string(), hive::json::Json::Str("claimed".into()))],
    );

    // b. 挪锚：把 a 任务的合法锚冒充给本任务（spec 字节不同 → 公式必失配）
    let (b, db) = submit_anchored(&jobs, 61);
    fs::write(
        db.join("result.json"),
        format!(r#"{{"ok":true,"content":"forged","result_anchor":"{good}"}}"#),
    )
    .unwrap();
    let _ = job::patch_status(
        &db,
        vec![("state".to_string(), hive::json::Json::Str("claimed".into()))],
    );

    // c. 旧格式伪造产物：FI-R03 注入形态——ok=true 但无锚
    let (c, dc) = submit_anchored(&jobs, 60);
    fs::write(
        dc.join("result.json"),
        r#"{"ok":true,"content":"伪造内容-CHAOS-FI-R03"}"#,
    )
    .unwrap();
    let _ = job::patch_status(
        &dc,
        vec![("state".to_string(), hive::json::Json::Str("claimed".into()))],
    );

    // e. 旧格式任务（无 nonce）+ 旧格式产物 → 旧判据（向后兼容）
    let e = submit(&jobs, "0", 60);
    let de = job::job_dir(&jobs, &e);
    fs::write(de.join("result.json"), r#"{"ok":true,"content":"legacy"}"#).unwrap();
    let _ = job::patch_status(
        &de,
        vec![("state".to_string(), hive::json::Json::Str("claimed".into()))],
    );

    let cfg = ServeCfg::new(jobs.clone(), 1, tmp.join("fake_exec.py"))
        .with_result_key(Some(ANCHOR_KEY.to_string()));
    recover_orphans(&cfg);

    assert_eq!(read_state(&jobs, &a), "done", "诚实锚产物必须照常采信 done");
    assert_eq!(
        read_state(&jobs, &b),
        "error",
        "挪锚/伪锚必须拒绝采信（error 终态）"
    );
    let st_b = job::read_status(&db).unwrap();
    let err_b = st_b.get("error").unwrap().as_str().unwrap();
    assert!(
        err_b.contains("完整性锚校验失败"),
        "b 的 error 须点明锚校验失败: {err_b}"
    );
    assert_eq!(
        read_state(&jobs, &c),
        "needs_review",
        "旧格式伪造产物不得采信 done（不自动采信，P11）"
    );
    let st_c = job::read_status(&dc).unwrap();
    let err_c = st_c.get("error").unwrap().as_str().unwrap();
    assert!(
        err_c.contains("产物完整性锚缺失"),
        "c 的 error 须点明锚缺失: {err_c}"
    );
    assert_eq!(
        read_state(&jobs, &e),
        "done",
        "旧格式任务必须维持旧判据（向后兼容零变更）"
    );

    // d. 无密钥 serve 对同一批锚预期产物 → fail-closed needs_review（不静默放行）
    let (d, dd) = submit_anchored(&jobs, 60);
    fs::write(
        dd.join("result.json"),
        format!(r#"{{"ok":true,"content":"x","result_anchor":"{good}"}}"#),
    )
    .unwrap();
    let _ = job::patch_status(
        &dd,
        vec![("state".to_string(), hive::json::Json::Str("running".into()))],
    );
    let cfg_keyless = ServeCfg::new(jobs.clone(), 1, tmp.join("fake_exec.py"));
    recover_orphans(&cfg_keyless);
    assert_eq!(
        read_state(&jobs, &d),
        "needs_review",
        "无密钥 serve 不得采信锚预期产物（fail-closed）"
    );
    let st_d = job::read_status(&dd).unwrap();
    assert!(
        st_d.get("error")
            .unwrap()
            .as_str()
            .unwrap()
            .contains("不可校验"),
        "d 的 error 须点明不可校验"
    );
    let _ = fs::remove_dir_all(&tmp);
}

/// 承重断言 5（P11 锚 + M1 逃生门组合，批次53）：spec 显式 rerun_on_recover 时，
/// needs_review（锚缺失）产物同样走「更名留痕 + 强制重投」——可疑产物不终局，
/// 重跑给诚实执行器第二次机会。反向对照：缺省（无逃生门）必须停在 needs_review。
#[test]
fn anchor_needs_review_rerun_escape_hatch() {
    let tmp = tmpjobs("anchor_rerun");
    let jobs = tmp.join("jobs");

    // a. 锚预期 + 旧格式伪造产物 + rerun_on_recover → 重投（留痕，回 pending）
    let (a, da) = submit_anchored(&jobs, 60);
    fs::write(
        da.join("spec.json"),
        r#"{"model":"fake","user_prompt":"0","timeout_s":60,"rerun_on_recover":true}"#,
    )
    .unwrap();
    fs::write(
        da.join("result.json"),
        r#"{"ok":true,"content":"stale-forged"}"#,
    )
    .unwrap();
    let _ = job::patch_status(
        &da,
        vec![("state".to_string(), hive::json::Json::Str("claimed".into()))],
    );

    // b. 同型伪造但无逃生门 → needs_review 终态（缺省行为，反向对照）
    let (b, db) = submit_anchored(&jobs, 61);
    fs::write(
        db.join("result.json"),
        r#"{"ok":true,"content":"stale-forged"}"#,
    )
    .unwrap();
    let _ = job::patch_status(
        &db,
        vec![("state".to_string(), hive::json::Json::Str("claimed".into()))],
    );

    let cfg = ServeCfg::new(jobs.clone(), 1, tmp.join("fake_exec.py"))
        .with_result_key(Some(ANCHOR_KEY.to_string()));
    recover_orphans(&cfg);

    assert_eq!(read_state(&jobs, &a), "pending", "逃生门应把锚可疑产物重投");
    assert!(!da.join("result.json").exists(), "重投前旧产物须让位");
    assert!(
        fs::read_dir(&da)
            .unwrap()
            .filter_map(|e| e.ok())
            .any(|e| e.file_name().to_string_lossy().starts_with("result.json.recovered-")),
        "旧产物须以 recovered-<ts> 留痕"
    );
    assert_eq!(
        read_state(&jobs, &b),
        "needs_review",
        "缺省（无逃生门）必须停在 needs_review（反向对照）"
    );
    let _ = fs::remove_dir_all(&tmp);
}

/// 承重断言 6（P11 端到端，批次53）：锚预期任务经真实 serve + 回写锚执行器跑完
/// → done；同池旧格式任务 → done（向后兼容）。执行器从 env HIVE_RESULT_ANCHOR
/// 原样回写（与 exec.py / exec_cmd.py 的执行器契约同形）。
#[test]
fn anchor_e2e_done_with_echo_executor() {
    const ECHO_EXEC: &str = r#"
import sys, json, os
d = sys.argv[1]
with open(os.path.join(d, "spec.json"), encoding="utf-8") as f:
    spec = json.load(f)
anchor = os.environ.get("HIVE_RESULT_ANCHOR", "")
r = {"ok": True, "content": "e2e-ok", "usage": {"total_tokens": 1}}
if anchor:
    r["result_anchor"] = anchor
with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
    json.dump(r, f, ensure_ascii=False)
"#;
    let tmp = tmpjobs("anchor_e2e");
    let jobs = tmp.join("jobs");
    let exec_py = tmp.join("echo_exec.py");
    fs::write(&exec_py, ECHO_EXEC).unwrap();

    let spec = parse(r#"{"model":"fake","user_prompt":"0","timeout_s":60}"#).unwrap();
    let a = job::init_job_with_anchor(&jobs, &spec, 60, Some(ANCHOR_NONCE)).unwrap();
    let b = submit(&jobs, "0", 60); // 旧格式对照

    let cfg = ServeCfg::new(jobs.clone(), 2, exec_py)
        .with_result_key(Some(ANCHOR_KEY.to_string()));
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
    assert!(ok, "锚预期任务与旧格式任务都应到 done");
    let r = job::read_json(&job::job_dir(&jobs, &a).join("result.json")).unwrap();
    assert_eq!(r.get("content").unwrap().as_str().unwrap(), "e2e-ok");
    assert!(
        r.get("result_anchor").is_some(),
        "回写锚执行器必须带 result_anchor（env 注入链生效）"
    );
    let _ = fs::remove_dir_all(&tmp);
}
