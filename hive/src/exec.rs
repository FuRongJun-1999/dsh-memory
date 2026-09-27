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

/// 生效条件：env HIVE_PYTHON 非空 → 取之；否则回落 PATH 上的 python——
/// 解释器的唯一决策点（serve/runner 共用，不做各自的第二套决策）。
pub fn python_bin() -> String {
    std::env::var("HIVE_PYTHON").unwrap_or_else(|_| "python".to_string())
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
/// 为什么需要进程树回收（2026-09-22 实锤，`D:\2_ai` C10/M2）：`child.kill()` 在
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

/// 锚密钥链 env 键（与 keyres.rs::resolve_key_from_env 解析链同源）：serve 进程
/// 持有，spawn 执行器子进程时**默认全部剥离**（N185，批次65）。
const ORCH_SECRET_ENV_KEYS: [&str; 3] =
    ["HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE", "HIVE_API_KEY"];

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
/// N185（批次65）env 卫生：serve 侧锚密钥链三键（`ORCH_SECRET_ENV_KEYS`）**默认
/// 剥离**——exec.py:110-111 书面契约「锚的秘密性归 serve 侧密钥，执行器侧无法
/// 也不必复算」；执行器是接触不可信 LLM 内容最多、最可能被注入的进程，env 继承
/// 会把 serve 密钥扩散给执行器及其派生的任意孙进程，拿到密钥即可对任意任务自签
/// 合法锚（keyres.rs:10-11 不可伪造性对最暴露进程失效）。唯一例外：spec.orchestrate
/// 真值任务（执行器=orch.py 编排器）按身份面条件重注 HIVE_ORCH_TOKEN/
/// HIVE_ORCH_TOKEN_FILE（orch.py load_principal fail-closed 必需）；HIVE_API_KEY
/// 永不重注（编排器不调 LLM API）。
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
    // N185：先剥离锚密钥链（serve env 不随子进程扩散），后按身份面条件重注。
    for k in ORCH_SECRET_ENV_KEYS {
        cmd.env_remove(k);
    }
    if spec_orchestrate(dir) {
        for k in ["HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE"] {
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

    /// N185：serve 侧锚密钥链 env（keyres.rs 解析链三键）不得随 spawn_executor
    /// 继承扩散给执行器子进程——exec.py:110-111 书面契约「锚的秘密性归 serve
    /// 侧密钥，执行器侧无法也不必复算」；执行器接触不可信 LLM 内容最多，拿到
    /// 密钥即可对任意任务自签合法锚。普通任务（无 orchestrate）：三键全剥离，
    /// HIVE_RESULT_ANCHOR 注入不受影响。
    #[test]
    fn env_secrets_stripped_from_plain_executor() {
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
        assert!(env_of(&dump, "HIVE_API_KEY").is_none(), "HIVE_API_KEY 泄漏: {dump:?}");
        assert_eq!(env_of(&dump, "HIVE_RESULT_ANCHOR"), Some(r#""DUMMY-N185-ANCHOR""#));
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// N185 口径固定：orchestrate 真值任务（spec.orchestrate → orch.py）需要
    /// 身份令牌认领 principal（orch.py load_principal fail-closed）——serve
    /// 按 spec.orchestrate 条件重注 HIVE_ORCH_TOKEN/HIVE_ORCH_TOKEN_FILE，
    /// 但 HIVE_API_KEY（编排器不调 LLM API）永不注入。
    #[test]
    fn orchestrate_executor_gets_identity_token_not_api_key() {
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
        assert!(env_of(&dump, "HIVE_API_KEY").is_none(), "HIVE_API_KEY 不得进编排器: {dump:?}");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
