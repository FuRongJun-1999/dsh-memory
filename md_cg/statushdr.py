# -*- coding: utf-8 -*-
"""md_cg · 状态摘要协议（MCP 输出面一等公民）

【为什么】验证态若只在 frontmatter / 索引里躺着，读面就得「先知道去哪查」——
与纪律只存在于认知图时执行率近零同构。故把状态**推进每一次返回体**：
人类与 agent 读面一致，默认开启。

四符号（`HEAD_MARKS`）：
    ✓ 已验证   证据在位、依赖未动、时效内
    △ 已修改   复核中（上游动过，复核进行态）
    ! 异常     已过期（时效失效）或依赖目标悬空——**地基动了**
    ? 存疑     依赖变动后被自动标记，待复核
（未验证补 `·`：不是四态之一，但读面需要一个「尚未验证」的可视锚点。）

【怎么做】在 `_cg_call` **单一出口**统一挂 `status_head` 并升级既有 `hint`——
29+ 个 op 分支一处不改，爆炸半径最小。注入仅对返回体中**实际出现的节点 id**
计算（O(k)，受 `k` 与 MAX_IDS 约束），不做全库扫描。

【关闭】`MDCG_STATUS_HEAD=0` 回退旧 hint 文本（灰度/排障用）。

零第三方依赖（D-005）。
"""
from __future__ import annotations

import os

from . import trust

#: 四符号（读面契约，勿随意改字形——agent 侧提示词按此对齐）
MARK_VERIFIED = "✓"
MARK_MODIFIED = "△"
MARK_ABNORMAL = "!"
MARK_DOUBTED = "?"
MARK_UNVERIFIED = "·"
HEAD_MARKS = (MARK_VERIFIED, MARK_MODIFIED, MARK_ABNORMAL, MARK_DOUBTED)

ENV = "MDCG_STATUS_HEAD"
#: 注入上限：单次返回体最多为这么多节点计算状态头（防大结果集拖慢出口）
MAX_IDS = 50


def enabled() -> bool:
    """状态头开关（默认开启；`MDCG_STATUS_HEAD=0` 回退旧 hint 文本）。"""
    v = (os.environ.get(ENV) or "").strip().lower()
    return v not in ("0", "false", "no", "off")


def _mark(state: str, valid_kind: str, dangling: bool) -> str:
    if dangling or valid_kind == "expired" or state == "expired":
        return MARK_ABNORMAL
    if state == "doubted":
        return MARK_DOUBTED
    if state == "rechecking":
        return MARK_MODIFIED
    if state == "verified":
        return MARK_VERIFIED
    return MARK_UNVERIFIED


def _label(mark: str) -> str:
    return {MARK_VERIFIED: "已验证", MARK_MODIFIED: "已修改",
            MARK_ABNORMAL: "异常", MARK_DOUBTED: "存疑",
            MARK_UNVERIFIED: "未验证"}.get(mark, "未验证")


def render(cg, node_id: str, *, node: dict = None, index_entry: dict = None,
           now: float = None) -> str:
    """单条状态头字符串（附方式 / 时间 / 影响范围 / 待确认条件）。只读不抛。"""
    try:
        e = index_entry
        if e is None:
            e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id)
        fm = (node or {}).get("frontmatter") if node else None
        if fm is None:
            fm = e or {}
        state = trust.state_of(fm)
        kind, _s, _e = trust.validity(fm, now=now)
        deps = trust.as_deps(fm.get(trust.DEPS_FIELD))
        known = set((getattr(cg, "index", None) or {}).get("nodes") or {})
        dangling = [p for p in deps if p not in known]
        mark = _mark(state, kind, bool(dangling))
        bits = []
        if dangling:
            bits.append(f"依赖目标缺失：{','.join(dangling[:3])}")
        if kind == "expired":
            bits.append("时效已过")
        elif kind == "not_yet":
            bits.append("尚未生效")
        method = (fm.get("verification_method") or fm.get("verification_basis")
                  or "")
        if method and mark == MARK_VERIFIED:
            bits.append(f"方式={str(method)[:40]}")
        if mark == MARK_DOUBTED:
            bits.append("上游变动，待复核")
        if mark in (MARK_VERIFIED, MARK_MODIFIED) and fm.get("verified_at"):
            try:
                import time as _t
                bits.append("验证于 " + _t.strftime(
                    "%Y-%m-%d", _t.localtime(float(fm["verified_at"]))))
            except Exception:                              # noqa: BLE001
                pass
        return f"{mark} {_label(mark)}" + (f"（{'；'.join(bits)}）" if bits else "")
    except Exception as exc:                               # noqa: BLE001
        return f"{MARK_UNVERIFIED} 未验证（状态头降级：{type(exc).__name__}）"


#: 返回体中可能承载节点 id 的键（显式枚举，避免把任意字符串误当 id）
_ID_KEYS = ("node_id", "id", "nid")


def _collect_ids(obj, acc: list, depth: int = 0) -> None:
    """递归收集候选节点 id（深度/数量双上限；找不到就不找，绝不猜）。"""
    if len(acc) >= MAX_IDS or depth > 4:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _ID_KEYS and isinstance(v, str) and v:
                acc.append(v)
            elif isinstance(v, (dict, list)):
                _collect_ids(v, acc, depth + 1)
                if len(acc) >= MAX_IDS:
                    return
    elif isinstance(obj, list):
        for it in obj:
            _collect_ids(it, acc, depth + 1)
            if len(acc) >= MAX_IDS:
                return


def attach_heads(cg, out: dict, *, now: float = None) -> dict:
    """扫描返回体中的节点 id，批量挂 `status_head`（O(k)，幂等）。"""
    if not isinstance(out, dict):
        return out
    ids, seen = [], set()
    _collect_ids(out, ids)
    known = (getattr(cg, "index", None) or {}).get("nodes") or {}
    heads = {}
    for nid in ids:
        if nid in seen or nid not in known:
            continue
        seen.add(nid)
        heads[nid] = render(cg, nid, index_entry=known.get(nid), now=now)
    if not heads:
        return out
    out["status_heads"] = heads
    out["status_head"] = (next(iter(heads.values())) if len(heads) == 1
                          else f"{len(heads)} 节点（见 status_heads）")
    return out


def annotate(cg, out: dict, *, now: float = None) -> dict:
    """**单出口**注入口：挂状态头 + 把既有 `hint` 升级为状态头格式。

    幂等：已注入过（`status_head` 在返回体中）则不再重复改写 hint。
    """
    if not enabled() or not isinstance(out, dict):
        return out
    if "status_head" in out:
        return out
    before_hint = out.get("hint")
    attach_heads(cg, out, now=now)
    head = out.get("status_head")
    if head and before_hint:
        out["hint"] = f"{head} · {before_hint}"
    elif head:
        out["hint"] = head
    return out


def catalog() -> dict:
    """自描述（供 MCP catalog / 人工核对）。"""
    return {
        "layer": "状态摘要协议",
        "marks": {"verified": MARK_VERIFIED, "modified": MARK_MODIFIED,
                  "abnormal": MARK_ABNORMAL, "doubted": MARK_DOUBTED,
                  "unverified": MARK_UNVERIFIED},
        "env": ENV, "default_on": True, "max_ids": MAX_IDS,
        "note": "统一在 _cg_call 单出口注入；hint 同步升级（Q3 默认开启）",
    }
