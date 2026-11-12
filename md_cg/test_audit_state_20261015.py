# -*- coding: utf-8 -*-
"""test_audit_state_20261015 · 状态事件→槽位投影 定点回归

来源：2026-10-15 状态链审计。保留一条「实际可复现的行为错误」及其最小复现：

B2 state_slots 的撤回判据不认空白串（md_cg/state_slots.py _is_void）
   工具面 cg(op=state_event) 的 new 是 string 参数，说明逐字写着「撤回＝留空；
   空值即值作废」——客户端按该说明发 new="" 时台账落空串。旧判据只认 None，
   于是空串撤回被读成「设成空值」：槽位不退役、value 为空串、
   status.retired 不计数、缺省投影仍列出该槽位。

运行：
    python -X utf8 -m md_cg.test_audit_state_20261015
    python -X utf8 -m md_cg.test_audit_state_20261015 --mutate         # 定点变异自证
    python -X utf8 -m md_cg.test_audit_state_20261015 --mutate --list  # 只列变异表

变异纪律：变异体只写进**临时目录**的副本文件后 exec（__package__="md_cg"），
共享源码一字不改；锚点漂移即 ANCHOR-MISS + 退出码 2（fail-closed）。
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import types

from . import state_slots
from .mdcos import MdCGOS

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="mdcg_audit_state_20261015_")
_GEN = [0]

#: 被测模块（--mutate 时被临时副本替换，组末还原）。
SS = state_slots
_REAL_SS = state_slots

_PASS, _FAIL = [], []


def ok(cond, name, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS " + name)
    else:
        _FAIL.append(name)
        print("  FAIL %s  · %s" % (name, str(detail)[:300]))


def _fresh():
    _GEN[0] += 1
    return MdCGOS(os.path.join(_TMP, "g%d" % _GEN[0], "root"))


def _evt(cg, **a):
    """经真实 MCP 入口写一条状态事件（actor 走无令牌路径，落 "system"）。"""
    from . import mcp_server as MS
    args = {"op": "state_event"}
    args.update(a)
    return MS._cg_call(cg, args)


@contextlib.contextmanager
def _env(**kv):
    saved = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ------------------------------------------------------------------ B2 夹具
def _b2_write(new_kw):
    """经 MCP 入口写「启用 → 撤回」，返回 (cg, 撤回事件行)。"""
    cg = _fresh()
    _evt(cg, subject="甲", slot="住所", old=None, new="别墅",
         kind="enablement", seq=1)
    out = _evt(cg, subject="甲", slot="住所", old="别墅",
               kind="retraction", seq=2, **new_kw)
    return cg, (out or {}).get("event") or {}


def _b2_unit(cg):
    u = SS.project(cg, subject="甲", slot="住所", include_retired=True)
    return u[0] if u else None


def gB2():
    print("== B2 撤回判据认空白串（new 留空即值作废） ==")
    for tag, kw, ledger in (("None", {"new": None}, None),
                            ("空串", {"new": ""}, ""),
                            ("全空白串", {"new": "   "}, "   ")):
        cg, ev = _b2_write(kw)
        u = _b2_unit(cg)
        st = SS.status(cg)
        live = SS.project(cg, subject="甲")
        ok(u and u["state"] == "retired" and u["value"] is None,
           "B2 撤回写法 new=%s → state=retired / value=None" % tag,
           u and (u["state"], u["value"]))
        ok(st["retired"] == 1,
           "B2 撤回写法 new=%s → status.retired=1" % tag, st)
        ok(live == [],
           "B2 撤回写法 new=%s → 缺省投影（剔退役）不含该槽位" % tag, live)
        ok(u and u["t_to"] == ev.get("t") and u["seq_to"] == 2,
           "B2 撤回写法 new=%s → t_to/seq_to 闭合到撤回事件" % tag,
           u and (u["t_to"], u["seq_to"]))
        if ledger is not None:
            ok(u and u["history"][-1]["new"] == ledger,
               "B2 撤回写法 new=%r → history 原样回带台账值（判据不改数据）" % ledger,
               u and u["history"][-1]["new"])
    # 有值事件不受影响（判据只把「空白」归为无值，不吞真值）
    cg = _fresh()
    _evt(cg, subject="甲", slot="住所", old=None, new="别墅", seq=1)
    u = _b2_unit(cg)
    ok(u and u["state"] == "active" and u["value"] == "别墅",
       "B2f 有值事件仍是 active/真值（判据不吞非空值）", u and (u["state"], u["value"]))
    # 撤回后复活：空白串撤回不影响后续带值事件
    cg = _fresh()
    _evt(cg, subject="甲", slot="住所", old=None, new="别墅", seq=1)
    _evt(cg, subject="甲", slot="住所", old="别墅", kind="retraction",
         new="", seq=2)
    _evt(cg, subject="甲", slot="住所", old=None, new="船屋", seq=3)
    u = _b2_unit(cg)
    ok(u and u["state"] == "active" and u["value"] == "船屋" and u["seq_from"] == 3,
       "B2g 空白串撤回后带值事件照常复活（事件序不变）",
       u and (u["state"], u["value"], u["seq_from"]))
    # stg.state_chain 与投影逐位一致（开关开）
    cg, _ = _b2_write({"new": ""})
    from . import stg as _stg
    with _env(MDCG_STG_STATE="1"):
        chain = _stg.state_chain(cg, subject="甲", include_retired=True)
    ok(chain.get("count") == 1
       and chain["items"] == SS.project(cg, subject="甲", include_retired=True),
       "B2h stg(state_chain) 与 project 逐位一致（投影单点，不复制判据）",
       chain.get("count"))


# ------------------------------------------------------------------ 变异表
#: (名字, 仓根相对路径, 原缺陷形态锚点, 现行形态锚点)
#: 变异 = 把**现行**源码里的修复点还原成原缺陷形态，写进临时目录后 exec。
_MUTATIONS = (
    ("B2 撤回判据还原成只认 None", "md_cg/state_slots.py",
     '    v = rec.get("new")\n'
     '    return v is None or (isinstance(v, str) and not v.strip())',
     '    return rec.get("new") is None'),
)


def _rel_text(rel):
    with io.open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _temp_module(name, rel, text):
    """把 text 写成临时目录里的副本文件后 exec 成模块（共享源码零改动）。"""
    d = tempfile.mkdtemp(prefix="mut_", dir=_TMP)
    p = os.path.join(d, os.path.basename(rel))
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(text)
    ns = {"__name__": name, "__package__": "md_cg", "__file__": p}
    exec(compile(text, p, "exec"), ns)                 # noqa: S102 —— 临时副本
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


def _run_groups():
    _PASS.clear()
    _FAIL.clear()
    for g in (gB2,):
        try:
            g()
        except Exception as exc:                       # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-700:])
    return list(_FAIL)


def _mutate_mode(list_only=False):
    print("!! 定点变异自证：把修复点还原成原缺陷形态，套件必须转红\n")
    if list_only:
        for name, rel, _fixed, _legacy in _MUTATIONS:
            print("  %-34s [%s]" % (name, rel))
        return 0
    global SS
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % len(clean))
    if clean:
        bad.append("未变异基线即失败")
        for l in clean:
            print("        " + l)
    for name, rel, fixed, legacy in _MUTATIONS:
        src = _rel_text(rel)
        if fixed not in src:
            anchor_miss.append("%s ← %s" % (name, fixed.splitlines()[0].strip()[:48]))
            continue
        mut = src.replace(fixed, legacy, 1)
        try:
            mod = _temp_module("md_cg._mut_%s" % os.path.basename(rel), rel, mut)
            SS = mod
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
        finally:
            SS = _REAL_SS
        lines = [l.strip() for l in buf.getvalue().splitlines()
                 if l.strip().startswith("FAIL ")]
        print("  %s %-34s 红项=%d  %s"
              % ("OK    " if reds else "MISS  ", name, len(reds),
                 "红" if reds else "**仍全绿 = 该判据空转**"))
        for l in lines[:6]:
            print("        " + l[5:])
        if not reds:
            bad.append(name)
    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（该机制有断言钉死）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main():
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        n = len(_run_groups())
        print("\n状态链审计守卫：%d 通过 / %d 失败" % (len(_PASS), n))
        print("SUMMARY: md_cg.test_audit_state_20261015 通过=%d 失败=%d"
              % (len(_PASS), n))
        return 0 if not n else 1
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
