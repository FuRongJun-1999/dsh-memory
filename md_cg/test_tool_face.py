# -*- coding: utf-8 -*-
"""工具面渐进披露（Pi 移植① 上下文经济学）验收：交接文档 §3①。

蓝图验收两条，本测试把它们机械化为可裁决断言：
① 瘦身前后工具描述 token 数对比（目标 ≥50% 削减，主面 = kernel）；
② 检索/写入功能回归零变化 —— 展开为「工具名 / 参数名 / required / 类型 /
   单枚举值集逐位不变」+「被投影掉的原文可由 op=help 无损取回」。

运行：python -m md_cg.test_tool_face
"""

import json
import os
import re
import sys

from . import mcp_server as ms
from . import tool_face as tf

_ok = 0
_bad = []


def _check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


_ENUM_RE = re.compile(r"[A-Za-z_][\w\-]*(?:\|[A-Za-z_][\w\-]*)+")


def _size(tools):
    return len(json.dumps(tools, ensure_ascii=False))


def _props(tool):
    return (tool.get("inputSchema") or {}).get("properties") or {}


def _required(tool):
    return list((tool.get("inputSchema") or {}).get("required") or [])


def _run():
    origin = ms.ALL_TOOLS
    origin_json = json.dumps(origin, ensure_ascii=False)
    slim = tf.slim_tools(origin)
    by_name_origin = {t["name"]: t for t in origin}
    by_name_slim = {t["name"]: t for t in slim}

    # ---- ① 尺寸：主面（kernel）与 full 面 ----
    k_before, k_after = _size(ms.KERNEL_TOOLS), _size(tf.slim_tools(ms.KERNEL_TOOLS))
    k_cut = 100.0 * (k_before - k_after) / k_before
    _check("kernel 注入面削减 ≥50%%（%d→%d，%.2f%%）" % (k_before, k_after, k_cut),
           k_cut >= 50.0, "%.2f%%" % k_cut)
    f_before = _size(ms.TOOLS)
    f_after = _size(tf.slim_tools(ms.TOOLS))
    f_cut = 100.0 * (f_before - f_after) / f_before
    _check("full 面削减 ≥20%%（%d→%d，%.2f%%）" % (f_before, f_after, f_cut),
           f_cut >= 20.0, "%.2f%%" % f_cut)
    cg_slim = by_name_slim["cg"]
    _check("cg 工具职责行 ≤160 字符",
           len(cg_slim.get("description") or "") <= 160,
           str(len(cg_slim.get("description") or "")))
    _check("每个工具职责行非空且 ≤160 字符",
           all(0 < len(t.get("description") or "") <= 160 for t in slim),
           str([t["name"] for t in slim if not t.get("description")]))

    # ---- ② 契约逐位不变 ----
    _check("工具名序列逐位一致",
           [t["name"] for t in origin] == [t["name"] for t in slim],
           str([t["name"] for t in slim]))
    name_ok, type_ok, req_ok, order_ok = True, True, True, True
    for name, o in by_name_origin.items():
        s = by_name_slim[name]
        po, ps = _props(o), _props(s)
        if list(po.keys()) != list(ps.keys()):
            order_ok = False
        if _required(o) != _required(s):
            req_ok = False
        for key, spec in po.items():
            if spec.get("type") != ps[key].get("type"):
                type_ok = False
    _check("参数名序列逐位一致（含顺序）", order_ok)
    _check("required 逐位一致", req_ok)
    _check("参数类型逐位一致", type_ok)

    enum_ok, enum_detail = True, ""
    externalized = []          # 被整体外置的参数：(tool, param, 原文)
    for name, o in by_name_origin.items():
        ps = _props(by_name_slim[name])
        for key, spec in _props(o).items():
            d0 = spec.get("description") or ""
            d1 = ps[key].get("description")
            if not d0:
                continue
            groups = _ENUM_RE.findall(d0)
            if len(groups) == 1:
                if d1 != groups[0]:
                    enum_ok = False
                    enum_detail = "%s.%s: %r != %r" % (name, key, d1, groups[0])
            if d1 is None:
                externalized.append((name, key, d0))
    _check("单枚举参数的完整值集保留（调用契约不可省）", enum_ok, enum_detail)
    _check("存在被外置的长尾参数（确实发生了分层）", len(externalized) > 0,
           "%d 个" % len(externalized))

    # ---- ③ 信息零丢失：被投影掉的原文可由 op=help 无损取回 ----
    miss = []
    for name, key, d0 in externalized:
        r = tf.help_text(origin, query=key)
        got = [h.get("desc") for h in r.get("hits", [])
               if h.get("tool") == name and h.get("param") == key]
        if not got or got[0] != d0:
            miss.append("%s.%s" % (name, key))
    _check("外置参数原文可由 op=help 逐字取回（%d 个）" % len(externalized),
           not miss, str(miss[:5]))

    tm = tf.help_text(origin, query="cg")
    ok_desc = all(tm["params"][i]["desc"] == _props(by_name_origin["cg"])[p["name"]]["description"]
                  for i, p in enumerate(tm["params"]))
    _check("工具级 help 返回真源全参数完整描述（逐字）", ok_desc)
    secs = tf.op_sections(by_name_origin["cg"].get("description") or "")
    bad_ops = [op for op in secs
               if not any(h.get("op") == op and h.get("doc") == secs[op]
                          for h in tf.help_text(origin, query=op).get("hits", []))]
    _check("每个 op 的段落原文可由 op=help 取回（%d op）" % len(secs), not bad_ops,
           str(bad_ops[:5]))
    # 分层后的按需面必须完整：op 枚举里的每个 op 都要有说明段，
    # 否则「常驻面不再解释它」+「按需面也查不到」= 真的丢能力。
    enum_ops = set()
    for m in _ENUM_RE.finditer(_props(by_name_origin["cg"])["op"].get("description") or ""):
        enum_ops |= set(m.group(0).split("|"))
    enum_ops.discard("help")
    gap = sorted(o for o in enum_ops if o not in secs)
    _check("op 枚举的每个 op 都有按需说明段（%d 个）" % len(enum_ops), not gap, str(gap))

    # ---- ④ help 面 ----
    idx = tf.help_text(origin, query=None)
    _check("help 无 query 返回全量工具索引",
           [i["name"] for i in idx["tool_index"]] == [t["name"] for t in origin])
    _check("索引每项职责行非空",
           all(i["brief"].strip() for i in idx["tool_index"]))
    r = tf.help_text(origin, query="write")
    _check("help query=write 命中 cg 的 write 段",
           any(h.get("tool") == "cg" and h.get("op") == "write" and h.get("doc")
               for h in r.get("hits", [])))
    r2 = tf.help_text(origin, query="__no_such_op__")
    _check("help 未命中时诚实报错并给 hint",
           r2.get("ok") is False and "hint" in r2, str(r2)[:80])
    e2e = ms._cg_call(None, {"op": "help", "query": "write"})
    _check("cg(op=help) 端到端可用（经分发层）",
           isinstance(e2e, dict) and e2e.get("ok") is True, str(e2e)[:80])

    # ---- ⑤ 开关 / 幂等 / 真源不受损 ----
    os.environ["MDCG_TOOL_FACE"] = "full"
    try:
        raw = ms.tools_for_surface()
    finally:
        os.environ.pop("MDCG_TOOL_FACE", None)
    _check("MDCG_TOOL_FACE=full 时返回完整真源",
           json.dumps(raw, ensure_ascii=False) == json.dumps(
               ms.KERNEL_TOOLS if ms.SURFACE != "full" else ms.ALL_TOOLS,
               ensure_ascii=False))
    _check("投影幂等（slim(slim)==slim）",
           json.dumps(tf.slim_tools(slim), ensure_ascii=False)
           == json.dumps(slim, ensure_ascii=False))
    _check("投影不改真源（ALL_TOOLS 逐字未变）",
           json.dumps(ms.ALL_TOOLS, ensure_ascii=False) == origin_json)
    _check("tools_for_surface 与投影一致",
           json.dumps(ms.tools_for_surface(), ensure_ascii=False)
           == json.dumps(tf.slim_tools(ms.KERNEL_TOOLS if ms.SURFACE != "full"
                                       else ms.ALL_TOOLS), ensure_ascii=False))


def main():
    print("[tool_face] 工具面渐进披露验收")
    _run()
    print("\n%d passed, %d failed" % (_ok, len(_bad)))
    return 1 if _bad else 0


if __name__ == "__main__":
    sys.exit(main())
