# -*- coding: utf-8 -*-
"""kp_ 对齐端到端（P36 · 设计态验收）。

对照交付计划「决策一：三段硬依赖，不可并行倒置」与「条目 4：豁免分批解除与验收对比」：

  ① 基线：`ccg_exempt=true` 的节点四态恒 DEFER（可检索、不可判定）
  ② 反证：**证据未补就摘豁免** → 由 DEFER 退化为 BLINDSPOT（必须比现状更差）
  ③ 顺序：证据（crosscheck）→ 5 要素齐备 → 才允许摘豁免
  ④ 分批：`exempt_plan` 只列就绪节点，`exempt_apply` 逐批推进、可续跑、天然幂等
  ⑤ 打破：摘豁免后有证据节点转 ACCEPT，DEFER 恒定被打破
  ⑥ 诚实：占位空壳与缺证据节点**不摘**，保持 DEFER（不以「已完成」充数）
  ⑦ 对比：产出改造前后四态分布
  ⑧ 回滚：`exempt_rollback` 还原豁免标记，四态回退
  ⑨ 分派：`backfill.run(action="exempt*")` 与 `MdCGOS.MAINTAIN_ACTIONS` 已登记

独立临时根，重跑 ≡ 首跑。
运行：python -m md_cg.test_p36_kp_align
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import backfill, crosscheck as cc, nodefile
from .mdcg import STATE_ACCEPT, STATE_BLINDSPOT, STATE_DEFER
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


SRC_BOOK = ["人教版《中外历史纲要》上册 第 3 单元"]
PH = "[历史·高中] 骨架锚点，内容待填充"


def _doc(fn, cond, sub, exe, neg="问完全无关主题"):
    return (f"# 功能名：{fn}\n# 生效条件：{cond}\n# 子功能：{sub}\n"
            f"# 执行：{exe}\n# 不适用条件：{neg}\n")


def _seed(root):
    """模拟「接线已完成、等待补证据」的迁移期现场。"""
    cg = MdCGOS(root)
    for nid, name in (("kp_a", "历史·秦朝郡县制"), ("kp_b", "历史·科举变迁"),
                      ("kp_c", "历史·市舶司")):
        cg.add(nid, _doc(name.split("·")[1], f"问{nid[-1]}", f"说明{nid}",
                         f"讲{nid}"),
               layer="knowledge", ccg_exempt=True,
               state_attributes={"name": name})
    # 已齐备（有验证方式行 + 合法基底），仅差摘豁免
    cg.add("kp_present",
           _doc("浮力计算", "问浮力", "按阿基米德原理算", "代入公式")
           .replace("# 执行：", "# 验证方式：编译器/静态检查通过\n# 执行："),
           layer="knowledge", ccg_exempt=True, verification_basis="test",
           state_attributes={"name": "数学·浮力计算"})
    # 占位空壳：不可摘（不冒充齐全）
    cg.add("kp_ph", "# 功能名：骨架节点\n\n迁移期空壳。\n", layer="knowledge",
           ccg_exempt=True,
           state_attributes={"comment": {"生效条件": [PH], "子功能": PH}})
    return cg


def _state(cg, nid, q="问主题"):
    e = cg.index["nodes"][nid]
    fm, c = cg._read(e)
    return MdCGOS.judge_qualification({"frontmatter": fm, "content": c}, q,
                                      {"query": q})["state"]


def _dist(cg, ids_, q_map=None):
    out = {}
    for nid in ids_:
        st = _state(cg, nid, (q_map or {}).get(nid, "问主题"))
        out[st] = out.get(st, 0) + 1
    return out


ALL = ["kp_a", "kp_b", "kp_c", "kp_present", "kp_ph"]
TARGETS = ["kp_a", "kp_b", "kp_c"]
#: v2 正条件确认：情境须命中节点声明的生效条件词面才可 ACCEPT
QMAP = {"kp_a": "问a", "kp_b": "问b", "kp_c": "问c", "kp_present": "问浮力"}


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="mdcg_p36_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = _seed(root)

        # 前置：豁免标记确实落到 frontmatter
        fm, _ = cg._read(cg.index["nodes"]["kp_a"])
        ok(fm.get("ccg_exempt") is True, "①豁免标记已写入 frontmatter")

        # ---------- ① 基线 ----------
        before = _dist(cg, ALL)
        ok(before.get(STATE_DEFER) == 5 and before.get(STATE_ACCEPT, 0) == 0,
           f"①基线：5 个豁免节点四态恒 DEFER（实测 {before}）")

        # ---------- ② 反证：顺序倒置更差 ----------
        bad = backfill.exempt_apply(cg, ids=["kp_a"], require_ready=False,
                                    batch="p36bad", actor="tester")
        ok(bad["written"] == 1, "②强制（跳过就绪校验）摘除成功，可复现风险路径")
        ok(_state(cg, "kp_a") == STATE_BLINDSPOT,
           "②证据未补就摘豁免 → 由 DEFER 退化为 BLINDSPOT（证明顺序不可倒置）")
        rb_bad = backfill.exempt_rollback(cg, batch="p36bad", actor="tester")
        ok(rb_bad["reverted"] == 1 and _state(cg, "kp_a") == STATE_DEFER,
           "②还原后回到 DEFER（风险路径可撤销）")

        # ---------- ③ 就绪闸门：证据没补，一个也摘不了 ----------
        p0 = backfill.exempt_plan(cg, require_ready=True)
        ok(p0["targeted"] == 1 and p0["planned_ids"] == ["kp_present"],
           f"③只列就绪节点（实测 {p0['planned_ids']}）")
        ok(p0["skipped_unready"] == 4 and p0["unready_reasons"].get("verification_basis") == 4,
           f"③未就绪 4 个，归因 verification_basis（实测 {p0['unready_reasons']}）")
        ok("ccg5" in p0["unready_reasons"], "③5 要素未齐备同样计入归因")

        # ---------- ③ 补证据（crosscheck） ----------
        verdicts = []
        for nid in TARGETS:
            verdicts += [
                {"id": nid, "unit": "reflect", "field": "验证方式",
                 "value": "据教材单元小结核对", "basis": "textbook",
                 "source": SRC_BOOK, "verdict": "accept"},
                {"id": nid, "unit": "verify", "field": "验证方式",
                 "value": "据教材单元小结核对", "verdict": "accept"},
            ]
        rep = cc.crosscheck(cg, ids=TARGETS, verdicts=verdicts, apply=True,
                            batch="p36ev", actor="tester")
        ok(rep["written"] == 3, f"③证据落库 3 个（实测 {rep['written']}）")
        for nid in TARGETS:
            fm, c = cg._read(cg.index["nodes"][nid])
            ok(nodefile.ccg_completeness(c).get("complete"),
               f"③{nid} 5 要素齐备（含验证方式行）")

        # ---------- ④ 分批摘豁免（可续跑、幂等） ----------
        p1 = backfill.exempt_plan(cg, require_ready=True, sample=2)
        ok(p1["targeted"] == 4, f"④就绪 4 个（实测 {p1['targeted']}）")
        ok(len(p1["sample"]) == 2 and all(s in p1["planned_ids"] for s in p1["sample"]),
           "④抽样接口可用（确定性样本，用于 50 节点验收）")
        b1 = backfill.exempt_apply(cg, require_ready=True, limit=2, batch="p36a",
                                   actor="tester")
        ok(b1["written"] == 2, f"④第一批摘 2 个（实测 {b1['written']}）")
        b2 = backfill.exempt_apply(cg, require_ready=True, limit=2, batch="p36a",
                                   actor="tester")
        ok(b2["written"] == 2, f"④第二批自动续（实测 {b2['written']}）")
        b3 = backfill.exempt_apply(cg, require_ready=True, limit=2, batch="p36a",
                                   actor="tester")
        ok(b3["written"] == 0 and b3["skipped_drift"] == 0,
           "④第三批无事可做（幂等，不重复摘）")

        # kp_ph 始终不可摘
        ok(_state(cg, "kp_ph") == STATE_DEFER, "⑥占位空壳始终不摘，保持 DEFER")
        fm, _ = cg._read(cg.index["nodes"]["kp_ph"])
        ok(fm.get("ccg_exempt") is True, "⑥空壳豁免标记未被误摘")

        # ---------- ⑤ 打破 DEFER 恒定 ----------
        # v2 语义：摘豁免只是解除 DEFER 短路，ACCEPT 还需情境命中正条件词面
        for nid in TARGETS:
            ok(_state(cg, nid, QMAP[nid]) == STATE_ACCEPT,
               f"⑤{nid} 摘豁免后 + 情境命中条件 → ACCEPT")
        ok(_state(cg, "kp_present", QMAP["kp_present"]) == STATE_ACCEPT,
           "⑤已齐备节点 + 情境命中条件 → ACCEPT")
        after = _dist(cg, ALL, QMAP)
        ok(after.get(STATE_ACCEPT) == 4 and after.get(STATE_DEFER) == 1,
           f"⑤术后分布 ACCEPT=4 / DEFER=1（实测 {after}）")

        # ---------- ⑦ 前后对比 ----------
        report = {"before": before, "after": after,
                  "accept_gain": after.get(STATE_ACCEPT, 0) - before.get(STATE_ACCEPT, 0),
                  "still_defer": [n for n in ALL
                                  if _state(cg, n, QMAP.get(n, "问主题")) == STATE_DEFER]}
        ok(report["accept_gain"] == 4 and report["still_defer"] == ["kp_ph"],
           f"⑦前后对比：ACCEPT +4，剩余 DEFER 仅为不可闭合项（实测 {report}）")

        # ---------- ⑧ 留痕与回滚 ----------
        h = backfill.history(cg, action="exempt", limit=100)
        ok(h["total"] >= 4 and all("exempt_before" in r for r in h["records"]),
           "⑧豁免留痕含原始标记（可反向应用）")
        # 显式点名一个未就绪节点：必须留痕，不得静默丢弃
        skip = backfill.exempt_apply(cg, ids=["kp_ph"], require_ready=True,
                                     batch="p36skip", actor="tester")
        ok(skip["written"] == 0 and skip["skipped_unready"] == 1,
           f"⑧点名未就绪节点 → 拒绝执行（实测 {skip['skipped_unready']}）")
        ok("exempt_skip" in {r.get("action") for r in
                             (backfill.history(cg, limit=200)["records"])},
           "⑧未就绪节点留 exempt_skip 记录（不静默跳过）")
        rb = backfill.exempt_rollback(cg, batch="p36a", actor="tester")
        ok(rb["reverted"] == 4, f"⑧回滚 4 条（实测 {rb['reverted']}）")
        back = _dist(cg, ALL)
        ok(back.get(STATE_DEFER) == 5 and back.get(STATE_ACCEPT, 0) == 0,
           f"⑧回滚后四态回到基线（实测 {back}）")

        # ---------- ⑨ 分派登记 ----------
        ok("exempt" in backfill.ACTIONS and "exempt" in MdCGOS.MAINTAIN_ACTIONS,
           "⑨exempt 三动作已在 ACTIONS 与 MAINTAIN_ACTIONS 登记")
        ok(all(a in MdCGOS.MAINTAIN_ACTIONS for a in backfill.ACTIONS),
           "⑨契约：backfill.ACTIONS ⊆ MAINTAIN_ACTIONS")
        r_plan = backfill.run(cg, "exempt", layer="knowledge")
        ok(r_plan["action"] == "exempt" and r_plan["dry_run"] is True,
           "⑨run(action='exempt') 默认 dry-run")
        r_hist = backfill.run(cg, "exempt_history", limit=5)
        ok(r_hist["total"] >= 4, "⑨run(action='exempt_history') 可查留痕")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nPASS={PASS} FAIL={FAIL}")
    if FAILS:
        print("FAILED:")
        for f in FAILS:
            print("  -", f)
        raise SystemExit(1)
    print("全部通过：P36 kp_ 端到端（顺序/就绪闸门/分批/四态对比/回滚）")


if __name__ == "__main__":
    main()
