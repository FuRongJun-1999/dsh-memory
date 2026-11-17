# -*- coding: utf-8 -*-
"""信任度计算（对齐智能论 3.4 §2.7 / §2.9 / PROP-EMO-DIRECTION-002）。

为什么单独一个模块：这套公式一直写在理论里、**从未进入算法**（使用者 2026-11-17 指出）。
本模块只做纯函数计算，不读写库、不依赖状态机，便于被 affect / trust / 任何调用方复用。

理论原文（docs/theory/智能论3.4.md）：
  §2.7.1  预测误差三极管限制：U = clamp(max(0, 平均误差 − 死区), 0, 0.3)
  §2.7.2  动态死区：死区_有效 = max(0.02, 3σ)，死区_最终 = min(死区_有效, 0.20)
  §2.9.1  P_trust = P(δ_norm < 0.15 | 最近 N 轮)；P_gap = P(D_norm < 0.10 | 最近 N 轮)
          完全可信状态：两者**同时** ≥ 0.95
  §2.9    T_total = f(P_trust, T_pred, T_context)
          E_weight = d²T_total/dt²（情感＝信任的二阶变化率）
          T_total_effective = T_total × (1 + η·E_weight)，η 默认 0.1–0.3
  PROP-EMO-DIRECTION-002  情绪 = d²D_norm/dt²（信息差二阶变化）

**权重不在理论里**（理论只给结构关系），故本模块把 w 作为显式参数并给出工程默认值，
调用方必须能与之对照——不把工程默认伪装成理论结论。
"""

from __future__ import annotations

DEADZONE_STATIC = 0.02        # §2.7.1 预测误差死区
DEADZONE_MAX = 0.20           # §2.7.2 动态死区上限
U_LIMIT = 0.30                # §2.7.1 限幅
DELTA_TRUST = 0.15            # §2.9.1 信任置信阈值（δ_norm）
GAP_STABLE = 0.10             # §2.9.1 信息差置信阈值（D_norm）
FULL_TRUST = 0.95             # §2.9.1 完全可信阈值
ETA_DEFAULT = 0.20            # §2.9 情感权重结构影响系数（理论给 0.1–0.3）
#: 工程默认权重（**非理论结论**，理论只给 f(...) 的结构）
W_DEFAULT = (0.50, 0.30, 0.20)   # (P_trust, 1−U_pred, T_context)


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def deadzone(errors, sigma=None):
    """§2.7.2 动态死区：max(静态, 3σ)，再封顶 0.20。"""
    dz = DEADZONE_STATIC
    if sigma is not None:
        dz = max(dz, 3.0 * float(sigma))
    return min(dz, DEADZONE_MAX)


def u_prediction_error(errors, sigma=None):
    """§2.7.1：U = clamp(max(0, 平均误差 − 死区), 0, 限幅)。errors 为空 ⇒ 0。"""
    vals = [float(e) for e in (errors or [])]
    if not vals:
        return 0.0
    avg = sum(vals) / len(vals)
    return _clamp(max(0.0, avg - deadzone(vals, sigma)), 0.0, U_LIMIT)


def ratio_below(values, threshold):
    """P(·) 的离散估计：窗口内低于阈值的比例。窗口空 ⇒ 0。"""
    vals = [float(v) for v in (values or [])]
    if not vals:
        return 0.0
    return sum(1 for v in vals if v < threshold) / float(len(vals))


def p_trust(deltas):
    """§2.9.1 信任置信：P(δ_norm < 0.15 | 最近 N 轮)。"""
    return ratio_below(deltas, DELTA_TRUST)


def p_gap(gaps):
    """§2.9.1 信息差置信：P(D_norm < 0.10 | 最近 N 轮)。"""
    return ratio_below(gaps, GAP_STABLE)


def fully_trusted(pt, pg):
    """§2.9.1：完全可信要求两者**同时** ≥ 0.95——不允许任一维独大。"""
    return bool(pt >= FULL_TRUST and pg >= FULL_TRUST)


def t_total(deltas, errors, t_context=0.5, sigma=None, weights=W_DEFAULT):
    """§2.9 T_total = f(P_trust, T_pred, T_context)。

    T_pred 用 (1 − U_prediction_error) 表达：预测误差越小，信任越高。
    """
    wp, wu, wc = weights
    pt = p_trust(deltas)
    u = u_prediction_error(errors, sigma)
    return _clamp(wp * pt + wu * (1.0 - u) + wc * _clamp(t_context))


def e_weight(t_prev2, t_prev1, t_now):
    """§2.9 情感权重 = 信任的二阶变化率（等间隔近似）。"""
    d1 = float(t_prev1) - float(t_prev2)
    d2 = float(t_now) - float(t_prev1)
    return d2 - d1


def effective(t, ew, eta=ETA_DEFAULT):
    """§2.9 T_total_effective = T_total × (1 + η·E_weight)，结果仍限制在 0..1。"""
    return _clamp(float(t) * (1.0 + float(eta) * float(ew)))


def emotion_signal(d2_gap):
    """PROP-EMO-DIRECTION-002：情绪 = d²D_norm/dt²。

    返回**有符号效价**：信息差加速收缩（d²D<0）⇒ 正；加速扩张（d²D>0）⇒ 负。
    与 affect.py 的 valence 同向，可直接对接。
    """
    return -_clamp(float(d2_gap), -1.0, 1.0)
