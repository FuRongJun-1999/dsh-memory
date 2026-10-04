# -*- coding: utf-8 -*-
"""test_ghostref · 幽灵引用检查器（A2）：短语层标记 + id 层降级告警（不拒收）。

多主体世界模型对齐 v0.1 §2 L1「转引不得升级」的行为守卫。
运行：python -m md_cg.test_ghostref
"""
from __future__ import annotations

import os
import tempfile
import time

from . import branches, ghostref, nodefile
from .mdcos import MdCGOS
from .writepipe import default_pipeline

_ok = 0
_fail = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[ok] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


H = ("# 功能名：幽灵引用守卫\n# 生效条件：测试环境\n# 子功能：无\n"
     "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n")
URF = nodefile.UNCERTAIN_REFS_FIELD


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_ghost_test_")
    cg = MdCGOS(os.path.join(tmp, "root"))
    pipe = default_pipeline()

    def W(nid, body, **kw):
        a = {"op": "write", "node_id": nid, "content": H + body + "\n",
             "layer": "knowledge", "content_kind": "text",
             "verification_basis": "test"}
        a.update(kw)
        return pipe.execute(cg, a)

    def FM(nid):
        return ((cg.get(nid) or {}).get("frontmatter")) or {}

    # ---- 1. 短语层：无可解析出处 ⇒ 标记；**不拒收** ----
    out1 = W("ghp_one", "可以允许你在帐篷里点那根你上次买的香薰蜡烛。")
    check("T1a 幽灵回指仍落盘（不拒收）", out1.get("committed") is True,
          {k: out1.get(k) for k in ("ok", "committed", "moved_to")})
    _refs1 = FM("ghp_one").get(URF) or []
    check("T1b 短语标记落 fm（上次买）", "上次买" in _refs1, _refs1)
    check("T1c 出口带 ghost_refs 告警",
          bool(out1.get("ghost_refs")) and "上次买" in out1["ghost_refs"],
          out1.get("ghost_refs"))

    # ---- 2. 有出处（句内含库内 id）⇒ 不标记 ----
    W("base_node", "集市采购的凭证记录。")
    out2 = W("ghp_two", "上次说的那件事，见 base_node 的记载。")
    check("T2a 有出处的回指不落标记",
          URF not in FM("ghp_two"), FM("ghp_two").get(URF))
    check("T2b 有出处的回指建 reference 边",
          any(e.get("target") == "base_node" for e in (FM("ghp_two").get("edges") or [])),
          FM("ghp_two").get("edges"))
    check("T2c 出口无 ghost_refs", not out2.get("ghost_refs"), out2.get("ghost_refs"))

    # ---- 3. 无回指短语 ⇒ 不标记（对照）----
    out3 = W("ghp_three", "集市购物，周末进行。")
    check("T3a 无短语不落标记", URF not in FM("ghp_three"), FM("ghp_three").get(URF))
    # 2026-10-05 复核实证：T3 在「写入被拒」时会假通过（无标记≠已落盘）——
    # 补 committed 断言把「对照场景确实落盘」钉住。
    check("T3b 对照场景确实落盘", out3.get("committed") is True,
          out3.get("committed"))

    # ---- 4. 幽灵 id（句内 id 形态但不在库）⇒ 无出处 ⇒ 标记 ----
    W("ghp_four", "参照 ghost_absent 那条记载，明明讲过。")
    _refs4 = FM("ghp_four").get(URF) or []
    check("T4a 幽灵 id 句仍标记（明明讲过）", "明明讲过" in _refs4, _refs4)
    check("T4b 幽灵 id 不建边", not (FM("ghp_four").get("edges") or []),
          FM("ghp_four").get("edges"))

    # ---- 5. id 层：目标晚于自身 ⇒ 降级告警（不拒收）----
    W("late_target", "晚出现的凭证节点。")
    out5 = W("late_src", "依据见 late_target 记载。",
             valid_from=time.time() - 100000)
    check("T5a 目标晚于自身仍落盘（不拒收）", out5.get("committed") is True,
          out5.get("committed"))
    _lr = out5.get("late_refs") or []
    check("T5b 降级告警点名目标",
          len(_lr) == 1 and _lr[0].get("target") == "late_target", _lr)

    # ---- 6. 正常时序 ⇒ 无告警（对照）----
    out6 = W("ok_src", "依据见 late_target 记载。",
             valid_from=time.time() + 100)
    check("T6a 正常时序无告警", not out6.get("late_refs"), out6.get("late_refs"))
    check("T6b 对照场景确实落盘", out6.get("committed") is True,
          out6.get("committed"))

    # ---- 7. opt-out（ghostref=False）⇒ 不标记 ----
    out7 = W("ghp_opt", "上次说的事。", ghostref=False)
    check("T7a opt-out 仍落盘", out7.get("committed") is True, out7.get("committed"))
    check("T7b opt-out 不落标记", URF not in FM("ghp_opt"),
          FM("ghp_opt").get(URF))

    # ---- 8. add 层：显式落键 / 覆写不继承 / 非法拒（直调，不经写链）----
    cg.add("ghp_eight", H + "上次说的那件事。\n", layer="knowledge",
           verification_basis="test", uncertain_refs=["上次说", "之前说"])
    check("T8a 显式落键", FM("ghp_eight").get(URF) == ["上次说", "之前说"],
          FM("ghp_eight").get(URF))
    cg.add("ghp_eight", H + "改写后的干净正文。\n", layer="knowledge",
           verification_basis="test")
    check("T8b 覆写不继承（正文属性重算）", URF not in FM("ghp_eight"),
          FM("ghp_eight").get(URF))
    try:
        cg.add("ghp_bad", H + "正文。\n", layer="knowledge",
               verification_basis="test", uncertain_refs="上次的")
        check("T8c 非法类型拒绝", False, "未抛 ValueError")
    except ValueError:
        check("T8c 非法类型拒绝", True)

    # ---- 9. fork 副本携带标记 ----
    r9 = branches.fork(cg, ["ghp_one"], branch_id="br_ghost")
    _bid = (r9.get("forked") or [{}])[0].get("to")
    check("T9a fork 成功", bool(r9.get("ok")) and bool(_bid), r9)
    check("T9b 副本携带标记", (_bid and FM(_bid).get(URF) == FM("ghp_one").get(URF)),
          (_bid, FM(_bid).get(URF) if _bid else None))

    # ---- 11. rewrite 按新正文重算标记（复核 yellow-1 修）----
    # 副本 ghp_one@br_ghost 有标记 ["上次买"]（T1/ fork 携带）：
    # 改成干净正文 → 标记消失；改回幽灵正文 → 标记出现（双向，非「清空」）。
    rr1 = branches.rewrite(cg, _bid, H + "改写为干净正文。\n")
    check("T11a rewrite 成功", rr1.get("ok") is True, rr1)
    check("T11b rewrite 干净正文 → 标记重算消失", URF not in FM(_bid),
          FM(_bid).get(URF))
    rr2 = branches.rewrite(cg, _bid, H + "之前说的那件事。\n")
    check("T11c rewrite 幽灵正文 → 标记重算出现",
          "之前说" in (FM(_bid).get(URF) or []), FM(_bid).get(URF))

    # ---- 12. merge 回主支按分支正文重算（复核 yellow-2① 修）----
    # 主支幽灵正文 → fork → rewrite 分支为干净 → merge 回主支 → 主支标记消失。
    W("ghp_merge", "明明讲过的那件事。")
    check("T12a 主支初始有标记", "明明讲过" in (FM("ghp_merge").get(URF) or []),
          FM("ghp_merge").get(URF))
    r12 = branches.fork(cg, ["ghp_merge"], branch_id="br_mg")
    _bid12 = (r12.get("forked") or [{}])[0].get("to")
    branches.rewrite(cg, _bid12, H + "干净正文（无回指）。\n")
    rm = branches.merge(cg, "br_mg")
    check("T12b merge 成功", rm.get("ok") is True, rm)
    check("T12c 主支标记按分支正文重算（消失）", URF not in FM("ghp_merge"),
          FM("ghp_merge").get(URF))
    # 反方向（2026-10-05 自证补）：干净主支 → 分支改幽灵 → merge 回写 ⇒ 主支
    # 标记应**出现**——「消失」方向抓「携带旧值」，「出现」方向抓「置空不重算」。
    W("ghp_merge2", "干净正文示例。")
    r13 = branches.fork(cg, ["ghp_merge2"], branch_id="br_mg2")
    _bid13 = (r13.get("forked") or [{}])[0].get("to")
    branches.rewrite(cg, _bid13, H + "上次说的那件事。\n")
    branches.merge(cg, "br_mg2")
    check("T12d 主支标记按分支正文重算（出现）",
          "上次说" in (FM("ghp_merge2").get(URF) or []),
          FM("ghp_merge2").get(URF))

    # ---- 10. 纯函数级：短语去重保序 + late_targets 边界 ----
    # 「上次说的那件」只命中「上次说」——「上次的」要求连续子串（说/的 之间
    # 不跳字）；命中去重后跨句保序。
    _pf = ghostref.find_ghost_phrases("上次说的事；上次说的那件；之前说的那批。")
    check("T10a 短语去重保序", _pf == ["上次说", "之前说"], _pf)
    check("T10b late_targets 无 own_from 直接空",
          ghostref.late_targets(cg, ["late_target"], None) == [])
    check("T10c late_targets 非数 own_from 空",
          ghostref.late_targets(cg, ["late_target"], "昨天") == [])

    print("\ntest_ghostref: %d 通过 / %d 失败" % (_ok, len(_fail)))
    if _fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
