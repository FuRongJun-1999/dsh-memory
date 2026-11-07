# -*- coding: utf-8 -*-
"""读取策略改造 · A 项守卫：跨轮状态聚合（topicagg）。

契约：同话题命中 >=2 条才成组；组内按时间正序；state 只读既有 metadata
（不自造，issue #111 同纪律）；MDCG_TOPIC_AGG=0 关闭；聚合不改 pack 顺序。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import topicagg  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []
CCG = ("# 功能名：{n}\n# 生效条件：{c}\n# 子功能：s\n# 执行：e\n"
       "# 验证方式：test\n# 不适用条件：无\n\n{b}\n")


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def entry(eid, tags, t, state=None, label=None):
    return {"id": eid,
            "frontmatter": {"tags": tags, "created_at": t},
            "metadata": {"state": state},
            "content": "# 功能名：" + (label or eid) + "\n# 生效条件：x\n"}


def main():
    print("=" * 66)
    print("跨轮状态聚合（topicagg）")
    print("=" * 66)
    pack = [entry("a9", ["灯箱"], 100.0, "ACCEPT", "灯箱进度（轮9）"),
            entry("a20", ["灯箱"], 200.0, "ACCEPT", "灯箱进度（轮20）"),
            entry("b1", ["其它"], 150.0, None, "无关"),
            entry("c1", [], 120.0, None, "无标签")]
    ag = topicagg.aggregate(pack, "灯箱 进行到哪一步")
    ok(len(ag) == 1, "A1 只有一个话题成组", [g["topic"] for g in ag])
    ok(ag and ag[0]["topic"] == "灯箱" and ag[0]["count"] == 2,
       "A2 组名/成员数正确", ag[0] if ag else None)
    ok(ag and ag[0]["ids"] == ["a9", "a20"], "A3 ids 按时间正序",
       ag[0]["ids"] if ag else None)
    ok(ag and ag[0]["timeline"][0]["label"] == "灯箱进度（轮9）",
       "A4 label 只取功能名行", ag[0]["timeline"][0] if ag else None)
    ok(ag and ag[0]["timeline"][0]["state"] == "ACCEPT",
       "A5 state 只读既有 metadata", ag[0]["timeline"][0] if ag else None)
    ok(topicagg.aggregate([entry("x", ["灯箱"], 1.0)], "灯箱") == [],
       "A6 单条不成组")
    ok(topicagg.aggregate([], "灯箱") == [], "A7 空输入不炸")

    root = tempfile.mkdtemp(prefix="tagg_")
    g = MdCGOS(root, actor="test")
    g.add("lamp9", CCG.format(n="灯箱进度（轮9）", c="灯箱 进度", b="已有报价"), tags=["灯箱"])
    g.add("lamp20", CCG.format(n="灯箱进度（轮20）", c="灯箱 进度", b="仍未安排制作"), tags=["灯箱"])
    pack2 = g.recall("灯箱 进行到哪一步", budget_tokens=2000, k=10)
    ag2 = pack2.get("aggregates") or []
    ok(len(ag2) == 1 and ag2[0]["count"] == 2,
       "A8 recall 端到端产出聚合组（轮9+轮20）", ag2)

    os.environ["MDCG_TOPIC_AGG"] = "0"
    try:
        pack3 = g.recall("灯箱 进行到哪一步", budget_tokens=2000, k=10)
        ok(pack3.get("aggregates") == [], "A9 MDCG_TOPIC_AGG=0 关闭")
    finally:
        os.environ.pop("MDCG_TOPIC_AGG", None)

    p4 = g.recall("灯箱 进行到哪一步", budget_tokens=2000, k=10)
    ok([e["id"] for e in p4["pack"]] == [e["id"] for e in pack2["pack"]],
       "A10 聚合不改 pack 顺序（纯后处理）")

    print()
    print("topicagg：%d 项失败" % len(FAILS) if FAILS else "topicagg：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())