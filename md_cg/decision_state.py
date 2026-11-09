r"""决策状态快照（M8）：把「证据」与「决策取数」解耦。

设计稿见 `D:\wook\audit\M8-PLAN.md`。要点：
- 证据文件（`_forgetting.jsonl` / `_audit.jsonl`）仍是唯一权威，只追加；
- 本模块把「R1/R3 决策所需的计数与序列」预计算成 `_decision_state.json`（30 天窗稳态约 57 KB）；
- 读侧先校验（文件不存在/损坏/schema/形状/窗口常量/stale）→ 任一不过一律回退原慢路径；
- 偏移落后（进程崩在 append 与 save 之间）→ 就地增量追上，不报错、不出错数；
- 轮转（ino 变 / size 变小）→ 该面从头重读。

纪律：证据是主，快照是仆。本模块任何失败都必须吞掉，不许影响证据写入。
"""

from __future__ import annotations

import json
import os
import time

STATE_FILE = "_decision_state.json"
METRICS_FILE = "_decision_state.metrics.json"
SCHEMA = 3
SLACK = 3 * 3600.0          # 保留带余量：now_read >= generated_t - 3h 即精确
DEBOUNCE_S = 2.0            # 攒够这么多秒才落一次盘
DEBOUNCE_N = 64             # 或攒够这么多条

_DIRTY = {}                 # root -> {"faces": set(), "pending": int}
_LAST_SAVE = {}             # root -> t


def _A():
    """延迟 import，避免与 admission 循环引用。"""
    from . import admission  # noqa: WPS433
    return admission


def _now(now=None):
    return time.time() if now is None else float(now)


def _wl():
    a = _A()
    return float(a.WINDOW_LONG_D) * float(a.DAY)


def _paths(root, sd=None):
    d = sd or root
    return os.path.join(d, STATE_FILE), os.path.join(d, METRICS_FILE)


def _atomic_json(path, obj):
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp-%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, path)


def _empty():
    return {"schema": SCHEMA, "generated_t": 0.0, "window_d": 0,
            "offsets": {"forgetting": {"size": 0, "ino": 0},
                        "audit": {"size": 0, "ino": 0}},
            "forgetting": {"all_total": 0, "all_verdicts": {}, "undated_all": 0,
                           "verdicts": [], "ts_base_ms": 0, "ts_delta_ms": [],
                           "ks": [], "last_ms": 0, "n": 0},
            "audit": {"first_forget_at": {}, "restores": []},
            "metrics": {"builds": 0, "full_rebuilds": 0, "last_build_ms": 0.0,
                        "trimmed": 0}}


def load(root, sd=None):
    """(state, reason)，reason ∈ ok|missing|corrupt|io|shape|schema|window。"""
    try:
        with open(_paths(root, sd)[0], "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return None, "missing"
    except json.JSONDecodeError:
        return None, "corrupt"
    except OSError:
        return None, "io"
    except Exception:
        return None, "corrupt"
    if not isinstance(d, dict):
        return None, "shape"
    if d.get("schema") != SCHEMA:
        return None, "schema"
    try:
        if int(d.get("window_d") or 0) != int(_A().WINDOW_LONG_D):
            return None, "window"
    except Exception:
        return None, "shape"
    return d, "ok"


def save(root, st, sd=None):
    p = _paths(root, sd)[0]
    _atomic_json(p, st)
    return p


def note_fallback(root, reason, sd=None):
    """回退计数写在快照**外面**，这样快照丢了也能知道发生过回退。

    只在 metric 文件已存在时落盘（由写者侧 bump 首次创建）——纯读路径一个字节都不写，
    否则「读不许改库指纹」这条纪律就被 metric 破了。
    """
    p = _paths(root, sd)[1]
    try:
        with open(p, "r", encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict):
            m = {}
    except Exception:
        return {}
    m["fallback_reads"] = int(m.get("fallback_reads", 0)) + 1
    m["last_reason"] = reason
    m["last_t"] = time.time()
    m[reason] = int(m.get(reason, 0)) + 1
    try:
        _atomic_json(p, m)
    except Exception:
        pass
    return m


def _sig(path):
    try:
        st = os.stat(path)
        return {"ino": int(getattr(st, "st_ino", 0)), "size": int(st.st_size)}
    except OSError:
        return {"ino": 0, "size": 0}


def _tail(path, offset):
    """从字节偏移读增量，返回 (records, end_offset)；end_offset 只到最后一个换行。"""
    if not os.path.exists(path):
        return [], offset
    try:
        if os.path.getsize(path) < offset:
            return [], 0
        with open(path, "rb") as f:
            f.seek(offset)
            buf = f.read()
    except OSError:
        return [], offset
    if not buf:
        return [], offset
    cut = buf.rfind(b"\n")
    if cut < 0:
        return [], offset
    out = []
    for raw in buf[:cut + 1].split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out, offset + cut + 1


def build(root, now=None, sd=None, incremental=True):
    now = _now(now)
    t0 = time.perf_counter()
    a = _A()
    wl = _wl()
    st = None
    if incremental:
        st, _why = load(root, sd)
    if st is None:
        st = _empty()
        st["metrics"]["full_rebuilds"] += 1
    st["window_d"] = int(a.WINDOW_LONG_D)
    F = st["forgetting"]
    cut = now - wl - SLACK

    # ---- 面 1：_forgetting.jsonl ----
    fp = os.path.join(root, a.FORGETTING_LOG)
    sig_f = _sig(fp)
    prev_f = st["offsets"].get("forgetting") or {"size": 0, "ino": 0}
    fo = int(prev_f.get("size", 0))
    if prev_f.get("ino") not in (0, sig_f["ino"]) or sig_f["size"] < fo:
        fo = 0
        st["forgetting"] = _empty()["forgetting"]
        F = st["forgetting"]
    frecs, fo2 = _tail(fp, fo)
    if frecs:
        vocab = F["verdicts"]
        idx = {v: i for i, v in enumerate(vocab)}
        for rec in frecs:
            v = str(rec.get("verdict") or "?")
            F["all_verdicts"][v] = F["all_verdicts"].get(v, 0) + 1
            F["all_total"] += 1
            t = a._ts(rec)
            if t is None:
                F["undated_all"] += 1
                continue
            if v not in idx:
                idx[v] = len(vocab)
                vocab.append(v)
            tm = int(round(float(t) * 1000.0))
            if F["n"] == 0:
                F["ts_base_ms"] = tm
                F["ts_delta_ms"].append(0)
            else:
                F["ts_delta_ms"].append(tm - int(F["last_ms"]))
            F["ks"].append(idx[v])
            F["n"] += 1
            F["last_ms"] = tm
    st["offsets"]["forgetting"] = {"size": fo2, "ino": sig_f["ino"]}

    # ---- 面 2：_audit.jsonl（只活动分片） ----
    ap = os.path.join(root, a.DEVICE_AUDIT)
    sig_a = _sig(ap)
    prev_a = st["offsets"].get("audit") or {"size": 0, "ino": 0}
    ao = int(prev_a.get("size", 0))
    if prev_a.get("ino") not in (0, sig_a["ino"]) or sig_a["size"] < ao:
        ao = 0
        st["audit"] = {"first_forget_at": {}, "restores": []}
    arecs, ao2 = _tail(ap, ao)
    U = st["audit"]
    for rec in arecs:
        op, nid, t = rec.get("op"), rec.get("id"), a._ts(rec)
        if not nid or t is None:
            continue
        nid = str(nid)
        if op == "forget":
            if nid not in U["first_forget_at"] or t < U["first_forget_at"][nid]:
                U["first_forget_at"][nid] = float(t)
        elif op == "restore":
            U["restores"].append([float(t), nid])
    st["offsets"]["audit"] = {"size": ao2, "ino": sig_a["ino"]}

    # ---- 裁掉真正老掉的一段（O(aged)） ----
    if F["n"] and (float(F["ts_base_ms"]) / 1000.0) < cut:
        keep = 0
        cur = int(F["ts_base_ms"])
        new_base = cur
        while keep < F["n"]:
            cur = int(F["ts_base_ms"]) if keep == 0 else cur + int(F["ts_delta_ms"][keep])
            if (float(cur) / 1000.0) >= cut:
                new_base = cur
                break
            keep += 1
        else:
            new_base = 0
        if keep:
            F["ts_delta_ms"] = F["ts_delta_ms"][keep:]
            F["ks"] = F["ks"][keep:]
            F["n"] = len(F["ks"])
            F["ts_base_ms"] = new_base
            if F["ts_delta_ms"]:
                F["ts_delta_ms"][0] = 0
            st["metrics"]["trimmed"] += keep
    U["restores"] = [r for r in U["restores"] if r[0] >= cut]

    st["generated_t"] = now
    st["metrics"]["builds"] += 1
    st["metrics"]["last_build_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    return st


def _walk(F):
    """按毫秒差还原每条记录的时间（float 秒）。"""
    cur = int(F["ts_base_ms"])
    for i, (dt, k) in enumerate(zip(F["ts_delta_ms"], F["ks"])):
        cur = int(F["ts_base_ms"]) if i == 0 else cur + int(dt)
        yield float(cur) / 1000.0, k


def covered(st, now=None, slack=SLACK):
    return _now(now) >= (float(st.get("generated_t") or 0.0) - slack)


def r1_counts(st, now=None):
    now = _now(now)
    a = _A()
    wl = _wl()
    F = st["forgetting"]
    vocab = F["verdicts"]
    by, total = {}, 0
    for t, k in _walk(F):
        if 0 <= (now - t) <= wl:
            v = vocab[k]
            by[v] = by.get(v, 0) + 1
            total += 1
    seen = {v: by.get(v, 0) for v in a.R1_VERDICTS}
    missing = [v for v, n in seen.items() if n < a.R1_MIN_ONE]
    top = max(by, key=by.get) if by else None
    share = (by[top] / total) if total else None
    return {"by_win": by, "total_win": total, "by_all": F["all_verdicts"],
            "total_all": F["all_total"], "undated_all": F["undated_all"],
            "seen": seen, "missing": missing, "top": top, "share": share}


def r3_d_face(st, now=None, lo=None):
    now = _now(now)
    lo = (now - _wl()) if lo is None else float(lo)
    fa = st["audit"]["first_forget_at"]
    ev = []
    for t, nid in st["audit"]["restores"]:
        ft = fa.get(nid)
        if ft is not None and ft < t and lo <= t <= now:
            ev.append({"source": "audit_restore", "node_id": nid, "t": t,
                       "forget_t": ft,
                       "detail": "删（%.0f）→ 回（%.0f）" % (ft, t)})
    return ev


def _stale_offsets(root, st):
    a = _A()
    out = []
    for face, name in (("forgetting", a.FORGETTING_LOG), ("audit", a.DEVICE_AUDIT)):
        cur = _sig(os.path.join(root, name))
        old = st["offsets"].get(face) or {"size": 0, "ino": 0}
        if cur["ino"] != old.get("ino") or cur["size"] != old.get("size"):
            out.append(face)
    return out


def read_verified(root, now=None, sd=None):
    """返回可用快照；任一守卫不过返回 None（调用方回退慢路径）。"""
    st, why = load(root, sd)
    if st is None:
        note_fallback(root, why, sd)
        return None
    if not covered(st, now):
        note_fallback(root, "stale", sd)
        return None
    try:
        if _stale_offsets(root, st):
            # 读路径**不落盘**（E9 纪律：读不许改库指纹）；只在内存里追平，
            # 真正的持久化交给写者侧的 bump()。
            st = build(root, now, sd, incremental=True)
    except Exception:
        note_fallback(root, "io", sd)
        return None
    return st


def bump(root, face):
    """证据追加后调用：标脏 + 去抖落盘。任何异常都必须吞掉。"""
    try:
        now = time.time()
        d = _DIRTY.setdefault(root, {"faces": set(), "pending": 0})
        d["faces"].add(face)
        d["pending"] += 1
        last = float(_LAST_SAVE.get(root) or 0.0)
        if d["pending"] >= DEBOUNCE_N or (now - last) >= DEBOUNCE_S:
            st = build(root, now, incremental=True)
            save(root, st)
            mp = _paths(root, None)[1]
            if not os.path.exists(mp):      # 首次落盘时把 metric 面建出来（读侧才有地方累加）
                try:
                    _atomic_json(mp, {"fallback_reads": 0, "last_reason": None,
                                      "last_t": now})
                except Exception:
                    pass
            d["faces"].clear()
            d["pending"] = 0
            _LAST_SAVE[root] = now
        return True
    except Exception:
        return False


def metrics(root, sd=None):
    try:
        with open(_paths(root, sd)[1], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
