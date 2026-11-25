# -*- coding: utf-8 -*-
"""日桶 / 会话桶索引（bucketindex）——把「时间」与「会话身份」真正用起来。

实测现状（主库 34,218 节点，2026-11-09）：
  · `created_at` 覆盖 **100%**，按天聚集（09-29 有 2733 条、11-08 有 2516 条）；
  · `session` 覆盖 **99.4%**，但其中 **48% 是 `unattributed`**（无法归属）；
  · `bucket` 字段**不是**日桶/会话桶，而是**条件桶**（`cond_<topic>_<hash>`）——别混用。

所以两件事必须显式建出来：
  · **日桶** `day:YYYY-MM-DD`：由 `created_at` 确定性派生（不新增写入代价）；
  · **会话桶** `session:<sid>`：由 `frontmatter.session` 派生，`unattributed` 单独成桶不与他人合并。

索引文件（落库根目录，按需重建）：
  · `_days.json`     {day: [node_id, ...]}
  · `_sessions.json` {session: [node_id, ...]}

为什么用索引：查询期扫 34k 节点按日期过滤实测 **2–17 秒**（见 timeboost.scoped_recall 注释），
索引后是字典查找 + O(命中数) 取节点。
"""
from __future__ import annotations

import json
import math
import os
import threading
import time

from . import crypto as _crypto
from . import fsutil as _fsutil
from . import lifecycle as _lifecycle
from .bm25 import tokenize as _bm25_tokenize

DAYS_FILE = "_days.json"
SESSIONS_FILE = "_sessions.json"
TERMS_FILE = "_bucketterms.json"
SKEL_FILE = "_bucketskel.json"
UNATTRIBUTED = "unattributed"
#: 桶骨架：每节点/每桶保留的字符数（供子串共现，bench 口径）
SKEL_CHARS_PER_NODE = 600
SKEL_CHARS_PER_BUCKET = 20000


_ISOLATED_LAYERS = ("rejected", "unresolved", "goals")
_PRIVATE_DOMAIN_TAG = "域:私密"


def _is_sensitive_or_private(rec, fm=None):
    """节点是否属密级加密/受限/私密域（明文与词项不得写入明文桶索引）。"""
    for src in (rec, fm):
        if not isinstance(src, dict):
            continue
        sens = src.get("sensitivity")
        if sens:
            s = str(sens).strip().lower()
            if s == "restricted" or _crypto.is_encrypted_level(s):
                return True
        tags = src.get("tags") or ()
        if isinstance(tags, (list, tuple, set)):
            for t in tags:
                if str(t).strip() == _PRIVATE_DOMAIN_TAG:
                    return True
    return False


def _is_non_recallable(rec, fm=None):
    """退役（archived/superseded）或隔离层（rejected/unresolved/goals）节点。"""
    for src in (rec, fm):
        if not isinstance(src, dict):
            continue
        if _lifecycle.is_retired(src):
            return True
        layer = src.get("layer")
        if layer and str(layer).strip().lower() in _ISOLATED_LAYERS:
            return True
    return False


def day_of(ts):
    """epoch 秒 → 本地日期字符串；不可解析/bool/非有限返回 None。"""
    if isinstance(ts, bool):
        return None
    try:
        v = float(ts)
        if not math.isfinite(v):
            return None
        return time.strftime("%Y-%m-%d", time.localtime(v))
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _fm(rec):
    if not isinstance(rec, dict):
        return {}
    fm = rec.get("frontmatter")
    return fm if isinstance(fm, dict) and fm else rec


def build(store, write=True, with_content=False, content_limit=400):
    """从索引面重建桶。返回 {days, sessions, purposes, projects, nodes, unattributed}。

    purposes 是「用途」副键（goal-caf158e5）：来自写时标签「用途:xx」，纯增量，
    不进词表，故不影响既有检索打分与桶名。
    """
    idx = getattr(store, "index", {}) or {}
    content_terms = 0
    nodes = idx.get("nodes") or {}
    days = {}
    sessions = {}
    purposes = {}
    projects = {}
    unattributed = 0
    for nid, rec in nodes.items():
        fm = _fm(rec)
        d = day_of(fm.get("created_at"))
        if d:
            days.setdefault(d, []).append(nid)
        sid = str(fm.get("session") or "") or UNATTRIBUTED
        if sid == UNATTRIBUTED:
            unattributed += 1
        sessions.setdefault(sid, []).append(nid)
        # 用途副键（goal-caf158e5 第②步）：从**写时打的「用途:xx」标签**取，
        # 不读 session（实测 remember 路径会话归属会丢），也不靠内容关键词。
        # **纯增量**：只多一个 purposes 映射，不进 terms/skel 词表 ⇒ 既有打分与桶名零变化。
        for _t in (fm.get("tags") or []):
            _ts = str(_t)
            if _ts.startswith("用途:"):
                purposes.setdefault(_ts, []).append(nid)
            elif _ts.startswith("项目:"):
                # 项目副键（goal-caf158e5）：**主归属**用项目（工作区）——实测节点无 workspace 字段、
                # 会话归属也不落盘，故只能从写时标签「项目:xx」取；同样纯增量，不进词表。
                projects.setdefault(_ts, []).append(nid)
    # 桶词表：{bucket_key: {term: 次数}} —— 供 scopeselect 打分（查询期只做字典运算）
    terms = {}
    skel = {}
    for nid, rec in nodes.items():
        fm = _fm(rec)
        d0 = day_of(fm.get("created_at"))
        sid0 = str(fm.get("session") or "") or UNATTRIBUTED
        names = []
        if d0:
            names.append("day:" + d0)
        if sid0 != UNATTRIBUTED:
            names.append("session:" + sid0)
        if not names:
            continue
        blob = []
        for key in ("tags", "bucket_zh", "bucket", "role", "content_kind"):
            val = fm.get(key)
            if isinstance(val, (list, tuple)):
                blob.extend(str(x) for x in val)
            elif val:
                blob.append(str(val))
        # 与检索面**同口径**分词（bm25.tokenize：汉字单字 + 相邻二元）。
        # 早期版本按标点切整句，查询里的短词（「商人」「蒙德城广场」）整词匹配不上，
        # 生产共现实测只有 34%；换成 n-gram 粒度后才可能与 bench 的「子串语义」对齐。
        # 密文/受限/私密域与退役/隔离层节点不得向明文桶词表与骨架泄露正文或词项
        if _is_sensitive_or_private(rec, fm) or _is_non_recallable(rec, fm):
            continue
        text = " ".join(blob).lower()
        body = ""
        if with_content:
            node = store.get(nid)
            nfm = (node or {}).get("frontmatter") if isinstance(node, dict) else None
            raw_content = (node or {}).get("content") if isinstance(node, dict) else None
            if (node
                    and not _is_sensitive_or_private(node, nfm)
                    and not _is_non_recallable(node, nfm)
                    and not _crypto.is_encrypted(raw_content)):
                body = str(raw_content or "")[:content_limit * 8].lower()
                if body:
                    text = text + " " + body
                    content_terms += 1
        toks = list(_bm25_tokenize(text))
        skel_part = (body if (with_content and body) else text)[:SKEL_CHARS_PER_NODE]
        for bucket in names:
            skel[bucket] = (skel.get(bucket, "") + "　" + skel_part)[:SKEL_CHARS_PER_BUCKET]
            bag = terms.setdefault(bucket, {})
            for t in toks[:content_limit]:
                bag[t] = bag.get(t, 0) + 1
    out = {"content_enriched": content_terms, "days": len(days), "sessions": len(sessions),
           # 用途副键计数（goal-caf158e5）：纯增量，只多一个读数，不改既有键与词表
           "purposes": len(purposes),
           "projects": len(projects),
           "nodes": len(nodes), "unattributed": unattributed}
    if write:
        root = getattr(store, "root", None)
        if root:
            for name, data in ((DAYS_FILE, days), (SESSIONS_FILE, sessions),
                              (TERMS_FILE, terms), (SKEL_FILE, skel)):
                path = os.path.join(root, name)
                _fsutil.atomic_write(path, json.dumps(data, ensure_ascii=False))
            # 构建统计落盘（含 purposes / projects 副键计数）：读面 info 由此取，零重算。
            _write_meta(store, out, time.time())
    return out


def _load(store, name):
    root = getattr(store, "root", None)
    if not root:
        return {}
    path = os.path.join(root, name)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def day_ids(store, day):
    return list(_load(store, DAYS_FILE).get(day) or ())


def session_ids(store, session):
    return list(_load(store, SESSIONS_FILE).get(str(session)) or ())


def all_days(store):
    """全部日桶键（升序未排序，调用方自行排序）。"""
    return list(_load(store, DAYS_FILE).keys())


#: 自动重建：元数据文件（记录上次重建时间与规模）。
META_FILE = "_bucketindex_meta.json"
#: 缺省重建间隔（小时）：每日收尾一次 ⇒ 20 小时���给抖动余量）。
DEFAULT_INTERVAL_H = 20.0
#: 自动重建开关的环境变量（缺省开；0=关）。
AUTO_ENV = "MDCG_BUCKET_AUTO"
INTERVAL_ENV = "MDCG_BUCKET_INTERVAL_H"

_RUNNING = {"on": False}
_RUNNING_LOCK = threading.Lock()
_RUNNING_ROOTS = set()


def _meta_path(store):
    root = getattr(store, "root", None)
    return os.path.join(root, META_FILE) if root else None


def last_stats(store):
    """读取上次构建的统计（含 purposes / projects 副键计数）；缺失或损坏返回 {}。

    为什么要它：副键计数此前只作为 build() 的返回值**算完即丢**，
    读面（cg op=info）看不到；而元数据文件本来就由 build() 写入，故直接读它，
    不新增文件、不重算全库。
    """
    p = _meta_path(store)
    if not p or not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def last_build_ts(store):
    p = _meta_path(store)
    if not p or not os.path.exists(p):
        return 0.0
    try:
        with open(p, encoding="utf-8") as fh:
            return float(json.load(fh).get("ts") or 0.0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def _write_meta(store, stats, ts):
    p = _meta_path(store)
    if not p:
        return
    try:
        payload = dict(stats)
        payload["ts"] = ts
        _fsutil.atomic_write(p, json.dumps(payload, ensure_ascii=False))
    except OSError:
        pass


def _age_round(age_h):
    """age_h is None when the index has never been built -- round(None, 2) raises."""
    return None if age_h is None else round(age_h, 2)


def maybe_auto_rebuild(store, interval_h=None, background=True):
    """每日收尾式自动重建：距上次重建超过 interval 小时才重建。

    为什么这样设计：主库重建 3–5 秒，**不能**卡在写入或查询路径上，
    故（a）只在「陈旧」时触发，（b）缺省放后台线程跑；
    并有模块级 `_RUNNING` 防重入（同一进程内不会并发重建）。

    返回 {"rebuilt": bool, "reason": str, "age_h": float, ...}，便于调用方审计。
    """
    if os.environ.get("MDCG_BUCKET_AUTO", "1") == "0":
        return {"rebuilt": False, "reason": "disabled"}
    if interval_h is not None:          # 显式参数优先（0 = 强制重建）
        if isinstance(interval_h, bool):
            interval = DEFAULT_INTERVAL_H
        else:
            try:
                interval = float(interval_h)
            except (TypeError, ValueError):
                interval = DEFAULT_INTERVAL_H
            if not math.isfinite(interval) or interval < 0.0:
                interval = DEFAULT_INTERVAL_H
    else:
        try:
            interval = float(os.environ.get("MDCG_BUCKET_INTERVAL_H", "20"))
        except ValueError:
            interval = DEFAULT_INTERVAL_H
        if not math.isfinite(interval) or interval < 0.0:
            interval = DEFAULT_INTERVAL_H
    # Single read of ts: the original read last_build_ts twice here, so a rebuild
    # thread writing the meta between the two reads made age_h disagree with the
    # value the staleness decision used.
    last_ts = last_build_ts(store)
    # When never rebuilt, last_ts == 0 and (now - 0) / 3600 yields the number of
    # hours since the Unix epoch (measured: 1794589724 / 3600 = 498497.05 h, i.e.
    # ~56.7 years). That reports "never rebuilt" as "rebuilt very long ago".
    # Semantically this is "no history", so report None instead of a bogus number.
    age_h = None if last_ts <= 0 else (time.time() - last_ts) / 3600.0
    if last_ts > 0 and age_h < interval:
        return {"rebuilt": False, "reason": "fresh", "age_h": _age_round(age_h)}
    root_raw = getattr(store, "root", None)
    root_key = os.path.abspath(str(root_raw)) if root_raw else f"mem:{id(store)}"
    with _RUNNING_LOCK:
        if root_key in _RUNNING_ROOTS:
            return {"rebuilt": False, "reason": "running", "age_h": _age_round(age_h)}
        _RUNNING_ROOTS.add(root_key)
        _RUNNING["on"] = True

    def _job():
        try:
            stats = build(store, write=True)
            _write_meta(store, stats, time.time())
        except Exception:          # noqa: BLE001 —— 后台失败不得影响主流程
            pass
        finally:
            with _RUNNING_LOCK:
                _RUNNING_ROOTS.discard(root_key)
                _RUNNING["on"] = bool(_RUNNING_ROOTS)

    if background:
        try:
            threading.Thread(target=_job, daemon=True).start()
        except Exception:          # noqa: BLE001 —— 启动线程失败必须释放占锁
            with _RUNNING_LOCK:
                _RUNNING_ROOTS.discard(root_key)
                _RUNNING["on"] = bool(_RUNNING_ROOTS)
            return {"rebuilt": False, "reason": "spawn_failed", "age_h": _age_round(age_h)}
        return {"rebuilt": True, "reason": "stale", "age_h": _age_round(age_h), "async": True}
    _job()
    return {"rebuilt": True, "reason": "stale", "age_h": _age_round(age_h), "async": False}