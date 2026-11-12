# -*- coding: utf-8 -*-
r"""#121 守卫：calibration() 的越界 confidence 必须**可观测**且**不变量成立**。

缺陷（本件修复，2026-10-11）
--------------------------
conf 落在 BINS 覆盖域（[0, 1.01)）之外的节点照计 used/exp_sum/total_pos/
total_neg（**进分母**），却因不落任何桶而对 ECE 分子零贡献 ⇒ **ECE 被系统性低估**；
且返回体 n_nodes 与 Σbins.n_nodes **对不上而无人报**（静默丢弃）。
复现读数（6 正常 + 6 越界，其中 3 条真越界）：修前 n_nodes=12 / Σbins=9 / 无 dropped 字段。

本守卫钉三条
------------
  ① **不变量**：n_nodes == Σbins.n_nodes + dropped（恒成立）
  ② **可追**：dropped/out_of_range 计数 + dropped_ids 抽样（截断须显式标出）
  ③ **口径不变**：ECE 只由**入桶**节点贡献——用公式手算的期望值钉住返回值（
     同时证明修法没有顺手改口径）；且 conf==0.0 / 0.99 / 1.0 必须**入桶**（上界 1.01）

运行：python -X utf8 -m md_cg.test_issue121_calibration_bounds
      python -X utf8 -m md_cg.test_issue121_calibration_bounds --mutate
退出码：0 全绿 / 1 有失败
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import sys
import tempfile

from . import metacognition as mc
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []
_SANDBOXES = []

BODY = ("# 功能名：t" + chr(10) + "# 生效条件：t" + chr(10) + chr(10) + "正文")


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


# 生效条件：in_values/oor_values 为 confidence 列表；建临时库（真 API 造节点+证据，
# 再文本改写 confidence 以模拟外部/legacy 越界来源），返回 (root, cg)。
def _mk_lib(in_values=(0.3, 0.5, 0.7, 0.9, 0.55, 0.65), oor_values=()):
    root = tempfile.mkdtemp(prefix="i121_guard_")
    _SANDBOXES.append(root)
    cg = MdCGOS(root)
    want = {}
    for i, c in enumerate(in_values):
        cg.add("in%d" % i, BODY, confidence=0.5, importance=0.5)
        cg.verify("in%d" % i, "e%d" % i, "confirmed")
        want["in%d" % i] = c
    for j, c in enumerate(oor_values):
        cg.add("oor%d" % j, BODY, confidence=0.5, importance=0.5)
        cg.verify("oor%d" % j, "e-oor%d" % j, "confirmed")
        want["oor%d" % j] = c
    cg.close()
    # verify() 会把 confidence +0.05（并夹到 [0,0.99]）⇒ 逐文件**文本改写**回目标值，
    # 使桶归属完全由本守卫指定（否则期望值要跟着 verify 的抖动走，判据变脆）。
    for nid, c in want.items():
        for dp, _dn, fns in os.walk(root):
            if nid + ".md" in fns:
                p = os.path.join(dp, nid + ".md")
                fm, content = nodefile_load(p)
                fm["confidence"] = c
                io.open(p, "w", encoding="utf-8", newline="").write(
                    nodefile_dumps(fm, content))
    return root, MdCGOS(root)


from . import nodefile as _nf                                # noqa: E402


def nodefile_load(p):
    return _nf.loads(io.open(p, encoding="utf-8").read())


def nodefile_dumps(fm, content):
    return _nf.dumps(fm, content)


# 生效条件：rep 为 calibration() 返回体、oor_ids 为本次构造的越界节点 id 集合；
# 返回违规描述列表（空列表=全部合规）。**这是本守卫的唯一判据函数**（变异打在此层之上）。
def violations(rep, oor_ids):
    bad = []
    nn = rep.get("n_nodes")
    sb = sum(b["n_nodes"] for b in rep.get("bins") or [])
    if "dropped" not in rep or "out_of_range" not in rep:
        bad.append("返回体缺 dropped/out_of_range 键（静默面未关闭）")
        return bad
    d = rep.get("dropped") or 0
    if nn != sb + d:
        bad.append("不变量破：n_nodes(%s) != Σbins(%s) + dropped(%s)" % (nn, sb, d))
    if rep.get("out_of_range") != d:
        bad.append("dropped 与 out_of_range 不等：%s vs %s"
                   % (d, rep.get("out_of_range")))
    ids = rep.get("dropped_ids")
    if not isinstance(ids, list):
        bad.append("dropped_ids 不是列表：%r" % (ids,))
    else:
        if d and "dropped_ids_truncated" not in rep:
            bad.append("缺 dropped_ids_truncated（截断不可观测）")
        if rep.get("dropped_ids_truncated") is False and len(ids) != d:
            bad.append("未截断但抽样数(%d) != dropped(%d)" % (len(ids), d))
        stray = [x for x in ids if x not in oor_ids]
        if stray:
            bad.append("抽样 id 不属于越界集合：%s" % stray)
    return bad


def g_invariant_and_trace():
    """G1/G2/G3 不变量 + 可追（3 条真越界）。"""
    root, cg = _mk_lib(oor_values=(-0.2, 1.5, 2.0, 0.0, 1.0, 0.99))
    try:
        rep = mc.calibration(cg)
        oor_ids = {"oor0", "oor1", "oor2"}          # -0.2 / 1.5 / 2.0
        bad = violations(rep, oor_ids)
        check("G1 不变量成立且可追（无违规）", not bad, bad)
        check("G2 dropped == 3（恰好三条越界）", rep.get("dropped") == 3,
              rep.get("dropped"))
        check("G3 dropped_ids 恰为三条越界 id（0.0/0.99/1.0 不算越界）",
              sorted(rep.get("dropped_ids") or []) == sorted(oor_ids),
              rep.get("dropped_ids"))
        check("G3b Σbins.n_nodes == 9（越界三条未入桶）",
              sum(b["n_nodes"] for b in rep.get("bins") or []) == 9,
              rep.get("bins"))
        check("G3c dropped_ids_truncated is False", rep.get("dropped_ids_truncated") is False,
              rep.get("dropped_ids_truncated"))
    finally:
        cg.close()


def g_edges_in_range():
    """G4 边界值 0.0 / 0.99 / 1.0 必须入桶（BINS 上界 1.01 覆盖）。"""
    root, cg = _mk_lib(in_values=(0.0, 0.99, 1.0, 0.5, 0.7, 0.8))
    try:
        rep = mc.calibration(cg)
        check("G4 全在域内 ⇒ dropped == 0", rep.get("dropped") == 0, rep.get("dropped"))
        check("G4b Σbins == n_nodes", sum(b["n_nodes"] for b in rep.get("bins") or [])
              == rep.get("n_nodes"), rep.get("bins"))
        check("G4c 0.8/0.99/1.0 三条落 0.8-1.01 桶",
              any(b["bin"] == "0.8-1.01" and b["n_nodes"] == 3
                  for b in rep.get("bins") or []), rep.get("bins"))
        check("G4d 无违规", not violations(rep, set()), "")
    finally:
        cg.close()


def g_sample_truncation():
    """G5 抽样上限：>DROPPED_SAMPLE_MAX 条越界 ⇒ 计数完整、列表截断且显式标出。"""
    n = mc.DROPPED_SAMPLE_MAX + 5
    root, cg = _mk_lib(in_values=(0.5, 0.6, 0.7, 0.8, 0.9),
                       oor_values=tuple([2.0] * n))
    try:
        rep = mc.calibration(cg)
        check("G5 dropped 计数完整 == %d" % n, rep.get("dropped") == n, rep.get("dropped"))
        check("G5b dropped_ids 截断到上限 %d" % mc.DROPPED_SAMPLE_MAX,
              len(rep.get("dropped_ids") or []) == mc.DROPPED_SAMPLE_MAX,
              len(rep.get("dropped_ids") or []))
        check("G5c dropped_ids_truncated is True", rep.get("dropped_ids_truncated") is True,
              rep.get("dropped_ids_truncated"))
        check("G5d 截断下不变量仍成立", not violations(rep, {"oor%d" % i for i in range(n)}), "")
    finally:
        cg.close()


def g_insufficient_shape():
    """G6 insufficient_data 分支形状稳定（也含 dropped 三键）。"""
    root, cg = _mk_lib(in_values=(), oor_values=())
    try:
        rep = mc.calibration(cg)
        check("G6 无样本 ⇒ ok False / insufficient_data",
              rep.get("ok") is False and rep.get("reason") == "insufficient_data", rep)
        check("G6b 该分支同样含 dropped/out_of_range/dropped_ids 三键",
              all(k in rep for k in ("dropped", "out_of_range", "dropped_ids")),
              sorted(rep))
    finally:
        cg.close()


def g_ece_caliber_locked():
    """G7 口径钉：手算 ECE（只由入桶节点贡献）== 返回值 ⇒ 修法未改口径。"""
    root, cg = _mk_lib(oor_values=(-0.2, 1.5, 2.0))
    try:
        rep = mc.calibration(cg)
        want = 0.0
        for b in rep.get("bins") or []:
            n_ev = b["n_evidence"]
            want += (n_ev / rep["n_evidence"]) * abs(b["confidence"] - b["accuracy"])
        check("G7 手算 ECE（入桶口径）== 返回值 %s" % rep.get("ece"),
              round(want, 4) == rep.get("ece"), (round(want, 4), rep.get("ece")))
        check("G7b 越界三条不进任何桶（Σbins == 6，与 n_nodes 9 差 3）",
              sum(b["n_nodes"] for b in rep.get("bins") or []) == 6, rep.get("bins"))
    finally:
        cg.close()


_CASES = (g_invariant_and_trace, g_edges_in_range, g_sample_truncation,
          g_insufficient_shape, g_ece_caliber_locked)


def _run_all():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    for fn in _CASES:
        try:
            fn()
        except Exception as exc:                            # noqa: BLE001
            check(False, "%s 组抛异常：%s: %s" % (fn.__name__, type(exc).__name__, exc))
    return list(FAILS)


# 生效条件：无入参；对同一库跑「真实现 vs 三个破坏契约的替身」，断言判据函数逐条转红；返回失败条数。
def _run_mutations():
    print(chr(10) + "=== 定点变异自证（变异前 → 变异后）===")
    root, cg = _mk_lib(oor_values=(-0.2, 1.5, 2.0))
    try:
        rep0 = mc.calibration(cg)
        oor_ids = {"oor0", "oor1", "oor2"}
        base = violations(rep0, oor_ids)
        print("  [基线] 变异前违规项 = %s（应为空）" % (base or "无"))
        def _shim_drop0(rep):
            r = dict(rep)
            r["dropped"] = 0
            r["out_of_range"] = 0
            r["dropped_ids"] = []
            return r

        def _shim_drop_plus1(rep):
            r = dict(rep)
            r["dropped"] = (rep.get("dropped") or 0) + 1
            r["out_of_range"] = r["dropped"]
            return r

        def _shim_double_count(rep):
            r = dict(rep)
            bins = [dict(b) for b in rep.get("bins") or []]
            if bins:
                bins[0]["n_nodes"] += rep.get("dropped") or 0
            r["bins"] = bins
            return r

        cases = (
            ("M1 dropped/out_of_range 恒 0（越界被静默）", _shim_drop0),
            ("M2 dropped 虚报 +1（计数不守恒）", _shim_drop_plus1),
            ("M3 越界节点被塞进首桶且 dropped 照记（重复计数）", _shim_double_count),
        )
        bad = 0
        for label, shim in cases:
            got = violations(shim(rep0), oor_ids)
            hit = bool(got)
            if not check(label, hit, "变异后违规项为空 ⇒ 判据无判别力"):
                bad += 1
            print("        变异前：违规项=[] ｜ 变异后：违规项=%d 项 %s ⇒ %s"
                  % (len(got), got[:2], "命中" if hit else "未命中"))
        print("  变异自证结论：%s" % ("全部按预期转红" if bad == 0
                                  else "存在 %d 条未按预期" % bad))
        return bad
    finally:
        cg.close()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="#121 calibration 越界守卫")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    a = ap.parse_args()
    print("[1] 判据面")
    reds = _run_all()
    rc = 1 if reds else 0
    if a.mutate:
        rc = 1 if (_run_mutations() or reds) else 0
    print(chr(10) + "SUMMARY: #121 calibration 越界守卫：%d 通过，%d 失败%s"
          % (PASS, FAIL, ("；失败项=" + "; ".join(FAILS)) if FAILS else ""))
    for d in _SANDBOXES:
        shutil.rmtree(d, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
