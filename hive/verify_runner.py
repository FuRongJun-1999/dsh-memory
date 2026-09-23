# -*- coding: utf-8 -*-
"""互验执行器（批次11，§7.4 步骤4）：验证实例的 cmd 任务调用本脚本。

流程：角色守卫（仅 verifier）→ 读冻结凭证 → A1/A2/A3 断言 → 跑全量套件
（cargo test + scripts/run_tests.py，不按改动面裁剪）→ make_verdict（脱敏
门禁）→ 写 hive/interop/<iter_id>/verdict.json。

断言任一不成立 → verdict 结论**作废**（"valid": false），不得进入合并——
写入 verdict.json 本身是留痕（§7.3），不是放行。

身份来源：本进程 env（serve 派发验证 job 时注入）——HIVE_ROLE 必须 verifier；
SUBJECT_FP = 主实例候选的判据面指纹（spec.env 传入，A2 比对输入）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
from md_cg.interop import assert_a1, assert_a2, assert_a3, make_verdict
from md_cg.mdcos import _sig  # noqa: F401  保持与库同源初始化


# 生效条件：命令、超时秒数给定——正常结束返回 (exit_code, stdout, stderr)；
# 超时 → (124, 部分输出, 超时说明)；启动失败 → (127, "", 错误说明)。
# 验证方式：test——test_p39 冒烟链（2b/2c 计数解析依赖本函数输出）。
def _run(cmd, timeout_s):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout_s)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", f"超时（{timeout_s}s）被强杀"
    except OSError as e:
        return 127, "", f"启动失败：{type(e).__name__}: {e}"


# 生效条件：text 给定——宽松累加两类计数形态（cargo `N passed; M failed` 与
# run_tests「通过 X / 失败 Y」），返回 (passed, failed)；无命中 → (0, 0)。
# 不适用条件：不区分套件层级（冒烟与全量同口径累加）。
def _parse_counts(text):
    """宽松解析套件计数（cargo 的 `N passed; M failed` 与 run_tests 的两种）。"""
    passed = failed = 0
    for m in re.finditer(r"(\d+) passed", text):
        passed += int(m.group(1))
    for m in re.finditer(r"(\d+) failed", text):
        failed += int(m.group(1))
    for m in re.finditer(r"通过\s+(\d+)\s*/\s*失败\s+(\d+)", text):
        passed += int(m.group(1))
        failed += int(m.group(2))
    return passed, failed


# 生效条件（核心入口 · CCG 六要素）：
#   功能名：互验执行器（§7.4 步骤 4）。
#   生效条件：argv[1]=iter_id 且冻结凭证 hive/interop/<iter>/frozen.json 可读、
#   HIVE_ROLE=verifier（否则 rc=3 角色守卫拒跑）、SUBJECT_FP 由派发方 spec.env 注入。
#   子功能：A1/A2/A3 断言 → 全量套件（cargo+run_tests；--smoke 走内置探针）→
#   make_verdict 脱敏 → verdict.json 落盘。
#   执行：断言不成立 → valid=false 结论作废（不进合并），照常落盘留痕。
#   验证方式：test——test_p39_verify_flow 9/0（--smoke 冒烟链）。
#   不适用条件：不产出 pass/fail 以外的裁决（分歧仲裁属 arbitration.json 另一产物）。
def main(argv):
    iter_id = argv[1] if len(argv) > 1 else ""
    role = (os.environ.get("HIVE_ROLE") or "").strip()
    inst = (os.environ.get("HIVE_INSTANCE") or "").strip()
    subject_fp = (os.environ.get("SUBJECT_FP") or "").strip()
    timeout_s = int(os.environ.get("VERIFY_TIMEOUT_S") or 1200)

    # 角色守卫（§7.1）：验证只能由 verifier 发起——身份不符不跑，诚实留痕退出
    if role != "verifier":
        print(json.dumps({"ok": False, "error":
                          f"角色守卫：HIVE_ROLE={role!r}≠verifier，拒绝执行互验"},
                         ensure_ascii=False))
        return 3

    frozen_fp = os.path.join(REPO, "hive", "interop", iter_id, "frozen.json")
    try:
        frozen = json.load(open(frozen_fp, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(json.dumps({"ok": False,
                          "error": f"冻结凭证不可读（{frozen_fp}）: {e}"}))
        return 4

    # 判据面指纹（A3 输入）：验证者**自己 worktree** 的当前判据面
    r = subprocess.run([sys.executable, os.path.join(REPO, "scripts",
                                                     "judgment_manifest.py"),
                        "--digest"], capture_output=True, text=True,
                       encoding="utf-8")
    fp_ver = r.stdout.strip() if r.returncode == 0 else ""

    a1 = assert_a1(inst, "main")
    a2 = assert_a2(fp_ver, subject_fp)
    a3 = assert_a3(frozen, fp_ver)

    # 全量套件（不按改动面裁剪，§7.4 质量行）：cargo + python 两大块。
    # --smoke：链路冒烟模式（内置轻量探针，参数在 python 内构造零转义问题——
    # 字符串 shell 形态的套件参数化在 Windows 反斜杠路径下不可靠，弃）
    if len(argv) > 2 and argv[2] == "--smoke":
        cargo_cmd = [sys.executable, "-c", "print('3 passed')"]
        py_cmd = [sys.executable, "-c", "print('4 passed')"]
    else:
        cargo_cmd = ["cargo", "test"]
        py_cmd = [sys.executable, "scripts/run_tests.py"]
    rc_cargo, out_c, _ = _run(cargo_cmd, timeout_s // 2)
    rc_py, out_p, _ = _run(py_cmd, timeout_s // 2)
    passed, failed = _parse_counts(out_c + out_p)
    ok = rc_cargo == 0 and rc_py == 0 and failed == 0

    verdict = "pass" if (ok and a1["ok"] and a2["ok"] and a3["ok"]) else "fail"
    v = make_verdict(
        iter_id=iter_id,
        verifier_instance=inst or "verifier",
        verifier_fingerprint=fp_ver,
        subject_instance="main",
        subject_fingerprint=subject_fp,
        suite_origin="verifier-worktree",
        frozen_at=str(frozen.get("frozen_at") or ""),
        verdict=verdict,
        passed=passed, failed=failed + (0 if ok else 1),
        details=[a1, a2, a3,
                 {"cargo_exit": rc_cargo, "run_tests_exit": rc_py}],
    )
    # 断言不成立 → 结论作废（不得进入合并）：照常落盘留痕，但 valid=false
    v["valid"] = bool(a1["ok"] and a2["ok"] and a3["ok"])

    out_fp = os.path.join(REPO, "hive", "interop", iter_id, "verdict.json")
    os.makedirs(os.path.dirname(out_fp), exist_ok=True)
    with open(out_fp, "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, indent=2)
    print(json.dumps({"ok": True, "verdict": v["verdict"], "valid": v["valid"],
                      "path": out_fp, "passed": passed, "failed": failed},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
