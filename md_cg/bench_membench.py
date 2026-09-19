# -*- coding: utf-8 -*-
"""memory-bench-1000 上的 A/B 评测：四路 RRF vs 五路 RRF（+fuzzy 分级隶属度）

数据集：data/memory-bench-1000.jsonl（真实记忆库分层抽样，保留真实噪声形态）
  250 signal / 400 noise / 350 unlabeled —— 噪声率 40%，且噪声带强重复模式
  （`[会话X·要点N]`、`[consolidation] 演练 N`），正是词法路最容易被抢占的场景。

评测问题：**fuzzy 路（分级隶属度 + 加权同义词组）是净增益还是净损失？**
不做预设结论——四条查询模式 × 两臂 × 同批指标，如实报告。

查询模式（全部确定性可复现，不需要 LLM）：
  orig 原文前 30 字        —— 回忆原话（词法路的天花板）
  head 原文前 8 字         —— 只记得开头
  para 同义词组改写         —— 泛化/同义查询（fuzzy 的靶心）
  drop 随机丢弃一半语义片段 —— 模糊记忆（词法 Jaccard 下降）

指标（Top-K）：
  self@K   查询来源节点是否被召回（MRR 同报）
  sigP@K   Top-K 中 signal 占比
  noiseP@K Top-K 中 noise 占比
  fuzzy_prov  target 命中时 fuzzy 路参与的比例（可审计）

跑法：
    python -m md_cg.bench_membench            # 全量 250 条
    python -m md_cg.bench_membench --n 60     # 抽样 60 条
    python -m md_cg.bench_membench --rebuild  # 重建库
"""
import os
import io
import re
import sys
import json
import time
import random
import argparse
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcg import SYNONYM_GROUPS_WEIGHTED, expand_query_terms
from md_cg.mdcos import MdCGOS

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data", "memory-bench-1000.jsonl")
ROOT = os.path.join(HERE, "_md_cg_membench")

ARM4 = ("lexical", "bucket", "entity", "graph")
ARM5 = ("lexical", "bucket", "entity", "graph", "fuzzy")

SEG_SPLIT = re.compile(r"([，。；：、,;.!?！？\s]+)")


# --------------------------------------------------------------------------- 数据

# 生效条件：按 path（默认模块常量 DATA）以 utf-8 打开文件逐行 json.loads，仅保留 l.strip() 为真的行，返回解析出的记录列表。
def load_rows(path=DATA):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# 生效条件：以 root（默认模块常量 ROOT）建 MdCGOS，rows 为假值（None/空容器）时回落 load_rows() 取数据，逐行用 r["id"] 与 r["text"] 调 add，仅当 r["id"] 已在构建开始时取的 cg.index["nodes"] 快照 have 中才 continue（该快照不随新增 id 更新），verbose 假值则不打印，最后 cg.flush() 并返回 cg。
def build(root=ROOT, rows=None, verbose=True):
    """把数据集写进 md 认知图（幂等：同 id 覆盖）。"""
    rows = rows or load_rows()
    cg = MdCGOS(root, autoflush=200)
    have = set(cg.index["nodes"])
    n_new = 0
    for r in rows:
        if r["id"] in have:
            continue
        cg.add(r["id"], r["text"], layer="contextual",
               tags=r.get("tags") or [], importance=float(r.get("importance") or 0.5),
               verification_basis="data",
               bench_label=r.get("label"), bench_cat=r.get("category"),
               bench_observed_at=r.get("observed_at"),
               bench_chars=r.get("chars"))
        n_new += 1
    cg.flush()
    if verbose:
        print(f"  建库 {root}：新增 {n_new}，库内 {len(cg.index['nodes'])} 节点")
    return cg


# --------------------------------------------------------------------- 查询构造

# 生效条件：遍历 SYNONYM_GROUPS_WEIGHTED 每组，按权重降序找第一个出现在当前 out（初值 text，可能已被前组改写）里的词 w，若组内除 w 外还有词则用其中权重最大者 alt 执行一次 out.replace(w, alt, 1) 且 hits+1，随后 break 该组；返回 (out, hits)。
def paraphrase(text):
    """按加权同义词组做一次同义/泛化改写，返回 (改写后, 替换次数)。

    替换目标取同组权重最高者（通常是组心）——即「说成更泛的词」。
    """
    out, hits = text, 0
    for group in SYNONYM_GROUPS_WEIGHTED:
        for w in sorted(group, key=lambda x: -group[x]):
            if w in out:
                alts = [x for x in group if x != w]
                if alts:
                    alt = max(alts, key=lambda x: group[x])
                    out = out.replace(w, alt, 1)
                    hits += 1
                break
    return out, hits


# 生效条件：text 经 SEG_SPLIT.split 后剔除空白项与分隔符本身得 parts，len(parts)<=1 时原样返回 text，否则按 rng.random() < keep_p（默认 0.5；keep_p 为 0 时全被丢弃）保留片段，若一条未留则回退 [parts[0]]，返回拼接串。
def drop_segments(text, rng, keep_p=0.5):
    """随机丢弃约一半语义片段（模拟「记得不全」）。"""
    parts = [p for p in SEG_SPLIT.split(text)
             if p.strip() and not SEG_SPLIT.fullmatch(p)]
    if len(parts) <= 1:
        return text
    kept = [p for p in parts if rng.random() < keep_p]
    if not kept:
        kept = [parts[0]]
    return "".join(kept)


# 生效条件：rows 中 r.get("label")=="signal" 且 r.get("text") 为真的行入选，n 为真值且 n < len(sig) 时才用 random.Random(seed) 抽 n 条（n=0 等假值不抽样），每条产生 orig/head/drop 三条查询，仅在 paraphrase(t[:60]) 的 hits 非零时追加 para 查询，返回 qs。
def make_queries(rows, n=250, seed=7):
    """从 signal 条目构造查询集（多模式）。"""
    sig = [r for r in rows if r.get("label") == "signal" and r.get("text")]
    rng = random.Random(seed)
    if n and n < len(sig):
        sig = rng.sample(sig, n)
    qs = []
    for r in sig:
        t = r["text"]
        qs.append({"mode": "orig", "q": t[:30], "target": r["id"]})
        qs.append({"mode": "head", "q": t[:8], "target": r["id"]})
        p, hits = paraphrase(t[:60])
        if hits:
            qs.append({"mode": "para", "q": p, "target": r["id"]})
        qs.append({"mode": "drop", "q": drop_segments(t[:80], rng), "target": r["id"]})
    return qs


# ----------------------------------------------------------------------- 评测

# 生效条件：传入 cg 后把 cg._read 换成按 entry["path"] 缓存的闭包（该 path 未命中才调用原 _read），返回该 cache 字典。
def install_read_cache(cg):
    """评测是只读的：把节点文件读进内存，避免每次检索重复 1000 次磁盘 I/O。"""
    cache = {}
    orig = cg._read

# 生效条件：entry["path"] 不在闭包 cache 中时调用 orig(entry) 存入该键，随后返回 cache[p]（同一 path 后续命中直接取缓存）。
    def _cached(entry):
        p = entry["path"]
        if p not in cache:
            cache[p] = orig(entry)
        return cache[p]

    cg._read = _cached
    return cache


# 生效条件：对 queries 每条 item 以 cg.search_rrf(item["q"], k=k, paths=arm, judge=False, record=False, path_weights=path_weights, recall_only=recall_only, fusion=fusion) 取结果，rank 记 item["target"] 在返回 ids 中的 1 基位次（不在 ids 中记 0），逐条追加明细后返回 out。
def run_arm(cg, queries, arm, k=10, path_weights=None, recall_only=None,
            fusion="sum"):
    """跑一臂，返回 per-query 明细。"""
    out = []
    for item in queries:
        res, meta = cg.search_rrf(item["q"], k=k, paths=arm, judge=False,
                                  record=False, path_weights=path_weights,
                                  recall_only=recall_only, fusion=fusion)
        ids = [r[0]["id"] for r in res]
        labels = [r[0]["frontmatter"].get("bench_label") for r in res]
        rank = ids.index(item["target"]) + 1 if item["target"] in ids else 0
        prov = next((r[3] for r in res if r[0]["id"] == item["target"]), [])
        out.append({
            "mode": item["mode"], "rank": rank, "labels": labels,
            "fuzzy_hit": any(p.get("path") == "fuzzy" for p in (prov or [])),
            "expand_source": meta.get("expand_source"),
            "n": len(res),
        })
    return out


# 生效条件：对 queries 每条以 cg.search_rrf(item["q"], k=k, paths=(path,)) 单路取结果，rank 记 item["target"] 的 1 基位次（未命中记 0），fuzzy_hit 恒为 False、expand_source 恒为 None，返回 out。
def run_single(cg, queries, path, k=10):
    """单路独立排序（用于诊断每路的自身质量）。"""
    out = []
    for item in queries:
        res, meta = cg.search_rrf(item["q"], k=k, paths=(path,), judge=False,
                                  record=False)
        ids = [r[0]["id"] for r in res]
        labels = [r[0]["frontmatter"].get("bench_label") for r in res]
        rank = ids.index(item["target"]) + 1 if item["target"] in ids else 0
        out.append({"mode": item["mode"], "rank": rank, "labels": labels,
                    "fuzzy_hit": False, "expand_source": None, "n": len(res)})
    return out


# 生效条件：rows 为空时返回 None；否则按 n=len(rows) 算 self@1、self@k（0<rank<=k，k 由形参给定）、mrr（仅 rank 非 0 行取 1/rank 再除 n）与标签占比（分母 sum(lab.values()) or 1，无标签时用 1），fuzzy_prov 在 hit_rows 为空时记 0.0。
def summarize(rows, k=10):
    """汇总一个查询模式的指标。"""
    n = len(rows)
    if not n:
        return None
    self_hit = sum(1 for r in rows if r["rank"] == 1)
    in_k = sum(1 for r in rows if 0 < r["rank"] <= k)
    mrr = sum(1.0 / r["rank"] for r in rows if r["rank"]) / n
    lab = collections.Counter()
    for r in rows:
        lab.update(r["labels"])
    tot = sum(lab.values()) or 1
    hit_rows = [r for r in rows if r["rank"]]
    return {
        "n": n, "self@1": self_hit / n, f"self@{k}": in_k / n, "mrr": mrr,
        "sigP": lab["signal"] / tot, "noiseP": lab["noise"] / tot,
        "unlabP": lab["unlabeled"] / tot,
        "fuzzy_prov": (sum(1 for r in hit_rows if r["fuzzy_hit"]) / len(hit_rows)
                       if hit_rows else 0.0),
    }


# 生效条件：把 x 乘 100 后按 5 位宽保留一位小数加百分号返回，源码未对 x 做类型或范围校验。
def _pct(x):
    return f"{x * 100:5.1f}%"


# 生效条件：r4 长度为 0 时返回 {}；否则以 seed 建 rng，对 (1,"self@1") 与 (k,f"self@{k}") 由 r4/r5 的 0<rank<=kk 命中向量算 b01/b10，m=b01+b10 为 0 时 p=1.0 否则取 McNemar 精确单侧和除以 2**m，并用 n_boot 次有放回重采样取 deltas[int(0.025*n_boot)] 与 deltas[int(0.975*n_boot)-1] 为 ci，另加 MRR 键（b01/b10/p 与 ci 均为 None）后返回。
def paired_test(r4, r5, k=10, seed=0, n_boot=5000):
    """配对显著性：bootstrap 95% CI + McNemar 精确单侧 p（H1: 五路更好）。"""
    from math import comb
    rng = random.Random(seed)
    n = len(r4)
    if not n:
        return {}
    out = {}
    for kk, name in ((1, "self@1"), (k, f"self@{k}")):
        a = [1 if 0 < r["rank"] <= kk else 0 for r in r4]
        b = [1 if 0 < r["rank"] <= kk else 0 for r in r5]
        b01 = sum(1 for x, y in zip(a, b) if x == 0 and y == 1)   # 四路漏→五路中
        b10 = sum(1 for x, y in zip(a, b) if x == 1 and y == 0)   # 四路中→五路漏
        m = b01 + b10
        p = (sum(comb(m, i) for i in range(b01, m + 1)) / (2 ** m)) if m else 1.0
        deltas = []
        for _ in range(n_boot):
            idx = [rng.randrange(n) for _ in range(n)]
            deltas.append((sum(b[i] for i in idx) - sum(a[i] for i in idx)) / n)
        deltas.sort()
        out[name] = {"delta": (sum(b) - sum(a)) / n, "b01": b01, "b10": b10, "p": p,
                     "ci": (deltas[int(0.025 * n_boot)],
                            deltas[int(0.975 * n_boot) - 1])}
    mrr4 = sum(1.0 / r["rank"] for r in r4 if r["rank"]) / n
    mrr5 = sum(1.0 / r["rank"] for r in r5 if r["rank"]) / n
    out["MRR"] = {"delta": mrr5 - mrr4, "b01": None, "b10": None, "p": None,
                  "ci": (None, None)}
    return out


# 生效条件：scopes 以 ("全合并", r4, r5) 起头，仅当某模式在 r4 中有条目时才追加该模式（orig/head/para/drop）的 (模式名, 筛选后 a, 筛选后 b)；对每个 scope 用 k、seed 调 paired_test 并逐项打印 self@1、self@k、MRR 的 delta/ci/b01-b10/p，函数本身不返回值。
def print_sig(r4, r5, qs, k=10, seed=0):
    """按查询模式 + 全模式合并，打印配对显著性。"""
    print(f"\n配对显著性（五路 − 四路，配对 bootstrap 5000 次 + McNemar 精确单侧）")
    print(f"{'范围':<8}{'指标':<9}{'Δ':>9}{'95% CI':>19}{'b01/b10':>10}{'p':>9}")
    print("-" * 66)
    scopes = [("全合并", r4, r5)]
    for m in ("orig", "head", "para", "drop"):
        a = [r for r in r4 if r["mode"] == m]
        b = [r for r in r5 if r["mode"] == m]
        if a:
            scopes.append((m, a, b))
    for name, a, b in scopes:
        res = paired_test(a, b, k=k, seed=seed)
        for kk in ("self@1", f"self@{k}", "MRR"):
            s = res[kk]
            ci = s["ci"]
            ci_s = f"[{ci[0]:+.3f},{ci[1]:+.3f}]" if ci[0] is not None else ""
            dis = f"{s['b01']}/{s['b10']}" if s["b01"] is not None else ""
            p_s = f"{s['p']:.3f}" if s["p"] is not None else ""
            print(f"{name:<8}{kk:<9}{s['delta']:>+9.3f}{ci_s:>19}{dis:>10}{p_s:>9}")
        print("-" * 66)


# 生效条件：把 cg._path_fuzzy 换成闭包，原结果按分数降序取前 50 后用 random.Random(seed) 打乱并改写为递减伪分；本函数自身无 return。
def patch_shuffled_fuzzy(cg, seed=0):
    """把 fuzzy 路**候选集保留、内部顺序打乱**（对照：区分「候选集贡献」与「排序质量贡献」）。

    注意：search_rrf 会在 _path_fuzzy 返回后按分数重排，因此必须先把真实 top-50
    候选集定下来，再用递减伪分固化打乱后的顺序，否则 shuffle 会被排序覆盖（空控制）。
    """
    rng = random.Random(seed)
    orig = cg._path_fuzzy

# 生效条件：以 (query, entries, context, expand=expand) 调用原 _path_fuzzy，结果按分数降序取前 50 条，用闭包 rng 打乱后改写为递减伪分 (node, float(n-i))，返回 (out, str(src)+"+shuffled")。
    def _shuf(query, entries, context=None, expand=None):
        out, src = orig(query, entries, context, expand=expand)
        out = sorted(out, key=lambda x: -x[1])[:50]      # fuzzy 真实候选集
        rng.shuffle(out)                                  # 打乱内部顺序
        n = len(out)
        out = [(node, float(n - i)) for i, (node, _s) in enumerate(out)]
        return out, str(src) + "+shuffled"

    cg._path_fuzzy = _shuf


# 生效条件：把 cg._path_fuzzy 换成忽略 context/expand、对 cg._read_many 全量条目按 random.Random(seed) 随机分降序排序的闭包；本函数自身无 return。
def patch_random_path(cg, seed=0):
    """把第 5 路替换为**全库随机排序**（对照：max 融合机制本身能带来多少增益）。"""
    rng = random.Random(seed)

# 生效条件：忽略 context 与 expand，对 cg._read_many(entries, stat) 的每条记录用 rng.random() 打分并降序排序，节点 id 取 fm.get("id") or e["path"]，返回 (out, "random")。
    def _rand(query, entries, context=None, expand=None):
        stat = {"scanned": 0}
        out = []
        for e, fm, c in cg._read_many(entries, stat):
            out.append(({"id": fm.get("id") or e["path"], "frontmatter": fm,
                         "content": c, "path": e["path"]}, rng.random()))
        out.sort(key=lambda x: -x[1])
        return out, "random"

    cg._path_fuzzy = _rand


# 生效条件：不使用 cg，直接把 md_cg.mdcos.GLOBAL_CAP 置为 10**9 并返回该值。
def patch_symmetric_pool(cg):
    """【2026-09-16 起已冗余】抬高 GLOBAL_CAP，让 lexical 与 fuzzy 候选池对称。

    背景：lexical 命中数超 GLOBAL_CAP 时按**插入序**截断，fuzzy 则全库打分后取
    Top-50；两条路候选池不对称，会系统性偏袒 fuzzy。当时以「抬高 cap」对冲。

    现状：截断依据已改为**相关度**（`mdcg.cut_by_relevance` 与 `mdcos._lexical`
    均先全量打分再排序截断，cap 值仍为 500）——插入序偏置的根因已消除，本 patch
    不再必要。保留仅为兼容既有对照命令（`--symmetric-pool`）与历史口径复现。
    """
    from md_cg import mdcos as _m
    _m.GLOBAL_CAP = 10 ** 9
    return _m.GLOBAL_CAP


# 生效条件：把 cg._lexical 换成先 cg._read_many(entries, stat) 全量读入、再 cg._score(docs, query, bigrams(query)) 打分的闭包；本函数自身无 return。
def patch_lexical_full(cg):
    """让 lexical 也对**全量候选池**打分（消除「扫描范围」差异，只留排序算法差异）。

    默认 _lexical 只在 LIKE 命中集上打分（中位约 20 条），而 _path_fuzzy 扫全库 1000 条。
    注：截断依据改为相关度后（2026-09-16），「排序依据不对等」已消除，此处差异
    仅剩**扫描范围**一项；本 patch 仍用于隔离排序算法差异的对照实验。
    """
    from md_cg.mdcg import bigrams

# 生效条件：entries 经 cg._read_many(entries, stat) 全量读入后交给 cg._score(docs, query, bigrams(query)) 打分并返回其结果。
    def _lex(query, entries, stat):
        docs = cg._read_many(entries, stat)
        return cg._score(docs, query, bigrams(query))

    cg._lexical = _lex


# 生效条件：把 cg._read 包装为仅当原 _read 返回的 fm 是 dict 时覆写 fm["importance"]=0.5（非 dict 不修改），返回 (fm, c)；本函数自身无 return。
def patch_zero_importance(cg):
    """抹掉 importance：数据集里 signal 的 importance 系统性偏高（≈0.6），
    而 search_rrf 用 (-score, -importance) 做同分 tie-break → 会泄漏 label。
    """
    orig = cg._read

# 生效条件：orig(entry) 返回的 fm 是 dict 时把 fm["importance"] 设为 0.5（非 dict 不修改），返回 (fm, c)。
    def _z(entry):
        fm, c = orig(entry)
        if isinstance(fm, dict):
            fm["importance"] = 0.5
        return fm, c

    cg._read = _z


# 生效条件：cg 与 qs 均须可用；内部先经 cg._candidates() 取候选池、cg._read_many 读正文，再按每题 query terms 统计 _like 命中数；只打印诊断（含 GLOBAL_CAP 与截断计数）并返回 None，不改库；
def pool_diag(cg, qs):
    """候选池对称性诊断：lexical 的 LIKE 命中数是否真的被 GLOBAL_CAP 截断。"""
    from md_cg import mdcos as _m
    entries = cg._candidates()
    stat = {"scanned": 0}
    docs = cg._read_many(entries, stat)
    dist = []
    for item in qs:
        terms = expand_query_terms(item["q"])
        dist.append(sum(1 for d in docs if cg._like(d[2], d[1], terms)))
    dist.sort()
    cap = _m.GLOBAL_CAP
    trunc = sum(1 for x in dist if x > cap)
    mid = dist[len(dist) // 2] if dist else 0
    print(f"\n候选池对称性诊断（候选池 {len(entries)}，GLOBAL_CAP={cap}）")
    print(f"  lexical LIKE 命中数：min={dist[0]} 中位={mid} max={dist[-1]}")
    print(f"  被 GLOBAL_CAP 截断的查询：{trunc}/{len(dist)}"
          f"（{trunc / max(len(dist), 1):.0%}）")
    print("  说明：截断按插入序取前 cap 条 → lexical 的候选池小于 fuzzy（fuzzy 全库打分）。")
    return 0


# 生效条件：cg.search_rrf 可用、queries 每项含 q/target/mode 时，对目标未列首的题打印顶替者与目标在 ARM5 各单路的排名，最多打印 limit 例。
def diag_failures(cg, queries, k=10, arm=ARM5, limit=6, path_weights=None):
    """打印失败案例：谁把目标挤掉了、目标在单路里排第几。"""
    print(f"\n失败案例诊断（{'+'.join(arm)}，Top-{k} 未把目标排第一）")
    shown = 0
    for item in queries:
        res, _m = cg.search_rrf(item["q"], k=k, paths=arm, judge=False,
                                record=False, path_weights=path_weights)
        ids = [r[0]["id"] for r in res]
        if ids and ids[0] == item["target"]:
            continue
        rank = ids.index(item["target"]) + 1 if item["target"] in ids else 0
        per = {}
        for p in ARM5:
            r2, _ = cg.search_rrf(item["q"], k=50, paths=(p,), judge=False,
                                  record=False)
            i2 = [x[0]["id"] for x in r2]
            per[p] = i2.index(item["target"]) + 1 if item["target"] in i2 else 0
        top = res[0]
        tgt_prov = next((r[3] for r in res if r[0]["id"] == item["target"]), None)
        print(f"\n  [{item['mode']}] q={item['q'][:26]!r}  目标 rank={rank or '未命中'}")
        print(f"     被谁顶掉：{top[0]['id']} label="
              f"{top[0]['frontmatter'].get('bench_label')} prov={top[3]}")
        print(f"     目标 prov={tgt_prov}")
        print(f"     目标单路 rank={per}")
        shown += 1
        if shown >= limit:
            break
    if not shown:
        print("  （无失败案例）")


# 生效条件：args.ablate=="pool" 时直接返回 pool_diag(cg, qs)；=="idcheck" 时对四路 sum 与四路 max 逐条比较 rank/labels 并打印差异数后返回 0；其余取值时先算四路基线与五路 fuzzy max 基线，再按 =="shuffle" 调 patch_shuffled_fuzzy、否则调 patch_random_path 做扰动臂，打印三臂指标后返回 0（k 取 args.k）。
def ablate(cg, qs, args):
    """对照实验：分离「候选集贡献」「排序质量贡献」「融合机制红利」。"""
    k = args.k
    if args.ablate == "pool":
        return pool_diag(cg, qs)
    if args.ablate == "idcheck":
        a = run_arm(cg, qs, ARM4, k=k, fusion="sum")
        b = run_arm(cg, qs, ARM4, k=k, fusion="max")
        diff = [i for i, (x, y) in enumerate(zip(a, b))
                if x["rank"] != y["rank"] or x["labels"] != y["labels"]]
        print("\n恒等性自检：四路 sum vs 四路 max")
        print("  （若 bucket/entity/graph 三路确实全空，两者应逐条完全相同）")
        print(f"  不同查询：{len(diff)}/{len(a)}")
        for i in diff[:6]:
            print(f"  [{qs[i]['mode']}] sum rank={a[i]['rank']} "
                  f"max rank={b[i]['rank']}")
        return 0

    base = summarize(run_arm(cg, qs, ARM4, k=k), k=k)
    real = summarize(run_arm(cg, qs, ARM5, k=k, path_weights={"fuzzy": 1.0},
                             fusion="max"), k=k)
    if args.ablate == "shuffle":
        patch_shuffled_fuzzy(cg, seed=args.seed)
        label = "fuzzy 候选同、顺序打乱"
    else:
        patch_random_path(cg, seed=args.seed)
        label = "第5路=全库随机排序"
    abl = summarize(run_arm(cg, qs, ARM5, k=k, path_weights={"fuzzy": 1.0},
                            fusion="max"), k=k)
    print(f"\n对照实验（均 max 融合，Top-{k}，n={len(qs)} 查询）")
    print(f"{'臂':<26}{'self@1':>9}{'self@%d' % k:>9}{'MRR':>8}{'sigP':>8}")
    print("-" * 62)
    for name, s in (("四路基线（仅 lexical 有效）", base), ("五路 fuzzy max", real),
                    (label, abl)):
        print(f"{name:<26}{_pct(s['self@1']):>9}"
              f"{_pct(s['self@' + str(k)]):>9}{s['mrr']:>8.3f}"
              f"{_pct(s['sigP']):>8}")
    print("-" * 62)
    print("  判读：若「打乱」或「随机」也拿到大部分 +self@10 → 增益来自融合机制，"
          "不是 fuzzy 的排序质量。")
    return 0


# 生效条件：argv 经 argparse 解析（--n/--k/--seed/--rebuild/--per-path/--sweep/--diag/--ablate/--sympool/--fusion/--lexfull/--zero-importance 等）；外部数据集缺失即抛异常、不静默降级；返回进程退出码；
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=250, help="抽样 signal 条数（0=全量）")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--per-path", action="store_true", help="逐路诊断（慢）")
    ap.add_argument("--sweep", action="store_true", help="融合策略扫描（慢）")
    ap.add_argument("--diag", action="store_true", help="打印失败案例诊断")
    ap.add_argument("--ablate", default="none",
                    choices=["none", "idcheck", "shuffle", "random", "pool"],
                    help="对照实验：恒等性自检 / 打乱 fuzzy 顺序 / 随机第5路 / 候选池对称性")
    ap.add_argument("--sympool", action="store_true",
                    help="抬高 GLOBAL_CAP，使 lexical 与 fuzzy 候选池对称")
    ap.add_argument("--fusion", default="sum", choices=["sum", "max"],
                    help="五路融合模式（sum=经典 RRF 求和；max=取各路最高贡献）")
    ap.add_argument("--lexfull", action="store_true",
                    help="lexical 也对全量池打分（与 fuzzy 的扫描范围真正对等）")
    ap.add_argument("--zero-importance", action="store_true",
                    help="抹掉 importance（消除数据集里 importance 对 label 的泄漏）")
    args = ap.parse_args()

    print("=" * 76)
    print("memory-bench-1000 · 四路 vs 五路（+fuzzy 分级隶属度）A/B")
    print("=" * 76)

    rows = load_rows()
    lab = collections.Counter(r.get("label") for r in rows)
    print(f"\n数据集：{len(rows)} 条  signal {lab['signal']} / noise {lab['noise']} "
          f"/ unlabeled {lab['unlabeled']}  → 噪声率 {lab['noise'] / len(rows):.0%}")

    if args.rebuild and os.path.isdir(ROOT):
        import shutil
        shutil.rmtree(ROOT)
    t0 = time.perf_counter()
    cg = build(ROOT, rows)
    install_read_cache(cg)
    print(f"  建库耗时 {(time.perf_counter() - t0) * 1000:.0f} ms"
          f"（{len(cg.index['nodes'])} 节点，{len(cg.index['buckets'])} 桶）")

    if args.sympool:
        cap = patch_symmetric_pool(cg)
        print(f"  [对照] 候选池对称化：GLOBAL_CAP → {cap}（lexical 不再按插入序截断）")
    if args.zero_importance:
        patch_zero_importance(cg)
        print("  [对照] importance 已抹平为 0.5（消除 signal 的 label 泄漏）")
    if args.lexfull:
        patch_lexical_full(cg)
        print("  [对照] lexical 全量池打分（与 fuzzy 扫描范围对等）")

    qs = make_queries(rows, n=args.n, seed=args.seed)
    by_mode = collections.Counter(q["mode"] for q in qs)
    print(f"\n查询集：{len(qs)} 条  {dict(by_mode)}"
          f"（seed={args.seed}，signal 抽样 {args.n}）")

    if args.ablate != "none":
        return ablate(cg, qs, args)

    t0 = time.perf_counter()
    r4 = run_arm(cg, qs, ARM4, k=args.k, fusion="sum")
    t4 = time.perf_counter() - t0
    t0 = time.perf_counter()
    r5 = run_arm(cg, qs, ARM5, k=args.k, path_weights={"fuzzy": 1.0},
                 fusion=args.fusion)
    t5 = time.perf_counter() - t0
    print(f"耗时：四路 {t4:.1f}s / 五路 {t5:.1f}s（五路融合={args.fusion}）")

    modes = [m for m in ("orig", "head", "para", "drop") if by_mode.get(m)]
    print(f"\n{'模式':<6}{'臂':<5}{'n':>5}{'self@1':>9}{'self@%d' % args.k:>9}"
          f"{'MRR':>8}{'sigP':>8}{'noiseP':>9}{'fuzzy参与':>10}")
    print("-" * 76)
    delta = {}
    for m in modes:
        s4 = summarize([r for r in r4 if r["mode"] == m], k=args.k)
        s5 = summarize([r for r in r5 if r["mode"] == m], k=args.k)
        for arm, s in (("四路", s4), ("五路", s5)):
            print(f"{m:<6}{arm:<5}{s['n']:>5}{_pct(s['self@1']):>9}"
                  f"{_pct(s['self@' + str(args.k)]):>9}{s['mrr']:>8.3f}"
                  f"{_pct(s['sigP']):>8}{_pct(s['noiseP']):>9}"
                  f"{_pct(s['fuzzy_prov']):>10}")
        delta[m] = {k: s5[k] - s4[k] for k in
                    ("self@1", "self@" + str(args.k), "mrr", "sigP", "noiseP")}
        print("-" * 76)

    print(f"\n{'净变化（五路 − 四路）':<20}{'self@1':>10}{'self@%d' % args.k:>10}"
          f"{'MRR':>10}{'sigP':>10}{'noiseP':>10}")
    for m in modes:
        d = delta[m]
        print(f"{m:<20}{d['self@1']:>+10.1%}{d['self@' + str(args.k)]:>+10.1%}"
              f"{d['mrr']:>+10.3f}{d['sigP']:>+10.1%}{d['noiseP']:>+10.1%}")

    # 全模式合并（诚实口径：四模式混合，权重按出现次数）
    s4a = summarize(r4, k=args.k)
    s5a = summarize(r5, k=args.k)
    print(f"\n{'全模式合并':<20}{'self@1':>10}{'self@%d' % args.k:>10}"
          f"{'MRR':>10}{'sigP':>10}{'noiseP':>10}")
    print(f"{'四路':<20}{_pct(s4a['self@1']):>10}"
          f"{_pct(s4a['self@' + str(args.k)]):>10}{s4a['mrr']:>10.3f}"
          f"{_pct(s4a['sigP']):>10}{_pct(s4a['noiseP']):>10}")
    print(f"{'五路':<20}{_pct(s5a['self@1']):>10}"
          f"{_pct(s5a['self@' + str(args.k)]):>10}{s5a['mrr']:>10.3f}"
          f"{_pct(s5a['sigP']):>10}{_pct(s5a['noiseP']):>10}")
    print(f"{'净变化':<20}{s5a['self@1'] - s4a['self@1']:>+10.1%}"
          f"{s5a['self@' + str(args.k)] - s4a['self@' + str(args.k)]:>+10.1%}"
          f"{s5a['mrr'] - s4a['mrr']:>+10.3f}"
          f"{s5a['sigP'] - s4a['sigP']:>+10.1%}"
          f"{s5a['noiseP'] - s4a['noiseP']:>+10.1%}")

    print_sig(r4, r5, qs, k=args.k, seed=args.seed)

    if args.sweep:
        print(f"\n融合策略扫描（全模式合并，Top-{args.k}；相对四路基线的净变化）")
        print(f"{'策略':<18}{'self@1':>9}{'Δself@1':>10}{'self@%d' % args.k:>9}"
              f"{'MRR':>8}{'sigP':>8}{'noiseP':>9}")
        print("-" * 76)
        base = summarize(r4, k=args.k)
        arms = [("四路 sum（基线）", ARM4, None, None, "sum"),
                ("四路 max", ARM4, None, None, "max"),
                ("五路 sum w=1.0", ARM5, {"fuzzy": 1.0}, None, "sum"),
                ("五路 sum w=0.3", ARM5, {"fuzzy": 0.3}, None, "sum"),
                ("五路 sum w=0.1", ARM5, {"fuzzy": 0.1}, None, "sum"),
                ("五路 max w=1.0", ARM5, {"fuzzy": 1.0}, None, "max"),
                ("五路 max w=0.5", ARM5, {"fuzzy": 0.5}, None, "max"),
                ("fuzzy 仅召回", ARM5, None, {"fuzzy"}, "sum")]
        if args.n and args.n > 100:     # 全量时只保留关键臂，控制耗时
            keep = {"四路 sum（基线）", "五路 sum w=1.0", "五路 max w=1.0",
                    "fuzzy 仅召回"}
            arms = [a for a in arms if a[0] in keep]
        for label, arm, pw, ro, fu in arms:
            if label.startswith("四路 sum"):
                s = base
            else:
                s = summarize(run_arm(cg, qs, arm, k=args.k, path_weights=pw,
                                      recall_only=ro, fusion=fu), k=args.k)
            print(f"{label:<18}{_pct(s['self@1']):>9}"
                  f"{s['self@1'] - base['self@1']:>+10.1%}"
                  f"{_pct(s['self@' + str(args.k)]):>9}{s['mrr']:>8.3f}"
                  f"{_pct(s['sigP']):>8}{_pct(s['noiseP']):>9}")
        print("-" * 76)

    if args.per_path:
        print(f"\n逐路单独质量（各路径独立排序，Top-{args.k}）")
        print(f"{'模式':<6}{'路':<9}{'n':>5}{'self@1':>9}{'self@%d' % args.k:>9}"
              f"{'MRR':>8}{'sigP':>8}{'noiseP':>9}")
        print("-" * 76)
        for m in modes:
            sub = [q for q in qs if q["mode"] == m]
            for p in ARM5:
                s = summarize(run_single(cg, sub, p, k=args.k), k=args.k)
                print(f"{m:<6}{p:<9}{s['n']:>5}{_pct(s['self@1']):>9}"
                      f"{_pct(s['self@' + str(args.k)]):>9}{s['mrr']:>8.3f}"
                      f"{_pct(s['sigP']):>8}{_pct(s['noiseP']):>9}")
            print("-" * 76)

    if args.diag:
        diag_failures(cg, [q for q in qs if q["mode"] == "drop"], k=args.k)

    src = collections.Counter(r["expand_source"] for r in r5)
    print(f"\nfuzzy 路扩展来源：{dict(src)}")
    print("\n诚实边界：本数据集无显式 edges → graph 路候选为空；节点无 domain: 标签 → "
          "fuzzy 的大域亲和项恒等（实际区分力全部来自加权覆盖率）。")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())