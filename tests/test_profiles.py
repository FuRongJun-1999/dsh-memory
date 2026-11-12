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

    # ---- D14/D15：人物档案（属性区必须在卡正文里）----
    import os as _os2
    _os2.environ["MDCG_ROLE_USER"] = "沈知夏"
    _root2 = tempfile.mkdtemp(prefix="dos_")
    _cg2 = MdCGOS(_root2, actor="test")
    _cg2.add("x1", "我叫沈知夏，知了的知，夏天的夏，24", created_at=ts("2026-04-26 10:00:00"),
             role="user", tags=["domain:d"], consistency=False)
    _cg2.add("x2", "我在江北咖啡店做结构设计，我住在江北市，本科", created_at=ts("2026-05-03 10:00:00"),
             role="user", tags=["domain:d"], consistency=False)
    profiles.build(_cg2, dry_run=False)
    _body = (_cg2.get("profile-role-沈知夏") or {}).get("content") or ""
    ok("【档案】" in _body, "D14 角色卡含【档案】区（属性题落点）", _body[:60])
    ok(("姓名：沈知夏" in _body) and ("年龄：24" in _body),
       "D15 档案含姓名与年龄（自我介绍抽取）", _body[:200])
    ok(("职业：结构设计" in _body) and ("单位：江北咖啡店" in _body), "D16 档案含职业与单位")
    ok("身份证" not in _body, "D17 敏感字段不入档（隐私边界）")

    # ---- N：早期自我介绍不被事实窗口截断 + 合并期过地名闸 ----
    _root3 = tempfile.mkdtemp(prefix="win_")
    _cg3 = MdCGOS(_root3, actor="test")
    _cg3.add("t0015", "我叫沈知夏，知了的知，夏天的夏，24", created_at=ts("2026-01-01 10:00:00"),
             role="user", tags=["domain:d"],
             extra={"dossier": {"姓名": {"value": "沈知夏", "w": 3},
                             "年龄": {"value": 24, "w": 3}}}, consistency=False)
    for _i in range(60):
        _cg3.add("t%04d" % (100 + _i), "今天店里做了第%d批贝果" % _i,
                  created_at=ts("2026-03-01 10:00:00"), role="user",
                  tags=["domain:d"], consistency=False)
    _cg3.add("t0163", "我把饭盒落在地铁站长椅了，在包里翻了半天",
             created_at=ts("2026-05-12 10:00:00"), role="user", tags=["domain:d"],
             extra={"dossier": {"城市": {"value": "外出包里", "w": 1}}}, consistency=False)
    profiles.build(_cg3, dry_run=False)
    _b3 = (_cg3.get("profile-role-沈知夏") or {}).get("content") or ""
    ok("姓名：沈知夏" in _b3 and "年龄：24" in _b3,
       "N1 早期自我介绍不被事实窗口截断（dossier 扫全量 facts）", _b3[:160])
    ok("外出包里" not in _b3, "N2 合并期同样过地名闸（旧节点绕过写入复核也拦）")

    # ---- S：dossier 形态容错（外部脚手架的裸 list / 裸值也要渲染）----
    _root4 = tempfile.mkdtemp(prefix="shape_")
    _cg4 = MdCGOS(_root4, actor="test")
    _T4 = "我叫祁野，25，在渝中区半坡酒馆做晚班调酒师。曾在江北那家咖啡店做过一年学徒"
    import os as _os4
    _os4.environ["MDCG_ROLE_USER"] = "祁野"
    _cg4.add("n1", _T4, role="user", consistency=False)
    _cg4.add("n1", _T4, role="user", extra={"dossier": {
        "姓名": "祁野",
        "年龄": {"value": 25},
        "经历": [{"单位": "江北咖啡店", "职位": "学徒", "_raw": "江北那家咖啡店做过一年学徒"}],
        "家庭": {"value": [{"关系": "父", "职业": "钳工"}]},
    }}, consistency=False)
    profiles.build(_cg4, dry_run=False)
    _b4 = (_cg4.get("profile-role-祁野") or {}).get("content") or ""
    ok("【经历】" in _b4 and "【家庭】" in _b4,
       "S1 裸 list / {value:list} 两种形态都渲染成区块", _b4[:200])
    ok("姓名：祁野" in _b4 and "年龄：25" in _b4, "S2 标量为裸值时也能渲染")
    ok("江北那家咖啡店做过一年学徒" not in _b4.split("【经历】")[1].split("【")[0],
       "S3 _raw 证据键不进渲染值")

    # ---- T：资料卡的源轮次注入（卡给属性、源轮次给原句）----
    import os as _os5
    _os5.environ["MDCG_ROLE_USER"] = "祁野"
    _root5 = tempfile.mkdtemp(prefix="src_")
    _cg5 = MdCGOS(_root5, actor="test")
    _cg5.add("n2", "曾在江北那家咖啡店做过一年学徒，后来转到半坡调酒",
             role="user", tags=["domain:d"], consistency=False)
    _cg5.add("n1", "我叫祁野，25", role="user", tags=["domain:d"], consistency=False)
    for _i in range(20):
        _cg5.add("m%d" % _i, "今天店里做了第%d批贝果" % _i,
                  role="user", tags=["domain:d"], consistency=False)
    profiles.build(_cg5, dry_run=False)
    bi.build(_cg5, write=True, with_content=True)
    _out5 = _cg5.recall("我之前在哪儿做过学徒", budget_tokens=4000, k=20)
    _ids5 = [x.get("id") for x in (_out5.get("pack") or [])]
    ok("n2" in _ids5, "T1 资料卡事实行的源轮次被注入候选（原句进 pack）", _ids5[:6])
    ok((_out5.get("meta") or {}).get("profile_injected", 0) >= 1,
       "T2 meta 透出 profile_injected 计数（可审计）")

    # ---- V：自述轮次召回（零模型、与题目无关）----
    from md_cg import selfstmt as _ss2
    _root6 = tempfile.mkdtemp(prefix="ss_")
    _cg6 = MdCGOS(_root6, actor="test")
    _cg6.add("a1", "我叫沈知夏，知了的知，夏天的夏，24", tags=["domain:d"], consistency=False)
    _cg6.add("a2", "我大学读的是土木工程", tags=["domain:d"], consistency=False)
    for _i in range(20):
        _cg6.add("z%d" % _i, "今天天气不错第%d次" % _i, tags=["domain:d"], consistency=False)
    ok(set(_ss2.load(_root6)) == {"a1", "a2"},
       "V1 写时登记自述轮次（非自述不入表）", _ss2.load(_root6))
    bi.build(_cg6, write=True, with_content=True)
    _o6 = _cg6.recall("帮我看看这个", budget_tokens=600, k=10)
    _i6 = [x.get("id") for x in (_o6.get("pack") or [])]
    ok(any(x in _i6 for x in ("a1", "a2")),
       "V2 词法打不中时自述轮次仍被注入", _i6)

    # ---- W：selfstmt API 容错 + maintain 补登入口 ----
    _root7 = tempfile.mkdtemp(prefix="ss2_")
    _cg7 = MdCGOS(_root7, actor="test")
    _cg7.add("s1", "我叫沈知夏，24", tags=["domain:d"], consistency=False)
    ok(_ss2.load(_cg7) == _ss2.load(_root7) == ["s1"],
       "W1 load() 传 cg 或 root 等价（API 容错）", _ss2.load(_cg7))
    import os as _os7
    _os7.remove(_os7.path.join(_root7, "_selfstmt.json"))
    _o7 = _cg7.maintain(action="selfstmt", apply=True)
    ok(_o7.get("recorded") == 1 and _ss2.load(_cg7) == ["s1"],
       "W2 maintain action=selfstmt 可补登存量库", _o7)

    # ---- X：自述注入按信息密度排序（不能因「最新优先」漏掉早期答案句）----
    _root8 = tempfile.mkdtemp(prefix="rk_")
    _cg8 = MdCGOS(_root8, actor="test")
    _cg8.add("t0013", "我叫谈书宁，谈是谈话的谈", tags=["domain:d"], consistency=False)
    for _i, _m in enumerate(["今天做了点吃的", "我在店里忙了一天", "我妈打电话来问我"]):
        _cg8.add("m%d" % _i, _m, tags=["domain:d"], consistency=False)
    ok(_ss2.density("我叫谈书宁") > _ss2.density("我在店里忙了一天"),
       "X1 密度分能把「我叫…」排到「我在…」之前")
    _top1 = _cg8._selfstmt_nodes(limit=1)
    ok(bool(_top1) and (_top1[0][0] or {}).get("id") == "t0013",
       "X2 限 1 条时也选到早期高密度轮次（不是最新那条）",
       [((x[0] or {}).get("id")) for x in _top1])

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0
if __name__ == "__main__":
    sys.exit(main2())