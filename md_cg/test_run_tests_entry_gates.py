# -*- coding: utf-8 -*-
# 功能名：包内测试入口的「零执行假绿」守卫（零选中 + 全跳过）
# 生效条件：python -X utf8 -m md_cg.test_run_tests_entry_gates；被测面＝md_cg/run_tests.py 的零选中门与全跳过门
# 子功能：①零选中 ⇒ rc=2（此前 rc=0 假绿）②--list 零选中 ⇒ rc=0 但必须打印原因（不静默缩面）③真跑正常 ⇒ rc=0 ④全跳过 ⇒ rc=3 ⑤路径锚点：两道门都在 if args.list 之后、if bad: 之后 ⑥判别力自证：旧实现两处都返回 0
# 执行：子进程跑 `python -m md_cg.run_tests` 断言退出码与输出；结构锚点直接读源码
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不判各测试用例本身是否正确；不覆盖 scripts/run_tests.py（那边另有 test_run_tests_all_skip_not_green.py 与 test_run_tests_no_false_green.py）
"""包内测试入口的零执行假绿守卫。

为什么单独守这一处（2026-11-08 实测）：
  `md_cg/run_tests.py` 是**出货包入口**——`pip install` 后没有 `scripts/`，
  用户只能 `python -m md_cg.run_tests`。但此前 #1910（零选中 ⇒ rc≠0）与
  「全跳过 ⇒ rc≠0」两道门**只在 scripts/ 版修过**，包内版一直漏着：

    $ python -m md_cg.run_tests -k 拼错的名字
    ===== SUMMARY 0/0 通过，0 跳过 =====
    rc=0                      ← 零个目标、零个断言，报绿

  这比单个测试失败危险：失败会喊，零执行只会沉默地说「通过」。而受影响的是
  **装了这个包的每一个用户**，不是只跑 CI 的贡献者。

与 scripts 版的差异（有意）：
  本模块 `_run_one` 不识别「模块内 SKIP」（没有 #284 那条路径），故全跳过判据
  只看依赖探测集的 skipped，不含 mod_skips。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(HERE, "run_tests.py")

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  <- " + str(detail)) if detail and not cond else ""))


def _run(*argv, timeout=600):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.run_tests", *argv],
                       cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=timeout)
    return (r.stdout or "") + (r.stderr or ""), r.returncode


def main():
    print("== A 零选中：必须非 0（#1910 的包内版缺口）")
    out, rc = _run("-k", "definitely_no_such_target_zzz")
    ok(rc == 2, "A1 零选中 ⇒ rc=2（旧实现是 0，即沉默通过）", rc)
    ok("无匹配目标" in out, "A2 明确说明「无匹配目标」", out[-300:])
    ok("#1910" in out, "A3 可检索到 issue 号（便于溯源）", out[-300:])

    print("== B --list 零选中：可 rc=0，但必须打印原因")
    out2, rc2 = _run("-k", "definitely_no_such_target_zzz", "--list")
    ok(rc2 == 0, "B1 --list 零选中仍 rc=0（查看语义）", rc2)
    ok("共 0 个" in out2, "B2 如实报 0 个", out2[-200:])
    ok("无匹配目标" in out2,
       "B3 必须打印原因（只报 0 个会让用户以为仓库里真没有目标）", out2[-300:])

    print("== C 真跑正常：不得误伤")
    out3, rc3 = _run("md_cg", "-k", "test_goal_gen")
    ok(rc3 == 0, "C1 真跑且通过 ⇒ rc=0", rc3)
    ok("SUMMARY 1/1" in out3, "C2 确实执行了 1 条", out3[-300:])
    ok("全部跳过" not in out3, "C3 不打印「全部跳过」", out3[-300:])

    print("== D 结构锚点：两道门的位置与形态")
    src = open(SCRIPT, encoding="utf-8").read()
    # 只对**非注释行**做结构断言：注释里提到 `if not targets:` 是说明文字，
    # 不构成第二道门（2026-11-08 实测踩到——注释字面量让 count/find 误判）。
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    ok("if not targets:" in code, "D1 有零选中分支")
    ok("return 0 if args.list else 2" in code, "D2 零选中执行路径返回 2")
    ok("if _passed == 0 and skipped:" in code, "D3 有全跳过门")
    ok("        return 3" in code, "D4 全跳过门返回 3（与 rc=2 区分）")
    i_list = code.find("if args.list:")
    i_zero = code.find("if not targets:")
    i_bad = code.find("    if bad:")
    i_allskip = code.find("if _passed == 0 and skipped:")
    ok(0 < i_list < i_zero,
       "D5 零选中门在 --list 分支之后（--list 才拿得到 rc=0）", (i_list, i_zero))
    ok(0 < i_bad < i_allskip,
       "D6 全跳过门在 `if bad:` 之后（有失败优先报失败）", (i_bad, i_allskip))

    print("== E 判别力自证：旧实现两处都返回 0")
    # 旧实现在 git 历史里（本笔之前）。这里用结构事实自证：本笔新增的两道门
    # 各自只出现一次，且旧末段 `if bad: return 1 / return 0` 仍在其后——
    # 说明我们是在原返回值链上**插入**门，而不是另建一条并存路径。
    ok(code.count("return 3") == 1, "E1 全跳过门只出现一次（无重复/死代码）", code.count("return 3"))
    ok(code.count("if not targets:") == 1, "E2 零选中门只出现一次", code.count("if not targets:"))
    _tail = code[i_allskip:]
    ok("return 0" in _tail,
       "E3 全跳过门之后仍有正常 return 0（跑到真通过时不被 3 覆盖）", _tail[-200:])

    print()
    print("包内入口零执行守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    print("VERDICT=%s" % ("PASS" if not _FAIL else "FAIL"))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
