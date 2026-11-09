# -*- coding: utf-8 -*-
"""rewrite.py —— E：查询改写（LLM 扩展词）与重排（LLM 打分）

为什么做：[检索实测] 「家里网络老卡顿」这类问法与库里的「无线信道拥塞/丢包」用词
完全不同，词法路给 0.05 分，向量路能捞到但排序不保证。改写把问法先摊成库里可能
用的词，再喂给既有各路；重排只在末尾对融合结果做一次有约束的重排。

三条纪律：
  1. **默认只开改写、不开重排**。改写结果落盘缓存（同一问句只花一次 LLM），
     重排是每题一次调用，热路径上不默认付这个延迟。
  2. 任一环节失败（网络/解析/超预算）→ 返回空，检索按原样继续。不抛异常。
  3. 改写**只加词不改原词**：`expand_query_terms` 仍是词表真源，这里只补它漏的。
"""
import hashlib
import io
import json
import os
import threading
import time

CACHE_DIR = "_llm_cache"
CACHE_FILE = "rewrite.jsonl"
# 重排结果另存一族：key 是「问法 + 候选 id 列表」，与改写的只按问法缓存不同。
RERANK_FILE = "rerank.jsonl"
CACHE_TTL = 7 * 86400
MAX_TERMS = 8
_cache = {}
_rcache = {}
_lock = threading.Lock()
_r_hit = 0
_r_miss = 0


# 三档：`1` 在线问模型；`cache` 只读缓存、不联网；`0` 全关。
# 缺省用 `cache`：实测 bge-base 上线后一次冷查询问模型要 3-6 s（向量路本身只要
# 10 ms），交互式面板受不了；缓存由 cron 预热，命中即可用。
MODE_CACHE = "cache"


def mode():
    m = (os.environ.get("MDCG_REWRITE") or MODE_CACHE).strip().lower()
    if m in ("0", "false", "off"):
        return "off"
    if m == MODE_CACHE:
        return MODE_CACHE
    return "live"


def enabled():
    return mode() != "off"


def rerank_enabled():
    return (os.environ.get("MDCG_RERANK") or "0").strip() in ("1", "true", "on")


def _key(q):
    return hashlib.sha1((q or "").strip().encode("utf-8")).hexdigest()[:16]


def _cache_path(root):
    d = os.path.join(root, CACHE_DIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, CACHE_FILE)


def _load_disk(root, q):
    p = _cache_path(root)
    if not os.path.exists(p):
        return None
    k = _key(q)
    try:
        for line in io.open(p, encoding="utf-8"):
            try:
                rec = json.loads(line)
            except Exception:                       # noqa: BLE001
                continue
            if rec.get("k") == k and (time.time() - float(rec.get("at") or 0)) < CACHE_TTL:
                return rec.get("terms") or []
    except Exception:                               # noqa: BLE001
        return None
    return None


def _save_disk(root, q, terms):
    try:
        p = _cache_path(root)
        with io.open(p, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"k": _key(q), "q": q, "terms": terms,
                                 "at": time.time()}, ensure_ascii=False) + "\n")
    except Exception:                               # noqa: BLE001
        pass


PROMPT = u"""你是检索词扩展器。用户会给你一句中文问题，请给出**最多 8 个**该问题在技术
笔记里最可能出现的检索词/同义词（不要解释、不要句子、不要标点）。

要求：
- 每个词 2-6 个字，彼此不重复，不要包含原问题里的整句；
- 优先给领域术语与同义说法（例：「卡顿」→「丢包、延迟、拥塞」）；
- 只输出 JSON 数组，例如 ["丢包","延迟","信道"]。

问题：%s
"""


def _ask(prompt, role=None):
    """唯一的模型出口。role 让重排走 verify（非思考模型），不复用改写那套。"""
    from . import consolidate as _cons
    return _cons.http_llm(prompt, role=(role or "reflect"))


def _parse(text):
    if not text:
        return []
    s = str(text)
    i, j = s.find("["), s.rfind("]")
    if i >= 0 and j > i:
        try:
            arr = json.loads(s[i:j + 1])
            out = []
            for t in arr:
                t = str(t).strip().strip("，,。.、\"'")
                if 2 <= len(t) <= 8 and t not in out:
                    out.append(t)
            return out[:MAX_TERMS]
        except Exception:                           # noqa: BLE001
            pass
    out = []
    for t in s.replace("\n", " ").replace("，", " ").replace(",", " ").split(" "):
        t = t.strip().strip("[]\"'")
        if 2 <= len(t) <= 8 and t not in out:
            out.append(t)
    return out[:MAX_TERMS]


def terms(query, root=None):
    """返回扩展词列表；失败/关闭返回 []。root 给了就走磁盘缓存。"""
    if not enabled():
        return []
    q = (query or "").strip()
    if len(q) < 2:
        return []
    k = _key(q)
    with _lock:
        hit = _cache.get(k)
    if hit is not None and (time.time() - hit[1]) < CACHE_TTL:
        return list(hit[0])
    if root:
        disk = _load_disk(root, q)
        if disk is not None:
            with _lock:
                _cache[k] = (disk, time.time())
            return list(disk)
    if mode() == MODE_CACHE:
        # 只读缓存：没预热过就返回空，绝不在热路径上等模型
        with _lock:
            _cache[k] = ([], time.time())
        return []
    try:
        out = _parse(_ask(PROMPT % q))
    except Exception:                               # noqa: BLE001
        return []
    with _lock:
        _cache[k] = (out, time.time())
    if root and out:
        _save_disk(root, q, out)
    return list(out)


# 重排用**非思考**模型（verify 角色 = glm-5.3-flash）：实测用 reflect 的
# deepseek-v4.1-flash 跑三条查询要 8.9–29.7 s，不可接受。
RERANK_ROLE = (os.environ.get("MDCG_RERANK_ROLE") or "verify").strip()
RERANK_CANDIDATES = int(os.environ.get("MDCG_RERANK_TOPN") or 5)

RERANK_PROMPT = u"""给下列候选记忆与问题的相关度打分：3=直接回答了问题，2=相关背景，
1=只共享话题，0=无关。只输出 JSON 对象 {"序号": 分}，不要解释。

问题：%s

候选：
%s
"""


def _rkey(query, ids, top):
    raw = "%s|%s|%d" % ((query or "").strip(), "/".join(ids), int(top))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _rpath(root):
    d = os.path.join(root, CACHE_DIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, RERANK_FILE)


def _rload(root, key):
    """返回 {nid: grade} 或 None。命中条件：同 key、未过期、ids 与 grade 键对得上。"""
    if not root:
        return None
    p = _rpath(root)
    if not os.path.exists(p):
        return None
    try:
        for line in io.open(p, encoding="utf-8"):
            try:
                rec = json.loads(line)
            except Exception:                       # noqa: BLE001
                continue
            if rec.get("k") != key:
                continue
            if (time.time() - float(rec.get("at") or 0)) >= CACHE_TTL:
                continue
            g = rec.get("g") or {}
            return {str(k): int(v) for k, v in g.items()}
    except Exception:                               # noqa: BLE001
        return None
    return None


def _rsave(root, key, query, ids, graded):
    if not root:
        return
    try:
        with io.open(_rpath(root), "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"k": key, "q": query, "ids": ids, "g": graded,
                                 "at": time.time()}, ensure_ascii=False) + "\n")
    except Exception:                               # noqa: BLE001
        pass


def rerank(query, fused, node_by_id, top=None, root=None):
    """对融合结果前 top 条重排（LLM 打分，稳定排序）。失败原样返回。

    root 给了就按「问法 + 候选 id 列表」读写磁盘缓存：命中直接复用上次的
    打分，不再问模型（缓存键含 ids 与 top，候选一变就是另一次判定）。
    """
    global _r_hit, _r_miss
    if not rerank_enabled() or not fused:
        return fused
    top = int(top or RERANK_CANDIDATES)
    head = fused[:top]
    tail = fused[top:]
    ids = [str(nid) for nid, _s in head]
    ckey = _rkey(query, ids, top)
    lines = []
    for i, (nid, _s) in enumerate(head, 1):
        node, _ = node_by_id.get(nid) or ({}, 0)
        body = (node.get("content") or "")[:300].replace("\n", " ")
        lines.append("%d. %s" % (i, body))
    try:
        graded = None
        with _lock:
            hit = _rcache.get(ckey)
        if hit is not None and (time.time() - hit[1]) < CACHE_TTL:
            graded = dict(hit[0])
            _r_hit += 1
        else:
            graded = _rload(root, ckey)
            if graded is not None:
                with _lock:
                    _rcache[ckey] = (graded, time.time())
                _r_hit += 1
        if graded is None:
            raw = _ask(RERANK_PROMPT % (query, "\n".join(lines)), role=RERANK_ROLE)
            i, j = raw.find("{"), raw.rfind("}")
            scores = json.loads(raw[i:j + 1]) if i >= 0 and j > i else {}
            graded = {}
            for k, v in scores.items():
                try:
                    ix = int(k) - 1
                except Exception:                   # noqa: BLE001
                    continue
                if 0 <= ix < len(ids):
                    graded[ids[ix]] = int(v)
            if not graded:
                return fused
            with _lock:
                _rcache[ckey] = (dict(graded), time.time())
            _r_miss += 1
            _rsave(root, ckey, query, ids, graded)
        # 分数跟着改：只挪顺序会让返回列表分数非单调（第 1 名 0.0256 < 第 2 名
        # 0.0308），下游任何「看分数差/第一名分数」的读数都会失真。
        # 乘性调整保持量级：grade 0 → ×0.85，1.5 → ×1.0，3 → ×1.15。
        rescored = []
        for nid, sc in head:
            g = graded.get(str(nid))
            nsc = float(sc) if g is None else float(sc) * (1.0 + 0.1 * (g - 1.5))
            rescored.append((nid, nsc, g if g is not None else -1))
        rescored.sort(key=lambda x: (-x[1], -x[2]))
        return [(nid, sc) for nid, sc, _g in rescored] + tail
    except Exception:                               # noqa: BLE001
        return fused


def stats():
    return {"rewrite_enabled": enabled(), "rerank_enabled": rerank_enabled(),
            "cache_entries": len(_cache),
            "rerank_cache": {"entries": len(_rcache), "hit": _r_hit,
                             "miss": _r_miss},}
