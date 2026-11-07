# -*- coding: utf-8 -*-
"""确定性重排（detrerank）——检索结论的**唯一裁决口**。

裁定（structural: mem_ruling_vector_ref_deterministic）：
  向量/语义相似度 **只提供参考**（候选扩展），结论必须由**词法·时间·空间·交互**
   四类确定性信号重排，且**必须由确定性规则裁决**：固定常量 + 可数信号，
  同输入同输出（可对拍、可回放）。

为什么这样切：相似度回答「像不像」，因果观察三元组（时间/空间/交互）回答
「是不是真的发生过」，词法回答「原文对不对得上」。三者性质不同，
用一个浮点分数混合会让「像」压过「真」——这正是 #753/#790 那类 fail-open 的同源病。

确定性约束（本模块的三条硬纪律）：
  1. **无模型分**：函数体不得出现 embedding / 相似度 / 模型调用；
  2. **时钟显式**：`now` 必须由调用方传入（不内部取 time.time()），否则不可回放；
  3. **全序**：分数相同按 id 字典序兜底，保证任意两次结果逐位相同。
"""
from __future__ import annotations

import re

#: 四信号权重（固定常量；改值等于改裁决口径，必须走评审 + 读数）。
WEIGHTS = {
    "lexical": 4,      # 词法最重：原文对得上才算证据
    "interaction": 3,  # 交互次之：真的发生过作用
    "spatial": 2,      # 空间可达：在同域/同链路里
    "temporal": 1,     # 时间只做轻微加权（新旧不代表对错）
}

#: 时间衰减半衰期（天）——与 temporal 路同源口径，固定常量，不随环境变。
TEMPORAL_HALF_LIFE_D = 30.0


def _terms(text) -> list:
    return [t.lower() for t in re.split(r"[\s,，、;；。！？:：()（）\[\]【】]+", text or "")
            if len(t) >= 2]


def _snippet(node, limit: int = 1200) -> str:
    parts = [str(node.get("content") or "")[:limit]]
    fm = node.get("frontmatter") or {}
    for key in ("tags", "title", "conditions"):
        val = fm.get(key)
        if val:
            parts.append(str(val))
    return " ".join(parts).lower()


def signals(node, query_terms, now, session=None) -> dict:
    """四信号取值（全部确定性可数）。"""
    text = _snippet(node)
    # 词法：query 词项在原文/标签里的命中数（整数）
    lexical = sum(1 for t in query_terms if t in text)
    fm = node.get("frontmatter") or {}
    # 交互：出边数 + 入标记（edges 是「真的发生过作用」的痕迹）
    edges = fm.get("edges")
    out_edges = len(edges) if isinstance(edges, list) else 0
    refs = fm.get("derived_from") or fm.get("alias_of") or []
    refs_n = len(refs) if isinstance(refs, (list, tuple)) else (1 if refs else 0)
    interaction = out_edges + refs_n
    # 空间：同会话（同域）+ 同层（结构可达）——两个可数布尔
    same_session = 1 if (session and str(fm.get("session") or "") == str(session)) else 0
    layer = str(fm.get("layer") or "")
    spatial = same_session + (1 if layer in ("knowledge", "structural") else 0)
    # 时间：按半衰期衰减到 [0,1] 后取整到 3 位（确定性，无时钟读取）
    try:
        created = float(fm.get("created_at") or 0)
    except (TypeError, ValueError):
        created = 0.0
    if created > 0 and now:
        age_days = max(0.0, (float(now) - created) / 86400.0)
        temporal = round(0.5 ** (age_days / TEMPORAL_HALF_LIFE_D), 3)
    else:
        temporal = 0.0
    return {"lexical": lexical, "interaction": interaction,
            "spatial": spatial, "temporal": temporal}


def score(sig: dict) -> float:
    """加权和（整数权重 × 确定性信号），保留 6 位。"""
    total = 0.0
    for key, weight in WEIGHTS.items():
        total += float(weight) * float(sig.get(key) or 0)
    return round(total, 6)


def rerank(results, query, now, session=None):
    """对 [(node, fused_score, qual, prov), ...] 做确定性重排。

    返回新列表（不改入参）：按 (det_score desc, id asc) 全序。
    `now` 必须由调用方给（时钟显式，可回放）。
    """
    terms = _terms(query)
    scored = []
    for item in results or ():
        node = item[0]
        sig = signals(node, terms, now, session=session)
        scored.append((score(sig), str(node.get("id") or ""), sig, item))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(item, det, sig) for det, _nid, sig, item in scored]