# -*- coding: utf-8 -*-
"""守卫 · issue #909 同一经历只因原文摘录不同就被重复列出。

病象（issue 复现）：两条经历业务字段相同（示例工坊 | 学徒），只有 `_raw` 摘录不同 ⇒
`dossier.merge` 的去重键把 `_raw` 一起比，于是拆成两项；`profiles.render` 又跳过下划线键，
结果资料卡里出现两行**完全相同**的内容。

修法：去重键只比业务字段（排除 `_` 前缀键）。

断言（照 issue 的三组复现）：
  D1 摘录相同 ⇒ 一条
  D2 摘录不同、业务字段相同 ⇒ **仍一条**（本件修的正是这条）
  D3 职位不同 ⇒ 保留两条（防「去重过度」）
  D4 合并后仍保留首条 `_raw`（证据可回查）
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import dossier, profiles  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def build(mode):
    root = tempfile.mkdtemp(prefix="i909_", dir=".")
    cg = MdCGOS(root, actor="test")
    for i, raw in enumerate(("在示例工坊当学徒", "曾在示例工坊做过学徒")):
        if mode == "same_anchor":
            raw = "在示例工坊当学徒"
        role = "木工" if mode == "different_role" and i == 1 else "学徒"
        if role == "木工":
            raw = "曾在示例工坊做过木工"
        stamp = time.mktime(time.strptime("2026-10-0%d" % (i + 1), "%Y-%m-%d"))
        cg.add("source%d" % i, raw, created_at=stamp,
               diary={"speaker": "示例甲", "date": "2026-10-0%d" % (i + 1)},
               extra={"dossier": {"经历": [
                   {"单位": "示例工坊", "职位": role, "_raw": raw}]}},
               consistency=False)
    profiles.build(cg, dry_run=False)
    card = (cg.get(profiles.card_id("role", "示例甲")) or {}).get("content") or ""
    rows = [ln for ln in card.splitlines() if ln.startswith("- 示例工坊 | ")]
    return cg, card, rows


def main():
    print("=" * 70)
    print("issue #909：经历去重（证据摘录不参与比较）")
    print("=" * 70)

    _, _, r1 = build("same_anchor")
    ok(len(r1) == 1, "D1 摘录相同 ⇒ 一条", r1)

    _, card2, r2 = build("different_anchor")
    ok(len(r2) == 1, "D2 摘录不同、业务字段相同 ⇒ 仍一条（本件靶心）", r2)
    ok(r2 == ["- 示例工坊 | 学徒"], "D2b 渲染内容正确", r2)

    _, _, r3 = build("different_role")
    ok(len(r3) == 2, "D3 职位不同 ⇒ 保留两条（防去重过度）", r3)

    # D4 合并后仍保留首条 _raw（纯函数级，快且直指判据）
    m = dossier.merge({}, {"经历": {"value": [{"单位": "示例工坊", "职位": "学徒",
                                           "_raw": "在示例工坊当学徒"}]}})
    m = dossier.merge(m, {"经历": {"value": [{"单位": "示例工坊", "职位": "学徒",
                                          "_raw": "曾在示例工坊做过学徒"}]}})
    items = (m.get("经历") or {}).get("value") or []
    ok(len(items) == 1, "D4a 业务字段相同 ⇒ 合成一条", items)
    ok(items and items[0].get("_raw") == "在示例工坊当学徒",
       "D4b 保留首条 _raw（证据可回查）", items)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())