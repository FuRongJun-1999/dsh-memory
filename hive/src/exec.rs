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

/// 拉起执行器子进程（stdio 全 null：执行器自己写 job/log.txt）。
pub fn spawn_executor(exec_py: &Path, dir: &Path) -> std::io::Result<Child> {
    Command::new(python_bin())
        .arg(exec_py)
        .arg(dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
}
