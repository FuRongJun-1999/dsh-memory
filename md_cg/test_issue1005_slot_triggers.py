# -*- coding: utf-8 -*-
"""守卫 · issue #1005：槽位词直取档案卡（测评端 11 道稳定失败里 7 道是槽位型提问）。

病灶：那 7 道题的问法是「我全名咋写」「爸妈退休前各干什么」「我住哪个城市」——
**不含日期/数字/专名**，所以按「实体抽取」做的缺口判据在 179 题上命中 0/179，
永远不会触发（测评端 2026-11-24 实测）。

正确形状不是「报告缺口」，而是**按槽位词直取档案卡**：命中即注入，绕过分类配额。
本守卫钉住：
  1. 槽位词命中 ⇒ `_profile_candidates` 必须返回对应卡（path=profile_slot）;
  2. 不相关查询 ⇒ 不注入（不许滥用配额）;
  3. 城市槽走 place 卡，姓名/家庭槽走 role 卡（种类不能串）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  " + str(detail)[:160]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


CARD = ("# 功能名：角色资料\n# 生效条件：t\n# 子功能：s\n# 执行：档案聚合\n"
        "# 验证方式：t\n# 不适用条件：无\n"
        "【档案】\n- 基本信息：姓名 谈书宁；年龄 34\n- 身份职业：中学教师\n"
        "- 家庭：父亲 谈国强 退休工人\n- 地点：江北区\n")
PLACE = ("# 功能名：地点资料\n# 生效条件：t\n# 子功能：s\n# 执行：档案聚合\n"
         "# 验证方式：t\n# 不适用条件：无\n【档案】江北区\n")


def main():
    T = tempfile.mkdtemp(prefix="slot_guard_")
    try:
        cg = MdCGOS(T, actor="t")
        cg.add("profile-role-谈书宁", CARD, layer="knowledge",
               tags=["profile", "role:谈书宁"], importance=0.9)
        cg.add("profile-place-江北区", PLACE, layer="knowledge",
               tags=["profile", "place:江北区"], importance=0.9)
        cg.flush()

        def hit(q):
            got = cg._profile_candidates(q)
            return [g[0].get("id") for g in got], [g[2].get("path") for g in got]

        ids, paths = hit("我全名咋写")
        ok(any(str(i).startswith("profile-role-") for i in ids) and "profile_slot" in paths,
           "S1 姓名槽（我全名咋写）⇒ 注入角色卡", (ids, paths))

        ids, paths = hit("爸妈退休前各干什么")
        ok(any(str(i).startswith("profile-role-") for i in ids),
           "S2 家庭/职业槽（爸妈退休前各干什么，无自指词）⇒ 注入角色卡", (ids, paths))

        ids, paths = hit("我住哪个城市")
        ok(any(str(i).startswith("profile-") for i in ids),
           "S3 城市槽（我住哪个城市）⇒ 注入地点/角色卡", (ids, paths))

        ids, _ = hit("今天天气怎么样")
        ok(not ids, "S4 反例：无关查询不注入（不许滥用配额）", ids)

        ids, _ = hit("我们要不要重构检索")
        ok(not ids, "S5 反例：工程话题不注入", ids)

        ids, paths = hit("我的全名到底是啥来着")
        ok("profile_slot" in paths,
           "S6 换一种问法（到底是啥来着）仍命中", (ids, paths))

        # ===== 二次修正（2026-11-24，测评端带卡复测：救 3 赔 17）=====
        # 槽位卡必须**不参与常规名额**：从候选池剔除 → 装包后按独立配额追加。
        T2 = tempfile.mkdtemp(prefix="slot_quota_")
        try:
            cg2 = MdCGOS(T2, actor="t")
            cg2.add("profile-role-谈书宁", CARD, layer="knowledge",
                    tags=["profile", "role:谈书宁"], importance=0.9)
            for i in range(12):
                cg2.add("turn_%02d" % i,
                        "# 对话\n我学历的事你再问问我 第%d次 机械 修伞\n" % i,
                        layer="contextual", tags=["对话"], importance=0.5)
            cg2.flush()

            def run(cap, q="我的学历是什么"):
                old_cap = os.environ.get("MDCG_SLOT_CARDS")
                os.environ["MDCG_SLOT_CARDS"] = cap
                try:
                    out = cg2.recall(q, budget_tokens=500, k=10)
                finally:
                    if old_cap is None:
                        os.environ.pop("MDCG_SLOT_CARDS", None)
                    else:
                        os.environ["MDCG_SLOT_CARDS"] = old_cap
                ids = [e.get("id") for e in out.get("pack") or []]
                return out.get("meta", {}), ids

            meta_on, ids_on = run("2")
            meta_off, ids_off = run("0")
            ok(meta_on.get("slot_cards_added", 0) >= 1,
               "Q1 槽位命中时卡走追加通道（slot_cards_added>=1）", meta_on)
            turns_on = [i for i in ids_on if str(i).startswith("turn_")]
            turns_off = [i for i in ids_off if str(i).startswith("turn_")]
            ok(len(turns_on) >= len(turns_off),
               "Q2 原话条数不因卡而减少（配额外）", (len(turns_on), len(turns_off)))
            ok(not str(ids_on[0]).startswith("profile-") if ids_on else True,
               "Q3 卡不占前段名次（原话优先）", ids_on[:3])
        finally:
            shutil.rmtree(T2, ignore_errors=True)
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print("槽位触发守卫：%d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())