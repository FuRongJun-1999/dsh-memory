# -*- coding: utf-8 -*-
"""test_state_events · 状态事件账本（append-only）＋检验强度字段（check_strength）

多主体世界模型对齐 v0.1 §2（L0「事件必记账」/ L1「检验强度」）落地的行为守卫。

运行：python -m md_cg.test_state_events
"""
from __future__ import annotations

import json
import os
import tempfile

from . import state_events
from .mdcos import MdCGOS

_ok = 0
_fail = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[ok] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


def _dump(r):
    return json.dumps(r, sort_keys=True, ensure_ascii=False)


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_se_test_")
    cg = MdCGOS(os.path.join(tmp, "root"))

    # ---- 1. append 与读回（落盘序）----
    state_events.append(cg, "鲸娘", "住所", old="帐篷", new="海景别墅",
                        kind="migration", seq=553, evidence="用户侧 r0553")
    state_events.append(cg, "鲸娘", "房贷", old="有", new=None,
                        kind="retraction", seq=577, evidence="用户侧 r0577")
    state_events.append(cg, "鲸娘", "烤箱", old=None, new="已启用",
                        kind="enablement", seq=595, evidence="AI 侧 r0595")
    recs = state_events.read(cg)
    check("append 3 条 → read 回 3 条", len(recs) == 3, len(recs))
    check("落盘序保持（首条=迁移）", recs and recs[0]["kind"] == "migration",
          recs[0] if recs else None)
    check("五元在场", bool(recs) and all(
        k in recs[0] for k in ("subject", "slot", "old", "new", "seq", "evidence")),
        sorted(recs[0].keys()) if recs else None)

    # ---- 2. append-only 不覆盖（连写后旧记录逐条原样）----
    before = [_dump(r) for r in recs]
    state_events.append(cg, "鲸娘", "住所", old="海景别墅", new="海边小屋",
                        kind="migration", seq=700, evidence="r0700")
    after = state_events.read(cg)
    check("追加不覆盖（4 条）", len(after) == 4, len(after))
    check("旧 3 条逐条原样", [_dump(r) for r in after[:3]] == before)

    # ---- 3. 重启（新实例）读回 ----
    cg2 = MdCGOS(cg.root)
    check("新实例读回 4 条", len(state_events.read(cg2)) == 4)

    # ---- 4. 过滤与 limit ----
    check("按 slot 过滤", len(state_events.read(cg, slot="住所")) == 2)
    check("按 kind 过滤", len(state_events.read(cg, kind="retraction")) == 1)
    check("limit 取末 2 条", len(state_events.read(cg, limit=2)) == 2)
    check("limit 末条为最后写入", state_events.read(cg, limit=1)[0]["seq"] == 700)

    # ---- 5. 参数校验（fail-closed）----
    # 注：空 subject/空白 slot 两用例须带 new="v"——否则同时命中「old/new 同空」
    # 校验（2026-10-05 复核：无判别力断言，删目标校验后仍照绿）。
    # 独立库：拒绝用例若在某处校验被误删的变异态下真落盘，只污染本库，
    # 不波及第 6 段条数统计（编排侧变异自证：1 变异 → 1 红的干净定点）。
    bad_root = MdCGOS(os.path.join(tmp, "bad_root"))
    for bad, nm in [
        (dict(subject="", slot="x", new="v"), "空 subject 拒绝"),
        (dict(subject="x", slot=" ", new="v"), "空白 slot 拒绝"),
        (dict(subject="x", slot="y", old=None, new=None), "old/new 同空拒绝"),
    ]:
        try:
            state_events.append(bad_root, **bad)
            check(nm, False, "未抛 ValueError")
        except ValueError:
            check(nm, True)
    try:
        state_events.append(bad_root, "x", "y", new="v", kind="teleport")
        check("未知 kind 拒绝", False, "未抛 ValueError")
    except ValueError:
        check("未知 kind 拒绝", True)

    # ---- 6. 坏行容忍（跳过 + 记账 + 不中断 + 样本有界）----
    # 坏行数（12）须**越过** _BAD_ROW_SAMPLE_CAP（8）：只造 2 行时
    # `len(samples) <= cap` 是平凡真（空列表也满足），且删掉记录逻辑后
    # 仍全绿——无判别力（2026-10-05 复核 NEW-red 实证）。故断言取
    # **精确等式** `min(前值+12, cap)` 且要求 >0：既抓「不记录」也抓「无界」。
    p = state_events.ledger_path(cg)
    bad_lines = 12
    with open(p, "a", encoding="utf-8") as f:
        f.write("{broken json\n")
        f.write("[1, 2, 3]\n")
        for i in range(bad_lines - 2):
            f.write("not-json-%d\n" % i)
    n0 = state_events.BAD_ROWS
    s0 = len(state_events._BAD_ROW_SAMPLES)
    recs2 = state_events.read(cg)
    check("坏行跳过后好行全在", len(recs2) == 4, len(recs2))
    check("坏行记账（+%d）" % bad_lines, state_events.BAD_ROWS == n0 + bad_lines,
          state_events.BAD_ROWS - n0)
    _cap = state_events._BAD_ROW_SAMPLE_CAP
    _want = min(s0 + bad_lines, _cap)
    check("坏行样本有界（cap %d，期望 %d，实际 %d）"
          % (_cap, _want, len(state_events._BAD_ROW_SAMPLES)),
          len(state_events._BAD_ROW_SAMPLES) == _want
          and len(state_events._BAD_ROW_SAMPLES) > 0,
          len(state_events._BAD_ROW_SAMPLES))

    # ---- 7. check_strength 字段（缺省零迁移 / 非法拒绝）----
    cg.add("cs_a", "# 功能名：断言甲\n# 生效条件：测\n", layer="knowledge",
           verification_basis="test", check_strength="hoop")
    fm_a = (cg.get("cs_a") or {}).get("frontmatter") or {}
    check("带 check_strength 落 fm", fm_a.get("check_strength") == "hoop",
          fm_a.get("check_strength"))
    cg.add("cs_b", "# 功能名：断言乙\n# 生效条件：测\n", layer="knowledge",
           verification_basis="test")
    fm_b = (cg.get("cs_b") or {}).get("frontmatter") or {}
    check("缺省不落键（存量零迁移）", "check_strength" not in fm_b,
          fm_b.get("check_strength"))
    try:
        cg.add("cs_c", "# 功能名：断言丙\n# 生效条件：测\n", layer="knowledge",
               verification_basis="test", check_strength="nuke")
        check("非法强度拒绝", False, "未抛 ValueError")
    except ValueError:
        check("非法强度拒绝", True)

    # ---- 8. 覆写继承（全量重建 fm 的坑）----
    cg.add("cs_a", "# 功能名：断言甲\n# 生效条件：测（覆写）\n", layer="knowledge",
           verification_basis="test", override=True)
    fm_a2 = (cg.get("cs_a") or {}).get("frontmatter") or {}
    check("覆写默认继承", fm_a2.get("check_strength") == "hoop",
          fm_a2.get("check_strength"))
    cg.add("cs_a", "# 功能名：断言甲\n# 生效条件：测（再覆写）\n",
           layer="knowledge", verification_basis="test", override=True,
           check_strength="doubly_decisive")
    fm_a3 = (cg.get("cs_a") or {}).get("frontmatter") or {}
    check("覆写显式改值", fm_a3.get("check_strength") == "doubly_decisive",
          fm_a3.get("check_strength"))

    print("\ntest_state_events: %d 通过 / %d 失败" % (_ok, len(_fail)))
    if _fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
