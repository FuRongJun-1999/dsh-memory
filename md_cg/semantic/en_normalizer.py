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
    # e-脱落动词机械去 -ed 会得错形（inspired→inspir）；词次取证达标者逐词收编
    "inspired": "inspire",
}

# ---- 虚词（不入语义序列）----
STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "with",
    "by", "from", "up", "about", "into", "over", "after", "is", "are",
    "was", "were", "be", "been", "being", "do", "does", "did", "have",
    "has", "had", "will", "would", "could", "should", "may", "might",
    "and", "or", "but", "not", "no", "so", "if", "then", "than",
    "this", "that", "these", "those", "it", "its", "as", "also",
    # locomo-500 词频取证补充（expand_en_zh analyze，2026-09-14）：物主/宾格
    # 代词与疑问框架词对中文库检索零语义贡献，保留只制造噪声原子
    # （unknown_keep 头部：his 90 / her 72 / get 20 / during 19 词次）。
    # 主格代词不动（i/we/you/he/she/they 已映射 我/我们/你/他/她/他们）。
    "his", "her", "hers", "him", "their", "theirs", "them", "us",
    "when", "where", "why", "how", "what", "which", "who", "whose",
    "during", "out", "get", "kind",
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
    # 盲测缺口修补（bench_blind_comp L2 白箱探针锁定，2026-09-14）：
    # horse/mare/goat/duck/oil/fat 六词未映射 → 英文组合词展开缺语素。
    # 只补探针暴露的缺口，不顺手扩表——修复面与暴露面精确对齐，净效应可归因。
    "horse": "马", "mare": "马", "goat": "羊", "duck": "鸭",
    "oil": "油", "fat": "油",
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
    # locomo-500 词频取证定向补词（expand_en_zh analyze top30 实词，2026-09-14；
    # 映射逐一核对唯一；partner 搭档/伴侣一对多跳过——宁缺勿滥）
    "friend": "朋友", "family": "家庭", "trip": "旅行", "plan": "计划",
    "game": "游戏", "type": "类型", "dance": "舞", "share": "分享",
    "painting": "画", "favorite": "喜欢", "feel": "感觉",
    "activity": "活动", "project": "项目", "photo": "照片",
    "studio": "工作室", "long": "长", "first": "第一", "recently": "最近",
    "start": "开始", "inspire": "激励",
    # CEDICT 词汇分布缺口定向补（2026-09-14）：CEDICT 用英式 mum（mom 缺）、
    # pet 冲突集全书面词在口语语料零命中、日常义项缺词条——映射唯一明确的
    # top30 级残留词逐词补，修复面=证据面
    "pet": "宠物", "mom": "妈妈", "tournament": "锦标赛",
    "festival": "节日", "advice": "建议", "often": "经常",
    "pottery": "陶艺",
    # 第三方 LoCoMo 报告错译暴露面语境化修正（2026-09-15，修复面=暴露面对齐）：
    # scared 错切链路 = strip_tense(scared)→scar × CEDICT scar→创痕，复合错译
    # （应为 害怕）；shelter/tough/times 为 CEDICT 第一义项与口语语料语境失配
    # （CEDICT 庇护/厉害/时间 → 语境 收容所/坚强/次）。低置信标记
    # （source=cedict）对此全部捕获后，人工校对层逐一核对的落地
    "scared": "害怕", "shelter": "收容所", "tough": "坚强", "times": "次",
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
    # 第三方 LoCoMo 报告错译暴露面（2026-09-15）：scavenger hunt 逐词直译
    # → 食腐动物 猎取（应为 寻宝游戏）；three times a week → 三 时间 周
    # （应为 每周三次）。配合内嵌短语扫描机制在长文本/问句内部生效
    "scavenger hunt": "寻宝游戏", "three times a week": "每周三次",
    "word": "字", "soul": "灵", "hub": "枢",
}

# 含空格多词短语预计算（内嵌短语扫描用，长键优先防前缀吞并）
COMPOUND_ZH_PHRASES = sorted(
    ((k, v) for k, v in COMPOUND_ZH.items() if " " in k),
    key=lambda kv: -len(kv[0]))


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


_CEDICT_CACHE = None


def cedict_map():
    """词级 CEDICT 反查表（build_cedict_en_zh.py 产物，17700 键级）。

    CC BY-SA 4.0 派生数据独立文件署名，不内联 MIT 的 EN_ZH；
    缺文件返回空表——纯手工表兜底，零外部依赖路径保持（第7条兜底纪律）。
    """
    global _CEDICT_CACHE
    if _CEDICT_CACHE is None:
        import json
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "lexicon", "cedict_en_zh.json")
        try:
            with io.open(path, encoding="utf-8") as f:
                _CEDICT_CACHE = json.load(f).get("map", {})
        except (OSError, ValueError):
            _CEDICT_CACHE = {}
    return _CEDICT_CACHE


def _lookup_chain(extra_map=None):
    """置信分层查表链（第三方验证 2026-09-15）：extra（实验注入）→
    EN_ZH（人工逐词校对）→ CEDICT（机械反查，第一义项直译）。

    分层依据 = 词条来源的人工校对程度，即映射质量的确定性代理信号：
    CEDICT 层命中即 low_confidence（语境失配风险，实证 scavenger→食腐动物，
    见 docs/第三方验证报告_LoCoMo_灵枢_.md 发现 5）。
    """
    chain = []
    if extra_map:
        chain.append((extra_map, "extra"))
    chain.append((EN_ZH, "manual"))
    cedict = cedict_map()
    if cedict:
        chain.append((cedict, "cedict"))
    return chain


def normalize_en_query(query, extra_map=None):
    """英文 query → 语义原子序列（中文语素）

    返回 (normalized_terms, detail)：
      normalized_terms: 用于检索的中文/保留词序列
      detail: 逐词归一化记录（mapped 词带 source/low_confidence 置信信号；
              low_confidence=True = 机械反查未人工校对，语境失配风险）
    """
    chain = _lookup_chain(extra_map)
    # 短语优先匹配：先尝试多词短语整体映射（复合概念名）
    phrase_key = query.lower().strip()
    if phrase_key in COMPOUND_ZH:
        comp_zh = COMPOUND_ZH[phrase_key]
        return [comp_zh], [{"orig": query, "phrase_zh": comp_zh,
                            "action": "phrase_mapped"}]
    # 内嵌短语扫描：多词短语在长文本/问句内部出现时整体替换为中文
    # （整体 query 匹配只救短语独占 query 的形态；doc 侧英文原文与含修饰语
    # 的问句靠此层，否则逐词直译拆散复合语义——第三方 LoCoMo 报告错译样本
    # scavenger hunt → 食腐动物 猎取 即此缺口。短语表键 ≤11 个，逐键扫描
    # 成本可忽略）。中文替换段经 findall 整体成原子，后续逐词链路不受影响
    inline_hits = []
    for phrase, pzh in COMPOUND_ZH_PHRASES:
        if phrase in query.lower():
            query = re.sub(re.escape(phrase), pzh, query, flags=re.IGNORECASE)
            inline_hits.append({"orig": phrase, "phrase_zh": pzh,
                                "action": "phrase_inline"})
    # 屈折还原 + 查表。所有格剥离：'s 是正字法黏着成分非独立词
    # （Melanie's → Melanie）——不剥离则分词残留 "s" 成为伪 OOV
    # （locomo-500 实测 85 词次）。
    words = re.findall(r"[A-Za-z\u4e00-\u9fff]+",
                       re.sub(r"'s\b", "", query))
    terms = []
    detail = []
    for w in words:
        wl = w.lower()
        base0 = strip_tense(wl)
        # 原形与还原形都查虚词表：getting/doing 屈折形原表漏网（还原后
        # get/do 是虚词，保留只产生 OOV 噪声原子）
        if wl in STOPWORDS or base0 in STOPWORDS:
            detail.append({"orig": w, "action": "stopword_drop"})
            continue
        base = base0
        zh = src = None
        for m, s in chain:
            z = m.get(base) or m.get(wl)
            if z:
                zh, src = z, s
                break
            if not base.endswith("e"):
                # e-脱落动词词表感知还原：loved→lov(错形)→love。词表小时收益≈0
                # （2026-09-14 早前取证 102 词次判不修）；词级表 17700 键后
                # motivated→motivate / visited 类命中真实存在，条件已变
                z = m.get(base + "e")
                if z:
                    base = base + "e"
                    zh, src = z, s
                    break
        if zh and is_proper(w) and wl not in EN_ZH:
            # 专名词表命中双原子：doc 侧音译/原文两形态并存（corpus567 实测
            # 地名 巴黎13/Paris4 音译主导，人名 Caroline127/卡罗琳0 原文主导）
            # ——原文+译文都进匹配面；未命中侧在 doc 侧零出现，组合共现需
            # 双方在场，不构成假匹配。手工表已有词（i/we/you 等句首大写代词、
            # 基础词）形态唯一，不具双形态不确定性，排除
            terms.append(w)
            terms.append(zh)
            detail.append({"orig": w, "base": base, "zh": zh, "source": src,
                           "low_confidence": src == "cedict",
                           "action": "proper_mapped_both"})
        elif zh:
            terms.append(zh)
            detail.append({"orig": w, "base": base, "zh": zh, "source": src,
                           "low_confidence": src == "cedict",
                           "action": "mapped"})
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
    return terms, inline_hits + detail


def low_confidence_terms(detail):
    """从归一化 detail 提取低置信映射词清单（去重保序）。

    低置信 = mapped 词来自 CEDICT 机械反查（第一义项直译，未经人工
    语境校对）。用途：错译审计靶子 / 词表人工校对优先级（警告不拒绝，
    与 semantic_oov 同哲学——标记是观测依据，不改检索行为）。
    """
    out = []
    for d in detail:
        if d.get("low_confidence"):
            w = (d.get("orig") or "").lower()
            if w and w not in out:
                out.append(w)
    return out


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
