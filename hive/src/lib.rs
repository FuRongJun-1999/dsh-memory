//! `lingshu-hive` 库入口：灵枢蜂巢 · 蜂群多智能体并发运行时。
//!
//! 定位（对齐仓内四件套的边界纪律）：
//!   * **并发调度核心（rust，本 crate）**：任务领取、并发度控制、心跳观测、
//!     超时强杀、kill 通道——生命周期全部归 rust（std::thread 纯零依赖）；
//!   * **LLM 调用（python 执行器，`exec.py`）**：HTTPS 与 API 协议不进 rust
//!     （TLS 无第三方库不可行；执行器作为可替换子进程，`std::process::Command`
//!     拉起，uv 之外的 Python 标准库 urllib 即可）；
//!   * **文件协议即接口**：`jobs/<id>/{spec,status,result,kill}` + serve 心跳，
//!     跨语言宿主（Python MCP / CLI / 任意进程）零 IPC 依赖即可驱动；
//!   * **MCP 面（`hive_mcp/`）**：手写 stdio JSON-RPC，形态对齐 `md_cg/mcp_server.py`。
//!
//! 与 `rust/`（mdcg-eval 只读检索核心）的关系：正交——检索管「找」，
//! 蜂巢管「并发跑」；零依赖（D-005）与 serve 实例形态与之一脉相承。
//!
//! 单实例约束：同一 jobs 目录同一时刻至多一个 `hive serve`（领取经
//! `claimed.lock` create_new 原子保护；多实例不损坏数据，但心跳/doctor
//! 语义按单实例设计）。

pub mod exec;
pub mod job;
pub mod json;
pub mod scheduler;
pub mod spec;

pub use spec::Spec;
