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
    """条件空间对象→可序列化字典（观测位·工具·时间窗·存在约束）。

    双形态兼容：sqlite ConditionSpace（.to_json()）与 md 行 dict
    （md 真源模式下 shim 节点的 condition_space 已是 dict）。
    """
    cs = getattr(node, "condition_space", None)
    if isinstance(cs, dict):
        return cs
    try:
        return json.loads(cs.to_json()) if cs else {}
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

    def __init__(self, engine=None, cg=None):
        """双模初始化（写路径收口 · md 真源裁定）。

        - `cg` 给定 → **md 真源模式**：节点输入读 `md_access.MdConn`
          （知识层行），分离边写经 `cg.append_edge` / `cg.set_edge_condition`
          （mdcg 边域窄原语，唯一写入闸门）。engine 可为 None。
        - `engine` 给定且无 cg → sqlite 派生库旧路（兜底）。
        """
        self.engine = engine
        self.cg = cg
        self.store = engine.store if engine is not None else None
        self._mdc = None

    def _md_conn(self):
        """md 模式只读连接（懒加载，root 取 cg.root）。"""
        if self._mdc is None:
            from md_access import MdConn
            self._mdc = MdConn(self.cg.root)
        return self._mdc

    class _NV:
        """md 行 → 节点视图 shim（separation_note/_tag_diff 所需最小面）。

        MdConn 行的 json 列（tags/condition_space/state_attributes）为
        字符串原值（同构指列位），在此反序列化为 dict/list。
        """

        @staticmethod
        def _js(v):
            if isinstance(v, (dict, list)) or v is None:
                return v or ({} if not isinstance(v, list) else [])
            try:
                return json.loads(v)
            except Exception:
                return {}

        def __init__(self, row):
            from md_access import COLS
            d = dict(zip(COLS, row))
            self.id = d["id"]
            self.content = d["content"] or ""
            self.tags = self._js(d["tags"]) or []
            self.state_attributes = self._js(d["state_attributes"]) or {}
            self.condition_space = self._js(d["condition_space"]) or {}

    def _is_sep_dict(self, edge):
        """md 边 dict 的分离判据（observation_position=模式分离）。"""
        cs = edge.get("condition_space") or {}
        return isinstance(cs, dict) and cs.get(
            "observation_position") == "模式分离"

    def scan(self, limit=200, tag_only=False):
        """扫描相似节点对，建立分离边（similar + 差异注记）。
        参与节点：全部知识层节点（含无 name 的感知节点——它们最需要分离）。"""
        if self.cg is not None:
            return self._scan_md(limit)
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

    def _scan_md(self, limit=200):
        """md 真源扫描：节点输入=MdConn 知识层行，
        分离边写=cg.append_edge / cg.set_edge_condition（唯一写入闸门）。

        与 sqlite 版同判据（SIM_THRESHOLD / 0.99 去重上界 / separation_note
        有差异才建边），边 dict 形态对齐迁移语料（confidence=引擎默认 0.5、
        verified=0、source_evidence=inferred）。
        """
        md = self._md_conn()
        try:
            from aeis_core import LayeredStore
        except Exception:
            return {"created": 0, "updated": 0, "error": "no LayeredStore"}
        rows = md.execute(
            "SELECT * FROM nodes WHERE layer='knowledge' LIMIT 400").fetchall()
        nodes = [self._NV(r) for r in rows
                 if (r[1] or "") and len(r[1] or "") > 10]
        created = updated = done = 0
        now = time.time()
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                if done >= limit:
                    break
                a, b = nodes[i], nodes[j]
                sim = LayeredStore.char_bigram_jaccard(a.content, b.content)
                if sim < SIM_THRESHOLD or sim >= 0.99:
                    continue
                a_name = a.state_attributes.get("name") or a.content[:12]
                b_name = b.state_attributes.get("name") or b.content[:12]
                note, diffs = separation_note(a_name, b_name, a, b)
                if not note:
                    # 无真实差异 → 纯内容重叠（去重问题），不建分离边
                    continue
                try:
                    sep_cs = {"observation_position": "模式分离",
                              "observation_tool": "条件空间对比",
                              "time_window": [now, now + 3600.0],
                              "existence_constraint": note}
                    hit = self._find_sep_edge_md(a.id, b.id)
                    if hit is not None:
                        src, tgt = hit
                        if self.cg.set_edge_condition(src, tgt, "similar",
                                                      sep_cs):
                            updated += 1
                    else:
                        if self.cg.append_edge(a.id, {
                                "target": b.id, "relation_type": "similar",
                                "confidence": 0.5, "verified": 0,
                                "condition_space": sep_cs,
                                "source_evidence": "inferred"}):
                            created += 1
                except Exception:
                    pass
                done += 1
            if done >= limit:
                break
        # 批次持久化边界：写走 cg 脏缓冲（唯一闸门），scan 完成即显式落盘——
        # 否则 autoflush 阈值前磁盘无文件，同工具内的 MdConn 读面看不到边。
        try:
            self.cg.flush()
        except Exception:
            pass
        return {"created": created, "updated": updated, "scanned": done}

    def _find_sep_edge_md(self, a_id, b_id):
        """md 真源：定位 a-b 之间的 separation 边，返回 (source, target)。

        双向语义对齐 sqlite 版（a→b 出边或 b→a 出边均可承载分离注记）。
        无命中返回 None。
        """
        md = self._md_conn()
        for src, tgt in ((a_id, b_id), (b_id, a_id)):
            for e in md.edges_between(src, tgt, "similar"):
                if self._is_sep_dict(e):
                    return (src, tgt)
        return None

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
        """检索 + 分离提示：命中节点若带 separation 边，附差异注记。

        边界：该读面走 engine 派生库快照（md 真源模式下快照可能滞后），
        运行时检索面的读路径收口属 md_access 专项，本方法不重复建设。
        """
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
    cg = None
    engine = None
    if (os.environ.get("WB_MD_DIRECT") == "1"
            and os.environ.get("WB_MD_ROOT")):
        # md 真源模式：分离边写入 md 语料（WB_MD_ROOT 即语料根）
        _root_parent = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        if _root_parent not in sys.path:
            sys.path.insert(0, _root_parent)
        from md_cg.mdcg import MdCG
        cg = MdCG(root=os.environ["WB_MD_ROOT"])
        print(f"[md] 真源根: {cg.root}")
        ps = PatternSeparation(cg=cg)
    else:
        from aeis_core import SpacetimeMemoryEngine
        db = os.environ.get("AEIS_DB", os.path.join("data", "lingshu.db"))
        engine = SpacetimeMemoryEngine(db_path=db, identity="灵枢",
                                       role="PRIMARY")
        ps = PatternSeparation(engine=engine)
    if "--scan" in sys.argv:
        r = ps.scan(limit=200)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        q = " ".join(a for a in sys.argv[1:] if not a.startswith("--")) or "物理"
        r = ps.retrieve_with_separation(q, limit=5)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    if cg is not None:
        cg.flush()
    elif engine is not None:
        engine.close()


if __name__ == "__main__":
    main()
