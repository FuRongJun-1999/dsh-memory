# -*- coding: utf-8 -*-
"""自我面（self surface）——把「自我认知数据」与「审核裁决审计记录」分开。

背景（2026-10-18 实测）：self 层 780 条里 769 条是审核裁决审计记录（rev_*），
真实自我锚点只剩 11 条。原因是 _write_review_record 曾把审计节点写进 self 层
（已改为 structural，只堵住源头），而存量 769 条按方案 C 处理——**不迁移**
（它们带 record_hash 与加密正文、可能被引用，迁移会动 is_protected 判定面），
改为打 audit_trace 标签 + 在读取面过滤。

为什么选「打标签」而不是迁移：
* 零迁移风险：不动文件位置、不动 record_hash 引用、不动层保护判定；
* 语义正确：审计痕迹**应当**在自我面被排除，而不是被搬到别处继续占位；
* 可逆：删标签即回到原状。

判据单点：AUDIT_TRACE_TAG。任何需要「真实自我面」的调用方都经 self_surface()，
不各写一份过滤逻辑（本仓已被「同一语义两份实现」咬过多次）。
"""

__all__ = ["AUDIT_TRACE_TAG", "is_audit_trace", "self_surface"]

#: 审计痕迹标签。打在审核裁决节点上，表示「这是裁决痕迹，不是自我认知数据」。
AUDIT_TRACE_TAG = "audit_trace"


def is_audit_trace(fm):
    """该条目是否为审核裁决审计痕迹（按标签判定，缺 tags 视为否）。"""
    if not isinstance(fm, dict):
        return False
    tags = fm.get("tags") or []
    return AUDIT_TRACE_TAG in tags


def self_surface(cg, include_audit_trace=False):
    """返回 self 层的「真实自我面」节点 id 列表。

    include_audit_trace=True 时不过滤（用于审计/排查）。
    排序后返回，保证可复跑（不依赖索引遍历顺序）。
    """
    idx = getattr(cg, "index", None) or {}
    nodes = idx.get("nodes") or {}
    out = []
    for nid, e in nodes.items():
        if not isinstance(e, dict):
            continue
        if e.get("layer") != "self":
            continue
        if not include_audit_trace and is_audit_trace(e):
            continue
        out.append(nid)
    return sorted(out)
