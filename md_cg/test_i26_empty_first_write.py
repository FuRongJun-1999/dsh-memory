# -*- coding: utf-8 -*-
"""issue #26 守卫：空库首次写入必须可落盘（BLINDSPOT ≠ 冲突）。

病灶（2026-09-23 外部报告，两方独立复现）：冲突闸把 BLINDSPOT（comparable==0，
检测前提不存在）与 REJECT（明确冲突）等同按 on_conflict=defer 拦截——README
推荐的 content_kind='code'「立刻落盘」通路在全新空库上必然失败（committed=false
入审核队列），且 hint 文案把「无法比对」误述为「与既有条件冲突」。

处置层修正（consistency 判定层不动——四态判定保持诚实）：
  BLINDSPOT 恒放行（cvd 审计经链尾 _executor 的 consistency 字段透出）；
  REJECT 拦截语义不变；on_conflict=record 语义不变。

断言：
  E1 空库首写（无条件声明）→ committed=true，verdict=ACCEPT（无冲突）；
  E2 空库首写（带条件声明 → 冲突闸 BLINDSPOT）→ committed=true（能红旧
     实现：原先 committed=false 入队死胡同）且 BLINDSPOT 审计如实透出；
  E3 REJECT（自否定）仍被 defer 拦截入队——明确冲突语义不回归；
  E4 on_conflict=record 放行语义不变。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGSecure
from md_cg.mcp_server import _cg_dispatch

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def _principal(cg_root):
    from md_cg.security import Principal
    return MdCGSecure(cg_root, principal=Principal(
        actor="t_i26", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))


def main():
    print("== E1 空库首写（code，无条件声明）==")
    root = tempfile.mkdtemp(prefix="mdcg_i26a_")
    cg = _principal(os.path.join(root, "graph"))
    out = _cg_dispatch(cg, {"op": "write", "content_kind": "code",
                            "layer": "knowledge",
                            "content": "def main():\n    return 42\n"})
    check("E1 空库首写落盘 + ACCEPT（无冲突）",
          out.get("committed") is True
          and (out.get("consistency") or {}).get("verdict") == "ACCEPT",
          json.dumps(out, ensure_ascii=False, default=str)[:200])

    print("== E2 空库首写（code，带条件声明 → 冲突闸 BLINDSPOT）==")
    root2 = tempfile.mkdtemp(prefix="mdcg_i26b_")
    cg2 = _principal(os.path.join(root2, "graph"))
    out2 = _cg_dispatch(cg2, {"op": "write", "content_kind": "code",
                              "layer": "knowledge",
                              "content": "def main():\n    return 42\n",
                              "condition_space": {"existence_constraint":
                                                  "仅在测试环境"}})
    cvd = out2.get("consistency") or {}
    check("E2a BLINDSPOT 场景落盘成功（能红旧实现：原 committed=false 入队）",
          out2.get("committed") is True,
          json.dumps(out2, ensure_ascii=False, default=str)[:220])
    check("E2b BLINDSPOT 审计如实透出（放行原因可观测）",
          cvd.get("verdict") == "BLINDSPOT",
          json.dumps(cvd, ensure_ascii=False, default=str)[:160])
    check("E2c 无 moved_to（不入死胡同队列）", "moved_to" not in out2)

    print("== E3 REJECT（自否定）仍被 defer 拦截 ==")
    root3 = tempfile.mkdtemp(prefix="mdcg_i26c_")
    cg3 = _principal(os.path.join(root3, "graph"))
    out3 = _cg_dispatch(cg3, {"op": "write", "content_kind": "code",
                              "layer": "knowledge",
                              "content": "x = 1  # debugmode\nprint(x)\n",
                              "non_applicable_conditions": ["debugmode"]})
    cvd3 = out3.get("consistency") or {}
    check("E3 自否定 REJECT 仍拦截入队（明确冲突语义不回归）",
          out3.get("committed") is False
          and out3.get("moved_to") == "review_queue"
          and cvd3.get("verdict") == "REJECT",
          json.dumps(out3, ensure_ascii=False, default=str)[:200])

    print("== E4 on_conflict=record 放行语义不变 ==")
    root4 = tempfile.mkdtemp(prefix="mdcg_i26d_")
    cg4 = _principal(os.path.join(root4, "graph"))
    out4 = _cg_dispatch(cg4, {"op": "write", "content_kind": "code",
                              "layer": "knowledge",
                              "content": "def main():\n    return 7\n",
                              "on_conflict": "record"})
    check("E4 record 下放行（既有语义，不拦不队）",
          out4.get("committed") is True,
          json.dumps(out4, ensure_ascii=False, default=str)[:160])

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print(f"ALL OK: {PASS} 项（issue #26 空库首写守卫全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
