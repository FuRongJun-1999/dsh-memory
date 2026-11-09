# -*- coding: utf-8 -*-
"""CCG 要素口径的**单点**：谁需要六要素、谁被豁免、豁免怎么被看见。

为什么必须有这一层（2026-11-06 取证）：
  · 写入闸门的必需规则是**数据**（`data/policy.json` 的 `required` +
    `required_kinds: ["text"]`），而检索面（资格裁决 BLINDSPOT、健康面
    `ccg_complete`）用的是 `nodefile.ccg_completeness(content)`——它只看正文，
    不看 kind。同一个节点因此可以在写入面「不适用」而在检索面「缺 6 项」。
  · 实测存量 859 个节点 `frontmatter.content_kind` **全部缺失**（写入链没把
    `content_kind` 落 fm），于是 `required_kinds` 在整个库上**空转**：调用方
    传了 kind 就按 text 卡六要素、不传就一律放行。口径随调用方漂移。

本模块只做一件事：把「kind → 是否需要六要素」这条口径收成一处，两个面共用。
判定顺序：policy 的 required_kinds（缺省/空 → 全部 kind 都需要）。
"""

TEXT_KIND = "text"


def required_kinds():
    """policy.json 的 required_kinds（去空）；读不到时回落 ("text",)。"""
    try:
        from . import audit
        rules, _src, _err = audit.resolve_rulebook()
        kinds = [str(k).strip() for k in (rules or {}).get("required_kinds") or []]
        kinds = [k for k in kinds if k]
        return tuple(kinds) or (TEXT_KIND,)
    except Exception:                                  # noqa: BLE001
        return (TEXT_KIND,)


def needs_marks(kind):
    """该 kind 是否受六要素约束。kind 缺失按 text 算（保留现状，不静默豁免）。"""
    k = (str(kind or "").strip() or TEXT_KIND)
    return k in required_kinds()


def is_exempt(fm):
    """fm 显示的 content_kind 是否把该节点排除在六要素之外。"""
    return not needs_marks((fm or {}).get("content_kind"))


def completeness(content, fm=None):
    """nodefile.ccg_completeness 的同口径包装：额外带 exempt 标记。"""
    from . import nodefile
    cpl = dict(nodefile.ccg_completeness(content))
    cpl["exempt"] = bool(fm is not None and is_exempt(fm))
    cpl["required_kinds"] = list(required_kinds())
    return cpl
