# -*- coding: utf-8 -*-
"""md_cg · 本地热层（分库分表的第一层）——把「自我信息 + 短期记忆」固化成本地库，检索优先。

【为什么】总库 3.5 万节点，一次 `search/read` 实测 24s（成本在检索本体，不在条数）。
而 agent 每轮真正需要的，往往只有三类：
  ① 自我（self / anchor 层）——身份、价值观、状态卡，变了要立刻可见；
  ② 短期（最近 N 天的 contextual）——刚才聊了什么；
  ③ 高重要度知识（importance ≥ 阈值）——少数但常被引用。
这三类合起来只有几千条。把它们**固化**成一个本地小库（`_hot/`），检索先问它，
答不上再回总库——这就是「分库分表 + 本地优先」的最小可用形态。

【设计（白箱 + 可回滚）】
  - 热层是**派生物，不是真源**：随时可从总库重建；删掉 `_hot/` 不影响任何数据；
  - 产物三个文件（同目录 `_hot/`）：
      `hot_nodes.json`  精选节点快照（id / layer / importance / t / session / preview≤300）
      `hot_postings.json` 倒排（归一化词 → id 列表），O(1) 候选召回
      `hot_meta.json`   构建元数据（built_at / 源库 index mtime+size / 计数 / 跳过原因）
  - **过期判定**：源库 `_index.json` 的 (mtime, size) 变了 ⇒ 视为过期（外部改库/本进程写入都会推进）；
    未过期时 `ensure()` 直接复用，零成本。
  - **优先检索**：`MDCG_HOT_FIRST=1` 时，`search` 先走热层取候选并前置（去重后合并），
    meta 里带 `hot_hits` 与 `hot_built_at`；关掉即回到原行为（默认关闭，可随时回滚）。

【边界】
  - 热层检索是**词法**（归一后包含匹配 + 命中密度），不做向量/语义——它只负责「先看近的」，
    答不上就回总库，**不假装是完整检索**；
  - 不写总库、不改任何节点；短期的「整理写入」在 `scripts/sync_hot_tier.py` 里，且幂等、可软删；
  - preview 截断 300 字（只做召回与预览，正文仍回总库取）。

零第三方依赖。
"""
from __future__ import annotations

import json
import os
import re
import time

HOT_DIR = "_hot"
NODES_FILE = "hot_nodes.json"
POSTINGS_FILE = "hot_postings.json"
META_FILE = "hot_meta.json"

#: 短期记忆窗口（天）
RECENT_DAYS = 7
#: 高重要度阈值
IMPORTANCE_MIN = 0.7
#: 热层上限（防止有人把「热层」做成第二个总库）
MAX_NODES = 6000
#: preview 截断
PREVIEW_MAX = 300

_TOKEN = re.compile(r"[\u4e00-\u9fff]{1,4}|[A-Za-z0-9_]{2,}")


def _hot_dir(root: str) -> str:
    return os.path.join(str(root or ""), HOT_DIR)


def _read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _write_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(value, ensure_ascii=False))
    os.replace(tmp, path)


def _dir_stamp(path: str) -> str:
    """目录戳：条目数 + 总字节 + 最新 mtime。追加写（文件数不变、大小变）也能看见。"""
    try:
        names = os.listdir(path)
    except OSError:
        return ""
    total = 0
    newest = 0
    for name in names:
        fp = os.path.join(path, name)
        try:
            st = os.stat(fp)
        except OSError:
            continue
        total += int(st.st_size)
        newest = max(newest, int(getattr(st, "st_mtime_ns", st.st_mtime * 1e9)))
    return "n=%d:bytes=%d:mt=%d" % (len(names), total, newest)


def source_stamp(root: str) -> str:
    """源库戳：`_index.json` 与 `_index_log/` 的合成戳。变即过期。

    为什么要两块：索引是**派生物**，`_index.json` 只由 compact/close 落盘，
    而每次写入都会往 `_index_log/` 追加。只认 `_index.json` 会在
    「刚写完但没 compact」的窗口里判「未过期」，热层就会漏掉最新写入。
    `_index_log/` 用「条目数 + 总字节 + 最新 mtime」而非目录自身 mtime——
    追加写不增加条目数，目录 mtime 也不一定变（实测同一 flush 前后戳相同）。
    两者都缺 ⇒ `missing`（调用方应按「无法判定」处理，即重建）。
    """
    base = str(root or "")
    parts = []
    fp = os.path.join(base, "_index.json")
    try:
        st = os.stat(fp)
        parts.append("_index.json:%d:%d" % (int(getattr(st, "st_mtime_ns", st.st_mtime * 1e9)), int(st.st_size)))
    except OSError:
        pass
    d = os.path.join(base, "_index_log")
    if os.path.isdir(d):
        seg = _dir_stamp(d)
        if seg:
            parts.append("_index_log:" + seg)
    return "|".join(parts) if parts else "missing"


def tokens(text) -> list:
    """归一化词元（与检索面同口径：fold_variants 先做 NFKC+casefold+繁简折叠）。"""
    try:
        from . import routing as _rt
        s = _rt.fold_variants(text)
    except Exception:
        s = str(text or "").lower()
    return [t for t in _TOKEN.findall(s) if t.strip()]


def build(cg, *, recent_days: int = RECENT_DAYS, importance_min: float = IMPORTANCE_MIN,
          max_nodes: int = MAX_NODES) -> dict:
    """从总库重建热层（幂等；一次遍历）。返回 meta。"""
    root = getattr(cg, "root", "")
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    now = time.time()
    cutoff = now - recent_days * 86400
    picked = {}
    unreadable = 0
    truncated = False
    # 两遍：① 自我/锚点**永不因上限被挤掉**；② 其余按 (importance, 时间) 优先序取。
    priority = []
    for nid in list(nodes):
        e = nodes.get(nid) or {}
        layer = str(e.get("layer") or "")
        imp = float(e.get("importance") or 0.0)
        ts = float(e.get("t") or e.get("created_at") or e.get("last_access") or 0.0)
        if layer in ("self", "anchor"):
            priority.append((2, nid, layer, imp, ts))
        elif layer == "contextual" and ts >= cutoff:
            priority.append((1, nid, layer, imp, ts))
        elif imp >= importance_min:
            priority.append((0, nid, layer, imp, ts))
    # 组内：高重要度 + 新近 优先；组间：self/anchor > 近期情景 > 高重要度知识
    priority.sort(key=lambda r: (-r[0], -r[3], -r[4]))
    for _grp, nid, layer, imp, ts in priority:
        if len(picked) >= max_nodes:
            truncated = True
            break
        try:
            node = cg.get(nid)
        except Exception:
            unreadable += 1
            continue
        if not node:
            unreadable += 1
            continue
        fm = node.get("frontmatter") or {}
        body = str(node.get("content") or "")
        picked[nid] = {
            "id": nid,
            "layer": layer or fm.get("layer") or "",
            "importance": float(fm.get("importance") or imp or 0.0),
            "t": ts,
            "session": fm.get("session") or "",
            "preview": re.sub(r"\s+", " ", body).strip()[:PREVIEW_MAX],
        }
    # 兜底口径：self/anchor 若仍因上限被挤掉（理论不该发生），显式记为 truncated
    missing_self = [n for (_g, n, L, _i, _t) in priority if L in ("self", "anchor") and n not in picked]
    if missing_self:
        truncated = True
    postings = {}
    for nid, rec in picked.items():
        for tok in set(tokens(rec.get("preview") or "")):
            postings.setdefault(tok, []).append(nid)
    meta = {
        "built_at": now,
        "source_stamp": source_stamp(root),
        "recent_days": recent_days,
        "importance_min": importance_min,
        "nodes": len(picked),
        "tokens": len(postings),
        "skipped_layer": len(nodes) - len(priority),
        "unreadable": unreadable,
        "truncated": bool(truncated),
        "layers": {L: sum(1 for r in picked.values() if r["layer"] == L)
                   for L in sorted({r["layer"] for r in picked.values()})},
    }
    d = _hot_dir(root)
    _write_json(os.path.join(d, NODES_FILE), picked)
    _write_json(os.path.join(d, POSTINGS_FILE), postings)
    _write_json(os.path.join(d, META_FILE), meta)
    return meta


def load(root: str):
    """读热层（缺失返回 None）。"""
    d = _hot_dir(root)
    nodes = _read_json(os.path.join(d, NODES_FILE))
    postings = _read_json(os.path.join(d, POSTINGS_FILE))
    meta = _read_json(os.path.join(d, META_FILE))
    if not isinstance(nodes, dict) or not isinstance(postings, dict) or not isinstance(meta, dict):
        return None
    return {"nodes": nodes, "postings": postings, "meta": meta}


def is_fresh(root: str) -> bool:
    """热层是否新鲜（meta 里的源库戳 == 当前源库戳）。"""
    h = load(root)
    if not h:
        return False
    cur = source_stamp(root)
    return cur != "missing" and h["meta"].get("source_stamp") == cur


def ensure(cg, *, force: bool = False, **kw) -> dict:
    """确保热层存在且新鲜；返回 meta（未过期则不重建）。"""
    root = getattr(cg, "root", "")
    h = load(root)
    cur = source_stamp(root)
    if h and not force and cur != "missing" and h["meta"].get("source_stamp") == cur:
        return dict(h["meta"], reused=True)
    return dict(build(cg, **kw), reused=False)


def search(cg, query: str, *, k: int = 10, root: str = "") -> dict:
    """热层词法检索。返回 {items, meta}；未命中返回空列表（不抛错）。"""
    root = root or getattr(cg, "root", "")
    h = load(root)
    if not h:
        return {"items": [], "meta": {"available": False}}
    q = tokens(query)
    if not q:
        return {"items": [], "meta": {"available": True, "reason": "empty_query"}}
    score = {}
    for tok in set(q):
        for nid in h["postings"].get(tok, []):
            score[nid] = score.get(nid, 0.0) + 1.0
    if not score:
        return {"items": [], "meta": {"available": True, "reason": "no_token_hit",
                                        "built_at": h["meta"].get("built_at")}}
    # 层加权：自我/锚点优先（这正是「先看自己与近的」）
    w = {"self": 2.0, "anchor": 1.8, "knowledge": 1.2, "structural": 1.0,
         "contextual": 1.0}
    ranked = sorted(score.items(), key=lambda kv: -(kv[1] * w.get(h["nodes"].get(kv[0], {}).get("layer"), 1.0)))
    items = []
    for nid, s in ranked[:k]:
        rec = dict(h["nodes"].get(nid) or {})
        rec["hot_score"] = round(s, 4)
        items.append(rec)
    return {"items": items, "meta": {"available": True, "built_at": h["meta"].get("built_at"),
                                     "candidates": len(score), "total": h["meta"].get("nodes")}}