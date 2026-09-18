# -*- coding: utf-8 -*-
"""倒排（发布表）候选层：不读遍全库即可取「词法候选」。

为何需要（实测依据：docs/hive/真实库端到端实测_S1b与召回权衡_v0.1.md）：
S1b 桶收敛能少扫 5.5~10.4 倍，但**召回集合会变**（真实库一致率仅 1/4）。要两全，
必须有「廉价高精度候选生成器」——即本模块：把「字符 bigram → 节点」做成发布表，
查询时按 bigram 交集取候选，再用既有 `_like` 精确过滤，从而**召回与全表扫描一致**。

设计要点：
1. 索引对象 = 节点 **content + tags** 的字符 bigram（与打分口径同源：mdcg.bigrams/normalize_en）。
2. 查询侧：对每个查询词 t（len ≥ 2）取 t 的 bigram 集合在发布表中的**交集**；
   这些节点必然包含 t 的全部 bigram（是「包含 t」的超集，可能跨词假阳性）；
   各词取并集 → 候选 ⊇ 真命中集 → 再用 `_like` 精确过滤 → 结果与全表扫描一致。
3. 单字查询词无法用 bigram 表达 → 该查询**回退全量**（安全，记 reason）。
4. 存储：`<root>/_postings.json`（{bigram: [id,...]}）+ `<root>/_postings_meta.json`（版本/规模/时间）。
5. 位置：只作**候选生成器**（契约 §7 允许的「候选内加速」），不替代认知路径。
"""
import io
import json
import os
import time

SCHEMA = "mdcg-postings-1"


# 生效条件：root 为真值时返回 root 下 postings 数据文件路径，否则返回 "_postings.json"（相对路径）。
def postings_path(root: str) -> str:
    return os.path.join(root or "", "_postings.json")


# 生效条件：root 为真值时返回 root 下 postings 元数据文件路径，否则返回 "_postings_meta.json"。
def meta_path(root: str) -> str:
    return os.path.join(root or "", "_postings_meta.json")


# 生效条件：无条件以 utf-8 惰性引入 mdcg 的 bigrams/normalize_en 并返回；导入失败返回 (None, None)。
def _bigrams_fn():
    try:
        from .mdcg import bigrams, normalize_en
        return bigrams, normalize_en
    except Exception:
        return None, None


# 生效条件：text 与 tags 均为假值时返回空集合；否则返回二者（tags 以空格拼接）经 normalize_en 后的 bigram 并集；
# bigrams/normalize_en 不可用时返回空集合。
def ngrams(text, tags=None) -> set:
    """节点侧取词：content + tags 的字符 bigram 集合（与打分同源）。"""
    bigrams, normalize_en = _bigrams_fn()
    if bigrams is None:
        return set()
    buf = str(text or "")
    if tags:
        buf += " " + " ".join(str(t) for t in tags)
    if not buf.strip():
        return set()
    return set(bigrams(normalize_en(buf)))


# 生效条件：terms 为假值时返回（[]，'empty_terms'）；任一词的 normalize_en 结果长度 < 2 时返回（[]，'single_char_term'）；
# 否则返回（[每词 bigram 集合]，''），供 candidates 逐词取交集。
def term_ngram_sets(terms):
    """查询侧取词：把每个查询词转成 bigram 集合；含单字词则整体不可用（安全回退）。"""
    bigrams, normalize_en = _bigrams_fn()
    if not terms:
        return [], "empty_terms"
    if bigrams is None or normalize_en is None:
        return [], "no_bigram_fn"
    sets = []
    for t in terms:
        nt = normalize_en(str(t))
        if len(nt) < 2:
            return [], "single_char_term"
        sets.append(set(bigrams(nt)))
    return sets, ""


# 生效条件：构建完成后无条件以 utf-8 原子写 root/_postings.json（JSON）与 root/_postings_meta.json，并返回 stats dict。
def _save(root, table, stats):
    tmp = postings_path(root) + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline=chr(10)) as f:
        json.dump(table, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, postings_path(root))
    with io.open(meta_path(root), "w", encoding="utf-8", newline=chr(10)) as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    return stats


# 生效条件：无条件读 root/_postings.json 并返回 dict（缺文件/解析失败返回 {}；内容非 dict 亦返回 {}）。
def load(root: str) -> dict:
    p = postings_path(root)
    try:
        with io.open(p, encoding="utf-8") as f:
            t = json.load(f)
        return t if isinstance(t, dict) else {}
    except Exception:
        return {}


_CACHE = {}


# 生效条件：root/postings 为假值返回 {}；否则按 (路径, mtime, size) 缓存命中则返回缓存表，未命中则 load 后写入缓存并返回。
def load_cached(root: str) -> dict:
    p = postings_path(root)
    try:
        st = os.stat(p)
    except OSError:
        return {}
    key = (p, st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(p)
    if hit and hit[0] == key:
        return hit[1]
    t = load(root)
    _CACHE[p] = (key, t)
    return t


# 生效条件：cg 为假值或取不到 index["nodes"] 时返回 {"nodes":0,"terms":0,"postings":0,"rebuilt":False}；
# 否则遍历 index 逐节点取 content+tags 的 bigram、按 id 去重累积，写出数据与元数据并返回含 nodes/terms/postings/rebuilt=True 的 stats。
def build(cg, limit: int = None) -> dict:
    """全量重建发布表（幂等）。limit 为真值时最多处理 limit 个节点。"""
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    if not nodes:
        return {"nodes": 0, "terms": 0, "postings": 0, "rebuilt": False}
    table = {}
    n = 0
    for nid, e in list(nodes.items()):
        if limit and n >= limit:
            break
        got = cg.get(nid)
        if not got:
            continue
        gs = ngrams(got.get("content"), got.get("frontmatter", {}).get("tags"))
        if not gs:
            continue
        for g in gs:
            table.setdefault(g, []).append(nid)
        n += 1
    stats = {"schema": SCHEMA, "built_at": int(time.time()), "nodes": n,
             "terms": len(table), "postings": sum(len(v) for v in table.values())}
    _save(cg.root, table, stats)
    return dict(stats, rebuilt=True)


# 生效条件：无条件把 node_id 追加进 table 中每个 bigram 的列表（bigram 不存在则新建列表），返回追加的 bigram 个数。
def add_to_table(table: dict, node_id, text, tags=None) -> int:
    """增量维护：把某节点的 bigram 追加进表（调用方负责持久化）。"""
    gs = ngrams(text, tags)
    for g in gs:
        table.setdefault(g, []).append(node_id)
    return len(gs)


# 生效条件：无条件把 node_id 从 table 各列表中移除（不存在则无操作并原样返回 table），返回剩余 bigram 数。
def remove_from_table(table: dict, node_id) -> int:
    for g in list(table.keys()):
        lst = table.get(g)
        if not lst:
            continue
        try:
            table[g] = [x for x in lst if x != node_id]
        except Exception:
            continue
        if not table[g]:
            table.pop(g, None)
    return len(table)


# 生效条件：terms 为假值或任一词为单字（或 bigram 函数不可用）时返回 (None, reason)；发布表为空时返回 (None,'no_index')；
# 否则逐词以「该词的全部 bigram 发布列表交集」取候选、各词取并集，返回 (候选 id 集合, '')。
def candidates(root: str, terms):
    """返回 (candidate_ids | None, reason)。None 表示「不可用，调用方应回退全量」。"""
    sets, reason = term_ngram_sets(terms)
    if not sets:
        return None, reason or "unusable_terms"
    table = load_cached(root)
    if not table:
        return None, "no_index"
    out = set()
    for gs in sets:
        lists = [table.get(g) for g in gs]
        if any(x is None for x in lists):
            continue                     # 该词有 bigram 不在表里 → 该词无候选（并集里不贡献）
        inter = set(lists[0])
        for x in lists[1:]:
            inter &= set(x)
            if not inter:
                break
        out |= inter
    return out, ""


# 生效条件：无条件统计 root 下发布表规模并返回 {"terms": 词项数, "postings": 倒排条目数, "meta": 元数据 dict 或 None}。
def stats(root: str) -> dict:
    t = load_cached(root)
    meta = None
    try:
        with io.open(meta_path(root), encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = None
    return {"terms": len(t), "postings": sum(len(v) for v in t.values()), "meta": meta}
