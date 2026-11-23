# -*- coding: utf-8 -*-
"""BM25 默认开 + 能力降级守卫。

B1 前提：search_rrf 只存在于 MdCGOS/MdCGSecure，纯 MdCG 没有（guard 的由来）
B2 检索面：mdcg_search 未传 bm25 时走 BM25 路且不报错（MdCGSecure 上）
B3 降级：cg 无 search_rrf 时不得抛 AttributeError（用最小伪造对象验证同一判据表达式）
B4 recall 面按**查询脚本**取路（issue #999）：未显式传 bm25 时判据单点
   `recall_use_bm25` 决定走哪条词法路，中文查询仍落到缺省六路且不崩
"""
from __future__ import annotations

import tempfile

from .mdcg import MdCG
from .mdcos import MdCGSecure, MdCGOS
from .mcp_server import call_tool


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

    chk(hasattr(MdCGOS, "search_rrf") and hasattr(MdCGSecure, "search_rrf"), "B1 MdCGOS/MdCGSecure 有 search_rrf")
    chk(not hasattr(MdCG, "search_rrf"), "B1b 纯 MdCG 没有 search_rrf（guard 前提成立）")

    class NoRrf:
        def search(self, *a, **kw):
            return ([], {})

    fake = NoRrf()
    chk(not hasattr(fake, "search_rrf"), "B3 无该能力的对象可被 hasattr 判出（表达式不抛错）")

    root = tempfile.mkdtemp(prefix="bm25_def_")
    cg = MdCGSecure(root)
    cg.add("m1", "生产环境 连接池 32 个", layer="knowledge")
    out = call_tool(cg, "mdcg_search", {"query": "连接池", "k": 5})
    chk(isinstance(out, dict) and "results" in out, "B2 mdcg_search 缺省（BM25 开）可正常返回")

    out2 = call_tool(cg, "mdcg_recall", {"query": "连接池", "k": 5})
    chk(isinstance(out2, (dict, list)), "B4 mdcg_recall 缺省仍可用（取路判据=查询脚本，中文走 lexical）")
    # B4b：同一判据在英文查询上确实选了 bm25——否则「脚本自适应」只是一句空话。
    from .mcp_server import recall_use_bm25
    chk(recall_use_bm25("blue screen while installing", None) is True
        and recall_use_bm25("连接池 32 个", None) is False,
        "B4b 判据分语言：英文→bm25，中文→lexical")

    print("=" * 60)
    print("BM25 默认开守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
