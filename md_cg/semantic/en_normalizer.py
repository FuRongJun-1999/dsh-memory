#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英文查询归一器：English query → 语义原子序列（中文语素）→ 检索键

原则（设计者裁定）：
  · 时态全部抛弃，时间由时间词承载
  · 无联系虚词（冠词/介词/系动词）不入语义序列
  · 音译/专有词：保留原名（不归一化），标记为 proper_noun
  · 构词法：英文复合词按中文语素序拆解重组（beef → cow_meat → 牛 肉）

用法：
    from en_normalizer import normalize
    terms = normalize("I eat beef yesterday")
    # → ["我", "吃", "牛肉", "昨天"]  (用于 cg.search)
"""
import json, io, os, re

# ---- 时态还原表：英文屈折 → 基形 ----
IRREGULAR = {
    "ate": "eat", "eaten": "eat", "went": "go", "gone": "go",
    "saw": "see", "seen": "see", "wrote": "write", "written": "write",
    "took": "take", "taken": "take", "made": "make", "ran": "run",
    "bought": "buy", "brought": "bring", "thought": "think",
    "taught": "teach", "caught": "catch", "sought": "seek",
    "fought": "fight", "sold": "sell", "told": "tell", "felt": "feel",
    "fell": "fall", "sent": "send", "spent": "spend", "built": "build",
    "lost": "lose", "met": "meet", "paid": "pay", "led": "lead",
    "won": "win", "sat": "sit", "stood": "stand",
    "understood": "understand", "heard": "hear",
    "spoke": "speak", "spoken": "speak", "broke": "break", "broken": "break",
    "chose": "choose", "chosen": "choose", "drew": "draw", "drawn": "draw",
    "drove": "drive", "driven": "drive", "grew": "grow", "grown": "grow",
    "knew": "know", "known": "know", "gave": "give", "given": "give",
    "was": "be", "were": "be", "been": "be", "had": "have", "has": "have",
    "did": "do", "done": "do", "said": "say", "got": "get",
    "left": "leave", "kept": "keep", "held": "hold",
    "slept": "sleep", "swept": "sweep", "meant": "mean",
    "dealt": "deal", "lent": "lend", "bent": "bend",
}

# ---- 虚词（不入语义序列）----
STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "with",
    "by", "from", "up", "about", "into", "over", "after", "is", "are",
    "was", "were", "be", "been", "being", "do", "does", "did", "have",
    "has", "had", "will", "would", "could", "should", "may", "might",
    "and", "or", "but", "not", "no", "so", "if", "then", "than",
    "this", "that", "these", "those", "it", "its", "as", "also",
}

# ---- en→zh 语义原子映射 ----
# 构词法：英文语素 → 中文语素（与 standard_en.json 的 morphemes 表互逆）
# 同时覆盖：常用动词基形 / 名词 / 时间词 / 形容词
EN_ZH = {
    # 代词
    "i": "我", "me": "我", "my": "我", "you": "你", "he": "他", "she": "她",
    "we": "我们", "they": "他们",
    # 动作
    "eat": "吃", "go": "去", "come": "来", "see": "看", "hear": "听",
    "read": "读", "write": "写", "walk": "走", "run": "跑", "fly": "飞",
    "make": "做", "build": "建", "find": "找", "give": "给", "take": "拿",
    "know": "知道", "think": "想", "say": "说", "speak": "说",
    "love": "爱", "use": "用", "buy": "买", "sell": "卖",
    "teach": "教", "learn": "学", "study": "学", "work": "工作",
    "sleep": "睡", "open": "开", "close": "关", "drive": "驾驶",
    # 名词
    "book": "书", "water": "水", "fire": "火", "meat": "肉",
    "milk": "奶", "egg": "蛋", "road": "路", "bridge": "桥",
    "tree": "木", "star": "星", "moon": "月", "sun": "日",
    "sea": "海", "mountain": "山", "city": "城", "country": "国",
    "people": "人", "person": "人", "king": "王", "heart": "心",
    "hand": "手", "head": "头", "eye": "眼", "blood": "血",
    "medicine": "医", "drug": "药", "disease": "病",
    "knowledge": "知识", "work": "工作", "discipline": "纪律",
    "memory": "记忆", "cognition": "认知", "graph": "图",
    "dog": "狗", "cat": "猫", "bird": "鸟", "fish": "鱼",
    "cow": "牛", "pig": "猪", "sheep": "羊", "chicken": "鸡",
    # 形容词
    "big": "大", "small": "小", "high": "高", "low": "低",
    "new": "新", "old": "旧", "good": "好", "bad": "坏",
    "hot": "热", "cold": "冷", "fast": "快", "slow": "慢",
    # 时间词
    "yesterday": "昨天", "today": "今天", "tomorrow": "明天",
    "morning": "早上", "evening": "晚上", "night": "夜",
    "spring": "春天", "summer": "夏天", "autumn": "秋天", "winter": "冬天",
    "year": "年", "month": "月", "day": "天", "week": "周",
    "hour": "小时", "minute": "分", "second": "秒",
    # 数
    "one": "一", "two": "二", "three": "三", "four": "四", "five": "五",
    "six": "六", "seven": "七", "eight": "八", "nine": "九", "ten": "十",
    "hundred": "百", "thousand": "千",
    # 其他
    "water": "水", "light": "光", "sound": "音", "metal": "金",
    "stone": "石", "wood": "木", "cloud": "云", "wind": "风",
    "rain": "雨", "snow": "雪",
}

# ---- 复合词映射（英文复合 → 中文标准概念）----
COMPOUND_ZH = {
    "soul hub": "灵枢",
    "beef": "牛肉", "pork": "猪肉", "mutton": "羊肉", "chicken": "鸡肉",
    "computer": "电脑", "telephone": "电话", "television": "电视",
    "movie": "电影", "film": "电影", "battery": "电池",
    "train": "火车", "car": "汽车", "airplane": "飞机", "mobile": "手机",
    "volcano": "火山", "seawater": "海水", "moonlight": "月光",
    "monday": "星期一", "tuesday": "星期二", "wednesday": "星期三",
    "thursday": "星期四", "friday": "星期五", "saturday": "星期六",
    "sunday": "星期日",
    "mathematics": "数学", "chemistry": "化学", "physics": "物理学",
    "geography": "地理学", "biology": "生物学", "thermodynamics": "热力学",
    "student": "学生", "doctor": "医生", "lawyer": "律师", "worker": "工人",
    "knowledge": "知识", "graph": "图",
    # 短语映射
    "electric brain": "电脑", "soul hub": "灵枢", "memory store": "记忆库",
    "fire vehicle": "火车", "cow meat": "牛肉", "gas vehicle": "汽车",
    "work discipline": "工作纪律", "knowledge graph": "知识图谱",
    "cognition graph": "认知图", "memory store": "记忆库",
    "word": "字", "soul": "灵", "hub": "枢",
}


def _de_double(w):
    """双写辅音还原（CVC 动词屈折）：regrett→regret / runn→run / stopp→stop。

    s / l 结尾排除（正字法惯例保留）：crossed→cross、called→call。
    """
    if len(w) > 2 and w[-1] == w[-2] and w[-1] not in "aeiousl":
        return w[:-1]
    return w


def strip_tense(word):
    """英文屈折归零：不规则动词查表；规则动词去 -ed/-ing/-s + 双写辅音还原"""
    w = word.lower()
    if w in IRREGULAR:
        return IRREGULAR[w]
    if w.endswith("ed") and len(w) > 4:
        return _de_double(w[:-2])
    if w.endswith("ing") and len(w) > 5:
        return _de_double(w[:-3])
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def is_stopword(w):
    return w.lower() in STOPWORDS


def is_proper(w):
    """专有词：原始 query 中首字母大写（人名/品牌/地名不归一化）"""
    return w[0].isupper() if w else False


def normalize_en_query(query, extra_map=None):
    """英文 query → 语义原子序列（中文语素）

    返回 (normalized_terms, detail)：
      normalized_terms: 用于检索的中文/保留词序列
      detail: 逐词归一化记录
    """
    en_zh = dict(EN_ZH)
    if extra_map:
        en_zh.update(extra_map)
    # 短语优先匹配：先尝试多词短语整体映射（复合概念名）
    phrase_key = query.lower().strip()
    if phrase_key in COMPOUND_ZH:
        comp_zh = COMPOUND_ZH[phrase_key]
        return [comp_zh], [{"orig": query, "phrase_zh": comp_zh, "action": "phrase_mapped"}]
    # 屈折还原 + 查表
    words = re.findall(r"[A-Za-z\u4e00-\u9fff]+", query)
    terms = []
    detail = []
    for w in words:
        wl = w.lower()
        if wl in STOPWORDS:
            detail.append({"orig": w, "action": "stopword_drop"})
            continue
        base = strip_tense(wl)
        zh = en_zh.get(base) or en_zh.get(wl)
        if zh:
            terms.append(zh)
            detail.append({"orig": w, "base": base, "zh": zh, "action": "mapped"})
        elif is_proper(w):
            terms.append(w)  # 专有词保留原名
            detail.append({"orig": w, "action": "proper_noun_keep"})
        else:
            # 未知词：尝试复合拆解（compound→zh morphemes）
            comp = COMPOUND_ZH.get(wl) or COMPOUND_ZH.get(base)
            if comp:
                terms.append(comp)
                detail.append({"orig": w, "compound_zh": comp, "action": "compound_mapped"})
            else:
                terms.append(w)
                detail.append({"orig": w, "action": "unknown_keep"})
    return terms, detail


def main():
    import sys
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "I eat beef yesterday"
    terms, detail = normalize_en_query(query)
    print("query:", query)
    print("normalized terms:", terms)
    print("search string:", " ".join(terms))
    for d in detail:
        print(" ", json.dumps(d, ensure_ascii=False))


if __name__ == "__main__":
    main()
