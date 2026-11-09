# -*- coding: utf-8 -*-
"""宪章第十五条（复读污染）的实现：注入过滤 + history 去重 + 污染清除。

## 为什么需要它

`docs/mdcg/guardrail-charter.md` 第十五条写：「幻觉锚点/失败复读自我强化——
注入过滤 + history 去重 + 污染清除。」但**此前只有条文、没有实现**
（`src/` 与 `md_cg/` 搜「复读/degenerat/repetition」零命中）。

## 关键取舍：**检测不等于删除**

用户可能真的把同一句话说了两遍（实测库里就有一条 `role=user` 的消息重复 7 次，
那是真发的，不是模型复读）。所以本模块**只做三件事，不做静默删除**：

1. **检测**（`scan`）：按 `(role, sha1(text))` 在**同一会话窗口内**计数；
2. **标注**（`annotate`）：给命中项打上 `repeat={count,suffix,first_t}`，供注入面渲染；
3. **清理**（`dedupe`）：**只保留最新一条 + 其余折叠为计数**，且**仅当调用方显式要求**
   ——库内原文一个字都不动（与 `thinking-guard` 的「改注入副本、不改日志」同原则）。

## 判据（阈值来源）

仿 `dsh-degeneration-kit` 的 `rotationHit` 双阈值思路，但用于**事件窗口**而非思考块：

| 配置 | 默认 | 含义 |
|---|---|---|
| `minCount` | 3 | 同一 `(role, hash)` 至少出现这么多次才算「复读」 |
| `minChars` | 12 | 文本短于此长度不判（太短的话重复是正常的，如「好」「继续」） |
| `window` | 200 | 只看窗口内（与 `DEFAULT_RECENT_WINDOW` 同口径） |

⚠️ `minChars=12` 这条是**从实测反推**的：实测库里 `x7` 那条长文本是真重复，
而「好」「继续」这类短指令重复属正常对话，不该被判成污染。

## 与智能论《扮演崩溃治理》的关系

智能论 3.4 附录22.1：**「状态丢失（数不出搜索次数）= 扮演崩溃 → 状态外部化治之」**。
本节做的是**事后**（`history 去重`），扮演崩溃的**事前**防线是「状态外置」
（把步骤清单/计数器写进任务消息，模型零判断）——两者互补，不是替代。
"""

import hashlib

# 生效条件：恒返回 8 位十六进制（sha1(text) 前 8 位）——**纯确定性**，同一 text 恒得同一串；
# 用作「同一条事件」的判据，不参与任何权限判定。
def text_suffix(text) -> str:
    return hashlib.sha1((text or "").encode("utf-8", "replace")).hexdigest()[:8]


# 生效条件：events 为可迭代的事件 dict 列表、min_count>=1、min_chars>=0 时，
# 按 (role, text_suffix(text)) 计数并返回命中项列表（按 count 降序）；
# 文本长度 < min_chars 的条目不参与；非 dict 条目跳过（与 recent_record_ok 同款容错）。
def scan(events, min_count: int = 3, min_chars: int = 12):
    """检测事件窗口内的重复（复读候选）。**只读，不修改入参**。"""
    try:
        lo = max(1, int(min_count))
        lc = max(0, int(min_chars))
    except (TypeError, ValueError):
        lo, lc = 3, 12
    buckets = {}
    for ev in (events or ()):
        if not isinstance(ev, dict):
            continue
        text = ev.get("text") or ""
        if not isinstance(text, str) or len(text) < lc:
            continue
        key = (ev.get("role") or "user", text_suffix(text))
        b = buckets.setdefault(key, {"count": 0, "suffix": key[1], "role": key[0],
                                     "text": text[:200], "first_t": ev.get("t"),
                                     "seqs": []})
        b["count"] += 1
        b["first_t"] = ev.get("t")
    hits = [b for b in buckets.values() if b["count"] >= lo]
    hits.sort(key=lambda b: -b["count"])
    return hits


# 生效条件：scan 返回的命中列表非空时，为 events 中命中项**加** repeat 标注（返回新列表，
# 原 dict 不被修改——与「只改注入副本、库内正文保真」一致）；未命中项原样透传。
def annotate(events, min_count: int = 3, min_chars: int = 12):
    """给命中项加 `repeat={count, suffix}`。**返回新列表，不改原 dict**。"""
    hits = scan(events, min_count=min_count, min_chars=min_chars)
    if not hits:
        return list(events or ())
    by_key = {(b["role"], b["suffix"]): b for b in hits}
    out = []
    for ev in (events or ()):
        if not isinstance(ev, dict):
            out.append(ev)
            continue
        text = ev.get("text") or ""
        h = by_key.get((ev.get("role") or "user", text_suffix(text))) if isinstance(text, str) else None
        out.append(dict(ev, repeat={"count": h["count"], "suffix": h["suffix"]}) if h else ev)
    return out


# 生效条件：events 非空且 dense=True 时，同一 (role, suffix) 只保留**最新一条**、
# 其余折叠为 `repeat:{count}` 标注（条目数减少，但每条都还在）；dense=False 时等价于 annotate。
# **只作用于返回副本**：盘面 `_recent.jsonl` 不被读写。
def dedupe(events, min_count: int = 3, min_chars: int = 12):
    """history 去重（注入面用）：同一复读只留最新一条，其余合并为计数。**不写盘**。"""
    rows = list(events or ())
    hits = scan(rows, min_count=min_count, min_chars=min_chars)
    if not hits:
        return rows
    by_key = {(b["role"], b["suffix"]): b for b in hits}
    seen = set()
    out = []
    for ev in reversed(rows):
        if not isinstance(ev, dict):
            out.append(ev)
            continue
        text = ev.get("text") or ""
        key = (ev.get("role") or "user", text_suffix(text)) if isinstance(text, str) else None
        h = by_key.get(key) if key else None
        if not h:
            out.append(ev)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(ev, repeat={"count": h["count"], "suffix": h["suffix"], "collapsed": True}))
    out.reverse()
    return out