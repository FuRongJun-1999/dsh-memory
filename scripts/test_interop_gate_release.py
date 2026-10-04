# -*- coding: utf-8 -*-
"""test_interop_gate_release —— N252 互验门禁「放行判据」守卫（唯一放行态＝断言 AND 套件皆过）

背景（2026-10-05 缺陷 N252，severity=high）：`scripts/interop_gate.py` 的 docstring
:8-12 承诺 exit 0 的唯一放行态是「verdict==pass 且 valid==True（断言 AND 套件皆过）」，
但 :73 的放行判据只查 verdict/valid **两项**，把同一契约里断言面与套件面的三个字段
（`assertions_ok` / `failed` / `failure_reason`）整体丢掉；`_load` :41-53 又漏了
`verdict` 的**类型闸**。后果两条：
  · 自相矛盾 verdict 被放行：生产端公开 API `md_cg/interop.py:220`
    `make_verdict(verdict='pass', failed=1)` 经 sanity+shape **双门禁正常产出**
    `verdict=pass / valid=True / assertions_ok=False / failure_reason='assertions_failed'
    / passed=9 / failed=1`（本轮实测，见 G0），喂给本门禁 → 修前 **exit 0（放行）**，
    且 stdout 自己就打印着 `failed=1`。即「被批准的产出路径即可造出被放行的非放行态」，
    §7.4「门禁 FAIL 一律不得合并」在断言面整体失守。
  · docstring :8-12 的三态只兑现 0 一态：`verdict=123`（类型不对）→ 修前 exit 1，而
    :12 承诺「类型不对」= exit 3（拒绝解析而不是猜测）。
  （v26 台账 `docs/eval/缺陷挖掘_自主迭代_v26.md` 条目 16 / 要点补记 11 已留档同一
  where 同一缺陷、无 N 号：『门禁只兑现 docstring 三判据之一（`failure_reason` 非空→
  exit 1、`verdict` 类型非法→exit 3 均未实现），自相矛盾 verdict 被放行』——本轮补号修复。）

守卫断言面（全哑数据；生产端腿调真实公开 API 复算，不依赖任何在役产物）：
  G0 前提坐实：make_verdict(verdict='pass', failed=1) 的五字段如上，且过 sanity+shape 双门禁
  G1 生产端 E2E：G0 产物落盘 → 门禁 exit 1（修前 0），stdout 点名 assertions_ok 阻因
  G2 生产端真放行：make_verdict(verdict='pass', failed=0) → exit 0（不误伤放行态）
  G3 套件面败：make_verdict(verdict='fail', passed=9, failed=0)（valid=False /
     assertions_ok=True / failure_reason='suite_failed'）→ exit 1
  G4 手写腿·failure_reason 非空而其余全绿 → exit 1（修前 0）
  G5 手写腿·failed 非 0 而其余全绿 → exit 1（修前 0）
  G6 verdict 类型闸：123 / null / ["pass"] → exit 3（修前 1；docstring :12 的形状非法态）
  G7 阻因可见：非放行态 stdout 含阻因行并点名字段（修前无）
  G8 既有三态契约不破：缺产物 → 2；顶层非对象 / 缺字段 / 计数为 bool → 3
  G9 既有守卫回归：`python scripts/test_gate_json_shape.py`（N217，S1–S7）全绿

运行：python -X utf8 scripts/test_interop_gate_release.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

# 生产端公开 API（只读导入：实测无任何落盘副作用）
from md_cg.interop import (  # noqa: E402
    InteropSanityError, make_verdict, sanity_check_verdict, shape_check_verdict)

_GATE = os.path.join(HERE, "scripts", "interop_gate.py")
_SHAPE_GUARD = os.path.join(HERE, "scripts", "test_gate_json_shape.py")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  "
              + str(detail).replace("\n", " | ")[:400])


def _env():
    return dict(os.environ, PYTHONUTF8="1")


def _run(argv):
    return subprocess.run([sys.executable, "-X", "utf8"] + argv,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_env(), cwd=HERE, timeout=300)


def _gate(path):
    return _run([_GATE, "--path", path])


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)


def _produced(**kw):
    """经生产端公开 API 造 verdict（本轮全部哑数据；指纹为哑十六进制）。"""
    return make_verdict(iter_id="iter-n252", verifier_instance="inst-a",
                        verifier_fingerprint="a" * 12,
                        subject_instance="inst-b", subject_fingerprint="b" * 12,
                        suite_origin="runner", frozen_at="2026-10-05T00:00:00Z",
                        **kw)


#: 唯一放行态（与 docstring :8-12 逐字段对应）
_RELEASE = {"verdict": "pass", "valid": True, "assertions_ok": True,
            "failure_reason": None, "passed": 9, "failed": 0}


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with tempfile.TemporaryDirectory() as tmp:
        vp = os.path.join(tmp, "verdict.json")

        print("[1] 前提坐实：被批准的产出路径可造出自相矛盾 verdict")
        contra = _produced(verdict="pass", passed=9, failed=1)
        fields = {k: contra.get(k) for k in ("verdict", "valid", "assertions_ok",
                                            "failure_reason", "passed", "failed")}
        check("G0 生产端五字段 = pass/True/False/assertions_failed/9/1",
              fields == {"verdict": "pass", "valid": True, "assertions_ok": False,
                         "failure_reason": "assertions_failed", "passed": 9,
                         "failed": 1}, fields)
        try:
            sanity_check_verdict(contra)
            shape_check_verdict(contra)
            ok_shape = True
        except InteropSanityError as exc:
            ok_shape = False
            check("G0 该产物过 sanity+shape 双门禁", False, str(exc))
        else:
            check("G0 该产物过 sanity+shape 双门禁", ok_shape)

        print("[2] 放行判据：五条件合取（唯一放行态）")
        _write(vp, contra)
        got = _gate(vp)
        check("G1 生产端自相矛盾 verdict → exit 1（修前 exit 0 放行）",
              got.returncode == 1, "rc=%s | %s" % (got.returncode, got.stdout))
        check("G1 stdout 点名断言面阻因",
              "assertions_ok" in (got.stdout or ""), got.stdout)

        _write(vp, _produced(verdict="pass", passed=9, failed=0))
        got = _gate(vp)
        check("G2 生产端真放行态 → exit 0（不误伤）", got.returncode == 0,
              "rc=%s | %s" % (got.returncode, got.stdout))

        _write(vp, _produced(verdict="fail", passed=9, failed=0))
        got = _gate(vp)
        check("G3 套件面败（valid=False/failure_reason=suite_failed）→ exit 1",
              got.returncode == 1, "rc=%s | %s" % (got.returncode, got.stdout))

        print("[3] 逐字段收紧（手写腿，各只坏一处）")
        _write(vp, dict(_RELEASE, failure_reason="both"))
        got = _gate(vp)
        check("G4 failure_reason 非空而其余全绿 → exit 1（修前 0）",
              got.returncode == 1, "rc=%s | %s" % (got.returncode, got.stdout))

        _write(vp, dict(_RELEASE, failed=1))
        got = _gate(vp)
        check("G5 failed 非 0 而其余全绿 → exit 1（修前 0）",
              got.returncode == 1, "rc=%s | %s" % (got.returncode, got.stdout))

        _write(vp, dict(_RELEASE, assertions_ok=False))
        got = _gate(vp)
        check("G5 assertions_ok=False 而其余全绿 → exit 1（修前 0）",
              got.returncode == 1, "rc=%s | %s" % (got.returncode, got.stdout))
        check("G7 阻因行可见并点名该字段",
              "阻因" in (got.stdout or "") and "assertions_ok" in (got.stdout or ""),
              got.stdout)

        print("[4] verdict 类型闸（docstring :12 的形状非法态 = 3）")
        for val, label in ((123, "verdict=123"), (None, "verdict=null"),
                           (["pass"], 'verdict=["pass"]')):
            _write(vp, dict(_RELEASE, verdict=val))
            got = _gate(vp)
            check("G6 %s → exit 3（修前 exit 1）" % label, got.returncode == 3,
                  "rc=%s | %s" % (got.returncode, got.stdout))

        print("[5] 既有三态契约不破（缺产物 2 / 形状非法 3）")
        missing = os.path.join(tmp, "nope.json")
        got = _gate(missing)
        check("G8 缺产物 → exit 2（fail-closed）", got.returncode == 2, got.stdout)
        for obj, label in (([1, 2], "顶层数组"), ('"x"', "顶层字符串"),
                           ({"verdict": "pass"}, "缺契约字段"),
                           (dict(_RELEASE, passed=True), "passed 为 bool")):
            with open(vp, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(obj))
            got = _gate(vp)
            check("G8 %s → exit 3" % label, got.returncode == 3,
                  "rc=%s | %s" % (got.returncode, got.stdout))

    print("[6] 既有守卫回归：test_gate_json_shape（N217 的 S1–S7）")
    got = _run([_SHAPE_GUARD])
    check("G9 test_gate_json_shape 全绿", got.returncode == 0,
          (got.stdout or "")[-500:])

    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
