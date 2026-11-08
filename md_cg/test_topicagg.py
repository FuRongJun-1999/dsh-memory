# -*- coding: utf-8 -*-
"""读取策略改造 · A 项守卫：跨轮状态聚合（topicagg）。

契约：同话题命中 >=2 条才成组；组内按时间正序；state 只读既有 metadata
（不自造，issue #111 同纪律）；MDCG_TOPIC_AGG=0 关闭；聚合不改 pack 顺序。
"""
from __future__ import annotations

import json
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
    # A8 的口径在**加入跨轮闸**后变严：`add()` 连续两次写入几乎同一时刻，
    # 时间跨度 < MIN_SPAN_SECONDS ⇒ 判为「同一批材料」不成组（这正是闸的目的）。
    # 端到端的「成组」用例由 F5 用拉开的时间戳覆盖；此处只钉**接线**：
    # aggregates 键必须存在（列表），且同批写入不产出假组。
    ok("aggregates" in pack2 and isinstance(ag2, list),
       "A8 recall 端到端接通 aggregates 键（列表）", type(ag2).__name__)
    ok(ag2 == [], "A8b 同批写入（跨度 < 30s）不产出假组", ag2)

    os.environ["MDCG_TOPIC_AGG"] = "0"
    try:
        pack3 = g.recall("灯箱 进行到哪一步", budget_tokens=2000, k=10)
        ok(pack3.get("aggregates") == [], "A9 MDCG_TOPIC_AGG=0 关闭")
    finally:
        os.environ.pop("MDCG_TOPIC_AGG", None)

    p4 = g.recall("灯箱 进行到哪一步", budget_tokens=2000, k=10)
    ok([e["id"] for e in p4["pack"]] == [e["id"] for e in pack2["pack"]],
       "A10 聚合不改 pack 顺序（纯后处理）")

    # ---------- 兜底与闸（F 组）：bench 读数驱动，缺省关 ----------
    def entry_t(eid, content, t, tags=None):
        return {"id": eid, "frontmatter": {"tags": tags or [], "created_at": t},
                "metadata": {}, "content": "# 功能名：" + eid + "\n" + content}

    os.environ.pop("MDCG_TOPIC_AGG_TAGFALLBACK", None)
    try:
        p_untagged = [entry_t("x1", "灯箱 报价", 1000.0), entry_t("x2", "灯箱 制作", 2000.0)]
        ok(topicagg.aggregate(p_untagged, "灯箱") == [],
           "F1 缺省关：无 tag 时不聚合（行为不变）")

        os.environ["MDCG_TOPIC_AGG_TAGFALLBACK"] = "1"
        ag = topicagg.aggregate(p_untagged, "灯箱")
        ok(len(ag) == 1 and ag[0]["topic"] == "灯箱" and ag[0]["count"] == 2,
           "F2 开启兜底：正文命中话题词即成组", ag)

        p_generic = [entry_t("g1", "内容 甲乙", 1000.0), entry_t("g2", "内容 丙丁", 2000.0)]
        ok(topicagg.aggregate(p_generic, "内容") == [],
           "F3 泛词闸：停用词不作组名（防「泛词聚一切」）")

        p_short = [entry_t("s1", "灯箱 报价", 1000.0), entry_t("s2", "灯箱 制作", 1005.0)]
        ok(topicagg.aggregate(p_short, "灯箱") == [],
           "F4 跨轮闸：时间跨度 < 30s 不算跨轮")

        p_span = [entry_t("d1", "灯箱 报价", 1000.0), entry_t("d2", "灯箱 制作", 1300.0)]
        ok(len(topicagg.aggregate(p_span, "灯箱")) == 1,
           "F5 跨轮闸放行：跨度 >= 30s 正常成组")

        r1 = topicagg.aggregate(p_untagged, "灯箱")
        r2 = topicagg.aggregate(p_untagged, "灯箱")
        ok(json.dumps(r1, ensure_ascii=False) == json.dumps(r2, ensure_ascii=False),
           "F6 确定性：同输入两次结果相同")
    finally:
        os.environ.pop("MDCG_TOPIC_AGG_TAGFALLBACK", None)

    print()
    print("topicagg：%d 项失败" % len(FAILS) if FAILS else "topicagg：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())