# -*- coding: utf-8 -*-
"""S9b 三元组反查 · 工具面集成探针（阶段二 4.2 T9，脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_retr_s9_entity_ctx
库层原语语义归 `test_retr_s9_edges.py`，本件只测**工具面集成**：
- 分派全链路：`_cg_dispatch` / `_cg_call` → `_edges_call` → `provenance.find_edges`
- op 缺省推导防呆负例：`child=` 不构成 edges 签名，漏 op 走 read 不冒充反查
- 权限闸双面：`ops_allow` 含 edges 放行；不含 → AccessDenied（通配 "*" 不限）
- 渐进披露：slim 后 op=edges 段被投影、职责行 ≤160；`op=help,query=edges` 无损取回
- schema 一致性：扁平参数面与库层签名同形（含 expand_nodes）；无 subject/predicate/object 第二套参数
- 协议对账：`protocol.audit` AST 自动发现 edges（extension_ops 报告项，ok=True）
- FUNC_DESC 覆盖守卫：cogmap_sync 功能描述表必须登记 ("cg", "edges")
"""
import inspect
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import provenance, protocol, tool_face as tf          # noqa: E402
from md_cg.mdcg import MdCG                                      # noqa: E402
from md_cg.mdcos import MdCGSecure                               # noqa: E402
from md_cg.security import AccessDenied, Principal               # noqa: E402
from md_cg import mcp_server as ms                               # noqa: E402

passed = 0
failed = 0
T = "阿尔法 三元组 反查 探针"

# _edges_call 透传的扁平参数面（schema ↔ 实现同形守卫的期望集）
EDGE_ARGS = ("child", "parent", "relation", "batch",
             "start_time", "end_time", "start_operator", "end_operator",
             "time_axis", "ordering", "offset", "limit", "aggregation",
             "expand_nodes")


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + detail)


def _build(root):
    cg = MdCG(root)
    for nid in ("p1", "p2"):
        cg.add(nid, T, "knowledge")
    cg.add("a1", T, "knowledge", derived_from=["p1"])
    cg.add("a2", T, "knowledge", derived_from=["p1"], relation="extracted_from")
    cg.flush()
    return cg


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:                                       # noqa: BLE001
        return False
    return False


def main():
    root = tempfile.mkdtemp(prefix="retr_s9b_")
    cg = _build(root)

    # ================= 1) 分派全链路 =================
    r = ms._cg_dispatch(cg, {"op": "edges", "child": "a1"})
    check("dispatch 直调：op=edges → _edges_call → find_edges（ok/readonly/total）",
          isinstance(r, dict) and r.get("ok") is True and r.get("readonly") is True
          and r.get("op") == "edges" and r.get("total") == 1
          and r["edges"][0]["child"] == "a1", str(r)[:200])

    rc = ms._cg_call(cg, {"op": "edges", "child": "a2", "expand_nodes": True})
    check("_cg_call 外层透传 expand_nodes：边附端点摘要（a2 在库 / p1 在库）",
          rc.get("ok") is True and rc.get("total") == 1
          and rc["edges"][0]["child_node"]["present"] is True
          and rc["edges"][0]["parent_node"]["present"] is True,
          str(rc.get("edges", [{}])[0].get("child_node")))

    # ================= 2) op 缺省推导防呆（负例）=================
    rd = ms._cg_call(cg, {"child": "a1"})
    check("漏 op 不冒充反查：child= 不是 edges 签名 → 按既有规则推导为 read（op_derived 透出）",
          rd.get("op") == "read" and rd.get("op_derived") is True,
          str({k: rd.get(k) for k in ("op", "op_derived")}))
    check("显式 op 优先：op=edges 时 op_derived 不出现（推导只兜底不覆盖）",
          "op_derived" not in rc)

    # ================= 3) 权限闸双面 =================
    p_ok = Principal(actor="anon", role="anonymous", can_write=False,
                     ops_allow=("info", "route", "read", "edges"))
    p_no = Principal(actor="narrow", role="reader", can_write=False,
                     ops_allow=("info", "route", "read"))
    cg_ok = MdCGSecure(root, principal=p_ok)
    cg_no = MdCGSecure(root, principal=p_no)
    check("ops_allow 含 edges → 放行（只读结果正常返回）",
          ms._cg_dispatch(cg_ok, {"op": "edges", "parent": "p1"}).get("total") == 2)
    check("ops_allow 不含 edges → AccessDenied（角色作用域闸，不静默降级）",
          _raises(AccessDenied, lambda: ms._cg_dispatch(cg_no, {"op": "edges"})),
          "expected AccessDenied")
    check("通配白名单不受新 op 影响：ops_allow=('*',) 放行（designer 形态）",
          ms._cg_dispatch(
              MdCGSecure(root, principal=Principal(
                  actor="boss", role="designer", can_write=True, can_admin=True,
                  ops_allow=("*",))),
              {"op": "edges", "relation": "derived_from"})["total"] == 1)

    # ================= 4) 渐进披露（投影 ↔ help 回取）=================
    slim = {t["name"]: t for t in tf.slim_tools(ms.ALL_TOOLS)}
    cg_slim_desc = slim["cg"].get("description") or ""
    check("slim 后 op=edges 段被投影（常驻上下文不付费）",
          "op=edges：" not in cg_slim_desc and "edges" not in tf.op_sections(cg_slim_desc),
          cg_slim_desc[:120])
    check("slim 后 cg 职责行仍 ≤160 字符（投影不破尺寸预算）",
          len(cg_slim_desc) <= 160, str(len(cg_slim_desc)))
    h = tf.help_text(ms.ALL_TOOLS, query="edges")
    hit = next((x for x in h.get("hits", []) if x.get("op") == "edges"), None)
    check("op=help,query=edges 无损取回：命中 op 段落与透传参数清单（expand_nodes 在列）",
          h.get("ok") is True and hit is not None
          and "expand_nodes" in json.dumps(hit.get("params") or []),
          str(h)[:200])

    # ================= 5) schema 一致性 =================
    cg_tool = next(t for t in ms.ALL_TOOLS if t["name"] == "cg")
    isch = cg_tool.get("inputSchema") or {}
    props = isch.get("properties") or {}
    req = set(isch.get("required") or [])
    check("schema：edges 全部透传参数在列且均为可选（required 不含）",
          all(k in props for k in EDGE_ARGS)
          and not (req & set(EDGE_ARGS)),
          str([k for k in EDGE_ARGS if k not in props]))
    check("schema：predicate/object 不进参数面（subject 是 identity/self_state/link 既有主体参数，非 edges 引入）",
          not ({"predicate", "object"} & set(props)))
    _ec_src = inspect.getsource(ms._edges_call)
    check("实现面：_edges_call 不读 subject/predicate/object 第二套参数键（术语映射只在 docstring）",
          not any(('"%s"' % k) in _ec_src or ("'%s'" % k) in _ec_src
                  for k in ("subject", "predicate", "object")),
          str([k for k in ("subject", "predicate", "object")
               if k in _ec_src]))
    check("实现签名：find_edges 用 expand_nodes（旧名 expand 已废除，防回潮）",
          "expand_nodes" in inspect.signature(provenance.find_edges).parameters
          and "expand" not in inspect.signature(provenance.find_edges).parameters,
          str(list(inspect.signature(provenance.find_edges).parameters)))

    # ================= 6) 协议对账（AST 自动发现）=================
    au = protocol.audit()
    check("protocol.audit：ok=True、shape_errors 空（edges 属扩展面不违例）",
          au.get("ok") is True and not au.get("shape_errors")
          and not au.get("errors"), str(au.get("errors")))
    check("protocol.audit：AST 自动发现 edges 分支（extension_ops 报告项在列）",
          "edges" in (au.get("actual") or [])
          and "edges" in (au.get("extension_ops") or []),
          str(au.get("actual")))

    # ================= 7) FUNC_DESC 覆盖守卫 =================
    sync_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "scripts", "cogmap_sync.py")
    sync_src = open(sync_path, encoding="utf-8").read()
    check("cogmap_sync.FUNC_DESC 登记 (\"cg\", \"edges\")（功能调用映射表覆盖门禁的前置）",
          '("cg", "edges")' in sync_src)

    print("\ntest_retr_s9_entity_ctx: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
