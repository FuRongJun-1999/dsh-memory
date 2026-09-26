//! protocol_vm · 智能论字节码（.pbc）Rust 原生运行时 —— 库入口
//!
//! 零外部依赖（仅 std），对齐项目零依赖哲学。对外提供：
//!   - [`pbc`]   字节码反序列化（tag0-tag6，与 Python 侧 swarm/pbc.py 逐字节对齐）
//!   - [`vm`]    解释器（值栈 / 符号表 / 条件空间栈 / 信任寄存器 / 调用栈帧）
//!   - [`serve`] VM 实例化（stdin/stdout 逐行 JSON，进程存活 = 实例）
//!   - [`swarm`] 蜂群协调器（多进程 + 事件路由 + WAL + HMAC 签名 + 信任聚合）
//!   - [`hmac`]  手写 SHA-256 / HMAC-SHA256（FIPS 180-4 / RFC 2104）
//!
//! 字节码来源见 [`load_program`]：显式路径优先，其次编译期嵌入。
//! `embed` 特性开启时把 `../program.pbc` 编入二进制（生成项目形态——
//! rust_codegen.py 拷贝模板时改写 Cargo.toml 默认开）；
//! 独立 / 库形态（模板默认）不嵌入，改为运行期 `--pbc <文件>`。
//!
//! 独立构建与调用：
//! ```text
//! cargo build --release --no-default-features
//! ./target/release/protocol_vm --pbc out.pbc --trust 0.5
//! ```

pub mod hmac;
pub mod health;
pub mod pbc;
pub mod serve;
pub mod swarm;
pub mod vm;

/// 编译期嵌入的字节码。`embed` 特性开启时来自 `../program.pbc`。
#[cfg(feature = "embed")]
pub const EMBEDDED_PROGRAM: Option<&[u8]> = Some(include_bytes!("../program.pbc"));

/// 编译期嵌入的字节码。`embed` 特性关闭时恒为 [`None`]。
#[cfg(not(feature = "embed"))]
pub const EMBEDDED_PROGRAM: Option<&[u8]> = None;

/// 是否携带编译期嵌入的字节码（生成项目形态 = true，独立形态 = false）。
pub const HAS_EMBEDDED_PROGRAM: bool = cfg!(feature = "embed");

/// 载入字节码字节流：显式路径优先，其次编译期嵌入。
///
/// - `Some(path)`：读该文件——可覆盖已嵌入的字节码，便于一个二进制运行多个程序
/// - `None` 且带 `embed`：用嵌入字节码（生成项目形态）
/// - `None` 且无 `embed`：报错并给出两种修法
pub fn load_program(pbc_path: Option<&str>) -> Result<Vec<u8>, String> {
    if let Some(path) = pbc_path {
        return std::fs::read(path).map_err(|e| format!("读取字节码失败 {path}: {e}"));
    }
    match EMBEDDED_PROGRAM {
        Some(bytes) => Ok(bytes.to_vec()),
        None => Err("未提供字节码：本二进制为独立形态（未启用 embed 特性），"
            .to_string()
            + "请用 --pbc <文件> 指定；或改用 cargo build --release --features embed "
            + "在编译期嵌入 program.pbc"),
    }
}
