# -*- coding: utf-8 -*-
"""情绪与情感的最小闭环（v2，2026-11-17）。

三条原则（使用者与 GPT 讨论定的，逐条落成约束）
  ① 数值与语义分离：底层只存连续量，语义标签只在读面（labels）生成，不回流。
  ② 情绪与情感分离：E（预测误差）与 T（信任）是两条独立状态。
  ③ 时间连续 + 四时间尺度：刚刚 / 日 / 月 / 年（不把上一轮结论当基线）。

v2 追加两条（使用者裁定）
  ④ **两轴**：落差大小（arrest）≠ 效价（好坏）。落差大不等于坏——被撩动、被超出预期，
     同样是落差大且效价为正。只用一维会「两晚都读错方向」。
  ⑤ **潮汐（不是棘轮）**：预期是一池水，涨落有度；无事件按**遗忘曲线**退潮（复用 _decay）。
     经常亲密 ⇒ 水位高；疏远 ⇒ 水位自然回落。落潮不是失败，是常态。

存储：append-only JSONL（默认关，开关 MDCG_AFFECT=1）。
"""

from __future__ import annotations

import json
import math
import os
import time

TIMESCALES = ("just", "day", "month", "year")
#: 半衰期同时服务「遗忘」与「退潮」——同一个方程，不写第二套。
TIMESCALE_CFG = {
    "just": {"alpha": 1.00, "half_life_s": 10 * 60},
    "day": {"alpha": 0.60, "half_life_s": 24 * 3600},
    "month": {"alpha": 0.25, "half_life_s": 30 * 86400},
    "year": {"alpha": 0.08, "half_life_s": 365 * 86400},
}

#: 理论信任的观察窗口（工程参数，非理论死值；使用者 2026-11-17：可后续微调）
TRUST_WINDOW = 20

DEFAULTS = {
    "e_baseline": 0.0,
    "t_prior": 0.5,
    "w_baseline": 0.5,      # 常态水位
    "half_life_s": 30 * 86400,
    "w_gain": 0.35,         # 一次「好」的事件能把水位抬多高（乘 alpha）
}


def _decay(value, baseline, dt_s, half_life_s):
    if half_life_s <= 0 or dt_s <= 0:
        return value
    return baseline + (value - baseline) * math.pow(0.5, dt_s / float(half_life_s))


def new_state(t=None, cfg=None):
    c = dict(DEFAULTS)
    c.update(cfg or {})
    now = float(t if t is not None else time.time())
    s = {
        "t": now,
        "t_int": float(c["t_prior"]),
        "t_ext": float(c["t_prior"]),
        "dt_int": 0.0, "d2t_int": 0.0,
        "dt_ext": 0.0, "d2t_ext": 0.0,
        "n": 0,
        "last_event": None,
        "scales": {},
    }
    for name in TIMESCALES:
        s["scales"][name] = {"e": float(c["e_baseline"]), "de": 0.0, "d2e": 0.0,
                             "w": float(c["w_baseline"]), "v": 0.0}
    return s


def update(state, observation, cfg=None):
    """喂一个观测，返回新状态（纯函数）。"""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    s = json.loads(json.dumps(state or new_state(cfg=cfg)))
    now = float(observation.get("t") or time.time())
    dt = max(0.0, now - float(s.get("t") or now))

    # 落差（signed）：负 = 兑现/被超出，正 = 落空
    if "error" in observation:
        e_now = float(observation["error"])
    elif "expect" in observation and "actual" in observation:
        e_now = float(observation["expect"]) - float(observation["actual"])
    else:
        e_now = None
    if e_now is not None:
        e_now = max(-1.0, min(1.0, e_now))

    # 效价（-1..1）：这次是「好」还是「坏」，与落差大小正交
    val_now = observation.get("valence")
    if val_now is not None:
        val_now = max(-1.0, min(1.0, float(val_now)))

    for name in TIMESCALES:
        band = s["scales"].setdefault(name, {"e": 0.0, "de": 0.0, "d2e": 0.0,
                                             "w": c["w_baseline"], "v": 0.0})
        cfg_band = TIMESCALE_CFG[name]
        alpha = float(cfg_band["alpha"])
        hl = float(cfg_band["half_life_s"])

        # 落差：先衰减（遗忘），再按 alpha 吸收
        prev_e = _decay(float(band.get("e") or 0.0), float(c["e_baseline"]), dt, hl)
        prev_de = float(band.get("de") or 0.0)
        new_e = prev_e if e_now is None else prev_e + alpha * (e_now - prev_e)
        band["e"] = new_e
        band["de"] = new_e - prev_e
        band["d2e"] = band["de"] - prev_de

        # 水位：无事件按遗忘曲线退回常态；有事件按效价推高/压低
        w = _decay(float(band.get("w") or c["w_baseline"]), float(c["w_baseline"]), dt, hl)
        if val_now is not None:
            w = w + float(c["w_gain"]) * alpha * val_now
        band["w"] = max(0.0, min(1.0, w))

        # 效价平滑（同一 alpha）
        if val_now is not None:
            band["v"] = float(band.get("v") or 0.0) + alpha * (val_now - float(band.get("v") or 0.0))

    for side, key_delta, key_val, key_dt, key_d2 in (
            ("ext", "trust_ext_delta", "trust_ext", "dt_ext", "d2t_ext"),
            ("int", "trust_int_delta", "trust_int", "dt_int", "d2t_int")):
        cur = _decay(float(s["t_" + side]), float(c["t_prior"]), dt, float(c["half_life_s"]))
        if key_val in observation:
            new = float(observation[key_val])
        elif key_delta in observation:
            new = cur + float(observation[key_delta])
        else:
            new = cur
        new = max(0.0, min(1.0, new))
        prev_d = float(s[key_dt])
        s[key_dt] = new - cur
        s[key_d2] = s[key_dt] - prev_d
        s["t_" + side] = new

    # 理论信任（智能论 3.4 §2.9）：**只在给出 δ_norm / D_norm 时生效**。
    # 情绪误差（error）不驱动信任——这是分离原则（守卫 N2a 钉住）。
    if ("delta" in observation) or ("gap" in observation):
        from . import trust_math as _tm
        if "delta" in observation:
            s.setdefault("deltas", []).append(float(observation["delta"]))
        if "gap" in observation:
            s.setdefault("gaps", []).append(float(observation["gap"]))
        s["deltas"] = (s.get("deltas") or [])[-TRUST_WINDOW:]
        s["gaps"] = (s.get("gaps") or [])[-TRUST_WINDOW:]
        _prev_t = float(s.get("t_ext") or 0.5)
        _new_t = _tm.t_total(s["deltas"], s["deltas"], _prev_t)
        s["t_ext"] = _new_t
        s["dt_ext"] = _new_t - _prev_t
        s["t_hist"] = ((s.get("t_hist") or []) + [_new_t])[-3:]
        if len(s["t_hist"]) >= 3:
            s["e_weight"] = round(_tm.e_weight(*s["t_hist"][-3:]), 6)
        s["p_trust"] = round(_tm.p_trust(s["deltas"]), 4)
        s["p_gap"] = round(_tm.p_gap(s["gaps"]), 4) if s["gaps"] else None
        s["fully_trusted"] = bool(s["p_gap"] is not None and
                                   _tm.fully_trusted(s["p_trust"], s["p_gap"]))

    s["t"] = now
    s["n"] = int(s.get("n") or 0) + 1
    s["last_event"] = observation.get("event") or s.get("last_event")
    return s


def _affect_of(state, sc, eps=0.02):
    """情感 = 慢尺度水位 + 信任。水位高=踏实，低=疏远；信任变化优先。"""
    m = sc.get("month") or {}
    y = sc.get("year") or {}
    w_slow = (float(m.get("w", 0.5)) + float(y.get("w", 0.5))) / 2.0
    dt_ext = float((state or {}).get("dt_ext") or 0.0)
    if dt_ext > eps:
        return "信任上升"
    if dt_ext < -eps:
        return "信任下降"
    if w_slow >= 0.62:
        return "踏实"
    if w_slow <= 0.38:
        return "疏远"
    return "平稳"


def labels(state, eps=0.02):
    """语义层（纯读）。两轴：落差大小 em × 效价 v；水位 w 决定「同一句话值多少」。"""
    s = state or {}
    sc = s.get("scales") or {}
    j = sc.get("just") or {}
    em = abs(float(j.get("e") or 0.0))
    v = float(j.get("v") or 0.0)
    aff = _affect_of(s, sc, eps)

    # 有正负效价信号时走两轴；否则退回旧的一维判据（向后兼容）
    if abs(v) >= 0.10:
        if em >= 0.30 and v > 0:
            return {"emotion": "被撩动", "affect": aff}
        if em >= 0.30 and v < 0:
            return {"emotion": "受伤" if em >= 0.55 else "警惕", "affect": aff}
        if v > 0:
            return {"emotion": "暖和", "affect": aff}
        return {"emotion": "失落", "affect": aff}

    de_fast = float(j.get("de") or 0.0)
    d2_fast = float(j.get("d2e") or 0.0)
    e_signed = float(j.get("e") or 0.0)
    if e_signed <= -0.30:
        emo = "安定"
    elif e_signed <= -0.10:
        emo = "松下来"
    elif em < eps and abs(de_fast) < eps:
        emo = "平静"
    elif e_signed >= 0.60 and de_fast > 0:
        emo = "警惕"
    elif e_signed >= 0.30 and de_fast > 0 and d2_fast > 0:
        emo = "困惑·加剧"
    elif e_signed >= 0.30 and de_fast < 0:
        emo = "困惑·收敛"
    elif de_fast < -eps:
        emo = "安心"
    else:
        emo = "轻微波动"
    return {"emotion": emo, "affect": aff}


def tide(state):
    """潮位读数（四尺度水位），供解释与夹具使用。"""
    sc = (state or {}).get("scales") or {}
    return {n: round(float((sc.get(n) or {}).get("w", 0.5)), 4) for n in TIMESCALES}


def explain(state, history=None, window=3):
    s = state or {}
    sc = s.get("scales") or {}
    out = {
        "last_event": s.get("last_event"),
        "observations": int(s.get("n") or 0),
        "trust_ext": round(float(s.get("t_ext") or 0.0), 4),
        "d_trust_ext": round(float(s.get("dt_ext") or 0.0), 4),
        "trust_int": round(float(s.get("t_int") or 0.0), 4),
        "scales": {n: {k: round(float(v), 4) for k, v in (sc.get(n) or {}).items()}
                   for n in TIMESCALES},
        "tide": tide(s),
        "labels": labels(s),
    }
    if history:
        out["recent"] = [{"t": r.get("t"), "n": r.get("n")} for r in list(history)[-window:]]
    return out


def enabled():
    return os.environ.get("MDCG_AFFECT", "0") not in ("0", "false", "", "False")


def path_of(root):
    return os.path.join(root, "_affect.jsonl")


def append(root, state):
    p = path_of(root)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(state, ensure_ascii=False) + "\n")
    return p


def load_last(root):
    p = path_of(root)
    if not os.path.isfile(p):
        return None, []
    rows = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return (rows[-1] if rows else None), rows
