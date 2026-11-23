# -*- coding: utf-8 -*-
"""价值观闸（v0.4 首次接线，2026-11-17）。

背景：`docs/architecture/唯一的价值观_可被追责_v0.3.md` + 节点
`identity_trait_self_lingshu_1c1554bf7d`（structural，v0.4）确立了价值观根节点，
但装置此前只被 `identity`/`evidence` 读，**写入链与判定面零引用**——
即 v0.2 记的那个断点：意义只有叙事，没有约束力。本模块把它接进写入链。

## 判据只有两条，都可机械判定（不做语义裁决）

1. **禁止项命中**：价值观条款可携带 `values_forbid`（正则列表），命中即 deny。
2. **可归因**：写 结构/自我/锚点 层时，正文须能指回一条已声明条款
   （条款 node_id 或其 `values_keys` 关键词）。指不回 ⇒ 追责链断裂 ⇒ flag。

## 为什么不做语义裁决

「内容是否符合某条自然语言价值观」判定不了；硬做只会得到噪声。
能机械判定的是**可归因**与**显式禁止项**——这两条恰好就是
「可被追责」的工程含义：**这条写入能指回哪一条我可被追责的承诺？**

## 档位

`MDCG_VALUES_GATE`：off / observe（缺省）/ enforce。
缺省 observe：只记录、放进写入结果，不拦。理由与写入闸一致——
先观察再收紧，不拿新规则直接挡人。

## 诚实边界

- 只覆盖 tier ≥ 2（结构/自我/锚点）的写入；知识/情景层不查（量太大，且低风险）。
- 条款为空时**不拦也不假装有**：没建价值观就不该收门票。
- observe 档只会留下读数，不产生任何阻断行为。
"""

from __future__ import annotations

import os
import re

MODE_ENV = "MDCG_VALUES_GATE"
TAG = "identity_trait"
MAX_CLAUSES = 50

_STATS = {"checked": 0, "flagged": 0, "denied": 0}


def gate_mode(environ=None):
    """当前档位（off / observe / enforce，缺省 observe）。非法值 fail-open 到 observe。"""
    env = os.environ if environ is None else environ
    raw = str(env.get(MODE_ENV) or "observe").strip().lower()
    return raw if raw in ("off", "observe", "enforce") else "observe"


def stats():
    """只读读数（供 cg(op=info) 或排障）。"""
    return dict(_STATS)


def _keys_of(cg, nid, fm):
    """条款的归因关键词：显式 values_keys 优先；否则取正文首行的前 24 字。"""
    keys = fm.get("values_keys")
    if isinstance(keys, (list, tuple)) and keys:
        return [str(k).strip() for k in keys if str(k).strip()]
    try:
        node = cg.get(nid) or {}
        first = (node.get("content") or "").strip().splitlines()
        head = first[0] if first else ""
    except Exception:
        head = ""
    # 归因键取**标题首段**：条款正文首行常是「标题：展开说明」，
    # 整行当键永远匹配不上（实测：内容里写「依据：可被追责」判不归因）。
    # 故按中英文冒号切段，取第一段；过长再截 12 字。
    for sep in ("：", ":", "——", "-"):
        if sep in head:
            head = head.split(sep, 1)[0].strip()
            break
    head = head[:12]
    return [head] if head else []


def clauses(cg):
    """收集已声明的价值观条款（structural 层 + TAG）。条款为空返回 []。"""
    idx = dict((getattr(cg, "index", {}) or {}).get("nodes") or {})
    out = []
    for nid, e in idx.items():
        tags = (e or {}).get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        if TAG not in [str(t) for t in tags]:
            continue
        # 读**文件**取条款字段：索引只落固定键集（values_forbid 这类扩展键
        # 不在其中）——实测 add(values_forbid=...) 落盘有、索引无。
        # 条款数极小（上限 50），逐条读盘可接受。
        try:
            fm = (cg.get(nid) or {}).get("frontmatter") or {}
        except Exception:
            fm = e or {}
        forbid = fm.get("values_forbid") or []
        if isinstance(forbid, str):
            forbid = [forbid]
        out.append({"node_id": nid,
                    "keys": _keys_of(cg, nid, fm),
                    "forbid": [str(p) for p in forbid if str(p).strip()]})
        if len(out) >= MAX_CLAUSES:
            break
    return out


def _log(cg, rec):
    """逐次留痕（best-effort）：价值观判定必须可查，否则等于没查。"""
    import json, os, time
    try:
        path = os.path.join(getattr(cg, "root", "") or ".", "_values.jsonl")
        rec = dict(rec)
        rec["t"] = time.time()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except Exception:
        pass


def check(cg, a, content):
    """判定一次写入。返回 verdict dict 或 None（不适用/未启用）。"""
    mode = gate_mode()
    if mode == "off":
        return None
    from . import writegate as _wg
    layer = str((a or {}).get("layer") or "knowledge").strip().lower()
    if _wg.tier_of(layer) < 2:
        return None
    cls = clauses(cg)
    if not cls:
        return None
    text = str(content or "")
    _STATS["checked"] += 1
    for c in cls:
        for pat in c["forbid"]:
            try:
                hit = re.search(pat, text)
            except re.error:
                continue
            if hit:
                _STATS["denied"] += 1
                _log(cg, {"decision": "deny", "layer": layer, "clause": c["node_id"]})
                return {"decision": "deny", "mode": mode, "clause": c["node_id"],
                        "reason": "命中价值观禁止项：%s" % pat}
    cited = [c["node_id"] for c in cls
             if c["node_id"] in text or any(k and k in text for k in c["keys"])]
    if cited:
        _log(cg, {"decision": "allow", "layer": layer, "clause": cited[0]})
        return {"decision": "allow", "mode": mode, "clause": cited[0], "reason": "可归因"}
    _STATS["flagged"] += 1
    _log(cg, {"decision": "flag", "layer": layer})
    return {"decision": "flag", "mode": mode, "clause": None,
            "reason": "该写入无法指回任何已声明价值观条款（追责链断裂）",
            "clauses": [c["node_id"] for c in cls]}
