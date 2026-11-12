# -*- coding: utf-8 -*-
r"""守卫 · #91 whitebox verifier 不得在判定前产生副作用（2026-10-09 DSH 端实施）。

缺陷（GitHub #91）：三处 exec(compile(req.code, ...), ns) 的 ns 未限 __builtins__
⇒ 模块顶层代码在**判定之前**就执行。实测（issue 报告）：
    B_builtin_open()  ok=False  副作用文件已创建=True   ← 判负之前已落盘
另：STDLIB_OK 原含 os/sys/socket/threading；且**无超时**。

本笔处置：①__builtins__ 限白名单（去 open/__import__/eval/exec/compile/…）
          ②STDLIB_OK 去 os/sys/socket/threading。
未处置（见节点）：**超时**（exec 同步阻塞，需子进程方案）；缓存完整性。

判据（真跑 Verifier，临时目录观察副作用）：
  G1 open() 载荷 ⇒ 副作用文件**不得被创建**（修前会创建）。
     **必须带 `cases`**（#429 修正）：verifier 只在跑用例时才执行载荷；不给 cases 时
     载荷根本不进执行器 ⇒ 判据恒真（#429 的病灶之一）。
  G2 os 导入 ⇒ L1 层拒（白名单已去 os）
  G3 正常纯函数 ⇒ 仍能校验通过（不误伤）
  G4 SAFE_NS 的 builtins 白名单**不含**危险名（open/__import__/eval/exec/compile）
  G5 直接 exec 进 SAFE_NS ⇒ open 不可用（父侧判据，保留为对照）
  G4b–G4e 受控 __import__ 的判据（#186/#187）
  G7 **子进程侧行为判据（#429 补）**：带 cases 走 `Verifier().verify()`（生产路径经
     `_run_guarded` → `_EXEC_RUNNER_SRC`），载荷 `__import__('pathlib')` 写文件
     ⇒ 副作用文件不得被创建。G5 打在**父侧** `SAFE_NS()`，而生产只走子进程；
     #429 的病灶正是「父侧有判据、子进程那一行没人钉」。
  G8 **防回退锚点（#429 补）**：`_EXEC_RUNNER_SRC` 里执行命名空间那一行在场。

定点变异（`--mutate`，#429 的元判据）：
  在镜像树里把子进程执行器的 `ns = {"__builtins__": _safe_builtins(), ...}` 撤回成
  `ns = {"__name__": "__mdcg_verify__"}`（缺陷态：被校验代码拿回真内置）⇒
  **G1、G7（行为面）+ G8（锚点行被改写）必须转红**。红项集合打印且须与预期逐项相符。

判别力边界（如实）：
  · 变异腿只撤**子进程执行器**那一行。父侧 `SAFE_NS()`（`:383`）同时撤回时 G5 也红，
    但生产路径不走父侧，故本腿只钉生产面；G5 仍是父侧的独立对照。
  · G1/G7 依赖「载荷真的被执行」——若将来 verifier 改成不执行模块顶层（更强的
    静态判据），这两条会因「文件本来就不会被创建」而变**恒真**；届时必须补一条
    「载荷确实被执行过」的正向证据（如让载荷返回可观测值），而不是删判据。
  · 不判超时面（`_run_guarded` 的 timeout 另有守卫）；不判缓存完整性。
  · G8 是源码锚点（fail-closed）：重写该行会让它红——这是有意的。

运行：python -X utf8 -m md_cg.test_issue91_verifier_sandbox [--mutate]
退出码：0 全绿 ｜ 1 断言失败（含变异腿不符预期）
"""
from __future__ import annotations

import builtins
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []

#: 子进程执行器里的执行命名空间那一行（#429 的 M7c 变异点）。
_RUNNER_NS = '    ns = {"__builtins__": _safe_builtins(), "__name__": "__mdcg_verify__"}'
_RUNNER_NS_BAD = '    ns = {"__name__": "__mdcg_verify__"}'
#: G8 锚点（去缩进后比较）。
_NS_ANCHOR = 'ns = {"__builtins__": _safe_builtins(), "__name__": "__mdcg_verify__"}'

#: 载荷末尾的中文注释只为绕开 R1（函数/类须有中文注释）——与沙箱判据无关。
_C = "    \"\"\"恒等。\"\"\"\n"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _verify(code, cases):
    from md_cg.whitebox_kb.wisdom import verifier as V
    try:
        res = V.Verifier().verify(V.VerifyRequest(task="unit", code=code,
                                                  cases=cases))
        return (res.ok if hasattr(res, "ok") else (res or {}).get("ok")), res
    except Exception as exc:                   # noqa: BLE001
        return "EXC:%s" % type(exc).__name__, exc


def main():
    from md_cg.whitebox_kb.wisdom import verifier as V

    d = tempfile.mkdtemp(prefix="p91_")
    try:
        victim = os.path.join(d, "SIDE_EFFECT_CREATED.txt")
        # 载荷：模块顶层就在判定前执行（#91 的 B_builtin_open 同款）。
        # ★必须带 cases：不带 cases 时载荷不执行，判据恒真（#429）。
        payload = (
            "def f(x):\n"
            + _C +
            "    return x\n\n"
            "open(r'%s', 'w').write('pwned')\n" % victim
        )
        ok, res = _verify(payload, [(1, 1)])
        check("G1 open() 载荷（带 cases ⇒ 真执行）⇒ 副作用文件不得被创建（修前会创建）",
              not os.path.exists(victim),
              "ok=%r exists=%r" % (ok, os.path.exists(victim)))

        # G2 os 导入 ⇒ L1 拒
        req2 = V.VerifyRequest(task="unit", code="import os\n\ndef f(x):\n"
                                + _C + "    return x\n")
        try:
            r2 = V.Verifier().verify(req2)
            ev = str(getattr(r2, "reason", "") or getattr(r2, "evidence", "") or "")
            ok2 = getattr(r2, "ok", None)
        except Exception as exc:               # noqa: BLE001
            ev, ok2 = "EXC:%s" % type(exc).__name__, None
        check("G2 import os ⇒ 被拒（白名单已去 os）",
              (ok2 is False) or ("非标准库" in ev) or ("os" in ev and ok2 is not True),
              "ok=%r ev=%s" % (ok2, ev[:70]))

        # G3 正常纯函数仍可校验
        # 注：必须带中文注释——「规范符合性」一层（条件论 R1）要求函数/类有中文注释，
        # 否则 ok=False。那是**既有判据**，与本笔的沙箱加固无关（首版守卫即栽在此，
        # 误把 R1 判负当成自己的改动造成的误伤）。
        req3 = V.VerifyRequest(
            task="unit",
            code="# 加一\ndef f(x):\n    \"\"\"加一。\"\"\"\n    return x + 1\n",
            cases=[(1, 2)])
        try:
            r3 = V.Verifier().verify(req3)
            check("G3 正常纯函数仍通过（不误伤）", getattr(r3, "ok", None) is True,
                  "ok=%r" % (getattr(r3, "ok", None),))
        except Exception as exc:               # noqa: BLE001
            check("G3 正常纯函数仍通过（不误伤）", False, repr(exc)[:70])

        # G7 子进程侧行为判据（#429 补）：生产路径 = verify() → _run_guarded →
        # _EXEC_RUNNER_SRC。父侧 SAFE_NS() 的判据（G5）覆盖不到这一行。
        victim7 = os.path.join(d, "SIDE_EFFECT_IMPORT.txt")
        payload7 = (
            "def f(x):\n"
            + _C +
            "    return x\n\n"
            "__import__('pathlib').Path(r'%s').write_text('pwned')\n" % victim7
        )
        ok7, _r7 = _verify(payload7, [(1, 1)])
        check("G7 子进程执行器：__import__ 载荷（带 cases）⇒ 副作用文件不得被创建",
              not os.path.exists(victim7),
              "ok=%r exists=%r" % (ok7, os.path.exists(victim7)))

        # G5（**绕开 L1 的直接判据**）：把载荷直接 exec 进 SAFE_NS()，验证 open 不可用。
        # 为什么需要它：G1 走 verify() 全流程，而**L1 语法层可能先拒**某些载荷 ⇒
        # 即使把 SAFE_NS 退回空 dict（变异），文件也不会被创建 ⇒ G1 判据**恒真**、
        # 变异不点名（本笔实测：变异后 G1 仍 PASS，只点了 G4b）。本条直接打在
        # 执行命名空间上，才对该加固有判别力。
        victim2 = os.path.join(d, "SIDE_EFFECT_VIA_EXEC.txt")
        payload2 = "open(r'%s', 'w').write('x')" % victim2
        ns5 = V.SAFE_NS()
        blocked = False
        try:
            exec(compile(payload2, "<g5>", "exec"), ns5)   # noqa: S102 —— 守卫自身的有意调用
        except NameError:
            blocked = True
        except Exception:                      # noqa: BLE001
            blocked = True
        check("G5 直接 exec 进 SAFE_NS ⇒ open 不可用且无副作用",
              blocked and (not os.path.exists(victim2)),
              "blocked=%r exists=%r" % (blocked, os.path.exists(victim2)))

        # G4 SAFE_NS 白名单不含危险名
        ns = V.SAFE_NS()
        b = ns.get("__builtins__") or {}
        danger = [k for k in ("open", "eval", "exec", "compile",
                              "globals", "locals", "vars", "input") if k in b]
        check("G4 SAFE_NS 不含危险内建", not danger, "越界=%r" % (danger,))
        # G4c~G4e（issue #187 判据升级）：`__import__` 的处置由「不许有」升级为
        # 「只许有**受控**的」。判据强度不降反升——旧判据是「能力可达性」的**代理**
        # （代理：没有 __import__ ⇒ 碰不到外面），新判据**直接测**该能力属性：
        # ① 在场者不是真内置；② 危险模块逐项 ImportError；③ 纯计算模块可用。
        # 若将来有人把真内置塞回来，G4c 立红；把受控导入删掉，G4c 也红（设计已变更，
        # 见 md_cg/whitebox_kb/wisdom/verifier.py 的 _safe_builtins() 与 #187 守卫）。
        _gi = b.get("__import__")
        check("G4c SAFE_NS 的 __import__ 在位且非真内置（受控导入）",
              _gi is not None and _gi is not builtins.__import__,
              "present=%r is_real=%r" % (_gi is not None,
                                          _gi is builtins.__import__))
        _blocked = []
        for _m in ("os", "sys", "subprocess", "builtins", "importlib",
                   "ctypes", "socket"):
            try:
                _gi(_m)
                _blocked.append(_m)
            except ImportError:
                pass
            except Exception as _e:                          # noqa: BLE001
                _blocked.append("%s:%s" % (_m, type(_e).__name__))
        check("G4d SAFE_NS 的受控导入逐项拒绝危险模块", not _blocked,
              "未拦住=%r" % (_blocked,))
        try:
            _r = _gi("re")
            _ok_re = hasattr(_r, "search") and getattr(_r, "__builtins__", None) is None
        except Exception as _e:                              # noqa: BLE001
            _ok_re = False
            _r = "%s: %s" % (type(_e).__name__, _e)
        check("G4e SAFE_NS 的受控导入放行纯计算模块且不泄露裸 module",
              _ok_re, "%r" % (_r,))
        check("G4b SAFE_NS 保留常用纯函数（len/range/sorted 在）",
              all(k in b for k in ("len", "range", "sorted")), "")

        # G8 防回退锚点（#429 补）：执行器里那行被改写/移除时立红（fail-closed）。
        src = open(os.path.join(HERE, "whitebox_kb", "wisdom", "verifier.py"),
                   encoding="utf-8").read()
        check("G8 防回退锚点：子进程执行器的执行命名空间限 __builtins__ 那一行在场",
              _NS_ANCHOR in [ln.strip() for ln in src.splitlines()],
              "锚点=%s" % _NS_ANCHOR)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


# ---------------------------------------------------------------- 定点变异腿
def _mirror_build():
    dst = tempfile.mkdtemp(prefix="i91_mut_")
    for name in ("md_cg", "data", "scripts"):
        src = os.path.join(REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(REPO)):
        p = os.path.join(REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_TOKEN", "MDCG_VERIFY_KEY", "MDCG_ROOT", "MDCG_AUX_ROOT",
              "MDCG_TOKEN_FILE"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue91_verifier_sandbox"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=900)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln[len("[FAIL] "):].strip().split(" ")[0]
            for ln in out.splitlines() if ln.startswith("[FAIL] ")]
    return pr.returncode, reds, out


#: 变异后应转红的项：G1/G7（行为面：副作用文件真被创建）+ G8（锚点行被改写）。
_EXPECT = ("G1", "G7", "G8")


def _mutate():
    print("!! 定点变异自证：撤回子进程执行器的 __builtins__ 限白名单，G1/G7/G8 必须转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%r（必须 rc=0 且 0 红）" % (rc, reds))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print("\n".join(out.splitlines()[-20:]))
        p = os.path.join(tree, "md_cg", "whitebox_kb", "wisdom", "verifier.py")
        with open(p, encoding="utf-8", newline="") as f:
            bak = f.read()
        eol = "\r\n" if "\r\n" in bak else "\n"
        old = _RUNNER_NS.replace("\n", eol)
        if bak.count(old) != 1:
            bad.append("回退锚点命中 %d 次" % bak.count(old))
            print("  ANCHOR-MISS 回退锚点命中 %d 次" % bak.count(old))
        else:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak.replace(old, _RUNNER_NS_BAD.replace("\n", eol), 1))
            for root, _dd, _ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            hit = sorted(set(reds2))
            print("  变异后：rc=%d 红项=%r" % (rc2, hit))
            if rc2 != 0 and hit == sorted(_EXPECT):
                print("  OK   回退即红：指定红项 %r 全部命中" % (hit,))
            else:
                bad.append("回退后红项不符预期")
                print("  MISMATCH 实际=%r 期望=%r" % (hit, sorted(_EXPECT)))
                for ln in out2.splitlines():
                    if ln.startswith("[FAIL] "):
                        print("        " + ln)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    _rc = main()
    if "--mutate" in sys.argv and _rc == 0:
        _rc = 1 if _mutate() else 0
    sys.exit(_rc)
