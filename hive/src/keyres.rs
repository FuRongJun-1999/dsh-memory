//! keyres.rs · 结果完整性锚密钥解析（P11，批次53）。
//!
//! 密钥**只取 hive 既有配置/令牌面**，不新发明密钥来源（对照 config.local 既有键）：
//!   1. `HIVE_ORCH_TOKEN`        —— hive 编排器令牌（env 直值；orch.py:326 同一读取面）
//!   2. `HIVE_ORCH_TOKEN_FILE`   —— 令牌文件路径（env；config.local.json 既有键，读全文 strip）
//!   3. `HIVE_API_KEY`           —— LLM 网关密钥（env；config.local.json 既有键）
//! 首个非空者胜。三键皆缺 → None（锚判据对无密钥部署**不启用**，行为=旧产物判据，
//! 零配置零变更；有密钥的部署经 serve_start.py 读 config.local.json 注入 env 即生效）。
//!
//! 诚实边界（N143 教训）：**不设公开缺省常量密钥**——公开缺省 = 任何能写盘面的组件
//! 都可自签合法锚，P11 判据面不可伪造性随之瓦解（同型缺口见注入格 FI-R08）。

/// 生效条件：进程 env 给定——`HIVE_ORCH_TOKEN` 非空 → 取之；否则
/// `HIVE_ORCH_TOKEN_FILE` 指向可读文件 → 取全文 strip 非空者；否则 `HIVE_API_KEY`
/// 非空 → 取之；三键皆缺/文件不可读 → None。锚密钥唯一解析点（submit 与 serve
/// 共用，勿在调用方各自第二套解析——口径分叉即判据分叉）。
pub fn resolve_key_from_env() -> Option<String> {
    let env = |k: &str| {
        std::env::var(k)
            .ok()
            .map(|v| v.trim().to_string())
            .filter(|v| !v.is_empty())
    };
    if let Some(t) = env("HIVE_ORCH_TOKEN") {
        return Some(t);
    }
    if let Some(f) = env("HIVE_ORCH_TOKEN_FILE") {
        if let Ok(s) = std::fs::read_to_string(&f) {
            let s = s.trim().to_string();
            if !s.is_empty() {
                return Some(s);
            }
        }
    }
    env("HIVE_API_KEY")
}

#[cfg(test)]
mod tests {
    use super::*;

    /// env 链优先级：HIVE_ORCH_TOKEN 胜过 HIVE_API_KEY；全缺 → None。
    /// 进程 env 竞争面：测试串行段内 set/remove，测毕恢复（Rust test 同进程共享 env）。
    #[test]
    fn env_chain_priority() {
        let (tok, api) = (
            std::env::var("HIVE_ORCH_TOKEN").ok(),
            std::env::var("HIVE_API_KEY").ok(),
        );
        std::env::remove_var("HIVE_ORCH_TOKEN_FILE");
        std::env::set_var("HIVE_ORCH_TOKEN", "tok-primary");
        std::env::set_var("HIVE_API_KEY", "api-fallback");
        assert_eq!(resolve_key_from_env().as_deref(), Some("tok-primary"));
        std::env::remove_var("HIVE_ORCH_TOKEN");
        assert_eq!(resolve_key_from_env().as_deref(), Some("api-fallback"));
        std::env::remove_var("HIVE_API_KEY");
        assert_eq!(resolve_key_from_env(), None);
        // 空白值视同缺失（trim 非空才采信）
        std::env::set_var("HIVE_ORCH_TOKEN", "   ");
        assert_eq!(resolve_key_from_env(), None);
        std::env::remove_var("HIVE_ORCH_TOKEN");
        // 恢复现场
        match tok {
            Some(v) => std::env::set_var("HIVE_ORCH_TOKEN", v),
            None => std::env::remove_var("HIVE_ORCH_TOKEN"),
        }
        match api {
            Some(v) => std::env::set_var("HIVE_API_KEY", v),
            None => std::env::remove_var("HIVE_API_KEY"),
        }
    }
}
