# -*- coding: utf-8 -*-
"""md_cg · 记忆动词协议 v1 形状钉死（静态对账 + 进程内真调形状）

运行：python -m md_cg.test_protocol

分工（三层，各自独立可裁）：
  A 静态——协议声明 ↔ MCP 面实现：声明五动词 / live 有分支 / reserved 无分支 /
    形状声明完备；`_ops_from_source` 的 AST 提取鲁棒性（单引号 · `op in` 元组 ·
    `op.strip().lower()` 三写法 + 负例 `action ==` 不误取 + 语法错误不炸）。
  B 动态——进程内真调 `_cg_call`，按协议声明的 required 子集校验**真实返回**：
    route / read 三态（node · list · pack，含目标缺失返回 null）/ write 铁律三键 /
    forget 两动作 + 失败形态 / op 推导兜底透出。
  C 集成——`conformance.check()` 确实带上了 protocol.* 四条断言且全绿。

边界（如实声明，不假装覆盖）：
  · write 的 committed 形态在本环境不可达：未配置 MDCG_POLICY_FILE 时校验闸门恒
    DEFER 入 review_queue（实测），故 B 段对 write 断言「铁律三键 + 未 committed
    时去向可见（gate|moved_to）」，并按实际走的那一态校验对应形状；
    committed 形态的字段依据是 writepipe 链尾执行器的源码事实。
  · 本测试**不连真实库**：库根为 tempdir，断言面是形状（键集），不是数据正确性。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import conformance
from md_cg import mcp_server as M
from md_cg import protocol as P
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


def _p(actor="proto"):
    return Principal(actor=actor, clearance=DEFAULT_SENSITIVITY,
                     can_write=True, can_admin=True, role="designer")


def _sub(shape, ret):
    """required 子集判定——协议形状断言的原语。"""
    return set(shape["required"]) <= set(ret or {})


def _raises(exc, fn):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:                                       # noqa: BLE001
        return False


# ==================== A. 静态：协议声明 ↔ MCP 面实现 ====================
print("-- A 静态对账 --")
_a = P.audit()

check("A1 audit ok（声明与实现一致）", _a["ok"] is True, _a["errors"])
check("A2 协议 v1 且 draft 期未冻结（冻结是单向门）",
      _a["protocol_version"] == 1 and _a["frozen"] is False,
      (_a["protocol_version"], _a["frozen"]))
check("A3 声明五动词且顺序固定",
      tuple(_a["declared"]) == ("route", "read", "write", "supersede", "forget"),
      _a["declared"])
check("A4 live 四动词有实现分支",
      set(_a["live"]) == {"route", "read", "write", "forget"}, _a["live"])
check("A5 supersede 登记 reserved 且未泄漏实现（不冒充）",
      _a["reserved"] == ["supersede"] and _a["reserved_leaked"] == [],
      _a["reserved"])
check("A6 无 live 动词缺实现分支", _a["missing_impl"] == [], _a["missing_impl"])
check("A7 扩展能力面如实报告（属能力不属违例）",
      bool(_a["extension_ops"]) and "write" not in _a["extension_ops"],
      _a["extension_ops"])
check("A8 每动词至少一形态、每形态带 when", all(
    P.VERB_SPECS[v]["shapes"]
    and all(s.get("when") for s in P.VERB_SPECS[v]["shapes"].values())
    for v in _a["declared"]), "")
check("A9 write 各形态 required 均含铁律三键",
      all(set(P.WRITE_TRIO) <= set(s["required"])
          for s in P.VERB_SPECS["write"]["shapes"].values()), "")
check("A10 reserved 动词给出 map_to 现状映射证据",
      bool(P.VERB_SPECS["supersede"].get("map_to")), "")
check("A11 read 显式登记 null 形态（目标缺失 ≠ 错误）",
      P.shape_of("read", "node_missing").get("returns_null") is True, "")
check("A12 非法动词 fail-closed（shape_of 抛 KeyError）",
      _raises(KeyError, lambda: P.shape_of("nosuch")), "")
check("A13 summary 单行含 ok=True", "ok=True" in P.summary(), P.summary())

_src = '''
def _d(op, action):
    if op == "double":
        return 1
    if op == 'single':
        return 2
    if op in ("in_a", "in_b"):
        return 3
    if op.strip().lower() == "stripped":
        return 4
    if action == "not_op":
        return 5
    return 0
'''
_ops = P._ops_from_source(_src)
check("A14 AST 提取四写法齐（双引号/单引号/in 元组/strip().lower）",
      set(_ops) == {"double", "single", "in_a", "in_b", "stripped"}, _ops)
check("A15 负例：action == 分支不被误取为 op", "not_op" not in _ops, _ops)
check("A16 语法错误返回空列表且不抛异常",
      P._ops_from_source("if (op ==") == [], "")
check("A17 dispatch_ops 与 audit 同源（同一次提取口径）",
      P.dispatch_ops()["ops"] == _a["actual"], P.dispatch_ops()["ops"])

# ==================== B. 动态：进程内真调形状 ====================
print("-- B 进程内真调形状 --")
_root = tempfile.mkdtemp(prefix="mdcg_proto_")
_body = ("# 功能名：协议形状探针\n# 生效条件：协议形状测试\n# 子功能：无\n"
         "# 执行：探针\n# 验证方式：test_protocol 断言\n"
         "# 不适用条件：非形状测试场景\n\n正文 material_proto")
try:
    cg = MdCGSecure(_root, principal=_p())

    _r = M._cg_call(cg, {"op": "route", "intent": "记忆动词协议形状"})
    check("B1 route 形态 required 齐（knowledge/meta）",
          _sub(P.shape_of("route"), _r), _r)

    _w = M._cg_call(cg, {"op": "write", "content_kind": "text",
                         "layer": "knowledge", "tags": ["proto"],
                         "content": _body})
    check("B2 write 铁律三键齐（ok/id/committed——落盘与否不靠猜）",
          set(P.WRITE_TRIO) <= set(_w or {}), _w)
    check("B3 write 未 committed 时去向可见（gate 或 moved_to）",
          bool((_w or {}).get("committed"))
          or ("gate" in (_w or {}) or "moved_to" in (_w or {})), _w)
    if _w.get("committed"):
        check("B3b write committed 形态 required 齐",
              _sub(P.shape_of("write", "committed"), _w), _w)
    else:
        check("B3c write 闸门短路形态 required 齐（moved_to/verdict/hint）",
              _sub(P.shape_of("write", "gate_short_circuit"), _w), _w)
    check("B4 verdict 字段集与协议声明一致（写闸门短路态）",
          set(P.VERDICT_FIELDS) <= set(_w.get("verdict") or {}), _w.get("verdict"))

    _nid = "mem_proto1"
    cg.add(_nid, _body, content_kind="text", layer="knowledge", tags=["proto"])
    cg.flush()

    _rn = M._cg_call(cg, {"op": "read", "node_id": _nid})
    check("B5 read(node) 形态 required 齐（含 verification_state）",
          _sub(P.shape_of("read", "node"), _rn),
          list(_rn.keys()) if isinstance(_rn, dict) else _rn)

    _rl = M._cg_call(cg, {"op": "read", "query": "协议形状探针"})
    check("B6 read(list) 形态 required 齐（meta/results）",
          _sub(P.shape_of("read", "list"), _rl), _rl)

    _rp = M._cg_call(cg, {"op": "read", "query": "协议形状探针",
                          "budget_tokens": 300})
    check("B7 read(pack) 形态 required 齐（pack/tokens_used/budget/skipped/recent/meta）",
          _sub(P.shape_of("read", "pack"), _rp),
          list(_rp.keys()) if isinstance(_rp, dict) else _rp)

    check("B8 read 目标缺失返回 null（协议登记形态，非错误对象）",
          M._cg_call(cg, {"op": "read", "node_id": "mem_不存在"}) is None, "")

    _f = M._cg_call(cg, {"op": "forget", "node_id": _nid, "reason": "协议测试"})
    check("B9 forget 成功形态 required 齐（ok/id/tombstone）",
          _sub(P.shape_of("forget", "forgotten"), _f), _f)
    check("B10 forget 后 read(node_id) 立即返回 null（软删对读面生效）",
          M._cg_call(cg, {"op": "read", "node_id": _nid}) is None, "")

    _ff = M._cg_call(cg, {"op": "forget", "node_id": _nid, "action": "restore"})
    check("B11 restore 返回属声明两形态之一（restored / failed）",
          _sub(P.shape_of("forget", "restored"), _ff)
          or _sub(P.shape_of("forget", "failed"), _ff), _ff)

    _fm = M._cg_call(cg, {"op": "forget", "node_id": "mem_不存在"})
    check("B12 forget 目标缺失失败形态 required 齐（ok/error）",
          _sub(P.shape_of("forget", "failed"), _fm), _fm)

    _d1 = M._cg_call(cg, {"content": "推导探针 derive_probe_content"})
    check("B13 op 推导兜底：content → write 且透出 op_derived",
          (_d1 or {}).get("op") == "write" and _d1.get("op_derived") is True, _d1)
    check("B14 推导附加键不破坏 write 铁律三键",
          set(P.WRITE_TRIO) <= set(_d1 or {}), _d1)
    check("B15 推导附加键集与协议声明一致（op/op_derived/hint）",
          set(P.DERIVE_EXTRA_KEYS) <= set(_d1 or {}), _d1)

    _d2 = M._cg_call(cg, {"query": "协议形状探针"})
    check("B16 op 推导兜底：query → read",
          (_d2 or {}).get("op") == "read"
          and _sub(P.shape_of("read", "list"), _d2), _d2)
finally:
    shutil.rmtree(_root, ignore_errors=True)

# ==================== C. 集成：conformance 静态对账 ====================
print("-- C conformance 集成 --")
_croot = tempfile.mkdtemp(prefix="mdcg_proto_conf_")
try:
    # conformance.check 需要 `_index.json` 存在，而 flush() 只写分片日志
    # （`_index_log/`）——只有 compact_index()/rebuild_index() 才落 `_index.json`。
    _ccg = MdCGSecure(_croot, principal=_p("proto_conf"))
    _ccg.add("mem_conf1", _body, content_kind="text", layer="knowledge",
             tags=["proto"])
    _ccg.rebuild_index()
    _rep = conformance.check(_croot)
    check("C1 报告含 protocol 段", bool(_rep.get("protocol")),
          list(_rep.keys())[:12])
    _ids = {c["id"]: c for c in _rep["checks"]}
    for _cid in ("protocol.op.extension_surface", "protocol.verb.implemented",
                 "protocol.verb.reserved_clean", "protocol.shape.declared"):
        _c = _ids.get(_cid)
        check("C2 已钉入 conformance 且 ok：%s" % _cid,
              bool(_c) and _c["ok"] is True, _c)
    check("C3 协议外 op 面为报告项 WARN（能力不是违例）",
          _ids["protocol.op.extension_surface"]["level"] == "WARN",
          _ids["protocol.op.extension_surface"]["level"])
    check("C4 protocol.* 全绿（无 FAIL 残留）",
          [c["id"] for c in _rep["checks"]
           if c["id"].startswith("protocol.") and not c["ok"]] == [],
          [c["id"] for c in _rep["checks"]
           if c["id"].startswith("protocol.") and not c["ok"]])
finally:
    shutil.rmtree(_croot, ignore_errors=True)

print("=" * 60)
print("protocol：%d 通过 / %d 失败" % (_ok, len(_fail)))
if _fail:
    print("失败项：" + "; ".join(_fail))
sys.exit(1 if _fail else 0)
