//! `mdcg_eval` 库入口：把灵枢检索核心以库形态暴露给 Rust 宿主。
//!
//! 设计约束（与评测器同源）：
//!   * **零第三方依赖**（D-005）：全部 `std`，评测机离线可构建；
//!   * **口径一致**：检索编排与评测 CLI（`main.rs::search`）逐位一致，
//!     文本/存储层与 Python `md_cg` 逐函数对齐（见 `text.rs` / `store.rs` 头注释）；
//!   * **只读**：库只做读侧（大批量检索）；写侧（写入闸门/凭据/冲突检测）
//!     仍由 Python MCP 承担——职责分离，避免双写实现漂移。
//!
//! 两条使用形态：
//!   1. **库内嵌**：`SearchEngine::open(root, cfg)` 后多线程并发 `search`
//!      （`&SearchEngine` 只读共享，`Send + Sync`）；
//!   2. **进程实例**：`mdcg-eval --serve`，stdin/stdout 逐行 JSON（见 `serve.rs`），
//!      每智能体一进程，索引只读共享 OS 页缓存——多智能体并发的语言无关形态。

pub mod engine;
pub mod json;
pub mod metrics;
pub mod retrieval;
pub mod serve;
pub mod store;
pub mod text;

pub use engine::{EngineConfig, SearchEngine, SearchHit};
