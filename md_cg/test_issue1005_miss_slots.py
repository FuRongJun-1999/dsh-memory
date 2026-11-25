# -*- coding: utf-8 -*-
"""守卫 · issue #1005：槽位级「这项没材料」（miss_slots）。

病灶（测评端 2026-11-24 实测）：27/27 道真实失败题 recall 都报 `coverage_certified=True`。
现有 `anchor_missing` 要求「无词面命中 **且** 分数贴基准」，而真实失败是
「有少量词面重合、但必需要素缺失」，两个条件都不满足 ⇒ 这个信号在最该报警的地方从不报警。

本守卫钉住：
  1. query 点名的槽位在 pack 里没有证据 ⇒ miss_slots 非空（且指出是哪一项）;
  2. 材料齐备 / query 不含槽位词 ⇒ miss_slots 为空;
  3. miss_slots 与 coverage_gaps **各报各的**（弱信号不冒充缺口）;
  4. 判读合同里写明了 miss_slots 怎么读。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import coverage  # noqa: E402
from md_cg import reading_policy  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  " + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    T = tempfile.mkdtemp(prefix="miss_slots_")
    try:
        cg = MdCGOS(T, actor="t")
        for i in range(6):
            cg.add("turn_%02d" % i,
                   "# 闲聊\n我喜欢钓鱼，周末常去河边 第%d次\n" % i,
                   layer="contextual", tags=["对话"], importance=0.6)
        cg.flush()

        def call(q):
            out = cg.recall(q, budget_tokens=500, k=8)
            return out, [m.get("slot") for m in (out.get("miss_slots") or [])]

        out, slots = call("我全名咋写")
        ok(slots == ["姓名"], "M1 「我全名咋写」⇒ miss_slots=[姓名]", slots)

        out, slots = call("爸妈退休前各干什么")
        ok(set(slots) == {"父亲·职业", "母亲·职业"},
           "M2 「爸妈退休前各干什么」⇒ 拆成父亲/母亲两个子项都报（槽位整体口径会漏）", slots)

        # ===== 子项级（2026-11-25，测评端实测反馈）=====
        # 病灶：按槽位整体判时「家庭」只认「爸/妈」任一出现 ⇒ 母亲职业缺失也不报警。
        def gap_of(pack, q):
            return [g.get("slot") for g in coverage.slot_gaps(pack, q)]

        ok(gap_of([{"content": "我爸是中学教师，教了三十年"}], "爸妈退休前各干什么")
           == ["母亲·职业"],
           "M10 只有父亲的材料 ⇒ 只报母亲·职业（不因出现「妈」字就放过）")
        ok(gap_of([{"content": "我妈以前在纺织厂上班"}], "爸妈退休前各干什么")
           == ["父亲·职业"],
           "M11 只有母亲的材料 ⇒ 只报父亲·职业")
        ok(gap_of([{"content": "我爸是教师，我妈在厂里上班"}], "爸妈退休前各干什么") == [],
           "M12 父母职业都在 ⇒ 不报（防误报）")

        out, slots = call("我住哪个城市")
        ok(slots == ["城市"], "M3 「我住哪个城市」⇒ miss_slots=[城市]", slots)

        out, slots = call("我喜欢什么")
        ok(slots == [], "M4 材料里有该槽位证据 ⇒ 不报（防误报）", slots)

        out, slots = call("我们要不要重构检索")
        ok(slots == [], "M5 query 不含槽位词 ⇒ 不报", slots)

        # M6：两个信号各报各的——miss_slots 不改 coverage_gaps 的语义
        out, slots = call("我全名咋写")
        gaps_codes = [g.get("code") for g in (out.get("coverage_gaps") or [])]
        ok("miss_slots" not in gaps_codes,
           "M6 miss_slots 不冒充 coverage_gaps 条目", gaps_codes)

        # M7：判读合同写明 miss_slots 怎么读
        pol = reading_policy.TEXT
        ok("miss_slots" in pol and "不确定" in pol,
           "M7 判读合同写明「miss_slots 非空 ⇒ 先说明这一点不确定」")

        # M8：纯函数级——pack 为空时，命中槽位应报
        ok(coverage.slot_gaps([], "我全名咋写") != [],
           "M8 pack 为空且 query 命中槽位 ⇒ 照样报")
        ok(coverage.slot_gaps([], "重构检索") == [],
           "M9 pack 为空但 query 无槽位 ⇒ 不报")
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print("槽位缺口守卫：%d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())