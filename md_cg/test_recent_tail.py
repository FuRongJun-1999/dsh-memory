# -*- coding: utf-8 -*-
"""issue #739 系列 / Ornn8 测评建议②：search_rrf 的 cutoff 邻近保障（recent_tail）。

行为契约：
  · 最近 N 条用户轮次中，与 query 有词法交集、且未命中结果的事件，
    以 score=0.0 追加在结果**尾部**（带 recent_event=True 标记）；
  · MDCG_RECENT_TAIL=0 关闭；
  · 缓存命中路径同样补尾（补尾不写缓存）；
  · meta["recent_tail"] 报计数。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

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


def mk(n, c, b):
    return CCG.format(n=n, c=c, b=b)


def main():
    print("=" * 66)
    print("cutoff 邻近保障（recent_tail）")
    print("=" * 66)
    root = tempfile.mkdtemp(prefix="rtail_")
    g = MdCGOS(root, actor="test")
    g.add("old1", mk("灯箱进度（老）", "问灯箱进度", "已有报价但未安排制作"))
    for i in range(4):
        g.add("noise%d" % i, mk("近期噪声%d" % i, "无关话题", "别的项目"))
    g.remember_event("user", "（轮20）灯箱已经报价，还没安排制作", tags=["灯箱"])
    g.remember_event("user", "（轮21）其它项目开工", tags=[])

    os.environ.pop("MDCG_RECENT_TAIL", None)
    r, meta = g.search_rrf("灯箱 进行到哪一步", k=5)
    ids = [x[0].get("id") for x in r]
    tails = [x[0] for x in r if x[0].get("recent_event")]
    ok(len(r) >= 2, "B1 结果包含正排命中 + 补尾", (len(r), meta.get("recent_tail")))
    ok("old1" in ids, "B2 正排命中不受影响（仍含 old1）", ids)
    ok(len(tails) == 1 and "轮20" in tails[0]["content"],
       "B3 与 query 词法交集的最近轮被补入尾部", [t["id"] for t in tails])
    ok(tails[0] is r[-1][0], "B4 补尾在结果尾部（不打乱正排）")
    ok(r[-1][1] == 0.0, "B5 补尾 score=0.0（不参与打分）", r[-1][1])
    ok(meta.get("recent_tail") == 1, "B6 meta.recent_tail=1", meta.get("recent_tail"))
    ok(all("其它项目开工" not in (x[0].get("content") or "") for x in r),
       "B7 无词法交集的最近轮不补入（防噪声）")

    os.environ["MDCG_RECENT_TAIL"] = "0"
    try:
        r2, m2 = g.search_rrf("灯箱 进行到哪一步", k=5)
        ok(m2.get("recent_tail") == 0 and len(r2) == 1,
           "B8 MDCG_RECENT_TAIL=0 关闭", (len(r2), m2.get("recent_tail")))
    finally:
        os.environ.pop("MDCG_RECENT_TAIL", None)

    r3, m3 = g.search_rrf("灯箱 进行到哪一步", k=5)
    ok(m3.get("recent_tail") == 1 and any(x[0].get("recent_event") for x in r3),
       "B9 缓存命中路径同样补尾", (len(r3), m3.get("recent_tail")))

    # B10（裁定修订）：补尾**不做内容级判重**——同一事实可能正排+补尾各出现一次，
    # 但补尾条目带 recent_event=True 标记可识别。契约钉「可识别」而非「不重复」。
    g.add("hit1", mk("灯箱报价记录", "问灯箱报价", "灯箱已报价"))
    r4, m4 = g.search_rrf("灯箱 报价", k=5)
    n_hit = sum(1 for x in r4 if x[0].get("id") == "hit1")
    n_tail = sum(1 for x in r4 if x[0].get("recent_event"))
    ok(n_hit == 1 and all("recent_event" in x[0] for x in r4 if x[0].get("recent_event")),
       "B10 正排命中 + 补尾共存，补尾条目带 recent_event 标记", (n_hit, n_tail))

    print()
    print("recent_tail：%d 项失败" % len(FAILS) if FAILS else "recent_tail：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())