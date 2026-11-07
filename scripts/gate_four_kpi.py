# -*- coding: utf-8 -*-
"""灵枢 1.0 · W5 四个 KPI 门禁（每个 KPI 一条可红可绿的检查）。

真源：docs/architecture/灵枢1.0_建设路线_v0.1.md
  §0  「记得住、查得到、改得回、账不丢」
  §9  W5「四个 KPI 门禁脚本 | 每 KPI 一条可红可绿的检查」
  §1  目标③「四个 KPI 各有可判门禁」

# 功能名：W5 四 KPI 门禁
# 生效条件：需要判断 1.0 的四个 KPI 当前成不成立、以及改动有没有把它们弄坏时
# 子功能：①四 KPI 各绑一条既有证据（不新写断言，复用现存守卫）
#         ②「可红可绿」由 --selftest 自证——变异体必须变红
#         ③拒绝「恒绿」：解析证据的**断言条数**而非只看退出码
# 执行：python -X utf8 scripts/gate_four_kpi.py [--json] [--selftest] [--only NAME]
# 验证方式：--selftest 逐条打断证据，门禁必须报红
# 不适用条件：不判 KPI 的语义是否"足够好"（只判它此刻成不成立）；
#             不替代全量套件（run_tests.py 才是全量）

为什么不能只看退出码
    本会话已实证过一类事故：断言写错对象后，删掉被测判据用例仍 PASS（恒绿）。
    只看 returncode 无法区分「真通过」与「没断言」。故本门禁额外要求解析出
    **通过的断言条数 > 0**，否则判 INVALID（红），而不是 PASS。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

#: 四个 KPI：名字取自路线稿 §0 原文，不得自行改写。
#: 每条必须给出：证据模块、输出里「通过条数」的正则、最小可接受条数。
KPIS = (
    {
        "kpi": "记得住",
        "question": "写下去的东西，重启后还在不在？",
        "evidence": "md_cg.test_issue470_wal_event_durable",
        "why": "WAL 事件行 durable：sync_data 在轮末快照写入之前，事件行不依赖 no-op 的 flush()",
        "pattern": r"(\d+)\s*通过，\s*(\d+)\s*失败",
        "min_pass": 4,
    },
    {
        "kpi": "查得到",
        "question": "记下来的东西，检索能不能命中？",
        "evidence": "md_cg.test_recall_metadata",
        "why": "回忆面的元数据/可见性/资格判定守卫（unittest，按 run 数计）",
        "pattern": r"Ran (\d+) tests?",
        "min_pass": 5,
    },
    {
        "kpi": "改得回",
        "question": "改错了能不能逐字节回到改之前？",
        "evidence": "md_cg.test_mutation_rollback",
        "why": "变更单回滚面：C 改写入/B 合并/D 删除三类各演一次，回滚后盘面逐字节 == 执行时点前像",
        "pattern": r"(\d+)\s*通过，\s*(\d+)\s*失败",
        "min_pass": 20,
    },
    {
        "kpi": "账不丢",
        "question": "审计台账能不能证明自己没被动过？",
        "evidence": "md_cg.test_issue472_audit_chain",
        "why": "哈希链审计：链内改行/截断尾行/未知链外插入判硬失败，已知退化判软信号，空文件不误红",
        "pattern": r"PASS (\d+) / FAIL (\d+)",
        "min_pass": 5,
    },
)


def run_evidence(module, timeout=900):
    """跑一条证据模块，返回 (ok, detail, passed_count, failed_count)。

    fail-closed：超时、import 失败、输出解析不出条数，一律不判 PASS。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        p = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", module],
            cwd=REPO, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "超时（%ds）——不判 PASS" % timeout, 0, 0
    except Exception as exc:                              # noqa: BLE001
        return False, "无法执行：%s" % exc, 0, 0

    out = (p.stdout or b"").decode("utf-8", "replace")
    return p.returncode, out, 0, 0


def evaluate(spec, timeout=900):
    rc, out, _, _ = run_evidence(spec["evidence"], timeout=timeout)
    if not isinstance(out, str):
        return {"kpi": spec["kpi"], "state": "INVALID", "reason": out,
                "passed": 0, "failed": 0, "rc": None}

    m = re.search(spec["pattern"], out)
    if not m:
        tail = "\n".join(out.strip().splitlines()[-4:])
        return {"kpi": spec["kpi"], "state": "INVALID",
                "reason": "输出里解析不出断言条数（正则 `%s` 未命中）——不判 PASS；尾部：%s"
                          % (spec["pattern"], tail),
                "passed": 0, "failed": 0, "rc": rc}

    groups = [int(g) for g in m.groups() if g is not None and g.isdigit()]
    passed = groups[0] if groups else 0
    failed = groups[1] if len(groups) > 1 else 0

    if failed:
        return {"kpi": spec["kpi"], "state": "FAIL",
                "reason": "证据自报 %d 条失败" % failed,
                "passed": passed, "failed": failed, "rc": rc}

    if rc != 0:
        return {"kpi": spec["kpi"], "state": "FAIL",
                "reason": "证据退出码 %s" % rc,
                "passed": passed, "failed": failed, "rc": rc}

    if passed < spec["min_pass"]:
        return {"kpi": spec["kpi"], "state": "INVALID",
                "reason": "只跑出 %d 条断言（下限 %d）——疑似恒绿，不判 PASS"
                          % (passed, spec["min_pass"]),
                "passed": passed, "failed": failed, "rc": rc}

    return {"kpi": spec["kpi"], "state": "PASS", "reason": "证据 %d 条全绿" % passed,
            "passed": passed, "failed": failed, "rc": rc}


def run_all(timeout=900, only=None):
    rows = []
    for spec in KPIS:
        if only and spec["kpi"] != only:
            continue
        rows.append(evaluate(spec, timeout=timeout))
    return rows


def verdict_of(rows):
    if any(r["state"] == "FAIL" for r in rows):
        return "FAIL"
    if any(r["state"] == "INVALID" for r in rows):
        return "INVALID"
    if not rows:
        return "INVALID"
    return "PASS"


def selftest():
    """自证「可红」：把证据模块换成一个不存在的名字，门禁必须转红。

    只证明「门禁会红」还不够——本会话已见过「改旁坐常量仍恒绿」的事故。
    故这里逐条打四种变异，全部必须红：
      M1 证据模块不存在           → INVALID
      M2 证据模块恒真但不打印条数  → INVALID（解析不出条数）
      M3 证据模块打印 0 条断言     → INVALID（低于下限）
      M4 证据模块打印失败          → FAIL
    外加一条反向：真证据必须 PASS（否则门禁恒红，同样无判别力）。
    """
    import tempfile

    tmp = tempfile.mkdtemp(prefix="kpi_gate_selftest_")
    results = []

    def write_mod(name, body):
        p = os.path.join(tmp, name + ".py")
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        return name

    os.environ["PYTHONPATH"] = tmp + os.pathsep + os.environ.get("PYTHONPATH", "")

    write_mod("mut_always_pass", "import sys\nsys.exit(0)\n")
    write_mod("mut_zero_assert", "print('0 通过，0 失败')\n")
    write_mod("mut_failed", "print('3 通过，2 失败')\nimport sys\nsys.exit(1)\n")

    cases = [
        ("M1 证据模块不存在", "mut_does_not_exist_xyz", "INVALID"),
        ("M2 恒真但不打印条数", "mut_always_pass", "INVALID"),
        ("M3 打印 0 条断言", "mut_zero_assert", "INVALID"),
        ("M4 证据自报失败", "mut_failed", "FAIL"),
    ]

    for label, module, expect in cases:
        spec = dict(KPIS[0])
        spec["evidence"] = module
        spec["pattern"] = r"(\d+)\s*通过，\s*(\d+)\s*失败"
        spec["min_pass"] = 4
        r = evaluate(spec, timeout=120)
        ok = r["state"] == expect
        results.append((label, expect, r["state"], ok))

    # 反向：真证据必须 PASS（防门禁恒红）
    r0 = evaluate(KPIS[2], timeout=600)          # 改得回：最快的一条
    results.append(("R 真证据应 PASS（防恒红）", "PASS", r0["state"], r0["state"] == "PASS"))

    print("=" * 78)
    print("W5 门禁自证：变异体必须变红，真证据必须变绿")
    print("=" * 78)
    bad = 0
    for label, expect, got, ok in results:
        print("  %-34s 期望 %-8s 实得 %-8s %s"
              % (label, expect, got, "ok" if ok else "<<< 不达标"))
        if not ok:
            bad += 1
    print()
    print("  %d/%d 达标" % (len(results) - bad, len(results)))
    return 0 if bad == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--only", default=None, help="只跑某个 KPI（名字见 KPIS）")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    rows = run_all(timeout=a.timeout, only=a.only)
    v = verdict_of(rows)

    if a.json:
        print(json.dumps({"verdict": v, "kpis": rows}, ensure_ascii=False, indent=1))
    else:
        print("=" * 78)
        print("灵枢 1.0 · 四个 KPI 门禁")
        print("=" * 78)
        for spec, r in zip([s for s in KPIS if not a.only or s["kpi"] == a.only], rows):
            print("  [%s] %s —— %s" % (r["state"], r["kpi"], spec["question"]))
            print("        证据：%s" % spec["evidence"])
            print("        判据：%s" % spec["why"])
            print("        读数：%s" % r["reason"])
            print()
        print("  VERDICT=%s" % v)

    return 0 if v == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
