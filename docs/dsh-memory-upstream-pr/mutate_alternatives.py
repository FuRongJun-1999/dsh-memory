# -*- coding: utf-8 -*-
"""定点变异：证明 `test_alternatives_historical` 的断言**有牙**（改坏必红）。

每个变异都：①原地改 md_cg/state_slots.py ②跑守卫 ③断言守卫变红
④还原并校验 sha256 逐字节一致。任一变异没被抓到 ⇒ 该断言无牙。
"""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(os.path.dirname(HERE))
TARGET = os.path.join(PKG, "md_cg", "state_slots.py")
GUARD = "md_cg.test_alternatives_historical"

MUTANTS = [
    ("M1 当前值也算进备择（去掉 v == value 过滤）",
     '        if v == value:\n            continue\n',
     ''),
    ("M2 撤回值不再进备择（跳过 void）",
     '        if _is_void(rec):\n            continue\n',
     ''),
    ("M3 不去重（同一值重复出现）",
     '        if v not in out:\n            out.append(v)\n',
     '        out.append(v)\n'),
    ("M4 快速路径不标注 partial（假装完整）",
     '                    "alternatives": [], "alternatives_partial": True,\n',
     '                    "alternatives": [],\n'),
    ("M5 完整路径也用空列表（回退到改前行为）",
     '            "alternatives": _alternatives_of(recs, value),\n',
     '            "alternatives": [],\n'),
    ("M6 顺带把 blindspots 也填了（越界改另一个字段）",
     '            "blindspots": [],\n',
     '            "blindspots": _alternatives_of(recs, value),\n'),
    ("M7 _project 不按 history 路由（两入口口径分叉）",
     '    if not history:\n        return _project_current_page(recs, include_retired=include_retired)[1]\n',
     ''),
    ("M8 去重改回 set（遇 dict 值崩溃）",
     '        if v not in out:\n            out.append(v)\n',
     '        if v not in set(map(repr, out)):\n            out.append(v)\n'),
]


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_guard():
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", GUARD],
                       cwd=PKG, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    orig = io.open(TARGET, encoding="utf-8").read()
    base_hash = sha(TARGET)

    rc0, _ = run_guard()
    print("基线 rc=%d（须为 0）" % rc0)
    if rc0 != 0:
        print("!! 基线不绿，先修基线再谈变异")
        return 2

    caught, missed = [], []
    for i, (name, old, new) in enumerate(MUTANTS, 1):
        if old not in orig:
            print("  SKIP %s —— 锚点未命中（源码已变，须同步变异）" % name)
            missed.append(name)
            continue
        try:
            io.open(TARGET, "w", encoding="utf-8", newline="\n").write(
                orig.replace(old, new, 1))
            rc, out = run_guard()
            if rc != 0:
                caught.append(name)
                fails = [l.strip() for l in out.splitlines() if l.strip().startswith("FAIL")]
                print("  CAUGHT %s  rc=%d  %s" % (name, rc, fails[:2]))
            else:
                missed.append(name)
                print("  MISSED %s  rc=0（断言无牙！）" % name)
        finally:
            io.open(TARGET, "w", encoding="utf-8", newline="\n").write(orig)

    # 还原校验
    restored = sha(TARGET) == base_hash
    print("\n还原 sha256 逐字节一致: %s" % restored)
    print("变异捕获: %d/%d" % (len(caught), len(MUTANTS)))
    if not restored:
        print("!! 还原失败，源码可能被污染")
        return 3
    if missed:
        for m in missed:
            print("  MISSED:", m)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
