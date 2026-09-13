//! health.rs · 实例健康四因子评分（B3 甲案 · 2026-09-13 荣裁定）
//! 与 ruflo 的差异：全部因子从 HMAC 事件流统计自算，可复算可审计
//! （ruflo 把评分交给 LLM 角色卡——不可复算，见研读笔记 A5 §4）。
//!
//! 公式：score = W.success×success_rate + W.uptime×uptime_rate
//!             + W.threat×(1 − threat_rate) + W.integrity×integrity_rate
//! 默认权重 0.4/0.2/0.2/0.2（对齐 A5 federation 公式，可配置）。
//!
//! 因子定义（单机多进程口径）：
//!   success_rate   = 成功轮次 / 应参与轮次
//!   uptime_rate    = 实际参与轮次 / 应参与轮次（实例中途缺失轮次即降）
//!   threat_rate    = error 终态轮次 / 实际参与轮次（error = 威胁事件）
//!   integrity_rate = 验签通过事件 / 实例相关事件总数（在线全签=1.0；
//!                    区分度在 G3b 水位对账/跨机场景启用）
//!
//! 纯 std 零依赖。

use std::collections::HashMap;

/// 四因子权重（和应为 1.0；不做硬校验，clamp 兜底）
#[derive(Debug, Clone)]
pub struct HealthWeights {
    pub success: f64,
    pub uptime: f64,
    pub threat: f64,
    pub integrity: f64,
}

impl Default for HealthWeights {
    fn default() -> Self {
        HealthWeights { success: 0.4, uptime: 0.2, threat: 0.2, integrity: 0.2 }
    }
}

/// 单实例健康评分结果
#[derive(Debug, Clone)]
pub struct InstanceHealth {
    pub success_rate: f64,
    pub uptime_rate: f64,
    pub threat_rate: f64,
    pub integrity_rate: f64,
    pub score: f64,
}

/// 单实例评分。
///
/// `round_outcomes` 按轮序：`None`=该轮缺失（实例未参与），`Some(true)`=成功终态，
/// `Some(false)`=error 终态。`verify_fail`/`total_events` 为该实例相关事件的
/// 验签失败数与总数。`gossip_coverage` = gossip 实收/对账基准（G3c：
/// 实收<基准=全网传播缺收，integrity 因子按比例降级；无 gossip 时传 1.0）。
pub fn score_instance(
    round_outcomes: &[Option<bool>],
    verify_fail: usize,
    total_events: usize,
    gossip_coverage: f64,
    w: &HealthWeights,
) -> InstanceHealth {
    let total = round_outcomes.len().max(1) as f64;
    let participated = round_outcomes.iter().filter(|x| x.is_some()).count();
    let success = round_outcomes.iter().filter(|x| **x == Some(true)).count();
    let errors = round_outcomes.iter().filter(|x| **x == Some(false)).count();
    let p = participated.max(1) as f64;
    let success_rate = success as f64 / total;
    let uptime_rate = participated as f64 / total;
    let threat_rate = errors as f64 / p;
    let integrity_rate = if total_events == 0 {
        gossip_coverage.clamp(0.0, 1.0)
    } else {
        ((total_events.saturating_sub(verify_fail)) as f64 / total_events as f64)
            * gossip_coverage.clamp(0.0, 1.0)
    };
    let score = (w.success * success_rate
        + w.uptime * uptime_rate
        + w.threat * (1.0 - threat_rate)
        + w.integrity * integrity_rate)
        .clamp(0.0, 1.0);
    InstanceHealth {
        success_rate,
        uptime_rate,
        threat_rate,
        integrity_rate,
        score,
    }
}

/// 蜂群健康报告：实例 id → 评分
pub type HealthReport = HashMap<String, InstanceHealth>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verify_fail_degrades_integrity() {
        let w = HealthWeights::default();
        let h = score_instance(&[Some(true), Some(true)], 3, 12, 1.0, &w);
        assert!((h.integrity_rate - 0.75).abs() < 1e-9);
        assert!((h.score - (0.4 + 0.2 + 0.2 + 0.2 * 0.75)).abs() < 1e-9);
    }

    #[test]
    fn zero_events_falls_back_to_coverage() {
        let w = HealthWeights::default();
        let h = score_instance(&[Some(true)], 0, 0, 0.5, &w);
        assert!((h.integrity_rate - 0.5).abs() < 1e-9);
    }
}
