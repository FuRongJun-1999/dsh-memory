# -*- coding: utf-8 -*-
"""issue #672 守卫：资产包可裁剪——缺包降级而非 import 期崩。"""
from __future__ import annotations

import math

from . import freshness, mdcg


def main():
    ok = bad = 0

    def chk(cond, label, extra=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label, extra)

    # ① 可选导入单点：有包返回模块，无包返回 None（不抛）
    uni = mdcg._optional_asset(".semantic.unify")
    chk(uni is not None and hasattr(uni, "unify_query"), "#672 有包时返回模块对象")
    chk(mdcg._optional_asset(".semantic.this_module_does_not_exist") is None,
        "#672 缺包时返回 None（不抛 ImportError）", "")

    # ② freshness 的退化核与权威**同式**（e 指数 + clamp）
    class _Fake(object):
        pass

    f = freshness._FallbackCore.cred_factor
    for gamma, dt, floor, ceil in ((0.1, 10, 0.0, 1.0), (0.05, 0, 0.2, 0.9),
                                   (1.0, 3.5, 0.1, 0.8), (0.0, 99, 0.3, 0.7)):
        want = max(floor, min(ceil, math.exp(-gamma * dt)))
        chk(abs(f(gamma, dt, floor, ceil) - want) < 1e-12,
            "#672 退化核与权威同式（gamma=%s dt=%s）" % (gamma, dt))

    # ③ 现状：资产包在场 ⇒ 未降级，且 decay_factor 与权威逐位一致
    chk(freshness._CORE_DEGRADED is False, "#672 资产包在场时 _CORE_DEGRADED=False")
    from .whitebox_kb.aeis_core import time_core as _tc
    chk(freshness.decay_factor(0.1, 10) == _tc.cred_factor(0.1, 10),
        "#672 未降级时仍走唯一权威（逐位相等）")

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
