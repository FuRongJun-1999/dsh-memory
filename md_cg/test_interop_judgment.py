# -*- coding: utf-8 -*-
"""test_interop_judgment —— 互验执行链判据强度守卫（issue #37 六项）

J1  valid=单一放行位（断言 AND 套件）——套件全挂时必须 False
J2  A2 标注 self-reported；伪造 subject_fp 不影响 A3（承重墙输入不含自报值）
J3  failure_reason 枚举四象限结构化
J4  interop_gate 机械消费方三态（pass 放行 / fail 拒绝 / 缺产物 fail-closed）
J5  脱敏黑名单扩面（UNC/unix/~/$HOME/密钥形态/Bearer/文本形态）+ 形状白名单
J6  freeze 显式 out_dir 警告（不被 runner 识别）

运行：python -X utf8 -m md_cg.test_interop_judgment
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from md_cg.interop import (                        # noqa: E402
    InteropSanityError, assert_a2, assert_a3, freeze,
    make_verdict, sanity_check_verdict, shape_check_verdict)

_spec = importlib.util.spec_from_file_location(
    "verify_runner", os.path.join(HERE, "hive", "verify_runner.py"))
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:200])


def _mk(a_ok, suite_ok):
    return vr._compose_semantics(a_ok, suite_ok)


def main():
    print("[1] J1/J3：verdict 语义四象限")
    v, valid, a_ok, fr = _mk(True, True)
    check("全过 → pass/valid=True/reason=None",
          v == "pass" and valid and a_ok and fr is None)
    v, valid, a_ok, fr = _mk(True, False)
    check("断言过+套件挂 → fail/valid=False/assertions_ok=True/reason=suite_failed"
          "（#37 实测形态：套件全挂时 valid 必须不再是 true）",
          v == "fail" and valid is False and a_ok is True
          and fr == "suite_failed")
    v, valid, a_ok, fr = _mk(False, True)
    check("断言挂+套件过 → reason=assertions_failed",
          v == "fail" and valid is False and a_ok is False
          and fr == "assertions_failed")
    v, valid, a_ok, fr = _mk(False, False)
    check("双挂 → reason=both", v == "fail" and fr == "both")

    print("[2] J2：A2 self-reported 分层 + A3 不受伪造 subject_fp 影响")
    a2 = assert_a2("a" * 64, "deadbeef" * 8)
    check("伪造 subject_fp 可过 A2（弱断言如实）", a2["ok"] is True)
    check("A2 输出标注 subject_fp_source=self-reported（#27 分层复用）",
          a2.get("subject_fp_source") == "self-reported")
    frozen = {"digest": "f" * 64}
    a3 = assert_a3(frozen, "e" * 64)
    check("A3 输入不含 subject_fp（伪造自报值过不了 A3——承重墙）",
          "subject" not in json.dumps(a3) and a3["ok"] is False)

    print("[3] J5：脱敏黑名单扩面（issue 列举形态全部拦截）")
    leaks = [
        ("UNC 路径", "\\\\server\\share\\secret.txt"),
        ("macOS /Volumes", "/Volumes/disk/proj/x.md"),
        ("unix /etc", "配置在 /etc/passwd 附近"),
        ("家目录 ~", "见 ~/secret/keys.txt"),
        ("$HOME", "文件在 $HOME/.aws 下"),
        # 假 token 字面量须自带占位符标记（fake/example 等）：形状正则
        # （md_cg/interop.py 的 `ghp_[A-Za-z0-9]{20,}`）照旧命中 → 本用例的
        # 拦截断言不变；同时 scripts/check_publish_artifact.py 的 R1 会把它
        # 记为 NOTE 而非 FAIL（否则出货门禁对「测试夹具里的假值」恒红——
        # 红着等于没门禁）。见 FAKE_TOKEN_MARKERS。
        ("ghp_ token", "ghp_dummyABCDEFGHIJKLMNOPQRSTUVWXYZ1234"),
        ("AIza key", "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ1234567"),
        ("AKIA key", "AKIAIOSFODNN7EXAMPLE"),
        ("Bearer", "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"),
        ("文本形态 user_prompt", "note: user_prompt: tell me a secret"),
    ]
    base = {"iter_id": "t", "verifier_instance": "v", "verifier_fingerprint":
            "a" * 64, "subject_instance": "m", "subject_fingerprint":
            "b" * 64, "suite_origin": "w", "frozen_at": "x", "verdict":
            "fail", "passed": 0, "failed": 0, "details": [], "valid": False,
            "assertions_ok": False, "failure_reason": "both"}
    for label, payload in leaks:
        try:
            v2 = dict(base, iter_id=payload[:40])
            v2["details"] = [{"note": payload}]
            sanity_check_verdict(v2)
            check(f"拦截 {label}", False, payload)
        except InteropSanityError:
            check(f"拦截 {label}", True)
    try:
        sanity_check_verdict(dict(base))
        check("正常 verdict 过脱敏门禁（无误伤）", True)
    except InteropSanityError as e:
        check("正常 verdict 过脱敏门禁（无误伤）", False, str(e))

    print("[4] J5：形状白名单（越权字段/坏形状/坏枚举）")
    for label, mut in [
            ("越权顶层字段", {"extra_key": "x"}),
            ("指纹非十六进制", {"verifier_fingerprint": "zzz!*"}),
            ("verdict 枚举外", {"verdict": "PASS"}),
            ("failure_reason 枚举外", {"failure_reason": "whatever"}),
            ("计数非整数", {"passed": "3"}),
            ("计数负数", {"failed": -1})]:
        try:
            shape_check_verdict(dict(base, **mut))
            check(f"形状拦截 {label}", False)
        except InteropSanityError:
            check(f"形状拦截 {label}", True)
    try:
        shape_check_verdict(dict(base, verdict="fail", failure_reason=None,
                                 passed=1, failed=2))
        check("合法形状通过白名单", True)
    except InteropSanityError as e:
        check("合法形状通过白名单", False, str(e))

    print("[5] J6：freeze 显式 out_dir 警告")
    import contextlib
    with tempfile.TemporaryDirectory() as td:
        buf = io_err = None
        try:
            import io as _io
            buf = _io.StringIO()
            with contextlib.redirect_stderr(buf):
                freeze("zz-guard-j6", out_dir=td)
        finally:
            pass
        check("显式 out_dir → stderr 警告（不被 runner 识别）",
              buf is not None and "不被" in (buf.getvalue() or ""))
        std = os.path.join(HERE, "hive", "interop", "zz-guard-j6")
        import shutil
        shutil.rmtree(std, ignore_errors=True)

    print("[6] J4：interop_gate 机械消费方三态")
    gate = os.path.join(HERE, "scripts", "interop_gate.py")
    with tempfile.TemporaryDirectory() as td:
        vp = os.path.join(td, "verdict.json")
        ok_v = dict(base, verdict="pass", valid=True, assertions_ok=True,
                    failure_reason=None, passed=9, failed=0)
        json.dump(ok_v, open(vp, "w", encoding="utf-8"), ensure_ascii=False)
        r = subprocess.run([sys.executable, gate, "--path", vp],
                           capture_output=True, text=True, encoding="utf-8")
        check("pass+valid → exit 0（放行）", r.returncode == 0, r.stdout)
        json.dump(dict(base), open(vp, "w", encoding="utf-8"),
                  ensure_ascii=False)
        r = subprocess.run([sys.executable, gate, "--path", vp],
                           capture_output=True, text=True, encoding="utf-8")
        check("fail/valid=False → exit 1（拒绝合并）", r.returncode == 1)
        os.remove(vp)
        r = subprocess.run([sys.executable, gate, "--path", vp],
                           capture_output=True, text=True, encoding="utf-8")
        check("无 verdict → exit 2（未互验 fail-closed）", r.returncode == 2)
        json.dump({"verdict": "pass"}, open(vp, "w", encoding="utf-8"))
        r = subprocess.run([sys.executable, gate, "--path", vp],
                           capture_output=True, text=True, encoding="utf-8")
        check("旧版产物缺契约字段 → exit 3（拒绝猜测）", r.returncode == 3)

    print("[7] make_verdict 全链（新字段经双门禁落盘）")
    v3 = make_verdict(iter_id="t", verifier_instance="v",
                      verifier_fingerprint="a" * 64, subject_instance="m",
                      subject_fingerprint="b" * 64,
                      suite_origin="w", frozen_at="x", verdict="fail",
                      passed=0, failed=1,
                      details=[assert_a2("a" * 64, "b" * 64)])
    v3.update({"valid": False, "assertions_ok": False,
               "failure_reason": "both"})
    try:
        sanity_check_verdict(v3)
        shape_check_verdict(v3)
        check("含 self-reported 标注的完整产物过双门禁", True)
    except InteropSanityError as e:
        check("含 self-reported 标注的完整产物过双门禁", False, str(e))

    print("[8] _parse_counts 与 run_tests SUMMARY 实际形态契约（v6 N28）")
    # 契约断裂实形：run_tests.py:216 打印 `===== SUMMARY N/M 通过，Z 跳过…`，
    # 而 _parse_counts 旧第三正则只认 `通过 X / 失败 Y`（run_tests 从未打印）
    # → python 侧计数恒 (0,0)，verdict.json passed/failed 系统性失真
    # （判决靠 exit code 仍对，留痕假零）。
    p188, f188 = vr._parse_counts(
        "===== SUMMARY 188/189 通过，1 跳过（依赖缺失/平台不符） =====")
    check("实跑 SUMMARY 形态可解析（188/189 → passed=188，非 0）",
          p188 == 188, p188)
    check("failed 由 runnable-passed 推出（→ 1，非 0）", f188 == 1, f188)
    # 生产者现场取证：真跑 run_tests（scripts 组 -k 过滤到单测），SUMMARY
    # 行必须能被消费端解析——两侧契约同一守卫钉死，任一侧漂移必红。
    r = subprocess.run(
        [sys.executable, "-X", "utf8",
         os.path.join(HERE, "scripts", "run_tests.py"), "scripts",
         "-k", "judgment"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=HERE, timeout=600)
    summ = [ln for ln in (r.stdout or "").splitlines() if "SUMMARY" in ln]
    check("run_tests 实跑产出 SUMMARY 行（生产者在场）", bool(summ),
          (r.stdout or "")[-200:])
    if summ:
        pp, ff = vr._parse_counts(r.stdout)
        check("消费端能解析生产端实跑输出（非 (0,0) 假读）",
              (pp, ff) != (0, 0), (pp, ff, summ[-1]))
    # cargo 形态不回归；跳过单列不计失败（裸 clone SKIP 面不虚增 failed）
    pc, fc = vr._parse_counts("test result: ok. 3 passed; 1 failed; 0 ignored")
    check("cargo 形态照旧（3 passed; 1 failed → (3,1)）", (pc, fc) == (3, 1),
          (pc, fc))
    ps, fs = vr._parse_counts("===== SUMMARY 187/187 通过，2 跳过（依赖缺失） =====")
    check("跳过不计入 failed（187/187+2 跳过 → (187,0)）", (ps, fs) == (187, 0),
          (ps, fs))

    print(f"\ninterop_judgment: {passed} 通过 / {failed} 失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
