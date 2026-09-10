# -*- coding: utf-8 -*-
"""灵枢 · 情景重构（H4 · 海马体情景记忆功能）

学海马体的情景记忆：从部分线索重建完整事件场景。
设计者定义：「情景重构 = 条件空间下的信息复原——回忆起某种情景实际上是
基于某种条件进行分析恢复，并不代表真实发生的过去就是如此。」

机制：
  1. 线索检索：片段/关键词 → 召回相关记忆节点
  2. 场景合成：沿 similar/causal 边遍历关联节点，用各节点条件空间
    （观测位置/时间窗/存在约束）拼出「重建场景」
  3. 诚实边界：输出显式标注「基于条件重构，非真实回放」（0.0.3 局部不可知
    ——重构受当前条件空间约束，可能与真实过去不同）

用法：
  python scene_reconstruction.py --query "验证"      # 重构相关情景
"""
import json
import os
import sys
import time
from typing import Dict, List


def _cs_dict(node):
    """条件空间→字典（与 pattern_separation 同一口径）。"""
    try:
        return json.loads(node.condition_space.to_json()) if node.condition_space else {}
    except Exception:
        return {}


class SceneReconstruction:
    """情景重构器：线索 → 重建场景（条件空间驱动 · 诚实标注）"""

    def __init__(self, engine):
        """情景重构器初始化（H4：重构非回放显式标注）。"""
        self.engine = engine
        self.store = engine.store

    def reconstruct(self, clue: str, depth: int = 2, max_nodes: int = 8) -> Dict:
        """从线索重建场景。返回 {scene, elements, conditions, reconstructed_note}"""
        try:
            from aeis_core import LayeredStore
        except Exception:
            return {"scene": [], "error": "no LayeredStore"}

        # 1. 线索检索：召回最相关节点
        seeds = self.store.search_content(clue, limit=4) or []
        if not seeds:
            return {"scene": [], "clue": clue,
                    "note": "无相关记忆——线索未命中任何节点（0.0.3 局部不可知）"}

        # 2. 图遍历：沿 similar/causal 边展开关联节点（条件空间驱动）
        visited = set()
        elements = []
        queue = [(n, 0, s) for n, s in seeds]

        while queue and len(elements) < max_nodes:
            node, d, sim = queue.pop(0)
            if node.id in visited:
                continue
            visited.add(node.id)
            cs = _cs_dict(node)
            elements.append({
                "node_id": node.id,
                "content": node.content[:60],
                "importance": round(node.importance, 2),
                "similarity": round(sim, 2),
                "depth": d,
                # 条件空间要素（重构的关键：每个记忆在什么条件下成立）
                "conditions": {
                    "observation_position": cs.get("observation_position", "")[:40],
                    "time_window": cs.get("time_window"),
                    "existence_constraint": cs.get("existence_constraint", "")[:60],
                },
                "tags": (node.tags or [])[:5],
            })
            if d < depth:
                try:
                    for e in self.store.get_outgoing_edges(node.id):
                        if e.relation_type.value in ("similar", "causal"):
                            tgt = self.store.get_node(e.target_id)
                            if tgt and tgt.id not in visited:
                                queue.append((tgt, d + 1, sim * 0.6))
                except Exception:
                    pass

        # 3. 场景合成：按深度排序，输出重建场景
        elements.sort(key=lambda x: x["depth"])
        scene = []
        for el in elements:
            cond = el["conditions"]["existence_constraint"]
            scene.append({
                "内容": el["content"],
                "条件": cond or "（条件未声明）",
                "观测位": el["conditions"]["observation_position"] or "（默认）",
                "置信": el["importance"],
            })

        return {
            "clue": clue,
            "scene": scene,
            "elements": len(elements),
            "conditions": self._scene_conditions(elements),
            # 诚实边界：重构 ≠ 回放（0.0.3 + 设计者定义）
            "reconstructed_note": ("基于条件空间的重构，非真实回放——"
                                   "回忆起的情景是当前条件下对记忆的分析恢复，"
                                   "不代表真实发生的过去就是如此（0.0.3 局部不可知）"),
        }

    def _scene_conditions(self, elements) -> Dict:
        """场景条件空间合成：各要素条件的并集（重构的约束框架）。"""
        positions = {}
        constraints = []
        time_windows = []
        for el in elements:
            p = el["conditions"]["observation_position"]
            if p:
                positions[p] = positions.get(p, 0) + 1
            c = el["conditions"]["existence_constraint"]
            if c and c not in constraints:
                constraints.append(c[:40])
            tw = el["conditions"]["time_window"]
            if tw and tw not in time_windows:
                time_windows.append(tw)
        return {
            "观测位置分布": positions,
            "存在约束集": constraints[:3],
            "时间窗数": len(time_windows),
        }


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from aeis_core import SpacetimeMemoryEngine

    db = os.environ.get("AEIS_DB", os.path.join("data", "lingshu.db"))
    engine = SpacetimeMemoryEngine(db_path=db, identity="灵枢", role="PRIMARY")
    sr = SceneReconstruction(engine)
    q = " ".join(sys.argv[1:]) or "验证"
    r = sr.reconstruct(q)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    engine.close()


if __name__ == "__main__":
    main()
