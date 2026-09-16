# -*- coding: utf-8 -*-
"""记忆评审流水线（M1 机械层 / M2 蜂巢并发 / M3 定位）。

真源：docs/记忆评审系统_立项设计与施工交接_20260915.md §3 / §5 / §6。

    [1 候选生成] → [2 捆绑] → [3 规则装配] → [4 蜂巢评审] → [5 落库治理]
      确定性        确定性       确定性        LLM(M2)       确定性(M4)

* candidates.py 级 1：四源候选（断言超限 / 闸门 DEFER / 冷节点 / 轮巡）
* bundle.py     级 2：按模板签名/血缘/主题捆绑（同模板组一包一评）
* ruleset.py    级 3：D3 规则装配（规则全落 rules/*.json，引擎零改动）
* pipeline.py   M2 级 4+5：投递收卷（蜂巢）+ 意见落库（verify 令牌 + writepipe）
* locate.py     M3 D1：字段级定位——意见说「有问题」，定位说「在第几个字段/哪一段」

边界：M1/M3 只读不写；机械可算的在蜂巢 job 前跑完（LLM 只看语义问题）；
本条流水线不产出「删除」动作（治理只有合并/降权/回填/移层，M4 终裁）。
"""

__all__ = ["candidates", "bundle", "ruleset", "pipeline", "locate", "SPEC_VERSION"]

SPEC_VERSION = 1
