# -*- coding: utf-8 -*-
"""unresolved 层：已知不知道、且还没结案（P3-4 生产者）。

背景（设计真源 `D:\\wook\\audit\\MEMORY-DESIGN-p34-p35-2026-10-29.md`）：
  `unresolved` 是 `admission.gate()` 的 R2 闸门计数对象
  （`md_cg/admission.py:118 LAYERS_SAY_NO = ("rejected", "unresolved")`），
  但全库**没有任何代码路径写它** ⇒ R2 恒红（`short_missing: ["unresolved"]`），
  `review` 侧也永远少一路「我知道我不知道」。本模块补的就是这个生产者。

三条纪律：
  1. **不抛**：所有入口对主检索是旁路，异常一律吞掉（写不进去不能把检索弄挂）。
  2. **幂等**：同一问题（同正文）只落一个节点，`nid = unr_<sha12(question)>`。
  3. **有上限**：`note_miss` 每日最多写 `MDCG_UNRESOLVED_DAILY_CAP`（默认 20）条，
     超了只计数不落盘——这是给「检索无果」用的自动口，不能变成写放大。

字段（frontmatter，`_CCG_EXEMPT_LAYERS` 已含 unresolved，正文按纯文本写）：
  question / blocker / closes_when / first_seen / recheck_after / attempts / source
"""
import hashlib
import os
import time

LAYER = "unresolved"
PREFIX = "unr_"
DEFAULT_CAP = 20
RECHECK_DAYS = 7
#: 复现判定宽限：last_access 比 created_at 晚出这么多秒才算「复查期内被再访问」
#: （同一次写入的尾部访问不动 last_access，故不会把新条目误判成活的）。
REPROOF_GRACE = 3600
#: 单轮最多结案条数：到期项可能成百，一次改太多无法复核。
RECHECK_DEFAULT_CAP = 10
#: 检索无果自动登记的总开关。默认关——它自动产出的条目 90% 是问句碎片
#: （「记忆 检索 缺陷」「阿里云欠费」），进了 unresolved 就变成元认知建议里的
#: 「11 个未解问题」，反过来驱动建更多噪声。
MISS_ENABLED = os.environ.get("MDCG_UNRESOLVED_MISS", "0").strip() == "1"
_QUESTION_WORDS = ("吗", "什么", "怎么", "为何", "为什么", "哪", "是否", "如何",
                   "谁", "多少", "能不能", "要不要", "有没有")


# 生效条件：q 去空白后长度 < 8 返回 False；含疑问词返回 True；否则长度 >= 16 返回 True。
# 这是「可回答性」的粗闸，不是语义判定——它的职责只是拦掉碎片式输入，
# 不负责判断问题是否值得问（那要人）。
def _answerable(q):
    s = "".join(str(q or "").split())
    if len(s) < 8:
        return False
    if any(w in s for w in _QUESTION_WORDS):
        return True
    return len(s) >= 16


def _nid(question):
    return PREFIX + hashlib.sha256(question.encode("utf8")).hexdigest()[:12]


def _iso(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t if t is not None else time.time()))


def _exists(cg, nid):
    nodes = (cg.index or {}).get("nodes") or {}
    if nid in nodes:
        return True
    return bool(cg.get(nid, probe=True))


def _body(question, blocker, closes_when, source, first_seen, recheck_after):
    return ("# 问题：%s\n"
            "# 卡在：%s\n"
            "# 何时算结案：%s\n"
            "# 首次出现：%s\n"
            "# 复查：%s\n"
            "# 来源：%s\n") % (question, blocker or "未写明",
                               closes_when or "未写明", first_seen,
                               recheck_after, source)


def log(cg, question, blocker="", closes_when="", source="manual", session=None):
    """登记一条「已知不知道」。幂等；返回 {ok, id, created}。"""
    q = (question or "").strip()
    if len(q) < 4:
        return {"ok": False, "error": "question_too_short"}
    nid = _nid(q)
    if _exists(cg, nid):
        return {"ok": True, "id": nid, "created": False}
    now = time.time()
    body = _body(q, blocker, closes_when, source, _iso(now),
                 _iso(now + RECHECK_DAYS * 86400))
    kw = dict(layer=LAYER, tags=["unresolved", "producer:" + source],
              importance=0.3, sensitivity="internal",
              verification_basis="other", effective_from=now)
    if session:
        kw["session"] = session
    cg.add(nid, body, **kw)
    return {"ok": True, "id": nid, "created": True}


def _today_count(cg, root_node_ids):
    nodes = (cg.index or {}).get("nodes") or {}
    today = time.strftime("%Y-%m-%d")
    n = 0
    for nid in root_node_ids:
        ent = nodes.get(nid) or {}
        if time.strftime("%Y-%m-%d", time.localtime(ent.get("created_at") or 0)) == today:
            n += 1
    return n


def note_miss(cg, query, layer=None, cap=None):
    """检索无果 → 登记一条。带日上限；从不抛。"""
    try:
        if not MISS_ENABLED:
            return {"ok": False, "skipped": "disabled",
                    "hint": "检索无果自动登记默认关闭；MDCG_UNRESOLVED_MISS=1 才启用"}
        limit = DEFAULT_CAP if cap is None else int(cap)
        nodes = (cg.index or {}).get("nodes") or {}
        ids = [k for k, v in nodes.items() if v.get("layer") == LAYER]
        if _today_count(cg, ids) >= limit:
            return {"ok": False, "skipped": "daily_cap"}
        q = (query or "").strip()
        if not q:
            return {"ok": False, "skipped": "empty"}
        if not _answerable(q):
            return {"ok": False, "skipped": "not_answerable", "query": q,
                    "hint": "问句过短或不像可回答的问题，不落 unresolved"}
        return log(cg, q,
                   blocker="检索 0 命中（层=%s）" % (layer or "any"),
                   closes_when="库里出现能回答它的节点，或改写问题后命中",
                   source="search_miss")
    except Exception as exc:  # noqa: BLE001 —— 旁路，绝不影响检索
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


def listing(cg, limit=20):
    nodes = (cg.index or {}).get("nodes") or {}
    rows = [(v.get("created_at") or 0, k) for k, v in nodes.items() if v.get("layer") == LAYER]
    rows.sort(reverse=True)
    out = []
    for _, nid in rows[:limit]:
        n = cg.get(nid) or {}
        out.append({"id": nid, "created_at": n.get("created_at"),
                    "body": (n.get("content") or "")[:200]})
    return {"ok": True, "count": len(rows), "items": out}


def close(cg, nid, resolution="", to_layer="knowledge"):
    """结案：把未解问题移出 unresolved（默认升层到 knowledge 并记结论）。"""
    n = cg.get(nid)
    if not n:
        return {"ok": False, "error": "not_found"}
    body = (n.get("content") or "") + "\n# 已结案：%s\n# 结案时间：%s\n" % (
        resolution or "已解决", _iso())
    cg.add(nid, body, layer=to_layer, tags=["resolved", "from:unresolved"],
           importance=0.5, sensitivity=n.get("sensitivity") or "internal",
           override=True)
    return {"ok": True, "id": nid, "to_layer": to_layer}


# 生效条件：**发现**与**处置**分开——遍历 unresolved 层，列出「created_at 早于
# days 天前、且 last_access 未晚于创建后 REPROOF_GRACE 秒」的条目（复查期内没复现），
# 每条附问题正文与龄期；只有在显式给出 ids 且 dry_run=False 时才结案那些点名的条目
# （走 close，改层不删文件）。不给 ids 一律只读。返回 {ok, dry_run, days, scanned,
# aged, candidates[{id,question,age_days}], picked, closed, cap, skipped}；
def recheck(cg, days=None, cap=None, dry_run=True, ids=None, to_layer="rejected"):
    """到期复查：给清单，处置由调用方点名。

    为什么**不**按龄自动批量结案（2026-11-05 实测）：本库里真实待办与噪声结构同形
    （同 `producer:search_miss`、`importance` 0.3、`access_count` 0、`last_access` 0），
    唯一差别是问题正文。用「到期 + 没复现」自动结案，会把「阿里云欠费」这类真问题
    一并清掉——那正是这次要修的病，不能换个方向再犯一次。
    """
    try:
        limit = RECHECK_DEFAULT_CAP if cap is None else int(cap)
        span = (RECHECK_DAYS if days is None else int(days)) * 86400
        now = time.time()
        nodes = (cg.index or {}).get("nodes") or {}
        scanned = aged = 0
        candidates = []
        for nid, ent in nodes.items():
            if (ent or {}).get("layer") != LAYER:
                continue
            scanned += 1
            created = float((ent or {}).get("created_at") or 0)
            if not created or now - created < span:
                continue
            aged += 1
            last = float((ent or {}).get("last_access") or 0)
            if last - created > REPROOF_GRACE:
                continue                      # 复查期内被再访问过 ⇒ 还活着
            candidates.append({
                "id": nid,
                "question": _question(cg, nid),
                "age_days": round((now - created) / 86400.0, 1),
            })
        candidates.sort(key=lambda c: (-c["age_days"], c["id"]))
        picked = [c["id"] for c in candidates[:max(0, limit)]]
        closed = []
        skipped = []
        if not dry_run:
            if not ids:
                return {"ok": True, "dry_run": True, "days": span // 86400,
                        "scanned": scanned, "aged": aged, "candidates": candidates,
                        "picked": picked, "closed": [], "cap": limit,
                        "skipped": [], "no_ids": True,
                        "note": "只出清单：结案要点名 ids（防止把真待办当噪声清掉）"}
            wanted = [str(i) for i in ids]
            picked = wanted[:max(0, limit)]
            cand_ids = {c["id"] for c in candidates}
            for nid in picked:
                if nid not in cand_ids:
                    skipped.append({"id": nid, "why": "不在候选里（未到期或复查期内复现过）"})
                    continue
                r = close(cg, nid,
                          resolution="复查期内未复现（%d 天），人工点名结案" % (span // 86400),
                          to_layer=to_layer)
                if r.get("ok"):
                    closed.append(nid)
                else:
                    skipped.append({"id": nid, "why": r.get("error") or "close 失败"})
        return {"ok": True, "dry_run": bool(dry_run), "days": span // 86400,
                "scanned": scanned, "aged": aged, "candidates": candidates,
                "picked": picked, "closed": closed, "cap": limit, "skipped": skipped,
                "to_layer": to_layer}
    except Exception as exc:                   # noqa: BLE001 —— 维护旁路，绝不拖垮调用方
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


def _question(cg, nid):
    """取问题正文（只读：`probe=True` 不推进 last_access，避免复查把证据改掉）。"""
    try:
        n = cg.get(nid, probe=True) or {}
    except Exception:                          # noqa: BLE001
        return ""
    for line in (n.get("content") or "").splitlines():
        if line.startswith("# 问题："):
            return line[len("# 问题："):].strip()
    return ""
