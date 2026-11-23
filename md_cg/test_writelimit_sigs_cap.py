# -*- coding: utf-8 -*-
"""活签名上限守卫（issue #1003）。

#1001 只收死重，活条目本身无上界（RATE_MAX=8/60s ⇒ 11520/日/role）。本守卫校准
「超限按最近命中 LRU 淘汰」这一层：

C1 未超限不动（少一条都不该动）
C2 超限后规模恰为 cap，且留下的是最近命中的那批
C3 'last' 优先于 't'：登记早但反复命中的模板必须留下
C4 坏型/缺失时间戳按最旧处理（不被当成最新保下来）
C5 MDCG_SIGS_MAX=0 关闭上限（老行为：只收死重）
C6 MDCG_SIGS_MAX 环境变量覆盖常量；非法值回落常量
C7 死重与活重同一遍处理：返回条数 = 死重 + 淘汰
C8 上限小于回收阈值时仍能触发（trigger 取 min）
C9 未来戳保留（#1001 判据不变），且按 t 参与排序
C10 不动 rate 与顶层结构；返回值保持 int（调用方契约不变）
"""
from __future__ import annotations

import os

from . import writelimit as W


def _sig(i: str) -> str:
    return "%064x" % (int(i) * 2654435761)


def main():
    ok = 0
    bad = 0

    def chk(cond, label):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label)

    now = 1_800_000_000.0

    def mk(n, last=None):
        st = {"rate": {}, "sigs": {}}
        for i in range(n):
            rec = {"nid": "n%d" % i, "t": now - i * 10, "n": 1, "sk": "x", "sens": None}
            if last is not None:
                rec["last"] = last(i)
            st["sigs"][_sig(str(i))] = rec
        return st

    st = mk(10)
    n = W._prune_sigs(st, now=now, min_sigs=5)
    chk(n == 0 and len(st["sigs"]) == 10, "C1 未超限不动（10 条 → 10 条）")

    old = W.SIGS_MAX
    W.SIGS_MAX = 8
    try:
        st = mk(20)
        n = W._prune_sigs(st, now=now, min_sigs=5)
        chk(len(st["sigs"]) == 8 and n == 12,
            "C2 20 条超限 → 恰 8 条，删 12 条（实 %d / 删 %d）" % (len(st["sigs"]), n))
        kept = sorted(st["sigs"].values(), key=lambda r: r["t"], reverse=True)
        chk([r["nid"] for r in kept] == ["n%d" % i for i in range(8)],
            "C2b 留下的是 t 最新的 8 条")

        # i>=15 的登记时间 t 更旧，但 last 更新（now+100）——必须按 last 留下
        st = mk(20, last=lambda i: (now + 100) if i >= 15 else (now - i * 10))
        W._prune_sigs(st, now=now, min_sigs=5)
        kept_ids = {r["nid"] for r in st["sigs"].values()}
        chk(all(("n%d" % i) in kept_ids for i in range(15, 20)),
            "C3 登记早但 last 最近的模板被留下")

        st = {"rate": {}, "sigs": {}}
        for i in range(12):
            st["sigs"][_sig(str(i))] = {"nid": "n%d" % i, "t": now - i, "n": 1}
        st["sigs"][_sig("77")] = {"nid": "nx", "t": "not-a-number", "n": 1}
        st["sigs"][_sig("78")] = {"nid": "ny", "t": now, "last": float("nan"), "n": 1}
        W._prune_sigs(st, now=now, min_sigs=5)
        ids = {r["nid"] for r in st["sigs"].values()}
        chk("nx" not in ids, "C4 t 坏型 → 按最旧处理（被淘汰）")
        chk("ny" in ids, "C4b last 坏（NaN）回落到 t=now ⇒ 按最新保留，不因单字段坏被判最旧")
    finally:
        W.SIGS_MAX = old

    os.environ["MDCG_SIGS_MAX"] = "0"
    try:
        st = mk(20)
        n = W._prune_sigs(st, now=now, min_sigs=5)
        chk(len(st["sigs"]) == 20 and n == 0, "C5 MDCG_SIGS_MAX=0 不淘汰（老行为）")
    finally:
        os.environ.pop("MDCG_SIGS_MAX", None)

    os.environ["MDCG_SIGS_MAX"] = "3"
    try:
        chk(W._sigs_max() == 3, "C6 env=3 覆盖常量")
        st = mk(20)
        W._prune_sigs(st, now=now, min_sigs=5)
        chk(len(st["sigs"]) == 3, "C6b env=3 时活条目收到 3 条")
        os.environ["MDCG_SIGS_MAX"] = "abc"
        chk(W._sigs_max() == W.SIGS_MAX, "C6c 非法值回落常量")
    finally:
        os.environ.pop("MDCG_SIGS_MAX", None)

    old = W.SIGS_MAX
    W.SIGS_MAX = 4
    try:
        st = mk(10)
        for i, k in enumerate(list(st["sigs"])):
            if i < 3:
                st["sigs"][k] = dict(st["sigs"][k], t=now - W.CONVERGE_WINDOW - 10)
        n = W._prune_sigs(st, now=now, min_sigs=2)
        chk(len(st["sigs"]) == 4 and n == 6,
            "C7 删 3 死重 + 3 活重 = 6（实 %d / 删 %d）" % (len(st["sigs"]), n))

        st = mk(6)
        n = W._prune_sigs(st, now=now, min_sigs=999)
        chk(n == 2 and len(st["sigs"]) == 4, "C8 cap(4) < 阈值(999) 时仍触发")

        st = mk(6)
        st["sigs"][_sig("79")] = {"nid": "nz", "t": now + 3600, "n": 1}
        W._prune_sigs(st, now=now, min_sigs=2)
        chk(_sig("79") in st["sigs"], "C9 未来戳被保留")
    finally:
        W.SIGS_MAX = old

    st = {"rate": {"contextual:user": [now]}, "sigs": {}}
    for i in range(6):
        st["sigs"][_sig(str(i))] = {"nid": "n%d" % i, "t": now - i, "n": 1}
    n = W._prune_sigs(st, now=now, min_sigs=2)
    chk(isinstance(n, int) and st["rate"] == {"contextual:user": [now]},
        "C10 返回 int 且 rate 原样")

    print()
    print("活签名上限守卫：%d 通过 / %d 失败" % (ok, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
