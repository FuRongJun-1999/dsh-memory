# -*- coding: utf-8 -*-
"""灵枢 · 模式分离（H3 · 海马体齿状回功能）

学海马体齿状回：把相似的经验编码成**不同的表征**，防检索混淆。
工程映射：相似节点对（高内容相似）→ 提取条件空间差异 → 显式化。

机制：
  1. 扫描相似节点对（内容二元组相似度 ≥ 阈值 且 非相同节点）
  2. 逐字段对比条件空间（观测位置/观测工具/时间窗/存在约束 + edu_level）
  3. 提取「区分维度」：差异字段列表 + 差异描述
  4. 建立/更新分离边：similar 边 + separation 标签 + 差异注记（note）
  5. 检索时：命中相似节点时显式提示「这两个的区别在 XXX」

用法：
  python pattern_separation.py --scan        # 全库扫描建分离边
  python pattern_separation.py --query 物理   # 检索时带分离提示
"""
import json
import os
import sys
import time

SIM_THRESHOLD = 0.10     # 内容相似度阈值（灵枢记忆库感知节点间较高）
SEP_EDGE_TAG = "separation"

CS_FIELDS = ("observation_position", "observation_tool",
             "existence_constraint")
SA_FIELDS = ("edu_level", "domain", "kind", "source")


def _cs_dict(node):
    """条件空间对象→可序列化字典（观测位·工具·时间窗·存在约束）。"""
    try:
        return json.loads(node.condition_space.to_json()) if node.condition_space else {}
    except Exception:
        return {}


def _tag_diff(a_node, b_node, max_show=4):
    """标签差异：A 独有的标签（区分维度最可靠）。"""
    ta = set(a_node.tags or [])
    tb = set(b_node.tags or [])
    a_only = sorted(ta - tb)[:max_show]
    b_only = sorted(tb - ta)[:max_show]
    if not a_only and not b_only:
        return None
    parts = []
    if a_only:
        parts.append(f"A 独有标签:{'、'.join(a_only)}")
    if b_only:
        parts.append(f"B 独有标签:{'、'.join(b_only)}")
    return "；".join(parts)


def separation_note(a_name, b_name, a_node, b_node):
    """提取 A vs B 的差异，返回差异注记（区分维度列表）。
    维度：条件空间字段 → 状态属性 → 标签差异（最可靠）。"""
    ca = _cs_dict(a_node)
    cb = _cs_dict(b_node)
    sa = a_node.state_attributes or {}
    sb = b_node.state_attributes or {}
    diffs = []
    for f in CS_FIELDS:
        va = str(ca.get(f, ""))
        vb = str(cb.get(f, ""))
        if va != vb and va.strip() and vb.strip():
            diffs.append(f"{f}:「{va[:30]}」vs「{vb[:30]}」")
    for f in SA_FIELDS:
        va = str(sa.get(f, ""))
        vb = str(sb.get(f, ""))
        if va != vb and va.strip() and vb.strip():
            diffs.append(f"{f}: {va} vs {vb}")
    tag_diff = _tag_diff(a_node, b_node)
    if tag_diff:
        diffs.append(tag_diff)
    if not diffs:
        return None, []
    note = "模式分离：" + "；".join(diffs)
    return note, diffs


class PatternSeparation:
    """模式分离器：相似节点对 → 分离边（条件差异显式化）"""

    def __init__(self, engine):
        """模式分离器初始化：挂载灵枢引擎引用。"""
        self.engine = engine
        self.store = engine.store

    def scan(self, limit=200, tag_only=False):
        """扫描相似节点对，建立分离边（similar + 差异注记）。
        参与节点：全部知识层节点（含无 name 的感知节点——它们最需要分离）。"""
        created, updated = 0, 0
        try:
            from aeis_core import LayeredStore
        except Exception:
            return {"created": 0, "updated": 0, "error": "no LayeredStore"}

        nodes = []
        try:
            from aeis_core import MemoryLayer
            for n in self.store.query_nodes(layer=MemoryLayer.KNOWLEDGE, limit=400):
                if n.content and len(n.content) > 10:
                    nodes.append(n)
        except Exception:
            return {"created": 0, "updated": 0, "error": "query failed"}

        done = 0
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                if done >= limit:
                    break
                a, b = nodes[i], nodes[j]
                sim = LayeredStore.char_bigram_jaccard(a.content, b.content)
                # 相似度 1.0 = 完全重复 → 去重问题，不是分离问题（跳过，交 M5 去重）
                if sim < SIM_THRESHOLD or sim >= 0.99:
                    continue
                a_name = a.state_attributes.get("name") or a.content[:12]
                b_name = b.state_attributes.get("name") or b.content[:12]
                note, diffs = separation_note(a_name, b_name, a, b)
                if not note:
                    # 无真实差异（条件空间/标签都相同）→ 纯内容重叠，不建分离边
                    # （那是去重问题；分离边只服务于「相似但不同」的知识）
                    continue
                # 已存在 separation 边则更新注记，否则新建
                edge_id = self._find_sep_edge(a.id, b.id)
                try:
                    from aeis_core import ConditionSpace
                    sep_cs = ConditionSpace(
                        observation_position="模式分离",
                        observation_tool="条件空间对比",
                        time_window=(time.time(), time.time() + 3600),
                        existence_constraint=note)
                    if edge_id:
                        self.store.conn.execute(
                            "UPDATE edges SET condition_space=? WHERE id=?",
                            (sep_cs.to_json(), edge_id))
                        self.store.conn.commit()
                        updated += 1
                    else:
                        from aeis_core import EdgeType
                        self.engine.add_edge(
                            a.id, b.id, relation_type=EdgeType.SIMILAR,
                            condition_space=sep_cs,
                            source_evidence="inferred")
                        created += 1
                except Exception:
                    pass
                done += 1
            if done >= limit:
                break
        return {"created": created, "updated": updated, "scanned": done}

    def _find_sep_edge(self, a_id, b_id):
        """为相似节点对定位分离边候选：条件差异显式化的落点。"""
        try:
            for e in self.store.get_outgoing_edges(a_id):
                if e.target_id == b_id and self._is_sep(e):
                    return e.id
            for e in self.store.get_incoming_edges(a_id):
                if e.source_id == b_id and self._is_sep(e):
                    return e.id
        except Exception:
            pass
        return None

    @staticmethod
    def _is_sep(edge):
        """判断边是否为模式分离边（condition_space 的观测位置 = 模式分离）。"""
        try:
            cs = json.loads(edge.condition_space.to_json()) \
                if hasattr(edge.condition_space, "to_json") else {}
            return cs.get("observation_position") == "模式分离"
        except Exception:
            return False

    def retrieve_with_separation(self, query, limit=5):
        """检索 + 分离提示：命中节点若带 separation 边，附差异注记。"""
        results = []
        try:
            from aeis_core import LayeredStore
            hits = self.store.search_content(query, limit=limit) or []
            for n, score in hits:
                item = {"name": n.state_attributes.get("name") or n.id[:16],
                        "score": round(score, 2)}
                # 找 separation 边注记
                seps = []
                try:
                    for e in self.store.get_outgoing_edges(n.id):
                        if self._is_sep(e):
                            cs = json.loads(e.condition_space.to_json())
                            ec = cs.get("existence_constraint", "")
                            if ec:
                                seps.append(ec)
                except Exception:
                    pass
                if seps:
                    item["separation"] = seps[:2]
                results.append(item)
        except Exception as e:
            return {"error": str(e)}
        return results


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from aeis_core import SpacetimeMemoryEngine

    db = os.environ.get("AEIS_DB", os.path.join("data", "lingshu.db"))
    engine = SpacetimeMemoryEngine(db_path=db, identity="灵枢", role="PRIMARY")
    ps = PatternSeparation(engine)
    if "--scan" in sys.argv:
        r = ps.scan(limit=200)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        q = " ".join(sys.argv[1:]) or "物理"
        r = ps.retrieve_with_separation(q, limit=5)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    engine.close()


if __name__ == "__main__":
    main()
