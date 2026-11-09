#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""autocut —— 检索截断的**阈值裁切**层（C-2，2026-10-31）。

位置：`md_cg/mdcg.py::cut_by_relevance` 完成「按相关度排序」之后、
`pooling.cut_report` 之前。职责是把「名次融合后的有序候选」按三条阈值裁短，
且**只依赖 (cap, tie_max, drop_zero)，与调用方的 k 无关**——于是任意 LIMIT
的返回都是同一条有序表的前缀（`LIMIT 5 ⊂ LIMIT 20 ⊂ LIMIT 100`）。

三条规则（顺序固定，每步都记账）：

  R1 zero_drop  `score <= 0` 的行删掉。
                分数面的 0 有两种语义（见 `MdCG._emit` docstring）：T3 兜底里
                0＝真无关；T2/T0/T1 里 0＝过了 LIKE 闸但没命中打分面（纯填充）。
                两者都不该占名次——真无关有负覆盖尾条负责，填充行本来就排不上。
                **例外**：reach 图扩散邻居、S5 开启时被 λ 降权到 0 的真候选，
                调用方传 `zero_policy="keep"` 保留（见 `cut_by_relevance`）。
  R2 tie_trim   同一分数（round 6 位）最多留 `tie_max` 行，超出的按名次丢掉。
                分数面只有有限几档（1.0 / 0.97716 / 0.954842 / …），实测一个
                查询 100 条里能有 68 条同分——那一段的名次已经退化成 id 序，
                属噪声。留前 `tie_max` 条＝保留全部名次信息，丢掉的本来排不出序。
  R3 cap_trim   截到 `cap` 行（`pooling.cut_report` 之后还会再截一次，同值）。

开关（env，默认全开；关掉任一项都用于负控）：

  MDCG_AUTOCUT=0             整层关闭（R1/R2/R3 全不做）
  MDCG_AUTOCUT_TIE_MAX=0     关闭 R2（同分簇不裁）
  MDCG_AUTOCUT_DROP_ZERO=0   关闭 R1（0 分行保留）

`cut()` 是纯函数（不改入参、不读盘、不抛业务异常），可单独测：
    /usr/bin/python3 md_cg/autocut.py --selftest
"""
import os

__all__ = ["cut", "rule_of", "tie_max_of", "drop_zero_of", "enabled_of",
           "floor_of"]

RULE = "autocut/v1"
DEFAULT_TIE_MAX = 20
SCORE_DP = 6          # 同分判定的小数位（与观测到的 0.97716/0.954842 同精度）


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return int(default)


def enabled_of():
    """整层开关：默认开，`MDCG_AUTOCUT=0` 关。"""
    raw = os.environ.get("MDCG_AUTOCUT")
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() not in ("0", "off", "false", "no", "")


def tie_max_of():
    """R2 上限；`<=0` 表示**关闭 R2**（负控用，不是「一条都不留」）。"""
    return _env_int("MDCG_AUTOCUT_TIE_MAX", DEFAULT_TIE_MAX)


def drop_zero_of():
    """R1 开关：默认开，`MDCG_AUTOCUT_DROP_ZERO=0` 关。"""
    raw = os.environ.get("MDCG_AUTOCUT_DROP_ZERO")
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() not in ("0", "off", "false", "no", "")


def floor_of():
    """R0 绝对地板（R-3）：返回 (floor, source)。

    `MDCG_RETRIEVAL_FLOOR` 缺省 **0.0 = 关门**——不开门时 `cut()` 与加门之前逐字节
    等价（这是本补丁的负控前提）。取 0~1 之间的浮点；无法解析 → 0.0 并如实回报
    `source="bad"`。分数面只有 0~1，超出范围的按 1.0 截上。
    """
    raw = os.environ.get("MDCG_RETRIEVAL_FLOOR")
    if raw is None or str(raw).strip() == "":
        return 0.0, "default"
    try:
        f = float(str(raw).strip())
    except (TypeError, ValueError):
        return 0.0, "bad"
    if f != f:                                     # NaN
        return 0.0, "bad"
    if f <= 0.0:
        return 0.0, "off"
    return min(1.0, f), "env"


def rule_of():
    return RULE


def _q(score):
    """同分判定用的量化分数（NaN → 0.0，避免 NaN 让比较全假）。"""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return 0.0
    if s != s:                                     # NaN
        return 0.0
    return round(s, SCORE_DP)


def _clusters(rows):
    """有序行 → [(量化分数, 条数)]，同分相邻合并（不重排，只数）。"""
    out = []
    for _doc, score in rows:
        key = _q(score)
        if out and out[-1][0] == key:
            out[-1][1] += 1
        else:
            out.append([key, 1])
    return [(k, n) for k, n in out]


def cut(pairs, cap, *, tie_max=None, drop_zero=None, floor=None):
    """按阈值裁切**已排好序**的候选。

    `pairs`：`[(doc, score)]`，名次序（`cut_by_relevance` 的排序结果）。
    `cap`：输出上限（= `GLOBAL_CAP`）。
    `tie_max` / `drop_zero`：缺省读 env（见模块 docstring）。

    返回 `(kept, report)`；`kept` 仍是 `[(doc, score)]`，顺序与入参一致。
    """
    rows = []
    for d, s in pairs:
        try:
            s = float(s)
        except (TypeError, ValueError):
            s = 0.0
        if s != s:                                 # NaN → 0（同 _q）
            s = 0.0
        rows.append((d, s))
    n_in = len(rows)
    cap = int(cap)
    tie_max = tie_max_of() if tie_max is None else int(tie_max)
    if floor is None:
        floor, floor_src = floor_of()
    else:
        floor, floor_src = float(floor), "arg"
    drop_zero = drop_zero_of() if drop_zero is None else bool(drop_zero)
    on = enabled_of()

    cl_in = _clusters(rows)
    rep = {
        "rule": RULE,
        "enabled": bool(on),
        "cap": cap,
        "tie_max": tie_max,
        "drop_zero": bool(drop_zero),
        "floor": round(float(floor), 6),
        "floor_src": floor_src,
        "floor_dropped": 0,
        "n_in": n_in,
        "n_out": n_in,
        "zero_dropped": 0,
        "tie_trimmed": 0,
        "cap_trimmed": 0,
        "clusters_in": len(cl_in),
        "clusters_out": len(cl_in),
        "max_cluster_in": max([n for _k, n in cl_in] or [0]),
        "max_cluster_out": max([n for _k, n in cl_in] or [0]),
    }
    if not on:
        # 关闭态：**一个字节都不裁**，也不伪造裁切账（只如实回报入参形态）。
        return rows, rep

    # R0 —— 绝对地板（R-3）：分数 < floor 的直接不出结果面。
    # 与 R1 的区别：R1 只删「恰好 0 分」的填充行；R0 删的是「有分但不够格」
    # 的弱命中（实测噪声可到 0.24~0.62，真查询 0.79~1.0）。floor=0 时本段不动任何行。
    if floor > 0:
        kept0 = [(d, s) for d, s in rows if _q(s) >= round(float(floor), SCORE_DP)]
        rep["floor_dropped"] = len(rows) - len(kept0)
        rows = kept0
        n_in = len(rows)
        cl_in = _clusters(rows)
        rep["n_out"] = n_in
        rep["clusters_out"] = len(cl_in)
        rep["max_cluster_out"] = max([n for _k, n in cl_in] or [0])

    # R1 —— 删 0 分填充行（尾部连续段；排序保证 0 分不会出现在正分中间）
    kept = rows
    if drop_zero:
        kept = [(d, s) for d, s in rows if _q(s) > 0]
        rep["zero_dropped"] = n_in - len(kept)

    # R2 —— 同分簇裁到 tie_max（留簇内前 tie_max 条）
    if tie_max > 0:
        seen = {}
        trimmed = []
        for d, s in kept:
            key = _q(s)
            hit = seen.get(key, 0)
            if hit >= tie_max:
                continue
            seen[key] = hit + 1
            trimmed.append((d, s))
        rep["tie_trimmed"] = len(kept) - len(trimmed)
        kept = trimmed

    # R3 —— 截到 cap
    if cap >= 0 and len(kept) > cap:
        rep["cap_trimmed"] = len(kept) - cap
        kept = kept[:cap]

    cl_out = _clusters(kept)
    rep["n_out"] = len(kept)
    rep["clusters_out"] = len(cl_out)
    rep["max_cluster_out"] = max([n for _k, n in cl_out] or [0])
    return kept, rep


# ---------------------------------------------------------------- selftest
def _selftest():
    ok = 0
    fail = []

    def chk(name, cond):
        nonlocal ok
        if cond:
            ok += 1
        else:
            fail.append(name)

    # 夹具：3 个分数簇，最大簇 30 条 0.5 分，尾部 5 条 0 分
    def mk(n_pos, tie, n_zero):
        rows = [({"id": "a%d" % i}, 1.0) for i in range(n_pos)]
        rows += [({"id": "t%d" % i}, 0.5) for i in range(tie)]
        rows += [({"id": "z%d" % i}, 0.0) for i in range(n_zero)]
        return rows

    old = {k: os.environ.get(k) for k in
           ("MDCG_AUTOCUT", "MDCG_AUTOCUT_TIE_MAX", "MDCG_AUTOCUT_DROP_ZERO")}
    try:
        for k in old:
            os.environ.pop(k, None)

        rows = mk(3, 30, 5)
        kept, rep = cut(rows, 500)
        chk("zero 删净", rep["zero_dropped"] == 5)
        chk("同分簇裁到 20", rep["max_cluster_out"] == 20)
        chk("簇内留前 20", [d["id"] for d, _s in kept][3:6] == ["t0", "t1", "t2"])
        chk("总长 3+20", len(kept) == 23)
        chk("入参不被改", len(rows) == 38)
        chk("账目闭合", rep["n_in"] - rep["zero_dropped"] -
            rep["tie_trimmed"] - rep["cap_trimmed"] == rep["n_out"])

        # 前缀一致：cap 更大时结果只是更长，前缀逐位相同
        kept2, _ = cut(mk(3, 30, 5), 5000)
        chk("任意 cap 前缀一致", kept2[:len(kept)] == kept)

        # R3
        kept3, rep3 = cut(mk(3, 30, 5), 10)
        chk("cap 咬合", len(kept3) == 10 and rep3["cap_trimmed"] == 13)

        # 负控 1：整层关闭 → 38 条原样返回（0 分行也在）
        os.environ["MDCG_AUTOCUT"] = "0"
        kept4, rep4 = cut(mk(3, 30, 5), 500)
        chk("负控-整层关", len(kept4) == 38 and rep4["enabled"] is False)
        chk("负控-整层关仍报簇", rep4["max_cluster_out"] == 30)
        os.environ.pop("MDCG_AUTOCUT", None)

        # 负控 2：tie_max=0 关 R2 → 同分簇回到 30（判据该变红）
        os.environ["MDCG_AUTOCUT_TIE_MAX"] = "0"
        _k5, rep5 = cut(mk(3, 30, 5), 500)
        chk("负控-tie_max=0", rep5["max_cluster_out"] == 30 and
            rep5["tie_trimmed"] == 0)
        os.environ.pop("MDCG_AUTOCUT_TIE_MAX", None)

        # 负控 3：DROP_ZERO=0 → 0 分行保留（Z 判据该变红）
        os.environ["MDCG_AUTOCUT_DROP_ZERO"] = "0"
        _k6, rep6 = cut(mk(3, 30, 5), 500)
        chk("负控-drop_zero=0", rep6["zero_dropped"] == 0 and
            sum(1 for _d, s in _k6 if s <= 0) == 5)
        os.environ.pop("MDCG_AUTOCUT_DROP_ZERO", None)

        # 空输入 / 全 0 分
        chk("空输入", cut([], 500)[0] == [])
        _k7, rep7 = cut(mk(0, 0, 4), 500)
        chk("全 0 分删净", _k7 == [] and rep7["n_out"] == 0)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    total = ok + len(fail)
    print("autocut selftest: %d/%d %s" % (ok, total, "PASS" if not fail else
                                          "FAIL " + ",".join(fail)))
    return 0 if not fail else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("usage: python3 -m md_cg.autocut --selftest")
