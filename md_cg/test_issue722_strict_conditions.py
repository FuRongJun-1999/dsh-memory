# -*- coding: utf-8 -*-
"""issue #722：strict_conditions（Q1=A 工具面默认放宽 / Q2=A 不抬 state）。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import mcp_server   # noqa: E402
from md_cg.mdcg import MdCG, STATE_BLINDSPOT, STATE_DEFER, STATE_REJECT   # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


BODY = ("# 功能名：周一会议\n# 生效条件：周一上午九点开会\n# 子功能：a\n# 执行：b\n"
        "# 验证方式：test\n# 不适用条件：无\n\n正文内容")

Q = "正文内容怎么用"


def _node(fm_extra=None, content=None):
    fm = {"node_id": "x", "layer": "knowledge"}
    if fm_extra:
        fm.update(fm_extra)
    return {"frontmatter": fm, "content": BODY if content is None else content}


def main():
    print("=" * 68)
    print("issue #722 · strict_conditions（Q1=A / Q2=A）")
    print("=" * 68)
    node = _node({"verification_basis": "test"})
    d0 = MdCG.judge_qualification(node, Q)
    d1 = MdCG.judge_qualification(node, Q, strict_conditions=True)
    ok(d0 == d1, "S1 不传 == 显式 True（深度相等）", (d0, d1))
    ok(d0.get("state") == STATE_DEFER and "usable" not in d0, "S1b 默认 DEFER 且无 usable", d0)
    dr = MdCG.judge_qualification(node, Q, strict_conditions=False)
    ok(dr.get("state") == STATE_DEFER, "S2a 放宽后 state 仍 DEFER", dr)
    ok(dr.get("usable") is True and dr.get("relaxed") is True
       and dr.get("code") == "relaxed_condition", "S2b usable/relaxed/code 齐", dr)
    ok("放宽" in str(dr.get("reason")) and "未冒充" in str(dr.get("reason")),
       "S2c reason 明说放宽且未冒充", dr.get("reason"))
    rej = _node({"verification_basis": "test", "non_applicable_conditions": ["正文内容"]})
    r1 = MdCG.judge_qualification(rej, "正文内容")
    r2 = MdCG.judge_qualification(rej, "正文内容", strict_conditions=False)
    ok(r1.get("state") == STATE_REJECT == r2.get("state"), "S3 REJECT 不受影响", (r1, r2))
    blind = {"frontmatter": {"node_id": "b"}, "content": "只有正文"}
    b1 = MdCG.judge_qualification(blind, Q)
    b2 = MdCG.judge_qualification(blind, Q, strict_conditions=False)
    ok(b1.get("state") == STATE_BLINDSPOT == b2.get("state"), "S4 BLINDSPOT 不受影响", (b1, b2))
    n1 = MdCG.judge_qualification(_node(), Q, strict_conditions=False)
    ok(n1.get("state") == STATE_DEFER and not n1.get("usable"),
       "S5 无验证基底：DEFER 且不标 usable", n1)
    tmp = tempfile.mkdtemp(prefix="iss722_")
    try:
        cg = MdCG(os.path.join(tmp, "r"), autoflush=1)
        cg.add("n722", BODY, layer="knowledge")
        cg.index["nodes"]["n722"]["verification_basis"] = "test"
        # 判定读的是**节点文件**里的 frontmatter（_emit 加载正文+fm），故连文件一起补。
        _rel = cg.index["nodes"]["n722"].get("path") or "knowledge/orphan/n722.md"
        _fp = os.path.join(cg.root, _rel)
        _txt = open(_fp, encoding="utf-8").read().replace("verification_basis: null", "verification_basis: test")
        open(_fp, "w", encoding="utf-8", newline="").write(_txt)
        e1 = (mcp_server.call_tool(cg, "cg", {"op": "read", "query": Q}) or {})
        it1 = (e1.get("results") or [{}])[0]
        ok(it1.get("usable") is True and it1.get("state") == STATE_DEFER,
           "S6a cg(op=read) 不传参 ⇒ 工具面默认放宽",
           {k: it1.get(k) for k in ("state", "usable", "relaxed", "code")})
        e2 = (mcp_server.call_tool(cg, "cg", {"op": "read", "query": Q, "strict_conditions": True}) or {})
        it2 = (e2.get("results") or [{}])[0]
        ok(it2.get("state") == STATE_DEFER and not it2.get("usable"),
           "S6b 显式 strict_conditions=true ⇒ 回严格",
           {k: it2.get(k) for k in ("state", "usable")})
        cg.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("issue #722：%d 项失败" % len(FAILS) if FAILS else "issue #722：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
