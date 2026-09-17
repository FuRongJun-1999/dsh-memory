# -*- coding: utf-8 -*-
"""units 复核通道口径验收（候选新增测试；按互验设计 §7.6，本轮不参与判据面）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile

from . import units

_ok = 0
_bad = []


def _check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


def _mk_job(root, job_id, payload):
    d = os.path.join(root, job_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"job_id": job_id, "state": "done", "model": "stub"}, f,
                  ensure_ascii=False)
    return d


def main():
    print("=" * 68)
    print("md_cg units 复核通道口径验收")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="mdcg_units_poll_")
    _check("DEFAULT_MAX_TOKENS 对齐统一默认 200000（文档口径）",
           units.DEFAULT_MAX_TOKENS == 200000, str(units.DEFAULT_MAX_TOKENS))
    _mk_job(tmp, "j_empty", {"ok": True, "content": "",
                             "usage": {"completion_tokens": 2048,
                                       "completion_tokens_details": {"reasoning_tokens": 2048}}})
    r1 = units.poll("j_empty", jobs=tmp)
    _check("poll：空正文不报成功（防假死锁）", r1.get("ok") is False, repr(r1.get("ok")))
    _check("poll：空正文给出可归因错误（指向预算）",
           "空正文" in str(r1.get("error") or ""), str(r1.get("error"))[:90])
    _check("poll：终态仍被识别", r1.get("terminal") is True)
    _mk_job(tmp, "j_good", {"ok": True, "content": "verdict: ACCEPT"})
    r2 = units.poll("j_good", jobs=tmp)
    _check("poll：正常正文仍报成功且正文保留",
           r2.get("ok") is True and r2.get("content") == "verdict: ACCEPT", repr(r2)[:80])
    _mk_job(tmp, "j_fail", {"ok": False, "error": "boom"})
    r3 = units.poll("j_fail", jobs=tmp)
    _check("poll：显式失败原样透出", r3.get("ok") is False and r3.get("error") == "boom")
    chain = units.plan()["chain"]
    _check("plan：第 1 序声明承认「调用方显式传 model」路径",
           "显式传 model" in str(chain[0].get("when") or ""),
           str(chain[0].get("when"))[:100])
    print()
    print("PASS %d / FAIL %d" % (_ok, len(_bad)))
    for b in _bad:
        print("  - " + b)
    return 1 if _bad else 0


if __name__ == "__main__":
    sys.exit(main())
