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
//!   * 退出码：0 成功 / 2 规格错 / 3 API 错误。

use std::path::Path;
use std::process::{Child, Command, Stdio};

/// 默认解释器（env HIVE_PYTHON 可覆盖；否则 PATH 上的 python）。
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
#[cfg(target_os = "windows")]
pub fn hide_window(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

/// 非 Windows：无操作（unix 不存在「弹终端」这一形态）。
#[cfg(not(target_os = "windows"))]
pub fn hide_window(_cmd: &mut Command) {}

/// 拉起执行器子进程（stdio 全 null：执行器自己写 job/log.txt）。
pub fn spawn_executor(exec_py: &Path, dir: &Path) -> std::io::Result<Child> {
    let mut cmd = Command::new(python_bin());
    cmd.arg(exec_py)
        .arg(dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_window(&mut cmd);
    cmd.spawn()
}
