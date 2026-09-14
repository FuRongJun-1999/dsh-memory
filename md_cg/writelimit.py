# -*- coding: utf-8 -*-
"""自动写入限流与同构聚合（流水污染治理：写入侧前置 + 读侧整理）。

背景（2026-09-15 污染实测）：某环境 contextual 层 355 个自动写入节点中，
46% 是单日批次流水（「批次247收官记忆」…×163 条同模板），17% 是无结构
mem_* 节点；主动遗忘闸门（forgetting.assess）MERGE 命中率仅 1%——精确
内容签名对「每次只换数字的同模板流水」完全无感。

本模块两层治理（只作用 contextual 层——自动写入落层；knowledge 等
手动纪律写入不受限）：

  写入侧（remember_gated 前置，工程策略独立于三问裁决）：
    1) 同源频率限制：同 (layer, role) 滑动窗口内超量 → DEFER（防灌水；
       原始事件仍在 recent log 时间线，可追溯不丢失）
    2) 同构聚合：短内容模板签名（去数字/URL/长十六进制）命中 →
       并入既有节点（正文追加一行 + merge_count+1，不新增节点）

  读侧（sustain 周期巡检调 tidy_contextual）：
    已落盘的同构组（≥min_group 条）→ 保留最早节点追加成员清单，
    成员降权（importance×0.5，下限 0.1）+ tidy:converged 标记；
    永不删除节点（可逆、可审计），受保护节点跳过。

状态持久化 <root>/_writelimit.json（进程重启不失效）；
env MDCG_WRITELIMIT=0 整体关闭；importance_hint≥0.7（保护优先语义）
跳过所有限流。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from .fsutil import FileLock, atomic_write

STATE_FILE = "_writelimit.json"
RATE_WINDOW = 60.0            # 频率窗口（秒）
RATE_MAX = 8                  # 窗口内同 (layer, role) 最大写入数
CONVERGE_WINDOW = 86400.0     # 同构聚合窗口（秒，24h）
MAX_CONTENT = 200             # 参与同构聚合的内容长度上限（字符）
MIN_SKELETON = 4              # 模板骨架最短长度（防「好的/收到」误聚）
MAX_APPLY = 500               # tidy 单次落盘成员数上限（防一次改爆）

_RE_URL = re.compile(r"https?://\S+")
_RE_HEX = re.compile(r"\b[0-9a-fA-F]{12,}\b")
_RE_LONG_NUM = re.compile(r"\d{4,}")
_RE_NUM = re.compile(r"\d+")
_RE_WS = re.compile(r"\s+")
_RE_TITLE = re.compile(r"^\s*#\s*功能名[：:]\s*(.+?)\s*$", re.M)


def enabled() -> bool:
    """总开关：env MDCG_WRITELIMIT=0/false/no 时关闭所有限流。"""
    return os.environ.get("MDCG_WRITELIMIT", "1").strip().lower() \
        not in ("0", "false", "no")


def template_signature(content: str):
    """同模板流水签名：标题模板优先，其次全文骨架。

    - 带「# 功能名：X」标题行的节点：对标题做去数字骨架（不受正文长度
      限制）——批次报告正文各不相同但标题同模板（「批次N收官记忆」），
      标题是节点身份的最强模板信号
    - 无标题：去 URL/长十六进制/数字后的全文压缩骨架；长文
      （≥MAX_CONTENT）是正经记忆不参与聚合
    - 骨架过短（<MIN_SKELETON）或纯数字 → None（防「好的/收到」误聚）
    """
    if not content:
        return None
    text = content.strip()
    m = _RE_TITLE.search(text)
    if m:
        s = _skeleton(m.group(1))
        return ("t:" + s) if s and len(s) >= MIN_SKELETON else None
    if len(text) >= MAX_CONTENT:
        return None
    s = _skeleton(text)
    return s if s and len(s) >= MIN_SKELETON else None


def _skeleton(text: str) -> str:
    s = _RE_URL.sub(" ", text)
    s = _RE_HEX.sub(" ", s)
    s = _RE_LONG_NUM.sub(" ", s)
    s = _RE_NUM.sub(" ", s)
    s = _RE_WS.sub("", s)
    return s


# ---------- 状态持久化 ----------

def _state_path(cg) -> str:
    return os.path.join(cg.root, STATE_FILE)


def _load(cg) -> dict:
    try:
        with open(_state_path(cg), encoding="utf-8") as f:
            st = json.load(f)
        if isinstance(st.get("sigs"), dict) and isinstance(st.get("rate"), dict):
            return st
    except (OSError, ValueError):
        pass
    return {"sigs": {}, "rate": {}}


def _save(cg, st: dict) -> None:
    p = _state_path(cg)
    with FileLock(p):
        atomic_write(p, json.dumps(st, ensure_ascii=False, sort_keys=True))


def _push_rate(st: dict, key: str, now: float) -> None:
    win = [t for t in st["rate"].get(key, []) if now - t < RATE_WINDOW]
    win.append(now)
    st["rate"][key] = win[-RATE_MAX * 4:]


# ---------- 写入侧：前置限流 + 同构聚合 ----------

def check(cg, content, layer="contextual", role=None, node_id=None,
          importance_hint=None, now=None):
    """remember_gated 前置限流。None=放行；否则 {"verdict": DEFER|CONVERGE}。

    - DEFER：同 (layer, role) 滑动窗口内已满 RATE_MAX 条（被拒者也计数，
      防持续灌水每条都重算窗口）
    - CONVERGE：签名命中（CONVERGE_WINDOW 内、目标节点仍在）→ 应并入
      rec["nid"]；签名首见即预占位（nid=node_id），assess 若 DEFER/DROP
      该节点未落盘，下次 cg.get 失效自动重置——自愈
    """
    if layer != "contextual" or not enabled():
        return None
    if importance_hint is not None:
        try:
            if float(importance_hint) >= 0.7:
                return None                     # 保护优先语义：跳过限流
        except (TypeError, ValueError):
            pass
    now = float(now if now is not None else time.time())
    st = _load(cg)
    key = f"{layer}:{role or 'user'}"
    # 1) 同源频率限制
    win = [t for t in st["rate"].get(key, []) if now - t < RATE_WINDOW]
    if len(win) >= RATE_MAX:
        win.append(now)
        st["rate"][key] = win[-RATE_MAX * 4:]
        _save(cg, st)
        return {"verdict": "DEFER", "limiter": "rate", "reason":
                f"ratelimit:{key}:>{RATE_MAX}in{int(RATE_WINDOW)}s"}
    # 2) 同构聚合
    sig = template_signature(content)
    if sig:
        rec = st["sigs"].get(sig)
        if rec and now - float(rec.get("t") or 0) < CONVERGE_WINDOW \
                and rec.get("nid"):
            tgt = cg.get(rec["nid"])
            if tgt:
                if (tgt.get("content") or "").strip() \
                        == (content or "").strip():
                    # 与既有节点正文完全一致：零新信息 → 交回旧闸门语义
                    # DROP（不落库、不追加聚合行、不强化既有）——对齐
                    # forgetting 闸门「确定性内部冗余 → DROP 先于 MERGE」
                    # 纪律；同模板但内容不同才走聚合（那才是流水治理）
                    _push_rate(st, key, now)
                    _save(cg, st)
                    return {"verdict": "DROP", "limiter": "exact_dup",
                            "target": rec["nid"],
                            "reason": f"exact_dup_of:{rec['nid']}"}
                rec["n"] = int(rec.get("n") or 1) + 1
                rec["last"] = now
                st["sigs"][sig] = rec
                _push_rate(st, key, now)
                _save(cg, st)
                return {"verdict": "CONVERGE", "limiter": "converge",
                        "target": rec["nid"], "sig": sig[:40], "n": rec["n"],
                        "reason": f"converge:{sig[:40]}#{rec['n']}"}
        st["sigs"][sig] = {"nid": node_id, "t": now, "n":
                           int((rec or {}).get("n") or 1),
                           "sk": sig[:60]}
    _push_rate(st, key, now)
    _save(cg, st)
    return None


def record_accepted(cg, node_id, content, now=None) -> None:
    """ACCEPT 落盘后确保签名→节点映射存在（check 已预占位，此处兜底）。"""
    sig = template_signature(content)
    if not sig:
        return
    now = float(now if now is not None else time.time())
    st = _load(cg)
    rec = st["sigs"].get(sig)
    if rec is None or not rec.get("nid"):
        st["sigs"][sig] = {"nid": node_id, "t": now, "n":
                           int((rec or {}).get("n") or 1), "sk": sig[:60]}
        _save(cg, st)


def converge_into(cg, target: str, content: str) -> dict:
    """同构聚合落库：正文追加一行【聚合】摘要，merge_count+1。

    importance **不变**——流水不该越聚越重要（与 forgetting.reinforce
    的 +0.05 相反）；原始内容截 80 字入行，全文仍在 recent log 可溯。
    """
    e = cg.get(target)
    if not e:
        return {"ok": False, "error": "target_missing"}
    fm = dict(e.get("frontmatter") or {})
    body = " ".join((content or "").split())[:80]
    stamp = time.strftime("%m-%d %H:%M", time.localtime())
    fm["merge_count"] = int(fm.get("merge_count") or 0) + 1
    fm["last_merge_at"] = time.time()
    cg._write_node(target, os.path.join(cg.root, e["path"]), fm,
                   (e.get("content") or "") + f"\n- 【聚合 {stamp}】{body}",
                   durable=True)
    entry = cg.index["nodes"].get(target)
    if entry is not None:
        entry.update({"merge_count": fm["merge_count"],
                      "last_merge_at": fm["last_merge_at"]})
        cg._dirty[target] = entry
    return {"ok": True, "merge_count": fm["merge_count"]}


# ---------- 读侧：已落盘同构组的周期整理（sustain 巡检入口）----------

def tidy_contextual(cg, apply=False, min_group=3, actor="sustain_tidy",
                    limit=2000) -> dict:
    """扫描 contextual 层已落盘节点，按模板签名分组并整理。

    对 ≥min_group 的同构组（apply=True 时）：
      · 保留最早节点：正文追加【整理聚合】成员清单段落
      · 成员节点：tags += tidy:converged、importance×0.5（下限 0.1）
    永不删除节点（可逆、可审计）；protected/immutable 成员跳过；
    apply=False 只盘点不动任何节点。
    """
    groups: dict = {}
    scanned = 0
    for nid, entry in list(getattr(cg, "index", {})
                           .get("nodes", {}).items()):
        if scanned >= limit:
            break
        if entry.get("layer") != "contextual":
            continue
        e = cg.get(nid)
        if not e:
            continue
        scanned += 1
        sig = template_signature(e.get("content") or "")
        if sig:
            groups.setdefault(sig, []).append(e)
    planned = []
    for sig, members in groups.items():
        if len(members) < min_group:
            continue
        members.sort(key=lambda m: float((m.get("frontmatter") or {})
                                         .get("created_at", 0) or 0))
        planned.append({"sig": sig[:40], "keep": members[0]["id"],
                        "members": [m["id"] for m in members[1:]]})
    planned.sort(key=lambda p: -len(p["members"]))
    out = {"t": time.time(), "actor": actor, "scanned": scanned,
           "groups": len(planned),
           "members": sum(len(p["members"]) for p in planned),
           "apply": bool(apply), "planned": planned[:20], "applied": []}
    if not apply or not planned:
        return out
    n_ap = 0
    for p in planned:
        if n_ap >= MAX_APPLY:
            break
        keep = cg.get(p["keep"])
        if not keep:
            continue
        lines = [f"\n\n# 整理聚合（tidy {time.strftime('%Y-%m-%d')}）："
                 f"同模板成员 {len(p['members'])} 条"]
        for mid in p["members"]:
            m = cg.get(mid)
            if not m:
                continue
            mfm = dict(m.get("frontmatter") or {})
            if mfm.get("protected") or mfm.get("immutable"):
                continue
            first = " ".join((m.get("content") or "").split())[:48]
            lines.append(f"- {mid} {first}")
            _demote(cg, m)
            n_ap += 1
        kfm = dict(keep.get("frontmatter") or {})
        kfm["merge_count"] = int(kfm.get("merge_count")
                                 or 0) + len(p["members"])
        kfm["last_merge_at"] = time.time()
        cg._write_node(keep["id"], os.path.join(cg.root, keep["path"]),
                       kfm, (keep.get("content") or "") + "\n".join(lines),
                       durable=True)
        out["applied"].append({"keep": p["keep"],
                               "converged": len(p["members"])})
    out["applied_count"] = n_ap
    flush = getattr(cg, "flush", None)
    if callable(flush):
        flush()
    return out


def _demote(cg, e: dict) -> None:
    """成员降权：tags += tidy:converged，importance×0.5（下限 0.1）。"""
    fm = dict(e.get("frontmatter") or {})
    tags = list(fm.get("tags") or [])
    if "tidy:converged" not in tags:
        tags.append("tidy:converged")
    fm["tags"] = tags
    fm["importance"] = round(max(0.1, float(fm.get("importance", 0.5)
                                          or 0) * 0.5), 3)
    cg._write_node(e["id"], os.path.join(cg.root, e["path"]), fm,
                   e.get("content") or "")
    entry = cg.index["nodes"].get(e["id"])
    if entry is not None:
        entry.update({"tags": tags, "importance": fm["importance"]})
        cg._dirty[e["id"]] = entry


def stats(cg) -> dict:
    """限流状态摘要（诊断面）。"""
    st = _load(cg)
    live_sigs = sum(1 for r in st["sigs"].values() if r.get("nid"))
    return {"enabled": enabled(), "sigs_tracked": len(st["sigs"]),
            "sigs_live": live_sigs,
            "rate_keys": len(st["rate"]),
            "state_file": STATE_FILE}
