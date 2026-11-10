#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""idf —— 主库 `_idf.json` 的加载与 idf 加权覆盖打分（R-2 / R-1 的底座）。

背景（为什么要有这个文件）：
    `/home/ubuntu/mdcg-data/_idf.json`（1,990,537 B、`N=10,975`、`df` 157,668 个 bigram）
    一直躺在数据根里，但全仓没有一处读它（`grep -rn "_idf" md_cg/*.py` 只命中
    `routing.domain_idf`，那是另一件事）。于是检索的打分腿一直是
    `md_cg/mdcg.py:628 lexical_sim()` 的 `inter / len(qb)` —— 分母是**查询**的
    bigram 数，一个常见 bigram 就能拿 0.25，长文档撞一个词就上分。

口径：
    idf(t)      = ln(1 + N / (1 + df(t)))
    idf_cov(Q,D)= Σ idf(g)  g∈Q∩D  /  Σ idf(g)  g∈Q
    缺词（不在 df 表里）按 `max_df` 计权 —— 与「没见过的词一定罕见」相反的一侧？
    不是：`max_df` 是**最常见**那个词的 df，用它算出的 idf 是下界，取它意味着
    「未知词最多只值一个常见词的权重」，不会让未知词凭空抬分。这一点与
    `basic-memory` 的「先归一化再设门」是同一思路的两个面。

设计约束：
    - 只读：不写任何文件，不碰 `_index.json`。
    - fail-open：`_idf.json` 缺失/损坏 → `enabled()` False，上层必须回退 legacy
      并在返回体标 `mode`，不得静默换口径。
    - 缓存：解析按 (路径, mtime_ns, size) 失效；`enabled()` 走 1 秒 TTL，
      避免逐候选 `os.stat`（一次检索会问上千次）。

自检：
    /usr/bin/python3 md_cg/idf.py --selftest
    /usr/bin/python3 md_cg/idf.py --probe 灵枢 唯一事实源 网关
    /usr/bin/python3 md_cg/idf.py --bench 1200
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import threading
import time

__all__ = [
    "ROOT_ENV", "DEFAULT_ROOT", "STATS",
    "load", "enabled", "idf", "idf_mass", "coverage",
    "reset_cache", "bigrams", "main",
]

ROOT_ENV = "MDCG_IDF_ROOT"
DEFAULT_ROOT = os.environ.get("MDCG_IDF_ROOT") or os.environ.get("MDCG_ROOT") or "/home/ubuntu/mdcg-data"
FILENAME = "_idf.json"
EN_TTL = 1.0

STATS = {
    "enabled": False,
    "mode": "legacy",       # legacy | idf_cov
    "n": 0,
    "df_terms": 0,
    "max_df": 1,
    "built_at": None,
    "path": "",
    "loaded_at": None,
    "error": "",
}

_lock = threading.Lock()
_cache_key = None
_cache = {"n": 0, "df": {}, "max_df": 1, "built_at": None, "failed": 0}
_en_at = 0.0
_en_val = False
_en_mode = None


def _path(root=None):
    return os.path.join(root or DEFAULT_ROOT, FILENAME)


def _signature(p):
    try:
        st = os.stat(p)
    except OSError:
        return None
    return (p, st.st_mtime_ns, st.st_size)


def reset_cache():
    global _cache_key, _en_at, _en_val, _en_mode
    with _lock:
        _cache_key = None
        _en_at = 0.0
        _en_val = False
        _en_mode = None
        _cache.update({"n": 0, "df": {}, "max_df": 1, "built_at": None, "failed": 0})


def load(root=None, force=False):
    """加载（或复用缓存）`_idf.json`。返回 STATS 的浅拷贝；任何失败都 fail-open。"""
    global _cache_key, _en_at, _en_val, _en_mode
    p = _path(root)
    sig = _signature(p)
    with _lock:
        if sig is None:
            _cache_key = None
            _en_at, _en_val, _en_mode = 0.0, False, None
            STATS.update({"enabled": False, "mode": "legacy", "path": p,
                          "error": "missing", "n": 0, "df_terms": 0})
            return dict(STATS)
        if not force and _cache_key == sig:
            return dict(STATS)
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            df = d.get("df") or {}
            if not isinstance(df, dict) or not df:
                raise ValueError("df 为空")
            n = int(d.get("N") or d.get("n") or 0)
            if n <= 0:
                raise ValueError("N 非法")
            _cache.update({
                "n": n,
                "df": df,
                "max_df": max(int(v) for v in df.values()),
                "built_at": d.get("built_at"),
                "failed": int(d.get("failed") or 0),
            })
            _cache_key = sig
            _en_at, _en_val, _en_mode = 0.0, False, None      # 让 enabled() 重新判定
            STATS.update({
                "enabled": False,
                "mode": "idf_cov",
                "n": n,
                "df_terms": len(df),
                "max_df": _cache["max_df"],
                "built_at": _cache["built_at"],
                "path": p,
                "loaded_at": time.time(),
                "error": "",
            })
        except Exception as e:                       # noqa: BLE001 —— fail-open 是本模块契约
            _cache_key = None
            _en_at, _en_val, _en_mode = 0.0, False, None
            STATS.update({"enabled": False, "mode": "legacy", "path": p,
                          "error": "%s: %s" % (type(e).__name__, e)})
        return dict(STATS)


def enabled(root=None):
    """是否可用 idf 口径。`MDCG_SCORE_MODE=legacy` 可强制关掉（负控用）。"""
    global _en_at, _en_val, _en_mode
    mode = (os.environ.get("MDCG_SCORE_MODE") or "idf_cov").strip().lower()
    now = time.time()
    if _en_mode == mode and (now - _en_at) < EN_TTL:
        return _en_val
    if mode == "legacy":
        _en_at, _en_val, _en_mode = now, False, mode
        STATS.update({"enabled": False, "mode": "legacy"})
        return False
    s = load(root)
    ok = bool(s["n"]) and bool(_cache["df"])
    _en_at, _en_val, _en_mode = now, ok, mode
    STATS["enabled"] = ok
    if ok:
        STATS["mode"] = "idf_cov"
    return ok


def _idf_raw(term):
    df = _cache["df"].get(term)
    n = _cache["n"]
    if df is None:
        df = _cache["max_df"]
    return math.log(1.0 + float(n) / (1.0 + float(df)))


def idf(term, root=None):
    """单 term 的 idf；未启用 → 1.0（与 legacy 等权等价）。"""
    if not enabled(root):
        return 1.0
    return _idf_raw(term)


# R-515（2026-11-10 审计）：这里原有 `idf_of(n, df)` 函数，docstring 称自己是
# 「两腿共用的 idf 公式（**唯一口径** `ln(1 + N/(1+df))`）」。两个事实都不对：
#   ① **没有调用方** —— 全仓零调用，连本模块的 `idf_mass` 都是**内联**同一算术
#      （见下方 `total += math.log(1.0 + base / (1.0 + float(df.get(g, max_df))))`）；
#   ② **不是唯一口径** —— `md_cg/mdcg.py:781` 另有一个 `idf_of(df, n_docs)`
#      （参数顺序相反），公式是 `log1p((N - df + 0.5) / (df + 0.5))`。
# 两套公式的关系已实测（N=100 扫 df 0..100）：**分数差很大**（df=90 时 0.741 vs
# 0.110），但 **rank 顺序逐位相同** ⇒ 对 RRF（用 rank 不用分数）无影响，对
# `min_score` 一类绝对阈值有影响。故两处各自在路内使用是可接受的，**但不得再声称
# 「唯一口径」**。此处删掉死函数，把公式留在 `idf_mass` 内联处（那才是活的那一份）。


def idf_mass(grams, root=None):
    if not grams:
        return 0.0
    if not enabled(root):
        return float(len(grams))
    total = 0.0
    df = _cache["df"]
    n = _cache["n"]
    max_df = _cache["max_df"]
    base = float(n)
    for g in grams:
        total += math.log(1.0 + base / (1.0 + float(df.get(g, max_df))))
    return total


def coverage(qb, nb, root=None):
    """idf 加权覆盖 = Σidf(Q∩D)/Σidf(Q)；未启用时退化成 legacy 同形。"""
    if not qb or not nb:
        return 0.0
    if not enabled(root):
        return len(qb & nb) / float(len(qb))
    denom = idf_mass(qb, root)
    if denom <= 0.0:
        return 0.0
    return idf_mass(qb & nb, root) / denom


def bigrams(s):
    """与主库同口径：去空白后相邻两字（`md_cg/mdcg.py` 的 bigrams 定义）。"""
    s = "".join((s or "").split())
    if len(s) <= 1:
        return set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def main(argv):
    root = None
    probe = None
    bench = 0
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--root" and i + 1 < len(argv):
            root = argv[i + 1]; i += 2; continue
        if a == "--probe" and i + 1 < len(argv):
            probe = argv[i + 1]; i += 2; continue
        if a == "--bench" and i + 1 < len(argv):
            bench = int(argv[i + 1]); i += 2; continue
        i += 1

    s = load(root, force=True)
    print("path          ", s["path"])
    print("enabled       ", enabled(root))
    print("mode          ", STATS["mode"])
    print("N             ", s["n"], "  df_terms", s["df_terms"], "  max_df", s["max_df"])
    print("built_at      ", s["built_at"], "  error", s["error"] or "-")

    if s["n"]:
        df = _cache["df"]
        vals = sorted(df.values())
        if vals:
            def pct(p):
                return vals[min(len(vals) - 1, int(len(vals) * p))]
            print("df 分位       p10=%d p50=%d p90=%d max=%d  df<=2 占比 %.2f%%"
                  % (pct(0.10), pct(0.50), pct(0.90), vals[-1],
                     100.0 * sum(1 for v in vals if v <= 2) / len(vals)))
        for t in ("记忆", "灵枢", "网关", "判据", "贝塞尔", "检索"):
            print("  %-6s df=%-6s idf=%.4f" % (t, df.get(t, "缺"), idf(t, root)))

    if probe is not None:
        qb = bigrams(probe)
        print("\n== probe: %r  (%d bigram) ==" % (probe, len(qb)))
        mass = idf_mass(qb, root)
        print("Σidf(Q) =", round(mass, 4))
        for g in sorted(qb):
            print("  %-4s df=%-6s idf=%.4f  权重占比 %.2f%%"
                  % (g, _cache["df"].get(g, "缺"), idf(g, root),
                     100.0 * idf(g, root) / mass if mass else 0.0))
        demo = set(list(qb)[:1]) | set(["记忆"])
        print("例：只中 1 个 bigram 的 idf_cov =", round(coverage(qb, demo, root), 4))

    if bench > 0:
        qb = bigrams("灵枢 唯一事实源 网关 记忆层 判据")
        pool = [set(random.sample(list(_cache["df"]), 8)) for _ in range(bench)]
        t0 = time.time()
        for nb in pool:
            coverage(qb, nb, root)
        dt = time.time() - t0
        print("\nbench: %d 对 idf_cov 用时 %.1f ms（每对 %.3f ms）"
              % (bench, dt * 1000, dt * 1000 / max(1, bench)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
