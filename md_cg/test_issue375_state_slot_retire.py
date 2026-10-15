# -*- coding: utf-8 -*-
# 功能名：state_event 空串撤回必须使槽位退役（issue #375）
# 生效条件：python -X utf8 -m md_cg.test_issue375_state_slot_retire [--mutate]；被测面＝md_cg/state_slots.py::_is_void 及其在 _replay 的两处消费点（经 cg(op=state_event) 写口与 stg(state_chain) 读口端到端）
# 子功能：A 组＝#375 正题（new="" 与全空白串一律按撤回，退役态/统计/默认投影/变迁史/复读口/复活全对齐）；K 组＝非恒真对照（非空白值照旧算「有值」、kind 标签不进判据、非字符串值口径不变、其余读数不受扰）；E 组＝判据单点存在性
# 执行：--mutate 时在镜像树里逐条把判据改回改动前形态 / 过度放宽，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**（多红/少红皆不合格）
# 不适用条件：不覆盖 state_events.append 的入参校验口径（old/new 双空拒收，本轮刻意不动写侧）；不判语义消歧（not_fact 等，见 state_slots 模块头）；不覆盖跨库/多租户合并；不判 CLI 面（只读人工入口）
"""issue #375 守卫：撤回判据 `_is_void` 必须认「None **或空白字符串**」。

病象（修前）：`_is_void` 只判断 `new is None`。工具说明与 `state_events` 模块头
都以「**new 为空**」定义撤回（`new=""` 是调用方按说明给出的撤回形态），于是空串
按「有值」进入回放 —— 三处读数同时错：槽位仍 `active`、`status()["retired"]` 少计、
默认投影多出一条现值＝空串的单元。

修法：判据只放宽**无值**这一判断（None ∪ 空白字符串）。台账行与 `history` 条目
的 `new` / `old` **原值一字不改**（值作废只发生在投影回放里）；其后带值事件
自然复活（回放循环无特判分支）。`state_events.append` 的校验口径不在本批改动面内。
"""
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss375_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain",
                   "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_STG_STATE": "1"})   # stg 状态链读面默认关，本守卫显式开

from md_cg import mcp_server as _ms     # noqa: E402
from md_cg import stg as _stg           # noqa: E402
from md_cg import state_slots as SS     # noqa: E402
from md_cg.mdcos import MdCGOS          # noqa: E402


def _lib(tag):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    return MdCGOS(d)


def _evt(cg, **kw):
    a = {"op": "state_event"}
    a.update(kw)
    return _ms._cg_call(cg, a)


def _first(cg, **kw):
    """默认投影首条（空则 None）——变异把投影改坏时只转红、不抛 IndexError。"""
    rows = SS.project(cg, **kw)
    return rows[0] if rows else None


def _ledger_rows(cg):
    p = os.path.join(cg.root, "_state_events.jsonl")
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


print("== A 组：#375 正题——空串撤回必须退役 ==")
# —— issue 原文最小复现（逐字） ——
_cg = _lib("repro")
_evt(_cg, subject="甲", slot="住所", old=None, new="别墅", kind="enablement", seq=1)
_evt(_cg, subject="甲", slot="住所", old="别墅", new="", kind="retraction", seq=2)
_row = SS.project(_cg, include_retired=True)[0]
_check("A01 new='' 撤回 → state=retired", _row["state"] == "retired", _row["state"])
_check("A02 new='' 撤回 → value=None（值作废，不留空串）", _row["value"] is None, _row["value"])
_check("A03 new='' 撤回 → status()['retired']=1", SS.status(_cg)["retired"] == 1,
       SS.status(_cg))
_check("A04 new='' 撤回 → 默认投影 0 条（退役的不进默认读面）",
       len(SS.project(_cg)) == 0, SS.project(_cg))

# —— new=None（修前既有行为，必须一字不变） ——
_cg0 = _lib("none_case")
_evt(_cg0, subject="甲", slot="住所", old=None, new="别墅", kind="enablement", seq=1)
_evt(_cg0, subject="甲", slot="住所", old="别墅", new=None, kind="retraction", seq=2)
_r0 = SS.project(_cg0, include_retired=True)[0]
_check("A05 对照：new=None 的读数与修前一致（retired/None/1/0）",
       _r0["state"] == "retired" and _r0["value"] is None
       and SS.status(_cg0)["retired"] == 1 and len(SS.project(_cg0)) == 0,
       (_r0["state"], _r0["value"], SS.status(_cg0)["retired"]))

# —— 全空白串 ——
print("  —— 全空白串（'' / '   ' / '\\t\\n ' / 全角空格） ——")
for _i, _w in enumerate(("", "   ", "\t\n ", "\u3000"), start=6):
    _cgw = _lib("blank_%d" % _i)
    _evt(_cgw, subject="甲", slot="住所", old=None, new="别墅", kind="enablement", seq=1)
    _evt(_cgw, subject="甲", slot="住所", old="别墅", new=_w, kind="retraction", seq=2)
    _u = SS.project(_cgw, include_retired=True)[0]
    _check("A%02d 空白串 %r → 退役（state/value/统计/默认投影四项全对）" % (_i, _w),
           _u["state"] == "retired" and _u["value"] is None
           and SS.status(_cgw)["retired"] == 1 and len(SS.project(_cgw)) == 0,
           (_u["state"], _u["value"], SS.status(_cgw)["retired"]))

# —— 历史原值保留 + 台账行原值未改写 ——
_row = SS.project(_cg, include_retired=True)[0]
_check("A10 变迁史原值保留：history 里 new 仍是 ''、old 仍是 '别墅'",
       [h["new"] for h in _row["history"]] == ["别墅", ""]
       and [h["old"] for h in _row["history"]] == [None, "别墅"],
       _row["history"])
_rows = _ledger_rows(_cg)
_check("A11 台账落盘行原值未被改写（new 仍是空串，append-only 不被回写）",
       [r.get("new") for r in _rows] == ["别墅", ""]
       and [r.get("old") for r in _rows] == [None, "别墅"],
       [r.get("new") for r in _rows])
_check("A12 退役单元的闭合点＝撤回事件（t_to/seq_to 指向第 2 条）",
       _row["t_to"] is not None and _row["seq_to"] == 2, (_row["t_to"], _row["seq_to"]))

# —— 后续带值事件恢复 ——
_evt(_cg, subject="甲", slot="住所", old="", new="小屋", kind="migration", seq=3)
_u = _first(_cg)
_check("A13 后续带值事件自然复活（active / value='小屋' / 默认投影 1 条）",
       _u is not None and _u["state"] == "active" and _u["value"] == "小屋"
       and len(SS.project(_cg)) == 1,
       (_u and _u["state"], _u and _u["value"]))

# —— stg(state_chain) 一致 ——
_ch = _stg.state_chain(_cg, subject="甲", slot="住所")
_check("A14 stg(state_chain) 与投影一致（复活后 count=1 且 items == project）",
       _ch.get("count") == 1 and _ch.get("items") == SS.project(_cg, subject="甲",
                                                                slot="住所"),
       _ch)
_cg2 = _lib("stg_retired")
_evt(_cg2, subject="甲", slot="住所", old=None, new="别墅", kind="enablement", seq=1)
_evt(_cg2, subject="甲", slot="住所", old="别墅", new="   ", kind="retraction", seq=2)
_ch2 = _stg.state_chain(_cg2, subject="甲", slot="住所")
_check("A15 stg(state_chain) 关闭态一致：空白串撤回后 count=0（默认剔除退役）",
       _ch2.get("count") == 0 and _ch2.get("items") == [], _ch2)
_ch3 = _stg.state_chain(_cg2, subject="甲", slot="住所", include_retired=True)
_check("A16 stg(state_chain) include_retired=True → 恰好 1 条且 state=retired",
       _ch3.get("count") == 1 and _ch3["items"][0]["state"] == "retired", _ch3)

print("== K 组：非恒真对照（有值路径不得被误判成撤回） ==")
_cg3 = _lib("k")
_evt(_cg3, subject="甲", slot="s1", old="x", new="0", kind="replacement", seq=1)
_evt(_cg3, subject="乙", slot="s2", old="y", new="  小屋  ", kind="replacement", seq=2)
_evt(_cg3, subject="丙", slot="s3", old="z", new="0", kind="retraction", seq=3)
_evt(_cg3, subject="丁", slot="s4", old="w", new="", kind="migration", seq=4)
_evt(_cg3, subject="戊", slot="s5", old=None, new=0, kind="acquisition", seq=5)
_evt(_cg3, subject="己", slot="s6", old=None, new=False, kind="acquisition", seq=6)
_m = {(u["subject"], u["slot"]): u for u in SS.project(_cg3, include_retired=True)}
_check("K01 非空白单字符 '0' 仍算**有值**（不把「假值」当空）",
       _m[("甲", "s1")]["state"] == "active" and _m[("甲", "s1")]["value"] == "0",
       _m[("甲", "s1")])
_check("K02 带前后空格的值原样保留（不 strip 数据）",
       _m[("乙", "s2")]["state"] == "active"
       and _m[("乙", "s2")]["value"] == "  小屋  ", _m[("乙", "s2")])
_check("K03 kind 标签不进判据①：kind='retraction' 但 new='0' → 仍 active（payload 优先）",
       _m[("丙", "s3")]["state"] == "active", _m[("丙", "s3")])
_check("K04 kind 标签不进判据②：kind='migration' 但 new='' → 仍退役（payload 优先）",
       _m[("丁", "s4")]["state"] == "retired", _m[("丁", "s4")])
_check("K05 非字符串值口径不变：new=0 / new=False 仍算有值（只 None 与空白串算无值）",
       _m[("戊", "s5")]["state"] == "active" and _m[("戊", "s5")]["value"] == 0
       and _m[("己", "s6")]["state"] == "active"
       and _m[("己", "s6")]["value"] is False,
       (_m[("戊", "s5")]["value"], _m[("己", "s6")]["value"]))
_check("K06 孤立撤回（全程无有值事件）→ 退役且起端不编造（t_from/seq_from 为 None）",
       _m[("丁", "s4")]["t_from"] is None and _m[("丁", "s4")]["seq_from"] is None,
       _m[("丁", "s4")])
_st = SS.status(_cg3)
_check("K07 status() 其余读数不受扰（events/subjects/slots 逐位对得上，bad_rows=0）",
       _st["events"] == 6 and _st["subjects"] == 6 and _st["slots"] == 6
       and _st["bad_rows"] == 0 and _st["retired"] == 1, _st)
_check("K08 未受本批影响：history=False 仍不带 history 键（投影 schema 不变）",
       "history" not in SS.project(_cg3, include_retired=True, history=False)[0],
       list(SS.project(_cg3, include_retired=True, history=False)[0]))

print("== E 组：判据单点存在性 ==")
_check("E01 _is_void 是模块级可调用单点",
       callable(getattr(SS, "_is_void", None)), "")
_src = inspect.getsource(SS._replay)
_check("E02 _replay 的两处消费点仍经 _is_void（接线未脱焊：不回退成内联判空）",
       _src.count("_is_void(") == 2, [l for l in _src.splitlines()
                                      if "_is_void" in l])
_src_v = inspect.getsource(SS._is_void)
_check("E03 判据本体在 _is_void 内（None 与空白串两条腿都在）",
       "is None" in _src_v and ".strip()" in _src_v, _src_v)

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #375 结果：%d 失败" % len(FAILS))
else:
    print("issue #375 结果：全部通过")


#: 判据本体的「strip 腿」一行（#383，2026-10-14：判据本体已搬到**源模块**
#: `md_cg/state_events.py::is_void`——投影侧 `state_slots._is_void` 只是同一函数对象的
#: 绑定，state_slots.py 里已无判据源码可改，故 M1 的锚点改指该文件；M2 见下（裁定锚在
#: **重放消费点**，理由与分工写在该条上方））。
#: 单行锚点同时规避本仓 CRLF/LF 混合的折算（state_events.py 为 CRLF）。
_OLD_LEG = '    return isinstance(v, str) and not v.strip()'

_MUTATIONS = (
    ("M1 回缺陷：撤回判据只认 None（空白串按有值进入回放）", "md_cg/state_events.py",
     (_OLD_LEG, '    return False'),
     # 机制：空白串按「有值」进入回放 ⇒ 退役态/统计/默认投影/闭合点/读口全错
     #（A01–A09、A12、A15、A16），同一条判据的其它消费面随之转红：
     # K04（payload 优先腿）、K06（孤立撤回腿）、K07（status 统计腿）、
     # E03（源码形态腿）。A10/A11 只钉「原值保留」，本变异不动原值 ⇒ 恒绿（如实）。
     ("A01", "A02", "A03", "A04", "A06", "A07", "A08", "A09", "A12",
      "A15", "A16", "K04", "K06", "K07", "E03")),
    # ⚠ M2 锚在**重放消费点**（`state_slots._replay`），**不**锚判据本体——编排侧裁定
    # 2026-10-14（方案 F）。为什么：判据被 #383 上收为**跨面共享单点**后，「恒判无值」
    # 打在判据本体上会连**写入口**一起砖掉——本守卫的**首个**夹具
    # _evt(old=None, new="别墅") 立即被 append 的双空闸拒（ValueError 崩栈，栈落
    # state_events.py::append 的 raise），任何 _check 都还没跑到 ⇒ 命名红项恒为空 ⇒
    # _mutate 记 MISMATCH：rc=1 很响、但**红得不可归因**＝变异腿失效（#353 形态）。
    # ⚠ 因此本腿**只测消费方向**：判据**本体**的「恒判无值」方向由 **#383 守卫的 M2** 覆盖
    #（`md_cg/test_issue383_state_event_write_gate.py`，红 19 项、带命名红项）——两面分工：
    # 本体方向归 #383、消费方向归 #375。**后来者勿在本守卫补一条打在判据本体上的腿**
    #（会重复踩本坑：不可归因的红）；本体方向要加，加到 #383 那条上。
    ("M2 过度放宽：恒判无值（任何值都作废）", "md_cg/state_slots.py",
     ('        if _is_void(rec):', '        if True:'),
     # 机制：重放侧恒判无值 ⇒ 一切值都作废、槽位一律退役：「有值」路径全断
     #（K01 非空白单字符 / K02 带前后空格的值 / K05 非字符串值 0、False）、复活腿失效
     #（A13）、消费点计数腿 E02（_replay 里 `_is_void(` 计数 2→1，接线脱焊）转红。
     # 恒绿项如实说明：A01–A04/A12/A15/A16 仍绿——本变异不碰账本行与写闸，只砖重放。
     ("A13", "E02", "K01", "K02", "K05")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss375_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue375_state_slot_retire"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态 / 过度放宽，守卫必须按指定项转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        bad = []
        for desc, rel, (old, new), exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次" % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:10]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
