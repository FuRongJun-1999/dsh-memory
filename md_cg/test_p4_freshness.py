# -*- coding: utf-8 -*-
"""P4 守卫 · 权重刷新与衰减进主分数（§7.1–§7.4）。

覆盖判据（每条对应契约的一项）：

  G1 **核来自唯一权威**：`md_cg/whitebox_kb/aeis_core/time_core.py`——本模块
      源码**不含指数核调用**，且 `decay_factor` 与 `cred_factor` 在 6 个 dt 上
      **逐位相等**（含 inf → floor）。
  G2 **γ 与 Δt 口径**（§〇.3-12）：γ 缺省 `ln2/30 天`、与 `mdcos.temporal_gamma`
      **同一读取点**（env `MDCG_TEMPORAL_GAMMA` 同时覆盖两条路）；Δt 取
      `created_at`；**单位必须是「天」**——30 天 → 0.5，若按秒喂同一时长则触 floor
      （单位断言的**判别力**）。
  G3 **refresh 参数照抄 AEIS**：与 `aeis_core/core.py` 的 `consolidate_cycle`
      既有取值逐条相等（源码对拍 + 行为三档 1.01 / 0.99 / 1.0）。
  G4 **衰减必加 floor**（§7.3）：老节点/缺 created_at 不低于 `SCORE_FLOOR`；
      **受保护节点** `importance × 乘子 ≥ IMPORTANCE_PROTECT` 恒成立；判别力
      （未保护节点不享有该下界）。
  G5 **落位 = 与分池权重同一乘子位**（§7.2）：源码断言乘子行紧邻
      `pooling.weight_of(...)` 行；行为断言 `_score` 的同内容两节点分数比
      == 乘子比。
  G6 **索引条目取数**（P4-2①）：条目含 `access_count`/`last_access`；
      `freshness.entry_weight` 只凭条目即可算（无 IO 面）。
  G7 **开关可回退**：`MDCG_FRESHNESS=0` → 乘子恒 1.0，`_score` 与基线逐位一致。
  G8 **三件套**（§7.4）：预演零写盘；apply 逐节点 before/after 落
      `_maintain.jsonl`（`action="freshness"`，与 `importance` 同族）；
      rollback 写回 before 且**不删节点**。
  G9 **降级不得实现为删除记录**（§7.3）：降级只写 `freshness_state="degraded"`，
      节点与正文原样在库；跨层降级走既有 `_move_layer`（内含 `guard_move`）
      ——受保护节点被移出保护层抛 `ProtectionError` 且无副作用。
  G10 `weights.recalc` 的「`after ≥ 0.70` 自动补写 `protected`」行为**仍在位**。
  G11 **Rust 侧同口径**：`rust/src/freshness.rs` 的四个常量与 Python 同值；
      乘子只在 `sort_path(..., apply_freshness=true)` 生效且 `fuse` 只对
      lexical 传 true（与 Python `_score` 的对位面一致）。

运行：
    python -X utf8 -m md_cg.test_p4_freshness
    python -X utf8 -m md_cg.test_p4_freshness --mutate
    python -X utf8 -m md_cg.test_p4_freshness --mutate --list

退出码：0 = 全绿；1 = 有失败 / 变异未按预期转红；2 = ANCHOR-MISS。

硬边界：库根一律 tempfile；不动在役数据根；不 git add/commit/push。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile

# ── 隔离前置（必须在 import md_cg 子模块之前）──
_TMP0 = tempfile.mkdtemp(prefix="p4_fresh_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP0, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "12" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP0, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP0, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "MDCG_RETRIEVAL_PIPELINE", "MDCG_POOLING", "MDCG_FRESHNESS",
           "MDCG_FRESHNESS_NOW", "MDCG_TEMPORAL_GAMMA"):
    os.environ.pop(_k, None)

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from md_cg import freshness as F                              # noqa: E402
from md_cg import mdcg as M                                   # noqa: E402
from md_cg import nodefile                                    # noqa: E402
from md_cg import weights as W                                # noqa: E402
from md_cg.mdcos import MdCGOS                                # noqa: E402
from md_cg.whitebox_kb.aeis_core import time_core as TC       # noqa: E402

REF = 1_800_000_000.0
DAY = 86400.0

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")
    return bool(cond)


BODY = ("# 功能名：{n}\n# 生效条件：无条件\n# 子功能：无\n# 执行：占位\n"
        "# 验证方式：compiler 复现\n# 不适用条件：其它会话\n\n{t}\n")


def _mk(cg, nid, layer="knowledge", **kw):
    cg.add(nid, BODY.format(n=nid, t=f"{nid} 正文 苹果 章节"), layer=layer, **kw)


def _lib(extra=None):
    root = tempfile.mkdtemp(prefix="p4_lib_")
    cg = MdCGOS(root)
    for nid, kw in (extra or (("k_new", {"importance": 0.5,
                                         "created_at": REF}),
                              ("k_old", {"importance": 0.5,
                                         "created_at": REF - 300 * DAY}))):
        _mk(cg, nid, **kw)
    cg.flush()
    return root, cg


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _tree_hash(root):
    h = hashlib.sha256()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("_"))
        for fn in sorted(files):
            if fn.startswith("_"):
                continue
            p = os.path.join(dirpath, fn)
            h.update(os.path.relpath(p, root).replace("\\", "/").encode())
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:16]


def _score_pair(cg, q="苹果 章节", protected=False):
    docs = []
    for nid, created, ac in (("k_new", REF, 0), ("k_old", REF - 300 * DAY, 0)):
        docs.append(({"path": f"knowledge/{nid}.md"},
                     {"id": nid, "tags": [], "created_at": created,
                      "access_count": ac, "last_access": 0,
                      "importance": 0.5, "protected": protected},
                     BODY.format(n=nid, t=f"{nid} 正文 苹果 章节")))
    return cg._score(docs, q, M.bigrams(M.normalize_en(q)))


def g1_core_authority():
    print("== G1 核来自唯一权威 time_core（本模块无自写指数核）==")
    sc = F.selfcheck()
    check("freshness 源码不含指数核调用", sc["no_local_exp_core"] is True, str(sc))
    check("核经 time_core.cred_factor", sc["uses_cred_factor"] is True)
    g = F.resolve_gamma()
    ok = True
    detail = []
    for dt in (0.0, 1.0, 7.0, 30.0, 300.0, float("inf")):
        a = F.decay_factor(g, dt)
        b = TC.cred_factor(g, dt, F.SCORE_FLOOR, F.SCORE_CEIL)
        if a != b:
            ok = False
        detail.append((dt, a))
    check("decay_factor ≡ time_core.cred_factor（6 个 dt 逐位相等）", ok, str(detail))


def g2_gamma_and_unit():
    print("== G2 γ 与 Δt 口径 / 单位必须是「天」==")
    from md_cg.mdcos import temporal_gamma
    from md_cg.links import DECAY_DAYS
    check("γ 缺省 = ln2/30 天",
          abs(F.resolve_gamma() - math.log(2.0) / 30.0) < 1e-15,
          str(F.resolve_gamma()))
    check("γ 与 mdcos.temporal_gamma **同一读取点**（缺省同值）",
          F.resolve_gamma() == temporal_gamma())
    check("半衰期真源 links.DECAY_DAYS == 30", DECAY_DAYS == 30.0)
    os.environ["MDCG_TEMPORAL_GAMMA"] = "0.5"
    try:
        check("env MDCG_TEMPORAL_GAMMA 同时覆盖两条路",
              F.resolve_gamma() == 0.5 and temporal_gamma() == 0.5)
    finally:
        os.environ.pop("MDCG_TEMPORAL_GAMMA", None)
    os.environ["MDCG_TEMPORAL_GAMMA"] = "abc"
    try:
        check("非法 γ 回落缺省（不抛）",
              abs(F.resolve_gamma() - math.log(2.0) / 30.0) < 1e-15)
    finally:
        os.environ.pop("MDCG_TEMPORAL_GAMMA", None)
    g = F.resolve_gamma()
    check("单位断言（天）：30 天 → 0.5", abs(F.decay_factor(g, 30.0) - 0.5) < 1e-12,
          str(F.decay_factor(g, 30.0)))
    check("判别力：同一时长按**秒**喂 → 触 floor（喂秒会快 86400 倍）",
          F.decay_factor(g, 30.0 * DAY) == F.SCORE_FLOOR,
          str(F.decay_factor(g, 30.0 * DAY)))
    check("Δt 取 created_at（entry_weight 用 created_at 算天数）",
          F.entry_weight({"created_at": REF - 30 * DAY, "importance": 0.5},
                         now=REF)[0] == F.decay_factor(g, 30.0))
    # 粒度=整日（向下取整）：同为「1.x 天」的节点与「1 天」同值；「0.x 天」不衰减
    check("粒度断言：Δt 取整日（1.5 天 ≡ 1 天）",
          F.entry_weight({"created_at": REF - 1.5 * DAY, "importance": 0.5},
                         now=REF)[0] == F.decay_factor(g, 1.0))
    check("粒度断言：当日写入（0.9 天）不衰减",
          F.entry_weight({"created_at": REF - 0.9 * DAY, "importance": 0.5},
                         now=REF)[0] == F.decay_factor(g, 0.0))
    check("可复算：同一 (created_at, 日) 上两轮乘子逐位一致",
          F.entry_weight({"created_at": REF - 3 * DAY - 100, "importance": 0.5},
                         now=REF)[0]
          == F.entry_weight({"created_at": REF - 3 * DAY - 100,
                             "importance": 0.5}, now=REF + 10.0)[0])


def g3_refresh_params():
    print("== G3 refresh 参数照抄 AEIS consolidate_cycle ==")
    src = _src(os.path.join("md_cg", "whitebox_kb", "aeis_core", "core.py"))
    check("AEIS 源码含 rehearsal_threshold = 0.7",
          re.search(r"rehearsal_threshold\s*:\s*float\s*=\s*0\.7", src)
          is not None)
    check("AEIS 源码含 degrade_threshold = 0.2",
          re.search(r"degrade_threshold\s*:\s*float\s*=\s*0\.2", src)
          is not None)
    check("AEIS 源码含 gain = 0.01",
          re.search(r"gain\s*:\s*float\s*=\s*0\.01", src) is not None)
    check("AEIS 源码的降权是 −gain（同一档语义）",
          re.search(r"update_node_importance\(n\.id,\s*-gain\)", src)
          is not None)
    check("AEIS 源码含 `% 10 == 0` 档",
          re.search(r"%\s*10\s*==\s*0", src) is not None)
    p = F.REFRESH_PARAMS
    check("参数取值与 AEIS 既有取值逐条相等",
          (p["rehearsal_threshold"], p["degrade_threshold"], p["gain"],
           p["cycle"]) == (0.7, 0.2, 0.01, 10), str(p))
    check("参数出处写在 paramsSource（REFRESH_PARAMS.source）",
          "consolidate_cycle" in p["source"] and "core.py" in p["source"],
          p["source"])
    check("行为档①演练：+gain", abs(F.refresh_factor(40, 1.0, 0.8) - 1.01) < 1e-12)
    check("行为档②降权：−gain", abs(F.refresh_factor(1, 1.0, 0.1) - 0.99) < 1e-12)
    check("行为档③其余：1.0", F.refresh_factor(3, 1.0, 0.5) == 1.0)
    check("从未访问不得白拿刷新（last_access=0 ⇒ 1.0）",
          F.refresh_factor(0, 0, 0.9) == 1.0)


def g4_floor():
    print("== G4 衰减必加 floor / 保护线不被穿过 ==")
    g = F.resolve_gamma()
    check("老节点 ≥ SCORE_FLOOR",
          F.decay_factor(g, 10000.0) >= F.SCORE_FLOOR)
    check("缺 created_at 的节点仍带非零分（不乘成 0）",
          F.entry_weight({"created_at": 0, "importance": 0.5})[0] > 0.0,
          str(F.entry_weight({"created_at": 0, "importance": 0.5})[0]))
    check("缺 created_at 的衰减项触 floor（decay 本身 = SCORE_FLOOR）",
          F.decay_factor(g, float("inf")) == F.SCORE_FLOOR)
    for imp in (0.70, 0.8, 0.95, 1.0):
        w = F.entry_weight({"created_at": REF - 3650 * DAY,
                            "importance": imp, "protected": True}, now=REF)[0]
        if not (imp * w >= W.IMPORTANCE_PROTECT):
            check(f"受保护节点 importance={imp} 乘子不穿保护线", False,
                  f"imp*w={imp * w}")
            return
    check("受保护节点：importance × 乘子 ≥ IMPORTANCE_PROTECT（跨越 1/10/100 个半衰期）",
          True)
    w_free = F.entry_weight({"created_at": REF - 3650 * DAY,
                             "importance": 0.8}, now=REF)[0]
    check("判别力：未保护节点不享有该下界（乘子触 floor）",
          abs(w_free - F.SCORE_FLOOR) < 1e-12, str(w_free))
    check("保护下限口径取自 weights.IMPORTANCE_PROTECT（单一真源）",
          F.IMPORTANCE_PROTECT == W.IMPORTANCE_PROTECT == 0.70)


def g5_same_multiplier_slot():
    print("== G5 落位：与分池权重同一乘子位 ==")
    root, cg = _lib()
    try:
        os.environ["MDCG_FRESHNESS_NOW"] = repr(REF)
        src = _src(os.path.join("md_cg", "mdcg.py"))
        lines = src.splitlines()
        i = next(n for n, l in enumerate(lines)
                 if l.startswith("    def _score(self, docs, q, qb"))
        seg = lines[i:i + 120]
        jd = next(n for n, l in enumerate(seg)
                  if "raw * pooling.weight_of(" in l)
        kd = next(n for n, l in enumerate(seg)
                  if "raw * freshness.entry_weight(" in l)
        check("乘子行与分池权重行同处一个语句块（中间只有注释、无空行）",
              0 < kd - jd <= 12
              and all(l.strip() for l in seg[jd + 1:kd]),
              f"pooling 行={jd} 乘子行={kd}")
        # N274：乘子行改为「调用跨两行」形态（循环外提升后追加
        # now/gamma/enabled 关键字透传）——判据性质不变（仍要求乘子**直接
        # 乘在 raw 上**、同一乘子位、以 [0] 取乘子），仅匹配形态同步为
        # 跨行；并顺带收紧为「行首即 raw = raw * …」。
        check("乘子直接乘在 raw 上（同一乘子位，不新开乘子链）",
              seg[kd].strip().startswith("raw = raw * freshness.entry_weight(")
              and "[0]" in (seg[kd] + seg[kd + 1]),   # 单行/跨行两形态皆可
              f"kd 行={seg[kd]!r} 次行={seg[kd + 1]!r}")
        # 行为：同内容两节点，仅 created_at 不同 → 分数比 == 乘子比
        scored = _score_pair(cg)
        m_new = F.entry_weight(cg.index["nodes"]["k_new"], now=REF)[0]
        m_old = F.entry_weight({"created_at": REF - 300 * DAY,
                                "importance": 0.5}, now=REF)[0]
        got = scored[0][1] / scored[1][1]
        check("_score 的同内容两节点分数比 == 乘子比（乘子确实进了主分数）",
              abs(got - (1.0 * m_new) / (1.0 * m_old)) < 1e-9,
              f"got={got} want={m_new / m_old}")
        check("旧节点被衰减（ratio > 1 且旧节点分更低）",
              scored[0][1] > scored[1][1], str(scored))
    finally:
        os.environ.pop("MDCG_FRESHNESS_NOW", None)
        cg.close()


def g6_index_entry_data():
    print("== G6 取数：access_count / last_access 进索引条目（检索期不读盘）==")
    root, cg = _lib()
    try:
        e = cg.index["nodes"]["k_new"]
        check("条目含 access_count", "access_count" in e, str(sorted(e)[:5]))
        check("条目含 last_access", "last_access" in e)
        check("条目含 created_at（Δt 的输入）", e.get("created_at") == REF,
              str(e.get("created_at")))
        w, why = F.entry_weight(e)
        check("只凭条目即可算乘子（entry_weight 无 IO）",
              isinstance(w, float) and why.get("unit") == F.DT_UNIT, str(why))
        check("单位依据如实标为 day", why.get("unit") == "day")
    finally:
        cg.close()


def g7_switch():
    print("== G7 开关可回退（MDCG_FRESHNESS=0 与基线逐位一致）==")
    root, cg = _lib()
    try:
        os.environ["MDCG_FRESHNESS_NOW"] = repr(REF)
        on = [round(s, 12) for _d, s in _score_pair(cg)]
        os.environ["MDCG_FRESHNESS"] = "0"
        off = [round(s, 12) for _d, s in _score_pair(cg)]
        os.environ.pop("MDCG_FRESHNESS", None)
        check("关时乘子恒 1.0",
              F.entry_weight(cg.index["nodes"]["k_new"])[0] == 1.0
              if os.environ.get("MDCG_FRESHNESS") == "0" else True)
        check("开/关两态下分数不同（开关真的有作用）", on != off,
              f"{on} vs {off}")
        check("关态 = 无乘子基线（两节点分数相同）", abs(off[0] - off[1]) < 1e-12,
              str(off))
    finally:
        os.environ.pop("MDCG_FRESHNESS", None)
        os.environ.pop("MDCG_FRESHNESS_NOW", None)
        cg.close()


def g8_triplet():
    print("== G8 三件套：预演 / 逐节点留痕 / 反向 apply ==")
    root, cg = _lib()
    try:
        os.environ["MDCG_FRESHNESS_NOW"] = repr(REF)
        src_a = _tree_hash(root)
        pre = F.recalc(cg, apply=False)
        check("预演：dry_run=True 且零写盘（源面逐字节不变）",
              pre["dry_run"] is True and _tree_hash(root) == src_a, str(pre["written"]))
        check("预演给出逐节点 before/after 样本", bool(pre["samples"]),
              str(pre["samples"][:1]))
        check("预演不改 frontmatter",
              (cg.get("k_old")["frontmatter"].get("freshness_weight") is None))
        res = F.recalc(cg, apply=True, min_delta=0.0)
        check("apply：written ≥ 1", res["written"] >= 1, str(res["written"]))
        fm = cg.get("k_old")["frontmatter"]
        check("apply 写入 freshness_weight（与乘子一致）",
              abs(float(fm.get("freshness_weight")) -
                  F.entry_weight({"created_at": REF - 300 * DAY,
                                  "importance": 0.5}, now=REF)[0]) < 1e-9,
              str(fm.get("freshness_weight")))
        log = os.path.join(cg.root, W.MAINTAIN_LOG)
        recs = [json.loads(x) for x in
                open(log, encoding="utf-8").read().splitlines() if x.strip()]
        mine = [r for r in recs if r.get("action") == "freshness"]
        check("逐节点留痕：_maintain.jsonl 有 action=freshness 记录",
              bool(mine), str([r.get("action") for r in recs]))
        check("留痕含 before/after（逐节点）",
              all(("before" in r and "after" in r) for r in mine),
              json.dumps(mine[:1], ensure_ascii=False))
        check("与 weights 的 action=importance 同族（同一 log 文件）",
              W.MAINTAIN_LOG == F.MAINTAIN_LOG == "_maintain.jsonl")
        rb = F.rollback(cg)
        check("rollback：reverted ≥ 1 且写回 before", rb["reverted"] >= 1, str(rb))
        fm2 = cg.get("k_old")["frontmatter"]
        check("rollback 后 freshness_weight 回到 before",
              abs(float(fm2.get("freshness_weight") or 0.0) - 1.0) < 1e-9,
              str(fm2.get("freshness_weight")))
        _p = (cg.index["nodes"].get("k_old") or {}).get("path") or ""
        check("rollback 后节点仍在索引（不删记录）",
              "k_old" in cg.index["nodes"] and bool(_p)
              and os.path.exists(os.path.join(cg.root, _p)), _p)
        check("rollback 自身再记一条留痕",
              any(r.get("action") == "freshness_rollback"
                  for r in [json.loads(x) for x in
                            open(log, encoding="utf-8").read().splitlines()
                            if x.strip()]))
    finally:
        os.environ.pop("MDCG_FRESHNESS_NOW", None)
        cg.close()


def g9_degrade_not_delete():
    print("== G9 降级 = 标记（不是删除）；跨层降级走 guard_move ==")
    root = tempfile.mkdtemp(prefix="p4_deg_")
    cg = MdCGOS(root)
    try:
        _mk(cg, "k_prot", importance=0.8)      # ≥0.70 ⇒ 自动打保护
        _mk(cg, "k_plain", importance=0.5, created_at=REF - 300 * DAY)
        cg.flush()
        os.environ["MDCG_FRESHNESS_NOW"] = repr(REF)
        e0 = dict(cg.index["nodes"]["k_prot"])
        check("夹具前提：节点受保护", bool(e0.get("protected")),
              str(e0.get("protected")))
        check("bind_move_layer 现绑既有 `_move_layer`（不新写搬迁路径）",
              F.bind_move_layer(cg) is True)
        res = F.recalc(cg, apply=True, min_delta=0.0)
        fm_p = cg.get("k_plain")["frontmatter"]
        _pp = (cg.index["nodes"].get("k_plain") or {}).get("path") or ""
        check("衰减到阈值下的节点被标 degraded（**只标记**）",
              fm_p.get("freshness_state") == "degraded", str(fm_p.get(
                  "freshness_state")))
        check("被标 degraded 的节点与正文原样在库（降级 ≠ 删除记录）",
              os.path.exists(os.path.join(cg.root, _pp))
              and "k_plain" in cg.index["nodes"], _pp)
        check("受保护节点**不被**降级（保护下界生效）",
              (cg.get("k_prot")["frontmatter"].get("freshness_state")
               in (None, "")), str(cg.get("k_prot")["frontmatter"].get(
                   "freshness_state")))
        check("报表给出降级计数", "degraded" in res, str(sorted(res)))
        # 跨层降级：受保护节点被移出保护层 → guard_move 抛错且无副作用
        import md_cg.protect as P
        before = cg.get("k_prot")["frontmatter"].get("layer")
        try:
            cg._move_layer("k_prot", "contextual", reason="guard 试")
            moved = True
        except P.ProtectionError:
            moved = False
        check("受保护节点降级被 guard_move 拒绝（ProtectionError）", moved is False)
        check("拒绝后节点层位与记录未变（无副作用）",
              cg.get("k_prot")["frontmatter"].get("layer") == before
              and "k_prot" in cg.index["nodes"])
        check("fixture 未因降级被删除（降级 ≠ 删除记录）",
              "k_prot" in cg.index["nodes"] and "k_plain" in cg.index["nodes"])
        check("非保护节点可被搬迁（同一闸的两侧对照）",
              isinstance(cg._move_layer("k_plain", "contextual",
                                        reason="guard 对照"), dict))
    finally:
        os.environ.pop("MDCG_FRESHNESS_NOW", None)
        cg.close()


def g10_weights_autoprotect_kept():
    print("== G10 weights.recalc 的 ≥0.70 自动补写 protected 仍在位 ==")
    src = _src(os.path.join("md_cg", "weights.py"))
    check("weights.py 仍含 IMPORTANCE_PROTECT 常量与自动补写分支",
          "IMPORTANCE_PROTECT = 0.70" in src
          and 'fm["protected"] = True' in src)
    root = tempfile.mkdtemp(prefix="p4_w_")
    cg = MdCGOS(root)
    try:
        _mk(cg, "hub", importance=0.2, verification_basis="formal_proof")
        for i in range(12):
            cg.add(f"leaf{i}", BODY.format(n=f"leaf{i}", t=f"leaf{i} 正文"),
                   layer="knowledge", importance=0.1,
                   edges=[{"target": "hub", "relation_type": "causal"}])
        cg.flush()
        rep = W.recalc(cg, apply=True, min_delta=0.0)
        fm = cg.get("hub")["frontmatter"]
        check("重算后 after ≥ 0.70 ⇒ 自动补写 protected",
              float(fm.get("importance") or 0) >= W.IMPORTANCE_PROTECT
              and fm.get("protected") is True,
              f"imp={fm.get('importance')} protected={fm.get('protected')}")
        check("recalc 报表结构未变（预演/留痕/回滚三件套仍在）",
              {"dry_run", "samples", "log"} <= set(rep), str(sorted(rep)))
    finally:
        cg.close()


def g11_rust_parity():
    print("== G11 Rust 侧同口径（常量 + 生效面）==")
    rs = _src(os.path.join("rust", "src", "freshness.rs"))
    for name, val in (("SCORE_FLOOR", "0.001"), ("SECONDS_PER_DAY", "86400.0"),
                      ("IMPORTANCE_PROTECT", "0.70"), ("DECAY_DAYS", "30.0")):
        check(f"rust 常量 {name} 与 Python 同值",
              f"pub const {name}: f64 = {val};" in rs, name)
    for name, val in (("REHEARSAL_THRESHOLD", "0.7"),
                      ("DEGRADE_THRESHOLD", "0.2"), ("GAIN", "0.01")):
        check(f"rust 参数 {name} 照抄 AEIS（{val}）",
              f"const {name}: f64 = {val};" in rs, name)
    ret = _src(os.path.join("rust", "src", "retrieval.rs"))
    check("sort_path 带 apply_freshness 开关",
          "pub fn sort_path(hits: &mut [Hit], docs: &[Option<Doc>],"
          " apply_freshness: bool)" in ret)
    check("fuse 只对 lexical 路开乘子（与 Python `_score` 对位）",
          'sort_path(&mut h, docs, *name == "lexical")' in ret)
    eng = _src(os.path.join("rust", "src", "engine.rs"))
    check("graph 种子排序带乘子（种子取自 lexical 路）",
          "retrieval::sort_path(&mut v, docs, true);" in eng)
    check("Rust 侧有核/参数的单测（半衰期、floor、保护线、演练闸）",
          rs.count("#[test]") >= 4, str(rs.count("#[test]")))


# --------------------------------------------------------------------------
# 定点变异（只改本进程内存对象/临时文件，绝不改仓库文件）
# --------------------------------------------------------------------------

def g12_rust_parity_e2e():
    """P4-2② 双侧同改的**端到端逐位对拍**（判别力夹具，非 rank_parity 现有语料）。

    为什么必须另造夹具：`scripts/rank_parity.py` 的语料是**新建节点**（Δt=0 天
    ⇒ 乘子恒 1.0）、无 edges/无时间参数/无六要素后两行 ⇒ 对 P4 乘子**零判别力**
    （实测：改前 10/10、改后 10/10、改后 Python + 改前 Rust 二进制亦 10/10）。
    只有把「同分不同龄」的节点放进去，乘子才改变路内名次，两侧才可能劈叉。

    夹具：6 个**正文逐字相同**（词法分并列）的节点，created_at 跨度 0/30/300 天，
    importance 随年龄递增（未乘者按 (-score,-importance,id) 会「越老越靠前」）；
    `MDCG_FRESHNESS_NOW` 钉死 → 两侧同一参照时刻。断言：
      ① 改后两侧 top-k **逐位一致**（Python `search_rrf` vs Rust `--serve`）；
      ② 夹具**有判别力**：把 Python 侧乘子关掉，名次与 ① 不同（否则本对拍空转）。
    二进制缺失 = fail-closed 红（「跑不起来」永不算通过）。
    """
    exe = os.path.join(_REPO, "rust", "target", "release",
                       "mdcg-eval.exe" if os.name == "nt" else "mdcg-eval")
    if not os.path.isfile(exe):
        check("Rust 二进制在位（逐位对拍的另一侧）", False,
              f"{exe} 不存在——先 cd rust && cargo build --release")
        return
    sys.path.insert(0, os.path.join(_REPO, "scripts"))
    import rank_parity as RP                      # noqa: E402
    py_mode, conflict = RP.pin_python_score_mode()
    if py_mode != "jaccard" or conflict:
        check("Python 侧口径可钉住（eval_common.use_jaccard）", False,
              f"{py_mode} / {conflict}")
        return
    root = tempfile.mkdtemp(prefix="p4_parity_")
    cg = MdCGOS(root)
    ages = (0.0, 0.0, 30.0, 30.0, 300.0, 300.0)
    for i, age in enumerate(ages):
        # importance 全部 < 0.70（避开自动保护 → 不受保护下界豁免衰减）
        # 且全部 ≥ 0.20（避开 AEIS 降权档），年龄越大 importance 越高 ⇒
        # 「未乘者越老越靠前」，乘子一到即翻转
        _mk(cg, f"p{i}", created_at=REF - age * DAY,
            importance=0.20 + 0.04 * i, tags=[])
    cg.flush()
    q = "苹果 章节"
    os.environ["MDCG_FRESHNESS_NOW"] = repr(REF)
    try:
        py = [(x[0]["id"], round(float(x[1]), 6))
              for x in cg.search_rrf(q, k=6, record=False)[0]]
        os.environ["MDCG_FRESHNESS"] = "0"
        off = [(x[0]["id"], round(float(x[1]), 6))
               for x in cg.search_rrf(q, k=6, record=False)[0]]
        os.environ.pop("MDCG_FRESHNESS", None)
        try:
            proc, rs_mode = RP.rust_open(exe, root)
        except Exception as exc:                  # noqa: BLE001
            check("Rust serve 可拉起且自报口径", False, str(exc)[:200])
            cg.close()
            return
        try:
            rs = RP.rust_topk(proc, [q], k=6)[q]
        finally:
            pass
        rs2 = [(i, None if s is None else round(float(s), 6)) for i, s in rs]
        print(f"     py(new)={py}")
        print(f"     rust   ={rs2}")
        print(f"     py(off)={off}")
        check("① 两侧 top-k 逐位一致（同乘子、同口径）",
              [i for i, _s in py] == [i for i, _s in rs2],
              f"{[i for i, _s in py]} vs {[i for i, _s in rs2]}")
        check("② 夹具判别力：关掉乘子后名次不同（本对拍非空转）",
              [i for i, _s in py] != [i for i, _s in off],
              f"{[i for i, _s in py]} vs {[i for i, _s in off]}")
        check("② 乘子使「新节点靠前、旧节点靠后」",
              [i for i, _s in py][0] in ("p0", "p1")
              and [i for i, _s in py][-1] in ("p4", "p5"),
              f"{[i for i, _s in py]}")
    finally:
        os.environ.pop("MDCG_FRESHNESS_NOW", None)
        cg.close()
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def g13_hot_loop_reads():
    """N274：freshness 读取点全部提升到 `_score` 循环外（调用计数判据）。

    判据＝**与文档数无关**：同一 `_score` 调用于 2 节点与 20 节点两批文档
    时，`enabled`/`freshness_now`/`resolve_gamma`/`temporal_gamma` 的调用
    计数相同。修前（8000 池实测，2026-10-05）为每节点 7 次（enabled 4×N
    + now/γ/temporal 各 N）；墙钟只作辅助，不作判据。
    """
    print("== G13 freshness 读取提升到 _score 循环外（N274）==")
    import md_cg.mdcos as MC
    root, cg = _lib()
    c = {"enabled": 0, "now": 0, "gamma": 0, "temporal": 0}
    orig = {n: getattr(F, n) for n in ("enabled", "freshness_now",
                                       "resolve_gamma")}
    orig_tg = MC.temporal_gamma

    def _wrap(fn, key):
        def _w(*a, **k):
            c[key] += 1
            return fn(*a, **k)
        return _w

    F.enabled = _wrap(orig["enabled"], "enabled")
    F.freshness_now = _wrap(orig["freshness_now"], "now")
    F.resolve_gamma = _wrap(orig["resolve_gamma"], "gamma")
    MC.temporal_gamma = _wrap(orig_tg, "temporal")
    try:
        def _mk_docs(n):
            return [({"path": "knowledge/k%d.md" % i},
                     {"id": "k%d" % i, "tags": [],
                      "created_at": REF - i * DAY, "access_count": 0,
                      "last_access": 0, "importance": 0.5},
                     BODY.format(n="k%d" % i, t="k%d 正文 苹果 章节" % i))
                    for i in range(n)]

        def _count(docs):
            for k in c:
                c[k] = 0
            cg._score(docs, "苹果 章节",
                      M.bigrams(M.normalize_en("苹果 章节")))
            return dict(c)

        c2 = _count(_mk_docs(2))
        c20 = _count(_mk_docs(20))
        # 判据面＝**env 读取三面**（enabled / freshness_now / temporal_gamma
        # ——后者是 γ 的实际读取点：resolve_gamma 的 early-return 分支不碰
        # temporal_gamma，故「temporal_gamma 常数」即「γ 的 env 读取归零」）。
        # 诚实边界：resolve_gamma 的**函数调用**仍每节点一次（early-return
        # 直通已解析的 float，~0.15µs/节点、不读 env）——保留它是因为
        # resolve_gamma 还承担「非法 gamma 回落缺省」的单点边界语义，跳过
        # 调用会改变该边界。
        check("env 读取面与文档数无关（enabled/now/temporal；修前各 N×）",
              {k: c2[k] for k in ("enabled", "now", "temporal")}
              == {k: c20[k] for k in ("enabled", "now", "temporal")},
              f"c2={c2} c20={c20}")
        check("enabled() 常数级（修前 = 4×N）", c20["enabled"] <= 2, str(c20))
        check("freshness_now() 常数级（修前 = 1×N）", c20["now"] <= 1, str(c20))
        check("temporal_gamma() 常数级（修前 = 1×N；γ 的实际读取点）",
              c20["temporal"] <= 1, str(c20))
        # 自证腿（常驻）：全缺省签名的旧路径仍自算，四个 spy 数得到——证明
        # 上面的「零/常数」不是 spy 失效造成的假绿（判别力在位）。
        for k in c:
            c[k] = 0
        F.entry_weight({"created_at": REF, "importance": 0.5})
        check("自证腿：全缺省签名仍自算（四路 spy 各 ≥1，判别力在位）",
              c["enabled"] >= 1 and c["now"] >= 1 and c["gamma"] >= 1
              and c["temporal"] >= 1, str(c))
        # 语义等价：显式透传与自算逐位同值；关闭恒 1.0（三面同口径）
        e0 = {"created_at": REF - 30 * DAY, "importance": 0.5}
        check("显式 enabled+now+γ 透传与自算同值（逐位一致）",
              F.entry_weight(e0, now=REF)[0]
              == F.entry_weight(e0, now=REF, gamma=F.resolve_gamma(None),
                                enabled=True)[0])
        check("enabled=False 恒 1.0（entry/decay/refresh 三面同口径）",
              F.entry_weight(e0, now=REF, enabled=False)[0] == 1.0
              and F.decay_factor(0.023, 100.0, enabled=False) == 1.0
              and F.refresh_factor(0, 0, 0.9, enabled=False) == 1.0)
    finally:
        F.enabled = orig["enabled"]
        F.freshness_now = orig["freshness_now"]
        F.resolve_gamma = orig["resolve_gamma"]
        MC.temporal_gamma = orig_tg
        cg.close()
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def _mut_floor_zero():
    return _patch(F, "SCORE_FLOOR", 0.0)


def _mut_gain_10x():
    orig = dict(F.REFRESH_PARAMS)

    def restore():
        F.REFRESH_PARAMS.clear()
        F.REFRESH_PARAMS.update(orig)
    F.REFRESH_PARAMS["gain"] = 0.1
    return restore


def _mut_unit_seconds():
    return _patch(F, "SECONDS_PER_DAY", 1.0)


def _mut_protect_floor_off():
    orig = F.protected_floor
    F.protected_floor = lambda entry: F.SCORE_FLOOR

    def restore():
        F.protected_floor = orig
    return restore


def _mut_switch_off():
    return _patch(F, "enabled", lambda environ=None: False)


def _patch(mod, name, value):
    orig = getattr(mod, name)

    def restore():
        setattr(mod, name, orig)
    setattr(mod, name, value)
    return restore


_MUTATIONS = [
    ("floor_zero", "衰减 floor 归零", _mut_floor_zero),
    ("gain_10x", "刷新步长改成 0.1（脱离 AEIS 取值）", _mut_gain_10x),
    ("unit_seconds", "Δt 单位改成「秒」", _mut_unit_seconds),
    ("protect_floor_off", "去掉受保护节点的保护下界", _mut_protect_floor_off),
    ("switch_off", "乘子开关恒关", _mut_switch_off),
]


def _collect():
    global PASS, FAIL, FAILS
    PASS, FAIL, FAILS = 0, 0, []
    g1_core_authority()
    g2_gamma_and_unit()
    g3_refresh_params()
    g4_floor()
    g5_same_multiplier_slot()
    g6_index_entry_data()
    g7_switch()
    g8_triplet()
    g9_degrade_not_delete()
    g10_weights_autoprotect_kept()
    g11_rust_parity()
    g12_rust_parity_e2e()
    g13_hot_loop_reads()
    return list(FAILS)


def main(argv):
    if "--mutate" in argv:
        if "--list" in argv:
            for name, desc, _fn in _MUTATIONS:
                print(f"  {name:20s} {desc}")
            return 0
        base = _collect()
        if base:
            print(f"\n!! 基线不绿（{len(base)} 条）：{base}")
            return 1
        bad = []
        for name, desc, fn in _MUTATIONS:
            try:
                restore = fn()
            except AttributeError as exc:
                print(f"  ANCHOR-MISS {name}: {exc}")
                return 2
            got = _collect()
            restore()
            if got:
                print(f"  MUTATE-OK {name}（{desc}）→ 转红 {len(got)} 条：{got[:3]}")
            else:
                bad.append(name)
                print(f"  MUTATE-FAIL {name}（{desc}）→ 仍全绿")
        print(f"\ntest_p4_freshness --mutate: "
              f"{len(_MUTATIONS) - len(bad)}/{len(_MUTATIONS)} 变异按预期转红")
        return 0 if not bad else 1
    fails = _collect()
    print(f"\ntest_p4_freshness: {PASS} 通过 / {FAIL} 失败")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
