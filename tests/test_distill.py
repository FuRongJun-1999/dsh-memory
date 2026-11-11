# -*- coding: utf-8 -*-
"""distill 守卫：LLM 填表 + **原文复核**（写入时整理）。

判据（使用者 2026-11-12）：规则对自然对话天生失效 ⇒ 用**表**让 LLM 填，
并做**原文复核**避免 LLM 失误。

复核是**可机械判定**的：值必须在原文里找得到（归一化子串 / 数值等值），否则拒收。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import distill, profiles  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []
TEXT = "我叫沈知夏，知了的知，夏天的夏，24"


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 70)
    print("distill：表 + 原文复核")
    print("=" * 70)

    t = distill.table_text()
    ok("姓名" in t and "城市" in t, "S1 表含全部字段")
    ok("只填原文" in t, "S2 表内明写「只填原文明确出现的值」")

    good, rej_g = distill.verify({"姓名": "沈知夏", "年龄": 24}, TEXT)
    ok(set(good) == {"姓名", "年龄"} and not rej_g, "V1 原文有的值通过", (good, rej_g))
    ok(good["姓名"]["ev_span"] == "沈知夏", "V2 给出 ev_span（可回溯原文）", good["姓名"])

    bad, rej_b = distill.verify({"姓名": "沈知远", "城市": "外出包里", "年龄": 30}, TEXT)
    ok(not bad, "V3 编造的值全部拒收", bad)
    ok(all(r["reason"] == "not_in_source" for r in rej_b), "V4 拒收原因=not_in_source", rej_b)

    ghost, rej_x = distill.verify({"爱好": "钓鱼", "姓名": "沈知夏"}, TEXT)
    ok(any(r["reason"] == "field_not_in_schema" for r in rej_x), "V5 表外字段被丢（不让 LLM 发明字段）", rej_x)

    root = tempfile.mkdtemp(prefix="dis_")
    cg = MdCGOS(root, actor="test")
    cg.add("n1", TEXT, role="user", consistency=False)
    r = distill.apply(cg, "n1", {"姓名": "沈知夏", "年龄": 24, "城市": "外出包里"})
    ok(r["ok"] and set(r["applied"]) == {"姓名", "年龄"}, "A1 apply 只落通过复核的字段", r["applied"])
    ok(any(x["field"] == "城市" for x in r["rejected"]), "A2 误抽的城市被拒", r["rejected"])
    ok(cg.get("n1")["frontmatter"].get("dossier") is None,
       "A3 apply 不写盘（无副作用，单写链）")

    # 端到端：把 apply 的 dossier 写回节点，再由 profiles 建卡 → 卡内有档案
    cg.add("n1", TEXT, role="user", extra={"dossier": r["dossier"]}, consistency=False)
    os.environ["MDCG_ROLE_USER"] = "沈知夏"
    profiles.build(cg, dry_run=False)
    body = (cg.get("profile-role-沈知夏") or {}).get("content") or ""
    ok("姓名：沈知夏" in body, "E1 LLM 填表结果进了卡（档案区）", body[:120])
    ok("城市" not in body, "E2 被拒字段没进卡", body[:160])

    # ---- C：城市值校验（原文有 ≠ 是地名）----
    ok(not distill.is_place("外出包里"), "C1 方位短语不是地名")
    ok(distill.is_place("渝中区") and distill.is_place("南宁"), "C2 地名通过（后缀/词典）")
    _acc, _rej = distill.verify({"城市": "外出包里"}, "外出包里放着伞")
    ok(not _acc and _rej and _rej[0]["reason"] == "not_a_place",
       "C3 原文里有但非地名 ⇒ 拒收 not_a_place", _rej)

    # ---- W：证据权重合并（强证据不得被弱证据覆盖）----
    from md_cg import dossier as _d2
    ok(_d2.weight_of("我叫沈知夏，24") == 3, "W1 自我介绍权重=3")
    ok(_d2.weight_of("我把伞落在包里了") == 1, "W2 泛提权重=1")
    _m = _d2.merge({}, {"城市": {"value": "南宁", "w": 3}})
    _m = _d2.merge(_m, {"城市": {"value": "包里", "w": 1}})
    ok(_m["城市"]["value"] == "南宁", "W3 弱证据不覆盖强证据", _m["城市"])
    _m = _d2.merge(_m, {"城市": {"value": "渝中区", "w": 3}})
    ok(_m["城市"]["value"] == "南宁", "W4 同权重非时间字段保留旧值（不覆盖）", _m["城市"])
    _m = _d2.merge({"年龄": {"value": 24, "w": 3}}, {"年龄": {"value": 25, "w": 3}})
    ok(_m["年龄"]["value"] == 25, "W5 时间可变字段（年龄）同权重取较新", _m["年龄"])

    # ---- L：序列字段（经历/家庭）----
    _T3 = "我叫沈知夏，24。曾在江北咖啡店做过一年学徒，后来转到半坡调酒。我妈是社区超市理货员"
    _acc3, _rej3 = distill.verify({
        "经历": [{"单位": "江北咖啡店", "职位": "学徒"}, {"单位": "半坡", "职位": "调酒"}],
        "家庭": [{"关系": "母", "职业": "理货员"}],
        "城市": "外出包里"}, _T3)
    ok(len((_acc3.get("经历") or {}).get("value") or []) == 2, "L1 经历逐项通过复核（两项）", _acc3.get("经历"))
    ok(len((_acc3.get("家庭") or {}).get("value") or []) == 1, "L2 家庭关系词走别名白名单（母↔妈）", _acc3.get("家庭"))
    ok(not _acc3.get("城市"), "L3 城市仍被拒（原文无此值）")
    _bad, _rj = distill.verify({"经历": [{"单位": "不存在的店", "职位": "学徒"}]}, _T3)
    ok(not _bad and _rj and _rj[0]["reason"] == "no_item_in_source",
       "L4 编造的经历项整条丢弃", _rj)
    _m3 = _d2.merge({"经历": {"value": [{"单位": "江北咖啡店"}]}},
                     {"经历": {"value": [{"单位": "江北咖啡店"}, {"单位": "半坡"}]}})
    ok(len(_m3["经历"]["value"]) == 2, "L5 序列按项去重追加（不互相覆盖）", _m3["经历"]["value"])

    # ---- R：_raw 证据锚（复核证据片段，不复核归一化值）----
    _T4 = "我叫罗杏子，今年38，在南宁，全职带娃。曾在江北那家咖啡店做过一年学徒"
    _a4, _r4 = distill.verify({"单位": {"value": "江北咖啡店"}}, _T4)
    ok(not _a4 and _r4 and _r4[0]["reason"] == "not_in_source",
       "R1 无 _raw 的归一化值仍被拒（原文写『江北那家咖啡店』）", _r4)
    _a5, _r5 = distill.verify({"单位": {"value": "江北咖啡店", "_raw": "江北那家咖啡店"}}, _T4)
    ok("单位" in _a5 and _a5["单位"]["ev_span"] == "江北那家咖啡店",
       "R2 带 _raw 的归一化值通过（复核证据而非值）", _a5)
    _a6, _r6 = distill.verify({"职业": {"value": "调酒师", "_raw": "在酒吧调了三年"}}, _T4)
    ok(not _a6 and _r6[0]["reason"] == "not_in_source",
       "R3 假 _raw（原文没有）仍拒收——防幻觉不放松", _r6)
    _a7, _r7 = distill.verify({"经历": [{"单位": "江北咖啡店", "职位": "学徒",
                                      "_raw": "江北那家咖啡店做过一年学徒"}]}, _T4)
    ok(len((_a7.get("经历") or {}).get("value") or []) == 1, "R4 序列项 _raw 锚定通过", _a7)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())