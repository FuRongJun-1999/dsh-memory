# -*- coding: utf-8 -*-
r"""守卫 · #491 code_compose.verify_code 的 L2 必须复用 verifier 的受控执行器。

缺陷（GitHub #491，SEC·P1）：`code_compose.verify_code` 的 L2 自校验在**同进程**
裸 `exec(unit.get("py_ref", ""), ns)` / `exec(code, ns)` 里跑——无 `__builtins__`
限制、无超时、无步数闸。同族的 `verifier.py` 在 #91 已修（受限白名单 +
子进程 + `subprocess` 超时），本文件是**另一载体**，未收。

修法（条件层）：不新建第二套沙箱——`code_compose` 经 `_load_verifier()` 取同一
个 verifier 模块，L2 一律走 `verifier.run_guarded`（委托 `_run_guarded`：
`SAFE_NS` 受限内建 + 子进程 + 超时）。本守卫证明：裸 `exec` 调用点在 AST 级清零、
超时在三条载荷上均有界、`open()` 副作用不再发生，且原有判据语义不被放宽。

判据（默认模式全绿；`--mutate` 时每条定点变异必须让**点名判据**转红）
  S1 AST：`code_compose.py` 内 `exec`/`eval` 调用点**清零**
  S2 单点：`_compose_exec` 调用 `run_guarded`；`code_compose` 不 import
     `subprocess`/不 `Popen`（沙箱只有 verifier 一份）；`verifier.run_guarded`
     委托 `_run_guarded`
  S3 函数级死循环 ⇒ 有界返回失败（不挂死；外层守护硬超时兜底）
  S4 模块级死循环 ⇒ 同上
  S5 py_ref 死循环（lang=rust 分支）⇒ 同上
  S6 `open()` 载荷 ⇒ 无副作用文件、判负
  S7 正对照：正常模板仍通过（不误伤）
  S8 判据不放宽：期望值严格相等（dict 子集匹配**不得**渗入本层）
  S9 语义保留：函数取「命名空间首个可调用对象」；tuple 多参样例与 'call' 标记照旧

生效条件：被守卫文件为 `md_cg/whitebox_kb/wisdom/{code_compose,verifier}.py`；
判据只依赖公开函数面（`verify_code` / `run_guarded` / `_run_guarded`）。
子功能：静态面（S1/S2）在父进程 AST 判；执行面（S3~S9）在子进程判——若加固被
变异摘掉，子进程会被父侧强杀并判红，守卫自身不会跟着挂死。
执行：`python -X utf8 -m md_cg.test_issue491_compose_sandbox`
      `python -X utf8 -m md_cg.test_issue491_compose_sandbox --mutate`
验证方式：默认模式退出码 0；`--mutate` 每条变异命中点名红项后退出码 0。
不适用条件：不判 `code_compose` 的域路由/组合生成质量（#187/#401 面）；不判
`verifier` 六层判据本身（#91 两个守卫覆盖）；不判 POSIX 下的进程树拆除
（本守卫只断言「有界返回 + 子进程被回收」）。
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WISDOM = os.path.join(REPO, "md_cg", "whitebox_kb", "wisdom")
CC_PATH = os.path.join(WISDOM, "code_compose.py")
V_PATH = os.path.join(WISDOM, "verifier.py")

#: 守卫注入的执行时限（小值；生产默认 EXEC_TIMEOUT_S=20 由 verifier 一处提供）
GUARD_TIMEOUT = 1.0
#: 外层守护：子进程硬上界（正常一轮约 6s；加固被摘掉则在此被强杀 ⇒ 判红）
OUTER_TIMEOUT = float(os.environ.get("MDCG_P491_OUTER_TIMEOUT") or 30.0)

PASS = 0
FAIL = 0
FAILS: list = []

S1 = "S1 AST：code_compose 无 exec/eval 调用点"
S2 = "S2 单点：L2 经 verifier.run_guarded（不新建第二套沙箱）"
S3 = "S3 函数级死循环有界返回失败"
S4 = "S4 模块级死循环有界返回失败"
S5 = "S5 py_ref 死循环有界返回失败"
S6 = "S6 open() 载荷无副作用且判负"
S7 = "S7 正对照：正常模板仍通过"
S8 = "S8 判据不放宽：期望严格相等"
S9 = "S9 语义保留：首可调用 / 多参 / call 标记"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))
    return bool(cond)


# --------------------------------------------------------------------------
# 子进程侧：执行面判据（S3~S9）
# 经 MDCG_P491_DIR 指定「code_compose.py / verifier.py 所在目录」——变异时指向
# 临时目录里的变异副本，正常时指向仓内真源。
# --------------------------------------------------------------------------
_CHILD_SRC = r'''
import json
import os
import sys
import tempfile
import time

DIR = os.environ["MDCG_P491_DIR"]
TO = float(os.environ["MDCG_P491_TIMEOUT"])
sys.path.insert(0, DIR)
import code_compose as CC            # noqa: E402  —— _load_verifier() 会从同目录取 verifier

CC.COMPOSE_EXEC_TIMEOUT_S = TO

out = {}


def timed(fn):
    t0 = time.time()
    try:
        r = fn()
        err = ""
    except Exception as e:            # noqa: BLE001
        r, err = None, "%s: %s" % (type(e).__name__, e)
    return r, err, time.time() - t0


def rec(key, fn):
    r, err, dt = timed(fn)
    out[key] = {"ok": None if r is None else r[0],
                "checks": [] if r is None else r[1],
                "err": err, "sec": round(dt, 2)}


LOOP_FN = "def solve(x):\n    while True:\n        pass\n"
LOOP_TOP = "def solve(x):\n    return x\n\nwhile True:\n    pass\n"
GOOD = "def solve(arr):\n    return sorted(arr)\n"


# S3 函数级死循环
rec("s3", lambda: CC.verify_code(LOOP_FN, {"task": "x", "cases": [([1], 1)]}))
# S4 模块级死循环
rec("s4", lambda: CC.verify_code(LOOP_TOP, {"task": "x", "cases": [([1], 1)]}))
# S5 py_ref 死循环（lang != python 分支）
rec("s5", lambda: CC.verify_code(
    "fn solve(x) { }",
    {"task": "x", "cases": [([1], 1)], "py_ref": "while True:\n    pass\n"},
    lang="rust"))


# S6 open() 载荷（模块级、判定前执行）
def s6():
    d = tempfile.mkdtemp(prefix="p491_")
    victim = os.path.join(d, "SIDE_EFFECT_CREATED.txt")
    code = 'def solve(x):\n    return x\n\nopen(r"%s", "w").write("x")\n' % victim
    r = CC.verify_code(code, {"task": "x", "cases": [([1], 1)]})
    return r, victim


_r, _err, _dt = timed(s6)
# s6 的返回是 ((ok, checks), victim 路径)
out["s6"] = {"ok": (_r[0][0] if _r else None),
             "checks": (_r[0][1] if _r else []),
             "err": _err,
             "created": bool(_r and os.path.exists(_r[1]))}

# S7 正对照
rec("s7", lambda: CC.verify_code(
    GOOD, {"task": "x", "cases": [([3, 1, 2], [1, 2, 3]), ([], [])]}))
# S8 判据不放宽：返回 dict 含额外键 ⇒ 与期望严格不等，必须判负
rec("s8", lambda: CC.verify_code(
    "def solve(x):\n    return {'a': 1, 'b': 2}\n",
    {"task": "x", "cases": [(1, {"a": 1})]}))
# S9a 首可调用（helper 先于 solve 定义 ⇒ 原语义取 helper）
rec("s9a", lambda: CC.verify_code(
    "def helper(x):\n    return x + 1\ndef solve(x):\n    return x * 10\n",
    {"task": "x", "cases": [(2, 3)]}))
# S9b 多参 tuple 样例 + 'call' 标记
rec("s9b", lambda: CC.verify_code(
    "def solve(a, b):\n    return a + b\n",
    {"task": "x", "cases": [((2, 3), 5), ("call", "x")]}))
# S9c py_ref 分支不展开 tuple（原实现 `fn(inp)`——单参传入）
rec("s9c", lambda: CC.verify_code(
    "fn solve(x) { }",
    {"task": "x", "cases": [((1, 2), (1, 2))],
     "py_ref": "def solve(x):\n    return x\n"},
    lang="rust"))

print("@@P491@@" + json.dumps(out, ensure_ascii=False))
'''


def _kill_tree(pid: int, popen) -> None:
    """拆除整个进程树（外层守护；Windows 走 taskkill /T，POSIX 走 killpg）。"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
        else:
            os.killpg(os.getpgid(pid), 9)
    except Exception:
        pass
    for fn in (getattr(popen, "kill", None),):
        try:
            fn()
        except Exception:
            pass
    try:
        popen.wait(timeout=5)
    except Exception:
        pass


def _run_child(src_dir: str):
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "MDCG_P491_DIR": src_dir,
                "MDCG_P491_TIMEOUT": repr(GUARD_TIMEOUT)})
    env.pop("MDCG_TOKEN", None)          # 派工书 §0：父 shell 令牌会污染子进程
    env.pop("MDCG_VERIFY_KEY", None)
    import time
    t0 = time.time()
    kw = {}
    if os.name != "nt":
        kw["start_new_session"] = True
    try:
        p = subprocess.Popen([sys.executable, "-X", "utf8", "-c", _CHILD_SRC],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env, encoding="utf-8", errors="replace", **kw)
    except Exception as e:                              # noqa: BLE001
        return {"hang": False, "sec": 0.0, "out": "",
                "stderr": "无法启动判据子进程: %s" % e}
    try:
        out, err = p.communicate(timeout=OUTER_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_tree(p.pid, p)
        return {"hang": True, "sec": time.time() - t0, "out": ""}
    m = re.search(r"@@P491@@(.*)", out, re.S)
    if not m:
        return {"hang": False, "sec": time.time() - t0, "out": out,
                "stderr": (err or "")[-500:]}
    return {"hang": False, "sec": time.time() - t0, "data": json.loads(m.group(1))}


# --------------------------------------------------------------------------
# 静态面判据（父进程 AST，不执行任何被校验代码）
# --------------------------------------------------------------------------
def _calls(tree):
    """收集所有调用点的名字（Name/Attribute 两种形态）。"""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            nm = (f.id if isinstance(f, ast.Name)
                  else (f.attr if isinstance(f, ast.Attribute) else "?"))
            out.append((nm, n.lineno))
    return out


def _func_node(tree, name):
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def static_checks(src_dir: str):
    cc_src = open(os.path.join(src_dir, "code_compose.py"), encoding="utf-8").read()
    v_src = open(os.path.join(src_dir, "verifier.py"), encoding="utf-8").read()
    cc_tree = ast.parse(cc_src)
    v_tree = ast.parse(v_src)

    bare = [(nm, ln) for nm, ln in _calls(cc_tree) if nm in ("exec", "eval")]
    check(S1, not bare, "裸调用点=%r" % (bare,))

    # S2 单点收束
    compose_exec = _func_node(cc_tree, "_compose_exec")
    rg_calls = [] if compose_exec is None else \
        [(nm, ln) for nm, ln in _calls(compose_exec) if nm == "run_guarded"]
    imports = [a.name for n in ast.walk(cc_tree)
               if isinstance(n, ast.Import) for a in n.names]
    imports += [n.module or "" for n in ast.walk(cc_tree)
                if isinstance(n, ast.ImportFrom)]
    subproc = [m for m in imports if m.split(".")[0] == "subprocess"]
    v_run = _func_node(v_tree, "run_guarded")
    v_delegate = [] if v_run is None else \
        [(nm, ln) for nm, ln in _calls(v_run) if nm == "_run_guarded"]
    check(S2, bool(rg_calls) and not subproc and bool(v_delegate),
          "run_guarded@%r subprocess_import=%r verifier委托=%r"
          % (rg_calls, subproc, v_delegate))


def judge(data):
    """把子进程读数判成 S3~S9。"""
    budget = GUARD_TIMEOUT * 8          # 宽松上界（含进程启停开销）

    def timed_out(k):
        d = data.get(k) or {}
        ev = " ".join(str(x) for x in (d.get("checks") or []))
        return (d.get("err") == "" and d.get("ok") is False
                and "超时" in ev and d.get("sec", 1e9) < budget)

    check(S3, timed_out("s3"),
          "ok=%r sec=%r checks=%r" % (data.get("s3", {}).get("ok"),
                                      data.get("s3", {}).get("sec"),
                                      (data.get("s3", {}).get("checks") or [""])[0][:80]))
    check(S4, timed_out("s4"),
          "ok=%r sec=%r checks=%r" % (data.get("s4", {}).get("ok"),
                                      data.get("s4", {}).get("sec"),
                                      (data.get("s4", {}).get("checks") or [""])[0][:80]))
    check(S5, timed_out("s5"),
          "ok=%r sec=%r checks=%r" % (data.get("s5", {}).get("ok"),
                                      data.get("s5", {}).get("sec"),
                                      (data.get("s5", {}).get("checks") or [""])[0][:80]))

    s6 = data.get("s6") or {}
    check(S6, s6.get("ok") is False and s6.get("created") is False,
          "ok=%r created=%r" % (s6.get("ok"), s6.get("created")))

    s7 = data.get("s7") or {}
    check(S7, s7.get("ok") is True and s7.get("err") == "",
          "ok=%r checks=%r" % (s7.get("ok"), (s7.get("checks") or [""])[0][:60]))

    s8 = data.get("s8") or {}
    check(S8, s8.get("ok") is False,
          "ok=%r（严格相等下 dict 多键必须判负）" % (s8.get("ok"),))

    s9a = data.get("s9a") or {}
    s9b = data.get("s9b") or {}
    s9c = data.get("s9c") or {}
    check(S9, s9a.get("ok") is True and s9b.get("ok") is True
          and s9c.get("ok") is True,
          "s9a=%r s9b=%r s9c=%r" % (s9a.get("ok"), s9b.get("ok"), s9c.get("ok")))


# --------------------------------------------------------------------------
# 定点变异自证（在临时副本上做，不落仓）
# --------------------------------------------------------------------------
MUTATIONS = (
    ("M1 在 _compose_exec 里塞回裸 exec（沙箱被摘掉）", "cc",
     "    res = V.run_guarded(code, cases, func_name, \"compose\", timeout, unpack)",
     "    exec(code, {})\n"
     "    res = {\"exec\": \"ok\", \"found\": True, \"results\": []}",
     (S1, S2)),
    ("M2 摘掉超时（不再经 run_guarded，同进程直接跑样例）", "cc",
     "    res = V.run_guarded(code, cases, func_name, \"compose\", timeout, unpack)",
     "    _ns = {}\n"
     "    exec(code, _ns)\n"
     "    _fn = next(v for k, v in _ns.items()\n"
     "               if callable(v) and not k.startswith('__'))\n"
     "    for _c in cases:\n"
     "        if _c[0] == 'call':\n"
     "            continue\n"
     "        _fn(*_c[0]) if isinstance(_c[0], tuple) else _fn(_c[0])\n"
     "    res = {\"exec\": \"ok\", \"found\": True, \"results\": []}",
     (S1, S3)),
    ("M3 受控执行器命名空间退回空 dict（内建白名单被摘掉）", "v",
     '    ns = {"__builtins__": _safe_builtins(), "__name__": "__mdcg_verify__"}',
     "    ns = {}",
     (S6,)),
    ("M4 compose 面放宽为 dict 子集匹配（判据被放宽）", "v",
     '        ok_match = (got == exp) if mode == "compose" else _match(got, exp)',
     "        ok_match = _match(got, exp)",
     (S8,)),
    ("M5 一律展开 tuple 入参（py_ref 分支原语义被改）", "v",
     '            got = (fn(*inp) if (isinstance(inp, tuple) and p.get("unpack", True))',
     '            got = (fn(*inp) if (isinstance(inp, tuple) and True)',
     (S9,)),
)


def _mutant_dir(cc_old, cc_new, v_old, v_new):
    """把变异副本写进临时目录；任一锚点缺失返回 None。"""
    cc_src = open(CC_PATH, encoding="utf-8").read()
    v_src = open(V_PATH, encoding="utf-8").read()
    if cc_old is not None and cc_old not in cc_src:
        return None
    if v_old is not None and v_old not in v_src:
        return None
    d = tempfile.mkdtemp(prefix="p491mut_")
    with open(os.path.join(d, "code_compose.py"), "w", encoding="utf-8") as f:
        f.write(cc_src.replace(cc_old, cc_new, 1) if cc_old is not None else cc_src)
    with open(os.path.join(d, "verifier.py"), "w", encoding="utf-8") as f:
        f.write(v_src.replace(v_old, v_new, 1) if v_old is not None else v_src)
    return d


def mutations_run() -> bool:
    print("")
    print("=" * 64)
    print("定点变异自证（每条变异必须让点名判据转红）")
    print("=" * 64)
    global PASS, FAIL, FAILS
    snap_pass, snap_fail, snap_fails = PASS, FAIL, list(FAILS)
    ok_all = True
    for label, target, old, new, wanted in MUTATIONS:
        print("--- %s" % label)
        is_cc = (target == "cc")
        d = _mutant_dir(old if is_cc else None, new if is_cc else None,
                        old if not is_cc else None, new if not is_cc else None)
        if d is None:
            print("    [MUT-ANCHOR-MISS] 锚点在当前源码里找不到（实现改了却没同步本表）")
            ok_all = False
            continue
        FAIL = 0
        FAILS.clear()
        child = _run_child(d)
        if child["hang"]:
            check(wanted[0], False, "子进程 %.1fs 未返回（挂死）" % OUTER_TIMEOUT)
            if len(wanted) > 1:
                check(wanted[1], False, "同上（挂死）")
            if "data" in child:
                judge(child["data"])
        elif "data" not in child:
            check("变异体判据子进程产出判决", False,
                  "stdout=%r stderr=%r" % (child["out"][-200:],
                                           child.get("stderr", "")[-200:]))
        else:
            judge(child["data"])
        static_checks(d)
        reds = list(FAILS)
        hit = [w for w in wanted if any(w in r for r in reds)]
        print("    变异后红项：%s" % (reds or "（无——变异未被判据发现 = 假绿）"))
        if hit:
            print("    ✓ 点名命中 %s" % list(hit))
        else:
            print("    ✗ 未点名 %s —— 该加固缺判别力" % (list(wanted),))
            ok_all = False
        PASS, FAIL, FAILS = snap_pass, snap_fail, list(snap_fails)
        shutil.rmtree(d, ignore_errors=True)
    return ok_all


def main() -> int:
    mutate = "--mutate" in sys.argv
    for p in (CC_PATH, V_PATH):
        if not os.path.exists(p):
            print("[FAIL] 预期文件不存在：%s" % p)
            return 1

    child = _run_child(WISDOM)
    if child["hang"]:
        print("[FAIL] 执行面判据子进程挂死（>%ss 未返回）——加固失效" % OUTER_TIMEOUT)
        print("       stdout 尾部：%s" % child["out"][-400:])
        for n in (S3, S4, S5):
            check(n, False, "子进程挂死，被外层守护强制终止")
    elif "data" not in child:
        print("[FAIL] 判据子进程未产出判决；stderr=%r"
              % (child.get("stderr", "")[-300:],))
        check("判据子进程产出判决", False, "见上")
    else:
        judge(child["data"])
    static_checks(WISDOM)

    mut_ok = True
    if mutate:
        mut_ok = mutations_run()

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if (FAIL or not mut_ok) else 0


if __name__ == "__main__":
    sys.exit(main())
