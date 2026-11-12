# -*- coding: utf-8 -*-
"""test_check_placeholder_leak —— 占位符守卫的自证与 fail-closed 配对守卫

背景（2026-10-17 实测，基线 c8d66fa）：
  `scripts/check_placeholder_leak.py` 此前**没有任何自证入口**（被 check_guard_coverage
  登记为孤儿例外），且有两处判据不自洽：
    D1 同一行多处占位符只记第一处 —— docstring 承诺「逐处点名」，实测一行两个只报 1 处；
    D2 不存在的根 / 空判据面（0 个追踪文本件）⇒ 返回 0「零命中 ✓」= **假绿**。
  本笔：修 D1/D2 + 新增 `--selftest`；本文件是**配对守卫**（run_tests.py 的
  `scripts/test_*.py` 收集面 → CI 会跑它）。

断言面：
  G1 模块自带 `selftest()` 通过（14 条判据分支）
  G2 同一行两处占位符 ⇒ 记 **2 处**（D1 的独立见证，不靠模块自证）
  G3 不存在的根 ⇒ 退出码 **2**（D2 红点）
  G4 空判据面（空 git 仓）⇒ 退出码 **2**（D2 红点）
  G5 回归：真干净 ⇒ 0；有泄漏 ⇒ 1
  G6 守卫自身源码零命中（本仓体例：占位符由字符拼出，源码不出现字面量）
  M1 变异锚点在源码中恰好出现一次（仅 --mutate）
  M2 定点变异：把「循环 find」还原成「单次 find」⇒ **恰好** G2 红
     （G1 同步红：模块自证与配对守卫是同一缺陷的两把尺，刻意双尺冗余）

运行：
  python -X utf8 scripts/test_check_placeholder_leak.py            # 全绿（CI 收集此行）
  python -X utf8 scripts/test_check_placeholder_leak.py --mutate   # 定点变异：恰好红 G2(+G1)
"""
import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(HERE, "scripts", "check_placeholder_leak.py")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + ("  —— " + detail if detail else ""))


def load_mod(path, name="cpl_under_test"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


def _init_repo(path, files):
    os.makedirs(path, exist_ok=True)
    r = _git(path, "init", "-q")
    if r.returncode != 0:
        raise RuntimeError("git init 失败：%s" % (r.stderr or r.stdout))
    for rel, text in files.items():
        p = os.path.join(path, rel)
        parent = os.path.dirname(p)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    if not files:
        return
    _git(path, "add", "-A")
    r = _git(path, "-c", "user.name=selftest",
             "-c", "user.email=selftest@example.com", "commit", "-qm", "selftest")
    if r.returncode != 0:
        raise RuntimeError("git commit 失败：%s" % (r.stderr or r.stdout))


def _quiet_main(mod, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main(list(args))
    return rc, buf.getvalue()


def _quiet_selftest(mod):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.selftest()
    return rc, buf.getvalue()


def run_assertions(mod, *, record=True, label=""):
    """对本模块跑 G1–G6；record=False 时只观测（变异体用），返回红项集合。"""
    reds = set()

    def guard(name, cond, detail=""):
        if not cond:
            reds.add(name)
        if record:
            check((("[%s] " % label) if label else "") + name, cond, detail)
        else:
            print("  [观测] %s %s%s" % ("红" if not cond else "绿", name,
                                       ("  —— " + detail) if (detail and not cond) else ""))

    rc, _ = _quiet_selftest(mod)
    guard("G1 模块自带 selftest 通过", rc == 0, "rc=%d" % rc)

    ph = mod.PLACEHOLDERS[0]
    base = tempfile.mkdtemp(prefix="cpl_pair_")
    try:
        dupe = os.path.join(base, "dupe.md")
        with io.open(dupe, "w", encoding="utf-8", newline="") as f:
            f.write(ph + " / " + ph + "\n")
        hits = mod._scan_file(dupe, "dupe.md")
        guard("G2 同一行两处占位符全部点名", len(hits) == 2, "hits=%d" % len(hits))

        missing = os.path.join(base, "no_such_root")
        rc, _ = _quiet_main(mod, "--root", missing)
        guard("G3 不存在的根 ⇒ 退出码 2", rc == 2, "rc=%d" % rc)

        empty = os.path.join(base, "empty_repo")
        _init_repo(empty, {})
        rc, _ = _quiet_main(mod, "--root", empty)
        guard("G4 空判据面 ⇒ 退出码 2", rc == 2, "rc=%d" % rc)

        clean = os.path.join(base, "clean_repo")
        _init_repo(clean, {"clean.md": "clean\n"})
        rc, _ = _quiet_main(mod, "--root", clean)
        guard("G5a 真干净 ⇒ 退出码 0（回归）", rc == 0, "rc=%d" % rc)
        leak = os.path.join(base, "leak_repo")
        _init_repo(leak, {"leak.md": ph + "\n"})
        rc, _ = _quiet_main(mod, "--root", leak)
        guard("G5b 有泄漏 ⇒ 退出码 1（回归）", rc == 1, "rc=%d" % rc)

        own = mod._scan_file(os.path.abspath(mod.__file__), "self.py")
        guard("G6 自身源码零命中（不自指）", own == [], str(own[:2]))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return reds


def run_plain():
    mod = load_mod(TARGET)
    run_assertions(mod)


def run_mutate():
    """镜像树里把「循环 find」还原成「单次 find」（绝不就地改源）。

    期望：恰好 G2 红；G1 同步红（模块自证也覆盖同一分支）；G3/G4/G5/G6 保持绿。
    """
    src = io.open(TARGET, encoding="utf-8").read()
    old = ("                    start = 0\n"
           "                    while True:\n"
           "                        col = line.find(ph, start)\n"
           "                        if col < 0:\n"
           "                            break\n"
           "                        hits.append((rel.replace(os.sep, \"/\"), ln, col + 1, ph,\n"
           "                                     line.strip()[:120]))\n"
           "                        start = col + len(ph)\n")
    new = ("                    col = line.find(ph)\n"
           "                    if col < 0:\n"
           "                        continue\n"
           "                    hits.append((rel.replace(os.sep, \"/\"), ln, col + 1, ph,\n"
           "                                 line.strip()[:120]))\n")
    n = src.count(old)
    check("M1 变异锚点在源码中恰好出现一次", n == 1, "出现 %d 次" % n)
    if n != 1:
        return

    tmp = tempfile.mkdtemp(prefix="cpl_mutate_")
    try:
        mut_path = os.path.join(tmp, "check_placeholder_leak.py")
        with io.open(mut_path, "w", encoding="utf-8") as f:
            f.write(src.replace(old, new, 1))
        mut = load_mod(mut_path, "cpl_mutant")
        reds = run_assertions(mut, record=False, label="变异体")
        expect = {"G1 模块自带 selftest 通过", "G2 同一行两处占位符全部点名"}
        check("M2 变异后红项恰好=锚在本次修复那一处（G3/G4/G5/G6 保持绿）",
              reds == expect, "实得=%s，期望=%s" % (sorted(reds), sorted(expect)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    print("=== 占位符泄漏守卫 · 自证与 fail-closed 配对守卫 ===")
    if "--mutate" in argv:
        print("[模式] 定点变异自证（镜像树，不就地改源）")
        run_mutate()
    else:
        print("[模式] 常规断言（CI 收集此行）")
        run_plain()
    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
