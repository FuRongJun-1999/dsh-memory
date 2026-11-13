#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建繁简折叠表（issue #607 的第 1 件：真实映射表）。

真源：OpenCC `data/dictionary/TSCharacters.txt`（Apache-2.0），已原样 vendored 到
`md_cg/data/opencc/TSCharacters.txt`，来源/许可/哈希记在同目录 `PROVENANCE.json`。

四件齐备的落地口径（issue #607）：
  ① 真实表：OpenCC 官方字典，不是示意表；
  ② 许可：Apache-2.0（表头自带声明），来源 URL + sha256 可追溯；
  ③ 覆盖声明：本脚本把「总行数 / 单目标 / 多目标跳过 / 多字符键跳过」逐项写进产物
     `coverage` 字段——哪些进表、哪些明确不进，可复核；
  ④ 反向腿：**不生成** 简→繁 猜测表。折叠只在表命中时发生，未覆盖字符原样返回
     （`fold` 的含义就是「已知的繁→简」，没有表就没有折叠，不去猜）。

用法：python -X utf8 scripts/build_trad_to_simp.py --write
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "md_cg", "data", "opencc", "TSCharacters.txt")
OUT = os.path.join(ROOT, "md_cg", "data", "trad_to_simp.json")


def build():
    raw = io.open(SRC, encoding="utf-8").read()
    rows = [ln for ln in raw.splitlines() if ln and not ln.startswith("#")]
    table = {}
    multi_char_keys = []
    ambiguous = []
    for ln in rows:
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        key = parts[0].strip()
        vals = [v for v in parts[1].strip().split(" ") if v]
        if len(vals) != 1:
            ambiguous.append({"key": key, "targets": vals})
            continue
        if len(key) != 1 or len(vals[0]) != 1:
            multi_char_keys.append({"key": key, "target": vals[0]})
            continue
        table[key] = vals[0]
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    out = {
        "schema": 1,
        "source": "OpenCC TSCharacters.txt",
        "license": "Apache-2.0",
        "source_sha256": sha,
        "rows_total": len(rows),
        "table_size": len(table),
        "coverage": {
            "included": "单字符键 + 单目标（1:1）",
            "excluded_ambiguous": len(ambiguous),
            "excluded_multi_char": len(multi_char_keys),
            "excluded_examples": {
                "ambiguous": ambiguous[:5],
                "multi_char": multi_char_keys[:5],
            },
            "reverse_leg": "不生成 简→繁 猜测表：未覆盖字符原样返回（不猜）",
        },
        "table": table,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    out = build()
    print(json.dumps({k: v for k, v in out.items() if k != "table"},
                     ensure_ascii=False, indent=2))
    if a.write:
        io.open(OUT, "w", encoding="utf-8", newline="").write(
            json.dumps(out, ensure_ascii=False, indent=1) + "\n")
        print("已写：" + os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())