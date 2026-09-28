# -*- coding: utf-8 -*-
"""test_gate_json_shape —— N217 三件门禁脚本「顶层非对象 JSON」类型闸 + 退出码守卫

背景（2026-09-28 缺陷 N217，medium；v23 第 25 项未编号登记的正式编号）：
  三件门禁脚本对「合法 JSON 但顶层非对象」无类型闸，TypeError/AttributeError 逃出
  main，退出码落到与本脚本自陈契约相反的一侧——把「读不通」伪装成「语义判负」：
    · scripts/check_registry_tarball.py:42  `json.load(fh)["version"]`
      → `[1,2,3]` 得 TypeError（不在 except (OSError, ValueError, KeyError) 内），
        契约「读不通=2」实得 1；
    · scripts/check_publish_artifact.py:400（本地模式）/ :465·:474（registry 模式
      packument / 版本端点）`pj.get` / `pack.get` / `vdoc.get` → AttributeError，
        契约 2 实得 1；
    · scripts/interop_gate.py:32 `k not in v` 对**字符串**是**子串成员测试**：一个
      含四字段名的 JSON 字符串连 missing 闸都绕过，随后 `v.get` 抛 AttributeError，
        契约「形状非法=3」实得 1；另 `failed` 未入 _REQUIRED，verdict=pass 分支的
        f-string 缺键 KeyError 同型逃逸。

守卫断言面（全哑数据/临时文件）：
  S1 check_registry_tarball：package.json ∈ {[1,2,3], "x", null, 42} → exit 2（修前 1）
  S2 check_publish_artifact 本地模式：package.json ∈ 同上 → exit 2（修前 1）
  S3 check_publish_artifact registry 模式（桩 http_get_json）：packument=[] / 版本
     端点=[] → 返回 2（修前 AttributeError 逃逸）
  S4 interop_gate：JSON 字符串含四字段名 → exit 3（修前 1，子串闸被绕过）
  S5 interop_gate：数组/缺 failed/计数为 bool → exit 3
  S6 interop_gate 反向腿：合法 verdict=pass → exit 0（不误伤放行态）
  S7 既有套件回归：`python -m md_cg.test_interop_judgment` 全绿（J4 三态断言）

运行：python -X utf8 scripts/test_gate_json_shape.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

_REG = os.path.join(HERE, "scripts", "check_registry_tarball.py")
_CPA = os.path.join(HERE, "scripts", "check_publish_artifact.py")
_IG = os.path.join(HERE, "scripts", "interop_gate.py")

passed = failed = 0

_NON_OBJECTS = [("[1,2,3]", "数组"), ('"x"', "字符串"), ("null", "null"), ("42", "数字")]


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:400])


def _env():
    return dict(os.environ, PYTHONUTF8="1")


def _run(argv):
    return subprocess.run([sys.executable, "-X", "utf8"] + argv,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_env(), cwd=HERE, timeout=300)


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with tempfile.TemporaryDirectory() as tmp:
        entry = os.path.join(tmp, "e.yml")
        _write(entry, "url: x\nname: y\ncategory: agi\n"
                      "tarball: https://e/x-0.4.8.tgz\n")
        pkg = os.path.join(tmp, "package.json")

        print("[1] check_registry_tarball：顶层非对象 → exit 2（读不通）")
        for body, label in _NON_OBJECTS:
            _write(pkg, body)
            got = _run([_REG, "--entry", entry, "--package", pkg])
            check("S1 %s 形态 exit 2（修前 traceback exit 1）" % label,
                  got.returncode == 2,
                  "rc=%s out=%s err=%s" % (got.returncode, got.stdout[-200:],
                                           got.stderr[-200:]))

        print("[2] check_publish_artifact 本地模式：顶层非对象 → exit 2")
        for body, label in _NON_OBJECTS:
            _write(pkg, body)
            got = _run([_CPA, "--root", tmp])
            check("S2 %s 形态 exit 2（修前 AttributeError exit 1）" % label,
                  got.returncode == 2,
                  "rc=%s err=%s" % (got.returncode, got.stderr[-200:]))

        print("[3] check_publish_artifact registry 模式：桩 packument/版本端点非对象 → 2")
        spec = importlib.util.spec_from_file_location("cpa_shape_guard", _CPA)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _write(pkg, json.dumps({"name": "p", "version": "1.0.0"}))
        for stub, label in (([], "packument=[]"), ({"time": {}}, "packument 正常")):
            calls = {"n": 0}

            def _stub(url, _stub=stub):
                calls["n"] += 1
                return _stub if calls["n"] == 1 else []
            mod.http_get_json = _stub
            try:
                rc = mod.registry_mode(tmp, "1.0.0", mod.CheckReport(5))
            except Exception as exc:  # noqa: BLE001
                rc = "逃逸: %s: %s" % (type(exc).__name__, exc)
            check("S3 %s → 返回 2（修前 AttributeError 逃逸）" % label, rc == 2, rc)

        print("[4] interop_gate：形状非法 → exit 3")
        vp = os.path.join(tmp, "verdict.json")
        bypass = json.dumps(
            "verdict valid assertions_ok failure_reason passed failed")
        _write(vp, bypass)
        got = _run([_IG, "--path", vp])
        check("S4 含四字段名的 JSON 字符串 → exit 3（修前子串闸绕过→exit 1）",
              got.returncode == 3, "rc=%s out=%s" % (got.returncode, got.stdout[-200:]))
        for obj, label in (
                ([1, 2], "数组"),
                ({"verdict": "pass", "valid": True, "assertions_ok": True,
                  "failure_reason": None, "passed": 1}, "缺 failed 键"),
                ({"verdict": "pass", "valid": True, "assertions_ok": True,
                  "failure_reason": None, "passed": True, "failed": 0},
                 "passed 为 bool")):
            _write(vp, json.dumps(obj))
            got = _run([_IG, "--path", vp])
            check("S5 %s → exit 3" % label, got.returncode == 3,
                  "rc=%s out=%s" % (got.returncode, got.stdout[-200:]))

        print("[5] 反向腿：合法放行态与拒绝态不受影响")
        _write(vp, json.dumps({"verdict": "pass", "valid": True,
                               "assertions_ok": True, "failure_reason": None,
                               "passed": 9, "failed": 0}))
        got = _run([_IG, "--path", vp])
        check("S6 verdict=pass/valid=true → exit 0", got.returncode == 0, got.stdout)
        _write(vp, json.dumps({"verdict": "fail", "valid": False,
                               "assertions_ok": True,
                               "failure_reason": "suite_failed",
                               "passed": 3, "failed": 1}))
        got = _run([_IG, "--path", vp])
        check("S6 verdict=fail → exit 1（不得被类型闸吞掉）", got.returncode == 1,
              got.stdout)

    print("[6] 既有套件回归：md_cg.test_interop_judgment（J4 三态）")
    got = subprocess.run([sys.executable, "-X", "utf8", "-m",
                          "md_cg.test_interop_judgment"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=_env(), cwd=HERE, timeout=900)
    check("S7 test_interop_judgment 全绿", got.returncode == 0,
          (got.stdout or "")[-500:])

    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
