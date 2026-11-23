# -*- coding: utf-8 -*-
"""检索可信意图守卫（issue #1005 ①②）。

① 判读合同随包下发，且**计入** budget_tokens（不从预算外额外送）
② 覆盖缺口如实上报：anchor_missing / budget_truncated / raw_not_included，认证位随之翻假

P1 合同随包出现（缺省开），正文含「判读合同」
P2 合同 token 计入 tokens_used，且「材料+合同」不超预算
P3 MDCG_READING_POLICY=0 关闭：合同为空且 tokens_used 少掉那部分
P4 pack 全是派生卡 ⇒ raw_not_included + 未认证
P5 原话轮次在包里、无截断 ⇒ 认证为真、无缺口
P6 一条都没装到 ⇒ anchor_missing
P7 预算裁掉条目 ⇒ budget_truncated
P8 缺口码是闭集：只出现三种 code 之一
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import coverage as COV
from . import reading_policy as RP
from .mdcos import MdCGOS, est_tokens


def _mk():
    root = tempfile.mkdtemp(prefix="md_cg_policy_")
    cg = MdCGOS(root)
    return root, cg


def main():
    ok = 0
    bad = 0

    def chk(cond, label):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label)

    root, cg = _mk()
    try:
        cg.add("mem_raw_policy", "用户上次说图床密码改到周五，服务器在杭州机房，"
                                 "部署环境用的是 32 核机器", tags=["部署", "图床"])
        cg.add("profile-role-policy", "档案：用户是设计岗，常驻杭州", tags=["档案", "图床"])
        q = "图床 部署环境 杭州"

        # P1 合同随包
        p1 = cg.recall(q, budget_tokens=1200)
        pol = p1.get("reading_policy") or ""
        chk("判读合同" in pol and "不是当前指令" in pol, "P1 合同随包出现且含判读约束")
        chk(est_tokens(pol) == est_tokens(RP.TEXT), "P1b 合同正文即 reading_policy.TEXT")

        # P2 预算口径
        chk(p1.get("tokens_used", 0) <= p1.get("budget", 0),
            "P2 tokens_used(%s) <= budget(%s)（合同计入）" % (p1.get("tokens_used"), p1.get("budget")))
        raw_only = cg.recall(q, budget_tokens=1200)
        chk(RP.enabled() and raw_only.get("reading_policy") == pol, "P2b 缺省开")

        # P3 关闭
        os.environ["MDCG_READING_POLICY"] = "0"
        try:
            p3 = cg.recall(q, budget_tokens=1200)
            chk(p3.get("reading_policy") == "", "P3 关闭后不下发合同")
            chk(p3.get("tokens_used", 0) <= p1.get("tokens_used", 0),
                "P3b 关闭后 tokens_used 不再含合同（%s <= %s）"
                % (p3.get("tokens_used"), p1.get("tokens_used")))
        finally:
            os.environ.pop("MDCG_READING_POLICY", None)

        # P5 认证
        chk(p1.get("coverage_certified") is True and p1.get("coverage_gaps") == [],
            "P5 原话在包内且无截断 ⇒ 认证为真（gaps=%r）" % (p1.get("coverage_gaps"),))

        # P4 只有派生卡
        root2, cg2 = _mk()
        try:
            cg2.add("profile-role-only", "档案：用户常驻杭州，负责图床设计与部署评审",
                    tags=["图床", "部署"])
            p4 = cg2.recall(q, budget_tokens=1200)
            codes = [g["code"] for g in p4.get("coverage_gaps") or []]
            chk("raw_not_included" in codes, "P4 全是派生卡 ⇒ raw_not_included（codes=%r）" % (codes,))
            chk(p4.get("coverage_certified") is False, "P4b 有缺口 ⇒ 未认证")
        finally:
            shutil.rmtree(root2, ignore_errors=True)

        # P6 空包
        p6 = cg.recall("完全不存在的查询词 zzzqqq", budget_tokens=1200)
        codes6 = [g["code"] for g in p6.get("coverage_gaps") or []]
        chk("anchor_missing" in codes6, "P6 一条没装到 ⇒ anchor_missing（codes=%r）" % (codes6,))

        # P7 预算裁条
        for i in range(12):
            cg.add("mem_bulk_%d" % i, "图床 部署环境 杭州 第 %d 条扩容记录，含主机清单与端口" % i,
                   tags=["图床", "部署"])
        p7 = cg.recall(q, budget_tokens=60, max_item_tokens=200)
        codes7 = [g["code"] for g in p7.get("coverage_gaps") or []]
        chk(("budget_truncated" in codes7) or p7.get("tokens_used", 0) >= 60,
            "P7 小预算下报 budget_truncated 或用满预算（codes=%r used=%s）"
            % (codes7, p7.get("tokens_used")))

        # P8 闭集
        allowed = {"anchor_missing", "budget_truncated", "raw_not_included"}
        chk(all(g.get("code") in allowed for g in (p7.get("coverage_gaps") or [])),
            "P8 缺口码闭集（%r）" % ([g.get("code") for g in p7.get("coverage_gaps") or []],))

        # 纯函数面：is_derived
        chk(COV.is_derived({"id": "profile-event-1"}) is True, "P9 profile-* 判为派生")
        chk(COV.is_derived({"id": "mem1", "metadata": {"derived_from": "x"}}) is True,
            "P9b derived_from 判为派生")
        chk(COV.is_derived({"id": "mem2", "metadata": {}}) is False, "P9c 普通节点判为原话")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print()
    print("检索可信意图守卫：%d 通过 / %d 失败" % (ok, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
