# -*- coding: utf-8 -*-
r"""#829 守卫：calibration() 分母里没有正例时**不得判方向**。

缺陷（本件修复，2026-11-08）
--------------------------
`calibration()` 的判据是 `Σ正例 / Σ(正例+负例)`，而本仓没有任何生产路径
写 `confirmed`（只有测试与外部裁决会发）。故活库 Σ正例 恒为 0 ⇒
`actual_accuracy` 数学上恒为 0.0、`gap` 恒等于 `expected_accuracy` ⇒
`verdict` **恒为 overconfident**。这不是「读数偏低」，是**该字段不携带信息**。

活库实测（2026-11-09，修前）：
    n_nodes=77 / n_evidence=409 / expected=0.3234 / actual=0.0
    gap=0.3234 / verdict=overconfident
    逐层人口：contextual 42 节点 0 正 218 负；knowledge 35 节点 0 正 191 负

两层危害（本守卫各钉一条）：
  ① **读数面**：恒红比不报更有害——下游 `self_state` / `report` 把它当真读数消费；
  ② **事实面**：`scrub.calibrate(apply=True)` 会据这个退化的 gap 把全库
     confidence 一律下调（gap 恒正 ⇒ 偏置恒负）。一个不携带信息的读数
     直接改写事实层，比不调更有害。

本守卫钉四条
-----------
  A 组 **不判方向**：无正例 ⇒ verdict=insufficient_data /
    calibration_defined=False / reason=no_positive_evidence，
    但 expected/actual/gap/ece **照旧如实算并透出**（不隐藏、不编造）
  B 组 **正向对照**：有正例时方向照旧可判（不得把缺陷修成「永不判」）
  C 组 **人口可观测**：n_by_layer 逐层 n_nodes/pos/neg，且三条不变量成立
  D 组 **零写回**：scrub.calibrate 在 calibration_defined=False 时
    拒绝出偏置、apply=True 也不改任何节点的 confidence
  E 组 **建议面**：_advise 不产出方向建议，改产出 no_positive_evidence

运行：python -X utf8 -m md_cg.test_issue829_calibration_positive_gate
      python -X utf8 -m md_cg.test_issue829_calibration_positive_gate --mutate
退出码：0 全绿 / 1 有失败
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile

from . import metacognition as mc
from . import scrub
from .mdcg import MdCG

PASS = FAIL = 0
FAILS = []
_SANDBOXES = []

BODY = "# 功能名：t\n# 生效条件：t\n\n正文"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))
    return bool(cond)


# 生效条件：pos/neg 为要造的正例/负例条数（neg 用 weakened 造、pos 用 confirmed
# 造，走真实 API 而非改写 frontmatter），返回 (root, cg)；调用方负责 close。
def _mk_lib(pos=0, neg=0, confidence=0.6):
    root = tempfile.mkdtemp(prefix="i829_")
    _SANDBOXES.append(root)
    cg = MdCG(root)
    i = 0
    for _ in range(int(pos)):
        nid = "pos%d" % i
        i += 1
        cg.add(nid, BODY, layer="knowledge", importance=0.5,
               confidence=confidence)
        cg.verify(nid, "外部裁决通过", "confirmed")
    for _ in range(int(neg)):
        nid = "neg%d" % i
        i += 1
        cg.add(nid, BODY, layer="knowledge", importance=0.5,
               confidence=confidence)
        cg.verify(nid, "外部裁决不成立", "weakened")
    return root, cg


# 生效条件：入参为 calibration() 返回体，返回违规描述列表（空列表=合规）。
# **这是 A 组唯一判据函数**（变异打在此层之上）。
def no_pos_violations(rep):
    bad = []
    if rep.get("n_positive") != 0:
        bad.append("前置破：本组库应当没有正例，实得 n_positive=%r"
                   % (rep.get("n_positive"),))
    if rep.get("verdict") != "insufficient_data":
        bad.append("无正例却判了方向：verdict=%r（修前恒 overconfident）"
                   % (rep.get("verdict"),))
    if rep.get("calibration_defined") is not False:
        bad.append("calibration_defined 应为 False：%r"
                   % (rep.get("calibration_defined"),))
    if rep.get("reason") != "no_positive_evidence":
        bad.append("reason 应为 no_positive_evidence：%r" % (rep.get("reason"),))
    # 「不判方向」不等于「隐藏读数」：三个数值必须照旧如实透出。
    for k in ("expected_accuracy", "actual_accuracy", "gap", "ece"):
        if rep.get(k) is None:
            bad.append("读数被隐藏了：%s 为 None（应如实透出）" % k)
    exp, act, gap = (rep.get("expected_accuracy"), rep.get("actual_accuracy"),
                     rep.get("gap"))
    if act is not None and abs(float(act)) > 1e-9:
        bad.append("无正例时 actual 应恰为 0：%r" % (act,))
    if None not in (exp, act, gap) and abs(float(gap) - (float(exp) - float(act))) > 1e-6:
        bad.append("gap 仍须自洽 expected-actual：%r vs %r-%r"
                   % (gap, exp, act))
    return bad


# 生效条件：入参为「有正例」库的 calibration() 返回体，返回违规描述列表。
def has_pos_violations(rep):
    bad = []
    if int(rep.get("n_positive") or 0) <= 0:
        bad.append("前置破：本组库应当有正例，实得 n_positive=%r"
                   % (rep.get("n_positive"),))
    if rep.get("calibration_defined") is not True:
        bad.append("有正例却判 calibration_defined=%r（修过头：永不判）"
                   % (rep.get("calibration_defined"),))
    if rep.get("verdict") == "insufficient_data":
        bad.append("有正例且样本够却仍 insufficient_data（修过头）")
    exp, act, gap = (rep.get("expected_accuracy"), rep.get("actual_accuracy"),
                     rep.get("gap"))
    if None not in (exp, act, gap) and abs(float(gap) - (float(exp) - float(act))) > 1e-6:
        bad.append("gap 与 expected-actual 不自洽")
    return bad


# 生效条件：入参为 calibration() 返回体，返回 n_by_layer 不变量违规描述列表。
def layer_violations(rep):
    bad = []
    nbl = rep.get("n_by_layer")
    if not isinstance(nbl, dict):
        bad.append("缺 n_by_layer（人口构成不可观测）：%r" % (nbl,))
        return bad
    s_nodes = sum(int(v.get("n_nodes") or 0) for v in nbl.values())
    s_pos = sum(int(v.get("pos") or 0) for v in nbl.values())
    s_neg = sum(int(v.get("neg") or 0) for v in nbl.values())
    if s_nodes != rep.get("n_nodes"):
        bad.append("Σlayer.n_nodes(%d) != n_nodes(%r)" % (s_nodes, rep.get("n_nodes")))
    if s_pos != rep.get("n_positive"):
        bad.append("Σlayer.pos(%d) != n_positive(%r)" % (s_pos, rep.get("n_positive")))
    if s_neg != rep.get("n_negative"):
        bad.append("Σlayer.neg(%d) != n_negative(%r)" % (s_neg, rep.get("n_negative")))
    for k, v in nbl.items():
        for kk in ("n_nodes", "pos", "neg"):
            if kk not in v:
                bad.append("layer %r 缺 %s" % (k, kk))
    return bad


# 生效条件：rep 为 scrub.calibrate 返回体、before/after 为前后 confidence 映射；
# 返回违规描述列表（无正例时应当零偏置、零写回）。
def scrub_violations(rep, before, after):
    bad = []
    if rep.get("ok") is not False:
        bad.append("无正例时 calibrate 仍返回 ok=True（会出偏置）")
    if rep.get("reason") != "no_positive_evidence":
        bad.append("reason 应为 no_positive_evidence：%r" % (rep.get("reason"),))
    if abs(float(rep.get("suggested_offset") or 0.0)) > 1e-9:
        bad.append("仍给出非零偏置：%r" % (rep.get("suggested_offset"),))
    if rep.get("applied"):
        bad.append("applied 应为 False")
    if int(rep.get("n_adjusted") or 0) != 0:
        bad.append("n_adjusted 应为 0：%r" % (rep.get("n_adjusted"),))
    changed = [k for k in before if before[k] != after.get(k)]
    if changed:
        bad.append("零写回破：这些节点 confidence 被改了 %s" % (changed[:5],))
    return bad


# 生效条件：adv 为 _advise 返回的建议列表；无正例库上不得出现方向建议。
def advise_violations(adv):
    codes = [a.get("code") for a in adv or []]
    bad = []
    if "overconfident" in codes:
        bad.append("无正例仍产出 overconfident 建议")
    if "underconfident" in codes:
        bad.append("无正例仍产出 underconfident 建议")
    if "no_positive_evidence" not in codes:
        bad.append("未产出 no_positive_evidence 提示：%s" % (codes,))
    if not all("why" in a and "action" in a for a in adv or []):
        bad.append("建议缺 why/action（不可复核）")
    return bad


def _conf_of(cg, ids):
    out = {}
    for nid in ids:
        node = cg.get(nid) or {}
        out[nid] = (node.get("frontmatter") or {}).get("confidence")
    return out


# --------------------------------------------------------------------------
# A 组：不判方向（核心）
# --------------------------------------------------------------------------

def g_a_no_positive():
    """A1/A2/A3 无正例 ⇒ 不判方向，但读数如实透出。"""
    root, cg = _mk_lib(pos=0, neg=8)
    try:
        rep = mc.calibration(cg)
        bad = no_pos_violations(rep)
        check("A1 无正例 ⇒ 不判方向（verdict/calibration_defined/reason 三键齐）",
              not bad, bad)
        check("A2 读数未被隐藏（expected/actual/gap/ece 四值照旧透出）",
              all(rep.get(k) is not None
                  for k in ("expected_accuracy", "actual_accuracy", "gap", "ece")),
              {k: rep.get(k) for k in ("expected_accuracy", "actual_accuracy",
                                       "gap", "ece")})
        check("A3 无正例不影响 n_nodes/n_evidence 口径", 
              rep.get("n_nodes") == 8 and rep.get("n_evidence") == 8,
              (rep.get("n_nodes"), rep.get("n_evidence")))
    finally:
        cg.close()


def g_a_mixed_no_positive():
    """A4 负例跨两层仍无正例 ⇒ 同样不判（人口不是原因，缺正例才是）。"""
    root = tempfile.mkdtemp(prefix="i829_mix_")
    _SANDBOXES.append(root)
    cg = MdCG(root)
    try:
        for i in range(3):
            cg.add("k%d" % i, BODY, layer="knowledge", importance=0.5)
            cg.verify("k%d" % i, "不成立", "weakened")
        for i in range(3):
            cg.add("c%d" % i, BODY, layer="contextual", importance=0.5)
            cg.verify("c%d" % i, "不成立", "weakened")
        rep = mc.calibration(cg)
        bad = no_pos_violations(rep)
        check("A4 跨层全负例 ⇒ 仍不判方向", not bad, bad)
    finally:
        cg.close()


# --------------------------------------------------------------------------
# B 组：正向对照（不得修成「永不判」）
# --------------------------------------------------------------------------

def g_b_has_positive():
    """B1 全正例高置信 ⇒ 方向可判；B2 gap 仍自洽。"""
    root, cg = _mk_lib(pos=6, neg=0, confidence=0.9)
    try:
        rep = mc.calibration(cg)
        bad = has_pos_violations(rep)
        check("B1 有正例 ⇒ 方向照旧可判（不得修成永不判）", not bad, bad)
        check("B1b 全正例 ⇒ actual=1.0",
              abs(float(rep.get("actual_accuracy")) - 1.0) < 1e-9,
              rep.get("actual_accuracy"))
    finally:
        cg.close()


def g_b_mixed():
    """B3 正负混合 ⇒ 方向按 gap 判（与修前口径一字不改）。"""
    root, cg = _mk_lib(pos=3, neg=9, confidence=0.6)
    try:
        rep = mc.calibration(cg)
        bad = has_pos_violations(rep)
        check("B3 正负混合 ⇒ 方向可判且 gap 自洽", not bad, bad)
        # actual = 3/(3+9) = 0.25
        check("B3b actual == 正例/(正例+负例)",
              abs(float(rep.get("actual_accuracy")) - 3.0 / 12.0) < 1e-6,
              rep.get("actual_accuracy"))
    finally:
        cg.close()


# --------------------------------------------------------------------------
# C 组：人口可观测
# --------------------------------------------------------------------------

def g_c_n_by_layer():
    """C1 逐层人口 + 三条不变量。"""
    root, cg = _mk_lib(pos=0, neg=8)
    try:
        rep = mc.calibration(cg)
        bad = layer_violations(rep)
        check("C1 n_by_layer 产出且三条不变量成立", not bad, bad)
        check("C1b 逐层 pos 全 0（活库口径复刻）",
              all(int(v.get("pos") or 0) == 0
                  for v in (rep.get("n_by_layer") or {}).values()),
              rep.get("n_by_layer"))
    finally:
        cg.close()


def g_c_insufficient_shape():
    """C2 无样本分支形状稳定（也带 n_by_layer / calibration_defined）。"""
    root = tempfile.mkdtemp(prefix="i829_empty_")
    _SANDBOXES.append(root)
    cg = MdCG(root)
    try:
        rep = mc.calibration(cg)
        check("C2 无样本 ⇒ ok False / insufficient_data",
              rep.get("ok") is False and rep.get("reason") == "insufficient_data",
              rep)
        check("C2b 该分支同样带 n_by_layer / calibration_defined 两键",
              "n_by_layer" in rep and rep.get("calibration_defined") is False,
              sorted(rep))
    finally:
        cg.close()


# --------------------------------------------------------------------------
# D 组：零写回（事实面）
# --------------------------------------------------------------------------

def g_d_scrub_no_writeback():
    """D1 apply=True 在无正例库上零写回；D2 有正例时偏置照旧可出。"""
    root, cg = _mk_lib(pos=0, neg=8)
    try:
        ids = ["neg%d" % i for i in range(1, 9)]
        before = _conf_of(cg, ids)
        rep = scrub.calibrate(cg, apply=True)
        after = _conf_of(cg, ids)
        bad = scrub_violations(rep, before, after)
        check("D1 无正例 ⇒ 拒绝出偏置且 apply=True 零写回", not bad, bad)
    finally:
        cg.close()
    # 正向对照：有正例时，偏置路径必须仍然工作（不得一律拒绝）
    root2, cg2 = _mk_lib(pos=2, neg=6, confidence=0.9)
    try:
        rep2 = scrub.calibrate(cg2)
        check("D2 有正例 ⇒ 偏置路径照旧工作（ok=True 且有 suggested_offset）",
              rep2.get("ok") is True and "suggested_offset" in rep2,
              {k: rep2.get(k) for k in ("ok", "verdict", "suggested_offset")})
    finally:
        cg2.close()


# --------------------------------------------------------------------------
# E 组：建议面
# --------------------------------------------------------------------------

def g_e_advise():
    """E1 无正例 ⇒ 不产出方向建议，改产出 no_positive_evidence。"""
    root, cg = _mk_lib(pos=0, neg=8)
    try:
        cal = mc.calibration(cg)
        adv = mc._advise({"ok": True, "d2": 0.0, "emotion": "stable",
                          "state_rates": {}}, cal, {"unresolved_count": 0}, {})
        bad = advise_violations(adv)
        check("E1 无正例 ⇒ 建议面不产出方向建议", not bad, bad)
        # 正向对照：calibration_defined=True 的夹具必须照旧产出方向建议
        adv2 = mc._advise(
            {"ok": True, "d2": 0.0, "emotion": "stable", "state_rates": {}},
            {"verdict": "overconfident", "expected_accuracy": 0.8,
             "actual_accuracy": 0.5, "gap": 0.3, "calibration_defined": True},
            {"unresolved_count": 0}, {})
        check("E2 可判时方向建议照旧产出（正向对照）",
              any(a["code"] == "overconfident" for a in adv2), str(adv2))
    finally:
        cg.close()


_CASES = (g_a_no_positive, g_a_mixed_no_positive, g_b_has_positive, g_b_mixed,
          g_c_n_by_layer, g_c_insufficient_shape, g_d_scrub_no_writeback,
          g_e_advise)


def _run_all():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    for fn in _CASES:
        try:
            fn()
        except Exception as exc:                            # noqa: BLE001
            check(False, "%s 组抛异常：%s: %s"
                  % (fn.__name__, type(exc).__name__, exc))
    return list(FAILS)


# 生效条件：无入参；对同一份真实返回体做 5 个「破坏契约」的替身改写，
# 断言判据函数逐条转红；返回失败条数。
def _run_mutations():
    print(chr(10) + "=== 定点变异自证（变异前 → 变异后） ===")
    root, cg = _mk_lib(pos=0, neg=8)
    bad_total = 0
    try:
        rep0 = mc.calibration(cg)
        base = no_pos_violations(rep0)
        print("  [基线] 变异前违规项 = %s（应为空）" % (base or "无"))
        ids = ["neg%d" % i for i in range(1, 9)]
        before = _conf_of(cg, ids)
        scrub0 = scrub.calibrate(cg, apply=False)
        adv0 = mc._advise({"ok": True, "d2": 0.0, "emotion": "stable",
                           "state_rates": {}}, rep0, {"unresolved_count": 0}, {})

        def _shim_verdict(rep):
            r = dict(rep)
            r["verdict"] = "overconfident"          # 退回修前：恒判过度自信
            return r

        def _shim_drop_reason(rep):
            r = dict(rep)
            r.pop("reason", None)
            return r

        def _shim_layer_count(rep):
            r = dict(rep)
            nbl = {k: dict(v) for k, v in (rep.get("n_by_layer") or {}).items()}
            for v in nbl.values():
                v["pos"] = int(v.get("pos") or 0) + 1     # 人口造假
                break
            r["n_by_layer"] = nbl
            return r

        def _shim_scrub(rep):
            r = dict(rep)
            r.update({"ok": True, "reason": None, "suggested_offset": -0.3234,
                      "applied": True, "n_adjusted": 8})
            return r

        def _shim_advise(adv):
            return list(adv) + [{"code": "overconfident",
                                 "why": "期望 > 实际", "action": "抽查复核"}]

        cases = (
            ("M1 verdict 退回恒 overconfident（修前病象）",
             lambda: no_pos_violations(_shim_verdict(rep0))),
            ("M2 reason 被吞（不可观测）",
             lambda: no_pos_violations(_shim_drop_reason(rep0))),
            ("M3 n_by_layer 计数造假（人口不可信）",
             lambda: layer_violations(_shim_layer_count(rep0))),
            ("M4 scrub 照旧出偏置并写回（事实面破）",
             lambda: scrub_violations(_shim_scrub(scrub0), before, before)),
            ("M5 建议面仍产出方向建议",
             lambda: advise_violations(_shim_advise(adv0))),
        )
        for label, run in cases:
            got = run()
            hit = bool(got)
            if not check(label, hit, "变异后违规项为空 ⇒ 判据无判别力"):
                bad_total += 1
            print("        变异前：违规项=[] ｜ 变异后：违规项=%d 项 %s ⇒ %s"
                  % (len(got), got[:2], "命中" if hit else "未命中"))
        print("  变异自证结论：%s" % ("全部按预期转红" if bad_total == 0
                                  else "存在 %d 条未按预期" % bad_total))
        return bad_total
    finally:
        cg.close()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="#829 calibration 正例入口守卫")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    a = ap.parse_args()
    print("[1] 判据面")
    reds = _run_all()
    rc = 1 if reds else 0
    if a.mutate:
        rc = 1 if (_run_mutations() or reds) else 0
    print(chr(10) + "SUMMARY: #829 calibration 正例入口守卫：%d 通过，%d 失败%s"
          % (PASS, FAIL, ("；失败项=" + "; ".join(FAILS)) if FAILS else ""))
    for d in _SANDBOXES:
        shutil.rmtree(d, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
