# -*- coding: utf-8 -*-
"""md_cg · 日志真源桥（P1）：认知图 ref 节点 ↔ DSH 日志真源 / 确定性转写。

真源身份与区间表的**唯一实现**在 `srcindex`（`session_src_id` / `log_units`）——
本模块只做桥与读路径：把 `refindex` 的 ref 协议接到「日志真源 + 转写区间」上。
md_cg 侧**零路径常量、零 scripts 依赖**：转写根由调用方（scripts 侧）注入，
单点仍在 `scripts/dsh_log_index.py:138/:514-516`；服务态因此不可能「自己决定
把转写写到哪」（P2 的再生**不在服务态做**，见 `read_index_node`）。

两层回读（方案 v0.3 §2、§9 裁定①）：
  区间层     `refindex.read_ref(doc_ref)`        → 转写文件行区间
  真源身份层 `srcindex.read_unit(src_unit(ref))` → zstd 日志本体（whole 粒度）

生效条件：ref 为 `refindex` 写出的 doc_ref（含 path/root/hash），且 root（转写根）
由调用方注入；`probe_src` 另需 `doc_ref.src` 且在 `MDCG_INGEST_ROOT` 白名单内。
不适用条件：无 doc_ref 的节点（非索引节点）；`src.path` 为空（`--src-path hash`
降级）时无法探测真源——`probe_src` 如实返回 unresolved，不猜。
"""
from __future__ import annotations

import os

from . import refindex, srcindex

#: 落库判据的两个状态名（`node_state` 的 state；其余状态见 docstring）
WRITE_STATES = ("new", "overwrite")
KIND = "doc_ref"


# 生效条件：path/workspace/session_id 为任意值（缺省按空串处理）；返回
# "<workspace>/<session_id>/<session_id>.md"（"/" 分隔，与 doc_ref.path 同形）。
def default_rel_of(workspace: str, session_id: str) -> str:
    ws = (workspace or "").strip("/\\")
    sid = (session_id or "").strip("/\\")
    return "/".join(p for p in (ws, sid, sid + ".md") if p)


# 生效条件：无入参副作用；返回 doc_ref → srcindex whole 单位的 dict（真源身份层回读入参）。
def src_unit(ref: dict) -> dict:
    """doc_ref → `srcindex` 的 whole 单位（真源身份层的回读入参，纯函数）。"""
    src = (ref or {}).get("src")
    src = src if isinstance(src, dict) else {}
    return {"src": src, "span": {"unit": "whole"},
            "span_hash": src.get("file_hash")}


# 生效条件：ref 为 dict（其余按 {} 处理）；verify 取 "hash"（缺省，实核 sha256）或其它值
# （只做 size/mtime 快路径）。返回 status ∈ ok/stale/unverified/dangling/unresolved/denied
# 与 ok/hash_verified 布尔；无 src 子键或 src.path 为空时返回 unresolved（不抛 KeyError）。
def probe_src(ref: dict, *, verify: str = "hash") -> dict:
    """探测真源（zstd 日志）状态——**与 ref 回读挂同一条根白名单闸**。

    为什么必须挂闸：frontmatter 是写入侧可塞的内容（`mdcg.py:1709 fm.update(extra)`），
    于是 `doc_ref.src.path` 与 `doc_ref.path` 一样是模型可控输入；本函数直接 stat
    并按需整读该文件。故走 `security.check_path_root(..., "MDCG_INGEST_ROOT", "src")`
    ——与 `mcp_server.py:2939-2942` 给 ref 回读挂的是同一条闸（未配置=放开、
    配置=realpath 落根内否则拒，fail-closed）。

    `verify="hash"`（缺省）时**必须**核 sha256 才算 ok：只对 (size, mtime) 相同只能
    给 `unverified`（fail-closed，巡检视为 not-ok）——否则「同长度同时间戳的替换」
    会静默通过。`hash_verified` 布尔用来区分「核过的 ok」与「没核的 ok」。
    """
    ref = ref or {}
    src = ref.get("src")
    src = src if isinstance(src, dict) else None
    path = (src or {}).get("path") or ""
    base = {"src": src, "path": path, "verify": verify,
            "ok": False, "hash_verified": False}
    if not src:
        return {**base, "status": "unresolved",
                "error": "该 ref 无 src 子键（不是日志真源索引节点），无法探测真源"}
    if not path:
        return {**base, "status": "unresolved",
                "error": "src.path 为空（--src-path hash 降级：真源路径未落库）"
                         "，无法探测——不猜"}
    if not os.path.isabs(path):
        return {**base, "status": "unresolved",
                "error": "src.path 是相对路径（--src-path rel 降级：dir 未落库），"
                         "无绝对根可解析——不猜"}
    from .security import check_path_root
    try:
        check_path_root(path, "MDCG_INGEST_ROOT", "src")
    except PermissionError as exc:              # 拒读即 not-ok，绝不降级放行
        return {**base, "status": "denied", "error": str(exc)[:300]}
    if not os.path.isfile(path):
        return {**base, "status": "dangling", "abspath": path,
                "error": "真源不存在（索引已悬空）：%s" % path}
    expect = src.get("file_hash")
    if verify == "hash":
        if not expect:
            return {**base, "status": "unverified", "abspath": path,
                    "error": "src.file_hash 缺失，无法核 hash（fail-closed：不计 ok）"}
        # 整文件回读走 **P0 的唯一实现**（`srcindex.read_unit(whole)`）——不在这里
        # 再写一份 sha256：与区域哈希同一条教训，两处算法会让「核过了」永远为真。
        u = srcindex.read_unit(src_unit(ref))
        if not u.get("ok"):
            return {**base, "abspath": path, "status": "dangling",
                    "error": str(u.get("error"))[:200]}
        match = bool(u.get("hash_match"))
        return {**base, "abspath": path, "bytes": u.get("bytes"),
                "hash": u.get("hash"), "hash_expected": expect,
                "hash_match": match, "hash_verified": match,
                "ok": match, "status": "ok" if match else "stale"}
    try:
        st = os.stat(path)
    except OSError as exc:
        return {**base, "status": "dangling", "abspath": path, "error": str(exc)[:200]}
    same = (src.get("size") == st.st_size
            and abs(float(src.get("mtime") or 0.0) - st.st_mtime) < 1e-6)
    if same:
        return {**base, "abspath": path, "status": "unverified",
                "error": "仅 (size, mtime) 相同、未核 hash ⇒ 不计 ok（fail-closed）"}
    return {**base, "abspath": path, "status": "stale",
            "size": st.st_size, "mtime": st.st_mtime}


# 生效条件：it 为 docindex 口径条目、kind 默认 "doc_ref"；返回 {id, state, ...}，
# state ∈ new/unchanged/overwrite/blocked（blocked 带 error 原因）。
def node_state(cg, it: dict, *, kind: str = KIND) -> dict:
    """单条条目的落库判据：**读节点自己的 doc_ref**，不读水位台账。

    判据 = `hash` 与 `lineno/end` **全等**才算已索引。为什么不看 id：
    `docindex.node_id` 是 `path#heading_path` 寻址（docindex.py:294-299），
    同标题换正文时 **id 不变而 hash 变**——「id 撞即跳」会把漂移判成已索引、
    静默放过（N203 的静默正是这么来的）。
    为什么不看 `Ledger` 水位：水位在活库根、且记的 rel 与改写后的
    `doc_ref.path` 不同源（refindex.py:302-317），开它就等于引一条会误判的
    快路径；真源增量改由节点自描述的 `doc_ref.src.file_hash` 承担。
    """
    nid = refindex.node_id_of(it, kind)
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    if nid not in nodes:
        return {"id": nid, "state": "new"}
    try:
        node = cg.get(nid)
    except Exception as exc:                    # 读隔离/保护抛错 → 拦下，不越权覆写
        return {"id": nid, "state": "blocked", "error": ("cg.get 抛错：%s" % exc)[:200]}
    if not node:
        return {"id": nid, "state": "blocked",
                "error": "索引有条目但 cg.get 读不回（密级/保护）——fail-closed，不覆写"}
    _k, ref = refindex.ref_of(node)
    if not isinstance(ref, dict) or not ref:
        # refindex.ref_of 对无 doc_ref 的节点返回 ('', None)：覆写并**计数**（不静默）
        return {"id": nid, "state": "overwrite", "reason": "no_ref"}
    same = (ref.get("hash") == it.get("hash")
            and _int(ref.get("lineno")) == _int(it.get("lineno"))
            and _int(ref.get("end")) == _int(it.get("end")))
    if same:
        return {"id": nid, "state": "unchanged"}
    return {"id": nid, "state": "overwrite", "reason": "hash_or_span",
            "was": {"hash": ref.get("hash"), "lineno": _int(ref.get("lineno")),
                    "end": _int(ref.get("end"))},
            "now": {"hash": it.get("hash"), "lineno": _int(it.get("lineno")),
                    "end": _int(it.get("end"))}}


# 生效条件：v 可转 int 时返回该 int，否则返回 -1（行位缺失/非法一律判不等，不抛）。
def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


# 生效条件：items 为 docindex 口径条目序列、transcript_root 为转写根、src 为日志真源身份；
# 返回 {new/overwritten/unchanged/blocked 计数, ids, rows, sens, encrypted}；
# dry_run 为真时只判定不写库。
def write_session(cg, items, *, transcript_root: str, src: dict, session: str,
                  workspace: str, session_uuid: str, kind: str = KIND,
                  rel_of=None, dry_run: bool = False) -> dict:
    """把一个会话的转写区间条目落库（真源身份挂在 `doc_ref.src`）。

    · `items` 的 `path` 一律改写成 `rel_of(workspace, session_uuid)`——即转写文件
      **相对转写根**的真实位置（`<ws>/<sid>/<sid>.md`），`doc_ref.root` = 转写根：
      这样 `read_ref(doc_ref)` 的 `join(root, path)` 才落在转写上。裸文件名口径
      在「同 sid 跨工作区」时会撞 id 且回读指错文件，故缺省即改写。
    · 逐条先过 `node_state`：`blocked` 的**不写**（fail-closed，原因透出），
      其余（new / overwrite）交给 `refindex.add_items`（落盘细节与生产同源）。
    · 密级**跟源**：`docindex.sensitivity_for(src["path"], None)` —— 真源路径判，
      只可能更严；落在加密档的条数单独计数（`encrypted`）由调用方告警：v1.0 曾
      误标 private 触发加密致检索零命中，静默复现是不可接受的。
    不改调用方传入的 `items`（内部逐条复制）。
    """
    if kind != KIND:
        raise ValueError("logref 只服务日志转写（kind=%r）" % KIND)
    rel_of = rel_of or default_rel_of
    rel = rel_of(workspace, session_uuid)
    plan, keep = [], []
    for it in items or []:
        it2 = dict(it)
        it2["path"] = rel
        st = node_state(cg, it2, kind=kind)
        plan.append(st)
        if st["state"] in WRITE_STATES:
            keep.append(it2)
    sens, _why = _docindex().sensitivity_for((src or {}).get("path") or "", None)
    enc = _encrypted_levels()
    rows = [{"id": st["id"], "state": st["state"], "reason": st.get("reason"),
             "heading_path": (it.get("heading_path") or []),
             "lineno": _int(it.get("lineno")), "end": _int(it.get("end")),
             "hash": it.get("hash")}
            for it, st in zip(items or [], plan)]
    out = {
        "transcript_root": transcript_root, "rel": rel,
        "items": len(items or []),
        "new": [st["id"] for st in plan if st["state"] == "new"],
        "overwritten": [st["id"] for st in plan if st["state"] == "overwrite"],
        "overwritten_no_ref": len([st for st in plan
                                   if st.get("reason") == "no_ref"]),
        "unchanged": [st["id"] for st in plan if st["state"] == "unchanged"],
        "blocked": [{"id": st["id"], "error": st.get("error")}
                    for st in plan if st["state"] == "blocked"],
        "rows": rows, "sensitivity": sens, "sens": {}, "src_sensitivity": sens,
        "encrypted": 0, "dry_run": bool(dry_run),
    }
    if dry_run or not keep:
        return out

    def _extra(it):
        return {"tags": ["dsh-log", "logsrc", "regenerable"]
                        + ([f"ws:{workspace}"] if workspace else []),
                "attrs": {"session": session, "workspace": workspace,
                          "dsh_session_uuid": session_uuid}}

    ids, sens_counts = refindex.add_items(
        cg, keep, kind=kind, root=transcript_root, sensitivity=sens,
        src_of=lambda it: src, extra_of=_extra)
    out["sens"] = sens_counts
    out["written"] = ids
    out["encrypted"] = sum(c for s, c in sens_counts.items() if s in enc)
    return out


# 生效条件：无入参副作用；返回 docindex 模块（局部 import，避免模块级循环）。
def _docindex():
    from . import docindex
    return docindex


# 生效条件：无入参副作用；返回 at-rest 加密档位元组（crypto.ENCRYPTED_LEVELS）。
def _encrypted_levels() -> tuple:
    from . import crypto
    return tuple(crypto.ENCRYPTED_LEVELS)


# 生效条件：node 为 cg.get 取回的节点 dict（其余按无 ref 处理）；with_src 缺省 False。
# 返回 {ok, status, text/hash_match, src_verified, ...}；真源块仅在 with_src 为真时给出。
def read_index_node(node, *, with_src: bool = False, verify: str = "hash") -> dict:
    """节点 → 两层回读结果（区间层恒做，真源身份层按 `with_src` 显式开）。

    `with_src` 缺省 **False**：默认不 stat/哈希真源——每次检索命中都整读一遍大
    zstd 是不可能的代价。返回里恒带 `src_verified: false` 明示「本次未看真源」，
    免得调用方把「没核」读成「核过且 ok」（与 `probe_src` 的 unverified 同源纪律）。

    状态机（转写层）：`ok` / `stale`（转写被重生成或源续写致内容变）⇒ **原样返回
    stale ＋ 建议重跑落库，不自动覆写**；`dangling`（转写被系统清理）⇒ 返回
    `rematerialize` 指路离线工具——**服务态不做再生**（mcp_server 进程零写临时目录）。
    """
    kind, ref = refindex.ref_of(node)
    if not ref:
        return {"ok": False, "error": "该节点没有 code_ref/doc_ref（不是索引节点）"}
    out = refindex.read_ref(ref, ref_kind=kind)
    # read_ref 的非 ok 只有 dangling/unresolved/error，且**仅 dangling** 置 stale=True
    # （refindex.py:474-478）——故用 stale 位区分 dangling 与 unresolved，不猜。
    if out.get("ok"):
        out["status"] = "stale" if out.get("stale") else "ok"
    else:
        out["status"] = "dangling" if out.get("stale") else "unresolved"
    out["node_ref_kind"] = kind
    out["span_status"] = out["status"]
    out["src_verified"] = False
    if out["status"] == "stale":
        out["suggested_action"] = ("重跑落库（区间哈希已变：转写被重生成或日志续写）；"
                                   "本函数不自动覆写")
    elif out["status"] == "dangling":
        out["rematerialize"] = "scripts/_mdcg_reindex_dshlogs.py --repair 1"
        out["note"] = ("服务态不写临时目录（不自动再生转写）；回读落到转写文件行区间，"
                       "转写缺失时用上述离线工具再生")
    if with_src:
        out["src"] = probe_src(ref, verify=verify)
        out["src_verified"] = bool((out["src"] or {}).get("hash_verified"))
    else:
        out["src_note"] = "本次未看真源（with_src=False）：默认不 stat/哈希 zstd 日志"
    return out


# 生效条件：cg 的节点带 doc_ref 且 ref['src']['file_hash'] 存在时按会话 src 水位判
# 「是否需要重切」；返回 {sessions: {sid: {file_hash, changed, n}}}（纯只读）。
def session_src_state(cg, *, tag: str = "logsrc") -> dict:
    """按**会话级 src 水位**报每条日志会话的真源哈希现状（P1 的增量口径）。

    为什么不用 `refindex` 的 `ledger` 增量：`Ledger` 只在活库根开 `_refindex.json`，
    且记的 rel 与改写后的 `doc_ref.path` 不同源（见 `node_state` docstring）。
    日志一路的增量判据改由**节点自描述的 `doc_ref.src.file_hash`** 承担——
    「某会话每个节点的 src 哈希都与当前真源相同」即无需 re-parse。
    """
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    out = {}
    for nid, e in list(nodes.items()):
        if tag not in ((e or {}).get("tags") or []):
            continue
        try:
            node = cg.get(nid)
        except Exception:
            continue
        if not node:
            continue
        _k, ref = refindex.ref_of(node)
        src = (ref or {}).get("src") if isinstance(ref, dict) else None
        if not isinstance(src, dict):
            continue
        ws = src.get("workspace") or ""
        sid = src.get("session_uuid") or ""
        key = f"{ws}/{sid}"
        row = out.setdefault(key, {"file_hash": src.get("file_hash"), "n": 0,
                                   "path": src.get("path")})
        row["n"] += 1
        if row["file_hash"] != src.get("file_hash"):
            row["file_hash"] = None               # 同会话内哈希不一致：不判「未变」
    for row in out.values():
        row["changed"] = None
        if row.get("path"):
            try:
                row["changed"] = (row["file_hash"] != srcindex.file_hash(row["path"]))
            except OSError:
                row["changed"] = True
    return {"sessions": out}
