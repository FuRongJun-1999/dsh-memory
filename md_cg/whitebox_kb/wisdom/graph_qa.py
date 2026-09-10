# -*- coding: utf-8 -*-
"""graph_qa.py · 条件图数据库问答（第六阶段·目标6 图查询进对话）
组装白箱图数据库单元（graph_db_units：建图/影响面/路径）→ 条件图问答：
  「气压会影响哪些规律？」→ 影响面；「X 和 Y 有关系吗？」→ 路径存在；
  「从 X 到 Y 怎么走？」→ 路径枚举。零 LLM——白箱知识库即条件图数据库。
"""
import sys
import ast
sys.stdout.reconfigure(encoding='utf-8')


def _load_whitebox_units():
    """从白箱单元库提取生成的函数（graph_db_units pattern → exec，注入 Graph）"""
    from graph_db_units import GRAPH_UNITS

    def _exec_unit(uid):
        """编译执行图单元 pattern 源码，返回其命名空间供函数体调用。"""
        tree = ast.parse(GRAPH_UNITS[uid]["pattern"])
        ns = {}
        exec(compile(tree, "<unit>", "exec"), ns)
        return ns

    graph_cls = _exec_unit("图存储-节点边")["Graph"]

    def _fn(uid):
        """取单元命名空间并注入 Graph 类，支持白箱单元之间互相组装。"""
        ns = _exec_unit(uid)
        ns["Graph"] = graph_cls  # 注入 Graph（白箱单元互相组装）
        return ns

    return {
        "Graph": graph_cls,
        "build": _fn("条件路由图-对接")["build_from_condition_units"],
        "impact": _fn("条件路由图-对接")["condition_impact"],
        "has_path": _fn("图遍历-路径")["has_path"],
        "all_paths": _fn("图遍历-路径枚举")["all_paths"],
    }


class ConditionGraphQA:
    """条件图数据库问答：建图（真实条件单元库）→ 影响/关系/路径 查询"""

    def __init__(self, condition_units):
        """图问答器初始化：挂载图存储与单元执行通道。"""
        self.units = _load_whitebox_units()
        self.graph = self.units["build"](condition_units)

    def ask(self, question):
        qtype = self._classify(question)
        if qtype is None:
            return {"ok": False, "reply": "（非条件图问题——不属图查询通道）", "type": None}
        name = self._extract(question)
        if not name:
            return {"ok": False, "type": qtype,
                    "reply": "（未识别到条件/知识名——诚实边界）"}
        if qtype == "影响":
            impact = self.units["impact"](self.graph, name)
            if not impact:
                return {"ok": True, "type": "影响",
                        "reply": f"条件「{name}」不直接影响任何规律单元。", "detail": []}
            return {"ok": True, "type": "影响",
                    "reply": f"条件「{name}」影响的规律: {', '.join(impact)}。",
                    "detail": impact}
        if qtype == "关系":
            target = self._extract2(question)
            if not target:
                return {"ok": False, "type": "关系",
                        "reply": "（关系查询需要两个名字——诚实边界）"}
            # 双向：任一路径存在即有关（有向条件链）
            has = (self.units["has_path"](self.graph, name, target)
                   or self.units["has_path"](self.graph, target, name))
            return {"ok": True, "type": "关系",
                    "reply": f"「{name}」与「{target}」{'有关联' if has else '无关联'}（条件链路径）。",
                    "detail": {"has_path": has}}
        if qtype == "路径":
            target = self._extract2(question)
            if not target:
                return {"ok": False, "type": "路径", "reply": "（路径查询需要两个名字）"}
            paths = self.units["all_paths"](self.graph, name, target)
            if not paths:
                return {"ok": True, "type": "路径",
                        "reply": f"「{name}」到「{target}」没有路径。"}
            return {"ok": True, "type": "路径",
                    "reply": f"「{name}」→「{target}」路径 {len(paths)} 条: "
                             + " | ".join("→".join(p) for p in paths[:3]),
                    "detail": paths}
        return {"ok": False, "type": qtype, "reply": "（未识别问题类型）"}

    def _classify(self, q):
        """图问题意图分类：按关键词命中分派问型（影响/关系/路径等）。"""
        if any(w in q for w in ("影响哪些", "涉及哪些", "影响什么", "怎么影响")):
            return "影响"
        if any(w in q for w in ("有关系", "有关吗", "能到", "关联")):
            return "关系"
        if any(w in q for w in ("怎么走", "路径", "怎么到", "经过")):
            return "路径"
        return None

    def _extract(self, q):
        """条件与知识名提取：最长匹配优先（「光照」优于「光」——更具体者胜）。"""
        # 提取条件/知识名：最长匹配优先（光照 > 光——更具体）
        for name in sorted(self.graph.nodes, key=len, reverse=True):
            if name in q:
                return name
        return None

    def _extract2(self, q):
        """提取第二个名字（关系/路径查询的目标）"""
        hits = [n for n in sorted(self.graph.nodes, key=len, reverse=True)
                if n in q]
        return hits[1] if len(hits) > 1 else None


if __name__ == "__main__":
    print("=== 条件图数据库问答（目标6 · 图查询进对话）===\n")
    import compose_engine as ce
    qa = ConditionGraphQA(ce.CONDITION_UNITS)
    for q in ["气压会影响哪些规律？", "气压 和 沸点-气压 有关系吗？",
              "从 气压 到 沸点-气压 怎么走？", "什么是碳中和？"]:
        r = qa.ask(q)
        mark = "✔" if r.get("ok") else "✘"
        print(f"[{mark}] Q: {q}")
        print(f"     A: {r.get('reply', '')}")
