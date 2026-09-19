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

from . import trust

TIME_RELATIONS = ("before", "after", "equals", "contains", "during", "overlaps")
SPACE_RELATIONS = ("left_of", "right_of", "above", "below",
                   "contains", "inside", "overlaps")

# 预览脱敏占位符：时间线/锚点预览**绝不回显密文碎片**
PLACEHOLDER_LOCKED = "[密文·预览已脱敏]"
PLACEHOLDER_DENIED = "[无权限·预览已脱敏]"


# 生效条件：time_axis 经 trust.time_axis_of 归一（None → observed，非法轴如 believed 抛 ValueError）；observed 轴下 fm 的 temporal 非 None 且 float(t) 可成功时返回 (float(t), float(t))，temporal 缺失/为 None/转换抛 TypeError 或 ValueError 时回退到 fm["condition_space"]（假值按 {} 处理）的 time_window，仅当其为长度 2 的 list/tuple 且两元素可 float 时返回 (float(tw[0]), float(tw[1]))，否则返回 None；effective 轴下取 trust.time_window_of(fm, "effective") 的两端点，两端均可解析才返回 (float(s), float(e))，任一端缺失或不可解析返回 None。
def _interval(fm, time_axis="observed"):
    """节点时间区间；轴语义与 `trust.time_window_of` **同源**（唯一口径，不新写解析）。

    · `observed`（默认，与旧行为**逐位一致**）：优先 `temporal`（事件时刻），
      回退 `condition_space.time_window`（观测窗）。
      注意 add() 在调用方未给 time_window 时会以「写入时刻」自动填充；
      若把它当事件时间，两条不同时刻的节点会得到假的重叠关系，故 temporal 优先。
    · `effective`（效力轴）：`effective_from` / `effective_until` 及其别名
      （`trust.FROM_ALIASES` / `UNTIL_ALIASES`，规范键优先、别名回落）。
      区间语义要求**两端齐备**——单侧缺失/不可解析 → `None`（不可判定，
      不猜测边界：给半开区间补 `±inf` 会让 `time_relation` 报出假的 contains/during）。

    `believed_at` **永不参与任何轴**（同 `trust.BELIEVED_FIELD` 的隔离纪律）。
    """
    if trust.time_axis_of(time_axis) == "effective":
        s, e = trust.time_window_of(fm, "effective")
        if s is None or e is None:
            return None
        return (float(s), float(e))
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


# 生效条件：fm["spatial"]（假值按 {} 处理）为 dict 且其 bbox 是长度 4 的 list/tuple 且四元素可 float 时返回浮点四元组，spatial 非 dict、bbox 非长度 4 序列或元素转换抛 TypeError/ValueError 时返回 None。
def _bbox(fm):
    sp = fm.get("spatial") or {}
    bb = sp.get("bbox") if isinstance(sp, dict) else None
    if isinstance(bb, (list, tuple)) and len(bb) == 4:
        try:
            return tuple(float(x) for x in bb)
        except (TypeError, ValueError):
            return None
    return None


# 生效条件：a、b 均非 None 且各可解包为两个元素时，按 a 相对 b 依次返回 equals（两端全等）、before（a2<b1）、after（a1>b2）、contains（a1<=b1 且 a2>=b2）、during（a1>=b1 且 a2<=b2）或 overlaps（其余）；a 或 b 为 None 时返回 None；
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


# 生效条件：a 或 b 为 None 时返回 None，否则按 a=(ax1,ay1,ax2,ay2)、b=(bx1,by1,bx2,by2) 依序判定 ax2<=bx1→"left_of"、ax1>=bx2→"right_of"、ay2<=by1→"above"、ay1>=by2→"below"、四边全含→"contains"、四边全被含→"inside"，全部不满足时返回 "overlaps"。
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

# 生效条件：cg.get(node_id) 为真值（非 None、非空映射）时返回 {"id": node_id, "frontmatter": n.get("frontmatter") or {}（假值回落 {}）, "content": n.get("content") or ""（假值回落 ""）}，cg.get(node_id) 为假值时返回 None。
def _node(cg, node_id):
    n = cg.get(node_id)
    if not n:
        return None
    return {"id": node_id, "frontmatter": n.get("frontmatter") or {},
            "content": n.get("content") or ""}


# 生效条件：cg.index["nodes"] 存在时按 list(...items())[:max_scan] 遍历，layer 为真值时仅保留 e.get("layer")==layer 的条目（layer 为假值不筛层），e 含 "temporal" 或 "spatial" 键时直接以快照字段构造 frontmatter、否则调用 cg._read(e) 且在 fm 为 None 时跳过；返回 out 列表（max_scan=None 切片取全部，0 时为空）；
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
            # 效力轴四键必须一并从快照带出：否则 `time_axis="effective"` 在快照
            # 路径上永远「不可判定」（静默全空，比报错更难查）。旧索引快照无这些
            # 键时 `.get` 得 None → 不可判定，是本轴**如实降级**而非误判。
            fm = {"temporal": e.get("temporal"), "spatial": e.get("spatial"),
                  trust.EFFECTIVE_FROM_FIELD: e.get(trust.EFFECTIVE_FROM_FIELD),
                  trust.EFFECTIVE_UNTIL_FIELD: e.get(trust.EFFECTIVE_UNTIL_FIELD),
                  trust.FROM_FIELD: e.get(trust.FROM_FIELD),
                  trust.UNTIL_FIELD: e.get(trust.UNTIL_FIELD),
                  "condition_space": {"time_window": e.get("time_window")}}
        else:
            fm, _content = cg._read(e)
            if fm is None:
                continue
        out.append({"id": nid, "frontmatter": fm, "layer": e.get("layer"),
                    "path": e.get("path")})
    return out


# 生效条件：cg.index["nodes"].get(node_id) 缺失或为假值时返回 ""；否则 cg._readable 可调用且对其返回假值或抛异常时返回 PLACEHOLDER_DENIED；cg._read(e) 的 frontmatter 为 None 时返回 ""；content 非密文时返回 content[:n]（n 默认 200）；content 为密文时，cg._open_content 可调用且取到非 None 且非密文的 opened 才返回 opened[:n]，opened 为 None、抛异常或仍为密文时返回 PLACEHOLDER_LOCKED。
def _preview(cg, node_id, n=200):
    """按需读单个节点正文做预览（只发生在最终返回的条目上）。

    脱敏规则（对齐「按调用方权限返回明文或占位符」）：
      · 读隔离拦截的节点 → 占位符，不泄露任何正文；
      · 密文节点：有密钥且能解开 → 明文；否则 → 占位符，**绝不回显密文碎片**。
    """
    from . import crypto
    e = cg.index["nodes"].get(node_id)
    if not e:
        return ""
    guard = getattr(cg, "_readable", None)
    if callable(guard):
        try:
            if not guard(e):
                return PLACEHOLDER_DENIED
        except Exception:                          # noqa: BLE001
            return PLACEHOLDER_DENIED
    fm, content = cg._read(e)
    if fm is None:
        return ""
    content = content or ""
    if not crypto.is_encrypted(content):
        return content[:n]
    opener = getattr(cg, "_open_content", None)
    opened = None
    if callable(opener):
        try:
            opened = opener(node_id, fm, content)
        except Exception:                          # noqa: BLE001
            opened = None
    # 父类 _open_content 对密文是恒等返回（无密钥上下文）——再判一次，
    # 保证任何路径都不会把密文写进预览。
    if opened is None or crypto.is_encrypted(opened):
        return PLACEHOLDER_LOCKED
    return opened[:n]


# 生效条件：cg 上 _node(cg, a_id) 与 _node(cg, b_id) 均返回真值时返回含 a_id/b_id、时间关系、空间关系和 time_known/space_known 的 dict（两侧时间区间均按 time_axis 轴取，见 _interval；time_axis 非法经 trust.time_axis_of 抛 ValueError）；任一 _node 结果为假值时返回 {"error":"node_not_found","missing":[...]}；
def relation(cg, a_id, b_id, time_axis="observed"):
    """两节点间的时空关系（a 相对 b）。`time_axis` 决定时间区间取哪条轴（见 `_interval`）。"""
    na, nb = _node(cg, a_id), _node(cg, b_id)
    if not na or not nb:
        return {"error": "node_not_found",
                "missing": [x for x, n in ((a_id, na), (b_id, nb)) if not n]}
    ia, ib = (_interval(na["frontmatter"], time_axis),
              _interval(nb["frontmatter"], time_axis))
    ba, bb = _bbox(na["frontmatter"]), _bbox(nb["frontmatter"])
    return {"a": a_id, "b": b_id,
            "time": {"relation": time_relation(ia, ib), "a": ia, "b": ib},
            "space": {"relation": space_relation(ba, bb), "a": ba, "b": bb},
            "meta": {"time_known": ia is not None and ib is not None,
                     "space_known": ba is not None and bb is not None}}


# 生效条件：以 _scan(cg,layer=layer,max_scan=max_scan) 为范围，_interval(n["frontmatter"], time_axis) 为 None 的节点被跳过，其余按 (start,end) 以 reverse=bool(desc) 排序，返回 count=全部命中数、limit=传入 limit、items 为排序后前 limit 项（limit=0 时为空列表）且每项附 _preview(cg,id)（time_axis 缺省 observed，与旧行为逐位一致；非法轴抛 ValueError）。
def timeline(cg, layer=None, limit=50, desc=True, max_scan=5000,
             time_axis="observed"):
    """按时间排序的节点列表。`time_axis` 决定排序依据的时间区间（见 `_interval`）。"""
    items = []
    for n in _scan(cg, layer=layer, max_scan=max_scan):
        iv = _interval(n["frontmatter"], time_axis)
        if iv is None:
            continue
        items.append((iv[0], iv[1], n["id"], n["layer"]))
    items.sort(key=lambda x: (x[0], x[1], x[2]), reverse=bool(desc))
    return {"count": len(items), "limit": limit,
            "items": [{"id": i, "layer": l, "start": s, "end": e,
                       "preview": _preview(cg, i)}
                      for s, e, i, l in items[:limit]]}


# 生效条件：time_window 为长度 2 的 list/tuple 时 q_t=(float(time_window[0]),float(time_window[1]))（元素不可转 float 会直接抛异常，源码未捕获），bbox 为长度 4 的 list/tuple 时同理构造 q_b；q_t 与 q_b 均为 None 时返回 {"error":"need_time_window_or_bbox"}；否则扫描节点、每节点时间区间按 _interval(fm, time_axis) 取（time_axis 缺省 observed 与旧行为逐位一致，非法轴抛 ValueError），并要求时间关系在 during/contains/overlaps/equals、空间关系在 inside/contains/overlaps/equals（提供查询侧才检查），返回 hits[:limit]（limit=None 取全部，0/False 取空）；
def anchors(cg, time_window=None, bbox=None, layer=None, limit=50, max_scan=5000,
            time_axis="observed"):
    """落在给定时间窗 / 空间范围内的节点。`time_axis` 决定候选时间区间（见 `_interval`）。"""
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
        iv, bb = _interval(fm, time_axis), _bbox(fm)
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


# 生效条件：遍历 _scan(cg,layer=layer,max_scan=max_scan) 每条 frontmatter，bb 非 None 且不满足 bb[0]<=bb[2] and bb[1]<=bb[3] 记 invalid_bbox、iv（由 _interval(fm, time_axis) 取，time_axis 缺省 observed 与旧行为逐位一致、非法轴抛 ValueError）非 None 且 iv[0]>iv[1] 记 inverted_time_window、temporal 非 None 且 time_window 为长度 2 的 list/tuple 且 float 比较成功却不满足 tw[0]<=t<=tw[1] 记 temporal_outside_window（该检查恒按观察轴内部口径、不随 time_axis 漂移；转换抛 TypeError/ValueError 则忽略），返回 scanned 计数、issues 总数与 issues[:limit]（limit 默认 50）。
def consistency(cg, layer=None, limit=50, max_scan=5000, time_axis="observed"):
    """时空字段自洽性检查：非法 bbox / 时间倒置 / 窗口与时刻冲突。

    `time_axis` 只决定「时间倒置」按哪条轴判；`temporal_outside_window`
    恒按**观察轴内部**口径（temporal 与 time_window 的关系）——那是该 issue 的
    定义本身，换轴会让它变成另一件事（不随参数漂移）。
    """
    issues = []
    scanned = 0
    for n in _scan(cg, layer=layer, max_scan=max_scan):
        scanned += 1
        fm = n["frontmatter"]
        bb, iv = _bbox(fm), _interval(fm, time_axis)
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