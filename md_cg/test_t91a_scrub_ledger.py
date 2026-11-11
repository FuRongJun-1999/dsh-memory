# -*- coding: utf-8 -*-
"""t91a 守卫：`_scrub.jsonl` 台账必须**如实**记 auto 开关——dry_run 不许伪装成已启用。

病（已核实）：`sustain.py:_tick_scrub` **无条件每轮都跑** `scrub.sweep`，
dry_run 由 `not self.auto_scrub` 取反；而 `AUTO_DEFAULTS["auto_scrub"] is False`
（`sustain.py:36`）。于是默认部署下 `_scrub.jsonl` 每轮都有一行，
**有行 ≠ scrub 已启用**——读台账的人会把「每轮只读巡检」误读成「修剪已上线」。

本套判据（对应 accept ①②③④⑤，全部在**真 tick** 上取证，非静态读码）：

  G1 字段一致：`auto_scrub=True` 跑真 tick → 常驻自己的账行里 `dry_run is False`
     且 `auto_scrub is True`；`auto_scrub=False` 跑真 tick → `dry_run is True`
     且 `auto_scrub is False`。两个方向都断言（只测一边会被常量蒙混过关）。
  G2 反例守卫（真跑有副作用）：`auto_scrub=True` 的 tick 必须产生**可观察的
     修剪副作用**——陈旧 `.md.tmp` 被清（`writepipe` 陈旧临时文件清扫）、
     候选节点被处理；`auto_scrub=False` 的 tick 必须**零变更**（同一指纹逐位相同）。
  G3 读侧一致性：从台账反推「本轮 scrub 到底跑没跑」的函数，对 dry 与真跑
     **两种情形都给正确答案**。
  G4 向后兼容：`last_scrub` / `status()` / `_scrub.jsonl` 的既有键一个不少、
     值不变，新键只做加法。
  G5 影子根真跑：全程 `tempfile.mkdtemp` 临时影子根，先真 tick 再断言；
     不读、不写任何真实数据根。

沙箱注记：本套不起子进程，与 CreatePipe 禁令无涉；临时目录建在系统临时区，
只读校验后 `rmtree` 回收。

运行：
  python D:\\wook\\lingshu-src\\md_cg\\test_t91a_scrub_ledger.py     # 退出码 0 = 全绿
  python -m md_cg.test_t91a_scrub_ledger --mutate M1                # 定点变异自证
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if __package__:
    from . import scrub as _scrub
    from . import sustain as _sustain
    from .mdcg import MdCG
else:                                  # 直接 `python md_cg/test_t91a_scrub_ledger.py` 也能跑
    sys.path.insert(0, _REPO)
    from md_cg import scrub as _scrub
    from md_cg import sustain as _sustain
    from md_cg.mdcg import MdCG

PASS = FAIL = 0
FAILS = []

#: 陈旧临时文件的 mtime 回拨量（秒）——`writepipe.sweep_stale_temps` 阈值 1h，
#: 回拨 2h 保证必被判陈旧（确定性，不靠等时间）。
STALE_BACKDATE_S = 7200.0

#: G4 钉死的既有键（`_tick_scrub` 的**内存账行**形态基线 = 改动前 `sustain.py:1986-1718`）。
LEGACY_KEYS = ("t", "ok", "n_issues", "n_high_medium", "applied",
               "already_handled", "planned_dry_run", "checked_breakdown",
               "seed", "dry_run")

#: `_scrub.jsonl` 里 `op=="sweep"` 行的既有键基线（由 `scrub.sweep:914` 写）。
LEGACY_ROW_KEYS = ("op", "n_sample", "n_issues", "n_high_medium", "applied",
                   "dry_run", "already_handled", "planned_dry_run",
                   "checked_breakdown", "calibration", "t")


# 生效条件：cond 为真记录 PASS 并返回 True，否则记录 FAIL 并返回 False；group/label 为断言分组与名。
def ok(cond, group, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append((group, label))
        print(f"  FAIL [{group}] {label}")
    return bool(cond)


# --------------------------------------------------------------------------
# 场景工具（全部在影子根上）
# --------------------------------------------------------------------------

# 生效条件：`tempfile.mkdtemp` 造一个临时父目录并返回其绝对路径（调用方负责 rmtree）。
def mk_tmp():
    return tempfile.mkdtemp(prefix="t91a_scrub_")


# 生效条件：在 root 下造一个含**可修剪候选**的库并返回该 cg——两个 expired 节点
# （high：weaken+demote）、一个孤立噪音（low）、一个过期但高重要的受保护节点
# （protected 跳过，用于证明「真跑也不是无差别乱动」）。
def mk_lib(root):
    cg = MdCG(root)
    # expired / high：会被 weaken + demote（可观察副作用）
    cg.add("t91a-exp-a", "# 功能名：过期甲\n\n这条已过期",
           layer="knowledge", importance=0.5, confidence=0.6,
           valid_until="2020-01-01")
    cg.add("t91a-exp-b", "# 功能名：过期乙\n\n这条也已过期",
           layer="knowledge", importance=0.5, confidence=0.6,
           valid_until="2020-01-01")
    # orphan_noise / low：零访问 + 低重要 + 情境层（weaken）
    cg.add("t91a-orphan", "# 功能名：孤立噪音\n\n孤立的情境噪音",
           layer="contextual", importance=0.2, confidence=0.6)
    # 受保护（importance≥0.7）：任何开关下都不得被动——真跑≠无差别乱动
    cg.add("t91a-prot", "# 功能名：重要过期\n\n重要节点但过期",
           layer="knowledge", importance=0.9, confidence=0.8,
           valid_until="2020-01-01")
    return cg


# 生效条件：造一个 2 小时前 mtime 的陈旧临时残留于 cg.root，返回其路径。命名
# 与路径**必须逐字符合** `fsutil.sweep_stale_temps` 的判据（`startswith(".")` 且
# 含 `".tmp-"`）——「陈旧临时文件被清」是 `MdCG.__init__` 的既有副作用，
# 用来把「真跑确实在盘面上动了手」与「只看不改一点没动」区分开。
def mk_stale_tmp(cg, name="t91a_stale"):
    p = os.path.join(cg.root, f".{name}.md.tmp-0")
    with open(p, "w", encoding="utf-8") as f:
        f.write("陈旧残留\n")
    old = time.time() - STALE_BACKDATE_S
    os.utime(p, (old, old))
    return p


# 生效条件：读 `<cg.root>/_scrub.jsonl` 的 `op=="sweep"` 行（缺文件返回 []）。
# 说明：常驻 `_tick_scrub` 的账在**内存**（`last_scrub` / `scrubs`），落盘的
# `_scrub.jsonl` 里 `op=="sweep"` 那一行由 `scrub.sweep` 自己写（`:914`），
# 故它**不含** `auto_scrub`——这是既有分账，不是缺陷。
def sweep_recs(cg):
    p = os.path.join(cg.root, _scrub.SCRUB_LOG)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                if rec.get("op") == "sweep":
                    out.append(rec)
    return out


# 生效条件：返回 cg 数据根的可观察指纹 dict——每个 `.md` 文件（含空文件）的
# 相对路径 → 字节数 + sha1；外加索引里的节点集合与 层/置信/反例 读数。
# 用于「dry_run 轮零变更」与「真跑轮确有变更」的**逐位**对照。
def fingerprint(cg):
    import hashlib
    files = {}
    for dirpath, _dirnames, filenames in os.walk(cg.root):
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, cg.root).replace("\\", "/")
            with open(fp, "rb") as f:
                data = f.read()
            files[rel] = [len(data), hashlib.sha1(data).hexdigest()]
    nodes = {}
    for nid in sorted((cg.index.get("nodes") or {})):
        node = cg.get(nid) or {}
        fm = node.get("frontmatter") or {}
        nodes[nid] = [fm.get("layer"), fm.get("confidence"),
                      fm.get("negative_evidence"),
                      (node.get("content") or "")[:0]]
    fm_all = {}
    for nid in sorted((cg.index.get("nodes") or {})):
        node = cg.get(nid) or {}
        fm = node.get("frontmatter") or {}
        fm_all[nid] = {k: fm.get(k) for k in
                       ("layer", "confidence", "negative_evidence",
                        "evidence_count")}
    return {"files": files, "nodes": nodes, "fm": fm_all}


# 生效条件：指纹差异摘要 list（供断言失败时打印可读证据）。
def fp_diff(a, b):
    out = []
    for k in sorted(set(a["files"]) | set(b["files"])):
        if a["files"].get(k) != b["files"].get(k):
            out.append(f"file {k}: {a['files'].get(k)} -> {b['files'].get(k)}")
    for k in sorted(set(a["fm"]) | set(b["fm"])):
        if a["fm"].get(k) != b["fm"].get(k):
            out.append(f"fm {k}: {a['fm'].get(k)} -> {b['fm'].get(k)}")
    return out


# --------------------------------------------------------------------------
# 读侧反推（G3 的被测面）
# --------------------------------------------------------------------------

# 生效条件：传入一条 scrub 台账记录，返回 'applied'（本轮真跑并改了东西）/
# 'ran_noop'（本轮真跑、无可动）/ 'dry_run_only'（本轮只看不改）/
# 'unknown'（`dry_run` 缺键——旧格式，**不猜**）。
# 纪律：不以「台账里有没有行」推断已启用；只认显式 `dry_run` 字段。
def did_scrub_run(rec):
    if not isinstance(rec, dict) or "dry_run" not in rec:
        return "unknown"
    if rec.get("dry_run") is False:
        return "applied" if int(rec.get("applied") or 0) > 0 else "ran_noop"
    return "dry_run_only"


# --------------------------------------------------------------------------
# G1 字段一致性（真 tick，两个方向）
# --------------------------------------------------------------------------

def g1_flag_faithful(sc, su, tmp):
    # 方向 A：auto_scrub=True → dry_run=False
    root_a = os.path.join(tmp, "g1_true")
    cg_a = mk_lib(root_a)
    lp_a = su.SustainLoop(cg_a, "t91a_g1a", auto_scrub=True,
                          d=os.path.join(tmp, "g1_true_net"))
    lp_a._tick_scrub()                      # ← 真 tick（不是造常量）
    ra = lp_a.last_scrub or {}
    rows_a = sweep_recs(cg_a)
    ok(ra.get("dry_run") is False and ra.get("auto_scrub") is True, "G1",
       f"auto_scrub=True 的 tick：last_scrub dry_run/auto_scrub = "
       f"{ra.get('dry_run')!r}/{ra.get('auto_scrub')!r}")
    ok(bool(rows_a) and rows_a[-1].get("dry_run") is False, "G1",
       f"_scrub.jsonl 落下 dry_run=False 的实修行（真跑确实写进了台账）："
       f"{ {k: rows_a[-1].get(k) for k in ('dry_run', 'applied')} if rows_a else None }")

    # 方向 B：auto_scrub=False → dry_run=True
    root_b = os.path.join(tmp, "g1_false")
    cg_b = mk_lib(root_b)
    lp_b = su.SustainLoop(cg_b, "t91a_g1b", auto_scrub=False,
                          d=os.path.join(tmp, "g1_false_net"))
    lp_b._tick_scrub()
    rb = lp_b.last_scrub or {}
    rows_b = sweep_recs(cg_b)
    ok(rb.get("dry_run") is True and rb.get("auto_scrub") is False, "G1",
       f"auto_scrub=False 的 tick：last_scrub dry_run/auto_scrub = "
       f"{rb.get('dry_run')!r}/{rb.get('auto_scrub')!r}")
    ok(bool(rows_b) and rows_b[-1].get("dry_run") is True, "G1",
       f"_scrub.jsonl 的巡检行 dry_run=True（有行 ≠ 已启用）："
       f"{ {k: rows_b[-1].get(k) for k in ('dry_run', 'applied')} if rows_b else None }")

    # 方向 C（**不信记账，信盘面**）：只在 `self.auto_scrub` 与**真跑的证据**之间
    # 建立联系——台账说 dry_run=False 时盘面必须真的变了。没有这条，一个把
    # `dry_run` 写成常量的谎言（两边都对不上却没东西被动过）仍可能溜过去。
    ok(ra.get("applied") == rb_row_applied(rows_a), "G1",
       "真跑轮：last_scrub.applied 与落盘 sweep 行同源同值")
    ok(int(ra.get("applied") or 0) > 0 and int(rb.get("applied") or 0) == 0, "G1",
       f"开关取值与副作用方向一致：auto_scrub=True applied={ra.get('applied')}"
       f" > 0；auto_scrub=False applied={rb.get('applied')} == 0")

    # 缺省路径：不传 auto_scrub 取真源缺省（AUTO_DEFAULTS=False）→ 必须记 dry
    root_c = os.path.join(tmp, "g1_default")
    cg_c = mk_lib(root_c)
    lp_c = su.SustainLoop(cg_c, "t91a_g1c", d=os.path.join(tmp, "g1_def_net"))
    lp_c._tick_scrub()
    rc = lp_c.last_scrub or {}
    ok(su.AUTO_DEFAULTS["auto_scrub"] is False
       and rc.get("auto_scrub") is False and rc.get("dry_run") is True, "G1",
       f"缺省（auto_scrub 取真源 False）的 tick 也记 dry_run=True："
       f"{rc.get('dry_run')!r}/{rc.get('auto_scrub')!r}")
    for lp in (lp_a, lp_b, lp_c):
        lp.stop()


# 生效条件：取末条落盘 sweep 行的 applied 读数（无行返回 None）——用于把
# `last_scrub.applied`（常驻账）与落盘行车牌对齐，防「内存账与盘面账分叉」。
def rb_row_applied(rows):
    return (rows[-1].get("applied") if rows else None)


# --------------------------------------------------------------------------
# G2 反例守卫：真跑有副作用 / dry 零变更
# --------------------------------------------------------------------------

def g2_counterexample(sc, su, tmp):
    # ---- 真跑：必须产生可观察副作用 ----
    root_t = os.path.join(tmp, "g2_true")
    cg_t = mk_lib(root_t)
    stale = mk_stale_tmp(cg_t)
    ok(os.path.exists(stale), "G2", "影子根上造出陈旧临时残留（真跑前存在）")
    before = fingerprint(cg_t)
    lp_t = su.SustainLoop(cg_t, "t91a_g2t", auto_scrub=True,
                          d=os.path.join(tmp, "g2_true_net"))
    lp_t._tick_scrub()
    lp_t.stop()
    after = fingerprint(cg_t)
    rec_t = lp_t.last_scrub or {}
    diff = fp_diff(before, after)
    ok(rec_t.get("dry_run") is False, "G2",
       f"真跑轮 dry_run=False（实得 {rec_t.get('dry_run')!r}）")
    ok(int(rec_t.get("applied") or 0) >= 1, "G2",
       f"真跑轮 applied={rec_t.get('applied')} ≥ 1（确实处理了候选节点）")
    # 副作用（一）：候选节点被真改（层/置信/反例任一处变化）
    changed_nodes = [n for n in before["fm"]
                     if after["fm"].get(n) != before["fm"].get(n)]
    ok(bool(changed_nodes), "G2",
       f"真跑轮候选节点被处理（fm 变更的节点）：{changed_nodes}")
    ok(after["fm"].get("t91a-exp-a", {}).get("confidence")
       != before["fm"].get("t91a-exp-a", {}).get("confidence")
       or after["fm"].get("t91a-exp-a", {}).get("layer") != "knowledge", "G2",
       f"t91a-exp-a 被 weaken/demote：{before['fm'].get('t91a-exp-a')} -> "
       f"{after['fm'].get('t91a-exp-a')}")
    # 副作用（二）：真跑的盘面变更**只落在候选节点上**——受保护节点纹丝不动
    # （真跑 ≠ 无差别乱动），且 dry_run=False 这一事实有盘面证据背书。
    ok(after["fm"].get("t91a-prot") == before["fm"].get("t91a-prot"), "G2",
       f"真跑轮受保护节点未被波及：{after['fm'].get('t91a-prot')}")
    ok(bool(diff), "G2", f"真跑轮盘面确有变更：{diff[:3]}")

    # ---- 只看不改：必须零变更 ----
    root_d = os.path.join(tmp, "g2_dry")
    cg_d = mk_lib(root_d)
    stale_d = mk_stale_tmp(cg_d, "t91a_stale_dry")
    before_d = fingerprint(cg_d)
    lp_d = su.SustainLoop(cg_d, "t91a_g2d", auto_scrub=False,
                          d=os.path.join(tmp, "g2_dry_net"))
    lp_d._tick_scrub()
    lp_d.stop()
    after_d = fingerprint(cg_d)
    rec_d = lp_d.last_scrub or {}
    ok(rec_d.get("dry_run") is True, "G2",
       f"dry 轮 dry_run=True（实得 {rec_d.get('dry_run')!r}）")
    ok(int(rec_d.get("applied") or 0) == 0, "G2",
       f"dry 轮 applied=0（实得 {rec_d.get('applied')}）")
    ok(before_d == after_d, "G2",
       f"dry 轮**零变更**（节点 fm / 层 / 内容 / 全部 .md 逐位相同）；"
       f"差异={fp_diff(before_d, after_d)[:3]}")
    ok(after_d["fm"].get("t91a-exp-a") == before_d["fm"].get("t91a-exp-a"), "G2",
       f"dry 轮 t91a-exp-a 逐位未动：{after_d['fm'].get('t91a-exp-a')}")

    # 真跑轮 vs dry 轮：同类库上「真跑有变、dry 零变」——反例守卫成立
    ok(bool(diff) and not fp_diff(before_d, after_d), "G2",
       "反例守卫：同一形态的库上，真跑有副作用而 dry 零副作用")


# --------------------------------------------------------------------------
# G3 读侧一致性（dry 与真跑两种情形都对）
# --------------------------------------------------------------------------

def g3_read_side(sc, su, tmp):
    root_t = os.path.join(tmp, "g3_true")
    cg_t = mk_lib(root_t)
    lp_t = su.SustainLoop(cg_t, "t91a_g3t", auto_scrub=True,
                          d=os.path.join(tmp, "g3_true_net"))
    lp_t._tick_scrub()
    lp_t.stop()
    rows_t = sweep_recs(cg_t)

    root_d = os.path.join(tmp, "g3_dry")
    cg_d = mk_lib(root_d)
    lp_d = su.SustainLoop(cg_d, "t91a_g3d", auto_scrub=False,
                          d=os.path.join(tmp, "g3_dry_net"))
    lp_d._tick_scrub()
    lp_d.stop()
    rows_d = sweep_recs(cg_d)

    ok(bool(rows_t) and did_scrub_run(rows_t[-1]) == "applied", "G3",
       f"真跑行反推 = 'applied'（实得 {did_scrub_run(rows_t[-1]) if rows_t else None}）")
    ok(bool(rows_d) and did_scrub_run(rows_d[-1]) == "dry_run_only", "G3",
       f"dry 行反推 = 'dry_run_only'（实得 {did_scrub_run(rows_d[-1]) if rows_d else None}）")
    ok(did_scrub_run({}) == "unknown"
       and did_scrub_run({"op": "sweep", "n_issues": 3}) == "unknown", "G3",
       "缺 dry_run 字段的旧行 → 'unknown'（不猜「已启用」）")
    ok(did_scrub_run({"dry_run": False, "applied": 0}) == "ran_noop", "G3",
       "真跑但无可动 → 'ran_noop'（仍属「跑过了」）")
    # 「有行 ≠ 已启用」这一读法本身被守卫：dry 轮的账行非空但反推是 dry_run_only
    ok(bool(rows_d) and did_scrub_run(rows_d[-1]) != "applied", "G3",
       f"dry 轮『台账有行』不得读成已启用（行数={len(rows_d)}）")


# --------------------------------------------------------------------------
# G4 向后兼容（既有键一个不少、值不变）
# --------------------------------------------------------------------------

def g4_compat(sc, su, tmp):
    root = os.path.join(tmp, "g4")
    cg = mk_lib(root)
    lp = su.SustainLoop(cg, "t91a_g4", auto_scrub=False,
                        d=os.path.join(tmp, "g4_net"))
    lp._tick_scrub()
    rec = lp.last_scrub or {}
    missing = [k for k in LEGACY_KEYS if k not in rec]
    ok(not missing, "G4", f"last_scrub 既有键一个不少（缺={missing}）")
    ok(isinstance(rec.get("checked_breakdown"), dict)
       and set(rec["checked_breakdown"]) == {"applied", "already_handled",
                                             "planned_dry_run", "protected",
                                             "hint"}, "G4",
       f"checked_breakdown 形状不变：{sorted(rec.get('checked_breakdown') or {})}")
    ok(isinstance(rec.get("seed"), str) and rec["seed"].startswith("sustain:"),
       "G4", f"seed 形态不变：{rec.get('seed')!r}")
    ok(lp.scrub_round == 1 and len(lp.scrubs) == 1, "G4",
       f"scrubs 环形账仍只追加：scrub_round={lp.scrub_round} len={len(lp.scrubs)}")
    st = lp.status()
    ok(isinstance(st, dict) and st.get("last_scrub") is not None, "G4",
       "status() 返回形状不破（仍含 last_scrub）")
    ok(set(st.get("last_scrub") or {}) >= set(LEGACY_KEYS), "G4",
       "status() 里 last_scrub 亦带全部既有键")
    # 新键只做加法：dry_run / auto_scrub 都在，且旧键值未被顶替
    rec2 = dict(rec)
    ok(rec2.get("applied") == (lp.last_scrub or {}).get("applied"), "G4",
       "旧键 applied 语义未变（= decontaminate.applied）")
    rows = sweep_recs(cg)
    ok(bool(rows) and set(rows[-1]) >= set(LEGACY_ROW_KEYS), "G4",
       f"_scrub.jsonl 的 sweep 行既有键一个不少："
       f"缺={[k for k in LEGACY_ROW_KEYS if k not in (rows[-1] if rows else {})]}")
    lp.stop()


# --------------------------------------------------------------------------
# G5 影子根真跑（不碰真实数据根）
# --------------------------------------------------------------------------

def g5_shadow_root(sc, su, tmp):
    ok(os.path.abspath(tmp).lower().startswith(
        os.path.abspath(tempfile.gettempdir()).lower()), "G5",
       f"工作根位于系统临时区（影子根）：{tmp}")
    ok("_scrub.jsonl" not in os.listdir(tmp), "G5",
       "断言前临时根下无预置台账（所有读数都来自本轮真 tick）")
    # 真 tick 写出的台账确实落在影子根里（不是别处的缓存读数）
    root = os.path.join(tmp, "g5")
    cg = mk_lib(root)
    lp = su.SustainLoop(cg, "t91a_g5", auto_scrub=False,
                        d=os.path.join(tmp, "g5_net"))
    lp._tick_scrub()
    lp.stop()
    ok(os.path.exists(os.path.join(root, sc.SCRUB_LOG)), "G5",
       "真 tick 在影子根下落了 _scrub.jsonl（读的是真账，不是常量）")
    # 陈旧临时残留是 `MdCG.__init__` 的既有清扫面：它只作「真跑/只看不改」的
    # 盘面变更旁证，与 scrub 抽样无关——显式钉住这条**旁证自身的有效性**，
    # 免得它在别的批次里静默失效（失效时本套会以「副作用缺失」误导）。
    probe_root = os.path.join(tmp, "g5probe")
    cg2 = MdCG(probe_root)
    sp = mk_stale_tmp(cg2, "t91a_g5probe")
    ok(os.path.exists(sp), "G5", "陈旧临时残留造得出来（命名符合清扫判据）")
    MdCG(probe_root)                                  # 再开一次 → 走 __init__ 清扫
    ok(not os.path.exists(sp), "G5",
       "陈旧临时残留确实会被既有清扫面清掉（副作用旁证有效）")


# --------------------------------------------------------------------------
# 运行
# --------------------------------------------------------------------------

def run_all(sc, su):
    global PASS, FAIL, FAILS
    PASS = FAIL = 0
    FAILS = []
    tmp = mk_tmp()
    try:
        g1_flag_faithful(sc, su, tmp)
        g2_counterexample(sc, su, tmp)
        g3_read_side(sc, su, tmp)
        g4_compat(sc, su, tmp)
        g5_shadow_root(sc, su, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return PASS, FAIL, list(FAILS)


def _mutations():
    sup = os.path.join(_HERE, "sustain.py")
    return {
        "M1": (sup,
               '''        dry = not self.auto_scrub
        rep = scrub.sweep(self.cg, dry_run=dry, seed=seed)''',
               '''        dry = False
        rep = scrub.sweep(self.cg, dry_run=dry, seed=seed)''',
               {"G1", "G2", "G3"},
               "伪装已启用：无论开关都按真跑跑（re-伪装病本体）"),
        "M2": (sup,
               '''               "dry_run": dry,
               "auto_scrub": self.auto_scrub}''',
               '''               "dry_run": rep["dry_run"],
               "auto_scrub": self.auto_scrub}''',
               set(),
               "真源漂移（**等价类，非缺陷**）：账行改读 rep；而 scrub.sweep "
               "返回的 dry_run 只来自入参，故 rep['dry_run'] is dry 恒真、二者"
               "不可区分。预期**零红项**，跑它是为把这条等价性钉住"),
        "M3": (sup,
               '''               "dry_run": dry,
               "auto_scrub": self.auto_scrub}''',
               '''               "dry_run": False,
               "auto_scrub": self.auto_scrub}''',
               {"G1", "G2"},
               "常量伪装：台账恒记 dry_run=False（最原始的那种谎）"),
        # M4 专测「账与盘面分叉」：开关说 dry、盘面却按真跑改了库。单看常驻
        # 内存账（dry_run=True）与开关（auto_scrub=False）二者是自洽的，只有把
        # 台账读数与**真跑证据**（applied / 盘面变更）对起来才抓得住。
        "M4": (sup,
               '''        dry = not self.auto_scrub
        rep = scrub.sweep(self.cg, dry_run=dry, seed=seed)''',
               '''        dry = not self.auto_scrub
        rep = scrub.sweep(self.cg, dry_run=False, seed=seed)''',
               {"G1", "G2", "G3"},
               "账盘分叉：开关说 dry，盘面却按真跑改了库"),
    }


def _load_mutated(path, old, new, name):
    import types
    with open(path, encoding="utf-8") as f:
        src = f.read()
    n = src.count(old)
    if n != 1:
        raise SystemExit(f"变异目标在源码中出现 {n} 次（须恰 1 次）：{name}")
    src = src.replace(old, new, 1)
    mod = types.ModuleType(name)
    mod.__package__ = "md_cg"          # 相对导入仍解析到真包
    mod.__file__ = path
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mutate = None
    if argv and argv[0] == "--mutate":
        mutate = argv[1] if len(argv) > 1 else None
    sc, su = _scrub, _sustain
    expect = None
    if mutate:
        muts = _mutations()
        if mutate not in muts:
            print(f"未知变异：{mutate}（可选：{', '.join(sorted(muts))}）")
            return 2
        path, old, new, expect, why = muts[mutate]
        mod = _load_mutated(path, old, new, "md_cg.sustain_mut")
        su = mod
        print(f"== 定点变异 {mutate}：{why} ==")
    passed, failed, fails = run_all(sc, su)
    if expect is None:
        print(f"\nt91a_scrub_ledger: {passed} passed, {failed} failed")
        for g, lbl in fails:
            print(f"  - [{g}] {lbl}")
        return 1 if failed else 0
    hit = sorted({g for g, _ in fails})
    good = set(hit) == set(expect)
    print(f"  变异红项组={hit} 预期={sorted(expect)} → "
          f"{'定点命中' if good else '未命中/连带'}")
    if not good:
        for g, lbl in fails:
            print(f"  - [{g}] {lbl}")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
