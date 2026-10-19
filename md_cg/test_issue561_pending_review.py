# -*- coding: utf-8 -*-
# 功能名：#561 第①项（#553 可见性）——读面对「有待复核新值」的节点标注 pending_review
# 生效条件：python -X utf8 -m md_cg.test_issue561_pending_review；被测面＝mcp_server 的 cg(op=read) 单节点分支 + mdcos.pending_proposals
# 子功能：A 组＝主库旧值 + 队列新值 ⇒ 读面同时给出 pending_review/pending_proposals；K 组＝反恒真（无待复核不得落键、裁决后消失、无关节点不受影响）
# 执行：直接跑；全部 PASS 即通过（退出码 0）
# 验证方式：断言全过 + 退出码 0
# 不适用条件：① 不判检索列表（search/recall）是否逐条标注（本项只钉单节点读面；列表面加标注要按结果数付扫描成本）；
#   ② 不判 DSH 宿主侧提示（#561 第②项）；③ 不判治理面 review_list 的形状（既有守卫覆盖）。
"""issue #561 第①项守卫：读面的「有新值待复核」必须可见。

背景：智能论 3.4 的四态里 DEFER 不冒充接受——但**读者若只看到旧值**，会把「待复核」
误当「最新」。本条不改裁决语义，只在读面 additive 落两个键：
`pending_review: true` 与 `pending_proposals: [pid…]`；没有待复核提案时**不落键**。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASS = 0
FAIL = 0
FAILS = []


def ok(cond, title, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS %s" % title)
    else:
        FAIL += 1
        FAILS.append(title)
        print("  FAIL %s  <- %r" % (title, str(detail)[:180]))


def main():
    tmp = tempfile.mkdtemp(prefix="i561_")
    os.environ.update({
        "MDCG_ROOT": os.path.join(tmp, "brain"),
        "MDCG_STATE_ROOT": os.path.join(tmp, "state"),
        "MDCG_AUX_ROOT": os.path.join(tmp, "auxstore"),
        "MDCG_DATA_ROOT": os.path.join(tmp, "data"),
        "MDCG_EXPORT_ROOT": tmp, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
    })
    for k in ("MDCG_TOKEN", "MDCG_VERIFY_KEY"):
        os.environ.pop(k, None)
    from md_cg import crypto
    os.environ[crypto.MASTER_ENV] = "ab" * 32
    from md_cg import mcp_server as MS
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    p = Principal(tenant="t", actor="designer", role="designer",
                  clearance="private", can_write=True, can_admin=True)
    cg = MdCGSecure(os.environ["MDCG_ROOT"], principal=p)
    cg.add("A", "生产环境数据库端口是 5433。", layer="contextual")
    cg.add("B", "与提案无关的节点。", layer="contextual")

    def read(nid):
        return MS.call_tool(cg, "cg", {"op": "read", "node_id": nid})

    print("== A 组：队列里挂着针对 A 的待裁决提案 ==")
    pv = cg.propose("A", "生产环境数据库端口是 5432（新值，待复核）。",
                    layer="contextual", info=True)
    pid = pv.get("pid") if isinstance(pv, dict) else pv
    ok(bool(pid), "A00 提案已入队（前置）", pv)
    ra = read("A")
    ok(isinstance(ra, dict) and ra.get("pending_review") is True,
       "A01 读面标 pending_review=True", ra.get("pending_review") if isinstance(ra, dict) else ra)
    ok(isinstance(ra, dict) and pid in (ra.get("pending_proposals") or []),
       "A02 读面列出待裁决 pid", (ra or {}).get("pending_proposals"))
    ok(isinstance(ra, dict) and "5433" in (ra.get("content") or ""),
       "A03 旧值仍在（不改语义：主库正文逐字不变）", (ra or {}).get("content"))

    print("== K 组：反恒真与边界 ==")
    rb = read("B")
    ok(isinstance(rb, dict) and "pending_review" not in rb
       and "pending_proposals" not in rb,
       "K01 无待复核提案的节点**不落键**（反恒真）",
       {k: v for k, v in (rb or {}).items() if k.startswith("pending")})
    ok(cg.pending_proposals("A") == [pid], "K02 单点读数与读面一致", cg.pending_proposals("A"))
    ok(cg.pending_proposals("") == [] and cg.pending_proposals("NOPE") == [],
       "K03 空/不存在 id ⇒ 空列表（不抛）",
       (cg.pending_proposals(""), cg.pending_proposals("NOPE")))
    cg.review_decide(pid, "accept", reason="test")
    ra2 = read("A")
    ok(isinstance(ra2, dict) and "pending_review" not in ra2,
       "K04 裁决后键随之消失（不是一次性标记）",
       {k: v for k, v in (ra2 or {}).items() if k.startswith("pending")})
    ok(isinstance(ra2, dict) and "5432" in (ra2.get("content") or ""),
       "K05 裁决 accept 后新值已并入（旧值仍在，聚合可读）",
       (ra2 or {}).get("content"))

    print("")
    print("=" * 60)
    print("#561① 守卫：%d 通过，%d 失败" % (PASS, FAIL))
    for f in FAILS:
        print("  红项：" + f)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
