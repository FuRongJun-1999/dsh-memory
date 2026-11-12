# -*- coding: utf-8 -*-
"""结构信号重排（structboost）守卫。

钉五件事：
  1. 章节解析（中文数字/阿拉伯数字）；
  2. 章号来源优先级：正文标题 > ch:N 盖章 tag；
  3. **信息不足闸**：候选集里知道章号的比例 < CHAPTER_MIN_KNOWN ⇒ 章节信号整条弃用；
  4. 确定性：同输入两次结果逐位相同；
  5. 缺省关：env 未设时 search_rrf 不改任何顺序。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import structboost as sb  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:180])
        FAILS.append(name)


def node(nid, content, tags=None):
    return {"id": nid, "content": content, "frontmatter": {"tags": tags or []}}


def main():
    print("=" * 66)
    print("结构信号重排（structboost）")
    print("=" * 66)
    ok(sb.cn2int("三") == 3 and sb.cn2int("十二") == 12 and sb.cn2int("21") == 21,
       "S1 章号解析（中文/阿拉伯）", (sb.cn2int("三"), sb.cn2int("十二"), sb.cn2int("21")))
    ok(sb.query_chapter("第2章「巧合还是阴谋」·陈默") == 2, "S2 题面取章号")

    with_head = node("a", "## 第三章 身份谜团\n正文" + "x" * 50)
    with_tag = node("b", "没有标题的块" + "y" * 50, tags=["ch:5"])
    ok(sb.node_chapter(with_head) == 3, "S3a 正文标题优先", sb.node_chapter(with_head))
    ok(sb.node_chapter(with_tag) == 5, "S3b ch:N 盖章 tag 可识别", sb.node_chapter(with_tag))
    ok(sb.node_chapter(node("c", "无任何章信息")) is None, "S3c 无章号返回 None")

    # 信息不足闸：10 个候选里只有 1 个知道章号 ⇒ 章节信号弃用。
    # 夹具要「独苗分数低于他人」才有区分度：若闸失灵，×2 提升会把独苗顶到第一。
    few = [(node("h", "## 第二章 x\n" + "z" * 60), 0.30, {}, [])]
    few += [(node("n%d" % i, "无关" + "w" * 60), 0.40, {}, []) for i in range(9)]
    out_few = sb.rerank(few, "第2章 某陈述")
    ok(out_few[0][0]["id"] != "h",
       "S4 信息不足闸：章节信号整条弃用（低分独苗不被顶到第一）",
       [x[0]["id"] for x in out_few[:3]])

    # 确定性命中：章号齐备时，同章候选被提升
    many = [(node("g", "## 第二章 y\n" + "k" * 60), 0.3, {}, [])]
    many += [(node("m%d" % i, "## 第一章 z\n" + "k" * 60), 0.4, {}, []) for i in range(3)]
    ranked = sb.rerank(many, "第2章 陈述")
    ok(ranked[0][0]["id"] == "g", "S5 章号齐备时同章候选被提升", [x[0]["id"] for x in ranked])

    again = sb.rerank(many, "第2章 陈述")
    ok([x[0]["id"] for x in ranked] == [x[0]["id"] for x in again], "S6 确定性（同输入同输出）")

    # S7 缺省关：env 未设时 search_rrf 顺序不变
    os.environ.pop("MDCG_STRUCT_BOOST", None)
    os.environ["MDCG_RECENT_TAIL"] = "0"
    os.environ["MDCG_TOPIC_AGG"] = "0"
    g = MdCGOS(tempfile.mkdtemp(prefix="sbg_"), actor="test")
    ccg = ("# 功能名：{n}\n# 生效条件：语料\n# 子功能：s\n# 执行：e\n"
           "# 验证方式：bench\n# 不适用条件：无\n\n{body}\n")
    g.add("c1", ccg.format(n="第一章块", s="w", e="1", body="## 第一章 开端\n话题甲 内容"),
          tags=["ch:1"])
    g.add("c2", ccg.format(n="第二章块", s="w", e="2", body="## 第二章 发展\n话题甲 内容"),
          tags=["ch:2"])
    res0, meta0 = g.search_rrf("话题甲", k=5)
    ok(meta0.get("struct_boost") is False, "S7a 缺省关（meta.struct_boost=False）",
       meta0.get("struct_boost"))
    os.environ["MDCG_STRUCT_BOOST"] = "1"
    try:
        res1, meta1 = g.search_rrf("第2章 话题甲", k=5)
        ok(meta1.get("struct_boost") is True, "S7b 开启后 meta.struct_boost=True")
        ok(len(res1) <= 5, "S7c 对外仍只回 k 条（超取→重排→截断）", len(res1))
    finally:
        os.environ.pop("MDCG_STRUCT_BOOST", None)
        os.environ.pop("MDCG_RECENT_TAIL", None)
        os.environ.pop("MDCG_TOPIC_AGG", None)

    print()
    print("structboost：%d 项失败" % len(FAILS) if FAILS else "structboost：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())