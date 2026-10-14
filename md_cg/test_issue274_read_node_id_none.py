# -*- coding: utf-8 -*-
"""读面 node_id「两种显式」处置不对称的守卫（issue #274）。

【本守卫守什么】
#274 报：cg(op=read) 的 node_id=None **静默降级为检索**（返回检索结果包），
而 node_id=123 正确报 node_id_not_str —— 同一个「类型错」两种相反待遇。

复核结论：**读数全部成立，但处置不对称是刻意的，不是疏漏。**
  · 显式 "" 是**显式** —— 旧写法会把它当没传而静默转检索，故它必须落进类型闸，
    走「节点不存在」的 null。
  · 显式 None 是**未传** —— MCP 客户端把「没有 id」序列化成 null 是常规形态，
    故它落到检索分支；由 test_read_face_input_gates 的 M2-B8 / M2-B9 钉住
    （M2-B9 断言名即「node_id=None 仍是「未传」，走检索（不回归）」）。

⇒ 本件的**实际缺陷是文档缺口**：源码只写了 "" 的动机、没写 None 的动机，
  于是外部复审把它读成了疏漏。修法是**补文档**（+ 本守卫钉住该不对称），
  **不是**改行为——改行为会打红 M2-B9，属 issue #274 的 R1（行为变更）。

判据：
  N1 node_id=None ⇒ 走检索（**刻意**；与「不传」同处置）。
  N2 node_id=123 ⇒ node_id_not_str（类型错，对照）。
  N3 node_id="" ⇒ null（显式空串**是**显式，不转检索）。
  N4 不传 node_id ⇒ 走检索。
  N5 node_id=None 与「不传」**逐字节相同** —— 把报告读到的这一事实**钉成契约**，
     以免将来有人"顺手修"成报错而不自知（要改须连带改 M2-B9 与协议表）。
  N6 错误里 got_type 如实（不吞类型）。
  N7 **跨面**：audit 面对 node_id=None 报 node_id_not_str —— 两面口径不同，
     本守卫**如实记录**该差异（不是要求一致；audit 无检索分支可落）。
  N8 **真 MCP stdio**：JSON null ⇒ 检索包；123 ⇒ 类型错（真通路同形）。
  N9 **反陈化（本件修复的实质）**：源码注释必须写明 None 的动机。
     只写 "" 的动机 ⇒ 红——因为那正是本件被误读成疏漏的根因。
  N10 交叉引用：钉住该行为的 M2-B8 / M2-B9 两条断言仍存在（若被删，本守卫须知道）。

运行：python -X utf8 -m md_cg.test_issue274_read_node_id_none
      python -X utf8 -m md_cg.test_issue274_read_node_id_none --mutate

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红。

沙箱纪律：库根落守卫临时目录，绝不碰在役库与 ~/.mdcg。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile

from .mdcos import MdCGOS
from . import mcp_server as MS

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

_PASS: list = []
_FAIL: list = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  -> " + str(extra)) if (extra and not cond) else ""))


def _cg(tag):
    root = tempfile.mkdtemp(prefix="n274_%s_" % tag)
    cg = MdCGOS(root)
    cg.add(content="# alpha 知识\n\nalpha 内容。", layer="knowledge", node_id="n1",
           importance=0.5, consistency=False, on_conflict="defer")
    return cg


def _call(cg, a):
    try:
        return MS._cg_call(cg, a)
    except Exception as exc:                                  # noqa: BLE001
        return {"__exc__": type(exc).__name__, "msg": str(exc)[:90]}


def _is_search_pack(o) -> bool:
    return isinstance(o, dict) and ("results" in o or "meta" in o or "pack" in o)


def _is_type_error(o) -> bool:
    return isinstance(o, dict) and o.get("error") == "node_id_not_str"


def n1():
    print("== N1 node_id=None 走检索（刻意行为）==")
    cg = _cg("n1")
    o = _call(cg, {"op": "read", "node_id": None, "query": "alpha"})
    ok(_is_search_pack(o), "N1 node_id=None + query ⇒ 检索结果包（刻意）",
       json.dumps(o, ensure_ascii=False)[:150])
    o2 = _call(cg, {"op": "read", "node_id": None})
    ok("__exc__" not in (o2 or {}), "N1b node_id=None 无 query 不抛异常",
       json.dumps(o2, ensure_ascii=False)[:150])


def n2():
    print("== N2 node_id=123 报类型错（对照）==")
    cg = _cg("n2")
    o = _call(cg, {"op": "read", "node_id": 123, "query": "alpha"})
    ok(_is_type_error(o), "N2 node_id=123 ⇒ node_id_not_str",
       json.dumps(o, ensure_ascii=False)[:150])


def n3():
    print("== N3 node_id='' 是显式 ⇒ null（不转检索）==")
    cg = _cg("n3")
    o = _call(cg, {"op": "read", "node_id": "", "query": "alpha"})
    ok(not _is_search_pack(o), "N3a node_id='' 不返回检索包", repr(o)[:150])
    ok(o is None, "N3b node_id='' ⇒ null（协议登记的 node_missing 形态）", repr(o)[:120])


def n4():
    print("== N4 不传 node_id 走检索 ==")
    cg = _cg("n4")
    o = _call(cg, {"op": "read", "query": "alpha"})
    ok(_is_search_pack(o), "N4a 不传 node_id + query ⇒ 检索结果包")
    ok(not _is_type_error(o), "N4b 不传 node_id 不报类型错")


def n5():
    print("== N5 node_id=None 与「不传」逐字节相同（钉成契约）==")
    cg = _cg("n5")
    a1 = _call(cg, {"op": "read", "node_id": None, "query": "alpha"})
    a2 = _call(cg, {"op": "read", "query": "alpha"})
    ok(json.dumps(a1, ensure_ascii=False, sort_keys=True)
       == json.dumps(a2, ensure_ascii=False, sort_keys=True),
       "N5 node_id=None 与不传 node_id 逐字节相同（报告读数，已钉为契约）",
       (json.dumps(a1, ensure_ascii=False)[:100],
        json.dumps(a2, ensure_ascii=False)[:100]))


def n6():
    print("== N6 错误里 got_type 如实 ==")
    cg = _cg("n6")
    for v, want in ((123, "int"), (1.5, "float"), (True, "bool"),
                    (["x"], "list"), ({"a": 1}, "dict")):
        o = _call(cg, {"op": "read", "node_id": v})
        ok(_is_type_error(o) and o.get("got_type") == want,
           "N6 node_id=%r ⇒ got_type=%s" % (v, want),
           (o or {}).get("got_type"))


def n7():
    print("== N7 跨面：audit 面对 None 报类型错（如实记录差异）==")
    cg = _cg("n7")
    o = _call(cg, {"op": "audit", "node_id": None})
    ok(_is_type_error(o), "N7 audit 面 node_id=None ⇒ node_id_not_str（与 read 面口径不同）",
       json.dumps(o, ensure_ascii=False)[:150])


def _wire_err(res):
    try:
        if isinstance(res, dict) and "structuredContent" in res:
            sc = res["structuredContent"]
            if isinstance(sc, dict) and "result" in sc:
                return sc["result"]
            return sc
        if isinstance(res, dict) and "content" in res:
            return json.loads(res["content"][0]["text"])
    except Exception:                                         # noqa: BLE001
        pass
    return res


def n8():
    print("== N8 真 MCP stdio：null ⇒ 检索包；123 ⇒ 类型错 ==")
    root = tempfile.mkdtemp(prefix="n274_stdio_")
    os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
    from . import nodefile
    with io.open(os.path.join(root, "knowledge", "n1.md"), "w",
                 encoding="utf-8") as f:
        f.write(nodefile.dumps({"id": "n1", "layer": "knowledge",
                                "importance": 0.4, "created_at": 1800000000.0,
                                "tags": []}, "alpha 内容"))
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "cg", "arguments": {"op": "read", "node_id": None,
                                        "query": "alpha"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "cg", "arguments": {"op": "read", "node_id": 123,
                                        "query": "alpha"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ]
    env = dict(os.environ, MDCG_ROOT=root,
               MDCG_AUX_ROOT=os.path.join(root, "auxiliary"),
               MDCG_DATA_ROOT=os.path.join(root, "data"),
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               MDCG_MCP_SURFACE="kernel")
    env.pop("MDCG_TOKEN", None)
    keep = ("MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT", "MDCG_MCP_SURFACE")
    for k in list(env):
        if k.startswith("MDCG_") and k not in keep:
            env.pop(k, None)
    try:
        pr = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                            input="".join(json.dumps(m) + "\n" for m in msgs),
                            env=env, cwd=_REPO, capture_output=True, text=True,
                            encoding="utf-8", timeout=120)
        outs = {}
        for line in (pr.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                m = json.loads(line)
            except Exception:                                 # noqa: BLE001
                continue
            if m.get("id") in (1, 2):
                outs[m["id"]] = m.get("result", m)
        ok(pr.returncode == 0, "N8a 真 stdio 子进程正常退出",
           (pr.returncode, (pr.stderr or "")[-200:]))
        o1 = outs.get(1)
        ok(o1 is not None and not _is_type_error(_wire_err(o1)),
           "N8b 真 wire：JSON null ⇒ 走检索（不报类型错）",
           json.dumps(o1, ensure_ascii=False)[:220])
        o2 = outs.get(2)
        ok(o2 is not None and _is_type_error(_wire_err(o2)),
           "N8c 真 wire：123 ⇒ node_id_not_str",
           json.dumps(o2, ensure_ascii=False)[:220])
    except Exception as exc:                                  # noqa: BLE001
        ok(False, "N8 真 stdio 腿抛异常：%r" % (exc,))


def _src() -> str:
    with io.open(os.path.join(_REPO, "md_cg", "mcp_server.py"),
                 encoding="utf-8", errors="replace") as f:
        return f.read()


def n9():
    print("== N9 反陈化：源码必须写明 None 的动机（本件修复的实质）==")
    t = _src()
    ok("issue #274" in t, "N9a 源码标注 issue #274（可追溯）")
    ok("刻意保留" in t or "刻意" in t,
       "N9b 源码写明该不对称是**刻意**的（不是疏漏）")
    ok("M2-B9" in t or "M2-B8" in t,
       "N9c 源码点名钉住该行为的测试（M2-B8/M2-B9）——改它须连带改测试")
    ok("显式 None 是" in t,
       "N9d 源码**逐字**写明 None 的语义（显式 None 是未传）——本件被误读的根因行")


def n10():
    print("== N10 交叉引用：钉住该行为的两条断言仍存在 ==")
    p = os.path.join(_REPO, "md_cg", "test_read_face_input_gates.py")
    with io.open(p, encoding="utf-8", errors="replace") as f:
        t = f.read()
    ok("M2-B8" in t, "N10a M2-B8（显式空串不再静默降级为检索）仍在")
    ok("M2-B9" in t, "N10b M2-B9（node_id=None 仍是未传，走检索）仍在")
    ok("不回归" in t, "N10c M2-B9 仍声明「不回归」语义")


_GROUPS = (n1, n2, n3, n4, n5, n6, n7, n8, n9, n10)


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                              # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-700:])
    return len(_FAIL)


def main() -> int:
    n = _run_groups()
    print("\nnode_id 两种显式处置守卫：%d 通过，%d 失败" % (len(_PASS), n))
    return 1 if n else 0


# --------------------------------------------------------------- 定点变异自证
_MUTATIONS = (
    ("V1 删掉 None 的动机说明（退回「只写空串动机」= 本件被误读的根因）",
     "        #   · 显式 None 是**未传**：MCP 客户端把「没有 id」序列化成 null 是常规形态，",
     "        #   （此处原本写明 None 的动机，被变异删除）",
     "N9"),
    ("V2 判据改为键存在性（把 None 也当显式 ⇒ 行为变更）",
     '        if a.get("node_id") is not None:',
     '        if "node_id" in a:',
     "N1"),
    ("V3 判据改为真值判（把显式空串也当没传）",
     '        if a.get("node_id") is not None:',
     '        if a.get("node_id"):',
     "N3"),
)


def _reload():
    import importlib
    from . import mcp_server as _m
    importlib.reload(_m)
    globals()["MS"] = _m


def _mutate() -> int:
    bad = []
    src_p = os.path.join(_REPO, "md_cg", "mcp_server.py")
    for name, anchor, repl, want in _MUTATIONS:
        with io.open(src_p, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        try:
            if a_ not in orig:
                print("  ANCHOR-MISS %s" % name)
                bad.append(name)
                continue
            with io.open(src_p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_))
            _reload()
            _run_groups()
            reds = list(_FAIL)
            hit = any(r.startswith(want) for r in reds)
            print("  %-4s %-52s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want,
                     "是" if hit else "否"))
            if not hit:
                bad.append(name)
        finally:
            with io.open(src_p, "w", encoding="utf-8", newline="") as f:
                f.write(orig)
            _reload()
    if bad:
        print("\n定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print("\n定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
