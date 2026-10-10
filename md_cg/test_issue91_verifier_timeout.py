# -*- coding: utf-8 -*-
r"""守卫 · #91（根因③）whitebox verifier 的被校验代码必须在**受控时限**内运行。

缺陷（GitHub #91，本笔处置第三项）：`Verifier` 的三处 `exec(compile(req.code, …), ns)`
（L2 样例 / L3 边界 / 集成）是**同步阻塞**——被校验代码（模型可控输入）里一个
`while True: pass` 即令调用方**永久挂死**。修前实测：`verify()` 对死循环载荷
永不返回（无任何时间上界）。

形态＝**子进程 + subprocess 超时**（理由见 `verifier.py` 的 `EXEC_TIMEOUT_S` 段：
同进程 `signal.alarm` 在 Windows 上不存在；看门狗线程杀不掉 `while True`，投递的
异步异常被裸 `except` 吞掉即永久挂死且吃满 GIL；独立进程可被无条件终止，
超时路径 kill＋wait 不留僵尸）。超时＝**fail-closed**（判负返回），不静默回退、
不静默通过。

判据（`--mutate` 时逐条做定点变异，必红并**点名**）
  T1a 模块级死循环载荷 ⇒ `verify()` 在给定时限内返回**失败**（不挂死）
  T1b 函数级死循环载荷（样例调用）⇒ 同上
  T2  **正对照**：合法载荷照常通过（L2 报「N 组样例全部通过」）
  T3  连续超时载荷 ⇒ 子进程个个被**回收**（reaped）、存活 python 进程数不增长；
      其后的全链路调用仍正常（不泄漏、不卡住后续调用）
  T4  防回退：`_SAFE_BUILTIN_NAMES` 不含 `__import__`/`open`/`eval`；
      `_STDLIB_OK` 不含 `os`/`sys`/`socket`/`threading`
  T5  缓存面：超时结果**不得**被固化成缓存条目（更不得缓存成 ok）；正对照＝
      正常载荷确会写缓存
  T6  结构防回退：`Verifier` 类体内执行全部经 `_run_guarded`（3 处），
      类体内**没有** `exec`/`compile` 裸调用

★为什么 T1/T2/T3/T5 要在**外层守护**里跑：本守卫正是判「不挂死」的——若把死循环
载荷直接跑在守卫主进程里，一旦加固被变异摘掉，**守卫自身也挂死**，连「红」都印
不出来。故这几条经子进程执行、父侧以硬超时兜底：子进程被父侧强杀 ⇒ 直接判红
「挂死（外层守护强制终止）」。

测试时长：超时值一律用**小值**（默认 0.8s），不用产品默认 20s——不让守卫拖慢整套。

运行
    python -X utf8 -m md_cg.test_issue91_verifier_timeout            # 全绿裁决
    python -X utf8 -m md_cg.test_issue91_verifier_timeout --mutate   # 定点变异自证
退出码：0 全绿 ｜ 1 有断言失败 / 变异未被判据发现
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFIER = os.path.join(REPO, "md_cg", "whitebox_kb", "wisdom", "verifier.py")
WISDOM = os.path.dirname(VERIFIER)

#: 守卫内使用的受控时限（**小值**——产品默认 EXEC_TIMEOUT_S=20，守卫不用它，
#: 免得把整套测试拖长；判据与时限绝对值无关，只判「有界且 fail-closed」）。
GUARD_TIMEOUT = 0.8
#: 外层守护：子进程的硬上界（正常全绿轮约 6s；加固被摘掉则在此被强杀——判红）
OUTER_TIMEOUT = float(os.environ.get("MDCG_P91_OUTER_TIMEOUT") or 20.0)

PASS = 0
FAIL = 0
FAILS: list = []

T1A = "T1a 模块级死循环 ⇒ 有界返回失败（不挂死）"
T1B = "T1b 函数级死循环 ⇒ 有界返回失败（不挂死）"
T3D = "T3d 子进程整体墙钟有界（外层守护未触发强杀）"


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
# 子进程侧：受控时限判据（T1a/T1b/T2/T3/T5）
# 经环境变量 MDCG_P91_SRC 选择「要加载的 verifier 源码」——变异时指向临时文件，
# 正常时指向仓内真源。父侧只认它打印的 JSON 判决。
# --------------------------------------------------------------------------
_CHILD_SRC = r'''
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

WISDOM = os.environ["MDCG_P91_WISDOM"]
SRC = os.environ["MDCG_P91_SRC"]
TO = float(os.environ["MDCG_P91_TIMEOUT"])

sys.path.insert(0, WISDOM)
spec = importlib.util.spec_from_file_location("verifier_under_test", SRC)
V = importlib.util.module_from_spec(spec)
sys.modules["verifier_under_test"] = V          # dataclass 需要模块在场
spec.loader.exec_module(V)

out = {}
tmp = tempfile.mkdtemp(prefix="p91g_")
LOOP_TOP = "def f(x):\n    return x\n\nwhile True:\n    pass\n"
LOOP_FN = "def f(x):\n    while True:\n        pass\n"
GOOD = "# 加一\ndef f(x):\n    \"\"\"加一。\"\"\"\n    return x + 1\n"

def verifier(**kw):
    # 隔离缓存：不读也不写仓内 verify_cache.json / savings 日志
    cache = V.VerifyCache(path=os.path.join(tmp, "c.json"), savings_log=None)
    return V.Verifier(cache=cache, exec_timeout=TO), cache


def timed(fn):
    t0 = time.time()
    try:
        r, err = fn(), ""
    except Exception as e:
        r, err = None, "%s: %s" % (type(e).__name__, e)
    return r, err, time.time() - t0


def l2_of(r):
    if r is None:
        return {}
    return next((c for c in r.checks if c.get("level") == "L2样例"), {})


# ---------- T1a：模块级死循环（exec(compile(...)) 自身挂死） ----------
# 必须带 cases：L2 在**无样例**时短路跳过（不执行任何代码），那只是「没跑」而不是
# 「跑了但有界」——判在没跑的那一层上，判据恒真（#91 已有先例教训）。
# ★判据打在 **L2 那一层**上（l2_ok），不打在整体 ok 上：本载荷无中文注释，「规范
# 符合性」层无论如何都会判负 ⇒ 拿整体 ok 当判据则**超时静默放行也照样「红」**，
# 判别力为零（同 #91 首版 G1 的坑）。l2_ok 才是被改造的那一层。
v, _c = verifier()
r, err, dt = timed(lambda: v.verify(V.VerifyRequest(
    task="unit", code=LOOP_TOP, unit_id="t1a", cases=[(1, 1)])))
c = l2_of(r)
out["t1a"] = {"sec": dt, "err": err, "ok": (r.ok if r else None),
              "l2_ok": c.get("ok"),
              "ev": str(c.get("evidence", ""))[:120],
              "blocked": bool(c.get("guard_blocked"))}

# ---------- T1b：函数级死循环（样例调用挂死） ----------
v, _c = verifier()
r, err, dt = timed(lambda: v.verify(V.VerifyRequest(
    task="unit", code=LOOP_FN, unit_id="t1b", cases=[(1, 1)])))
c = l2_of(r)
out["t1b"] = {"sec": dt, "err": err, "ok": (r.ok if r else None),
              "l2_ok": c.get("ok"),
              "ev": str(c.get("evidence", ""))[:120],
              "blocked": bool(c.get("guard_blocked"))}

# ---------- T2：正对照（合法载荷照常通过） ----------
v, _c = verifier()
r, err, dt = timed(lambda: v.verify(V.VerifyRequest(
    task="unit", code=GOOD, unit_id="t2", cases=[(1, 2), (0, 1)])))
c = l2_of(r)
out["t2"] = {"sec": dt, "err": err, "ok": (r.ok if r else None),
             "l2_ok": c.get("ok"),
             "ev": str(c.get("evidence", ""))[:120]}


# ---------- T3：连续超时后不泄漏、后续调用仍正常 ----------
def live_python():
    """存活 python 进程数（探针不可用返回 None＝该子项跳过，如实标注）。"""
    try:
        if os.name == "nt":
            p = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe",
                                "/FO", "CSV", "/NH"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               check=False)
            txt = p.stdout.decode("utf-8", "replace")
            return sum(1 for ln in txt.splitlines() if "python.exe" in ln.lower())
        n = 0
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % d, "rb") as f:
                    if b"python" in f.read():
                        n += 1
            except Exception:
                pass
        return n
    except Exception:
        return None


before = live_python()
reaped, kinds, secs = [], [], []
for i in range(3):
    res = V._run_guarded(LOOP_FN, [(1, 1)], "f", "samples", TO)
    kinds.append(res.get("exec"))
    reaped.append(res.get("reaped"))
    secs.append(res.get("timeout"))
after = live_python()
v, _c = verifier()
r, err, dt = timed(lambda: v.verify(V.VerifyRequest(
    task="unit", code=LOOP_FN, unit_id="t3_full", cases=[(1, 1)])))
full_c = l2_of(r)
full_ok, full_l2, full_dt = (r.ok if r else None), full_c.get("ok"), dt
v, _c = verifier()
r, err, dt = timed(lambda: v.verify(V.VerifyRequest(
    task="unit", code=GOOD, unit_id="t3_ok", cases=[(1, 2)])))
out["t3"] = {"kinds": kinds, "reaped": reaped, "timeout": secs[0],
             "before": before, "after": after, "full_ok": full_ok,
             "full_l2_ok": full_l2, "full_sec": full_dt,
             "ok_after": (r.ok if r else None), "err": err}

# ---------- T5：超时结果不得被固化进缓存（也不得缓存成 ok） ----------
# 同样必须带 cases（见 T1a 注）：否则 L2 短路，超时根本没发生，T5 就成了空判。
LOOP_MASK = "def f(x):\n    return x\n\nwhile True:\n    pass\n# t5\n"
v, cache = verifier()
req5 = V.VerifyRequest(task="unit", code=LOOP_MASK, unit_id="t5",
                       cases=[(1, 1)])
r, err, dt = timed(lambda: v.verify(req5))
fp = req5.fingerprint()
c5 = l2_of(r)
out["t5"] = {"ok": (r.ok if r else None), "l2_ok": c5.get("ok"),
             "blocked": bool(c5.get("guard_blocked")),
             "cached": cache.get(fp) is not None,
             "reason": str(r.reason if r else "")[:80]}
# 正对照：正常载荷确会写缓存
v2, cache2 = verifier()
req5b = V.VerifyRequest(task="unit", code=GOOD, unit_id="t5b", cases=[(1, 2)])
r5b, err, dt = timed(lambda: v2.verify(req5b))
out["t5"]["ctrl_cached"] = cache2.get(req5b.fingerprint()) is not None
out["t5"]["ctrl_ok"] = (r5b.ok if r5b else None)

print("@@P91@@" + json.dumps(out, ensure_ascii=False))
'''


def _kill_tree(pid: int, popen) -> None:
    """拆除**整个进程树**（守卫外层守护专用）。

    为什么不能只 `popen.kill()`：本条判据的子进程自己也 Popen 执行器——只杀直接
    子进程会让孙进程（真跑载荷的那个）成孤儿继续死循环。故 Windows 走
    `taskkill /F /T`（tree），POSIX 走进程组 `killpg`。两者都在**同一 argv 列表**
    语义下调用（纪律 15），失败即忽略（清理尽力而为，判红不受影响）。
    """
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
        else:
            os.killpg(os.getpgid(pid), 9)
    except Exception:
        pass
    try:
        popen.kill()
    except Exception:
        pass
    try:
        popen.wait(timeout=5)
    except Exception:
        pass


def _run_child(src_path: str):
    """在子进程里跑受控时限判据；父侧硬超时兜底（挂死 ⇒ 判红而非跟着挂）。"""
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "MDCG_P91_WISDOM": WISDOM,
                "MDCG_P91_SRC": src_path,
                "MDCG_P91_TIMEOUT": repr(GUARD_TIMEOUT)})
    t0 = time.time()
    kw = {}
    if os.name != "nt":
        kw["start_new_session"] = True          # 便于 killpg 拆树
    try:
        p = subprocess.Popen([sys.executable, "-X", "utf8", "-c", _CHILD_SRC],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env, **kw)
    except Exception as e:
        return {"hang": False, "sec": 0.0, "out": "",
                "stderr": "无法启动判据子进程: %s" % e}
    try:
        out, err = p.communicate(timeout=OUTER_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_tree(p.pid, p)                    # 挂死 ⇒ 拆整棵树（含孙进程）
        return {"hang": True, "sec": time.time() - t0, "out": ""}
    txt = out.decode("utf-8", "replace")
    m = re.search(r"@@P91@@(.*)", txt, re.S)
    if not m:
        return {"hang": False, "sec": time.time() - t0, "out": txt,
                "stderr": err.decode("utf-8", "replace")[-500:]}
    return {"hang": False, "sec": time.time() - t0, "data": json.loads(m.group(1))}


def _proc_ok(t3):
    if t3["before"] is None or t3["after"] is None:
        print("       （进程计数探针不可用 ⇒ T3b 跳过，如实标注）")
        return True
    return (t3["after"] - t3["before"]) <= 1      # 允许 1 台外部抖动


def _hang_reds():
    """子进程挂死 ⇒ 时限类判据一并判红（挂死本身就是「加固失效」的读数）。"""
    for n in (T1A, T1B, T3D):
        check(n, False, "子进程 %.1fs 未返回，被外层守护强制终止（挂死）"
                        % OUTER_TIMEOUT)


def judge(data, sec):
    """把子进程读数判成 T1a/T1b/T2/T3/T5。"""
    d = data
    budget = GUARD_TIMEOUT * 4          # 「有界」的宽松上界（含进程启停开销）

    a = d["t1a"]
    check(T1A, a["err"] == "" and a["l2_ok"] is False and a["blocked"] is True
          and a["sec"] < budget,
          "l2_ok=%r blocked=%r sec=%.2fs ev=%s"
          % (a["l2_ok"], a.get("blocked"), a["sec"], a["ev"][:60]))

    b = d["t1b"]
    check(T1B, b["err"] == "" and b["l2_ok"] is False and b["blocked"] is True
          and b["sec"] < budget,
          "l2_ok=%r blocked=%r sec=%.2fs ev=%s"
          % (b["l2_ok"], b.get("blocked"), b["sec"], b["ev"][:60]))

    t2 = d["t2"]
    check("T2（正对照）合法载荷仍通过（整体 ok 与 L2 层都通过）",
          t2["err"] == "" and t2["ok"] is True and t2["l2_ok"] is True,
          "ok=%r l2_ok=%r ev=%s" % (t2["ok"], t2["l2_ok"], t2["ev"][:60]))

    t3 = d["t3"]
    check("T3a 超时子进程被回收（kill 后 wait，无残留）",
          all(x is True for x in t3["reaped"]) and
          all(k == "timeout" for k in t3["kinds"]),
          "kinds=%r reaped=%r" % (t3["kinds"], t3["reaped"]))
    check("T3b 连续超时后存活进程数不增长", _proc_ok(t3),
          "before=%r after=%r" % (t3["before"], t3["after"]))
    check("T3c 连续超时后后续调用仍正常（全链路 L2 有界判负 + 正常载荷通过）",
          t3["err"] == "" and t3["full_l2_ok"] is False
          and t3["ok_after"] is True and t3["full_sec"] < budget,
          "full_l2_ok=%r full_sec=%.2fs ok_after=%r"
          % (t3["full_l2_ok"], t3["full_sec"], t3["ok_after"]))

    t5 = d["t5"]
    check("T5a 超时结果不被固化成缓存条目（不会缓存成 ok）",
          t5["l2_ok"] is False and t5["blocked"] is True and t5["cached"] is False,
          "l2_ok=%r blocked=%r cached=%r" % (t5["l2_ok"], t5["blocked"],
                                             t5["cached"]))
    check("T5b（正对照）正常载荷确会写缓存",
          t5["ctrl_ok"] is True and t5["ctrl_cached"] is True,
          "ctrl_ok=%r ctrl_cached=%r" % (t5["ctrl_ok"], t5["ctrl_cached"]))

    check(T3D, sec < OUTER_TIMEOUT,
          "child sec=%.2fs outer=%.1fs" % (sec, OUTER_TIMEOUT))


# --------------------------------------------------------------------------
# T4/T6：父进程内的静态判据（不执行任何被校验代码，故无挂死风险）
# --------------------------------------------------------------------------
def _load_module(src_path: str, name: str):
    """按文件路径加载 verifier 模块（**注册进 sys.modules**——`@dataclass` 在
    处理注解时要经 `sys.modules[cls.__module__]` 反查，裸 exec 会 AttributeError）。"""
    import importlib.util
    if WISDOM not in sys.path:
        sys.path.insert(0, WISDOM)
    spec = importlib.util.spec_from_file_location(name, src_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def static_checks(src_path: str):
    src = open(src_path, encoding="utf-8").read()
    ns = vars(_load_module(src_path, "verifier_guard_under_test"))

    # T4：白名单收窄防回退（issue #91 根因①②；本笔只补守卫把它钉住）
    names = set(ns["_SAFE_BUILTIN_NAMES"])
    danger = sorted(n for n in ("__import__", "open", "eval", "exec", "compile",
                                "globals", "locals", "vars", "input")
                    if n in names)
    check("T4a _SAFE_BUILTIN_NAMES 不含 __import__/open/eval 等危险内建",
          not danger, "越界=%r" % (danger,))
    stdlib = set(ns["_STDLIB_OK"])
    banned = sorted(m for m in ("os", "sys", "socket", "threading")
                    if m in stdlib)
    check("T4b _STDLIB_OK 不含 os/sys/socket/threading", not banned,
          "越界=%r" % (banned,))
    check("T4c _STDLIB_OK 仍保留常用纯标准库（collections/math/itertools 在）",
          {"collections", "math", "itertools"} <= stdlib, "")

    # T6：结构防回退——三处执行必须全走 _run_guarded；类体内不得再有裸 exec/compile
    tree = ast.parse(src)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "Verifier")
    calls = []
    for n in ast.walk(cls):
        if isinstance(n, ast.Call):
            f = n.func
            nm = (f.id if isinstance(f, ast.Name)
                  else (f.attr if isinstance(f, ast.Attribute) else "?"))
            if nm in ("exec", "compile", "_run_guarded"):
                calls.append("%s@%d" % (nm, n.lineno))
    guard_calls = [c for c in calls if c.startswith("_run_guarded")]
    bare = [c for c in calls if c.startswith(("exec", "compile"))]
    check("T6a Verifier 类体内执行全部经 _run_guarded（3 处）",
          len(guard_calls) == 3, "guard_calls=%r" % (guard_calls,))
    check("T6b Verifier 类体内无裸 exec/compile 调用",
          not bare, "bare=%r" % (bare,))
    check("T6c 时限可注入（Verifier(exec_timeout=…)）且默认取模块常量 EXEC_TIMEOUT_S",
          "self.exec_timeout" in src and "EXEC_TIMEOUT_S" in src, "")


# --------------------------------------------------------------------------
# 定点变异自证：每条变异精确指向一条判据，且必须**落到具体断言名**上
# --------------------------------------------------------------------------
MUTATIONS = (
    ("M1 摘掉超时（communicate(timeout=timeout) → 无超时，回到同步阻塞）",
     "proc.communicate(timeout=timeout)",
     "proc.communicate(timeout=None)",
     ("T1a", "T1b")),
    ("M2 把 os 放回 _STDLIB_OK（白名单收窄回退）",
     '_STDLIB_OK = {"collections"',
     '_STDLIB_OK = {"os",\n              "collections"',
     ("T4b",)),
    ("M3 把 eval 放回 _SAFE_BUILTIN_NAMES（内建白名单回退）",
     '"pow", "print", "range", "repr", "reversed", "round",',
     '"pow", "print", "range", "repr", "reversed", "round", "eval",',
     ("T4a",)),
    ("M4 撤掉「资源态失败不缓存」闸（超时结果被固化）",
     'if not any(c.get("guard_blocked") for c in checks):',
     'if True:',
     ("T5a",)),
)


def _mutant_file(old: str, new: str):
    """定点变异后的源码写进临时文件（**不落仓**）；锚点缺失返回 None。"""
    src = open(VERIFIER, encoding="utf-8").read()
    if old not in src:
        return None
    d = tempfile.mkdtemp(prefix="p91mut_")
    p = os.path.join(d, "verifier_mutant.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(src.replace(old, new, 1))
    return p


def mutations_run() -> bool:
    print("")
    print("=" * 64)
    print("定点变异自证（每条变异必须让**点名判据**转红）")
    print("=" * 64)
    global PASS, FAIL, FAILS
    snap_pass, snap_fail, snap_fails = PASS, FAIL, list(FAILS)
    ok_all = True
    for label, old, new, wanted in MUTATIONS:
        p = _mutant_file(old, new)
        print("--- %s" % label)
        if p is None:
            print("    [MUT-ANCHOR-MISS] 锚点在当前源码里找不到"
                  "（实现改了却没同步本表）")
            ok_all = False
            continue
        FAIL = 0
        FAILS.clear()
        child = _run_child(p)
        if child["hang"]:
            _hang_reds()
        else:
            if "data" not in child:
                check("变异体判据子进程产出判决", False,
                      "stdout=%r stderr=%r" % (child["out"][-200:],
                                               child.get("stderr", "")[-200:]))
            else:
                judge(child["data"], child["sec"])
            static_checks(p)
        reds = list(FAILS)
        hit = [w for w in wanted if any(w in r for r in reds)]
        print("    变异后红项：%s" % (reds or "（无——变异未被判据发现 = 假绿）"))
        if hit:
            print("    ✓ 点名命中 %s" % list(hit))
        else:
            print("    ✗ 未点名 %s —— 该加固缺判别力" % (list(wanted),))
            ok_all = False
        PASS, FAIL, FAILS = snap_pass, snap_fail, list(snap_fails)
        # 复位：变异轮读数只用于自证，不污染全绿读数
    return ok_all


def main() -> int:
    mutate = "--mutate" in sys.argv
    if not os.path.exists(VERIFIER):
        print("[FAIL] verifier.py 不在预期位置：%s" % VERIFIER)
        return 1

    child = _run_child(VERIFIER)
    if child["hang"]:
        print("[FAIL] 受控时限判据子进程挂死（>%ss 未返回）" % OUTER_TIMEOUT)
        print("       stdout 尾部：%s" % child["out"][-400:])
        _hang_reds()
    elif "data" not in child:
        print("[FAIL] 判据子进程未产出判决；stderr=%r"
              % (child.get("stderr", "")[-300:],))
        check("受控时限判据子进程产出判决", False, "见上")
    else:
        judge(child["data"], child["sec"])
    static_checks(VERIFIER)

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
