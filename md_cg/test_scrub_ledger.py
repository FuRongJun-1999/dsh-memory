# -*- coding: utf-8 -*-
"""issue #66 守卫：去污染账本口径（幂等账本 vs 覆盖账）。

断言面：
  S1 覆盖账可区分：造「同一批旧面孔多轮」与「每轮全新问题」两场景，
     断言两者在账本读数上**可区分**（issue 的核心诉求）；含 dry_run 轮的
     sweep 记录（常驻默认下唯一的账）。
  S2 `_handled` 语义不动：仍只由「改过」的单条记录（op=="decontaminate"
     且 ok）构成——未被「检查过」（hint / 保护跳过 / 批量汇总）污染。
  S3 处置行为不变：同一输入下「谁被改／谁被跳过／原因」逐位一致——
     黄金序列取自**修前基线**（.tmp/issue66_baseline.py，改码前实测）。
  S4 兼容键：`skipped_done` 仍在，且 == `already_handled`（返回体 + 批量
     记录）；源码里 `skipped_done` 旁有语义正名说明（防再误读）。
  S5 抽样轮转：常驻路径连续两轮取到**不同** seed（抽样面轮转）；库层
     `sample()` 缺省调用仍**可复现**（seed=0 不变）。
  S6 summary 双口径：累计 applied 之和与原口径（单条记录条数）各自正确、
     另留 `batches`（批量轮数）。

运行：
  python -m md_cg.test_scrub_ledger                # 全绿基线
  python -m md_cg.test_scrub_ledger --mutate M1    # 定点变异自证（预期恰 S1 红）

变异自证：把生产源码文本注入退化（唯一替换，非唯一即报错拒绝），以
`__package__="md_cg"` 的模块对象 exec 执行——相对导入仍解析到真包——
再对**同一断言集**运行：要求「恰好打中预期红项组」（无连带、无漏网）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import types

from . import scrub as _scrub
from . import sustain as _sustain
from .fsutil import append_jsonl
from .mdcg import MdCG

PASS = FAIL = 0
FAILS = []

# S3 黄金动作序列（修前基线逐位实测，见模块 docstring）
GS = [("exp1", "expired", "applied"), ("ny1", "not_yet", "hint"),
      ("dup1", "duplicate", "hint"), ("prot1", "expired", "skip_protected"),
      ("done1", "expired", "skip")]
IDS_A = ["e1", "e2", "e3", "d1"]


def ok(cond, group, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append((group, label))
        print(f"  FAIL [{group}] {label}")


# --------------------------------------------------------------------------
# 场景工具
# --------------------------------------------------------------------------

def _mk_root(tmp, name):
    root = os.path.join(tmp, name)
    os.makedirs(root, exist_ok=True)
    return root


def _mk_expired(cg, nid, **kw):
    cg.add(nid, f"# 功能名：{nid}\n\n这条已过期", valid_until="2020-01-01",
           **kw)


def _mk_dup_pair(cg, a, b, text):
    cg.add(a, f"# 功能名：{a}\n\n{text}")
    cg.add(b, f"# 功能名：{b}\n\n{text}")


def _recs(cg, sc):
    p = os.path.join(cg.root, sc.SCRUB_LOG)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _batches(cg, sc):
    return [r for r in _recs(cg, sc) if r.get("op") == "decontaminate_batch"]


def _sweeps(cg, sc):
    return [r for r in _recs(cg, sc) if r.get("op") == "sweep"]


def _fm(cg, nid):
    f = cg.get(nid)["frontmatter"]
    return {"confidence": f.get("confidence"), "layer": f.get("layer"),
            "negative_evidence": f.get("negative_evidence")}


# --------------------------------------------------------------------------
# S1 覆盖账可区分
# --------------------------------------------------------------------------

def s1_ledger(sc, tmp):
    # A：同一批旧面孔多轮（3 expired 处置后每轮名单命中 + 1 duplicate hint）
    cga = MdCG(_mk_root(tmp, "s1a"))
    for i in range(1, 4):
        _mk_expired(cga, f"e{i}")
    _mk_dup_pair(cga, "d1", "d2", "重复内容主体：超时参数是 30 秒")
    for _ in range(3):
        sc.decontaminate(cga, IDS_A, dry_run=False)
    ba = _batches(cga, sc)
    cb_a = (ba[1].get("checked_breakdown") if len(ba) > 1 else None) or {}
    ok(cb_a.get("already_handled") == 3 and cb_a.get("applied") == 0, "S1",
       f"旧面孔轮：checked_breakdown={{already_handled:3, applied:0}} 实得 {cb_a}")

    # B：每轮全新问题（每轮 4 个全新 duplicate，全 hint）
    cgb = MdCG(_mk_root(tmp, "s1b"))
    for rnd in range(1, 4):
        ids = [f"n{rnd}_{i}" for i in range(1, 5)]
        _mk_dup_pair(cgb, ids[0], ids[1], f"轮{rnd}甲重复主体：参数 A")
        _mk_dup_pair(cgb, ids[2], ids[3], f"轮{rnd}乙重复主体：参数 B")
        sc.decontaminate(cgb, ids, dry_run=False)
    bb = _batches(cgb, sc)
    cb_b = (bb[0].get("checked_breakdown") if bb else None) or {}
    ok(cb_b.get("already_handled") == 0 and cb_b.get("hint") == 4, "S1",
       f"全新问题轮：checked_breakdown={{already_handled:0, hint:4}} 实得 {cb_b}")

    # 核心诉求：两场景在账本读数上可区分（修前 last_sweep 口径 {n_issues,
    # n_high_medium, applied} 两场景相同——覆盖账即为此而设）
    ok(bool(cb_a) and cb_a != cb_b, "S1",
       f"两场景账本读数可区分：旧面孔={cb_a} vs 全新={cb_b}")

    # dry_run 轮（常驻默认）也有覆盖账：批量记录不写，sweep 记录是唯一账
    cgc = MdCG(_mk_root(tmp, "s1c"))
    _mk_expired(cgc, "x1")
    _mk_expired(cgc, "x2")
    _mk_dup_pair(cgc, "p1", "p2", "重复内容主体：参数 Y")
    sw = sc.sweep(cgc, n=3, seed=11, dry_run=True)
    dec = sw["decontaminate"]
    n_planned = sum(1 for a in dec["actions"] if a["action"] == "planned")
    ok(dec["planned_dry_run"] == n_planned and n_planned >= 1, "S1",
       f"dry_run 轮：planned_dry_run == planned 数（实得 {dec['planned_dry_run']}"
       f"/{n_planned}）")
    sws = _sweeps(cgc, sc)
    srec = sws[-1] if sws else {}
    ok(isinstance(srec.get("checked_breakdown"), dict)
       and srec["checked_breakdown"].get("planned_dry_run")
       == dec["planned_dry_run"], "S1",
       "dry_run 轮 sweep 记录带覆盖账（last_sweep 可区分旧面孔/新检查）")


# --------------------------------------------------------------------------
# S2 `_handled` 语义不动
# --------------------------------------------------------------------------

def s2_handled(sc, tmp):
    cg = MdCG(_mk_root(tmp, "s2"))
    _mk_expired(cg, "e1")
    _mk_expired(cg, "e2")
    _mk_dup_pair(cg, "d1", "d2", "重复内容主体：参数 Z")
    cg.add("prot1", "# 功能名：重要过期\n\n重要但过期", importance=0.9,
           valid_until="2020-01-01")
    sc.decontaminate(cg, ["e1", "e2", "d1", "prot1"], dry_run=False)
    handled = sc._handled(cg)
    ok(handled == {("e1", "expired"), ("e2", "expired")}, "S2",
       f"_handled 只含「改过」的记录：{sorted(map(str, handled))}")
    ok(all(isinstance(x[0], str) and isinstance(x[1], str) for x in handled),
       "S2", "_handled 元素均为 (node_id, kind) 实名对（无「检查过」混入）")
    ok(("d1", "duplicate") not in handled
       and ("prot1", "expired") not in handled, "S2",
       "hint / 保护跳过 不进 _handled（幂等账本认「改过」，不认「查过」）")


# --------------------------------------------------------------------------
# S3 处置行为不变（黄金序列）
# --------------------------------------------------------------------------

def s3_behavior(sc, tmp):
    cg = MdCG(_mk_root(tmp, "s3"))
    _mk_expired(cg, "exp1")
    cg.add("ny1", "# 功能名：未生效\n\n未来才生效", valid_from="2030-01-01")
    _mk_dup_pair(cg, "dup1", "dup2", "重复内容主体：超时参数是 30 秒")
    cg.add("prot1", "# 功能名：重要过期\n\n重要节点但过期", importance=0.9,
           valid_until="2020-01-01")
    _mk_expired(cg, "done1")
    sc.decontaminate(cg, ["done1"], dry_run=False, min_severity="info")
    before = {n: _fm(cg, n) for n in ("exp1", "ny1", "dup1", "prot1",
                                      "done1")}
    ret = sc.decontaminate(cg, ["exp1", "ny1", "dup1", "prot1", "done1"],
                           dry_run=False, min_severity="info")
    got = [(a["node_id"], a["kind"], a["action"]) for a in ret["actions"]]
    ok(got == GS, "S3", f"动作序列逐位一致（谁被改/谁被跳过/原因）：{got}")
    after = {n: _fm(cg, n) for n in before}
    ok(after["exp1"] == {"confidence": 0.45, "layer": "contextual",
                         "negative_evidence": 1}, "S3",
       f"被改的、改到位（exp1 weaken+demote）：{after['exp1']}")
    ok(all(after[n] == before[n] for n in ("ny1", "dup1", "prot1", "done1")),
       "S3", "被跳过/建议的（ny1/dup1/prot1/done1）逐位未动")


# --------------------------------------------------------------------------
# S4 兼容键
# --------------------------------------------------------------------------

def s4_compat(sc, tmp):
    cg = MdCG(_mk_root(tmp, "s4"))
    for i in range(1, 4):
        _mk_expired(cg, f"e{i}")
    _mk_dup_pair(cg, "d1", "d2", "重复内容主体：超时参数是 30 秒")
    sc.decontaminate(cg, IDS_A, dry_run=False)
    ret = sc.decontaminate(cg, IDS_A, dry_run=False)
    ok("skipped_done" in ret
       and ret["skipped_done"] == ret["already_handled"] == 3, "S4",
       "返回体：skipped_done 仍在且 == already_handled（=3）")
    bt = _batches(cg, sc)[-1]
    ok("skipped_done" in bt
       and bt["skipped_done"] == bt["already_handled"] == 3, "S4",
       "批量记录：skipped_done == already_handled（=3）")
    src = open(sc.__file__, encoding="utf-8").read()
    ok("skipped_done" in src and ("正名" in src or "实际含义" in src), "S4",
       "源码里 skipped_done 旁有语义正名说明（防再误读成「检查并跳过」）")


# --------------------------------------------------------------------------
# S5 抽样轮转
# --------------------------------------------------------------------------

def s5_rotation(sc, su, tmp):
    cg = MdCG(_mk_root(tmp, "s5"))
    for i in range(6):
        cg.add(f"k{i}", f"# 功能名：节点{i}\n\n内容 {i}")
    # 库层缺省可复现（显式调用口径不破）
    s1 = sc.sample(cg, 4)
    s2 = sc.sample(cg, 4)
    ok(s1["seed"] == 0
       and [x["node_id"] for x in s1["sample"]]
       == [x["node_id"] for x in s2["sample"]], "S5",
       "库层缺省 sample 仍可复现（seed=0 不变）")
    # 常驻路径：连续两轮 seed 不同（抽样面轮转）
    net = _mk_root(tmp, "s5net")
    lp = su.SustainLoop(cg, "i66loop", beat_interval=30.0, heal_interval=30.0,
                        scrub_interval=30.0, auto_scrub=False, d=net)
    try:
        lp._tick_scrub()
        seed1 = (lp.last_scrub or {}).get("seed")
        lp._tick_scrub()
        seed2 = (lp.last_scrub or {}).get("seed")
        ok(seed1 is not None and seed2 is not None and seed1 != seed2, "S5",
           f"常驻两轮 seed 不同：{seed1} vs {seed2}（抽样面轮转）")
        ok(lp.scrub_round == 2, "S5",
           f"轮次计数自增（seed 轮次分量可审计）：scrub_round={lp.scrub_round}")
    finally:
        lp.stop()


# --------------------------------------------------------------------------
# S6 summary 双口径
# --------------------------------------------------------------------------

def s6_summary(sc, tmp):
    cg = MdCG(_mk_root(tmp, "s6"))
    for i in range(3):
        _mk_expired(cg, f"x{i}")
    sc.decontaminate(cg, ["x0", "x1", "x2"], dry_run=False)   # applied=3
    sc.decontaminate(cg, ["x0", "x1", "x2"], dry_run=False)   # applied=0
    # 注入一条轮级记录：模拟「单条记录写失败但轮账在」的分歧面——两个口径
    # 必须能各自正确（不得互相覆盖）。
    append_jsonl(os.path.join(cg.root, sc.SCRUB_LOG),
                 {"op": "decontaminate_batch", "ok": True, "applied": 5,
                  "t": time.time()})
    sm = sc.summary(cg)
    ok(sm["decontaminated"] == 8, "S6",
       f"decontaminated = 累计 applied 之和（3+0+5）：{sm['decontaminated']}")
    ok(sm["decontaminated_records"] == 3, "S6",
       f"原口径（单条记录条数）另留：{sm['decontaminated_records']}")
    ok(sm["batches"] == 3, "S6", f"批量轮数另留：{sm['batches']}")


# --------------------------------------------------------------------------
# 运行全部断言
# --------------------------------------------------------------------------

def run_all(sc, su):
    global PASS, FAIL, FAILS
    PASS = FAIL = 0
    FAILS = []
    tmp = tempfile.mkdtemp(prefix="mdcg_i66g_")
    try:
        s1_ledger(sc, tmp)
        s2_handled(sc, tmp)
        s3_behavior(sc, tmp)
        s4_compat(sc, tmp)
        s5_rotation(sc, su, tmp)
        s6_summary(sc, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return PASS, FAIL, list(FAILS)


# --------------------------------------------------------------------------
# 定点变异自证
# --------------------------------------------------------------------------

def _mutations():
    here = os.path.dirname(os.path.abspath(__file__))
    scrub_p = os.path.join(here, "scrub.py")
    sustain_p = os.path.join(here, "sustain.py")
    return {
        "M1": (scrub_p,
               '''    breakdown = {"applied": n_applied, "already_handled": n_done,
                 "planned_dry_run": n_planned, "protected": n_prot,
                 "hint": n_hint}''',
               '''    breakdown = {}''',
               {"S1"}, "覆盖账退化：分类明细置空（回退「账上不可区分」）"),
        "M2": (scrub_p,
               '''        if rec.get("op") == "decontaminate" and rec.get("ok"):''',
               '''        if rec.get("op") in ("decontaminate",
                                     "decontaminate_batch") and rec.get("ok"):''',
               {"S2"}, "把批量记录也读进 `_handled`（「检查过并进名单」——裁定禁止）"),
        "M3": (scrub_p,
               '''        if kind in ("duplicate", "unverified") or _declared == ("hint",):''',
               '''        if kind in ("duplicate", "unverified"):''',
               {"S3"}, "声明判定被绕过：not_yet 落 weaken（历史 bug 重演）"),
        "M4": (scrub_p,
               '''            "already_handled": n_done, "skipped_done": n_done,''',
               '''            "already_handled": n_done, "skipped_done": n_done + 1,''',
               {"S4"}, "兼容键失真：skipped_done 不再等于 already_handled"),
        "M5": (sustain_p,
               '''        seed = f"sustain:{self.scrub_round}"''',
               '''        seed = None''',
               {"S5"}, "抽样面冻结回退：常驻路径不再派生轮次 seed"),
        "M6": (scrub_p,
               '''            "decontaminated": sum(int(r.get("applied") or 0) for r in batches),''',
               '''            "decontaminated": len(decs),''',
               {"S6"}, "summary 口径回退：decontaminated 数单条记录"),
        "M7": (scrub_p,
               '''            n_planned += 1\n''',
               '''''',
               {"S1"}, "planned 不计数：planned_dry_run 与 actions 对不上"),
        "M8": (scrub_p,
               '''             skipped_protected=n_prot, skipped_done=n_done, hints=n_hint,''',
               '''             skipped_protected=n_prot, skipped_done=n_done + 1,
             hints=n_hint,''',
               {"S4"}, "批量记录兼容键失真：skipped_done ≠ already_handled"),
        "M9": (scrub_p,
               '''    seed = 0 if seed is None else seed''',
               '''    seed = time.time_ns() if seed is None else seed''',
               {"S5"}, "库层缺省 seed 漂移：显式调用可复现性被破"),
    }


def _load_mutated(path, old, new, name):
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
        mod = _load_mutated(path, old, new,
                            f"md_cg.{os.path.basename(path)[:-3]}_mut")
        if path.endswith(os.sep + "scrub.py"):
            sc = mod
        else:
            su = mod
        print(f"== 定点变异 {mutate}：{why} ==")
    passed, failed, fails = run_all(sc, su)
    if expect is None:
        print(f"\nscrub_ledger: {passed} passed, {failed} failed")
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
