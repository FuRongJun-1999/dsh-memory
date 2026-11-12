# -*- coding: utf-8 -*-
"""回执（锚定记录）与独立校验——I14 的代码落点。

理论依据：智能论 3.4 §3.2.1 结构锚定记录（分层·架构层.md:70-98）。原文五字段：

    锚定标识   #ANCHOR-[HASH]   唯一标识，由记录单元生成
    授予方     设计者位置标识
    接收方     协议实例标识
    时间戳     结构事件的时间
    状态摘要   锚定时协议实例的结构状态（用于验证锚点与协议版本的一致性）

原文三条验证功能需求：**不可篡改**、**可独立校验**（任何持有副本的节点可通过
状态摘要验证一致性）、**多节点冗余**。

本模块的诚实边界：
* 实现前两条（不可篡改靠内容寻址；可独立校验靠 verify_anchor）；
* **多节点冗余不实现**——那是部署面的事，单库内做不了，不假装。
* 字段按 §3.2.1 对齐，但本模块服务的是「信息锚定 + 回执校验」（I14），
  不声称实现了完整的「协定式自我赋予」流程（那属 L3 契约面）。

I14 的含义落在这里：**回执不得自带真值**——回执只带指针与摘要，不复制原文；
原文不可读或已变，校验就必须失败。若回执能脱离原文独立"通过"，它就不再是回执，
而是一份冒充原文的投影（I17）。
"""

import hashlib
import json
import time

__all__ = ["make_anchor", "verify_anchor", "ANCHOR_PREFIX", "STATE_FIELDS"]

ANCHOR_PREFIX = "#ANCHOR-"

#: 进入「状态摘要」的字段。取**结构状态**而非正文——§3.2.1 要求状态摘要是
#: 「锚定时协议实例的结构状态」，用于验证锚点与版本的一致性；正文指纹另列
#: content_hash，两者分开才能分别定位「结构变了」与「内容变了」。
STATE_FIELDS = ("layer", "condition_space", "lifecycle_state", "edges", "tags")


def _sha(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _canonical_state(fm):
    picked = {}
    for k in STATE_FIELDS:
        if k in (fm or {}):
            picked[k] = fm[k]
    return json.dumps(picked, ensure_ascii=False, sort_keys=True, default=str)


def make_anchor(cg, node_id, grantor=None, grantee=None):
    """为一条已存在的信息生成锚定记录（回执）。

    返回 {"ok": True, "anchor": {...}} 或 {"ok": False, "reason": ...}。
    锚定记录**不含正文**——这是 I14 的前提。
    """
    node = cg.get(node_id)
    if node is None:
        return {"ok": False, "reason": "节点不存在：%s" % node_id}
    fm = node.get("frontmatter") or {}
    content = node.get("content") or ""

    state_digest = _sha(_canonical_state(fm))
    content_hash = _sha(content)
    anchor_id = ANCHOR_PREFIX + _sha(node_id + state_digest + content_hash)[:16]

    return {"ok": True, "anchor": {
        "anchor_id": anchor_id,          # 锚定标识
        "node_id": node_id,              # 接收方（本条信息）
        "grantor": grantor,              # 授予方
        "grantee": grantee or node_id,   # 接收方标识
        "created_at": time.time(),       # 时间戳
        "state_digest": state_digest,    # 状态摘要（§3.2.1）
        "content_hash": content_hash,    # 正文指纹（供 I14 校验）
    }}


def verify_anchor(cg, receipt):
    """独立校验：只凭回执 + 库内原文判断一致性。

    三种失败都要**分别归因**（不合并成一句"校验失败"）：
        missing_node     原文不可读 → 回执无法被独立校验（I14：回执不得自带真值）
        content_changed  正文已变
        state_changed    结构状态已变（layer/condition_space/生命周期/边/标签）

    不抛异常：校验失败是结论，不是错误。
    """
    anc = (receipt or {}).get("anchor") if isinstance(receipt, dict) else None
    if not isinstance(anc, dict):
        return {"ok": False, "reason": "missing_anchor", "detail": "回执结构不合法"}

    for k in ("anchor_id", "node_id", "state_digest", "content_hash"):
        if not anc.get(k):
            return {"ok": False, "reason": "incomplete_anchor", "detail": "缺字段 %s" % k}

    node = cg.get(anc["node_id"])
    if node is None:
        # 关键：原文没了，回执**必须**失败——若这里能"通过"，回执就自带真值了。
        return {"ok": False, "reason": "missing_node",
                "detail": "原文不可读，回执无法独立校验（I14）"}

    fm = node.get("frontmatter") or {}
    content = node.get("content") or ""
    cur_state = _sha(_canonical_state(fm))
    cur_content = _sha(content)

    if cur_content != anc["content_hash"]:
        return {"ok": False, "reason": "content_changed",
                "expected": anc["content_hash"], "actual": cur_content}
    if cur_state != anc["state_digest"]:
        return {"ok": False, "reason": "state_changed",
                "expected": anc["state_digest"], "actual": cur_state}
    return {"ok": True, "anchor_id": anc["anchor_id"], "node_id": anc["node_id"]}
