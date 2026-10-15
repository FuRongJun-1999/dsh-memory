# -*- coding: utf-8 -*-
# 功能名：writelimit 台账脏值的类型收敛与时间戳纠偏（issue #354 P1-9/P1-10/P1-11）
# 生效条件：python -X utf8 -m md_cg.test_issue354_p1_writelimit_type [--mutate]；被测面=md_cg/writelimit.py 的 _load / _window_stamps / _window_stamp / check / record_accepted / stats
# 子功能：A 组=三类脏值（顶层非 dict、时间戳元素非数值、未来时间戳）在 _load/check/stats 全链不崩且不锁死窗口；K 组=干净台账的限流语义与旁路未被削弱（非恒真/非恒假对照）
# 执行：--mutate 时逐条把判据改回改动前形态，守卫必须转红（定点变异自证，镜像树形态）
# 验证方式：全部 PASS 即通过（断言总数须 ≥ FLOOR）；--mutate 下每条变异的「指定命中」须与预期一致
# 不适用条件：不覆盖多进程并发写同一台账的竞态；不判「台账内容是否可信」（只判形态可用性与窗口有界性）；不覆盖非 contextual 层（check 首闸直接放行，K7 只做回归）；**台账被判「不可用」时静默回落**空台账、不发 stderr——沿用 _load 既有 OSError/ValueError 约定（本面只保证「脏值不崩」，不承诺「喊一声」），是否改为 stderr 告警归维护者裁（属越出 #354 面的行为变更）
"""issue #354 Python 面守卫：_writelimit.json 的三类脏值不得崩闸、不得永久锁死限流。

病象（修前，逐条实测）：
  P1-9   台账顶层是 JSON 数组/标量/null ⇒ _load 先 st.get(...) 再判类型 ⇒
         AttributeError 逃到调用方（限流器崩在写入路径上）；
  P1-10  台账里存在**未来**时间戳 ⇒ 旧判据 now - t < RATE_WINDOW 单向，未来戳
         now - t 恒为负 ⇒ 恒落在窗口内 ⇒ 8 个未来戳把 (layer, role) 永久判 DEFER；
  P1-11  时间戳元素非数值（str/None/dict）或 rate[key] 非 list ⇒ now - t 抛
         未捕获 TypeError。
修法（报告 §5.7 口径）：类型收敛 + 未来时间戳纠偏——时间过滤做成**双向界定**
（t <= now 且 now - t < window），剔除非数值元素与未来时间戳。

隔离纪律：本守卫不碰任何真实库——cg 是只提供 root/get 的桩，台账落在
tempfile.mkdtemp 下；MDCG_WRITELIMIT 在本进程内强制为 "1" 并在 finally 还原。
镜像树变异只在临时目录里改源码，真实工作树的 md_cg/ 一字不动。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from . import writelimit as W

FLOOR = 30
PASS, FAIL = 0, 0
FAILS = []


def _check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:220])


# ---------------------------------------------------------------- 桩与夹具

class _CG:
    """最小 cg 桩：check/record_accepted/stats 只用到 root 与 get。"""

    def __init__(self, root, nodes=None):
        self.root = root
        self.nodes = dict(nodes or {})

    def get(self, nid):
        return self.nodes.get(nid)


def _mk(root, state):
    """把台账写成给定形态（state 为对象则 json 序列化；为 str 则逐字写入）。"""
    p = os.path.join(root, W.STATE_FILE)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(state if isinstance(state, str)
                else json.dumps(state, ensure_ascii=False))
    return p


def _read(root):
    p = os.path.join(root, W.STATE_FILE)
    if not os.path.exists(p):
        return None
    with io.open(p, encoding="utf-8", newline="") as f:
        return json.loads(f.read())


def _call(fn, *a, **kw):
    """返回 (ok, value_or_exc)；把「抛没抛」本身当成被测读数。"""
    try:
        return True, fn(*a, **kw)
    except Exception as e:                        # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


NOW = 1_700_000_000.0          # 固定 now：不依赖真实时钟，读数可复现
KEY = "contextual:user"
CONTENT = "批次7收官记忆"       # 无标题、短文本 ⇒ template_signature 非空


print("== A 组：修复点（三类脏值不崩 / 不锁死）==")

_A_STATE_OK = {"sigs": {}, "rate": {}}


def _a1():
    """P1-9：顶层非 dict ⇒ _load 回落空台账、check 放行，不抛。"""
    for label, raw in (("数组", "[1, 2, 3]"), ("标量", "42"), ("字符串", '"oops"'),
                       ("null", "null"), ("bool", "true")):
        root = tempfile.mkdtemp(prefix="i354p1_a1_")
        try:
            _mk(root, raw)
            cg = _CG(root)
            ok, st = _call(W._load, cg)
            _check("A1 _load 顶层%s 回落空台账且不抛" % label,
                   ok and st == _A_STATE_OK, (ok, st))
            ok2, v = _call(W.check, cg, CONTENT, now=NOW)
            _check("A1 check 顶层%s 放行且不抛" % label, ok2 and v is None,
                   (ok2, v))
        finally:
            shutil.rmtree(root, ignore_errors=True)


def _a2():
    """P1-9 同族：sigs/rate 槽非 dict ⇒ 回落；sigs 单条记账非 dict ⇒ 不崩。"""
    for label, st_obj in (("sigs 非 dict", {"sigs": [], "rate": {}}),
                          ("rate 非 dict", {"sigs": {}, "rate": []}),
                          ("rate 为标量", {"sigs": {}, "rate": 7})):
        root = tempfile.mkdtemp(prefix="i354p1_a2_")
        try:
            _mk(root, st_obj)
            cg = _CG(root)
            ok, st = _call(W._load, cg)
            _check("A2 _load（%s）回落空台账且不抛" % label,
                   ok and st == _A_STATE_OK, (ok, st))
        finally:
            shutil.rmtree(root, ignore_errors=True)
    # 顶层是合法 dict，但单条签名记账是标量/序列
    sig = W.template_signature(CONTENT)
    _check("A2 前置：CONTENT 的模板签名非空（判据有效）", bool(sig), sig)
    for label, rec in (("list", [1, 2]), ("str", "xyz"), ("int", 5)):
        root = tempfile.mkdtemp(prefix="i354p1_a2b_")
        try:
            _mk(root, {"sigs": {sig: rec}, "rate": {}})
            ok, v = _call(W.check, _CG(root), CONTENT, now=NOW)
            _check("A2 check（sigs[签名]=%s）不抛" % label, ok, v)
            ok2, v2 = _call(W.record_accepted, _CG(root), "n1", CONTENT, now=NOW)
            _check("A2 record_accepted（sigs[签名]=%s）不抛" % label, ok2, v2)
        finally:
            shutil.rmtree(root, ignore_errors=True)


def _a3():
    """P1-10：未来时间戳不得把窗口永久占满。"""
    root = tempfile.mkdtemp(prefix="i354p1_a3_")
    try:
        fut = NOW + 10 ** 9                      # 约 31 年后
        _mk(root, {"sigs": {}, "rate": {KEY: [fut] * W.RATE_MAX}})
        cg = _CG(root)
        ok, v = _call(W.check, cg, CONTENT, now=NOW)
        _check("A3 8 条未来时间戳不再 DEFER（放行）",
               ok and v is None, (ok, v))
        st = _read(root) or {}
        left = st.get("rate", {}).get(KEY) or []
        _check("A3 未来时间戳被清除（窗口只剩本次追加的 now）",
               len(left) == 1 and abs(float(left[0]) - NOW) < 1.0, left)
        # 连续多次：旧行为下每次都被拒（永久锁死），新行为每次放行
        allpass = True
        for i in range(5):
            ok2, v2 = _call(W.check, cg, CONTENT, now=NOW + i)
            allpass = allpass and ok2 and v2 is None
        _check("A3 连续 5 次检查均放行（窗口未被永久占满）", allpass, "")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _a4():
    """P1-11：非数值时间戳元素不得抛未捕获异常。"""
    for label, val in (("字符串", ["abc"]), ("None", [None]), ("dict", [{"t": 1}]),
                       ("混装", [NOW, "x"]), ("bool", [True]), ("NaN", [float("nan")]),
                       ("无穷", [float("inf")])):
        root = tempfile.mkdtemp(prefix="i354p1_a4_")
        try:
            _mk(root, {"sigs": {}, "rate": {KEY: val}})
            ok, v = _call(W.check, _CG(root), CONTENT, now=NOW)
            _check("A4 check（时间戳元素=%s）不抛" % label, ok, v)
            ok2, v2 = _call(W._push_rate, {"rate": {KEY: val}}, KEY, NOW)
            _check("A4 _push_rate（时间戳元素=%s）不抛" % label, ok2, v2)
        finally:
            shutil.rmtree(root, ignore_errors=True)
    # rate[key] 本身不是序列
    for label, val in (("int", 5), ("str", "xx"), ("dict", {"a": 1})):
        root = tempfile.mkdtemp(prefix="i354p1_a4b_")
        try:
            _mk(root, {"sigs": {}, "rate": {KEY: val}})
            ok, v = _call(W.check, _CG(root), CONTENT, now=NOW)
            _check("A4 check（rate[key]=%s）不抛" % label, ok, v)
            ok2, v2 = _call(W.stats, _CG(root))
            _check("A4 stats（rate[key]=%s）不抛" % label, ok2 and isinstance(v2, dict), v2)
        finally:
            shutil.rmtree(root, ignore_errors=True)


def _a5():
    """P1-10/P1-11 同族：签名记账的 t 非数值 / 未来。"""
    sig = W.template_signature(CONTENT)
    nodes = {"n1": {"id": "n1", "content": "别的内容", "frontmatter": {}}}
    for label, t in (("字符串", "abc"), ("None", None), ("未来", NOW + 10 ** 9)):
        root = tempfile.mkdtemp(prefix="i354p1_a5_")
        try:
            _mk(root, {"sigs": {sig: {"nid": "n1", "t": t, "n": 1}}, "rate": {}})
            ok, v = _call(W.check, _CG(root, nodes), CONTENT, now=NOW)
            _check("A5 check（签名记账 t=%s）不抛且不 CONVERGE" % label,
                   ok and (v is None or v.get("verdict") != "CONVERGE"), (ok, v))
        finally:
            shutil.rmtree(root, ignore_errors=True)


def _a6():
    """stats 诊断面：sigs 值非 dict 时不崩。"""
    root = tempfile.mkdtemp(prefix="i354p1_a6_")
    try:
        _mk(root, {"sigs": {"a": 5, "b": None, "c": {"nid": "x"}}, "rate": {}})
        ok, st = _call(W.stats, _CG(root))
        _check("A6 stats（sigs 值混装非 dict）不抛", ok, st)
        _check("A6 stats 只把 dict 且 nid 为真的记账算 live",
               ok and st.get("sigs_live") == 1, st)
        _check("A6 stats 如实计数 sigs_tracked", ok and st.get("sigs_tracked") == 3, st)
    finally:
        shutil.rmtree(root, ignore_errors=True)


_a1()
_a2()
_a3()
_a4()
_a5()
_a6()

print("")
print("== K 组：非恒真 / 非恒假对照（干净台账的语义未被削弱）==")


def _k1():
    """阈值语义在位：窗口内 8 条仍 DEFER，7 条放行。"""
    for n, want in ((W.RATE_MAX, "DEFER"), (W.RATE_MAX - 1, None)):
        root = tempfile.mkdtemp(prefix="i354p1_k1_")
        try:
            stamps = [NOW - 1.0] * n
            _mk(root, {"sigs": {}, "rate": {KEY: stamps}})
            ok, v = _call(W.check, _CG(root), CONTENT, now=NOW)
            got = (v or {}).get("verdict") if isinstance(v, dict) else None
            _check("K1 窗口内 %d 条 ⇒ %s" % (n, want), ok and got == want, (ok, v))
        finally:
            shutil.rmtree(root, ignore_errors=True)


def _k2():
    """时间过滤在位：窗口外的旧戳不计入。"""
    root = tempfile.mkdtemp(prefix="i354p1_k2_")
    try:
        old = [NOW - W.RATE_WINDOW - 1.0] * W.RATE_MAX
        _mk(root, {"sigs": {}, "rate": {KEY: old}})
        ok, v = _call(W.check, _CG(root), CONTENT, now=NOW)
        _check("K2 窗口外 8 条 ⇒ 放行", ok and v is None, (ok, v))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # 边界：恰好 now - RATE_WINDOW 属窗口外（判据 >= window 即除）
    ok, v = _call(W._window_stamp, NOW - W.RATE_WINDOW, NOW, W.RATE_WINDOW)
    _check("K2 边界：t == now - window 判为窗外", v is None, v)
    ok, v = _call(W._window_stamp, NOW - W.RATE_WINDOW + 0.5, NOW, W.RATE_WINDOW)
    _check("K2 边界：t 略进窗内即计", v is not None, v)


def _k3():
    """未来戳只剔它自己，不误伤同列表里的合法戳。"""
    root = tempfile.mkdtemp(prefix="i354p1_k3_")
    try:
        mix = [NOW - 1.0] * (W.RATE_MAX - 1) + [NOW + 10 ** 9, NOW + 5.0]
        _mk(root, {"sigs": {}, "rate": {KEY: list(mix)}})
        ok, v = _call(W.check, _CG(root), CONTENT, now=NOW)
        _check("K3 7 条合法 + 2 条未来 ⇒ 合法 7 条保留、放行",
               ok and v is None, (ok, v))
        st = _read(root) or {}
        left = st.get("rate", {}).get(KEY) or []
        _check("K3 保留数 = 7 合法 + 1 本次追加 = 8",
               len([x for x in left if float(x) <= NOW]) == W.RATE_MAX, left)
        # 再补一条合法戳 ⇒ 命中阈值
        _mk(root, {"sigs": {}, "rate": {KEY: [NOW - 1.0] * W.RATE_MAX}})
        ok2, v2 = _call(W.check, _CG(root), CONTENT, now=NOW)
        _check("K3 对照：全合法 8 条 ⇒ DEFER（判据非恒假）",
               ok2 and (v2 or {}).get("verdict") == "DEFER", (ok2, v2))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _k4():
    """纯函数判据面：_window_stamp / _window_stamps 的边界与类型。"""
    cases = ((NOW, True), (NOW - 1.0, True), (NOW + 0.001, False),
             (NOW - W.RATE_WINDOW, False), (0, False), (-1.0, False),
             (True, False), (False, False), ("abc", False), (None, False),
             ([1], False), (float("nan"), False), (float("inf"), False))
    for t, want in cases:
        ok, v = _call(W._window_stamp, t, NOW, W.RATE_WINDOW)
        _check("K4 _window_stamp(%r) ⇒ %s" % (t, "计" if want else "剔"),
               ok and ((v is not None) == want), (ok, v))
    ok, v = _call(W._window_stamps, [NOW - 1.0, "x", NOW + 9, NOW - 2.0, None],
                  NOW, W.RATE_WINDOW)
    _check("K4 _window_stamps 剔脏值、保序、只留窗内",
           ok and v == [NOW - 1.0, NOW - 2.0], (ok, v))
    for raw in (None, 5, "abc", {"a": 1}, (NOW - 1.0,)):
        ok, v = _call(W._window_stamps, raw, NOW, W.RATE_WINDOW)
        want_empty = not isinstance(raw, tuple)
        _check("K4 _window_stamps(%r) ⇒ %s" % (raw, "[]" if want_empty else "序列"),
               ok and (len(v) == (0 if want_empty else 1)), (ok, v))


def _k5():
    """既有旁路与语义回归：非 contextual 层 / 总开关 / 加密级 / 干净台账。"""
    root = tempfile.mkdtemp(prefix="i354p1_k5_")
    try:
        _mk(root, {"sigs": {}, "rate": {KEY: [NOW - 1.0] * W.RATE_MAX}})
        cg = _CG(root)
        ok, v = _call(W.check, cg, CONTENT, layer="knowledge", now=NOW)
        _check("K5 非 contextual 层直接放行（层闸回归）", ok and v is None, (ok, v))
        os.environ["MDCG_WRITELIMIT"] = "0"
        try:
            ok, v = _call(W.check, cg, CONTENT, now=NOW)
            _check("K5 MDCG_WRITELIMIT=0 关闭限流（总开关回归）",
                   ok and v is None, (ok, v))
        finally:
            os.environ["MDCG_WRITELIMIT"] = "1"
        ok, v = _call(W.check, cg, CONTENT, importance_hint=0.9, now=NOW)
        _check("K5 importance_hint>=0.7 保护优先跳过（回归）", ok and v is None, (ok, v))
        # _load 对合法台账逐字返回（不误清洗）
        good = {"sigs": {"t:x": {"nid": "n1", "t": NOW - 1.0, "n": 2}},
                "rate": {KEY: [NOW - 1.0, NOW - 2.0]}}
        _mk(root, good)
        ok, st = _call(W._load, _CG(root))
        _check("K5 _load 对合法台账逐字返回（不误清洗）", ok and st == good, st)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _k6():
    """sigs 记账的窗内 CONVERGE 语义仍在位（非恒假）。"""
    sig = W.template_signature(CONTENT)
    root = tempfile.mkdtemp(prefix="i354p1_k6_")
    try:
        nodes = {"n1": {"id": "n1", "content": "别的内容", "frontmatter": {}}}
        _mk(root, {"sigs": {sig: {"nid": "n1", "t": NOW - 10.0, "n": 1}},
                   "rate": {}})
        ok, v = _call(W.check, _CG(root, nodes), CONTENT, now=NOW)
        _check("K6 窗内签名记账仍 CONVERGE（聚合语义未被削弱）",
               ok and isinstance(v, dict) and v.get("verdict") == "CONVERGE",
               (ok, v))
        _mk(root, {"sigs": {sig: {"nid": "n1", "t": NOW - W.CONVERGE_WINDOW - 1.0,
                                  "n": 1}}, "rate": {}})
        ok, v = _call(W.check, _CG(root, nodes), CONTENT, now=NOW)
        _check("K6 窗外签名记账不再 CONVERGE（窗口有界）",
               ok and (v is None or v.get("verdict") != "CONVERGE"), (ok, v))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _k7():
    """record_accepted 正常路径未被改动语义破坏。"""
    sig = W.template_signature(CONTENT)
    root = tempfile.mkdtemp(prefix="i354p1_k7_")
    try:
        _mk(root, {"sigs": {}, "rate": {}})
        W.record_accepted(_CG(root), "n9", CONTENT, now=NOW)
        st = _read(root) or {}
        rec = (st.get("sigs") or {}).get(sig)
        _check("K7 record_accepted 首见即落占位", isinstance(rec, dict)
               and rec.get("nid") == "n9", rec)
    finally:
        shutil.rmtree(root, ignore_errors=True)


_k1()
_k2()
_k3()
_k4()
_k5()
_k6()
_k7()

print("")
print("断言总数 %d（PASS %d / FAIL %d），FLOOR=%d" % (PASS + FAIL, PASS, FAIL, FLOOR))
if PASS + FAIL < FLOOR:
    FAILS.append("FLOOR")
    print("  FAIL 断言总数低于 FLOOR —— 探针面疑似失效（防假绿）")

if FAILS:
    print("issue #354 [P1-9/P1-10/P1-11] 结果：%d 失败" % len(FAILS))
    for f in FAILS:
        print("   - " + f)
else:
    print("issue #354 [P1-9/P1-10/P1-11] 结果：全部通过")


# ---------------------------------------------------------------- 定点变异自证

_TARGET = "md_cg/writelimit.py"

#: (说明, 改前锚, 改后锚, 期望转红的断言名前缀)
_MUTATIONS = (
    ("V1 _load 去掉顶层 isinstance(st, dict) 类型闸（回到 P1-9 形态）",
     "if (isinstance(st, dict) and isinstance(st.get(\"sigs\"), dict)",
     "if (isinstance(st.get(\"sigs\"), dict)",
     ("A1",)),
    ("V2 _window_stamp 去掉 t > now 这一半（回到 P1-10 单向判据）",
     "if t > now or now - t >= window:",
     "if now - t >= window:",
     ("A3", "A5")),
    ("V3 _window_stamp 去掉类型闸（回到 P1-11 直算形态）",
     "if isinstance(t, bool) or not isinstance(t, (int, float)):\r\n        return None",
     "if t is None:\r\n        return None",
     ("A4",)),
    ("V4 _window_stamps 去掉序列闸（rate[key] 非 list 直接迭代）",
     "if not isinstance(raw, (list, tuple)):\r\n        return []",
     "if raw is None:\r\n        return []",
     ("A4",)),
    ("V5 反向过度收紧：窗口宽度被压成 0（限流与聚合恒不触发）",
     "if t > now or now - t >= window:",
     "if t > now or now - t >= 0:",
     ("K1", "K6")),
)


def _mirror_build():
    """镜像树：拷 md_cg/scripts/根级 .py 到临时树（真实工作树只读）。"""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dst = tempfile.mkdtemp(prefix="i354p1_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(repo, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(repo)):
        p = os.path.join(repo, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _fold(text, eol):
    """按目标文件实际行尾折算（本仓 CRLF/LF 混合）。"""
    return text.replace("\r\n", "\n").replace("\n", eol)


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MDCG_WRITELIMIT"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue354_p1_writelimit_type"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态，守卫必须转红（镜像树）")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print("\n".join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, _TARGET)
            with io.open(p, encoding="utf-8", newline="") as f:
                t = f.read()
            eol = "\r\n" if "\r\n" in t else "\n"
            o, n = _fold(old, eol), _fold(new, eol)
            if t.count(o) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次" % (desc, _TARGET, t.count(o)))
                print("  ANCHOR-MISS " + desc)
                continue
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(t.replace(o, n, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(t)
            hit = [r for r in reds2 if any(r.startswith(e) for e in exp)]
            if rc2 != 0 and len(hit) >= len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    global NOW
    NOW = time.time() if "--now" in sys.argv else NOW
    if "--mutate" in sys.argv:
        _mutate()
        return 0 if not FAILS else 1
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
