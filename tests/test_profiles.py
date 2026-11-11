# -*- coding: utf-8 -*-
"""资料树档 1 守卫：聚合卡必须**可召回**、**幂等**、**增量**。

使用者判据：人物·地点·时间·事件 = 核心状态；物品·情绪 = 辅助（只进 facet）。
归因前提：弱项 19 题「要素不在 pack」（2/19）⇒ 资料卡的价值是给单点事实造可召回容器。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import bucketindex as bi  # noqa: E402
from md_cg import profiles  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:180])
        FAILS.append(name)


def ts(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))


def main():
    print("=" * 70)
    print("资料树档 1：聚合卡（人物/地点/事件）")
    print("=" * 70)
    root = tempfile.mkdtemp(prefix="prof_")
    cg = MdCGOS(root, actor="test")
    cg.add("n1", "我叫沈知夏，知了的知，夏天的夏，24", created_at=ts("2026-04-26 10:00:00"),
           tags=["domain:diary"], consistency=False)
    cg.add("n2", "沈知夏在江北咖啡店做结构设计，24岁那年转的行",
           created_at=ts("2026-05-03 10:00:00"), tags=["domain:diary"], consistency=False)
    cg.add("n3", "和吴越说好了下周三在展馆门口碰面，带上那本画册",
           created_at=ts("2026-07-06 10:00:00"), tags=["domain:diary"], consistency=False)

    dry = profiles.build(cg, dry_run=True)
    ok(dry["cards"] >= 2, "P1 dry_run 能算出资料卡", dry)
    ok(dry["written"] == 0, "P2 dry_run 不落盘", dry)

    st = profiles.build(cg, dry_run=False)
    ok(st["written"] >= 2, "P3 落盘资料卡", st)

    pid = profiles.card_id("person", "沈知夏")
    card = cg.get(pid)
    ok(bool(card), "P4 人物卡存在且 id 可预测", pid)
    body = (card or {}).get("content") or ""
    ok("沈知夏" in body and "2026-04-26" in body, "P5 卡里带姓名与日期", body[:120])
    ok("24" in body, "P6 卡里带年龄事实")
    ok(body.count("来源") >= 2, "P7 每条事实带来源节点（可回溯）", body.count("来源"))

    plid = profiles.card_id("place", "江北咖啡店")
    ok(bool(cg.get(plid)), "P8 地点卡存在", plid)

    # 幂等：再跑一次不写
    again = profiles.build(cg, dry_run=False)
    ok(again["written"] == 0 and again["skipped"] >= 1, "P9 幂等：重跑不重写", again)

    # 辅助面只进 tags，不建树
    tags = (cg.get(pid) or {}).get("frontmatter", {}).get("tags") or []
    ok(any(str(t).startswith("profile") for t in tags), "P10 卡有自己的 profile 标签", tags[:6])
    ok(not any(str(t).startswith("obj:profile") for t in tags), "P11 未误建物品树")

    # 增量：新增一条事实 ⇒ 卡更新且旧事实仍在
    cg.add("n4", "沈知夏说她下个月要换工作，还在江北那边",
           created_at=ts("2026-08-01 10:00:00"), tags=["domain:diary"], consistency=False)
    inc = profiles.build(cg, dry_run=False)
    ok(inc["written"] >= 1, "P12 增量：新增事实触发重写", inc)
    body2 = (cg.get(pid) or {}).get("content") or ""
    ok("2026-08-01" in body2 and "2026-04-26" in body2,
       "P13 增量：新事实追加且旧事实保留", body2[:160])

    # 可召回：建桶索引后，用实体名查询能命中资料卡
    bi.build(cg, write=True, with_content=True)
    res = cg.recall("沈知夏", budget_tokens=2000, k=8)
    ids = [e.get("id") for e in (res.get("pack") or [])]
    ok(pid in ids, "P14 资料卡可被召回命中（关键判据）", ids)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())