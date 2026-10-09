# -*- coding: utf-8 -*-
"""`autostart` 从模型可达工具面移除（待裁清单第 17 条 D 案）守卫。

裁定：设计者 2026-10-10 当场裁定「按推荐做」＝ 待裁清单第 17 条 **D**——
**把 `autostart` 从模型可达的工具面移除**（原话见
`docs/plans/灵枢1.0_最小智能系统实存答卷_纲领_v0.1.md` 裁定行）。

缺陷形状（改动前，逐条引 `path:line`）：

    md_cg/mcp_server.py:2832   `autostart=bool(o.get("autostart"))` —— 工具面
                               `ccg` 对象参数**原样透传**给 `units.review`
    md_cg/units.py:797-798     `if autostart and not serve_state(jobs)["alive"]:
                                   pr["autostart"] = autostart_serve(jobs)`
    md_cg/units.py:846         `subprocess.Popen([exe, "serve", "--jobs", jd], ...)`
                               —— **不传 `env=`**，继承脑侧 MCP 子进程环境

即「模型经一次 MCP 调用即可让脑侧拉起一个 detached 进程」。仓内同族留档
`docs/eval/缺陷挖掘_自主迭代_v21.md:128`（G6/N178：「review 带 autostart
**可在模型选的目录**拉起 serve」）。

**D 的边界（本守卫钉住的形态）**：
  · 工具面 schema 的 `ccg` 入参清单**不再列出** `autostart`（模型无法表达）；
  · 模型侧仍携带该键 ⇒ **显式拒绝**（`ok=False` + `removed_params=["autostart"]`
    + 可照做的 hint），**不是静默忽略**——静默会让调用方按「已拉起」继续推理
    （本仓既有教训：静默降级＝观测面全绿而事实已偏）；
  · `units.review(autostart=...)` 与 `units.autostart_serve` **原样保留**
    （默认 False，供部署侧/代码内通道；两仓零调用方显式置 true，故去掉透传
    不破坏任何调用方——`git grep autostart` 实证）。

**次级发现（如实记入，不升格）**：`units.review` 的 autostart 分支只在
`probe()` 已返回 HIVE（＝serve 心跳存活 ∧ 模型已配）之后才被求值，而紧接着
又要求 `not serve_state(jobs)["alive"]` ⇒ **Popen 分支实际只在两次判活之间
serve 恰好死掉的 TOCTOU 窗口内可达**。故「模型可拉起进程」在改动前是**窄面
但真**的（G6/N178 的表述偏强）。D 案的价值不在堵一个高频洞，而在
**结构上去掉模型面对「请拉起进程」这件事的表达能力**（拉起属部署动作）。

断言分组：

  G0 前提自证——工具面/单元层两面都在位；`_CCG_REMOVED_PARAMS` 含 `autostart`；
     `units.autostart_serve` 与 `units.review(autostart=...)` **能力保留**。
  G1 工具面 schema——`cg` 的 `ccg` 入参清单不再含 `autostart`（真源 + 投影两面）；
     其余入参名**一个不少**（防「顺手改多了」）；`op=help` 取回面亦不含。
  G2 模型侧携带 = 显式拒绝且可观测——`call_tool` 端到端 + `_ccg_call` 直调两条
     路径都返回 `ok=False` / `removed_params=["autostart"]` / 非空 hint；
     并以**调用探针**证明「根本没进派发」（`units.review` 未被调用）。
  G3 代码内通道保留——`units.review(autostart=True)` 在（被模拟的）死 serve
     条件下**仍会**调 `units.autostart_serve`（能力没被误删）；
     `units.autostart_serve` 在 exe 缺失时如实返回 `started=False` 且**不起进程**。
  G4 静态面（AST）——`md_cg/mcp_server.py` 里：`_units.review(...)` 调用**无**
     `autostart` 关键字；全文件**零** `autostart_serve` 引用（工具面碰不到拉起原语）。

运行：python -X utf8 -m md_cg.test_d17_autostart_toolface
      python -X utf8 -m md_cg.test_d17_autostart_toolface --mutate         # 定点变异自证
      python -X utf8 -m md_cg.test_d17_autostart_toolface --mutate --list  # 只列变异表

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到——实现改了却没同步本表）。

**基线纪律**：本守卫不以 git HEAD 为基线源——「改动前形态」由在当前工作区源码上
做**定点文本变异**（`_MUTATIONS`）复现，锚点漂移即退出码 2。**不改任何既有测试
断言换绿灯**：本件是新增判据，不触碰他人断言。
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import sys
import types

from . import mcp_server as MCP
from . import units

_PASS = []
_FAIL = []
_SKIP = []
#: 变异模式下供静态组读取的**源码文本**（rel → text）；未变异时读盘。
_SRC = {}

_REAL_MCP = MCP

#: 本次移除的参数名（与实现同源：不硬编码字面量在断言里，从实现读）
def _removed():
    return tuple(getattr(MCP, "_CCG_REMOVED_PARAMS", ()))


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def skip(msg):
    _SKIP.append(msg)
    print("  SKIP " + msg)


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rel_text(rel: str) -> str:
    """源码文本：变异模式下取变异后的文本，否则读盘。"""
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_repo_root(), rel), encoding="utf-8") as f:
        return f.read()


def _ccg_schema_desc(mod) -> str:
    """取 `cg` 工具 `inputSchema.properties.ccg.description` 原文。"""
    for t in mod.KERNEL_TOOLS:
        if t.get("name") == "cg":
            return t["inputSchema"]["properties"]["ccg"]["description"]
    return ""


def _review_call_keywords(src: str) -> list:
    """`_ccg_call` 内 `_units.review(...)` 调用的关键字名（AST，不含注释）。"""
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (isinstance(fn, ast.Attribute) and fn.attr == "review"
                and isinstance(fn.value, ast.Name) and fn.value.id == "_units"):
            out.extend(k.arg for k in node.keywords if k.arg)
    return out


def _names_used(src: str) -> set:
    """AST 里出现的全部 Name / Attribute 名（注释与字符串不算）。"""
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


# ---------------------------------------------------------------- 调用探针
class _Recorder:
    """记录「被调用过」的假实现（证明某条路径**没有**被走到）。"""

    def __init__(self, ret=None):
        self.calls = []
        self.ret = ret if ret is not None else {}

    def __call__(self, *a, **kw):
        self.calls.append({"args": a, "kwargs": kw})
        return self.ret


# ---------------------------------------------------------------- G0
def g0():
    print("== G0 前提自证 ==")
    ok(bool(_removed()) and "autostart" in _removed(),
       "G0a 实现侧声明了被移除参数表且含 autostart", _removed())
    ok(hasattr(units, "autostart_serve") and callable(units.autostart_serve),
       "G0b 能力保留：units.autostart_serve 仍在位（代码内通道）")
    import inspect
    sig = inspect.signature(units.review)
    ok("autostart" in sig.parameters,
       "G0c 能力保留：units.review 仍接受 autostart（默认 False，代码内通道）",
       list(sig.parameters))
    ok(sig.parameters["autostart"].default is False,
       "G0d units.review 的 autostart 缺省仍为 False（不自动拉起）",
       sig.parameters["autostart"].default)
    ok(hasattr(MCP, "_ccg_param_gate") and callable(MCP._ccg_param_gate),
       "G0e 入参闸 _ccg_param_gate 在位（模型面拒绝点）")


# ---------------------------------------------------------------- G1
_SCHEMA_KEEP = ("action", "node_id", "dialog", "marks", "slots", "strict_spans",
                "role", "verdict", "verifier", "compiled_by", "evidence",
                "slot_corrections", "model", "jobs", "blocking", "wait_s",
                "allow_degrade", "channel", "doctor", "apply", "basis")


def g1():
    print("== G1 工具面 schema（模型侧无表达面）==")
    M = globals()["MCP"]
    desc = _ccg_schema_desc(M)
    ok(desc and "autostart" not in desc,
       "G1 真源 schema：cg 的 ccg 入参清单不再列出 autostart", desc[:120])
    # 投影面（工具面渐进披露）——模型真正看到的那一份
    from .tool_face import slim_tools
    slim = [t for t in slim_tools(M.KERNEL_TOOLS) if t.get("name") == "cg"][0]
    sdesc = slim["inputSchema"]["properties"]["ccg"]["description"]
    ok("autostart" not in sdesc,
       "G1a 投影面 schema（模型实见）：ccg 入参短提示亦不含 autostart", sdesc[:120])
    # 防「顺手改多了」：其余入参名一个不少
    missing = [k for k in _SCHEMA_KEEP if k not in desc]
    ok(not missing,
       "G1b 其余入参名一个不少（本次只移除 autostart 一项）", missing)
    # op=help 按需取回面（被投影掉的原文从这里取回，故这里也必须干净）
    with contextlib.redirect_stdout(io.StringIO()):
        h = M._help_call(None, {"query": "ccg"})
    ok("autostart" not in json.dumps(h, ensure_ascii=False),
       "G1c op=help 取回面（cg 的 ccg 段）不含 autostart")
    # 源文本面（静态，供 src 型变异打红）
    src = _rel_text("md_cg/mcp_server.py")
    i = src.find("CCG 六要素编译器入参")
    block = src[i:i + 400] if i >= 0 else ""
    ok(block and "autostart" not in block,
       "G1d 源码文本：ccg 入参说明块不含 autostart（静态面）", block[:160])


# ---------------------------------------------------------------- G2
def g2():
    print("== G2 模型侧携带 = 显式拒绝且可观测 ==")
    M = globals()["MCP"]
    # --- 端到端：真工具面入口 ---
    r = M.call_tool(None, "cg", {"op": "ccg",
                                 "ccg": {"action": "review", "node_id": "x",
                                         "autostart": True}})
    ok(r.get("ok") is False,
       "G2 端到端：工具面带 autostart → ok=False（显式拒，不静默吞）", str(r)[:160])
    ok(list(r.get("removed_params") or []) == ["autostart"],
       "G2a 拒答点名 removed_params=['autostart']（可观测）", r.get("removed_params"))
    ok("autostart" in str(r.get("error") or ""),
       "G2b 拒答 error 点名该参数", str(r.get("error"))[:120])
    ok(bool(str(r.get("hint") or "").strip()),
       "G2c 拒答带非空 hint（给出下一步：部署侧拉起）", str(r.get("hint"))[:120])

    # --- 直调 _ccg_call：同一结论 + 证明「根本没进派发」 ---
    rec_review = _Recorder()
    rec_auto = _Recorder()
    live_review, live_auto = units.review, units.autostart_serve
    units.review, units.autostart_serve = rec_review, rec_auto
    try:
        r2 = M._ccg_call(None, {"ccg": {"action": "review", "node_id": "x",
                                        "autostart": True}})
    finally:
        units.review, units.autostart_serve = live_review, live_auto
    ok(r2.get("ok") is False and list(r2.get("removed_params") or []) == ["autostart"],
       "G2d 直调 _ccg_call 同判（ok=False / removed_params）", str(r2)[:160])
    ok(not rec_review.calls and not rec_auto.calls,
       "G2e 调用探针：units.review 与 autostart_serve **零调用**（拒在派发之前）",
       {"review": rec_review.calls, "autostart_serve": rec_auto.calls})

    # --- 对照：不带该键仍照常进派发（防「闸门误伤正常调用」）---
    # 需要让 review 分支真走到 `_units.review(...)`：桩掉 pending 装载与提示词生成，
    # 只留「review 被调用时的实参」这一个观测点。
    from . import ccgc as _ccgc
    rec_review2 = _Recorder(ret={"ok": False, "error": "stub", "state": "configure"})
    live_review, live_prompt = units.review, units.prompt_for
    live_load = _ccgc.load_pending
    units.review = rec_review2
    units.prompt_for = lambda *a, **kw: "stub-prompt"
    _ccgc.load_pending = lambda cg, nid: {"ok": True, "hash_ok": True,
                                          "compiled": types.SimpleNamespace(actor="a1")}
    try:
        M._ccg_call(None, {"ccg": {"action": "review", "node_id": "x"}})
    finally:
        units.review, units.prompt_for = live_review, live_prompt
        _ccgc.load_pending = live_load
    ok(rec_review2.calls and "autostart" not in (rec_review2.calls[0]["kwargs"] or {}),
       "G2f 对照：不带该键 → 照常派发，且**不**传 autostart（无回归）",
       rec_review2.calls)

    # --- 非 dict 仍拒（既有形态不回归）---
    r3 = M._ccg_call(None, {"ccg": "x"})
    ok(r3.get("ok") is False and "对象" in str(r3.get("error") or ""),
       "G2g 非对象 ccg 仍拒（既有形态不回归）", str(r3)[:120])


# ---------------------------------------------------------------- G3
def g3():
    print("== G3 代码内通道保留（能力没被误删）==")
    U = globals().get("units", units)
    # ① 死 serve 条件下，review(autostart=True) 仍会调 autostart_serve
    rec = _Recorder(ret={"started": False, "note": "stub"})
    live = (U.probe, U.serve_state, U.autostart_serve, U.submit)
    U.probe = lambda *a, **kw: {"state": U.HIVE, "transport": U.HIVE,
                                "model": "stub-model", "jobs_dir": "x",
                                "serve": {"alive": True}, "channel": "", "hint": ""}
    U.serve_state = lambda *a, **kw: {"alive": False}
    U.autostart_serve = rec
    U.submit = lambda **kw: {"ok": False, "error": "stub-submit"}
    try:
        r = U.review(prompt="p", role=U.REFLECT, node_id="x", jobs="j", autostart=True)
    finally:
        U.probe, U.serve_state, U.autostart_serve, U.submit = live
    ok(len(rec.calls) == 1,
       "G3 review(autostart=True) 在死 serve 下仍调 autostart_serve（代码内通道在）",
       {"calls": rec.calls, "state": (r or {}).get("state")})
    # ② 缺省不拉起：不传 autostart 时 autostart_serve 零调用
    rec2 = _Recorder(ret={"started": False, "note": "stub"})
    live = (U.probe, U.serve_state, U.autostart_serve, U.submit)
    U.probe = lambda *a, **kw: {"state": U.HIVE, "transport": U.HIVE,
                                "model": "stub-model", "jobs_dir": "x",
                                "serve": {"alive": True}, "channel": "", "hint": ""}
    U.serve_state = lambda *a, **kw: {"alive": False}
    U.autostart_serve = rec2
    U.submit = lambda **kw: {"ok": False, "error": "stub-submit"}
    try:
        U.review(prompt="p", role=U.REFLECT, node_id="x", jobs="j")
    finally:
        U.probe, U.serve_state, U.autostart_serve, U.submit = live
    ok(not rec2.calls,
       "G3a 不传 autostart（缺省 False）→ autostart_serve 零调用", rec2.calls)
    # ③ exe 缺失时如实返回、**不起进程**（安全读法：不真拉 serve）
    old_exe = os.environ.get(U.ENV_EXE)
    os.environ[U.ENV_EXE] = os.path.join(_repo_root(), "_no_such_hive_exe_")
    try:
        rr = U.autostart_serve(jobs=os.path.join(_repo_root(), "_no_such_jobs_"))
    finally:
        if old_exe is None:
            os.environ.pop(U.ENV_EXE, None)
        else:
            os.environ[U.ENV_EXE] = old_exe
    ok(rr.get("started") is False and "未找到可执行文件" in str(rr.get("note") or ""),
       "G3b autostart_serve 在 exe 缺失时如实返回 started=False（不假装、不起进程）",
       rr)


# ---------------------------------------------------------------- G4
def g4():
    print("== G4 静态面（AST：工具面碰不到拉起原语）==")
    src = _rel_text("md_cg/mcp_server.py")
    kws = _review_call_keywords(src)
    ok("autostart" not in kws,
       "G4 工具面 _units.review(...) 调用无 autostart 关键字", kws)
    names = _names_used(src)
    ok("autostart_serve" not in names,
       "G4a 工具面源码零 autostart_serve 引用（无第二处拉起入口）")
    ok("_CCG_REMOVED_PARAMS" in names and "_ccg_param_gate" in names,
       "G4b 移除参数表与入参闸均被引用（不是死代码）")


_GROUPS = (g0, g1, g2, g3, g4)


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, 模式, rel, old, new, 预期红项数下限)。
#   "mod" = 改**可执行实现**（exec 成模块并换进 `sys.modules`，供 `from . import` 面读到）
#   "src" = 只改**源码文本**（静态组读 `_SRC`，不 exec）
# 「改动前形态」的复现即在这里：
#   M1 把 autostart 加回工具面入参清单（= 改动前的 schema）
#   M2 把 review 分支的 autostart 透传加回去（= 改动前的 _ccg_call）
#   M3 去掉入参闸（= 改动前的静默透传形态）
_MUTATIONS = (
    ("schema 把 autostart 加回工具面入参清单（改动前形态）", "mod",
     "md_cg/mcp_server.py",
     '"allow_degrade, channel, doctor, apply, basis}"),',
     '"allow_degrade, channel, autostart, doctor, apply, basis}"),', 1),
    ("review 分支恢复 autostart 透传（改动前形态）", "mod",
     "md_cg/mcp_server.py",
     "                          blocking=bool(o.get(\"blocking\")), cg=cg, actor=actor)",
     "                          blocking=bool(o.get(\"blocking\")), cg=cg, actor=actor,\n"
     "                          autostart=bool(o.get(\"autostart\")))", 1),
    ("去掉入参闸（改动前的静默透传形态）", "mod",
     "md_cg/mcp_server.py",
     "    if not isinstance(o, dict) or (set(_CCG_REMOVED_PARAMS) & set(o)):",
     "    if not isinstance(o, dict):", 1),
)


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                       # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s: %s" % (g.__name__, type(exc).__name__, exc))
            import traceback
            print(traceback.format_exc()[-800:])
    return len(_FAIL)


def _exec_module(name: str, rel: str, text: str):
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_repo_root(), rel)}
    exec(compile(text, rel, "exec"), ns)               # noqa: S102 —— 基线自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把「模型面移除」改回改动前形态，套件必须转红\n")
    if list_only:
        for name, kind, rel, _o, _n, exp in _MUTATIONS:
            print("  %-46s [%s] expect_red>=%d  (%s)" % (name, kind, exp, rel))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, kind, rel, old, new, expect in _MUTATIONS:
        src = _rel_text(rel)
        if old not in src:
            print("  ANCHOR-MISS %s —— 锚点在 %s 源码里找不到（实现改了却没同步"
                  "本表；锚点漂移不得静默）" % (name, rel))
            anchor_miss.append(name)
            continue
        mut_src = src.replace(old, new, 1)
        _SRC[rel] = mut_src
        live = None
        try:
            if kind == "mod":
                live = sys.modules["md_cg.mcp_server"]
                mut = _exec_module("md_cg._d17_mut", rel, mut_src)
                sys.modules["md_cg.mcp_server"] = mut
                globals()["MCP"] = mut
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            if live is not None:
                sys.modules["md_cg.mcp_server"] = live
                globals()["MCP"] = _REAL_MCP
            _SRC.pop(rel, None)
        red_lines = [l for l in detail.splitlines()
                     if l.strip().startswith("FAIL ")]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        mark = "OK  " if reds >= expect else "MISMATCH"
        print("  %s %-46s 红项=%d 预期>=%d  %s"
              % (mark, name, reds, expect, verdict))
        for l in red_lines[:6]:
            print("        " + l.strip()[5:])
        if reds < expect:
            bad.append("%s（红=%d 预期>=%d）" % (name, reds, expect))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都被打红）" if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    if "--mutate" in sys.argv:
        return _mutate_mode("--list" in sys.argv)
    n = _run_groups()
    print("\n第 17 条 D（autostart 工具面移除）守卫：%d 通过，%d 失败，%d 跳过"
          % (len(_PASS), n, len(_SKIP)))
    return 0 if not n else 1


if __name__ == "__main__":
    sys.exit(main())
