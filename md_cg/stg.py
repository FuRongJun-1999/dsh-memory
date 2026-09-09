# -*- coding: utf-8 -*-
"""语义时空图接口（STG）：精确得到信息的时间 / 空间关系。

节点时空字段（md 认知图 frontmatter）：
    temporal: 1788612...                    # 观测时刻（秒）
    spatial: {bbox: [x1, y1, x2, y2]}       # 空间包围盒
    condition_space.time_window: [t1, t2]   # 观测窗口（temporal 缺失时的回退）

四种查询：
    relation(a, b)   两节点间的时空关系（时间 6 态 + 空间 7 态）
    timeline(...)    按时间排序
    anchors(...)     落在给定时间窗 / 空间范围内的节点
    consistency()    时空字段自洽性检查
"""
from __future__ import annotations

TIME_RELATIONS = ("before", "after", "equals", "contains", "during", "overlaps")
SPACE_RELATIONS = ("left_of", "right_of", "above", "below",
                   "contains", "inside", "overlaps")


def _interval(fm):
    """节点时间区间：优先 temporal（事件时刻），回退 condition_space.time_window（观测窗）。

    注意 add() 在调用方未给 time_window 时会以「写入时刻」自动填充；
    若把它当事件时间，两条不同时刻的节点会得到假的重叠关系，故 temporal 优先。
    """
    t = fm.get("temporal")
    if t is not None:
        try:
            return (float(t), float(t))
        except (TypeError, ValueError):
            pass
    cs = fm.get("condition_space") or {}
    tw = cs.get("time_window")
    if isinstance(tw, (list, tuple)) and len(tw) == 2:
        try:
            return (float(tw[0]), float(tw[1]))
        except (TypeError, ValueError):
            return None
    return None


def _bbox(fm):
    sp = fm.get("spatial") or {}
    bb = sp.get("bbox") if isinstance(sp, dict) else None
    if isinstance(bb, (list, tuple)) and len(bb) == 4:
        try:
            return tuple(float(x) for x in bb)
        except (TypeError, ValueError):
            return None
    return None


def time_relation(a, b):
    """Allen 区间代数的 6 个基本态。"""
    if a is None or b is None:
        return None
    (a1, a2), (b1, b2) = a, b
    if a1 == b1 and a2 == b2:
        return "equals"
    if a2 < b1:
        return "before"
    if a1 > b2:
        return "after"
    if a1 <= b1 and a2 >= b2:
        return "contains"
    if a1 >= b1 and a2 <= b2:
        return "during"
    return "overlaps"


def space_relation(a, b):
    """RCC-8 简化的 7 个空间态（图像坐标：y 向下为正）。"""
    if a is None or b is None:
        return None
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    if ax2 <= bx1:
        return "left_of"
    if ax1 >= bx2:
        return "right_of"
    if ay2 <= by1:
        return "above"
    if ay1 >= by2:
        return "below"
    if ax1 <= bx1 and ax2 >= bx2 and ay1 <= by1 and ay2 >= by2:
        return "contains"
    if ax1 >= bx1 and ax2 <= bx2 and ay1 >= by1 and ay2 <= by2:
        return "inside"
    return "overlaps"


# ---------- 查询实现 ----------

def _node(cg, node_id):
    n = cg.get(node_id)
    if not n:
        return None
    return {"id": node_id, "frontmatter": n.get("frontmatter") or {},
            "content": n.get("content") or ""}


def _scan(cg, layer=None, max_scan=5000):
    """遍历节点：时空字段直接读索引快照（不读文件，O(1)/节点）。

    索引为旧快照（无 temporal/spatial 键）时回退读文件，保证兼容；
    正文一律不在此加载——预览按需读，避免全库 IO。
    """
    out = []
    for nid, e in list(cg.index["nodes"].items())[:max_scan]:
        if layer and e.get("layer") != layer:
            continue
        if "temporal" in e or "spatial" in e:
            fm = {"temporal": e.get("temporal"), "spatial": e.get("spatial"),
                  "condition_space": {"time_window": e.get("time_window")}}
        else:
            fm, _content = cg._read(e)
            if fm is None:
                continue
        out.append({"id": nid, "frontmatter": fm, "layer": e.get("layer"),
                    "path": e.get("path")})
    return out


def _preview(cg, node_id, n=200):
    """按需读单个节点正文做预览（只发生在最终返回的条目上）。"""
    e = cg.index["nodes"].get(node_id)
    if not e:
        return ""
    fm, content = cg._read(e)
    return (content or "")[:n] if fm is not None else ""


def relation(cg, a_id, b_id):
    """两节点间的时空关系（a 相对 b）。"""
    na, nb = _node(cg, a_id), _node(cg, b_id)
    if not na or not nb:
        return {"error": "node_not_found",
                "missing": [x for x, n in ((a_id, na), (b_id, nb)) if not n]}
    ia, ib = _interval(na["frontmatter"]), _interval(nb["frontmatter"])
    ba, bb = _bbox(na["frontmatter"]), _bbox(nb["frontmatter"])
    return {"a": a_id, "b": b_id,
            "time": {"relation": time_relation(ia, ib), "a": ia, "b": ib},
            "space": {"relation": space_relation(ba, bb), "a": ba, "b": bb},
            "meta": {"time_known": ia is not None and ib is not None,
                     "space_known": ba is not None and bb is not None}}


def timeline(cg, layer=None, limit=50, desc=True, max_scan=5000):
    """按时间排序的节点列表。"""
    items = []
    for n in _scan(cg, layer=layer, max_scan=max_scan):
        iv = _interval(n["frontmatter"])
        if iv is None:
            continue
        items.append((iv[0], iv[1], n["id"], n["layer"]))
    items.sort(key=lambda x: (x[0], x[1]), reverse=bool(desc))
    return {"count": len(items), "limit": limit,
            "items": [{"id": i, "layer": l, "start": s, "end": e,
                       "preview": _preview(cg, i)}
                      for s, e, i, l in items[:limit]]}


def anchors(cg, time_window=None, bbox=None, layer=None, limit=50, max_scan=5000):
    """落在给定时间窗 / 空间范围内的节点。"""
    q_t = None
    if isinstance(time_window, (list, tuple)) and len(time_window) == 2:
        q_t = (float(time_window[0]), float(time_window[1]))
    q_b = None
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        q_b = tuple(float(x) for x in bbox)
    if q_t is None and q_b is None:
        return {"error": "need_time_window_or_bbox"}

    hits = []
    for n in _scan(cg, layer=layer, max_scan=max_scan):
        fm = n["frontmatter"]
        iv, bb = _interval(fm), _bbox(fm)
        t_rel = time_relation(iv, q_t) if (q_t and iv) else None
        s_rel = space_relation(bb, q_b) if (q_b and bb) else None
        if q_t and t_rel not in ("during", "contains", "overlaps", "equals"):
            continue
        if q_b and s_rel not in ("inside", "contains", "overlaps", "equals"):
            continue
        hits.append({"id": n["id"], "layer": n["layer"], "time": iv, "bbox": bb,
                     "time_relation": t_rel, "space_relation": s_rel})
    for h in hits[:limit]:
        h["preview"] = _preview(cg, h["id"])
    return {"count": len(hits), "query": {"time_window": q_t, "bbox": q_b},
            "items": hits[:limit]}


def consistency(cg, layer=None, limit=50, max_scan=5000):
    """时空字段自洽性检查：非法 bbox / 时间倒置 / 窗口与时刻冲突。"""
    issues = []
    scanned = 0
    for n in _scan(cg, layer=layer, max_scan=max_scan):
        scanned += 1
        fm = n["frontmatter"]
        bb, iv = _bbox(fm), _interval(fm)
        if bb and not (bb[0] <= bb[2] and bb[1] <= bb[3]):
            issues.append({"id": n["id"], "issue": "invalid_bbox", "bbox": bb})
        if iv and iv[0] > iv[1]:
            issues.append({"id": n["id"], "issue": "inverted_time_window", "time": iv})
        t = fm.get("temporal")
        cs = fm.get("condition_space") or {}
        tw = cs.get("time_window")
        if t is not None and isinstance(tw, (list, tuple)) and len(tw) == 2:
            try:
                if not (float(tw[0]) <= float(t) <= float(tw[1])):
                    issues.append({"id": n["id"], "issue": "temporal_outside_window",
                                   "temporal": t, "time_window": [tw[0], tw[1]]})
            except (TypeError, ValueError):
                pass
    return {"scanned": scanned, "issues": len(issues), "limit": limit,
            "items": issues[:limit]}
