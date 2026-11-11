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




def _run_diary_checks():
    """情景层 v0.1：diary 声明优先 / 角色卡 / 人名闸 / 资料卡配额。"""
    import datetime as _dt
    root = tempfile.mkdtemp(prefix="diary_")
    cg = MdCGOS(root, actor="test")
    # 1) diary 声明：角色名不抽取
    cg.add("d1", "我叫沈知夏，24岁，在江北咖啡店做结构设计",
           created_at=ts("2026-04-26 10:00:00"), tags=["domain:diary"],
           diary={"date": "2026-04-26", "scene": "初见", "speaker": "沈知夏",
                  "listener": "满师傅", "participants": ["老贺"],
                  "place": "江北咖啡店"}, consistency=False)
    st = profiles.build(cg, dry_run=False)
    ok(st.get("declared", 0) >= 1, "D1 声明类卡计数", st)
    rid = profiles.card_id("role", "沈知夏")
    ok(bool(cg.get(rid)), "D2 角色卡按声明建立（零抽取）", rid)
    ok(bool(cg.get(profiles.card_id("role", "满师傅"))), "D3 对手角色卡也建立")
    ok(bool(cg.get(profiles.card_id("person", "老贺"))), "D4 第三方人物卡建立")
    ok(bool(cg.get(profiles.card_id("place", "江北咖啡店"))), "D5 地点卡按声明建立")
    ok(bool(cg.get(profiles.card_id("event", "2026-04-26"))), "D6 事件卡按 diary.date 建立")
    body = (cg.get(rid) or {}).get("content") or ""
    ok("角色资料" in body, "D7 角色卡标题正确", body[:40])
    tags = ((cg.get(rid) or {}).get("frontmatter") or {}).get("tags") or []
    ok("card_source:declared" in tags, "D8 卡标 declared（与 extracted 不混报）", tags[:8])

    # 2) 人名闸：错名不得成卡
    cg.add("d2", "号你 们说 这不是人名", created_at=ts("2026-04-27 10:00:00"),
           tags=["domain:diary"], consistency=False)
    profiles.build(cg, dry_run=False)
    bad = [nid for nid in (cg.index.get("nodes") or {})
           if str(nid).startswith("profile-person-")]
    ok(all("号你" not in str(n) for n in bad), "D9 人名闸挡住错名（无 号你 卡）", bad[:4])

    # 3) 资料卡配额
    for i in range(8):
        cg.add("p%d" % i, "沈知夏 提到第%d次" % i, created_at=ts("2026-05-01 10:00:00"),
               tags=["domain:diary"], consistency=False)
    bi.build(cg, write=True, with_content=True)
    res = cg.recall("沈知夏", budget_tokens=4000, k=30)
    ids = [e.get("id") for e in (res.get("pack") or [])]
    n_prof = sum(1 for i in ids if str(i).startswith("profile-"))
    ok(n_prof <= 3, "D10 资料卡配额生效（≤3）", (n_prof, ids[:6]))
    ok(rid in ids, "D11 正确的角色卡仍在 pack 里（没被配额误杀）", ids[:6])
    return cg, rid


def main2():
    print("=" * 70)
    print("情景层 v0.1：diary 声明 / 角色卡 / 人名闸 / 配额")
    print("=" * 70)
    cg, rid = _run_diary_checks()
    # ---- D12/D13（外测请求 #2 + 候选注入）----
    _fm2 = (cg.get(rid) or {}).get("frontmatter") or {}
    _d = _fm2.get("created_at")
    _day = time.strftime("%Y-%m-%d", time.localtime(float(_d))) if _d else None
    ok(_day == "2026-04-26", "D12 卡 created_at 取最早事实日（非建卡时刻）", _day)
    _cand = cg._profile_candidates("沈知夏 姓名 年龄")
    _cids = [n.get("id") for n, _a, _b, _c in _cand]
    ok(rid in _cids, "D13 实体标签直取资料卡（候选注入可用）", _cids[:4])

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0
if __name__ == "__main__":
    sys.exit(main2())