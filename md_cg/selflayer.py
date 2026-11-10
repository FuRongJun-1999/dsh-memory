# -*- coding: utf-8 -*-
"""self 层：关于我自己的、可被召回的主张（P3-5 物化器 + 独立取数腿）。

设计真源 `D:\\wook\\audit\\MEMORY-DESIGN-p34-p35-2026-10-29.md` §3。

三条纪律（对齐设计 §3.2）：
  1. **没有读数就不许写**：`evidence` 为空一律 `ValueError("evidence_empty")`；
     主张必须指向 JSONL 的具体行号，不接受「我觉得」。
  2. **方向一致才物化**：同一维度最近 `require`（默认 3）次采样方向不翻转。
  3. **自我认知会过期**：`effective_until` 必填（默认 +30 天），过期即从取数腿消失
     —— 过期不是删除，节点仍在 `self/`，只是不再注入。

为什么字段写在正文而不是 frontmatter：
  索引条目字段是共享形状（P2-8 刚做过「恒空字段剔除」），为一条新腿加自定义
  frontmatter 键会让索引膨胀且丢进恒空统计；正文用 `# 键：值` 行，取数腿解析，
  零索引代价。

生效条件（**R-401b 校正，2026-11-10**）：本模块目前**没有任何调用点** ——
`materialize()` 与 `claims()` 都未接线。原注释声称的两个入口
（一个 cron 侧物化脚本、一个 `cg(op="self_claims")` 工具）经机械扫描确认
**均未落盘**（脚本从未创建，op 不在 `op_table._OP_TABLE` 的 38 个 op 里）。
故「本层已在用」的说法不成立；要启用需先补入口 + 一个守卫。
设计意图（未变）：两者都不参与主检索排序（`RECALL_SKIP_LAYERS` 含 `self`）。
"""
import hashlib
import json
import os
import re
import time

LAYER = "self"
PREFIX = "slf_"
TTL_DAYS = 30
RECHECK_DAYS = 7
CLAIM_MAX = 160
IMPORTANCE_CAP = 0.6

_EXP_RE = re.compile(r"^# 有效期至：(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\s*$", re.M)
_CLAIM_RE = re.compile(r"^# 主张：(.+)$", re.M)
_DIM_RE = re.compile(r"^# 维度：(.+)$", re.M)


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def _nid(dimension, claim):
    return PREFIX + hashlib.sha256((dimension + "|" + claim).encode("utf8")).hexdigest()[:12]


def _body(claim, dimension, evidence, effective_until, recheck_after):
    ev = "\n".join("#   %d. %s" % (i + 1, e) for i, e in enumerate(evidence))
    return ("# 主张：%s\n"
            "# 维度：%s\n"
            "# 证据：\n%s\n"
            "# 有效期至：%s\n"
            "# 复核：%s\n"
            "# 物化：self-materialize.py\n") % (
        claim, dimension, ev, _iso(effective_until), _iso(recheck_after))


def add_claim(cg, claim, dimension, evidence, now=None, ttl_days=TTL_DAYS,
              importance=0.5, dry=False):
    """写一条自我主张。evidence 为空 ⇒ ValueError（判据 S2 的落点）。"""
    claim = (claim or "").strip()
    dimension = (dimension or "").strip()
    if not claim:
        raise ValueError("claim_empty")
    if len(claim) > CLAIM_MAX:
        raise ValueError("claim_too_long:%d>%d" % (len(claim), CLAIM_MAX))
    if not dimension:
        raise ValueError("dimension_empty")
    ev = [e for e in (evidence or []) if str(e).strip()]
    if not ev:
        raise ValueError("evidence_empty")
    now = time.time() if now is None else float(now)
    eu = now + ttl_days * 86400
    ra = now + RECHECK_DAYS * 86400
    nid = _nid(dimension, claim)
    out = {"ok": True, "id": nid, "dimension": dimension,
           "effective_until": eu, "evidence_n": len(ev)}
    if dry:
        out["dry"] = True
        return out
    body = _body(claim, dimension, ev, eu, ra)
    tags = ["self", "dimension:" + dimension, "claim"]
    imp = min(IMPORTANCE_CAP, max(0.0, float(importance)))
    # 同一维度 + 同一主张 → id 确定，重跑会撞同一颗节点，而 self 层是**不可篡改层**
    # （`md_cg/protect.py` 层保护：覆盖需显式 override=True）。这不是异常路径而是常态：
    # 主张每天被重新确认一次，有效期据此顺延。2026-10-29 实测：不加 override 时
    # cron 每次都记一条 ProtectionError，主张停在首日 TTL，第二天起就全部过期不注入。
    exists = nid in (((cg.index or {}).get("nodes")) or {})
    if exists:
        # 续期必须**直接写**，不能走 `remember_gated`：gated 在 plan 档自治下会把
        # 覆盖动作变成一条 mutation 提案丢进审核队列 —— 提案不会自己落地，于是
        # 主张的 `effective_until` 永远停在首日，30 天后集体过期，注入面静默变空，
        # 而队列每天稳定长 2 条（2026-10-29 实测 pending 7→8 只增不减）。
        # `add(..., override=True)` 才是「我确认这条还是原话，只是顺延有效期」。
        # 层保护仍生效：不带 override 会被 `protect` 拦（self 层不可篡改）。
        cg.add(nid, body, layer=LAYER, tags=tags, importance=imp,
               sensitivity="internal", verification_basis="other",
               effective_from=now, override=True)
        out["refreshed"] = True
    else:
        cg.add(nid, body, layer=LAYER, tags=tags, importance=imp,
               sensitivity="internal", verification_basis="other",
               effective_from=now)
    return out


def _tail(path, n):
    if not os.path.exists(path):
        return []
    lines = open(path, encoding="utf8").read().strip().split("\n")
    out = []
    for idx, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            out.append((idx, json.loads(line)))
        except Exception:
            continue
    return out[-n:]


def _consistent(rows, key):
    """最近 len(rows) 次同键取值是否方向一致（全等）。

    接受两种入参：`[(行号, dict), …]` 或 `[dict, …]`（同一键两种调用都出现过，
    2026-10-29 首跑时就是这里 `too many values to unpack`）。
    """
    vals = []
    for r in rows:
        if isinstance(r, tuple):
            r = r[1] if len(r) > 1 else None
        if isinstance(r, dict):
            vals.append(r.get(key))
    if len(vals) < len(rows) or not vals:
        return None
    return vals[0] if all(v == vals[0] for v in vals) else None


def materialize(cg, root=None, now=None, require=3, ttl_days=TTL_DAYS, dry=False):
    """把三条反思管线的稳定结论物化成 self 主张。返回读数，不抛。"""
    root = root or getattr(cg, "root", None) or ""
    now = time.time() if now is None else float(now)
    meta_p = os.path.join(root, "_metacognition.jsonl")
    self_p = os.path.join(root, "_self_state.jsonl")
    refl_p = os.path.join(root, "_reflection.jsonl")

    checked, written, skipped, rows_out = 0, [], [], []

    def try_one(claim, dimension, evidence, importance):
        nonlocal checked
        checked += 1
        try:
            r = add_claim(cg, claim, dimension, evidence, now=now,
                          ttl_days=ttl_days, importance=importance, dry=dry)
            written.append({"dimension": dimension, "claim": claim,
                            "id": r["id"], "effective_until": r["effective_until"]})
        except Exception as exc:  # noqa: BLE001 —— 物化器不抛
            skipped.append({"dimension": dimension, "reason": "%s: %s" % (type(exc).__name__, exc)})

    # ① 置信度校准：最近 require 次 calibration_verdict 全等且非空
    mrows = _tail(meta_p, require)
    if len(mrows) == require:
        v = _consistent([r for _, r in mrows], "calibration_verdict")
        if v:
            ev = ["_metacognition.jsonl:%d (calibration_verdict=%s, gap=%s)" %
                  (ln, v, r.get("gap")) for ln, r in mrows]
            gaps = [r.get("gap") for _, r in mrows]
            tail = ("，gap=%s" % gaps[-1]) if gaps and gaps[-1] is not None else ""
            try_one("我的置信度校准连续 %d 次为 %s%s" % (require, v, tail),
                    "calibration", ev, 0.55)
        # ①b 盲区信号：最近 require 次 advice 都含同一标记（元认知自陈「这批检索出问题」）
        adv = [r.get("advice") or [] for _, r in mrows]
        for tag in ("blindspot_dense", "underconfident"):
            if all(isinstance(a, list) and tag in a for a in adv):
                ev = ["_metacognition.jsonl:%d (advice 含 %s)" % (ln, tag) for ln, _ in mrows]
                try_one("连续 %d 次元认知采样都判出 %s" % (require, tag),
                        tag.replace("_dense", ""), ev, 0.5)

    # ② 情绪/自评状态：最近 require 次 affect 全等
    srows = _tail(self_p, require)
    if len(srows) == require:
        for key, dim, imp, word in (("affect", "affect", 0.4, "自评状态"),
                                    ("emotion", "emotion", 0.4, "情绪")):
            v = _consistent([r for _, r in srows], key)
            if v:
                ev = ["_self_state.jsonl:%d (%s=%s)" % (ln, key, v) for ln, r in srows]
                try_one("%s连续 %d 次采样为 %s" % (word, require, v), dim, ev, imp)
        # ③ 信任度：最近 require 次 p_trust 全等且非 None
        pt = [r.get("p_trust") for _, r in srows]
        if pt and pt[0] is not None and all(p == pt[0] for p in pt):
            ev = ["_self_state.jsonl:%d (p_trust=%s)" % (ln, r.get("p_trust")) for ln, r in srows]
            try_one("对自身预测的信任度连续 %d 次为 %s" % (require, pt[0]),
                    "trust", ev, 0.45)

    # ④ 判断力维度：最近 require 次 d_current 全等且非 None
    rrows = _tail(refl_p, require)
    if len(rrows) == require:
        ds = [r.get("d_curr") for _, r in rrows]
        if ds and ds[0] is not None and all(d == ds[0] for d in ds):
            ev = ["_reflection.jsonl:%d (d_curr=%s)" % (ln, r.get("d_curr")) for ln, r in rrows]
            try_one("判断力维度 d_current 连续 %d 次为 %s" % (require, ds[0]),
                    "d_current", ev, 0.45)

    rows_out = {"checked": checked, "written_n": len(written),
                "skipped_n": len(skipped), "written": written, "skipped": skipped}
    return {"ok": True, "now": now, **rows_out}


def claims(cg, limit=3, now=None):
    """独立取数腿：未过期的自我主张，按有效期升序。"""
    now = time.time() if now is None else float(now)
    nodes = (cg.index or {}).get("nodes") or {}
    out = []
    for nid, ent in nodes.items():
        if ent.get("layer") != LAYER:
            continue
        tags = ent.get("tags") or []
        if "claim" not in tags:
            continue
        try:
            node = cg.get(nid)
        except Exception:
            node = None
        if not node:
            continue
        body = node.get("content") or ""
        m = _EXP_RE.search(body)
        if not m:
            continue
        try:
            eu = time.mktime(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            continue
        if eu <= now:
            continue
        c = _CLAIM_RE.search(body)
        d = _DIM_RE.search(body)
        out.append({"id": nid, "claim": (c.group(1).strip() if c else ""),
                    "dimension": (d.group(1).strip() if d else ""),
                    "effective_until": eu})
    out.sort(key=lambda r: r["effective_until"])
    return {"ok": True, "count": len(out), "items": out[:max(1, int(limit))]}


def move_legacy(cg, to_layer="structural", dry=True, limit=None):
    """存量审计副本移层（设计 §3.5 方案甲：保留审计可查，零丢失）。"""
    nodes = (cg.index or {}).get("nodes") or {}
    moved, failed = [], []
    for nid, ent in list(nodes.items()):
        if ent.get("layer") != LAYER:
            continue
        tags = ent.get("tags") or []
        legacy = ("audit" in tags or "review-record" in tags or nid.startswith("rev_"))
        if not legacy or "claim" in tags:
            continue
        if limit is not None and len(moved) + len(failed) >= int(limit):
            break
        if dry:
            moved.append({"id": nid, "dry": True})
            continue
        try:
            node = cg.get(nid)
            if not node:
                failed.append({"id": nid, "reason": "unreadable"})
                continue
            body = node.get("content") or ""
            fm = node.get("frontmatter") or {}
            cg.add(nid, body, layer=to_layer,
                   tags=list(dict.fromkeys((fm.get("tags") or []) + ["moved:from-self"])),
                   importance=fm.get("importance", 0.2),
                   sensitivity=fm.get("sensitivity") or "internal",
                   override=True)
            moved.append({"id": nid, "to": to_layer})
        except Exception as exc:  # noqa: BLE001
            failed.append({"id": nid, "reason": "%s: %s" % (type(exc).__name__, exc)})
    return {"ok": not failed, "moved_n": len(moved), "failed_n": len(failed),
            "moved": moved, "failed": failed, "dry": dry}
