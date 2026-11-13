# -*- coding: utf-8 -*-
"""守卫 · issue #607 繁简折叠表「四件齐备」。

重启条件（issue 原文）：① 真实映射表（不是示意表）② 许可来源 ③ 覆盖声明
④ 反向腿（表未覆盖时如实跳过，不按简体/繁体猜测）。四件缺一不动。

断言：
  T1 真实表已接上：trad_to_simp() 非空且规模量级合理（>2000 条）
  T2 许可可追溯：覆盖声明带 license=Apache-2.0 且源文件 sha256 与 PROVENANCE 一致
  T3 覆盖声明可复核：table_size + excluded_ambiguous + excluded_multi_char == rows_total
  T4 折叠生效：繁→简 在检索面真的折叠（fold_variants）
  T5 反向腿诚实：未收录字符**原样返回**（不猜）；歧义条目**不入表**
  T6 表缺失时诚实降级：空表、不抛错（行为与 #362c 时期一致）
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import routing  # noqa: E402

FAILS = []
DATA = os.path.join(ROOT, "md_cg", "data")


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 70)
    print("issue #607：繁简折叠表四件齐备")
    print("=" * 70)

    table = routing.trad_to_simp()
    ok(len(table) > 2000, "T1 真实表已接上（非示意表）", len(table))

    cov = routing.table_coverage()
    ok(cov.get("license") == "Apache-2.0", "T2 许可可追溯（Apache-2.0）", cov.get("license"))
    prov_p = os.path.join(DATA, "opencc", "PROVENANCE.json")
    prov = json.load(io.open(prov_p, encoding="utf-8"))
    raw = io.open(os.path.join(DATA, "opencc", "TSCharacters.txt"), "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    ok(prov.get("sha256") == sha == cov.get("source_sha256"),
       "T2b 源文件哈希与 PROVENANCE 一致", (prov.get("sha256", "")[:12], sha[:12]))

    c = cov.get("coverage") or {}
    total = cov.get("rows_total")
    ok(cov.get("table_size", 0) + c.get("excluded_ambiguous", 0)
       + c.get("excluded_multi_char", 0) == total,
       "T3 覆盖声明自洽（收+排除=总行数）",
       (cov.get("table_size"), c.get("excluded_ambiguous"), c.get("excluded_multi_char"), total))
    ok(bool(c.get("reverse_leg")), "T3b 覆盖声明写明反向腿口径", c.get("reverse_leg"))

    ok(routing.fold_variants("資訊與網絡") == "资讯与网络",
       "T4 检索面折叠生效（繁→简）", routing.fold_variants("資訊與網絡"))

    # T5 反向腿：未覆盖字符原样；歧义条目不入表
    unlisted = "\u9fa5\u9fa6"   # 两个不在表里的生僻字（表未覆盖就不动）
    ok(routing.fold_variants(unlisted) == unlisted,
       "T5 未覆盖字符原样返回（不猜）", routing.fold_variants(unlisted))
    amb = (c.get("excluded_examples") or {}).get("ambiguous") or []
    ok(all(a.get("key") not in table for a in amb),
       "T5b 歧义条目（多目标）不入表", amb[:2])

    # T6 表缺失 ⇒ 空表、不抛错
    old_path, old_loaded, old_table = routing._TABLE_PATH, routing._TABLE_LOADED, routing.TRAD_TO_SIMP
    try:
        routing._TABLE_PATH = os.path.join(DATA, "__no_such_table__.json")
        routing._TABLE_LOADED = False
        routing.TRAD_TO_SIMP = {}
        ok(routing.trad_to_simp() == {}, "T6 表缺失 ⇒ 空表（诚实降级、不抛错）",
           len(routing.trad_to_simp()))
        ok(routing.fold_variants("資訊") == "資訊", "T6b 无表时不做折叠（不猜）",
           routing.fold_variants("資訊"))
    finally:
        routing._TABLE_PATH, routing._TABLE_LOADED, routing.TRAD_TO_SIMP = old_path, old_loaded, old_table

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())