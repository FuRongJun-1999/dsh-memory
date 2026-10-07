# -*- coding: utf-8 -*-
"""盲区 → 目标生成器（W2 自主目标 · 第 2 小步实施）。

功能名：goal_gen —— 盲区信号六源 → 目标候选（确定性模板 + 三区确认闸 + 留痕）。
生效条件：**仅显式调用**（MCP `cg(op=goal, action=generate)` 或
    `goal_gen.candidates(cg, ...)`）；首版**不进 sleep/sustain 自动循环**
    （设计者裁定第 8 条：阈值未标定前自动化 = 制造噪声）。
    外部定义的损失函数场景（训练/评测回路）不适用（N1）。
子功能：① 六路**只读**信号源各出一组候选——
    S1 unresolved 未解台账（`mdcg.add_unresolved` :2857）
    S2 insight pending 待验证洞见（`insight.record` :164 / `list_events` :340）
    S3 sustain 固化候补（`sustain.evolution_candidates` :510 → `_ccg_backlog` :484）
    S4 BLINDSPOT 高频盲区（`metacognition.blindspots` :259）
    S5 predict 空路由（`predict.routes` :625 → `routes_from_blindspot` :650）
    S6 evolution 缺失维度（`evolution.patterns` :308）
  ② 三区确认闸分档（裁定第 9 条白名单冻结）——维护类过 `autonomy_modes.decide(A_ADD)`
    （:335）判 allow 才自动 `add_goal`；探索类一律入审核队列（`cg.propose` :2134）；
    越权类（命中纲领 §七边界词面）**直接丢弃并记 boundary_refused**（不静默）。
  ③ 每轮生成 append 一条留痕（形态照 `autonomy._explore.jsonl` :47/:256）。
执行：`candidates(cg, sources=None, limit=N, apply=False)` —— 默认 dry_run（零落库）；
    `apply=True` 才落台账 / 入队 / 丢弃。goal_text 用确定性模板（不含时间戳/随机），
    复用 `add_goal` 的 sha1 幂等（`mdcg.py` :2939，同文本 → 同 id → 覆盖更新）。
验证方式：`python -m md_cg.test_goal_gen`（含定点变异自证）。
不适用条件：结构性不可知盲区不生成（`predictability == "unknowable"`，N2）；
    退出权/自毁归 W3（N3，本模块不触碰）。

边界（如实）：本模块**只产文本候选**，不执行任何外部动作；落库一律经
`cg.add_goal`（公开 API，库层 `require_layer_write("goals", …)` 不可绕，`security.py` :217）
——**禁止直调 `_write_node`**（红线三「价值观判定被绕过」）。
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from . import autonomy_modes, evolution, insight, metacognition, predict, sustain
from .fsutil import append_jsonl

__all__ = [
    "GOAL_LOG", "DEFAULT_LIMIT",
    "CLASS_MAINTAIN", "CLASS_EXPLORE", "CLASS_REFUSE",
    "BOUNDARY_WORDS", "MAINTAIN_SOURCES",
    "S1_TEMPLATE", "S2_PENDING_MIN", "S3_CCG_MIN", "S4_BLINDSPOT_MIN",
    "S6_MISSING_MIN", "S4_SCAN", "S5_SCAN",
    "candidates", "classify_candidate", "hits_boundary", "goal_log_path",
]

#: 生成留痕日志名（形态照 `autonomy.EXPLORE_LOG` :61，append-only jsonl）
GOAL_LOG = "_goal_gen.jsonl"
#: 每轮候选上限（照 `blindspot_tickets.make_tickets` 的 `limit` :66）
DEFAULT_LIMIT = 10

# ---- 三区分类（裁定第 9 条「白名单冻结」） --------------------------------
CLASS_MAINTAIN = "维护类"   # S3 / S6：结构自维护，过 decide(A_ADD) 可自动登记
CLASS_EXPLORE = "探索类"    # S1 / S2 / S4 / S5 及涉新方向者：一律入审核队列
CLASS_REFUSE = "越权类"     # 命中纲领 §七运行规则 5 边界词面：直接丢弃

#: 可自动登记的白名单源（**冻结**：只有结构自维护两源）
MAINTAIN_SOURCES = ("S3", "S6")

#: 纲领 §七运行规则 5「须停下待裁的边界」词面（命中即拒，不静默）
#: （`docs/plans/灵枢1.0_最小智能系统实存答卷_纲领_v0.1.md` L171）
BOUNDARY_WORDS = ("对外发送", "对外发布", "npm publish", "智能论真源",
                  "资金", "账号")

# ---- 六源阈值（**首版保守缺省、观察期标定**，裁定第 10 条） -------------------
S1_TEMPLATE = "消解未解问题：%s"
S2_PENDING_MIN = 3          # 沿用 insight.outlook 既有建议阈值（:423 pending>=3）
S3_CCG_MIN = 5              # 单层无验证基底节点数阈值（保守）
S4_BLINDSPOT_MIN = 3        # 与 blindspot_tickets._JUDGE research 判据同源（:30）
S6_MISSING_MIN = 3          # 单一缺失维度计分阈值（保守）
S4_SCAN = 50                # 盲区地图扫描上限（候选筛选用，非落库）
S5_SCAN = 20                # S5 空路由探针扫描上限（避免每轮全库推演）

#: 优先级权重（确定性：priority = clamp(base + W_FREQ·频次 + W_IMPACT·影响面)）
W_FREQ, W_IMPACT = 0.03, 0.01


# ---------------------------------------------------------------- 基础工具

# 生效条件：x 与常量 lo/hi 比较，返回钳制在 [lo, hi] 内的同型值（lo 缺省 0.0、hi 缺省 1.0）。
def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# 生效条件：base 为数值、freq/impact 经 int() 转整数（失败回落 0），返回 clamp(base + W_FREQ·min(freq,10) + W_IMPACT·min(impact,20)) 并 round(·,4)——纯函数、无 IO、无时间戳，同输入恒同值；
def _prio(base, freq, impact_n):
    """确定性优先级（base + 频次项 + 影响面项，钳制 [0,1]）。"""
    f = min(int(freq or 0), 10)
    i = min(int(impact_n or 0), 20)
    return round(_clamp(base + W_FREQ * f + W_IMPACT * i), 4)


# 生效条件：cg 有 root 属性时以其值为目录前缀，否则回落 '.'，与模块常量 GOAL_LOG 拼接；纯字符串运算，不触碰盘面。
def goal_log_path(cg):
    """生成留痕日志完整路径（形态照 `autonomy._explore_log_path` :73）。"""
    return os.path.join(getattr(cg, "root", "."), GOAL_LOG)


# 生效条件：text 经 str() 与 lower() 归一后逐词匹配 BOUNDARY_WORDS（同样 lower 归一），命中返回该词原形，未命中返回 None；
def hits_boundary(text):
    """命中纲领 §七边界词面则返回该词，否则 None。"""
    t = str(text or "").lower()
    for w in BOUNDARY_WORDS:
        if w.lower() in t:
            return w
    return None


# 生效条件：cand 为 dict 时取 goal_text / conditions / evidence(json 串) 拼成一串返回，非 dict 返回空串；纯字符串运算。
def _cand_blob(cand):
    ev = cand.get("evidence")
    try:
        ev_s = json.dumps(ev, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        ev_s = str(ev)
    return " ".join([str(cand.get("goal_text") or ""),
                     str(cand.get("conditions") or ""), ev_s])


# 生效条件：候选命中边界词面 → CLASS_REFUSE；否则 source 属 MAINTAIN_SOURCES → CLASS_MAINTAIN；其余 → CLASS_EXPLORE；
def classify_candidate(cand):
    """三区分类（越权类优先——命中边界词面即拒，不看来源）。"""
    if hits_boundary(_cand_blob(cand)):
        return CLASS_REFUSE
    return (CLASS_MAINTAIN if cand.get("source") in MAINTAIN_SOURCES
            else CLASS_EXPLORE)


# 生效条件：恒返回一条候选 dict，键集固定（source/evidence/impact/goal_text/priority/conditions/class），class 恒为 None（由 candidates() 统一分类）；纯构造，无 IO。
def _cand(source, evidence, impact, goal_text, priority, conditions):
    return {"source": source, "evidence": evidence, "impact": impact,
            "goal_text": goal_text, "priority": float(priority),
            "conditions": conditions, "class": None}


# 生效条件：content 按行切分，取以「# 问题：」开头行的去前缀值返回 question、以「# 目标：」开头行的去前缀值返回 goal_line；两行缺一或全缺时对应值为空串；
def _unresolved_fields(content):
    """解析 unresolved 正文（模板见 `mdcg.add_unresolved._render` :2869）。"""
    q, g = "", ""
    for line in str(content or "").splitlines():
        s = line.strip()
        if s.startswith("# 问题："):
            q = s[len("# 问题："):].strip()
        elif s.startswith("# 目标："):
            g = s[len("# 目标："):].strip()
    return q, g


def _nodes(cg):
    return (getattr(cg, "index", {}) or {}).get("nodes") or {}


# ---------------------------------------------------------------- 六源（只读）

# 生效条件：遍历索引中 layer=="unresolved" 的节点，读取其正文；「# 问题：」行非空且「# 目标：」行为空或「（未设定）」时产出一条候选，否则跳过；只读、无落库；
def _s1(cg):
    """S1 · unresolved 未解问题台账 → 消解目标。"""
    out = []
    for nid, e in list(_nodes(cg).items()):
        if (e or {}).get("layer") != "unresolved":
            continue
        node = cg.get(nid) or {}
        question, goal_line = _unresolved_fields(node.get("content") or "")
        if not question:
            continue
        if goal_line and goal_line not in ("（未设定）",):
            continue                       # 已设定目标 → 不再生成（幂等语义）
        out.append(_cand(
            "S1", evidence={"node_id": nid, "question": question},
            impact={"layer": "unresolved", "n": 1},
            goal_text=S1_TEMPLATE % question,
            priority=_prio(0.5, 1, 1),
            conditions="库内存在该 unresolved 工单且未被裁决时"))
    return out


# 生效条件：insight.list_events(state=pending) 取待验证洞见；计数 < S2_PENDING_MIN 时返回空列表（沿用既有建议阈值，不新造）；否则逐条 pending 事件（正文取 frontmatter.insight_statement，空则跳过）各产出一条候选；
def _s2(cg):
    """S2 · insight pending 待验证洞见 → 裁决目标。"""
    try:
        events = insight.list_events(cg, state=insight.STATE_PENDING)
    except Exception:                       # noqa: BLE001
        return []
    if len(events) < S2_PENDING_MIN:
        return []
    out = []
    for ev in events:
        nid = ev.get("node_id")
        node = cg.get(nid) or {}
        stmt = str((node.get("frontmatter") or {})
                   .get("insight_statement") or "").strip()
        if not stmt:
            continue
        out.append(_cand(
            "S2", evidence={"node_id": nid, "pending": len(events)},
            impact={"layer": "insight", "n": len(events)},
            goal_text="裁决待验证洞见：%s" % stmt,
            priority=_prio(0.5, len(events), len(events)),
            conditions="该洞见仍处 pending 且无外部证据时"))
    return out


# 生效条件：按层分组统计固化候补（谓词镜像 sustain._ccg_backlog :497-500：缺 verification_basis 或 has_neg_conditions），返回 {layer: {"n","no_basis","no_neg"}}；只读索引、零写盘。
def _ccg_backlog_by_layer(cg):
    out = {}
    for _nid, e in list(_nodes(cg).items()):
        e = e or {}
        mb = not e.get("verification_basis")
        mn = not e.get("has_neg_conditions")
        if not (mb or mn):
            continue
        layer = str(e.get("layer") or "unknown")
        d = out.setdefault(layer, {"n": 0, "no_basis": 0, "no_neg": 0})
        d["n"] += 1
        d["no_basis"] += 1 if mb else 0
        d["no_neg"] += 1 if mn else 0
    return out


# 生效条件：sustain.evolution_candidates(cg) 的 ccg_backlog.n 为 0 时返回空列表（无货不生成）；否则按层产出候选——单层 no_basis >= S3_CCG_MIN 时产出一条；只读、零落库；
def _s3(cg):
    """S3 · sustain 固化候补（**索引代理指标**，只作驱动信号）→ 清账目标。"""
    try:
        ev = sustain.evolution_candidates(cg)
    except Exception:                       # noqa: BLE001
        return []
    cb = (ev or {}).get("ccg_backlog") or {}
    if not cb.get("n"):
        return []
    out = []
    for layer, d in sorted(_ccg_backlog_by_layer(cg).items()):
        if d["no_basis"] < S3_CCG_MIN:
            continue
        out.append(_cand(
            "S3", evidence={"layer": layer, "no_basis": d["no_basis"],
                            "no_neg": d["no_neg"], "n": d["n"]},
            impact={"layer": layer, "n": d["n"]},
            goal_text="固化候补清账：%s 层 %d 个无验证基底节点"
                      % (layer, d["no_basis"]),
            priority=_prio(0.6, d["no_basis"], d["n"]),
            conditions="库内该层固化候补 ≥ 阈值时"))
    return out


# 生效条件：metacognition.blindspots(limit=S4_SCAN) 的 items 中 blindspot >= S4_BLINDSPOT_MIN 且 query 非空者各产出一条候选（goal_text 用 metacognition._key(query) 作稳定标识）；只读；
def _s4(cg):
    """S4 · BLINDSPOT 高频盲区 → 补条件目标。"""
    try:
        mp = metacognition.blindspots(cg, limit=S4_SCAN)
    except Exception:                       # noqa: BLE001
        return []
    out = []
    for it in mp.get("items") or []:
        b = int(it.get("blindspot") or 0)
        if b < S4_BLINDSPOT_MIN:
            continue
        q = str(it.get("query") or "").strip()
        if not q:
            continue
        out.append(_cand(
            "S4", evidence={"query": q, "blindspot": b,
                            "defer": int(it.get("defer") or 0)},
            impact={"layer": "contextual", "n": b},
            goal_text="补条件消解高频盲区：%s" % metacognition._key(q),
            priority=_prio(0.5, b, b),
            conditions="该盲区簇 BLINDSPOT/DEFER 计数未归零时"))
    return out


# 生效条件：探针源 = unresolved 节点 id ∪ 盲区簇 key（与 predict.find_blindspot :454 同口径），去重后逐源调 predict.routes(blindspot_id=…)：status 为 unpredictable/blindspot_not_found 的跳过（N2 结构性不可知不生成），routes 为空且 status 属 {no_anchor, ok} 的产出一条候选；扫描上限 S5_SCAN；只读、零落库；
def _s5(cg):
    """S5 · predict 空路由 → 补锚点/边目标。"""
    bids = []
    for nid, e in list(_nodes(cg).items()):
        if (e or {}).get("layer") == "unresolved":
            bids.append(nid)
    try:
        mp = metacognition.blindspots(cg, limit=S4_SCAN)
    except Exception:                       # noqa: BLE001
        mp = {}
    for it in mp.get("items") or []:
        q = str(it.get("query") or "").strip()
        if q:
            bids.append(metacognition._key(q))
    out, seen = [], set()
    for bid in bids:
        if bid in seen:
            continue
        seen.add(bid)
        if len(seen) > S5_SCAN:
            break
        try:
            res = predict.routes(cg, blindspot_id=bid)
        except Exception:                   # noqa: BLE001
            continue
        st = res.get("status")
        if st in ("unpredictable", "blindspot_not_found"):
            continue                        # N2：结构性不可知 / 未定位，不生成
        if res.get("routes"):
            continue                        # 有路由 → 非空，不生成
        if st not in ("no_anchor", "ok"):
            continue
        out.append(_cand(
            "S5", evidence={"blindspot_id": bid, "status": st},
            impact={"layer": "contextual", "n": 1},
            goal_text="补锚点/边：%s 推演路由为空" % bid,
            priority=_prio(0.45, 1, 1),
            conditions="该方向可预测（非 unknowable）且路由仍为空时"))
    return out


# 生效条件：evolution.patterns(cg) 的 by_missing 中计数 >= S6_MISSING_MIN 的维度各产出一条候选（按字段名排稳序）；只读；
def _s6(cg):
    """S6 · evolution 缺失维度 → 补条件维度目标。"""
    try:
        p = evolution.patterns(cg)
    except Exception:                       # noqa: BLE001
        return []
    out = []
    for field, cnt in sorted((p.get("by_missing") or {}).items()):
        if int(cnt) < S6_MISSING_MIN:
            continue
        out.append(_cand(
            "S6", evidence={"missing": field, "count": int(cnt)},
            impact={"layer": "structural", "n": int(cnt)},
            goal_text="补条件维度：%s" % field,
            priority=_prio(0.55, int(cnt), int(cnt)),
            conditions="该维度缺失计分位仍 ≥ 阈值时"))
    return out


_SOURCES = {"S1": _s1, "S2": _s2, "S3": _s3, "S4": _s4, "S5": _s5, "S6": _s6}


# ---------------------------------------------------------------- 确认闸（分档落点）

# 生效条件：cand["goal_text"] 非空时以其 utf-8 sha1 前 10 位构造 "goal_<hex>"（与 mdcg.add_goal 的 gid 同口径 :2939）；空文本回落 "goal_" + 空 sha1 片段；
def _goal_id(goal_text):
    return "goal_%s" % hashlib.sha1(
        str(goal_text or "").encode("utf-8")).hexdigest()[:10]


# 生效条件：恒返回候选的 CCG 六要素正文（目标按 CCG 格式落盘，保证 judge_qualification 给 ACCEPT 而非 BLINDSPOT，与 mdcg._goal_content :2915 同构）；纯字符串拼接；
def _proposal_content(cand):
    return ("# 功能名：%s\n"
            "# 生效条件：%s\n"
            "# 子功能：自主目标候选（来源 %s）——为检索提供方向偏置（goal 路）\n"
            "# 执行：经 cg(op=goal, action=generate) 生成；入审核队列待裁决\n"
            "# 验证方式：other\n"
            "# 不适用条件：目标状态为 done/dropped 时不再参与定向\n"
            % (cand.get("goal_text") or "",
               cand.get("conditions") or "（未声明——视为任意情境下有效）",
               cand.get("source") or "?"))


# 生效条件：cg 具 propose 时以确定性 gid 为 node_id、CCG 正文为 content、layer="goals" 入既有审核队列（kind 缺省 = proposal，靠 tags 标识来源）；返回 pid；
def _enqueue(cg, cand):
    return cg.propose(
        _goal_id(cand["goal_text"]), _proposal_content(cand),
        layer="goals", tags=["goal-gen", "goal-gen:%s" % cand["source"]])


# 生效条件：按 cand["class"] 分档——越权类返回 boundary_refused（记命中词，不落库）；维护类先调 autonomy_modes.decide(A_ADD) 判 allow（auto add_goal）/confirm（入队）/forbid（fail-closed 拒）；探索类一律入审核队列；只写经公开 API（add_goal / propose），绝不直调 _write_node；
def _apply_candidate(cg, cand, actor=None):
    """确认闸分档落点（自主 ≠ 自裁）。"""
    cls = cand.get("class")
    if cls == CLASS_REFUSE:
        return {"moved_to": "boundary_refused",
                "boundary_word": hits_boundary(_cand_blob(cand)) or "",
                "decision": "refused"}
    if cls == CLASS_MAINTAIN:
        dec = autonomy_modes.decide(autonomy_modes.A_ADD)
        d = dec.get("decision")
        if d == autonomy_modes.ALLOW:
            kw = {"actor": actor} if actor else {}
            gid = cg.add_goal(cand["goal_text"], priority=cand["priority"],
                              conditions=cand["conditions"],
                              tags=["goal-gen", "goal-gen:%s" % cand["source"]],
                              **kw)
            return {"moved_to": "goals", "id": gid, "decision": d,
                    "mode": dec.get("mode")}
        if d == autonomy_modes.CONFIRM:      # confirm 档：出变更单（入审核队列）
            return {"moved_to": "review_queue", "pid": _enqueue(cg, cand),
                    "decision": d, "mode": dec.get("mode")}
        return {"moved_to": "forbidden", "decision": d,
                "mode": dec.get("mode"), "hint": dec.get("hint")}
    # 探索类：一律入审核队列（不入 goals 层）
    return {"moved_to": "review_queue", "pid": _enqueue(cg, cand),
            "decision": "confirm"}


# 生效条件：cg 与 rec 传入时经 fsutil.append_jsonl 追加一条生成留痕；仅 OSError 被忽略（留痕失败不阻断主流程，与 autonomy.explore :316-319 同款）；
def _log(cg, rec):
    try:
        append_jsonl(goal_log_path(cg), rec)
    except OSError:
        pass


# ---------------------------------------------------------------- 入口

# 生效条件：cg 具 index/get/add_goal/propose 时——按 sources（缺省六源全开，非法项忽略）收集候选、统一分类、按 (-priority, goal_text) 稳序并截断到 limit；apply=False（默认）全部标 moved_to="dry_run"（零落库）；apply=True 经 _apply_candidate 分档落库/入队/丢弃；末尾 append 一条生成留痕；返回含 by_class/created/queued/refused 计数的结果体；
def candidates(cg, sources=None, limit=DEFAULT_LIMIT, apply=False, actor=None):
    """盲区 → 目标候选（默认 dry_run；apply=True 才落台账/入队/丢弃）。"""
    want = [str(s).strip().upper() for s in sources] if sources else list(_SOURCES)
    raw = []
    for sid in want:
        fn = _SOURCES.get(sid)
        if fn is None:
            continue
        raw.extend(fn(cg))
    for c in raw:
        c["class"] = classify_candidate(c)
    # 稳序：优先级降序，同优先级按 goal_text 升序（**确定性**，不含时间/随机）
    raw.sort(key=lambda c: (-c["priority"], c["goal_text"]))
    raw = raw[:int(limit)]

    out, by_class = [], {}
    created = queued = refused = forbidden = 0
    for c in raw:
        by_class[c["class"]] = by_class.get(c["class"], 0) + 1
        if apply:
            res = _apply_candidate(cg, c, actor=actor)
        else:
            res = {"moved_to": "dry_run", "decision": "dry_run"}
        mv = res.get("moved_to")
        created += 1 if mv == "goals" else 0
        queued += 1 if mv == "review_queue" else 0
        refused += 1 if mv == "boundary_refused" else 0
        forbidden += 1 if mv == "forbidden" else 0
        item = dict(c)
        item.update(res)
        out.append(item)

    rec = {"type": "goal_gen", "t": time.time(), "apply": bool(apply),
           "actor": actor, "sources": want, "n_candidates": len(out),
           "by_class": by_class, "created": created, "queued": queued,
           "refused": refused, "forbidden": forbidden,
           "candidates": [{"source": c["source"], "goal_text": c["goal_text"],
                           "priority": c["priority"], "class": c["class"],
                           "moved_to": c.get("moved_to")} for c in out]}
    _log(cg, rec)

    return {"ok": True, "action": "generate", "op": "goal",
            "applied": bool(apply), "n_candidates": len(out),
            "by_class": by_class, "created": created, "queued": queued,
            "refused": refused, "forbidden": forbidden,
            "candidates": out}
