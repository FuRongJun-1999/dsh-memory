//! 执行器子进程拉起。
//!
//! 架构边界：HTTPS 与 LLM API 协议不进 rust（TLS 无第三方库不可行，D-005）。
//! 执行器是**可替换子进程**：默认 `python exec.py <job_dir>`（标准库 urllib），
//! rust 只持有子进程句柄管生命周期（等退出 / kill）。
//!
//! 执行器契约（exec.py 实现）：
//!   * 入参：argv[1] = job 目录；
//!   * 读 spec.json → 调 API → 写 result.json（成功与 API 错误都写，error 字段区分）；
//!   * 详细日志写 job/log.txt；stdout/stderr 保持安静（不污染 serve 控制台）；
//!   * 退出码：0 成功 / 2 规格错 / 3 API 错误；
//!   * **不得派生脱离生命周期的守护进程**：子进程须随执行器主进程退出
//!     （Windows 下 kill/timeout 走 kill_tree 进程树回收；unix 只杀直接子进程，
//!     孙进程存活即执行器违约）。

use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::OnceLock;

/// 解释器候选序列（顺序即契约）：POSIX 惯例名优先、Windows 惯例名兜底。
///
/// 为什么不能只判「名字在不在 PATH 上」（2026-09-28 根因取证）：Windows 的
/// `python3.exe` 常是 Microsoft Store 的**应用执行别名桩**——名字在 PATH 上、
/// 执行却退出 49（本机 `python3 -c "import sys"` 实测 exit=49，而 `python` 正常）。
/// 只判存在性会挑中一个跑不起来的桩，故候选须**试跑通过**才算可用（probe_runs）。
pub const PYTHON_CANDIDATES: [&str; 2] = ["python3", "python"];

/// 生效条件：env `HIVE_PYTHON` 去空白后非空 → 原样取之且**不探测**（显式压倒探测）；
/// 否则按 PYTHON_CANDIDATES 顺序探测首个可运行者；全不可跑时返回首候选名
/// （错误信息里指向符号名本身，而不是无声取一个不存在的解释器）。
pub fn resolve_python_bin(explicit: &str, probe: &dyn Fn(&str) -> bool) -> String {
    let e = explicit.trim();
    if !e.is_empty() {
        return e.to_string();
    }
    for cand in PYTHON_CANDIDATES {
        if probe(cand) {
            return cand.to_string();
        }
    }
    PYTHON_CANDIDATES[0].to_string()
}

/// 试跑判据：`<cand> -c ""` 退出码 0 才算可用。探测进程同样是 console 子系统
/// 程序，serve 无控制台时须 hide_window，否则每次探测闪一个新窗口。
fn probe_runs(cand: &str) -> bool {
    let mut c = Command::new(cand);
    c.arg("-c").arg("").stdout(Stdio::null()).stderr(Stdio::null());
    hide_window(&mut c);
    matches!(c.status(), Ok(s) if s.success())
}

/// 探测结果按进程缓存（PATH 在进程生命周期内不变；不缓存则每次拉起多付一次探测）。
/// 显式值不走缓存，仍每次读 env——测试与运行期改 env 都即时生效。
static PROBED_PYTHON: OnceLock<String> = OnceLock::new();

/// 生效条件：env HIVE_PYTHON 去空白后非空 → 取之；否则取进程内探测出的候选
/// （python3 优先、python 兜底，见 resolve_python_bin）——解释器的**唯一决策点**
/// （serve/runner 共用，不做各自的第二套决策：scheduler.rs 亦须经此，见
/// python_bin_tests::no_second_python_decision_point_in_scheduler）。
pub fn python_bin() -> String {
    let explicit = std::env::var("HIVE_PYTHON").unwrap_or_default();
    if !explicit.trim().is_empty() {
        return explicit.trim().to_string();
    }
    PROBED_PYTHON
        .get_or_init(|| resolve_python_bin("", &probe_runs))
        .clone()
}

/// Windows：抑制子进程弹出新的控制台窗口（其余平台为 no-op）。
///
/// 为什么必须显式设置（2026-09-22 根因取证）：serve 由 `serve_start.py` 以
/// `DETACHED_PROCESS` 拉起，**自身没有控制台**；而 `python.exe` / `tasklist.exe` 都是
/// console 子系统程序——Windows 在「父进程无控制台 且 子进程未声明
/// `CREATE_NO_WINDOW` / `DETACHED_PROCESS`」时会为它**新建一个可见的控制台窗口**，
/// 表现为「每执行一次任务就弹一个终端，打断使用者正在做的事」。
/// `CREATE_NO_WINDOW`（0x0800_0000）= 仍在控制台子系统下运行，但不分配可见窗口。
/// 生效条件：Windows 编译目标下对 Command 注入 CREATE_NO_WINDOW——
/// serve 无控制台时防「每任务弹一窗」。
#[cfg(target_os = "windows")]
pub fn hide_window(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

/// 非 Windows：无操作（unix 不存在「弹终端」这一形态）。
#[cfg(not(target_os = "windows"))]
pub fn hide_window(_cmd: &mut Command) {}

/// 终止执行器子进程。Windows 用 taskkill /T /F 回收**进程树**（含孙进程），
/// 其余平台只杀直接子进程（诚实边界：孙进程由执行器契约约束，见下）。
///
/// 为什么需要进程树回收（2026-09-22 实锤，外部设计稿 C10/M2）：`child.kill()` 在
/// Windows = TerminateProcess，**只杀直接子进程**——执行器派生的孙进程
/// （subprocess / 编译器 / 测试长睡进程）在 kill/timeout 后成为孤儿继续运行，
/// 占用端口、文件句柄，表现为「任务已 killed 但还有进程在跑」。
///
/// 实现约束：
///   * taskkill 是系统自带工具调用，**非 crate 依赖**（D-005 不破）；
///   * taskkill 自身是 console 程序，serve 无控制台，**必须 hide_window**
///     （否则每次强杀弹一个终端——迭代项 1 同族缺陷）；
///   * taskkill 失败回落 `child.kill()`（宁可只杀直接子进程，也不什么都不做）。
/// 生效条件：须终止执行器及其全部后代时调用——Windows taskkill /T /F（失败
/// 回落 child.kill()，宁可只杀直接子进程也不放任）；unix child.kill()。
/// 验证方式：test——judgment_surface::kill_tree_kills_grandchildren（孙进程
/// 3s 内消失，旧路径必红）。
pub fn kill_tree(child: &mut Child) {
    #[cfg(target_os = "windows")]
    {
        let pid = child.id();
        let mut cmd = Command::new("taskkill");
        cmd.args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        hide_window(&mut cmd);
        if cmd.status().is_err() {
            let _ = child.kill();
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = child.kill();
    }
}

/// **身份面** env 键（= keyres.rs::resolve_key_from_env 身份链，即锚密钥链两环）：
/// serve 进程持有，spawn 执行器子进程时**默认全部剥离**（N185 批次65 立闸，
/// N190 收窄到身份面）。
///
/// 剥离判据是**身份**，不是「键名里带不带 API/TOKEN」（N190，本批）：
///   * 在表内 = 身份令牌/锚密钥——执行器持之即可对任意任务自签合法锚
///     （keyres.rs 不可伪造性对最暴露进程失效），或以 serve 身份认领 principal；
///   * 不在表内 = 普通配置，随 serve env 默认继承给执行器。
///
/// 为什么 `HIVE_API_KEY` **不在**此表：它是**模型（网关）密钥**，属普通配置，
/// 执行器侧本来就通过 env 读它（hive/exec.py 的 `_post_chat`：`api_key =
/// os.environ.get("HIVE_API_KEY", "")`，缺即 RuntimeError；hive/orch.py 派发的
/// 子任务 spec 亦不写密钥、由子执行器继承同一 env）——剥离它只会让执行器拿不到
/// 模型密钥而报错，与身份面无关。
/// 故它既不剥离、也不需条件重注（两种任务形态一致地在执行器 env 中）。
const ORCH_SECRET_ENV_KEYS: [&str; 2] = ["HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE"];

/// spec.orchestrate 的 Python 真值（对齐 exec_cmd.py:177 `spec.get("orchestrate")`）：
/// 非空 Obj/Arr/Str、Bool(true)、Num(≠0) 为真；Null/空容器/空串为假。
/// spec.json 不可读/解析失败 → false（fail-closed：存疑时不注入身份令牌，
/// 编排器将报令牌缺失而非带密钥运行——宁错杀不漏密钥）。
fn spec_orchestrate(dir: &Path) -> bool {
    match crate::job::read_json(&dir.join("spec.json")) {
        Ok(v) => match v.get("orchestrate") {
            Some(crate::json::Json::Obj(kv)) => !kv.is_empty(),
            Some(crate::json::Json::Arr(a)) => !a.is_empty(),
            Some(crate::json::Json::Str(s)) => !s.is_empty(),
            Some(crate::json::Json::Bool(b)) => *b,
            Some(crate::json::Json::Num(n)) => *n != 0.0,
            _ => false,
        },
        Err(_) => false,
    }
}

/// 拉起执行器子进程（stdio 全 null：执行器自己写 job/log.txt）。
/// `anchor`（P11，批次53）：Some = 锚预期任务，注入 env `HIVE_RESULT_ANCHOR`
/// （执行器契约：回写 result.json `result_anchor` 字段，值原样透传）；None =
/// 旧格式任务，env 不含该键（执行器零感知，行为不变）。
/// N185（批次65）/N190 收窄 env 卫生：serve 侧**身份面**两键
/// （`ORCH_SECRET_ENV_KEYS` = 令牌 + 令牌文件，即 keyres.rs 锚密钥链正式两环）
/// **默认剥离**——exec.py:110-111 书面契约「锚的秘密性归 serve 侧密钥，执行器侧
/// 无法也不必复算」；执行器是接触不可信 LLM 内容最多、最可能被注入的进程，env
/// 继承会把身份令牌/锚密钥扩散给执行器及其派生的任意孙进程，拿到密钥即可对任意
/// 任务自签合法锚（keyres.rs 头注「不设公开缺省常量密钥」段：不可伪造性对最暴露
/// 进程失效）、并以 serve 身份认领 principal。唯一例外：spec.orchestrate 真值任务（执行器=orch.py 编排器）按
/// 身份面条件重注该两键（orch.py load_principal fail-closed 必需）。
/// `HIVE_API_KEY` **不在剥离面**（N190）：它是模型（网关）密钥、属普通配置，
/// exec.py 调 LLM 必需——随 serve env 默认继承到达执行器（两种任务形态一致），
/// 既不剥离也不再需要「条件重注」这条规则。
/// 生效条件：exec_py/dir 给定且解释器可达 → spawn 子进程（argv=[python,
/// exec_py, dir]，stdio 全 null——执行器自写 log.txt；anchor=Some 时 env 多
/// HIVE_RESULT_ANCHOR）返回 Child；解释器缺失 → Err。调用方持 Child 句柄管
/// 生命周期（wait/kill_tree）。
pub fn spawn_executor(
    exec_py: &Path,
    dir: &Path,
    anchor: Option<&str>,
) -> std::io::Result<Child> {
    let mut cmd = Command::new(python_bin());
    cmd.arg(exec_py)
        .arg(dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    // N185/N190：先剥离**身份面**两键（serve 身份令牌/锚密钥不随子进程扩散），
    // 后按 spec.orchestrate 条件重注同一份身份键表；模型密钥（HIVE_API_KEY）
    // 不在剥离面，随 env 默认继承到达执行器（exec.py 调 LLM 必需）。
    for k in ORCH_SECRET_ENV_KEYS {
        cmd.env_remove(k);
    }
    if spec_orchestrate(dir) {
        // 重注面 = 剥离面（同一常量，勿另立第二份身份键清单——两处清单分叉
        // 即「剥离了却不重注」或「重注了不该重注的」同族缺陷）。
        for k in ORCH_SECRET_ENV_KEYS {
            if let Ok(v) = std::env::var(k) {
                if !v.trim().is_empty() {
                    cmd.env(k, v);
                }
            }
        }
    }
    if let Some(a) = anchor {
        cmd.env("HIVE_RESULT_ANCHOR", a);
    }
    hide_window(&mut cmd);
    cmd.spawn()
}

#[cfg(test)]
mod python_bin_tests {
    use super::{probe_runs, resolve_python_bin, PYTHON_CANDIDATES};
    use std::cell::RefCell;

    /// 候选序本身是契约：POSIX 惯例名优先、Windows 惯例名兜底。
    /// 顺序写反（python 优先）等于把本缺陷重新引入。
    #[test]
    fn candidates_are_python3_first() {
        assert_eq!(PYTHON_CANDIDATES[0], "python3");
        assert_eq!(PYTHON_CANDIDATES[1], "python");
    }

    /// 探测「首个可运行者」：python3 不可跑时必须继续问 python，
    /// 且问询顺序可观测（不是只凭返回值反推）。
    #[test]
    fn probe_stops_at_first_runnable_in_order() {
        let asked = RefCell::new(Vec::new());
        let probe = |c: &str| {
            asked.borrow_mut().push(c.to_string());
            c == "python"
        };
        assert_eq!(resolve_python_bin("", &probe), "python");
        assert_eq!(*asked.borrow(), vec!["python3".to_string(), "python".to_string()]);
    }

    /// 首个候选可跑即收手——多余探测让每次拉起多付一个进程启动。
    #[test]
    fn probe_short_circuits_on_first_hit() {
        let asked = RefCell::new(Vec::new());
        let probe = |c: &str| {
            asked.borrow_mut().push(c.to_string());
            c == "python3"
        };
        assert_eq!(resolve_python_bin("", &probe), "python3");
        assert_eq!(*asked.borrow(), vec!["python3".to_string()]);
    }

    /// 显式设置压倒一切且**不探测**：用户指定的解释器即使探测不过也照用——
    /// 探测失败就静默换一个，等于把使用者的选择悄悄改掉，比照旧报错更坏。
    #[test]
    fn explicit_wins_and_never_probes() {
        let asked = RefCell::new(Vec::new());
        let probe = |c: &str| {
            asked.borrow_mut().push(c.to_string());
            false
        };
        assert_eq!(
            resolve_python_bin("/opt/venv/bin/python3", &probe),
            "/opt/venv/bin/python3"
        );
        assert!(asked.borrow().is_empty(), "显式路径不得触发探测");
    }

    /// 空白串按「未设置」处理——与 doc 的「非空 → 取之」一致。旧实现
    /// （unwrap_or_else）会把空串当值返回，spawn 时以 ENOENT 收场且难以归因。
    #[test]
    fn blank_explicit_is_unset() {
        let asked = RefCell::new(Vec::new());
        let probe = |c: &str| {
            asked.borrow_mut().push(c.to_string());
            c == "python"
        };
        assert_eq!(resolve_python_bin("   ", &probe), "python");
        assert!(!asked.borrow().is_empty(), "空白值应回落探测");
    }

    /// 两候选都不可跑时返回首候选（python3）：失败信息里指向的应是符号名本身，
    /// 而不是无声取一个不存在的解释器。
    #[test]
    fn no_candidate_runs_falls_back_to_first_name() {
        assert_eq!(resolve_python_bin("", &|_| false), "python3");
    }

    /// 端到端不变量：未设 HIVE_PYTHON 时 `python_bin()` 必须给出**真能跑**的解释器。
    /// 两候选都不可跑的环境跳过——那时正确行为是拉起失败且可见。
    #[test]
    fn resolved_binary_is_runnable_when_any_candidate_is() {
        if !PYTHON_CANDIDATES.iter().any(|c| probe_runs(c)) {
            return;
        }
        let picked = resolve_python_bin("", &probe_runs);
        assert!(probe_runs(&picked), "选中的解释器 {} 不可运行", picked);
    }

    /// 防腐蚀：解释器决策**单点在 exec.rs**——scheduler.rs 再写一次
    /// `Command::new("python")` 即第二套决策（本缺陷原形态）。源码自省，
    /// 判别力用合成正例自证，避免守卫退化成恒绿的空检查。
    #[test]
    fn no_second_python_decision_point_in_scheduler() {
        fn has_hardcoded_python(src: &str) -> bool {
            src.contains("Command::new(\"python\")") || src.contains("Command::new('python')")
        }
        assert!(has_hardcoded_python(r#"std::process::Command::new("python")"#));
        let src = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/src/scheduler.rs"))
            .expect("读 scheduler.rs");
        assert!(
            !has_hardcoded_python(&src),
            "scheduler.rs 出现硬编码 python 决策点——应改用 crate::exec::python_bin()"
        );
        assert!(src.contains("python_bin()"), "scheduler.rs 应经 python_bin() 取解释器");
    }
}

#[cfg(test)]
pub(crate) mod env_secrets_tests {
    use super::spawn_executor;
    use crate::json::parse;
    use std::path::Path;

    /// env 串行锁：env_secrets_tests 与 keyres::tests 同进程并行跑都会
    /// set/remove 同一批 HIVE_* 键（Rust 测试共享进程 env），不互斥即竞态假红
    /// （实测：HIVE_ORCH_TOKEN_FILE 在 keyres remove_var 窗口内被 spawn 读取
    /// 得 None）。两模块测试一律先持锁；容忍 poison（前测 panic 不连锁假红）。
    pub(crate) static ENV_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    fn env_lock() -> std::sync::MutexGuard<'static, ()> {
        ENV_TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// 哑执行器：把自身 HIVE_* env 原样落盘 dir/env_dump.json（N185 守卫面：
    /// spawn 子进程 env 的实际到达集，读码不算数）。
    fn write_dumper(dir: &Path) {
        let dump = dir.join("env_dump.json");
        let _ = std::fs::remove_file(&dump);
        std::fs::write(
            dir.join("env_dump_exec.py"),
            format!(
                "import json, os\n\
                 json.dump({{k: v for k, v in os.environ.items() if k.startswith('HIVE_')}}, \
                 open(r'{}', 'w', encoding='utf-8'))\n",
                dump.display()
            ),
        )
        .unwrap();
    }

    fn read_dump(dir: &Path) -> Vec<(String, String)> {
        let text = std::fs::read_to_string(dir.join("env_dump.json")).unwrap();
        match parse(&text).unwrap() {
            crate::json::Json::Obj(kv) => {
                kv.into_iter().map(|(k, v)| (k, v.to_json_string())).collect()
            }
            _ => panic!("env dump 非 JSON 对象"),
        }
    }

    fn env_of<'a>(dump: &'a [(String, String)], key: &str) -> Option<&'a str> {
        dump.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
    }

    /// 进程 env 恢复守卫（同 keyres::tests 模式：Rust test 同进程共享 env，
    /// set/remove 串行段内完成，测毕恢复原值；哑值独特以降低并行假撞）。
    /// 三键全设哑值：身份两键用于断言「被剥离 / orchestrate 重注」，
    /// `HIVE_API_KEY` 用于断言「模型密钥不被剥离、照旧到达执行器」（N190）。
    struct EnvGuard(Vec<(&'static str, Option<String>)>);
    impl EnvGuard {
        fn set_dummy() -> EnvGuard {
            let keys = ["HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE", "HIVE_API_KEY"];
            let saved: Vec<_> = keys.iter().map(|k| (*k, std::env::var(k).ok())).collect();
            std::env::set_var("HIVE_ORCH_TOKEN", "DUMMY-N185-TOKEN");
            std::env::set_var("HIVE_ORCH_TOKEN_FILE", "DUMMY-N185-NOT-A-FILE");
            std::env::set_var("HIVE_API_KEY", "DUMMY-N185-APIKEY");
            EnvGuard(saved)
        }
    }
    impl Drop for EnvGuard {
        fn drop(&mut self) {
            for (k, v) in &self.0 {
                match v {
                    Some(s) => std::env::set_var(k, s),
                    None => std::env::remove_var(k),
                }
            }
        }
    }

    fn temp_dir(tag: &str) -> std::path::PathBuf {
        let d = std::env::temp_dir().join(format!("n185-{}-{}", tag, std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    /// N185（批次65）/N190（本批，契约同步改口径）：serve 侧**身份面** env
    /// （exec.rs::ORCH_SECRET_ENV_KEYS 两键，= keyres.rs 身份/锚密钥链两环）不得随
    /// spawn_executor 继承扩散给执行器子进程——exec.py:110-111 书面契约「锚的
    /// 秘密性归 serve 侧密钥，执行器侧无法也不必复算」；执行器接触不可信 LLM 内容
    /// 最多，拿到身份令牌/锚密钥即可对任意任务自签合法锚。
    /// 普通任务（无 orchestrate）：身份两键剥离，HIVE_RESULT_ANCHOR 注入不受影响。
    /// N190 口径变更（本条第二段的旧断言「三键全不在」已按契约同步）：
    /// `HIVE_API_KEY` 是**模型（网关）密钥、普通配置**，不在剥离面——
    /// 普通任务下必须照旧到达执行器（exec.py 靠它调 LLM）。
    #[test]
    fn identity_secrets_stripped_from_plain_executor() {
        let _lock = env_lock();
        let _g = EnvGuard::set_dummy();
        let dir = temp_dir("plain");
        write_dumper(&dir);
        std::fs::write(
            dir.join("spec.json"),
            r#"{"model":"cmd","user_prompt":"t"}"#,
        )
        .unwrap();
        let mut child = spawn_executor(
            &dir.join("env_dump_exec.py"),
            &dir,
            Some("DUMMY-N185-ANCHOR"),
        )
        .unwrap();
        child.wait().unwrap();
        let dump = read_dump(&dir);
        assert!(env_of(&dump, "HIVE_ORCH_TOKEN").is_none(), "HIVE_ORCH_TOKEN 泄漏到执行器: {dump:?}");
        assert!(env_of(&dump, "HIVE_ORCH_TOKEN_FILE").is_none(), "HIVE_ORCH_TOKEN_FILE 泄漏: {dump:?}");
        assert_eq!(
            env_of(&dump, "HIVE_API_KEY"),
            Some(r#""DUMMY-N185-APIKEY""#),
            "模型密钥未到达执行器（N190：HIVE_API_KEY 不在剥离面）: {dump:?}"
        );
        assert_eq!(env_of(&dump, "HIVE_RESULT_ANCHOR"), Some(r#""DUMMY-N185-ANCHOR""#));
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// N190 口径固定：orchestrate 真值任务（spec.orchestrate → orch.py）需要
    /// 身份令牌认领 principal（orch.py load_principal fail-closed）——serve
    /// 按 spec.orchestrate 条件重注**身份两键**（重注面 = 剥离面，同一常量）；
    /// 同时 `HIVE_API_KEY` 与普通任务一致地到达（不在剥离面，无需重注）——
    /// 「编排器不得持模型密钥」在 N190 已作废：编排器派发的子任务是普通任务，
    /// 其子执行器继承同一 env 调 LLM，剥离主键只会打断编排。
    #[test]
    fn orchestrate_executor_gets_identity_token_and_model_key() {
        let _lock = env_lock();
        let _g = EnvGuard::set_dummy();
        let dir = temp_dir("orch");
        write_dumper(&dir);
        std::fs::write(
            dir.join("spec.json"),
            r#"{"model":"cmd","user_prompt":"t","orchestrate":{"subtasks":["a"]}}"#,
        )
        .unwrap();
        let mut child = spawn_executor(
            &dir.join("env_dump_exec.py"),
            &dir,
            Some("DUMMY-N185-ANCHOR"),
        )
        .unwrap();
        child.wait().unwrap();
        let dump = read_dump(&dir);
        assert_eq!(
            env_of(&dump, "HIVE_ORCH_TOKEN"),
            Some(r#""DUMMY-N185-TOKEN""#),
            "编排器身份令牌未注入: {dump:?}"
        );
        assert_eq!(
            env_of(&dump, "HIVE_ORCH_TOKEN_FILE"),
            Some(r#""DUMMY-N185-NOT-A-FILE""#),
        );
        assert_eq!(
            env_of(&dump, "HIVE_API_KEY"),
            Some(r#""DUMMY-N185-APIKEY""#),
            "模型密钥未到达编排器（N190：不在剥离面，继承即达）: {dump:?}"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }
}
