# -*- coding: utf-8 -*-
r"""守卫 · #99 WAL 签名串字段边界可挪动（2026-10-09 DSH 端，入口堵法）。

缺陷（GitHub #99）：签名串按 seq|type|from|to|round|ts|payload 直接拼接，
字段里的 | 不转义、无长度前缀 ⇒ 攻击者不知密钥也能把 | 挪一格改写 from/to：
    原始:  from=inst_a  to=inst_b|inst_c
    伪造:  from=inst_a|inst_b  to=inst_c     —— 两者签名串完全相同。

本笔的处置＝**堵入口**（配置侧 id / 路由 event_type 不得含 |）；
彻底解（长度前缀 / JSON 规范化 + Rust 与 Python 两侧同步）另计。

判据：
  G1 复现：两个不同字段划分产出**同一拼串** ⇒ 缺陷真实存在（非空转）
  G2 入口拒绝：id 含 | ⇒ make_swarm_config 抛 ValueError
  G3 入口拒绝：routes 的 event_type 含 | ⇒ 抛 ValueError
  G4 不误伤：正常 id / 正常路由仍可构造
运行：python -X utf8 -m swarm.tests.test_issue99_wal_boundary
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _msg(seq, typ, frm, to, rnd, ts, payload):
    """与 verify_wal_signatures 同构的拼串（守卫内复刻，用于 G1 复现）。"""
    return "%s|%s|%s|%s|%s|%s|%s" % (seq, typ, frm, to, rnd, ts, payload)


def main():
    from swarm.rust_swarm import make_swarm_config

    # G1 复现（非空转）：两种字段划分 ⇒ 同一拼串
    m1 = _msg(1, "ev", "inst_a", "inst_b|inst_c", 0, 0, "{}")
    m2 = _msg(1, "ev", "inst_a|inst_b", "inst_c", 0, 0, "{}")
    check("G1 复现：两种 from/to 划分产出**同一拼串**（缺陷真实存在）",
          m1 == m2, "m1=%r m2=%r" % (m1, m2))

    # G2 id 含 | ⇒ 拒
    try:
        make_swarm_config([{"id": "inst_a|inst_b"}], [], shared_secret="k")
        check("G2 id 含 | ⇒ ValueError", False, "未抛异常")
    except ValueError as exc:
        check("G2 id 含 | ⇒ ValueError", "|" in str(exc), str(exc)[:60])

    # G3 event_type 含 | ⇒ 拒
    try:
        make_swarm_config([{"id": "a"}],
                          [{"from": "a", "event_type": "x|y", "to": "a"}],
                          shared_secret="k")
        check("G3 路由 event_type 含 | ⇒ ValueError", False, "未抛异常")
    except ValueError as exc:
        check("G3 路由 event_type 含 | ⇒ ValueError", "|" in str(exc), str(exc)[:60])

    # G4 不误伤
    try:
        cfg = make_swarm_config([{"id": "inst_a"}], [], shared_secret="k")
        check("G4 正常 id 不受影响", cfg.get("shared_secret") == "k", "")
    except Exception as exc:
        check("G4 正常 id 不受影响", False, repr(exc)[:60])

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
