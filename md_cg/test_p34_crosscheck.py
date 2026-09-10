# -*- coding: utf-8 -*-
"""批量核对管线（P34 · 设计态验收）。

对照交付计划「条目 2 — 反思单元 + 验证单元批量核对」：

  ① 工单：缺 `verification_basis`/`验证方式` 的节点入列；占位空壳转待填充工单
     不进接线；已齐备节点跳过
  ② 来源执照：文科只认 textbook/public_kb（宽松=来源一致性）；
     理科只认 compiler/test/measurement/formal_proof/data（严格=可复现）；
     赛道未定或无来源 → 一律 DEFER，不写
  ③ 双单元防自证：reflect 与 verify 必须为不同执行者；验证单元只能否决、不能新增
  ④ 留痕：`_crosscheck.jsonl` 记录 before/after 与 units；history 可查
  ⑤ 回滚：仅在「当前值 == 写入值」时撤销，改过的计入 conflict

独立临时根，重跑 ≡ 首跑；只读真实库之外的临时节点。
运行：python -m md_cg.test_p34_crosscheck
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from . import crosscheck as cc
from . import tokens
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


PH = "[历史·高中] 骨架锚点，内容待填充"
SCI_NAME = "数学·函数单调性判定"
HUM_NAME = "历史·丝绸之路"

SRC_MEASURE = ["《函数单调性基准集》v1 第 3 节"]
SRC_BOOK = ["人教版《中外历史纲要》上册 第 3 单元"]
SRC_KB = ["https://example.org/kb/tang-poetry-meter"]


def _doc(fn, cond, sub, exe, va="", neg="问完全无关主题"):
    lines = [f"# 功能名：{fn}", f"# 生效条件：{cond}",
             f"# 子功能：{sub}", f"# 执行：{exe}"]
    if va:
        lines.append(f"# 验证方式：{va}")
    lines.append(f"# 不适用条件：{neg}")
    return "\n".join(lines) + "\n"


def _seed(root):
    cg = MdCGOS(root)
    K = {"layer": "knowledge"}

    cg.add("cc_sci_ok", _doc("函数单调性判定", "问单调性", "判定单调区间", "取导数定号"),
           state_attributes={"name": SCI_NAME}, **K)
    cg.add("cc_sci_bad", _doc("函数奇偶性判定", "问奇偶性", "判定奇偶", "代入 -x"),
           state_attributes={"name": "数学·函数奇偶性判定"}, **K)
    cg.add("cc_hum_ok", _doc("丝绸之路影响", "问丝路", "解释丝路影响", "讲商贸与交流"),
           state_attributes={"name": HUM_NAME}, **K)
    cg.add("cc_nosrc", _doc("唐诗格律", "问格律", "说明格律", "举五言例"),
           state_attributes={"name": "语文·唐诗格律"}, **K)
    cg.add("cc_veto", _doc("数列极限", "问极限", "求极限", "按定义算"),
           state_attributes={"name": "数学·数列极限"}, **K)
    cg.add("cc_newfield", _doc("概率计算", "问概率", "算概率", "用组合数"),
           state_attributes={"name": "数学·概率计算"}, **K)
    cg.add("cc_self", _doc("导数应用", "问导数", "单调性应用", "求导"),
           state_attributes={"name": "数学·导数应用"}, **K)
    cg.add("cc_undet", _doc("函数挂载流程", "问挂载", "说明挂载", "按步骤"),
           state_attributes={"name": "函数挂载流程"}, **K)
    cg.add("cc_fn", _doc("注入式测试", "问注入", "说明注入", "执行注入"),
           state_attributes={"name": "数学·注入式测试"}, **K)
    # 空壳：无 state_attributes.name、无真实 comment 字段 → 全部推导向都是占位
    cg.add("cc_ph", "# 功能名：骨架节点\n\n迁移期空壳。\n", **K,
           state_attributes={"comment": {"生效条件": [PH], "子功能": PH, "执行": PH}})
    cg.add("cc_present", _doc("已齐备知识点", "问齐备", "说明", "执行",
                              va="编译器/静态检查通过"),
           verification_basis="test", state_attributes={"name": SCI_NAME}, **K)
    cg.add("cc_btype",
           _doc("丝绸之路文化价值", "问丝路文化",
                "丝绸之路是东西方文化交流的结晶", "讲商贸与交流"),
           state_attributes={"name": HUM_NAME}, **K)
    return cg


def _rows():
    def R(nid, unit, value, basis, source, verdict, reason="", actor=None):
        r = {"id": nid, "unit": unit, "field": "验证方式", "value": value,
             "basis": basis, "source": source, "verdict": verdict,
             "reason": reason}
        if actor:
            r["actor"] = actor
        return r

    return [
        R("cc_sci_ok", "reflect", "以基准函数集实测判定单调区间", "measurement",
          SRC_MEASURE, "accept"),
        R("cc_sci_ok", "verify", "以基准函数集实测判定单调区间", "", [], "accept"),
        R("cc_sci_bad", "reflect", "据教材结论", "textbook", SRC_BOOK, "accept"),
        R("cc_sci_bad", "verify", "据教材结论", "", [], "accept"),
        R("cc_hum_ok", "reflect", "据教材单元小结核对", "textbook", SRC_BOOK, "accept"),
        R("cc_hum_ok", "verify", "据教材单元小结核对", "", [], "accept"),
        R("cc_nosrc", "reflect", "据公开知识库条目", "public_kb", [], "accept"),
        R("cc_nosrc", "verify", "据公开知识库条目", "", [], "accept"),
        R("cc_veto", "reflect", "按定义复算", "measurement", SRC_MEASURE, "accept"),
        R("cc_veto", "verify", "按定义复算", "", [], "drop", "来源无法复核"),
        {"id": "cc_newfield", "unit": "reflect", "field": "子功能",
         "value": "偷偷改子功能", "basis": "measurement", "source": SRC_MEASURE,
         "verdict": "accept"},
        R("cc_self", "reflect", "按导数定义复算", "measurement", SRC_MEASURE,
          "accept", actor="同一子代理"),
        R("cc_self", "verify", "按导数定义复算", "", [], "accept", actor="同一子代理"),
        R("cc_undet", "reflect", "据公开知识库", "public_kb", SRC_KB, "accept"),
        R("cc_undet", "verify", "据公开知识库", "", [], "accept"),
        R("cc_btype", "reflect", "据教材单元小结核对", "textbook", SRC_BOOK, "accept"),
        R("cc_btype", "verify", "据教材单元小结核对", "", [], "accept"),
    ]


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="mdcg_p34_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = _seed(root)

        # ---------- ① 工单 ----------
        wl = cc.build_worklist(cg)
        row_ids = {r["id"] for r in wl["items"]}
        ok("cc_sci_ok" in row_ids and "cc_hum_ok" in row_ids, "①缺证据节点入工单")
        ok("cc_present" not in row_ids and wl["skipped_present"] >= 1,
           "①已齐备节点不入工单")
        ok("cc_ph" not in row_ids and "cc_ph" in wl["placeholder_ids"],
           "①占位空壳排除并登记待填充清单")
        row = next(r for r in wl["items"] if r["id"] == "cc_sci_ok")
        ok(row["track"] == "science" and row["source_policy"] == "reproducible",
           "①理科工单：track=science / policy=reproducible")
        ok(set(row["need"]) == {"verification_basis", "验证方式"},
           "①need 精确列出待补字段")
        ok(any(c["text"] == "判定单调区间" for c in row["claims"]),
           "①工单携带可核对断言")
        hum = next(r for r in wl["items"] if r["id"] == "cc_hum_ok")
        ok(hum["track"] == "humanities" and hum["source_policy"] == "consistency",
           "①文科工单：track=humanities / policy=consistency")
        ok(wl["undetermined"] >= 1, "①赛道未定单独计数（不猜）")

        # ---------- ② 来源执照（契约层） ----------
        ok(cc.basis_licensed("science", "measurement")
           and cc.basis_licensed("science", "compiler")
           and not cc.basis_licensed("science", "textbook"),
           "②理科严格：只认可复现档，教材不算依据")
        ok(cc.basis_licensed("humanities", "textbook")
           and cc.basis_licensed("humanities", "public_kb")
           and not cc.basis_licensed("humanities", "measurement"),
           "②文科宽松：认来源一致性档")
        ok(not cc.basis_licensed("undetermined", "public_kb"),
           "②赛道未定不发放来源执照")
        ok(cc.classify_track({"state_attributes": {"name": SCI_NAME}}) == "science"
           and cc.classify_track(
               {"state_attributes": {"name": HUM_NAME}}) == "humanities",
           "②赛道判定按已声明学科名")

        # ---------- ③ 双单元折叠（纯函数） ----------
        a, d, dr = cc.fold_verdicts([
            {"id": "x", "unit": "reflect", "field": "验证方式", "value": "v",
             "basis": "test", "source": ["s"], "verdict": "accept"},
            {"id": "x", "unit": "verify", "field": "验证方式", "value": "v",
             "verdict": "drop", "reason": "来源无法复核"}])
        ok(not a and len(dr) == 1 and "来源无法复核" in dr[0]["reason"],
           "③验证单元否决 → 不进 accepted（veto 优先）")
        a, d, dr = cc.fold_verdicts([
            {"id": "x", "unit": "reflect", "field": "验证方式", "value": "v",
             "basis": "test", "source": ["s"], "verdict": "accept"}])
        ok(not a and d and "验证裁决" in d[0]["reason"],
           "③只有反思单元 → 缺验证裁决，DEFER")
        ok(cc.detect_self_verify([
            {"unit": "reflect", "actor": "a"}, {"unit": "verify", "actor": "a"}])
           and not cc.detect_self_verify([
               {"unit": "reflect", "actor": "a"}, {"unit": "verify", "actor": "b"}]),
           "③自证检测：同执行者即判自证")

        # ---------- ④ 解析器 ----------
        fenced = ('```json\n[{"field":"验证方式","value":"v","basis":"test",'
                  '"source":["s"],"verdict":"accept"}]\n```')
        ok(len(cc.parse_reflect_rows(fenced)) == 1, "④容忍代码围栏的 JSON 解析")
        ok(cc.parse_reflect_rows("不是 JSON") == [], "④坏输出不抛异常、返回空")
        ok(cc.parse_verify_rows(json.dumps({"rows": [
            {"field": "验证方式", "value": "v", "verdict": "drop"}]}))[0][
                "verdict"] == "drop", "④包裹对象的 JSON 解析")

        # ---------- 注入式两单元（cc_fn，全程不写盘） ----------
        def fake_reflect(prompt):
            return json.dumps([{"field": "验证方式", "value": "由基准集实测",
                                "basis": "measurement", "source": SRC_MEASURE,
                                "verdict": "accept"}])

        def fake_verify(prompt):
            return ('```json\n' + json.dumps([{"field": "验证方式",
                                              "value": "由基准集实测",
                                              "verdict": "accept"}]) + '\n```')

        rep3 = cc.crosscheck(cg, ids=["cc_fn"], reflect_fn=fake_reflect,
                             verify_fn=fake_verify, apply=False, batch="p34d")
        ok(rep3["accepted"] == 1, "④注入式两单元管线可用")
        rep4 = cc.crosscheck(cg, ids=["cc_fn"], reflect_fn=fake_reflect,
                             apply=False, batch="p34e")
        ok(rep4["deferred"] == 1 and "verify_unavailable" in rep4["reasons"],
           "③缺验证单元 → DEFER（默认不允许单单元自证）")
        rep5 = cc.crosscheck(cg, ids=["cc_fn"], reflect_fn=fake_reflect,
                             verify_fn=fake_reflect, apply=False, batch="p34f")
        ok("self_verify_disallowed" in rep5["reasons"],
           "③同一函数既反思又验证 → 自证拒绝")

        # ---------- ②⑤ 落库 ----------
        rep = cc.crosscheck(cg, verdicts=_rows(), apply=True, batch="p34a",
                            actor="tester")
        ok(rep["accepted"] == 3, f"⑤接受 3 个（实测 {rep['accepted']}）")
        ok(rep["rejected"] == 1, f"⑤验证否决计 1（实测 {rep['rejected']}）")
        ok(rep["written"] == 3, "⑤写入数 == accepted")
        ok(rep["skipped_placeholder"] >= 1 and rep["skipped_present"] >= 1,
           "⑤占位/已齐备在核对主流程同样跳过")

        fm, c = cg._read(cg.index["nodes"]["cc_sci_ok"])
        ok(fm.get("verification_basis") == "measurement", "②理科写入 evidence 基底")
        ok("# 验证方式：以基准函数集实测判定单调区间" in c,
           "⑤正文出现验证方式规范行（用裁决值，非基底默认文案）")
        ok(fm.get("verification_evidence", {}).get("source") == SRC_MEASURE,
           "⑤留痕记录来源（可追溯）")
        units = fm.get("verification_evidence", {}).get("units", {})
        ok(units.get("reflect") and units.get("verify"), "③留痕记录两单元执行者")

        fm, c = cg._read(cg.index["nodes"]["cc_hum_ok"])
        ok(fm.get("verification_basis") == "textbook" and "# 验证方式：" in c,
           "②文科宽松档落库成功")
        fm, c = cg._read(cg.index["nodes"]["cc_sci_bad"])
        ok(not fm.get("verification_basis") and "# 验证方式：" not in c,
           "②理科拿教材当依据 → 不写（严格）")
        fm, c = cg._read(cg.index["nodes"]["cc_nosrc"])
        ok(not fm.get("verification_basis"), "②无来源 → 不写，保持 DEFER")
        fm, c = cg._read(cg.index["nodes"]["cc_veto"])
        ok(not fm.get("verification_basis") and "verify_veto" in rep["reasons"],
           "③被否决 → 不写（veto 留痕）")
        fm, c = cg._read(cg.index["nodes"]["cc_newfield"])
        ok(not fm.get("verification_basis") and "偷偷改子功能" not in c,
           "③越界字段被白箱闸门挡下（验证单元不得新增）")
        fm, c = cg._read(cg.index["nodes"]["cc_self"])
        ok(not fm.get("verification_basis")
           and "self_verify_disallowed" in rep["reasons"], "③自证被拒")
        fm, c = cg._read(cg.index["nodes"]["cc_undet"])
        ok(not fm.get("verification_basis"), "②赛道未定 → 不写")

        # ---------- ④ 留痕 ----------
        h = cc.history(cg, action="crosscheck")
        ok(h["total"] >= 3 and os.path.exists(cc._log_path(cg)),
           "④_crosscheck.jsonl 有核对留痕")
        ok(all("write_id" in r and r.get("node") for r in h["records"]),
           "④留痕含 write_id 与节点定位")

        # ---------- 幂等 ----------
        rep2 = cc.crosscheck(cg, verdicts=_rows(), apply=True, batch="p34b",
                             actor="tester")
        ok(rep2["accepted"] == 0, "⑤重跑幂等：已齐备节点不再被接受")
        fm, c = cg._read(cg.index["nodes"]["cc_sci_ok"])
        ok(c.count("# 验证方式：") == 1, "⑤验证方式行幂等（不重复堆叠）")

        # ---------- 条目 3 雏形：B 型条件化 ----------
        fm, c = cg._read(cg.index["nodes"]["cc_btype"])
        ok(cc.CONDITION_MARK in c and "结晶" in c and c.count("结晶") == 1,
           "⑤B 型断言改写为带来源限定的条件表述")
        ok("来源限定" in c and "人教版" in c, "⑤条件表述显式声明来源")
        ok("# 生效条件：问丝路文化" in c, "⑤A 型（事实性）表述保持原样")

        # ---------- ⑤ 回滚 + conflict ----------
        rb = cc.rollback(cg, batch="p34a")
        ok(rb["reverted"] == 3, f"⑤回滚 3 条（实测 {rb['reverted']}）")
        fm, c = cg._read(cg.index["nodes"]["cc_sci_ok"])
        ok("# 验证方式：" not in c and not fm.get("verification_basis")
           and "verification_evidence" not in fm,
           "⑤回滚彻底还原 frontmatter 与正文行")
        fm, c = cg._read(cg.index["nodes"]["cc_btype"])
        ok(cc.CONDITION_MARK not in c and "结晶" in c,
           "⑤回滚还原 B 型原文（未加来源限定）")

        cc.crosscheck(cg, verdicts=_rows(), apply=True, batch="p34c", actor="tester")
        e = cg.index["nodes"]["cc_sci_ok"]
        fm, c = cg._read(e)
        fm["verification_evidence"]["write_id"] = "被人改过"
        cg._write_node("cc_sci_ok", os.path.join(cg.root, e["path"]), fm, c)
        rb2 = cc.rollback(cg, batch="p34c")
        ok(rb2["conflict"] == 1 and rb2["reverted"] == 2,
           f"⑤改过的节点计入 conflict 不误撤（conflict={rb2['conflict']}）")
        fm, _ = cg._read(cg.index["nodes"]["cc_sci_ok"])
        ok(fm["verification_evidence"]["write_id"] == "被人改过",
           "⑤conflict 节点未被撤销")

        # ---------- 权限（防提权） ----------
        tokfile = os.path.join(tmp, "tokens.json")
        des = tokens.issue("designer", actor="tester", path=tokfile)
        ref = tokens.issue("reflect", actor="r1", path=tokfile)
        p_des = tokens.verify_token(des["token"], path=tokfile)
        p_ref = tokens.verify_token(ref["token"], path=tokfile)
        ok(cc.can_write_knowledge(None) is False, "③无令牌 fail-closed")
        ok(cc.can_write_knowledge(p_des) is True, "③designer 令牌可写 knowledge")
        ok(cc.can_write_knowledge(p_ref) is False,
           "③reflect 令牌不含 knowledge 层，不能提权落库")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nPASS={PASS} FAIL={FAIL}")
    if FAILS:
        print("FAILED:")
        for f in FAILS:
            print("  -", f)
        raise SystemExit(1)
    print("全部通过：P34 批量核对管线（工单/来源执照/双单元/留痕/回滚）")


if __name__ == "__main__":
    main()
