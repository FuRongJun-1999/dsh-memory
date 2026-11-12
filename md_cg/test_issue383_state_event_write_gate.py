# -*- coding: utf-8 -*-
# 功能名：state_event 写入口 old/new 双空拒收须认「None 或空白串」，判据与 #375 同源单点（issue #383）
# 生效条件：python -X utf8 -m md_cg.test_issue383_state_event_write_gate [--mutate]；被测面＝md_cg/state_events.py 的 old/new 双空闸（append 经 void_value 走判据单点 is_void）＋ md_cg/state_slots.py 对同一判据的绑定；直调 append / 工具面 cg(op=state_event) / 投影 state_slots 三面端到端
# 子功能：A 组＝#383 正题（双空与全空白串一律 ValueError 且零落盘、工具面同拒、合法组合逐字不改写、写入口确实走单点）；K 组＝非恒真对照（过度收紧方向：合法撤回与合法启用不得被误拒、值不 strip、非字符串值口径不变、其余读数不受扰）；E 组＝判据单源（AST 面：全仓含两条腿的判据实现恰 1 处；源码面：旧判据已退役；运行时 is 同一性）
# 执行：--mutate 时在镜像树里逐条把闸改回缺陷形态／判据退化／过度放宽／过度收紧／再分裂成两份，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符（多红/少红皆不合格），锚点未命中即 fail-closed
# 不适用条件：不覆盖 mcp_server 的参数声明文案（工具面 string 声明已写明双空非法，本批不碰该文件）；不判 kind/seq/evidence 的其它校验；不判语义消歧（not_fact 等，见 state_slots 模块头）；不覆盖跨库/多租户合并；不判 CLI 面（只读人工入口）
"""issue #383 守卫：写入口双空拒收必须与投影侧 #375 判据**同源**。

病象（修前）：`state_events.append` 的闸是 `old is None and new is None`，而工具面参数
声明为 string、「留空」落盘是**空串** ⇒ 该闸在工具面**恒不触发**：客户端发
`{"old": "", "new": ""}` 被静默接受，落一行既不是启用也不是撤回的台账行。

修法：判据上收为**源模块单点** `state_events.is_void`（`None` ∪ 空白串），写入口对裸值
经 `void_value` 走同一条腿；投影侧 `state_slots._is_void` 由「自己实现一份」改为
**绑定同一函数对象**。#375（投影侧）与 #383（写入口侧）是同一病灶的两个落点，
本守卫以 AST 面断言钉死「含两条腿的判据实现全仓恰好一处」。

合法组合**逐字不改写**：`old="v", new=""`＝合法撤回、`old="", new="v"`＝合法启用。
"""
from __future__ import annotations

import ast
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


_TMP = tempfile.mkdtemp(prefix="iss383_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain",
                   "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_STG_STATE": "1"})

from md_cg import mcp_server as _ms     # noqa: E402
from md_cg import state_events as SE    # noqa: E402
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


def _err(fn):
    """调 fn：正常返回 ("", "")；抛异常返回 (异常类型名, 错误文本)。"""
    try:
        fn()
        return "", ""
    except Exception as exc:                      # noqa: BLE001
        return type(exc).__name__, str(exc)


def _rows(cg):
    p = SE.ledger_path(cg)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _by_key(cg):
    return {(r.get("subject"), r.get("slot")): r for r in _rows(cg)}


print("== A 组：#383 正题——双空（含全空白串）必须拒收且零落盘 ==")
# —— issue 原文最小复现（逐字）：修前 append(old="", new="") 静默落一行 ——
_cg = _lib("repro")
_t, _m = _err(lambda: SE.append(_cg, "甲", "住所", old="", new=""))
_check("A01 append(old='', new='') → ValueError（修前静默接受并落盘）",
       _t == "ValueError", (_t, _m))
_check("A02 拒收即零落盘：台账文件不存在、read 0 条",
       not os.path.exists(SE.ledger_path(_cg)) and SE.read(_cg) == [],
       (os.path.exists(SE.ledger_path(_cg)), SE.read(_cg)))
_t, _m = _err(lambda: SE.append(_cg, "甲", "住所", old=None, new=""))
_check("A03 append(old=None, new='') → ValueError（#375 标注的未覆盖边界）",
       _t == "ValueError", (_t, _m))
_t, _m = _err(lambda: SE.append(_cg, "甲", "住所", old="", new=None))
_check("A04 append(old='', new=None) → ValueError", _t == "ValueError", (_t, _m))
_t, _m = _err(lambda: SE.append(_cg, "甲", "住所", old=None, new=None))
_check("A05 既有行为不变：append(None, None) → ValueError（E5/E6 口径）",
       _t == "ValueError", (_t, _m))
_bad = []
for _i, (_o, _n) in enumerate((("  ", chr(9) + chr(10) + " "), (chr(0x3000), ""),
                               (" " + chr(9) + " ", chr(0x3000)))):
    _c = _lib("blank%d" % _i)
    _t, _m = _err(lambda: SE.append(_c, "甲", "住所", old=_o, new=_n))
    if _t != "ValueError" or SE.read(_c):
        _bad.append((_o, _n, _t, SE.read(_c)))
_check("A06 全空白串三组合（含全角空格/制表换行）→ ValueError 且零落盘",
       not _bad, _bad)
for _k in range(3):
    _err(lambda: SE.append(_cg, "甲", "住所", old="", new=""))
_check("A07 连续三次拒收不累积（幂等拒收，台账仍 0 条）",
       _rows(_cg) == [] and SE.read(_cg) == [], _rows(_cg))
_cg2 = _lib("pollute")
_err(lambda: SE.append(_cg2, "乙", "住所", old="v", new="w", kind="migration", seq=1))
_err(lambda: SE.append(_cg2, "乙", "住所", old="", new=""))
_check("A08 拒收不污染既有台账（1 条合法 ＋ 1 次拒收 ⇒ 仍恰 1 条且原值未变）",
       len(_rows(_cg2)) == 1 and _rows(_cg2)[0].get("old") == "v"
       and _rows(_cg2)[0].get("new") == "w", _rows(_cg2))
_t, _m = _err(lambda: SE.append(_cg, "甲", "住所", old="", new=""))
_check("A09 拒收形态是 fail-closed 的 ValueError 且点名 old/new",
       _t == "ValueError" and "old" in _m and "new" in _m, (_t, _m))

# —— 合法组合：逐字不改写（撤回＝old 有值/new 空；启用＝old 空/new 有值） ——
_cgl = _lib("legal")
_t, _m = _err(lambda: SE.append(_cgl, "甲", "住所", old="别墅", new="",
                                kind="retraction", seq=1))
_check("A10 合法撤回 old='别墅', new='' 必须接受", _t == "", (_t, _m))
_t, _m = _err(lambda: SE.append(_cgl, "乙", "住所", old="", new="别墅",
                                kind="enablement", seq=1))
_check("A11 合法启用 old='', new='别墅' 必须接受", _t == "", (_t, _m))
_map = _by_key(_cgl)
_r1 = _map.get(("甲", "住所")) or {}
_r2 = _map.get(("乙", "住所")) or {}
_check("A12 撤回行原值逐字落盘（old='别墅'、new=''，闸不改写值）",
       _r1.get("old") == "别墅" and _r1.get("new") == "", _r1)
_check("A13 启用行原值逐字落盘（old=''、new='别墅'）",
       _r2.get("old") == "" and _r2.get("new") == "别墅", _r2)
_u1 = SS.project(_cgl, subject="甲", slot="住所", include_retired=True)
_u2 = SS.project(_cgl, subject="乙", slot="住所", include_retired=True)
_check("A14 投影对齐：撤回→retired/value=None；启用→active/value='别墅'",
       bool(_u1) and _u1[0]["state"] == "retired" and _u1[0]["value"] is None
       and bool(_u2) and _u2[0]["state"] == "active" and _u2[0]["value"] == "别墅",
       (_u1, _u2))
# —— 写入口确实走**同一单点**（不是内联的第二份判据） ——
_cgs = _lib("single_point")
_orig = SE.is_void
try:
    SE.is_void = lambda rec: rec.get("new") is None
    _t, _m = _err(lambda: SE.append(_cgs, "甲", "住所", old=None, new=""))
    _n = len(SE.read(_cgs))
finally:
    SE.is_void = _orig
_check("A15 单点换成「只认 None」后 append(None,'') 随之放行（写入口经同一条腿）",
       _t == "" and _n == 1, (_t, _n))
_t, _m = _err(lambda: SE.append(_cgs, "甲", "住所", old="", new=""))
_check("A16 单点还原后同一调用恢复拒收（闸不是一份独立内联判据）",
       _t == "ValueError", (_t, _m))

print("== A 组（工具面）：cg(op=state_event) 双空必须拒收且台账 0 行 ==")
_cgt = _lib("toolface")
_t, _m = _err(lambda: _evt(_cgt, subject="甲", slot="住所", old="", new=""))
_check("A17 工具面 old='' new='' → ValueError（修前 ok:true ＋ 台账 1 行）",
       _t == "ValueError", (_t, _m))
_check("A18 工具面拒收后零落盘（台账文件不存在、read 0 条）",
       not os.path.exists(SE.ledger_path(_cgt)) and _rows(_cgt) == [], _rows(_cgt))
_t, _m = _err(lambda: _evt(_cgt, subject="甲", slot="住所", old="  ",
                           new=chr(9) + chr(10)))
_check("A19 工具面全空白串双空 → ValueError 且仍 0 行",
       _t == "ValueError" and _rows(_cgt) == [], (_t, _rows(_cgt)))
_t, _m = _err(lambda: _evt(_cgt, subject="甲", slot="住所", old="v", new=""))
_check("A20 工具面合法撤回 old='v' new='' 照常通过（不误伤）",
       _t == "" and len(_rows(_cgt)) == 1, (_t, _rows(_cgt)))

print("== K 组：非恒真对照（过度收紧方向——合法组合不得被误拒） ==")
_cgk = _lib("k")
_t1, _m1 = _err(lambda: SE.append(_cgk, "甲", "住所", old="别墅", new="",
                                   kind="retraction", seq=1))
_check("K01 合法撤回不得被误拒（不是「任一为空即拒」）", _t1 == "", (_t1, _m1))
_t2, _m2 = _err(lambda: SE.append(_cgk, "乙", "住所", old="", new="别墅",
                                   kind="enablement", seq=1))
_check("K02 合法启用不得被误拒", _t2 == "", (_t2, _m2))
_t3, _m3 = _err(lambda: SE.append(_cgk, "丙", "住所", old="   ", new="船屋",
                                   kind="enablement", seq=2))
_check("K03 old 全空白 ＋ new 有值 ⇒ 合法启用（空白串只在「双空」时才算空）",
       _t3 == "", (_t3, _m3))
_t4, _m4 = _err(lambda: SE.append(_cgk, "丁", "住所", old="船屋", new="   ",
                                   kind="retraction", seq=3))
_check("K04 old 有值 ＋ new 全空白 ⇒ 合法撤回", _t4 == "", (_t4, _m4))
_t5, _m5 = _err(lambda: SE.append(_cgk, "戊", "住所", old="  小屋  ",
                                   new="海景别墅", kind="migration", seq=4))
_check("K05 带前后空格的值照常接受（闸不 strip 数据）", _t5 == "", (_t5, _m5))
_t6, _m6 = _err(lambda: SE.append(_cgk, "己", "住所", old=None, new=0,
                                   kind="acquisition", seq=5))
_t7, _m7 = _err(lambda: SE.append(_cgk, "庚", "住所", old=False, new="",
                                   kind="retraction", seq=6))
_check("K06 非字符串值口径不变：0/False 不是「空」（仍算有值 ⇒ 接受）",
       _t6 == "" and _t7 == "", ((_t6, _m6), (_t7, _m7)))
_kr = _by_key(_cgk).get(("戊", "住所")) or {}
_check("K07 落盘原值逐字未改写（old='  小屋  '、new='海景别墅'）",
       _kr.get("old") == "  小屋  " and _kr.get("new") == "海景别墅", _kr)
_kst = SS.status(_cgk)
_check("K08 投影/统计读数不受扰（events=7、subjects=7、slots=1、bad_rows=0）",
       _kst["events"] == 7 and _kst["subjects"] == 7 and _kst["slots"] == 1
       and _kst["bad_rows"] == 0, _kst)
_b0 = SE.BAD_ROWS
_err(lambda: SE.append(_cgk, "辛", "住所", old="", new=""))
_check("K09 双空拒收不走「坏行容忍」路径（BAD_ROWS 不增）",
       SE.BAD_ROWS == _b0, SE.BAD_ROWS)
_cgk2 = _lib("k_kind")
_t, _m = _err(lambda: _evt(_cgk2, subject="壬", slot="住所", old="v", new="",
                           kind="   "))
_kr2 = _by_key(_cgk2).get(("壬", "住所")) or {}
_check("K10 工具面 kind 归一不受新闸误伤（kind='   ' → None 落盘）",
       _t == "" and _kr2.get("kind") is None, (_t, _kr2))
_t, _m = _err(lambda: SE.append(_cgk, "", "住所", new="v", old=None))
_check("K11 既有 subject/slot 校验不受影响（空 subject 仍 ValueError 且点名 subject）",
       _t == "ValueError" and "subject" in _m, (_t, _m))

print("== E 组：判据单源（AST 面＋源码面＋运行时同一性） ==")
_check("E01 单点是模块级可调用对象（state_events.is_void / void_value）",
       callable(getattr(SE, "is_void", None))
       and callable(getattr(SE, "void_value", None)), "")
_check("E02 投影侧绑定的是同一函数对象（SS._is_void is SE.is_void）",
       getattr(SS, "_is_void", None) is SE.is_void, "")


def _legs(node):
    """函数节点是否含「None 腿」（x is None 比较）与「strip 腿」（x.strip() 调用）。"""
    has_none = has_strip = False
    for n in ast.walk(node):
        if isinstance(n, ast.Compare):
            if any(isinstance(op, ast.Is) for op in n.ops) and any(
                    isinstance(c, ast.Constant) and c.value is None
                    for c in n.comparators):
                has_none = True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "strip":
            has_strip = True
    return has_none, has_strip


def _tree(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return ast.parse(f.read())


_IMPLS = []
for _rel in ("md_cg/state_events.py", "md_cg/state_slots.py"):
    for _n in ast.walk(_tree(_rel)):
        if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _hn, _hs = _legs(_n)
            if _hn or _hs:
                _IMPLS.append((_rel, _n.name, _hn, _hs))
_BOTH = [x for x in _IMPLS if x[2] and x[3]]
_check("E03 AST：全仓（两文件）同时含 None 腿与 strip 腿的判据实现恰 1 处",
       len(_BOTH) == 1, _IMPLS)
_check("E04 AST：该唯一判据落在源模块 state_events.is_void（投影侧不得再写一份）",
       bool(_BOTH) and _BOTH[0][0] == "md_cg/state_events.py"
       and _BOTH[0][1] == "is_void", _BOTH)
_slots = _tree("md_cg/state_slots.py")
_deffs = [n.name for n in ast.walk(_slots) if isinstance(n, ast.FunctionDef)]
_binds = []
for _n in _slots.body:
    if isinstance(_n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_is_void" for t in _n.targets):
        _binds.append(ast.unparse(_n.value))
    elif isinstance(_n, ast.AnnAssign) and isinstance(_n.target, ast.Name) \
            and _n.target.id == "_is_void":
        _binds.append(ast.unparse(_n.value))
_check("E05 AST：state_slots 里 _is_void 是「绑定」而非「实现」（无同名 FunctionDef）",
       "_is_void" not in _deffs, _deffs)
_check("E06 AST：绑定目标逐字 state_events.is_void",
       _binds == ["state_events.is_void"], _binds)
_sa = inspect.getsource(SE.append)
_check("E07 源码：写入口已退役旧判据（不含 old is None and new is None）且经 void_value",
       "old is None and new is None" not in _sa and "void_value(" in _sa, _sa)
_sv = inspect.getsource(SE.void_value)
_check("E08 源码：值面适配不复制判据（void_value 内无 None 腿/strip 腿）",
       "is None" not in _sv and ".strip()" not in _sv, _sv)
_si = inspect.getsource(SE.is_void)
_check("E09 源码：判据本体两条腿都在（is None ＋ strip）",
       "is None" in _si and ".strip()" in _si, _si)
_sr = inspect.getsource(SS._replay)
_check("E10 源码：投影侧两处消费点仍经 _is_void（接线未脱焊）",
       _sr.count("_is_void(") == 2,
       [l for l in _sr.splitlines() if "_is_void" in l])

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #383 结果：%d 失败" % len(FAILS))
else:
    print("issue #383 结果：全部通过")


# ---------------------------------------------------------------- 定点变异表
# 锚点跨行一律用 chr(10) 拼接；_apply_text 按目标文件**实际行尾**折算（本仓 CRLF/LF 混合：
# state_events.py=CRLF、state_slots.py=LF），锚点命中数 != 1 即 ANCHOR-MISS（fail-closed）。
_PRED_LEG = "    return isinstance(v, str) and not v.strip()"
_GATE = "    if void_value(old) and void_value(new):"
_ALIAS = "_is_void = state_events.is_void"
_SPLIT_DEF = """def _is_void(rec) -> bool:
    v = rec.get("new")
    if v is None:
        return True
    return isinstance(v, str) and not v.strip()"""

_MUTATIONS = (
    # M1 回缺陷（#375 投影侧的旧形态）经**共享单点**同时打到两个面：写入口不再拒空白串
    #（A01–A09/A17–A19），且投影侧把空串当「有值」⇒ 撤回不退役（A14）、单点还原后仍放行
    #（A16）、工具面台账多出行（A20）；判据本体少一条腿 ⇒ E03/E04/E09 转红。
    # 设计内不红项：A15（把单点换成「只认 None」后 append(None,"") 放行——本变异下同样放行，
    # 结论不变）、A05（双 None 两态皆拒）、A20 之外的合法组合（值路径本就不经空白串腿）。
    ("M1 判据退化：只认 None（空白串按有值）", "md_cg/state_events.py",
     ((_PRED_LEG, "    return False"),),
     ("A01", "A02", "A03", "A04", "A06", "A07", "A08", "A09", "A14",
      "A16", "A17", "A18", "A19", "A20", "E03", "E04", "E09")),
    # M2 过度放宽：恒判无值 ⇒ 一切合法组合（含撤回/启用/带空白值/非字符串值）全被拒，
    # A10–A14/A20/K01–K08/K10 转红；A08 的合法写入也失败 ⇒ 计数错。
    # 设计内不红项：拒收面（A01–A09/A17–A19）照旧拒（仍 ValueError）、K09（BAD_ROWS 与闸无关）、
    # K11（subject 校验在闸之前）。
    ("M2 过度放宽：恒判无值（任何值都作废）", "md_cg/state_events.py",
     ((_PRED_LEG, "    return True"),),
     ("A08", "A10", "A11", "A12", "A13", "A14", "A20", "E03", "E04",
      "E09", "K01", "K02", "K03", "K04", "K05", "K06", "K07", "K08",
      "K10")),
    # M3 再分裂（本次修复针对的病灶形态本身）：投影侧重新实现一份判据 ⇒ 行为不变
    #（A/K 全绿，**正是**「两处各一份必然漂移」的静默性），但单源面四条断言全红：
    # 同一性（E02）、判据实现计数（E03）、绑定而非实现（E05）、绑定目标（E06）。
    ("M3 再分裂：投影侧重写一份判据（不再绑定）", "md_cg/state_slots.py",
     ((_ALIAS, _SPLIT_DEF),),
     ("E02", "E03", "E05", "E06")),
    # M4 写入口内联旧判据：闸恒不触发（工具面恒久失效）⇒ A01–A09/A17–A19 转红，
    # 且 A16（用 ("","") 探闸）与 A20（台账多出行）随之转红；**E03 也转红**——append 内联的
    # `old is None and new is None` 让 append 自己带上两条腿，「全仓判据实现恰 1 处」当场
    # 破功（AST 面直接抓到「判据被复制回写入口」）；E07 源码面同时转红。
    ("M4 写入口内联旧判据（绕开单点）", "md_cg/state_events.py",
     ((_GATE, "    if old is None and new is None:"),),
     ("A01", "A02", "A03", "A04", "A06", "A07", "A08", "A09", "A16",
      "A17", "A18", "A19", "A20", "E03", "E07")),
    # M5 过度收紧（「任一为空即拒」）：合法撤回/启用被误拒 ⇒ A10–A14/A20/K01–K04/K06 转红，
    # A15（探针用 append(None,"")）也因 or 而拒；带空白**值**的 K05/K07 与不带空白的写入
    # 不受影响（设计内绿：过度收紧只伤「有一侧为空」的合法组合）。
    ("M5 过度收紧：任一为空即拒", "md_cg/state_events.py",
     ((_GATE, "    if void_value(old) or void_value(new):"),),
     ("A10", "A11", "A12", "A13", "A14", "A15", "A20", "K01", "K02",
      "K03", "K04", "K06", "K08", "K10")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss383_mut_")
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
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT",
              "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue383_state_event_write_gate"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _apply_text(text, rel, pairs):
    """按目标文件实际行尾折算锚点后逐条替换；任一锚点命中数 != 1 返回 (None, 原因)。"""
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _mutate():
    print("!! 定点变异自证：逐条把闸改回缺陷形态／判据退化／过度放宽／过度收紧／再分裂，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-25:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:12]:
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
