//! keyres.rs · 结果完整性锚密钥解析（P11，批次53；链收窄见 N190）。
//!
//! 密钥**只取 hive 既有身份/令牌面**，不新发明密钥来源、不用普通配置顶替：
//!   1. `HIVE_ORCH_TOKEN`        —— hive 编排器令牌（env 直值；orch.py:326 同一读取面）
//!   2. `HIVE_ORCH_TOKEN_FILE`   —— 令牌文件路径（env；config.local.json 既有键，读全文 strip）
//! 首个非空者胜；两环皆缺 → None。
//!
//! N190（本批）为什么去掉 `HIVE_API_KEY` 兜底环：它是**模型（网关）密钥**，
//! 属普通配置——exec.py 调 LLM 必需、随 serve env 默认继承给执行器
//! （hive/src/exec.rs::ORCH_SECRET_ENV_KEYS 已按身份面收窄为两键）。把它当锚密钥
//! = 判据面与身份面混同：每个部署到模型密钥的面都自动成为锚签发面，且「谁有权
//! 签锚」变成「谁能调模型」。故链只剩身份两环：
//! `HIVE_ORCH_TOKEN` → `HIVE_ORCH_TOKEN_FILE` → None。
//!
//! 诚实边界（安全方向降级，点名不掩）：某部署若**从未配身份密钥**，本判据
//! **整体不启用**——submit 面不写 `result_nonce`、serve 面按旧产物判据处置
//! （行为 = 批次53 之前的产物判据，零配置零变更）；serve 启动面与复核提示会
//! 明说「锚未启用 / 不可校验」（hive/src/main.rs cmd_serve、hive/src/scheduler.rs
//! 的 Unverifiable 分支），不静默。即：配了身份密钥才升级判据，没配就退到旧判据。
//!
//! 诚实边界（N143 教训）：**不设公开缺省常量密钥**——公开缺省 = 任何能写盘面的组件
//! 都可自签合法锚，P11 判据面不可伪造性随之瓦解（同型缺口见注入格 FI-R08）。
//!
//! 同链副本（勿分叉）：Python 侧 MCP 面 `hive/hive_mcp/mcp_server.py::_result_anchor_key`
//! 按注释声明「与 keyres.rs 同链同序」——本文件改链时该处必须同步，否则 submit 面
//! 与 serve 面对「锚密钥」判据分叉（口径分叉即判据分叉）。
//!
//! 小写读取（2026-09-28 使用者裁定）：`HIVE_ORCH_TOKEN` 系值**读取即折小写**——
//! 写面（`md_cg.tokens` 签发）产小写、读面折小写 ⇒ 大小写不再构成第二语义。
//! 只折 ASCII `A-Z`（`to_ascii_lowercase`，与 Python 侧 `_ascii_lower` 逐位同口径；
//! 非 ASCII 段一律不动——`str::to_lowercase` 与 Python `str.lower()` 对 Unicode
//! 结论不同，会造出跨语言分叉）。
//!
//! 诚实边界（点名不掩）：①锚密钥＝折小写后的值 ⇒ 锚面**大小写不敏感**；对**含大写
//! 的存量令牌**折小写会改变锚密钥 ⇒ 混跑窗口内 submit 面与 serve 面必须是同一构建，
//! 否则判「伪锚」。②本归一**只作用于锚面**（值仅作 HMAC 密钥，无对照物）；
//! 身份面 `hive/orch.py::_read_token` **不折**——那里的值要与令牌库逐字节比对，
//! 而 secret 是 base64url（必含大写，见 `md_cg/tokens.py::parse_token`），折小写即毁令牌。

/// 生效条件：进程 env 给定——`HIVE_ORCH_TOKEN` 非空（trim + ASCII 折小写）→ 取之；否则
/// `HIVE_ORCH_TOKEN_FILE` 指向可读文件 → 取全文 strip + 折小写后非空者；否则 None
/// （N190：`HIVE_API_KEY` 不再兜底——它属模型密钥/普通配置，不是身份面）。
/// 锚密钥唯一解析点（submit 与 serve 共用，勿在调用方各自第二套解析——
/// 口径分叉即判据分叉）。
pub fn resolve_key_from_env() -> Option<String> {
    let env = |k: &str| {
        std::env::var(k)
            .ok()
            .map(|v| v.trim().to_ascii_lowercase())
            .filter(|v| !v.is_empty())
    };
    if let Some(t) = env("HIVE_ORCH_TOKEN") {
        return Some(t);
    }
    if let Some(f) = env("HIVE_ORCH_TOKEN_FILE") {
        if let Ok(s) = std::fs::read_to_string(&f) {
            let s = s.trim().to_ascii_lowercase();
            if !s.is_empty() {
                return Some(s);
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    /// env 链优先级（N190 口径，契约同步项）：`HIVE_ORCH_TOKEN` 胜过
    /// `HIVE_ORCH_TOKEN_FILE`（文件全文 strip）；身份两环皆缺 → None——
    /// **即使 `HIVE_API_KEY` 非空也不兜底**（模型密钥不是身份/锚密钥）。
    /// 进程 env 竞争面：测试串行段内 set/remove，测毕恢复（Rust test 同进程共享 env）；
    /// 与 exec::env_secrets_tests 同锁串行（N185 守卫并行 set/remove 同批键，
    /// 不互斥即竞态假红——实测 HIVE_ORCH_TOKEN_FILE 撞 remove_var 窗口）。
    #[test]
    fn env_chain_priority() {
        let _lock = crate::exec::env_secrets_tests::ENV_TEST_LOCK
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        let (tok, tokf, api) = (
            std::env::var("HIVE_ORCH_TOKEN").ok(),
            std::env::var("HIVE_ORCH_TOKEN_FILE").ok(),
            std::env::var("HIVE_API_KEY").ok(),
        );
        // 令牌文件用系统临时目录哑值（绝不触真实令牌库；测毕删文件）
        let tokfile = std::env::temp_dir()
            .join(format!("n190-keyres-tok-{}", std::process::id()));
        std::fs::write(&tokfile, "  tok-file  \n").unwrap();

        // 1) 身份直值优先于令牌文件；模型密钥在旁不参与
        std::env::set_var("HIVE_ORCH_TOKEN_FILE", tokfile.to_str().unwrap());
        std::env::set_var("HIVE_ORCH_TOKEN", "tok-primary");
        std::env::set_var("HIVE_API_KEY", "api-model-key");
        assert_eq!(resolve_key_from_env().as_deref(), Some("tok-primary"));

        // 2) 直值缺 → 令牌文件（读全文 strip）
        std::env::remove_var("HIVE_ORCH_TOKEN");
        assert_eq!(resolve_key_from_env().as_deref(), Some("tok-file"));

        // 3) 身份两环皆缺 → None；HIVE_API_KEY 仍为 "api-model-key" 也不兜底（N190 承重断言）
        std::env::remove_var("HIVE_ORCH_TOKEN_FILE");
        assert_eq!(
            resolve_key_from_env(),
            None,
            "身份两环皆缺时 HIVE_API_KEY 不得兜底（N190：模型密钥≠锚密钥）"
        );

        // 4) 空白值视同缺失（trim 非空才采信）
        std::env::set_var("HIVE_ORCH_TOKEN", "   ");
        assert_eq!(resolve_key_from_env(), None);
        std::env::remove_var("HIVE_ORCH_TOKEN");

        // 5) 令牌文件不可读/内容空白 → 视同缺失，不回落模型密钥
        std::env::set_var("HIVE_ORCH_TOKEN_FILE", "DUMMY-N190-NOT-A-FILE");
        assert_eq!(resolve_key_from_env(), None);
        std::fs::write(&tokfile, "   \n").unwrap();
        std::env::set_var("HIVE_ORCH_TOKEN_FILE", tokfile.to_str().unwrap());
        assert_eq!(resolve_key_from_env(), None);

        // 6) 小写读取（2026-09-28 使用者裁定）：两环取值一律折 ASCII 大写 → 小写；
        //    非 ASCII 段不动（与 Python 侧 `_ascii_lower` 逐位同口径）
        std::env::set_var("HIVE_ORCH_TOKEN", "  TOK-UP-Per  ");
        assert_eq!(resolve_key_from_env().as_deref(), Some("tok-up-per"));
        std::env::remove_var("HIVE_ORCH_TOKEN");
        std::fs::write(&tokfile, "  TOK-FILE-UP  \n").unwrap();
        std::env::set_var("HIVE_ORCH_TOKEN_FILE", tokfile.to_str().unwrap());
        assert_eq!(resolve_key_from_env().as_deref(), Some("tok-file-up"));
        std::env::remove_var("HIVE_ORCH_TOKEN_FILE");

        // 恢复现场
        let _ = std::fs::remove_file(&tokfile);
        for (k, v) in [
            ("HIVE_ORCH_TOKEN", tok),
            ("HIVE_ORCH_TOKEN_FILE", tokf),
            ("HIVE_API_KEY", api),
        ] {
            match v {
                Some(s) => std::env::set_var(k, s),
                None => std::env::remove_var(k),
            }
        }
    }
}
