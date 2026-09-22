# -*- coding: utf-8 -*-
"""md 认知图 · 存储、检索与认知循环

对齐白箱认知架构（《白箱智能是什么？》系列·第 1-5 篇）：
  五层记忆（anchor/structural/knowledge/contextual/self）
  + 两类负记忆（rejected 失败/否决、unresolved 未解问题，第 5 篇 L2/L5）
  + 条件路由（rec_content 优先 + 条件路由到桶）
  + 四态资格判定（ACCEPT/REJECT/DEFER/BLINDSPOT，与性能 tier 正交）
  + 验证基底（verification_basis：白箱信任的硬门槛）

P0 风险（基线功能）：
  风险1 分桶键退化 → routing.route_key 归一化（普查驱动）+ 健康度自检
  风险2 检索无情境入参 → search(context=...)，无情境时显式不走路由
  风险3 回退语义被改变 → 分级阶梯 T0..T3，结果标注 tier
  风险4 检索变写操作 → 访问计数走 append-only 日志

索引是派生物：节点 .md 是唯一真相源，_index.json 随时可由 rebuild_index() 重建。
"""
import os
import re
import json
import time
import atexit
import weakref
import hashlib
import threading

from . import (nodefile, protect, routing, subgraph, chain, provenance, pooling,
               lifecycle, reach, trust, roleviews)
from .fsutil import (FileLock, ShardedLog, atomic_write, append_jsonl,
                     read_jsonl, sweep_stale_temps)

# 五层 + 两类负记忆 + 目标槽（白箱记忆七件套工程化：事实/规则→knowledge；
# 假设→contextual；失败/未解→独立目录；目标→goals）。
# 第 5 篇第 3 章：「没有目标，检索就没有方向」——goals 层不参与词法正排，
# 只作为检索定向（goal 路）的偏置来源，默认不启用，保持既有基线可比。
LAYERS = ("anchor", "structural", "knowledge", "contextual", "self",
          "rejected", "unresolved", "goals")
# 有条件分区的层：knowledge 是主检索层；负记忆/目标目录按自己的 MARKS 走，不路由
BUCKETED_LAYERS = ("knowledge",)

# ---- S4 层级激活优先级（契约 §3 S4）----
# 认知优先级：anchor/self（自我与锚点）先激活，其次 structural，再次 knowledge/contextual。
# 语义是**加成**而非过滤：只改初始激活值/排序，不改变任何门控（不会把被门控剔除的节点拉回来）。
LAYER_BOOST_DEFAULT = {
    "anchor": 0.20, "self": 0.20, "structural": 0.15,
    "knowledge": 0.10, "contextual": 0.05,
}


# 生效条件：env 为假值（None/空串）时返回 LAYER_BOOST_DEFAULT 的副本；否则按「层=值,层=值」解析，
# 忽略无等号的项与不可转 float 的值（负值夹到 0.0），未出现的层保留默认值，返回合并后的 dict。
def layer_boosts(env=None) -> dict:
    """层级加成表：`MDCG_LAYER_BOOST="anchor=0.3,knowledge=0.05"`（部分覆盖，未提及的层取默认）。"""
    out = dict(LAYER_BOOST_DEFAULT)
    raw = env if env is not None else os.environ.get("MDCG_LAYER_BOOST", "")
    if not raw:
        return out
    for part in str(raw).split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            out[k.strip()] = max(0.0, float(v.strip()))
        except ValueError:
            continue
    return out
# 负记忆的 MARKS 必填（与 knowledge 的 5 要素不同）
NEG_MEMORY_MARKS = {
    "rejected":   ("假设", "否决原因", "验证"),
    "unresolved": ("问题", "已知线索", "目标"),
}
SCHEMA = 2

# 目标槽状态机（白箱第 5 篇第 3 章「目标」）：active 才参与检索定向。
GOAL_STATUSES = ("active", "done", "dropped")

# 可信度降级阈值（白箱第 5 篇第 4 章「可信度分级」）：knowledge 层节点
# confidence 跌破该值 → 降级为 contextual（假设层），并留 demotion 审计记录。
# 假设层不再二次降级（它本来就是假设）。默认 0.2：从 0.6 起需连续 3 次 weakened。
DEMOTE_CONFIDENCE = 0.2

# 近期事件滚动窗口（白箱第 5 篇第 3 章「近期事件」）：保留最近 N 条原始事件，
# 保证当前任务的连续性。只做 append + 截断，不参与词法正排（不稀释既有基线）。
DEFAULT_RECENT_WINDOW = 200

# 全量回退的读取上限，对齐 sqlite 版 `ORDER BY importance DESC, created_at DESC LIMIT 500`
GLOBAL_CAP = 500

# ---------- 索引持久化 · 进程退出兜底（2026-09-16 取证） ----------
# 脏索引（`_dirty`）靠调用方显式 flush()/close() 落分片日志。一次性脚本/CLI
# （review_cli、backfill、migrate_* 等）写入 1~2 条后直接退出，未达 autoflush(64)
# 阈值 → 日志无记录；而**已有 `_index.json` 的根重开时不重扫目录**，于是节点
# 「在盘上但索引无条目」：其它进程与重载后的长驻进程都检索不到，只能靠某次全量
# rebuild_index() 偶然救回（首例=审核裁决通路，见 mdcos.review_decide）。
# 兜底语义（刻意收窄）：**正常进程退出时**对所有存活实例补一次 close()——
# 幂等（`_dirty` 为空即 no-op）、不改变正常路径行为、不替代显式收尾
# （异常退出 / 被 kill 仍须调用方自己保证）。WeakSet 不阻止实例回收。
_LIVE_CGS = weakref.WeakSet()
_ATEXIT_HOOK = None


# 生效条件：当模块级 `_LIVE_CGS` 含实例时，函数对每个实例调用 close() 并吞掉异常，不返回值。
def _atexit_flush_all():
    """进程退出兜底：把仍存活实例的脏索引落盘（异常吞掉——退出路径不该再抛）。"""
    for cg in list(_LIVE_CGS):
        try:
            cg.close()
        except Exception:  # noqa: BLE001
            pass


# 生效条件：当模块级 `_ATEXIT_HOOK` 为 None 时注册 `_atexit_flush_all` 并缓存为 `_ATEXIT_HOOK`，否则直接返回已缓存的 `_ATEXIT_HOOK`。
def _register_atexit_hook():
    global _ATEXIT_HOOK
    if _ATEXIT_HOOK is None:
        atexit.register(_atexit_flush_all)
        _ATEXIT_HOOK = _atexit_flush_all
    return _ATEXIT_HOOK


# 生效条件：当 `len(scored)` 与 `len(docs)` 不一致时，该分支不按 `scored` 排序而直接返回 `cut_report(docs, total, ...)` 并在 `stat` 非 None 时标记 `insert_fallback`；二者同长时按 `scored` 排序后截断到 `total` 并返回 `cut_report(ranked, total, ...)`。
def cut_by_relevance(docs, scored, total, pools=None, key_of=None, stat=None):
    """候选截断：**先按相关度排序，再截断到 `total`**（截断依据=相关度）。

    动机（真库实测 2026-09-16，11521 节点 / cap=500）：原实现是「LIKE 命中集
    沿 `entries`（目录枚举序）取前 `total` 条 → 再打分」——命中集超上限时，
    等价于用**写入顺序抽签**决定谁进候选池。实测 40 个抽样查询中 27 个命中数
    超 cap（最差 10963/11073 ≈ 99%），被现状丢弃的候选平均分 0.650、被保留的
    平均分 0.340，gold 进 top10 由 19/40 降至 29/40。

    本函数把 cap 语义从「候选生成上限」降级为「输出上限」：候选质量责任交还
    排序（与 `mdcos._lexical` 同源先例一致），**cap 值本身不变**。

    `docs` 与 `scored` 必须同序同长（`MdCG._score` 输出序=输入序）。不一致时
    不猜：退回原序截断，并在 `stat["cut_order"]` 标 `insert_fallback` 供审计。
    分池生效时在**分数序**内按池额度截断（池内原序=分数序）。
    返回 `(picked, report)`。
    """
    if len(scored) != len(docs):
        if stat is not None:
            stat["cut_order"] = "insert_fallback"
        return pooling.cut_report(docs, total, pools=pools,
                                  key_of=key_of or pooling.doc_key)
    order = sorted(
        range(len(docs)),
        key=lambda i: (-float(scored[i][1]),
                       -float(scored[i][0]["frontmatter"].get("importance") or 0),
                       -float(scored[i][0]["frontmatter"].get("created_at") or 0),
                       # 终键：三级全等时按 nid 定序。没有它，sorted 的**稳定性**
                       # 会把顺序回落到输入序（docs = index["nodes"] 物理序），
                       # 于是「同分同权重同写入时刻」的结果顺序随写入序/重建序漂移
                       # —— 索引重建前后不可复现（S6 幂等实测：created_at 被量化到
                       # ~1ms，4 次快速写入常两两碰撞，导致 ~50% 概率重建后换序）。
                       str(scored[i][0].get("id") or "")))
    ranked = [docs[i] for i in order]
    if stat is not None:
        stat["cut_order"] = "relevance"
    return pooling.cut_report(ranked, total, pools=pools,
                              key_of=key_of or pooling.doc_key)

# 条件论「观测时间」栏的默认观测窗口（秒）：调用方未提供 time_window 时，
# 以写入时刻为锚开一个 1 小时窗口（与 AEIS 既有约定一致）。
OBSERVATION_WINDOW_SEC = 3600.0

# 与 aeis.core.LayeredStore.SYNONYM_GROUPS 保持一致（检索结果可比性的前提）
SYNONYM_GROUPS = [
    {"视觉", "图像", "画面", "图片", "影像", "视像"},
    {"语义", "含义", "意思", "意义", "概念"},
    {"识别", "检测", "感知", "探测", "发现"},
    {"转换", "转化", "映射", "变换"},
    {"实验", "试验", "集成", "实现", "验证", "测试"},
    {"评测", "评估", "跑分", "基准", "benchmark", "评审", "考核"},
    {"记忆", "记录", "库"},
    {"智能", "智能体", "灵枢", "AI"},
    {"语音", "声音", "音频", "说话"},
    {"对话", "聊天", "交流"},
]

# 加权同义词组（分级隶属度）：组内每个词对「组心」的隶属度 0.3~1.0。
# 与 SYNONYM_GROUPS 并存而非替换——老函数 expand_query_terms 保持二值展开，
# P0/P1 基线可比性不受影响；新函数 expand_query_terms_weighted 用本表。
# 权重含义：1.0 = 组心（完全隶属）；0.9 = 近义；0.6~0.8 = 强相关；
# 0.3~0.5 = 弱相关（只在长查询里做低权补充，避免稀释主词）。
SYNONYM_GROUPS_WEIGHTED = [
    {"视觉": 1.0, "图像": 0.9, "图片": 0.9, "画面": 0.8, "影像": 0.7, "视像": 0.6},
    {"语义": 1.0, "含义": 0.8, "意思": 0.8, "意义": 0.8, "概念": 0.7},
    {"识别": 1.0, "检测": 0.9, "感知": 0.7, "探测": 0.7, "发现": 0.5},
    {"转换": 1.0, "转化": 0.9, "变换": 0.8, "映射": 0.7},
    {"实验": 1.0, "试验": 0.9, "验证": 0.6, "测试": 0.6, "实现": 0.4, "集成": 0.4},
    {"评测": 1.0, "评估": 0.9, "benchmark": 0.8, "基准": 0.7, "跑分": 0.6,
     "评审": 0.5, "考核": 0.5},
    {"记忆": 1.0, "记录": 0.7, "库": 0.3},
    {"智能": 1.0, "智能体": 0.8, "AI": 0.7, "灵枢": 0.6},
    {"语音": 1.0, "声音": 0.8, "音频": 0.8, "说话": 0.4},
    {"对话": 1.0, "聊天": 0.8, "交流": 0.6},
]

# 性能回退阶梯（怎么找到的）
TIER_BUCKET_LIKE = "T0_bucket_like"
TIER_BUCKET_SCAN = "T1_bucket_scan"
TIER_GLOBAL_LIKE = "T2_global_like"
TIER_GLOBAL_SCAN = "T3_global_scan"
# S3 图扩散激活（契约 §3 S3）：从词法命中节点沿 edges 扩散得到的候选，单独成层以便审计
TIER_SPREAD = "T2b_spread_activation"

# 资格判定四态（该不该用——白箱第 1 篇核心）
STATE_ACCEPT = "ACCEPT"           # 条件满足，有资格执行
STATE_REJECT = "REJECT"           # 条件冲突/不适用条件命中，明确不适用
STATE_DEFER = "DEFER"             # 条件不足但可继续寻找缺失条件
STATE_BLINDSPOT = "BLINDSPOT"     # 无法建立可靠归属，停止猜测

# 验证基底（白箱第 2 篇第 7 章：能被验证才能被信任）
VERIFICATION_BASIS = nodefile.VERIFICATION_BASIS


# 英→中语素召回中的代词黑名单（超泛词，进召回词只添噪声）
_EN_ZH_PRONOUNS = {"我", "你", "他", "她", "它", "我们", "你们", "他们"}


# 生效条件：无 required 形参，锚定环境变量名 MDCG_SEMANTIC；当 os.environ.get("MDCG_SEMANTIC") == "1" 时返回 True，否则返回 False。
def semantic_on() -> bool:
    """语义摘要路开关（MDCG_SEMANTIC=1，默认关闭零回归）。

    开启时两件事生效（设想「摘要作为检索面」的两层）：
    1. 候选资格：fm.semantic 节点无条件进入 LIKE 候选池（否则摘要层只在
       LIKE 全空时才生效，形同虚设——e2e 实证：干扰文档的弱词法 2-gram
       碰撞会把 gold 挡在打分池外）；
    2. 打分面：_score 组合窗口共现分与词法分 max 聚合。
    老库（节点无 semantic 字段）行为逐位不变。
    """
    return os.environ.get("MDCG_SEMANTIC") == "1"


# 生效条件：当 `text` 含英文字母且环境变量 `MDCG_EN_ATOMS` 为 `'1'` 且 `normalize_en_query` 可用时，返回小写化并过滤后的中文语素列表；`text` 无字母、开关未开或归一化异常时返回 `[]`。
def en_zh_terms(text: str) -> list:
    """原子级中英归一 v1（2026-09-13 管线接入）：英文词 → 中文语素召回词。

    依据：英文 query 词面与中文语料零重叠（bench6 实测英文 hit@1 41% vs 中文 95%
    的主因），形态归一（normalize_en）救不了跨语——beef 与「牛肉」无任何共享字符。
    语义.en_normalizer 词表映射（时态归零→停用词剔除→英→中语素/复合词映射→
    专有词保留）产出中文检索键，直接命中中文正文。

    约束（与 cn_recall_grams 同模式）：
      - 本函数只扩召回（terms/LIKE 资格）；打分侧由 en_zh_bigrams 显式负责
        （search/_lexical 三处 qb 均已补充），两者同受 MDCG_EN_ATOMS 开关控制；
      - 默认关闭（MDCG_EN_ATOMS=1 显式开启）：md_cg 主链路英文检索走
        独立归一化原子+Jaccard 路（REPRODUCE.md 双语双路裁定，md_cg
        char-bigram 管线跑英文实测比独立方案差 25% vs 52%），本集成为
        opt-in 实验能力与 soul hub 序列化出口，不在默认链路生效；
      - 仅当 query 含英文字母时触发，纯中文 query 零开销零变化；
      - 代词语素剔除（我/你/他…超泛词防污染），动词/名词单字语素保留
        （「吃/雨」在中文正文检索价值高，_score 终排兜底精度）；
      - semantic 模块缺失时静默降级（不阻断主链路）。
    词表未覆盖词保留原名（unknown_keep），是词表边界而非错误。
    """
    if os.environ.get("MDCG_EN_ATOMS", "0") != "1":
        return []
    if not re.search(r"[A-Za-z]", text or ""):
        return []
    try:
        from .semantic.en_normalizer import normalize_en_query
        terms, _detail = normalize_en_query(text)
    except Exception:
        return []
    # 专有词/未知词保留原名是序列化语义；作为检索键必须统一小写
    # （与 normalize_en 口径一致，避免大小写敏感 LIKE 意外命中）
    return [t.lower() for t in terms
            if t and (len(t) >= 2 or t not in _EN_ZH_PRONOUNS)]


# 生效条件：当 `text` 经 `en_zh_terms` 产出非空语素时，返回长度≥2 的语素集合与相邻中文语素拼接的 char-bigram 并集；语素为空时返回空集。
def en_zh_bigrams(text: str) -> set:
    """英→中语素的打分侧补充：中文语素进 query bigram 集合。

    背景：en_zh_terms 只扩 LIKE 召回资格，而 _score/_lexical 的词法分
    = lexical_sim(qb, doc_bigrams)——英文 bigram 与中文文档恒零交集
    （跨语场景词法分全 0、排序退化到扫描序，2026-09-13 端到端实测）。
    「牛肉/昨天」等中文语素本身是合法 bigram，补进 qb 后与中文正文
    bigram（牛肉面→{牛肉,肉面}）正常相交，词法分恢复区分度。

    拼接升级（2026-09-14 盲测实证）：单字语素（马/肉/油…）被 len>=2
    过滤后打分侧仍空集→跨语词法分恒 0→top5 全为 0 分扫描序干扰
    （bench_blind_comp：词表补齐后 hit@1 反而 36.4%→27.3%，证明基线
    命中全靠小候选集扫描序运气而非排序能力）。现把相邻中文语素按
    query 词序拼接成 char-bigram（[马,肉]→「马肉」），与本仓主链路
    char-bigram 口径同构（英文 query 译中文串再取 bigram）。
    噪声边界：跨语素拼接 bigram（吃牛肉→「吃牛」「肉昨」）可与语义
    相邻文档假相交，由 Jaccard 分母稀释，_score 终排兜底精度。

    纯中文 query 零变化（en_zh_terms 不触发）；与 en_zh_terms 同受
    MDCG_EN_ATOMS 开关控制（默认关闭）。
    """
    terms = en_zh_terms(text)
    grams = {t for t in terms if len(t) >= 2}
    # 相邻中文语素拼接：query 词序即语素序（horse meat→马 肉→「马肉」）
    zh_seq = [t for t in terms if t and all("\u4e00" <= ch <= "\u9fff" for ch in t)]
    joined = "".join(zh_seq)
    grams |= {joined[i:i + 2] for i in range(len(joined) - 1)}
    return grams


# 生效条件：当 `query` 为字符串时，返回整句、≥2 字符分词、同义词组展开、`cn_recall_grams` 及（若 `MDCG_EN_ATOMS=1`）英→中语素去重后的列表；无扩展项时至少含归一化整句。
def expand_query_terms(query: str) -> list:
    """与 aeis.core 同实现：整句 + 分词（≥2字符）+ 同义词组展开 + 英文归一化
    + 英→中语素召回扩展（en_zh_terms，MDCG_EN_ATOMS=1 开启，默认关）。"""
    # 原子级中英归一：在 normalize_en 之前取（专有词首字母大写判断依赖原始形态）
    _en_zh = en_zh_terms(query)
    # 英文归一化（中文不动；小写化+去停用词+去时态复数）
    query = normalize_en(query)
    terms = [query]
    for w in re.split(r"[\s、，。；：,;.:/\\|]+", query):
        w = w.strip()
        if len(w) >= 2 and w not in terms:
            terms.append(w)
    for group in SYNONYM_GROUPS:
        for w in group:
            if w in query:
                terms.extend(g for g in group if g not in terms)
                break
    # 构词法 v1：中文连续串 2-gram 召回扩展（只增召回，不改打分口径）
    for g in cn_recall_grams(query):
        if g not in terms:
            terms.append(g)
    # 原子级中英归一 v1：英→中语素召回扩展（与 cn_recall_grams 同模式：只增召回）
    for t in _en_zh:
        if t not in terms:
            terms.append(t)
    return list(dict.fromkeys(terms))


# 生效条件：当 `s` 为字符串时，先去掉空白字符；去空白后长度≤1 返回 `{s}`，否则返回所有相邻 2-gram 集合。
def bigrams(s: str) -> set:
    s = "".join(s.split())
    if len(s) <= 1:
        return {s}
    return {s[i:i + 2] for i in range(len(s) - 1)}


# 中文高频功能 bigram（召回扩展时剔除：纯语法组合，召回价值低、噪音高）
CN_STOP_GRAMS = {
    "的了", "是一", "的在", "有个", "就是", "不是", "没有", "这个", "那个",
    "我们", "你们", "可以", "一个", "的话", "来说", "关于", "对于", "还是",
}


# 生效条件：当 query 非空且环境变量 MDCG_CN_GRAMS 不为 "0" 时，对 query 中长度 ≥ max(min_run,2) 的连续中文串切 2-gram，去重且排除 CN_STOP_GRAMS，最多 cap 个返回；MDCG_CN_GRAMS=="0" 或 query 为假值时返回 []（cap<=0 仍会 append 后立即返回首个 gram）。
def cn_recall_grams(query: str, min_run: int = 4, cap: int = 16) -> list:
    """构词法 v1 · 中文召回扩展：把连续中文串切成 2-gram 作为额外召回键。

    背景（2026-09-13 诊断）：expand_query_terms 对无标点中文查询只产出「整句」
    一个召回词，而 _like 要求正文原样包含整句才给召回资格 —— 导致「抑制剂怎么选」
    无法召回含「酪氨酸激酶抑制剂」的节点（部分中文无法词匹配的机制断点）。

    约束：只扩召回，不改打分口径（bigrams(q) 的 _score 不变）；纯标准库，零依赖；
    仅当中文连续串 ≥ min_run 字时触发（短词本身已是召回词，无需扩展）。
    """
    if os.environ.get("MDCG_CN_GRAMS") == "0":   # A/B 开关：关闭即回退旧行为
        return []
    out = []
    for run in re.findall(r"[\u4e00-\u9fff]{%d,}" % max(min_run, 2), query or ""):
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            if g in CN_STOP_GRAMS or g in out:
                continue
            out.append(g)
            if len(out) >= cap:
                return out
    return out


# ---- 英文归一化（与中文 cn_recall_grams 对称的英文预处理）----
# 设计者裁定：大小写统一转小写；停用词（the 等）不能拆成 bigram 参与匹配；
# 时态/复数归零（walked→walk, pets→pet），与语义层原子化原则一致。
EN_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "will", "would", "could",
    "should", "may", "might", "of", "to", "in", "on", "at", "for", "with",
    "by", "from", "up", "about", "into", "over", "after", "and", "or",
    "but", "not", "no", "so", "if", "then", "than", "also", "very",
    "what", "which", "who", "how", "why", "when", "where",
    "this", "that", "these", "those", "it", "its", "as", "there",
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "they", "them", "their",
})

EN_IRREGULAR = {
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

# 生效条件：当 `w` 为英文单词字符串时，先查 `EN_IRREGULAR` 映射，否则按保守后缀规则（-ing/-ed/-ies/-es/-s 等长度阈值）返回归一化词形；不适用规则时原样返回 `w`。
def strip_tense_en(w: str) -> str:
    """英文时态/复数归零（保守策略：宁可少剥不可误剥）"""
    if w in EN_IRREGULAR:
        return EN_IRREGULAR[w]
    # -ous 结尾 = 形容词不是复数（courageous/famous/various）
    if w.endswith("ous") or w.endswith("us") or w.endswith("is"):
        return w
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]
    if w.endswith("ed") and len(w) > 4:
        return w[:-2]
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    # -es 只剥真复数（boxes→box, watches→watch），不剥 motivates→motivate
    if re.search(r'(ch|sh|ss|x|z)o?es$', w) and len(w) > 4:
        return w[:-2]
    # -s 剥离（motivates→motivate, pets→pet）
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w

# 生效条件：给定 text（假值按 "" 处理），先清除非中文/空格/字母数字字符，再对长度 ≥2 的英文词小写、若在 EN_STOPWORDS 中剔除否则 strip_tense_en 去时态复数，压缩空白后返回；中文保持不变。
def normalize_en(text: str) -> str:
    """英文归一化：小写 + 去停用词 + 去时态复数。中文部分不动。

    设计者裁定：
      - 大小写统一转小写匹配
      - 停用词（the 等）不能拆成 bigram 参与匹配（整词剔除）
      - 时态/复数归零（walked→walk, pets→pet）
    """
    # 清标点（保留中文字符和空格和数字）
    cleaned = re.sub(r'[^\u4e00-\u9fff a-zA-Z0-9]', ' ', text or "")
# 生效条件：m.group(0) 小写后不在模块级常量 EN_STOPWORDS 中时返回 strip_tense_en(该小写词)，命中 EN_STOPWORDS 时返回空串 ""；
    def _norm_word(m):
        w = m.group(0).lower()
        if w in EN_STOPWORDS:
            return ""
        return strip_tense_en(w)
    result = re.sub(r'[a-zA-Z]{2,}', _norm_word, cleaned)
    result = re.sub(r'\s+', ' ', result).strip()
    return result


# 词法相似度口径（二元组集合）：
#   legacy  = |q ∩ d| / |q|      只归一化**查询侧** → 长文档天然占优（既有基线）。
#                                 LongMemEval-S 长 turn 上把证据挤出 Top-5：
#                                 precise/temporal/reference hit@1 均为 0%。
#   jaccard = |q ∩ d| / |q ∪ d|  对称归一化（长度自惩罚，无参数）。
#                                 同口径实测：长文档组 0%→8.97% / 0%→6.77% /
#                                 1.28%→20.51%；短文档组（LoCoMo）基本持平或微降
#                                 → 收益随文档长度单调增长，是长度偏置的定向修复。
# 切换：mdcg.SCORE_MODE = "jaccard"，或环境变量 MDCG_SCORE_MODE=jaccard。
# 缺省 "legacy"：既有检索行为与基线完全不变。
# **评测侧**改用 eval_common.use_jaccard() 显式注入——长 turn 语料上
# precise 0%→8.97% / temporal 0%→6.77% / interference 1.28%→20.51% /
# reference 0%→3.76%（与 Rust mdcg-eval --score jaccard 逐位一致）。
# 主库不切：收益随文档长度单调增长，短条目语料上无增益（该语料本无长度偏置）。
# 另注：test_p17_predict G4 曾出现的「可预测锚点由因果起点 a 错配到语义邻居 x」
# 已由 predict.anchor_from_description 的**可起推资格**修复（2026-09-16，出边
# 非空优先），锚点漂移不再是切换打分口径的理由；口径切换仍按上列数据收益决定。
SCORE_MODES = ("legacy", "jaccard")
SCORE_MODE = os.environ.get("MDCG_SCORE_MODE") or "legacy"


# 生效条件：当 `qb` 与 `nb` 均为非空集合时，若 `mode` 或模块级 `SCORE_MODE` 为 `'jaccard'` 返回交集/并集，否则返回交集/len(`qb`)；任一为空返回 0.0。
def lexical_sim(qb: set, nb: set, mode: str = None) -> float:
    """查询/文档二元组集合的相似度。mode 缺省取模块级 `SCORE_MODE`。

    显式传 mode 用于单点 A/B（不改全局口径即可对比两套打分）。
    """
    if not qb or not nb:
        return 0.0
    inter = len(qb & nb)
    if (mode or SCORE_MODE) == "jaccard":
        union = len(qb | nb)
        return inter / union if union else 0.0
    return inter / len(qb)


# 生效条件：当 `query` 为字符串时，返回含整句、≥2 字符分词及命中 `SYNONYM_GROUPS_WEIGHTED` 组加权项（同名取最大权重）的字典；空串返回 `{}`。
def expand_query_terms_weighted(query: str) -> dict:
    """分级版查询扩展：返回 {词: 隶属度}，隶属度 ∈ (0, 1]。

    与 expand_query_terms 结构一致（整句 + 分词 + 同义词组），区别是：
      · 同义词不再二值地「全进」，而是带 SYNONYM_GROUPS_WEIGHTED 的权重；
      · 同一个词被多组命中时取最大权重（避免重复降权）。
    只新增、不改老函数 → 既有检索路径与 P0/P1 基线不受影响。
    """
    q = query or ""
    weights = {}

# 生效条件：w 为真值且 float(v) 严格大于 weights 中 w 的现有值（w 不在 weights 时基准为 0.0）才写入 weights[w]；w 为 ""/0/None 等假值或 float(v) 不大于现有值时不做任何写入；
    def put(w, v):
        if w and float(v) > weights.get(w, 0.0):
            weights[w] = float(v)

    put(q, 1.0)
    for w in re.split(r"[\s、，。；：,;.:/\\|]+", q):
        w = w.strip()
        if len(w) >= 2:
            put(w, 1.0)
    for group in SYNONYM_GROUPS_WEIGHTED:
        for w in group:
            if w in q:
                for g, gw in group.items():
                    put(g, gw)
                break
    return weights


_LLM_EXPAND_PROMPT = (
    "你是检索查询扩展器。给定用户查询，输出与之相关的中文检索词及权重。\n"
    "只输出一个 JSON 数组，不要任何解释。每项形如 "
    '{{"term": "词", "weight": 0.0~1.0}}。\n'
    "权重含义：1.0=同义或完全等价；0.7~0.9=强相关；0.4~0.6=弱相关；"
    "不要输出无关词，最多 {n} 项。\n"
    "查询：{q}"
)


# 生效条件：当 raw（假值按 "" 处理）去空白后首个 "[" 位置 i 满足 0 ≤ i 且末个 "]" 位置 j > i 时，返回 json.loads(s[i:j+1])；否则返回 None。
def _extract_json_array(raw: str):
    """从 LLM 输出里抠出第一个 JSON 数组（容忍前后废话/代码围栏）。"""
    s = (raw or "").strip()
    i, j = s.find("["), s.rfind("]")
    if i < 0 or j <= i:
        return None
    return json.loads(s[i:j + 1])


# 生效条件：当 `query` 非空时，若 `cache` 传入且含该查询则返回其副本；若 `llm_fn` 为 None 返回带 `__source__='whitebox'` 的白箱加权字典；若 `llm_fn` 返回可解析 JSON 数组则合并至多 `max_terms` 项并标 `'llm'`；异常时回退白箱并标 `'whitebox_fallback'`；空 `query` 返回 `{}`。
def expand_query_terms_llm(query: str, llm_fn=None, cache=None,
                           max_terms: int = 12) -> dict:
    """LLM 查询侧扩展（黑箱只在**查询时刻**，索引侧全程白箱）。

    返回 {词: 隶属度}，与 expand_query_terms_weighted 同构，可直接喂给
    routing.big_domain_score_weighted / MdCGOS 的 fuzzy 路径。
    额外带元数据键 "__source__"：'llm' / 'whitebox' / 'whitebox_fallback'。

    llm_fn: 形如 fn(prompt: str) -> str 的可调用对象（返回 JSON 数组）。
            None → 纯白箱加权扩展；调用/解析失败 → 回退白箱（不抛异常）。
    cache:  可选 dict；**缺省不缓存**（避免隐藏全局状态）。传入 dict 时按 query
            缓存，同一查询只调一次 LLM（不同 llm_fn 请用不同 cache）。
    """
    q = (query or "").strip()
    if not q:
        return {}
    if cache is not None and q in cache:
        return dict(cache[q])

    base = expand_query_terms_weighted(q)
    if llm_fn is None:
        base["__source__"] = "whitebox"
        if cache is not None:
            cache[q] = base
        return dict(base)

    try:
        raw = llm_fn(_LLM_EXPAND_PROMPT.format(n=max_terms, q=q))
        items = _extract_json_array(raw)
        if not items:
            raise ValueError("no json array")
        out = dict(base)
        for it in items[:max_terms]:
            if isinstance(it, dict):
                term = str(it.get("term") or "").strip()
                try:
                    w = float(it.get("weight", 0.5))
                except (TypeError, ValueError):
                    w = 0.5
            else:
                term, w = str(it).strip(), 0.5
            if len(term) >= 1:
                # 只抬高不压低：白箱精确命中的 1.0 不被 LLM 的低权重覆盖
                out[term] = max(out.get(term, 0.0), max(0.0, min(1.0, w)))
        out["__source__"] = "llm"
        if cache is not None:
            cache[q] = out
        return dict(out)
    except Exception:
        base["__source__"] = "whitebox_fallback"
        if cache is not None:
            cache[q] = base
        return dict(base)


# 生效条件：enabled 为假值（默认取 MDCG_RETRIEVAL_PIPELINE=="1"）时无条件删除 entry 中 big_domain / observation_position 两键并返回 entry；
# enabled 为真值时仅删除其中假值的键（真值原样保留）并返回 entry。
def _strip_empty_gate_fields(entry, enabled=None):
    """索引快照里的门控可选字段落键策略。

    默认关闭（总开关未设）→ 两个键**一律不落**：索引条目与 search() 返回的候选 entry
    形状与改动前逐字节一致（否则真实库中大量节点的 observation_position 会平铺进
    候选，改变默认口径——独立复核 2026-09-19 指出）。
    开启后 → 真值才落键（假值不落）。
    """
    if enabled is None:
        enabled = os.environ.get("MDCG_RETRIEVAL_PIPELINE") == "1"
    for _k in ("big_domain", "observation_position"):
        if _k in entry and (not enabled or not entry[_k]):
            del entry[_k]
    return entry


# 生效条件：entry 与其 frontmatter 的 condition_space 取 cs（缺键/假值按 {}）；ctx 为假值或非 dict 时无条件返回 True；
# ctx 与 cs 同时给出非空 observation_position 且 routing.normalize_domain 归一化后不同时返回 False；
# ctx 与 cs 同时给出长度 2 的 time_window 时两端经 trust.epoch_seconds 归一（毫秒自动 /1000）后比较，不相交返回 False（区间相交或任一侧缺值/不可转数值一律返回 True）。
def _cond_prefilter_pass(entry, ctx) -> bool:
    """S2 条件空间前置门控：**不读正文**即可判定的硬槽（契约 §3 S2）。

    铁律（宁多勿漏）：只剔除**明确不匹配**；任一侧信息不足一律放行。
      · observation_position：双方都有且归一化后不同 → 不匹配；
      · time_window：双方都有且**区间不相交** → 不匹配（相交即放行，
        否则缺省窗口 [created_at, created_at+WINDOW] 会把历史观测整片判死）；
      · 其余槽（existence_constraint / observation_tool 等语义判定）留在 judge_qualification（后置）。
    """
    if not isinstance(ctx, dict):
        return True
    # 索引快照把可判定硬槽平铺在 entry 上（免读文件）；兼容直接传 condition_space 的调用方
    entry = entry or {}
    cs = entry.get("condition_space") or {}
    want = ctx.get("observation_position") or ""
    have = entry.get("observation_position") or cs.get("observation_position") or ""
    if want and have:
        try:
            if routing.normalize_domain(str(want)) != routing.normalize_domain(str(have)):
                return False
        except Exception:
            pass
    # 索引快照把 time_window 平铺在 entry 上（不在 condition_space 里）——直接读 cs 会让 S2 时间门控永不生效
    cw, nw = ctx.get("time_window"), (entry.get("time_window") or cs.get("time_window"))
    if (isinstance(cw, (list, tuple)) and len(cw) == 2
            and isinstance(nw, (list, tuple)) and len(nw) == 2):
        # 单位归一（唯一口径 trust.epoch_seconds）：历史毫秒节点的区间若不归一，
        # 与秒级查询窗「必然不相交」→ 整片历史观测被误剔除（issue #23 同根因）。
        c0, c1 = trust.epoch_seconds(cw[0]), trust.epoch_seconds(cw[1])
        n0, n1 = trust.epoch_seconds(nw[0]), trust.epoch_seconds(nw[1])
        if None in (c0, c1, n0, n1):
            return True                  # 任一端不可转 → 信息不足，放行（宁多勿漏）
        if c1 < n0 or n1 < c0:
            return False
    return True


# 生效条件：构造须传入 root，经 os.path.abspath 后以 exist_ok=True 创建该目录及 LAYERS 各层子目录；autoflush 无论取值（默认 64）都原样赋给实例。
class MdCG:
# 生效条件：root 传参即被 os.path.abspath 绝对化并 makedirs(exist_ok=True) 建立 root 与模块级 LAYERS 各层目录，autoflush（默认 64，含 0 等假值）原样存入 self.autoflush，随后 _load_index() 载入索引、sweep_stale_temps(self.root) 清扫，并把 self 登记进模块级 _LIVE_CGS；
    def __init__(self, root: str, autoflush: int = 64):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        for L in LAYERS:
            os.makedirs(os.path.join(self.root, L), exist_ok=True)
        self.index_path = os.path.join(self.root, "_index.json")
        self.index_log_dir = os.path.join(self.root, "_index_log")
        self.access_log = os.path.join(self.root, "_access.log")
        # 信息差 D 跟踪（白箱第 4 篇：D=D(t,C)）
        self.d_trace = os.path.join(self.root, "_d_trace.jsonl")
        # 反思单元日志（白箱第 3 篇第 13 章）
        self.reflection_log = os.path.join(self.root, "_reflection.jsonl")
        # 近期事件滚动窗口（白箱第 5 篇第 3 章「近期事件」）
        self.recent_log = os.path.join(self.root, "_recent.jsonl")
        self.autoflush = autoflush
        self._dirty = {}
        self._log = None
        self.index = self._load_index()
        sweep_stale_temps(self.root)
        # 进程退出兜底登记（见模块级 _LIVE_CGS）：一次性脚本漏收尾时索引仍能落盘。
        _LIVE_CGS.add(self)
        _register_atexit_hook()

    # ---------- 索引（派生物，可重建） ----------

# 生效条件：os.path.exists(self.index_path) 为真、json.load 成功且其 "schema" 等于模块级 SCHEMA 时以该快照为基底，否则以 self._scan_nodes() 结果与空 buckets 新建；随后重放 ShardedLog.read_all(self.index_log_dir)：记录无 id 跳过、e 为 None 则 pop 该 nid（tombstone）、e 非 None 则覆盖，最终 buckets 由 _count_buckets 重算；
    def _load_index(self):
        idx = None
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("schema") == SCHEMA:
                    idx = d
            except (ValueError, OSError):
                idx = None
        if idx is None:
            idx = {"schema": SCHEMA, "nodes": self._scan_nodes(), "buckets": {}}
        for rec in ShardedLog.read_all(self.index_log_dir):
            nid, e = rec.get("id"), rec.get("e")
            if not nid:
                continue
            if e is None:
                # 删除记录（tombstone）：删除必须能重放，否则已删节点会在下次
                # 启动时从旧记录里复活成**幽灵条目**（索引有条目、文件不存在）。
                idx["nodes"].pop(nid, None)
            else:
                idx["nodes"][nid] = e
        idx["buckets"] = self._count_buckets(idx["nodes"])
        return idx

    @staticmethod
# 生效条件：nodes 须为带 values() 的映射且各元素支持 .get("bucket")；仅当 bucket 取值为真值时才计入返回计数，缺键或假值均跳过。
    def _count_buckets(nodes):
        buckets = {}
        for e in nodes.values():
            b = e.get("bucket")
            if b:
                buckets[b] = buckets.get(b, 0) + 1
        return buckets

# 生效条件：os.path.exists(self.index_path) 为真、JSON 可解析且 "schema" 等于 SCHEMA 时以该快照为基底，否则用空骨架 {"schema":SCHEMA,"nodes":{},"buckets":{}} 作基底（不重扫目录），再对 index_log_dir 逐条重放（无 id 跳过、e 为 None 则 pop、否则覆盖），落盘并清空日志后替换 self.index 并返回 idx；
    def compact_index(self):
        with FileLock(self.index_path):
            idx = {"schema": SCHEMA, "nodes": {}, "buckets": {}}
            if os.path.exists(self.index_path):
                try:
                    with open(self.index_path, encoding="utf-8") as f:
                        d = json.load(f)
                    if d.get("schema") == SCHEMA:
                        idx = d
                except (ValueError, OSError):
                    pass
            for rec in ShardedLog.read_all(self.index_log_dir):
                nid, e = rec.get("id"), rec.get("e")
                if not nid:
                    continue
                if e is None:              # 删除记录（tombstone），见 _load_index
                    idx["nodes"].pop(nid, None)
                else:
                    idx["nodes"][nid] = e
            idx["buckets"] = self._count_buckets(idx["nodes"])
            atomic_write(self.index_path, json.dumps(idx, ensure_ascii=False))
            ShardedLog.clear(self.index_log_dir)
        self.index = idx
        return idx

# 生效条件：self._dirty 非空时才（必要时新建 ShardedLog）逐条 append、清空 _dirty 并关闭分片句柄；self._dirty 为空时立即返回、不写任何记录；
    def flush(self):
        if not self._dirty:
            return
        if self._log is None:
            self._log = ShardedLog(self.index_log_dir)
        for nid, e in self._dirty.items():
            self._log.append({"id": nid, "e": e})
        self._dirty = {}
        # 写完立即关分片句柄：Windows 上「被本进程打开的文件」无法删除，
        # 若持有句柄，rebuild_index 的 ShardedLog.clear 会静默失败，已并进
        # 快照的旧记录被永久重放（旧条目反而覆盖新快照）。append 内部已
        # 每次 flush，句柄无需常驻；下一次 append 会按需重开。
        self._log.close()

# 生效条件：随认知图对象生命周期结束调用、可重复；先 flush() 落未达 autoflush 阈值的脏索引（否则尾部写入虽在盘上但不可见），再关闭并置空日志句柄（句柄为假值时跳过关闭）；
    def close(self):
        # 先落脏索引再关句柄：否则未达 autoflush 阈值的尾部写入会永久丢失，
        # 已有 _index.json 的根重开时不会重扫目录，节点将「在盘上但不可见」。
        self.flush()
        if self._log:
            self._log.close()
            self._log = None

# 生效条件：遍历模块级 LAYERS 各层目录下所有 .md 文件，读取抛 OSError 的跳过；nid 取 fm.get("id")，为假值时回落去掉 .md 的文件名；bucket 取父目录名、父目录等于层名时为 None；返回 nodes；
    def _scan_nodes(self):
        nodes = {}
        for layer in LAYERS:
            base = os.path.join(self.root, layer)
            for dirpath, _dirs, files in os.walk(base):
                for fn in files:
                    if not fn.endswith(".md"):
                        continue
                    p = os.path.join(dirpath, fn)
                    try:
                        with open(p, encoding="utf-8") as f:
                            fm, content = nodefile.loads(f.read())
                    except OSError:
                        continue
                    nid = fm.get("id") or fn[:-3]
                    rel = os.path.relpath(p, self.root).replace("\\", "/")
                    parent = os.path.basename(dirpath)
                    nodes[nid] = _strip_empty_gate_fields({
                        "path": rel, "layer": fm.get("layer", layer),
                        # role 必须回填：它写在节点 frontmatter 里（写入时 role or "user"），
                        # 但索引重建时若不复制，os.roles 会全部退化为 (none)，
                        # 来源归因打分随之失效（实测 48 条全丢）。
                        "role": fm.get("role"),
                        # content_kind 入快照：角色化读取视图（第四阶段 6.1）的
                        # 候选资格维度须免读文件可判（与 role 同款理由）。
                        # 纯增量键：批次 C 之前零消费方，view=None 零行为变更。
                        "content_kind": fm.get("content_kind"),
                        # 会话归属入快照（P45 归因维度）：写入路径 _stage 早已带出
                        # 该键，重建路径若漏掉，rebuild_index() 之后「按会话过滤」
                        # 即静默全空——快照与 _stage 必须同口径（与 role 同款理由）。
                        "session": fm.get("session"),
                        "tags": fm.get("tags", []),
                        "bucket": parent if parent != layer else None,
                        "importance": fm.get("importance", 0.5),
                        "created_at": fm.get("created_at", 0),
                        "verification_basis": fm.get("verification_basis"),
                        "has_neg_conditions": nodefile.has_non_applicable(content),
                        # 内容指纹走 nodefile 的唯一实现（两段式对账依赖同一算法）
                        "content_hash": nodefile.content_hash(content),
                        # 时空字段入索引快照：STG 查询免读文件（大域/目录索引的延伸）
                        "temporal": fm.get("temporal"),
                        "spatial": fm.get("spatial"),
                        "time_window": (fm.get("condition_space") or {}).get("time_window"),
                        # 生命周期状态（② 显式状态机）：索引入快照 → 免读文件可查，
                        # 写入路径也因此无需读盘就能校验迁移合法性。重建口径与
                        # _stage 一致（旧库无该字段 → None → state_of 视为 active）。
                        lifecycle.STATE_FIELD: fm.get(lifecycle.STATE_FIELD),
                        # 可验证记忆单元（trust）：重建口径与 _stage 三件同源
                        # （验证态 / 依赖 / 双时间轴）——索引缺键即免读文件不可判。
                        trust.STATE_FIELD: fm.get(trust.STATE_FIELD),
                        trust.DEPS_FIELD: fm.get(trust.DEPS_FIELD),
                        trust.FROM_FIELD: fm.get(trust.FROM_FIELD),
                        trust.UNTIL_FIELD: fm.get(trust.UNTIL_FIELD),
                        # 规范时间轴键（2026-09-19 阶段一）：与 _stage 同口径，
                        # 重建索引后新旧口径一致（检索面 validity 须免读盘可判）。
                        trust.EFFECTIVE_FROM_FIELD: fm.get(trust.EFFECTIVE_FROM_FIELD),
                        trust.EFFECTIVE_UNTIL_FIELD: fm.get(trust.EFFECTIVE_UNTIL_FIELD),
                        # 记忆演化分支（④）：重建口径与 _stage 一致
                        "branch_id": fm.get("branch_id"),
                        "branched_from": fm.get("branched_from"),
                        "evidence_count": fm.get("evidence_count", 0),
                        # S1 大域先验：域标签入索引快照 → 候选收敛零读文件（与 add() 同口径）
                        "big_domain": fm.get("big_domain"),
                        # S2 条件门控所需的可判定硬槽（免读文件即可门控）
                        "observation_position": (fm.get("condition_space") or {}).get("observation_position"),
                        # 嵌套子图 / 关系边入索引快照：递归展开与链式遍历免读文件
                        "subgraph": fm.get("subgraph"),
                        "edges": fm.get("edges") or [],
                        "protected": fm.get("protected"),
                        "protection_reason": fm.get("protection_reason"),
                        "immutable": fm.get("immutable"),
                        # 自我状态卡标记：protect 据此豁免「不可覆盖」（仍不可遗忘）
                        "self_state": fm.get("self_state"),
                        # G8 派生溯源：frontmatter 声明入索引 → 悬空巡检零读文件
                        "derived_from": fm.get("derived_from") or [],
                        "derived_relation": fm.get("derived_relation"),
                    })
        # 索引序确定性：按 nid 排序返回。os.walk 的遍历序是**文件系统事实**
        # （NTFS 上常为字母序，但换 FS / 目录碎片化后不保证），若直接作为
        # index["nodes"] 的物理序，就会让「完全并列」的结果顺序依赖重建路径。
        # 排序后重建序恒定（增量路径另由 cut_by_relevance 的 nid 终键兜住）。
        return {k: nodes[k] for k in sorted(nodes)}

# 生效条件：每次调用都以 self._scan_nodes() 的结果重建 nodes 与 buckets，在 FileLock 下 atomic_write 覆盖 index_path 并 ShardedLog.clear(index_log_dir)，随后替换 self.index、清空 _dirty 并返回 idx（无 .md 时也照样覆盖为空索引）；
    def rebuild_index(self):
        nodes = self._scan_nodes()
        idx = {"schema": SCHEMA, "nodes": nodes,
               "buckets": self._count_buckets(nodes)}
        with FileLock(self.index_path):
            atomic_write(self.index_path, json.dumps(idx, ensure_ascii=False))
            ShardedLog.clear(self.index_log_dir)
        self.index = idx
        self._dirty = {}
        return idx

    # ---------- 写 ----------

# 生效条件：node_id/content 必填，layer 不在 LAYERS 内、或 verification_basis 非 None 且不在 VERIFICATION_BASIS 内时抛 ValueError；consistency 为真且 _cons.check 判 REJECT 时，on_conflict="reject" 抛 ConsistencyError、on_conflict="defer" 返回 None，verdict 为 BLINDSPOT 且 on_conflict="defer" 同样返回 None，其余情形完成写盘/入索引后返回 node_id。
    def add(self, node_id: str, content: str, layer: str = "knowledge",
            tags=None, condition_space=None, importance: float = 0.5,
            confidence: float = 0.6, edges=None, verification_basis: str = None,
            non_applicable_conditions=None, override: bool = False,
            consistency: bool = False, on_conflict: str = "reject",
            derived_from=None, relation: str = provenance.DEFAULT_RELATION,
            semantic: str = None, depends_on=None, valid_from=None,
            valid_until=None, effective_from=None, effective_until=None,
            believed_at=None, verification_state: str = None, **extra) -> str:
        """写入一个节点。

        verification_basis: 外部验证基底（白箱信任的硬门槛），
                            可选值在 nodefile.VERIFICATION_BASIS。
                            knowledge/self/anchor/structural 层强烈建议填写；
                            负记忆层（rejected/unresolved）通常填 "test" 或 "data"。
        non_applicable_conditions: 不适用条件列表，第 1 篇第 10 章 28%→88% 的关键。
        consistency: 是否做节点间自动冲突检测（三级决策：情绪→反思→递归反思）。
        on_conflict: 冲突处置——"reject" 抛 ConsistencyError（默认）/
                     "defer" 不写盘返回 None / "record" 记录后放行。
        derived_from:（G8 派生溯源）本节点来源节点 id，单个或列表。声明后写进
                     frontmatter（单一真相源）并追加派生边到 <root>/_link.jsonl；
                     **建链失败不阻断本次写入**（降级为告警 + .fail 台账留痕）。
        relation: 派生关系名，默认 "derived_from"；允许值见 provenance.RELATIONS。
        semantic: 标准语义摘要（空格分隔的标准原子序列，如「鱼 油」）——
                  **AI 写入侧归一**的产物（使用者设想 2026-09-14：归一主体是
                  AI，系统只供词表真源 atoms.json + OOV 审计）。落 fm.semantic
                  衍生层，正文原文无损；OOV token 记 fm.semantic_oov 警告不拒绝
                  （词表覆盖有限，拒绝会堵死合法写入）。检索面经
                  MDCG_SEMANTIC=1 开启组合共现打分（mdcg._score）。
        depends_on:（可验证记忆单元）本节点**依赖**的节点 id，单个或列表。落
                    frontmatter.depends_on（= CCG「子功能」槽的落字段，见 nodefile）。
                    被依赖单元变动/证伪时，本节点由 trust.mark_dependents **同步**
                    标 doubted（一跳，低成本）；多跳交巡检 trust.propagate。
        valid_from / valid_until: 双时间轴（何时开始成立 / 何时不再成立），
                    使时效可判定：未生效 / 生效中 / 已过期（trust.validity）。
                    **历史名**——2026-09-19 阶段一新增规范名 `effective_from` /
                    `effective_until`（新调用方优先用它；旧参数名照旧落旧键，
                    读取侧由 trust.FROM_ALIASES/UNTIL_ALIASES 统一回落，存量不迁移）。
        believed_at: 信念时间（体系**何时确认此条**）——取代/审核的锚。
                    **不是效力语义**：既非「未生效」也非「已过期」，与双时间轴物理隔离
                    （绝不并入 scrub 的任一键族）；覆写默认继承，缺省不写。
        verification_state: 验证态（unverified/verified/doubted/rechecking/expired，
                    真源 trust.py）。**覆写既有节点时默认继承**——add 是全量重建
                    fm，不显式继承会把已 verified 静默打回 unverified（与
                    lifecycle_state 同构的坑）；显式传入则走迁移裁决，非法即拒。
        """
        if layer not in LAYERS:
            raise ValueError(f"未知层：{layer}（允许：{LAYERS}）")
        if verification_basis is not None and verification_basis not in VERIFICATION_BASIS:
            raise ValueError(f"未知验证基底：{verification_basis}（允许：{VERIFICATION_BASIS}）")
        # 写保护：self/anchor 层、protected 标记、importance≥0.7 的**既有**节点
        # 不可被任意覆写；覆盖需 override=True（旧版本自动快照 + 审计留痕）。
        protect.guard_write(self, node_id, layer=layer, override=override,
                            actor=extra.get("actor"))
        # 节点间自动冲突检测（智能论 §十一 情绪二阶 / 条件论「反题」/ :273 递归约束）
        if consistency:
            from . import consistency as _cons
            vd = _cons.check(self, content, layer=layer,
                             condition_space=condition_space,
                             non_applicable_conditions=non_applicable_conditions,
                             tags=tags, exclude=node_id, auto_flywheel=True)
            v = vd["verdict"]
            if v == "REJECT" and on_conflict == "reject":
                raise _cons.ConsistencyError(v, vd["reason"], vd["conflicts"])
            if v in ("REJECT", "BLINDSPOT") and on_conflict == "defer":
                return None
            extra["consistency"] = {
                "verdict": v, "reason": vd["reason"],
                "strength": vd["conflict_strength"],
                "emotional": (vd.get("emotional") or {}).get("bias"),
                "unresolved_id": vd.get("unresolved_id")}
        tags = list(tags or [])
        # 标准语义摘要（semantic/canonical.py：词表真源 + OOV 审计，警告不拒绝）。
        # 语义校验失败不阻断写入（与 derived_from 建链降级同风格）。
        if semantic is not None:
            extra["semantic"] = str(semantic)
            try:
                from .semantic import canonical as _canon
                _oov = _canon.oov_of(str(semantic))
                if _oov:
                    extra["semantic_oov"] = _oov
            except Exception:
                pass
        bucket = None
        d = os.path.join(self.root, layer)
        if layer in BUCKETED_LAYERS:
            bucket = routing.bucket_dir(routing.route_key(condition_space, tags))
            d = os.path.join(d, bucket)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{node_id}.md")
        created_at = extra.pop("created_at", time.time())
        # 条件论「观测时间」栏：写入时必须记录观测时间窗。
        # 调用方未提供 time_window 时，以写入时刻为锚、默认窗口 OBSERVATION_WINDOW_SEC。
        cs = dict(condition_space or {})
        tw = cs.get("time_window")
        if not (isinstance(tw, (list, tuple)) and len(tw) == 2):
            cs["time_window"] = [created_at, created_at + OBSERVATION_WINDOW_SEC]
        fm = {
            "id": node_id, "layer": layer,
            "modality": extra.pop("modality", "text"),
            "importance": importance, "confidence": confidence,
            "condition_space": cs, "tags": tags,
            "created_at": created_at,
            "access_count": 0, "last_access": 0, "edges": list(edges or []),
            "verification_basis": verification_basis,
            "non_applicable_conditions": list(non_applicable_conditions or []),
            # 证据计数（白箱第 5 篇第 4 章）：每次 verify 累加，正/反例分开记
            "evidence_count": 0, "positive_evidence": 0, "negative_evidence": 0,
        }
        fm.update(extra)
        # S1 大域先验：写入时固化「内容 → 大域」（契约 §3 S1）。
        # 为何在写入侧：检索侧要按域收敛，节点就必须带域；query 侧分类器已存在，
        # 缺的只是这一列节点元数据（审计偏差 4 的根因）。调用方可显式传入覆盖。
        # 无有效域信号（classify_text 返回 None）时**不写**该字段 → 留在兜底池。
        # 默认（MDCG_RETRIEVAL_PIPELINE 未设）**不写**该字段：默认口径与改动前一致；
        # 开启后新写入的节点开始积累域标签，历史节点由 md_cg.backfill_bigdomain 补齐。
        if os.environ.get("MDCG_RETRIEVAL_PIPELINE") == "1" and not fm.get("big_domain"):
            try:
                _bd = routing.classify_text(content)
            except Exception:
                _bd = None
            if _bd:
                fm["big_domain"] = _bd
        # 生命周期状态（② 显式状态机，真源 `lifecycle.py`）：add 是**全量重建
        # fm** 而非增量更新，故必须显式处理状态——否则已定型/已降权节点会被静默
        # 打回 active（与 ④ rewrite 必须重传 branch_id 同构的坑）。口径：
        #   · 新节点：显式落 active（不再依赖「缺省即 active」的隐式约定）；
        #   · 覆写既有节点：**继承旧状态**；显式传入 state 时走迁移裁决，非法迁移
        #     **拒绝**（负路由：抛 TransitionError，与非法层名同风格）。
        # 取旧状态优先读**索引快照**（免读盘）；索引缺该键（升级前的旧库）才回读
        # 节点文件兜底——不兜底会把存量 converged/demoted 节点误判成 active。
        prev_entry = (self.index.get("nodes") or {}).get(node_id)
        prev_state = lifecycle.state_of(prev_entry)
        if prev_entry and lifecycle.STATE_FIELD not in prev_entry:
            prev_state = lifecycle.state_of(
                (self.get(node_id) or {}).get("frontmatter"))
        # 显式入口兼容两种写法：`state=`（调用方直觉）与 `lifecycle_state=`。
        # `state` 必须 **pop 掉**——该键名已属裁决四态（ACCEPT/REJECT/DEFER/
        # BLINDSPOT），落进 frontmatter 只会在读面制造同名歧义；归一到真字段名后
        # 再走同一裁决。两者同时给出时以 `lifecycle_state=` 为准（字段名更明确）。
        _alias = fm.pop("state", None)
        want_state = fm.get(lifecycle.STATE_FIELD)
        if want_state is None:
            want_state = _alias
        if want_state is None:
            fm[lifecycle.STATE_FIELD] = prev_state
        else:
            # 受保护判定取**索引快照**（兼具两层含义）：本次 fm 里的保护标记、以及
            # 节点**既有**的保护（快照带 protected/immutable）。只看本次 fm 会漏掉
            # 「既有受保护节点被覆写时降级」——保护 = 不可遗忘，不因一次 add 失守。
            # 注：该参数只在降级迁移上生效（check 内按方向判定），回升不受限。
            _pe = prev_entry or {}
            lifecycle.require_transition(
                prev_state, want_state,
                protected=bool(fm.get("protected") or fm.get("immutable")
                               or _pe.get("protected") or _pe.get("immutable")),
                override=override)
            fm[lifecycle.STATE_FIELD] = want_state
        # 可验证记忆单元（真源 `trust.py`）：验证态 + 依赖声明 + 双时间轴。
        # 与 lifecycle 同构的坑——add 是**全量重建 fm**：既有 verified 节点被普通
        # 覆写时若不显式继承，会静默打回 unverified。故默认继承，显式传入才裁决。
        prev_vstate = trust.state_of(prev_entry)
        if prev_entry and trust.STATE_FIELD not in prev_entry:
            prev_vstate = trust.state_of(
                (self.get(node_id) or {}).get("frontmatter"))
        _v_alias = fm.pop(trust.STATE_FIELD, None)   # **extra 通道的兼容写法
        want_vstate = verification_state or _v_alias
        if want_vstate is None:
            fm[trust.STATE_FIELD] = prev_vstate
        else:
            _pe_v = prev_entry or {}
            trust.require_transition(
                prev_vstate, want_vstate,
                protected=bool(fm.get("protected") or fm.get("immutable")
                               or _pe_v.get("protected") or _pe_v.get("immutable")),
                override=override)
            fm[trust.STATE_FIELD] = want_vstate
        # 依赖声明（CCG「子功能」的落字段）与双时间轴：**覆写即继承**语义——
        # 一次普通覆写抹掉依赖，会让失效传播从源头断链（下游永远收不到存疑信号）。
        _deps = trust.as_deps(depends_on) or trust.as_deps(fm.get(trust.DEPS_FIELD))
        if not _deps and prev_entry:
            _deps = trust.as_deps(prev_entry.get(trust.DEPS_FIELD))
        if _deps:
            fm[trust.DEPS_FIELD] = _deps
        else:
            fm.pop(trust.DEPS_FIELD, None)      # 不保留空列表噪声
        # 双时间轴键族（2026-09-19 阶段一）：规范键 `effective_*` 优先、历史键
        # `valid_*` 回落。**落键口径**——显式新参数 → 落规范键；旧参数名 → 照旧落
        # 旧键（既有调用面字节不变，零破坏）；均未给 → 本次 fm → 旧快照，任一有值即继承
        # （不把 `valid_from` 悄悄改名，避免无谓 diff）。同族双写必留歧义，故落一键、剔另一键。
        for _spec, _legacy, _nv in (
                (trust.EFFECTIVE_FROM_FIELD, trust.FROM_FIELD, effective_from),
                (trust.EFFECTIVE_UNTIL_FIELD, trust.UNTIL_FIELD, effective_until)):
            if _nv is not None:
                fm[_spec] = _nv
                fm.pop(_legacy, None)
                continue
            _lv = valid_from if _spec == trust.EFFECTIVE_FROM_FIELD else valid_until
            if _lv is not None:
                fm[_legacy] = _lv
                fm.pop(_spec, None)
                continue
            _val, _key = None, None
            for _k in (_spec, _legacy):
                if fm.get(_k) not in (None, ""):
                    _val, _key = fm.get(_k), _k
                    break
            if _val is None and prev_entry:
                for _k in (_spec, _legacy):
                    if prev_entry.get(_k) not in (None, ""):
                        _val, _key = prev_entry.get(_k), _k
                        break
            fm.pop(_spec, None)
            fm.pop(_legacy, None)
            if _val not in (None, ""):
                fm[_key] = _val
        # 过期时刻冗余（2026-09-20 补全阶段一声明的设计：nodefile.EXPIRED_AT_FIELD
        # 注释自书「由 effective_until 派生，供审计/对账免计算直读」，但派生逻辑
        # 从未落地——scrub._EXPIRY_KEYS 读取侧已消费该键，写入侧缺失即恒空）。
        # 冗余字段不独立存活：终点在则随终点落、终点失则剔除（防与终点漂移）。
        _end = None
        for _k in trust.UNTIL_ALIASES:
            if fm.get(_k) not in (None, ""):
                _end = fm.get(_k)
                break
        if _end is not None:
            fm[trust.EXPIRED_FIELD] = _end
        else:
            fm.pop(trust.EXPIRED_FIELD, None)
        # 审计 / 血缘向字段（**不进索引白名单** → 索引快照里没有这些键）的统一回读
        # 来源：惰性读节点文件一次、多字段共用。照搬 prev_entry 会让已落盘字段在
        # 下次普通覆写时静默丢失（lifecycle_state / verification_state 两度踩的同一坑）。
        _old = {}

        def _old_fm(key):
            if not prev_entry:
                return None
            if "fm" not in _old:
                _old["fm"] = (self.get(node_id) or {}).get("frontmatter") or {}
            return _old["fm"].get(key)

        # 信念时间（体系何时确认此条）：与效力时间**物理隔离**的第三类语义——
        # 覆写即继承，缺省不写空值噪声。
        _bel = believed_at if believed_at is not None else fm.get(trust.BELIEVED_FIELD)
        if _bel in (None, ""):
            _bel = _old_fm(trust.BELIEVED_FIELD)
            if _bel is None and prev_entry:
                _bel = prev_entry.get(trust.BELIEVED_FIELD)   # 防御：万一被透传
        if _bel in (None, ""):
            fm.pop(trust.BELIEVED_FIELD, None)
        else:
            fm[trust.BELIEVED_FIELD] = _bel
        # 巩固 / 归纳留痕（2026-09-19 阶段一 · 真源 md_cg/consolidate.py）：成员侧
        # 「巩固进哪一条 + 何时」与概念侧「前身是谁 + 何时」同族（nodefile.
        # CONSOLIDATION_FIELDS）——同属审计/血缘向、索引里没有，故同样回读继承；
        # 缺了它，概念节点被一次普通覆写（如审核 edit/merge 重写）就丢掉前身清单，
        # 「任一合并条目可定位全部前身」即断。
        for _cf in nodefile.CONSOLIDATION_FIELDS:
            if fm.get(_cf) in (None, "", [], {}):
                _cv = _old_fm(_cf)
                if _cv in (None, "", [], {}):
                    fm.pop(_cf, None)
                else:
                    fm[_cf] = _cv
        # G8 派生溯源：把「来源声明」写进 frontmatter（单一真相源），台账为派生物。
        # 只声明事实、不做校验式拒绝——关系名非法仅回退默认值，不阻断写入。
        parents = provenance.as_list(derived_from)
        derived_rel = provenance.coerce_relation(relation) if parents else None
        if parents:
            fm["derived_from"] = parents
            fm["derived_relation"] = derived_rel
        # 重要性 ≥0.7 自动打保护标记（对齐 tool_table：≥0.7 触发不可遗忘保护）
        if (float(importance or 0.0) >= protect.AUTO_PROTECT_IMPORTANCE
                and not fm.get("protected")):
            fm["protected"] = True
            fm["protection_reason"] = (f"importance={float(importance):.2f}"
                                       f"≥{protect.AUTO_PROTECT_IMPORTANCE}")
        # 私有内容封装（默认恒等；MdCGSecure 覆盖为 AEAD 加密）。
        # 索引派生同样基于落盘内容，保证与 _scan_nodes 重建结果一致。
        sealed = self._write_node(node_id, path, fm, content)
        self._stage(node_id, _strip_empty_gate_fields({
            "path": os.path.relpath(path, self.root).replace("\\", "/"),
            "layer": layer, "tags": tags, "bucket": bucket,
            "importance": importance, "created_at": fm["created_at"],
            "verification_basis": verification_basis,
            "has_neg_conditions": nodefile.has_non_applicable(sealed),
            "content_hash": hashlib.sha256(sealed.encode("utf-8")).hexdigest()[:12],
            "temporal": fm.get("temporal"),
            "spatial": fm.get("spatial"),
            "time_window": cs.get("time_window"),
            "big_domain": fm.get("big_domain"),
            "observation_position": cs.get("observation_position"),
            "subgraph": fm.get("subgraph"),
            "edges": fm.get("edges") or [],
            "protected": fm.get("protected"),
            "protection_reason": fm.get("protection_reason"),
            "immutable": fm.get("immutable"),
            "self_state": fm.get("self_state"),
            "derived_from": parents,
            "derived_relation": derived_rel,
            "writer": fm.get("writer"),
            "session": fm.get("session"),
            "harness": fm.get("harness"),
            # 角色化读取视图（第四阶段 6.1）：候选资格维度入快照（免读文件
            # 可判，与 _scan_nodes 同口径）。
            "content_kind": fm.get("content_kind"),
            # 记忆演化分支（④）：fork 副本带分支归属与溯源主支
            "branch_id": fm.get("branch_id"),
            "branched_from": fm.get("branched_from"),
            # 生命周期状态（②）：索引快照透出 → 免读文件可查（与 _scan_nodes 同口径）
            lifecycle.STATE_FIELD: fm.get(lifecycle.STATE_FIELD),
            # 可验证记忆单元（trust）：验证态 + 依赖 + 双时间轴入快照 → 免读文件可查
            trust.STATE_FIELD: fm.get(trust.STATE_FIELD),
            trust.DEPS_FIELD: fm.get(trust.DEPS_FIELD),
            trust.FROM_FIELD: fm.get(trust.FROM_FIELD),
            trust.UNTIL_FIELD: fm.get(trust.UNTIL_FIELD),
            # 规范时间轴键（2026-09-19 阶段一）：检索面 validity 过滤免读盘即可判定。
            # `believed_at`（信念时间）属审计/取代锚，**不进索引热点**（只落 fm）。
            trust.EFFECTIVE_FROM_FIELD: fm.get(trust.EFFECTIVE_FROM_FIELD),
            trust.EFFECTIVE_UNTIL_FIELD: fm.get(trust.EFFECTIVE_UNTIL_FIELD),
        }))
        subgraph.invalidate_cache(self)
        chain.invalidate_cache(self)
        trust.invalidate_cache(self)     # 依赖声明可能变化 → 反查索引作废
        # G8 常态化建链：仅对**新增**节点、仅在显式声明来源时建边。
        # 硬约束：建链失败绝不阻断写入（record 永不抛，失败降级留痕）。
        if parents:
            provenance.record(self.root, node_id, parents,
                              relation=derived_rel,
                              batch=extra.get("batch"),
                              actor=extra.get("actor"))
        return node_id

# 生效条件：node_id、dst、reason、actor、override 全部原样转交 lifecycle.set_state 并返回其结果，本方法自身不做校验、分支或参数回落；
    def set_state(self, node_id: str, dst: str, reason: str = None,
                  actor: str = None, override: bool = False) -> dict:
        """节点生命周期状态推进（② 显式状态机：**唯一推进入口**，见 lifecycle.py）。

        非法迁移**拒绝**（返回 `ok=False` + `error` 机器码，不抛异常——负路由）；
        受保护节点（`protected`/`immutable`）不接受降级，需 `override=True`。
        状态与迁移历史落 frontmatter，索引快照同步，审计追加 `_lifecycle.jsonl`。
        """
        return lifecycle.set_state(self, node_id, dst, reason=reason,
                                   actor=actor, override=override)

# 生效条件：无条件转调 trust.set_state(self, node_id, dst, reason=..., actor=..., evidence=..., method=..., trigger=..., override=...) 并原样返回其结果，本方法自身不做校验、分支或参数回落；
    def set_verification(self, node_id: str, dst: str, reason: str = None,
                         actor: str = None, evidence: str = None,
                         method: str = None, trigger: str = None,
                         override: bool = False) -> dict:
        """节点**验证态**推进（真源 `trust.py`：唯一推进入口）。

        与 `set_state`（生命周期）**正交**：一个管「节点是否还在服役」
        （active/converged/demoted/archived），一个管「它现在还成不成立」
        （unverified/verified/doubted/rechecking/expired）。两套状态集不共享常量。

        非法迁移走负路由（`ok=False` + `error` 机器码，不抛）；受保护节点不接受
        降级（需 `override=True`）；审计追加 `<root>/_trust.jsonl`，索引快照同步。
        """
        return trust.set_state(self, node_id, dst, reason=reason,
                               actor=actor, evidence=evidence,
                               method=method, trigger=trigger,
                               override=override)

# 生效条件：只读转调 trust.describe(self, node_id) 并返回其结果，自身不做校验或分支；
    def verification(self, node_id: str) -> dict:
        """单节点验证态全貌（验证态 + 依赖 + 反查 + 时间轴 + 履历）。只读。"""
        return trust.describe(self, node_id)

# 生效条件：每次调用都延迟导入 twophase 并以原样 apply（含 False）与 limit（含 0）转调 twophase.reconcile(self, apply=apply, limit=limit) 并返回，自身不做参数回落；
    def reconcile_writes(self, apply: bool = True, limit: int = 2000) -> dict:
        """写入两段式对账（③ 两段式提交）：把崩溃遗留的半途写入**补账或标记**。

        幂等（补出的 outcome 与正常 outcome 同形，二次扫描无未配对项）；
        `apply=False` 为只读盘点。返回 `{"unpaired","committed","interrupted",
        "applied","details"}`；账本为 root 下 `_write_2pc.jsonl`（append-only）。
        """
        from . import twophase       # 延迟导入：与写路径解耦，避免模块环
        return twophase.reconcile(self, apply=apply, limit=limit)

# 生效条件：每次调用都延迟导入 twophase 并以原样 limit（含 0）转调 twophase.pending(self, limit=limit) 并返回，自身不做参数回落；
    def pending_writes(self, limit: int = 200) -> list:
        """未结清的写入意图（有 intent 无 outcome）——只读，不改账本。"""
        from . import twophase
        return twophase.pending(self, limit=limit)

    # ------------------------------------------------------------------
    # 边域窄原语（写路径收口：白箱工具写 md 真源的唯一正路）。
    #
    # 三条纪律：
    # 1. 一律经 `self.get()` 读 + `_write_node()` 写（加密形态下 get 解封、
    #    _write_node 再封装——绕过即破坏加密）；
    # 2. 只动边域（fm.edges / fm.subgraph.nodes），不改 content / importance /
    #    tags 等本体字段，故不走 guard_write 写保护（保护语义=本体覆写），
    #    但索引 entry 的 edges/subgraph 键同步更新并标 _dirty；
    # 3. 幂等去重：append_edge 按 (target, relation_type)、append_subgraph_node
    #    按 child_id 去重，重复追加返回 False 不落盘。
    # ------------------------------------------------------------------

# 生效条件：self.get(node_id) 返回假值（取不到节点）时返回 None；取到时返回 (frontmatter or {}, content or "", root 下 node.get("path") 或回落 f"{node_id}.md")；
    def _edge_node(self, node_id):
        """取节点 (fm, content, full_path)；不存在返回 None。"""
        node = self.get(node_id)
        if not node:
            return None
        return (node.get("frontmatter") or {}, node.get("content") or "",
                os.path.join(self.root, node.get("path") or f"{node_id}.md"))

# 生效条件：self.index["nodes"].get(node_id) 非 None 时把该条目 edges 置为 fm.get("edges") or []、subgraph 置为 fm.get("subgraph") 并标脏；条目为 None 则完全不同步（subgraph 缓存失效调用被静默吞异常）；
    def _sync_edge_entry(self, node_id, fm):
        """边域变更后同步索引 entry（edges/subgraph 键）并标脏。"""
        entry = self.index["nodes"].get(node_id)
        if entry is not None:
            entry["edges"] = fm.get("edges") or []
            entry["subgraph"] = fm.get("subgraph")
            self._dirty[node_id] = entry
        try:
            from . import subgraph as _sg
            _sg.invalidate_cache(self)
        except Exception:
            pass

# 生效条件：node_id 取不到节点返回 False；fm.edges 非 list 时重置为 []；已存在 dict 边其 str(target or "") 与 str(relation_type or "") 同时等于 edge 归一值（缺键为 ""）时返回 False（幂等），否则追加 dict(edge)、写盘并同步后返回 True；
    def append_edge(self, node_id: str, edge: dict) -> bool:
        """向既有节点追加一条出边（fm.edges），幂等去重。

        edge 形态对齐迁移语料：{"target", "relation_type", "confidence",
        "verified", "condition_space", ...}。节点不存在返回 False。
        """
        got = self._edge_node(node_id)
        if got is None:
            return False
        fm, content, path = got
        edges = fm.setdefault("edges", [])
        if not isinstance(edges, list):
            edges = fm["edges"] = []
        tgt = str(edge.get("target") or "")
        rel = str(edge.get("relation_type") or "")
        if any(str(e.get("target") or "") == tgt
               and str(e.get("relation_type") or "") == rel
               for e in edges if isinstance(e, dict)):
            return False  # 幂等：同 target 同关系已存在
        edges.append(dict(edge))
        self._write_node(node_id, path, fm, content)
        self._sync_edge_entry(node_id, fm)
        return True

# 生效条件：node_id 取不到节点返回 False；subgraph 非 dict 时重置为 {"nodes":[]}、其 nodes 非 list 时重置为 []；child_id 已在列表中返回 False（幂等），否则追加 str(child_id)、写盘并同步后返回 True；
    def append_subgraph_node(self, node_id: str, child_id: str) -> bool:
        """向既有父节点追加层级子节点（fm.subgraph.nodes），幂等去重。

        层级边（hierarchical）在 md 语料的落点即父节点 subgraph.nodes
        （source=父，与 migrate_wisdom_graph 导出形态一致）。
        """
        got = self._edge_node(node_id)
        if got is None:
            return False
        fm, content, path = got
        sg = fm.get("subgraph")
        if not isinstance(sg, dict):
            sg = fm["subgraph"] = {"nodes": []}
        subs = sg.setdefault("nodes", [])
        if not isinstance(subs, list):
            subs = sg["nodes"] = []
        if child_id in subs:
            return False  # 幂等
        subs.append(str(child_id))
        self._write_node(node_id, path, fm, content)
        self._sync_edge_entry(node_id, fm)
        return True

# 生效条件：node_id 取不到节点返回 False；tags 非 list 时重置为 []；先按 remove（假值按空集合）删除、再把 add（假值按空列表）中不在结果内的 str 项追加，结果等于原 tags 时返回 False 不落盘，否则写盘、同步索引 tags、标脏并返回 True；
    def update_tags(self, node_id: str, add=None, remove=None) -> bool:
        """节点 tags 增删（节点状态更新窄原语——causal 候选状态迁移面）。

        remove 先于 add（状态迁移语义：去旧标→加新标），去重保序；
        无实质变更不落盘返回 False。节点不存在返回 False。
        """
        got = self._edge_node(node_id)
        if got is None:
            return False
        fm, content, path = got
        tags = fm.get("tags")
        if not isinstance(tags, list):
            tags = fm["tags"] = []
        tags = [str(t) for t in tags]
        rm = {str(t) for t in (remove or [])}
        new_tags = [t for t in tags if t not in rm]
        for t in (add or []):
            t = str(t)
            if t not in new_tags:
                new_tags.append(t)
        if new_tags == tags:
            return False  # 幂等：无实质变更
        fm["tags"] = new_tags
        self._write_node(node_id, path, fm, content)
        entry = self.index["nodes"].get(node_id)
        if entry is not None:
            entry["tags"] = list(new_tags)
            self._dirty[node_id] = entry
        return True

# 生效条件：node_id 取不到节点返回 False；在 fm.get("edges") or [] 中找首个 dict 且 str(target or "")==str(target_id)、str(relation_type or "")==str(relation_type) 的边，找不到返回 False；命中则把该边 condition_space 置为 dict(condition_space or {})、写盘并同步后返回 True；
    def set_edge_condition(self, node_id: str, target_id: str,
                           relation_type: str, condition_space: dict) -> bool:
        """改既有节点上指定出边的 condition_space（模式分离更新面）。

        匹配 (target, relation_type) 唯一边；无匹配返回 False 不落盘。
        """
        got = self._edge_node(node_id)
        if got is None:
            return False
        fm, content, path = got
        edges = fm.get("edges") or []
        hit = None
        for e in edges:
            if (isinstance(e, dict)
                    and str(e.get("target") or "") == str(target_id)
                    and str(e.get("relation_type") or "") == str(relation_type)):
                hit = e
                break
        if hit is None:
            return False
        hit["condition_space"] = dict(condition_space or {})
        self._write_node(node_id, path, fm, content)
        self._sync_edge_entry(node_id, fm)
        return True

# 生效条件：nid（"rej_"+sha1(hypothesis) 前 10 位）已在 self.index["nodes"] 中时直接返回该 nid 不写盘（幂等）；否则以 hypothesis/reason/verification_basis（默认 "test"）拼正文并 add(..., layer="rejected", importance=0.0, **extra) 返回新 nid；
    def add_rejected(self, hypothesis: str, reason: str, verification_basis: str = "test",
                     tags=None, **extra) -> str:
        """第 5 篇 L2：负记忆——失败/否决的假设库。重复证伪幂等。"""
        nid = f"rej_{hashlib.sha1(hypothesis.encode()).hexdigest()[:10]}"
        if nid in self.index["nodes"]:
            return nid  # 幂等：重复证伪不重复记录
        content = (f"# 假设：{hypothesis}\n"
                   f"# 否决原因：{reason}\n"
                   f"# 验证：{verification_basis}\n")
        return self.add(nid, content, layer="rejected",
                        tags=tags, verification_basis=verification_basis,
                        importance=0.0, **extra)  # importance=0：不被检索优先

# 生效条件：nid（"unr_"+sha1(question) 前 10 位）已在 self.index["nodes"] 中时直接返回；否则拼接 question、known_clues（假值渲染「（暂无）」）、context 非空才追加「现场」行、goal（假值渲染「（未设定）」）与 verification_basis 后 add(layer="unresolved", importance=0.3)；
    def add_unresolved(self, question: str, known_clues: str = "",
                       goal: str = "", verification_basis: str = "data",
                       tags=None, context: str = "", **extra) -> str:
        """第 5 篇 L5：未解问题清单——驱动主动探索。

        context：结构化「现场」（如「同条件两条不同取值 vs mem_A」）。
        缺此字段时「32 / 64 哪个对」这类缺口在裁决时看不到原始对照。
        """
        nid = f"unr_{hashlib.sha1(question.encode()).hexdigest()[:10]}"
        if nid in self.index["nodes"]:
            return nid
        content = (f"# 问题：{question}\n"
                   f"# 已知线索：{known_clues or '（暂无）'}\n"
                   + (f"# 现场：{context}\n" if context else "")
                   + f"# 目标：{goal or '（未设定）'}\n"
                   f"# 验证：{verification_basis}\n")
        return self.add(nid, content, layer="unresolved",
                        tags=tags, verification_basis=verification_basis,
                        importance=0.3, **extra)

    # ---------- 目标槽（白箱第 5 篇第 3 章「目标」）----------

    @staticmethod
# 生效条件：传入 goal 即返回渲染文本；conditions 为假值（含默认空串）时「生效条件」行填「（未声明——视为任意情境下有效）」，action 为假值时填默认执行说明。
    def _goal_content(goal, conditions="", action=""):
        """目标节点的 CCG 渲染：目标不是知识，但按 CCG 格式落盘，
        保证 judge_qualification 能给出 ACCEPT 而非 BLINDSPOT。"""
        return (f"# 功能名：{goal}\n"
                f"# 生效条件：{conditions or '（未声明——视为任意情境下有效）'}\n"
                f"# 子功能：为检索提供方向偏置（goal 路）\n"
                f"# 执行：{action or '启用 goal 路时，以本目标文本扩展查询并偏置排序'}\n"
                f"# 验证方式：other\n"
                f"# 不适用条件：目标状态为 done/dropped 时不再参与定向\n")

# 生效条件：status 不属于模块级 GOAL_STATUSES 时抛 ValueError；goal 经 (goal or "").strip() 后为空（None/空串/纯空白）时抛 ValueError("goal 不能为空")；否则按 "goal_"+sha1(goal utf-8) 前 10 位生成 gid 并 add(layer="goals", importance=float(priority), goal_status=status, deadline=deadline, ...)；
    def add_goal(self, goal: str, priority: float = 0.5, deadline=None,
                 conditions: str = "", action: str = "", tags=None,
                 status: str = "active", **extra) -> str:
        """写入一个目标（幂等：同目标文本 → 同 id，覆盖）。

        priority 同时作为 importance（目标排序 / goal 路偏置强度的依据）；
        deadline 为 ISO 字符串或时间戳，仅供调用方排序，不做硬约束。
        """
        if status not in GOAL_STATUSES:
            raise ValueError(f"未知目标状态：{status}（允许：{GOAL_STATUSES}）")
        goal = (goal or "").strip()
        if not goal:
            raise ValueError("goal 不能为空")
        gid = f"goal_{hashlib.sha1(goal.encode('utf-8')).hexdigest()[:10]}"
        content = self._goal_content(goal, conditions, action)
        return self.add(gid, content, layer="goals", tags=tags,
                        importance=float(priority), confidence=1.0,
                        verification_basis="other",
                        goal_text=goal, goal_status=status,
                        deadline=deadline, **extra)

# 生效条件：self.index["nodes"].get(node_id) 为假值或其 layer 不等于 "goals" 时返回 None；_read 得到的 fm 为 None 时返回 None；否则返回 dict，其中 goal 取 goal_text 假值回落 ""、status 取 goal_status 假值回落 "active"、priority/created_at 取 importance/created_at 假值回落 0.0；
    def _goal_entry(self, node_id):
        e = self.index["nodes"].get(node_id)
        if not e or e.get("layer") != "goals":
            return None
        fm, _content = self._read(e)
        if fm is None:
            return None
        return {"id": node_id,
                "goal": fm.get("goal_text") or "",
                "status": fm.get("goal_status") or "active",
                "priority": float(fm.get("importance") or 0.0),
                "deadline": fm.get("deadline"),
                "created_at": float(fm.get("created_at") or 0.0),
                "path": e["path"]}

# 生效条件：遍历 self.index["nodes"] 中 layer=="goals" 的节点，_goal_entry 取不到者跳过；status 为假值时不过滤、否则仅保留 status 相等者；按 (-priority, -created_at) 降序，limit 为真值时截断 out[:limit]，否则返回全量；
    def list_goals(self, status=None, limit=None):
        """列出目标，按 (priority, created_at) 降序。status 过滤 active/done/dropped。"""
        out = []
        for nid, e in self.index["nodes"].items():
            if e.get("layer") != "goals":
                continue
            g = self._goal_entry(nid)
            if g and (status is None or g["status"] == status):
                out.append(g)
        # 终键 nid：同 priority 且 created_at 碰撞（量化到 ~1ms）时定序，
        # 否则并列顺序回落到 self.index["nodes"] 的物理序（增量路径=写入序）。
        out.sort(key=lambda g: (-g["priority"], -g["created_at"],
                                str(g.get("id") or "")))
        return out[:limit] if limit else out

# 生效条件：等价于 list_goals(status="active", limit=limit)，limit 缺省 5；返回按 (-priority, -created_at) 降序的活跃目标列表；
    def active_goals(self, limit: int = 5):
        """当前活跃目标（默认最多 5 条）——检索定向的默认来源。"""
        return self.list_goals(status="active", limit=limit)

# 生效条件：status 不属于模块级 GOAL_STATUSES 时抛 ValueError；self.get(node_id) 取不到节点或其 frontmatter 的 layer 不等于 "goals" 时返回 None；否则写回 goal_status 与 status_changed_at 并返回 {"id": node_id, "status": status}；
    def set_goal_status(self, node_id: str, status: str):
        """目标状态机：active → done/dropped（可回退）。"""
        if status not in GOAL_STATUSES:
            raise ValueError(f"未知目标状态：{status}（允许：{GOAL_STATUSES}）")
        node = self.get(node_id)
        if not node or (node["frontmatter"].get("layer") or "") != "goals":
            return None
        fm = node["frontmatter"]
        fm["goal_status"] = status
        fm["status_changed_at"] = time.time()
        self._write_node(node_id, os.path.join(self.root, node["path"]),
                         fm, node["content"])
        return {"id": node_id, "status": status}

# 生效条件：goal 为真值（非 None/空串/0）时返回 str(goal)；goal 为假值时返回 self.active_goals(limit=limit) 中非空 goal 文本以空格拼接的字符串；
    def goal_text(self, goal=None, limit: int = 5) -> str:
        """检索定向用的目标文本：显式 goal 优先，否则拼接活跃目标。"""
        if goal:
            return str(goal)
        return " ".join(g["goal"] for g in self.active_goals(limit=limit)
                        if g["goal"])

    # ---------- 近期事件滚动窗口（白箱第 5 篇第 3 章「近期事件」）----------

# 生效条件：role 为假值回落 "user"、text 为假值回落 ""、tags/meta 为假值回落 []/{} 后拼成 rec 追加到 recent_log，再按 window（默认模块级 DEFAULT_RECENT_WINDOW）调 roll_recent 截断，返回 {"event": rec, "dropped": dropped}；
    def remember_event(self, role: str, text: str, tags=None, meta=None,
                       window: int = DEFAULT_RECENT_WINDOW):
        """追加一条近期事件（原始、未结构化），并按窗口滚动截断。"""
        rec = {"t": time.time(), "role": role or "user",
               "text": text or "", "tags": list(tags or []),
               "meta": dict(meta or {})}
        append_jsonl(self.recent_log, rec)
        dropped = self.roll_recent(window)
        return {"event": rec, "dropped": dropped}

# 生效条件：read_jsonl(recent_log) 条数 <= window（默认 DEFAULT_RECENT_WINDOW）时返回 0 不写盘；否则在 FileLock 下 atomic_write 保留 recs[-window:] 并返回 len(recs) - len(keep)；window 为 0 时 recs[-0:] 即全部记录，返回 0 且不实际截断。
    def roll_recent(self, window: int = DEFAULT_RECENT_WINDOW) -> int:
        """把窗口截断到最近 window 条，返回丢弃条数（未超限则 0，幂等）。"""
        recs = list(read_jsonl(self.recent_log))
        if len(recs) <= window:
            return 0
        keep = recs[-window:]
        with FileLock(self.recent_log):
            atomic_write(self.recent_log, "".join(
                json.dumps(r, ensure_ascii=False) + "\n" for r in keep))
        return len(recs) - len(keep)

# 生效条件：roles 为真值时按 r.get("role") 是否在 set(roles) 内过滤；since 非 None 时按 float(r.get("t") or 0) >= float(since) 过滤；limit 为真值时取末 limit 条、为 None/0 等假值时取全部；newest_first 为真值时反转返回，否则按原序返回；
    def recent_events(self, limit: int = 20, roles=None, since=None,
                      newest_first: bool = True):
        """读取近期事件（默认最新在前）。roles 过滤角色，since 过滤时间戳。"""
        recs = list(read_jsonl(self.recent_log))
        if roles:
            allow = set(roles)
            recs = [r for r in recs if r.get("role") in allow]
        if since is not None:
            recs = [r for r in recs if float(r.get("t") or 0) >= float(since)]
        out = recs[-limit:] if limit else recs
        return list(reversed(out)) if newest_first else out

# 生效条件：无条件读取全部记录并在 FileLock 下把 recent_log 原子写空，返回被清条数（无记录时为 0）；
    def clear_recent(self):
        """清空近期窗口（返回被清条数）。"""
        recs = list(read_jsonl(self.recent_log))
        with FileLock(self.recent_log):
            atomic_write(self.recent_log, "")
        return len(recs)

# 生效条件：无条件把 entry 写入 _dirty[node_id] 与 index["nodes"][node_id]；entry.get("bucket") 为真值时该桶计数 +1；当 len(self._dirty) >= self.autoflush 时调 flush()（autoflush 为 0 时每次标脏都立即 flush）；
    def _stage(self, node_id, entry):
        self._dirty[node_id] = entry
        self.index["nodes"][node_id] = entry
        if entry.get("bucket"):
            self.index["buckets"][entry["bucket"]] = \
                self.index["buckets"].get(entry["bucket"], 0) + 1
        if len(self._dirty) >= self.autoflush:
            self.flush()

# 生效条件：无条件 pop index["nodes"][node_id]（不存在则无操作）；被 pop 的条目有真值 bucket 时该桶计数 -1，减后 <=0 则删除该桶键；随后无论是否命中都把 _dirty[node_id] 置 None（删除 tombstone）并立即调 flush() 持久化；
    def _unstage(self, node_id):
        """摘除索引条目并**持久化**——与 `_stage` 对称的删除原语。

        只 pop 内存索引是不够的：`close()` 注释里记过同构的坑（已有
        `_index.json` 的根重开不重扫目录），于是「删掉的条目」会在
        `_index_log` 重放时复活成**幽灵条目**（索引有条目、节点文件不存在）。
        幽灵条目的代价：检索白跑候选、`ref action=prune` 因 `cg.get` 取不回
        而够不着它，`check` 的 dangling 永不归零（本机实测累积数百条）。
        """
        e = self.index["nodes"].pop(node_id, None)
        if e and e.get("bucket"):
            b = e["bucket"]
            left = self.index["buckets"].get(b, 0) - 1
            if left > 0:
                self.index["buckets"][b] = left
            else:
                self.index["buckets"].pop(b, None)
        self._dirty[node_id] = None      # None = 删除记录，随 flush 落分片日志
        self.flush()                     # 删除不可延迟到 autoflush 阈值

    # ---------- 内容封装钩子（默认恒等；MdCGSecure 覆盖为「私有内容加密」）----

# 生效条件：默认实现无条件原样返回 content，node_id 与 sensitivity 均不改变返回值；
    def _seal_content(self, node_id: str, content: str,
                      sensitivity: str = None) -> str:
        """写入前的正文封装钩子。默认原样返回；加密实现见 `crypto.seal_node`。"""
        return content

# 生效条件：默认实现无条件返回传入的 content（不返回 None），node_id 与 fm 不参与；
    def _open_content(self, node_id: str, fm: dict, content: str):
        """读取后的正文解封钩子。返回 None 表示不可读（无密钥 / 身份不符）。"""
        return content

# 生效条件：无条件以 fm.get("sensitivity") 调 _seal_content 封装后执行 atomic_write(path, nodefile.dumps(fm, sealed), durable=durable) 并返回 sealed，durable 原样透传、无校验；
    def _write_node(self, node_id: str, path: str, fm: dict, content: str,
                    durable: bool = False):
        """统一节点写盘口：先封装再原子写。**所有写盘点都应走这里**，
        否则 `get()` 解密后的明文会被直接回写（破坏加密）。"""
        sealed = self._seal_content(node_id, content, fm.get("sensitivity"))
        atomic_write(path, nodefile.dumps(fm, sealed), durable=durable)
        return sealed

    # ---------- S1 前置元数据：域标签回填 ----------

# 生效条件：dry_run 为真时只统计不改盘；否则遍历 index["nodes"]，get(nid) 取不到（无密钥/文件缺失）计入 unreadable，
# fm 已有 big_domain 计入 already，content 为 None 计入 unreadable，routing.classify_text(content) 为 None 计入 no_signal，
# 其余写 fm["big_domain"] → _write_node → 同步索引 entry["big_domain"]；limit 为真值时 written 达 limit 即停；写完 flush()；返回统计 dict。
    def backfill_big_domain(self, dry_run: bool = False, limit: int = None) -> dict:
        """为缺 `big_domain` 的节点补域标签（S1 大域收敛的前置元数据；幂等）。

        只改这一列元数据，不动 content/importance/edges/条件空间；
        走 `get()`（解密）→ `_write_node()`（重新封装），保证加密库不会双重封装。
        """
        st = {"seen": 0, "already": 0, "written": 0, "no_signal": 0,
              "unreadable": 0, "index_synced": 0, "dry_run": bool(dry_run)}
        # 前置：功能未开启时**不做任何写入**——域标签是 S1 的元数据，默认口径不得被改变：
        # 否则「回填写索引」会与「_scan_nodes 默认关剥键」冲突，写/重建两条路口径不一致。
        if os.environ.get("MDCG_RETRIEVAL_PIPELINE") != "1":
            st["skipped"] = "pipeline_disabled"
            return st
        for nid, e in list((self.index.get("nodes") or {}).items()):
            if limit and st["written"] >= limit:
                break
            st["seen"] += 1
            got = self.get(nid)
            if not got:
                st["unreadable"] += 1
                continue
            fm, content = got["frontmatter"], got["content"]
            _fm_dom = fm.get("big_domain")
            if _fm_dom:
                # 对账支路：frontmatter 已有标签但索引快照没同步（历史部分失败/旧索引）→ 修索引，不重写文件
                if e.get("big_domain") != _fm_dom:
                    st["index_synced"] += 1
                    if dry_run:            # dry-run 语义：只统计，不改内存也不落盘
                        continue
                    e["big_domain"] = _fm_dom
                    self._stage(nid, _strip_empty_gate_fields(e))
                else:
                    st["already"] += 1
                continue
            if content is None:
                st["unreadable"] += 1
                continue
            try:
                dom = routing.classify_text(content)
            except Exception:
                dom = None
            if not dom:
                st["no_signal"] += 1
                continue
            if dry_run:
                st["written"] += 1
                continue
            fm["big_domain"] = dom
            self._write_node(nid, os.path.join(self.root, e["path"]), fm, content)
            e["big_domain"] = dom
            # 必须走 _stage：索引持久化靠 _dirty → flush → _index_log 重放，
            # 只改内存 entry 会在重启后丢掉标签（S1 失效，且二次回填因 fm 已有标签而跳过）
            self._stage(nid, _strip_empty_gate_fields(e))
            st["written"] += 1
        # 写入与「只对账索引」两种情形都要落盘：索引持久化靠 _dirty → flush → _index_log 重放，
        # 只 _stage 不 flush 会在重启后丢掉标签（对账支路尤其容易漏）。
        if not dry_run and (st["written"] or st["index_synced"]):
            self.flush()
        return st

    # ---------- 读 ----------

# 生效条件：index["nodes"].get(node_id) 为假值时回落 self._dirty.get(node_id)，仍为假值返回 None；打开 root 下 e["path"] 抛 OSError 返回 None；_open_content 返回 None（无密钥/身份不符）返回 None；否则返回 {id, frontmatter, content, path}；
    def get(self, node_id: str):
        e = self.index["nodes"].get(node_id) or self._dirty.get(node_id)
        if not e:
            return None
        p = os.path.join(self.root, e["path"])
        try:
            with open(p, encoding="utf-8") as f:
                fm, content = nodefile.loads(f.read())
        except OSError:
            return None
        content = self._open_content(node_id, fm, content)
        if content is None:
            return None                     # 有节点但无密钥 → 不可读即不存在
        return {"id": node_id, "frontmatter": fm, "content": content, "path": e["path"]}

# 生效条件：打开 os.path.join(self.root, entry["path"]) 成功时返回 nodefile.loads 的 (fm, content)；抛 OSError 时返回 (None, None)（entry 的 "path" 按源码直接取键，无 .get 回落）；
    def _read(self, entry):
        p = os.path.join(self.root, entry["path"])
        try:
            with open(p, encoding="utf-8") as f:
                return nodefile.loads(f.read())
        except OSError:
            return None, None

    # ---------- 资格判定（与性能 tier 正交）----------

    @staticmethod
# 生效条件：content 为假值时按空串扫描并返回 ""；仅当某行去空白后以 "#" 开头、包含 name，且按全角或半角冒号切出的 head 去空白后等于 name 时返回该值，否则返回 ""。
    def _ccg_line(content: str, name: str) -> str:
        """取 CCG 正文 `# <name>：` 行的值。

        与 mdcos._ccg_field 同源实现——父类不得反向 import mdcos，
        故在此落同款确定性扫描（无正则回溯风险）。
        """
        for line in (content or "").splitlines():
            s = line.strip()
            if not s.startswith("#") or name not in s:
                continue
            body = s.lstrip("#").strip()
            for sep in ("：", ":"):
                if sep in body:
                    head, _, val = body.partition(sep)
                    if head.strip() == name:
                        return val.strip()
        return ""

    @staticmethod
# 生效条件：cond_text 为假值时按空串返回空列表；仅当按槽分隔与槽内分隔切出的短语长度≥2、非纯数字且不含时间维哨兵短语时进入返回列表，重复短语只保留首次。
    def _cond_terms(cond_text: str):
        """生效条件声明 → 匹配短语列表（确定性切分，无语义猜测）。

        切分规则：按槽分隔「；/;」拆槽（condition_space_text 以「；」连四槽）
        → 每槽剥「槽标签：」前缀（载体/位置、时间、方法、约束等标签是通用词，
        参与命中必误判）→ 槽内按「，,、/（）」切短语 → 丢弃长度 <2、纯数字、
        全时窗哨兵短语（全时窗 = 时间维无信息量，不因其未命中而降级）。
        """
        out, seen = [], set()
        for slot in re.split(r"[；;]", str(cond_text or "")):
            if "：" in slot:
                slot = slot.split("：", 1)[1]
            elif ":" in slot:
                slot = slot.split(":", 1)[1]
            for seg in re.split(r"[，,、/（）()]", slot):
                seg = seg.strip()
                if len(seg) < 2 or seg.isdigit():
                    continue
                if "全时窗" in seg or "任意时刻" in seg:
                    continue
                if seg not in seen:
                    seen.add(seg)
                    out.append(seg)
        return out

    @staticmethod
# 生效条件：node_dict 的 content 经 ccg_completeness 判为不完整 → BLINDSPOT；否则由 query 与 context（仅当 context 为 dict 时并入）合成情境串，命中 frontmatter 的任一 non_applicable_conditions 词 → REJECT；否则情境非空（query 去空白后非空，或 context 为真）且「生效条件」文本非空、非"无条件"、其词项全未命中且词项非空 → DEFER；否则无 verification_basis → DEFER；否则 ACCEPT；
    def judge_qualification(node_dict, query: str, context=None):
        """四态判定（白箱第 1/2 篇）。

        输入：节点 + 查询 + 当前情境
        输出：{state: ACCEPT|REJECT|DEFER|BLINDSPOT, reason: str}

        判定逻辑（与文档一致）：
        - BLINDSPOT：节点 MARKS 不完整（6 行缺一不可；生效条件不可隐含，
          必须由条件空间四槽合成显式声明）→ 无法建立可靠归属，停止
        - REJECT：不适用条件命中 → 明确不适用
        - DEFER：生效条件未在情境（query+context）词面确认，或未声明验证基底
          → 可继续寻找/补证据
        - ACCEPT：条件满足（生效条件已确认，或无情境可比——此时 reason 诚实
          标注「未做正条件确认」，不冒充已确认）
        """
        fm = node_dict.get("frontmatter") or {}
        content = node_dict.get("content") or ""
        cpl = nodefile.ccg_completeness(content)

        # 1) BLINDSPOT：CCG 要素不全 → 无法建立可靠归属
        if not cpl["complete"]:
            return {"state": STATE_BLINDSPOT,
                    "reason": f"CCG 要素不全：缺 {set(nodefile.CCG_REQUIRED) - set(cpl['required_present'])}"}

        # 情境合成（query + context）：正/负条件共用同一情境口径。
        # 负条件扩面依据（2026-09-12）：不适用条件的语义是「本节点明确不适用
        # 于这类问句」，问句（query）是情境的一半——只看 context 时「我没喝水」
        # 声明的负条件「刚才在干什么」在同类问句下永不命中，否定事件得以冒充
        # 事件。扩面已过全量回归（test_p33 负条件断言保绿：其词面本就命中）。
        scene = {"query": query or ""}
        if isinstance(context, dict):
            scene.update(context)
        scene_str = json.dumps(scene, ensure_ascii=False)

        # 2) REJECT：不适用条件命中（需条件对比，简化版用关键词命中）
        neg = fm.get("non_applicable_conditions") or []
        neg_hit = [n for n in neg if any(w in scene_str for w in n.split())]
        if neg_hit:
            return {"state": STATE_REJECT,
                    "reason": f"不适用条件命中：{neg_hit[:3]}"}

        # 3) 正条件确认：生效条件须在情境（query+context）中词面可确认——
        #    「没发现拒绝理由」≠「确认适用」（相似度产生候选，条件授予资格）。
        #    情境为空（无 query 且无 context）→ 无可判定依据，跳过本段不降级：
        #    「无情境」不能被误判成「不适用」。
        cond_hit = None
        has_scene = bool((query or "").strip()) or bool(context)
        if has_scene:
            cond_text = MdCG._ccg_line(content, "生效条件")
            if not cond_text and fm.get("condition_space"):
                cond_text = nodefile.condition_space_text(fm["condition_space"])
            if cond_text and cond_text.strip() != "无条件":
                terms_ = MdCG._cond_terms(cond_text)
                cond_hit = next((t for t in terms_ if t in scene_str), None)
                if cond_hit is None and terms_:
                    return {"state": STATE_DEFER,
                            "reason": ("生效条件未在情境确认（未命中任何声明条件："
                                       + "、".join(terms_[:3])
                                       + "）；可补充情境或条件词面后重判")}

        # 4) DEFER：节点无 verification_basis → 信任根基不足
        if not fm.get("verification_basis"):
            return {"state": STATE_DEFER,
                    "reason": "未声明验证基底，需补充才能继续判定"}

        # 5) ACCEPT：默认——reason 诚实标注正条件是否经情境确认
        acc = "5 要素齐全 + 不适用条件未命中 + 验证基底已声明"
        if cond_hit:
            acc = f"生效条件已确认（命中「{cond_hit}」）+ " + acc
        elif not has_scene:
            acc = "无情境可比（未做正条件确认）+ " + acc
        return {"state": STATE_ACCEPT, "reason": acc}

    # ---------- 检索（性能阶梯 + 资格判定）----------

# 生效条件：query strip 后为空即返回 ([], {"tier": None, "reason": "empty_query", "scanned": 0})；非空时按 T0–T3 性能阶梯取候选（layer / session / branch / validity / view 为假值时对应维度不过滤），judge 为真时对每条结果附独立的四态资格判定；返回 (results, meta)；
    def search(self, query: str, layer: str = None, k: int = 20,
               context=None, min_results: int = 1, record: bool = True,
               include_neg: bool = True, judge: bool = True, pools=None,
               session=None, branch=None, validity=None,
               start_time=None, end_time=None, start_operator=None,
               end_operator=None, time_axis=None, view=None):
        """返回 (results, meta)。results = [(node_dict, score, qualification)]。

        meta 含 tier（性能层级）、scanned（读取节点数）、bucket（路由桶）、candidates。
        qualification 是独立的 {state, reason}，与 tier 正交：
          - tier = 怎么找到的（性能）
          - state = 是否该用（资格）

        include_neg：是否包含 rejected/unresolved 层（默认 True：负记忆可参与判定）
        judge：是否对每条结果做四态资格判定（默认 True）
        pools：（§七 召回分池）None=关闭（默认，沿用 GLOBAL_CAP 平截，原行为）；
               True=内置显式权重表；dict=自定义表（各池 cap_ratio 之和必须 == 1.0）。
               也受 MDCG_POOLING=1 影响（载体侧开关）。分池只重分配截断额度、不抬高上限。
        validity：时效过滤（显式启用，缺省 None 不过滤）——真值时剔除**已过期**
               （valid_until 已过）节点；**未生效（valid_from 未到）保留**，因其与
               「已失效」语义相反（scrub 纪律「valid_from 绝不并入 _EXPIRY_KEYS」）。
               判定走 trust.validity 唯一真源；时间轴缺失/端点不可解析 → 不过滤（不猜测）。
              start_time/end_time/start_operator/end_operator/time_axis：时间算子
               （阶段二 4.1，**显式启用**）——按 `time_axis` 轴把候选收敛到查询时间窗内。
               轴未指定 → 回落 `effective`；轴/算子非法、孤 operator、start>end 一律
               `ValueError`（fail-closed 只针对**调用方误用**，不针对节点缺字段）。
               效力轴缺字段 fail-open（保留）、观察轴缺字段 fail-closed（剔除）。
               审计落 `meta["time_filter"]`，且**仅在启用时**落键（默认关零变更）。
        view：角色化读取视图（第四阶段 6.1，显式启用；roleviews.py 规则表）——
              main/verifier/receipt 三视图各自声明候选资格（content_kind/
              layer/role 维度），view 非空时叠加资格谓词；非法视图
              ValueError（fail-closed 只针对调用方误用）。
        """
        q = (query or "").strip()
        if not q:
            return [], {"tier": None, "reason": "empty_query", "scanned": 0}
        pool_cfg = pooling.resolve(pooling.from_env(pools))
        now = time.time() if validity else None      # 统一取一次 now，保判定口径一致

        terms = expand_query_terms(q)
        # 英文归一化后再取 bigram（小写+去停用词+去时态；中文不动）
        # + 英→中语素 bigram 补充（跨语词法分：纯中文零变化，MDCG_EN_ATOMS 可关）
        qb = bigrams(normalize_en(q)) | en_zh_bigrams(q)
        # 把 rejected/unresolved 视作可参与召回的特殊「候选池」
        # ——命中它们的结果会改变 meta 的 covered_neg（被负记忆覆盖的查询）
        # 默认排除掉负记忆层的节点进入正排打分，仅作为「覆盖标记」用
        entries = [e for e in self.index["nodes"].values()
                   if (not layer or e["layer"] == layer)
                   # '"*"' = 显式跨会话（读遍所有会话）；缺省 None 同义
                   and (not session or session == "*"
                        or e.get("session") == session)
                   # 分支实验场：默认（branch=None）分支节点全部隐身；
                   # branch=<id> 时主支 + 本分支可见、其他分支仍隐身
                   and e.get("branch_id") in (None, branch)
                   # 角色化读取视图（第四阶段 6.1）：view 非空时叠加资格谓词
                   # （非法视图 ValueError——fail-closed 只针对调用方误用）
                   and (view is None or roleviews.matches(e, view))
                   # 时效：只在显式启用时排除已过期（not_yet 保留）
                   and not (validity and trust.is_expired(e, now=now))]

        # 默认关：索引里可能残留门控字段（曾开启过 / 回填过）→ 返回前剥离，
        # 保证候选 entry 形状与「从未启用过本功能」逐字节一致（独立复核 2026-09-19）。
        # 只在确有残留时才拷贝（默认路径无额外开销）。
        if (os.environ.get("MDCG_RETRIEVAL_PIPELINE") != "1" and entries
                and any(("big_domain" in e) or ("observation_position" in e)
                        for e in entries)):
            entries = [_strip_empty_gate_fields(dict(e), enabled=False)
                       for e in entries]

        # ---- 时间算子（阶段二 4.1）：候选**资格**过滤（在 S1/S2 收敛之前）----
        # 与 validity 各司其职、互不替代：
        #   validity = 「是否已失效」——默认关、只排过期、未生效一律保留；
        #   时间算子 = 「是否落在查询时间窗内」——轴 + 算子显式启用，双端可空 = 无界。
        # fail-closed 只针对**调用方误用**（轴/算子非法、孤 operator、start>end →
        # ValueError）；节点缺字段按**轴策略**处置：效力轴 fail-open（可选声明，
        # 缺 = 沉默不是否认）、观察轴 fail-closed（写入侧保证存在，缺 = 数据异常，
        # 须计数可见而非静默放行）。审计块仅在启用时落键（默认关零变更纪律）。
        _tf_audit = None
        _en_t, _ax_t, _why_t = trust.check_time_args(
            start_time, end_time, start_operator, end_operator, time_axis)
        if _why_t:
            raise ValueError(_why_t)
        if _en_t:
            _qs_t, _qe_t = trust.parse_time(start_time), trust.parse_time(end_time)
            entries, _dr_t, _ms_t = trust.filter_by_time(
                entries, _ax_t, _qs_t, _qe_t, start_operator, end_operator)
            _tf_audit = trust.time_filter_meta(
                axis=_ax_t,
                mode="endpoint" if (start_operator or end_operator) else "overlap",
                start=_qs_t, end=_qe_t, start_operator=start_operator,
                end_operator=end_operator, dropped=_dr_t, axis_missing=_ms_t,
                applied=True)

        # ---- S1/S2 检索前门控（契约 docs/hive/检索路径与认知结构契约_v0.1.md）----
        # 历史偏差：大域先验与条件空间都只在「扫完 + 排完」之后才用（审计偏差 2/4）。
        # 这里把它们前移到候选构建：候选先按域收敛、再按可判定硬槽门控。
        # 默认（MDCG_RETRIEVAL_PIPELINE 未设）全关 → 行为与改动前等价。
        big_domain = routing.big_domain_classify(terms)
        big_scores = routing.big_domain_score_breakdown(terms)
        gates = {}
        # S3 子开关**必须显式 =1**（与 S1/S2 的「未设=开」不同，是有意的非对称）：
        # S3 会新增候选并引入新的 tier（TIER_SPREAD），在总开关开启时若默认随开，
        # 会让「启用 S1/S2」的用户静默多出一层结果——独立复核（2026-09-19）要求显式启用。
        # 参数：hops（默认 2）、decay（默认 0.5）、gain（默认 0.2）。
        _s3 = (os.environ.get("MDCG_RETRIEVAL_PIPELINE") == "1"
               and os.environ.get("MDCG_GATE_S3_SPREAD") == "1")
        # S4 层级激活优先级：同样必须显式 =1（新层加成会改变排序，属显式启用项）
        _s4 = (os.environ.get("MDCG_RETRIEVAL_PIPELINE") == "1"
               and os.environ.get("MDCG_GATE_S4_LAYER") == "1")
        # S7 倒排候选层（只作候选生成器；召回与全表扫描一致）；见 md_cg/postings.py
        _s7 = (os.environ.get("MDCG_RETRIEVAL_PIPELINE") == "1"
               and os.environ.get("MDCG_GATE_S7_POSTINGS") == "1")
        _s7_narrowed = False
        if _s4 and entries:
            _bo = layer_boosts()
            _lc = {}
            for _e in entries:
                _l = str(_e.get("layer") or "")
                _lc[_l] = _lc.get(_l, 0) + 1
            gates["s4"] = {"boosts": _bo, "layers": _lc}
        try:
            _s3_hops = max(1, int(os.environ.get("MDCG_SPREAD_HOPS", "2")))
        except ValueError:
            _s3_hops = 2
        try:
            _s3_decay = min(1.0, max(0.0, float(os.environ.get("MDCG_SPREAD_DECAY", "0.5"))))
        except ValueError:
            _s3_decay = 0.5
        try:
            _s3_gain = min(1.0, max(0.0, float(os.environ.get("MDCG_SPREAD_GAIN", "0.2"))))
        except ValueError:
            _s3_gain = 0.2
        if os.environ.get("MDCG_RETRIEVAL_PIPELINE") == "1" and entries:
            if os.environ.get("MDCG_GATE_S1_DOMAIN", "1") != "0" and big_domain:
                # 域内 ∪ 未标域（兜底池）：无域标签的历史节点绝不能因「域内够多」被丢
                #（契约 §3 S1 不变量：ORPHAN/未标域必须可被召回）
                same = [e for e in entries
                        if not e.get("big_domain") or e.get("big_domain") == big_domain]
                # 召回安全：域内候选不足以支撑 min_results 时不收敛，留全量兜底
                if len(same) >= max(1, min_results):
                    gates["s1"] = {"domain": big_domain, "in": len(same),
                                   "dropped": len(entries) - len(same)}
                    entries = same
                else:
                    gates["s1"] = {"domain": big_domain, "in": len(same),
                                   "dropped": 0, "fallback": "insufficient"}
            elif os.environ.get("MDCG_GATE_S1_DOMAIN", "1") != "0":
                gates["s1"] = {"domain": None, "reason": "no_domain_signal"}
            # ---- S1b 细口径桶收敛（设计见 docs/hive/检索收敛实测与S1b设计_v0.1.md）----
            # 为何：真实库 91.1% 节点有非 orphan 桶、期望扫描仅 2.1%（细口径），但 T0/T1 桶路
            # 只在调用方传 context 时可用；普通 search(q) 无 context 就只能全扫。S1b 让 query 侧
            # 自己推断候选桶（只用索引，不读文件），把这份收敛拿回来。
            # 召回安全：orphan/无桶节点恒留兜底；命中不足 min_results 即回退（不改 entries）。
            # 开关与参数就地定义（位于“总开关块”内，不在 S4 块内）：S1b 只依赖总开关 + MDCG_GATE_S1B_BUCKET。
            _s1b = (os.environ.get("MDCG_GATE_S1B_BUCKET") == "1")
            try:
                _s1b_topk = int(os.environ.get("MDCG_BUCKET_TOPK", "3"))
            except ValueError:
                _s1b_topk = 3
            try:
                _s1b_minsim = min(1.0, max(0.0, float(os.environ.get("MDCG_BUCKET_MIN_SIM", "0.34"))))
            except ValueError:
                _s1b_minsim = 0.34
            if _s1b and entries:
                if _s1b_topk <= 0:
                    gates["s1b"] = {"keys": [], "reason": "disabled_by_topk"}
                else:
                    _sizes = {}
                    for _e in entries:
                        _b = _e.get("bucket")
                        if _b and _b != routing.ORPHAN:
                            _sizes[_b] = _sizes.get(_b, 0) + 1
                    _best = {}
                    for _b in _sizes:
                        _kk = routing.bucket_key_readable(_b)
                        if not _kk:
                            continue
                        _sim = 0.0
                        for _t in terms:
                            _sv = routing.domain_similarity(_t, _kk)
                            if _sv > _sim:
                                _sim = _sv
                        if _sim >= _s1b_minsim:
                            _best[_b] = _sim
                    if not _best:
                        gates["s1b"] = {"keys": [], "reason": "no_key_match",
                                       "in": len(entries), "buckets": len(_sizes)}
                    else:
                        _picked = sorted(_best.items(),
                                         key=lambda kv: (-kv[1], -_sizes[kv[0]],
                                                         str(kv[0])))[:_s1b_topk]
                        _keep = {_b for _b, _ in _picked}
                        _kept = [e for e in entries
                                 if (e.get("bucket") in _keep)
                                 or not e.get("bucket")
                                 or e.get("bucket") == routing.ORPHAN]
                        gates["s1b"] = {"keys": [_b for _b, _ in _picked],
                                        "sims": [round(_v, 4) for _, _v in _picked],
                                        "in": len(entries), "out": len(_kept),
                                        "sizes": {_b: _sizes[_b] for _b, _ in _picked}}
                        if len(_kept) >= max(1, min_results):
                            entries = _kept
                        else:
                            # 回退：entries 保持不变 → 审计的 out 必须记「真实输出规模」，
                            # 命中桶本可保留的数量另存 would_keep（独立复核 2026-09-19 指出口径误导）
                            gates["s1b"]["would_keep"] = len(_kept)
                            gates["s1b"]["out"] = len(entries)
                            gates["s1b"]["fallback"] = "insufficient"
            if os.environ.get("MDCG_GATE_S2_COND", "1") != "0" and isinstance(context, dict):
                kept = [e for e in entries if _cond_prefilter_pass(e, context)]
                gates["s2"] = {"in": len(entries), "out": len(kept),
                               "dropped": len(entries) - len(kept)}
                # 门控清空则回退（宁多勿漏）
                if kept:
                    entries = kept
                else:
                    gates["s2"]["fallback"] = "empty"
        if not entries:
            _m = {"tier": None, "reason": "no_candidates", "scanned": 0}
            if gates:                      # 默认关时 gates 为空 → 不落键（口径与改动前一致）
                _m["gates"] = gates
            return [], _m

        # 负记忆覆盖：查询词是否已被否决议过
        neg_coverage = []
        if include_neg:
            for e in self.index["nodes"].values():
                if e["layer"] in ("rejected", "unresolved"):
                    got = self.get(e["path"].split("/")[-1][:-3])
                    # 用 path 末段作为 id 反查（_index 用 path，get 用 id）
                    # 上面写法是错的；改用直接路径读
                    full_path = os.path.join(self.root, e["path"])
                    if not os.path.exists(full_path):
                        continue
                    try:
                        with open(full_path, encoding="utf-8") as f:
                            fm, content = nodefile.loads(f.read())
                    except OSError:
                        continue
                    if any(t in content for t in terms):
                        neg_coverage.append(e)

        stat = {"scanned": 0, "query": q, "gates": gates}
        if _tf_audit:
            stat["time_filter"] = _tf_audit
        route_bucket = None
        if context is not None:
            ctx = context if isinstance(context, dict) else {}
            route_bucket = routing.bucket_dir(
                routing.route_key(ctx, ctx.get("tags")))

        # 阶段 1 大域打分已在候选构建前算好（S1 门控要用）；此处不再重复计算。

# 生效条件：docs 经 self._score(docs, q, qb, pool_cfg) 后分数 >0 的条数达到闭包阈值 min_results 时返回 self._emit(scored, k, tier, stat, route_bucket, record, len(docs), judge, context, neg_coverage, big_domain, big_scores, pool_cfg)（tier 原样透传）；未达阈值返回 None；
        def try_stage(docs, tier):
            scored = self._score(docs, q, qb, pool_cfg)
            valid = sum(1 for _, s in scored if s > 0)
            if valid >= min_results:
                return self._emit(scored, k, tier, stat, route_bucket, record,
                                  len(docs), judge, context, neg_coverage,
                                  big_domain, big_scores, pool_cfg)
            return None

        # T0/T1：路由桶内
        if route_bucket:
            in_bucket = [e for e in entries if e.get("bucket") == route_bucket]
            if in_bucket:
                docs = self._read_many(in_bucket, stat)
                # 语义资格（MDCG_SEMANTIC=1）：fm.semantic 节点无条件入池
                hits = [d for d in docs if self._like(d[2], d[1], terms)
                        or (semantic_on() and d[1].get("semantic"))]
                out = try_stage(hits, TIER_BUCKET_LIKE)
                if out:
                    return out
                out = try_stage(docs, TIER_BUCKET_SCAN)
                if out:
                    return out

        # T1'（reach）：大域收敛 → 条件门控 → 图扩散（2026-09-18 新增）。
        # 层级仍报 TIER_GLOBAL_LIKE（它就是「全量 LIKE」阶段的收敛实现，test_p0 契约
        # 「无 context 走全量阶梯」不因优化而变）；收敛与否由 meta.reach* 字段区分。
        # 收敛集是 LIKE 命中集与词法打分>0 集合的**超集**（必要条件倒排，见
        # md_cg/test_reach.py 包含性断言），故本阶段不可能丢召回；任一不适用条件
        # （MDCG_REACH 未开启 / 单字符 term / 索引不可用 / 收敛集为空）整段跳过，由下方全量阶段兜底。
        # 默认关（契约 §7「不在默认路径上启用新行为」）：整段不进入 → meta 键集合与改动前逐字节一致。
        reach_entries, _rstat = None, {}
        if reach.enabled():
            reach_entries, _rstat = reach.narrow(self, entries, terms, qb, context, q=q)
        if _rstat:
            stat.update(_rstat)
        if reach_entries is not None:
            _pre_scan = int(stat.get("scanned") or 0)   # 收敛阶段读盘基线（供回退审计）
            docs_r = self._read_many(reach_entries, stat)
            _dif = set(_rstat.get("reach_diffused_paths") or ())
            hits_r = [d for d in docs_r
                      if self._like(d[2], d[1], terms)
                      or (semantic_on() and d[1].get("semantic"))
                      or d[0].get("path") in _dif]     # 图扩散补召回：无词面命中也放行进打分
            stat["pre_cap"] = len(hits_r)     # 与 T2 同序：截断**前**的候选数
            stat["cap"] = GLOBAL_CAP
            # 与 T2 **无条件**同序调用（不可按 cap 短路：cut_by_relevance 还会写
            # 池账 pool_taken/cands/lost，短路会让 meta.pools.taken 缺失 → test_p43(13) 红）
            hits_r, _rep = cut_by_relevance(hits_r, self._score(hits_r, q, qb, pool_cfg),
                                            GLOBAL_CAP, pools=pool_cfg,
                                            key_of=pooling.doc_key, stat=stat)
            pooling.record_audit(stat, _rep)
            out = try_stage(hits_r, TIER_GLOBAL_LIKE)
            if out:
                return out
            # 收敛阶段未产出结果 → 继续走下方全量 T2/T3；此时必须**改写 reach 审计**，
            # 否则 meta.reach 谎报 converged、A3 也会把「收敛读+全量读」双计当成收敛（r14 复核取证）
            stat["reach"] = "reverted"          # 已回退：本次结果不是收敛路径产出的
            stat["reach_reverted"] = True
            # 收敛阶段确实读过盘 → 如实暴露其读盘量，A3 可据此扣减（**不**回滚 scanned：
            # 累计读盘是事实；也**不**清除 reach_build_docs：首建成本真实发生过，r16 复核取证）
            stat["reach_reverted_docs"] = int(stat.get("scanned") or 0) - _pre_scan
            for _k in ("reach_seed", "reach_diffused", "reach_hops", "reach_diffused_paths",
                       "reach_fresh_nodes"):
                stat.pop(_k, None)

        # T2：跨桶 LIKE（§七 截断点：分池截断，索引类不再挤掉知识类）
        # 截断依据=相关度（先全量打分再排序截断）：命中集沿 entries（目录枚举序）
        # 排列，原来「取前 GLOBAL_CAP 条再打分」等价于用写入顺序抽签决定谁进
        # 候选池。cap 值不变，变的只是拿什么排序（见 cut_by_relevance）。
        # ---- S7 倒排候选层：用发布表取出「含查询词全部 bigram」的节点作为候选 ----
        # 候选 ⊇ 真命中集 → 随后仍走既有 `_like` 精确过滤 → 结果与全表扫描一致（契约 §7「候选内加速」定位）。
        # 不可用时（单字词 / 无发布表 / 空候选）一律回退全表；T3 兜底也强制走全量（保持兜底口径不变）。
        entries_full = entries
        if _s7 and entries:
            _pd = None
            try:
                from . import postings as _pd
            except Exception:
                _pd = None
            if _pd is None:
                gates["s7"] = {"reason": "no_module", "in": len(entries_full),
                               "fallback": "full_scan"}
            else:
                # 发布表是**快照**：节点被改写后可能漏掉命中 → 先验快照指纹，过期即回退全量
                # （宁可慢，不可丢召回）。指纹只做 stat（≈目录数，本库 1,074 目录 ≈ 0.03s）。
                # MDCG_S7_FRESHNESS=skip 只供离线对照实测使用；生产默认 auto。
                # 组合语义（S7×语义路）：MDCG_SEMANTIC=1 时「frontmatter 有 semantic 的节点」
                # 在 _like 之外**无条件入池**（见下方 hits 构造），而该标志只在节点文件里
                # （索引快照没有该键）→ 候选阶段无法识别它们，窄化会漏读 → 漏召回。
                # 故语义路开启时 S7 一律不窄化（独立复核 2026-09-19 REJECT 第 1 条）。
                _sem = semantic_on()
                _stale = ""
                if not _sem and os.environ.get("MDCG_S7_FRESHNESS") != "skip":
                    _stale = _pd.stale_reason(self.root, self.index.get("nodes") or {})
                if _sem:
                    gates["s7"] = {"reason": "semantic_on", "in": len(entries_full),
                                   "fallback": "full_scan"}
                elif _stale:
                    gates["s7"] = {"reason": "stale_index:" + _stale,
                                   "in": len(entries_full), "fallback": "full_scan"}
                else:
                    _ids7, _why = _pd.candidates(self.root, terms)
                    if _ids7 is None:
                        gates["s7"] = {"reason": _why, "in": len(entries_full),
                                       "fallback": "full_scan"}
                    else:
                        # 保持**索引原序**（不是发布表序）：候选集是过滤，不是重排。
                        # 完全并列（同分同重要性）时排序稳定，故只有原序一致，S7 的
                        # results 才能与全表扫描逐字节一致（独立复核口径）。
                        _keep = []
                        for _e in entries_full:
                            _nid = _e.get("id") or os.path.splitext(
                                os.path.basename(_e.get("path") or ""))[0]
                            if _nid in _ids7:
                                _keep.append(_e)
                        gates["s7"] = {"cands": len(_keep), "in": len(entries_full),
                                       "terms": len(terms)}
                        if _keep:
                            entries = _keep
                            _s7_narrowed = True
                        else:
                            gates["s7"]["fallback"] = "no_candidate"
        _s7_scan0 = stat["scanned"]        # S7 窄化前的扫描基线（供 T3 兜底还原口径）
        docs_all = self._read_many(entries, stat)
        # 语义资格（MDCG_SEMANTIC=1）：fm.semantic 节点无条件入池
        hits = [d for d in docs_all if self._like(d[2], d[1], terms)
                or (semantic_on() and d[1].get("semantic"))]
        # ---- S3 图扩散激活（契约 §3 S3；flag 控，默认关）----
        # 为何：edges 一直只被写入、检索从不使用（审计偏差 1）。这里从词法命中节点沿
        # edges 双向扩散，把「关联但词面不重叠」的记忆作为独立一层候选（TIER_SPREAD）。
        # 约束：扩散只走索引里的 edges（不读文件）；**不得引入未通过 S1/S2 门控**的节点；
        # 命中不足时自然落回原 T2/T3 路径（无召回损失）。
        if _s3 and hits:
            # 组合语义（S3×S7）：S7 只是 T2 的候选加速器，**不得**改变 S3 的可达域。
            # 若把窄化后的 entries 当 allowed，S7+S3 会把扩散限制在词法候选内，
            # 恰好丢掉 S3 的目标（「只沿 edges 可达、词面无交集」的节点）→ 组合退化。
            # 故 allowed 恒取 S1/S2 门控后的全量候选（S7 关时 entries 即全量，行为不变）。
            _s3_pool = entries_full if _s7_narrowed else entries
            _act, _seeds = self._spread_activation(_s3_pool, hits, _s3_hops, _s3_decay)
            if _act:
                _by_path = {e.get("path"): e for e in _s3_pool}
                _extra_entries = [_by_path[p] for p in _act if p in _by_path]
                _extra_docs = self._read_many(_extra_entries, stat)
                _seen = {d[0]["path"] for d in hits}
                _extra_docs = [d for d in _extra_docs if d[0]["path"] not in _seen]
                _sc_hits = self._score(hits, q, qb, pool_cfg)
                _sc_extra = self._score(_extra_docs, q, qb, pool_cfg)
                _bonus = [(doc, max(sc, _act.get(doc["path"], 0.0) * _s3_gain))
                          for doc, sc in _sc_extra]
                _merged = _sc_hits + _bonus
                _valid = sum(1 for _, s in _merged if s > 0)
                gates["s3"] = {"seeds": len(_seeds), "expanded": len(_bonus),
                               "hops": _s3_hops, "decay": _s3_decay,
                               "gain": _s3_gain, "valid": _valid}
                if _valid >= min_results:
                    _merged.sort(key=lambda x: (-x[1], -float(
                        x[0]["frontmatter"].get("importance") or 0),
                        str(x[0].get("id") or "")))
                    if record and _merged[:k]:
                        self.record_access([r[0]["id"] for r in _merged[:k]], TIER_SPREAD)
                    return self._emit(_merged, k, TIER_SPREAD, stat, route_bucket,
                                      record, len(_merged), judge, context,
                                      neg_coverage, big_domain, big_scores, pool_cfg)
            else:
                gates["s3"] = {"seeds": len(_seeds), "expanded": 0,
                               "hops": _s3_hops, "reason": "no_edges"}

        stat["pre_cap"] = len(hits)
        stat["cap"] = GLOBAL_CAP
        hits, _rep = cut_by_relevance(hits, self._score(hits, q, qb, pool_cfg),
                                      GLOBAL_CAP, pools=pool_cfg,
                                      key_of=pooling.doc_key, stat=stat)
        pooling.record_audit(stat, _rep)
        out = try_stage(hits, TIER_GLOBAL_LIKE)
        if out:
            return out

        # T3：全量兜底（同为分池截断点；截断依据同为相关度，importance 作次级键）
        # S7 只作 T2 的候选加速；T2 未达阈值时兜底必须回到**全量**，否则兜底口径被 S7 改变（与改动前不等价）。
        if _s7_narrowed:
            # 口径还原：T3 是「全量兜底」，S7 只是 T2 的加速器——回退时 scanned 必须
            # 与「从未窄化」逐值一致，否则同配置的审计指标被候选层改变（独立复核要求）。
            # 窄化那趟的读取量另记为 attempted（诚实计量，不混入 scanned）。
            _attempted = stat["scanned"] - _s7_scan0
            stat["scanned"] = _s7_scan0
            entries = entries_full
            docs_all = self._read_many(entries, stat)
            _s7_narrowed = False
            gates.setdefault("s7", {}).update(
                {"fallback": "t3_full", "attempted": _attempted})
        stat["pre_cap"] = len(docs_all)
        stat["cap"] = GLOBAL_CAP
        picked, _rep = cut_by_relevance(docs_all,
                                        self._score(docs_all, q, qb, pool_cfg),
                                        GLOBAL_CAP, pools=pool_cfg,
                                        key_of=pooling.doc_key, stat=stat)
        pooling.record_audit(stat, _rep)
        scored = self._score(picked, q, qb, pool_cfg)
        return self._emit(scored, k, TIER_GLOBAL_SCAN, stat, route_bucket,
                          record, len(picked), judge,
                          context, neg_coverage, big_domain, big_scores, pool_cfg)

# 生效条件：无条件按 hits 的 path 与 allowed 集合做双向邻接扩散（只读 index["nodes"] 的 edges/target，不读节点文件），
# hops<=0 或无命中/无 allowed 时返回 ({}, seeds)；否则返回 ({被扩散节点 path: decay**跳数}, seeds)，不含种子自身；
# 目标必须是 allowed（未过 S1/S2 门控的节点一律不引入）且在 index 中存在。
    def _spread_activation(self, entries, hits, hops, decay):
        """从词法命中节点沿 edges 双向扩散（契约 §3 S3）。

        只用索引快照（`edges`/`target`）不读文件；`allowed` = 已通过 S1/S2 门控的候选，
        因此扩散**不可能**把未过门控的节点拉进结果。返回 ({nid: 激活值}, 种子 id 集合)。
        """
        nodes = self.index.get("nodes") or {}
        allowed, seeds = set(), set()
        for e in entries:
            nid = e.get("id") or os.path.splitext(os.path.basename(e.get("path") or ""))[0]
            if nid in nodes:
                allowed.add(nid)
        for d in hits:
            p = d[0].get("path")
            nid = os.path.splitext(os.path.basename(p or ""))[0]
            if nid in nodes and nid in allowed:
                seeds.add(nid)
        if hops <= 0 or not seeds:
            return {}, seeds
        adj = {}
        for nid in allowed:
            for ed in (nodes[nid].get("edges") or []):
                if isinstance(ed, dict):
                    t = str(ed.get("target") or "")
                    if t:
                        adj.setdefault(nid, set()).add(t)
                        adj.setdefault(t, set()).add(nid)
        act, seen, frontier = {}, set(seeds), set(seeds)
        for hop in range(1, hops + 1):
            nxt = set()
            for nid in frontier:
                for t in adj.get(nid, ()):
                    if t in seen or t not in allowed or t not in nodes:
                        continue
                    seen.add(t)
                    nxt.add(t)
                    # 键用**节点文件路径**（与 search 的 entries/doc["path"] 同口径，避免 id/path 混用）
                    act[nodes[t].get("path") or t] = decay ** hop
            frontier = nxt
            if not frontier:
                break
        return act, seeds


# 生效条件：entries 逐条经 _read 得 content 为 None 的跳过、_open_content 返回 None 的跳过，其余以 (e, fm, c) 进入 docs，并把 len(docs) 累加进 stat["scanned"] 后返回 docs；
    def _read_many(self, entries, stat):
        docs = []
        for e in entries:
            fm, c = self._read(e)
            if c is None:
                continue
            c = self._open_content(fm.get("id"), fm, c)
            if c is None:
                continue                    # 无密钥 / 身份不符 → 不参与检索
            docs.append((e, fm, c))
        stat["scanned"] += len(docs)
        return docs

    @staticmethod
# 生效条件：terms 为空时返回 False；否则任一 t 在 positive_body(content) 的小写串中出现，或该 t 的小写形式出现在 fm 的 tags（tags 取自 fm.get("tags") or []，缺键或假值按空列表拼接）小写串中即返回 True。
    def _like(content, fm, terms):
        # 负条件行（`# 不适用条件：`）是反例声明，不作召回键：命中它只应由
        # judge_qualification 走 REJECT，不能把节点召回。tags 仍参与匹配。
        tags = " ".join(str(t) for t in (fm.get("tags") or []))
        body = nodefile.positive_body(content)
        # 双边小写化：英文大小写统一（中文无大小写不受影响）
        body_l = body.lower()
        tags_l = tags.lower()
        return any(t in body_l or t.lower() in tags_l for t in terms)

# 生效条件：semantic_on() 为真、semantic.canonical.pair_hits 导入成功且该 doc 的 fm 有 semantic 时 raw = min(1.0, max(lexical_sim(qb, 该文档 normalize_en 后的 bigram, mode), pair_hits(fm["semantic"], q)) + tag_bonus)，否则 raw = min(1.0, sim + tag_bonus)；tag_bonus 仅在 fm.tags 中有 t 满足 str(t) in q 或 q in str(t) 时为 0.05，否则 0.0；pools 为真值时 raw 再乘 pooling.weight_of(...) 并夹到 [0,1]；返回 scored 列表；
    def _score(self, docs, q, qb, pools=None, mode=None):
        # 语义摘要路（MDCG_SEMANTIC=1 opt-in，默认关闭零回归）：
        # doc 侧 fm.semantic 标准原子序列 × query 归一序列的组合窗口共现分
        # （semantic/canonical.pair_hits），与词法分 **max 聚合**——语义路=
        # 候选生成器/终排器（judge_ranking 同定位），词法强时不拖累、词法
        # 零交集（L3 盲测靶区）时独立成臂。延迟导入+异常静默降级（与
        # en_zh_terms 同风格：semantic 模块缺失不阻断主链路）。
        sem_on = semantic_on()
        _pair_hits = None
        if sem_on:
            try:
                from .semantic import canonical as _canon
                _pair_hits = _canon.pair_hits
            except Exception:
                sem_on = False
        # S4 层级激活优先级（契约 §3 S4）：加成而非过滤；子开关须显式 =1
        _s4_on = (os.environ.get("MDCG_RETRIEVAL_PIPELINE") == "1"
                  and os.environ.get("MDCG_GATE_S4_LAYER") == "1")
        _boost = layer_boosts() if _s4_on else None
        scored = []
        for e, fm, c in docs:
            # 归一化 content 后取 bigram（与 query 侧 normalize_en 对称）
            c_norm = normalize_en(c)
            nb = bigrams(c_norm)
            sim = lexical_sim(qb, nb, mode)
            tag_bonus = 0.05 if any(str(t) in q or q in str(t)
                                    for t in (fm.get("tags") or [])) else 0.0
            if sem_on and _pair_hits is not None and fm.get("semantic"):
                raw = min(1.0, max(sim, _pair_hits(fm["semantic"], q))
                          + tag_bonus)
            else:
                raw = min(1.0, sim + tag_bonus)
            if pools:                       # §七 降权：乘数只来自显式权重表（可复算）
                raw = max(0.0, min(1.0, raw * pooling.weight_of(
                    fm.get("id") or e["path"], e, pools)))
            if _boost:                      # S4：层级加成（最后一步；上限仍夹在 1.0）
                raw = min(1.0, raw + _boost.get(str(fm.get("layer") or ""), 0.0))
            scored.append(({"id": fm.get("id") or e["path"], "frontmatter": fm,
                            "content": c, "path": e["path"]}, raw))
        return scored


# 生效条件：scored 按 (-分数, -importance) 排序后取前 k 条逐条判定——judge 为真值时调 judge_qualification(r[0], stat["query"] 或 "", context)，否则 qual={"state":None,"reason":"judge_disabled"}；再把 neg_coverage 前 3 条以 id=其 path 追加到 out 末尾（该项 layer=="rejected"→STATE_REJECT，否则 STATE_DEFER，读文件抛 OSError 则跳过）；record 为真且 results 非空时调 record_access；pool_plan 以 pooling.plan(stat["cap"] 或模块级 GLOBAL_CAP, pools) 生成，stat["pool_taken"] 为真时并入 taken/cands/lost；返回 (out, 含 tier/scanned/bucket/candidates/pre_cap/cap/cut_order/pools/big_domain 的审计 dict)；
    def _emit(self, scored, k, tier, stat, bucket, record, candidates,
              judge, context, neg_coverage, big_domain=None, big_scores=None,
              pools=None):
        # ---- S5 负记忆抑制（契约 §3 S5；flag 控、默认关）----
        # 现状：rejected/unresolved 命中只会被「附加」到结果里（sensing），对正候选毫无影响。
        # 这里把它变成**抑制信号**：与负记忆「边相邻」或「词面高度重叠」的正候选按
        # w ← w × (1-λ) 降权（只降权、不删除、下限 0）；开关默认关 → 行为与改动前一致。
        _s5 = (os.environ.get("MDCG_RETRIEVAL_PIPELINE") == "1"
               and os.environ.get("MDCG_GATE_S5_NEG") == "1")
        _s5_lam, _s5_thr, _s5_hits = 0.5, 0.5, []
        # λ/阈值的解析必须在「scored 是否为空」之外：否则 scored 为空时负记忆条目会按默认 λ 降权、
        # 审计也会记错配置（独立复核 2026-09-19 指出）
        if _s5 and neg_coverage:
            try:
                _s5_lam = min(1.0, max(0.0, float(os.environ.get("MDCG_NEG_LAMBDA", "0.5"))))
            except ValueError:
                _s5_lam = 0.5
            try:
                _s5_thr = min(1.0, max(0.0, float(os.environ.get("MDCG_NEG_SIM", "0.5"))))
            except ValueError:
                _s5_thr = 0.5
        if _s5 and neg_coverage and scored:
            _negs = []
            for _nc in neg_coverage[:10]:
                try:
                    with open(os.path.join(self.root, _nc["path"]), encoding="utf-8") as _f:
                        _fm_n, _c_n = nodefile.loads(_f.read())
                except Exception:
                    continue        # 解析异常同样放行（信息不足不得中断检索）
                _negs.append((str(_fm_n.get("id") or os.path.splitext(
                    os.path.basename(_nc["path"]))[0]), _fm_n, _c_n))
            for _i, (_doc, _sc) in enumerate(scored):
                _pid = str(_doc.get("id") or _doc.get("path") or "")
                _pt = {str(_e.get("target") or "")
                       for _e in (_doc["frontmatter"].get("edges") or [])
                       if isinstance(_e, dict)}
                _hit = False
                for _nid, _nfm, _nc_content in _negs:
                    _nt = {str(_e.get("target") or "")
                           for _e in (_nfm.get("edges") or []) if isinstance(_e, dict)}
                    if _nid == _pid or _pid in _nt or _nid in _pt:
                        _hit = True
                        break
                    try:
                        _sim = lexical_sim(bigrams(normalize_en(_doc.get("content") or "")),
                                           bigrams(normalize_en(_nc_content)))
                    except Exception:
                        _sim = 0.0
                    if _sim >= _s5_thr:
                        _hit = True
                        break
                if _hit:
                    scored[_i] = (_doc, max(0.0, _sc * (1.0 - _s5_lam)))
                    _s5_hits.append(_pid)
        # 审计只在「确有负记忆命中」时落键（与 S1/S2「产生信息才落键」同规则）
        if _s5 and neg_coverage:
            _g = stat.setdefault("gates", {})
            _g["s5"] = {"lambda": _s5_lam, "threshold": _s5_thr,
                        "neg": len(neg_coverage), "suppressed": len(_s5_hits),
                        "suppressed_ids": _s5_hits[:20]}
        scored.sort(key=lambda x: (-x[1],
                                   -float(x[0]["frontmatter"].get("importance") or 0),
                                   str(x[0].get("id") or "")))
        results = scored[:k]
        # ---- S6 一致性交叉验证（契约 §3 S6；flag 控、默认关）----
        # 只读复用 crosscheck 的「赛道 × 来源执照」判定：对 top-k 逐个给出赛道、声明依据是否被
        # 该赛道许可、以及断言条数。**不进主排序**（scored/out 的次序一律不动），只落审计摘要。
        _s6 = (os.environ.get("MDCG_RETRIEVAL_PIPELINE") == "1"
               and os.environ.get("MDCG_GATE_S6_CROSSCHECK") == "1")
        if _s6:
            try:
                from . import crosscheck as _cc
            except Exception:
                _cc = None
            if _cc is not None:
                _rows6, _track6, _flagged6 = [], {}, []
                for _r in results:
                    _fm6 = _r[0].get("frontmatter") or {}
                    _c6 = _r[0].get("content") or ""
                    try:
                        _tk6 = _cc.classify_track(_fm6, _c6)
                        _bs6 = _fm6.get("verification_basis")
                        _ok6 = bool(_cc.basis_licensed(_tk6, _bs6)) if _bs6 else False
                        _cl6 = len(_cc.extract_claims(_fm6, _c6))
                    except Exception:
                        _tk6, _bs6, _ok6, _cl6 = "undetermined", None, False, 0
                    _track6[_tk6] = _track6.get(_tk6, 0) + 1
                    _rid6 = _r[0].get("id") or _r[0].get("path")
                    _rows6.append({"id": _rid6, "track": _tk6, "basis": _bs6,
                                   "licensed": _ok6, "claims": _cl6})
                    # 只在「赛道已定 ∧ 声明了依据 ∧ 依据不被该赛道许可」时点名（赛道未定不点名）
                    if _tk6 in ("science", "humanities") and _bs6 and not _ok6:
                        _flagged6.append({"id": _rid6, "track": _tk6, "basis": _bs6})
                stat.setdefault("gates", {})["s6"] = {
                    "checked": len(_rows6), "by_track": _track6,
                    "flagged": _flagged6, "rows": _rows6}
        # 资格判定（与性能正交）
        out = []
        for r in results:
            if judge:
                qual = self.judge_qualification(r[0], stat.get("query") or "",
                                                context)
            else:
                qual = {"state": None, "reason": "judge_disabled"}
            out.append((r[0], r[1], qual))
        # 把被负记忆覆盖的查询也作为结果条目返回（首条），方便调用方感知
        for nc in neg_coverage[:3]:
            full_path = os.path.join(self.root, nc["path"])
            try:
                with open(full_path, encoding="utf-8") as f:
                    fm, content = nodefile.loads(f.read())
            except OSError:
                continue
            entry = {"id": nc["path"], "frontmatter": fm,
                     "content": content, "path": nc["path"]}
            qual = {"state": STATE_REJECT if nc["layer"] == "rejected" else STATE_DEFER,
                    "reason": f"查询已被{nc['layer']}层覆盖：见 {nc['path']}"}
            # S5 开时：负记忆条目不再与正候选同权（契约 §3 S5）
            out.append((entry, (max(0.0, 1.0 - _s5_lam) if _s5 else 1.0), qual))
        if record and results:
            self.record_access([r[0]["id"] for r in results], tier)
        pool_plan = pooling.plan(stat.get("cap") or GLOBAL_CAP, pools)
        if stat.get("pool_taken"):
            # 各池「候选/计划额度/实取/被挤掉」——计划额度之外的审计面
            # taken：含空池回流后的实取；lost：`max(0, cands - taken)`（被池内额度挤掉）
            pool_plan["taken"] = dict(stat["pool_taken"])
            pool_plan["cands"] = dict(stat.get("pool_cands") or {})
            pool_plan["lost"] = dict(stat.get("pool_lost") or {})
        meta = {"tier": tier, "scanned": stat["scanned"], "bucket": bucket,
                "candidates": candidates,
                     # §七 分池审计：截断前候选数 / 全局额度 / 生效分池计划
                     "pre_cap": stat.get("pre_cap"), "cap": stat.get("cap"),
                     # 截断依据审计：relevance=先打分再排序截断（现行）
                     "cut_order": stat.get("cut_order"),
                     "pools": pool_plan,
                     "covered_neg": [nc["path"] for nc in neg_coverage],
                     # 阶段 1 大域收敛结果 + 完整打分明细（白箱可审计）
                     "big_domain": big_domain,
                     "big_domain_scores": big_scores,
                     # reach 收敛层审计（2026-09-18）：reach=converged/off/short_term/...
                     # 与 reach_seed（倒排命中数）/reach_diffused（图扩散增量）——
                     # A3「触碰量随查询变化」的观测面（scanned 只报读盘数）
                     "reach": stat.get("reach"),
                     "reach_seed": stat.get("reach_seed"),
                     "reach_diffused": stat.get("reach_diffused"),
                     "reach_hops": stat.get("reach_hops"),
                     # 首建全库读盘量（仅本次调用发生重建时出现）与新节点并入数
                     "reach_build_docs": stat.get("reach_build_docs"),
                     "reach_fresh_nodes": stat.get("reach_fresh_nodes"),
                     # 回退审计：reach_reverted=True 表示本次结果来自全量路径；
                     # reach_reverted_docs 为收敛阶段已发生的读盘量（A3 可据此扣减）
                     "reach_reverted": stat.get("reach_reverted"),
                     "reach_reverted_docs": stat.get("reach_reverted_docs")}
        # 分阶段审计仅在门控真的产生信息时落键（默认关闭 → meta 与改动前逐字节一致；契约 §5.3）
        if stat.get("gates"):
            meta["gates"] = stat["gates"]
        # 时间算子审计（阶段二 4.1）：同规则——只在时间算子真的启用时落键，
        # 未启用则 meta 键集合与改动前逐字节一致（默认关零变更纪律）。
        if stat.get("time_filter"):
            meta["time_filter"] = stat["time_filter"]
        return out, meta

    # ---------- 五大单元之四：反思 / 验证 / 输出 ----------

# 生效条件：无条件计算 d_prev/_compute_d(query, results)、states（results 为假值时 states 为空列表）与 D_meta 边界压力向量（d_meta.compute(self, query, results)，MDCG_D_META 关闭时三代理恒 0.0），并在追加前取 reflection_log 末条的 d_meta 作前值（无前值时为 None）算出 d_meta_delta，随后尝试追加 reflection_log（OSError 静默吞掉），返回含 user_feedback、d_meta、d_meta_delta 的反思 dict；
    def reflect(self, query: str, results, user_feedback: str = None):
        """反思单元（白箱第 3 篇第 13 章）。

        输入：本次查询 + 检索结果 + 用户反馈（可选）
        输出：反思记录（追加到 _reflection.jsonl）

        反思内容：
        - 信息差 D(t,C) 增量（**D_task**：`_compute_d` 口径零变更）
        - 命中节点的资格态分布
        - 是否触发 BLINDSPOT（覆盖率不足）
        - 用户反馈时记录「预测与事实的偏差」→ 知识飞轮的入口

        双 D 分离（智能论3.4 §2.7.0 DEV-002/002a）：**并列**落 `d_meta`
        （边界压力向量，三代理各自 [0,1]、**不合成单值**）与 `d_meta_delta`
        （与上一条反思的逐字段差，首条为 None）。D_meta **不参与**
        `_compute_d`——D_task 与 D_meta 对象不同、数值不互换；此处只做结构性
        投影落痕，供 predict / autonomy / self_state 三个上层消费。
        `MDCG_D_META` 关闭时 `d_meta` 三代理恒 0.0 且 `d_meta_delta=None`
        （显式回退留痕，不是缺键）。
        """
        from . import d_meta as _d_meta        # 惰性导入：叶子只读模块，防循环
        d_prev = self._last_d()
        d_curr = self._compute_d(query, results)
        states = [r[2]["state"] for r in results] if results else []
        meta = _d_meta.compute(self, query=query, results=results)
        recs = self.last_d_records()
        meta_prev = recs[-1].get("d_meta") if recs else None
        reflection = {
            "t": time.time(),
            "query": query,
            "d_prev": d_prev,
            "d_curr": d_curr,
            "d_delta": d_curr - d_prev,
            "d2": (d_curr - d_prev) - (d_prev - self._d_prev2()),
            "states": dict((s, states.count(s)) for s in set(states)),
            "n_results": len(results),
            "feedback": user_feedback,
            "d_meta": {k: float(meta.get(k) or 0.0)
                       for k in _d_meta.PROXY_KEYS},
            "d_meta_delta": (_d_meta.diff(meta_prev, meta)
                             if meta.get("enabled") else None),
        }
        try:
            append_jsonl(self.reflection_log, reflection)
        except OSError:
            pass
        return reflection

# 生效条件：list(read_jsonl(self.reflection_log)) 至少 2 条记录时返回倒数第二条的 "d_curr"（该键缺失时回落 1.0，键在而其值为 None 时返回 None），不足 2 条时返回 1.0。
    def _d_prev2(self):
        """上一次的前一次 D 值，用于二阶差分。"""
        recs = list(read_jsonl(self.reflection_log))
        if len(recs) >= 2:
            return recs[-2].get("d_curr", 1.0)
        return 1.0

# 生效条件：list(read_jsonl(self.reflection_log)) 非空时返回最后一条的 "d_curr"（该键缺失时回落 1.0，键在而其值为 None 时返回 None），为空时返回 1.0。
    def _last_d(self):
        recs = list(read_jsonl(self.reflection_log))
        if recs:
            return recs[-1].get("d_curr", 1.0)
        return 1.0

# 生效条件：无条件返回 list(read_jsonl(self.reflection_log))（日志为空时返回空列表）。
    def last_d_records(self):
        """反思日志全量记录（测试/审计用）。"""
        return list(read_jsonl(self.reflection_log))

# 生效条件：results 为假值（空列表/None）时返回 1.0；否则返回 max(0.0, 1.0 - （r[1]>0 且 r[2]["state"]==STATE_ACCEPT 的条数 / len(results)）)，query 不参与计算；
    def _compute_d(self, query, results):
        """信息差 D 的简化度量（白箱第 4 篇）：
        D = 1 - 有效命中比例，0=信息差为零（完美），1=完全空白。

        简化模型：本次查询的「有效命中」= score>0 且 state=ACCEPT 的比例。

        口径声明（智能论3.4 §2.7.0 DEV-002a）：本值是 D_task 的
        「检索-资格链路工程化身」——对象同一、数值不与 wisdom 四分量
        D_norm（验证链路化身）直接互换。
        """
        if not results:
            return 1.0
        accept = sum(1 for r in results
                     if r[1] > 0 and r[2]["state"] == STATE_ACCEPT)
        return max(0.0, 1.0 - accept / len(results))

# 生效条件：to_layer 不属于模块级 LAYERS 时抛 ValueError；self.get(node_id) 取不到节点或当前层（fm.layer 或路径首段）等于 to_layer 时返回 None；否则调 protect.guard_move 后写入 demotion 审计、搬文件到目标层并按新层 _stage、重算 buckets，返回 {id, from, to, path, reason}；
    def _move_layer(self, node_id: str, to_layer: str, reason: str = ""):
        """把节点搬到另一层（可信度降级用），同步索引与 demotion 审计字段。"""
        if to_layer not in LAYERS:
            raise ValueError(f"未知层：{to_layer}")
        node = self.get(node_id)
        if not node:
            return None
        fm = node["frontmatter"]
        from_layer = fm.get("layer") or node["path"].split("/")[0]
        if from_layer == to_layer:
            return None
        # 写保护：受保护节点（self/anchor/标记/高重要性）不得被降级移出保护层
        protect.guard_move(self, node_id, to_layer)
        fm["layer"] = to_layer
        fm["demotion"] = {"t": time.time(), "from": from_layer,
                          "to": to_layer, "reason": reason}
        d = os.path.join(self.root, to_layer)
        os.makedirs(d, exist_ok=True)
        new_path = os.path.join(d, f"{node_id}.md")
        self._write_node(node_id, new_path, fm, node["content"])
        old_full = os.path.join(self.root, node["path"])
        if (os.path.abspath(old_full) != os.path.abspath(new_path)
                and os.path.exists(old_full)):
            os.remove(old_full)
        rel = os.path.relpath(new_path, self.root).replace("\\", "/")
        self._stage(node_id, _strip_empty_gate_fields({
            "path": rel, "layer": to_layer, "tags": fm.get("tags", []),
            "bucket": None, "importance": fm.get("importance", 0.5),
            "created_at": fm.get("created_at", 0),
            "verification_basis": fm.get("verification_basis"),
            "has_neg_conditions": nodefile.has_non_applicable(node["content"]),
            "content_hash": hashlib.sha256(
                node["content"].encode("utf-8")).hexdigest()[:12],
            "temporal": fm.get("temporal"), "spatial": fm.get("spatial"),
            "time_window": (fm.get("condition_space") or {}).get("time_window"),
            "big_domain": fm.get("big_domain"),
            "observation_position": (fm.get("condition_space") or {}).get("observation_position"),
            "evidence_count": fm.get("evidence_count", 0),
        }))
        self.index["buckets"] = self._count_buckets(self.index["nodes"])
        return {"id": node_id, "from": from_layer, "to": to_layer,
                "path": rel, "reason": reason}

# 生效条件：verdict 不在 {confirmed,weakened,falsified} 时抛 ValueError；node_id 取不到节点返回 None；verdict=="falsified" 时以 content[:200] 为假设写入 rejected 层、删除原文件并 _unstage，返回 {"action":"falsified","new_id":None,"evidence_count":None,"demoted":None}；confirmed/weakened 时 confidence 分别 +0.05 / -0.15（夹到 [0,0.99] 并 round 2）、evidence_count 与 positive_evidence/negative_evidence 各 +1、追加 evidence_log，且仅当 weakened 后 confidence < DEMOTE_CONFIDENCE 且 layer=="knowledge" 时调 _move_layer 到 contextual 并 set_state("demoted")，否则 _write_node 回写并同步索引 evidence_count；
    def verify(self, node_id: str, evidence: str, verdict: str):
        """验证单元（白箱第 3 篇第 13 章）：对节点做一次外部验证裁决。

        verdict ∈ {"confirmed", "weakened", "falsified"}
        - confirmed：positive_evidence+1，confidence 上调 +0.05
        - weakened：negative_evidence+1，confidence 下调 -0.15（反例权重更大）
        - falsified：节点移入 rejected/（幂等：相同 hypothesis 不重复）

        每次裁决累加 evidence_count（白箱第 5 篇第 4 章）。
        weakened 后 confidence 跌破 DEMOTE_CONFIDENCE 且原属 knowledge 层 →
        降级为 contextual（假设层），返回 demoted 审计记录。
        """
        if verdict not in ("confirmed", "weakened", "falsified"):
            raise ValueError(f"未知裁决：{verdict}")
        node = self.get(node_id)
        if not node:
            return None
        if verdict == "falsified":
            # 移入 rejected：负记忆化
            self.add_rejected(hypothesis=node["content"][:200],
                              reason=evidence,
                              verification_basis="test")
            # 从原位置删除（节点进入 rejected 层）
            os.remove(os.path.join(self.root, node["path"]))
            self._unstage(node_id)      # 同上：索引删除必须可重放（防幽灵条目）
            trust.invalidate_cache(self)        # 索引已变 → 反查索引作废
            # 地基塌了：直接下游立即标存疑（**同步一跳**，永不抛、不阻断本次裁决）
            propagation = trust.mark_dependents(
                self, node_id,
                reason=f"上游 {node_id} 被证伪（falsified）——依赖的地基已不存在",
                actor="verify:falsified", trigger="verify_falsified")
            return {"action": "falsified", "new_id": None,
                    "evidence_count": None, "demoted": None,
                    "propagation": propagation}
        # confirmed/weakened：调整 confidence（白箱第 5 篇：
        # 反例的权重应该比正例大——这里用非对称步长实现）
        fm = node["frontmatter"]
        cur = float(fm.get("confidence", 0.6))
        step = 0.05 if verdict == "confirmed" else -0.15
        fm["confidence"] = round(min(0.99, max(0.0, cur + step)), 2)
        # 证据计数（白箱第 5 篇第 4 章）：总次数 + 正/反例分开记
        fm["evidence_count"] = int(fm.get("evidence_count") or 0) + 1
        key = ("positive_evidence" if verdict == "confirmed"
               else "negative_evidence")
        fm[key] = int(fm.get(key) or 0) + 1
        fm.setdefault("evidence_log", []).append(
            {"t": time.time(), "verdict": verdict, "evidence": evidence})
        demoted = None
        if (verdict == "weakened" and fm["confidence"] < DEMOTE_CONFIDENCE
                and (fm.get("layer") or "") == "knowledge"):
            demoted = self._move_layer(
                node_id, "contextual",
                reason=f"confidence {fm['confidence']} < {DEMOTE_CONFIDENCE}")
            # 层降级 = 生命周期降级（②）：knowledge→contextual 即 state→demoted。
            # 受保护节点已被 `guard_move` 拦在上一层（走不到这里）；此处仍按负路由
            # 柔和处理——ok=False 只说明状态不可降，不回滚已完成的层迁移。
            self.set_state(node_id, "demoted",
                           reason=f"confidence {fm['confidence']} < {DEMOTE_CONFIDENCE}",
                           actor="verify:weakened")
        else:
            self._write_node(node_id, os.path.join(self.root, node["path"]),
                             fm, node["content"])
            e = self.index["nodes"].get(node_id)
            if e is not None:
                e["evidence_count"] = fm["evidence_count"]
        # 验证态流转（可验证记忆单元）：外部证据裁决**就是**验证态迁移。
        #   confirmed → verified（首次转正；已在 verified 则幂等 no-op）
        #   weakened  → doubted（证据被削弱 ⇒ 存疑，待复核）
        # 受保护节点不接受降级——负路由 ok=False 只说明「不可降」，不回滚已完成的
        # 证据计数（与上方 lifecycle 降级同风格：不假装成功，也不推翻既成事实）。
        if verdict == "confirmed":
            ver = self.set_verification(
                node_id, "verified",
                reason=f"外部裁决 confirmed：{str(evidence)[:80]}",
                actor="verify:confirmed", evidence=evidence,
                method=fm.get("verification_basis"), trigger="verify")
        else:
            ver = self.set_verification(
                node_id, "doubted",
                reason=f"外部裁决 weakened：{str(evidence)[:80]}",
                actor="verify:weakened", evidence=evidence, trigger="verify")
        # 结论已变 ⇒ 下游的「地基动了」：同步一跳传播（永不抛，降级不阻断）
        propagation = trust.mark_dependents(
            self, node_id, reason=f"上游验证结论变为 {verdict}",
            actor=f"verify:{verdict}", trigger=f"verify_{verdict}")
        return {"action": verdict, "confidence": fm["confidence"],
                "evidence_count": fm["evidence_count"], "demoted": demoted,
                "verification": ver, "propagation": propagation}

    # ---------- 知识飞轮（白箱第 2 篇第 8 章）----------

# 生效条件：error_report 是 str 时经 json.loads 解析，否则按映射使用；question 由 query/actual_state/expected_state 缺键回落 "?" 拼成；detail 为 list 时非 dict 元素跳过，其中 type=="same_condition_divergence"、"condition_clash" 及其他真值 type 各渲染一条现场短语并以 " | " 连接作为 context（known_clues 取 missing 或 ""）传给 add_unresolved，返回 {"unresolved_id": nid, "question": question}；
    def flywheel_step(self, error_report: str):
        """知识飞轮入口：错误 → 寻找遗漏条件 → 验证 → 结构更新。

        error_report: 形如 {"query": ..., "expected_state": "ACCEPT",
                              "actual_state": "REJECT/BLINDSPOT",
                              "missing": "可能漏掉的 condition 描述"}

        行为：
        1. 把 missing 解析为新的条件分支
        2. 写入 unresolved/ 目录，等待人工/外部验证基底裁决
        3. 触发 reflect 记录这次飞轮输入
        """
        try_data = json.loads(error_report) if isinstance(error_report, str) else error_report
        question = (f"为何 {try_data.get('query','?')} 出现 {try_data.get('actual_state','?')}"
                    f" 而期望 {try_data.get('expected_state','?')}？")
        clues = try_data.get("missing", "")
        # detail：判定器的结构化缺口（[{type, with, same_condition, ...}]）。
        # 原先整字段被忽略——上游产出了结构却送不到下游。这里提炼为「现场」，
        # 使条目在人工/外部裁决时能看到原始对照（如「同条件两条不同取值」）。
        detail = try_data.get("detail") or []
        parts = []
        if isinstance(detail, list):
            for d in detail:
                if not isinstance(d, dict):
                    continue
                if d.get("type") == "same_condition_divergence":
                    parts.append("同条件取值分歧 vs %s（条件重合 %s / 槽位 %s / 结论差异 %s）"
                                 % (d.get("with"), d.get("same_condition"),
                                    d.get("slot_overlap"), d.get("conclusion_overlap")))
                elif d.get("type") == "condition_clash":
                    parts.append("条件互斥 vs %s（覆盖 %s）"
                                 % (d.get("with"), d.get("score")))
                elif d.get("type"):
                    parts.append("%s vs %s" % (d.get("type"), d.get("with")))
        nid = self.add_unresolved(question=question, known_clues=clues,
                                  goal="结构精化：补缺失条件分支（或裁决取值）",
                                  context=" | ".join(parts))
        return {"unresolved_id": nid, "question": question}

    # ---------- 访问计数：append-only，检索路径不写节点文件 ----------

# 生效条件：无条件尝试把 {"t": time.time(), "ids": list(node_ids), "tier": tier} 追加到 access_log，append 抛 OSError 时静默吞掉；
    def record_access(self, node_ids, tier=None):
        try:
            append_jsonl(self.access_log,
                         {"t": time.time(), "ids": list(node_ids), "tier": tier})
        except OSError:
            pass

# 生效条件：无 required 形参；遍历 self.access_log 的 read_jsonl 记录，ts 取 rec.get("t", 0)（缺键回落 0），对 rec.get("ids", []) 中每个 nid 计数加一，且 ts 大于该 nid 已记最大 ts 时更新 last[nid]=ts，返回 (counts, last)；
    def access_counts(self):
        counts, last = {}, {}
        for rec in read_jsonl(self.access_log):
            ts = rec.get("t", 0)
            for nid in rec.get("ids", []):
                counts[nid] = counts.get(nid, 0) + 1
                if ts > last.get(nid, 0):
                    last[nid] = ts
        return counts, last

# 生效条件：access_counts() 的 counts 为空返回 0；否则对每个 nid 在索引中存在且 _read 返回 fm 非 None 的节点累加 access_count、last_access 取 max 并落盘、n +1；最后在 FileLock 下清空 access_log 并返回 n（索引缺该 id 或读盘失败的不计）。
    def compact_access(self):
        counts, last = self.access_counts()
        if not counts:
            return 0
        n = 0
        for nid, c in counts.items():
            e = self.index["nodes"].get(nid)
            if not e:
                continue
            fm, content = self._read(e)
            if fm is None:
                continue
            fm["access_count"] = int(fm.get("access_count") or 0) + c
            fm["last_access"] = max(float(fm.get("last_access") or 0), last.get(nid, 0))
            self._write_node(nid, os.path.join(self.root, e["path"]), fm, content)
            n += 1
        with FileLock(self.access_log):
            atomic_write(self.access_log, "")
        return n

    # ---------- 健康度 ----------

# 生效条件：无条件以 index.get("buckets", {}) 生成分桶健康度并记 total_nodes，再遍历 index["nodes"] 逐条读文件（抛 OSError 跳过），按 layer 统计 total/ccg_complete/verification_basis_set/neg_conditions_set，另统计 rejected 与 unresolved 层数量，返回 h；
    def health(self):
        """扩充：分桶健康度 + 5 要素完整度 + 验证基底覆盖率 + 负记忆密度。"""
        h = routing.bucket_health(self.index.get("buckets", {}))
        h["total_nodes"] = len(self.index["nodes"])
        # 5 要素完整度（全节点扫一遍，可能慢但只在 health() 调用）
        layer_stats = {}
        neg_stats = {}
        for e in self.index["nodes"].values():
            full_path = os.path.join(self.root, e["path"])
            try:
                with open(full_path, encoding="utf-8") as f:
                    fm, content = nodefile.loads(f.read())
            except OSError:
                continue
            cpl = nodefile.ccg_completeness(content)
            layer = e["layer"]
            if layer not in layer_stats:
                layer_stats[layer] = {"total": 0, "ccg_complete": 0,
                                      "verification_basis_set": 0,
                                      "neg_conditions_set": 0}
            layer_stats[layer]["total"] += 1
            if cpl["complete"]:
                layer_stats[layer]["ccg_complete"] += 1
            if fm.get("verification_basis"):
                layer_stats[layer]["verification_basis_set"] += 1
            if e.get("has_neg_conditions"):
                layer_stats[layer]["neg_conditions_set"] += 1
            if layer in ("rejected", "unresolved"):
                if layer not in neg_stats:
                    neg_stats[layer] = 0
                neg_stats[layer] += 1
        h["ccg_by_layer"] = layer_stats
        h["neg_memory_counts"] = neg_stats
        return h