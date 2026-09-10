# -*- coding: utf-8 -*-
"""B 型评价断言 → 带来源限定的条件表述（P35 · 设计态验收）。

对照交付计划「条目 3」：

  ① 识别：`结晶/瑰宝/被誉为/堪称…` 判为 `B_valuation`；事实性表述判为 `A_fact`
     （宁缺勿猜：仅收明显价值判断/修饰语，不把事实误判）
  ② 形态：`〔来源限定〕据<来源标签>（<来源>）的表述：<原文>`——原文完整保留（可追溯）
  ③ A 型不动：事实性表述逐字保持原样
  ④ 幂等：已条件化的文本原样返回，重跑不叠加前缀
  ⑤ 诚实边界：缺来源 / 缺标签 → 不写（返回 None），绝不编造来源
  ⑥ 覆盖三处来源位：CCG 声明行 / `state_attributes.comment` / 正文句子
  ⑦ 审计：`frontmatter.verification_evidence.conditioned` 计数 + `_crosscheck.jsonl`
     记录 `where/field/before/after`；节点**仍留 knowledge 层**（不使用 _move_layer）
  ⑧ 可回滚：撤销改写后原文还原、前缀消失

独立临时根，重跑 ≡ 首跑。
运行：python -m md_cg.test_p35_conditioned_claim
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import crosscheck as cc
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


SRC_BOOK = ["人教版《中外历史纲要》上册 第 3 单元"]
SRC_MEASURE = ["《浮力基准实验集》v1 第 2 节"]

B_CCG = "都江堰是古代水利工程的杰作"
B_COMMENT = "故宫是中华文明的瑰宝"
B_BODY = "长城被誉为世界奇迹之一"
B_OFF = "唐诗是中国诗歌的瑰宝"
A_TEXT = "浮力等于排开液体的重力"


def _doc(fn, cond, sub, exe, neg="问完全无关主题"):
    return (f"# 功能名：{fn}\n# 生效条件：{cond}\n# 子功能：{sub}\n"
            f"# 执行：{exe}\n# 不适用条件：{neg}\n")


def _seed(root):
    cg = MdCGOS(root)
    K = {"layer": "knowledge"}

    # ⑥ CCG 行承载 B 型
    cg.add("p35_ccg", _doc("都江堰功能", "问都江堰", B_CCG, "讲分水与灌溉"),
           state_attributes={"name": "历史·都江堰"}, **K)
    # ⑥ comment 承载 B 型（正文不写 子功能 行，避免与 ccg 去重后抢位）
    cg.add("p35_comment",
           _doc("故宫价值", "问故宫", "", "讲建筑与文物").replace("# 子功能：\n", ""),
           state_attributes={"name": "历史·故宫价值",
                             "comment": {"子功能": B_COMMENT}}, **K)
    # ⑥ 正文句子承载 B 型
    body = _doc("长城概览", "问长城", "介绍长城工程", "讲修筑与防御")
    body += f"\n{B_BODY}。\n"
    cg.add("p35_body", body, state_attributes={"name": "语文·长城"}, **K)
    # ③ A 型（事实性）节点：理科
    cg.add("p35_a", _doc("浮力计算", "问浮力", A_TEXT, "按阿基米德原理算"),
           state_attributes={"name": "数学·浮力计算"}, **K)
    # ⑧ 开关关闭：不做条件化
    cg.add("p35_off", _doc("唐诗格律", "问格律", B_OFF, "讲平仄押韵"),
           state_attributes={"name": "历史·唐诗"}, **K)
    return cg


def _R(nid, value, basis, source):
    return [
        {"id": nid, "unit": "reflect", "field": "验证方式", "value": value,
         "basis": basis, "source": source, "verdict": "accept"},
        {"id": nid, "unit": "verify", "field": "验证方式", "value": value,
         "verdict": "accept"},
    ]


def _verdicts():
    out = []
    for nid in ("p35_ccg", "p35_comment", "p35_body"):
        out += _R(nid, "据教材单元小结核对", "textbook", SRC_BOOK)
    out += _R("p35_a", "按基准实验集复算", "measurement", SRC_MEASURE)
    return out


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="mdcg_p35_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = _seed(root)

        # ---------- ① 识别 ----------
        for t in ("结晶", "瑰宝", "杰作", "巅峰", "典范"):
            ok(cc.claim_type(f"某事物是文明的{t}") == cc.B_CLAIM,
               f"①评价性标记「{t}」判为 B 型")
        for t in ("被誉为世界奇迹", "堪称典范", "不愧为经典", "是思想的象征"):
            ok(cc.claim_type(t) == cc.B_CLAIM, f"①评价性句式「{t}」判为 B 型")
        for t in ("水的沸点为100摄氏度", "三角形内角和等于180度", A_TEXT):
            ok(cc.claim_type(t) == cc.A_CLAIM, f"①事实性表述「{t}」判为 A 型")
        ok(cc.claim_type("") == cc.A_CLAIM, "①空文本不误判为 B 型")

        # ---------- ②③④⑤ 条件化形态 ----------
        new = cc.conditioned_claim(B_CCG, "人教版教材", SRC_BOOK)
        ok(new.startswith(cc.CONDITION_MARK), "②改写以条件前缀开头")
        ok(new.endswith(B_CCG), "②原文完整保留在尾部（可追溯）")
        ok("人教版教材" in new and "中外历史纲要" in new,
           "②显式声明来源标签与来源地址")
        ok(cc.conditioned_claim(new, "人教版教材", SRC_BOOK) == new,
           "④幂等：已条件化文本原样返回")
        ok(cc.conditioned_claim(B_CCG, "人教版教材", []) is None,
           "⑤缺来源 → 不写（不编造来源）")
        ok(cc.conditioned_claim(B_CCG, "", SRC_BOOK) is None, "⑤缺来源标签 → 不写")
        ok(cc.is_conditioned(new) and not cc.is_conditioned(B_CCG),
           "④前缀可被识别，避免重复叠加")

        # ---------- ⑥ 三处来源位识别 ----------
        fm1, c1 = cg._read(cg.index["nodes"]["p35_ccg"])
        fm2, c2 = cg._read(cg.index["nodes"]["p35_comment"])
        fm3, c3 = cg._read(cg.index["nodes"]["p35_body"])
        cl1 = cc.extract_claims(fm1, c1)
        cl2 = cc.extract_claims(fm2, c2)
        cl3 = cc.extract_claims(fm3, c3)
        hit1 = [x for x in cl1 if x["text"] == B_CCG]
        hit2 = [x for x in cl2 if x["text"] == B_COMMENT]
        hit3 = [x for x in cl3 if x["text"] == B_BODY]
        ok(hit1 and hit1[0]["where"] == "ccg" and hit1[0]["field"] == "子功能"
           and hit1[0]["type"] == cc.B_CLAIM, "⑥CCG 行 B 型：where=ccg")
        ok(hit2 and hit2[0]["where"] == "comment" and hit2[0]["field"] == "子功能",
           "⑥comment B 型：where=comment")
        ok(hit3 and hit3[0]["where"] == "body" and hit3[0]["type"] == cc.B_CLAIM,
           "⑥正文句子 B 型：where=body")
        ok(not any(x["text"].split("：", 1)[0] in ("子功能", "执行")
                   for x in cl3 if x["where"] == "body"),
           "⑥声明行不重复成为正文断言（去重生效）")
        ok(not any(x["type"] == cc.B_CLAIM for x in cl1 if x["text"] == "都江堰功能"),
           "③功能名（事实性）不被判为 B 型")

        # ---------- ⑦ 端到端落库 ----------
        rep = cc.crosscheck(cg, verdicts=_verdicts(), apply=True, batch="p35a",
                            actor="tester")
        ok(rep["written"] == 4, f"⑦四个节点落库（实测 {rep['written']}）")
        ok(rep["claims_conditioned"] == 3,
           f"⑦工单内 B 型断言计 3（实测 {rep['claims_conditioned']}）")

        # CCG 行位
        fm, c = cg._read(cg.index["nodes"]["p35_ccg"])
        line = next(x for x in c.split("\n") if x.startswith("# 子功能："))
        ok(cc.CONDITION_MARK in line and B_CCG in line and c.count(B_CCG) == 1,
           "⑦CCG 行位：改写为条件表述且原文只留一份")
        ok(fm["verification_evidence"]["conditioned"] == 1,
           "⑦审计字段 conditioned 计数为 1")
        ok(fm["verification_evidence"]["basis"] == "textbook"
           and fm["verification_evidence"]["source"] == SRC_BOOK,
           "⑦审计字段记录基底与来源")

        # comment 位
        fm, c = cg._read(cg.index["nodes"]["p35_comment"])
        cv = fm["state_attributes"]["comment"]["子功能"]
        ok(cc.CONDITION_MARK in cv and B_COMMENT in cv,
           "⑦comment 位：改写为条件表述，原文保留")
        ok(CONDITION_MARK_NOT_IN_OTHER(c, cv), "⑦comment 位不误改正文")

        # body 位
        fm, c = cg._read(cg.index["nodes"]["p35_body"])
        ok(cc.CONDITION_MARK in c and B_BODY in c, "⑦正文位：改写为条件表述")
        ok(c.count(B_BODY) == 1, "⑦正文位原文只留一份（不重复）")
        ok("# 子功能：介绍长城工程" in c, "③A 型子功能表述逐字未动")

        # A 型节点：事实性表述不动
        fm, c = cg._read(cg.index["nodes"]["p35_a"])
        ok(cc.CONDITION_MARK not in c and A_TEXT in c,
           "③A 型节点无任何条件化改写")
        ok(fm["verification_evidence"]["conditioned"] == 0
           and "# 验证方式：" in c, "③A 型仍正常落验证方式")

        # ⑧ 开关关闭
        rep_off = cc.crosscheck(
            cg, ids=["p35_off"],
            verdicts=_R("p35_off", "据教材单元小结核对", "textbook", SRC_BOOK),
            apply=True, batch="p35b", actor="tester", condition_claims=False)
        ok(rep_off["written"] == 1, "⑧开关关闭仍完成证据落库")
        fm, c = cg._read(cg.index["nodes"]["p35_off"])
        ok(cc.CONDITION_MARK not in c and B_OFF in c,
           "⑧condition_claims=False → 不条件化")
        ok(fm["verification_evidence"]["conditioned"] == 0, "⑧审计计数为 0")

        # ⑦ 节点仍留 knowledge 层
        ok(all(cg.index["nodes"][n]["layer"] == "knowledge"
               for n in ("p35_ccg", "p35_comment", "p35_body", "p35_off")),
           "⑦改写后就地保留 knowledge 层（未 _move_layer）")

        # ---------- ⑦ 留痕可查 ----------
        h = cc.history(cg, action="crosscheck", batch="p35a")
        rec = next(r for r in h["records"] if r["node"] == "p35_ccg")
        cond = rec["claims_conditioned"][0]
        ok(cond["where"] == "ccg" and cond["field"] == "子功能"
           and cond["before"] == B_CCG and cond["after"].startswith(cc.CONDITION_MARK),
           "⑦留痕记录 where/field/before/after")

        # ---------- ④ 幂等：重跑不叠加 ----------
        fm, c = cg._read(cg.index["nodes"]["p35_body"])
        again = [x for x in cc.extract_claims(fm, c) if x["type"] == cc.B_CLAIM]
        ok(not again, "④已条件化断言不再被识别为待改写 B 型（重跑不叠加）")

        # ---------- ⑧ 回滚 ----------
        rb = cc.rollback(cg, batch="p35a")
        ok(rb["reverted"] == 4 and rb["conflict"] == 0,
           f"⑧回滚 4 条（实测 reverted={rb['reverted']} conflict={rb['conflict']}）")
        fm, c = cg._read(cg.index["nodes"]["p35_ccg"])
        ok(cc.CONDITION_MARK not in c and c.count(B_CCG) == 1,
           "⑧回滚还原 CCG 行原文")
        fm, c = cg._read(cg.index["nodes"]["p35_body"])
        ok(cc.CONDITION_MARK not in c and B_BODY in c, "⑧回滚还原正文原文")
        fm, _ = cg._read(cg.index["nodes"]["p35_comment"])
        ok(cc.CONDITION_MARK not in fm["state_attributes"]["comment"]["子功能"],
           "⑧回滚还原 comment 原文")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nPASS={PASS} FAIL={FAIL}")
    if FAILS:
        print("FAILED:")
        for f in FAILS:
            print("  -", f)
        raise SystemExit(1)
    print("全部通过：P35 B 型断言条件化（识别/形态/三处来源位/审计/回滚）")


def CONDITION_MARK_NOT_IN_OTHER(content, cv):
    """comment 位改写后：正文里不应出现条件前缀（避免误改正文）。"""
    return cc.CONDITION_MARK not in (content or "")


if __name__ == "__main__":
    main()
