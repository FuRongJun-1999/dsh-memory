# -*- coding: utf-8 -*-
r"""守卫 · #98 MDCG_TENANT 未设时不得打开他人租户的登记根（2026-10-09 DSH 端实施）。

缺陷（GitHub #98，本端守卫 G1 复现其形态）：
    A 的令牌 + MDCG_ROOT=B 的登记根 + **不设 MDCG_TENANT** ⇒ 可跨租户读 internal
    并写入（B 根下出现 A 写的文件）。
    根因：_resolve_root 只在 MDCG_TENANT 非空时查登记表；未设时**直接回落 MDCG_ROOT**，
    既不看令牌租户、也不看该根归属谁。

本笔处置（按 issue 建议 2，**无需解令牌**）：MDCG_TENANT 未设时**反向查登记表**
    —— 若 MDCG_ROOT 命中任一已登记租户的登记根 ⇒ 身份与根未对照 ⇒ fail-closed 拒绝。
    自建（未登记）根不受影响。

判据（真跑 _resolve_root，用临时登记表）：
  G1 复现：不设 TENANT + MDCG_ROOT=B 的登记根 ⇒ **返回 err**（修前返回 (rb, None)）
  G2 不误伤：MDCG_TENANT=A + MDCG_ROOT=A 的登记根 ⇒ 正常
  G3 不误伤：不设 TENANT + MDCG_ROOT=未登记的自建根 ⇒ 正常
  G4 既有行为保持：MDCG_TENANT=A + MDCG_ROOT=B 的登记根 ⇒ err（这条修前就有）
运行：python -X utf8 -m md_cg.test_issue98_tenant_root
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
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


def main():
    from md_cg.mcp_server import _resolve_root

    d = tempfile.mkdtemp(prefix="p98_")
    ra = os.path.join(d, "ra")
    rb = os.path.join(d, "rb")
    free = os.path.join(d, "free")
    for p in (ra, rb, free):
        os.makedirs(p, exist_ok=True)
    reg = os.path.join(d, "_tenants.json")
    # 登记表结构 = {"schema":1,"tenants":{租户:{root,clearance_cap,...}}}
    # （security.py:302 默认值 / :316 register() 写入形态）——首版守卫误写成
    # 裸 {"A": ra}，触发 KeyError: 'tenants' 并\u201c静默回落\u201d，四条判据里两条失真。
    with open(reg, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "tenants": {
            "A": {"root": os.path.abspath(ra), "clearance_cap": "internal"},
            "B": {"root": os.path.abspath(rb), "clearance_cap": "internal"},
        }}, f)

    def call(**env):
        e = dict(env)
        e["MDCG_TENANT_REGISTRY"] = reg
        return _resolve_root(e)

    # G1 复现：不设 TENANT + 打开 B 的登记根
    root1, err1 = call(MDCG_ROOT=rb)
    check("G1 不设 TENANT + MDCG_ROOT=B 的登记根 ⇒ 拒绝（修前放行）",
          err1 is not None, "root=%r err=%r" % (root1, (err1 or "")[:70]))

    # G2 正常：显式声明租户 A + A 的根
    root2, err2 = call(MDCG_TENANT="A", MDCG_ROOT=ra)
    check("G2 MDCG_TENANT=A + A 的根 ⇒ 正常",
          err2 is None and root2 == ra, "root=%r err=%r" % (root2, err2))

    # G3 自建根不受影响
    root3, err3 = call(MDCG_ROOT=free)
    check("G3 不设 TENANT + 未登记的自建根 ⇒ 正常（不误伤）",
          err3 is None and root3 == free, "root=%r err=%r" % (root3, err3))

    # G4 既有行为保持
    _root4, err4 = call(MDCG_TENANT="A", MDCG_ROOT=rb)
    check("G4 MDCG_TENANT=A + B 的根 ⇒ 拒绝（既有口径保持）",
          err4 is not None, "err=%r" % ((err4 or "")[:70],))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
