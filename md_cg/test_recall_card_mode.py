# -*- coding: utf-8 -*-
"""标题卡模式守卫（issue #1005 补充①，测评端 2026-11-22 复测）。

【守什么】
测评端四臂复测：memu-memory（BM25 主序）19/22，灵枢 18/22；差值集中在 F3 时间题与
F5 自我一致。F5 的解释是「它的 name/id/tag 只有标题卡进候选，正文在抽屉里——同样预算
能铺开更多候选；灵枢的 pack 是正文直铺，预算先被长材料吃满」。
→ 要一个 card_mode：pack 只给定位信息，正文按需二次取；**同一预算条目数应显著上升**。

判据：
  C1 缺省关：card_mode=False 时 pack 无 card 标、正文原样
  C2 开启：每条 pack 条目 card=True，content 是卡（不含正文全文），tokens 小于原正文
  C3 同一预算下条目数**严格增加**（这是这条改动的全部意义）
  C4 卡里带得回去：含 node_id 取用提示；标签与日期在卡上（不丢失定位信息）
  C5 卡的 token 计入预算：tokens_used = 卡 token 之和 + 判读合同（#1005 ①②）
  C6 不改检索：卡模式前后 pack 的 id 序列相同（只换呈现，不换召回）

运行：python -X utf8 -m md_cg.test_recall_card_mode
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGOS, est_tokens


TOPICS = [
    "检索面的预算争用：长材料先把预算吃满，后面的条目就进不来了。",
    "判读合同要贴着材料下发，否则模型会把助手的猜测当成使用者的陈述。",
    "覆盖缺口只说装包结果能证明的事，不做额外检索也不读盘。",
    "标题卡把正文挪到二次取用，同一预算能铺开更多候选。",
    "时间路的日期加成必须有单一常量表，散落各处必然漂移。",
    "写入闸门与召回折叠要共用一份阈值，否则两侧互相打架。",
]


class CardModeTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cg_card_")
        self.cg = MdCGOS(self.root)
        for i, topic in enumerate(TOPICS):
            body = topic + "这一段展开写长一些，用来模拟真实记忆里被长材料吃满预算的情形。" * 8
            self.cg.add("n%d" % i, body, layer="knowledge",
                        tags=["检索", "预算", "卡"], source="session:card")
        self.query = "检索 预算 标题卡"

    def _ids(self, out):
        return [p["id"] for p in out["pack"]]

    def test_c1_default_unchanged(self):
        out = self.cg.recall(self.query, budget_tokens=1200)
        self.assertTrue(out["pack"])
        for p in out["pack"]:
            self.assertNotIn("card", p)
            self.assertNotIn("【卡】", p["content"])

    def test_c2_card_shape(self):
        base = self.cg.recall(self.query, budget_tokens=1200)
        out = self.cg.recall(self.query, budget_tokens=1200, card_mode=True)
        self.assertTrue(out["pack"], "卡模式下 pack 不应为空")
        for p in out["pack"]:
            self.assertTrue(p.get("card"))
            self.assertIn("【卡】", p["content"])
            self.assertLess(p["tokens"], 60, "卡应当很短（原正文远超此值）")
        # C6：只换呈现，不换召回——卡模式装到的那几条，顺序与基础模式一致
        n = min(len(base["pack"]), len(out["pack"]))
        self.assertEqual(self._ids(out)[:n], self._ids(base)[:n])

    def test_c3_more_entries_same_budget(self):
        # 预算要够摊开判读合同（#1005 ①② 的 196 token 也计在预算内）：
        # 200/260 这种小预算里合同先吃掉大半，卡模式的优势体现不出来——
        # 实测 b=200 两者都只装 1 条；b=400 起差值才是这条改动的真实收益。
        budget = 400
        base = self.cg.recall(self.query, budget_tokens=budget)
        card = self.cg.recall(self.query, budget_tokens=budget, card_mode=True)
        self.assertGreater(len(card["pack"]), len(base["pack"]),
                           "同一预算下卡模式必须装进更多条目（%d vs %d）"
                           % (len(card["pack"]), len(base["pack"])))
        self.assertLessEqual(card["tokens_used"], budget)

    def test_c4_card_carries_locators(self):
        out = self.cg.recall(self.query, budget_tokens=1200, card_mode=True)
        p = out["pack"][0]
        self.assertIn(p["id"], p["content"])
        self.assertIn("标签", p["content"])
        self.assertIn("cg(op=get", p["content"])

    def test_c5_tokens_counted(self):
        out = self.cg.recall(self.query, budget_tokens=400, card_mode=True)
        self.assertLessEqual(out["tokens_used"], out["budget"])
        self.assertEqual(out["tokens_used"],
                         sum(p["tokens"] for p in out["pack"])
                         + est_tokens(out.get("reading_policy") or ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)