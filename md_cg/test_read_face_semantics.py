# -*- coding: utf-8 -*-
# 功能名：读面输入语义守卫（M1 显式 k 的**条数**语义 / M2 node_id 类型错与不存在的**可区分性** /
#         M4 action 来源**恒定在场**）
# 生效条件：md_cg/mcp_server.py 的 `_int_arg`（六处委托点：read 搜索路 :2291、read 召回路 :2284、
#           mdcg_search :3343、mdcg_recall :3330、pool_measure :1610、pool_compare :1620）、
#           read 分支的 `node_id` 类型闸（:2271-2278）、`_cg_call` 的
#           `out.setdefault("action_source", act_source)`（:1849-1857）与 `_ACTION_DEFAULT`
#           （:1763）及其 `_cg_call.__doc__` 文档表同源时成立；
#           沙箱条件：库根一律 tempfile.mkdtemp，绝不触在役库、绝不重启在役服务。
# 子功能：
#   M1 条数语义：显式 0 / False → **0 条**（修前回落 20）；缺省 / 显式 None → 20 条；
#     k=3 → 3 条；k=100 → 全量；六处入口逐一验证；pooling 的 `k` 读数如实回显；
#     「k<=0 意味什么」的判据单点在库层（本层不另造报错）。
#   M2 类型闸：非 str node_id（int/float/bool/bytes/list/dict/tuple/set/object）→ 结构化
#     `{"ok": False, "error": "node_id_not_str", "got_type": ...}`，不抛异常（修前哈希可算者
#     返回**裸 null**、不可哈希者 TypeError 逃出）；「id 不存在」仍是协议登记的 null；
#     两态可区分；空串也是「显式」；与字符串形态 id 的碰撞面不得被静默取到。
#   M4 来源透出：`action_source` 四态（explicit/sig/default/none）取值正确、与实际**执行**的
#     action 逐字一致、全 op 恒定在场；`_ACTION_DEFAULT` 与 `_cg_call` 文档表逐项同源。
# 执行：python -X utf8 -m md_cg.test_read_face_semantics
# 验证方式：三组断言各自打**目标语义**（条数 / 两态可区分 / 来源与实际执行一致），经 MCP 面
#           （_cg_call / _dispatch / _sustain_call）在临时沙箱读数。定点变异自证：
#           `python -X utf8 -m md_cg.test_read_face_semantics --drop-fix=all`
#           ——在内存里把 mcp_server.py 源码退回改动前形态（只 exec 副本，**不写盘**），
#           要求指定断言变红、恢复后转绿。
# 不适用条件：不覆盖写面 node_id 类型闸（md_cg/mdcg.py:1776 的 ValueError）；不覆盖「节点不存在 →
#           null」的协议形态（真源 md_cg/protocol.py 的 node_missing.returns_null，反向证据
#           md_cg/test_protocol.py A11/B8/B10）；不覆盖细粒度工具（mdcg_get 等）的入参；不覆盖
#           k 之外的同族入参（limit/offset/sample 等仍为 `or` 回落，非本次修复面）。
"""M1 / M2 / M4 读面输入语义守卫 —— 断言打在语义上，不打在站点上。

三个读面缺陷（2026-09-30 修复，真源 md_cg/mcp_server.py）：

M1 · 显式 k=0 被 `int(a.get("k") or 20)` 当成「没传」→ 静默给 20 条。本文件断言的**语义**是
     「调用方要 0 条就得到 0 条、要 k 条就最多 k 条」，而不是「某一行改成了什么写法」。

M2 · 非 str 的 node_id 静默失真（裸 null / TypeError）。本文件断言的**语义**是「类型错必须
     与『id 不存在』可区分，且不得抛穿 MCP 面、不得降级为检索、不得取到别的节点」。

M4 · 显式 action 时返回里无任何来源痕迹。本文件断言的**语义**是「调用方无需猜：返回里恒有
     action_source，且它与实际执行的那条 action 逐字一致」。

下游消费面（改动影响谁）：`action_source` 供经 MCP 面调 cg 的 agent/客户端判断 action 来源；
`k` 决定 read 的 results/pack 条数、mdcg_search/mdcg_recall 的返回条数、pool_measure/compare
回显的 `k` 字段；`node_id` 的两态形态供调用方区分「传错类型」与「id 不存在」。
"""
import os
import re
import shutil
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import mcp_server as M
from md_cg.mdcos import MdCGSecure
from md_cg.security import DEFAULT_SENSITIVITY, Principal

PASS = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("[PASS] " + name)
    else:
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


# ---------------- 取值钳（修前形态会返回裸 null / 抛 TypeError，直接 .get 会拖崩文件） --------
def _g(o, key, default=None):
    return o.get(key, default) if isinstance(o, dict) else default


def _n(o, key):
    v = _g(o, key)
    return len(v) if isinstance(v, (list, tuple, dict)) else None


def _call(fn, *a, **kw):
    """调 MCP 面并吞异常为可读 dict：异常本身是「形状错」，由断言判红而非拖崩文件。"""
    try:
        return fn(*a, **kw)
    except Exception as e:                                      # noqa: BLE001
        return {"_raised": "%s: %s" % (type(e).__name__, e)}


class Surface(object):
    """被测面：真模块或「源码退回改动前」的内存副本，断言只经它取函数。"""

    def __init__(self, mod):
        self.mod = mod
        self._cg_call = mod._cg_call
        self._dispatch = mod._dispatch
        self._sustain_call = mod._sustain_call
        self._node_view = mod._node_view
        self._int_arg = mod._int_arg
        self._ACTION_DEFAULT = mod._ACTION_DEFAULT
        self.doc = mod._cg_call.__doc__ or ""


def _body(i, token="红按钮"):
    """六要素齐备的语料（过 CCG 闸），每条互不相同以免被去重/合并。"""
    return ("# 功能名：%s移动%d\n# 生效条件：问%s%d\n# 子功能：左移%d\n"
            "# 执行：%s控制角色左移%d\n# 验证方式：test\n# 不适用条件：问蓝按钮%d\n\n"
            "%s控制角色左移 探针编号%d\n" % (token, i, token, i, i, token, i, i, token, i))


def _mk_cg(prefix):
    root = tempfile.mkdtemp(prefix=prefix)
    p = Principal(actor="tester", clearance=DEFAULT_SENSITIVITY, can_write=True,
                  can_admin=True, role="designer", session="sess_s",
                  harness="test-harness")
    return MdCGSecure(root, principal=p), root


# ==========================================================================
# M1 · 条数语义：显式 k 是被尊重的预算（缺省才是 20）
# ==========================================================================
def group_m1(S):
    cg, root = _mk_cg("mdcg_rfs_m1_")
    try:
        N = 25
        for i in range(N):
            cg.add("probe_%02d" % i, _body(i), layer="knowledge",
                   verification_basis="test")
        self_cg = len(cg.index["nodes"]) == N
        check("M1-0 语料自检：沙箱内 %d 条命中语料就位" % N, self_cg,
              len(cg.index["nodes"]))
        o = _call(S._cg_call, cg, {"op": "read", "query": "红按钮", "k": 100})
        check("M1-0b 语料自检：k=100 能收回全量 %d 条（否则条数断言不可判）" % N,
              _n(o, "results") == N, "results=%s" % _n(o, "results"))

        # —— 诚实化核心：显式 0/False 必须得到 0 条（修前回落 20） ——
        for kk in (0, False):
            o = _call(S._cg_call, cg, {"op": "read", "query": "红按钮", "k": kk})
            check("M1-1 read+query 显式 k=%r → 0 条（修前静默给默认 20）" % (kk,),
                  _n(o, "results") == 0, "results=%s" % _n(o, "results"))
        # —— 不放宽：缺省/显式 None 仍是 20 ——
        for a, tag in (({"op": "read", "query": "红按钮"}, "缺省"),
                       ({"op": "read", "query": "红按钮", "k": None}, "显式 None")):
            o = _call(S._cg_call, cg, a)
            check("M1-2 %s k → 20 条（默认预算未被改坏）" % tag,
                  _n(o, "results") == 20, "results=%s" % _n(o, "results"))
        # —— 条数不超过 k ——
        o = _call(S._cg_call, cg, {"op": "read", "query": "红按钮", "k": 3})
        check("M1-3 read+query k=3 → 3 条（条数不超过 k）", _n(o, "results") == 3,
              "results=%s" % _n(o, "results"))
        o = _call(S._cg_call, cg, {"op": "read", "query": "红按钮", "k": "3"})
        check("M1-4 字符串 k='3' 与整数同宽 → 3 条（不回归）",
              _n(o, "results") == 3, "results=%s" % _n(o, "results"))
        # —— 召回路（budget_tokens）：k=0 → pack 0 条 ——
        for kk in (0, False):
            o = _call(S._cg_call, cg, {"op": "read", "query": "红按钮",
                                       "budget_tokens": 1000000, "k": kk})
            check("M1-5 read+budget_tokens 显式 k=%r → pack 0 条（修前满额 20）"
                  % (kk,), _n(o, "pack") == 0, "pack=%s" % _n(o, "pack"))
        # —— 细粒度工具面两条腿 ——
        o = _call(S._dispatch, cg, "mdcg_search", {"query": "红按钮", "k": 0})
        check("M1-6 mdcg_search k=0 → 0 条（修前 20）", _n(o, "results") == 0,
              "results=%s" % _n(o, "results"))
        o = _call(S._dispatch, cg, "mdcg_recall",
                  {"query": "红按钮", "budget_tokens": 1000000, "k": 0})
        check("M1-7 mdcg_recall k=0 → pack 0 条（修前 20）", _n(o, "pack") == 0,
              "pack=%s" % _n(o, "pack"))
        # —— pooling 两条腿：读数如实回显 + 端到端确实空入榜 ——
        o = _call(S._sustain_call, cg, {"op": "sustain", "action": "pool_measure",
                                        "queries": ["红按钮"], "k": 0})
        check("M1-8 pool_measure k=0 → 读数如实回显 k=0（修前回显 20）",
              _g(o, "k") == 0, "k=%r" % _g(o, "k"))
        check("M1-8b pool_measure k=0 → 入榜构成全 0（该查询确实没有任何结果入榜）",
              _g(o, "knowledge_share") == 0.0, "knowledge_share=%r"
              % _g(o, "knowledge_share"))
        o = _call(S._sustain_call, cg, {"op": "sustain", "action": "pool_measure",
                                        "queries": ["红按钮"]})
        check("M1-8c pool_measure 缺省 → 回显 20 且入榜构成非 0（不回归）",
              _g(o, "k") == 20 and (_g(o, "knowledge_share") or 0) > 0,
              "k=%r share=%r" % (_g(o, "k"), _g(o, "knowledge_share")))
        o = _call(S._sustain_call, cg, {"op": "sustain", "action": "pool_compare",
                                        "queries": ["红按钮"], "k": 0})
        check("M1-9 pool_compare k=0 → 读数如实回显 k=0",
              _g(o, "k") == 0, "k=%r" % _g(o, "k"))
        # —— 判据单点在库层：本层不另造报错，两处读数同口径 ——
        res, _meta = cg.search("红按钮", k=0)
        check("M1-10 库层 cg.search(k=0) 返空且不抛（本层不另造报错的依据）",
              res == [], res)
        check("M1-11 单点判据 _int_arg 自身口径：显式 0 透传、缺键回落默认",
              S._int_arg({"k": 0}, "k", 20) == 0
              and S._int_arg({}, "k", 20) == 20
              and S._int_arg({"k": None}, "k", 20) == 20,
              "%r/%r/%r" % (S._int_arg({"k": 0}, "k", 20),
                            S._int_arg({}, "k", 20), S._int_arg({"k": None}, "k", 20)))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ==========================================================================
# M2 · node_id 类型错与「id 不存在」必须可区分，且不得抛穿 / 不得降级为检索
# ==========================================================================
_BAD_TYPES = ((123, "int"), (1, "int"), (3.5, "float"), (True, "bool"),
              (False, "bool"), (b"n1", "bytes"), (["x"], "list"), ({"a": 1}, "dict"),
              (("x",), "tuple"), ({"x"}, "set"))


def group_m2(S):
    cg, root = _mk_cg("mdcg_rfs_m2_")
    try:
        cg.add("n1", _body(1), layer="knowledge", verification_basis="test")
        # 碰撞面：库里真的有字符串形态 id "1" / "True"（与 int 1 / bool True 同形）
        cg.add("1", _body(2), layer="knowledge")
        cg.add("True", _body(3), layer="knowledge")

        # —— 零回归：str 正路径 ——
        o = _call(S._cg_call, cg, {"op": "read", "node_id": "n1"})
        check("M2-1 str node_id 仍返回节点视图（不回归）",
              _g(o, "id") == "n1" and "content" in (o if isinstance(o, dict) else {}),
              str(o)[:90])
        o = _call(S._cg_call, cg, {"op": "read", "node_id": "n1", "offset": 1})
        check("M2-1b str node_id 带 offset 仍工作（不回归）",
              isinstance(o, dict) and "content" in o, str(o)[:90])
        miss = _call(S._cg_call, cg, {"op": "read", "node_id": "no_such_node"})
        check("M2-2 id 不存在 → 协议登记的 null（protocol/test_protocol 零回归）",
              miss is None, repr(miss)[:120])

        # —— 类型错：不抛、给结构化 error、带 got_type ——
        for v, tn in _BAD_TYPES:
            r = _call(S._cg_call, cg, {"op": "read", "node_id": v})
            check("M2-3 非 str node_id(%s) 不抛异常（修前 list/dict/set 抛 TypeError）"
                  % tn, "_raised" not in (r if isinstance(r, dict) else {}),
                  str(r)[:140])
            check("M2-4 非 str node_id(%s) → 结构化 node_id_not_str（修前裸 null）" % tn,
                  isinstance(r, dict) and r.get("ok") is False
                  and r.get("error") == "node_id_not_str"
                  and r.get("got_type") == tn and r.get("node_id") == v,
                  str(r)[:140])

        # —— 两态可区分：类型错 = 结构化 error / 不存在 = null ——
        check("M2-5 两态可区分：类型错是 error 对象、不存在是 null（调用方不必猜）",
              _g(_call(S._cg_call, cg, {"op": "read", "node_id": 1}), "error")
              == "node_id_not_str"
              and _call(S._cg_call, cg, {"op": "read", "node_id": "zzz"}) is None,
              "%r / %r" % (_call(S._cg_call, cg, {"op": "read", "node_id": 1}),
                           _call(S._cg_call, cg, {"op": "read", "node_id": "zzz"})))
        # —— 碰撞面：库内真有 id=="1"，int 1 不得被静默取到那张卡 ——
        check("M2-6 对照：库里 id=='1' 的节点确实存在（碰撞面真实）",
              _g(cg.get("1"), "id") == "1", repr(cg.get("1"))[:60])
        r = _call(S._cg_call, cg, {"op": "read", "node_id": 1})
        check("M2-7 库里存在 id=='1' 时传 int 1 不得取到它（必须报类型错）",
              _g(r, "error") == "node_id_not_str" and _g(r, "id") != "1", str(r)[:120])
        r = _call(S._cg_call, cg, {"op": "read", "node_id": True})
        check("M2-7b 库里存在 id=='True' 时传 bool True 不得取到它（必须报类型错）",
              _g(r, "error") == "node_id_not_str" and _g(r, "id") != "True",
              str(r)[:120])
        # —— 空串也是「显式」：不得静默降级为检索 ——
        e = _call(S._cg_call, cg, {"op": "read", "node_id": ""})
        check("M2-8 空串 node_id 不再静默降级为检索（无 results/meta）",
              not isinstance(e, dict) or ("results" not in e and "meta" not in e),
              str(e)[:140])
        check("M2-8b 空串走「id 不存在」路（与 M2-2 同形：null）", e is None,
              repr(e)[:120])
        # —— 零回归：显式 None 仍是「未传」→ 检索 ——
        o = _call(S._cg_call, cg, {"op": "read", "node_id": None, "query": "红按钮"})
        check("M2-9 node_id=None 仍是「未传」→ 走检索（不回归）",
              (_n(o, "results") or 0) > 0, str(o)[:100])
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ==========================================================================
# M4 · action 来源恒定在场，且与实际执行的 action 逐字一致
# ==========================================================================
def _op_enum(S):
    """从模块**自己的** cg 工具 schema 里取 op 枚举（不另抄一份清单）。"""
    for t in getattr(S.mod, "KERNEL_TOOLS", []):
        if t.get("name") == "cg":
            for v in (t.get("inputSchema") or {}).get("properties", {}).values():
                d = v.get("description") or ""
                if "route|read|write" in d:
                    return d.split("|")
    return []


def group_m4(S):
    cg, root = _mk_cg("mdcg_rfs_m4_")
    try:
        cg.add("n1", _body(1), layer="knowledge", verification_basis="test")
        OPS = _op_enum(S)
        check("M4-0 从模块自身 schema 取到 op 枚举（%d 个）" % len(OPS),
              len(OPS) >= 30, OPS)

        # —— 文档表 ↔ 常量同源（调用方照文档读到的默认动作表不得漂移） ——
        pairs = set(re.findall(r"([a-z_]+)→([a-z_]+)", S.doc))
        table = set(S._ACTION_DEFAULT.items())
        check("M4-1 _cg_call 文档的默认动作表与 _ACTION_DEFAULT 逐项同源（缺/多均红）",
              pairs == table,
              "缺=%s 多=%s" % (sorted(table - pairs), sorted(pairs - table)))

        # —— 四态取值 ——
        o = _call(S._cg_call, cg, {"op": "review", "action": "list"})
        check("M4-2 显式 action（同默认）→ action_source='explicit' 且真的执行了该 action",
              _g(o, "action_source") == "explicit" and "pending" in (o or {}),
              str(o)[:120])
        check("M4-2b 显式态下 action_derived 不出现（旧契约保持）",
              isinstance(o, dict) and "action_derived" not in o, sorted(o or {})[:12])
        # 显式 action ≠ 默认 action：载荷必须是显式那条（证明没被默认顶掉），来源也必须如实
        o = _call(S._cg_call, cg, {"op": "theory", "action": "catalog"})
        check("M4-2c 显式 action≠默认（theory catalog vs check）→ 执行的是显式的、来源如实",
              _g(o, "action_source") == "explicit" and "schema" in (o or {})
              and "declaration_hash" not in (o or {}), str(o)[:120])
        _o, _pid = None, None
        pr = _call(S._dispatch, cg, "mdcg_propose",
                   {"node_id": "p_act", "content": _body(9)})
        _pid = _g(pr, "pid")
        sig = _call(S._cg_call, cg, {"op": "review", "pid": _pid,
                                     "decision": "accept", "reason": "读面语义守卫"})
        check("M4-3 参数签名推导 → 'sig' + action_derived + hint_action 点名依据键",
              _g(sig, "action_source") == "sig" and _g(sig, "action_derived") is True
              and bool(_g(sig, "hint_action")), str(sig)[:140])
        o = _call(S._cg_call, cg, {"op": "review"})
        check("M4-4 无签名走默认 → 'default' 且 action == _ACTION_DEFAULT[op]",
              _g(o, "action_source") == "default"
              and _g(o, "action") == S._ACTION_DEFAULT["review"],
              str({k: _g(o, k) for k in ("action", "action_source")}))
        for _op in ("read", "status", "route", "info", "edges", "help"):
            o = _call(S._cg_call, cg, {"op": _op})
            check("M4-5 无默认的 op=%s → 'none'（不编造默认）" % _op,
                  _g(o, "action_source") == "none"
                  and _g(o, "action_derived") is not True,
                  str({k: _g(o, k) for k in ("action", "action_source",
                                             "action_derived")}))
        # —— 全表逐项：默认动作**实际执行**的那条 == 层里声明的默认 ——
        for _op in sorted(S._ACTION_DEFAULT):
            o = _call(S._cg_call, cg, {"op": _op})
            _d = S._ACTION_DEFAULT[_op]
            check("M4-6 op=%-13s 缺省 → source=default / action=%s（与实际执行一致）"
                  % (_op, _d),
                  _g(o, "action_source") == "default" and _g(o, "action") == _d
                  and _g(o, "action_derived") is True and bool(_g(o, "hint_action")),
                  str({k: _g(o, k) for k in ("action", "action_source",
                                             "action_derived")})[:120])
        # —— 恒定在场：模块自身 op 枚举全覆盖 ——
        raised = []
        for _op in OPS:
            o = _call(S._cg_call, cg, {"op": _op})
            if "_raised" in (o if isinstance(o, dict) else {}):
                raised.append((_op, o["_raised"]))
                continue
            check("M4-7 op=%-11s 返回 dict 时 action_source 恒定在场且取值合法" % _op,
                  isinstance(o, dict) and _g(o, "action_source") in
                  ("explicit", "sig", "default", "none"),
                  str(o)[:110])
        # 抛错面钉住（既有 fail-closed，非本闸范围）：只允许 verify（缺 verdict）
        # 与 state_event（缺 subject/slot——P3 写口的 fail-closed，缺参即
        # ValueError 原样上抛，见 md_cg/test_state_event_op.py E 组）两支；
        # 本闸只管读面 action 推导，写口抛错面在此**登记**（仍「新增抛错即红」）。
        check("M4-8 抛错面只有既有的 verify 缺裁决与 state_event 缺参两支（新增抛错即红）",
              {r[0] for r in raised} <= {"verify", "state_event"}, raised)
        if raised:
            print("      · 已知非 dict 返回：%s" % raised)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ==========================================================================
# 定点变异自证（内存源码退回，不写盘）
# ==========================================================================
_SRC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")

_OLD_INT = '    v = a.get(key)\n    return int(v) if v is not None else default'
_NEW_INT = '    v = a.get(key)\n    return int(v) if v else default'

_OLD_NID = ('        if a.get("node_id") is not None:\n'
            '            _nid = a["node_id"]\n'
            '            if not isinstance(_nid, str):\n'
            '                return {"ok": False, "error": "node_id_not_str",\n'
            '                        "node_id": _nid, "got_type": type(_nid).__name__,\n'
            '                        "hint": "node_id 必须是字符串 id；要按关键词检索请改用 "\n'
            '                                "query（本层不再把类型错静默降级为检索）"}\n'
            '            return _node_view(cg.get(_nid), offset=int(a.get("offset") or 0))')
_NEW_NID = ('        if a.get("node_id"):\n'
            '            return _node_view(cg.get(a["node_id"]),\n'
            '                              offset=int(a.get("offset") or 0))')

_OLD_AS = '        out.setdefault("action_source", act_source)\n'


def _pre_fix_k_zero():
    """M1：把 `_int_arg` 退回真值判断（= 改动前 `int(a.get("k") or 20)`）。"""
    return [(_OLD_INT, _NEW_INT)]


def _pre_fix_node_id_gate():
    """M2：把 read 分支的类型闸退回改动前两行（哈希可算者裸 null、不可哈希者 TypeError）。"""
    return [(_OLD_NID, _NEW_NID)]


def _pre_fix_action_source():
    """M4：抽掉 action_source 的恒定挂载。"""
    return [(_OLD_AS, "")]


_MUTATIONS = {
    "k_zero": (_pre_fix_k_zero, ["M1-1", "M1-5", "M1-6", "M1-7", "M1-8", "M1-8b",
                                 "M1-9"]),
    "node_id_gate": (_pre_fix_node_id_gate, ["M2-3", "M2-4", "M2-5", "M2-7", "M2-8"]),
    "action_source": (_pre_fix_action_source, ["M4-2", "M4-3", "M4-4", "M4-6", "M4-7"]),
}


def _mutated_surface(subs):
    """把 mcp_server.py 源码按 subs 替代一次 → exec 到**独立模块对象**（不落盘）。"""
    src = open(_SRC_PATH, encoding="utf-8").read()
    for old, new in subs:
        if old not in src:
            raise AssertionError("变异锚点未命中：%r" % old[:60])
        src = src.replace(old, new, 1)
    mod = types.ModuleType("mcp_server_mut")
    mod.__file__ = _SRC_PATH
    mod.__package__ = "md_cg"
    exec(compile(src, _SRC_PATH, "exec"), mod.__dict__)      # noqa: S102
    return Surface(mod)


def _run_all(S):
    global PASS, FAILS
    PASS, FAILS = 0, []
    try:
        group_m1(S)
    except Exception as e:                                      # noqa: BLE001
        check("M1-EXCEPTION 分组中断 %s" % type(e).__name__, False, e)
    try:
        group_m2(S)
    except Exception as e:                                      # noqa: BLE001
        check("M2-EXCEPTION 分组中断 %s" % type(e).__name__, False, e)
    try:
        group_m4(S)
    except Exception as e:                                      # noqa: BLE001
        check("M4-EXCEPTION 分组中断 %s" % type(e).__name__, False, e)
    return PASS, list(FAILS)


def main(argv):
    which = None
    for a in argv:
        if a.startswith("--drop-fix"):
            which = a.split("=", 1)[1] if "=" in a else "all"
    if which is None:
        ok, bad = _run_all(Surface(M))
        print("\n==== 读面输入语义守卫：%d 通过%s ===="
              % (ok, "，%d 失败：%s" % (len(bad), "; ".join(bad)) if bad else ""))
        return 1 if bad else 0
    names = list(_MUTATIONS) if which == "all" else [which]
    rc = 0
    print("\n=== 定点变异自证（抽掉修复 → 守卫必红 → 恢复 → 转绿）===")
    for name in names:
        if name not in _MUTATIONS:
            print("  未知变异 %r（可选：%s）" % (name, sorted(_MUTATIONS)))
            return 2
        fn, want = _MUTATIONS[name]
        S = _mutated_surface(fn())
        ok, bad = _run_all(S)
        hit = [n for n in want
               if any(b.split()[0] == n or b.startswith(n) for b in bad)]
        missed = [n for n in want if n not in hit]
        print("  [%s] 红项 %d 个：%s" % (name, len(bad), "; ".join(bad) or "（无）"))
        if missed or not bad:
            print("  FAIL 变异 %s 未打红预期断言：%s" % (name, missed or "全绿"))
            rc = 1
        else:
            print("  ok   变异 %s 打红预期断言 %d 项" % (name, len(hit)))
        ok2, bad2 = _run_all(Surface(M))        # 恢复 = 换回真模块
        if bad2:
            print("  FAIL 恢复后未转绿，残余红项：%s" % bad2)
            rc = 1
        else:
            print("  ok   恢复后转绿（%d 通过，无残余）" % ok2)
    return rc


if __name__ == "__main__":
    try:
        _rc = main(sys.argv[1:])
    finally:
        pass
    sys.exit(_rc)
