# -*- coding: utf-8 -*-
"""记忆演化分支（Pi 机制移植④，交接文档 §3④「记忆演化 fork」，P0）。

pi：会话 = entry 树，任意历史节点可 fork；被放弃旁支由 branch_summary
归档定长摘要。灵枢映射（单一演化线 → 假设分支实验场）：

- fork：把主支节点复制成分支实验副本（fm.branch_id / branched_from），
  副本 derived_from=[主支]、relation="split_from"——血缘单向可回溯；
- 分支节点默认从主支检索隐身（_candidates 按 branch 过滤，一处生效
  全链路穿透）——实验不污染主支（验收：召回主支时分支节点零命中）；
- merge：按 branched_from 溯源回写主支（derived_from=[分支 nid] 追加进
  主支原链、relation="merged_from"），override 走快照——合并后链完整；
- discard：校验 BRANCH_MARKS 必填 → 写教训节点（knowledge 层、可检索）
  → 分支文件移入冷区 _branches/<id>/（物理保留、索引摘除、永不删除）。

与 writepipe 同哲学：库层函数收 cg，权限闸保持库层强制——
fork/merge 走 add 的 require_layer_write 自动覆盖；
discard 改变库可见性，需 can_admin（principal.require_admin）。
生命周期事件走 _audit.jsonl（③ 两段式载体，零新日志格式）。
"""

import os
import re
import uuid

#: discard 的 branch_summary 必填标记（复用 NEG_MEMORY_MARKS 的必填防呆模式：
#: 「假设 + 结果 + 教训」缺一不收——放弃分支必须留下可复用的教训）。
BRANCH_MARKS = ("分支假设", "实验结果", "教训")

#: 分支文件冷区（LAYERS 之外，_scan_nodes 不扫——天然不进索引与检索）。
COLD_DIR = "_branches"

_BRANCH_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def branch_tag(branch_id: str) -> str:
    """分支节点的标注 tag（fork 时写入；branch_summary 也带它以便反查）。"""
    return "branch:" + str(branch_id or "").strip().lower()


def branch_node_id(orig: str, branch_id: str) -> str:
    """分支副本 id：`<主支nid>@<branch_id>`（@ 文件名合法、撞名不可能）。"""
    return "%s@%s" % (orig, str(branch_id or "").strip().lower())


def _audit(cg, op: str, **meta) -> None:
    """生命周期留痕；审计失败绝不阻断主流程（G8 同哲学）。"""
    a = getattr(cg, "_audit", None)
    if a is None:
        return
    try:
        a(op, None, **meta)
    except Exception:
        pass


def _iter_branch_nodes(cg, branch_id: str):
    bid = str(branch_id or "").strip().lower()
    return [(k, v) for k, v in (cg.index.get("nodes") or {}).items()
            if v.get("branch_id") == bid]


def _fm_of(rec):
    """get 返回形态兼容：{'frontmatter': fm, 'content': c} 或平铺 fm。"""
    if not rec:
        return {}
    return rec.get("frontmatter") or rec


def fork(cg, node_ids, branch_id=None, note=None) -> dict:
    """把主支节点复制成分支实验副本。

    返回 {ok, branch_id, tag, forked:[{from,to}], skipped:[{id,why}]}。
    幂等：同 (主支节点, branch_id) 的副本已存在则 skipped，不重复复制。
    """
    ids = [str(x).strip() for x in (node_ids or []) if str(x).strip()]
    if not ids:
        return {"ok": False, "error": "node_ids 为空（至少指定一个主支节点）"}
    if branch_id is None:
        branch_id = "br_" + uuid.uuid4().hex[:8]
    branch_id = str(branch_id).strip().lower()
    if not _BRANCH_RE.match(branch_id):
        return {"ok": False, "error": "branch_id 非法（%s）：%r"
                % (_BRANCH_RE.pattern, branch_id)}
    forked, skipped = [], []
    for nid in ids:
        if "@" in nid:
            skipped.append({"id": nid, "why": "已是分支节点，不支持再 fork"})
            continue
        rec = cg.get(nid)
        if not rec:
            skipped.append({"id": nid, "why": "主支节点不存在或不可见"})
            continue
        fm = _fm_of(rec)
        bid = branch_node_id(nid, branch_id)
        if cg.get(bid):
            skipped.append({"id": nid, "why": "副本已存在：%s" % bid})
            continue
        cg.add(bid, rec.get("content") or "",
               layer=fm.get("layer") or "knowledge",
               role=fm.get("role"),
               tags=list(fm.get("tags") or []),
               condition_space=fm.get("condition_space"),
               importance=float(fm.get("importance", 0.5)),
               verification_basis=fm.get("verification_basis") or "test",
               non_applicable_conditions=fm.get("non_applicable_conditions"),
               consistency=False,
               derived_from=[nid], relation="split_from",
               branch_id=branch_id, branched_from=nid, branch_note=note,
               actor="branch_fork")
        forked.append({"from": nid, "to": bid})
    _audit(cg, "branch_fork", branch_id=branch_id,
           forked=[f["to"] for f in forked])
    return {"ok": bool(forked), "branch_id": branch_id,
            "tag": branch_tag(branch_id), "forked": forked, "skipped": skipped}


def search(cg, query: str, branch_id: str, **kw):
    """分支内检索：主支 + 本分支可见、其他分支隐身（_candidates branch 过滤）。"""
    return cg.search(query, branch=str(branch_id or "").strip().lower(), **kw)


# 生效条件：当 node_id 经 str 转换并 strip 后含 '@'、cg.index['nodes'] 中存在该 id 且其 branch_id 非空、content 不是 dict 且不是 None 时返回 {'ok': True, 'node': nid, 'branch_id': ...}，否则返回 {'ok': False, 'error': ...}。
def rewrite(cg, node_id, content, tags=None, importance=None,
            actor="branch_rewrite", **extra) -> dict:
    """分支实验改写的**唯一正路**（防裸 add 丢分支归属）。

    背景：add 是全量重建 fm——裸 add 改写分支节点而不重传 branch_id，
    节点会在索引里退化成主支（实验内容直接泄漏进主支检索）。本帮手：
    - 只接受在册分支节点（含 @ 且 entry.branch_id 在册）；
    - 归属与血缘（branch_id / branched_from / branch_note / derived_from /
      derived_relation）一律从旧 fm 继承，调用方**不可改**（extra 里
      同名键静默剥离）——「分支上怎么改内容都行，改不了它是谁的实验」；
    - 层/条件空间/验证基底默认继承旧 fm（tags/importance 可显式覆盖）；
    - override=True → 旧内容自动快照留痕（③ 快照机制，零新日志）。
    写权限由 add 的 require_layer_write 库层强制，不在此重复设闸。
    """
    nid = str(node_id or "").strip()
    if "@" not in nid:
        return {"ok": False,
                "error": "非分支节点（须为 <主支>@<branch_id> 形态）：%s" % nid}
    e = (cg.index.get("nodes") or {}).get(nid)
    if not e or not e.get("branch_id"):
        return {"ok": False, "error": "分支节点不存在或无分支归属：%s" % nid}
    rec = cg.get(nid)
    fm = _fm_of(rec)
    if isinstance(content, dict) or content is None:
        return {"ok": False, "error": "content 须为字符串"}
    for k in ("branch_id", "branched_from", "branch_note", "derived_from",
              "relation", "merged_from_branch", "override", "consistency"):
        extra.pop(k, None)   # 归属/血缘/写法闸不可经 extra 篡改
    cg.add(nid, str(content or ""),
           layer=fm.get("layer") or e.get("layer") or "knowledge",
           tags=list(tags if tags is not None else (fm.get("tags") or [])),
           importance=float(importance if importance is not None
                            else (fm.get("importance") or 0.5)),
           condition_space=fm.get("condition_space"),
           verification_basis=fm.get("verification_basis") or "test",
           non_applicable_conditions=fm.get("non_applicable_conditions"),
           override=True, consistency=False,
           derived_from=list(fm.get("derived_from") or []),
           relation=fm.get("derived_relation") or "split_from",
           branch_id=fm.get("branch_id") or e.get("branch_id"),
           branched_from=fm.get("branched_from") or e.get("branched_from"),
           branch_note=fm.get("branch_note"),
           actor=actor, **extra)
    _audit(cg, "branch_rewrite", branch_id=e.get("branch_id"), node=nid)
    return {"ok": True, "node": nid, "branch_id": e.get("branch_id")}


def merge(cg, branch_id, reason=None) -> dict:
    """把分支上的改写按 branched_from 溯源回写主支。

    - 主支内容 = 分支内容；层/tags/重要性继承主支（实验元数据不带回去）；
    - 主支 derived_from 追加分支 nid（原链保留）、relation="merged_from"；
    - override=True → 主支旧内容自动快照留痕；
    - 分支节点保留（merge 不自动删——显式两步、可逆、诚实）。
    """
    bid = str(branch_id or "").strip().lower()
    ents = _iter_branch_nodes(cg, bid)
    if not ents:
        return {"ok": False, "error": "分支不存在或无节点：%s" % bid}
    merged, skipped = [], []
    for nid, e in ents:
        orig = e.get("branched_from")
        rec = cg.get(orig) if orig else None
        if not rec:
            skipped.append({"id": nid, "why": "主支节点不存在：%s" % orig})
            continue
        src = cg.get(nid)
        old_fm = _fm_of(rec)
        src_fm = _fm_of(src)
        chain = list(old_fm.get("derived_from") or [])
        if nid not in chain:
            chain.append(nid)
        cg.add(orig, (src or {}).get("content") or "",
               layer=old_fm.get("layer") or e.get("layer") or "knowledge",
               tags=list(old_fm.get("tags") or e.get("tags") or []),
               condition_space=src_fm.get("condition_space"),
               importance=float(old_fm.get("importance", 0.5)),
               verification_basis=old_fm.get("verification_basis") or "test",
               non_applicable_conditions=old_fm.get("non_applicable_conditions"),
               override=True, consistency=False,
               derived_from=chain, relation="merged_from",
               merged_from_branch=bid, actor="branch_merge")
        merged.append({"branch_node": nid, "target": orig})
    _audit(cg, "branch_merge", branch_id=bid,
           merged=[m["target"] for m in merged], reason=reason)
    return {"ok": bool(merged), "branch_id": bid, "merged": merged,
            "skipped": skipped,
            "hint": "分支节点保留：可 branch_search 继续实验，或 discard 冷归档"}


def discard(cg, branch_id, summary: str) -> dict:
    """放弃分支：校验教训必填 → 写 branch_summary 教训节点 → 分支冷归档。

    - summary 必须含 BRANCH_MARKS 三标记（缺一不收，防「无声放弃」）；
    - 教训节点进 knowledge 层、tags 带 branch:<id>——可被正常检索召回；
    - 分支节点文件移入 _branches/<id>/（物理保留不违背永不删除，
      LAYERS 之外故 _scan_nodes 不再扫到——索引与主支检索天然干净）；
    - 需 can_admin（改变库可见性属高危操作）。
    """
    p = getattr(cg, "principal", None)
    if p is not None:
        p.require_admin("branch_discard")
    bid = str(branch_id or "").strip().lower()
    missing = [m for m in BRANCH_MARKS if m not in (summary or "")]
    if missing:
        return {"ok": False, "error": "branch_summary 缺必填标记",
                "missing": missing, "required": list(BRANCH_MARKS)}
    ents = _iter_branch_nodes(cg, bid)
    if not ents:
        return {"ok": False, "error": "分支不存在或无节点：%s" % bid}
    body = summary if summary.lstrip().startswith("#") else \
        "# branch_summary：%s\n\n%s" % (bid, summary)
    sid = cg.add("branch_summary_%s" % bid, body, layer="knowledge",
                 tags=["branch_summary", branch_tag(bid)],
                 verification_basis="test", consistency=False,
                 actor="branch_discard")
    cold = os.path.join(cg.root, COLD_DIR, bid)
    os.makedirs(cold, exist_ok=True)
    moved = 0
    for nid, e in ents:
        path = e.get("path")
        if path:
            src = os.path.join(cg.root, str(path).replace("/", os.sep))
            if os.path.exists(src):
                os.replace(src, os.path.join(cold, os.path.basename(src)))
                moved += 1
        (cg.index.get("nodes") or {}).pop(nid, None)
    fl = getattr(cg, "flush", None)
    if fl is not None:
        try:
            fl()
        except Exception:
            pass
    _audit(cg, "branch_discard", branch_id=bid, moved=moved, summary_node=sid)
    return {"ok": True, "branch_id": bid, "moved": moved,
            "summary_node": sid, "cold_dir": "%s/%s" % (COLD_DIR, bid)}


def list_branches(cg) -> dict:
    """按 branch_id 聚合现存分支（节点清单 + 溯源主支）。"""
    groups = {}
    for nid, e in (cg.index.get("nodes") or {}).items():
        bid = e.get("branch_id")
        if not bid:
            continue
        g = groups.setdefault(bid, {"branch_id": bid, "tag": branch_tag(bid),
                                    "nodes": [], "branched_from": []})
        g["nodes"].append(nid)
        bf = e.get("branched_from")
        if bf and bf not in g["branched_from"]:
            g["branched_from"].append(bf)
    return {"ok": True,
            "branches": sorted(groups.values(), key=lambda g: g["branch_id"])}