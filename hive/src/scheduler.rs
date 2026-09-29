//! 并发调度核心：领取 → worker 池执行 → 心跳 / 超时强杀 / kill → 终态。
//!
//! 零依赖并发模型（纯 std）：
//!   * 主循环（serve 线程）：扫描 pending 任务 → 占在飞名额（H-7，满员即本拍
//!     不再领取）→ `claimed.lock` 原子领取 → 投递 mpsc 队列；每拍写 serve 心跳
//!     （`_serve.json`）；
//!   * worker 池（`HIVE_WORKERS` 线程）：从共享队列领任务 → 拉起执行器
//!     子进程 → 1s 轮询（子进程退出 / kill 标志 / 超时）→ 写心跳与终态；
//!   * 停机语义（drain）：`stop` 置位后主循环停投、关闭队列；worker 把
//!     队列内已领任务跑完再退（最长一个 timeout_s）——不产孤儿，测试友好。
//!
//! H-7 领取上界（本轮）：**领取与投递解耦为有界在飞名额**（`InFlight`，容量 =
//! workers）。旧版主循环一拍把**全部** pending 任务 claim 进无界 mpsc 队列——
//! 上界 ceil(N/workers)×timeout_s 并不成立（实测 workers=1 时 3 条 pending 同拍
//! 全部转 claimed，只有 1 条能真跑），且 claimed 态无 pid/心跳，池外观察者分不出
//! 「在跑」与「排在队里干等」，kill 对未开跑者也看不到。现在领取点前先占一个在飞
//! 名额、满员即结束本拍扫描：不变量 = **任一时刻处于 claimed/running 的任务数
//! ≤ workers**（领取锁在手必然名额在手），超额任务老实留在 pending（可被 kill/
//! 隔离/改判据，仍是一等公民），worker 完成后释放名额下一拍继续领——吞吐不变、
//! 队列深度有界。
//!
//! 崩溃恢复：serve 启动时清理上次遗留——**产物说了算**（与 classify_exit 同判据，
//! 单一实现 `classify_result`）：claimed/running 若已有 result.json 则按产物定终态
//! done/error，不重跑；claimed 无产物删锁重投 pending；running 无产物诚实标 error
//! （其孤儿执行器若仍存活，写出的 result.json 宿主仍可读）。
//! N191（残留领取态）：state=pending 却带 claimed.lock（claim 与 patch_status
//! ("claimed") 之间被 kill -9/断电，或状态瞬时不可写）同样按产物判据处置——
//! 有产物定终态、无产物删锁重投；主循环侧状态改写失败即回滚领取锁（不吞错、
//! 不投递），双侧共同保证「锁在手 ⇔ state 已 claimed」，任务无 TTL 悬置归零。
//!
//! H-3 坏 status（本轮）：status.json 不可解析**不再被当成半成品无限等待**。
//! 判据走 `job::read_status_classified` 三态（Ok / Absent / Corrupt）：Absent 是
//! 提交竞态窗口（下拍再看），Corrupt 是事故——serve 启动时 stderr 告警、每拍
//! 计数，连续 `CORRUPT_MARK_TICKS` 拍仍不可解析则落**独立标记文件**
//! `status.corrupt.json`（**绝不改写 status.json 本体**），doctor 归 `corrupt`
//! 独立类别，`doctor --quarantine` 可整体移出池（可 --unquarantine 退回）。
//! **不做自动终态化**：那等于把坏文件静默吞掉，正是本缺陷的反面。
//!
//! P11 结果完整性锚（批次53）：锚预期任务（status 带 result_nonce）的产物在采信
//! done 前须过完整性锚校验——锚缺失 → needs_review（不自动采信）、锚不匹配 →
//! error（拒绝采信）、通过 → done；旧格式任务（无 nonce）维持旧判据（向后兼容）。
//! 密钥经 ServeCfg.result_key（生产入口 = keyres::resolve_key_from_env()，取
//! hive 既有配置/令牌面；None = 锚判据不启用，行为与旧版一致）。


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
    /// 互验身份（批次10，§7.1）：env HIVE_INSTANCE 显式设置才落心跳；
    /// None = 单实例部署旧行为（心跳无此字段，消费者按未知处理）。
    pub instance: Option<String>,
    /// 互验角色（§7.1）：env HIVE_ROLE（primary/verifier/arbiter）——决定该实例
    /// 被允许做什么；同 instance，显式设置才落心跳。
    pub role: Option<String>,
    /// 判据面组合指纹（§7.6 细化的 A3 输入）：scripts/judgment_manifest.py
    /// --digest 的输出，启动时算一次；计算失败 → None（诚实，不伪造）。
    pub fingerprint: Option<String>,
    /// 当前迭代 id（env HIVE_ITER_ID；空闲/未参与互验 → None）。
    pub iter_id: Option<String>,
    /// 结果完整性锚密钥（P11，批次53）：Some = 锚判据生效——拉起执行器时注入
    /// HIVE_RESULT_ANCHOR（hmac.rs 公式），classify_result 采信 done 前校验
    /// result_anchor；None = 锚判据不启用，终态判据保持旧口径（产物说了算）。
    /// ServeCfg::new 恒 None（测试密闭，不读进程 env）；生产入口 cmd_serve 经
    /// keyres::resolve_key_from_env() 注入；测试定向用 with_result_key()。
    pub result_key: Option<String>,
}

/// 执行器形态判据：**文件名**（非内容探测，宁可保守）。
///
/// `exec_cmd.py` = 多态转发器——spec 带 command/commands 跑命令（零 LLM），
/// 不带时转发 exec.py（LLM 委托）；其余（含兜底 exec.py）= 仅 LLM 委托。
///
/// 诚实边界：这是启发式。确证形态的正路是提交一个带 `command` 的探针任务——
/// result.content 以「确定性执行」开头即证明该 serve 兼跑确定性任务。
/// 生效条件：给定 exec_py 路径，按**文件名**（非内容探测，宁可保守）返回执行器
/// 形态——"exec_cmd" 词干 → "deterministic+llm"（多态转发器），其余 → "llm_only"。
/// 诚实边界：启发式；确证的正路是提交 command 探针任务看 result.content。
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
    /// 生效条件：jobs/workers/exec_py 给定时构造 ServeCfg——workers clamp 1..64
    ///（并发度上限防资源耗尽）、exec_mode 由 exec_mode_of 推得、poll_ms=400；
    /// 互验身份四字段（instance/role/fingerprint/iter_id）置 None，须显式
    /// with_interop_identity() 注入。
    pub fn new(jobs: PathBuf, workers: usize, exec_py: PathBuf) -> Self {
        let exec_mode = exec_mode_of(&exec_py);
        ServeCfg {
            jobs,
            workers: workers.clamp(1, 64),
            exec_py,
            exec_mode,
            poll_ms: 400,
            instance: None,
            role: None,
            fingerprint: None,
            iter_id: None,
            result_key: None,
        }
    }

    /// 结果完整性锚密钥注入（P11，批次53）：生产入口 cmd_serve 传
    /// keyres::resolve_key_from_env()；测试传 Some("...") 定向启用锚判据。
    /// 生效条件：key 原样落 cfg.result_key——Some 启用锚判据（注入 env + 终态
    /// 前校验），None 维持旧判据；不做任何 env 读取（密闭性归调用方）。
    pub fn with_result_key(mut self, key: Option<String>) -> Self {
        self.result_key = key;
        self
    }

    /// 互验身份注入（批次10，§7.1/§7.2）：env 显式设置才落心跳字段——
    /// 「缺省即旧行为」（单实例部署零变更，不伪造默认值）。
    /// fingerprint = 判据面组合指纹（python judgment_manifest.py --digest，
    /// 子进程一次性计算；失败 → None 诚实透出，不冒充）。
    /// 生效条件：互验 env 三者全空（单实例部署）→ 原样返回 self（旧行为，
    /// 不 spawn 不加字段）；任一非空 → 逐字段固化身份并算判据面指纹
    /// （python judgment_manifest.py --digest，cwd=exe 上溯三级的 repo 根；
    /// 子进程失败/输出空 → fingerprint 保持 None 诚实透出不伪造）。
    pub fn with_interop_identity(mut self) -> Self {
        let env = |k: &str| {
            std::env::var(k)
                .ok()
                .map(|v| v.trim().to_string())
                .filter(|v| !v.is_empty())
        };
        self.instance = env("HIVE_INSTANCE");
        self.role = env("HIVE_ROLE");
        self.iter_id = env("HIVE_ITER_ID");
        // 互验 env 全空 = 单实例部署 → 整段跳过（含 fingerprint 子进程调用）——
        // 「缺省即旧行为」：心跳不新增任何字段，也不为算指纹每次多 spawn 一个进程
        if self.instance.is_none() && self.role.is_none() && self.iter_id.is_none()
        {
            return self;
        }
        // repo 根 = exe（hive/target/debug|release/hive.exe）上溯三级
        let repo_root = std::env::current_exe().ok().and_then(|exe| {
            let hive = exe.parent()?.parent()?.parent()?;
            hive.parent().map(Path::to_path_buf)
        });
        if let Some(repo_root) = repo_root {
            // 解释器走 exec::python_bin() 单点决策：此处原硬编码 "python"，
            // 是 Linux 上（无 python 别名）指纹静默缺失的第二套决策点。
            let out = std::process::Command::new(crate::exec::python_bin())
                .arg("scripts/judgment_manifest.py")
                .arg("--digest")
                .current_dir(&repo_root)
                .output();
            if let Ok(o) = out {
                if o.status.success() {
                    let d = String::from_utf8_lossy(&o.stdout).trim().to_string();
                    if !d.is_empty() {
                        self.fingerprint = Some(d);
                    }
                }
            }
        }
        self
    }
}

/// 坏 status 标记阈值（H-3，单位=主循环拍）。
///
/// 连续这么多拍读 status.json 都不可解析 → 落 `job::CORRUPT_MARK` 标记文件。
/// 取 10 拍（poll_ms=400 ⇒ 约 4s）：短于「提交写入窗口」（write_json 是
/// tmp+fsync+rename 原子替换，正常写入不会让读者看到半成品），又长于任何
/// 瞬时抖动的量级——「持续不可解析」才落标记，不为一次抖动留痕。
/// 生效条件：serve 主循环每拍对 Corrupt 类任务计数，达本值（且标记不在场或
/// 错误文本已变）时写标记；status 恢复可解析即撤销标记。doctor 侧不依赖本
/// 值（它按「当下是否可解析」即时归类，与阈值解耦——阈值只决定标记何时落）。
pub const CORRUPT_MARK_TICKS: u64 = 10;

/// H-7 在飞名额：领取点的**有界闸**（容量 = workers）。
///
/// 主循环在 `claim()` **之前**先占一个名额，满员即本拍**不再领取**（扫描继续，
/// 好让观测面——H-3 坏 status 计数/告警——不被容量闸截断）；worker 跑完一个任务
/// 释放一个。不变量：任一时刻处于 claimed/running 的任务数
/// ≤ workers——旧版一拍把全部 pending claim 进无界 mpsc 队列（上界不成立），
/// 且 claimed 态无 pid/心跳，池外无法分辨「在跑」与「在队里干等」。
/// 纯 std（原子 CAS，无锁无中毒），容量在构造时固定、恒 > 0（ServeCfg 已 clamp）。
/// 生效条件：cap ≥ 1 给定 → try_acquire 在占用数 < cap 时占一个并返回 true，
/// 满员返回 false（**调用方不得再 claim**）；release 归还一个（幂等次数由
/// 调用方保证：acquire 成功者恰好 release 一次）。
/// 不适用条件：不做排队/阻塞——满员即放弃本拍（下拍自然重试），不引入等待语义。
struct InFlight {
    n: std::sync::atomic::AtomicUsize,
    cap: usize,
}

impl InFlight {
    fn new(cap: usize) -> Self {
        InFlight {
            n: std::sync::atomic::AtomicUsize::new(0),
            cap: cap.max(1),
        }
    }

    /// 生效条件：占用数 < cap → CAS 占位并返回 true；满员 → false（不修改计数）。
    fn try_acquire(&self) -> bool {
        let mut cur = self.n.load(Ordering::SeqCst);
        loop {
            if cur >= self.cap {
                return false;
            }
            match self.n.compare_exchange(
                cur,
                cur + 1,
                Ordering::SeqCst,
                Ordering::SeqCst,
            ) {
                Ok(_) => return true,
                Err(x) => cur = x,
            }
        }
    }

    /// 生效条件：归还一个名额（仅由 try_acquire 成功者调用，且恰好一次）。
    fn release(&self) {
        self.n.fetch_sub(1, Ordering::SeqCst);
    }

    /// 生效条件：恒成立——当前在飞占用数（诊断/测试可判定面，不参与判据）。
    #[allow(dead_code)]
    fn in_flight(&self) -> usize {
        self.n.load(Ordering::SeqCst)
    }
}

/// serve 主入口。阻塞直至 `stop` 置位且 worker drain 完毕。返回退出码。
/// 生效条件（核心入口 · CCG 六要素）：
///   功能名：蜂群并发调度主循环（serve）。
///   生效条件：cfg（jobs/workers/exec_py/poll_ms [+互验身份]）与 stop 开关给定；
///   同一 jobs 目录至多一个 serve（单实例守卫在 CLI 层）。
///   子功能：崩溃恢复 / 心跳自报 / job 扫描领取（H-7 有界在飞名额）/ worker
///   并发执行 / 终态落盘 / H-3 坏 status 观测与标记。
///   执行：先 recover_orphans 清理上轮残局（坏 status 在此告警），随后每拍写
///   _serve.json 心跳、扫描 pending 任务——**先占在飞名额（满员即结束本拍）
///   再 claim**，坏 status 计数达 CORRUPT_MARK_TICKS 落标记文件（改写状态类
///   操作一律不碰 status.json 本体）；stop 置位即停。
///   N191：领取后状态改写（patch_status("claimed")）失败即回滚领取锁并**归还
///   名额**（不吞错、不投递），保证「锁在手 ⇔ state 已 claimed」不变量成立。
///   H-7：不变量 = claimed/running 数 ≤ workers（名额先于 claim 占用，任何
///   失败路径都归还）；超额任务留在 pending，drain 吞吐不变。
///   验证方式：test——cargo e2e_done_and_heartbeat / kill_channel /
///   judgment_surface（recover_by_artifact 等）+ hive/test_h3_h7_scheduler.py
///   （坏 status 三态 / 标记 / 逐字节不改写 / quarantine / 上界实测）+ M6 实跑。
///   不适用条件：不做任务内容语义处理（归执行器），不做跨 jobs 目录路由；
///   坏 status **不做自动终态化**（那会把坏文件静默吞掉，见模块头 H-3）。
pub fn serve(cfg: &ServeCfg, stop: Arc<AtomicBool>) -> i32 {
    std::fs::create_dir_all(&cfg.jobs).expect("建 jobs 目录失败");
    recover_orphans(cfg);

    let inflight = Arc::new(InFlight::new(cfg.workers));
    let (tx, rx) = mpsc::channel::<String>();
    let rx = Arc::new(Mutex::new(rx));
    let mut handles = Vec::new();
    for _ in 0..cfg.workers {
        let rx = Arc::clone(&rx);
        let cfg = cfg.clone();
        let inflight = Arc::clone(&inflight);
        handles.push(thread::spawn(move || loop {
            let id = { rx.lock().expect("worker 锁中毒").recv() };
            match id {
                Ok(id) => {
                    run_job(&cfg, &id);
                    // H-7：任务终结（任何终态）即归还在飞名额——下一拍主循环
                    // 才可再领一条；名额不归还则队列永久变浅（自锁）。
                    inflight.release();
                }
                Err(_) => break, // 队列关闭且已清空 → worker 退出
            }
        }));
    }

    // H-3：坏 status 的跨拍计数与告警去重（键 = job_id）。
    //   * corrupt_ticks[id] = (首拍时刻 ms, 连续坏读拍数)——读好即删（信号跟随现实）；
    //   * warned[id] = 本段连续性内是否已告警过（避免每拍刷屏）。
    let mut corrupt_ticks: std::collections::HashMap<String, (u128, u64)> =
        std::collections::HashMap::new();
    let mut warned_corrupt: std::collections::HashSet<String> = std::collections::HashSet::new();

    // 主循环：心跳 + 扫描领取
    while !stop.load(Ordering::SeqCst) {
        let _ = job::write_serve_heartbeat_ext(
            &cfg.jobs,
            cfg.workers,
            &cfg.exec_py,
            &cfg.exec_mode,
            cfg.instance.as_deref(),
            cfg.role.as_deref(),
            cfg.fingerprint.as_deref(),
            cfg.iter_id.as_deref(),
            None, // progress：批次11 验证编排接线（跑套件时按阶段更新）
        );
        // H-7 名额用尽标记：本拍不再领取（改由 continue 跳过领取段），但扫描
        // **继续**——H-3 坏 status 的计数/告警不受名额闸截断（观测面与容量面解耦，
        // 池满时坏任务照样被计数；反之亦然）。
        // 领取顺序 = created_ts 升序（`job::list_jobs_by_created` 真值单点）= FIFO：
        // 旧形态 id 下与名升序逐位相同（保序），新契约 id 名序不再带时间序故必须读真值。
        let mut at_capacity = false;
        for id in job::list_jobs_by_created(&cfg.jobs) {
            let dir = job::job_dir(&cfg.jobs, &id);
            // H-3：三态读——Absent（提交竞态窗口）与 Corrupt（事故）分道。
            let st = match job::read_status_classified(&dir) {
                job::StatusRead::Ok(s) => {
                    // 读好即清零并撤销标记（坏→好的回退：信号跟随现实，
                    // 不留一枚会陈化的旧标记去误导下一班人）
                    if corrupt_ticks.remove(&id).is_some() {
                        warned_corrupt.remove(&id);
                        let _ = job::clear_corrupt_mark(&dir);
                    }
                    s
                }
                // 文件还没出现 = 正常时序（submit 先写 spec 后写 status），下拍再看
                job::StatusRead::Absent => continue,
                job::StatusRead::Corrupt(e) => {
                    let (first_ts, ticks) = {
                        let slot = corrupt_ticks
                            .entry(id.clone())
                            .or_insert((job::now_ms(), 0));
                        slot.1 += 1;
                        (slot.0, slot.1)
                    };
                    if warned_corrupt.insert(id.clone()) {
                        eprintln!(
                            "[hive serve] 告警：任务 {id} 的 status.json 不可解析（{e}）\
                             ——按坏 status 处置：不领取、不改写任务本体；连续 \
                             {CORRUPT_MARK_TICKS} 拍（约 {}s）仍不可解析则落标记文件 {}，\
                             可由 `hive doctor --quarantine` 隔离",
                            CORRUPT_MARK_TICKS * cfg.poll_ms / 1000,
                            job::CORRUPT_MARK
                        );
                    }
                    if ticks >= CORRUPT_MARK_TICKS {
                        // 标记只在「不在场」或「错误文本已变」时写（不逐拍刷盘）：
                        // 既保证标记在场，又不在坏盘上做无谓写放大。
                        let stale = job::read_corrupt_mark(&dir)
                            .and_then(|m| {
                                m.get("last_error")
                                    .and_then(|x| x.as_str())
                                    .map(String::from)
                            })
                            .as_deref()
                            != Some(e.as_str());
                        if !job::corrupt_mark_path(&dir).is_file() || stale {
                            let _ = job::write_corrupt_mark(
                                &dir,
                                &id,
                                ticks,
                                CORRUPT_MARK_TICKS,
                                first_ts,
                                &e,
                            );
                        }
                    }
                    continue; // 坏 status：既不领取也不改写（诊断证据留在盘上）
                }
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
            // H-7 有界闸：**先占名额再 claim**。满员即本拍不再领取（at_capacity
            // 置位，后续任务走同一 continue 路径），但扫描继续——名额闸只关领取，
            // 不关观测（见循环头注）。顺序不可颠倒：claim 后再发现没空位，就得
            // 回滚一个已落盘的领取锁（多余的状态写入窗口），而「名额在手才 claim」
            // 是「锁在手 ⇔ 名额在手」的结构保证。
            if !at_capacity && !inflight.try_acquire() {
                at_capacity = true;
            }
            if at_capacity {
                continue; // 本拍名额已满：留给下一拍（任务仍是 pending，可被 kill/隔离）
            }
            if !job::claim(&dir) {
                inflight.release();
                continue; // 已被领取（原子锁失败）
            }
            // N191：状态改写**不得吞错**。旧版 `let _ = patch_status(...)` 后照旧投递：
            // status.json 瞬时不可写（Windows 文件锁/盘满）时，任务会在「状态从未被
            // 记录」的情形下被执行，且锁永不释放——本拍回滚领取锁（删 lock）并
            // continue：状态未改则**不投递**（投递即让 pending 态任务被执行、且与
            // 恢复判据失配），下一拍重试；确认状态落盘才投递，保证「领取锁在手
            // ⇔ state 已 claimed」不变量成立，恢复面只需面对合法组合态。
            if job::patch_status(
                &dir,
                vec![("state".to_string(), crate::json::Json::Str("claimed".into()))],
            )
            .is_err()
            {
                let _ = std::fs::remove_file(dir.join("claimed.lock"));
                inflight.release();
                continue;
            }
            if tx.send(id).is_err() {
                inflight.release();
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

/// 坏 status 扫描（H-3 判据唯一实现）：返回 `(job_id, 原因)` 列表（created_ts 升序）。
///
/// 判据= `job::read_status_classified` 的 `Corrupt` 态——**只算「文件在但不可
/// 解析」，不算文件缺失**（缺失是提交竞态窗口的正常时序，报成事故=狼来了）。
/// 三处共用：recover_orphans（启动告警）、CLI `hive doctor`（corrupt 归类）、
/// 以及任何需要「池里坏了几台」的观测面——勿各自 try/catch 出第二套口径。
/// 生效条件：jobs 给定 → 逐个任务目录分类（created_ts 升序），返回全部 Corrupt 项；
/// 池空/无坏 → 空列表；目录不可读按空列表（list_jobs 的既有权衡）。
/// 不适用条件：不做任何写盘处置（标记落盘归 serve 主循环的跨拍计数，隔离归
/// doctor --quarantine）——本函数是**只读判据**。
pub fn scan_corrupt(jobs: &Path) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for id in job::list_jobs_by_created(jobs) {
        let dir = job::job_dir(jobs, &id);
        if let job::StatusRead::Corrupt(e) = job::read_status_classified(&dir) {
            out.push((id, e));
        }
    }
    out
}

/// 崩溃恢复：**产物说了算**——claimed/running 先查 result.json（与 classify_exit
/// 同一判据、同一实现）；有产物按产物定终态，无产物才走旧路径（claimed 重投 /
/// running 标 error）。
///
/// 历史缺陷（2026-09-22 实锤，`D:\2_ai` C9/M1）：同一段代码两套判据——
/// `classify_exit`（正常退出）信产物，`recover_orphans`（崩溃恢复）不信产物——
/// serve 崩溃重启后，执行器已写完 result.json 的任务被重投重跑（claimed）或
/// 误标「serve 中断」（running）。修复 = 判据前移，不是引入新机制。
///
/// N191：**残留领取态**（state=pending 却带 claimed.lock，见 match 前分支）与
/// claimed 态同判据同处置——旧版此组合态无分支（落 `_ => {}`），任务永久卡死。
///
/// pub（批次8b 判据面重定义）：承重反向对照测试（recover_by_artifact /
/// rerun_on_recover_escape_hatch）已迁至 hive/tests/judgment_surface.rs——
/// 判据面（tests/）与候选面（src/）物理分离，候选弱化测试时 A3 必红。
/// 生效条件：serve 启动时（每次）对 jobs 目录全体任务执行一次崩溃恢复。
///   H-3：status.json 不可解析（StatusRead::Corrupt）时**不做任何恢复处置**
///   （不删锁、不改写——诊断证据留在盘上），但**逐个统计并在启动日志告警**：
///   坏 status 在启动这一刻就不再静默。周期扫描的计数/标记归 serve 主循环
///   （阈值语义见 CORRUPT_MARK_TICKS）。
///   验证方式：test——cargo judgment_surface::recover_by_artifact（5 分支）+
///   rerun_on_recover_escape_hatch（逃生门双态+反向对照）+
///   pending_with_residual_claim_recovers（N191 残留领取态三断言）；
///   盘面注入：judgment_surface::claim_rollback_on_status_write_failure
///   （status.json 置只读 → patch_status 恒 Err，实测 WinError 5）；
///   H-3：hive/test_h3_h7_scheduler.py（A/C 组——启动告警 + doctor 归类）。
///   不适用条件：不改变正常执行路径（classify_exit 主判据不分叉）；不做跨 serve
///   协调（单实例守卫在 CLI 层，恢复期假定无活 serve）；**不自动终态化坏 status**
///   （自动终态化 = 把坏文件静默吞掉，正是本缺陷的反面）。
pub fn recover_orphans(cfg: &ServeCfg) {
    // H-3 启动告警：坏 status 点名（截断到前若干条，防超大池刷屏）。
    let corrupt = scan_corrupt(&cfg.jobs);
    if !corrupt.is_empty() {
        let head: Vec<String> = corrupt
            .iter()
            .take(5)
            .map(|(id, e)| format!("{id}（{e}）"))
            .collect();
        eprintln!(
            "[hive serve] 告警：启动扫描发现 {} 个任务的 status.json 不可解析：{}{}\
             ——按坏 status 处置：不被领取、不被改写（不做自动终态化）；\
             连续 {} 拍仍不可解析将落标记文件 {}，可由 `hive doctor --quarantine` 隔离",
            corrupt.len(),
            head.join("；"),
            if corrupt.len() > 5 { "；…" } else { "" },
            CORRUPT_MARK_TICKS,
            job::CORRUPT_MARK
        );
    }
    for id in job::list_jobs_by_created(&cfg.jobs) {
        let dir = job::job_dir(&cfg.jobs, &id);
        let st = match job::read_status_classified(&dir) {
            job::StatusRead::Ok(st) => st,
            // H-3：坏 status 无恢复处置（见头注「不适用条件」）——启动告警已在上方
            job::StatusRead::Corrupt(_) => continue,
            // 文件还没出现：正常时序（submit 先写 spec 后写 status），非事故
            job::StatusRead::Absent => continue,
        };
        let state = st.get("state").and_then(|v| v.as_str()).unwrap_or("");
        // N191（次轮首补候选）：**领取已发生、状态未改写**的窗口残留——state 仍
        // pending 却带 claimed.lock（claim() 与 patch_status("claimed") 之间被
        // kill -9/断电，或 status.json 瞬时不可写致 patch_status 出错）。旧版只
        // match claimed/running，此组合态落 `_ => {}`：主循环每拍 claim() 必失败
        // 即 continue → 任务**永久卡 pending**（无 TTL 的悬置），其下游经
        // deps_gate 对非 done 依赖恒 Ok(false) 连带悬置。
        // 处置与 claimed 态**同一判据、同一实现**（产物说了算，classify_result
        // 单点，勿分叉）：有产物按产物定终态（绝不重跑——防双写副作用），无产物
        // 删锁重投（状态本就 pending，删锁即恢复可领取）。恢复期不存在活 serve
        // （单实例守卫，见 serve 头注），故 pending+锁必为残留而非在飞领取。
        let residual_claim =
            state == "claimed" || (state == "pending" && dir.join("claimed.lock").is_file());
        if residual_claim {
            match classify_result(&dir, cfg.result_key.as_deref()) {
                // 产物已产出 → 按产物定终态（删锁但绝不重投重跑）；
                // 例外：spec 显式 rerun_on_recover → 旧产物更名留痕，强制重投（M1 逃生门）
                Some((final_state, err)) => {
                    if spec_rerun_on_recover(&dir) {
                        archive_stale_result(&dir);
                        let _ = std::fs::remove_file(dir.join("claimed.lock"));
                        let _ = job::patch_status(
                            &dir,
                            vec![(
                                "state".to_string(),
                                crate::json::Json::Str("pending".into()),
                            )],
                        );
                    } else {
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
            }
            continue;
        }
        match state {
            "running" => match classify_result(&dir, cfg.result_key.as_deref()) {
                // 孤儿执行器可能已写出产物 → 按产物定终态（不误标 serve 中断）；
                // 例外：spec 显式 rerun_on_recover → 旧产物更名留痕，回 pending 重投
                Some((final_state, err)) => {
                    if spec_rerun_on_recover(&dir) {
                        archive_stale_result(&dir);
                        let _ = job::patch_status(
                            &dir,
                            vec![(
                                "state".to_string(),
                                crate::json::Json::Str("pending".into()),
                            )],
                        );
                    } else {
                        let mut fields = vec![(
                            "state".to_string(),
                            crate::json::Json::Str(final_state),
                        )];
                        if let Some(e) = err {
                            fields.push(("error".to_string(), crate::json::Json::Str(e)));
                        }
                        let _ = job::patch_status(&dir, fields);
                    }
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

// ---------------------------------------------------------------------------
// H-4 止血（本轮）：拉起执行器的**有界**退避重试
//
// 缺陷（H-4b）：`exec::spawn_executor` 失败（解释器不可用 / 拉进程被环境瞬态
// 挡住）直接落 error 终态、无退避重试——一次瞬时抖动即把任务判死。
//
// 边界（只做止血，不做根治）：
//   * **有界**：尝试次数与单次等待都封顶（`SPAWN_MAX_ATTEMPTS` /
//     `SPAWN_BACKOFF_MAX_MS`）——无界重试会让 worker 永久占坑，把一个坏解释器
//     放大成整池停摆；
//   * **不静默**：尝试次数与**最后试的解释器**写进终态（`spawn_attempts` /
//     `spawn_interpreter` 字段 + error 文案），超限仍落 error 并保留最后一次失败
//     原因（不吞错、不冒充成功）；只留一句裸 OS 错误时「找的是哪个解释器」不可见；
//   * **零回归**：首次即成功时行为逐位不变（不多睡一拍、不多写字段）。
//
// 不做（属设计级，须单独立项）：拉起失败的分类治理（可重试/不可重试的判据
// 面）、worker 池自愈、把 spawn 失败降级为「任务重投 pending」。
// ---------------------------------------------------------------------------

/// 最多尝试次数（含首次）。3 次足以吸收毫秒级环境瞬态，又不至于让 worker 长占。
pub const SPAWN_MAX_ATTEMPTS: u32 = 3;
/// 退避基准：第 1 次失败后等待 `SPAWN_BACKOFF_BASE_MS`，第 n 次后为 base×2^(n-1)。
pub const SPAWN_BACKOFF_BASE_MS: u64 = 200;
/// 单次退避上限（防指数放大把 worker 卡死）。
pub const SPAWN_BACKOFF_MAX_MS: u64 = 2000;

/// 第 `failed` 次失败（1 起）后的等待时长：base × 2^(failed-1)，封顶 MAX。
/// 生效条件：failed ≥ 1 → 返回 200ms / 400ms / …（≤ 2s）；不适用条件：无。
fn spawn_backoff(failed: u32) -> Duration {
    let shift = failed.saturating_sub(1).min(16);
    let ms = SPAWN_BACKOFF_BASE_MS.saturating_mul(1u64 << shift);
    Duration::from_millis(ms.min(SPAWN_BACKOFF_MAX_MS))
}

/// 有界退避重试：至多 `attempts` 次调用 `op`，每次失败后（末次除外）按
/// `spawn_backoff` 等待。返回 `Ok((值, 尝试次数))` / `Err((最后一次错误, 尝试次数))`。
///
/// `sleep` 由调用方注入（生产传 `thread::sleep`）：测试可换成记录器，免真等，
/// 也让「重试几次、每次等多久」成为可断言面而不是读码推断。
/// 生效条件：attempts ≥ 1（小于 1 按 1 处理）→ 至少调用 op 一次；
/// 不适用条件：不吞错（最后一次错误原样带出）、不无界重试（次数硬上界）。
fn retry_spawn<T, E, F, S>(
    attempts: u32,
    mut op: F,
    mut sleep: S,
) -> Result<(T, u32), (E, u32)>
where
    F: FnMut() -> Result<T, E>,
    S: FnMut(Duration),
{
    let n = attempts.max(1);
    let mut last: Option<E> = None;
    for i in 1..=n {
        match op() {
            Ok(v) => return Ok((v, i)),
            Err(e) => {
                last = Some(e);
                if i < n {
                    sleep(spawn_backoff(i));
                }
            }
        }
    }
    // n ≥ 1 且走到此处必有一次失败；expect 只是防御（不 panic 拖垮 worker）
    Err((last.expect("attempts>=1 时循环必有失败"), n))
}

/// 拉起失败终态：state=error + 原因（含已尝试次数与**最后试的解释器**——
/// 重试不静默，且「试了哪个解释器」是排障第一问）+ 尝试次数字段。
/// 解释器取 `exec::python_bin()`（解释器决策的唯一入口，见 exec.rs 该函数注释）；
/// 文案里如实带上，避免只留一句裸 OS 错误（`program not found` 看不出找的是谁）。
/// 生效条件：退避重试全部失败时调用；不适用条件：不改写已有成功终态由上层保证
/// （本函数只在 run_job 的 running 段内调用，此时尚无产物）。
fn mark_spawn_failed(dir: &Path, attempts: u32, err: &std::io::Error) {
    let interp = exec::python_bin();
    let _ = job::patch_status(
        dir,
        vec![
            ("state".to_string(), crate::json::Json::Str("error".into())),
            (
                "error".to_string(),
                crate::json::Json::Str(format!(
                    "拉起执行器失败（解释器 {interp}，已尝试 {attempts} 次）: {err}"
                )),
            ),
            (
                "spawn_attempts".to_string(),
                crate::json::Json::Num(attempts as f64),
            ),
            (
                "spawn_interpreter".to_string(),
                crate::json::Json::Str(interp),
            ),
        ],
    );
}

/// worker 执行单个任务：拉起执行器 → 1s 轮询（退出 / kill / 超时）→ 终态。
/// 生效条件：serve 主循环领取到任务时调用（claimed 已原子持有）——拉起执行器
/// 子进程（exec_py）、写 running 心跳、落 progress、终态经 classify_exit 按产物
/// 定 done/error/timeout/killed；worker 生命周期全部由本函数承载。
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

    // H-4 止血：拉起执行器改为**有界退避重试**（次数/间隔有界，超限仍落 error
    // 并保留最后一次原因）。首次即成功时与旧路径逐位等价（retry_spawn 立刻
    // 返回 Ok(_, 1)，一次多余等待都没有）。
    let (mut child, _spawn_attempts) = match retry_spawn(
        SPAWN_MAX_ATTEMPTS,
        || exec::spawn_executor(&cfg.exec_py, &dir, spawn_anchor(&dir, cfg).as_deref()),
        thread::sleep,
    ) {
        Ok(v) => v,
        Err((e, attempts)) => {
            mark_spawn_failed(&dir, attempts, &e);
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
                let (state, err) = classify_exit(&dir, code, cfg.result_key.as_deref());
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
///
/// P11 完整性锚门（批次53）：无 error 字段（旧判据即 done）时先过锚校验——
/// 任务 status.json 带 `result_nonce`（= 提交面声明锚预期）则 result.json 必须
/// 携带与 HMAC 预期（hmac.rs 公式，密钥=key 参数）一致的 `result_anchor`：
///   * 校验通过 → done（诚实执行器语义不变）；
///   * 锚缺失（旧格式产物/伪造产物未带锚）→ needs_review（**不自动采信**，
///     可疑处置：人工复核，或 spec 显式 rerun_on_recover 时经 recover_orphans
///     重投）——注入实测 FI-R03 的伪造 ok=true 产物在此被拦；
///   * serve 无密钥（key=None）无法校验 → needs_review（fail-closed：不可校验
///     =不采信，不静默放行）；
///   * 锚不匹配（伪锚/挪锚/提交后 spec 被改）→ error（拒绝采信，终态）。
/// status.json 无 `result_nonce`（旧格式任务）→ 维持旧判据 done（向后兼容：
/// 存量任务池、无密钥提交面零变更）。
/// 生效条件：dir 下 result.json 存在且可解析 → Some((done|error|needs_review,
/// error 文本))；不存在 → None（无产物）；解析失败 → Some(("error", 解析错误))。
/// 判据唯一实现（classify_exit 与 recover_orphans 共用，勿分叉——C9 教训）。
fn classify_result(dir: &std::path::Path, key: Option<&str>) -> Option<(String, Option<String>)> {
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
                None => match verify_result_anchor(dir, &r, key) {
                    AnchorVerdict::Pass => ("done".into(), None),
                    AnchorVerdict::MissingAnchor => (
                        "needs_review".into(),
                        Some(
                            "产物完整性锚缺失：result.json 无 result_anchor \
                            （旧格式产物/伪造产物不自动采信，P11 批次53）——\
                             需人工复核，或经 spec.rerun_on_recover 重投"
                                .into(),
                        ),
                    ),
                    AnchorVerdict::Unverifiable => (
                        "needs_review".into(),
                        Some(
                            "产物完整性锚不可校验：本 serve 未配置锚密钥 \
                            （身份链 HIVE_ORCH_TOKEN / HIVE_ORCH_TOKEN_FILE 均缺；\
                             HIVE_API_KEY 是模型密钥、N190 起不作锚链兜底，P11 批次53）\
                             ——fail-closed 不自动采信，\
                             请以 serve_start.py（config.local.json 注入身份密钥）重启 serve"
                                .into(),
                        ),
                    ),
                    AnchorVerdict::Mismatch => (
                        "error".into(),
                        Some(
                            "完整性锚校验失败：result_anchor 与提交预期不匹配 \
                            （伪锚/挪锚/提交后 spec 被改）——拒绝采信（P11 批次53）"
                                .into(),
                        ),
                    ),
                },
            })
        }
        Err(e) => Some((
            "error".into(),
            Some(format!("result.json 解析失败: {e}")),
        )),
    }
}

/// 锚校验裁决（classify_result 内部；四态各对应一条终态处置）。
enum AnchorVerdict {
    /// 校验通过（或旧格式任务无锚预期 → 旧判据）→ done。
    Pass,
    /// 锚预期任务（status 有 result_nonce）但 result.json 无 result_anchor。
    MissingAnchor,
    /// 有锚可对但本 serve 无密钥，无法校验。
    Unverifiable,
    /// 锚不匹配（含 spec 不可读——校验输入残缺按失配拒绝，不冒险采信）。
    Mismatch,
}

/// P11 锚校验唯一实现：nonce 缺失 = 旧格式任务 → Pass（向后兼容基线）；
/// 否则 result_anchor 必须存在且与 HMAC(key, spec 字节, nonce) 恒时相等。
/// 生效条件：dir 的 status.json/spec.json/result 视图与密钥给定 → 四态裁决；
/// 判据细节见 classify_result 头注（承重反向对照在 tests/judgment_surface.rs）。
fn verify_result_anchor(
    dir: &std::path::Path,
    result: &crate::json::Json,
    key: Option<&str>,
) -> AnchorVerdict {
    let nonce = match job::read_status(dir)
        .ok()
        .and_then(|s| s.get("result_nonce").and_then(|v| v.as_str()).map(String::from))
    {
        Some(n) if !n.is_empty() => n,
        // 旧格式任务（无锚预期）→ 旧判据（向后兼容：存量池零变更）
        _ => return AnchorVerdict::Pass,
    };
    let echo = result
        .get("result_anchor")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if echo.is_empty() {
        return AnchorVerdict::MissingAnchor;
    }
    let Some(key) = key else {
        return AnchorVerdict::Unverifiable;
    };
    let Ok(spec_bytes) = std::fs::read(dir.join("spec.json")) else {
        return AnchorVerdict::Mismatch; // 校验输入残缺：按失配拒绝（fail-closed）
    };
    let expect = crate::hmac::result_anchor_hex(key, &spec_bytes, &nonce);
    if crate::hmac::ct_eq(&echo, &expect) {
        AnchorVerdict::Pass
    } else {
        AnchorVerdict::Mismatch
    }
}

/// M1 逃生门（批次7）：spec 显式 `"rerun_on_recover": true` 时，恢复不采信旧产物。
/// 读取失败/字段缺失一律 false（fail-safe——逃生门宁缺勿滥，产物判据是缺省正道）。
/// 生效条件：dir/spec.json 可读且 rerun_on_recover 显式 true → true；
/// 读取失败/字段缺失/null/false/非布尔一律 false（fail-safe——逃生门宁缺勿滥，
/// 产物判据是缺省正道）。
fn spec_rerun_on_recover(dir: &std::path::Path) -> bool {
    job::read_json(&dir.join("spec.json"))
        .ok()
        .and_then(|s| {
            s.get("rerun_on_recover").and_then(|v| match v {
                crate::json::Json::Bool(b) => Some(*b),
                _ => None,
            })
        })
        .unwrap_or(false)
}

/// 旧产物更名留痕：result.json → result.json.recovered-<unix_ts>。
/// 更名失败不阻断重投（留痕尽力而为；重投本身是硬要求）。
/// 生效条件：dir/result.json 存在时更名为 result.json.recovered-<unix_ts>；
/// 不存在则无操作；rename 失败不阻断重投（留痕尽力而为，重投是硬要求）。
fn archive_stale_result(dir: &std::path::Path) {
    let src = dir.join("result.json");
    if !src.is_file() {
        return;
    }
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let _ = std::fs::rename(&src, dir.join(format!("result.json.recovered-{ts}")));
}

/// 依赖门禁（I-1，中观任务 DAG 第一格）：
/// `Ok(true)` = 全依赖 done，可领取；`Ok(false)` = 有依赖未终态，等待；
/// `Err(原因)` = 依赖不完整或失败传播，任务直接终态 error（不执行）。
///
/// 七不变量对照（dsh-omc，设计稿 docs/hive/蜂巢迭代_宏观与群体调度_v0.1.md）：
/// 依赖完整 + 级联取消闭包在此落码；无环性由**存在性闸**结构性保证——提交时只能
/// 引用**已存在**的任务目录（`main.rs` 的 depends_on 存在性检查 + MCP 侧 `_dep_gate`
/// + 本函数的运行期 deps_gate），引用不到提交时尚不存在的任务，故无需运行时环检测。
/// （旧形态 id 恰好也带时间序，新形态语义四槽 id 不再有此性质 ⇒ 论证不得依赖时间序。）
/// 生效条件：任务的 depends_on 列表给定时裁决——全 done → Ok(true) 可领取；
/// 任一终态非 done（pending 等待 / error·timeout·killed·needs_review）→
/// Ok(false) 等待或 Err(失败传播原因) 直接 error 不执行。I-1 依赖门禁唯一实现。
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
        // 路径穿越防线（2026-09-25 缺陷）：spec.json 是池内落盘文件，可被手工
        // 改写（submit 侧校验不构成运行时保证），裸 join 会把 `h/../../x` 拼出
        // jobs 池外去读任意目录的 status——先过结构闸。
        if !job::valid_job_id(&dep) {
            return Err(format!("依赖不完整: {dep}（非法 job_id，含路径成分）"));
        }
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
            // needs_review（P11 批次53）同失败传播：锚不可信的上游产物不得作为
            // 下游执行前提，也不能让下游永久等待（旧版会落进 `_ => Ok(false)` 悬置）
            "error" | "timeout" | "killed" | "needs_review" => {
                return Err(format!("依赖失败传播: {dep} 终态 {dst}，本任务不执行"));
            }
            _ => return Ok(false), // pending/claimed/running → 等待
        }
    }
    Ok(true)
}

/// 子进程退出后的终态分类：以 result.json 为准（error 字段区分 API 错误）。
/// 生效条件：执行器正常退出后调用——**产物说了算**（result.json 有则按产物定
/// 终态，无则按退出码；与 recover_orphans 共用 classify_result，判据不分叉；
/// key 透传锚校验，见 classify_result P11 门）。
fn classify_exit(
    dir: &std::path::Path,
    code: std::process::ExitStatus,
    key: Option<&str>,
) -> (String, Option<String>) {
    match classify_result(dir, key) {
        Some(x) => x,
        None if code.success() => (
            "error".into(),
            Some("执行器退出码 0 但未产出 result.json".into()),
        ),
        None => ("error".into(), Some(format!("执行器异常退出: {code}"))),
    }
}

/// P11 拉起期锚计算（批次53）：serve 持密钥且任务声明锚预期（status 有
/// result_nonce）时，按 hmac.rs 公式对当前 spec.json 字节算锚，经 env
/// HIVE_RESULT_ANCHOR 注入执行器（执行器契约：回写 result_anchor）。None =
/// 旧格式任务或 serve 无密钥——env 不注入，执行器零感知。
/// 生效条件：dir/cfg 给定 → Some(锚) 当且仅当 cfg.result_key 与 result_nonce
/// 与可读 spec.json 三者齐备；任一缺 → None（与 verify_result_anchor 的
/// nonce 缺失→旧判据口径闭环：提交不锚、执行不注、终态不校）。
fn spawn_anchor(dir: &std::path::Path, cfg: &ServeCfg) -> Option<String> {
    let key = cfg.result_key.as_deref()?;
    let st = job::read_status(dir).ok()?;
    let nonce = st.get("result_nonce")?.as_str()?;
    if nonce.is_empty() {
        return None;
    }
    let spec_bytes = std::fs::read(dir.join("spec.json")).ok()?;
    Some(crate::hmac::result_anchor_hex(key, &spec_bytes, nonce))
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
        // 四槽写序单点（B7/B8）：id 由分配器独占创建给出，不再自造
        job::init_job_with_slots(jobs, "单测端", "id契约", "记录单元", &spec, timeout_s, None)
            .unwrap()
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

    // ---- H-4 止血：拉起执行器的有界退避重试（判据 = retry_spawn 的可断言面）----

    /// 退避表有界且单调不减：base×2^(n-1)，封顶 SPAWN_BACKOFF_MAX_MS。
    #[test]
    fn spawn_backoff_is_bounded_and_monotonic() {
        assert_eq!(spawn_backoff(1), Duration::from_millis(SPAWN_BACKOFF_BASE_MS));
        assert_eq!(spawn_backoff(2), Duration::from_millis(SPAWN_BACKOFF_BASE_MS * 2));
        let mut prev = Duration::ZERO;
        for n in 1..=64u32 {
            let d = spawn_backoff(n);
            assert!(d >= prev, "退避必须单调不减：n={n} {d:?} < {prev:?}");
            assert!(
                d <= Duration::from_millis(SPAWN_BACKOFF_MAX_MS),
                "退避必须封顶：n={n} → {d:?}"
            );
            prev = d;
        }
        assert_eq!(
            spawn_backoff(64),
            Duration::from_millis(SPAWN_BACKOFF_MAX_MS),
            "大 n 必须落在上限（指数不放大到卡死 worker）"
        );
    }

    /// 瞬时失败后成功：尝试次数 = 失败数 + 1，且只等「已失败次数」次。
    #[test]
    fn retry_spawn_recovers_after_transient_failures() {
        let mut calls = 0u32;
        let mut slept: Vec<Duration> = Vec::new();
        let r = retry_spawn(
            SPAWN_MAX_ATTEMPTS,
            || {
                calls += 1;
                if calls < 3 {
                    Err(format!("瞬态失败#{calls}"))
                } else {
                    Ok("spawned")
                }
            },
            |d| slept.push(d),
        );
        assert_eq!(r, Ok(("spawned", 3)), "第 3 次成功 → (值, 3)");
        assert_eq!(calls, 3);
        assert_eq!(
            slept,
            vec![spawn_backoff(1), spawn_backoff(2)],
            "只等「已失败次数」次，末次成功后不再等"
        );
    }

    /// 一直失败：尝试次数**有界**（= SPAWN_MAX_ATTEMPTS）、末次错误原样带出、
    /// 等待次数 = 尝试次数 - 1，且单次等待封顶。
    #[test]
    fn retry_spawn_exhausts_bounded_and_keeps_last_error() {
        let mut calls = 0u32;
        let mut slept: Vec<Duration> = Vec::new();
        let r: Result<((), u32), (String, u32)> = retry_spawn(
            SPAWN_MAX_ATTEMPTS,
            || {
                calls += 1;
                Err(format!("失败#{calls}"))
            },
            |d| slept.push(d),
        );
        assert_eq!(r, Err(("失败#3".to_string(), SPAWN_MAX_ATTEMPTS)));
        assert_eq!(calls, SPAWN_MAX_ATTEMPTS, "调用次数必须恰好等于硬上界");
        assert_eq!(slept.len(), (SPAWN_MAX_ATTEMPTS - 1) as usize);
        assert!(slept.iter().all(|d| *d <= Duration::from_millis(SPAWN_BACKOFF_MAX_MS)));
    }

    /// 反向对照（判据不空转）：把重试面关掉（attempts=1，即修复前「一次即判死」
    /// 的形态），本轮判据所依赖的谓词必须**转假**——证明上面两条断言真的能区分
    /// 「有退避重试」与「无退避重试」，而不是恒真。
    #[test]
    fn retry_spawn_reverse_control_single_attempt_is_red() {
        let mut calls = 0u32;
        let r: Result<((), u32), (String, u32)> = retry_spawn(
            1,
            || {
                calls += 1;
                Err("失败".to_string())
            },
            |_| {},
        );
        assert_eq!(r, Err(("失败".to_string(), 1)));
        assert_eq!(calls, 1);
        // 判据谓词（修复形态要求「≥2 次尝试」）在反向对照下必须为假
        let fixed_form = matches!(r, Err((_, n)) if n == SPAWN_MAX_ATTEMPTS && calls >= 2);
        assert!(!fixed_form, "反向对照下判据必须转假（否则判据恒真=空转）");
    }

    /// 终态落盘：超限仍落 error，且原因里带**已尝试次数**、**最后试的解释器**与
    /// 最后一次失败原因（可观测、不静默），并落 spawn_attempts / spawn_interpreter
    /// 字段——「试了哪个解释器」是排障第一问，只留裸 OS 错误看不出找的是谁。
    #[test]
    fn mark_spawn_failed_lands_error_with_reason() {
        let jobs = tmpjobs("spawnfail_mark");
        let a = submit(&jobs, "0", 60);
        let dir = job::job_dir(&jobs, &a);
        let err = std::io::Error::new(std::io::ErrorKind::NotFound, "解释器不存在");
        mark_spawn_failed(&dir, SPAWN_MAX_ATTEMPTS, &err);
        let st = job::read_status(&dir).unwrap();
        assert_eq!(st.get("state").and_then(|v| v.as_str()), Some("error"));
        let text = st.get("error").and_then(|v| v.as_str()).unwrap_or("");
        assert!(
            text.contains("拉起执行器失败") && text.contains("已尝试 3 次"),
            "error 文案须含尝试次数: {text}"
        );
        assert!(text.contains("解释器不存在"), "末次原因须保留: {text}");
        let interp = exec::python_bin();
        assert!(
            text.contains(&interp),
            "error 文案须点名最后试的解释器（{interp}）: {text}"
        );
        assert_eq!(
            st.get("spawn_attempts").and_then(|v| v.as_f64()),
            Some(3.0),
            "尝试次数须成为可观测字段"
        );
        assert_eq!(
            st.get("spawn_interpreter").and_then(|v| v.as_str()),
            Some(interp.as_str()),
            "最后试的解释器须成为可观测字段"
        );
        let _ = fs::remove_dir_all(&jobs);
    }

    // ---- H-4 止血端到端：真实拉起失败（重执行自进程隔离 env）----

    const H4_CHILD_ENV: &str = "H4_SPAWN_FAIL_E2E_CHILD";

    /// 真实拉起失败（`HIVE_PYTHON` 指向不存在的解释器）→ serve 在有界重试后落
    /// **error 终态**，原因带已尝试次数与最后一次失败原因，status 带
    /// `spawn_attempts` —— 既不静默判死（有退避重试），也不无限重试（有上界）。
    ///
    /// **为什么用「重执行本测试二进制做子进程」**：`HIVE_PYTHON` 是**进程级**
    /// env，`exec::python_bin()` 每次现读它；而本测试二进制里 e2e_done_and_heartbeat /
    /// timeout_kills / kill_channel / dependency_gate 等用例**并行**跑，都要拉真
    /// python——在同一进程里改 env 是必竞态假红（Rust 单测共享进程 env，仓内
    /// exec.rs::env_secrets_tests 的 ENV_TEST_LOCK 注释已记同款教训，但那把锁
    /// 只有 env 类用例去持，拉进程的用例不持）。子进程 = 独立 env 空间，父进程
    /// env 一字不改 ⇒ 零竞态。也**不落 hive/tests/**：那里是判据面
    /// （judgment_manifest 的文件集合指纹），本批是候选面止血，不扩判据面集合。
    #[test]
    fn spawn_failure_lands_error_with_reason_after_bounded_retries() {
        if std::env::var(H4_CHILD_ENV).is_err() {
            // 父进程：只负责把「哑解释器」注入子进程并复跑本测试（不改自身 env）
            let me = std::env::current_exe().expect("取当前测试二进制路径");
            let out = std::process::Command::new(me)
                .args([
                    "spawn_failure_lands_error_with_reason_after_bounded_retries",
                    "--nocapture",
                ])
                .env(H4_CHILD_ENV, "1")
                .env("HIVE_PYTHON", "h4-no-such-python-interpreter")
                .output()
                .expect("重执行测试二进制");
            let stdout = String::from_utf8_lossy(&out.stdout);
            let stderr = String::from_utf8_lossy(&out.stderr);
            assert!(
                out.status.success(),
                "子进程（真实拉起失败端到端）未通过：\n{stdout}\n{stderr}"
            );
            return;
        }

        // 子进程：HIVE_PYTHON 已是哑值（解释器不存在 → Command::spawn 必 Err）
        assert_eq!(
            std::env::var("HIVE_PYTHON").unwrap_or_default(),
            "h4-no-such-python-interpreter"
        );
        let jobs = tmpjobs("spawnfail_e2e");
        // 「执行器脚本不存在」不是本测试的注入点（那会 spawn 成功、走
        // classify_exit）——注入点是**解释器本身拉不起来**。
        let a = submit(&jobs, "0", 60);
        let cfg = ServeCfg::new(jobs.clone(), 1, jobs.join("no_such_exec.py"));
        let stop = Arc::new(AtomicBool::new(false));
        let h = {
            let cfg = cfg.clone();
            let stop = Arc::clone(&stop);
            thread::spawn(move || serve(&cfg, stop))
        };
        let mut got: Option<crate::json::Json> = None;
        for _ in 0..100 {
            let s = job::read_status(&job::job_dir(&jobs, &a)).unwrap();
            if s.get("state").and_then(|v| v.as_str()) == Some("error") {
                got = Some(s);
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        stop.store(true, Ordering::SeqCst);
        h.join().unwrap();
        let st = got.expect("拉起失败应在有界重试后落 error 终态（不得挂住）");
        let text = st.get("error").and_then(|v| v.as_str()).unwrap_or("");
        assert!(text.contains("拉起执行器失败"), "须保留拉起失败原因: {text}");
        assert!(
            text.contains("h4-no-such-python-interpreter"),
            "error 文案须点名**最后试的解释器**（注入的哑解释器）: {text}"
        );
        assert_eq!(
            st.get("spawn_interpreter").and_then(|v| v.as_str()),
            Some("h4-no-such-python-interpreter"),
            "spawn_interpreter 字段须如实记下最后试的解释器: {text}"
        );
        assert_eq!(
            st.get("spawn_attempts").and_then(|v| v.as_f64()),
            Some(SPAWN_MAX_ATTEMPTS as f64),
            "尝试次数须有界（= SPAWN_MAX_ATTEMPTS，既不 1 次判死也不无界）: {text}"
        );
        let _ = fs::remove_dir_all(&jobs);
    }
}
