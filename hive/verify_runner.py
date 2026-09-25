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
from md_cg.interop import (assert_a1, assert_a2, assert_a3, make_verdict,
                           sanity_check_verdict, shape_check_verdict)
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


# 生效条件：a_ok（三断言布尔）、suite_ok（套件布尔）给定——按四象限返回
# (verdict, valid, assertions_ok, failure_reason)：verdict="pass" 当且仅当两者皆真；
# valid（issue #37 J1 改义）= 单一放行位，与 verdict 同义（断言 AND 套件）——
# 旧语义「仅三断言」已废（套件全挂时 valid=true 的误读形态）；
# assertions_ok 承接旧 valid 的断言面语义；failure_reason（J3）枚举失败成因。
def _compose_semantics(a_ok: bool, suite_ok: bool):
    """verdict 语义四象限（issue #37 J1/J3：让「为什么失败」成为结构化事实）。"""
    verdict = "pass" if (a_ok and suite_ok) else "fail"
    failure_reason = None
    if not (a_ok and suite_ok):
        failure_reason = ("both" if (not a_ok and not suite_ok)
                          else ("assertions_failed" if not a_ok
                                else "suite_failed"))
    return verdict, (verdict == "pass"), a_ok, failure_reason


# 生效条件（核心入口 · CCG 六要素）：
#   功能名：互验执行器（§7.4 步骤 4）。
#   生效条件：argv[1]=iter_id 且**过白名单**（[A-Za-z0-9_.-]{1,80}，与姊妹入口
#   write_verdict_to_repo 同模板 md_cg/interop.py:316——CLI 直跑时 argv[1] 是
#   半信任输入，`..\` 穿越/绝对路径形态可在拼路径时越出 hive/interop/ 读写；
#   不过即 rc=2 拒跑，fail-closed 在任何路径拼接之前）、冻结凭证
#   hive/interop/<iter>/frozen.json 可读、HIVE_ROLE=verifier（否则 rc=3 角色守卫
#   拒跑——角色守卫只查 env 值，拦不住自设环境变量的 CLI 直跑，iter_id 白名单
#   是独立防线）、SUBJECT_FP 由派发方 spec.env 注入。
#   子功能：A1/A2/A3 断言 → 全量套件（cargo+run_tests；--smoke 走内置探针）→
#   make_verdict 脱敏 → verdict.json 落盘（sanity + shape 双门禁）。
#   执行：verdict=pass 当且仅当断言 AND 套件皆过；valid=放行位（与 verdict 同义），
#   assertions_ok=断言面，failure_reason 枚举失败成因（J1/J3）。
#   验证方式：test——test_p39_verify_flow 9/0（--smoke）+ test_interop_judgment 守卫。
#   不适用条件：不产出 pass/fail 以外的裁决（分歧仲裁属 arbitration.json 另一产物）。
def main(argv):
    iter_id = argv[1] if len(argv) > 1 else ""

    # iter_id 白名单（v2 N5/N11，2026-09-25）：CLI 直跑时 argv[1] 是半信任输入
    # ——`..\` 穿越/绝对路径/含分隔符形态在 :frozen_fp/:out_fp 裸拼时可越出
    # hive/interop/ 从仓库外读 frozen.json 并 makedirs+写 verdict.json。与姊妹
    # 入口 write_verdict_to_repo（md_cg/interop.py:316）同模板统一防御；不过即
    # 诚实留痕退出（rc=2），在任何路径拼接之前 fail-closed，不触盘。
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", iter_id):
        print(json.dumps({"ok": False,
                          "error": f"iter_id 非法（入库路径组成部分）: {iter_id!r}"},
                         ensure_ascii=False))
        return 2

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
    suite_ok = rc_cargo == 0 and rc_py == 0 and failed == 0
    a_ok = bool(a1["ok"] and a2["ok"] and a3["ok"])

    verdict, valid, assertions_ok, failure_reason = \
        _compose_semantics(a_ok, suite_ok)
    v = make_verdict(
        iter_id=iter_id,
        verifier_instance=inst or "verifier",
        verifier_fingerprint=fp_ver,
        subject_instance="main",
        subject_fingerprint=subject_fp,
        suite_origin="verifier-worktree",
        frozen_at=str(frozen.get("frozen_at") or ""),
        verdict=verdict,
        passed=passed, failed=failed + (0 if suite_ok else 1),
        details=[a1, a2, a3,
                 {"cargo_exit": rc_cargo, "run_tests_exit": rc_py}],
    )
    # J1/J3：valid=单一放行位（断言 AND 套件）；断言面独立成 assertions_ok；
    # failure_reason 让「为什么失败」结构化。写盘前过 sanity（脱敏黑名单）
    # + shape（形状白名单）双门禁——新字段与 details 同受检。
    v["valid"] = valid
    v["assertions_ok"] = assertions_ok
    v["failure_reason"] = failure_reason
    sanity_check_verdict(v)
    shape_check_verdict(v)

    out_fp = os.path.join(REPO, "hive", "interop", iter_id, "verdict.json")
    os.makedirs(os.path.dirname(out_fp), exist_ok=True)
    with open(out_fp, "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, indent=2)
    print(json.dumps({"ok": True, "verdict": v["verdict"], "valid": v["valid"],
                      "assertions_ok": v["assertions_ok"],
                      "failure_reason": v["failure_reason"],
                      "path": out_fp, "passed": passed, "failed": failed},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
