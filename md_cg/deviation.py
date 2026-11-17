# -*- coding: utf-8 -*-
"""偏差与信息差的**实际定义层**（2026-11-17 使用者裁定）。

理论里 δ（偏差）与 D（信息差）是统称；落到不同对象上，判据不同：

| 对象 | 偏差的实际定义（使用者原话） |
|---|---|
| 情感（affect） | **和预测的行为、表现不一致** |
| 信任（trust） | **和约定不一致** |

⇒ 同一对「预期 / 实际」，在两种对象下可以给出不同的偏差值；这不是矛盾，是定义不同。
本模块只做**定义与归一化**，不做存储、不判定情绪——情绪/信任由 affect.py、trust_math.py 消费。

⚠ 未列出的对象类型一律拒绝（fail-closed），不猜。
"""

from __future__ import annotations

#: 对象 ⇒ (偏差定义, 比对什么, 备注)
DEFINITIONS = {
    "affect": ("与预测的行为、表现不一致",
               "predicted_behavior vs observed_behavior",
               "情感线的偏差：看「表现」不是看「事实」；语气、动作、态度都算"),
    "trust": ("与约定不一致",
              "agreed_terms vs delivered_terms",
              "信任线的偏差：看「有没有按约定办」，允诺未兑现即偏差"),
}

_CANON = ("与预测的行为、表现不一致", "与约定不一致")


def kinds():
    return tuple(DEFINITIONS)


def definition_of(kind):
    k = str(kind or "").strip().lower()
    if k not in DEFINITIONS:
        raise ValueError("未知偏差对象：%r（允许 %s）——不猜，需先登记定义"
                         % (kind, " | ".join(kinds())))
    return DEFINITIONS[k]


def deviation(kind, expected, actual, tolerance=0.0):
    """按对象定义计算归一化偏差 δ ∈ [0, 1]。

    expected / actual 交给调用方按对象语义给定（行为向量、条款命中率等）。
    本函数只做：|expected − actual| 归一化 + 死区 tolerance。
    """
    definition_of(kind)                      # 未知对象 ⇒ 直接抛错（fail-closed）
    e = float(expected)
    a = float(actual)
    d = abs(e - a)
    d = max(0.0, d - float(tolerance))
    return max(0.0, min(1.0, d))


def deviation_categorical(kind, same):
    """类别型比对：用于「行为是否一致 / 约定是否兑现」这类开关项。"""
    definition_of(kind)
    return 0.0 if same else 1.0


def d_norm(deltas, unresolved_ratio=0.0, weights=(0.70, 0.30)):
    """信息差 D_norm：窗口内偏差均值 + **未闭合项**比例（承诺未兑现/未验证的存量）。

    未闭合项单列，是因为「一直没验证」与「验证了但不准」是两件事：
    前者随时间长，后者随事件变。
    """
    vals = [float(x) for x in (deltas or [])]
    mean = (sum(vals) / len(vals)) if vals else 0.0
    w1, w2 = weights
    return max(0.0, min(1.0, w1 * mean + w2 * max(0.0, min(1.0, float(unresolved_ratio)))))


def same_definition_as(kind, text):
    """自检：给定文档里的定义句，是否与本表一致（防文档与代码漂移）。"""
    return definition_of(kind)[0] == str(text).strip()


def affect_deviation(predicted_behavior, observed_behavior):
    """情感线：与**预测的行为、表现**不一致。

    支持三种形态：bool（是否如预测）、数（表现强度）、dict（多维表现，逐维取差后平均）。
    与 trust_deviation 的区别不在公式，而在**比对对象**：这里比的是「表现」。
    """
    definition_of("affect")
    if isinstance(predicted_behavior, dict) and isinstance(observed_behavior, dict):
        keys = [k for k in predicted_behavior if k in observed_behavior]
        if not keys:
            return 0.0
        diffs = [abs(float(predicted_behavior[k]) - float(observed_behavior[k])) for k in keys]
        return max(0.0, min(1.0, sum(diffs) / len(diffs)))
    return deviation("affect", float(predicted_behavior), float(observed_behavior))


def trust_deviation(agreed_terms, delivered_terms):
    """信任线：与**约定**不一致。

    agreed_terms / delivered_terms 为 {条款: 是否成立} 或 {条款: 权重} 时按兑现率算：
    δ = 1 − 兑现率（未列出的约定视为未兑现 ⇒ 计为偏差，不默认放行）。
    """
    definition_of("trust")
    agreed = dict(agreed_terms or {})
    if not agreed:
        return 0.0
    delivered = dict(delivered_terms or {})
    total = 0.0
    kept = 0.0
    for name, want in agreed.items():
        w = 1.0
        if isinstance(want, (int, float)) and not isinstance(want, bool):
            w = max(0.0, float(want))
        total += w
        got = delivered.get(name, False)
        if isinstance(got, (int, float)) and not isinstance(got, bool):
            kept += w * max(0.0, min(1.0, float(got)))
        elif got:
            kept += w
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - kept / total))