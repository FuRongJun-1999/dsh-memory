# -*- coding: utf-8 -*-
"""心跳台账（append-only · 有界分片轮转）守卫 —— 让「连续 N 周期无断」可严格测得。

背景（答卷 `docs/plans/灵枢1.0_最小智能系统实存答卷_v1.1.md` §八 分诊第 4 项，
**甲类能力缺口**；取证 `docs/eval/W7v11_结构面局限取证_v0.1.md` §丁）：
`_sustain.jsonl` 是 heal **动作**台账（有动作才写，平静期与停摆期不可区分），心跳戳
是**覆盖式单点**（无历史序列）——「连续 N 周期无断」在现数据结构下**不可严格测得**。
补法＝给心跳加 **append-only 台账**（`<root>/_heartbeat.jsonl`），配合**分片轮转＋
保留片数上限**（有界）与**只读统计**。

断言面（每条＝一个可定点变异的判据）：
  L1 **零判定变更**（硬门）：台账**开/关**下，`beat()` 返回、心跳戳字段、
     `_sustain.jsonl` 既有记录、`judge()`/`heal()`/`diagnose()` 的返回**逐位一致**
     （依 `root`/时间戳等天然差异字段外）。
  L2 **append-only**：台账只追加——旧字节是新内容的**前缀**，行数==写入次数，
     历史行不被改写。
  L3 **断点可检出**：注入一个人为断档（周期缺失 > 阈值）后，`heartbeat_ledger_stats`
     **报出断点**且最长连续区间**缩短**。
  L4 **有界**（硬门）：超轮转阈值后分片产生、保留片数受上限约束（淘汰有痕，
     不静默丢）；`HEARTBEAT_ROTATE_BYTES=0` 为显式退回无上界开关。

运行：python -X utf8 -m md_cg.test_heartbeat_ledger
      python -X utf8 -m md_cg.test_heartbeat_ledger --mutate          # 定点变异自证
      python -X utf8 -m md_cg.test_heartbeat_ledger --mutate --list   # 只列变异表

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到——实现改了却没同步本表，不得静默跳过）。

**基线纪律**：不以 git HEAD 为基线源——「改动前形态」由在当前工作区源码上做
**定点文本变异**（`_MUTATIONS`）复现，锚点漂移即退出码 2。
**沙箱纪律**：库根/辅助根/状态根/心跳目录全落守卫临时目录，绝不碰在役库与 `~/.mdcg`。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import types

from . import sustain
from .fsutil import read_jsonl

_PASS = []
_FAIL = []
_SRC = {}                                  # 变异模式下的源码文本（rel → text）
_REAL = sustain
_ORIG = {n: getattr(sustain, n) for n in (
    "HEARTBEAT_ROTATE_BYTES", "HEARTBEAT_KEEP_SHARDS", "HEARTBEAT_PROBE_EVERY",
    "HEARTBEAT_GAP_THRESHOLD")}


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rel_text(rel: str) -> str:
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_repo_root(), rel), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- 沙箱
_TMP = tempfile.mkdtemp(prefix="mdcg_hbledger_")
_SAVED = {}
_GEN = [0]
_ENV_KEYS = ("MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT", "MDCG_SUSTAIN_DIR",
             "MDCG_HEARTBEAT_LEDGER")


def _sandbox_env():
    for k in _ENV_KEYS:
        _SAVED[k] = os.environ.get(k)
    os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cg")
    os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "aux")
    os.environ["MDCG_STATE_ROOT"] = os.path.join(_TMP, "state")
    os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(_TMP, "sustain")
    os.environ.pop("MDCG_HEARTBEAT_LEDGER", None)


def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _fresh_root(tag):
    """每轮用**全新根**（同一根跨轮复用会读到上一轮残留而假绿）。"""
    _GEN[0] += 1
    root = os.path.join(_TMP, "gen%d" % _GEN[0], tag)
    os.makedirs(root, exist_ok=True)
    return root


def _netdir(tag):
    d = os.path.join(_TMP, "net", tag)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- 投影
#: 天然随运行变化的字段（路径/时间戳）——零判定变更比对应**排除**它们，其余逐位比。
_VOLATILE = ("ts", "iso", "uptime", "t", "age", "mtime", "updated_at",
             "last_t", "root", "path", "started_at")


def _strip(v):
    if isinstance(v, dict):
        return {k: _strip(x) for k, x in v.items() if k not in _VOLATILE}
    if isinstance(v, list):
        return [_strip(x) for x in v]
    return v


def _canon(v, root):
    """把该跑的库根路径归一为 <ROOT>——两跑库根不同，路径差异不算判定差异。"""
    s = json.dumps(_strip(v), ensure_ascii=False, sort_keys=True)
    for form in (root, root.replace(os.sep, "/")):
        s = s.replace(json.dumps(form)[1:-1], "<ROOT>")
    return s


# ---------------------------------------------------------------- G0 基线
def g0():
    print("== G0 隔离与基线自证 ==")
    S = globals()["sustain"]
    ok(S.heartbeat_ledger_enabled() is True,
       "G0a 缺省开：未设 MDCG_HEARTBEAT_LEDGER 时台账启用")
    ok(all(S.heartbeat_ledger_enabled({"MDCG_HEARTBEAT_LEDGER": off}) is False
           for off in ("0", "false", "False")),
       "G0b 关断字面量 0/false/False 均关（沿用 AUTO_OFF_VALUES 口径）")
    ok(all(S.heartbeat_ledger_enabled({"MDCG_HEARTBEAT_LEDGER": on}) is True
           for on in ("1", "true", "", "yes")),
       "G0c 其余值（含空串）为开——只有三个关断字面量算关")
    ok(S.HEARTBEAT_ROTATE_BYTES > 0 and S.HEARTBEAT_KEEP_SHARDS > 0
       and S.HEARTBEAT_PROBE_EVERY >= 1,
       "G0d 有界参数缺省 >0（轮转开、保留片数有上限、节流步长≥1）",
       (S.HEARTBEAT_ROTATE_BYTES, S.HEARTBEAT_KEEP_SHARDS, S.HEARTBEAT_PROBE_EVERY))
    ok(S.heartbeat_path("/x") == os.path.join("/x", S.HEARTBEAT_LOG)
       and S.HEARTBEAT_LOG == "_heartbeat.jsonl",
       "G0e 台账落点＝<root>/_heartbeat.jsonl（与 _sustain.jsonl 同域）",
       S.heartbeat_path("/x"))
    ok(os.environ["MDCG_ROOT"].startswith(_TMP),
       "G0f 沙箱：库根在守卫临时目录内（绝不碰在役库）", os.environ["MDCG_ROOT"])


# ---------------------------------------------------------------- L1 零判定变更
def _l1_scenario(root, netdir):
    """跑一段固定序列，返回「既有读面」的投影（台账开/关两跑须逐位一致）。"""
    from .mdcos import MdCGOS
    S = globals()["sustain"]
    cg = MdCGOS(root)
    # 造一个孤儿索引条目 → heal 必有动作 → `_sustain.jsonl` 必落一行（读面非空）。
    cg.index["nodes"]["ghost_hb"] = {"path": "knowledge/nope/ghost_hb.md"}
    lp = S.SustainLoop(cg, name="h1", d=netdir, beat_interval=3600.0,
                       heal_interval=3600.0, scrub_interval=3600.0,
                       evolve_interval=3600.0, tidy_interval=3600.0,
                       auto_heal=True, auto_scrub=False, auto_evolve=False,
                       auto_tidy=False)
    recs = [lp.beat(), lp.beat(True), lp.beat(False)]
    with open(S.stamp_path("h1", netdir), encoding="utf-8") as f:
        stamp = json.load(f)
    judges = [S.judge(a, interval=600.0, task_running=tr)
              for a in (None, 0.0, 1500.0, 2100.0, 2600.0, 99999.0)
              for tr in (False, True)]
    hr = S.heal(cg)
    dg = S.diagnose(cg)
    sust = list(read_jsonl(os.path.join(root, S.SUSTAIN_LOG)))
    return {"recs": recs, "stamp": stamp, "judges": judges, "heal": hr,
            "diag": dg, "sustain": sust,
            "sustain_exists": os.path.exists(os.path.join(root, S.SUSTAIN_LOG)),
            "ledger_exists": os.path.exists(S.heartbeat_path(root)),
            "ledger_n": len(list(read_jsonl(S.heartbeat_path(root))))}


def l1():
    print("== L1 零判定变更（硬门）——台账开/关读面逐位一致 ==")
    S = globals()["sustain"]
    r_off = _fresh_root("l1_off")
    os.environ["MDCG_HEARTBEAT_LEDGER"] = "0"
    off = _l1_scenario(r_off, _netdir("l1_off"))
    r_on = _fresh_root("l1_on")
    os.environ.pop("MDCG_HEARTBEAT_LEDGER", None)          # 缺省＝开
    on = _l1_scenario(r_on, _netdir("l1_on"))

    ok(off["ledger_exists"] is False and off["ledger_n"] == 0,
       "L1 前置：台账关时不写盘（无 _heartbeat.jsonl）")
    ok(on["ledger_exists"] is True and on["ledger_n"] == 3,
       "L1a 台账开时恰 3 条周期行（三次 beat）",
       (on["ledger_exists"], on["ledger_n"]))

    ok(_canon(off["recs"], r_off) == _canon(on["recs"], r_on)
       and [set(r) for r in off["recs"]] == [set(r) for r in on["recs"]],
       "L1b beat() 返回逐位一致（键集 + 值）——台账不改返回")
    ok(_canon(off["stamp"], r_off) == _canon(on["stamp"], r_on)
       and set(off["stamp"]) == set(on["stamp"]),
       "L1c 心跳戳字段逐位一致（含进度三字段）")
    ok(off["judges"] == on["judges"] and off["judges"],
       "L1d judge() 返回逐位一致（12 组年龄×任务态）", off["judges"][:2])
    ok(_canon(off["heal"], r_off) == _canon(on["heal"], r_on),
       "L1e heal() 返回逐位一致（含 before/after 统计）")
    ok(bool(off["heal"]["actions"]) and bool(on["heal"]["actions"]),
       "L1e' 前置：heal 确有动作（读面非空，比对有意义）",
       [a.get("code") for a in off["heal"]["actions"]])
    ok(_canon(off["diag"], r_off) == _canon(on["diag"], r_on),
       "L1f diagnose() 返回逐位一致（含 issues/stats）")
    ok(off["sustain_exists"] and on["sustain_exists"]
       and _canon(off["sustain"], r_off) == _canon(on["sustain"], r_on)
       and off["sustain"],
       "L1g _sustain.jsonl 既有记录逐位一致（台账不污染既有台账）",
       len(off["sustain"]))


# ---------------------------------------------------------------- L2 append-only
def l2():
    print("== L2 append-only —— 只追加，历史行不被改写 ==")
    S = globals()["sustain"]
    root = _fresh_root("l2")
    os.environ.pop("MDCG_HEARTBEAT_LEDGER", None)
    saved = S.HEARTBEAT_ROTATE_BYTES
    S.HEARTBEAT_ROTATE_BYTES = 1 << 30                     # 本轮不轮转，纯 append
    try:
        for i in range(5):
            S.record_heartbeat(root, "hb2", t=100.0 + i)
        raw1 = open(S.heartbeat_path(root), "rb").read()
        for i in range(5):
            S.record_heartbeat(root, "hb2", t=200.0 + i)
        raw2 = open(S.heartbeat_path(root), "rb").read()

        ok(raw1 and raw2.startswith(raw1),
           "L2 旧字节是新内容的前缀（历史行未被改写/截断）")
        lines = [l for l in raw2.split(b"\n") if l.strip()]
        ok(len(lines) == 10, "L2a 行数==写入次数（10）", len(lines))
        recs = [json.loads(l) for l in lines]
        ok([r["t"] for r in recs]
           == [100.0 + i for i in range(5)] + [200.0 + i for i in range(5)],
           "L2b 记录顺序==写入顺序（追加不重排）")
        ok(all(r.get("kind") == "beat" and "pid" in r and "name" in r
               and r.get("ok") is True for r in recs),
           "L2c 字段齐备（t/name/pid/ok/kind）")
    finally:
        S.HEARTBEAT_ROTATE_BYTES = saved


# ---------------------------------------------------------------- L3 断点可检出
def l3():
    print("== L3 断点可检出 —— 人为断档 → 报断点且最长区间缩短 ==")
    S = globals()["sustain"]
    os.environ.pop("MDCG_HEARTBEAT_LEDGER", None)
    saved = S.HEARTBEAT_ROTATE_BYTES
    S.HEARTBEAT_ROTATE_BYTES = 1 << 30
    try:
        r_move = _fresh_root("l3_move")
        for t in (0.0, 10.0, 20.0, 30.0, 40.0):            # 全连续
            S.record_heartbeat(r_move, "hb3", t=t)
        r_break = _fresh_root("l3_break")
        for t in (0.0, 10.0, 20.0, 30.0, 1000.0, 1010.0, 1020.0):   # 30→1000 断档
            S.record_heartbeat(r_break, "hb3", t=t)

        a = S.heartbeat_ledger_stats(r_move, name="hb3", threshold_s=15.0)
        b = S.heartbeat_ledger_stats(r_break, name="hb3", threshold_s=15.0)
        ok(a["breaks"] == 0 and a["longest_s"] == 40.0,
           "L3 连续序列：零断点、最长 40s", (a["breaks"], a["longest_s"]))
        ok(b["breaks"] == 1 and b["segments"] == 2,
           "L3a 注入断档后**报出断点**（breaks=1、segments=2）",
           (b["breaks"], b["segments"]))
        ok(b["longest_s"] == 30.0 and b["longest_s"] < a["longest_s"],
           "L3b 最长连续区间**缩短**（40s → 30s）",
           (a["longest_s"], b["longest_s"]))
        ok(b["breaks_top"] and b["breaks_top"][0]["gap_s"] == 970.0,
           "L3c 断点间隔可读数（30→1000＝970s）", b["breaks_top"])
        ok(b["last_iso"] is not None and b["last_age_s"] is not None,
           "L3d 最近一次周期时刻可读（last_iso / last_age_s）")

        r_one = _fresh_root("l3_one")
        S.record_heartbeat(r_one, "hb3", t=5.0)
        c = S.heartbeat_ledger_stats(r_one, name="hb3", threshold_s=15.0)
        ok(c["n"] == 1 and c["breaks"] == 0 and c["longest_s"] == 0.0
           and c["segments"] == 1,
           "L3e 单条记录：零断点、最长 0s、一段")
        d = S.heartbeat_ledger_stats(_fresh_root("l3_none"), name="hb3")
        ok(d["absent"] is True and d["n"] == 0 and d["longest_s"] is None,
           "L3f 无记录：absent=True（诚实不编数）")
    finally:
        S.HEARTBEAT_ROTATE_BYTES = saved


# ---------------------------------------------------------------- L4 有界
def l4():
    print("== L4 有界（硬门）——分片轮转 + 保留片数上限 ==")
    S = globals()["sustain"]
    os.environ.pop("MDCG_HEARTBEAT_LEDGER", None)
    rot, keep, probe = (S.HEARTBEAT_ROTATE_BYTES, S.HEARTBEAT_KEEP_SHARDS,
                        S.HEARTBEAT_PROBE_EVERY)
    S.HEARTBEAT_ROTATE_BYTES = 256
    S.HEARTBEAT_KEEP_SHARDS = 2
    S.HEARTBEAT_PROBE_EVERY = 1
    try:
        root = _fresh_root("l4")
        pad = {"pad": "z" * 80}
        for i in range(120):
            S.record_heartbeat(root, "hb4", t=float(i), extra=pad)
        shards = S._hb_shards(root)
        ok(len(shards) == 2, "L4 分片数受 KEEP=2 约束（实际 %d）" % len(shards),
           shards)
        ok(len(shards) <= S.HEARTBEAT_KEEP_SHARDS,
           "L4a 保留片数不超上限（淘汰在跑）")
        act = os.path.getsize(S.heartbeat_path(root))
        arc = S.heartbeat_archive_dir(root)
        sh_bytes = sum(os.path.getsize(os.path.join(arc, n)) for n in shards)
        slack = 512
        ok(act <= 256 + slack,
           "L4b 活动台账有界：%.0f ≤ 阈值 256 + 单条余量" % act, act)
        ok(all(os.path.getsize(os.path.join(arc, n)) <= 256 + slack
               for n in shards),
           "L4c 每个分片有界（≤ 阈值 + 单条余量）")
        ok(act + sh_bytes <= (2 + 1) * 256 + slack,
           "L4d 总字节有界：%d ≤ (keep+1)×阈值 + 余量" % (act + sh_bytes),
           act + sh_bytes)

        rows = [json.loads(l) for l in
                open(S.heartbeat_path(root), encoding="utf-8") if l.strip()]
        marks = [r for r in rows
                 if r.get("kind") == "rotate" and r.get("pruned")]
        ok(bool(marks) and len(marks[0]["pruned"]) >= 1,
           "L4e 淘汰**非静默**：pruned 名单写进轮转自述行（%s）"
           % (marks[0]["pruned"] if marks else "无"))
        idx = S._hb_load_index(root)
        ok(all(n in idx for n in shards) and all(n in shards for n in idx),
           "L4f 索引与磁盘分片对齐（淘汰即摘索引，不留悬空项）")

        # 显式退回无上界开关：阈值 0 → 不切分（应急/对照）
        r0 = _fresh_root("l4_off")
        S.HEARTBEAT_ROTATE_BYTES = 0
        for i in range(40):
            S.record_heartbeat(r0, "hb4", t=float(i), extra=pad)
        ok(not S._hb_shards(r0)
           and os.path.getsize(S.heartbeat_path(r0)) > 0,
           "L4g HEARTBEAT_ROTATE_BYTES=0 → 不切分（显式退回无上界形态）")

        # 归档目录不在 LAYERS（检索面零污染）
        from .mdcg import LAYERS
        ok(S.HEARTBEAT_ARCHIVE not in LAYERS,
           "L4h 归档目录不在 LAYERS → 分片不参与节点索引")
    finally:
        S.HEARTBEAT_ROTATE_BYTES, S.HEARTBEAT_KEEP_SHARDS, S.HEARTBEAT_PROBE_EVERY \
            = rot, keep, probe


_GROUPS = (g0, l1, l2, l3, l4)


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, kind, rel, old, new, 预期红项数下限, 预期命中的红项子串)。
#   kind="mod"：改**可执行实现**（exec 成模块并换进 sys.modules，供 `from .` 面读到）
_MUTATIONS = (
    ("M1 台账写入退化为覆盖式（非 append）", "mod", "md_cg/sustain.py",
     "        append_jsonl(heartbeat_path(root), row)\n",
     '        open(heartbeat_path(root), "w", encoding="utf-8").write('
     'json.dumps(row, ensure_ascii=False) + "\\n")\n',
     1, "L2"),
    ("M2 断点不可检出（阈值设为不可达）", "mod", "md_cg/sustain.py",
     "        if t - prev > threshold_s:",
     "        if t - prev > 1e300:",
     1, "L3"),
    ("M3 关闭轮转（有界性消失）", "mod", "md_cg/sustain.py",
     "    limit = HEARTBEAT_ROTATE_BYTES\n    if limit <= 0:\n        return",
     "    limit = HEARTBEAT_ROTATE_BYTES\n    if limit <= 0 or True:\n        return",
     1, "L4"),
    ("M4 关闭淘汰（分片无上界增长）", "mod", "md_cg/sustain.py",
     "    keep = HEARTBEAT_KEEP_SHARDS\n    if keep <= 0:\n        return []",
     "    keep = HEARTBEAT_KEEP_SHARDS\n    if keep <= 0 or True:\n        return []",
     1, "L4"),
    ("M5 台账污染既有 _sustain.jsonl（判定变更）", "mod", "md_cg/sustain.py",
     "        append_jsonl(heartbeat_path(root), row)\n",
     "        append_jsonl(heartbeat_path(root), row)\n"
     "        append_jsonl(os.path.join(root, SUSTAIN_LOG),"
     ' {"t": row["t"], "op": "hb_probe"})\n',
     1, "L1"),
)


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                           # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-800:])
    for mod in (globals().get("sustain"), _REAL):
        try:
            mod.stop_all()
        except Exception:                                  # noqa: BLE001
            pass
    return len(_FAIL)


def _exec_module(name, rel, text):
    """把变异源码 exec 进**模块自身的 __dict__**——使函数的 __globals__ 就是
    该模块 dict，从而 l2/l3/l4 的常量补丁（如 HEARTBEAT_ROTATE_BYTES）对变异
    模块同样生效（否则补丁落到副本、函数仍读旧值，会假红 L4）。"""
    m = types.ModuleType(name)
    m.__file__ = os.path.join(_repo_root(), rel)
    m.__package__ = "md_cg"
    exec(compile(text, rel, "exec"), m.__dict__)           # noqa: S102 —— 基线自证
    return m


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条注入退化，套件必须转红且打中预期判据\n")
    if list_only:
        for name, kind, rel, _o, _n, exp, label in _MUTATIONS:
            print("  %-44s [%s] expect_red>=%d  hit~%s  (%s)"
                  % (name, kind, exp, label, rel))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, kind, rel, old, new, expect, label in _MUTATIONS:
        src = _rel_text(rel)
        if old not in src:
            print("  ANCHOR-MISS %s —— 锚点在 %s 找不到（实现改了却没同步本表）"
                  % (name, rel))
            anchor_miss.append(name)
            continue
        _SRC[rel] = src.replace(old, new, 1)
        live = None
        try:
            if kind == "mod":
                live = sys.modules["md_cg.sustain"]
                mut = _exec_module("md_cg._hb_mut", rel, _SRC[rel])
                sys.modules["md_cg.sustain"] = mut
                globals()["sustain"] = mut
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            if live is not None:
                sys.modules["md_cg.sustain"] = live
                globals()["sustain"] = _REAL
            _SRC.pop(rel, None)
        red_lines = [l.strip() for l in detail.splitlines()
                     if l.strip().startswith("FAIL ")]
        hit = any(label in l for l in red_lines)
        mark = "OK  " if (reds >= expect and hit) else "MISMATCH"
        print("  %s %-44s 红项=%d 预期>=%d 命中%s=%s"
              % (mark, name, reds, expect, label, "是" if hit else "**否**"))
        for l in red_lines[:4]:
            print("        " + l[5:])
        if reds < expect or not hit:
            bad.append("%s（红=%d 预期>=%d，命中%s=%s）"
                       % (name, reds, expect, label, hit))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都被打红）" if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    _sandbox_env()
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        n = _run_groups()
        print("\n心跳台账守卫：%d 通过，%d 失败" % (len(_PASS), n))
        return 0 if not n else 1
    finally:
        try:
            _REAL.stop_all()
        except Exception:                                  # noqa: BLE001
            pass
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
