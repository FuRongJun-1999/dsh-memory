# -*- coding: utf-8 -*-
"""守卫 · recall 的 bm25 路取用判据（issue #999）。

判据是**脚本自适应**而不是全局翻开关：英文查询走 bm25（LongMemEval-S 419 题实测
R@5 0.4916→0.8234），含汉字的查询继续走 lexical（CJK 探针实测 lexical 100%/99.2%，
bm25 只有 89.2%/92.5%——bm25 把「连续汉字」当一个 token，不做中文分词）。

  N1 纯英文查询 + flag=None  → bm25
  N2 中文查询 + flag=None    → lexical（不许让分档默认把中文库打死）
  N3 中英混排 + flag=None    → lexical（含汉字即算中文，子串匹配更稳）
  N4 flag=True 强制 bm25（即使查询是中文）
  N5 flag=False 强制 lexical（即使查询是英文）
  N6 无 search_rrf → 恒 lexical（回退面必须还能召回到东西）
  N7 调用点**单点化**：源码里只有一处 recall_use_bm25(...)，且旧写法已消失
  N8 bm25 空召回时的 lexical 兜底仍在（且只在「自适应」这一档生效）

运行：python -m md_cg.test_recall_bm25_auto
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import mcp_server as MS

PASSED, FAILED = [], []


def ok(cond, name, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  " + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    ok(MS.recall_use_bm25("what did I say about the blue screen", None) is True,
       "N1 纯英文 + 缺省 → bm25")
    ok(MS.recall_use_bm25("电脑蓝屏了怎么办", None) is False,
       "N2 中文 + 缺省 → lexical")
    ok(MS.recall_use_bm25("mixed 混合 query 蓝屏", None) is False,
       "N3 中英混排 → lexical")
    ok(MS.recall_use_bm25("电脑蓝屏了", True) is True,
       "N4 flag=True 强制 bm25")
    ok(MS.recall_use_bm25("blue screen", False) is False,
       "N5 flag=False 强制 lexical")
    ok(MS.recall_use_bm25("blue screen", None, has_rrf=False) is False,
       "N6 无 search_rrf → lexical")
    ok(MS.recall_use_bm25("", None) is False and MS.recall_use_bm25(None, None) is False,
       "N6b 空查询 → lexical（不白建索引）")

    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "mcp_server.py"), encoding="utf-8").read()
    ok(src.count("use_bm25 = recall_use_bm25(") == 1,
       "N7a 调用点单点化（恰好一处）", src.count("use_bm25 = recall_use_bm25("))
    ok('bool(a.get("bm25")) and hasattr' not in src,
       "N7b 旧的 opt-in 写法已消失")
    ok('_pack.setdefault("meta", {})["bm25_fallback"] = "lexical"' in src,
       "N8a bm25 空召回的 lexical 兜底在")
    ok('use_bm25 and a.get("bm25") is None' in src,
       "N8b 兜底只在自适应档生效（显式 true/false 不改道）")

    print("bm25 取用判据守卫：%d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())