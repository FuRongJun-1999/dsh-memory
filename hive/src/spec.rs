//! 任务 spec：解析与校验（fail fast——submit 时把错拦住，不让坏任务进队列）。
//!
//! spec.json（v0.2）：
//! ```json
//! {
//!   "model": "<与 HIVE_API_BASE 配对的模型名>",  // 必填：LLM 模型名（确定性执行写 "cmd"）
//!   "system_prompt": "...",         // 可选：系统提示词
//!   "user_prompt": "...",           // 必填：用户提示词
//!   "context_files": ["a.md"],      // 可选：上下文文件（相对 workdir 或绝对）
//!   "workdir": "...",               // 可选：context 相对路径基准（默认 submit 时 cwd）
//!   "timeout_s": 300,               // 可选：硬超时（默认 300，5..=3600）
//!   "command": ["python", "x.py"],  // 可选：确定性执行（单条，零 LLM；需 serve 用 exec_cmd.py）
//!   "commands": [{"command": [...]}], // 可选：多步确定性执行（同上，逐步落 step_i_stdout.txt）
//!   "orchestrate": {"subtasks": [...]}, // 可选：编排（同上，走 orch.py）
//!   "max_tokens": 4096,             // 可选
//!   "temperature": 0.7,             // 可选，[0, 2]
//!   "thinking": {"type": "enabled"},  // 可选：思考开关（DeepSeek V4.1 同形，type ∈ enabled|disabled）
//!   "reasoning_effort": "high",     // 可选：思考强度 ∈ low|medium|high
//!   "context_budget_tokens": 300000, // 可选：输入 token 预算（执行器保守估算，超限 fail fast）
//!   "depends_on": ["h..."],          // 可选：上游任务列表——全 done 才领取，
//!                                    //   任一 error/timeout/killed → 本任务 error（失败传播）
//!   "rerun_on_recover": true,        // 可选：崩溃恢复逃生门（缺省 false）——恢复时
//!                                    //   不采信旧产物：result.json 更名
//!                                    //   result.json.recovered-<ts> 留痕并强制重投
//! }
//! ```

use crate::json::Json;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct Spec {
    pub model: String,
    pub system_prompt: Option<String>,
    pub user_prompt: String,
    pub context_files: Vec<String>,
    pub workdir: Option<String>,
    pub timeout_s: u64,
    pub max_tokens: Option<f64>,
    pub temperature: Option<f64>,
    /// 思考开关："enabled" | "disabled"（与 DeepSeek V4.1 API 的 thinking.type 同形）
    pub thinking: Option<String>,
    /// 思考强度："low" | "medium" | "high"
    pub reasoning_effort: Option<String>,
    /// 输入 token 预算上限（执行器侧保守估算校验，超限 fail fast 不白跑 API）
    pub context_budget_tokens: Option<u64>,
    /// 依赖门禁（I-1，宏观调度第一格）：上游任务 job_id 列表——全部 done 才可领取；
    /// 任一终态非 done（error/timeout/killed）→ 本任务直接 error（失败传播）。
    /// 无环性结构性成立：job_id 含毫秒时间戳，提交时间序 = DAG 拓扑序，
    /// 无法引用提交时尚不存在的任务（自引用亦不可能）。
    pub depends_on: Vec<String>,
    /// M1 逃生门（2026-09-23 批次7）：崩溃恢复时不采信旧产物——
    /// serve 重启的 recover_orphans 见本标志为 true 时，把 result.json 更名为
    /// `result.json.recovered-<ts>` 留痕并回 pending 强制新鲜重投。
    /// 用途：产物可能产生于被污染/中断的执行上下文，提交方显式声明
    /// 「宁可重跑也要新鲜结果」。缺省 false = 产物说了算（M1 主判据不变）。
    pub rerun_on_recover: bool,
}

pub const DEFAULT_TIMEOUT_S: u64 = 300;
pub const MIN_TIMEOUT_S: u64 = 5;
pub const MAX_TIMEOUT_S: u64 = 3600;

impl Spec {
    /// context 路径解析基准：spec.workdir 优先，否则 `fallback`（调用方 cwd）。
    /// 生效条件：workdir 显式给出 → 以其为基准；否则回退 fallback（调用方 cwd）
    /// ——context 相对路径解析的唯一锚点决策点。
    pub fn base_dir(&self, fallback: &Path) -> PathBuf {
        self.workdir
            .as_ref()
            .map(PathBuf::from)
            .unwrap_or_else(|| fallback.to_path_buf())
    }

    /// 校验 context 文件存在性（submit 侧 fail fast；执行器侧再兜底一次）。
    /// 生效条件：全部 context_files 相对 base 均为已存在文件 → Ok()；
    /// 任一缺失 → Err(路径)（submit 侧 fail fast，不让坏任务进队列；
    /// 执行器侧再兜底一次）。
    pub fn check_context(&self, base: &Path) -> Result<(), String> {
        for f in &self.context_files {
            let p = base.join(f);
            if !p.is_file() {
                return Err(format!("context 文件不存在: {}", p.display()));
            }
        }
        Ok(())
    }
}

/// 从 JSON 解析并校验 spec。`base_dir`：context 相对路径的校验基准
/// （spec.workdir 优先，否则调用方 cwd）。校验含 context 文件存在性。
/// 生效条件：validate_lenient 通过且 context 文件存在性校验通过 → Ok(Spec)；
/// 任一失败 → Err（submit 侧用：把错拦在进队列之前）。
pub fn validate(v: &Json, base_dir: &Path) -> Result<Spec, String> {
    let s = validate_lenient(v)?;
    let base = s.base_dir(base_dir);
    s.check_context(&base)?;
    Ok(s)
}

/// 宽松校验（不含 context 存在性检查）——worker 侧用：
/// job 目录不是合法 base，context 已在 submit 侧 fail fast。
/// 生效条件：v 为 JSON 对象且 model/user_prompt 非空、timeout_s/max_tokens/
/// temperature/thinking.type/reasoning_effort 各字段（若出现）在白名单内 →
/// Ok(Spec)（缺省字段回落默认：timeout 300、rerun_on_recover false 等）；
/// 必填缺失或越界 → Err。宽松形态（不含 context 存在性检查）供 worker 侧用
/// ——job 目录不是合法 base，context 已在 submit 侧校验过。
pub fn validate_lenient(v: &Json) -> Result<Spec, String> {
    v.as_obj()
        .ok_or_else(|| "spec 必须是 JSON 对象".to_string())?;

    let model = v
        .get("model")
        .and_then(|x| x.as_str())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "spec 缺必填字段 model（字符串）".to_string())?;

    let user_prompt = v
        .get("user_prompt")
        .and_then(|x| x.as_str())
        .map(|s| s.to_string())
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| "spec 缺必填字段 user_prompt（非空字符串）".to_string())?;

    let system_prompt = v
        .get("system_prompt")
        .and_then(|x| x.as_str())
        .map(|s| s.to_string())
        .filter(|s| !s.is_empty());

    let context_files = v
        .get("context_files")
        .map(|x| x.as_str_vec())
        .unwrap_or_default();

    let workdir = v
        .get("workdir")
        .and_then(|x| x.as_str())
        .map(|s| s.to_string())
        .filter(|s| !s.is_empty());

    let timeout_s = match v.get("timeout_s") {
        None => DEFAULT_TIMEOUT_S,
        Some(Json::Num(n)) if *n >= 1.0 => *n as u64,
        Some(_) => return Err("timeout_s 必须为正数".to_string()),
    };
    if !(MIN_TIMEOUT_S..=MAX_TIMEOUT_S).contains(&timeout_s) {
        return Err(format!(
            "timeout_s 超界: {timeout_s}（允许 {MIN_TIMEOUT_S}..={MAX_TIMEOUT_S}）"
        ));
    }

    let max_tokens = match v.get("max_tokens") {
        None | Some(Json::Null) => None,
        Some(Json::Num(n)) if *n >= 1.0 => Some(*n),
        Some(_) => return Err("max_tokens 必须为正数".to_string()),
    };

    let temperature = match v.get("temperature") {
        None | Some(Json::Null) => None,
        Some(Json::Num(n)) if (0.0..=2.0).contains(n) => Some(*n),
        Some(_) => return Err("temperature 必须在 [0, 2]".to_string()),
    };

    let thinking = match v.get("thinking") {
        None | Some(Json::Null) => None,
        Some(t) => {
            let ty = t
                .get("type")
                .and_then(|x| x.as_str())
                .ok_or_else(|| "thinking 必须是对象且含 type 字段".to_string())?;
            match ty {
                "enabled" | "disabled" => Some(ty.to_string()),
                _ => return Err(format!("thinking.type 非法: {ty}（允许 enabled|disabled）")),
            }
        }
    };

    let reasoning_effort = match v.get("reasoning_effort") {
        None | Some(Json::Null) => None,
        Some(Json::Str(s)) => match s.as_str() {
            "low" | "medium" | "high" => Some(s.clone()),
            _ => return Err(format!("reasoning_effort 非法: {s}（允许 low|medium|high）")),
        },
        Some(_) => return Err("reasoning_effort 必须为字符串".to_string()),
    };

    let context_budget_tokens = match v.get("context_budget_tokens") {
        None | Some(Json::Null) => None,
        Some(Json::Num(n)) if *n >= 1.0 => Some(*n as u64),
        Some(_) => return Err("context_budget_tokens 必须为正数".to_string()),
    };

    let depends_on = v
        .get("depends_on")
        .map(|x| x.as_str_vec())
        .unwrap_or_default();
    for d in &depends_on {
        // 结构闸（2026-09-25 缺陷）：旧检查只看 'h' 前缀，`h/../../x` 可过——
        // 该值随后会被 submit 侧存在性检查与 scheduler::deps_gate 裸 join 进
        // 路径（读池外目录 status）。须过 valid_job_id 全量结构校验。
        if !crate::job::valid_job_id(d) {
            return Err(format!(
                "depends_on 项非法: {d}（须为 h 开头且不含路径成分的 job_id）"
            ));
        }
    }

    // 逃生门只认显式 true；缺失/null/false/非布尔一律 false（fail-safe 缺省，
    // 不因写错类型拒绝整个 spec——重投语义宁缺勿滥）
    let rerun_on_recover =
        matches!(v.get("rerun_on_recover"), Some(Json::Bool(true)));

    Ok(Spec {
        model,
        system_prompt,
        user_prompt,
        context_files,
        workdir,
        timeout_s,
        max_tokens,
        temperature,
        thinking,
        reasoning_effort,
        context_budget_tokens,
        depends_on,
        rerun_on_recover,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn tmpdir(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!(
            "hive_spec_{tag}_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn valid_minimal() {
        let v = crate::json::parse(r#"{"model":"m1","user_prompt":"hi"}"#).unwrap();
        let s = validate(&v, Path::new(".")).unwrap();
        assert_eq!(s.model, "m1");
        assert_eq!(s.timeout_s, DEFAULT_TIMEOUT_S);
        assert!(s.system_prompt.is_none());
    }

    #[test]
    fn missing_model_rejected() {
        let v = crate::json::parse(r#"{"user_prompt":"hi"}"#).unwrap();
        assert!(validate(&v, Path::new(".")).is_err());
    }

    #[test]
    fn empty_user_prompt_rejected() {
        let v = crate::json::parse(r#"{"model":"m","user_prompt":"  "}"#).unwrap();
        assert!(validate(&v, Path::new(".")).is_err());
    }

    #[test]
    fn timeout_bounds() {
        let v = crate::json::parse(r#"{"model":"m","user_prompt":"x","timeout_s":1}"#).unwrap();
        assert!(validate(&v, Path::new(".")).is_err());
        let v = crate::json::parse(r#"{"model":"m","user_prompt":"x","timeout_s":99999}"#).unwrap();
        assert!(validate(&v, Path::new(".")).is_err());
        let v = crate::json::parse(r#"{"model":"m","user_prompt":"x","timeout_s":60}"#).unwrap();
        assert_eq!(validate(&v, Path::new(".")).unwrap().timeout_s, 60);
    }

    #[test]
    fn temperature_bounds() {
        let v = crate::json::parse(r#"{"model":"m","user_prompt":"x","temperature":2.5}"#).unwrap();
        assert!(validate(&v, Path::new(".")).is_err());
    }

    #[test]
    fn thinking_reasoning_budget_parse() {
        let v = crate::json::parse(
            r#"{"model":"deepseek-flash","user_prompt":"x",
                "thinking":{"type":"enabled"},"reasoning_effort":"high",
                "context_budget_tokens":300000}"#,
        )
        .unwrap();
        let s = validate(&v, Path::new(".")).unwrap();
        assert_eq!(s.thinking.as_deref(), Some("enabled"));
        assert_eq!(s.reasoning_effort.as_deref(), Some("high"));
        assert_eq!(s.context_budget_tokens, Some(300000));
    }

    #[test]
    fn thinking_bad_type_rejected() {
        let v = crate::json::parse(
            r#"{"model":"m","user_prompt":"x","thinking":{"type":"always"}}"#,
        )
        .unwrap();
        assert!(validate(&v, Path::new(".")).is_err());
        let v =
            crate::json::parse(r#"{"model":"m","user_prompt":"x","thinking":"enabled"}"#).unwrap();
        assert!(validate(&v, Path::new(".")).is_err());
    }

    #[test]
    fn reasoning_effort_whitelist() {
        for ok in ["low", "medium", "high"] {
            let s = format!(r#"{{"model":"m","user_prompt":"x","reasoning_effort":"{ok}"}}"#);
            assert!(validate(&crate::json::parse(&s).unwrap(), Path::new(".")).is_ok());
        }
        let v = crate::json::parse(
            r#"{"model":"m","user_prompt":"x","reasoning_effort":"ultra"}"#,
        )
        .unwrap();
        assert!(validate(&v, Path::new(".")).is_err());
    }

    #[test]
    fn context_budget_bounds() {
        let v = crate::json::parse(
            r#"{"model":"m","user_prompt":"x","context_budget_tokens":0}"#,
        )
        .unwrap();
        assert!(validate(&v, Path::new(".")).is_err());
    }

    /// 路径穿越载体必须被拒（2026-09-25 缺陷）：旧检查只看 'h' 前缀，
    /// `h/../../x` 可过校验后被 submit/deps_gate 裸 join 逃出 jobs 池。
    #[test]
    fn depends_on_traversal_rejected() {
        for bad in [r#""h/../../x""#, r#""..""#, r#""../victim""#, r#""h\\..""#, r#""x1""#] {
            let s = format!(r#"{{"model":"m","user_prompt":"x","depends_on":[{bad}]}}"#);
            assert!(
                validate(&crate::json::parse(&s).unwrap(), Path::new(".")).is_err(),
                "穿越载体必须被拒: {bad}"
            );
        }
        let ok = validate(
            &crate::json::parse(
                r#"{"model":"m","user_prompt":"x","depends_on":["h1758000000000_1a2b"]}"#,
            )
            .unwrap(),
            Path::new("."),
        )
        .unwrap();
        assert_eq!(ok.depends_on, vec!["h1758000000000_1a2b".to_string()]);
    }

    #[test]
    fn context_existence_checked() {
        let d = tmpdir("ctx");
        fs::write(d.join("a.txt"), "hello").unwrap();
        let v = crate::json::parse(
            r#"{"model":"m","user_prompt":"x","context_files":["a.txt"]}"#,
        )
        .unwrap();
        assert!(validate(&v, &d).is_ok());
        let v = crate::json::parse(
            r#"{"model":"m","user_prompt":"x","context_files":["nope.txt"]}"#,
        )
        .unwrap();
        assert!(validate(&v, &d).is_err());
        let _ = fs::remove_dir_all(&d);
    }

    /// M1 逃生门解析（批次7）：只认显式 true；缺省/否/null/错型一律 false。
    #[test]
    fn rerun_on_recover_parse() {
        let s = validate(
            &crate::json::parse(
                r#"{"model":"m","user_prompt":"x","rerun_on_recover":true}"#,
            )
            .unwrap(),
            Path::new("."),
        )
        .unwrap();
        assert!(s.rerun_on_recover);
        for bad in [r#"{"model":"m","user_prompt":"x"}"#,
                    r#"{"model":"m","user_prompt":"x","rerun_on_recover":false}"#,
                    r#"{"model":"m","user_prompt":"x","rerun_on_recover":null}"#,
                    r#"{"model":"m","user_prompt":"x","rerun_on_recover":"yes"}"#] {
            let s = validate(&crate::json::parse(bad).unwrap(), Path::new(".")).unwrap();
            assert!(!s.rerun_on_recover, "非显式 true 必须回落 false: {bad}");
        }
    }
}
