# -*- coding: utf-8 -*-
"""md_cg · 自我状态层（SELF STATE）：薄自我 + 富索引

理论约束（本仓已有文档，非外部发明）：
  · `docs/灵枢_自我层定义.md:6`
      SELF 层 = 身份 + 价值观 + 图接口，**不可遗忘**、跨会话自动加载。
      自我层是**薄的**——它不该变成事件仓库。
  · 智能论 §十一：情绪 = 信息差二阶 d^2D/dt^2；§十：P_gap / P_trust；
      情感 = 信任二阶 d^2T/dt^2。

由此定下本模块的形态：

    self 层只放两类一等公民（都很薄）：
      1. 自我状态卡（单例）——九项自我信息的**当前值 + 指针**
      2. 关系节点（有向）——自我与其他智能的关系
    具体细节（哪次会话 / 哪个任务 / 哪个人 / 哪个时间窗 / 哪条证据）
    仍然留在原本的层里，由**认知图的标签与边**连接、索引过来。

九项自我信息 → 薄卡字段 / 富索引指向：

  ┌ 信息差 D   d_current / d1 / d2 / emotion      ← _reflection.jsonl（reflect 留痕）
  ├ 信任 P     p_gap / p_trust / d2t / affect     ← 各节点 evidence_log（verify 留痕）
  ├ 情绪       emotion（= d^2D/dt^2）
  ├ 情感       affect（= d^2T/dt^2）
  ├ 短期记忆   recent{n, span, roles, ptr}        ← _recent.jsonl（只存摘要 + 指针）
  ├ 重要性     importance_self / important_refs   ← 各节点 frontmatter.importance
  ├ 身份       identity_ref                       ← self 层 identity 锚点
  ├ 关系       relations{out,in}                  ← self_relation_* 关系节点
  └ 预测校准   hit_rate / threshold / reflect / ece  ← _prediction.jsonl + evidence_log

第九项（预测校准）是「SELF = 自我描述」走向「SELF = 关于自身的预测模型」的最小一步：
它回答**我预测得准吗、该不该反思**，数据只来自 predict 的 feedback 留痕与
metacognition 的 ECE 校准，样本不足一律 unknown——不新增计算，也不编造。

五个索引维度（「具体任务 / 人物关系 / 会话 / 时间 / 信任」）用 tag 命名空间落地，
`index(cg, dim, value)` 从全图反查；状态卡只登记维度标签、不搬运内容：

    task:<slug>     具体任务
    person:<slug>   具体人物关系
    session:<id>    具体会话
    time:<bucket>   具体时间（YYYY-MM-DD）
    trust:<band>    具体信任档（low | mid | high）

一致性（`audit` 的每条判定都可重算，不依赖人的判断）：

    单例        同一 subject 至多一个状态卡
    版本链      state_version 连续 +1；prev_state_hash 必须等于上一条留痕的 hash
    时序单调    留痕时间戳不得回退
    留痕对齐    卡上的 state_hash 必须等于留痕末条
    派生自洽    d2/d2t 缺失时 emotion/affect 必须是 unknown（不许编造）
    跨面一致    卡值与 metacognition 现算值偏差 ≤ DRIFT_TOL
    身份唯一    identity_ref 必须指向存在的身份锚点
    关系完整    关系两端必须存在；禁止自环
    保护一致    状态卡必须「可覆盖」（否则自我认知被永久冻结）且「不可遗忘」
    索引不悬空  维度标签指向的详情节点必须存在

「不可遗忘 ≠ 不可覆盖」的延伸：
  · 身份锚点：既不可遗忘，也不可覆盖（protect 层保护）；
  · 自我状态卡：**不可遗忘，但必须可覆盖**——自我状态本来就要演化。
    靠 `frontmatter.self_state is True` 在 protect 里获得覆盖豁免，见 protect.py。
"""
import hashlib
import json
import os
import re
import time

from . import identity, metacognition
from .fsutil import append_jsonl, read_jsonl

DEFAULT_SUBJECT = "self:lingshu"
STATE_PREFIX = "self_state_"
RELATION_PREFIX = "self_relation_"
LOG_FILE = "_self_state.jsonl"
TAG_STATE = "self_state"
TAG_RELATION = "self_relation"
SCHEMA_VERSION = 1

# 跨面一致容差：卡里的 D/T 与 metacognition 现算值允许的最大偏差
DRIFT_TOL = 0.05
# 新鲜度：状态卡超过该秒数未刷新即视为 stale
STALE_AFTER = 24 * 3600.0
RECENT_WINDOW = 20

# 五维索引（具体任务 / 人物关系 / 会话 / 时间 / 信任）
DIMENSIONS = ("task", "person", "session", "time", "trust")
TRUST_BANDS = ((0.70, "high"), (0.40, "mid"), (0.00, "low"))
RELATION_TYPES = ("collaborator", "user", "peer", "mentor", "student",
                  "adversary", "tool", "other")
STATE_LINK_TYPE = "refers_to"


# ---------------------------------------------------------------- 基础工具

def _slug(text):
    """归一化 id 片段：保留中英文数字，其余折叠为下划线。"""
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", str(text or ""))
    return s.strip("_").lower()


def _iso(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return ""


def state_node_id(subject=DEFAULT_SUBJECT):
    """状态卡节点 id（单例：同一 subject 只有一个）。"""
    return STATE_PREFIX + _slug(subject)


def relation_node_id(frm, to):
    """关系节点 id（有向）。"""
    return f"{RELATION_PREFIX}{_slug(frm)}__{_slug(to)}"


def log_path(cg):
    return os.path.join(cg.root, LOG_FILE)


def dim_tag(dim, value):
    return f"{dim}:{_slug(value)}"


def trust_band(p_trust):
    """把 P_trust 映射到信任档（索引维度之一）。"""
    if p_trust is None:
        return None
    try:
        v = float(p_trust)
    except (TypeError, ValueError):
        return None
    for lo, name in TRUST_BANDS:
        if v >= lo:
            return name
    return "low"


# ---------------------------------------------------------------- 留痕

def _append_log(cg, rec):
    try:
        append_jsonl(log_path(cg), rec)
    except OSError:
        pass


def history(cg, limit=100, subject=None):
    """自我状态留痕（倒序）。"""
    try:
        recs = list(read_jsonl(log_path(cg)))
    except OSError:
        recs = []
    if subject:
        recs = [r for r in recs if r.get("subject") == subject]
    recs.reverse()
    return recs[:int(limit)] if limit else recs


def _last_log(cg, subject=None):
    recs = history(cg, limit=0, subject=subject)
    return recs[0] if recs else None


# ---------------------------------------------------------------- 读卡

def _node(cg, node_id):
    try:
        return cg.get(node_id)
    except Exception:
        return None


def _fm_of(cg, node_id):
    node = _node(cg, node_id)
    return (node or {}).get("frontmatter") or {}


def _entry(cg, node_id):
    return ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id)


def snapshot(cg, subject=DEFAULT_SUBJECT):
    """读当前状态卡 → 扁平 dict（不存在返回 None）。只读，不写盘。"""
    nid = state_node_id(subject)
    if _entry(cg, nid) is None:
        return None
    fm = _fm_of(cg, nid)
    if not fm:
        return None
    out = {"node_id": nid, "subject": fm.get("state_subject") or subject,
           "layer": "self", "state_version": fm.get("state_version"),
           "state_hash": fm.get("state_hash"),
           "prev_state_hash": fm.get("prev_state_hash"),
           "state_ts": fm.get("state_ts"),
           "updated_at": _iso(fm.get("state_ts"))}
    for key in ("information_gap", "trust", "short_term", "relations",
                "prediction", "dimensions", "emotion", "affect",
                "importance_self", "important_refs", "identity_ref",
                "state_links"):
        out[key] = fm.get(key)
    out["d_current"] = (fm.get("information_gap") or {}).get("d_current")
    out["p_trust"] = (fm.get("trust") or {}).get("p_trust")
    return out


def _fingerprint(state):
    """状态指纹：只对「会漂移的实质字段」取哈希，用于幂等刷新与版本链。

    注意：**不含 state_version**——版本号是元数据，若纳入指纹则每次刷新
    指纹必变，幂等判断失效（自我状态会在无信息变化时无限刷版本）。
    """
    core = {
        "subject": state.get("subject"),
        "information_gap": state.get("information_gap"),
        "trust": state.get("trust"),
        "emotion": state.get("emotion"),
        "affect": state.get("affect"),
        "importance_self": state.get("importance_self"),
        "important_refs": state.get("important_refs"),
        "identity_ref": state.get("identity_ref"),
        "short_term": state.get("short_term"),
        "relations": state.get("relations"),
        "prediction": state.get("prediction"),
        "dimensions": state.get("dimensions"),
        "state_links": state.get("state_links"),
    }
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- 聚合（九项）

def _prediction_face(cg):
    """预测校准（第九项）：我预测得准吗、该不该反思？

    数据源（只读留痕，不新增计算负担）：
      · `predict._hit_history` / `predict.dynamic_hit_threshold`
        ← `_prediction.jsonl`（predict_feedback 留痕）
      · `metacognition.calibration` ← evidence_log（verify 留痕）的 ECE

    诚实边界：无预测留痕 → ok=False、hit_rate=None（未知即未知）；
    ECE 仅在 metacognition 有足够证据时给出，否则 None。绝不编造。
    """
    try:
        from . import predict as _predict
        hist = list(_predict._hit_history(cg))
        th = _predict.dynamic_hit_threshold(cg)
    except Exception:                                      # noqa: BLE001
        hist, th = [], {}
    samples = len(hist)
    hit_rate = (sum(1 for x in hist if x) / samples) if samples else None
    try:
        cal = metacognition.calibration(cg)
    except Exception:                                      # noqa: BLE001
        cal = {}
    if samples == 0:
        note = "无预测留痕：先 predict_feedback() 积累命中记录"
    elif th.get("reflect"):
        note = "命中率低于动态阈值：建议反思（D-006）"
    else:
        note = "命中率正常"
    return {
        "ok": samples > 0,
        "samples": samples,
        "hit_rate": None if hit_rate is None else round(hit_rate, 4),
        "threshold": th.get("threshold"),
        "reflect": bool(th.get("reflect")),
        "ece": cal.get("ece") if cal.get("ok") else None,
        "calibration": cal.get("verdict") if cal.get("ok") else None,
        "note": note,
    }


def _recent_summary(cg, window):
    """短期记忆：只做窗口摘要，原文仍留在 _recent.jsonl（薄自我的关键取舍）。"""
    try:
        recs = cg.recent_events(limit=int(window), newest_first=False)
    except Exception:
        recs = []
    ts = [float(r.get("t") or 0.0) for r in recs]
    roles = {}
    for r in recs:
        k = str(r.get("role") or "unknown")
        roles[k] = roles.get(k, 0) + 1
    return {"n": len(recs), "span": [min(ts), max(ts)] if ts else None,
            "roles": roles,
            "ptr": os.path.basename(getattr(cg, "recent_log", "_recent.jsonl"))}


def _identity_ref(cg, subject):
    """身份：只存指针（锚点节点 id），锚点内容仍在 self 层原节点里。"""
    try:
        prof = identity.profile(cg, subject)
    except Exception:
        return None, 0
    anchors = prof.get("anchors") or []
    ref = (prof.get("anchor") or {}).get("node_id")
    return ref, len(anchors)


def _relation_counts(cg, subject):
    """关系：从索引里的关系节点统计出/入度（不读文件正文）。"""
    slug = _slug(subject)
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    out = inn = 0
    for nid, e in nodes.items():
        tags = set(e.get("tags") or [])
        if TAG_RELATION not in tags and not nid.startswith(RELATION_PREFIX):
            continue
        if f"rel_from:{slug}" in tags:
            out += 1
        if f"rel_to:{slug}" in tags:
            inn += 1
    return {"out": out, "in": inn}


def _normalize_dimensions(dimensions):
    """维度入参 → {dim: [value...]}（只保留已知维度）。"""
    out = {}
    for dim, val in (dimensions or {}).items():
        d = str(dim).strip().lower()
        if d not in DIMENSIONS or val is None:
            continue
        vals = val if isinstance(val, (list, tuple, set)) else [val]
        clean = [str(v).strip() for v in vals if str(v).strip()]
        if clean:
            out.setdefault(d, [])
            for v in clean:
                if v not in out[d]:
                    out[d].append(v)
    return out


def _derive(cg, subject, window, importance, important_refs, dimensions,
            links, old):
    """聚合九项自我信息 → 薄状态（纯读，不写盘）。"""
    tr = metacognition.trace(cg, window=max(2, int(window)))
    tt = metacognition.trust(cg, window=max(3, int(window)))
    d2 = tr.get("d2") if tr.get("ok") else None
    d2t = tt.get("d2") if tt.get("ok") else None
    # 派生自洽：无数据即 unknown，绝不编造
    emotion = tr.get("emotion") if (tr.get("ok") and d2 is not None) else "unknown"
    affect = tt.get("emotion") if (tt.get("ok") and d2t is not None) else "unknown"

    information_gap = {"ok": bool(tr.get("ok")), "n": tr.get("n", 0),
                       "d_current": tr.get("d_current"), "d1": tr.get("d1"),
                       "d2": d2, "trend": tr.get("trend")}
    trust = {"ok": bool(tt.get("ok")), "n_events": tt.get("n_events", 0),
             "p_gap": tt.get("p_gap"), "p_trust": tt.get("p_trust"),
             "d1": tt.get("d1"), "d2t": d2t,
             "band": trust_band(tt.get("p_trust"))}
    short_term = _recent_summary(cg, window)
    identity_ref, n_anchors = _identity_ref(cg, subject)
    relations = _relation_counts(cg, subject)

    if importance is None:
        importance = (old or {}).get("importance_self")
    importance = 1.0 if importance is None else float(importance)
    if important_refs is None:
        important_refs = list((old or {}).get("important_refs") or [])
    important_refs = [str(x) for x in important_refs if str(x).strip()]

    dims = _normalize_dimensions(dimensions)
    if not dims:
        dims = dict((old or {}).get("dimensions") or {})
    # 信任档与时间桶自动入索引（用户点名的「具体信任」「具体时间」）
    if trust["band"]:
        dims.setdefault("trust", [])
        if trust["band"] not in dims["trust"]:
            dims["trust"].append(trust["band"])
    today = time.strftime("%Y-%m-%d", time.localtime())
    dims.setdefault("time", [])
    if today not in dims["time"]:
        dims["time"].append(today)

    if links is None:
        links = list((old or {}).get("state_links") or [])

    return {"subject": subject, "information_gap": information_gap,
            "trust": trust, "emotion": emotion, "affect": affect,
            "short_term": short_term, "importance_self": importance,
            "important_refs": important_refs, "identity_ref": identity_ref,
            "identity_anchors": n_anchors, "relations": relations,
            "prediction": _prediction_face(cg),
            "dimensions": dims,
            "state_links": [str(x) for x in links if str(x).strip()]}


# ---------------------------------------------------------------- 写卡

def _render(state):
    """状态卡正文：人类可读，且与 frontmatter 字段一一对应。"""
    ig, tt = state["information_gap"], state["trust"]
    st = state["short_term"]
    pd = state.get("prediction") or {}
    dims = state["dimensions"]
    span = st.get("span")
    span_txt = f"{_iso(span[0])} ~ {_iso(span[1])}" if span else "（无）"
    roles = "、".join(f"{k}:{v}" for k, v in
                     sorted((st.get("roles") or {}).items())) or "（无）"
    lines = [
        f"# 自我状态卡 · {state['subject']}",
        f"# 更新时间：{_iso(state.get('state_ts'))}"
        f"（version={state.get('state_version')}）",
        f"# 信息差：D={ig.get('d_current')} dD/dt={ig.get('d1')} "
        f"d^2D/dt^2={ig.get('d2')} → 情绪={state['emotion']}"
        f"（趋势={ig.get('trend')}）",
        f"# 信任：P_gap={tt.get('p_gap')} P_trust={tt.get('p_trust')} "
        f"d^2T/dt^2={tt.get('d2t')} → 情感={state['affect']}"
        f"（档={tt.get('band')}）",
        f"# 短期记忆：{st.get('n')} 条（{span_txt}）角色 {roles}；"
        f"原文见 {st.get('ptr')}",
        f"# 重要性：self={state['importance_self']}，"
        f"显式重要 {len(state.get('important_refs') or [])} 条",
        f"# 身份：锚点 {state.get('identity_ref') or '（未设）'}"
        f"（共 {state.get('identity_anchors')} 条）",
        f"# 关系：出 {state['relations'].get('out')} / "
        f"入 {state['relations'].get('in')}",
        f"# 预测：命中率={pd.get('hit_rate')}（样本 {pd.get('samples')}）"
        f"阈值={pd.get('threshold')} 反思={'是' if pd.get('reflect') else '否'}"
        f"；ECE={pd.get('ece')}（{pd.get('calibration')}）",
        "# 索引：" + "；".join(
            f"{d}={','.join(dims.get(d) or []) or '-'}" for d in DIMENSIONS),
        "# 说明：本卡是薄自我——只登记当前值与指针；具体任务/人物/会话/"
        "时间/信任的细节由认知图按上述索引连接，不在此搬运。",
    ]
    return "\n".join(lines) + "\n"


def refresh(cg, subject=DEFAULT_SUBJECT, window=RECENT_WINDOW, importance=None,
            important_refs=None, dimensions=None, links=None,
            actor="self_state", force=False, strict=False, session=None):
    """刷新自我状态卡（幂等）：聚合九项 → 写卡 + 版本链留痕。

    dimensions: {"task": "...", "person": "...", "session": "...",
                 "time": "...", "trust": "..."}（值可为列表）
    links:      指向具体详情节点的边（认知图连接，而非内容复制）
    strict:     版本链断裂时是否拒绝写入（默认修复并记录 chain_repaired）
    session:    会话归因（嵌套身份）：并入 session 维度，不覆盖显式声明值
    """
    raw = snapshot(cg, subject)
    tail = _last_log(cg, subject=subject)
    # 卡缺失 / 被绕过 refresh 破坏（版本或 hash 对不上留痕）→ 以 append-only
    # 留痕为准恢复元数据（维度索引、重要性、边）。留痕是权威记录。
    old, rebuild = raw, False
    if tail and (raw is None or raw.get("state_version") is None
                 or raw.get("state_hash") != tail.get("state_hash")):
        rebuild = True
        old = {"state_version": tail.get("version"),
               "state_hash": tail.get("state_hash"),
               "dimensions": tail.get("dimensions"),
               "importance_self": tail.get("importance_self"),
               "important_refs": tail.get("important_refs"),
               "state_links": tail.get("state_links"),
               "identity_ref": tail.get("identity_ref")}
    # 会话归因：把本会话并入 session 维度（不覆盖调用方显式声明的维度值）。
    dims_in = dict(dimensions or {})
    if session:
        vals = dims_in.get("session") or []
        vals = list(vals) if isinstance(vals, (list, tuple, set)) else [vals]
        vals = [str(v) for v in vals if str(v).strip()]
        if str(session) not in vals:
            vals.append(str(session))
        dims_in["session"] = vals
    state = _derive(cg, subject, window=window, importance=importance,
                    important_refs=important_refs, dimensions=dims_in,
                    links=links, old=old)
    card_v = int((old or {}).get("state_version") or 0)
    log_v = int(tail.get("version") or 0) if tail else 0
    version = max(card_v, log_v) + 1
    state["state_version"] = version
    fp = _fingerprint(state)
    if not rebuild and old and old.get("state_hash") == fp and not force:
        return {"ok": True, "changed": False, "subject": subject,
                "node_id": state_node_id(subject), "state": state,
                "note": "状态未变化，跳过写入（幂等）"}

    # 版本链：prev 必须等于上一条留痕的 hash
    prev_hash = (raw or {}).get("state_hash")
    chain_issue = None
    if tail is not None and prev_hash != tail.get("state_hash"):
        chain_issue = {
            "code": "chain_repaired",
            "why": f"prev_state_hash={prev_hash} 与留痕末条 "
                   f"{tail.get('state_hash')} 不一致"}
        if strict:
            return {"ok": False, "changed": False, "subject": subject,
                    "error": "chain_broken", "detail": chain_issue}
        prev_hash = tail.get("state_hash")   # 以留痕为准修复
    if raw is None and tail is not None:
        chain_issue = {"code": "state_rebuilt",
                       "why": "状态卡缺失但留痕存在，按留痕续链重建"}
        prev_hash = tail.get("state_hash")

    state["prev_state_hash"] = prev_hash
    state["state_ts"] = time.time()
    state["state_hash"] = _fingerprint(state)

    tags = [TAG_STATE, f"state_subject:{_slug(subject)}"]
    for d in DIMENSIONS:
        for v in (state["dimensions"].get(d) or []):
            t = dim_tag(d, v)
            if t not in tags:
                tags.append(t)
    edges = [{"target": t, "relation_type": STATE_LINK_TYPE,
              "weight": 0.6} for t in state["state_links"]]

    nid = state_node_id(subject)
    cg.add(nid, _render(state), layer="self", tags=tags, edges=edges,
           importance=float(state["importance_self"]), confidence=0.9,
           verification_basis="data", override=True, actor=actor,
           self_state=True, state_subject=subject, state_version=version,
           state_hash=state["state_hash"], prev_state_hash=prev_hash,
           state_ts=state["state_ts"],
           information_gap=state["information_gap"], trust=state["trust"],
           emotion=state["emotion"], affect=state["affect"],
           short_term=state["short_term"],
           importance_self=state["importance_self"],
           important_refs=state["important_refs"],
           identity_ref=state["identity_ref"], relations=state["relations"],
           prediction=state["prediction"],
           dimensions=state["dimensions"], state_links=state["state_links"])

    _append_log(cg, {
        "t": state["state_ts"], "subject": subject, "node_id": nid,
        "version": version, "state_hash": state["state_hash"],
        "prev_state_hash": prev_hash, "actor": actor,
        "d_current": state["information_gap"].get("d_current"),
        "d1": state["information_gap"].get("d1"),
        "d2": state["information_gap"].get("d2"),
        "emotion": state["emotion"],
        "p_gap": state["trust"].get("p_gap"),
        "p_trust": state["trust"].get("p_trust"),
        "d2t": state["trust"].get("d2t"), "affect": state["affect"],
        "importance_self": state["importance_self"],
        "important_refs": state["important_refs"],
        "state_links": state["state_links"],
        "recent_n": state["short_term"].get("n"),
        "identity_ref": state["identity_ref"],
        "relations": state["relations"],
        "prediction_hit_rate": (state.get("prediction") or {}).get("hit_rate"),
        "prediction_samples": (state.get("prediction") or {}).get("samples"),
        "prediction_reflect": (state.get("prediction") or {}).get("reflect"),
        "dimensions": state["dimensions"], "issue": chain_issue})
    return {"ok": True, "changed": True, "subject": subject, "node_id": nid,
            "state_version": version, "state_hash": state["state_hash"],
            "prev_state_hash": prev_hash, "state": state,
            "issue": chain_issue}


# ---------------------------------------------------------------- 关系

def relate(cg, frm, to, relation_type="collaborator", strength=0.5,
           condition="", note="", reciprocal=False, actor="self_state"):
    """写一条有向关系（自我 ↔ 其他智能）。reciprocal=True 时同时写反向。"""
    rt = str(relation_type or "other").strip().lower()
    if rt not in RELATION_TYPES:
        rt = "other"
    if _slug(frm) == _slug(to):
        return {"ok": False, "error": "self_loop",
                "detail": "关系两端不能是同一主体（自环）"}
    try:
        w = max(0.0, min(1.0, float(strength)))
    except (TypeError, ValueError):
        w = 0.5
    written = []
    for a, b in ((frm, to), (to, frm)) if reciprocal else ((frm, to),):
        nid = relation_node_id(a, b)
        tags = [TAG_RELATION, f"rel_from:{_slug(a)}", f"rel_to:{_slug(b)}",
                f"relation:{rt}", f"person:{_slug(b)}",
                f"state_subject:{_slug(a)}"]
        body = (f"# 关系：{a} → {b}\n"
                f"# 类型：{rt}\n"
                f"# 强度：{w}\n"
                f"# 条件：{condition or '（未声明）'}\n"
                f"# 备注：{note or '（无）'}\n")
        cg.add(nid, body, layer="self", tags=tags,
               edges=[{"target": b, "relation_type": rt, "weight": w,
                       "condition": condition}],
               importance=w, confidence=0.8, verification_basis="other",
               override=True, actor=actor,
               self_relation=True, rel_from=a, rel_to=b,
               relation_type=rt, strength=w, condition=condition,
               reciprocal=bool(reciprocal))
        written.append(nid)
    return {"ok": True, "written": written, "from": frm, "to": to,
            "relation_type": rt, "strength": w,
            "reciprocal": bool(reciprocal)}


def relations(cg, subject=None, direction="both"):
    """列出关系节点（按 subject 过滤出/入）。"""
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    slug = _slug(subject) if subject else None
    out = []
    for nid, e in nodes.items():
        tags = set(e.get("tags") or [])
        if TAG_RELATION not in tags and not nid.startswith(RELATION_PREFIX):
            continue
        if slug:
            is_out = f"rel_from:{slug}" in tags
            is_in = f"rel_to:{slug}" in tags
            if direction == "out" and not is_out:
                continue
            if direction == "in" and not is_in:
                continue
            if direction == "both" and not (is_out or is_in):
                continue
        rels = [t[len("relation:"):] for t in tags if t.startswith("relation:")]
        frm = [t[len("rel_from:"):] for t in tags if t.startswith("rel_from:")]
        to = [t[len("rel_to:"):] for t in tags if t.startswith("rel_to:")]
        out.append({"node_id": nid, "from": frm[0] if frm else None,
                    "to": to[0] if to else None,
                    "relation_type": rels[0] if rels else None,
                    "strength": e.get("importance"),
                    "layer": e.get("layer")})
    out.sort(key=lambda x: (-float(x.get("strength") or 0), x["node_id"]))
    return out


# ---------------------------------------------------------------- 索引

def index(cg, dim, value, limit=50, with_content=False):
    """按五维索引反查具体详情节点（认知图连接，不是内容搬运）。"""
    d = str(dim or "").strip().lower()
    if d not in DIMENSIONS:
        return {"ok": False, "error": "unknown_dimension",
                "allowed": list(DIMENSIONS)}
    tag = dim_tag(d, value)
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    hits = [(nid, e) for nid, e in nodes.items()
            if tag in (e.get("tags") or [])]
    hits.sort(key=lambda kv: (-float(kv[1].get("importance") or 0),
                              -float(kv[1].get("created_at") or 0)))
    items = []
    for nid, e in hits[:int(limit)]:
        item = {"node_id": nid, "layer": e.get("layer"),
                "importance": e.get("importance"), "tags": e.get("tags"),
                "path": e.get("path")}
        if with_content:
            node = _node(cg, nid) or {}
            item["content"] = (node.get("content") or "")[:400]
        items.append(item)
    return {"ok": True, "dimension": d, "value": str(value), "tag": tag,
            "count": len(hits), "items": items}


def dimensions(cg, subject=DEFAULT_SUBJECT):
    """状态卡登记的五维索引标签。"""
    st = snapshot(cg, subject)
    if not st:
        return {"ok": False, "error": "no_state", "subject": subject}
    return {"ok": True, "subject": subject,
            "dimensions": st.get("dimensions") or {}}


# ---------------------------------------------------------------- 审计

def _issue(code, severity, why, **extra):
    d = {"code": code, "severity": severity, "why": why}
    d.update(extra)
    return d


def audit(cg, subject=DEFAULT_SUBJECT, window=RECENT_WINDOW):
    """自我信息一致性审计：全部判定可重算（不依赖人的判断）。"""
    from . import protect as _protect
    issues = []
    nid = state_node_id(subject)
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    st = snapshot(cg, subject)

    # 1 单例：同 subject 的状态卡只能有一张
    slug = _slug(subject)
    cards = [n for n, e in nodes.items()
             if TAG_STATE in (e.get("tags") or [])
             and f"state_subject:{slug}" in (e.get("tags") or [])]
    if len(cards) > 1:
        issues.append(_issue("duplicate_state", "error",
                             f"同一 subject 有 {len(cards)} 张状态卡",
                             nodes=cards))
    if st is None:
        issues.append(_issue("missing_state", "warn",
                             "状态卡不存在：先 refresh() 建立", node_id=nid))
        return {"ok": False, "verdict": "absent", "subject": subject,
                "n_issues": len(issues), "issues": issues,
                "checked_at": time.time()}

    ordered = list(reversed(history(cg, limit=0, subject=subject)))

    # 2 版本链：version 连续 +1，prev 必须等于上一条 hash
    for i in range(1, len(ordered)):
        p, c = ordered[i - 1], ordered[i]
        if c.get("version") != (p.get("version") or 0) + 1:
            issues.append(_issue(
                "version_gap", "error",
                f"版本不连续：{p.get('version')} → {c.get('version')}",
                at=c.get("t")))
        if c.get("prev_state_hash") != p.get("state_hash"):
            issues.append(_issue(
                "chain_broken", "error",
                f"留痕断链：prev={c.get('prev_state_hash')} ≠ 上一条 "
                f"{p.get('state_hash')}", at=c.get("t")))
        if float(c.get("t") or 0) < float(p.get("t") or 0):
            issues.append(_issue("time_regression", "error",
                                 "留痕时间戳回退", at=c.get("t")))

    # 3 留痕对齐：卡上的 hash 必须等于留痕末条
    if ordered:
        tail = ordered[-1]
        if st.get("state_hash") != tail.get("state_hash"):
            issues.append(_issue(
                "log_tail_mismatch", "error",
                f"卡 hash={st.get('state_hash')} ≠ 留痕末条 "
                f"{tail.get('state_hash')}（卡被绕过 refresh 改过？）",
                node_id=nid))

    # 4 派生自洽：无数据时必须 unknown（不许编造）
    ig = st.get("information_gap") or {}
    tt = st.get("trust") or {}
    if ig.get("d2") is None and st.get("emotion") not in (None, "unknown"):
        issues.append(_issue("fabricated_emotion", "error",
                             f"d^2D/dt^2 缺失但 emotion={st.get('emotion')}"))
    if tt.get("d2t") is None and st.get("affect") not in (None, "unknown"):
        issues.append(_issue("fabricated_affect", "error",
                             f"d^2T/dt^2 缺失但 affect={st.get('affect')}"))

    # 5 跨面一致：与 metacognition 现算值比对（drift）
    now = _derive(cg, subject, window=window, importance=None,
                  important_refs=None, dimensions=None, links=None, old=None)
    for name, old_v, new_v in (
            ("d_current", ig.get("d_current"),
             now["information_gap"].get("d_current")),
            ("d2", ig.get("d2"), now["information_gap"].get("d2")),
            ("p_trust", tt.get("p_trust"), now["trust"].get("p_trust")),
            ("d2t", tt.get("d2t"), now["trust"].get("d2t"))):
        if old_v is None and new_v is None:
            continue
        try:
            if old_v is None or new_v is None or \
                    abs(float(old_v) - float(new_v)) > DRIFT_TOL:
                issues.append(_issue(
                    "drift", "warn",
                    f"{name} 卡值={old_v} 现算={new_v}（容差 {DRIFT_TOL}）",
                    field=name))
        except (TypeError, ValueError):
            issues.append(_issue("drift", "warn",
                                 f"{name} 不可比较：{old_v} vs {new_v}",
                                 field=name))

    # 5b 预测面漂移：预测能力（命中率）随 predict_feedback 演化；卡值过时即为
    #    漂移——这是「自我模型是否跟上自身预测表现」的可重算判定。
    pd_old = st.get("prediction") or {}
    pd_new = now.get("prediction") or {}
    o_hr, n_hr = pd_old.get("hit_rate"), pd_new.get("hit_rate")
    if not (o_hr is None and n_hr is None):
        try:
            if o_hr is None or n_hr is None or \
                    abs(float(o_hr) - float(n_hr)) > DRIFT_TOL:
                issues.append(_issue(
                    "prediction_drift", "warn",
                    f"预测命中率 卡值={o_hr} 现算={n_hr}（容差 {DRIFT_TOL}）",
                    field="hit_rate"))
        except (TypeError, ValueError):
            issues.append(_issue("prediction_drift", "warn",
                                 f"预测命中率不可比较：{o_hr} vs {n_hr}",
                                 field="hit_rate"))

    # 6 身份唯一：identity_ref 必须指向存在的锚点
    ref = st.get("identity_ref")
    if not ref:
        issues.append(_issue("identity_missing", "info",
                             "identity_ref 为空：先在 self 层写身份锚点"))
    elif ref not in nodes:
        issues.append(_issue("identity_dangling", "error",
                             f"identity_ref={ref} 指向不存在的节点", ref=ref))

    # 7 关系完整：禁止自环、禁止同一有向对重复
    seen_rel = {}
    for rel in relations(cg, subject=None):
        nid_r = rel["node_id"]
        if rel["from"] == rel["to"]:
            issues.append(_issue("relation_self_loop", "error",
                                 f"关系自环：{rel['from']}", node_id=nid_r))
        key = (rel["from"], rel["to"])
        if key in seen_rel:
            issues.append(_issue("duplicate_relation", "error",
                                 f"重复关系 {key}", node_id=nid_r))
        seen_rel[key] = nid_r

    # 8 保护一致：状态卡必须可覆盖（否则自我认知被永久冻结）且不可遗忘
    try:
        imm, why = _protect.is_immutable(cg, nid)
        if imm:
            issues.append(_issue("protection_locked", "error",
                                 f"状态卡不可覆盖：{why}（自我状态将无法演化）"))
        pro, _ = _protect.is_protected(cg, nid)
        if not pro:
            issues.append(_issue("protection_missing", "warn",
                                 "状态卡未受保护：自我信息可能被遗忘"))
    except Exception as exc:                                  # pragma: no cover
        issues.append(_issue("protection_check_failed", "warn", str(exc)))

    # 9 索引不悬空：维度标签指向的详情节点必须存在
    dims = st.get("dimensions") or {}
    for d, vals in dims.items():
        if d not in DIMENSIONS:
            issues.append(_issue("unknown_dimension", "warn",
                                 f"未知索引维度 {d}"))
            continue
        for v in (vals or []):
            tag = dim_tag(d, v)
            holders = [n for n, e in nodes.items()
                       if tag in (e.get("tags") or [])]
            if not holders:
                issues.append(_issue("dimension_orphan", "warn",
                                     f"索引 {tag} 无对应节点（悬空索引）",
                                     dimension=d, value=v))

    # 10 新鲜度
    try:
        age = time.time() - float(st.get("state_ts") or 0)
        if age > STALE_AFTER:
            issues.append(_issue("stale", "warn",
                                 f"状态卡 {age / 3600:.1f} 小时未刷新"))
    except (TypeError, ValueError):
        issues.append(_issue("stale", "warn", "state_ts 不可解析"))

    errors = [i for i in issues if i["severity"] == "error"]
    warns = [i for i in issues if i["severity"] == "warn"]
    verdict = "broken" if errors else ("drift" if warns else "consistent")
    return {"ok": not errors, "verdict": verdict, "subject": subject,
            "node_id": nid, "n_issues": len(issues),
            "n_errors": len(errors), "issues": issues,
            "state_version": st.get("state_version"),
            "state_hash": st.get("state_hash"), "checked_at": time.time()}


# ---------------------------------------------------------------- 加载 / 概览

def bootstrap(cg, subject=DEFAULT_SUBJECT, window=RECENT_WINDOW,
              auto_refresh=True, actor="bootstrap"):
    """会话启动：加载自我状态卡 + 关系 + 最近留痕 + 索引概览。

    这是「跨会话自动加载自我」的入口：self 层薄卡 + 认知图连接。
    """
    st = snapshot(cg, subject)
    if st is None and auto_refresh:
        refresh(cg, subject, window=window, actor=actor)
        st = snapshot(cg, subject)
    elif st is not None and auto_refresh:
        # 只在漂移或过期时刷新，避免每次启动都写盘
        try:
            age = time.time() - float(st.get("state_ts") or 0)
        except (TypeError, ValueError):
            age = STALE_AFTER + 1
        if age > STALE_AFTER:
            refresh(cg, subject, window=window, actor=actor)
            st = snapshot(cg, subject)
    rels = relations(cg, subject=subject)
    return {"ok": st is not None, "subject": subject, "state": st,
            "relations": rels, "relations_count": len(rels),
            "recent_states": history(cg, limit=5, subject=subject),
            "dimensions": (st or {}).get("dimensions") or {},
            "loaded_at": time.time()}


def _with_session_slice(cg, out, st, session):
    """给 summary 结果补「本会话切片」（薄卡 + 富索引，不改单例语义）。

    · session_registered —— 本会话是否已登记在该状态卡的 session 维度上；
    · session_refs       —— 该维度反查到的详情节点指针（不搬运内容）。
    """
    if not session:
        return out
    s = str(session)
    out["session"] = s
    dims = (st or {}).get("dimensions") or {}
    out["session_registered"] = bool(s in (dims.get("session") or []))
    try:
        res = index(cg, "session", s, limit=20)
        out["session_refs"] = {"count": res.get("count", 0),
                               "items": res.get("items", [])}
    except Exception:                          # noqa: BLE001
        out["session_refs"] = {"count": 0, "items": [], "degraded": True}
    return out


def summary(cg, subject=DEFAULT_SUBJECT, session=None):
    """一句话自我状态（供 health / 面板）。

    session：会话归因切片。**不改变单例卡语义**——只回报「本会话是否已登记在
    该卡的 session 维度上」以及该维度反查到的详情节点指针（薄卡 + 富索引）。
    """
    st = snapshot(cg, subject)
    if not st:
        return _with_session_slice(cg, {"ok": False, "subject": subject,
                                        "note": "无状态卡"}, st, session)
    ig, tt = st.get("information_gap") or {}, st.get("trust") or {}
    out = {"ok": True, "subject": subject,
            "version": st.get("state_version"),
            "updated_at": st.get("updated_at"),
            "d_current": ig.get("d_current"), "d2": ig.get("d2"),
            "emotion": st.get("emotion"),
            "p_trust": tt.get("p_trust"), "d2t": tt.get("d2t"),
            "affect": st.get("affect"),
            "trust_band": tt.get("band"),
            "recent_n": (st.get("short_term") or {}).get("n"),
            "relations": st.get("relations"),
            "identity_ref": st.get("identity_ref"),
            "hit_rate": (st.get("prediction") or {}).get("hit_rate"),
            "prediction_reflect": (st.get("prediction") or {}).get("reflect"),
            "text": (f"[{subject}] D={ig.get('d_current')} "
                     f"情绪={st.get('emotion')} P_trust={tt.get('p_trust')} "
                     f"情感={st.get('affect')} "
                     f"短期={((st.get('short_term') or {}).get('n'))}条 "
                     f"v{st.get('state_version')}")}
    return _with_session_slice(cg, out, st, session)


def catalog():
    """自描述：九项自我信息 + 五维索引 + 审计规则（供协议对照验证）。"""
    return {
        "module": "self_state",
        "schema": SCHEMA_VERSION,
        "default_subject": DEFAULT_SUBJECT,
        "log": LOG_FILE,
        "principles": [
            "self 层是薄的：只放状态卡（单例）与关系节点，不搬运内容",
            "具体细节留在原层，由认知图的标签/边按五维索引连接过来",
            "不可遗忘 ≠ 不可覆盖：状态卡可演化，身份锚点两者皆禁",
        ],
        "self_info": {
            "information_gap": "D/d1/d2 + emotion ← _reflection.jsonl",
            "trust": "p_gap/p_trust + d2t/affect ← evidence_log",
            "emotion": "d^2D/dt^2（信息差二阶）",
            "affect": "d^2T/dt^2（信任二阶）",
            "short_term": "窗口摘要 + 指针 ← _recent.jsonl",
            "importance": "importance_self + important_refs",
            "identity": "identity_ref → self 层身份锚点",
            "relations": "self_relation_* 有向关系节点",
            "prediction": "hit_rate/threshold/reflect + ECE ← _prediction.jsonl",
        },
        "dimensions": list(DIMENSIONS),
        "trust_bands": [b for _lo, b in TRUST_BANDS],
        "relation_types": list(RELATION_TYPES),
        "audit_rules": [
            "duplicate_state", "version_gap", "chain_broken",
            "time_regression", "log_tail_mismatch", "fabricated_emotion",
            "fabricated_affect", "drift", "prediction_drift",
            "identity_missing",
            "identity_dangling", "relation_self_loop", "duplicate_relation",
            "protection_locked", "protection_missing", "unknown_dimension",
            "dimension_orphan", "stale", "missing_state",
        ],
        "tolerances": {"drift": DRIFT_TOL, "stale_after_sec": STALE_AFTER},
    }
