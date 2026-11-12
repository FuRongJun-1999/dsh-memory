# -*- coding: utf-8 -*-
"""修订与回滚（revise / rollback）——四动作里此前完全缺失的那一条。

背景（外部 issue #5 第 8/11 条，2026-10-18）：
    revise 在文档里早有签名，但**代码全仓 0 命中**；superseded 档已随方案 A 落地，
    本模块把「产生新版本、旧版转 superseded、可回滚」这三件事接起来。

三条设计纪律：

1. **先写新、再改旧**。新版本必须真正落盘成功，才允许把旧版本标为 superseded；
   否则会出现「旧版被取代、新版不存在」的悬空状态。任何一步失败都不动旧节点。
2. **CAS 防并发覆盖**。调用方可传 expect_state；与当前状态不符即 DEFER 让调用方
   重读，而不是覆盖别人的修改（issue #5 第 11 条：state_from 天然可作 CAS 前置）。
3. **回滚不删任何东西**。rollback 只做状态互换：旧版 superseded→active，
   新版 active→superseded。不归档、不删除——因为 active→archived 是跳级（被
   TRANSITIONS 拒绝），而「互换取代关系」既可逆又符合状态机。
"""

import time

from . import lifecycle

__all__ = ["revise", "rollback"]

#: 回滚令牌的最小形状（写进返回体，可持久化）
TOKEN_KEYS = ("old_id", "old_state", "new_id", "new_state", "ts")


def _state_of_node(cg, node_id):
    """取节点当前生命周期状态。

    实测（2026-10-18）：cg.get() 返回 {id, content, frontmatter, path}，
    lifecycle_state 在 frontmatter 里，**不在顶层**。首版把整个 dict 当 fm，
    state_of 读不到键就 fail-open 成 active——于是 set_state 明明成功、
    读回却是 active，conformance 直接红。

    这是同一类错误的第二次（前一次是 cg.search 返回 (res, meta) 而非 res）：
    **不要假设接口返回结构，先实测。**
    """
    node = cg.get(node_id)
    if node is None:
        return None
    if isinstance(node, dict):
        fm = node.get("frontmatter") or node
    elif isinstance(node, (list, tuple)) and node:
        fm = node[0]
    else:
        fm = node
    return lifecycle.state_of(fm)


def _write_new(cg, content, layer, tags, condition_space):
    """走正常写入链（含形式完备闸），返回 disp 结构。"""
    from .mcp_server import _cg_dispatch
    a = {"op": "write", "content": content, "content_kind": "work_done",
         "layer": layer or "knowledge", "tags": tags or ["revise"]}
    if condition_space:
        a["condition_space"] = condition_space
    r = _cg_dispatch(cg, a)
    return r if isinstance(r, dict) else {}


def revise(cg, old_id, new_content, expect_state=None, reason="修订",
           layer=None, tags=None, condition_space=None):
    """产生新版本并把旧版本标为 superseded。

    返回：
        {"verdict": "ACCEPT"|"REJECT"|"DEFER", "state_from", "state_to",
         "new_id", "rollback_token", "reason"}
    """
    old_state = _state_of_node(cg, old_id)
    if old_state is None:
        return {"verdict": "REJECT", "reason": "旧节点不存在：%s" % old_id,
                "state_from": None, "state_to": None, "new_id": None,
                "rollback_token": None}

    # CAS：并发前置条件
    if expect_state is not None and str(expect_state) != old_state:
        return {"verdict": "DEFER", "state_from": old_state, "state_to": old_state,
                "new_id": None, "rollback_token": None,
                "reason": "CAS 不符：期望 %s，实际 %s（请重读后再修订）"
                          % (expect_state, old_state)}

    if old_state in ("archived", "superseded"):
        return {"verdict": "REJECT", "state_from": old_state, "state_to": old_state,
                "new_id": None, "rollback_token": None,
                "reason": "已退役版本不可再被修订（%s）" % old_state}

    # ① 先写新版——失败则完全不动旧节点
    disp = _write_new(cg, new_content, layer, tags, condition_space)
    verdict = (disp.get("verdict") or {}).get("state")
    if not disp.get("committed") or verdict != "ACCEPT":
        return {"verdict": verdict or "REJECT", "state_from": old_state,
                "state_to": old_state, "new_id": None, "rollback_token": None,
                "reason": "新版未落盘，旧版保持不动",
                "new_verdict": disp.get("verdict")}

    new_id = disp.get("id")

    # ② 再改旧版——此时新版已确认存在
    lifecycle.set_state(cg, old_id, "superseded",
                        reason="%s（被 %s 取代）" % (reason, new_id))
    new_state = _state_of_node(cg, old_id)

    token = {"old_id": old_id, "old_state": old_state, "new_id": new_id,
             "new_state": "active", "ts": time.time()}
    return {"verdict": "ACCEPT", "state_from": old_state, "state_to": new_state,
            "new_id": new_id, "rollback_token": token, "reason": reason}


def rollback(cg, token, reason="回滚"):
    """撤销一次修订：旧版复活、新版转为被取代。**不删除任何节点。**

    不用「新版→archived」的理由：active→archived 是跳级（TRANSITIONS 拒绝）；
    互换取代关系既可逆，又正确表达了「回滚后谁是当前版本」。
    """
    if not isinstance(token, dict) or not token.get("old_id") or not token.get("new_id"):
        return {"verdict": "REJECT", "reason": "回滚令牌不完整"}

    old_id, new_id = token["old_id"], token["new_id"]
    st_old = _state_of_node(cg, old_id)
    st_new = _state_of_node(cg, new_id)
    if st_old is None or st_new is None:
        return {"verdict": "REJECT", "reason": "令牌指向的节点不存在",
                "state_old": st_old, "state_new": st_new}

    if st_old != "superseded":
        return {"verdict": "DEFER", "reason": "旧版当前不在 superseded（%s），拒绝回滚" % st_old,
                "state_old": st_old, "state_new": st_new}

    # 互换：旧版复活、新版被取代
    lifecycle.set_state(cg, old_id, "active", reason="%s：恢复旧版" % reason)
    if st_new == "active":
        lifecycle.set_state(cg, new_id, "superseded",
                            reason="%s：新版转为被取代" % reason)

    return {"verdict": "ACCEPT",
            "state_old_after": _state_of_node(cg, old_id),
            "state_new_after": _state_of_node(cg, new_id),
            "reason": reason}
