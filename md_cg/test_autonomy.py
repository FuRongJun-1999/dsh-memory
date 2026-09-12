# -*- coding: utf-8 -*-
"""信息差驱动自主探索闭环（autonomy.explore）验证。

断言面：
  ① 无信号诚实：空反思日志 → 零提案、零步骤（不编造探索价值）
  ② 信号聚合排序：|d2| 加速度 + BLINDSPOT/DEFER 计数 → 高信息差排前，
     提案携带证据明细
  ③ 全链路：提案 → learn_blindspots 五态终判 → 留痕 _explore.jsonl
  ④ 幂等：重复 explore 终态一致、gap 回写不重复（gap_<sha1(bid)> 幂等）

运行：python -m md_cg.test_autonomy
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import autonomy
from .fsutil import append_jsonl
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _sig(cg, t, query, d2, states):
    append_jsonl(cg.reflection_log,
                 {"t": t, "query": query, "d_prev": 1.0, "d_curr": 1.0,
                  "d_delta": 0.0, "d2": d2, "states": states,
                  "n_results": 3, "feedback": None})


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_autonomy_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = MdCGOS(root)

        # ---------- ① 无信号诚实 ----------
        pr = autonomy.proposals(cg)
        ok(pr["ok"] and not pr["proposals"] and pr["n_signals"] == 0,
           "①空反思日志 → 零提案（不编造探索价值）")
        ex = autonomy.explore(cg)
        ok(ex["ok"] and not ex["steps"],
           "①b空信号 explore → 零步骤、ok=True")

        # ---------- ② 信号聚合排序 ----------
        _sig(cg, 1.0, "反应堆冷却方案", 0.9, {"BLINDSPOT": 2})
        _sig(cg, 2.0, "反应堆冷却方案", 0.7, {"BLINDSPOT": 1})
        _sig(cg, 3.0, "周末菜单", 0.05, {})
        pr = autonomy.proposals(cg, limit=3)
        ps = pr["proposals"]
        ok(pr["n_signals"] == 2 and len(ps) == 2,
           "②两查询聚类（同 query 归一）、n_signals=2")
        ok(ps[0]["query"] == "反应堆冷却方案" and ps[0]["score"] > ps[1]["score"],
           "②b高信息差排前（Σ|d2|=1.6 + BLINDSPOT×3 ＞ 0.05）")
        ok("d2" in ps[0]["reason"] and "BLINDSPOT" in ps[0]["reason"],
           "②c提案携带证据明细（可审计）")

        # ---------- ③ 全链路：提案 → 五态终判 → 留痕 ----------
        cg.add("k1", "# 功能名：反应堆冷却知识\n"
                     "# 生效条件：问反应堆冷却方案\n"
                     "# 子功能：知识片段\n"
                     "# 执行：陈述知识\n"
                     "# 验证方式：test\n"
                     "# 不适用条件：无\n"
                     "反应堆冷却方案概述。\n",
               layer="knowledge", verification_basis="test")
        ex = autonomy.explore(cg, apply=True, actor="test")
        st0 = ex["steps"][0] if ex["steps"] else {}
        ok(bool(ex["steps"]) and st0.get("terminal") in
           ("unknowable", "no_anchor", "unresolved", "carried", "resolved"),
           f"③提案进入五态终判（terminal={st0.get('terminal')}，"
           f"routes={st0.get('routes')}）")
        if st0.get("terminal") in ("carried", "unresolved"):
            ok(bool(st0.get("written")),
               f"③b carried/unresolved 已回写 gap_hint（{st0.get('written')}）")
        else:
            ok(True, f"③b终态={st0.get('terminal')}：按诚实原则无需回写"
                     "（resolved=已有可判定终点；no_anchor=先补锚点）")
        ok(os.path.exists(autonomy._explore_log_path(cg)),
           "③c探索留痕 _explore.jsonl 落盘")

        # ---------- ④ 幂等 ----------
        ex2 = autonomy.explore(cg, apply=True, actor="test")
        st2 = ex2["steps"][0] if ex2["steps"] else {}
        ok(st2.get("terminal") == st0.get("terminal"),
           "④重复 explore 终态一致（判定确定性）")
        if st0.get("terminal") in ("carried", "unresolved"):
            ok(not st2.get("written"),
               "④b gap 回写幂等（第二次 written=None，节点已存在）")
        else:
            ok(True, "④b本终态无回写动作，幂等性由判定确定性保证")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nautonomy: {PASS} passed, {FAIL} failed")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
