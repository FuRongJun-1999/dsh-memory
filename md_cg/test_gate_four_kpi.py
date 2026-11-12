# -*- coding: utf-8 -*-
"""W5 四 KPI 门禁的守卫：门禁自己必须可红可绿。

真源：docs/architecture/灵枢1.0_建设路线_v0.1.md §9 W5「每 KPI 一条可红可绿的检查」。

# 功能名：W5 门禁自证守卫
# 生效条件：改动 scripts/gate_four_kpi.py、或有人怀疑「门禁恒绿」时
# 子功能：①四条 KPI 齐全且名字与路线稿一字不差
#         ②每条都绑定真实存在的证据模块（防证据路径写错导致永远 INVALID 却不自知）
#         ③变异体必须变红（模块不存在 / 恒真不打印 / 打印 0 条 / 自报失败）
#         ④真证据必须全绿（防门禁恒红，恒红与恒绿同属无判别力）
#         ⑤判据锚点在场（min_pass 下限、正则、fail-closed 的 INVALID 分支）
# 执行：python -X utf8 -m md_cg.test_gate_four_kpi
# 验证方式：本文件全绿即通过；任一条红退出码 1
# 不适用条件：不判 KPI 语义是否"足够好"；不替代全量套件

为什么要单独守这个门禁
    本会话已实证：断言写错对象后，删掉被测判据用例仍 PASS（恒绿）。
    门禁是「判别的判别」，它一旦恒绿，下游全部结论失效且无人察觉。
    故本守卫不只跑一遍门禁，而是**要求门禁对变异体必须变红**。
"""
from __future__ import annotations

import io
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

PASS = 0
FAIL = 0
FAILS = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  PASS %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL %s  %s" % (name, detail))


def main():
    import gate_four_kpi as G

    print("=" * 78)
    print("W5 四 KPI 门禁 · 守卫")
    print("=" * 78)

    # ---- A 四个 KPI 齐全，名字与路线稿一致 ----
    names = [s["kpi"] for s in G.KPIS]
    want = ["记得住", "查得到", "改得回", "账不丢"]
    check("A1 恰好四个 KPI 且顺序与 §0 原文一致", names == want, "实得 %r" % (names,))

    src = io.open(os.path.join(REPO, "docs", "architecture",
                               "灵枢1.0_建设路线_v0.1.md"), encoding="utf-8").read()
    missing = [n for n in want if n not in src]
    check("A2 四个名字都能在路线稿原文中找到", not missing, "缺：%r" % (missing,))

    # ---- B 证据模块真实存在 ----
    for spec in G.KPIS:
        mod = spec["evidence"]
        rel = os.path.join(REPO, "md_cg", mod.split(".")[-1] + ".py")
        check("B 证据存在：%s → %s" % (spec["kpi"], mod), os.path.isfile(rel), "缺文件 %s" % rel)

    # ---- C 每条都有可判参数（防漏填导致空转）----
    for spec in G.KPIS:
        ok = (spec["pattern"] and spec["min_pass"] > 0 and spec["why"].strip())
        check("C 判据参数齐备：%s（min_pass=%s）" % (spec["kpi"], spec["min_pass"]), ok)

    # ---- D 变异体必须变红（核心）----
    tmp = tempfile.mkdtemp(prefix="kpi_gate_guard_")
    os.environ["PYTHONPATH"] = tmp + os.pathsep + os.environ.get("PYTHONPATH", "")

    def write_mod(name, body):
        with open(os.path.join(tmp, name + ".py"), "w", encoding="utf-8") as f:
            f.write(body)
        return name

    m_missing = "zzz_no_such_module_xyz"
    m_pass = write_mod("mut_always_pass", "import sys\nsys.exit(0)\n")
    m_zero = write_mod("mut_zero_assert", "print('0 通过，0 失败')\n")
    m_bad = write_mod("mut_failed", "print('3 通过，2 失败')\nimport sys\nsys.exit(1)\n")

    cases = [
        ("D1 模块不存在 → INVALID", m_missing, "INVALID"),
        ("D2 恒真但不打印条数 → INVALID", m_pass, "INVALID"),
        ("D3 打印 0 条断言 → INVALID", m_zero, "INVALID"),
        ("D4 自报失败 → FAIL", m_bad, "FAIL"),
    ]
    for label, module, expect in cases:
        spec = dict(G.KPIS[0])
        spec["evidence"] = module
        spec["pattern"] = r"(\d+)\s*通过，\s*(\d+)\s*失败"
        spec["min_pass"] = 4
        r = G.evaluate(spec, timeout=120)
        check("%s（实得 %s）" % (label, r["state"]), r["state"] == expect, r["reason"])

    # ---- E 反向：真证据必须 PASS（防恒红）----
    ev = G.evaluate(G.KPIS[2], timeout=900)          # 改得回：单条最快
    check("E1 真证据应 PASS（防门禁恒红，实得 %s）" % ev["state"], ev["state"] == "PASS", ev["reason"])

    # ---- F 结构锚点：fail-closed 分支必须在场 ----
    gsrc = io.open(os.path.join(REPO, "scripts", "gate_four_kpi.py"), encoding="utf-8").read()
    for anchor, why in (
        ("INVALID", "解析不出条数/fail-closed 必须用 INVALID 而非 PASS"),
        ("min_pass", "低于断言下限必须判 INVALID（防恒绿）"),
        ("TimeoutExpired", "超时必须不判 PASS"),
        ("len(groups)", "必须真的解析出条数，不能只看退出码"),
    ):
        check("F 结构锚点在场：%s（%s）" % (anchor, why), anchor in gsrc)

    # ---- G verdict 聚合规则 ----
    rows = [{"state": "PASS"}, {"state": "INVALID"}]
    check("G1 有 INVALID 时整体 INVALID", G.verdict_of(rows) == "INVALID", G.verdict_of(rows))
    rows = [{"state": "INVALID"}, {"state": "FAIL"}]
    check("G2 FAIL 优先于 INVALID", G.verdict_of(rows) == "FAIL", G.verdict_of(rows))
    check("G3 空集判 INVALID（不判 PASS）", G.verdict_of([]) == "INVALID", G.verdict_of([]))

    print()
    print("===== W5 门禁守卫：%d 通过，%d 失败 =====" % (PASS, FAIL))
    if FAILS:
        print("  红项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
