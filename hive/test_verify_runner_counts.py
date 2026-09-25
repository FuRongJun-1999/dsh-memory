# -*- coding: utf-8 -*-
"""互验执行器套件计数门守卫（N9：suite_ok 不要求 passed>0，空跑全绿写 pass）。

背景（v2 首报，历轮零修复）：verify_runner.py:160 判定式
`suite_ok = rc_cargo == 0 and rc_py == 0 and failed == 0`——passed 算出后
不参与判定。run_tests.py 输出措辞漂移或套件静默退出 0 时，_parse_counts
（:52-69）对空输出/无计数命中返回 (0,0)，空跑组合 rc=0/0 + failed=0 判
suite_ok=True，_compose_semantics(:77-85) 产出 verdict="pass"——验证器
空跑全绿以 pass 写 verdict.json，「未验证不写入」第 5 条语义被空跑绕过，
未经任何真实验证的代码获得入库凭证。

修法（一处）：:160 判定式补 `and passed > 0`。--smoke 探针（:151-156）
打印 '3 passed'/'4 passed' 合计 passed=7，补门不误伤冒烟模式。

本测试（REPO 钉临时区 + _run 桩注入哑输出，绝不跑真 cargo/run_tests、
不触真实 hive/interop/）：
  [A] _parse_counts 单元：空串 (0,0)；smoke 形态合计 7；cargo/SUMMARY 形态
  [B] 空跑端到端：_run 桩 (0,"","")×2 → verdict 须 "fail"+suite_failed
      （旧代码 "pass" → 红=空跑绕过成立）
  [C] 冒烟形态对照：_run 桩注入 '3 passed'/'4 passed' → verdict "pass"
      （补门不误伤 --smoke；修前修后均绿）
  [D] 失败零回归：rc_py=1 → verdict "fail"（修前修后均绿）
  [E] 源断言：判定式含 passed > 0
运行：python -X utf8 -m hive.test_verify_runner_counts   （退出码 0 = 全绿）
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from unittest import mock

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
        return
    FAIL += 1
    print(f"  [FAIL] {name}  {detail}")


def _load(mod_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vr = _load("hive_verify_runner_n9", "verify_runner.py")

TMP = tempfile.mkdtemp(prefix="hive_n9_")


def _run_main(results, iter_id="iter_n9_probe"):
    """在钉死的临时 REPO + 桩 _run 下真跑 vr.main，回读 verdict.json。

    results: [(rc, stdout, stderr), ...] 依次喂给 cargo/run_tests 两次 _run。
    断言函数桩全 ok：隔离出纯套件面（被测即 suite 门）。
    """
    area = tempfile.mkdtemp(prefix="hive_n9_repo_", dir=TMP)
    itdir = os.path.join(area, "hive", "interop", iter_id)
    os.makedirs(itdir, exist_ok=True)
    with open(os.path.join(itdir, "frozen.json"), "w", encoding="utf-8") as f:
        json.dump({"frozen_at": "2026-09-26T00:00:00Z"}, f)
    queue = list(results)

    def fake_run(cmd, timeout_s):
        return queue.pop(0) if queue else (0, "", "")

    vr_assert = {"ok": True, "note": "stub-ok-isolates-suite-gate"}
    with mock.patch.object(vr, "REPO", area), \
            mock.patch.object(vr, "_run", fake_run), \
            mock.patch.object(vr, "assert_a1", return_value=dict(vr_assert)), \
            mock.patch.object(vr, "assert_a2", return_value=dict(vr_assert)), \
            mock.patch.object(vr, "assert_a3", return_value=dict(vr_assert)), \
            mock.patch.dict(os.environ, {
                "HIVE_ROLE": "verifier", "HIVE_INSTANCE": "verifier",
                "SUBJECT_FP": "e" * 64}):
        rc = vr.main(["verify_runner.py", iter_id])
    out_fp = os.path.join(itdir, "verdict.json")
    with open(out_fp, encoding="utf-8") as f:
        return rc, json.load(f)


# ------------------------------------------------------------- [A] 解析单元
print("[A] _parse_counts 计数形态单元")
check("A1 空串 → (0,0)（空跑计数前提）",
      vr._parse_counts("") == (0, 0), f"got {vr._parse_counts('')!r}")
check("A2 smoke 探针形态 '3 passed'+'4 passed' → (7,0)（补门不误伤前提）",
      vr._parse_counts("3 passed\n4 passed") == (7, 0),
      f"got {vr._parse_counts('3 passed\n4 passed')!r}")
check("A3 cargo 形态 → (25,0)",
      vr._parse_counts("test result: ok. 25 passed; 0 failed") == (25, 0))
check("A4 run_tests SUMMARY 形态 → (189,0)",
      vr._parse_counts("===== SUMMARY 189/189 通过，0 跳过（d=dyn） =====")
      == (189, 0))

# --------------------------------------------------- [B] 空跑端到端（核心红）
print("[B] 空跑端到端：双套件静默退出 0 且零计数 → 不得以 pass 入库")
rc_b, v_b = _run_main([(0, "", ""), (0, "", "")])
check("B1 main 返回 0（留痕写盘不炸）", rc_b == 0, f"rc={rc_b}")
check("B2 verdict != pass（旧代码空跑判 pass → 红）",
      v_b.get("verdict") == "fail",
      f"got verdict={v_b.get('verdict')!r} passed={v_b.get('passed')}")
check("B3 valid=假（放行位与 verdict 同义）", v_b.get("valid") is False,
      f"got {v_b.get('valid')!r}")
check("B4 failure_reason=suite_failed（J3 结构化归因）",
      v_b.get("failure_reason") == "suite_failed",
      f"got {v_b.get('failure_reason')!r}")
check("B5 passed=0 如实入库", v_b.get("passed") == 0,
      f"got {v_b.get('passed')!r}")

# ------------------------------------------------- [C] 冒烟形态对照（不误伤）
print("[C] 冒烟形态对照：'3 passed'/'4 passed' 合计 7 → verdict pass")
rc_c, v_c = _run_main([(0, "3 passed", ""), (0, "4 passed", "")],
                      iter_id="iter_n9_smoke")
check("C1 smoke 形态 verdict=pass（passed=7>0 过门）",
      rc_c == 0 and v_c.get("verdict") == "pass" and v_c.get("valid") is True,
      f"rc={rc_c} verdict={v_c.get('verdict')!r} passed={v_c.get('passed')}")

# ------------------------------------------------------- [D] 失败零回归
print("[D] 失败零回归：run_tests rc=1 → verdict fail")
rc_d, v_d = _run_main([(0, "10 passed", ""), (1, "5 passed 1 failed", "")],
                      iter_id="iter_n9_fail")
check("D1 rc=1 → verdict=fail 且 failure_reason=suite_failed",
      rc_d == 0 and v_d.get("verdict") == "fail"
      and v_d.get("failure_reason") == "suite_failed",
      f"rc={rc_d} verdict={v_d.get('verdict')!r} "
      f"reason={v_d.get('failure_reason')!r}")

# ------------------------------------------------------------- [E] 源断言
print("[E] 源断言：判定式含 passed > 0 门")
with open(os.path.join(_HERE, "verify_runner.py"), encoding="utf-8") as f:
    SRC = f.read()
_i = SRC.find("suite_ok =")
check("E1 suite_ok 判定式补 passed > 0（跨行形态亦命中）",
      _i != -1 and "passed > 0" in SRC[_i:_i + 160],
      f"判定式片段={SRC[_i:_i + 160]!r}" if _i != -1 else "未找到 suite_ok =")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n结果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
