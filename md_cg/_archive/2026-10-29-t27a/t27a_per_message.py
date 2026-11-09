# -*- coding: utf-8 -*-
r"""t27a_per_message —— 日常对话**逐条**判断存亡（E-T27a / run t27a-20261011）。

## 来源与作用

目标 T27「日常对话逐条判断存亡，不搞一刀切」的执行项 E-T27a：本模块是它的
**驱动面**——把一段多轮对话按消息拆开，**一条消息一次**送判，返回逐条结论。

判据真源是 `md_cg/judgment_rules.py` 的 J1–J11 判据表（E-T18a t1）。本模块
**零复制**判据：不写任何词表、正则、优先级，也不发明 state 取值，只做三件事——

  ① 把每条消息归一成 `role` / `text` 两字段；
  ② 逐条调 `judgment_rules.judge_event({"role": …, "text": …})`；
  ③ 从 verdict 里取 `state` / `judge` / `evidence` 原样收集。

## 为什么是逐条而不是整段

整段拼接会把一段对话**坍缩成一个事件**：判据表内部按 `_PRIORITY` 取最高优先级
（丢在前），于是只要有**一条**消息命中 DROP 类词表，整段对话就一起被判丢——
这正是 T27 要避免的「一刀切」。逐条判定下，同一段对话里长期偏好（J1）留、
一次性交代（J7）丢、技术结论（J4）留，各自独立成立，互不牵连。

## 诚实口径（关断不是伪判）

总开关关闭时（`judgment_rules.is_enabled()` 为 False）就是关了：本函数返回
`[]`——**空列表如实表示「没有逐条判定结果」**，绝不伪判成一批 keep/drop 来
冒充「判过了」。调用方判断是否判过，看 `judgment_rules.is_enabled()` 或
`len(result) == 0` 两个信号之一（二者在关断时一致）。

开关的取值口径**恒定读 `judgment_rules`，本模块不硬编码**：`is_enabled()` 是
真源，本驱动只读它的当前返回值。

## 用法

    from md_cg.t27a_per_message import per_message_verdicts
    verdicts = per_message_verdicts([{"role": "user", "text": "…"},
                                     {"role": "assistant", "text": "…"}])
    for v in verdicts:
        v["index"], v["role"], v["text"], v["state"], v["judge"], v["evidence"]

测试：`python -X utf8 -m md_cg.test_t27a_per_message`
"""

from __future__ import annotations

from . import judgment_rules as jr

__all__ = ["per_message_verdicts", "map_role", "VERDICT_KEYS", "DISABLED"]

#: 每条 verdict 的键集（**恰好五个**；顺序即返回顺序，测试与下游按它断言形状）。
VERDICT_KEYS = ("index", "role", "text", "state", "judge", "evidence")

#: 三态归一的取值集合——直接引用规则表常量，本模块不新增状态、不改取值。
STATES = jr.STATES

#: 总开关关断时的返回体：空列表（如实报 disabled，不伪判）。
DISABLED: list = []

#: 缺省 role/text 的字段名推断表：先按这些常见键名找，找不到再回落。
#: 顺序即优先级——越靠前越「像」该字段。
_ROLE_KEYS = ("role", "speaker", "from", "author", "sender", "who", "name")
_TEXT_KEYS = ("text", "content", "message", "body", "msg", "utterance",
              "value", "say")


# 生效条件：role_map 为假值（None）时原样返回 role；为可调用时调它取返回值；
# 为 dict 时按键查表、**缺键回落原 role**（映射是改写不是过滤，没配的 role
# 不该凭空消失）；其余形状同样回落原 role。永不抛异常（判定驱动不因映射坏）。
def map_role(role, role_map=None):
    """把一条消息的 role 经 role_map 映射（None=原样；dict 缺键=原样）。"""
    if role_map is None:
        return role
    try:
        if callable(role_map):
            return role_map(role)
        if isinstance(role_map, dict):
            return role_map.get(role, role)
    except Exception:
        return role
    return role


# 生效条件：按 _ROLE_KEYS / _TEXT_KEYS 的顺序在映射里找第一个存在的键，返回其值；
# 一个都没有时返回 None（调用方据此回落）。
def _first_key(mapping, keys):
    """在 mapping 里按 keys 顺序取第一个存在的键值（都没有返回 None）。"""
    for k in keys:
        if k in mapping:
            return mapping[k]
    return None


# 生效条件：role_map 为 None 时按 _ROLE_KEYS / _TEXT_KEYS 推断字段名；否则
# role_map 既然是「把输入消息的字段映射成 role/text」，先看它是否**直接就是**
# 字段名映射（如 {"content": "text", "speaker": "role"}）——命中即按它取键；
# 没命中该形状时就退回按常见键名推断（此时 role_map 只用于改写 role 取值）。
# _first_key 在映射里按 keys 顺序取第一个存在的键值（都没有返回 None）。
def _pick_fields(m, role_map=None):
    """从一条消息里取出 (role, text) 两字段；缺键回落 None。"""
    if not isinstance(m, dict):
        # 坏形状条目：不静默丢——按属性取样，让判据表按它自己的口径判。
        role = getattr(m, "role", None)
        text = getattr(m, "text", m)
        return role, text

    role, text = None, None
    if isinstance(role_map, dict) and role_map:
        # 「字段名映射」形态：值为目标字段名（role/text），键为源字段名。
        # 只认值为 role/text 的条目，避免与「role 取值映射」形态混淆。
        target = {}
        for src, dst in role_map.items():
            if dst in ("role", "text") and isinstance(src, str):
                target.setdefault(dst, src)
        if target:
            if "role" in target:
                role = m.get(target["role"])
            if "text" in target:
                text = m.get(target["text"])

    if role is None:
        role = _first_key(m, _ROLE_KEYS)
    if text is None:
        text = _first_key(m, _TEXT_KEYS)
    return role, text


# 生效条件：is_enabled() 为 True 时返回 list[dict]——与输入等长且同序，每条
# **恰好五键** index/role/text/state/judge/evidence，state ∈ STATES；
# 为 False（总开关关闭）时返回 []——空列表如实表示没有判定结果（不伪判）。
# 非 list/tuple 的 messages 视为空对话（返回 []，不抛异常）。
def per_message_verdicts(messages, role_map=None) -> list:
    """对一段多轮对话**逐条**判定存亡，返回逐条结论列表。

    参数：
        messages  —— 真实多轮对话，形如
                     `[{"role": "user", "text": "…"},
                       {"role": "assistant", "text": "…"}, …]`。
                     每条按常见键名取 role / text：
                     role ← role/speaker/from/author/sender/who/name，
                     text ← text/content/message/body/msg/utterance/value。
                     缺键回落 None（判据表按它自己的口径处理空值）。
        role_map  —— 可选。两种形态：
                     ① 「字段名映射」`{"content": "text", "speaker": "role"}`：
                        告诉本函数输入消息的字段叫什么；
                     ② 「role 取值映射」dict `{"assistant": "user"}` 或可调用
                        `lambda role: …`：把 role 的**值**先改写再送判
                        （规则表只认 user/assistant/tool-output 等角色）。
                     None 时全部按常见键名推断、role 原样送判。

    返回 list[dict]：
        与输入 messages **一一对应、条数相等**，顺序与输入一致；每条**恰好
        五个键**：
            index    —— 0-based，连续 0..n-1
            role     —— 映射后的 role
            text     —— 原文
            state    —— keep / drop / keep_life（取自 verdict，∈ jr.STATES）
            judge    —— 判据 id（如 "J1"…"J11"）
            evidence —— 命中证据片段列表

        **总开关关闭时返回 `[]`**（如实报 disabled，不伪判成 keep/drop）。

    判定**全部委托** `judgment_rules.judge_event`：
        event = {"role": <映射后 role>, "text": <原文>}
    本模块不复制任何判据规则、不发明 state 取值；state/judge/evidence 三个
    键直接取 verdict 的同名键。**逐条调**——绝不把整段对话拼成一个事件再判。
    """
    if not jr.is_enabled():
        # 总开关关断：如实报 disabled。返回空列表，不伪判、不伪造逐条结果。
        return []

    msgs = messages if isinstance(messages, (list, tuple)) else []
    verdicts = []
    for i, m in enumerate(msgs):
        role, text = _pick_fields(m, role_map)
        role = map_role(role, role_map)
        verdict = jr.judge_event({"role": role, "text": text})
        verdicts.append({
            "index": i,
            "role": role,
            "text": text,
            "state": verdict.get("state"),
            "judge": verdict.get("judge"),
            "evidence": list(verdict.get("evidence") or []),
        })
    return verdicts
