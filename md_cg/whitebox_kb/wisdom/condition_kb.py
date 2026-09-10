# -*- coding: utf-8 -*-
"""condition_kb.py · 知识库条件化层（第四阶段·蒸馏骨架接入组合引擎）
从 distilled_condition_units.json（573 条骨架 {条件词×方向词→规律}）加载——
问题条件词命中骨架 → 返回规律片段（白箱规律直答，零 LLM）。
组合引擎 route_compose 在未覆盖时查本层兜底——组合引擎覆盖知识库。
"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')

_HERE = os.path.dirname(os.path.abspath(__file__))
_JSON = os.path.join(_HERE, 'distilled_condition_units.json')

# 条件词表（与 distill 一致——问题条件词提取）
CONDITION_WORDS = [
    "气压", "温度", "湿度", "密度", "光照", "阳光", "重力", "摩擦", "压力",
    "面积", "速度", "浓度", "酸碱", "酸性", "碱性", "水分", "氧气", "二氧化碳",
    "热量", "能量", "电流", "电压", "电阻", "波长", "频率", "距离", "时间",
    "风", "海拔", "深度", "体积", "质量", "盐度", "糖分", "季节", "电解质",
    "催化剂", "酶", "磁力", "电场", "引力", "张力", "惯性", "杠杆",
    "光", "声", "电", "磁", "金属", "塑料", "木材", "水", "油", "糖",
    "盐", "维生素", "蛋白质", "细菌", "病毒", "细胞", "基因", "植物", "动物",
    "人类", "城市", "人口", "经济", "市场", "价格", "货币", "星球", "太阳",
    "月亮", "空气", "土壤", "海洋", "森林", "气候", "雨", "雪", "冰", "火山",
    "地震", "昼夜", "宇宙", "恒星", "行星", "轨道",
]

# 规律连词（组装规律片段）
_RULE_LINKS = ["降低", "升高", "上升", "下降", "增大", "减小", "变大", "变小",
               "变快", "变慢", "加快", "减慢", "加速", "减速", "变硬", "变软",
               "融化", "凝固", "蒸发", "液化", "升华", "凝华", "沸腾", "结冰",
               "熔化", "浮", "沉", "亮", "暗", "膨胀", "收缩", "折射", "反射",
               "溶解", "沉淀", "氧化", "燃烧", "发光", "发热", "吸收", "释放",
               "增加", "减少", "越快", "越慢", "越高", "越低", "越大", "越小"]


class ConditionKB:
    """知识库条件化层：蒸馏骨架查询（条件词命中 → 规律片段）"""

    def __init__(self, json_path=_JSON):
        """条件知识库初始化：骨架集与条件词表加载。"""
        self.skeletons = {}
        if os.path.exists(json_path):
            try:
                self.skeletons = json.load(open(json_path, encoding='utf-8'))
            except Exception:
                self.skeletons = {}
        # 条件词 → 簇 索引（查询加速）
        self.cond_index = {}
        for key, sk in self.skeletons.items():
            for c in sk.get("conds", []):
                self.cond_index.setdefault(c, []).append(key)

    def extract_conditions(self, question):
        """问题 → 条件词（与蒸馏词表一致）"""
        return [w for w in CONDITION_WORDS if w in question]

    def lookup(self, question):
        """问题条件词 → 命中骨架（条件词重叠最多）→ 规律片段
        返回 {ok, key, conds, dirs, rule, overlap}"""
        qconds = self.extract_conditions(question)
        if not qconds:
            return {"ok": False, "reason": "问题无条件词"}
        # 找重叠条件词最多的骨架
        best_key, best_overlap = None, 0
        for c in qconds:
            for key in self.cond_index.get(c, []):
                sk = self.skeletons[key]
                overlap = len(set(qconds) & set(sk.get("conds", [])))
                if overlap > best_overlap:
                    best_key, best_overlap = key, overlap
        if best_key is None:
            return {"ok": False, "reason": "无条件词命中骨架"}
        sk = self.skeletons[best_key]
        dirs = [d for d in sk.get("dirs", []) if d in _RULE_LINKS]
        rule = (f"知识规律「{best_key}」：条件 {sk['conds'][:4]} 相关，"
                f"规律方向 {dirs[:4]}")
        return {"ok": True, "key": best_key,
                "conds": sk.get("conds", []), "dirs": dirs,
                "rule": rule, "overlap": best_overlap}

    def stats(self):
        """骨架与条件词库规模快照：skeletons 数 + CONDITION_WORDS 词数。"""
        return {"skeletons": len(self.skeletons),
                "condition_words": len(CONDITION_WORDS)}


if __name__ == "__main__":
    kb = ConditionKB()
    print("=== 知识库条件化层：组合引擎覆盖知识库（零 LLM） ===\n")
    st = kb.stats()
    print(f"① 加载 {st['skeletons']} 条蒸馏骨架（{st['condition_words']} 条件词）\n")

    print("② 条件词查询（问题 → 规律片段）：")
    for q in ["为什么气压低沸点会降低？", "为什么温度高蒸发快？",
              "为什么密度大的物体会沉？", "为什么光照充足植物长得好？",
              "为什么摩擦力大刹车快？", "为什么电解质导电？"]:
        r = kb.lookup(q)
        if r.get("ok"):
            print(f"  ✔ {q}")
            print(f"    → {r['rule']}")
        else:
            print(f"  ✘ {q}（{r.get('reason')}）")

    # 判定
    hits = [kb.lookup(q).get("ok") for q in
            ["为什么气压低沸点会降低？", "为什么温度高蒸发快？",
             "为什么密度大的物体会沉？", "为什么光照充足植物长得好？"]]
    print(f"\n=== 判定 ===\n知识库条件化层命中: {sum(hits)}/{len(hits)}")
