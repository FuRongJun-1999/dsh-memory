# -*- coding: utf-8 -*-
"""route_memory · 第三层路由：对话集经验复用（记忆驱动 = 技能形成）
================================================================================
荣终裁（2026-08-20）：第三个路由方法是对话集——过去有人问过类似问题，
寻路方式是怎样。这是形成长期记忆/技能。加入后 = 与灵枢长期记忆联动，
白箱彻底绑定灵枢。

设计（慎重考虑 · 防固化错误路径）：
  记录：每次查询 → 路径链（top 卡）→ 验证结果 → 入经验库
  召回：相似问题 → 已验证路径 → 优先导航（三重验证门控）
  技能：高频成功路径 → 提升为技能卡（协议 P1-3）

三重验证门控（缺一不可）：
  ① 路径已验证：该链曾产生正确答案（验证单元确认）
  ② 未过时：链上节点仍存在（图谱未大改）
  ③ 条件空间一致：问题 Q 与历史 Q' 条件空间声明一致（相似度阈值）

存储：本地 JSON（经验库）+ 可选灵枢记忆联动（白箱绑定灵枢）。

用法：:
    from route_memory import RouteMemory
    rm = RouteMemory()
    rm.record(q, top_cards, verified=True)     # 记录寻路路径
    hit = rm.recall(q, threshold=0.8)          # 相似问题 → 历史路径
    skills = rm.top_skills()                    # 高频成功路径 = 技能
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "route_memory.json")


class RouteMemory:
    """对话集经验路由：历史寻路路径记录 + 召回 + 验证门控。"""

    def __init__(self, path: str = DEFAULT_PATH, max_entries: int = 5000):
        """路由记忆初始化：持久文件存在则恢复既有条目。"""
        self.path = path
        self.max_entries = max_entries
        self._entries = []      # [{q, q_fp, chain, verified, count, ts}]
        self._load()

    # ---------------- 存储 ----------------

    def _load(self) -> None:
        """从 JSON 文件读回历史路由记忆（缺失视为空白）。"""
        try:
            if os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as f:
                    self._entries = json.load(f)
        except Exception:
            self._entries = []

    def _save(self) -> None:
        """路由记忆写回 JSON 文件（原子覆盖）。"""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True) \
                if os.path.dirname(self.path) else None
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._entries[-self.max_entries:], f,
                          ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ---------------- 记录（寻路路径入经验库） ----------------

    def record(self, question: str, chain: list, verified: bool = True,
               focus: str = "") -> dict:
        """记录一次查询的寻路路径。

        question: 原始问题
        chain: 路径链（top 卡名列表，如 ["初中数学", "三角形"]）
        verified: 该路径是否验证过（答案正确=验证单元确认）
        focus: 问题焦点（可空，用于相似度辅助）
        """
        # 去重：同问题已记录 → 更新计数/验证状态
        for e in self._entries:
            if e.get("q") == question:
                e["count"] = e.get("count", 0) + 1
                e["verified"] = e["verified"] and verified
                e["ts"] = time.time()
                if focus:
                    e["focus"] = focus
                self._save()
                return {"status": "updated", "count": e["count"]}
        self._entries.append({
            "q": question, "chain": chain, "verified": bool(verified),
            "count": 1, "ts": time.time(), "focus": focus or "",
        })
        # 语义向量（荣：在可能的语义中匹配——路由依据是语义不是切片）
        try:
            from neural_retrieve import NeuralRetriever
            nr = NeuralRetriever()
            qv = nr.embed(question)
            if qv is not None:
                self._entries[-1]["qvec"] = [
                    round(float(x), 6) for x in qv.tolist()]
        except Exception:
            pass
        # 条件空间绑定（v1.20 · 荣：技能附带条件，不会在不适合的条件下
        # 出现——防题库过拟合。记录问题所属学科域，召回时校验一致：
        # 「什么是函数？」（数学）和「什么是函数呀」（编程）语义相似
        # 但条件空间不同，经验不可互用）
        try:
            from semantic_translate import classify_condition_space
            _cs = classify_condition_space(question)
            if _cs.get("nav"):
                self._entries[-1]["cond_space"] = _cs["domain"]
        except Exception:
            pass
        self._save()
        return {"status": "recorded", "count": 1}

    # ---------------- 召回（相似问题 → 历史路径） ----------------

    @staticmethod
    def _key_terms(text: str) -> set:
        """提取问题关键词集合（降级路由用，bge 不可用时兜底）：
        仅 3-4 字实义词（「勾股定理/圆的周长」），去疑问词/虚词。
        不用 2 字全窗口——碎片词稀释 Jaccard 相似度（荣：不随意切片，
        语义匹配为主，此处仅作 bge 不可用时的保守降级）。
        """
        try:
            import re as _re
            chars = [c for c in text if "\u4e00" <= c <= "\u9fff"]
            terms = set()
            for L in (4, 3):
                for i in range(len(chars) - L + 1):
                    w = "".join(chars[i:i + L])
                    if any(s in w for s in ("是什么", "怎么", "多少", "为什么",
                                            "公式", "内容", "定义", "关系",
                                            "分别是", "之间的", "多少个")):
                        continue
                    terms.add(w)
            return terms
        except Exception:
            return set()

    def recall(self, question: str, threshold: float = 0.55,
               max_results: int = 3) -> list:
        """语义召回相似问题的历史路径（第三层路由核心）。

        荣：不随意对句子切片，而在可能的语义中匹配——用 bge 语义向量
        余弦（「勾股定理的内容是什么？」vs「什么是勾股定理？」语义相同、
        字面不同 → 语义余弦正确匹配，切片 Jaccard 会漏）。
        优先级：已验证路径 > 相似度 > 使用次数。
        返回 [{q, chain, verified, count, similarity}]
        """
        if not question or not self._entries:
            return []
        # 当前问题条件空间（校验用——技能附带条件，不在不适合的条件下出现）
        _cur_cond = None
        try:
            from semantic_translate import classify_condition_space
            _cs = classify_condition_space(question)
            if _cs.get("nav"):
                _cur_cond = _cs["domain"]
        except Exception:
            _cur_cond = None
        # 语义匹配（主路径）
        try:
            import numpy as np
            from neural_retrieve import NeuralRetriever
            nr = NeuralRetriever()
            qv = nr.embed(question)
            if qv is not None:
                qn = qv / max(float(np.linalg.norm(qv)), 1e-9)
                scored = []
                for e in self._entries:
                    ev = e.get("qvec")
                    if not ev:
                        continue
                    # 条件空间一致性（v1.20 防过拟合）：历史问题的条件空间
                    # 与当前不一致 → 不召回（「什么是函数？」数学 vs
                    # 「什么是函数呀」编程——语义相似但经验不可互用）
                    hist_cond = e.get("cond_space")
                    if hist_cond and _cur_cond and hist_cond != _cur_cond:
                        continue
                    evn = np.asarray(ev, dtype=np.float32)
                    norm = float(np.linalg.norm(evn))
                    if norm < 1e-9:
                        continue
                    sim = float(np.dot(qn, evn / norm))
                    if sim >= threshold:
                        scored.append({"q": e.get("q"),
                                       "chain": e.get("chain", []),
                                       "verified": e.get("verified", False),
                                       "count": e.get("count", 1),
                                       "cond_space": hist_cond,
                                       "similarity": round(sim, 3)})
                scored.sort(key=lambda x: (-x["verified"], -x["similarity"],
                                           -x["count"]))
                return scored[:max_results]
        except Exception:
            pass
        # 降级：bge 不可用 → 关键词 Jaccard（保守）
        try:
            tq = self._key_terms(question)
            if not tq:
                return []
            scored = []
            for e in self._entries:
                te = self._key_terms(e.get("q", ""))
                inter = tq & te
                if not inter:
                    continue
                sim = len(inter) / max(1, min(len(tq), len(te)))
                if sim >= threshold:
                    scored.append({"q": e.get("q"), "chain": e.get("chain", []),
                                   "verified": e.get("verified", False),
                                   "count": e.get("count", 1),
                                   "similarity": round(sim, 3)})
            scored.sort(key=lambda x: (-x["verified"], -x["similarity"],
                                       -x["count"]))
            return scored[:max_results]
        except Exception:
            return []

    # ---------------- 技能形成（高频成功路径） ----------------

    def top_skills(self, min_count: int = 3, top: int = 10) -> list:
        """高频已验证路径 = 技能卡（协议 P1-3 技能获取）。

        条件：verified + count ≥ min_count（重复成功 = 可靠经验）。
        """
        skills = [e for e in self._entries
                  if e.get("verified") and e.get("count", 0) >= min_count]
        skills.sort(key=lambda x: -x.get("count", 0))
        return skills[:top]

    # ---------------- 状态 ----------------

    def info(self) -> dict:
        """路由记忆概况：总条数/已验证数/持久化路径。"""
        verified = sum(1 for e in self._entries if e.get("verified"))
        return {"entries": len(self._entries), "verified": verified,
                "path": self.path}

    def clear(self) -> None:
        """清空全部路由记忆并立即保存。"""
        self._entries = []
        self._save()
