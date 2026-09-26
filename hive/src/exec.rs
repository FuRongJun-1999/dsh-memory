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

/// 拉起执行器子进程（stdio 全 null：执行器自己写 job/log.txt）。
/// `anchor`（P11，批次53）：Some = 锚预期任务，注入 env `HIVE_RESULT_ANCHOR`
/// （执行器契约：回写 result.json `result_anchor` 字段，值原样透传）；None =
/// 旧格式任务，env 不含该键（执行器零感知，行为不变）。
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
    if let Some(a) = anchor {
        cmd.env("HIVE_RESULT_ANCHOR", a);
    }
    hide_window(&mut cmd);
    cmd.spawn()
}
