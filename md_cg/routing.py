# -*- coding: utf-8 -*-
"""md 认知图 · 路由键归一化（风险1）

普查结论（wisdom-book-cloud-new.db, 3048 节点）：
  - 原始 condition_space 四元组作分桶键 → 3037 桶 / 3048 节点，99.9% 单例桶。
    根因：observation_position 实际格式是「<域> 知识点（<实例名>）」，把节点特有的
    实例名嵌进了条件字段，3033 种取值 ≈ 唯一。按它分桶 = 一节点一桶，查询侧
    构造不出精确匹配的情境 → 命中率≈0，召回归零（比退化成全量更糟）。
  - observation_tool(93% 集中) / existence_constraint(95% 集中) 去掉 position 后
    塌缩成单个巨桶。
  - time_window 实测仅 3 种取值，进哈希键是纯噪声。
  - tags 的 domain: 标签 → 95 桶 / 最大桶 5.4% / 期望扫描 1.8%，是唯一健康的键。

因此路由键 = 归一化提取的「域」，而非四元组哈希。写入侧与查询侧共用本模块，
保证两侧同构（风险2 的前提：查询构造的键必须与写入键落在同一空间）。
"""
import math
import re
import hashlib
import unicodedata

# observation_position 的实例名尾巴：「知识点（xxx）」「概念（xxx）」等
_INSTANCE_TAIL = re.compile(
    r"\s*(知识点|概念|条目|卡片|节点|规律|定理|公式)\s*[（(].*?[)）]\s*$"
)
# 骨架填充类后缀：「高中物理知识点内容（按骨架填充）」→「高中物理」
_SKELETON_TAIL = re.compile(r"(知识点)?内容\s*[（(]按骨架填充[)）]\s*$")

ORPHAN = "orphan"


# 生效条件：raw 为真值时按 NFKC 归一化并 strip，最多 3 轮剥离 _INSTANCE_TAIL（无变化即停）、再剥 _SKELETON_TAIL、空白转下划线后返回；raw 为假值（None/空串）或处理后为空串时返回 ORPHAN。
def normalize_domain(raw: str) -> str:
    """把自由文本的域描述归一化成稳定的短键。

    「工程学 知识点（内力与截面法）」        → 工程学
    「高中物理知识点内容（按骨架填充）」      → 高中物理
    「数学分析知识点内容（按骨架填充） 知识点（贝塞尔不等式）」 → 数学分析
    """
    if not raw:
        return ORPHAN
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    # 反复剥离实例名尾巴（可能叠加两层，见上面第三个例子）
    for _ in range(3):
        new = _INSTANCE_TAIL.sub("", s)
        if new == s:
            break
        s = new.strip()
    s = _SKELETON_TAIL.sub("", s).strip()
    s = re.sub(r"\s+", "_", s)
    return s or ORPHAN


# 生效条件：tags 为真值时取其中首个 str(t) 以 "domain:" 开头的项，返回其前缀后内容的 normalize_domain 结果；无此标签且 condition_space 为真值时返回 normalize_domain(condition_space.get("observation_position"))（缺键即 None 归一为 ORPHAN）；tags 为假值且 condition_space 为假值时返回 ORPHAN。
def route_key(condition_space: dict = None, tags=None) -> str:
    """导出条件路由键。优先级：tags 的 domain: > observation_position 归一化 > orphan。

    domain: 标签是显式声明的域，普查证明它分布最健康（95 桶/最大桶 5.4%），
    所以优先。没有标签时才回退到从 observation_position 提取。
    """
    for t in tags or []:
        t = str(t)
        if t.startswith("domain:"):
            return normalize_domain(t[len("domain:"):])
    if condition_space:
        return normalize_domain(condition_space.get("observation_position"))
    return ORPHAN


# 生效条件：key 等于 ORPHAN 时原样返回 ORPHAN；否则返回 "cond_" + 把 key 中非[\w中文-]字符替换为下划线并截前 24 字符的串 + "_" + key 的 sha256（utf-8）前 8 位十六进制。
def bucket_dir(key: str) -> str:
    """路由键 → 目录名。中文键保留可读前缀 + 短哈希，避免文件系统非法字符/超长。"""
    if key == ORPHAN:
        return ORPHAN
    safe = re.sub(r"[^\w\u4e00-\u9fff-]", "_", key)[:24]
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return f"cond_{safe}_{h}"


# 14 大域代表词表（白箱第 2 篇第 5 章 + 第 3 篇第 4 章：「56 学科卡 → 14 大域
# → 域内 KCCS」两阶段并行收敛。本表用作阶段 1 的大域并行打分依据——
# 当 query 没有显式 context 但 query 词能落进某个大域时，先收敛到大域再查。
#
# 词的选取原则：覆盖白箱工程文档里出现的高频学科关键词，且不互相吞并。
# 同一个词可以出现在多个大域（如「公式」在数学与物理都常见），这是合理的：
# 大域并行打分阶段就是让多域同分，再由阶段 2 的 KCCS 进一步区分。
BIG_DOMAINS = {
    "数学":   {"数学", "算术", "几何", "代数", "微积分", "概率", "统计", "集合", "矩阵",
              "线性", "拓扑", "数论", "公式", "定理", "证明", "函数", "导数", "积分",
              "极限", "方程", "不等式", "贝塞尔", "二分", "素数", "微元"},
    "物理":   {"物理", "力学", "电磁", "光学", "热学", "量子", "相对论", "能量", "动量",
              "质量", "速度", "加速度", "电荷", "电压", "电流", "沸点", "海拔",
              "大气压", "压强", "温度", "牛顿", "惯性", "引力"},
    "化学":   {"化学", "元素", "分子", "原子", "化合物", "反应", "酸", "碱", "盐",
              "氧化", "还原", "有机", "无机", "离子", "键", "浓度", "溶液"},
    "生物":   {"生物", "细胞", "基因", "蛋白质", "酶", "光合", "呼吸", "植物", "动物",
              "进化", "免疫", "神经", "细菌", "病毒", "代谢", "染色", "分裂"},
    "计算机": {"计算机", "算法", "数据结构", "编程", "代码", "软件", "网络", "数据库",
              "系统", "排序", "递归", "图论", "哈希", "索引", "查询", "排序", "锁",
              "事务", "内存", "进程", "线程"},
    "语言":   {"语言", "中文", "英文", "语法", "词汇", "语义", "修辞", "文学", "写作",
              "阅读", "拼音", "字", "词", "句"},
    "历史":   {"历史", "朝代", "战争", "文明", "政治", "经济史", "文化史", "古代",
              "近代", "现代", "王朝", "革命", "改革"},
    "地理":   {"地理", "地形", "气候", "人口", "城市", "国家", "地图", "板块",
              "洋流", "经度", "纬度", "海拔带", "流域"},
    "艺术":   {"艺术", "绘画", "音乐", "雕塑", "电影", "设计", "色彩", "构图",
              "旋律", "节奏", "摄影"},
    "经济":   {"经济", "市场", "金融", "货币", "投资", "股票", "债券", "GDP",
              "通胀", "财政", "税收", "供需"},
    "心理":   {"心理", "认知", "情感", "记忆", "学习", "性格", "行为", "意识",
              "动机", "人格", "焦虑"},
    "医学":   {"医学", "疾病", "治疗", "药物", "诊断", "外科", "内科", "儿科",
              "中医", "症状", "病理", "处方"},
    "工程":   {"工程", "建筑", "结构", "材料", "机械", "电子", "土木", "桥梁",
              "内力", "截面", "梁", "柱", "应力"},
    "通用":   {"常识", "生活", "日常", "通用", "礼仪", "礼貌", "文明", "规则"},
}


# 生效条件：terms 为真值时对 BIG_DOMAINS 每个大域统计命中词数，最高分为 0 或 terms 为假值（None/空）时返回 None，否则返回最高分大域名（并列取 BIG_DOMAINS 迭代序首个最高分）。
def big_domain_classify(terms) -> str | None:
    """阶段 1：14 大域并行打分 → 收敛到 top-1。

    terms 是 expand_query_terms 返回的扩展词集合。
    大域打分 = query 词命中大域代表词的次数（多词同域累加）。
    并行在认知结构意义上：即使底层串行计算，14 个大域同时独立评估。

    返回最匹配的大域名（多个 0 分 → 返回 None，走原 bucket_dir 路由）。
    """
    if not terms:
        return None
    scores = {}
    for d, vocab in BIG_DOMAINS.items():
        scores[d] = sum(1 for t in terms
                        if any(w in t or t in w for w in vocab))
    best = max(scores.items(), key=lambda x: x[1])
    if best[1] == 0:
        return None
    # 多大域并列最高分时，按字典序取第一个稳定结果（避免浮点不确定）
    return best[0]


# 生效条件：terms 为假值（None/空）时返回 {每个 BIG_DOMAINS 域: 0}；terms 为真值时返回 {大域: 该域词表命中 terms 中词的个数}。
def big_domain_score_breakdown(terms) -> dict:
    """暴露打分明细，便于审计与回归测试。"""
    if not terms:
        return {d: 0 for d in BIG_DOMAINS}
    return {d: sum(1 for t in terms if any(w in t or t in w for w in vocab))
            for d, vocab in BIG_DOMAINS.items()}


# ---------------------------------------------------------------------------
# 分级隶属度（模糊控制「隶属函数」的手写版）
#
# 上面的 big_domain_classify 是二值控制：`w in t or t in w` 命中即计 1。
# 下面是同一套规则库的**分级**版本——命中程度是 0~1 的连续值，并乘 IDF：
#   · 隶属度 membership(t, w)：完全相同 1.0；包含关系取长度比（覆盖越全越高）
#   · IDF：一个代表词覆盖的大域越少，区分度越高（「贝塞尔」只在数学出现，
#     权重高于「公式」这种跨域通用词）
# 老函数保持不动 → P0/P1 基线可比性不受影响；新函数只供新路径（fuzzy）使用。
# ---------------------------------------------------------------------------

# 生效条件：term 或 word 为假值（None/空串）返回 0.0；相等返回 1.0；word 是 term 子串返回 len(word)/len(term)；term 是 word 子串返回 len(term)/len(word)；二者无包含关系返回 0.0。
def membership(term: str, word: str) -> float:
    """词 term 对代表词 word 的隶属度（0.0~1.0，越接近 1 越隶属）。

    完全相同            → 1.0
    term 包含 word      → len(word)/len(term)（覆盖越全越隶属）
    word 包含 term      → len(term)/len(word)
    无包含关系          → 0.0
    """
    if not term or not word:
        return 0.0
    if term == word:
        return 1.0
    if word in term:
        return len(word) / len(term)
    if term in word:
        return len(term) / len(word)
    return 0.0


# 生效条件：无入参，恒遍历模块级常量 BIG_DOMAINS 的各域代表词表，返回 {代表词: 包含该词的域个数}。
def _build_domain_df() -> dict:
    """代表词 → 覆盖它的大域数（IDF 的分母）。"""
    df = {}
    for vocab in BIG_DOMAINS.values():
        for w in vocab:
            df[w] = df.get(w, 0) + 1
    return df


_DOMAIN_DF = _build_domain_df()


# 生效条件：恒返回 math.log(1.0 + len(BIG_DOMAINS) / _DOMAIN_DF.get(word, 1))，即 word 在 _DOMAIN_DF 中取其覆盖域数，缺键（含任何未登记值）时按 _DOMAIN_DF.get 的默认 1 代入。
def domain_idf(word: str) -> float:
    """代表词的区分度权重：log(1 + 大域总数 / 覆盖它的大域数)。

    只在一个大域出现的词（如「贝塞尔」）≈ log(15)=2.71；
    14 个大域都出现的词（如「公式」）≈ log(2)=0.69。
    """
    return math.log(1.0 + len(BIG_DOMAINS) / _DOMAIN_DF.get(word, 1))


# 生效条件：terms 是 dict 时以其条目（键 str(t) 以 "__" 开头者剔除、值为 float）为词权重并忽略 weights，否则以 wmap.get(t, 1.0) 为权重（weights 为假值即 None/空 dict 时 wmap 为空、全部权重取 1.0，terms 为假值则词集为空）；逐域累加「词权重 × 该词在域词表内最大（membership × domain_idf）」，权重 <=0 的词跳过，返回 {大域: round(得分, 6)}。
def big_domain_score_weighted(terms, weights=None) -> dict:
    """阶段 1（分级版）：14 大域并行打分，按「隶属度 × IDF」加权。

    terms: 可迭代的词集合，或 {词: 权重}（expand_query_terms_weighted 的输出，
           调用方需先剔除 "__source__" 等元数据键）。
    weights: terms 为可迭代时的可选权重表；terms 已是 dict 时忽略。
    返回 {大域: 得分}，得分不再是整数计数，而是连续值。
    """
    if isinstance(terms, dict):
        tw = {str(t): float(w) for t, w in terms.items()
              if not str(t).startswith("__")}
    else:
        wmap = weights or {}
        tw = {str(t): float(wmap.get(t, 1.0)) for t in (terms or [])}
    out = {}
    for d, vocab in BIG_DOMAINS.items():
        s = 0.0
        for t, tw_ in tw.items():
            if tw_ <= 0:
                continue
            best = 0.0
            for w in vocab:
                m = membership(t, w)
                if m > 0.0:
                    best = max(best, m * domain_idf(w))
            s += tw_ * best
        out[d] = round(s, 6)
    return out


# 生效条件：以 terms、weights 计算各域加权得分（terms 为假值时各域均为 0.0），得分为空或最高分 <= min_score（默认 0.0）时返回 None，否则返回最高分大域名。
def big_domain_classify_weighted(terms, weights=None, min_score: float = 0.0):
    """阶段 1（分级版）收敛到 top-1；全部低于 min_score → None。"""
    scores = big_domain_score_weighted(terms, weights)
    if not scores:
        return None
    best = max(scores.items(), key=lambda kv: kv[1])
    if best[1] <= min_score:
        return None
    return best[0]


# 生效条件：a 或 b 为假值（None/空串）返回 0.0；相等返回 1.0；a 是 b 子串返回 len(a)/len(b)；b 是 a 子串返回 len(b)/len(a)；否则按二者二元组字符集合的 Jaccard 返回 len(ga & gb)/len(ga | gb)，任一集合为空（如单字符键）时返回 0.0。
def domain_similarity(a: str, b: str) -> float:
    """两个归一化域键的相似度（0~1）：相同 1.0；包含取长度比；否则二元组 Jaccard。

    「计算机科学」vs「计算机」→ 0.6（包含）；「高中物理」vs「物理」→ 0.5；
    完全无关 → 0.0。用于 fuzzy 路径的「大域亲和」打分。
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b:
        return len(a) / len(b)
    if b in a:
        return len(b) / len(a)
    ga = {a[i:i + 2] for i in range(len(a) - 1)}
    gb = {b[i:i + 2] for i in range(len(b) - 1)}
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


# 生效条件：counts 各值之和为 0（含空 dict 与全 0 计数）时返回 {'ok': True, 'reason': 'empty', 'buckets': 0}；否则在最大桶占比 >30%、桶数 >1 且单例桶占比 >50%、期望扫描 >30% 中命中的项写入 problems，返回含 ok(=problems 为空)、buckets、nodes、max_bucket_share、singleton_ratio、expected_scan、problems 的 dict。
def bucket_health(counts: dict) -> dict:
    """分区健康度自检。分桶键一旦退化（巨桶或碎片化），条件路由就是纸面收益，
    必须在写入侧就能发现，而不是等召回变差才回头查。

    counts: {bucket_dir: node_count}
    """
    n = sum(counts.values())
    if not n:
        return {"ok": True, "reason": "empty", "buckets": 0}
    nb = len(counts)
    top = max(counts.values())
    singles = sum(1 for v in counts.values() if v == 1)
    # 期望扫描占比：随机取一节点的情境去路由，命中桶的期望大小占全库比例
    expected_scan = sum(v * v for v in counts.values()) / n / n
    problems = []
    if top / n > 0.30:
        problems.append(f"巨桶：最大桶占 {top / n:.1%}（>30% 视为分区失效）")
    if nb > 1 and singles / nb > 0.50:
        problems.append(f"碎片化：单例桶占 {singles / nb:.1%}（>50% 说明键含实例级字段）")
    if expected_scan > 0.30:
        problems.append(f"路由无效：期望扫描 {expected_scan:.1%}（接近全量）")
    return {
        "ok": not problems,
        "buckets": nb,
        "nodes": n,
        "max_bucket_share": top / n,
        "singleton_ratio": singles / nb if nb else 0.0,
        "expected_scan": expected_scan,
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# 节点侧大域标签（S1 大域先验收敛的前置元数据）
#
# 为何需要：`big_domain_classify` 一直只作用于 **query 侧**（terms），节点侧没有域字段，
# 于是「14 大域并行打分」算完只能写进 meta（审计偏差 4：先验算出来却当成报告）。
# 要让大域先验真正参与候选收敛，节点必须在写入时固化自己的域。
# 口径：与查询侧同一个分类器（BIG_DOMAINS + big_domain_classify），保证两侧同构。
# ---------------------------------------------------------------------------

# 域词取词：中文（≥2 字）与拉丁词（≥2 字）。词表命中用「包含关系」判定，
# 故 2 字以上的切口足以覆盖 1~4 字代表词（如「工程」命中「工程师」）。
DOMAIN_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_]{1,}")


# 生效条件：text 为假值（None/空串）时返回 []；否则以 DOMAIN_TERM_RE 取词、按出现顺序去重后返回，
# 最多 limit 个（limit 为假值/负数时按空处理，返回 []）。
def domain_terms(text, limit: int = 400) -> list:
    """从节点正文/标题抽「域词」（供 big_domain_classify 使用）。

    只做最小分词：中文按 ≥2 字连续片段、拉丁按 [A-Za-z][A-Za-z0-9_]+ 取词；
    去重保序，最多 limit 个（默认 400，避免长文把分类器拖慢）。
    """
    if not text or not limit or limit < 1:
        return []
    out, seen = [], set()
    for m in DOMAIN_TERM_RE.finditer(str(text)):
        w = m.group(0)
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= limit:
            break
    return out


# 生效条件：bucket 为假值或等于 ORPHAN 时返回空串；否则去掉 "cond_" 前缀、并当末段为 8 位十六进制哈希时剥掉该段，返回剩余的可读键。
def bucket_key_readable(bucket: str) -> str:
    """桶目录名 → 可读键（S1b query 侧桶推断用）：'cond_感知系统_d94e90d2' → '感知系统'。

    与 `bucket_dir` 互逆（丢哈希段）；`orphan`/空值返回空串（S1b 不把 orphan 当键，orphan 恒作兜底）。
    """
    if not bucket or bucket == ORPHAN:
        return ""
    s = str(bucket)
    if s.startswith("cond_"):
        s = s[len("cond_"):]
    head, sep, tail = s.rpartition("_")
    if sep and len(tail) == 8 and all(c in "0123456789abcdef" for c in tail):
        s = head
    return s


# 生效条件：text 为假值或取不到任何域词时返回 None；否则返回 big_domain_classify(domain_terms(text))
# 的结果（无有效域信号时亦为 None，调用方据此决定是否落域字段）。
def classify_text(text, limit: int = 400):
    """正文 → 大域名（节点侧域标签真源）。与查询侧共用 big_domain_classify。

    返回 None 表示「无有效域信号」——此时**不写** big_domain 字段，
    该节点留在 ORPHAN/兜底池（S1 收敛时必须能被兜底召回，见契约 §3 S1 不变量）。
    """
    return big_domain_classify(domain_terms(text, limit))