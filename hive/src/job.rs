//! job 目录文件协议（跨语言接口的真源）。
//!
//! ```text
//! jobs/
//!   _serve.json               # serve 心跳 {pid, ts, workers}（主循环每拍写）
//!   <job_id>/
//!     spec.json               # 任务规格（submit 写；先写）
//!     status.json             # 状态（submit 写初始 pending；status.json 出现 = 任务就绪可领取）
//!     result.json             # 执行器产物（成功/API 错误均写，error 字段区分）
//!     kill                    # kill 标志（任意宿主创建；worker 检测到即强杀）
//!     claimed.lock            # 领取原子锁（create_new 成功者独占该任务）
//! ```
//!
//! 状态机：pending → claimed → running → done | error | timeout | killed
//!
//! 并发安全要点：
//!   * `claimed.lock` 用 `create_new(true)` 原子创建——多 serve 竞争时只有
//!     一个领取成功，其余跳过（不损坏数据）；
//!   * 领取后 status.json 只由持有者单写（worker 写心跳/终态），无双写者。

use crate::json::Json;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

/// 当前 Unix 毫秒。
pub fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

/// 生成 job_id：`h<unix_ms>_<pid4>`（同毫秒冲突由 pid 区分；进程内串行提交足够）。
pub fn new_job_id() -> String {
    let pid = std::process::id();
    format!("h{}_{:04x}", now_ms(), pid & 0xffff)
}

pub fn job_dir(jobs: &Path, id: &str) -> PathBuf {
    jobs.join(id)
}

/// 覆盖写 JSON 文本（UTF-8）——tmp + fsync + rename 原子替换。
///
/// 禁止直接 `File::create` 目标文件：它先把旧文件截断为 0 字节，并发读者
/// （patch_status 读-改-写、poll/doctor 轮询）会在「截断后、写完前」的窗口
/// 读到空文件导致 parse 失败。同目录 rename 在 POSIX 与 Windows
///（MoveFileEx + REPLACE_EXISTING）上均为原子替换，读者只见旧内容或新内容。
/// tmp 名带 pid：多 serve 竞争写 `_serve.json` 时互不踩踏，rename 最后写者赢。
pub fn write_json(path: &Path, v: &Json) -> std::io::Result<()> {
    let data = v.to_json_string();
    let tmp = path.with_extension(format!("tmp{}", std::process::id()));
    {
        let mut f = fs::File::create(&tmp)?;
        f.write_all(data.as_bytes())?;
        f.sync_all()?;
    }
    fs::rename(&tmp, path)
}

/// 读 JSON 文本并解析（坏文件按错误返回，不静默吞）。
pub fn read_json(path: &Path) -> Result<Json, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    crate::json::parse(&text).map_err(|e| format!("{}: {e}", path.display()))
}

/// 建任务目录并落 spec.json + 初始 status(pending)。
/// 写序：spec.json 先行，status.json 后写 = 「任务就绪」信号，
/// serve 只领取见到 status.json 且 state=pending 的任务。
pub fn init_job(jobs: &Path, spec_json: &Json, timeout_s: u64) -> Result<String, String> {
    let id = new_job_id();
    let dir = job_dir(jobs, &id);
    fs::create_dir_all(&dir).map_err(|e| format!("建任务目录失败: {e}"))?;
    write_json(&dir.join("spec.json"), spec_json)
        .map_err(|e| format!("写 spec.json 失败: {e}"))?;
    let status = Json::Obj(vec![
        ("job_id".to_string(), Json::Str(id.clone())),
        ("state".to_string(), Json::Str("pending".to_string())),
        ("created_ts".to_string(), Json::Num(now_ms() as f64)),
        ("started_ts".to_string(), Json::Null),
        ("heartbeat_ts".to_string(), Json::Null),
        ("elapsed_s".to_string(), Json::Num(0.0)),
        ("timeout_s".to_string(), Json::Num(timeout_s as f64)),
        ("model".to_string(), Json::Null),
        ("pid".to_string(), Json::Null),
        ("error".to_string(), Json::Null),
    ]);
    write_json(&dir.join("status.json"), &status)
        .map_err(|e| format!("写 status.json 失败: {e}"))?;
    Ok(id)
}

/// 原子领取：`claimed.lock` create_new 成功者独占。返回 false = 已被领取。
pub fn claim(dir: &Path) -> bool {
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(dir.join("claimed.lock"))
        .is_ok()
}

/// 读 status.json；不存在按 pending 前态处理（理论上仅在竞态窗口）。
pub fn read_status(dir: &Path) -> Result<Json, String> {
    read_json(&dir.join("status.json"))
}

/// 更新 status.json 的若干字段（读-改-写，全量覆盖）。
pub fn patch_status(dir: &Path, fields: Vec<(String, Json)>) -> Result<(), String> {
    let mut st = read_status(dir)?;
    if let Json::Obj(kv) = &mut st {
        for (k, v) in fields {
            match kv.iter_mut().find(|(ek, _)| *ek == k) {
                Some(slot) => slot.1 = v,
                None => kv.push((k, v)),
            }
        }
    }
    write_json(&dir.join("status.json"), &st).map_err(|e| e.to_string())
}

/// worker 心跳：刷新 heartbeat_ts / elapsed_s / state。
pub fn heartbeat(dir: &Path, state: &str, started_ms: u128) -> Result<(), String> {
    let now = now_ms();
    let elapsed = if started_ms > 0 { (now - started_ms) as f64 / 1000.0 } else { 0.0 };
    patch_status(
        dir,
        vec![
            ("state".to_string(), Json::Str(state.to_string())),
            ("heartbeat_ts".to_string(), Json::Num(now as f64)),
            ("elapsed_s".to_string(), Json::Num((elapsed * 100.0).round() / 100.0)),
        ],
    )
}

/// kill 标志是否存在。
pub fn kill_requested(dir: &Path) -> bool {
    dir.join("kill").exists()
}

/// 写 kill 标志（幂等）。
pub fn request_kill(dir: &Path) -> Result<(), String> {
    let p = dir.join("kill");
    if !p.exists() {
        fs::File::create(&p).map_err(|e| format!("写 kill 标志失败: {e}"))?;
    }
    Ok(())
}

/// 列出全部任务目录名（按名升序 = 时间升序）。
pub fn list_jobs(jobs: &Path) -> Vec<String> {
    let mut out = Vec::new();
    if let Ok(rd) = fs::read_dir(jobs) {
        for e in rd.flatten() {
            let name = e.file_name().to_string_lossy().to_string();
            if name.starts_with("h") && e.path().is_dir() {
                out.push(name);
            }
        }
    }
    out.sort();
    out
}

/// 写 serve 心跳。
///
/// `exec_py` / `exec_mode` 是**执行器资格的权威来源**（serve 启动时固化）：serve 的 env
/// 对另一个进程不可反查，doctor 若拿自身 env 判资格必得错位结论。故由 serve 把自己
/// 真实生效的执行器写进心跳——任何入口（CLI doctor / MCP doctor）读同一块即同口径。
pub fn write_serve_heartbeat(
    jobs: &Path,
    workers: usize,
    exec_py: &Path,
    exec_mode: &str,
) -> Result<(), String> {
    let v = Json::Obj(vec![
        ("pid".to_string(), Json::Num(std::process::id() as f64)),
        ("ts".to_string(), Json::Num(now_ms() as f64)),
        ("workers".to_string(), Json::Num(workers as f64)),
        (
            "exec_py".to_string(),
            Json::Str(exec_py.to_string_lossy().to_string()),
        ),
        ("exec_mode".to_string(), Json::Str(exec_mode.to_string())),
    ]);
    write_json(&jobs.join("_serve.json"), &v).map_err(|e| e.to_string())
}

/// 读 serve 心跳（不存在 → None）。
pub fn read_serve_heartbeat(jobs: &Path) -> Option<Json> {
    read_json(&jobs.join("_serve.json")).ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::parse;

    fn tmpdir(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!(
            "hive_job_{tag}_{}",
            now_ms()
        ));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn init_and_claim_once() {
        let jobs = tmpdir("claim");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let id = init_job(&jobs, &spec, 300).unwrap();
        let dir = job_dir(&jobs, &id);
        assert!(dir.join("spec.json").is_file());
        let st = read_status(&dir).unwrap();
        assert_eq!(st.get("state").unwrap().as_str().unwrap(), "pending");
        // 领取一次成功，第二次必须失败（原子性）
        assert!(claim(&dir));
        assert!(!claim(&dir));
        let _ = fs::remove_dir_all(&jobs);
    }

    #[test]
    fn status_patch_and_heartbeat() {
        let jobs = tmpdir("patch");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let id = init_job(&jobs, &spec, 60).unwrap();
        let dir = job_dir(&jobs, &id);
        patch_status(
            &dir,
            vec![
                ("state".to_string(), Json::Str("running".to_string())),
                ("model".to_string(), Json::Str("m".to_string())),
            ],
        )
        .unwrap();
        let st = read_status(&dir).unwrap();
        assert_eq!(st.get("state").unwrap().as_str().unwrap(), "running");
        assert_eq!(st.get("timeout_s").unwrap().as_f64().unwrap(), 60.0);
        heartbeat(&dir, "running", now_ms() - 1500).unwrap();
        let st = read_status(&dir).unwrap();
        let el = st.get("elapsed_s").unwrap().as_f64().unwrap();
        assert!(el >= 1.0 && el < 5.0, "elapsed={el}");
        let _ = fs::remove_dir_all(&jobs);
    }

    #[test]
    fn kill_flag_idempotent() {
        let jobs = tmpdir("kill");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let id = init_job(&jobs, &spec, 60).unwrap();
        let dir = job_dir(&jobs, &id);
        assert!(!kill_requested(&dir));
        request_kill(&dir).unwrap();
        request_kill(&dir).unwrap(); // 幂等
        assert!(kill_requested(&dir));
        let _ = fs::remove_dir_all(&jobs);
    }

    #[test]
    fn list_jobs_sorted() {
        let jobs = tmpdir("list");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let a = init_job(&jobs, &spec, 60).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(5));
        let b = init_job(&jobs, &spec, 60).unwrap();
        let all = list_jobs(&jobs);
        assert_eq!(all, vec![a, b]);
        let _ = fs::remove_dir_all(&jobs);
    }
}
