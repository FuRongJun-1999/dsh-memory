# -*- coding: utf-8 -*-
"""test_read_face_input_gates · 读面输入闸（M1 显式 k=0 / M2 node_id 类型 / M4 action 来源）

运行：python -m md_cg.test_read_face_input_gates

三个缺陷族（2026-09-30 修复，真源 md_cg/mcp_server.py）：

M1 · `k` 的「显式 0 也是显式」
    六处 `k=int(a.get("k") or 20)` 把显式 0（以及 -1）当「没传」，静默换成默认
    20 —— 调用方以为「要 0 条」，拿到的是 20 条且返回形似正常。修法：单点判据
    `_int_arg(a, "k", 20)`（`is not None` 口径，与 budget_tokens 先例一致），
    六处全部**委托**该助手的单点实现。库层是「k<=0 意味什么」的唯一判据真源
    （实测 cg.search/recall 对 0/-1 均返空且不抛），故本层只判透传 vs 回落。

    **同日补强（k 族同族残余 8 处）**：self_check(5) / scrub.sample(k→n→
    DEFAULT_SAMPLE) / scrub.associate(30) / scrub.sweep(k→n→DEFAULT_SAMPLE) /
    scrub.history(100) / task.find(k→limit→5) / route(10) / mdcg_reflect(10)
    原也是 `int(a.get("k") or N)`（含 k→n / k→limit 链式）。收口口径同上单点；
    链式站点写成 `_int_arg(a, "k", _int_arg(a, "n", D))`——**逐级都不吞显式 0**。
    其中 task.find（库层 `max(int(k or 5), 1)`）与 scrub.history（库层
    `records[-int(limit):]`，0 即「取全部」）在库层另有 0 的语义、端到端不可观察，
    故改断**本层透传给库层的原值**（打桩捕获，见 M1-D13/D14）。

M2 · read 的 node_id 类型闸
    非 str 的 node_id：哈希可算者（int/float/bool）cg.get() 取不到 →
    `_node_view(None)` → **裸 null**；不可哈希者（list/dict）TypeError 逃出。
    修后**类型错**给结构化 error `node_id_not_str`（附 got_type；写面对应闸
    见 mdcg.py:1776 的 `非法 node_id 类型` ValueError，读面取负路由形态）。

    **「节点不存在」有意不动**：`md_cg/protocol.py` 的 read 形态表已登记
    `node_missing.returns_null = True`（note："不是错误对象——客户端须先判空再
    解析"），反向证据 test_protocol A11/B8/B10 钉住它；改它须连带改协议真源与
    那三条断言（不在本次指派文件内）。故两态的可区分性为：类型错 =
    `{"ok": False, "error": "node_id_not_str", ...}`，不存在 = `null`。

M4 · action 来源恒定在场
    旧行为只在「推导过」时透出 action_derived；显式传 action 时返回里没有
    任何痕迹，调用方无法判断 action 是自己传的还是系统挑的。修后返回 dict 里
    `action_source ∈ {explicit, sig, default, none}` **恒定在场**（`action_derived`
    保持旧契约：只标记「推导发生过」，故显式态下**不出现**，test_action_derive
    的 C5 断言依赖这一点）。`_cg_call.__doc__` 载默认动作表，本文件含
    **表 ↔ 文档同源守卫**（防文档与 `_ACTION_DEFAULT` 漂移）。
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows cmd 默认 GBK：中文打印即 UnicodeEncodeError —— 自带 UTF-8 兜底。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import mcp_server as M
from md_cg.mdcos import MdCGSecure
from md_cg.security import DEFAULT_SENSITIVITY, Principal

_ok = 0
_fail = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[PASS] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


def _raises(fn):
    try:
        fn()
        return None
    except Exception as e:                                   # noqa: BLE001
        return e


CCG = ("# 功能名：红按钮移动\n# 生效条件：问红按钮\n# 子功能：左移\n"
       "# 执行：红按钮控制角色左移\n# 验证方式：test\n# 不适用条件：问蓝按钮\n\n"
       "红按钮控制角色左移\n")


# ==================== M1-A. 单点判据（纯函数） ====================
IA = M._int_arg

check("M1-A1 显式 0 原样透传（旧写法回落 20）", IA({"k": 0}, "k", 20) == 0,
      IA({"k": 0}, "k", 20))
check("M1-A2 显式负数原样透传", IA({"k": -3}, "k", 20) == -3, IA({"k": -3}, "k", 20))
check("M1-A3 缺键回落默认", IA({}, "k", 20) == 20, IA({}, "k", 20))
check("M1-A4 显式 None 视为未传，回落默认", IA({"k": None}, "k", 20) == 20,
      IA({"k": None}, "k", 20))
check("M1-A5 普通值原样（不回归）", IA({"k": 5}, "k", 20) == 5, IA({"k": 5}, "k", 20))
check("M1-A6 字符串数字可 int 化（与旧写法同宽）", IA({"k": "7"}, "k", 20) == 7,
      IA({"k": "7"}, "k", 20))
check("M1-A7 判据是 is not None 而非真值（False 也透传）",
      IA({"k": False}, "k", 20) == 0, IA({"k": False}, "k", 20))


# ==================== M1-B. 源码级：六处全部委托单点 ====================
_SRC = open(M.__file__, encoding="utf-8", errors="replace").read()
_k_old = re.findall(r'k=int\(a\.get\("k"\)\s*or\s+20\)', _SRC)
_k_new = re.findall(r'k=_int_arg\(a, "k", 20\)', _SRC)
check("M1-B1 旧写法 k=int(a.get('k') or 20) 已清零（六处全改）",
      len(_k_old) == 0, "残留 %d 处" % len(_k_old))
check("M1-B2 六处全部委托 _int_arg 单点（一处实现，六处调用）",
      len(_k_new) == 6, "实测 %d 处：%s" % (len(_k_new), _k_new))
check("M1-B3 单点实现唯一（_int_arg 只定义一次）",
      len(re.findall(r"^def _int_arg\(", _SRC, re.M)) == 1,
      len(re.findall(r"^def _int_arg\(", _SRC, re.M)))
# ---- k 族**全量**收口（2026-09-30 补强）：除 read 面六处外的其余 8 处站点 ----
# 旧写法在链式上还有 `int(a.get("k") or a.get("n") or N)` / `... or a.get("limit") or N`
# 两种形态，故用「`int(a.get(` 后紧跟 k 键 + or」的全族正则，避免只清直连形态。
_k_family_old = re.findall(r'int\(a\.get\("k"\)\s*or', _SRC)
check("M1-B4 k 族旧写法全量清零（含 k→n / k→limit 链式）",
      len(_k_family_old) == 0, "残留 %d 处" % len(_k_family_old))
_K_SITES = (
    ("metacognition.self_check", r'k=_int_arg\(a, "k", 5\)\)'),
    ("scrub.sample",
     r'cg, _int_arg\(a, "k", _int_arg\(a, "n", scrub\.DEFAULT_SAMPLE\)\),'),
    ("scrub.associate", r'limit=_int_arg\(a, "k", 30\),'),
    ("scrub.sweep",
     r'cg, n=_int_arg\(a, "k", _int_arg\(a, "n", scrub\.DEFAULT_SAMPLE\)\),'),
    ("scrub.history", r'return scrub\.history\(cg, limit=_int_arg\(a, "k", 100\)\)'),
    ("task.find", r'cg, name, k=_int_arg\(a, "k", _int_arg\(a, "limit", 5\)\)\)'),
    ("op.route", r'res, meta = cg\.search\(intent, k=_int_arg\(a, "k", 10\),'),
    ("mdcg_reflect",
     r'res, _ = cg\.search\(a\.get\("query", ""\), k=_int_arg\(a, "k", 10\),'),
)
_site_off = [(n, len(re.findall(p, _SRC)))
             for n, p in _K_SITES if len(re.findall(p, _SRC)) != 1]
check("M1-B5 k 族 8 处站点逐一委托 _int_arg 单点（各恰 1 处）",
      not _site_off, _site_off)


# ==================== M2-A / M4-B. 源码级：文档与常量同源 ====================
_doc = M._cg_call.__doc__ or ""
_doc_pairs = set(re.findall(r"([a-z_]+)→([a-z_]+)", _doc))
_table = dict(M._ACTION_DEFAULT)
check("M4-B1 默认动作表在 _cg_call 文档字符串中逐项在场（调用方不必猜）",
      _doc_pairs == set(_table.items()),
      "缺=%s 多=%s" % (sorted(set(_table.items()) - _doc_pairs),
                       sorted(_doc_pairs - set(_table.items()))))
check("M4-B2 文档表覆盖 _ACTION_DEFAULT 全部 %d 项" % len(_table),
      len([p for p in _doc_pairs if p[0] in _table]) == len(_table),
      len(_doc_pairs))


# ==================== 端到端（真 cg，临时库） ====================
root = tempfile.mkdtemp(prefix="mdcg_rfig_")
try:
    p = Principal(actor="tester", clearance=DEFAULT_SENSITIVITY, can_write=True,
                  can_admin=True, role="designer", session="sess_a",
                  harness="test-harness")
    cg = MdCGSecure(root, principal=p)
    cg.add("n1", CCG, layer="knowledge", verification_basis="test")
    cg.add("n2", CCG.replace("红按钮", "红按钮旁"), layer="knowledge")

    # ---- M1-C. 端到端：k=0 不再是「没传」 ----
    out0 = M._cg_call(cg, {"op": "read", "query": "红按钮", "k": 0})
    check("M1-C1 read+query k=0 返回空结果（修前 20 条）",
          out0.get("results") == [], str(out0.get("results"))[:80])
    outd = M._cg_call(cg, {"op": "read", "query": "红按钮"})
    check("M1-C2 read+query 不传 k 仍走默认 20（不回归）",
          len(outd.get("results") or []) > 0, len(outd.get("results") or []))
    outb = M._cg_call(cg, {"op": "read", "query": "红按钮",
                           "budget_tokens": 100000, "k": 0})
    check("M1-C3 read+budget_tokens 路 k=0 同样透传（pack 为空）",
          outb.get("pack") == [], str(outb.get("pack"))[:80])
    outs = M._dispatch(cg, "mdcg_recall", {"query": "红按钮", "budget_tokens": 100000,
                                           "k": 0})
    check("M1-C4 mdcg_recall k=0 pack 为空（修前 20 条）",
          outs.get("pack") == [], str(outs.get("pack"))[:80])
    outss = M._dispatch(cg, "mdcg_search", {"query": "红按钮", "k": 0})
    check("M1-C5 mdcg_search k=0 结果为空（修前 20 条）",
          outss.get("results") == [], str(outss.get("results"))[:80])
    # 两处 pooling 委托点：measure 把 k 原样回显在返回里，故可直接读读数
    pm0 = M._sustain_call(cg, {"op": "sustain", "action": "pool_measure",
                               "queries": ["红按钮"], "k": 0})
    check("M1-C6 pool_measure k=0 读数如实回显 0（修前回显 20）",
          pm0.get("k") == 0, str(pm0.get("k")))
    pmd = M._sustain_call(cg, {"op": "sustain", "action": "pool_measure",
                               "queries": ["红按钮"]})
    check("M1-C7 pool_measure 不传 k 仍回落 20（不回归）",
          pmd.get("k") == 20, str(pmd.get("k")))
    pc0 = M._sustain_call(cg, {"op": "sustain", "action": "pool_compare",
                               "queries": ["红按钮"], "k": 0})
    check("M1-C8 pool_compare k=0 读数如实回显 0（修前回显 20）",
          pc0.get("k") == 0, str(pc0.get("k")))
    # 库层是「k<=0」判据真源：不抛、返空（修法不自行报错的依据）
    check("M1-C9 库层 cg.search(k=0) 不抛且返空（本层不自造报错的依据）",
          cg.search("红按钮", k=0)[0] == [], cg.search("红按钮", k=0)[0])

    # ---- M1-D. 端到端：k 族**其余 8 处**站点（同日补强，不再只覆盖 read 面） ----
    # 判据面与 M1-C 同：本层只判「显式 0 透传 vs 缺省回落」，**0 在库层的含义由库层
    # 定**——故逐站点断「显式 0 与缺省可区分」，不假定 0 一律等于「0 条」。
    rf0 = M._dispatch(cg, "mdcg_reflect", {"query": "红按钮", "k": 0})
    check("M1-D1 mdcg_reflect k=0 → n_results=0（修前回落 10 条）",
          rf0.get("n_results") == 0, str(rf0.get("n_results")))
    rfd = M._dispatch(cg, "mdcg_reflect", {"query": "红按钮"})
    check("M1-D2 mdcg_reflect 缺省 k → 有结果（回落未被改坏）",
          (rfd.get("n_results") or 0) > 0, str(rfd.get("n_results")))
    rt0 = M._cg_dispatch(cg, {"op": "route", "intent": "红按钮", "k": 0})
    check("M1-D3 route k=0 → knowledge 空（修前回落 10 条）",
          rt0.get("knowledge") == [], len(rt0.get("knowledge") or []))
    rtd = M._cg_dispatch(cg, {"op": "route", "intent": "红按钮"})
    check("M1-D4 route 缺省 k → 有结果（回落未被改坏）",
          len(rtd.get("knowledge") or []) > 0, len(rtd.get("knowledge") or []))
    sm0 = M._scrub_call(cg, {"op": "scrub", "action": "sample", "k": 0})
    check("M1-D5 scrub.sample k=0 → n=0（修前回落 DEFAULT_SAMPLE）",
          sm0.get("n") == 0, str(sm0.get("n")))
    smd = M._scrub_call(cg, {"op": "scrub", "action": "sample"})
    check("M1-D6 scrub.sample 缺省 → 有样本（回落未被改坏）",
          (smd.get("n") or 0) > 0, str(smd.get("n")))
    as0 = M._scrub_call(cg, {"op": "scrub", "action": "associate",
                             "node_id": "n1", "k": 0})
    check("M1-D7 scrub.associate k=0 → 联想 0 条（limit 修前回落 30）",
          as0.get("n") == 0, str(as0.get("n")))
    asd = M._scrub_call(cg, {"op": "scrub", "action": "associate",
                             "node_id": "n1"})
    check("M1-D8 scrub.associate 缺省 → 有联想（回落未被改坏）",
          (asd.get("n") or 0) > 0, str(asd.get("n")))
    sw0 = M._scrub_call(cg, {"op": "scrub", "action": "sweep", "k": 0})
    check("M1-D9 scrub.sweep k=0 → 抽样 0 条（修前回落 DEFAULT_SAMPLE）",
          (sw0.get("sample") or {}).get("n") == 0,
          str((sw0.get("sample") or {}).get("n")))
    swd = M._scrub_call(cg, {"op": "scrub", "action": "sweep"})
    check("M1-D10 scrub.sweep 缺省 → 有抽样（回落未被改坏）",
          ((swd.get("sample") or {}).get("n") or 0) > 0,
          str((swd.get("sample") or {}).get("n")))
    # self_check：k 决定「吃几条相似历史」——上面两次 mdcg_reflect 已写入反思记录
    sc0 = M._metacognition_call(cg, {"op": "metacognition", "action": "self_check",
                                     "query": "红按钮", "k": 0})
    check("M1-D11 self_check k=0 → prior_attempts=0（修前回落 5 条历史）",
          sc0.get("prior_attempts") == 0, str(sc0.get("prior_attempts")))
    scd = M._metacognition_call(cg, {"op": "metacognition", "action": "self_check",
                                     "query": "红按钮"})
    check("M1-D12 self_check 缺省 → 吃到历史（回落未被改坏）",
          (scd.get("prior_attempts") or 0) > 0, str(scd.get("prior_attempts")))
    # task.find 与 scrub.history 两处：**库层对 k 另有语义**（`max(int(k or 5), 1)`
    # 下限 1；`records[-int(limit):]` 下 limit=0 即「取全部」），端到端不可观察 ——
    # 故改断**本层透传的原值**（打桩捕获库层入参，finally 恢复，零残留）。
    from md_cg import scrub as _s_mod, tasks as _t_mod
    _seen = {}
    _orig_fs, _orig_sh = _t_mod.find_similar, _s_mod.history
    try:
        _t_mod.find_similar = lambda cg_, name, k=5: (
            _seen.setdefault("task_find", []).append(k) or {"ok": True})
        _s_mod.history = lambda cg_, limit=100: (
            _seen.setdefault("scrub_history", []).append(limit)
            or {"n": 0, "records": []})
        M._task_call(cg, {"op": "task", "action": "find", "name": "红", "k": 0})
        M._task_call(cg, {"op": "task", "action": "find", "name": "红"})
        M._scrub_call(cg, {"op": "scrub", "action": "history", "k": 0})
        M._scrub_call(cg, {"op": "scrub", "action": "history"})
    finally:
        _t_mod.find_similar, _s_mod.history = _orig_fs, _orig_sh
    check("M1-D13 task.find 显式 k=0 原样透传库层（缺省才回落 5）",
          _seen.get("task_find") == [0, 5], _seen.get("task_find"))
    check("M1-D14 scrub.history 显式 k=0 原样透传库层（缺省才回落 100）",
          _seen.get("scrub_history") == [0, 100], _seen.get("scrub_history"))

    # ---- M2-B. 端到端：node_id 两态可区分、无裸 null、无 TypeError ----
    ok1 = M._cg_call(cg, {"op": "read", "node_id": "n1"})
    check("M2-B1 正路径：str node_id 仍返回节点视图（不回归）",
          isinstance(ok1, dict) and ok1.get("id") == "n1", str(ok1)[:90])
    ok2 = M._cg_call(cg, {"op": "read", "node_id": "n1", "offset": 1})
    check("M2-B2 正路径带 offset 仍工作", isinstance(ok2, dict) and "content" in ok2,
          str(ok2)[:90])
    # 修前此处是**裸 null**（None）；修后「不存在」**仍是 null**——protocol.py 的
    # read 形态表登记 `node_missing.returns_null=True`，反向证据 test_protocol
    # A11/B8/B10 钉住它（改它须连带改协议真源，不在本次指派文件内）。故此处断言的
    # 是「协议形态零回归」，两态可区分性由 M2-B7 单独钉。
    miss = M._cg_call(cg, {"op": "read", "node_id": "no_such_node"})
    check("M2-B3 不存在的 str id 仍返回协议登记的 null（A11/B8/B10 零回归）",
          miss is None, repr(miss)[:120])
    check("M2-B4 两态可区分：类型错是结构化 error 对象，不存在是 null",
          isinstance(M._cg_call(cg, {"op": "read", "node_id": 1}), dict)
          and miss is None, "%r / %r" % (M._cg_call(cg, {"op": "read",
                                                         "node_id": 1}), miss))
    for _bad, _tn in ((123, "int"), (3.5, "float"), (True, "bool"), (["x"], "list"),
                      ({"a": 1}, "dict"), (("x",), "tuple")):
        _r = _raises(lambda b=_bad: M._cg_call(cg, {"op": "read", "node_id": b}))
        check("M2-B5 非 str node_id=%r 不抛异常（修前 list/dict 抛 TypeError）"
              % (_bad,), _r is None, _r)
        # 修前此处 list/dict 会 TypeError：捕成断言失败而不是拖崩整个文件，
        # 否则后续断言连评估机会都没有（红项数会失真）。
        try:
            _o = M._cg_call(cg, {"op": "read", "node_id": _bad})
        except Exception as _e:                              # noqa: BLE001
            _o = {"_raised": "%s: %s" % (type(_e).__name__, _e)}
        check("M2-B6 非 str node_id=%s → node_id_not_str（修前裸 null）" % _tn,
              isinstance(_o, dict) and _o.get("ok") is False
              and _o.get("error") == "node_id_not_str"
              and _o.get("got_type") == _tn and _o.get("node_id") == _bad,
              str(_o)[:140])
    # 取值钳（先例：修前非 str 会返回裸 null/抛 TypeError，直接 .get 拖崩文件）
    def _err(args):
        try:
            _r = M._cg_call(cg, args)
        except Exception as _e:                              # noqa: BLE001
            return "RAISED:%s" % type(_e).__name__
        return _r.get("error") if isinstance(_r, dict) else _r

    check("M2-B7 两态可区分：类型错 = 结构化 error，不存在 = 协议登记的 null",
          _err({"op": "read", "node_id": 1}) == "node_id_not_str"
          and _err({"op": "read", "node_id": "zzz"}) is None,
          "type=%r miss=%r" % (_err({"op": "read", "node_id": 1}),
                               _err({"op": "read", "node_id": "zzz"})))
    check("M2-B8 显式空串 node_id 不再静默降级为检索（判据 is not None）",
          M._cg_call(cg, {"op": "read", "node_id": ""}) is None,
          repr(M._cg_call(cg, {"op": "read", "node_id": ""}))[:140])
    check("M2-B8b 空串走「节点不存在」路而非 query 检索路（无 results/meta）",
          not isinstance(M._cg_call(cg, {"op": "read", "node_id": ""}), dict),
          repr(M._cg_call(cg, {"op": "read", "node_id": ""}))[:140])
    _znone = M._cg_call(cg, {"op": "read", "node_id": None, "query": "红按钮"})
    check("M2-B9 node_id=None 仍是「未传」，走检索（不回归）",
          "results" in _znone and len(_znone["results"]) > 0, str(_znone)[:100])

    # ---- M4-C. 端到端：action_source 恒定在场 ----
    _o, pid = M._dispatch(cg, "mdcg_propose", {"node_id": "p_act",
                                               "content": CCG}), None
    pid = _o.get("pid")
    ex1 = M._cg_call(cg, {"op": "review", "action": "list"})
    check("M4-C1 显式 action → action_source='explicit'",
          ex1.get("action_source") == "explicit", str(ex1.get("action_source")))
    check("M4-C2 显式态下 action_derived 不出现（保持旧契约，C5 依赖）",
          "action_derived" not in ex1, sorted(ex1.keys())[:12])
    sig = M._cg_call(cg, {"op": "review", "pid": pid, "decision": "accept",
                          "reason": "读面闸自测"})
    check("M4-C3 签名推导 → action_source='sig' + action_derived + hint_action",
          sig.get("action_source") == "sig" and sig.get("action_derived") is True
          and bool(sig.get("hint_action")), str(sig)[:140])
    dfl = M._cg_call(cg, {"op": "review"})
    check("M4-C4 无签名走默认 → action_source='default' 且点名默认 action",
          dfl.get("action_source") == "default" and dfl.get("action") == "list"
          and "list" in (dfl.get("hint_action") or ""), str(dfl)[:140])
    dfl2 = M._cg_call(cg, {"op": "protect"})
    check("M4-C5 protect 缺省 stats 同样透出 action_source='default'",
          dfl2.get("action_source") == "default" and dfl2.get("action") == "stats",
          str({k: dfl2.get(k) for k in ("action", "action_source")}))
    ex2 = M._cg_call(cg, {"op": "protect", "action": "stats"})
    check("M4-C6 protect 显式 stats → 'explicit'",
          ex2.get("action_source") == "explicit", str(ex2.get("action_source")))
    none_ = M._cg_call(cg, {"op": "read", "query": "红按钮"})
    check("M4-C7 该 op 无默认（read）→ action_source='none'（不编造默认）",
          none_.get("action_source") == "none", str(none_.get("action_source")))
    for _op in ("review", "task", "recent", "goal", "protect", "scrub", "link",
                "theory", "ccg", "ref", "whitebox", "read", "status"):
        _r = M._cg_call(cg, {"op": _op})
        check("M4-C8 「推导发生过」恒定在场：op=%s" % _op,
              isinstance(_r, dict) and "action_source" in _r, str(_r)[:90])
finally:
    import shutil
    shutil.rmtree(root, ignore_errors=True)

print("=" * 64)
print("read_face_input_gates：%d 通过 / %d 失败" % (_ok, len(_fail)))
if _fail:
    print("失败项：" + "; ".join(_fail))
sys.exit(1 if _fail else 0)
