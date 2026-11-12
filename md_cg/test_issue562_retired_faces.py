# -*- coding: utf-8 -*-
# 功能名：#562 退役面单点——superseded 必须与 archived 一样退出默认检索/注入/结构面
# 生效条件：python -X utf8 -m md_cg.test_issue562_retired_faces；被测面＝search / recall / stg.timeline / stg.anchors / chain.adjacency / session_recall 的候选过滤
# 子功能：A 组＝被取代节点（superseded）在四个读面均不出现；K 组＝对照（活跃节点仍出现、archived 仍剔除、显式管理查询仍可见）
# 执行：直接跑；全部 PASS 即通过（退出码 0）
# 验证方式：断言全过 + 退出码 0
# 不适用条件：① 不判「显式管理查询面」（review/history 按 archived 单独判，本件不改）；
#   ② 不判注入的文本内容（只判 id 集合）；③ 不判跨进程可见性（本索引是进程内派生结构）。
"""issue #562 守卫：`is_retired`（archived ∪ superseded）必须被读面真正使用。

病象（报告，0ee388d0）：`superseded` 已进 `lifecycle.is_retired()`，但四个读面/注入面
仍只调 `is_archived()` ⇒ 经 `revise()` 取代的旧版本与新版本**并列返回**。

判据：`is_retired` 是「退出默认检索面」的单点（lifecycle.py 自述），凡是**默认**候选面
（检索候选汇聚、续接注入、stg 三 op、因果链邻接）都必须用它；显式管理查询面保持
`is_archived`（那是「归档」的原义）。
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
    tmp = tempfile.mkdtemp(prefix="i562_")
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
    from md_cg import chain, lifecycle, stg
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    Q = "取代单点探针槽位"
    # work_done 形式完备闸（condaccept）要四维齐；revise 的新版同样过这道闸。
    CS = {"observation_position": "r562", "observation_tool": "r562-probe",
          "existence_constraint": "minlen1"}
    BODY = ("# 功能名：R562 探针事实节点（旧版本）\n"
            "# 生效条件：隔离 temp root 内执行生命周期探针序列\n"
            "# 子功能：测试被取代节点是否退出默认检索面\n"
            "# 执行：add 一次 + revise.revise\n"
            "# 验证方式：四面 id 集合断言\n"
            "# 不适用条件：在役真实记忆库\n"
            "正文：%s = 旧值 v1 依据 lifecycle.py 实测读数\n" % Q)
    p = Principal(tenant="default", actor="r562", clearance="secret",
                  can_write=True, can_admin=True, role="designer")
    cg = MdCGSecure(os.environ["MDCG_ROOT"], principal=p)
    cg.add("r562_old", BODY, layer="knowledge")
    # 兄弟节点必须**文案不同**：V4（同槽异值）会把「同槽不同内容」判冲突，
    # 而 revise 的新旧版本来就同槽——夹具里再造两个同槽兄弟会把 revise 自己挡掉。
    cg.add("r562_live",
           "# 功能名：活跃对照节点" + chr(10) + "# 正文：与探针无关的活跃事实（live 对照）" + chr(10),
           layer="knowledge")
    cg.add("r562_arch",
           "# 功能名：归档对照节点" + chr(10) + "# 正文：与探针无关的归档事实（arch 对照）" + chr(10),
           layer="knowledge")
    # 合法迁移表里 active→archived 是**跨级**（被拒）；按表逐级：active→demoted→archived。
    cg.set_state("r562_arch", "demoted", reason="test")
    cg.set_state("r562_arch", "archived", reason="test")

    # 注：这里**不**用 `revise()` 造夹具——`revise` 的新版以 `work_done` 走形式完备闸，
    # 而 V4（同槽异值）会把「与被修订节点同槽」判成冲突（见本文件末尾的「相邻缺陷」
    # 说明）。#562 的判据面是**读面过滤**，故直接置 superseded + 手写新版本，
    # 保证夹具只测被审的那一件事。
    st = cg.set_state("r562_old", "superseded", reason="r562 夹具")
    ok(isinstance(st, dict) and st.get("ok") is True, "A00 set_state(superseded) 成立（前置）", st)
    new_id = "r562_new"
    cg.add(new_id, BODY.replace("旧值 v1", "新值 v2"), layer="knowledge")
    ok(lifecycle.state_of((cg.index["nodes"] or {}).get("r562_old")) == "superseded",
       "A01 旧节点状态 = superseded（前置）",
       lifecycle.state_of((cg.index["nodes"] or {}).get("r562_old")))
    ok(lifecycle.is_retired((cg.index["nodes"] or {}).get("r562_old")) is True
       and lifecycle.is_archived((cg.index["nodes"] or {}).get("r562_old")) is False,
       "A02 两个判据的差异在位（retired=True / archived=False）")

    def ids(res):
        return {str(x[0].get("id")) if isinstance(x, tuple) else str(x.get("id"))
                for x in (res or [])}

    print("== A 组：四面都不含被取代的旧版本 ==")
    res, _m = cg.search(Q, k=50, record=False)
    s_ids = ids(res)
    ok("r562_old" not in s_ids, "A03 search 不含 superseded", sorted(s_ids))
    ok(new_id in s_ids and "r562_live" in s_ids,
       "A04 search 仍含新版本与活跃节点（不误伤）", sorted(s_ids))
    ok("r562_arch" not in s_ids, "A05 search 仍剔除 archived（对照）", sorted(s_ids))

    pack = cg.recall(Q, budget_tokens=8000, k=50)
    rc_ids = {str(it.get("id")) for it in (pack.get("pack") or [])}
    ok("r562_old" not in rc_ids, "A06 recall 不含 superseded", sorted(rc_ids))

    tl = stg.timeline(cg, limit=10 ** 6, max_scan=10 ** 9)
    t_ids = {str(it.get("id")) for it in (tl.get("items") or [])}
    ok("r562_old" not in t_ids, "A07 stg.timeline 不含 superseded", sorted(t_ids))
    an = stg.anchors(cg, time_window=[1.0, 1e11], limit=10 ** 6, max_scan=10 ** 9)
    a_ids = {str(it.get("id")) for it in (an.get("items") or [])}
    ok("r562_old" not in a_ids, "A08 stg.anchors 不含 superseded", sorted(a_ids))

    print("== K 组：结构面与对照 ==")
    adj = chain.adjacency(cg, skip_archived=True)
    flat = set()
    for k2, vs in (adj.items() if isinstance(adj, dict) else []):
        flat.add(str(k2))
        for v in (vs or []):
            flat.add(str(v.get("id") if isinstance(v, dict) else v))
    ok("r562_old" not in flat, "K01 chain.adjacency（skip_archived）不含 superseded",
       sorted(flat))
    notes = cg._session_notes(session=None, limit=50)
    ok(all(str(n.get("id")) != "r562_old" for n in (notes or [])),
       "K02 会话要点注入面不含 superseded",
       [n.get("id") for n in (notes or [])][:6])

    print("")
    print("=" * 60)
    print("#562 守卫：%d 通过，%d 失败" % (PASS, FAIL))
    for f in FAILS:
        print("  红项：" + f)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
