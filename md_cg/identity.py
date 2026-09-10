# -*- coding: utf-8 -*-
"""身份特征识别（Identity Traits）——不止「用户画像」，而是「主体身份 × 位置效应 × 条件特征」。

理论出处
--------
· 智能论 v3.4 §十三「五大单元」·位置效应（`docs/智能的公理化基石.md:540-556`）：

      单元        位置效应   核心职责
      记录单元     全        保存观测、过程、结果和误差
      反思单元     新        发现差异、遗漏条件和新路径
      验证单元     稳        判断规则、执行结果和结构是否有效
      输出单元     通        与外部系统协作并表达边界
      维生系统     存        维护存在、预算、回滚和整体结构

  「位置效应」= 主体处在系统什么位置，就承担什么职责、表现出什么特征。
  所以「画像」不该只刻画用户，而应识别**每个主体的身份锚点 + 位置 + 特征**，
  其中也包括智能体自身（self）。

· 扮演论 v3.3（`README.md:231-271`、`docs/tool_table_v0.3.0.md:86-92`）：
  智能即扮演；角色卡 = 条件空间声明起点；三接口 =
      memory（历史 → 知识层）/
      anchor（自我锚点 → SELF 层，不可遗忘）/
      values（特化价值观 → STRUCTURE 层，带条件空间，条件空间即触发时机）。
  边界：角色人设 ≠ 灵枢自身锚点（后者在 self 层，需设计者验证）。

模型
----
    subject = {subject_id, kind, position, anchor, traits}
      subject_id : "self:lingshu" / "user:alice" / "role:whale" / "agent:coder"
      kind       : self | user | role | agent
      position   : record | reflect | verify | output | sustain | unknown
      anchor     : 身份锚点（不可遗忘；kind≠self 一律落 anchor 层）
      traits     : 条件触发的特征条目（条件空间 = 触发时机，带重要度）

诚实边界
--------
· position 是**推断**（`infer_position` 按行为证据投票），返回 confidence / votes /
  证据数，可审计「为什么判成这个位置」，不是事实断言。
· 平票时 position 取 `POSITION_ORDER` 中的首个并置 `tie` 字段提示歧义，不假装唯一。
· 复用 `protect` 写保护：self/anchor 层锚点不可遗忘；
  `role` 主体的锚点不得写入 self 层（扮演论边界）。
"""

import hashlib
import json
import os
import time

from .fsutil import append_jsonl

# 主体类型（扮演论：self=智能体自身 / role=扮演角色 / user=协作者 / agent=其他智能体）
SUBJECT_KIND = ("self", "user", "role", "agent")

# 位置效应（智能论 v3.4 §十三 五大单元）：顺序即平票裁决优先级
POSITIONS = {
    "record": {"unit": "记录单元", "effect": "全",
               "duty": "保存观测、过程、结果和误差"},
    "reflect": {"unit": "反思单元", "effect": "新",
                "duty": "发现差异、遗漏条件和新的路径"},
    "verify": {"unit": "验证单元", "effect": "稳",
                "duty": "判断规则、执行结果和结构是否有效"},
    "output": {"unit": "输出单元", "effect": "通",
               "duty": "与外部系统协作并表达边界"},
    "sustain": {"unit": "维生系统", "effect": "存",
                "duty": "维护存在、预算、回滚和整体结构"},
}
POSITION_ORDER = tuple(POSITIONS)

# 扮演论三接口 → 落层
INTERFACES = {
    "memory": {"layer": "knowledge",
               "meaning": "历史经验 / 交互证据 → 知识层"},
    "anchor": {"layer": "self|anchor",
               "meaning": "身份锚点 → 自我层(self) / 锚点层(其他主体)，不可遗忘"},
    "values": {"layer": "structural",
               "meaning": "特化特征 / 价值观 → 结构层，条件空间即触发时机"},
}

PROFILE_PREFIX = "identity_"
AUDIT_FILE = "_identity.jsonl"

TAG_ANCHOR = "identity_anchor"
TAG_TRAIT = "identity_trait"
TAG_OBS = "identity_observation"

# 位置投票的标签证据（每条都能追溯到五大单元职责）
_POSITION_TAGS = {
    "reflect": {"reflect", "candidate", "hypothesis", "反题", "遗漏条件"},
    "verify": {"verify", "verdict", "裁决", "验证"},
    "output": {"output", "表达", "协作"},
    "sustain": {"goal", "budget", "rollback", "health", "维生"},
}


def split_subject(subject_id):
    """`"self:lingshu"` → `("self", "lingshu")`；无前缀按 `user` 处理。"""
    s = (subject_id or "").strip()
    if ":" in s:
        kind, name = s.split(":", 1)
        kind = kind.strip().lower()
        if kind not in SUBJECT_KIND:
            kind = "user"
        return kind, name.strip()
    return "user", s


def _slug(s):
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in str(s))


def subject_node_id(subject_id):
    """主体的档案节点 id（锚点载体）：`identity_<kind>_<name>`。"""
    kind, name = split_subject(subject_id)
    return f"{PROFILE_PREFIX}{_slug(kind)}_{_slug(name)}"


def _nid(prefix, subject_id, seed=""):
    h = hashlib.sha256(f"{subject_id}|{seed}|{time.time()}".encode("utf-8"))
    return f"{PROFILE_PREFIX}{prefix}_{_slug(subject_id)}_{h.hexdigest()[:10]}"


def log(cg, rec):
    rec = dict(rec)
    rec.setdefault("ts", time.time())
    try:
        append_jsonl(os.path.join(cg.root, AUDIT_FILE), rec)
    except OSError:
        pass


def history(cg, limit=100):
    p = os.path.join(cg.root, AUDIT_FILE)
    out = []
    if not os.path.exists(p):
        return out
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return out
    return out[-int(limit or 100):]


# --------------------------------------------------------------------------
# 扮演论三接口：memory / anchor / values
# --------------------------------------------------------------------------

def observe(cg, subject_id, text, *, kind=None, role=None, layer=None, tags=None,
            condition_space=None, importance=0.5, verification_basis=None,
            evidence=None, node_id=None, override=False):
    """memory 接口：记录一条关于主体的**行为证据**（用于位置推断）。

    写入知识层，自动带 `subject:<id>` 标签，使 `infer_position` 定位到该主体。
    role 兼作来源证据：user=外部协作、command/tool-output=内部执行。
    """
    k, _ = split_subject(subject_id)
    k = (kind or k).strip().lower()
    nid = node_id or _nid("obs", subject_id, text[:32])
    tg = list(tags or []) + [f"subject:{subject_id}", TAG_OBS, f"kind:{k}"]
    if evidence:
        tg.append(f"evidence:{evidence}")
    cs = dict(condition_space or {})
    cs.setdefault("subject", subject_id)
    cs.setdefault("kind", k)
    extra = {"role": role} if role else {}
    cg.add(nid, text, layer=layer or "knowledge", tags=tg, condition_space=cs,
           importance=importance, verification_basis=verification_basis,
           override=override, **extra)
    log(cg, {"op": "observe", "subject": subject_id, "node_id": nid, "role": role,
             "layer": layer or "knowledge"})
    return {"ok": True, "node_id": nid, "subject_id": subject_id, "kind": k}


def set_anchor(cg, subject_id, text, *, kind=None, condition_space=None,
               importance=0.9, override=False, requested_layer=None):
    """anchor 接口：写入身份锚点（不可遗忘）。

    落层规则（扮演论边界）：
      · kind=self  → self 层（智能体自身的自我锚点，需设计者验证）
      · 其他 kind  → anchor 层（角色/用户锚点，仍不可遗忘）
    requested_layer="self" 但 kind≠self → 拒绝（角色人设 ≠ 灵枢自身锚点）。
    """
    k, _ = split_subject(subject_id)
    k = (kind or k).strip().lower()
    if k not in SUBJECT_KIND:
        raise ValueError(f"未知主体类型：{k}（允许：{SUBJECT_KIND}）")
    if requested_layer == "self" and k != "self":
        raise ValueError(
            "扮演论边界：角色/用户锚点不得写入 self 层"
            "（self 层是灵枢自身锚点，需设计者验证）")
    layer = "self" if k == "self" else "anchor"
    nid = subject_node_id(subject_id)
    cs = dict(condition_space or {})
    cs.setdefault("subject", subject_id)
    cs.setdefault("kind", k)
    tg = [f"subject:{subject_id}", TAG_ANCHOR, f"kind:{k}"]
    cg.add(nid, text, layer=layer, tags=tg, condition_space=cs,
           importance=importance, verification_basis="data", override=override)
    log(cg, {"op": "anchor", "subject": subject_id, "node_id": nid,
             "kind": k, "layer": layer, "override": bool(override)})
    return {"ok": True, "node_id": nid, "subject_id": subject_id, "kind": k,
            "layer": layer, "protected": True}


def add_trait(cg, subject_id, trait, *, condition_space=None, importance=0.6,
              position=None, kind=None, verification_basis="data",
              override=False, node_id=None):
    """values 接口：写入条件触发的特征/特化价值观。

    落 STRUCTURE 层；`condition_space` 即触发时机（扮演论：条件空间 = 触发条件）。
    """
    k, _ = split_subject(subject_id)
    k = (kind or k).strip().lower()
    nid = node_id or _nid("trait", subject_id, trait[:24])
    cs = dict(condition_space or {})
    cs.setdefault("subject", subject_id)
    cs.setdefault("kind", k)
    tg = [f"subject:{subject_id}", TAG_TRAIT, f"kind:{k}"]
    if position:
        tg.append(f"position:{position}")
    cg.add(nid, trait, layer="structural", tags=tg, condition_space=cs,
           importance=importance, verification_basis=verification_basis,
           override=override)
    log(cg, {"op": "trait", "subject": subject_id, "node_id": nid,
             "position": position})
    return {"ok": True, "node_id": nid, "subject_id": subject_id, "kind": k,
            "layer": "structural", "condition_space": cs}


# --------------------------------------------------------------------------
# 位置效应推断（智能论 v3.4 §十三）
# --------------------------------------------------------------------------

def _votes(role, layer, tags, vb, ev_pos, ev_neg):
    """把一条行为证据映射到位置效应候选（可多面）。规则可审计、可扩展。"""
    tags = set(tags or [])
    v = set()
    if role in ("command", "tool-output") or layer == "contextual":
        v.add("record")
    for pos, marks in _POSITION_TAGS.items():
        if tags & marks:
            v.add(pos)
    if ev_pos or ev_neg:
        v.add("verify")
    if role in ("user", "assistant") or any(
            isinstance(t, str) and t.startswith("cap:") for t in tags):
        v.add("output")
    if layer == "goals":
        v.add("sustain")
    return v


def infer_position(cg, subject_id):
    """按该主体的行为证据投票推断位置效应（带 confidence / votes，可审计）。

    只统计带 `subject:<id>` 标签、且**非档案节点**（锚点/特征）的证据节点，
    避免档案自证。返回 position=unknown 表示证据不足。
    """
    tag = f"subject:{subject_id}"
    nodes = cg.index.get("nodes") or {}
    votes, n = {}, 0
    for nid, e in nodes.items():
        tg = set(e.get("tags") or [])
        if tag not in tg or (tg & {TAG_ANCHOR, TAG_TRAIT}):
            continue
        node = cg.get(nid) or {}
        fm = node.get("frontmatter") or {}
        n += 1
        for pos in _votes(fm.get("role"), e.get("layer"), e.get("tags"),
                          e.get("verification_basis"), fm.get("positive_evidence"),
                          fm.get("negative_evidence")):
            votes[pos] = votes.get(pos, 0) + 1
    if not votes:
        return {"position": "unknown", "confidence": 0.0, "votes": {},
                "evidence_count": n, "tie": []}
    top = max(votes.values())
    winners = [p for p in POSITION_ORDER if votes.get(p) == top]
    total = sum(votes.values())
    return {"position": winners[0], "confidence": round(top / total, 3),
            "votes": votes, "evidence_count": n,
            "tie": winners if len(winners) > 1 else []}


def _position_view(pos):
    meta = POSITIONS.get(pos) or {}
    return {"position": pos, "unit": meta.get("unit"),
            "effect": meta.get("effect"), "duty": meta.get("duty")}


def profile(cg, subject_id):
    """主体画像 = 身份锚点 + 位置效应 + 条件特征（取代单一「用户画像」）。"""
    k, name = split_subject(subject_id)
    tag = f"subject:{subject_id}"
    nodes = cg.index.get("nodes") or {}
    anchors, traits = [], []
    for nid, e in nodes.items():
        tg = set(e.get("tags") or [])
        if tag not in tg:
            continue
        node = cg.get(nid) or {}
        fm = node.get("frontmatter") or {}
        if TAG_ANCHOR in tg:
            anchors.append({"node_id": nid, "layer": e.get("layer"),
                            "content": (node.get("content") or "")[:400]})
        elif TAG_TRAIT in tg:
            traits.append({"node_id": nid, "layer": e.get("layer"),
                           "content": (node.get("content") or "")[:200],
                           "condition_space": fm.get("condition_space"),
                           "importance": fm.get("importance")})
    pos = infer_position(cg, subject_id)
    out = {"subject_id": subject_id, "kind": k, "name": name,
           "anchor": anchors[0] if anchors else None, "anchors": anchors,
           "traits": traits, "traits_count": len(traits)}
    out.update(_position_view(pos["position"]))
    out.update({"position_confidence": pos["confidence"], "votes": pos["votes"],
                "evidence_count": pos["evidence_count"], "tie": pos["tie"]})
    return out


def positions(cg, limit=0):
    """所有主体的位置效应分布（OS 视角：谁在记录/反思/验证/输出/维生）。"""
    nodes = cg.index.get("nodes") or {}
    counts = {}
    for _nid_, e in nodes.items():
        for t in (e.get("tags") or []):
            if isinstance(t, str) and t.startswith("subject:"):
                sid = t[len("subject:"):]
                counts[sid] = counts.get(sid, 0) + 1
    out = []
    for sid, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        p = infer_position(cg, sid)
        out.append({"subject_id": sid, "kind": split_subject(sid)[0],
                    "nodes": cnt, "position": p["position"],
                    "confidence": p["confidence"], "evidence_count": p["evidence_count"]})
    return out[:int(limit)] if limit and int(limit) > 0 else out


def _audit_count(cg):
    p = os.path.join(cg.root, AUDIT_FILE)
    if not os.path.exists(p):
        return 0
    n = 0
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
    except OSError:
        return n
    return n


def summary(cg):
    """身份面汇总：主体数 + 位置分布（供 health / 运维审计，流式计数不载全量）。"""
    ps = positions(cg)
    dist = {}
    for s in ps:
        dist[s["position"]] = dist.get(s["position"], 0) + 1
    return {"subjects": len(ps), "by_position": dist,
            "audit_records": _audit_count(cg)}


def catalog():
    """自描述：位置效应表 + 三接口（供 MCP / 文档对照协议验证）。"""
    return {"positions": {p: dict(POSITIONS[p]) for p in POSITION_ORDER},
            "interfaces": {k: dict(v) for k, v in INTERFACES.items()},
            "kinds": list(SUBJECT_KIND)}
