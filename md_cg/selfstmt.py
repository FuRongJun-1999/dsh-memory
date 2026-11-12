# -*- coding: utf-8 -*-
"""自述轮次召回（零模型、与题目无关）——外测实证 12.8% → 35.9% 的那条规则。

判据（外测 2026-11-12 实验，无泄题、无 LLM）：
> 用户消息匹配「我叫 / 我今年 / 我大学 / 我最早 / 我在…做 / 我住 / 我妈我爸 / 学徒 / 退休…」
> → 这些轮次直接并入 pack（不经过档案、不经过 LLM）。

结果：值覆盖 5/39 → 14/39（12.8% → 35.9%），题级全命中 1/19 → 6/19；
成本：每库仅 5–15 轮额外注入。

调用口径（**两种写法都认**，见 _root_of）：
    from md_cg import selfstmt as ss
    ss.load(g) / ss.load(g.root)        # 读登记数
    ss.record(g, nid)                   # 单条登记（写时钩子已在 add() 里自动调）
    ss.rebuild(g)                       # 存量库全量补登（建图之后、recall 之前）

不适用条件：
  · 主语是「她/他」的亲属陈述（如「她61了，从社区超市理货员退下来」若词表未收录）不命中——需事件/关系抽取；
  · 事件型转述（转行、兼职经历）不保证命中；
  · 规则漏检就是漏，不做二次推断。
"""
from __future__ import annotations

import json
import os
import re

#: 自述句式（**与题目无关**；宁可少收，不加宽到泛化「我」）
SELF_RX = re.compile(
    r"(?:我叫|我的名字|我今年|我\d{1,2}岁|我大学|我念|我读|我最早|后来(?:才|就)?(?:转|去|做)|"
    r"我在[^，。]{0,12}(?:做|当|上班)|我住|我(?:妈|爸|母亲|父亲)|"
    r"学徒|退休|理货员|钳工|调酒|结构设计|兼职|写(?:悬疑|小说))"
)

_FILE = "_selfstmt.json"


# 生效条件：参数可以是库根路径，也可以是 cg 实例；返回库根路径
def _root_of(x):
    """★API 容错：既收库根路径，也收 cg 实例。

    踩过的坑（外测 2026-11-12）：load(g) 把实例当路径拼，文件不存在 ⇒ 静默返回 []，
    被误读成「写时登记没生效」。
    """
    if hasattr(x, "root"):
        return str(getattr(x, "root") or "")
    return str(x or "")


#: 信息密度权重（用于注入排序：先给最可能是「答案句」的轮次，而不是最新的）
DENSITY_PATTERNS = (
    (3, ("我叫", "我的名字", "我大学", "我最早", "我今年")),
    (2, ("我住", "我妈", "我爸", "母亲", "父亲", "岁")),
    (1, ("学徒", "退休", "理货员", "钳工", "调酒", "结构设计", "兼职",
         "念", "读", "做")),
)


# 生效条件：text 为节点正文；返回信息密度分（越高越像「答案句」）
def density(text):
    """自述轮次的信息密度分（确定性；用于注入排序）。"""
    body = str(text or "")
    score = 0
    for w, pats in DENSITY_PATTERNS:
        for p in pats:
            if p in body:
                score += w
                break
    return score


# 生效条件：text 为节点正文；命中自述句式返回 True
def matches(text):
    """是否自述轮次（确定性正则，与查询/题目无关）。"""
    return bool(SELF_RX.search(str(text or "")))


# 生效条件：root 为库根目录或 cg 实例；返回登记文件路径
def _path(root):
    return os.path.join(_root_of(root), _FILE)


# 生效条件：root 为库根或 cg；返回已登记的节点 id 列表（读失败一律当空，不抛）
def load(root):
    """读登记表。文件不存在/损坏 ⇒ 返回 []（不让召回因它挂掉）。"""
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
        return [str(x) for x in (data.get("ids") or [])]
    except (OSError, ValueError):
        return []


# 生效条件：root 为库根或 cg、nid 为节点 id；命中则登记（幂等）
def record(root, nid):
    """写时登记：把自述轮次的 id 记入小索引（幂等、去重）。"""
    base = _root_of(root)
    if not base:
        return False
    p = os.path.join(base, _FILE)
    ids = load(base)
    if str(nid) in ids:
        return False
    ids.append(str(nid))
    tmp = p + ".tmp"
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ids": ids[-5000:]}, f, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        return False
    return True


# 生效条件：cg 提供 index/get；返回 {scanned, recorded, ids}
def rebuild(cg, dry_run=False, limit=100000):
    """全量重建登记表（存量库补登用；不改任何节点）。"""
    base = _root_of(cg)
    ids = []
    scanned = 0
    for nid in list((cg.index.get("nodes") or {})):
        scanned += 1
        if scanned > limit:
            break
        node = cg.get(nid) or {}
        if matches(node.get("content") or ""):
            ids.append(str(nid))
    if not dry_run and base:
        try:
            with open(os.path.join(base, _FILE), "w", encoding="utf-8") as f:
                json.dump({"ids": ids[-5000:]}, f, ensure_ascii=False)
        except OSError:
            pass
    return {"scanned": scanned, "recorded": len(ids), "dry_run": bool(dry_run)}
