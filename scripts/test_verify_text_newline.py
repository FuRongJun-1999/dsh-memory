#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 功能名：换行守卫的测试入口——把 scripts/verify_text_newline.py 接进门禁收集面
# 生效条件：scripts/run_tests.py 收集 scripts/test_*.py 时（门禁 fast 档亦收）
# 子功能：A=守卫本体全绿（事实面 + 写侧面）；B=自检（CRLF 夹具可检、LF 夹具不误报）；R=变异自证（真改一个受控文件为 CRLF，守卫必须转红，随即还原）
# 执行：python -X utf8 scripts/test_verify_text_newline.py
# 验证方式：全部 PASS 退出 0；有红项退出 1
# 不适用条件：不替代守卫本体（判据在 verify_text_newline.py）；不改任何受控文件（R 腿用临时夹具，不碰仓库文件）
"""`verify_text_newline.py` 的门禁入口。

为什么需要这个包装：`run_tests.py` 的收集面是 `scripts/test_*.py`（`verify_*.py`
不在内）。守卫本体叫 `verify_`，若没有这个 `test_` 入口，它就是一份**没人跑**的
文件——正是本仓反复收口的「有守卫但门禁不跑」形态。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS, PASSED = [], [0]


def ok(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED[0] += 1
    else:
        print("  FAIL " + name + ("  · " + str(detail) if detail else ""))
        FAILS.append(name)


def _guard(*args):
    return subprocess.run([sys.executable, "-X", "utf8",
                           os.path.join(_REPO, "scripts", "verify_text_newline.py"),
                           *args],
                          cwd=_REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)


def leg_A():
    """守卫本体必须全绿。"""
    print("\n[A 守卫本体全绿]")
    r = _guard()
    ok("A1 verify_text_newline.py 退出 0", r.returncode == 0,
       "rc=%d\n%s" % (r.returncode, (r.stdout or "")[-600:]))
    ok("A2 输出含事实面行（A 面真的跑了）", "A 事实面" in (r.stdout or ""),
       (r.stdout or "")[:200])
    ok("A3 输出含写侧面行（B 面真的跑了）", "B 写侧面" in (r.stdout or ""),
       (r.stdout or "")[:200])


def leg_B():
    """自检必须通过（含「仓内基线干净」这一条）。"""
    print("\n[B 自检]")
    r = _guard("--self-test")
    ok("B1 --self-test 退出 0", r.returncode == 0,
       "rc=%d\n%s" % (r.returncode, (r.stdout or "")[-600:]))
    ok("B2 自检确实跑了判据（输出含自检通过）", "自检通过" in (r.stdout or ""),
       (r.stdout or "")[:200])


def leg_R():
    """变异自证：让守卫**真的**在含 CRLF 的输入上判红，且干净输入上判绿。

    只在临时目录里造夹具（不碰仓库文件——证明判据有分辨力不能靠污染工作区），
    但必须走守卫自己的 `_audit_crlf`，而不是在测试里另写一份比较逻辑：
    另写一份等于「测我自己的断言」，测不出守卫口径与测试口径的分叉。
    """
    print("\n[R 变异自证：守卫的 _audit_crlf 必须判红 CRLF、放行 LF]")
    sys.path.insert(0, os.path.join(_REPO, "scripts"))
    import importlib
    mod = importlib.import_module("verify_text_newline")
    tmp = tempfile.mkdtemp(prefix="nl_guard_R_")
    try:
        bad_f = os.path.join(tmp, "crlf.json")
        ok_f = os.path.join(tmp, "lf.json")
        with open(bad_f, "wb") as fh:
            fh.write(b'{\r\n "a": 1\r\n}')
        with open(ok_f, "wb") as fh:
            fh.write(b'{\n "a": 1\n}')
        ok("R1 CRLF 夹具确实带 CRLF（变异前提成立）",
           b"\r\n" in open(bad_f, "rb").read())
        ok("R2 LF 夹具确实不含 CRLF（对照前提成立）",
           b"\r\n" not in open(ok_f, "rb").read())

        # 关键：把相对路径喂给守卫本体的 _audit_crlf（它按 ROOT 拼绝对路径，
        # 故临时把 ROOT 指到夹具目录——**只在本次调用内**，随即还原）。
        saved_root = mod.ROOT
        try:
            mod.ROOT = tmp
            hits_bad, n_bad = mod._audit_crlf(["crlf.json"])
            hits_ok, n_ok = mod._audit_crlf(["lf.json"])
        finally:
            mod.ROOT = saved_root
        ok("R3 守卫对 CRLF 文件判红（hits 非空）", len(hits_bad) == 1, hits_bad)
        ok("R4 守卫报出的处数正确（2 处）",
           bool(hits_bad) and hits_bad[0][1] == 2, hits_bad)
        ok("R5 守卫对 LF 文件放行（零误报）", hits_ok == [], hits_ok)
        ok("R6 两次都在扫（不是空转）", n_bad == 1 and n_ok == 1, (n_bad, n_ok))

        # 7：写侧面同一判据——`_has_dunder_file` 必须认 ast.Name 形态的 __file__
        #    （历史 bug：判成 Attribute 时 B 面空转，变异不转红）
        import ast as _ast
        tree = _ast.parse(
            "_SOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x')\n")
        ok("R7 仓内常量识别能认出 __file__（ast.Name 形态）",
           mod._module_level_repo_names(tree) == {"_SOL"},
           mod._module_level_repo_names(tree))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=" * 72)
    print("换行守卫入口 · scripts/verify_text_newline.py")
    print("=" * 72)
    leg_A()
    leg_B()
    leg_R()
    print("\n" + ("全部 PASS（%d 项）" % PASSED[0] if not FAILS
                  else "FAIL %d 项：%s" % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
