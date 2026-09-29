//! job 目录文件协议（跨语言接口的真源）。
//!
//! ```text
//! jobs/
//!   _serve.json               # serve 心跳 {pid, ts, workers}（主循环每拍写）
//!   _quarantine/              # 坏 status 隔离保留区（H-3；doctor --quarantine 移入）
//!     <job_id>/               #   整体 rename 移入（任务目录原样，逐字节不动）
//!   <job_id>/
//!     spec.json               # 任务规格（submit 写；先写）
//!     status.json             # 状态（submit 写初始 pending；status.json 出现 = 任务就绪可领取）
//!     status.corrupt.json     # 坏 status 标记（H-3；serve 持续 N 拍解析失败后落。
//!                             #   **旁证，不是任务本体**——status.json 坏也照原样留着）
//!     result.json             # 执行器产物（成功/API 错误均写，error 字段区分；
//!                             #   锚预期任务须带 result_anchor 回写锚，见 scheduler）
//!     kill                    # kill 标志（任意宿主创建；worker 检测到即强杀）
//!     claimed.lock            # 领取原子锁（create_new 成功者独占该任务）
//! ```
//!
//! H-3（坏 status 不再静默）：`status.json` 不可解析时**既不改写它、也不当成
//! 半成品无限等待**——serve 周期扫描计数、达阈值落 `status.corrupt.json` 标记、
//! doctor 归 `corrupt` 独立类别、`doctor --quarantine` 可整体移入 `_quarantine/`
//! 退出领取面（可 --unquarantine 原路退回）。**自动终态化不做**：那会让坏文件被
//! 静默吞掉，正是本缺陷的反面；坏 status 的处置权留给显式隔离与人工。
//!
//! P11 结果完整性锚（批次53）：提交面解析到锚密钥（keyres.rs）时，status.json
//! 追加 `result_nonce`（init_job_with_anchor）= 该任务声明锚预期——serve 拉起执行器
//! 时注入 HIVE_RESULT_ANCHOR（hmac.rs 公式），执行器回写 result.json
//! `result_anchor`，classify_result 采信 done 前校验；无 nonce 的旧格式任务保持
//! 旧判据（向后兼容）。
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

/// 生效条件：恒成立（时钟倒退时 unwrap_or(0) 诚实回落）——返回当前 Unix 毫秒。
/// 全仓时间戳（job_id/心跳/日志 _t）的单点时钟源。
pub fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

/// 生效条件：每次调用生成新 id——`h<unix_ms>_<pid4>`，同毫秒冲突由 pid 区分，
/// 进程内串行提交足够；h 前缀使 list_jobs 的名升序 = 提交时间升序（I-1 拓扑序
/// 无环性的结构性根基，spec.rs depends_on 校验依赖此前缀）。
pub fn new_job_id() -> String {
    let pid = std::process::id();
    format!("h{}_{:04x}", now_ms(), pid & 0xffff)
}

/// 生效条件：恒成立——jobs 根目录 + job_id 拼任务目录路径（目录协议的唯一拼装点）。
pub fn job_dir(jobs: &Path, id: &str) -> PathBuf {
    jobs.join(id)
}

/// job_id 结构合法性（防路径穿越）：`h` 开头 + 其余字符限于 ASCII 字母数字与
/// 下划线——结构上排除 `/`、`\`、`..`、盘符 `:` 等一切可逃出 jobs 池的成分。
/// 与 `new_job_id`（`h<unix_ms>_<pid4hex>`）及 list_jobs 的 `h` 前缀过滤同口径。
/// 生效条件：id 匹配 `h[0-9A-Za-z_]*` → true；空串/非 h 开头/含路径成分
/// → false——kill/poll/depends_on 等一切把**外部输入**的 job_id 拼进路径的
/// 入口，必须先过此闸（2026-09-25 缺陷：`kill ..` 曾可在池外写 kill 文件、
/// `poll ../victim` 曾可读池外任意目录的 result 全文）。
pub fn valid_job_id(id: &str) -> bool {
    !id.is_empty()
        && id.starts_with('h')
        && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// 覆盖写 JSON 文本（UTF-8）——tmp + fsync + rename 原子替换。
///
/// 禁止直接 `File::create` 目标文件：它先把旧文件截断为 0 字节，并发读者
/// （patch_status 读-改-写、poll/doctor 轮询）会在「截断后、写完前」的窗口
/// 读到空文件导致 parse 失败。同目录 rename 在 POSIX 与 Windows
///（MoveFileEx + REPLACE_EXISTING）上均为原子替换，读者只见旧内容或新内容。
/// tmp 名带 pid：多 serve 竞争写 `_serve.json` 时互不踩踏，rename 最后写者赢。
/// 生效条件：写 JSON 文本（UTF-8）——tmp + fsync + rename 原子替换；并发读者
/// 只见旧内容或新内容，绝不读空；多写者竞争时 rename 最后写者赢。
/// 不适用条件：不保证跨进程写序（那由上层协议——status 单写者/日志锁——承载）。
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
/// 生效条件：文件存在且为合法 JSON → Ok(Json)；不存在/坏文件 → Err（含路径，
/// 不静默吞——坏文件是事故信号不是默认值来源）。
pub fn read_json(path: &Path) -> Result<Json, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    crate::json::parse(&text).map_err(|e| format!("{}: {e}", path.display()))
}

/// 结果锚 nonce（P11，批次53）：提交时生成、落 status.json `result_nonce`，
/// 与锚密钥（keyres.rs）共同参与结果完整性锚公式（hmac.rs::result_anchor_hex）。
/// nonce 只求**任务内唯一**（防锚跨任务复用），秘密性归锚密钥——故非密码学熵：
/// FNV-1a 混合 毫秒时钟 + pid + 进程内计数器 + 栈地址（ASLR）。
/// 生效条件：恒成立——每次调用返回 16 hex 字符；同进程单调计数保证批量提交
/// 互异，跨进程由 (时钟, pid, ASLR) 区分。
pub fn new_result_nonce() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let c = COUNTER.fetch_add(1, Ordering::Relaxed);
    let addr = &c as *const u64 as u64;
    let mut h: u64 = 0xcbf2_9ce4_8422_2325; // FNV-1a offset basis
    for x in [now_ms() as u64, std::process::id() as u64, c, addr] {
        for b in x.to_le_bytes() {
            h ^= b as u64;
            h = h.wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    format!("{h:016x}")
}

/// 建任务目录并落 spec.json + 初始 status(pending)。
/// 写序：spec.json 先行，status.json 后写 = 「任务就绪」信号，
/// serve 只领取见到 status.json 且 state=pending 的任务。
/// 生效条件：jobs 目录可写 → 建任务目录、先落 spec.json 再落 status(pending)
/// （status.json 出现 = 任务就绪可领取的发布信号），返回 job_id；任一写失败
/// → Err 且目录残留半成品（无害：serve 只领取见到 status=pending 的任务）。
pub fn init_job(jobs: &Path, spec_json: &Json, timeout_s: u64) -> Result<String, String> {
    init_job_with_anchor(jobs, spec_json, timeout_s, None)
}

/// 锚感知建任务（P11，批次53）：nonce 给定（= 提交面解析到了锚密钥）时在
/// status.json 追加 `result_nonce` 字段——该任务自此**声明锚预期**：终态判据面
/// 在采信 done 前校验 result.json 的 result_anchor（scheduler::classify_result）；
/// nonce 为 None = 旧格式任务（无锚预期），终态判据保持旧口径（向后兼容：
/// 存量消费者/手搭现场零变更）。
/// 生效条件：同 init_job；nonce=Some 时 status.json 多一个 `result_nonce`
/// 字符串字段（16 hex），其余字段与写序完全一致。
pub fn init_job_with_anchor(
    jobs: &Path,
    spec_json: &Json,
    timeout_s: u64,
    nonce: Option<&str>,
) -> Result<String, String> {
    let id = new_job_id();
    let dir = job_dir(jobs, &id);
    fs::create_dir_all(&dir).map_err(|e| format!("建任务目录失败: {e}"))?;
    write_json(&dir.join("spec.json"), spec_json)
        .map_err(|e| format!("写 spec.json 失败: {e}"))?;
    let mut status = vec![
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
    ];
    if let Some(n) = nonce {
        status.push(("result_nonce".to_string(), Json::Str(n.to_string())));
    }
    write_json(&dir.join("status.json"), &Json::Obj(status))
        .map_err(|e| format!("写 status.json 失败: {e}"))?;
    Ok(id)
}

/// 原子领取：`claimed.lock` create_new 成功者独占。返回 false = 已被领取。
/// 生效条件：claimed.lock 以 create_new 原子创建——成功 true = 本实例独占领取，
/// false = 已被领取（多 serve 竞争只有一胜者，不损坏数据）。
pub fn claim(dir: &Path) -> bool {
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(dir.join("claimed.lock"))
        .is_ok()
}

/// 读 status.json；不存在按 pending 前态处理（理论上仅在竞态窗口）。
/// 生效条件：status.json 存在且合法 → Ok(Json)；不存在 → Err（竞态窗口内
/// 调用方按 pending 前态处理）；坏文件 → Err（事故信号不吞）。
pub fn read_status(dir: &Path) -> Result<Json, String> {
    read_json(&dir.join("status.json"))
}

// ---------------------------------------------------- H-3 坏 status（可观测且可处置）

/// status.json 读取**三态**（H-3）。
///
/// 旧 `read_status` 把「文件不在」与「文件在但坏」都归 Err，调用方无从分辨
/// 「提交竞态窗口（正常时序，下拍就好）」与「status 损坏（事故，永不自愈）」，
/// 于是只能一律当半成品无限等待——这正是 H-3 的病灶（任务既不被领取也不被
/// 清理，只在 doctor 里变成一个 unknown）。
/// 生效条件：dir/status.json 存在且可解析 → `Ok(Json)`；**不存在** → `Absent`
/// （提交竞态窗口/手工删，调用方按「未就绪」下拍再看）；存在但读/解析失败 →
/// `Corrupt(原因)`——**必须与 Absent 区别对待**：Corrupt 是可观测、可标记、
/// 可隔离的事故信号，Absent 是正常时序。判据唯一实现（serve 主循环 /
/// recover_orphans / doctor 三处共用，勿各自 try/catch 出第二套口径）。
/// 不适用条件：不判断 state 取值合法性（那是 state 语义面的事，与本判据无关）。
pub enum StatusRead {
    Ok(Json),
    Absent,
    Corrupt(String),
}

/// 生效条件：dir 给定 → 按 StatusRead 三态分类（存在性先判，再解析）；
/// 文件不存在一律 Absent（与解析失败的 Corrupt 不混淆）。
pub fn read_status_classified(dir: &Path) -> StatusRead {
    let p = dir.join("status.json");
    if !p.is_file() {
        return StatusRead::Absent;
    }
    match read_json(&p) {
        Ok(v) => StatusRead::Ok(v),
        Err(e) => StatusRead::Corrupt(e),
    }
}

/// 坏 status 标记文件名（H-3）。
///
/// **旁证，不是任务本体**：status.json 即便不可解析也照原样留着（既是诊断证据，
/// 也是人工修复的输入）——标记只是「这台任务当前坏着」的独立落点，任何路径都
/// **不得**改写成 status.json 自己（覆盖任务本体 = 把事故静默吞掉）。
pub const CORRUPT_MARK: &str = "status.corrupt.json";

/// 坏 status 隔离保留区目录名（H-3）：池内子目录，`list_jobs` 只收 `h` 前缀
/// 目录，故移入者自动退出领取面/统计面（=「移出池」），但同卷同根——rename
/// 原子、任务目录逐字节不动、可原路退回（`doctor --unquarantine`）。
pub const QUARANTINE_DIR: &str = "_quarantine";

/// 生效条件：恒成立——坏 status 标记文件的路径（dir/status.corrupt.json）。
pub fn corrupt_mark_path(dir: &Path) -> PathBuf {
    dir.join(CORRUPT_MARK)
}

/// 生效条件：标记文件存在且合法 → Some(Json)；不存在/坏文件 → None
/// （消费者按「无标记」处理，不伪造默认值）。
pub fn read_corrupt_mark(dir: &Path) -> Option<Json> {
    read_json(&corrupt_mark_path(dir)).ok()
}

/// 生效条件：标记文件存在则删除，返回是否真的删了（幂等：无标记 → false
/// 不报错）——status 恢复可解析时撤销标记，信号跟随现实而非陈化。
pub fn clear_corrupt_mark(dir: &Path) -> bool {
    fs::remove_file(corrupt_mark_path(dir)).is_ok()
}

/// 落坏 status 标记（H-3）：**只写 status.corrupt.json，绝不碰 status.json**。
/// 生效条件：dir 可写且 job_id/ticks/threshold/first_ts/err 给定 → 写标记文件
/// （tmp+rename 原子，write_json 同款）；写失败 → Err 透传（serve 侧 `let _`，
/// 标记尽力而为：盘满/只读时 serve 的 stderr 告警与 doctor 归类仍在，不静默）。
/// 不适用条件：不改写/不改名 status.json（任务本体不受任何影响）。
pub fn write_corrupt_mark(
    dir: &Path,
    job_id: &str,
    ticks: u64,
    threshold: u64,
    first_ts: u128,
    err: &str,
) -> Result<(), String> {
    let v = Json::Obj(vec![
        ("job_id".to_string(), Json::Str(job_id.to_string())),
        ("kind".to_string(), Json::Str("status_unparseable".to_string())),
        ("detected_ts".to_string(), Json::Num(now_ms() as f64)),
        ("first_ts".to_string(), Json::Num(first_ts as f64)),
        ("ticks".to_string(), Json::Num(ticks as f64)),
        ("threshold".to_string(), Json::Num(threshold as f64)),
        ("last_error".to_string(), Json::Str(err.to_string())),
        (
            "note".to_string(),
            Json::Str(
                "status.json 不可解析（≥threshold 拍）：任务不被领取、不被改写；\
                 处置=doctor 归类 corrupt 后 doctor --quarantine 移出池（可 --unquarantine 退回）。\
                 本标记为独立旁证文件，status.json 本体逐字节未动。"
                    .to_string(),
            ),
        ),
    ]);
    write_json(&corrupt_mark_path(dir), &v).map_err(|e| e.to_string())
}

/// 隔离保留区中的任务名（H-3）：jobs/_quarantine 下 h 前缀目录，名升序。
/// 生效条件：jobs 给定 → 返回保留区内的任务目录名（目录不存在 → 空列表）；
/// 这些任务已退出领取面（list_jobs 不收），doctor 据此如实报「已隔离」。
pub fn quarantined_jobs(jobs: &Path) -> Vec<String> {
    let mut out = Vec::new();
    if let Ok(rd) = fs::read_dir(jobs.join(QUARANTINE_DIR)) {
        for e in rd.flatten() {
            let name = e.file_name().to_string_lossy().to_string();
            if name.starts_with('h') && e.path().is_dir() {
                out.push(name);
            }
        }
    }
    out.sort();
    out
}

/// 更新 status.json 的若干字段（读-改-写，全量覆盖）。
/// 生效条件：status.json 合法可读 → 读-改-写全量覆盖（write_json 原子替换），
/// 字段存在则覆写、不存在则追加；不可读 → Err。单写者纪律：仅领取者/serve
/// 写 status（并发安全要点，见模块头）。
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
/// 生效条件：worker 运行中周期调用——刷新 state/heartbeat_ts/elapsed_s
/// （started_ms>0 时按 now-started 计，否则 0）；超时强杀的「失联判据」即
/// heartbeat_ts 停更。写入失败 → Err 透传（worker 自行决定重试/退出）。
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
/// 生效条件：恒成立——kill 标志文件存在即 true（任意宿主创建，跨语言 kill 通道）。
pub fn kill_requested(dir: &Path) -> bool {
    dir.join("kill").exists()
}

/// 写 kill 标志（幂等）。
/// 生效条件：幂等写 kill 标志文件（已存在不重复创建）；写失败 → Err。
/// 不适用条件：不直接杀进程——真正回收由 worker 检测标志后的 kill 树路径执行。
pub fn request_kill(dir: &Path) -> Result<(), String> {
    let p = dir.join("kill");
    if !p.exists() {
        fs::File::create(&p).map_err(|e| format!("写 kill 标志失败: {e}"))?;
    }
    Ok(())
}

/// 列出全部任务目录名（按名升序 = 时间升序）。
/// 生效条件：恒成立——jobs 目录下 h 前缀子目录按名升序返回（名升序=提交
/// 时间升序，job_id 含毫秒时间戳保证）；目录不可读 → 空列表。
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
/// 生效条件：serve 主循环每拍调用——写 _serve.json（pid/ts/workers/exec_py/
/// exec_mode，tmp+rename 原子）。互验身份字段需走 write_serve_heartbeat_ext。
pub fn write_serve_heartbeat(
    jobs: &Path,
    workers: usize,
    exec_py: &Path,
    exec_mode: &str,
) -> Result<(), String> {
    write_serve_heartbeat_ext(
        jobs,
        workers,
        exec_py,
        exec_mode,
        None,
        None,
        None,
        None,
        None,
    )
}

/// 写 serve 心跳（互验扩展，批次10 §7.2）：instance/role/fingerprint/iter_id/
/// progress 五字段由 serve 自报（env 固化 + 判据面 digest），**显式设置才落**——
/// 消费者对缺失字段按「未知」处理，不伪造默认值（跨进程 env 不可反查，
/// 心跳是唯一权威来源）。
/// 生效条件：同 write_serve_heartbeat，另附互验五字段（instance/role/
/// fingerprint/iter_id/progress）——**显式 Some 才落**，None 时字段缺失，
/// 消费者按「未知」处理不伪造默认值（§7.2 兼容原则）。
#[allow(clippy::too_many_arguments)]
pub fn write_serve_heartbeat_ext(
    jobs: &Path,
    workers: usize,
    exec_py: &Path,
    exec_mode: &str,
    instance: Option<&str>,
    role: Option<&str>,
    fingerprint: Option<&str>,
    iter_id: Option<&str>,
    progress: Option<&str>,
) -> Result<(), String> {
    let mut v = vec![
        ("pid".to_string(), Json::Num(std::process::id() as f64)),
        ("ts".to_string(), Json::Num(now_ms() as f64)),
        ("workers".to_string(), Json::Num(workers as f64)),
        (
            "exec_py".to_string(),
            Json::Str(exec_py.to_string_lossy().to_string()),
        ),
        ("exec_mode".to_string(), Json::Str(exec_mode.to_string())),
    ];
    let opt = |k: &str, x: Option<&str>| {
        x.map(|s| (k.to_string(), Json::Str(s.to_string())))
    };
    v.extend(opt("instance", instance));
    v.extend(opt("role", role));
    v.extend(opt("fingerprint", fingerprint));
    v.extend(opt("iter_id", iter_id));
    v.extend(opt("progress", progress));
    write_json(&jobs.join("_serve.json"), &Json::Obj(v)).map_err(|e| e.to_string())
}

/// 读 serve 心跳（不存在 → None）。
/// 生效条件：_serve.json 存在且合法 → Some(Json)；不存在/坏文件 → None
/// （消费者按 no_heartbeat_or_legacy 口径如实标注，不伪造默认值）。
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

    /// 路径穿越防线（2026-09-25 缺陷复现口径）：`..` / `../victim` / `h/../../x`
    /// 等外部输入必须被拒——它们曾可经 job_dir 逃出 jobs 池写 kill 文件、读
    /// 任意目录 result 全文。
    #[test]
    fn valid_job_id_rejects_traversal() {
        // 合法形态：生成器产物 + 同构手写 id
        assert!(valid_job_id("h1758000000000_1a2b"));
        assert!(valid_job_id("h1_a"));
        assert!(valid_job_id("h"));
        // 穿越载体全拒：相对段 / 分隔符 / 盘符 / ADS / 绝对路径锚
        for bad in [
            "..",
            "../victim",
            "h/../../x",
            "h/.",
            "h\\..",
            "h:x",
            "/etc",
            "h..",
            "h.%.txt",
            "",
            "x123",
            "h\t",
        ] {
            assert!(!valid_job_id(bad), "穿越载体必须被拒: {bad:?}");
        }
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

    /// P11 结果锚（批次53）：nonce=Some 时 status 落 `result_nonce`；None 时
    /// 与旧格式逐字段一致（向后兼容）；nonce 生成器批量唯一。
    #[test]
    fn init_job_with_anchor_metadata() {
        let jobs = tmpdir("anchor");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        // 旧格式：无 result_nonce 字段
        let legacy = init_job(&jobs, &spec, 60).unwrap();
        let st = read_status(&job_dir(&jobs, &legacy)).unwrap();
        assert!(st.get("result_nonce").is_none(), "旧格式任务不得带锚字段");
        // 锚格式：result_nonce 落盘且与提交值一致
        let n1 = new_result_nonce();
        let anchored = init_job_with_anchor(&jobs, &spec, 60, Some(&n1)).unwrap();
        let st = read_status(&job_dir(&jobs, &anchored)).unwrap();
        assert_eq!(st.get("result_nonce").unwrap().as_str().unwrap(), n1);
        // nonce 唯一性：批量 1000 个互异、16 hex
        let mut seen = std::collections::HashSet::new();
        for _ in 0..1000 {
            let n = new_result_nonce();
            assert_eq!(n.len(), 16);
            assert!(seen.insert(n), "nonce 批量内必须互异");
        }
        let _ = fs::remove_dir_all(&jobs);
    }
}
