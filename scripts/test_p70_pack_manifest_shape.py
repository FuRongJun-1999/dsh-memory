# -*- coding: utf-8 -*-
"""守卫 · npm pack 清单形态识别（issue #70，2026-10-09 DSH 端修复随附）。

修前：extract_pack_manifest 只认「数组」与「含顶层 files 的单对象」两种形态；
npm 12 的 npm pack --json 产出**包名键控对象** {"<包名>": [ {...}, ... ]} ⇒ 形态闸
不认 ⇒ 判无候选 ⇒ check_publish_artifact 恒以环境错误退出（exit=2）。

修后：新增 _is_named_pack_object / _normalize_pack_manifest，把该形态纳入识别并在
extract_pack_manifest 返回前**摊平为条目数组**（下游 _manifest_paths 无需改）。

判据：
  G1 老版**数组**形态仍被识别（回归）
  G2 老版**单对象**形态仍被识别（回归）
  G3 **npm 12 包名键控对象**被识别，且归一后为 list、条目数与 files 正确
  G4 诱饵不被误认：只有 {"path": ...}（无 size/mode）的伪清单不算**全形态**
  G5 形状闸不误伤：普通对象（如 {"a": 1}）不得被当成清单
运行：python -X utf8 -m scripts.test_p70_pack_manifest_shape
      （cwd 须为仓根；亦可直接 python scripts/test_p70_pack_manifest_shape.py）
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for p in (REPO,):
    if p not in sys.path:
        sys.path.insert(0, p)

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


def _entry(pkg="x", n=2):
    return {"name": pkg, "version": "1.0.0", "size": 10, "unpackedSize": 20,
            "files": [{"path": "a.js", "size": 1, "mode": 420},
                      {"path": "b.md", "size": 2, "mode": 420}][:n]}


def main():
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import importlib
    mod = importlib.import_module("check_publish_artifact")
    ex = mod.extract_pack_manifest

    # G1 老版数组
    old_arr = json.dumps([_entry()])
    m1, meta1 = ex(old_arr)
    check("G1 老版数组形态仍被识别（回归）",
          isinstance(m1, list) and len(m1) == 1, "manifest=%r" % (m1,))

    # G2 老版单对象
    old_obj = json.dumps(_entry())
    m2, meta2 = ex(old_obj)
    check("G2 老版单对象形态仍被识别（回归）",
          isinstance(m2, dict) and isinstance(m2.get("files"), list), "manifest=%r" % (m2,))

    # G3 npm 12 包名键控对象
    named = json.dumps({"my-pkg": [_entry("my-pkg")]})
    m3, meta3 = ex(named)
    flat = isinstance(m3, list) and len(m3) == 1 and isinstance(m3[0].get("files"), list)
    check("G3 npm 12 包名键控对象被识别且摊平为 list", flat, "manifest=%r" % (m3,))
    check("G3b 摊平后 files 条数正确（2 条）",
          flat and len(m3[0]["files"]) == 2, "")

    # G4 诱饵（只有 path、无 size/mode）不算全形态
    decoy = json.dumps([{"files": [{"path": "a.js"}]}])
    m4, meta4 = ex(decoy)
    check("G4 无 size/mode 的伪清单不被判为全形态",
          meta4.get("shape_rank") == "shape", "shape_rank=%r" % (meta4.get("shape_rank"),))

    # G5 普通对象不被误认
    check("G5 普通对象不被当成清单",
          ex(json.dumps({"a": 1}))[0] is None, "")

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
