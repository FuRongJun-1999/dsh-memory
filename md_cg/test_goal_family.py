# -*- coding: utf-8 -*-
"""P0 目标分族与退役：goal_gen 同族重报不再堆积 + 检索定向不吃维护快照目标。

功能名：test_goal_family —— P0 目标准确性守卫（隔离临时库，零外部依赖）。
生效条件：`PYTHONPATH=<root> python -m md_cg.test_goal_family`。
子功能：断言面——
  A1 同族（S3|contextual）两次不同读数 → 只留 1 条 active，旧的那条 dropped；
  A2 返回值带 retired / family（调用方能看到退役了谁）；
  A3 不同族（S3|knowledge）并存，互不退役；
  A4 同文本重复 apply 幂等（同 id，不自我退役）；
  B1 goal_text 不拼 goal-gen:S3 的目标（检索定向不被每日读数稀释）；
  B2 goal_text 仍拼非 S3 目标（排除是定向口径，不是丢目标）；
  B3 active_goals 缺省不过滤（goal list / info 计数读数不变）。
执行：`python -m md_cg.test_goal_family`。
验证方式：test。
不适用条件：活库（一切读写都在 tempfile.mkdtemp 内）。
"""
from __future__ import annotations

import shutil
import sys
import tempfile

from . import autonomy_modes, goal_gen
from .mdcos import MdCGOS

PASS = 0
FAIL = 0
FAILS = []


def _ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS", label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL", label)


def _cand(source, layer, text, prio=0.7):
    return {"source": source, "class": goal_gen.CLASS_MAINTAIN,
            "goal_text": text, "priority": prio, "conditions": "该层候补 >= 阈值时",
            "evidence": {"layer": layer, "no_basis": 1, "n": 1}}


def _apply(cg, cand):
    return goal_gen._apply_candidate(cg, cand)


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_goal_family_")
    real_decide = autonomy_modes.decide
    autonomy_modes.decide = lambda a: {"decision": "allow", "mode": "test"}
    try:
        cg = MdCGOS(tmp)
        print("[A1/A2] 同族两次读数 → 旧的退役")
        r1 = _apply(cg, _cand("S3", "contextual", "固化候补清账：contextual 层 100 个无验证基底节点"))
        r2 = _apply(cg, _cand("S3", "contextual", "固化候补清账：contextual 层 200 个无验证基底节点"))
        act = cg.list_goals(status="active")
        _ok(r1.get("moved_to") == "goals" and r2.get("moved_to") == "goals", "两次都落 goals")
        _ok(len(act) == 1, "active 只有 1 条（实际 %d）" % len(act))
        _ok(act[0]["id"] == r2["id"], "留下的是新的那条")
        _ok(r2.get("retired") == [r1["id"]], "retired 点名旧 id（%r）" % (r2.get("retired"),))
        _ok(r2.get("family") == "S3|contextual", "family 键 = S3|contextual")
        old = cg.get(r1["id"], probe=True) or {}
        _ok((old.get("frontmatter") or {}).get("goal_status") == "dropped", "旧目标 goal_status=dropped")

        print("[A3] 不同族并存")
        r3 = _apply(cg, _cand("S3", "knowledge", "固化候补清账：knowledge 层 12 个无验证基底节点"))
        act = cg.list_goals(status="active")
        _ok(len(act) == 2, "active 2 条（实际 %d）" % len(act))
        _ok(r3.get("retired") == [], "跨族不退役（%r）" % (r3.get("retired"),))

        print("[A4] 同文本幂等")
        r4 = _apply(cg, _cand("S3", "knowledge", "固化候补清账：knowledge 层 12 个无验证基底节点"))
        _ok(r4["id"] == r3["id"], "同文本同 id")
        _ok(r4.get("retired") == [], "不把自己退役")
        _ok(len(cg.list_goals(status="active")) == 2, "active 仍 2 条")

        print("[B1/B2] goal_text 排除 S3")
        g = _apply(cg, _cand("S1", "goals", "补条件消解高频盲区：记忆 检索 缺陷"))
        _ok(g.get("moved_to") == "goals", "S1 目标落库")
        txt = cg.goal_text()
        _ok("固化候补清账" not in txt, "goal_text 不含 S3 快照（%r）" % txt[:60])
        _ok("补条件消解高频盲区" in txt, "goal_text 含非 S3 目标")

        print("[B3] active_goals 缺省不过滤")
        _ok(len(cg.active_goals(limit=10)) == 3, "缺省 3 条（%d）" % len(cg.active_goals(limit=10)))
        _ok(len(cg.active_goals(limit=10, exclude_tags=("goal-gen:S3",))) == 1,
            "排除 S3 后 1 条")
    finally:
        autonomy_modes.decide = real_decide
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== test_goal_family: PASS %d / FAIL %d ===" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
