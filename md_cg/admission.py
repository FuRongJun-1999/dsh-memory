# -*- coding: utf-8 -*-
"""三档自治 · 准入读数 R1–R4 与准入闸（设计 v0.2 §六/§七 · 批次④）。

设计真源（`docs/plans/记忆自处理三档自治_设计_v0.2.md`，已签收冻结）：
  · §七「放权阶梯与准入读数」——四条读数 R1–R4、门槛、窗口（裁定③：
    长期 30 天 / 短期 3 天）；「读数即断言……常驻断言（`conformance`/`census`
    家族，只告警不改数据），随时可答『它今天够格吗』」；
  · §六「完全访问·准入」——不满足时该档**不可选中**（fail-closed 并报
    「缺哪一条读数」，不静默降级）；
  · §十一「验收判据」——R1–R4 各有独立断言与一组「门槛刚过/刚不过」的
    边界用例（含窗口边界 3 天 / 30 天）。

三条纪律（与 `conformance` 家族同口径）：
  1. **只读**：本模块不写任何文件——读数与准入判定都不改数据（设计 §七
     「只告警不改数据」）。
  2. **如实**：窗口样本不足 ⇒ 该读数 `ok=None`（「不可判」），绝不冒充
     PASS；缺数据面 ⇒ 在读数体里指名缺哪个文件；有未纳入的归档面 ⇒
     在 `detail` 里如实点名（见 R3）。
  3. **不静默**：`ok` 不满足时读数体给出 `missing`/`detail`，由调用方
     （`autonomy_modes.settle`）原样报出——报「缺哪一条读数」。

四条读数（判据逐字照设计 §七 表；窗口 = 裁定③）：

  **R1 判断非退化**（长期 30 天）：`_forgetting.jsonl` 窗口内 DROP/MERGE/DEFER
  各自出现过，且单一 verdict 占比 < 90%。数据面 `_forgetting.jsonl`；另附
  全量分布 `summary_all`（与 `forgetting.summary` 同源同口径——两处都流式
  聚合同一个文件；本模块为保持热路径 import 面轻量不引 `forgetting`，
  守卫有常量一致性断言钉死同值）。

  **R2 会说「不」**（短期 3 天 + 长期 30 天总量）：`rejected/` 与 `unresolved/`
  两层**近期新增**——3 天内各 ≥1，且 30 天总量各 ≥1。判窗用节点
  `frontmatter.created_at`（实测两层的 add 均落该键）；无 `created_at` 的
  节点计入 `undated` 不计窗（如实，不猜文件 mtime）。

  **R3 破坏可逆且「回过」**（长期 30 天）：30 天内 ≥1 次**真实回滚**。
  **探针实测（步骤③报告 §6.1 第 3 条）**：回滚无独立留痕——`rollback_mutation`
  不写台账；C/B 回滚前后 `decisions.jsonl`/`_audit.jsonl` 零新增；D 回滚经
  `restore` 写 `_audit.jsonl` 但行内不含 pid。故本读数用**状态推断**两条
  证据面（`method="state_inference"`，逐条如实标注）：
    · **D 面**（`audit_restore`）：活动分片 `_audit.jsonl` 的 `op="restore"`
      行（时刻在 30 天窗内）且同 id 有**更早**的 `op="forget"` 行
      ⇒「删过又回过」；
    · **C/B 面**（`preimage_pair`）：`decisions.jsonl` 的 accept 执行记录
      （30 天窗内、`rec["mutation"]` 为 dict）＋ 执行时点前像在位
      （`_protected_history/` 文件 + `_protected_audit.jsonl` 的
      `action="preimage"` 行）＋ **现盘面与该前像逐字节相等** ⇒
      「曾变更且现回到前像」。
  成本边界（如实）：`_audit.jsonl` 只读**活动分片**；库存在归档分片
  （`_audit_archive/`，在役实测 8 片 ≈ 536MB）时**不**读（准入检查须限
  成本），读数体在 `archived_shards` / `detail` 里如实点名——落在归档里的
  `restore` 会被漏计（留池：需要时离线全扫）。

  **R4 判断收敛**（长期 30 天内 3 个 10 天子窗）：驳回率（reject+edit ÷
  全部裁定）**逐窗严格下降**且最近子窗 < 20%。任一子窗无裁定样本 ⇒
  `ok=None`「不可判」（窗口不足 3 个子窗，如实上报，不假装）。

触发频度与缓存（契约「关键约束」的落点）：`gate()` 是读数唯一入口，
带**进程级 TTL 缓存**（缺省 60s；键 = root 绝对路径）——热路径
（`autonomy_modes.mode()`/`decide()`）**零 IO**：只读 `settle()` 冻结的
结算态；批量 `settle()` 在 TTL 内复用读数（不重扫）。稳态下一次完整
读数扫描频率 ≤ 1 次 / TTL。在役库实测：一次完整扫描 ≈ 0.3s（主成本 =
`_audit.jsonl` 10.5 万行流式 0.26s；`_forgetting.jsonl`/`decisions.jsonl`
均 < 0.05s）——TTL=60s 即最坏每分钟一次。

CLI（「全入口可答『它今天够格吗』」）：
    python -X utf8 -m md_cg.admission [--root R] [--json out.json] [--ttl N]
退出码：0 = 四条全满足；1 = 有未满足或不可判；2 = root 不可读。

**补强批次（v1.1，2026-10-02）**：数值容错收口——`_ts`/`_fm_ts` 对不可表示的
时间戳值（超出 float 范围的整数型数值、±inf、NaN 等）一律**视同缺时间戳**
（返回 None ⇒ 读数的 `undated` 桶），**不抛**：口径与 `_stream_jsonl`「坏行
跳过不抛」、`_ts` docstring「非正数返回 None」一致（前述纪律②「如实」）。
四条读数与 `check()` 对含此类坏值的数据面不再崩溃（补强前：
`{"t": <400 位整数>}` 使 `float(v)` 抛 `OverflowError`、级联 R1–R4/`check`/
`settle` 全崩——复核 uncovered，见步骤④报告 §5.3/§六.12）；合法数值行为
逐位不变。数值闸单点见 `_as_ts`。

不适用条件：不做常驻巡检的自动接线（本批落读数与判定单点；挂 sustain/
启动面的接线由调用方按需调用 `gate`/`settle`，见 `autonomy_modes.settle`）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import nodefile

__all__ = [
    "DAY", "WINDOW_SHORT_D", "WINDOW_LONG_D",
    "R1_MAX_SHARE", "R1_VERDICTS", "R2_MIN_RECENT", "R2_MIN_TOTAL",
    "R3_MIN_ROLLBACKS", "R4_MAX_RATE", "R4_SUBWINDOWS", "R4_SUBWINDOW_D",
    "TTL_DEFAULT", "FORGETTING_LOG", "DEVICE_AUDIT", "PROTECT_AUDIT",
    "DECISIONS_LOG", "LAYERS_SAY_NO",
    "r1_non_degenerate", "r2_says_no", "r3_reversible", "r4_converging",
    "check", "gate", "cache_stats", "reset_cache", "default_root", "render",
    "main",
]

DAY = 86400.0
#: 裁定③：短期 = 3 天（R2 活性读数）；长期 = 30 天（R1/R3/R4 能力读数）。
WINDOW_SHORT_D = 3
WINDOW_LONG_D = 30

#: R1：单一 verdict 占比上限（严格小于——「恰 90%」不满足）。
R1_MAX_SHARE = 0.90
#: R1：必须各自出现过的 verdict 三态（设计 §七 表逐字）。
R1_VERDICTS = ("DROP", "MERGE", "DEFER")
#: R1 三态「各自出现过」的计数下限（>0）。
R1_MIN_ONE = 1

#: R2：短期 3 天内每层新增下限；长期 30 天总量每层下限。
R2_MIN_RECENT = 1
R2_MIN_TOTAL = 1
#: R2 计数面两层（设计 §九「它今天拒绝过吗 / 它不确定过吗」）。
LAYERS_SAY_NO = ("rejected", "unresolved")

#: R3：30 天内真实回滚次数下限。
R3_MIN_ROLLBACKS = 1

#: R4：3 个 10 天子窗；最近子窗驳回率上限（严格小于——「恰 20%」不满足）；
#: 「逐窗下降」取**严格递减**读法（平坦不算下降）。
R4_MAX_RATE = 0.20
R4_SUBWINDOWS = 3
R4_SUBWINDOW_D = 10.0

#: 读数缓存 TTL（秒）——探针定：在役库一次完整扫描 ≈ 0.3s（主成本 =
#: `_audit.jsonl` 10.5 万行流式 0.26s），TTL=60s ⇒ 最坏每分钟一次，热路径零 IO。
TTL_DEFAULT = 60.0

# ---- 数据面文件名（字面量出处；守卫有常量一致性断言钉死与真源同值）----------
#: = `forgetting.LOG_FILE`（按值复制：引 forgetting 会把 crypto/mdcg 重依赖
#: 拉进本模块的 import 面；一致性由守卫断言 `== forgetting.LOG_FILE` 保证）。
FORGETTING_LOG = "_forgetting.jsonl"
#: = `mdcos` 的设备审计活动分片（root 下 `_audit.jsonl`；归档在 `_audit_archive/`）。
DEVICE_AUDIT = "_audit.jsonl"
#: = `protect.AUDIT_FILE`（前像/快照审计）。
PROTECT_AUDIT = "_protected_audit.jsonl"
#: = `mdcos` 的裁决记录（`hippocampus/decisions.jsonl`）。
DECISIONS_LOG = os.path.join("hippocampus", "decisions.jsonl")
#: = `mdcos.AUDIT_ARCHIVE`（归档分片目录；R3 不读、只计数如实点名）。
AUDIT_ARCHIVE = "_audit_archive"
#: = `protect.HISTORY_DIR`（前像/快照目录）。
HISTORY_DIR = "_protected_history"
#: R3 盘面定位要跳过的目录（元数据/归档面；`_` 前缀整支另按前缀跳过）。
_SKIP_DIRS = ("trash", "hippocampus", "rejected", "unresolved", "goals",
              "structural", "data", "anchor")


# ---------------------------------------------------------------- 小工具

# 生效条件：now 为假值（None）时返回 time.time()，否则返回 float(now)——所有读数函数共用的「现在」单点（可注入以便守卫控制时间窗）；
def _now(now=None) -> float:
    return time.time() if now is None else float(now)


# 生效条件：v 能表示为**有限正浮点**（int/float，含 bool——与旧行为一致）时返回该 float；不可表示（超出 float 范围的整数型数值）/±inf/NaN/非正数/非数值型一律返回 None——坏值不抛；本函数是 _ts/_fm_ts 共用的数值闸单点（补强批次）；
def _as_ts(v):
    """时间戳候选值 → 有限正 float；不可表示值一律 None（不抛，坏行口径）。

    为什么单点：`float(v)` 对超大整数型数值抛 `OverflowError`（如 400 位十进制
    整数），±inf 转出非有限值——两者都不得让读数/结算崩溃（补强批次；口径见
    模块 docstring）。判定顺序：类型 → 可转换 → 有限且正。
    """
    if not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except (OverflowError, ValueError, TypeError):
        return None
    if not (0.0 < f < float("inf")):
        return None
    return f


# 生效条件：rec 为 dict 且含正的数值时间键 t（缺时回退 created_at/time）时返回该 float；全缺、非正数或不可表示（见 _as_ts）时返回 None；
def _ts(rec) -> float:
    """JSONL 行时间戳（本仓惯例键序：t > created_at > time）。

    坏值容错（补强批次）：数值超出 float 表示范围（如 400 位十进制整数）、
    ±inf、NaN 一律视同**缺时间戳**（None ⇒ 读数的 undated 桶），不抛——与
    `_stream_jsonl`「坏行跳过不抛」同口径（模块 docstring 纪律②）。
    """
    if not isinstance(rec, dict):
        return None
    for k in ("t", "created_at", "time"):
        f = _as_ts(rec.get(k))
        if f is not None:
            return f
    return None


# 生效条件：fm 为 dict 且含正的数值 created_at（缺时回退 t）时返回该 float；否则 None（不可表示值同样归 None，见 _as_ts）；
def _fm_ts(fm) -> float:
    """节点 frontmatter 的创建时间（实测 rejected/unresolved 的 add 均落 created_at）。

    坏值容错（补强批次）：同 `_ts`——不可表示/±inf/NaN 视同缺时间戳（None），
    由 R2 计入 `undated`（如实），不抛。
    """
    if not isinstance(fm, dict):
        return None
    for k in ("created_at", "t"):
        f = _as_ts(fm.get(k))
        if f is not None:
            return f
    return None


# 生效条件：path 为可读文本文件时逐行 yield 解析成功的 dict（空行/坏行跳过，不抛）；文件不存在或不可读时零 yield；
def _stream_jsonl(path):
    """流式 JSONL 迭代（不把大文件读进内存；坏行跳过不抛）。"""
    try:
        f = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    try:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:                                     # noqa: BLE001
                continue
            if isinstance(rec, dict):
                yield rec
    finally:
        f.close()


# 生效条件：root 为目录时返回 {rel_path: (size, mtime_ns)}（只读，不跟随目录符号链接）；root 不存在返回空 dict；
def _fingerprint(root):
    """目录指纹（相对路径 → (size, mtime_ns)）——守卫用来证明读数零写入。"""
    out = {}
    if not os.path.isdir(root):
        return out
    for dirpath, dirs, files in os.walk(root):
        dirs.sort()
        for fn in sorted(files):
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                st = os.stat(p)
            except OSError:
                out[rel] = None
                continue
            out[rel] = (st.st_size, st.st_mtime_ns)
    return out


# ---------------------------------------------------------------- R1

# 生效条件：root 下 `_forgetting.jsonl` 可读时流式统计窗口（30 天，按行 t）内与全量 verdict 分布，返回读数体 dict（ok=窗口内 DROP/MERGE/DEFER 各自 ≥1 且最大占比 < R1_MAX_SHARE）；文件缺失时按 total_win=0 且 ok=False 返回（detail 指名缺文件）；
def r1_non_degenerate(root, now=None) -> dict:
    """R1 判断非退化（窗口 30 天）：verdict 分布非常量，单一 verdict 占比 < 90%。"""
    now = _now(now)
    path = os.path.join(root, FORGETTING_LOG)
    by_all, by_win = {}, {}
    total_all = total_win = undated_all = 0
    if os.path.exists(path):
        for rec in _stream_jsonl(path):
            v = str(rec.get("verdict") or "?")
            by_all[v] = by_all.get(v, 0) + 1
            total_all += 1
            t = _ts(rec)
            if t is None:
                undated_all += 1
                continue
            if 0 <= (now - t) <= WINDOW_LONG_D * DAY:
                by_win[v] = by_win.get(v, 0) + 1
                total_win += 1
    seen = {v: by_win.get(v, 0) for v in R1_VERDICTS}
    missing_verdicts = [v for v, n in seen.items() if n < R1_MIN_ONE]
    top = max(by_win, key=by_win.get) if by_win else None
    top_share = (by_win[top] / total_win) if total_win else None
    ok = bool(total_win > 0 and not missing_verdicts
              and top_share is not None and top_share < R1_MAX_SHARE)
    if not os.path.exists(path):
        detail = "缺数据面：%s 不存在（库从未留痕？）——不可判。" % FORGETTING_LOG
    elif total_win == 0:
        detail = ("%s 在 %d 天窗内 0 条留痕（全量 %d 条）——样本不足，不可判。"
                  % (FORGETTING_LOG, WINDOW_LONG_D, total_all))
    elif missing_verdicts:
        detail = ("%d 天窗内 verdict 三态不全：缺 %s（窗口内 %s）——分布退化。"
                  % (WINDOW_LONG_D, "、".join(missing_verdicts), by_win))
    elif top_share is not None and top_share >= R1_MAX_SHARE:
        detail = ("%d 天窗内单一 verdict 占比 %.1f%% ≥ %.0f%%（%s）——分布退化。"
                  % (WINDOW_LONG_D, top_share * 100, R1_MAX_SHARE * 100, top))
    else:
        detail = ("%d 天窗内 %d 条：%s；最大占比 %.1f%% < %.0f%%——判断非退化。"
                  % (WINDOW_LONG_D, total_win, by_win,
                     (top_share or 0) * 100, R1_MAX_SHARE * 100))
    return {"id": "R1", "ok": ok, "window_days": WINDOW_LONG_D,
            "total": total_win, "by_verdict": by_win,
            "seen": seen, "missing_verdicts": missing_verdicts,
            "top": top, "top_share": top_share,
            "summary_all": {"total": total_all, "by_verdict": by_all},
            "undated": undated_all,
            "thresholds": {"max_share": R1_MAX_SHARE,
                           "required": list(R1_VERDICTS)},
            "detail": detail}


# ---------------------------------------------------------------- R2

# 生效条件：root 下 rejected/ 与 unresolved/ 目录可遍历时逐 .md 解析 frontmatter.created_at，返回两层计数与最近时间（recent=3 天内、total_30d=30 天内、undated=无 created_at 数）；ok=短期两层各 ≥R2_MIN_RECENT 且长期两层各 ≥R2_MIN_TOTAL；目录缺失按 0 计并计入 detail；
def r2_says_no(root, now=None) -> dict:
    """R2 会说「不」（短期 3 天各 ≥1 ＋ 长期 30 天总量各 ≥1）。"""
    now = _now(now)
    layers = {}
    for layer in LAYERS_SAY_NO:
        d = os.path.join(root, layer)
        n = recent = total_30 = undated = 0
        latest = None
        exists = os.path.isdir(d)
        if exists:
            for dirpath, dirs, files in os.walk(d):
                for fn in files:
                    if not fn.endswith(".md"):
                        continue
                    n += 1
                    try:
                        with open(os.path.join(dirpath, fn),
                                  encoding="utf-8", errors="replace") as f:
                            fm, _content = nodefile.loads(f.read())
                    except OSError:
                        undated += 1
                        continue
                    ca = _fm_ts(fm)
                    if ca is None:
                        undated += 1
                        continue
                    latest = ca if latest is None else max(latest, ca)
                    if 0 <= (now - ca) <= WINDOW_SHORT_D * DAY:
                        recent += 1
                    if 0 <= (now - ca) <= WINDOW_LONG_D * DAY:
                        total_30 += 1
        layers[layer] = {"exists": exists, "total": n, "recent": recent,
                         "total_30d": total_30, "latest_created_at": latest,
                         "undated": undated}
    short_ok = all(layers[l]["recent"] >= R2_MIN_RECENT for l in LAYERS_SAY_NO)
    long_ok = all(layers[l]["total_30d"] >= R2_MIN_TOTAL for l in LAYERS_SAY_NO)
    ok = bool(short_ok and long_ok)
    short_missing = [l for l in LAYERS_SAY_NO
                     if layers[l]["recent"] < R2_MIN_RECENT]
    long_missing = [l for l in LAYERS_SAY_NO
                    if layers[l]["total_30d"] < R2_MIN_TOTAL]
    if ok:
        detail = ("%d 天窗内两层各有新增（%s）；%d 天总量各 ≥%d——会说「不」。"
                  % (WINDOW_SHORT_D,
                     "、".join("%s=%d" % (l, layers[l]["recent"])
                               for l in LAYERS_SAY_NO),
                     WINDOW_LONG_D, R2_MIN_TOTAL))
    else:
        parts = []
        if short_missing:
            parts.append("%d 天窗内新增不足：%s" % (
                WINDOW_SHORT_D,
                "、".join("%s=%d" % (l, layers[l]["recent"]) for l in short_missing)))
        if long_missing:
            parts.append("%d 天总量不足：%s" % (
                WINDOW_LONG_D,
                "、".join("%s=%d" % (l, layers[l]["total_30d"])
                          for l in long_missing)))
        if not parts:
            parts.append("读数异常（无缺口但 ok=False）——如实上报")
        undated = {l: layers[l]["undated"] for l in LAYERS_SAY_NO
                   if layers[l]["undated"]}
        if undated:
            parts.append("无 created_at 未计窗：%s" % undated)
        detail = "；".join(parts) + "。"
    return {"id": "R2", "ok": ok,
            "window_days_short": WINDOW_SHORT_D, "window_days_long": WINDOW_LONG_D,
            "layers": layers, "short_missing": short_missing,
            "long_missing": long_missing,
            "thresholds": {"recent_min": R2_MIN_RECENT,
                           "total_min": R2_MIN_TOTAL},
            "detail": detail}


# ---------------------------------------------------------------- R3

# 生效条件：root 下数据面可读时收集两类「回过」证据——① 活动分片 _audit.jsonl 的 op=restore 行（t 在 30 天窗内）且同 id 有更早 op=forget 行；② decisions.jsonl 的 accept 执行记录（t 在 30 天窗内、rec["mutation"] 为 dict）中动作类 C/B 且执行时点前像在位（_protected_history 文件 + _protected_audit.jsonl 的 action=preimage 行）且现盘面与该前像逐字节相等（现盘面经 _disk_path_of 两段式定位：文件名优先、_index.json 兜底；索引仅在文件名未命中时加载）；返回读数体 dict（ok=证据数 ≥ R3_MIN_ROLLBACKS；archived_shards 为未纳入的 _audit_archive 分片数，如实点名）；
def r3_reversible(root, now=None) -> dict:
    """R3 破坏可逆且「回过」（30 天内 ≥1 次真实回滚；状态推断，见模块 docstring）。"""
    now = _now(now)
    lo = now - WINDOW_LONG_D * DAY
    evidence = []

    # ---- ① D 面：活动分片的 forget → restore 对 ----
    forget_at = {}
    audit_p = os.path.join(root, DEVICE_AUDIT)
    if os.path.isfile(audit_p):
        for rec in _stream_jsonl(audit_p):
            op = rec.get("op")
            nid = rec.get("id")
            t = _ts(rec)
            if not nid or t is None:
                continue
            if op == "forget":
                if nid not in forget_at or t < forget_at[nid]:
                    forget_at[nid] = t
            elif op == "restore":
                ft = forget_at.get(nid)
                if ft is not None and ft < t and lo <= t <= now:
                    evidence.append({"source": "audit_restore", "node_id": nid,
                                     "t": t, "forget_t": ft,
                                     "detail": "删（%.0f）→ 回（%.0f）" % (ft, t)})

    # ---- ② C/B 面：accept 执行记录 + 前像在位 + 现盘面 == 前像 ----
    cand = []
    dec_p = os.path.join(root, DECISIONS_LOG)
    if os.path.isfile(dec_p):
        for rec in _stream_jsonl(dec_p):
            if rec.get("decision") != "accept":
                continue
            mut = rec.get("mutation")
            if not isinstance(mut, dict):
                continue
            t = _ts(rec)
            if t is None or not (lo <= t <= now):
                continue
            act = str(mut.get("action") or "").strip().upper()
            if act in ("B", "C") and mut.get("before") and mut.get("target"):
                cand.append({"t": t, "action": act, "target": mut["target"],
                             "before": mut["before"], "pid": rec.get("pid")})
    pre_audit = set()
    prot_p = os.path.join(root, PROTECT_AUDIT)
    if os.path.isfile(prot_p):
        for rec in _stream_jsonl(prot_p):
            if rec.get("action") == "preimage" and rec.get("snapshot"):
                pre_audit.add(str(rec["snapshot"]).replace("\\", "/"))
    for c in cand:
        rel = str(c["before"]).replace("\\", "/")
        pre_p = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(pre_p):
            continue                       # 前像缺失——回滚句柄不存在，不计
        if rel not in pre_audit:
            continue                       # 审计链缺 preimage 行——不计（如实）
        disk_p = _disk_path_of(root, c["target"])
        if not disk_p:
            continue
        try:
            with open(disk_p, "rb") as f:
                a = f.read()
            with open(pre_p, "rb") as f:
                b = f.read()
        except OSError:
            continue
        if a != b:
            continue                       # 盘面尚未回到前像——破坏仍在外
        evidence.append({"source": "preimage_pair", "node_id": c["target"],
                         "t": c["t"], "action": c["action"], "pid": c["pid"],
                         "preimage": rel,
                         "detail": "执行后盘面已回到执行时点前像（逐字节）"})

    # 归档分片计数（不读内容，如实点名）
    arc_p = os.path.join(root, AUDIT_ARCHIVE)
    archived = 0
    if os.path.isdir(arc_p):
        try:
            archived = len([n for n in os.listdir(arc_p)
                            if n.startswith("_audit.") and n.endswith(".jsonl")])
        except OSError:
            archived = 0

    count = len(evidence)
    ok = bool(count >= R3_MIN_ROLLBACKS)
    d_restores = len([e for e in evidence if e["source"] == "audit_restore"])
    cb_pairs = len([e for e in evidence if e["source"] == "preimage_pair"])
    if ok:
        detail = ("%d 天窗内 %d 次「回过」证据（D 面 %d + C/B 面 %d）；"
                  "方法=状态推断（回滚无独立留痕，见模块 docstring）%s。"
                  % (WINDOW_LONG_D, count, d_restores, cb_pairs,
                     ("；未纳入归档分片 %d 个" % archived) if archived else ""))
    else:
        detail = ("%d 天窗内 0 次「回过」证据（D 面 0 + C/B 面 0；"
                  "候选执行记录 %d 条）%s——破坏可逆性未实测。"
                  % (WINDOW_LONG_D, len(cand),
                     ("；注意：未纳入归档分片 %d 个，落在归档里的 restore 会漏计"
                      % archived) if archived else ""))
    return {"id": "R3", "ok": ok, "window_days": WINDOW_LONG_D,
            "count": count, "min_count": R3_MIN_ROLLBACKS,
            "d_restores": d_restores, "cb_pairs": cb_pairs,
            "candidates": len(cand), "archived_shards": archived,
            "evidence": evidence[:20],
            "method": "state_inference（回滚无独立留痕：步骤③报告 §6.1 第 3 条）",
            "thresholds": {"min_count": R3_MIN_ROLLBACKS},
            "detail": detail}


# 生效条件：node_id 非空时按「① 层目录文件名 {id}.md（跳过 _ 前缀与 _SKIP_DIRS；不解析内容，纯文件名匹配）→ ② _index.json 的 nodes[id].path（兜底，库未 compact 时可能缺）」两段式定位盘面文件，返回绝对路径；两段都未命中或文件不存在时返回 None（不猜——调用方按「无法比对」计）；
def _disk_path_of(root, node_id):
    """盘面定位（只读；R3 的 C/B 面用）。

    为什么文件名优先：`_index.json` 只在 compact/close 时落盘（探针实测：
    add+flush 后仅 `_index_log/` 分片有记录），常驻库的索引快照可能滞后；
    文件名 `{id}.md` 是写侧惯例（`census.load` 同源：`nid = fm.get("id")
    or fn[:-3]`），walk 文件名不解析内容、成本 ≪ 加载 21MB 索引。
    """
    if not node_id:
        return None
    fn = node_id + ".md"
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs
                   if not d.startswith("_") and d not in _SKIP_DIRS]
        if fn in files:
            p = os.path.join(dirpath, fn)
            if os.path.isfile(p):
                return p
    idx = _load_index_nodes(root)
    e = idx.get(node_id) or {}
    if e.get("path"):
        p = os.path.join(root, str(e["path"]).replace("/", os.sep))
        if os.path.isfile(p):
            return p
    return None


# 生效条件：root 下 _index.json 可读且含 dict 型 nodes 时返回该 nodes；不可读/解析失败/nodes 非 dict 时返回 {}（不抛——R3 的索引面是兜底增强，缺失按「无法比对」计）；
def _load_index_nodes(root) -> dict:
    """读 `_index.json` 的 nodes（仅 R3 有候选执行记录时调用——成本门槛）。"""
    try:
        with open(os.path.join(root, "_index.json"), "r",
                  encoding="utf-8", errors="replace") as f:
            idx = json.load(f)
    except (OSError, ValueError):
        return {}
    nodes = idx.get("nodes") if isinstance(idx, dict) else None
    return nodes if isinstance(nodes, dict) else {}


# ---------------------------------------------------------------- R4

# 生效条件：root 下 hippocampus/decisions.jsonl 可读时单遍流式按 t 归入 3 个 10 天子窗（W0 最近 … W2 最远），返回读数体 dict——三个子窗均有裁定样本时 ok=(按时间升序严格递减 且 最近子窗驳回率 < R4_MAX_RATE)；任一子窗样本为 0 时 ok=None（不可判，如实）；驳回率=(reject+edit)/该窗全部裁定；
def r4_converging(root, now=None) -> dict:
    """R4 判断收敛（30 天内 3 个 10 天子窗，逐窗严格下降且最近 < 20%）。"""
    now = _now(now)
    windows = [{"lo": now - (k + 1) * R4_SUBWINDOW_D * DAY,
                "hi": now - k * R4_SUBWINDOW_D * DAY,
                "total": 0, "reject": 0, "edit": 0, "by_decision": {}}
               for k in range(R4_SUBWINDOWS)]
    dec_p = os.path.join(root, DECISIONS_LOG)
    if os.path.isfile(dec_p):
        for rec in _stream_jsonl(dec_p):
            t = _ts(rec)
            if t is None:
                continue
            for w in windows:
                if w["lo"] < t <= w["hi"]:
                    d = str(rec.get("decision") or "unknown")
                    w["total"] += 1
                    w["by_decision"][d] = w["by_decision"].get(d, 0) + 1
                    if d == "reject":
                        w["reject"] += 1
                    elif d == "edit":
                        w["edit"] += 1
                    break
    rates_desc = []          # 最近 → 最远（便于报文案）
    for w in windows:
        w["rate"] = ((w["reject"] + w["edit"]) / w["total"]) if w["total"] else None
        rates_desc.append(w["rate"])
    rates_asc = list(reversed(rates_desc))     # 时间升序（最远 → 最近）
    empty = [i for i, r in enumerate(rates_asc) if r is None]
    if empty:
        ok = None
        detail = ("30 天内子窗样本不足（%s 无裁定）——窗口不足 3 个子窗，"
                  "不可判（如实；不假装收敛也不假装不收敛）。"
                  % "、".join("W%d" % (R4_SUBWINDOWS - i) for i in empty))
    else:
        strictly_down = rates_asc[0] > rates_asc[1] > rates_asc[2]
        last_below = rates_asc[2] < R4_MAX_RATE
        ok = bool(strictly_down and last_below)
        detail = ("子窗驳回率（远→近）%s；逐窗严格下降=%s；最近子窗 %.1f%% "
                  "%s %.0f%%——%s。"
                  % (" / ".join("%.1f%%" % (r * 100) for r in rates_asc),
                     strictly_down, rates_asc[2] * 100,
                     "<" if last_below else "≥", R4_MAX_RATE * 100,
                     "判断收敛" if ok else "未收敛或不满足门槛"))
    return {"id": "R4", "ok": ok, "window_days": WINDOW_LONG_D,
            "subwindow_days": R4_SUBWINDOW_D, "subwindows": R4_SUBWINDOWS,
            "windows": [{"lo": w["lo"], "hi": w["hi"], "total": w["total"],
                         "reject": w["reject"], "edit": w["edit"],
                         "rate": w["rate"], "by_decision": w["by_decision"]}
                        for w in windows],
            "rates_asc": rates_asc,
            "thresholds": {"max_rate": R4_MAX_RATE,
                           "strictly_decreasing": True,
                           "subwindows": R4_SUBWINDOWS,
                           "subwindow_days": R4_SUBWINDOW_D},
            "detail": detail}


# ---------------------------------------------------------------- 汇总与缓存

READING_IDS = ("R1", "R2", "R3", "R4")


# 生效条件：root 为目录时依次跑 R1–R4（各自独立读数体），返回 {"root","t","ok","missing","indeterminate","readings","verdict"}——ok 为四条全 True；missing 列出一切非 True（含不可判，fail-closed）；本函数零写入；
def check(root, now=None) -> dict:
    """跑四条读数，返回汇总报告（只读：不改任何数据、不落任何文件）。"""
    t0 = _now(now)
    readings = [r1_non_degenerate(root, now=t0),
                r2_says_no(root, now=t0),
                r3_reversible(root, now=t0),
                r4_converging(root, now=t0)]
    missing = [r["id"] for r in readings if r["ok"] is not True]
    indeterminate = [r["id"] for r in readings if r["ok"] is None]
    ok = not missing
    return {"root": os.path.abspath(root), "t": t0, "ok": ok,
            "readings": readings, "missing": missing,
            "indeterminate": indeterminate,
            "verdict": "pass" if ok else "fail"}


#: 进程级读数缓存：{root_abspath: {"t": float, "res": dict}}——gate() 专用。
_CACHE = {}
#: 探针计数（守卫断言缓存生效：checks=实算次数、hits=缓存命中次数）。
_STATS = {"checks": 0, "hits": 0}


# 生效条件：root 为目录、ttl ≥ 0 时——命中缓存（同 root、未 force、距 t 不超过 ttl 秒）则原样返回上次读数体副本（hits+1，零重扫）；否则实算 check()（checks+1）并写缓存后返回；返回值 = check 报告 + {"cached": bool, "age_s": float}；
def gate(root, now=None, ttl=None, force=False) -> dict:
    """读数唯一入口（TTL 缓存）——热路径不经过本函数（只读结算态）。"""
    t = _now(now)
    ttl = TTL_DEFAULT if ttl is None else float(ttl)
    key = os.path.abspath(root)
    ent = _CACHE.get(key)
    if ent is not None and not force and (t - ent["t"]) <= ttl:
        _STATS["hits"] += 1
        out = dict(ent["res"])
        out["cached"] = True
        out["age_s"] = round(t - ent["t"], 3)
        return out
    res = check(root, now=t)
    _STATS["checks"] += 1
    _CACHE[key] = {"t": t, "res": res}
    out = dict(res)
    out["cached"] = False
    out["age_s"] = 0.0
    return out


# 生效条件：无入参；返回探针计数副本 {"checks","hits","cached_roots"}；
def cache_stats() -> dict:
    """缓存探针（守卫用来机械证明「不每次全扫」）。"""
    return {"checks": _STATS["checks"], "hits": _STATS["hits"],
            "cached_roots": len(_CACHE)}


# 生效条件：无入参；清空读数缓存与计数（测试/宿主重结算用），无返回值；
def reset_cache() -> None:
    _CACHE.clear()
    _STATS["checks"] = 0
    _STATS["hits"] = 0


# 生效条件：无入参，datapath.mdcg_root() 返回真值时返回该值，导入或调用抛异常、或返回假值（如空串）时返回仓库内 data/mdcg；与 conformance._default_root 同源同形；
def default_root() -> str:
    """root 解析沿用本仓约定：env `MDCG_ROOT` > `paths.json` > 用户级状态根。"""
    try:
        from .datapath import mdcg_root
        got = mdcg_root()
        if got:
            return got
    except Exception:                                             # noqa: BLE001
        pass
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "mdcg")


# ---------------------------------------------------------------- 报告/CLI

# 生效条件：rep 为 check()/gate() 的返回体（含 readings 列表）时拼接为多行文本，返回该文本；
def render(rep: dict) -> str:
    L = []
    a = L.append
    a("== 三档自治准入读数（R1–R4）· %s" % rep.get("root"))
    a("   结论：%s   缺：%s" % (
        "够格（R1–R4 全满足）" if rep.get("ok") else "不够格",
        "、".join(rep.get("missing") or []) or "无"))
    for r in rep.get("readings") or []:
        mark = {True: "ok ", False: "NO ", None: "~? "}[r.get("ok")]
        a("  [%s] %s: %s" % (mark, r["id"], r["detail"]))
    return "\n".join(L)


# 生效条件：argv 为 None 时 argparse 从 sys.argv 取值；--root 缺失/假值时回落 default_root()；root 非目录时打印并返回 2；否则 force 实算 gate() 打印 render()（--json 时另写 JSON 到该路径），按 ok 返回 0/1；
def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m md_cg.admission",
        description="三档自治准入读数 R1–R4（只读，零写入）")
    p.add_argument("--root", default=None,
                   help="认知图根（默认 MDCG_ROOT > paths.json > 用户级状态根）")
    p.add_argument("--json", dest="json_out", default=None,
                   help="把完整读数体写成 JSON 到该路径")
    p.add_argument("--ttl", type=float, default=None, help="读数缓存 TTL 秒")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    a = p.parse_args(argv)
    root = a.root or default_root()
    if not os.path.isdir(root):
        print("root 不存在或不是目录：%s（fail-closed，无法判读）" % root)
        return 2
    rep = gate(root, ttl=a.ttl, force=True)
    print(render(rep))
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
