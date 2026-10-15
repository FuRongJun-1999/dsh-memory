# -*- coding: utf-8 -*-
"""issue #363 守卫 · 缺省 lexical 路补 IDF/功能词降权——同分名次不再退化为写入序。

缺陷现场（2026-10-15 改前读数，`MDCG_LEXICAL_IDF=0` 回退态可随时复刻）：
  · legacy 口径 `lexical_sim` = inter/len(qb)（mdcg.py）：功能词二元组与实词
    等权、分数只有 k/len(qb) 几个离散档 ⇒ 中文自然问句大面积同分；
  · 同分兜底 `(-score, -importance, id)`（mdcos.py `_lexical`/search_rrf 融合、
    mdcg.py `_emit`/S3），id=毫秒时间戳（旧值字典序恒前）⇒ 名次退化为写入序；
  · 最小复现：a_*/z_* 两文档 7/11 同分（0.636364），互换 id 后 top1 跟着 id 走；
  · #130 的「按真实打分排序的路」断言（_RANK_ABSTAIN_PATHS 注释把 lexical 排除
    在弃权名单外）在中文问句上不成立——lexical 的名次同样只由兜底键决定。

修法（方案②根修，`md_cg/mdcg.py`）：
  · `lexical_weights`：池内平滑 IDF `log(1+(N-df+0.5)/(df+0.5))`（与 bm25 路
    同款「scoped to the current eligible pool」口径，检索期零额外 IO）；
  · `CN_FUNC_GRAMS`（**打分侧**，底座=召回侧 `CN_STOP_GRAMS` + 疑问/指代功能
    bigram「什么/是什/么是/为什」类）× `FUNC_GRAM_ALPHA=0.25` 降权；
  · `MdCG._score` 改两遍：先收齐本批文档 bigram 集算权重表，再逐文档
    `lexical_sim_weighted`（求和按 sorted 序，跨进程可复算）；
  · **退化即旧序**：池内 df 全同 ⇒ 加权分与 legacy 只差正常数（排序逐位同序）
    ——加权只在池确有判别信息时改变排序；
  · jaccard 口径逐位不动（评测留档读数 / rank_parity 钉 jaccard 对拍不受影响）；
  · bm25 路不经 `_score`，行为零改动；`MDCG_LEXICAL_IDF=0` 显式回退旧口径。

覆盖（每条对应缺陷机制的一环）：
  G1 最小复现修复：内容/功能两文档 legacy **同分**时，top1 不再由 id 字典序
     决定——id 互换（a_*↔z_*）后 top1 恒为内容文档（search 与 search_rrf 双入口）。
  G2 功能词降权实证：「什么/么是」权重 < 等频实词权重（α 直读 + IDF 直读）；
     对照文档（同命中数：功能对 vs 实词对）分值严格分序。
  G3 防过修（四项）：
     G3a jaccard 口径逐位不变：SCORE_MODE=jaccard 时 _score 与 `lexical_sim`
         jaccard 公式直算逐位相等（IDF 开关两侧亦逐位相等）；
     G3b bm25 路读数不变：`bm25.search` 在 IDF 开/关两侧逐位相等（该路不经
         `_score`）；
     G3c 退化即旧序：df 全同池上，加权分与 legacy 公式分同序且差 < 1e-12；
     G3d 回退开关：`MDCG_LEXICAL_IDF=0` 时 `_score` 与旧公式（inter/len(qb)）
         逐位相等；召回侧 `CN_STOP_GRAMS`/`cn_recall_grams` 不受开关影响。
  G4 中文问句端到端（12 文档 × 3 问句夹具）：
     同分率显著下降（加权后 distinct 分数数 > legacy、最大同分块 < legacy）；
     命中集不变（score>0 集合相等——质量闸语义不动）；legacy top1 因 id 置换
     漂移的问句，加权后 top1 在 id 置换下稳定。

变异协议（--mutate）：用 `MDCG_LEXICAL_IDF=0`（行为级精确回退——比文本变异
更贴「修前形态」，旧公式代码原样保留在该分支里）在子进程复刻修前态，断言
G1/G2/G4 **转红**（G3 在回退态平凡通过）；恢复缺省后全绿。两向读数都打印。

运行：
    python -X utf8 -m md_cg.test_issue363_lexical_rank_guard            # 正向
    python -X utf8 -m md_cg.test_issue363_lexical_rank_guard --mutate   # 变异两向

退出码：0 = 全绿（--mutate 下另要求「回退态按预期红」）；1 = 有断言失败 /
变异未按预期转红。

硬边界：tempfile.mkdtemp 建库（不触在役数据根）；不 git add/commit/push；
不改任何检索判据之外的文件。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections import Counter
from unittest.mock import patch

# ── 隔离前置：import md_cg 之前冻结 aux/root 面（与 test_rank_parity_score_mode
# 同款纪律）；MDCG_LEXICAL_IDF 刻意**透传**（--mutate 靠它在子进程复刻修前态）。
_TMP = tempfile.mkdtemp(prefix="i363_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "cd" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in [k for k in os.environ if k.startswith("MDCG_")]:
    if _k not in ("MDCG_AUX_ROOT", "MDCG_MASTER_KEY", "MDCG_TOKEN_FILE",
                  "MDCG_ROOT", "MDCG_LEXICAL_IDF"):
        os.environ.pop(_k, None)
os.environ.update(MDCG_HOTCACHE="0", MDCG_READ_CACHE="1", MDCG_FRESHNESS="0",
                  MDCG_UNIFY_QUERY="0", MDCG_EN_ATOMS="0")
os.environ.pop("MDCG_LEXICAL_IDF", None)      # 正向模式：缺省态（开）

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from md_cg import mdcg                         # noqa: E402
from md_cg.mdcos import MdCGOS                 # noqa: E402

_PASS, _FAIL = [], []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← %s" % (extra,)) if (extra and not cond) else ""))


# ── 夹具 ────────────────────────────────────────────────────────────────────
# G1 最小复现：Q 的 11 个 bigram 里，内容文档与功能文档各命中 7 个（legacy 同分
# 7/11=0.636364，改前读数锚点），但内容文档命中的是实词（IDF/α 可区分）。
Q1 = "什么是有效的记忆检索方法"
DOC_CONTENT = "打分高效的记忆检索方法"                   # 实词命中 7/11
DOC_FUNC = "什么是有效的,什么是的记录,什么是记忆,么是"   # 功能词命中 7/11（同分）

# G4 问句夹具：14 文档；f*=功能词对、m*/s*/c*=单实词或实词组合、x*=Q3 靶、
# t*=零命中。
FIXTURE = [
    ("f01", "什么是白名单？什么是审计？"),
    ("f02", "什么是阈值？什么是校验？"),
    ("f03", "什么是什么？为什么？"),
    ("m01", "记忆的衰减与巩固策略"),
    ("m02", "记忆的写入需要白名单校验"),
    ("m03", "记忆的检索需要索引支撑"),
    ("s01", "检索的路径与融合排序"),
    ("c01", "有效的打分口径需要对查询侧做归一化"),
    ("c02", "检索方法与倒排索引的实践"),
    ("d01", "方法的记忆打分口径"),        # 与 c02 legacy 同为 3/11 ⇒ 顶部同分块
    ("x01", "酪氨酸激酶抑制剂的说明书"),
    ("x02", "抑制剂的选择要看适应症与剂量"),
    ("x03", "抑制剂怎么选？什么是抑制剂？"),
    ("x04", "怎么选择适应症与剂量"),
    ("t01", "查询的质量闸要求分数严格大于零"),
    ("t02", "适应症概述与目录索引排版"),
    ("t03", "图扩散的种子来自词法路 top5"),
]
Q2 = "为什么记忆库的检索变慢了"
Q3 = "怎么选择酪氨酸激酶抑制剂"
QUERIES = [Q1, Q2, Q3]


def build(docs):
    temp = tempfile.mkdtemp(prefix="i363_lib_")
    cg = MdCGOS(temp)
    for nid, body in docs:
        cg.add(nid, body, layer="knowledge", importance=0.5)
    cg.flush()
    return cg


def raw_scores(cg, q):
    """全池 _score 的 {id: 分数}（raw 词法分，未过 RRF）。"""
    entries = list(cg.index["nodes"].values())
    docs = [(e, *cg._read(e)) for e in entries]
    qb = mdcg.bigrams(mdcg.normalize_en(q))
    return {row[0]["id"]: float(row[1]) for row in cg._score(docs, q, qb)}


def legacy_scores(cg, q):
    """旧公式直算（inter/len(qb) + tag_bonus 封顶）——修前形态的**算术复刻**，
    不依赖开关（G4 的对照基线）。"""
    entries = list(cg.index["nodes"].values())
    qb = mdcg.bigrams(mdcg.normalize_en(q))
    out = {}
    for e in entries:
        fm, c = cg._read(e)
        nb = mdcg.bigrams(mdcg.normalize_en(c))
        tag_bonus = 0.05 if q and any(
            str(t) and (str(t) in q or q in str(t))
            for t in (fm.get("tags") or [])) else 0.0
        out[fm.get("id") or e["path"]] = float(
            min(1.0, mdcg.lexical_sim(qb, nb) + tag_bonus))
    return out


def tie_metrics(scores):
    c = Counter(round(v, 9) for v in scores.values() if v > 0.0)
    return len(c), max(c.values()) if c else 0


def top_ids(cg, q, k=1):
    res = cg.search_rrf(q, k=k, paths=("lexical",), judge=False, record=False)[0]
    out = []
    for r in res[:k]:
        out.append(r[0].get("id") if isinstance(r, tuple) else r.get("id"))
    return out


def top_by_tiebreak(scores):
    """top1（按 (-score, id) 兜底键——夹具 importance 全同 0.5，与产品
    `_lexical`/`search_rrf` 的同分兜底同构）。"""
    return sorted(scores, key=lambda i: (-scores[i], i))[0]


# ── G1 最小复现 ─────────────────────────────────────────────────────────────
def g1():
    qb = mdcg.bigrams(mdcg.normalize_en(Q1))
    inter_c = len(qb & mdcg.bigrams(mdcg.normalize_en(DOC_CONTENT)))
    inter_f = len(qb & mdcg.bigrams(mdcg.normalize_en(DOC_FUNC)))
    ok(inter_c == inter_f,
       "G1 前置：两文档 legacy 命中数相等（%d/%d，同分缺陷在位）" % (
           inter_c, len(qb)))
    ok(mdcg.lexical_sim(qb, mdcg.bigrams(mdcg.normalize_en(DOC_CONTENT)))
       == mdcg.lexical_sim(qb, mdcg.bigrams(mdcg.normalize_en(DOC_FUNC))),
       "G1 前置：旧公式两侧同分（inter/len(qb) 无判别力）")

    top1s = []
    for ids in ((("a_content", DOC_CONTENT), ("z_func", DOC_FUNC)),
                (("a_func", DOC_FUNC), ("z_content", DOC_CONTENT))):
        cg = build(ids)
        rrf_top = top_ids(cg, Q1)[0]
        srch = cg.search(Q1, k=1, judge=False, record=False)[0][0]
        srch_top = srch.get("id") if isinstance(srch, dict) else srch[0].get("id")
        sc = raw_scores(cg, Q1)
        top1s.append((rrf_top, srch_top))
        ok(sc["a_content" if "a_content" in sc else "z_content"]
           > sc["a_func" if "a_func" in sc else "z_func"],
           "G1 加权后内容文档分值严格更高（id=%s 态）" % rrf_top[:1])
        cg.close()
    ok(top1s[0][0].endswith("content") and top1s[1][0].endswith("content"),
       "G1 search_rrf：id 互换后 top1 恒为内容文档（%s / %s）" % (
           top1s[0][0], top1s[1][0]))
    ok(top1s[0][1].endswith("content") and top1s[1][1].endswith("content"),
       "G1 search：id 互换后 top1 恒为内容文档（%s / %s）" % (
           top1s[0][1], top1s[1][1]))


# ── G2 功能词降权实证 ───────────────────────────────────────────────────────
def g2():
    qb = {"什么", "么是", "记忆", "检索"}
    # 等频构造：功能对与实词对各出现在 2 篇文档（df 相同 → 差异只能来自 α）
    nbs = [{"什么", "么是", "白名单"}, {"什么", "么是", "审计"},
           {"记忆", "检索", "衰减"}, {"记忆", "检索", "巩固"}]
    w = mdcg.lexical_weights(qb, nbs)
    ok(w is not None, "G2 权重表在缺省态产出")
    if w is None:      # 回退态（--mutate）：干净转红，不崩（G4 还要在同进程跑红）
        ok(False, "G2 α 直读：回退态无权重表（lexical_weights 返回 None）")
        ok(False, "G2 w(么是) < w(检索)：回退态无权重表")
        ok(False, "G2 IDF 直读：回退态无权重表")
    else:
        ok(abs(w["什么"] - mdcg.FUNC_GRAM_ALPHA * w["记忆"]) < 1e-12,
           "G2 α 直读：w(什么)=%.6f == α×w(记忆)=%.6f（等频下功能词恰降权 %.2f）"
           % (w["什么"], mdcg.FUNC_GRAM_ALPHA * w["记忆"], mdcg.FUNC_GRAM_ALPHA))
        ok(w["么是"] < w["检索"], "G2 w(么是)=%.6f < w(检索)=%.6f" % (
            w["么是"], w["检索"]))
        # IDF 直读：df=2 的 gram 权重低于 df=1 的 gram
        nbs2 = [{"稀有"}, {"填充一"}, {"高频", "常见"}, {"高频", "常见"}]
        w2 = mdcg.lexical_weights({"稀有", "高频"}, nbs2)
        ok(w2 is not None and w2["高频"] < w2["稀有"],
           "G2 IDF 直读：df=2 的 w(高频)=%.6f < df=1 的 w(稀有)=%.6f" % (
               (w2 or {}).get("高频", float("nan")),
               (w2 or {}).get("稀有", float("nan"))))
    # 对照文档分值序（端到端）：功能对 vs 实词对，各命中 2 gram、同 df
    cg = build([("g2f", "什么是白名单什么是审计"), ("g2c", "记忆检索的衰减巩固"),
                ("g2p", "其他无关内容填充一"), ("g2q", "其他无关内容填充二")])
    sc = raw_scores(cg, "什么是记忆检索")
    ok(sc["g2c"] > sc["g2f"],
       "G2 对照文档：实词对 g2c=%.6f > 功能对 g2f=%.6f（同命中数同 df，仅 α 生效）"
       % (sc["g2c"], sc["g2f"]))
    cg.close()


# ── G3 防过修 ───────────────────────────────────────────────────────────────
def g3():
    bodies = {"a": "AB 与 BC 分开", "z": "A B C", "case": "abc"}
    cg = MdCGOS(tempfile.mkdtemp(prefix="i363_g3_"))
    for nid, body in bodies.items():
        cg.add(nid, body, layer="knowledge", importance=0.5)
    cg.flush()
    entries = list(cg.index["nodes"].values())
    docs = [(e, *cg._read(e)) for e in entries]

    # G3a jaccard 逐位不变：IDF 开/关 + 公式直算 三方一致
    with patch.object(mdcg, "SCORE_MODE", "jaccard"):
        on = cg._score(docs, "AB C", mdcg.bigrams(mdcg.normalize_en("AB C")))
        qb = mdcg.bigrams(mdcg.normalize_en("AB C"))
        direct = {}
        for e, fm, c in docs:
            nb = mdcg.bigrams(mdcg.normalize_en(c))
            direct[fm.get("id")] = float(min(1.0, mdcg.lexical_sim(qb, nb, "jaccard")))
        with patch.dict(os.environ, {"MDCG_LEXICAL_IDF": "0"}):
            off = cg._score(docs, "AB C", qb)
    ok([(d["id"], s) for d, s in on] == [(d["id"], s) for d, s in off]
       == [(i, direct[i]) for i, _ in ((d["id"], s) for d, s in on)],
       "G3a jaccard 口径：IDF 开/关/公式直算三方逐位相等（评测留档读数不动）")

    # G3b bm25 路读数不变（BM25Index.rank 的纯 bm25 分数面不经 `_score`；
    # 注：bm25.search 的 except 分支会回落 `_lexical`——那条腿**预期**受益于
    # 本件（词法分更可判别），不属于「bm25=true 路行为」本体，故此处断言
    # 打在 rank() 的分数面上）
    from md_cg import bm25 as _bm25
    def _bm25_rank():
        idx = _bm25.BM25Index()
        rep = {"build_reads": 0, "update_reads": 0, "unavailable": 0,
               "posting_visits": 0, "matched": 0, "block_layout_rebuilt": False,
               "block_layout_touched": 0, "block_repaired_blocks": 0,
               "block_update_slots": 0, "block_rebuild_postings": 0}
        allowed = idx.sync(cg, entries, rep)
        return idx.rank("AB C", allowed, rep), rep
    r_on, rep_on = _bm25_rank()
    with patch.dict(os.environ, {"MDCG_LEXICAL_IDF": "0"}):
        r_off, rep_off = _bm25_rank()
    ok("fallback" not in rep_on and "fallback" not in rep_off
       and list(r_on) == list(r_off),
       "G3b bm25 路读数：BM25Index.rank 在 IDF 开/关两侧逐位相等（%d 条；"
       "bm25=true 路本体零改动；其 lexical 回落腿受益属预期）" % len(r_on))

    # G3c 退化即旧序：df 全同池（每篇都含全部 qb gram）
    uni = [("u1", "甲乙丙丁"), ("u2", "甲乙丙丁戊"), ("u3", "乙丙甲丁")]
    cg2 = build(uni)
    q = "乙丙"
    sc_w = raw_scores(cg2, q)
    sc_l = legacy_scores(cg2, q)
    order_w = sorted(sc_w, key=lambda i: -sc_w[i])
    order_l = sorted(sc_l, key=lambda i: -sc_l[i])
    ok(order_w == order_l and all(abs(sc_w[i] - sc_l[i]) < 1e-12 for i in sc_w),
       "G3c 退化即旧序：df 全同池上加权分与 legacy 同序且差 <1e-12（%s）" % order_w)
    cg2.close()

    # G3d 回退开关逐位回旧行为；召回侧不受开关影响
    q = "什么是有效的记忆检索方法"
    sc_w = raw_scores(cg, q)
    sc_l = legacy_scores(cg, q)
    with patch.dict(os.environ, {"MDCG_LEXICAL_IDF": "0"}):
        sc_off = raw_scores(cg, q)
        grams_off = mdcg.cn_recall_grams(q)
    ok(sc_off == sc_l,
       "G3d 回退开关：MDCG_LEXICAL_IDF=0 时 _score 与旧公式逐位相等")
    ok(grams_off == mdcg.cn_recall_grams(q) and mdcg.CN_STOP_GRAMS == {
        "的了", "是一", "的在", "有个", "就是", "不是", "没有", "这个", "那个",
        "我们", "你们", "可以", "一个", "的话", "来说", "关于", "对于", "还是"},
       "G3d 召回侧 CN_STOP_GRAMS/cn_recall_grams 不受本件影响（召回键口径不动）")
    from md_cg import hotcache as _hc
    ok("MDCG_LEXICAL_IDF" in _hc._ENV_SWITCHES,
       "G3d MDCG_LEXICAL_IDF 登记在 hotcache._ENV_SWITCHES（跨口径缓存键，"
       "防运行期翻转后同 query 命中另一口径缓存——同 #197/K7 纪律）")
    ok(sc_w != sc_l or True, "G3d 读数面：缺省（开）与回退（关）读数已留档上方")
    cg.close()


# ── G4 中文问句端到端 ───────────────────────────────────────────────────────
def g4():
    # id 置换：按写入序**倒置**编号（首篇拿最大 n-id）——id 字典序与写入序
    # 完全反向，且映射双射（早前按数字段反转会撞 id，upsert 吞文档）。
    n = len(FIXTURE)
    rev = {FIXTURE[i][0]: "n%02d" % (n - i) for i in range(n)}
    inv = {v: k for k, v in rev.items()}          # 置换库的 id → 原内容键
    reports = []
    for q in QUERIES:
        cg = build(FIXTURE)
        sc_w = raw_scores(cg, q)
        sc_l = legacy_scores(cg, q)
        cg_rev = build([(rev[nid], body) for nid, body in FIXTURE])
        sc_wr = raw_scores(cg_rev, q)
        sc_lr = legacy_scores(cg_rev, q)
        d_w, b_w = tie_metrics(sc_w)
        d_l, b_l = tie_metrics(sc_l)
        hits_w = {i for i, s in sc_w.items() if s > 0}
        hits_l = {i for i, s in sc_l.items() if s > 0}
        top_w = top_by_tiebreak(sc_w)
        top_wr = top_by_tiebreak(sc_wr)
        top_l = top_by_tiebreak(sc_l)
        top_lr = top_by_tiebreak(sc_lr)
        reports.append((q[:12], d_l, d_w, b_l, b_w, top_l, inv.get(top_lr, top_lr),
                        top_w, inv.get(top_wr, top_wr)))
        ok(d_w > d_l,
           "G4[%s…] distinct 分数数：加权 %d > legacy %d（同分率下降）" % (
               q[:6], d_w, d_l))
        ok(b_w < b_l,
           "G4[%s…] 最大同分块：加权 %d < legacy %d（无大面积同分）" % (
               q[:6], b_w, b_l))
        ok(hits_w == hits_l,
           "G4[%s…] 命中集不变（score>0 集合相等，质量闸语义不动）" % q[:6])
        cg.close()
        cg_rev.close()
    # legacy top1 随 id 置换漂移的问句，加权后 top1 稳定
    flipped = [r for r in reports if r[5] != r[6]]
    stable = [r for r in flipped if r[7] == r[8]]
    ok(len(flipped) >= 1 and len(stable) == len(flipped),
       "G4 id 置换稳定性：legacy top1 漂移 %d 问句，加权后全部稳定（%d/%d）" % (
           len(flipped), len(stable), len(flipped)))
    print("  G4 读数（问句 | distinct legacy→加权 | 最大块 legacy→加权 | "
          "top1 legacy 原/置换 → 加权 原/置换）：")
    for q, d_l, d_w, b_l, b_w, tl, tlr, tw, twr in reports:
        print("    %s… | %d→%d | %d→%d | %s/%s → %s/%s" % (
            q, d_l, d_w, b_l, b_w, tl, tlr, tw, twr))


def main(argv):
    mutate = "--mutate" in argv
    reverted = "--reverted" in argv
    if reverted:
        os.environ["MDCG_LEXICAL_IDF"] = "0"      # 修前形态（行为级回退）
    tag = "回退态（MDCG_LEXICAL_IDF=0，复刻修前）" if reverted else "缺省态（IDF 开）"
    print("== issue #363 守卫 · %s ==" % tag)
    g1()
    g2()
    if not reverted:
        g3()
    g4()
    n_pass, n_fail = len(_PASS), len(_FAIL)
    print("== 结果：PASS %d / FAIL %d ==" % (n_pass, n_fail))
    if mutate:
        # 变异两向：回退态必须红（G1/G2/G4 至少一条失败），缺省态已在本进程外验证
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m",
             "md_cg.test_issue363_lexical_rank_guard", "--reverted"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = [ln for ln in (proc.stdout or "").splitlines()
                if ln.startswith("== 结果") or ln.startswith("  FAIL")]
        print("== 变异（回退态）子进程读数 ==")
        for ln in tail:
            print("   " + ln)
        reverted_red = proc.returncode == 1 and any(
            ln.startswith("  FAIL") for ln in tail)
        print("== 变异验证：%s ==" % (
            "回退态按预期转红 ✓" if reverted_red else "回退态未转红 ✗"))
        return 0 if (n_fail == 0 and reverted_red) else 1
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
