# -*- coding: utf-8 -*-
"""test_audit_20261015_d_state_events_void · 状态事件写入口的「空」判据（批次 D）

缺陷（无源撤回被静默接受）：工具面 cg(op=state_event) 的参数说明写着 old「撤回时留空」、
new「撤回＝留空；空值即值作废」，并写明「old/new 双空非法」；state_events.append 的
判据却写作 old is None and new is None——只认 None 字面量。工具面 old/new 声明为
string，客户端「留空」落盘就是空串，于是「双空」的无源撤回被放行，落一行**既不是启用
也不是撤回**的台账行：投影把它读成 active 且 value 为空串（幽灵槽位），status 的
retired 不计数。

判据单点＝state_events.is_void（None 或空白串）：写入口的「双空拒收」经它判。投影侧
（state_slots._is_void）的同口径修复归在审 PR #379（源仓库 issue #375），按查重纪律
（与在审 PR 同文件同语义的不做）本批次**不改** state_slots.py，故本套件不涉投影侧的
空白串判据。

运行：python -X utf8 -m md_cg.test_audit_20261015_d_state_events_void
      python -X utf8 -m md_cg.test_audit_20261015_d_state_events_void --mutate
      python -X utf8 -m md_cg.test_audit_20261015_d_state_events_void --mutate --list

退出码（fail-closed）：0 = 全绿／变异自证 PASS；1 = 有断言失败／变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到——实现改了却没同步本表即硬失败）。
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import types

from . import mcp_server
from . import state_events
from . import state_slots
from .mdcos import MdCGOS

_PASS = []
_FAIL = []
_GEN = [0]
_TMP = tempfile.mkdtemp(prefix="mdcg_d_void_")
_SAVED = {}
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: 被测模块的**可变引用**（定点变异把它换成内存副本；组内一律经 _se() 取用）。
SE = state_events
_REAL_SE = state_events
_PKG = importlib.import_module("md_cg")


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _se():
    return globals()["SE"]


# 生效条件：无入参；把 MDCG_ROOT/MDCG_STATE_ROOT/MDCG_AUX_ROOT/MDCG_DATA_ROOT 的现值存入 _SAVED 并逐个从 os.environ 移除（隔离：任何经 env 取根的路径都不得落到在役库）。
def _sandbox_env():
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT"):
        _SAVED[k] = os.environ.get(k)
        os.environ.pop(k, None)


# 生效条件：无入参；把 _SAVED 逐个还原（原值 None 则移除键），恢复进程原有 env 形态。
def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# 生效条件：无入参；在 _TMP 下新建自增代次目录并返回其上的 MdCGOS 实例（每调用一个新根：组间与变异轮间零串味）。
def _fresh_cg():
    _GEN[0] += 1
    return MdCGOS(os.path.join(_TMP, "gen%d" % _GEN[0], "root"))


# 生效条件：cg 为沙箱实例时返回其台账行列表（经当前 SE 读面，落盘序）。
def _rows(cg):
    return _se().read(cg)


# 生效条件：fn 为待调用动作时——抛 ValueError 返回其消息文本，未抛返回 None（不吞其它异常）。
def _verr(fn):
    try:
        fn()
    except ValueError as e:
        return str(e)
    return None


# ---------------------------------------------------------------- A
# 生效条件：无入参；在自有沙箱根上逐条直调 state_events.append 断言「old/new 双空」（None、空串、纯空白串三种拼法）一律 ValueError 且零落盘，既有 None 双空行为不变。
def gA():
    print("== A 库层写入口：双空（含空串/纯空白串拼法）一律拒 ==")
    cg = _fresh_cg()
    cases = (
        ("A1 old=None new=''（无源撤回）", None, ""),
        ("A2 old='' new=''", "", ""),
        ("A3 old='  ' new='\\t'（纯空白）", "  ", "\t"),
        ("A4 old=None new=None（既有行为，须不变）", None, None),
    )
    for name, old, new in cases:
        t = _verr(lambda o=old, n=new: _se().append(cg, "甲", "住所", old=o, new=n))
        ok(t is not None and "old" in t and "new" in t,
           name + " → ValueError（点名 old/new）", t)
    ok(len(_rows(cg)) == 0, "A5 四次拒绝均零落盘（台账空）", len(_rows(cg)))


# ---------------------------------------------------------------- B
# 生效条件：无入参；在自有沙箱根上经 mcp_server._cg_call 走工具面 cg(op=state_event)，断言空串/纯空白串的双空被拒（ValueError 原样上抛）且零落盘、投影与 status 不留幽灵槽位，None 双空不变，带值一侧照常放行且值原样不改写。
def gB():
    print("== B 工具面 cg(op=state_event)：客户端按说明「留空」的实际落点 ==")
    cg = _fresh_cg()

    def _call(old, new):
        return mcp_server._cg_call(
            cg, {"op": "state_event", "subject": "甲", "slot": "住所",
                 "old": old, "new": new})

    t = _verr(lambda: _call("", ""))
    ok(t is not None and "old" in t and "new" in t,
       "B1 old='' new='' → ValueError（文档口径「old/new 双空非法」）", t)
    t = _verr(lambda: _call("  ", " "))
    ok(t is not None, "B2 old='  ' new=' ' → ValueError（纯空白同判）", t)
    t = _verr(lambda: _call(None, None))
    ok(t is not None, "B3 old=None new=None → ValueError（既有行为不变）", t)
    ok(len(_rows(cg)) == 0, "B4 三次拒绝零落盘", len(_rows(cg)))
    ok(state_slots.project(cg) == [] and state_slots.status(cg)["retired"] == 0,
       "B5 无幽灵槽位：缺省投影为空、retired=0",
       (state_slots.project(cg), state_slots.status(cg)))

    out = _call("旧值", "")
    ev = (out or {}).get("event") or {}
    ok(out.get("ok") is True and ev.get("old") == "旧值" and ev.get("new") == "",
       "B6 old='旧值' new='' 是合法撤回：放行且值原样不改写", out)
    out2 = _call("", "新值")
    ev2 = (out2 or {}).get("event") or {}
    ok(out2.get("ok") is True and ev2.get("old") == "" and ev2.get("new") == "新值",
       "B7 old='' new='新值' 是合法启用：放行且值原样不改写", out2)
    ok(len(_rows(cg)) == 2, "B8 两条合法事件落盘（append-only）", len(_rows(cg)))


# ---------------------------------------------------------------- C
# 生效条件：无入参；逐值断言判据单点 state_events.is_void 的取值表（None 与纯空白串为「空」，带内容串不是），并断言写入口对四象限的取舍与它同源（只有双空被拒）。
def gC():
    print("== C 判据单点 is_void（None 或空白串） ==")
    for v, want in ((None, True), ("", True), ("  ", True), ("\t\n ", True),
                    ("v", False), (" v ", False)):
        got = _se().is_void(v)
        ok(got is want, "C1 is_void(%r) == %s" % (v, want), got)
    cg = _fresh_cg()
    for name, old, new in (("C2 有旧值转空白＝合法撤回", "v", ""),
                           ("C3 空旧值转有值＝合法启用", "", "v"),
                           ("C4 两端有值＝迁移/替换", "v", "w")):
        t = _verr(lambda o=old, n=new: _se().append(cg, "乙", "槽", old=o, new=n))
        ok(t is None, name + " → 放行", t)
    ok(len(_rows(cg)) == 3, "C5 三条合法事件落盘", len(_rows(cg)))


# ---------------------------------------------------------------- D
# 生效条件：无入参；在自有沙箱根上断言值原样不改写（空串不归一成 None、空白串不 strip）、读回逐字相等、过滤面不受影响。
def gD():
    print("== D 值不改写 + 读回/过滤面不变 ==")
    cg = _fresh_cg()
    _se().append(cg, "丙", "槽", old="v", new="", kind="retraction", seq=1)
    _se().append(cg, "丙", "槽", old="", new="  x  ", kind="enablement", seq=2)
    rows = _rows(cg)
    ok(rows[0]["new"] == "" and rows[0]["old"] == "v",
       "D1 空串原样落盘（不归一成 None）", rows[0] if rows else None)
    ok(rows[1]["old"] == "" and rows[1]["new"] == "  x  ",
       "D2 空白串原样落盘（不 strip）", rows[1] if rows else None)
    back = json.dumps(_se().read(cg, subject="丙", slot="槽"), ensure_ascii=False)
    ok(back == json.dumps(rows, ensure_ascii=False),
       "D3 读回逐字相等（append-only 不读改写）")
    ok(len(_se().read(cg, subject="别的")) == 0
       and len(_se().read(cg, kind="retraction")) == 1,
       "D4 过滤面（subject/kind）不受影响")


_GROUPS = (gA, gB, gC, gD)


# 生效条件：无入参；逐组执行 _GROUPS（每组自行建沙箱根），组内抛异常记为一条失败并把栈尾打印出来（不中断其余组），返回失败条数。
def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                         # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-900:])
    return len(_FAIL)


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, rel, ((old, new), …))。每条必须让套件**转红**（红项原文由 --mutate 打印）：
#   M1 判据恢复旧形态（只认 None 字面量）→ A/B 组红（缺陷本体）
#   M2 单点判据退化为只认 None → A/B 组红（断言钉的是 is_void 本身，不是 append 里的内联字面量）
_MUTATIONS = (
    ("判据恢复旧形态（只认 None 字面量）", "md_cg/state_events.py",
     (('    if is_void(old) and is_void(new):',
       '    if old is None and new is None:'),)),
    ("单点判据退化为只认 None", "md_cg/state_events.py",
     (('    return v is None or (isinstance(v, str) and not v.strip())',
       '    return v is None'),)),
)


# 生效条件：rel 为仓根相对路径时返回该文件的当前源码文本（每次从盘读，不缓存——变异基线必须是**当前工作区**实现）。
def _rel_text(rel: str) -> str:
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


# 生效条件：name/rel/text 给定时——把 text 以 __package__="md_cg"、__file__=<仓内 rel 路径> 执行成命名空间并包成新模块对象返回（不注册 sys.modules、不触发 __main__；语法错误原样抛）。
def _exec_module(name: str, rel: str, text: str):
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(text, rel, "exec"), ns)                 # noqa: S102 —— 基线自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


# 生效条件：mut 为内存副本模块时——把它同时挂到全局引用、sys.modules 与包属性上（工具面 mcp_server 内的 from . import state_events 才会取到副本；全程内存，不写任何源文件）。
def _install(mut):
    globals()["SE"] = mut
    sys.modules["md_cg.state_events"] = mut
    setattr(_PKG, "state_events", mut)


# 生效条件：无入参；把全局引用、sys.modules 与包属性还原成真实模块（变异轮结束后必须复位）。
def _uninstall():
    globals()["SE"] = _REAL_SE
    sys.modules["md_cg.state_events"] = _REAL_SE
    setattr(_PKG, "state_events", _REAL_SE)


# 生效条件：list_only 为真时只打印变异表并返回 0；否则先跑未变异基线（必须 0 失败），再逐条在**内存副本**上注入变异（逐锚点 replace，锚点缺失记 ANCHOR-MISS）后重跑整套分组——有红项记 OK、无红项记 MISS（空转即失败）；全部锚点命中有红项时返回 0、否则 1；有 ANCHOR-MISS 时返回 2（fail-closed）。
def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把判据改回「缺陷」形态，套件必须转红\n")
    if list_only:
        for name, rel, _pairs in _MUTATIONS:
            print("  %-34s [%s]" % (name, rel))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(buf0 := io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")
        for l in buf0.getvalue().splitlines():
            if l.strip().startswith("FAIL "):
                print("        " + l.strip()[5:])
    for name, rel, pairs in _MUTATIONS:
        mut_src, miss = _rel_text(rel), []
        for old, new in pairs:
            if old not in mut_src:
                miss.append(old.splitlines()[0].strip()[:48])
                continue
            mut_src = mut_src.replace(old, new, 1)
        if miss:
            print("  ANCHOR-MISS %s —— 锚点在 %s 源码里找不到（实现改了却没"
                  "同步本表）：%s" % (name, rel, miss))
            anchor_miss.append(name)
            continue
        try:
            _install(_exec_module("md_cg._se_mut", rel, mut_src))
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            _uninstall()
        reds_lines = [l for l in detail.splitlines()
                      if l.strip().startswith("FAIL ")]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        print("  %s %-34s 红项=%d  %s"
              % ("OK    " if reds else "MISS  ", name, reds, verdict))
        for l in reds_lines[:6]:
            print("        " + l.strip()[5:])
        if not reds:
            bad.append(name)
    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处机制都有断言把它钉死）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    _sandbox_env()
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        n = _run_groups()
        print("\n状态事件写入口空判据守卫：%d 通过 / %d 失败" % (len(_PASS), n))
        print("SUMMARY: md_cg.test_audit_20261015_d_state_events_void 通过=%d 失败=%d"
              % (len(_PASS), n))
        return 0 if not n else 1
    finally:
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
