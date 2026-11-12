# -*- coding: utf-8 -*-
# 功能名：测试入口的「零选中假绿」守卫（1_ai 会话报告的假绿缺陷（跨仓 #1910））
# 生效条件：python -X utf8 scripts/test_run_tests_no_false_green.py；被测面＝scripts/run_tests.py 的 _module_match 与「零选中不得返回 0」
# 子功能：①`--module` 归一化（斜杠/点号/无前缀/带 .py 后缀等价）②斜杠写法必须真的选到目标（不是 0）③不存在的选择器必须 rc≠0 ④--list 零选中可 rc=0 但必须打印原因（不静默）⑤判别力自证：旧实现（裸 startswith）在斜杠写法下必然零选中
# 执行：直接调用 _module_match 断言语义 + 子进程跑 run_tests.py 断言退出码与输出
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不判 -k/group 的匹配语义（本守卫只覆盖 --module 与零选中退出码）；不判被测测试本身是否通过
"""零选中假绿守卫（1_ai 会话报告的假绿缺陷（跨仓 #1910））。

病灶（1_ai 会话复现，2026-10-28）：
  `--module` 的 help 教的是**斜杠**写法（`md_cg/test_issue4`），而实际目标名是**点号**
  （`md_cg.test_issue4`）。旧实现直接 `n.startswith(args.module)` ⇒ 斜杠写法**选中零个目标**，
  但入口仍 `SUMMARY 0/0 通过` + `rc=0`。

为什么这比「测试失败」危险：失败的测试会喊，**零选中的测试只会沉默地说"通过"**；
CI 只看退出码时，整条流水线的绿都可能是假的。
"""
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "run_tests.py")

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def _load():
    spec = importlib.util.spec_from_file_location("_rt_fg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(*argv, timeout=900):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, *argv], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=timeout)
    return (r.stdout or "") + (r.stderr or ""), r.returncode


def main():
    m = _load()

    print("== A 归一化：四种写法等价")
    target = "md_cg.test_issue452"
    for sel in ("md_cg/test_issue452", "md_cg.test_issue452", "test_issue452",
                "md_cg/test_issue452.py", "md_cg.test_issue452.py"):
        ok(m._module_match(sel, target), "A 选择器 %-28s 命中目标" % sel, sel)
    ok(not m._module_match("md_cg/test_other", target), "A 不匹配的名字仍不命中")
    ok(not m._module_match("", target), "A 空选择器不命中（不是「全选」）")

    print("== B 斜杠写法必须真的选到目标（不是 0）")
    out, rc = _run("md_cg", "--module", "md_cg/test_issue452", "--list")
    ok("共 2 个" in out, "B1 斜杠写法列出 2 个目标（旧实现是 0 个）", out[-200:])
    ok(rc == 0, "B2 --list 正常退出", rc)
    out2, rc2 = _run("md_cg", "--module", "md_cg/test_issue452")
    ok("SUMMARY 2/2" in out2, "B3 斜杠写法真的执行了 2 条（旧实现是 SUMMARY 0/0）", out2[-300:])
    ok(rc2 == 0, "B4 全部通过时 rc=0", rc2)

    print("== C 零选中必须非零（这是假绿的正题）")
    out3, rc3 = _run("md_cg", "--module", "no_such_module_zzz")
    ok(rc3 == 2, "C1 执行路径零选中 ⇒ rc=2（旧实现是 0）", rc3)
    ok("无匹配目标" in out3 and "1_ai 会话报告的假绿缺陷（跨仓 #1910）" in out3,
       "C2 明确说明原因（可检索到 issue 号）", out3[-300:])
    ok("SUMMARY 0/0" not in out3, "C3 零选中不得打成「通过」式的 SUMMARY", out3[-200:])

    print("== D --list 零选中：可 rc=0，但必须打印原因（不静默）")
    out4, rc4 = _run("md_cg", "--module", "no_such_module_zzz", "--list")
    ok(rc4 == 0, "D1 --list 零选中仍 rc=0（查看语义）", rc4)
    ok("无匹配目标" in out4, "D2 但必须打印原因", out4[-200:])

    print("== E 判别力自证：旧实现（裸 startswith）在斜杠写法下必然零选中")
    old = "md_cg.test_issue452".startswith("md_cg/test_issue452") or \
          "md_cg/test_issue452" in "md_cg.test_issue452"
    ok(old is False, "E1 旧判据对斜杠写法返回 False（即零选中）——证明本守卫能区分新旧实现", old)
    ok(m._module_match("md_cg/test_issue452", "md_cg.test_issue452") is True,
       "E2 新判据对同一输入返回 True")

    print("== F main() 里有「零选中不得返回 0」的锚点")
    src = open(SCRIPT, encoding="utf-8").read()
    ok("if not targets:" in src, "F1 有零选中分支")
    ok("return 0 if args.list else 2" in src, "F2 执行路径返回 2（非 0）")
    i_guard = src.find("if not targets:")
    i_disp = src.find("disposers.push") if "disposers.push" in src else 0
    ok(0 < i_guard, "F3 零选中检测在入口内（位置断言）", (i_guard, i_disp))

    print()
    print("零选中假绿守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())