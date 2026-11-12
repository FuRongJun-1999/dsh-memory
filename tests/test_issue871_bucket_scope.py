# -*- coding: utf-8 -*-
"""守卫 · issue #871 条件桶检索面（三处断点）。

三处断点（issue 实证）：
  ① `_path_bucket` 只做精确键路由 ⇒ 措辞一变即 0 命中；
  ② `scopeselect.terms()` 只按标点切 ⇒ 中文整串不在桶 bag（bm25 口径）里 ⇒ score_buckets 恒空；
  ③ `bucketscope` 只消费 kind=='day' ⇒ 桶范围被丢弃。

守卫取向：合成库（同类节点落同一 cond_* 桶）+ 真实 build/recall，只断言公开面（命中数与 meta.paths）。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import bucketindex as bi  # noqa: E402
from md_cg import scopeselect as ss  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def _mk():
    g = MdCGOS(tempfile.mkdtemp(prefix="i871_"), actor="test")
    for i in range(6):
        g.add("q%d" % i, "桩基承载力计算书第%d版，桩基与风险清单相关记录" % i,
              tags=["domain:桩基与风险清单"], consistency=False)
    for i in range(20):
        g.add("n%d" % i, "今天天气一般的记录第%d条" % i,
              tags=["domain:杂项"], consistency=False)
    bi.build(g, write=True, with_content=True)
    return g


def main():
    print("=" * 70)
    print("issue #871：条件桶检索面")
    print("=" * 70)

    # 断点 ②：中文 2/3-gram
    toks = ss.terms("桩基承载力")
    ok("桩基承载力" in toks, "B1 保留整串（精确命中优先）", toks)
    ok("桩基" in toks and "承载" in toks, "B2 追加汉字 2-gram", toks)
    ok("桩基承" in toks and "承载力" in toks, "B3 追加汉字 3-gram", toks)

    g = _mk()
    entries = list(g.index["nodes"].values())

    # 断点 ①：精确键 / 近义回落
    exact = g._path_bucket("桩基承载力", entries, {"observation_position": "桩基与风险清单"})
    ok(len(exact) >= 6, "B4 精确键路由仍命中（不回归）", len(exact))
    near = g._path_bucket("桩基承载力", entries, {"observation_position": "桩基与基础"})
    ok(len(near) >= 6, "B5 近义 context 回落命中（修前 0）", len(near))
    via_tags = g._path_bucket("桩基承载力", entries, {"tags": ["domain:桩基与基础"]})
    ok(len(via_tags) >= 6, "B6 tags 近义同样回落命中", len(via_tags))

    # 断点 ③：端到端 recall 的 bucket 路径非 0
    out = g.recall("桩基承载力", budget_tokens=3000, k=20,
                    context={"observation_position": "桩基与基础"})
    paths = (out.get("meta") or {}).get("paths") or {}
    ok(paths.get("bucket", 0) > 0, "B7 recall 的 bucket 路径非 0（修前恒 0）", paths)
    ids = [e.get("id") for e in (out.get("pack") or [])]
    ok(any(str(i).startswith("q") for i in ids), "B8 同域节点进 pack", ids[:6])

    # 无域信号仍弃权（既有不变量：不能把 orphan 当桶硬过滤）
    none_sig = g._path_bucket("桩基承载力", entries, {"role": "user"})
    ok(none_sig == [], "B9 无域信号仍弃权（不回归原不变量）", len(none_sig))

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())