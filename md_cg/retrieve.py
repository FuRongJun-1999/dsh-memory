# -*- coding: utf-8 -*-
"""取（retrieve）—— 四动作之一，返回**定型信封**（Envelope）。

为什么要这层（外部 issue #5 第 15 条）：
    既有检索面 cg.search 返回 (results, meta)，是内部检索包的形状；「可复跑」要求
    接口形状本身可判，故另立定型入口，把检索包规范化成 Envelope。

**不改既有 search 路径**：search 被几十处调用，改它的返回形状是破坏性变更。
本模块只做适配，新调用方用新入口，老调用方一字不动。

Envelope 字段（schema 见 interface_schema.ENVELOPE）：

    items[]            条目：node_id / content / condition_space / qualification /
                       lifecycle_state / content_kind
    completeness       bool   本次检索是否覆盖了候选全集（false 时不得进入零命中路径）
    hit_count          int    命中数；**非 success 时恒 null**（I1）
    snapshot_id        str    索引快照标识（跨快照比较必须显式声明）
    operation_status   success | partial | timeout | unavailable | operation_error

两条必须守的纪律：
* **I1**：非 success 时 hit_count 必须为 null——不能让人把「故障」读成「没有」。
* **条件空间如实**：索引条目不含 condition_space（见 condgate.qualify 的说明），
  故本模块对**每条命中**回查一次 frontmatter（k 条，代价可接受），
  以给出准确的 qualification，而不是拿索引的空字段糊弄。
  这也是 gap_cs_not_indexed 在「取」这一层的局部解法——全量索引改造另议。
"""

import time

from . import condgate, lifecycle

__all__ = ["retrieve", "ENVELOPE_FIELDS"]

ENVELOPE_FIELDS = ("items", "completeness", "hit_count", "snapshot_id",
                   "operation_status")


def _snapshot_id(cg):
    """索引快照标识 = 节点数 + 索引文件 mtime。

    首版读 cg._index_mtime（该属性不存在）→ 恒得 0，于是所有快照都叫 snap-N-0，
    **跨快照比较失去意义**（而 snapshot_id 的全部用途就是显式声明版本差异）。
    改为直接取索引文件 mtime；取不到（如内存库）则回落 0 并如实反映。
    """
    import os as _os
    idx = getattr(cg, "index", None) or {}
    n = len((idx.get("nodes") or {}))
    path = getattr(cg, "index_path", None)
    mtime = 0
    if path:
        try:
            mtime = int(_os.path.getmtime(str(path)))
        except OSError:
            mtime = 0
    return "snap-%d-%d" % (n, mtime)


def retrieve(cg, query, k=10, layer=None, session=None,
             condition_space=None, snapshot_id=None):
    """检索并返回定型 Envelope。失败也返回 Envelope（带 operation_status），不抛。"""
    q = (query or "").strip()
    if not q:
        return {"items": [], "completeness": True, "hit_count": 0,
                "snapshot_id": snapshot_id or _snapshot_id(cg),
                "operation_status": "success", "reason": "empty_query"}

    try:
        res = cg.search(q, k=k, layer=layer, session=session)
        hits, meta = res if isinstance(res, tuple) and len(res) == 2 else (res, {})
    except Exception as exc:                     # noqa: BLE001 —— 失败要如实成形态
        return {"items": [], "completeness": False, "hit_count": None,
                "snapshot_id": snapshot_id or _snapshot_id(cg),
                "operation_status": "operation_error",
                "error": "%s: %s" % (type(exc).__name__, exc)}

    items = []
    for h in (hits or []):
        node = h[0] if isinstance(h, (list, tuple)) and h else h
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        # 回查 frontmatter：索引里没有 condition_space，只能从节点本体取
        fm = {}
        try:
            got = cg.get(nid) if nid else None
            fm = (got or {}).get("frontmatter") or {}
        except Exception:                        # noqa: BLE001
            fm = {}
        full = node.get("content") or ""
        items.append({
            "node_id": nid,
            "content": full[:400],
            # I17 / I16（2026-10-18）：投影不得自称权威——截断必须显式声明。
            # 不声明的话，读者会把 400 字当成原文全文，这正是「投影冒充原文」。
            "content_truncated": len(full) > 400,
            "content_full_len": len(full),
            "condition_space": fm.get("condition_space"),
            "qualification": condgate.qualify(fm),
            "lifecycle_state": lifecycle.state_of(fm),
            "content_kind": node.get("content_kind") or fm.get("content_kind"),
        })

    scanned = meta.get("scanned")
    completeness = bool(meta.get("completeness", True)) if isinstance(meta, dict) else True
    status = "success"
    if isinstance(meta, dict) and meta.get("tier") is None and not items:
        status = "success"                        # 真空结果仍是 success
    elif isinstance(meta, dict) and meta.get("partial"):
        status = "partial"
        completeness = False

    # I2（2026-10-18）：completeness=False 时**不得断言「没有」**。
    # 零命中 + 不完整，若报 hit_count=0，调用方会读成「查了，确实没有」——
    # 而实际是「没查全」。故此时 hit_count 必须为 null（与 I1 同一精神：
    # 不确定的结论不能伪装成确定）。有命中时仍给数量，由 completeness 标注覆盖面。
    hit_count = len(items)
    if not completeness and hit_count == 0:
        hit_count = None

    return {
        "items": items,
        "completeness": completeness,
        "hit_count": hit_count,                  # 仅 success/partial 且完整时有意义
        "snapshot_id": snapshot_id or _snapshot_id(cg),
        "operation_status": status,
        "scanned": scanned,
        "tier": (meta or {}).get("tier") if isinstance(meta, dict) else None,
    }
