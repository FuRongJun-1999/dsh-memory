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


# 生效条件：time_axis 经 trust.time_axis_of 归一（None → observed，非法轴如 believed 抛 ValueError）；随后**完全委托** trust.time_window_of(fm, 该轴) 取两端点，两端均可解析才返回 (float(s), float(e))，任一端缺失或不可解析返回 None。
def _interval(fm, time_axis="observed"):
    """节点时间区间；**单一口径**——直接委托 `trust.time_window_of`，不新写解析。

    · `observed`（默认，合法秒值上与旧行为逐位一致）：优先 `temporal`（事件时刻），
      回退 `condition_space.time_window`（观测窗）。
      注意 add() 在调用方未给 time_window 时会以「写入时刻」自动填充；
      若把它当事件时间，两条不同时刻的节点会得到假的重叠关系，故 temporal 优先。
    · `effective`（效力轴）：`effective_from` / `effective_until` 及其别名
      （`trust.FROM_ALIASES` / `UNTIL_ALIASES`，规范键优先、别名回落）。
      区间语义要求**两端齐备**——单侧缺失/不可解析 → `None`（不可判定，
      不猜测边界：给半开区间补 `±inf` 会让 `time_relation` 报出假的 contains/during）。

    **单位归一**单点落在 `trust.parse_time` → `trust.epoch_seconds`（issue #23）：
    旧实现在观察轴分支自己写了一份 `float(tw[0])` 裸转、**绕开了归一**，于是历史
    毫秒节点在这里拿到 1.7e12 的 `start`，把 timeline 头部占满并顶掉 auto-recall。
    委托后两个轴共用同一份取值与归一实现，不会再出现「一个轴修了、另一个轴没修」。

    `believed_at` **永不参与任何轴**（同 `trust.BELIEVED_FIELD` 的隔离纪律）。
    """
    s, e = trust.time_window_of(fm, trust.time_axis_of(time_axis))
    if s is None or e is None:
        return None
    return (float(s), float(e))


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


# 生效条件：cg.index["nodes"] 存在时**逐条**遍历全部条目（不按索引序切片、不读正文），layer 为真值时仅保留 e.get("layer")==layer 的条目（layer 为假值不筛层），cg 带可调用的 _readable（MdCGSecure）时逐条过读可见性、不可见即跳过，e 含 "temporal" 或 "spatial" 键时直接以快照字段构造 frontmatter、否则调用 cg._read(e) 且在 fm 为 None 时跳过；返回 out 列表（全部 layer/可见性命中，**不做截断**——截断由各接口在条件过滤之后经 _cap_hits 执行，issue #52）；
def _scan(cg, layer=None):
    """遍历节点：时空字段直接读索引快照（不读文件，O(1)/节点）。

    索引为旧快照（无 temporal/spatial 键）时回退读文件，保证兼容；
    正文一律不在此加载——预览按需读，避免全库 IO。
    授权单点（issue #35 会话隔离定稿）：cg 带 `_readable`（MdCGSecure）
    时逐条过读可见性——密级 × 会话绑定档在此与 _candidates 同口径，
    stg 各 op（timeline/relation/anchors）不得成为绕过路径。可见性判定
    **先于一切**（含截断）：不可见节点既不进候选、也不占 kept 名额。

    issue #52（条件先行于限额）：旧实现在此处 `list(index["nodes"].items())[:max_scan]`
    ——按 id 字典序在**条件过滤之前**砍尾巴，库超 max_scan 后（a）本会话记忆等条件
    命中若落在切片外即被永久排除（新写入节点恰在索引尾部）、（b）选面是无意义的 id
    序、（c）截断完全静默、「读不全」与「读不到」不可区分、（d）被排除集合随索引
    重排漂移。现改为：本函数只做「遍历 + layer/可见性过滤」，条件过滤与截断都归
    各接口（条件先行，截断经 `_cap_hits` 只作用于条件命中集）。
    全量快照遍历是 O(N) 内存操作（历代实测 1.7 万节点 ≈0.04s），是本修正的既定代价。
    迭代仍取 `list(...)` 快照（H-4(a) 并发纪律：裸迭代在并写索引下会
    RuntimeError）——去掉的只是切片，不是快照。
    """
    out = []
    _sec = getattr(cg, "_readable", None)
    for nid, e in list(cg.index["nodes"].items()):
        if layer and e.get("layer") != layer:
            continue
        if _sec is not None and not _sec(e):
            continue
        if "temporal" in e or "spatial" in e:
            # 效力轴四键必须一并从快照带出：否则 `time_axis="effective"` 在快照
            # 路径上永远「不可判定」（静默全空，比报错更难查）。旧索引快照无这些
            # 键时 `.get` 得 None → 不可判定，是本轴**如实降级**而非误判。
            fm = {"temporal": e.get("temporal"), "spatial": e.get("spatial"),
                  # 会话归属必须一并从快照带出：timeline 的会话过滤与归属回带都
                  # 走这条快照路径，缺键 → 本会话视图静默全空（比报错更难查）。
                  "session": e.get("session"),
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


# 生效条件：hits 为条件命中序列、max_scan 为 None 或可 int 化的单次扫描限额（None 视同不截断）、recency_key 为把单条命中映射到「越大越近期」可比较键的可调用对象时——len(hits) <= cap（cap = max_scan 为 None 时取 len(hits)，否则 int(max_scan)，负数归 0）返回 (hits 原序, False)；超限返回 (sorted(hits, key=recency_key, reverse=True)[:cap], True)。recency_key 由各接口按自己的时间轴构造且须含 id 稳定终键（同一批键下结果与索引物理序无关）。
def _cap_hits(hits, max_scan, recency_key):
    """条件命中集截断（issue #52 第 1/2 层）：只作用于**条件命中集**。

    调用点恒在条件过滤之后（条件先行）；不过限时不改序、不标记（逐位兼容）。
    兜底选序＝时间倒序优先保留近期——**不是**主修法：主修法是明确检索条件
    与建立条件索引（docs/plans/stg条件化与结构索引_设计_v0.1.md）；选序只保证
    截断真的发生时，先抛掉的是最久远/最不可判定者，而不是索引尾部。
    """
    n = len(hits)
    cap = n if max_scan is None else int(max_scan)
    if cap < 0:
        cap = 0
    if n <= cap:
        return hits, False
    return sorted(hits, key=recency_key, reverse=True)[:cap], True


# 生效条件：h 为 timeline 命中元组 (start, end, id, layer, session)；返回 (start, end, id)——「越大越近期」，id 终键保证与索引物理序无关。
def _tl_recent(h):
    return (h[0], h[1], h[2])


# 生效条件：h 为 anchors 命中 dict（含 "time" 区间或 None）时返回 (时间可判定否, start, end, id)——时间不可判定者键最小（倒序保留时最先被截），id 终键保证与索引物理序无关。
def _an_recent(h):
    iv = h.get("time")
    if iv is None:
        return (False, 0.0, 0.0, str(h.get("id")))
    return (True, iv[0], iv[1], str(h.get("id")))


# 生效条件：n 为 _scan 条目、time_axis 为时间轴名时返回 (时间可判定否, start, end, id)（口径同 _an_recent，区间按 time_axis 轴经 _interval 取；非法轴由 _interval 抛 ValueError，不吞错）。
def _co_recent(n, time_axis):
    iv = _interval(n["frontmatter"], time_axis)
    if iv is None:
        return (False, 0.0, 0.0, str(n["id"]))
    return (True, iv[0], iv[1], str(n["id"]))


# 截断可操作提示（issue #52 第 2 层：禁止静默）——文案必须含「细化生效条件/不适用条件」与「建立条件索引」语义；数值放大（调 max_scan）不是修法，故明文劝阻。
_CAP_HINT = ("条件命中 %s 条超过单次扫描限额 max_scan=%s，已按时间倒序保留近期 %s 条"
             "（截断不静默）：请细化生效条件/不适用条件（如 session/layer/time_window）"
             "收窄命中集，或按设计稿建立条件索引（docs/plans/stg条件化与结构索引_设计_v0.1.md）"
             "——不要调大 max_scan 数值。")


# 生效条件：out 为接口返回体（dict）、scanned 为候选遍历数（layer/可见性过滤后、截断前）、hits 为条件命中总数（截断前）、kept 为截断后保留数、truncated 为其布尔标记、max_scan 为本次限额——恒把 scanned/kept/truncated 三键并入 out；truncated 为真时再并入 hint（_CAP_HINT 插值 hits/max_scan/kept）；返回 out。
def _with_scan_reads(out, *, scanned, hits, kept, truncated, max_scan):
    """读数与截断标记的统一出口（timeline/anchors/consistency 同一口径）。"""
    out.update({"scanned": scanned, "kept": kept, "truncated": truncated})
    if truncated:
        out["hint"] = _CAP_HINT % (hits, max_scan, kept)
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


# 生效条件：session 为 None 或 str(session).strip() 为空串时返回 ""（跨会话视图的内部表示，与旧实现 `"" if session is None else str(session).strip()` 逐位一致）；去空白后恰为 "*" 时返回 "*"；否则延迟导入 mcp_server._normalize_session 并返回其归一结果；该导入抛任何异常（ImportError 等）时返回去空白原值（fail-soft 退回旧行为）。
def _view_session(session):
    """读侧会话视图值 → 过滤值：**与写侧同一把尺**（H2，2026-09-30）。

    动机（端到端实测，见 `md_cg/test_h2_session_view_norm.py`）：写侧落盘值 =
    `_normalize_session(请求声明值)`（`MdCGSecure._attribution` 取 `cg.session`，
    而 `cg.session` 由 `call_tool` → `_declared_session` 归一），读侧若拿
    **未归一的原值**做等值比较，同一条记忆就「写进去查不出」——DSH 形态的
    会话 id 在会话根下不存在时，写侧落 `anonymous`、读侧按 `session-…`
    精确匹配 ⇒ `count=0`。

    由此本函数**只归一「具体会话值」这一态**，三态语义逐位不变：
      · None / 空串 → 跨会话（缺省不过滤，向后兼容）；
      · `"*"`       → 跨会话（显式意图；`"*"` 不是会话名，**不归一**）；
      · 其它值      → 过 `_normalize_session`（本会话视图与写侧同尺）。

    真源只有一份（`mcp_server._normalize_session`），此处**消费而不重写**：
    写侧读侧各写一份校验必然造出第三种不等值。延迟导入的副作用为零——正常
    形态下 stg 本就被 mcp_server 调用（模块早已加载）；`stg` 被独立使用时导入
    失败即 fail-soft 返回原值（退回旧行为，不报错、不改变既有语义）。

    不适用条件：`cg` 侧读路径（search/recall/`cg(op=read)`）的请求 `session`
    走 `MdCGSecure._candidates` 的**身份判定**（issue #35 定稿：身份不可自报），
    不经本函数——那不是视图过滤，两处不得互相「对齐」。

    返回值口径：None 与空串一律映射为 `""`（旧实现 `"" if session is None
    else str(session).strip()` 的内部表示，跨会话分支判据 `sid in ("", "*")`
    依赖它——返回 None 会让 `cross` 判假、把缺省视图变成「只看 session 为
    空的节点」，是一处会静默清空整块自动召回的坑）。
    """
    if session is None:
        return ""
    s = str(session).strip()
    if s in ("", "*"):
        return s
    try:
        from .mcp_server import _normalize_session
    except Exception:                          # noqa: BLE001  fail-soft：保旧行为
        return s
    return _normalize_session(s)


# 生效条件：以 _scan(cg,layer=layer) 为候选（全部 layer/可见性命中），session 经 _view_session 归一后（None/空/"*"=跨会话不过滤，其它值=归一后的具体会话）非跨会话时仅保留 frontmatter.session 精确相等的节点，_interval(n["frontmatter"], time_axis) 为 None 的节点被跳过——**条件命中集到此确定**；随后才截断：命中集超过 max_scan（默认 5000 不变）时按 (start,end,id) 时间倒序保留近期 max_scan 条并标记 truncated；保留集按 (start,end,id) 以 reverse=bool(desc) 排序，返回 count=条件命中总数（截断前，**不再受索引切片影响**）、limit=传入 limit、session=生效的会话过滤值（跨会话时为 None）、scanned=候选遍历数、kept=截断后保留数、truncated=截断标记（截断时另有 hint）、items 为排序后前 limit 项（limit=0 时为空列表）且每项附 session 归属与 _preview(cg,id)（time_axis 缺省 observed，与旧行为逐位一致；非法轴抛 ValueError）。
def timeline(cg, layer=None, limit=50, desc=True, max_scan=5000,
             time_axis="observed", session=None):
    """按时间排序的节点列表。`time_axis` 决定排序依据的时间区间（见 `_interval`）。

    `session` 是**视图开关**（P45 归因维度，与授权正交）：
      · 缺省 None / 空串 → 不过滤：一次读遍所有会话（向后兼容，旧调用方多如此）；
      · `"*"` → 同上语义，但把「我要看所有会话做了什么」写成**显式意图**，与
        「忘了传参」区分开，审计里也看得出这是一次跨会话读取；
      · 其它值 → 只取 `frontmatter.session` 精确相等的节点（本会话视图，
        自动召回用它防串台）。**该值先过 `_view_session` 归一**（H2）——
        写侧落盘时已过 `_normalize_session`，读侧不过同一把尺就会出现
        「写进去查不出」；返回体 `session` 回带的是**归一后**的生效值。
    `items` 一并回带 `session`：跨会话视图下「这条是哪个会话做的」必须可辨，
    否则「能读到所有会话做了什么」只剩内容、丢了归属。

    issue #52（条件先行 + 截断可观测）：`max_scan`（默认 5000，数值不变）
    **只在条件命中集上生效**——旧实现把它当索引序切片（在 session/时间条件
    过滤**之前**砍尾巴），本会话记忆因落在切片外而整片消失且没有任何标记；
    现在 `count` 恒为条件命中总数（不受切片影响），命中集超限才按时间倒序
    保留近期，并在返回体上报 `truncated`/`scanned`/`kept`/`hint`。
    """
    sid = _view_session(session)
    cross = sid in ("", "*")            # 跨会话：显式 "*" 与缺省同义
    scanned = 0
    items = []
    for n in _scan(cg, layer=layer):
        scanned += 1
        fm = n["frontmatter"] or {}
        if not cross and fm.get("session") != sid:
            continue
        iv = _interval(fm, time_axis)
        if iv is None:
            continue
        items.append((iv[0], iv[1], n["id"], n["layer"], fm.get("session")))
    hits = len(items)                    # 条件命中总数（截断前，count 的口径）
    items, truncated = _cap_hits(items, max_scan, _tl_recent)
    kept = len(items)
    items.sort(key=lambda x: (x[0], x[1], x[2]), reverse=bool(desc))
    return _with_scan_reads(
        {"count": hits, "limit": limit,
         "session": None if cross else sid,
         "items": [{"id": i, "layer": l, "start": s, "end": e,
                    "session": sn, "preview": _preview(cg, i)}
                   for s, e, i, l, sn in items[:limit]]},
        scanned=scanned, hits=hits, kept=kept, truncated=truncated,
        max_scan=max_scan)


# 生效条件：time_window 为长度 2 的 list/tuple 时 q_t=(float(time_window[0]),float(time_window[1]))（元素不可转 float 会直接抛异常，源码未捕获），bbox 为长度 4 的 list/tuple 时同理构造 q_b；q_t 与 q_b 均为 None 时返回 {"error":"need_time_window_or_bbox"}；否则以 _scan(cg,layer=layer) 为候选逐节点取 _interval(fm, time_axis)（time_axis 缺省 observed 与旧行为逐位一致，非法轴抛 ValueError）与 _bbox，要求时间关系在 during/contains/overlaps/equals、空间关系在 inside/contains/overlaps/equals（提供查询侧才检查）——**条件命中集到此确定**；随后才截断：命中集超过 max_scan（默认 5000 不变）时按 (时间可判定否,start,end,id) 倒序保留近期 max_scan 条并标记 truncated（无时间区间者最先被截）；返回 count=条件命中总数（截断前）、query、scanned=候选遍历数、kept=截断后保留数、truncated=截断标记（截断时另有 hint）、items=hits[:limit]（limit=None 取全部，0/False 取空）且每条附 preview；
def anchors(cg, time_window=None, bbox=None, layer=None, limit=50, max_scan=5000,
            time_axis="observed"):
    """落在给定时间窗 / 空间范围内的节点。`time_axis` 决定候选时间区间（见 `_interval`）。

    issue #52（条件先行 + 截断可观测）：时间窗/空间范围的条件命中集先于
    `max_scan`（默认 5000，数值不变）确定——`count` 恒为条件命中总数，
    命中集超限才按时间倒序保留近期（无时间区间者先被截），并上报
    `truncated`/`scanned`/`kept`/`hint`；旧实现按索引序切片在条件**之前**，
    命中项落在切片外即静默消失。
    """
    q_t = None
    if isinstance(time_window, (list, tuple)) and len(time_window) == 2:
        q_t = (float(time_window[0]), float(time_window[1]))
    q_b = None
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        q_b = tuple(float(x) for x in bbox)
    if q_t is None and q_b is None:
        return {"error": "need_time_window_or_bbox"}

    scanned = 0
    hits = []
    for n in _scan(cg, layer=layer):
        scanned += 1
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
    total = len(hits)                    # 条件命中总数（截断前，count 的口径）
    hits, truncated = _cap_hits(hits, max_scan, _an_recent)
    kept = len(hits)
    for h in hits[:limit]:
        h["preview"] = _preview(cg, h["id"])
    return _with_scan_reads(
        {"count": total, "query": {"time_window": q_t, "bbox": q_b},
         "items": hits[:limit]},
        scanned=scanned, hits=total, kept=kept, truncated=truncated,
        max_scan=max_scan)


# 生效条件：以 cand=list(_scan(cg,layer=layer)) 为候选（scanned=len(cand) 为遍历读数，layer/可见性即其条件面），**先**按 (时间可判定否,start,end,id) 时间倒序截断到 max_scan（默认 5000 不变，截断时 kept=保留数、truncated=True 并附 hint）——随后逐条检查：bb 非 None 且不满足 bb[0]<=bb[2] and bb[1]<=bb[3] 记 invalid_bbox、iv（由 _interval(fm, time_axis) 取，time_axis 缺省 observed 与旧行为逐位一致、非法轴抛 ValueError）非 None 且 iv[0]>iv[1] 记 inverted_time_window、temporal 与 time_window 均经 trust.epoch_seconds 归一后可比且不满足 tw[0]<=t<=tw[1] 记 temporal_outside_window（该检查恒按观察轴内部口径、不随 time_axis 漂移；任一端不可转数值则忽略）；返回 issues 总数与 issues[:limit]（limit 默认 50）、scanned=遍历读数、kept=实际检查节点数、truncated=截断标记（截断时另有 hint）。
def consistency(cg, layer=None, limit=50, max_scan=5000, time_axis="observed"):
    """时空字段自洽性检查：非法 bbox / 时间倒置 / 窗口与时刻冲突。

    `time_axis` 只决定「时间倒置」按哪条轴判；`temporal_outside_window`
    恒按**观察轴内部**口径（temporal 与 time_window 的关系）——那是该 issue 的
    定义本身，换轴会让它变成另一件事（不随参数漂移）。

    两端比较前统一经 `trust.epoch_seconds` 归一：旧实现裸 `float` 比较，历史毫秒
    节点的 `1.7e12` 与秒级 `temporal` 永不落入区间 → 该检查在真实库中**静默失效**
    （issue #23 同根因）。返回体的 `temporal` / `time_window` 也随之为归一后的秒值。

    issue #52（条件先行 + 截断可观测）：候选/条件命中集（layer × 可见性）
    **先于** `max_scan`（默认 5000，数值不变）确定；超限时按时间倒序保留近期
    再检查——`kept` 为实际检查数、`truncated` 显式上报（旧实现按索引序切片
    且无任何标记，「读不全」与「读不到」不可区分）。
    """
    cand = list(_scan(cg, layer=layer))
    scanned = len(cand)
    cand, truncated = _cap_hits(cand, max_scan, lambda n: _co_recent(n, time_axis))
    kept = len(cand)
    issues = []
    for n in cand:
        fm = n["frontmatter"]
        bb, iv = _bbox(fm), _interval(fm, time_axis)
        if bb and not (bb[0] <= bb[2] and bb[1] <= bb[3]):
            issues.append({"id": n["id"], "issue": "invalid_bbox", "bbox": bb})
        if iv and iv[0] > iv[1]:
            issues.append({"id": n["id"], "issue": "inverted_time_window", "time": iv})
        t = trust.epoch_seconds(fm.get("temporal"))
        cs = fm.get("condition_space") or {}
        tw = cs.get("time_window")
        if t is not None and isinstance(tw, (list, tuple)) and len(tw) == 2:
            lo, hi = trust.epoch_seconds(tw[0]), trust.epoch_seconds(tw[1])
            if lo is not None and hi is not None and not (lo <= t <= hi):
                issues.append({"id": n["id"], "issue": "temporal_outside_window",
                               "temporal": t, "time_window": [lo, hi]})
    return _with_scan_reads(
        {"issues": len(issues), "limit": limit, "items": issues[:limit]},
        scanned=scanned, hits=scanned, kept=kept, truncated=truncated,
        max_scan=max_scan)