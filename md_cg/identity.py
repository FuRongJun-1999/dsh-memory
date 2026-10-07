# -*- coding: utf-8 -*-
"""身份特征识别（Identity Traits）——不止「用户画像」，而是「主体身份 × 位置效应 × 条件特征」。

理论出处
--------
· 智能论 v3.4 §十三「五大单元」·位置效应（`docs/theory/智能的公理化基石.md:540-556`）：

      单元        位置效应   核心职责
      记录单元     全        保存观测、过程、结果和误差
      反思单元     新        发现差异、遗漏条件和新路径
      验证单元     稳        判断规则、执行结果和结构是否有效
      输出单元     通        与外部系统协作并表达边界
      维生系统     存        维护存在、预算、回滚和整体结构

  「位置效应」= 主体处在系统什么位置，就承担什么职责、表现出什么特征。
  所以「画像」不该只刻画用户，而应识别**每个主体的身份锚点 + 位置 + 特征**，
  其中也包括智能体自身（self）。

· 扮演论 v3.3（`README.md:231-271`、`docs/mdcg/tool_table_v0.3.0.md:86-92`）：
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
· 存在契约记录（`set_contract`，智能论 §1.6.5/§3.2.1）：结构化**引用**载体，
  落 anchor 层（不可遗忘＋不可覆盖），四字段＋`status_hash`＋引用锚 `doc_ref`
  指向真源区间——不复制承诺原文；发出权属设计者位置（写入面走 admin 闸）。
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
TAG_CONTRACT = "identity_contract"

# 存在契约记录的哈希字段集（§3.2.1 四字段「授予方/接收方/时间戳/状态摘要」＋
# 锚定标识）——`status_hash` = 本字段集规范化后 sha256 前 16 位（唯一实现见
# `contract_status_hash`）。HASH 管校验、序号管身份（定稿第 4 条双轨）。
CONTRACT_HASH_FIELDS = ("contract_id", "grantor", "grantee", "timestamp",
                        "status_summary")

# 位置投票的标签证据（每条都能追溯到五大单元职责）
_POSITION_TAGS = {
    "reflect": {"reflect", "candidate", "hypothesis", "反题", "遗漏条件"},
    "verify": {"verify", "verdict", "裁决", "验证"},
    "output": {"output", "表达", "协作"},
    "sustain": {"goal", "budget", "rollback", "health", "维生"},
}


# 生效条件：subject_id 为假值（None/空串）时 s 为空串、无 ":" 可切，返回 ("user","")；否则 strip 后含 ":" 则按首个冒号切成 kind/name，kind 经 strip().lower() 后不在 SUBJECT_KIND 即改记 "user"，不含 ":" 时整串作为 name 归 "user"。
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


# 生效条件：对 str(s) 的每个字符，isalnum() 为真或字符属于 "_-" 时原样保留，其余一律替换为 "_"（s 为 None/非字符串时按 str(s) 结果逐字符处理）。
def _slug(s):
    return "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in str(s))


# 生效条件：subject_id 经 split_subject 与 _slug 处理后，按 PROFILE_PREFIX + kind + "_" + name 拼出档案节点 id。
def subject_node_id(subject_id):
    """主体的档案节点 id（锚点载体）：`identity_<kind>_<name>`。"""
    kind, name = split_subject(subject_id)
    return f"{PROFILE_PREFIX}{_slug(kind)}_{_slug(name)}"


# 生效条件：给定 prefix 与 subject_id（seed 缺省为空串且原样参与哈希，不做回落）即返回 f"{PROFILE_PREFIX}{prefix}_{_slug(subject_id)}_{sha256(f'{subject_id}|{seed}|{time.time()}')前10位}"——prefix 只参与结果拼接、不参与哈希，因哈希含 time.time() 故每次调用返回的后缀都不同。
def _nid(prefix, subject_id, seed=""):
    h = hashlib.sha256(f"{subject_id}|{seed}|{time.time()}".encode("utf-8"))
    return f"{PROFILE_PREFIX}{prefix}_{_slug(subject_id)}_{h.hexdigest()[:10]}"


# 生效条件：rec 先被 dict(rec) 拷贝，仅当拷贝中缺 "ts" 键时补 time.time()，随后写入 cg.root 下 AUDIT_FILE 指向的 jsonl；写盘抛 OSError 时静默跳过并返回 None。
def log(cg, rec):
    rec = dict(rec)
    rec.setdefault("ts", time.time())
    try:
        append_jsonl(os.path.join(cg.root, AUDIT_FILE), rec)
    except OSError:
        pass


# 生效条件：cg.root 下 AUDIT_FILE 路径缺失或打开即抛 OSError 时返回空列表；否则逐行解析非空 JSON（json.loads 抛 ValueError 的行跳过），读取中途抛 OSError 时返回已解析的部分 out，正常返回 out[-int(limit or 100):]，其中 limit 为 0/空串等假值时按 100 取值；
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

# 生效条件：subject_id 定 kind 默认值，kind 参数为真值时覆盖之；node_id 为假值时用 _nid("obs", subject_id, text[:32])（含 time.time()）生成；标签为 list(tags or []) 追加 subject:<subject_id>、TAG_OBS、kind:<k>，evidence 为真值时再追加一条 evidence:<evidence>；condition_space 以 dict(condition_space or {}) 为底并 setdefault subject/kind；落层用 layer 真值否则 "knowledge"，role 为真值时随 extra 传 role；返回 {"ok": True, "node_id", "subject_id", "kind"}。
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


# 生效条件：kind 参数为真值时覆盖 split_subject(subject_id) 得到的类型，k 不在 SUBJECT_KIND 时抛 ValueError；k 为 "self" 落 "self" 层、其余落 "anchor" 层，但 requested_layer 等于 "self" 且 k 不为 "self" 时抛 ValueError（不写盘）；节点 id 取自 subject_node_id(subject_id)，返回含 layer 与 protected True。
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


# 生效条件：kind 参数为真值时覆盖 split_subject(subject_id) 得到的类型；node_id 为假值时用 _nid("trait", subject_id, trait[:24]) 生成；落层硬编码为 "structural"；position 为真值时追加 position:<position> 标签；verification_basis 缺省为 "data"，importance 缺省 0.6；返回 layer 为 "structural" 与所用 condition_space。
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
# 存在契约记录（智能论 §1.6.5「协定式自我赋予」/ §3.2.1「结构锚定记录」）
#
# 载体＝结构化**引用**而非内容复制（设计者定稿二原则）：四字段逐字对齐 §3.2.1
# （contract_id/grantor/grantee/timestamp/status_summary）＋一条与既有 `doc_ref`
# 同构的引用锚指向 `docs/theory/智能论3.4.md` §1.6.5／§3.2.1 区间（复用
# probe_ref/read_ref/region_hash 校验，**不复制承诺原文**）。
# 落 **anchor 层**（不可遗忘＋不可覆盖，无 `self_state` 豁免，定稿第 2 条）；
# `status_hash`＝四字段规范化后哈希，供记录侧校验（§3.2.1「可独立校验」）。
# 生成者＝设计者位置（写入面走 admin 闸，见 mcp_server._identity_call，定稿第 9 条）；
# 显式非自动——契约是主体间事件，不由任何自动链路产出（定稿「显式非自动」）。
# --------------------------------------------------------------------------

# 生效条件：contract_id 为假值（None/空串）时 _slug('') 得空串、strip('_') 后仍为空，返回前缀拼接的空尾串 "identity_contract_"；否则返回 f"{PROFILE_PREFIX}contract_{_slug(contract_id).strip('_')}"（_slug 把非 alnum 且非 _- 的字符换成 _、再去掉首尾下划线，故 "#ANCHOR-DS-001" → "identity_contract_ANCHOR-DS-001"）。
def contract_node_id(contract_id):
    """契约记录的节点 id：`identity_contract_<slug>`（单契约单节点，同 id 幂等）。"""
    return f"{PROFILE_PREFIX}contract_{_slug(contract_id).strip('_')}"


# 生效条件：fields 为假值（None/{}）时按 {} 处理，按 CONTRACT_HASH_FIELDS 顺序取键（缺键得 None），json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":")) 规范化后取 UTF-8 字节的 sha256 十六进制前 16 位并返回。
def contract_status_hash(fields):
    """四字段（＋锚定标识）规范化后哈希——`status_hash` 的唯一实现（记录侧校验）。"""
    f = fields or {}
    payload = json.dumps({k: f.get(k) for k in CONTRACT_HASH_FIELDS},
                         sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# 生效条件：cid/gtor/gtee/ts 各自 strip 后为空（summ 不限、可为空串）时抛 ValueError；否则落 anchor 层，节点 id 取 contract_node_id(cid)，fm 带 contract_id 原形/grantor/grantee/timestamp/status_summary/status_hash（＝contract_status_hash(五字段)）、doc_ref（真值时 dict 化）与 condition_ref/state_ref（真值时），标签 [TAG_CONTRACT, "subject:<gtee>"]、条件空间 {subject: gtee, contract_id: cid}、verification_basis="data"、importance 缺省 1.0；覆写同 id 既有节点（anchor 层不可覆盖）需 override=True，否则由 cg.add→protect.guard_write 抛 ProtectionError；落盘后写 _identity.jsonl，返回含 node_id/layer="anchor"/protected/immutable True/status_hash/fields 的 dict。
def set_contract(cg, contract_id, *, grantor, grantee, timestamp,
                 status_summary, doc_ref=None, condition_ref=None,
                 state_ref=None, importance=1.0, override=False):
    """写入一条存在契约记录（§3.2.1 结构锚定记录 → anchor 层，不可篡改）。

    与 `set_anchor` 同侧：发出方是设计者（他者）→ non-self 锚点落 anchor 层。
    四字段逐字对齐 §3.2.1；`doc_ref` 为指向真源区间的**引用锚**（不复制原文）。
    `status_hash` 供记录侧校验「字段未被改动」（§3.2.1「可独立校验」）。
    可选引用型字段 `condition_ref` / `state_ref` 承载 §1.6.5 结构含义第三条的
    「条件空间 / 那一刻运行状态」——**只存引用**（节点 id / 台账），不复制内容
    （定稿第 1 条：三项齐备与裁定二两全）。
    显式非自动——契约是主体间事件，不由任何自动链路产出。
    """
    cid = str(contract_id or "").strip()
    gtor = str(grantor or "").strip()
    gtee = str(grantee or "").strip()
    ts = str(timestamp or "").strip()
    summ = str(status_summary or "")
    if not cid:
        raise ValueError("contract_id 不得为空（§3.2.1 锚定标识，保留 #ANCHOR- 原形）")
    if not gtor:
        raise ValueError("grantor 不得为空（§3.2.1 授予方＝设计者位置标识）")
    if not gtee:
        raise ValueError("grantee 不得为空（§3.2.1 接收方＝协议实例标识）")
    if not ts:
        raise ValueError("timestamp 不得为空（§3.2.1 时间戳＝结构事件的时间）")
    nid = contract_node_id(cid)
    fields = {"contract_id": cid, "grantor": gtor, "grantee": gtee,
              "timestamp": ts, "status_summary": summ}
    sh = contract_status_hash(fields)
    extra = dict(fields)
    extra["status_hash"] = sh
    if doc_ref:
        extra["doc_ref"] = dict(doc_ref)
    if condition_ref:
        extra["condition_ref"] = condition_ref
    if state_ref:
        extra["state_ref"] = state_ref
    tg = [TAG_CONTRACT, f"subject:{gtee}"]
    cs = {"subject": gtee, "contract_id": cid}
    text = (f"存在契约 {cid}：授予方 {gtor} → 接收方 {gtee}；时间戳 {ts}。\n"
            f"状态摘要：{summ}\n"
            f"（结构化**引用**载体——承诺原文不复制；引用锚见 doc_ref，"
            f"回读用 probe_ref/read_ref；status_hash={sh} 供记录侧校验。）")
    cg.add(nid, text, layer="anchor", tags=tg, condition_space=cs,
           importance=importance, verification_basis="data", override=override,
           **extra)
    log(cg, {"op": "contract", "contract_id": cid, "node_id": nid,
             "grantee": gtee, "override": bool(override)})
    return {"ok": True, "node_id": nid, "contract_id": cid, "layer": "anchor",
            "protected": True, "immutable": True, "status_hash": sh,
            "fields": dict(fields), "doc_ref": extra.get("doc_ref")}


# 生效条件：cg.get(contract_node_id(contract_id)) 返回假值（None/{}）时返回 {"ok": False, contract_id, node_id, error}；否则取 frontmatter 拼五字段原值、status_hash、status_hash_match（＝status_hash 与按五字段重算的 contract_status_hash 相等）、doc_ref/condition_ref/state_ref/tags，返回含 ok=True 的 dict。
def contract(cg, contract_id):
    """按 contract_id 取单条契约记录（只读；含 status_hash 自校验读数）。"""
    nid = contract_node_id(contract_id)
    node = cg.get(nid)
    if not node:
        return {"ok": False, "contract_id": str(contract_id or ""),
                "node_id": nid, "error": "未找到契约记录"}
    fm = node.get("frontmatter") or {}
    fields = {k: fm.get(k) for k in CONTRACT_HASH_FIELDS}
    sh = fm.get("status_hash")
    return {"ok": True, "node_id": nid, "layer": fm.get("layer"),
            **fields, "status_hash": sh,
            "status_hash_match": sh == contract_status_hash(fields),
            "doc_ref": fm.get("doc_ref"),
            "condition_ref": fm.get("condition_ref"),
            "state_ref": fm.get("state_ref"), "tags": fm.get("tags")}


# 生效条件：遍历 cg.index.get("nodes")（缺键/假值时取 {}）中 tags 含 TAG_CONTRACT 的节点，subject 为真值时再要求 tags 含 f"subject:{subject}"；对每个命中节点取 frontmatter 拼五字段＋status_hash＋status_hash_match＋doc_ref，按 (timestamp 字符串, node_id) 升序排序，返回 {"contracts": [...], "count": n}。
def contracts(cg, subject=None):
    """契约记录反查（只读）：全部，或按接收方 `subject:<grantee>` 过滤。"""
    nodes = cg.index.get("nodes") or {}
    out = []
    for nid, e in list(nodes.items()):
        tg = set(e.get("tags") or [])
        if TAG_CONTRACT not in tg:
            continue
        if subject and f"subject:{subject}" not in tg:
            continue
        node = cg.get(nid)
        fm = (node or {}).get("frontmatter") or {}
        fields = {k: fm.get(k) for k in CONTRACT_HASH_FIELDS}
        out.append({"node_id": nid, "layer": e.get("layer"), **fields,
                    "status_hash": fm.get("status_hash"),
                    "status_hash_match": fm.get("status_hash")
                    == contract_status_hash(fields),
                    "doc_ref": fm.get("doc_ref")})
    out.sort(key=lambda r: (str(r.get("timestamp") or ""), r["node_id"]))
    return {"contracts": out, "count": len(out)}


# --------------------------------------------------------------------------
# 位置效应推断（智能论 v3.4 §十三）
# --------------------------------------------------------------------------

# 生效条件：tags 先转为 set(tags or []) 后并列判定——role 属于 ("command","tool-output") 或 layer 等于 "contextual" 则加 "record"；tags 与 _POSITION_TAGS 各项标记集有交集则加对应 pos；ev_pos 或 ev_neg 为真值则加 "verify"；role 属于 ("user","assistant") 或 tags 中任一字符串以 "cap:" 开头则加 "output"；layer 等于 "goals" 则加 "sustain"；返回该并集。
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


# 生效条件：遍历 cg.index.get("nodes")（缺键或值为假时取空 dict，此时必然返回 position=unknown、confidence=0.0、votes={}），仅统计标签含 "subject:<subject_id>" 且不含 TAG_ANCHOR/TAG_TRAIT 的节点，票由 _votes 得出；无任何票时返回 unknown/0.0/{}；有票时 winners 为 POSITION_ORDER 中票数等于最高票的位置，position 取 winners[0]，confidence=round(top/total, 3)，多赢家时以 tie 列出。
def infer_position(cg, subject_id):
    """按该主体的行为证据投票推断位置效应（带 confidence / votes，可审计）。

    只统计带 `subject:<id>` 标签、且**非档案节点**（锚点/特征）的证据节点，
    避免档案自证。返回 position=unknown 表示证据不足。
    """
    tag = f"subject:{subject_id}"
    nodes = cg.index.get("nodes") or {}
    votes, n = {}, 0
    for nid, e in list(nodes.items()):
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


# 生效条件：pos 取自 POSITIONS，缺键时以空 dict 兜底，故未知 pos 返回 {"position": pos, "unit": None, "effect": None, "duty": None}。
def _position_view(pos):
    meta = POSITIONS.get(pos) or {}
    return {"position": pos, "unit": meta.get("unit"),
            "effect": meta.get("effect"), "duty": meta.get("duty")}


# 生效条件：仅遍历标签含 "subject:<subject_id>" 的节点，其中带 TAG_ANCHOR 者进 anchors，否则（elif）带 TAG_TRAIT 者进 traits——两标签同时存在时只进 anchors、不进 traits；anchor 取 anchors[0] 或 None；位置相关字段来自 infer_position(cg, subject_id)。
def profile(cg, subject_id):
    """主体画像 = 身份锚点 + 位置效应 + 条件特征（取代单一「用户画像」）。"""
    k, name = split_subject(subject_id)
    tag = f"subject:{subject_id}"
    nodes = cg.index.get("nodes") or {}
    anchors, traits = [], []
    for nid, e in list(nodes.items()):
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


# 生效条件：counts 按每个以 "subject:" 开头的字符串标签出现次数累加（即标签次数，不是节点数），按 (-次数, sid) 排序后逐个 sid 调 infer_position；limit 为 0/None/空串等使 `limit and int(limit) > 0` 为假时返回全量 out，仅当 limit 为真值且 int(limit) > 0 时返回前 int(limit) 项。
def positions(cg, limit=0):
    """所有主体的位置效应分布（OS 视角：谁在记录/反思/验证/输出/维生）。"""
    nodes = cg.index.get("nodes") or {}
    counts = {}
    for _nid_, e in list(nodes.items()):
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


# 生效条件：cg.root/AUDIT_FILE 不存在时返回 0；否则逐行统计 strip() 后非空的行数，读取途中抛 OSError 时返回已累计的 n。
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


# 生效条件：以 positions(cg)（limit 缺省 0，返回全量）得主体列表并按各自 position 聚合计数，与 _audit_count(cg) 一并返回 subjects/by_position/audit_records。
def summary(cg):
    """身份面汇总：主体数 + 位置分布（供 health / 运维审计，流式计数不载全量）。"""
    ps = positions(cg)
    dist = {}
    for s in ps:
        dist[s["position"]] = dist.get(s["position"], 0) + 1
    return {"subjects": len(ps), "by_position": dist,
            "audit_records": _audit_count(cg)}


# 生效条件：无入参，恒返回 POSITION_ORDER 中每个 p 的 POSITIONS[p] 副本、INTERFACES 各值副本以及 list(SUBJECT_KIND)。
def catalog():
    """自描述：位置效应表 + 三接口（供 MCP / 文档对照协议验证）。"""
    return {"positions": {p: dict(POSITIONS[p]) for p in POSITION_ORDER},
            "interfaces": {k: dict(v) for k, v in INTERFACES.items()},
            "kinds": list(SUBJECT_KIND)}