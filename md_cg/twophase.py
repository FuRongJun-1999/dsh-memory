# -*- coding: utf-8 -*-
"""写入两段式提交（Pi 可学习优点 ③）：先记意图，再记结果，崩溃后可对账。

**问题（交接文档 §3③）**：写入只有**一条事后记录**——`_audit.jsonl` 只在
`op=add` **成功之后**追加一行。进程在「闸门通过之后、落盘前后」被杀，日志里
没有任何痕迹：
  · 落盘成功但簿记没写 → 记忆存在、历史里查不到（静默的记忆）；
  · 落盘只做了一半（原子写保证文件不半截，但索引增量可能没落）→ 对账无从下手，
    只能人工翻目录。
两段式把一次写入拆成两条记录：
  1. **intent**（意图，**先行**持久化）：写下「我准备写 node_id，正文指纹 = h」；
  2. **outcome**（结果）：写下「这笔以 committed / interrupted / error 结束」。
崩溃后 `reconcile()` 扫日志配对，对**有 intent 无 outcome** 的逐条判定：
  · 节点在库且正文指纹 == intent 的 h → **补账** outcome{committed, reconciled}；
  · 节点不在、或指纹不符 → outcome{interrupted}，如实标记（**不假装成功**）。
对账**幂等**：补出来的 outcome 与正常 outcome 同为 outcome 记录，第二次扫描
不再有未配对 intent。

**为何用独立文件 `_write_2pc.jsonl` 而非写进 `_audit.jsonl`**（对交接文档
「落 `_audit.jsonl`」建议的偏离，取证理由）：
  · `_audit.jsonl` 已被当作**单一语义流**消费——`test_p45_session_identity` 的 F
    段断言 `rows[-1]` 必须带 harness / unit / session 归因，coggraph 会话串链按
    `op` 值串链。混入两段式事件，同一文件的读者要多分辨三种事件语义，且既有
    断言口径被无谓扰动（一次写入 = 三行日志）。
  · 本仓已有「独立审计文件」惯例：`protect.py` 的 `_protected_audit.jsonl`。
  · 两段式是**写路径的崩溃一致性账本**，不是访问审计——语义本就不同源。

**诚实边界**：
  · `append_jsonl` 在 Windows 上非原子（O_APPEND 是 lseek+write 两步），多进程
    高并发下可能丢 intent——对账是**增益**，不是「保证不丢」；单进程/低并发足够，
    且 kill -9 不会丢已 write 的数据（只有断电才丢，见 `fsutil` 注释）。
  · 对账只做「补账 / 标记」，**不重放写入**——是否重做是使用者的决定。
  · 账本是 append-only：对账不重写历史，只追加 outcome。
"""

import os
import time
import uuid

from . import nodefile
from .fsutil import append_jsonl

#: 账本文件名（独立于 `_audit.jsonl`，理由见模块 docstring）
LOG_FILE = "_write_2pc.jsonl"

#: outcome 状态集
STATUS_COMMITTED = "committed"      # 落盘完成（正常路径或对账补账）
STATUS_INTERRUPTED = "interrupted"  # 有意图、未落盘（或指纹不符）——如实标记
STATUS_ERROR = "error"              # 执行抛异常
STATUS_ABORTED = "aborted"          # 闸门判定不落盘（reject/defer/丢弃）

#: 对账判定码
R_NODE_OK = "node_present_hash_match"   # 落盘已完成 → 补 committed
R_NODE_MISSING = "node_missing"         # 未落盘 → interrupted
R_MISMATCH = "content_mismatch"         # 落了别的正文 → interrupted（不覆盖）
R_UNREADABLE = "node_unreadable"        # 读节点失败 → interrupted（不猜测）


# 生效条件：给定 cg 且其 root 属性可参与 os.path.join 时，恒返回 os.path.join(cg.root, LOG_FILE)，无分支与早退。
def log_path(cg) -> str:
    return os.path.join(cg.root, LOG_FILE)


# 生效条件：text 为假值（None/""）时按空串处理，否则用 text 本身，返回去尾换行后的字符串（仅剥 "\n"）。
def _norm(text: str) -> str:
    """正文口径归一（**对账正确性的前提**）：`nodefile.dumps` 写盘时会给正文补尾
    换行，`loads` 读回即带它。若 intent 按入参原文、对账按读回内容各算一次指纹，
    两者**永远不会相等** → 每一笔都误报 interrupted——比不做对账更坏（假阳性会
    淹没真问题，且诱人去"修"不存在的问题）。故两侧统一按「去尾换行」归一。
    """
    return (text or "").rstrip("\n")


# 生效条件：给定 cg 与 rec 时，把 rec 以 JSONL 追加写入 log_path(cg)，无返回值、无分支。
def _append(cg, rec: dict) -> None:
    append_jsonl(log_path(cg), rec)


# 生效条件：pr 取自 cg.principal 或（假值时）回落 cg.session——pr 为真字符串时 meta["session"]=pr；否则 pr 非 None 时把 pr.session 记入 session、把 pr.writer 或（假值时）pr.unit 记入 writer；actor 为真时 meta["actor"]=actor，最后返回 meta。
def _ident(cg, actor=None) -> dict:
    """归因字段（尽力而为）：principal 缺省时留空，不编造。"""
    pr = getattr(cg, "principal", None) or getattr(cg, "session", None)
    meta = {}
    if isinstance(pr, str) and pr:
        meta["session"] = pr
    elif pr is not None:
        sid = getattr(pr, "session", None)
        if sid:
            meta["session"] = sid
        wid = getattr(pr, "writer", None) or getattr(pr, "unit", None)
        if wid:
            meta["writer"] = wid
    if actor:
        meta["actor"] = actor
    return meta


# 生效条件：给定 cg、node_id、content 时生成 iid 与 content_hash（对 _norm(content) 计算），先写 phase="intent" 记录再返回 tok；layer 为真才写入 rec["layer"]，actor 与 **meta 分别经 _ident、rec.update 合入。
def begin(cg, node_id: str, content: str, layer: str = None,
          actor: str = None, **meta) -> dict:
    """记录写入**意图**（先行持久化）→ 返回令牌 tok（供 `commit` 配对）。

    先于落盘调用；崩溃后据 tok 里的指纹判定该笔是否落盘完成。
    """
    tok = {
        "iid": uuid.uuid4().hex[:16],
        "node_id": node_id,
        "content_hash": nodefile.content_hash(_norm(content)),
    }
    rec = {"t": time.time(), "phase": "intent", "iid": tok["iid"],
           "id": node_id, "content_hash": tok["content_hash"]}
    if layer:
        rec["layer"] = layer
    rec.update(_ident(cg, actor))
    rec.update(meta)
    _append(cg, rec)
    return tok


# 生效条件：nid 取 node_id，node_id 为假值（None/""）时回落 (tok or {}).get("node_id")，iid 取 (tok or {}).get("iid")（tok 为假值时两项均为 None）；status 用实参或默认 STATUS_COMMITTED；tok 为真且 tok.get("content_hash") 为真才写入 content_hash；reason 为真才写入 rec["reason"]；追加记录后返回 rec。
def commit(cg, tok: dict, status: str = STATUS_COMMITTED, node_id: str = None,
           reason: str = None, **meta) -> dict:
    """记录写入**结果**（与 intent 按 iid 配对）。返回结果记录。"""
    nid = node_id or (tok or {}).get("node_id")
    rec = {"t": time.time(), "phase": "outcome", "iid": (tok or {}).get("iid"),
           "id": nid, "status": status}
    if tok and tok.get("content_hash"):
        rec["content_hash"] = tok["content_hash"]
    if reason:
        rec["reason"] = reason
    rec.update(_ident(cg))
    rec.update(meta)
    _append(cg, rec)
    return rec


# ----------------------------------------------------------------------
# 读侧：盘点 / 对账

# 生效条件：log_path(cg) 不是文件时直接返回空列表；否则逐行读取，空行跳过，json.loads 抛异常的行跳过，返回成功解析的记录列表。
def records(cg) -> list:
    """读全部账本记录（append-only，坏行跳过不炸）。"""
    out = []
    p = log_path(cg)
    if not os.path.isfile(p):
        return out
    import json
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


# 生效条件：遍历 records(cg)，记录 r.get("iid") 为假值（缺键或空串）时跳过；否则按 iid 建槽，仅当槽内 intent/outcome 仍为 None 时分别填入首个 phase=="intent" / phase=="outcome" 的记录，返回 pairs。
def _pair(cg) -> dict:
    """把账本配成 {iid: {"intent":…, "outcome":…}}（同时计入无 iid 的脏行）。"""
    pairs = {}
    for r in records(cg):
        iid = r.get("iid")
        if not iid:
            continue
        slot = pairs.setdefault(iid, {"intent": None, "outcome": None})
        if r.get("phase") == "intent" and slot["intent"] is None:
            slot["intent"] = r
        elif r.get("phase") == "outcome" and slot["outcome"] is None:
            slot["outcome"] = r
    return pairs


# 生效条件：遍历 _pair(cg) 取有 intent 且 outcome 为 None 的槽（展开 intent 字段）组成 out，按 r.get("t") or 0 升序排序后返回 out[:max(0, int(limit))]——limit 为 0 或负数时切片为空列表，默认值 200 仅在未传参时生效。
def pending(cg, limit: int = 200) -> list:
    """未结清的写入意图（有 intent 无 outcome）——只读，不改盘。

    供 `cg(op=recent)` / 巡检看「有没有半途而废的写入」。
    """
    out = []
    for iid, slot in _pair(cg).items():
        if slot["intent"] is not None and slot["outcome"] is None:
            out.append({"iid": iid, **slot["intent"]})
    out.sort(key=lambda r: r.get("t") or 0)
    return out[:max(0, int(limit))]


# 生效条件：intent 的 id 为假值或 cg.get(nid) 抛异常时返回 (STATUS_INTERRUPTED, R_UNREADABLE)；取回 node 为假值时返回 (STATUS_INTERRUPTED, R_NODE_MISSING)；intent 的 content_hash 为真且与 _norm(node.get("content") or "") 的指纹不等时返回 (STATUS_INTERRUPTED, R_MISMATCH)；否则返回 (STATUS_COMMITTED, R_NODE_OK)。
def _judge(cg, intent: dict):
    """判定一笔未结清意图的真实结局 → `(status, code)`。**不猜测**：读不到就如实说。"""
    nid = intent.get("id")
    want = intent.get("content_hash")
    if not nid:
        return STATUS_INTERRUPTED, R_UNREADABLE
    try:
        node = cg.get(nid)
    except Exception:
        return STATUS_INTERRUPTED, R_UNREADABLE
    if not node:
        return STATUS_INTERRUPTED, R_NODE_MISSING
    got = nodefile.content_hash(_norm(node.get("content") or ""))
    if want and got != want:
        return STATUS_INTERRUPTED, R_MISMATCH
    return STATUS_COMMITTED, R_NODE_OK


# 生效条件：以 limit 调 pending(cg, limit=limit) 得到未结清意图并统计 unpaired/committed/interrupted；apply 为真时对每笔 intent 调 commit 补写 outcome（reconciled=True、actor="twophase:reconcile"），apply 为假值时只报告不写账本，rep["applied"]=bool(apply)；limit 为 0 或负数时 pending 返回空、details 为空列表。
def reconcile(cg, apply: bool = True, limit: int = 2000) -> dict:
    """启动/巡检对账：把半途写入**补账或如实标记**。

    `apply=False` 为 dry-run（只报告，不写账本）。返回汇总：
    `{"unpaired", "committed", "interrupted", "applied", "details"}`。
    幂等——补出的 outcome 与正常 outcome 同形，二次扫描不再有未配对项。
    """
    pend = pending(cg, limit=limit)
    rep = {"unpaired": len(pend), "committed": 0, "interrupted": 0,
           "applied": bool(apply), "details": []}
    for intent in pend:
        status, code = _judge(cg, intent)
        if status == STATUS_COMMITTED:
            rep["committed"] += 1
        else:
            rep["interrupted"] += 1
        rep["details"].append({"iid": intent.get("iid"), "id": intent.get("id"),
                               "status": status, "reason": code})
        if apply:
            commit(cg, {"iid": intent.get("iid"), "node_id": intent.get("id"),
                        "content_hash": intent.get("content_hash")},
                   status=status, reason=code, reconciled=True,
                   actor="twophase:reconcile")
    return rep