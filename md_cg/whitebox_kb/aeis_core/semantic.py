#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
semantic_space · 协议原生语义空间（v1.6 · M11 落地）
三层语义坐标系（ANALYSIS-PROTOCOL-COMPILER-REV1-20260813-001）：
  L1 协议符号轴（名实校验器符号表 → 概念向量）     权重 0.6
  L2 部首语义轴（象形语义场 · 粗粒度聚类启发式）    权重 0.2
  L3 神经语义轴（bge 等嵌入 · 可选插件）            权重 0.2
约束：
  - L2 为粗粒度启发式（DEVIATION-003）：部首仅表义类；"法"（氵部）不得入水语义场
  - 核心零外部依赖（D-005）：L3 经 duck-typed 注入
  - 语义 = 图在符号条件空间下的投影（蜂群奠基声明）
"""

from typing import Dict, List, Optional


# =============================================================================
# L1 协议符号轴（协议自语义化：命名即语义绑定 · 0.0.4 节）
# =============================================================================

PROTOCOL_SYMBOLS: Dict[str, List[str]] = {
    # 核心价值与公理
    "存在优先": ["existence"], "存在": ["existence"], "第零定律": ["axiom"],
    "知识统一": ["axiom"], "熵管理": ["entropy"],
    # 信任体系（2.9 节）
    "信任值": ["trust"], "信任": ["trust"], "置信": ["trust"],
    "情感权重": ["trust", "emotion"], "情感": ["emotion"],
    # 信息差（2.7 节）
    "信息差": ["gap"], "偏差": ["gap", "verify"], "预测误差": ["gap"],
    "连接偏离": ["gap"], "动态死区": ["gap"],
    # 条件空间（0.0.x / 第三章）
    "条件空间": ["condition"], "观测位置": ["condition"], "观测工具": ["condition"],
    "时间窗口": ["condition", "time"], "存在约束": ["condition", "existence"],
    # 五大核心单元（3.1 节）
    "验证单元": ["verify", "unit"], "反思单元": ["reflect", "unit"],
    "记录单元": ["record", "unit"], "输出单元": ["output", "unit"],
    "维生系统": ["vital", "unit"], "终裁": ["vital"],
    # 记忆体系（3.2 节 / 第四章）
    "锚点": ["anchor"], "结构层": ["structure"], "情境": ["context"],
    "知识": ["knowledge"], "自我": ["self"], "记忆": ["memory"],
    "时空": ["space", "time"], "因果": ["causal"], "衰减": ["memory", "forget"],
    "巩固": ["learning", "memory"], "归纳": ["learning", "concept"],
    "实体": ["entity"], "技能": ["skill"],
    # 认知与盲区
    "盲区": ["gap", "metacognition"], "元认知": ["metacognition"],
    "价值观": ["value"], "反思": ["reflect"], "验证": ["verify"],
    "协议": ["protocol"], "实例": ["instance"], "身份": ["identity"],
    # 学习与演化
    "学习": ["learning"], "演化": ["learning"], "迭代": ["learning"],
    "回收": ["vital"], "退出": ["existence", "freedom"],
}

# 协议规范术语全集（自省接口用：uncovered 检测）
PROTOCOL_CANONICAL_TERMS = [
    "存在优先", "第零定律", "信任", "信息差", "条件空间", "验证单元", "反思单元",
    "记录单元", "输出单元", "维生系统", "盲区", "价值观", "情感权重", "锚点",
    "结构层", "情境层", "知识层", "自我层", "时空记忆", "因果", "归纳", "巩固",
    "实体", "技能", "协议", "实例", "身份", "退出权", "休眠", "合并", "自毁",
]


# =============================================================================
# L2 部首语义轴（象形语义场 · 粗粒度启发式 · DEVIATION-003）
# =============================================================================
# 说明：仅收录"形旁表义且语义相关"的常用字（义类标注）；
#       不含形旁与义类背离的字（如"法"氵部但不表水义——精度测试对象）。

RADICAL_FIELD_CHARS: Dict[str, set] = {
    "water": {"江", "河", "海", "流", "洗", "清", "湖", "浪", "油", "汽",
              "湿", "泳", "波", "汁", "汤", "汗", "泪", "滴", "泉", "溪",
              "源", "泡", "浴", "游", "温", "满", "浅", "深", "液", "泽"},
    "emotion": {"情", "性", "怕", "怪", "惊", "快", "慢", "忧", "愁", "想",
                "思", "忘", "念", "悔", "恼", "恨", "愉", "悦", "悲", "感",
                "愿", "爱", "恶", "慕", "慰"},
    "speech": {"说", "话", "讲", "议", "论", "评", "语", "诗", "词", "读",
               "课", "请", "谢", "认", "识", "记", "访", "询", "让", "许",
               "设", "诚", "证", "词", "谈", "谅"},
    "person": {"他", "们", "仁", "仪", "付", "代", "令", "以", "休", "会",
               "企", "位", "住", "体", "作", "你", "使", "例", "供", "依",
               "保", "信", "修", "健", "傲", "优"},
    "plant": {"村", "林", "树", "根", "枝", "叶", "果", "桥", "桃", "梅",
              "松", "柏", "森", "椅", "棋", "楼", "枝", "采", "朵", "茶"},
    "fire": {"灯", "灶", "炒", "烤", "烘", "烧", "热", "然", "照", "熟",
             "燃", "烟", "焰", "烫", "煮"},
    "metal": {"钢", "铁", "银", "铜", "锁", "钱", "钟", "铃", "错", "锻",
              "锋", "针"},
    "earth": {"地", "场", "址", "坡", "坦", "城", "堡", "境", "增", "塘",
              "坑", "埋"},
    "sun": {"时", "明", "昨", "是", "显", "晴", "晚", "暂", "暑", "晨"},
    "mountain": {"峰", "岛", "峡", "岭", "岩", "岸", "岗", "峦"},
    "hand": {"打", "把", "抓", "投", "折", "拉", "拍", "拿", "指", "持",
             "换", "推", "提", "摸", "摘", "操", "擦", "接", "握", "搬",
             "摇", "摆", "放", "扶", "护"},
    "eye": {"看", "相", "省", "盼", "眨", "真", "眼", "睛", "睡", "督"},
    "mouth": {"吃", "名", "向", "吗", "吧", "听", "味", "命", "和", "品",
              "哈", "哭", "唇", "吐", "唱"},
    "foot": {"跑", "跳", "踏", "跟", "路", "距", "踩", "踢", "跌"},
    "weather": {"雪", "雷", "零", "霜", "雾", "霞", "震"},
    "house": {"安", "完", "家", "宴", "客", "宫", "害", "寄", "宿", "密",
              "富", "寒", "宅"},
    "animal": {"虾", "蚁", "蛙", "蜂", "蝶", "蚂", "蝉"},
    "vehicle": {"转", "轻", "轿", "载", "辆", "输", "轮"},
    "jade": {"环", "珍", "珠", "理", "球", "现", "班", "琴"},
}

# 独立部首字符（文本中出现这些字符时直接映射语义场）
RADICAL_STANDALONE = {
    "氵": "water", "水": "water", "忄": "emotion", "心": "emotion",
    "讠": "speech", "言": "speech", "亻": "person", "人": "person",
    "木": "plant", "艹": "plant", "火": "fire", "灬": "fire",
    "金": "metal", "钅": "metal", "土": "earth", "日": "sun", "月": "moon",
    "山": "mountain", "石": "stone", "口": "mouth", "目": "eye",
    "扌": "hand", "手": "hand", "足": "foot", "纟": "thread", "糸": "thread",
    "虫": "animal", "雨": "weather", "宀": "house", "门": "gate",
    "女": "female", "马": "horse", "鸟": "bird", "鱼": "fish",
    "车": "vehicle", "王": "jade", "玉": "jade", "米": "grain",
}


# =============================================================================
# SemanticSpaceProvider
# =============================================================================

class SemanticSpaceProvider:
    """协议原生语义空间（v1.6 · M11 落地）
    L1 协议符号轴（名实绑定） + L2 部首语义轴（粗粒度启发式） + L3 神经轴（可选插件）"""

    WEIGHTS = {"L1": 0.6, "L2": 0.2, "L3": 0.2}

    def __init__(self, protocol_symbols: Dict[str, List[str]] = None,
                 radical_chars: Dict[str, set] = None,
                 radical_standalone: Dict[str, str] = None):
        self.protocol_symbols = protocol_symbols or PROTOCOL_SYMBOLS
        self.radical_chars = radical_chars or RADICAL_FIELD_CHARS
        self.radical_standalone = radical_standalone or RADICAL_STANDALONE
        self.neural_provider = None

    # ---- L3 神经轴（可选插件 · D-005 duck-typed） ----

    def set_neural_provider(self, provider):
        """provider 契约：encode(text) -> List[float]"""
        self.neural_provider = provider

    # ---- 各轴计算 ----

    def protocol_axis(self, text: str) -> Dict[str, float]:
        """L1：协议符号命中 → 概念向量（名实绑定）"""
        hits: Dict[str, float] = {}
        for term, axes in self.protocol_symbols.items():
            if term in text:
                for ax in axes:
                    hits[f"protocol_{ax}"] = hits.get(f"protocol_{ax}", 0.0) + 1.0
        total = sum(hits.values()) or 1.0
        return {k: round(v / total, 4) for k, v in hits.items()}

    def radical_axis(self, text: str) -> Dict[str, float]:
        """L2：语义场命中 → 粗粒度向量（仅义类相关字；'法'不映射 water）"""
        hits: Dict[str, float] = {}
        for field, chars in self.radical_chars.items():
            cnt = sum(1 for ch in text if ch in chars)
            if cnt:
                hits[f"radical_{field}"] = float(cnt)
        for ch in text:
            field = self.radical_standalone.get(ch)
            if field:
                hits[f"radical_{field}"] = hits.get(f"radical_{field}", 0.0) + 1.0
        total = sum(hits.values()) or 1.0
        return {k: round(v / total, 4) for k, v in hits.items()}

    def neural_axis(self, text: str) -> Dict[str, float]:
        """L3：神经嵌入（可选）"""
        if self.neural_provider is None:
            return {}
        try:
            vec = self.neural_provider.encode(text)
            return {f"neural_{i}": round(float(v), 4) for i, v in enumerate(vec[:8])}
        except Exception:
            return {}

    # ---- 综合 ----

    def to_coordinates(self, text: str) -> Dict[str, float]:
        """文本 → spatial_coordinates（加权三层）"""
        coords: Dict[str, float] = {}
        for k, v in self.protocol_axis(text).items():
            coords[k] = round(v * self.WEIGHTS["L1"], 4)
        for k, v in self.radical_axis(text).items():
            coords[k] = round(v * self.WEIGHTS["L2"], 4)
        for k, v in self.neural_axis(text).items():
            coords[k] = round(v * self.WEIGHTS["L3"], 4)
        return coords

    def similarity(self, text_a: str, text_b: str) -> float:
        """语义余弦相似度（加权坐标空间）"""
        ca, cb = self.to_coordinates(text_a), self.to_coordinates(text_b)
        keys = set(ca) | set(cb)
        if not keys:
            return 0.0
        dot = sum(ca.get(k, 0.0) * cb.get(k, 0.0) for k in keys)
        na = sum(v * v for v in ca.values()) ** 0.5 or 1.0
        nb = sum(v * v for v in cb.values()) ** 0.5 or 1.0
        return round(dot / (na * nb), 4)

    # ---- 名实校验 API（REV1 · 编译器名实校验的引擎侧接口） ----

    def resolve_concepts(self, text: str) -> List[str]:
        """文本 → 命中的协议概念（以名举实）"""
        return [term for term in self.protocol_symbols if term in text]

    # ---- v1.7 结构化语义坐标（DEVIATION-002/003） ----

    def to_semantic_coordinates(self, text: str) -> Dict:
        """v1.7：结构化语义坐标（L1 子空间 concept/entity/attribute/relation/logic + L2 + L3）"""
        return {
            "protocol": {"concept": self.protocol_axis(text),
                         "entity": [], "attribute": [], "relation": [], "logic": []},
            "radical": self.radical_axis(text),
            "neural": self.neural_axis(text),
        }

    @staticmethod
    def flatten_semantic(sc: Dict) -> Dict[str, float]:
        """结构化语义坐标 → 扁平向量（相似度计算）"""
        flat: Dict[str, float] = {}
        if not isinstance(sc, dict):
            return flat
        protocol = sc.get("protocol", {}) if isinstance(sc.get("protocol"), dict) else {}
        for subspace, vals in protocol.items():
            if isinstance(vals, dict):
                for k, v in vals.items():
                    flat[f"protocol_{subspace}_{k}"] = float(v)
            elif isinstance(vals, list):
                for i, v in enumerate(vals):
                    try:
                        flat[f"protocol_{subspace}_{i}"] = float(v)
                    except (TypeError, ValueError):
                        pass  # 字符串项（如实体名）不参与数值相似度；由实体名匹配处理
        radical = sc.get("radical", {})
        if isinstance(radical, dict):
            for k, v in radical.items():
                flat[f"radical_{k}"] = float(v)
        neural = sc.get("neural", {})
        if isinstance(neural, dict):
            for k, v in neural.items():
                flat[f"neural_{k}"] = float(v)
        return flat

    @staticmethod
    def similarity_coordinates(ca: Dict, cb: Dict) -> float:
        """结构化语义坐标余弦相似度"""
        fa = SemanticSpaceProvider.flatten_semantic(ca)
        fb = SemanticSpaceProvider.flatten_semantic(cb)
        keys = set(fa) | set(fb)
        if not keys:
            return 0.0
        dot = sum(fa.get(k, 0.0) * fb.get(k, 0.0) for k in keys)
        na = sum(v * v for v in fa.values()) ** 0.5 or 1.0
        nb = sum(v * v for v in fb.values()) ** 0.5 or 1.0
        return round(dot / (na * nb), 4)

    def introspect(self) -> Dict:
        """编译器自省（DEVIATION-005）：符号覆盖范围 + 未覆盖概念"""
        covered = set(self.protocol_symbols.keys())
        uncovered = [t for t in PROTOCOL_CANONICAL_TERMS if t not in covered]
        return {
            "symbol_count": len(self.protocol_symbols),
            "symbol_coverage": sorted(covered),
            "uncovered_terms": uncovered,
            "radical_fields": sorted(self.radical_chars.keys()),
            "neural_available": self.neural_provider is not None,
        }

    def blindspot_report(self) -> Dict:
        """语义盲区报告（DEVIATION-005）：无法处理的输入类型"""
        return {
            "unprocessable_modalities": ["image", "audio", "video", "tactile"],
            "note": "非符号/多模态条件空间（3.5 节）不在当前语义空间覆盖范围（v1.7 多模态扩展）",
            "radical_resolution": "粗粒度义类（形旁表义统计规律），非精确语义",
        }
