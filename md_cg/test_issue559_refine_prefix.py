# -*- coding: utf-8 -*-
r"""test_issue559_refine_prefix · maintain refine 的默认 id 前缀与实际 id 不自洽（issue #559）。

缺陷现场：`md_cg/refine.py:42` 的 `PREFIX_DEFAULT = "node_"`，而本仓默认铸出的 id 前缀是 `mem_`
（`mdcg.py:1708` 的 `<prefix><毫秒>_<hex>`），于是**默认参数下抽样池恒为 0**，且不报错——静默空池。

本守卫钉两件事：
  ① 默认前缀（不传 prefix）在 `mem_*` 节点库上必须抽到非空池（不得静默空）；
  ② 显式传入不匹配的前缀时，**不得**偷偷回落（保持调用方语义），且 meta 里 `prefix_fallback` 为假。
"""
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from md_cg import mdcg as M  # noqa: E402
from md_cg import refine as R  # noqa: E402

PASS = 0
FAIL = 0
FAILS = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


root = tempfile.mkdtemp(prefix="issue559_")
try:
    cg = M.MdCG(root)
    for i in range(4):
        cg.add("x%d" % i, "内容 %d" % i, layer="knowledge")
    ids = list(((cg.index or {}).get("nodes") or {}).keys())
    check("前置：库内有 4 个非受保护节点", len(ids) == 4, str(ids[:2]))

    pool, meta = R.sample_ids(cg, n=2)
    check("① 默认参数（不传 prefix）池非空",
          len(pool) > 0, "pool=%d meta=%s" % (len(pool), {k: meta.get(k) for k in ("prefix", "prefix_fallback")}))
    check("① 默认前缀已与默认 id 前缀一致",
          R.PREFIX_DEFAULT == "mem_", "PREFIX_DEFAULT=%r" % R.PREFIX_DEFAULT)

    pool2, meta2 = R.sample_ids(cg, n=2, prefix="node_")
    check("② 显式不匹配前缀不偷偷回落（池空且 fallback=False）",
          len(pool2) == 0 and not meta2.get("prefix_fallback"),
          "pool=%d fallback=%s" % (len(pool2), meta2.get("prefix_fallback")))
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("=" * 64)
print("通过 %d ／ 失败 %d" % (PASS, FAIL))
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  - " + f)
print("=" * 64)
sys.exit(0 if FAIL == 0 else 1)