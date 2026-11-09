"""DEFER 的正交状态轴（M5，2026-10-31）。

设计定案（与 `audit/M5-PLAN.md` §3 一致，三条都是实测出来的）：

  · **不用** `state="deferred"`：`mdcg.add` 里 `state` 已被裁决四态
    （ACCEPT / REJECT / DEFER / BLINDSPOT）占用并被 pop 出去归一为生命周期状态
    （见 `mdcg.py` 注释「该键名已属裁决四态」），实测直接抛
    `TransitionError: 非法状态迁移 active→deferred（unknown_state）`。
  · **不进** `lifecycle.STATES`：那是**降级阶梯**（active→converged→demoted→
    archived），`_RANK` 被 `check()` 用来判「受保护节点豁免降级」——把 deferred
    排进去会让「受保护节点的 DEFER」被当成降级拦截，语义退化；排 0 又与 active
    相撞。故 DEFER 与生命周期是**两根轴**。
  · 故：节点照常 `lifecycle_state: active`，另带 `defer_state: deferred`；
    裁决后改 `rejected`（仍隐身、但不再待审）或摘除（释放，回正常检索面）。

字段契约（都落节点 frontmatter；`defer_state` 另入 `_index.json` 快照，免读盘过滤）：

    defer_state         deferred | rejected（**缺键 = 无 DEFER 标记**）
    defer_pid           该草稿在审核队列里的稳定 pid（派生行重建时优先用它）
    defer_payload_hash  正文指纹（= `mdcos._sig(content)`），派生件免解密对账
    defer_reason        为什么被 DEFER（遗忘闸门给的理由，含重复对象标注）
    defer_target        撞 id 降级时被撞的原目标 id（人工追溯用）

本模块**只依赖 nodefile / fsutil**，不 import mdcos / mdcg —— 那两个模块要 import
本模块（谓词单点），反向 import 即成环。
"""

import argparse
import hashlib
import json
import os
import sys
import time

from . import nodefile
from .fsutil import FileLock, atomic_write

FIELD = "defer_state"
PID_FIELD = "defer_pid"
HASH_FIELD = "defer_payload_hash"
REASON_FIELD = "defer_reason"
TARGET_FIELD = "defer_target"

PENDING = "deferred"
REJECTED = "rejected"

# 带这两种标记的节点都**不进正排候选池**：deferred = 还没裁决、rejected = 裁决
# 为不采纳但仍留档。释放（accept）时整个标记被摘除，才算回到可召回面。
_BLOCKING = (PENDING, REJECTED)

INBOX_REL = ("hippocampus", "inbox.jsonl")
DECISION_REL = ("hippocampus", "decisions.jsonl")
DEFER_LAYERS = ("contextual",)


def is_hidden(entry) -> bool:
    """候选池过滤谓词：只看索引快照条目，不读盘。缺键 / 非法值 = 不拦（fail-open）。

    调用点两处（必须同谓词，否则检索面分家）：`mdcos.MdCGOS._candidates`（生产
    路径）与 `mdcg.MdCG.search`（基类路径）。
    """
    return isinstance(entry, dict) and entry.get(FIELD) in _BLOCKING


def is_pending(entry) -> bool:
    """待审（还没裁决）的 DEFER 条目——计数/巡检用，不用于候选过滤。"""
    return isinstance(entry, dict) and entry.get(FIELD) == PENDING


def payload_hash(content: str) -> str:
    """与 `mdcos._sig` 同算法（sha1 前 16 位）：派生件与队列行据此对账。"""
    return hashlib.sha1((content or "").encode("utf-8")).hexdigest()[:16]


def derived_pid(node_id: str, phash: str) -> str:
    """节点没带 `defer_pid` 时的稳定 pid（同一 nid+正文 恒得同一 pid → 幂等）。"""
    h = hashlib.sha1(("%s\x00%s" % (node_id or "", phash or ""))
                     .encode("utf-8")).hexdigest()[:12]
    return "prop_" + h


# ---------------------------------------------------------------- 扫描 / 派生件

def inbox_path(root: str) -> str:
    return os.path.join(root, *INBOX_REL)


def scan_deferred(root: str) -> dict:
    """读盘扫出全部带 DEFER 标记的节点：{nid: {"path","fm","content"}}。

    只走 `contextual` 层（DEFER 的落点），**不**扫 knowledge 分片——那里的历史
    DEFER 目标（706 条留痕里 260 条）从来没有正文落盘过，扫也扫不出东西。
    成本实测：1,806 个 contextual 文件全量读 fm ≈ 0.10 s。
    """
    out = {}
    for layer in DEFER_LAYERS:
        base = os.path.join(root, layer)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, encoding="utf-8") as f:
                        fm, content = nodefile.loads(f.read())
                except (OSError, UnicodeDecodeError, ValueError):
                    continue
                if fm.get(FIELD) not in _BLOCKING:
                    continue
                nid = str(fm.get("id") or fn[:-3])
                out[nid] = {
                    "path": os.path.relpath(p, root).replace("\\", "/"),
                    "fm": fm,
                    "content": content,
                }
    return out


def _read_rows(path: str) -> list:
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict):
                rows.append(r)
    return rows


def _row_for(nid: str, node: dict) -> dict:
    """由节点派生一条队列行：**正文为空**，只留指针与元数据。"""
    fm = node["fm"]
    ph = str(fm.get(HASH_FIELD) or payload_hash(node["content"]))
    pid = str(fm.get(PID_FIELD) or derived_pid(nid, ph))
    extra = {"defer_ref": True,
             "defer_reason": str(fm.get(REASON_FIELD) or ""),
             "writer": fm.get("writer")}
    if fm.get(TARGET_FIELD):
        outer = extra
        outer["defer_target"] = fm.get(TARGET_FIELD)
    return {"t": fm.get("created_at") or time.time(), "pid": pid, "id": nid,
            "content": "", "layer": fm.get("layer") or "contextual",
            "tags": list(fm.get("tags") or []),
            "condition_space": fm.get("condition_space") or {},
            "payload_hash": ph,
            "sensitivity": fm.get("sensitivity"),
            "verify": {}, "verify_hash": "",
            "extra": extra,
            "actor": fm.get("writer") or "defer-rebuild",
            "session": fm.get("session") or ""}


def rebuild_inbox(root: str, apply: bool = False) -> dict:
    """把 `hippocampus/inbox.jsonl` 重建为节点的**派生索引**（只增不删，幂等）。

    只增不删的理由：存量队列行（含 121 条历史正文）没有对应节点，删掉就永久
    丢内容；它们的正文本来也没法从 706 条 DEFER 留痕里回填（留痕行不含 content，
    实测含 content 的行数 = 0）。缺行补齐即可让「节点 → 队列」单向不丢。

    返回 {"nodes","rows","missing","appended","changed"}。
    """
    p = inbox_path(root)
    rows = _read_rows(p)
    have_pid = {str(r.get("pid")) for r in rows if r.get("pid")}
    have_hash = {str(r.get("payload_hash")) for r in rows if r.get("payload_hash")}
    nodes = scan_deferred(root)
    add = []
    for nid in sorted(nodes):
        node = nodes[nid]
        fmt = node["fm"]
        ph = str(fmt.get(HASH_FIELD) or payload_hash(node["content"]))
        pid = str(fmt.get(PID_FIELD) or derived_pid(nid, ph))
        if pid in have_pid or ph in have_hash:
            continue
        add.append(_row_for(nid, node))
    if apply and add:
        with FileLock(p, strict=True):
            base = ""
            if os.path.exists(p):
                with open(p, encoding="utf-8", errors="replace") as f:
                    base = f.read()
            if base and not base.endswith("\n"):
                base += "\n"
            body = base + "".join(json.dumps(r, ensure_ascii=False) + "\n"
                                  for r in add)
            atomic_write(p, body)
    return {"nodes": len(nodes), "rows": len(rows), "missing": len(add),
            "appended": len(add) if apply else 0, "changed": bool(add)}


def verify_inbox(root: str) -> dict:
    """两向差集：节点侧缺行（should_be_zero）+ 队列侧悬空指针。

    · `missing_rows`：有 DEFER 标记的节点在队列里找不到对应行（应恒 0）；
    · `orphan_rows`：队列行声称 `defer_ref`，但节点侧没有该 pid / 该标记
      （accept 后残留、或有人手工改了 fm —— 正是负控要暴露的形态）。

    `dangling_rows` = 历史正文行（无节点）：不算错，登记计数，供迁移时判断。
    """
    rows = _read_rows(inbox_path(root))
    nodes = scan_deferred(root)
    decided = {str(r.get("pid")) for r in
               _read_rows(os.path.join(root, *DECISION_REL)) if r.get("pid")}
    by_pid, by_hash = {}, set()
    for nid, node in nodes.items():
        fm = node["fm"]
        ph = str(fm.get(HASH_FIELD) or payload_hash(node["content"]))
        by_pid[str(fm.get(PID_FIELD) or derived_pid(nid, ph))] = nid
        by_hash.add(ph)
    missing, orphan, legacy = [], [], 0
    seen_pid, seen_hash = set(), set()
    for r in rows:
        pid = str(r.get("pid") or "")
        ph = str(r.get("payload_hash") or "")
        ref = bool((r.get("extra") or {}).get("defer_ref"))
        if pid:
            seen_pid.add(pid)
        if ph:
            seen_hash.add(ph)
        if not ref:
            legacy += 1
            continue
        if (pid and pid in by_pid) or (ph and ph in by_hash):
            continue
        # 已裁决的 pid（decisions.jsonl 里有）是**正常收尾**：accept 后节点标记
        # 被摘除、reject 后改标 rejected，队列行都还在——不算悬空。
        if pid and pid in decided:
            continue
        # 有 id 且有节点但节点已无标记（accept 后残留）也是悬空
        orphan.append({"pid": pid or None, "node_id": r.get("id")})
    for nid, node in nodes.items():
        fm = node["fm"]
        ph = str(fm.get(HASH_FIELD) or payload_hash(node["content"]))
        pid = str(fm.get(PID_FIELD) or derived_pid(nid, ph))
        if pid in seen_pid or ph in seen_hash:
            continue
        missing.append({"node_id": nid, "pid": pid,
                        "defer_state": fm.get(FIELD)})
    return {"nodes": len(nodes), "rows": len(rows), "legacy_rows": legacy,
            "missing_rows": missing, "orphan_rows": orphan,
            "ok": not missing and not orphan}


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m md_cg.defer",
        description="DEFER 派生件：把 hippocampus/inbox.jsonl 从节点重建 / 对账")
    ap.add_argument("--root", required=True, help="数据根（含 contextual/ 与 hippocampus/）")
    ap.add_argument("--rebuild", action="store_true", help="补齐缺失的派生行")
    ap.add_argument("--verify", action="store_true", help="两向差集对账（有差异 exit 2）")
    ap.add_argument("--apply", action="store_true", help="与 --rebuild 同用才真写")
    a = ap.parse_args(argv)
    if not a.rebuild and not a.verify:
        ap.error("至少给 --rebuild 或 --verify 之一")
    rc = 0
    if a.rebuild:
        r = rebuild_inbox(a.root, apply=a.apply)
        print("rebuild: " + json.dumps(r, ensure_ascii=False, sort_keys=True))
        if not a.apply and r["missing"]:
            print("（dry-run：未写盘；加 --apply 才落）")
    if a.verify:
        v = verify_inbox(a.root)
        print("verify: " + json.dumps(v, ensure_ascii=False, sort_keys=True))
        if not v["ok"]:
            rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(_main())
