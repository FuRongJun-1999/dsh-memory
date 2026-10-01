//! 权重刷新与衰减（设计稿 §七 · P4）——**Rust 读侧的乘子**，与 Python
//! `md_cg/freshness.py` **逐参数、逐 floor、逐单位**同口径。
//!
//! 形态：`score ← score × cred_factor(γ, Δt) × refresh(access_count, last_access)`
//!
//! 与 Python 侧的对应关系（**两侧必须同一处生效**）：
//!   * Python 的乘子落在 `MdCG._score` 的「与分池权重同一乘子位」；
//!   * Rust 侧的对位点是 `retrieval::sort_path`（`apply_freshness=true` 时）
//!     ——**只对 lexical 路生效**（`fuse` 里仅 lexical 传 true）。为什么：
//!     Python 的 `_score` 只被 lexical/bucket 两路使用，entity/graph 路的分数
//!     来自另一处（`_path_entity` 恒 1.0、`_path_graph` = 种子分×0.5），
//!     `sort_path` 却是 `fuse` 对**每一路**都调用的三键排序器——若在那里对
//!     entity 路也乘一次，两侧的 entity 路内名次就会分叉（Python 不乘），
//!     与「逐位对拍」的要求自相矛盾。故按「与 Python 同处生效」取 lexical。
//!
//! 参数（**照抄** AEIS `consolidate_cycle`，出处与 Python 侧同一处）：
//! `md_cg/whitebox_kb/aeis_core/core.py:4801-4831`
//!     rehearsal_threshold=0.7 / degrade_threshold=0.2 / gain=0.01 /
//!     `access_count % 10 == 0` / 低重要度降权上限 access_count ≤ 2
//!
//! γ 与 Δt（§〇.3-12 已裁）：γ 缺省 `ln2/30 天`（env `MDCG_TEMPORAL_GAMMA`
//! 可覆盖，与 Python `mdcos.temporal_gamma()` 同一 env）；Δt 取 `created_at`；
//! **单位必须是「天」**（`SECONDS_PER_DAY`）。
//!
//! floor（§7.3）：衰减项 floor = `SCORE_FLOOR`；**受保护节点**另有下界
//! `IMPORTANCE_PROTECT / importance` ⇒ `importance × 乘子 ≥ 0.70` 恒成立，
//! 保护判定不会被衰减翻转（与 Python `freshness.protected_floor` 同式）。
//!
//! 开关：`MDCG_FRESHNESS`（缺省开；`0/false/no/off` 关 → 乘子恒 1.0，
//! 与改动前逐位一致）；`MDCG_FRESHNESS_NOW`（探针/守卫的确定性冻结口）。

pub const SCORE_FLOOR: f64 = 0.001;
pub const SCORE_CEIL: f64 = 1.0;
pub const SECONDS_PER_DAY: f64 = 86400.0;
/// Δt 的**粒度**：整日（向下取整）——与 Python `freshness.DT_QUANTUM_DAYS` 同值
/// 同义（保证「两轮逐位一致」与两侧跨语言同值，见 Python 侧说明）。
pub const DT_QUANTUM_DAYS: f64 = 1.0;
/// 与 Python `weights.IMPORTANCE_PROTECT` 同值（保护下限）。
pub const IMPORTANCE_PROTECT: f64 = 0.70;
/// 与 Python `links.DECAY_DAYS` 同值（半衰期 30 天；Rust 侧无 links 模块，
/// 故此处是唯一取值点——`retrieval.rs` 单测断言两值相等由 Python 侧守卫兜住）。
pub const DECAY_DAYS: f64 = 30.0;

const REHEARSAL_THRESHOLD: f64 = 0.7;
const DEGRADE_THRESHOLD: f64 = 0.2;
const GAIN: f64 = 0.01;
const CYCLE: i64 = 10;
const DEGRADE_MAX_ACCESS: i64 = 2;

fn env_str(key: &str) -> Option<String> {
    std::env::var(key).ok()
}

/// `MDCG_FRESHNESS` 缺省开（与 Python `freshness.enabled` 同词表同缺省）。
pub fn enabled() -> bool {
    match env_str("MDCG_FRESHNESS") {
        None => true,
        Some(v) => {
            let s = v.trim().to_lowercase();
            if s.is_empty() {
                return true;
            }
            !matches!(s.as_str(), "0" | "false" | "no" | "off")
        }
    }
}

/// 观测时刻（unix 秒）：env `MDCG_FRESHNESS_NOW` 优先，否则系统时钟。
pub fn now() -> f64 {
    if let Some(v) = env_str("MDCG_FRESHNESS_NOW") {
        if let Ok(f) = v.trim().parse::<f64>() {
            return f;
        }
    }
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

/// γ（**每天**）：env `MDCG_TEMPORAL_GAMMA` 可覆盖（>0 才生效），否则 ln2/30 天。
pub fn gamma() -> f64 {
    if let Some(v) = env_str("MDCG_TEMPORAL_GAMMA") {
        if let Ok(g) = v.trim().parse::<f64>() {
            if g > 0.0 {
                return g;
            }
        }
    }
    std::f64::consts::LN_2 / DECAY_DAYS
}

/// 受保护节点的衰减乘子下界（与 Python `freshness.protected_floor` 同式）。
pub fn protected_floor(importance: f64, protected: bool) -> f64 {
    if !protected {
        return SCORE_FLOOR;
    }
    let imp = if importance > 0.0 { importance } else { 1.0 };
    (IMPORTANCE_PROTECT / imp).max(SCORE_FLOOR).min(1.0)
}

/// 访问刷新/降权乘子（门槛与步长照抄 AEIS；`last_access > 0` 一条同 Python）。
pub fn refresh_factor(access_count: f64, last_access: f64, importance: f64) -> f64 {
    let ac = access_count as i64;
    if importance >= REHEARSAL_THRESHOLD && last_access > 0.0 && ac % CYCLE == 0 {
        return 1.0 + GAIN;
    }
    if importance < DEGRADE_THRESHOLD && ac <= DEGRADE_MAX_ACCESS {
        return 1.0 - GAIN;
    }
    1.0
}

/// 单节点乘子（与 Python `freshness.entry_weight` 逐式一致；不读盘）。
pub fn factor(created_at: f64, access_count: f64, last_access: f64,
              importance: f64, protected: bool, ref_now: f64) -> f64 {
    if !enabled() {
        return 1.0;
    }
    let dt_days = if created_at > 0.0 {
        let d = (ref_now - created_at).abs() / SECONDS_PER_DAY;
        // 粒度=整日（向下取整；abs 后恒为正，trunc == floor）
        ((d / DT_QUANTUM_DAYS).trunc()) * DT_QUANTUM_DAYS
    } else {
        f64::INFINITY
    };
    let floor = protected_floor(importance, protected);
    let decay = ((-gamma() * dt_days).exp()).max(floor).min(SCORE_CEIL);
    decay * refresh_factor(access_count, last_access, importance)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decay_half_life_is_30_days() {
        let g = std::f64::consts::LN_2 / DECAY_DAYS;
        let f = ((-g * DECAY_DAYS).exp()).max(SCORE_FLOOR).min(SCORE_CEIL);
        assert!((f - 0.5).abs() < 1e-12, "30 天应为半衰期，得到 {f}");
    }

    #[test]
    fn fresh_node_factor_is_one() {
        // created_at = now、access_count=0、importance=0.5、未保护 → 1.0
        std::env::set_var("MDCG_FRESHNESS_NOW", "1800000000");
        let f = factor(1800000000.0, 0.0, 0.0, 0.5, false, now());
        assert!((f - 1.0).abs() < 1e-12, "新节点乘子应为 1.0，得到 {f}");
    }

    #[test]
    fn old_node_is_floored() {
        let f = factor(1800000000.0 - 300.0 * SECONDS_PER_DAY, 0.0, 0.0, 0.5,
                       false, 1800000000.0);
        assert!((f - SCORE_FLOOR).abs() < 1e-12, "300 天应触 floor，得到 {f}");
    }

    #[test]
    fn protected_node_keeps_protect_line() {
        let imp = 0.8_f64;
        let f = factor(1800000000.0 - 300.0 * SECONDS_PER_DAY, 0.0, 0.0, imp,
                       true, 1800000000.0);
        assert!(imp * f >= IMPORTANCE_PROTECT, "受保护节点被衰减穿过保护线");
    }

    #[test]
    fn rehearsal_needs_last_access() {
        assert!((refresh_factor(40.0, 0.0, 0.8) - 1.0).abs() < 1e-12);
        assert!((refresh_factor(40.0, 1.0, 0.8) - 1.01).abs() < 1e-12);
    }
}
