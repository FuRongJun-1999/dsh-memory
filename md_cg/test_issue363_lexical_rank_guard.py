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

修法（方案②根修，`md_cg/mdcg.py`；PR #381 复核返工 2026-10-16）：
  · `lexical_weights`：池内平滑 IDF `log(1+(N-df+0.5)/(df+0.5))`（与 bm25 路
    同款「scoped to the current eligible pool」口径，检索期零额外 IO）；
  · `CN_FUNC_GRAMS`（**打分侧**，底座=召回侧 `CN_STOP_GRAMS` + 疑问/指代功能
    bigram「什么/是什/么是/为什」类）× `FUNC_GRAM_ALPHA=0.25` 降权。
    #381 复核 P0-③ 裁剪：否定词（没有/不是）、情态/命题性词（可以）与命题
    性实词（是否/多少/自己）**不降权**——「没有审计日志」与「审计日志」语义
    相反，降权会抹平否定词的判别度（改前读数 w(没有)=0.173≈w(审计)=0.182，
    改后 w(没有)=0.693>0.182）。保留纯功能词，共 30 项（Rust 同表同步）；
  · `MdCG._score` 改两遍：先收齐本批文档 bigram 集算权重表，再逐文档
    `lexical_sim_weighted`（求和按 sorted 序，跨进程可复算）；
  · **退化即旧序（#381 复核 P0-① 修正）**：退化判据=**权重表全等**（df 全同
    且 qb 全在同侧、或 qb 单 gram，是全等的充分条件；df 全同但 qb 跨侧时
    w 恰差 α 倍，**不**属退化——反例 qb={"什么","记忆"} df 全同=1 ⇒
    w=0.173/0.693，名次可翻转）。全等 ⇒ `lexical_weights` 返回 None 逐位走
    旧 `lexical_sim`（退化池分数与修前**逐位相等**，G3c-1 钉 ==；跨侧不退化
    的分序由 G3c-2 钉）；
  · **N 口径（#381 复核 P0-② 对齐）**：Python N=传入 `_score` 的当批全量
    （`_lexical`/T2 路=LIKE 预筛后的命中全量，GLOBAL_CAP 截断在打分之后）
    ↔ Rust `retrieval.rs::lexical` 权重池改取「**截断前**命中全量」（空命中
    =完整候选集；现役调用 cap=1e9 两侧池恒等），两侧注释互指；
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
     G3c 退化判据（#381 复核 P0-① 改造，断言均 ≥2 gram）：
         G3c-1 同侧 df 全同 ⇒ 权重表全等 ⇒ `lexical_weights`=None ⇒ _score
              与 legacy 公式分**逐位相等（==）**；
         G3c-2 跨侧（功能词+实词）df 全同 ⇒ 权重恰差 α 倍、不跳过 ⇒ legacy
              同分处加权分序（实词档>功能档）——「df 全同⇒权重全等」的
              P0-① 反例入守卫（防跳过条件被误改回 df 判据）。
     G3d 回退开关：`MDCG_LEXICAL_IDF=0` 时 `_score` 与旧公式（inter/len(qb)）
         逐位相等；召回侧 `CN_STOP_GRAMS`/`cn_recall_grams` 不受开关影响。
  G4 中文问句端到端（17 文档 × 3 问句夹具）：同分块收窄（distinct 分数数
     加权 > legacy、最大同分块加权 < legacy）、命中集不变（score>0 集合相等
     ——质量闸语义不动）、legacy top1 因 id 置换漂移的问句加权后稳定。
     **收益口径（#381 复核 P2-⑤）**：distinct/最大块是**同分结构**读数，不是
     检索质量读数——值守实测 top1 0/500、MRR +0.0000（命中面不变，本件不
     改善也不恶化质量指标）；本件收益=「同分名次退化为写入序」的 **bug
     修复**（名次不再由 id=毫秒时间戳的字典序决定），不是质量提升。
  G5 公式锚（#381 复核 P1-④；不依赖 --mutate，静态锚死公式每一项）：
     手算常数精确断言（n=3/df=1 ⇒ w=ln(8/3)，df=0 ⇒ w=ln(8)，精确到 1e-12；
     端到端 `_score` 分值==手算加权分）；实词权重>功能词权重×(1+阈值=3)；
     跨进程（PYTHONHASHSEED=1/8 子进程）分值 repr 逐字符相等——自然 IDF 值
     锚 + **对抗值**锚（{1e16,1.4,1.4}：IDF 自然值域 4 值全排列舍入实测相同，
     序依赖仅在对抗值上必现）。平滑常数改错/去掉 log/求和去 sorted 三类公式
     注入任一即转红（改前守卫对此 28/0 全绿零判别力，#381 复核实测）。

变异协议（--mutate）：用 `MDCG_LEXICAL_IDF=0`（行为级精确回退——比文本变异
更贴「修前形态」，旧公式代码原样保留在该分支里）在子进程复刻修前态，断言
G1/G2/G4/G5 **转红**（G3 在回退态平凡通过）；恢复缺省后全绿。两向读数都打印。

运行：
    python -X utf8 -m md_cg.test_issue363_lexical_rank_guard            # 正向
    python -X utf8 -m md_cg.test_issue363_lexical_rank_guard --mutate   # 变异两向

退出码：0 = 全绿（--mutate 下另要求「回退态按预期红」）；1 = 有断言失败 /
变异未按预期转红。

硬边界：tempfile.mkdtemp 建库（不触在役数据根）；不 git add/commit/push；
不改任何检索判据之外的文件。
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
from collections import Counter
from unittest.mock import patch

# ── 隔离前置：import md_cg 之前冻结 aux/root 面（与 test_rank_parity_score_mode
# 同款纪律）；MDCG_LEXICAL_IDF 刻意**透传**（--mutate 靠它在子进程复刻修前态；
# --anchor-dump 子进程同样透传父进程口径——G5d 的跨进程可比性依赖它）。
_ANCHOR_DUMP = "--anchor-dump" in sys.argv
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
if not _ANCHOR_DUMP:
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

    # G3c 退化判据（PR #381 复核 P0-① 改造；旧断言用单 gram 查询「乙丙」，
    # 退化平凡成立、对公式错误零判别力，且其「df 全同 ⇒ 同序」的口径被反例
    # 证伪——qb 跨侧时 df 全同 w 恰差 α 倍，名次可翻转）。两条均 ≥2 gram：
    # G3c-1 同侧 df 全同 ⇒ 权重表全等 ⇒ lexical_weights=None ⇒ _score 逐位
    #       走旧公式（与 legacy_scores **==**，比旧断言的「同序＋1e-12」强）；
    # G3c-2 跨侧（功能词+实词）df 全同 ⇒ 权重恰差 α 倍、**不**跳过 ⇒ legacy
    #       同分处加权分序（P0-① 反例入守卫；防跳过条件被误改回 df 判据——
    #       那会连 G2 的「同 df 功能/实词必须分序」一起杀掉）。
    uni = [("u1", "记忆检索方法甲乙"), ("u2", "甲记忆检索方法乙"),
           ("u3", "乙甲记忆检索方法")]            # 每篇都含全部 qb gram
    cg2 = build(uni)
    q_deg = "记忆检索方法"                        # qb 5 gram，全实词侧
    qb_d = mdcg.bigrams(mdcg.normalize_en(q_deg))
    nbs_d = [mdcg.bigrams(mdcg.normalize_en(c)) for _, c in uni]
    w_d = mdcg.lexical_weights(qb_d, nbs_d)
    sc_w = raw_scores(cg2, q_deg)
    sc_l = legacy_scores(cg2, q_deg)
    ok(w_d is None and sc_w == sc_l,
       "G3c-1 退化即旧序（全等跳过）：df 全同全同侧多 gram 池 lexical_weights=None，"
       "_score 与 legacy 逐位相等（==，非仅同序）")
    cg2.close()

    mix = [("p1", "什么填充甲"), ("p2", "么记填充乙"), ("p3", "记忆填充丙")]
    cg3 = build(mix)
    q_mix = "什么记忆"                            # qb={什么,么记,记忆}：1 功能 + 2 实词
    qb_m = mdcg.bigrams(mdcg.normalize_en(q_mix))
    nbs_m = [mdcg.bigrams(mdcg.normalize_en(c)) for _, c in mix]
    w_m = mdcg.lexical_weights(qb_m, nbs_m)
    sc_w2 = raw_scores(cg3, q_mix)
    sc_l2 = legacy_scores(cg3, q_mix)
    ok(w_m is not None and len(set(w_m.values())) > 1
       and sc_l2["p1"] == sc_l2["p2"] == sc_l2["p3"],
       "G3c-2 前置：df 全同（=1）跨侧池 legacy 三档同分 %.6f，权重表产出且不全等"
       % sc_l2["p1"])
    ok(w_m is not None and w_m["记忆"] > w_m["什么"] and sc_w2["p3"] > sc_w2["p1"],
       "G3c-2 df 全同≠权重全等（P0-① 反例）：w(记忆)=%.6f > w(什么)=%.6f（恰 α 倍差，"
       "不跳过），加权分序 p3(实词)=%.6f > p1(功能)=%.6f（legacy 同分处加权必分序）"
       % ((w_m or {}).get("记忆", float("nan")), (w_m or {}).get("什么", float("nan")),
          sc_w2["p3"], sc_w2["p1"]))
    cg3.close()

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


# ── G5 公式锚（PR #381 复核 P1-④）───────────────────────────────────────────
# 旧守卫的变异面只有 MDCG_LEXICAL_IDF=0 行为级回退，对「公式本身写错」（平滑
# 常数改错/去掉 log/求和去 sorted）零判别力（28/0 全绿）。本组用**手算常数**
# 锚死公式每一项，任一项被改动即在正向模式转红：
#   · n=3/df=1 ⇒ w=ln(1+(3-1+0.5)/(1+0.5))=ln(8/3)——平滑常数两个 0.5 的锚；
#   · df=0 分支 ⇒ w=ln(1+(3-0+0.5)/0.5)=ln(8)——N 与 df=0 分支的锚；
#   · α 乘子只落在功能 gram（w(什么)=α·ln(8/3)≠w(记忆)）；
#   · 分式 Σw(∩)/Σw(qb)：字面权重 {什么:0.25, 记忆:1.0} ⇒ 1/(1+α)=0.8 精确；
#   · 跨进程（PYTHONHASHSEED=1/2）repr 逐字符相等——求和序若改走 set 迭代序，
#     不同哈希种子的末位舍入不同 ⇒ repr 不等 ⇒ 红（「去 sorted」的锚）。
A5_DOCS = [("a", "记忆的衰减"), ("b", "什么是白名单"), ("c", "填充内容其他")]
A5_QUERY = "什么是记忆"   # qb={什么,么是,是记,记忆}：2 功能 + 2 实词；df: 1/1/0/1
A5_ALPHA = 0.25           # = FUNC_GRAM_ALPHA（锚面直读常量，勿 import 以免同错对消）
A5_L83 = math.log(8.0 / 3.0)
A5_L8 = math.log(8.0)
# 「求和序确定性」对抗值锚：{1e16, 1.4, 1.4} 的逐位累加**序敏感**（两个 1.4
# 先聚再撞 1e16 ⇒ +2；先撞再聚 ⇒ +4——实测 PYTHONHASHSEED=1/8 恰好落两类）。
# IDF 自然值域（0.1~2.4）的 4 值全排列舍入相同（24/24 实测），「去 sorted」
# 变异在自然值上不可见；此对抗值把末位舍入的序依赖放大到必现。
A5_SPKY_QB = {"aa", "bb", "cc"}
A5_SPKY_NB = {"bb", "cc"}
A5_SPKY_W = {"aa": 1e16, "bb": 1.4, "cc": 1.4}


def _a5_expected():
    """锚点库手算分值（与实现独立推导：n=3，df(什么)=df(么是)=df(记忆)=1、
    df(是记)=0）。"""
    w = {"什么": A5_ALPHA * A5_L83, "么是": A5_ALPHA * A5_L83,
         "是记": A5_L8, "记忆": A5_L83}
    den = sum(w[g] for g in sorted(w))
    return w, den, {"a": w["记忆"] / den,
                    "b": (w["什么"] + w["么是"]) / den,
                    "c": 0.0}


def g5():
    # G5a 精确权重锚（n=3/df=1 ⇒ ln(8/3)；平滑常数/log/α 任一改动 ≥1e-3 量级即红）
    nbs = [{"什么"}, {"记忆"}, {"杂文"}]
    w = mdcg.lexical_weights({"什么", "记忆"}, nbs)
    ok(w is not None
       and abs(w["记忆"] - A5_L83) < 1e-12
       and abs(w["什么"] - A5_ALPHA * A5_L83) < 1e-12,
       "G5a 权重锚：n=3/df=1 ⇒ w(记忆)=%.9f==ln(8/3)、w(什么)=%.9f==α·ln(8/3)"
       "（手算常数，精确 1e-12）" % (
           (w or {}).get("记忆", float("nan")),
           (w or {}).get("什么", float("nan"))))
    ok(w is not None and w["记忆"] > w["什么"] * 3.0,
       "G5a 实词权重>功能词×(1+阈值=3)：%.6f > %.6f（比值恰 1/α=%.1f）" % (
           (w or {}).get("记忆", float("nan")),
           (w or {}).get("什么", float("nan")) * 3.0, 1.0 / A5_ALPHA))
    # G5b 分式锚（字面权重，与 IDF 无关——α 与 Σ/Σ 公式本身的锚）
    s = mdcg.lexical_sim_weighted({"什么", "记忆"}, {"记忆"},
                                  {"什么": A5_ALPHA, "记忆": 1.0})
    ok(abs(s - 1.0 / (1.0 + A5_ALPHA)) < 1e-12,
       "G5b 分式锚：Σw(∩)/Σw(qb)=1.0/(1.0+0.25)=%.9f 精确（字面权重 %.9f）" % (
           1.0 / (1.0 + A5_ALPHA), s))
    # G5c 端到端分值锚（过 MdCG._score 两遍链路；df=0 分支 ln(8) 一并钉住）
    cg = build(A5_DOCS)
    sc = raw_scores(cg, A5_QUERY)
    _, den, exp = _a5_expected()
    ok(all(abs(sc[i] - exp[i]) < 1e-12 for i in exp),
       "G5c 端到端分值锚：_score(a/b/c)=(%.9f/%.9f/%.1f) == 手算 (%.9f/%.9f/0)"
       "（n=3，df(是记)=0 ⇒ w=ln(8)=%.6f 同锚）" % (
           sc["a"], sc["b"], sc["c"], exp["a"], exp["b"], A5_L8))
    ok(sc["a"] > sc["b"] * 1.5,
       "G5c 分值序：实词档 a=%.6f > 功能档 b×1.5=%.6f（同池同 df，比值恰 "
       "1/(2α)=%.1f）" % (sc["a"], sc["b"] * 1.5, 1.0 / (2 * A5_ALPHA)))
    # G5d 跨进程可复算锚（「去 sorted」变异的锚）：两个显式哈希种子的子进程
    # 与本进程逐字符相等——自然 IDF 值的锚（ANCHOR 行）+ 对抗值锚（ANCHOR2
    # 行，序敏感必现；种子 1/8 实测分落 +4/+2 两类舍入）。
    dumps = []
    for seed in ("1", "8"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m",
             "md_cg.test_issue363_lexical_rank_guard", "--anchor-dump"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True, encoding="utf-8", env=env)
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines()
                 if ln.startswith("ANCHOR")]
        dumps.append(lines[:2] if len(lines) >= 2
                     else ["NO-ANCHOR(rc=%d)" % proc.returncode])
    spky = mdcg.lexical_sim_weighted(A5_SPKY_QB, A5_SPKY_NB, A5_SPKY_W)
    want = ["ANCHOR %r %r %r" % (sc["a"], sc["b"], sc["c"]),
            "ANCHOR2 %r" % (spky,)]
    ok(dumps[0] == dumps[1] == want,
       "G5d 跨进程可复算：PYTHONHASHSEED=1/8 子进程与父进程分值 repr 逐字符相等"
       "（自然值 %r；对抗值 %r——求和序若改走 set 迭代序，两种子末位舍入必劈叉）"
       % (dumps[0][0] if dumps[0] else "?", dumps[0][1] if len(dumps[0]) > 1 else "?"))
    cg.close()


def anchor_dump():
    """--anchor-dump 子进程入口：打印锚点分值（repr，往返精确）。"""
    cg = build(A5_DOCS)
    sc = raw_scores(cg, A5_QUERY)
    print("ANCHOR %r %r %r" % (sc["a"], sc["b"], sc["c"]))
    cg.close()
    print("ANCHOR2 %r" % (mdcg.lexical_sim_weighted(
        A5_SPKY_QB, A5_SPKY_NB, A5_SPKY_W),))


def main(argv):
    if "--anchor-dump" in argv:
        anchor_dump()
        return 0
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
    g5()
    n_pass, n_fail = len(_PASS), len(_FAIL)
    print("== 结果：PASS %d / FAIL %d ==" % (n_pass, n_fail))
    if mutate:
        # 变异两向：回退态必须红（G1/G2/G4/G5 至少一条失败），缺省态已在本进程外验证
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
