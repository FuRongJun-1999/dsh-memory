# -*- coding: utf-8 -*-
"""守卫 · issue #804 scrub 崩溃轮必须在 `_scrub.jsonl` 留痕。

病灶：`_tick_scrub` 同步调 `scrub.sweep`，异常直接穿出 ⇒ 既无 rec 也无台账行，
`_scrub.jsonl` 全是 `ok:true`，看不出「这一轮自净发生过但没完成」。

取向（判据在公开面，不打补丁细节）：
  S1 崩溃轮留一行 op="sweep" ok=False；
  S2 该行含 error 摘要（含末帧位置，可定位）；
  S3 崩溃仍向上抛（心跳 tick 失败不被吞）；
  S4 成功轮记录形状不变（不回归）；
  S5 失败行不污染幂等账（_handled 只认 op=="decontaminate" and ok）。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import scrub, sustain  # noqa: E402
from md_cg.fsutil import read_jsonl  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def _mk():
    g = MdCGOS(tempfile.mkdtemp(prefix="i804_"), actor="test")
    g.add("n1", "# 功能名：a\n# 生效条件：c\n# 子功能：s\n# 执行：e\n"
          "# 验证方式：t\n# 不适用条件：无\n\n正文\n",
          layer="knowledge", consistency=False)
    return g


def _rows(g):
    return list(read_jsonl(os.path.join(g.root, scrub.SCRUB_LOG)))


def main():
    print("=" * 70)
    print("issue #804：scrub 崩溃轮留痕")
    print("=" * 70)

    # ① 崩溃轮：sweep 抛 RuntimeError（照 issue 的实测异常形态）
    g = _mk()
    loop = sustain.SustainLoop(g, name="t804")
    boom = RuntimeError("dictionary changed size during iteration")
    with patch.object(scrub, "sweep", side_effect=boom):
        raised = None
        try:
            loop._tick_scrub()
        except Exception as e:            # noqa: BLE001 —— 就是要它抛
            raised = e
    ok(raised is boom, "S3 崩溃仍向上抛（心跳面能记 tick 失败，不被吞）", type(raised).__name__)

    rows = _rows(g)
    fails = [r for r in rows if r.get("op") == "sweep" and r.get("ok") is False]
    ok(len(fails) == 1, "S1 崩溃轮在 _scrub.jsonl 留一行 op=sweep ok=False", rows)
    row = fails[0] if fails else {}
    ok(bool(row.get("error")) and "RuntimeError" in str(row.get("error")),
       "S2 该行含 error 摘要（可定位）", row.get("error"))
    ok(row.get("round") == 1 and str(row.get("seed") or "").startswith("sustain:"),
       "S2b 该行带轮次与 seed（可对账到具体轮）", (row.get("round"), row.get("seed")))
    ok(row.get("phase") == "sweep" and "dry_run" in row,
       "S2c 该行带 phase 与 dry_run（能看出崩在哪一步、是否只读轮）", row)

    # ⑤ 失败行不污染幂等账
    ok(scrub._handled(g) == set(), "S5 失败行不进幂等账（_handled 仍空）", scrub._handled(g))

    # ④ 成功轮形状不变：恢复真实 sweep，再跑一轮
    loop2 = sustain.SustainLoop(g, name="t804b")
    loop2._tick_scrub()
    # 成功行沿用既有形状：**不带 ok 键**（缺省即成功）；失败行显式 ok=False。
    ok_rows = [r for r in _rows(g)
               if r.get("op") == "sweep" and r.get("ok") is not False]
    ok(len(ok_rows) >= 1, "S4 成功轮照常记账（不回归）", len(ok_rows))
    ok("error" not in (ok_rows[-1] if ok_rows else {}), "S4b 成功行不带 error")

    # ⑥ summary 口径：失败轮单列，last_sweep 不被失败行顶掉
    sm = scrub.summary(g)
    ok(sm.get("failed_sweeps") == 1, "S6 summary.failed_sweeps 计到 1 轮失败", sm.get("failed_sweeps"))
    ok((sm.get("last_sweep_failed") or {}).get("error"),
       "S6b last_sweep_failed 带 error（可直接定位）", sm.get("last_sweep_failed"))
    ok((sm.get("last_sweep") or {}).get("t") is not None,
       "S7 last_sweep 仍取最近成功轮（不被失败行顶掉）", sm.get("last_sweep"))
    ok(sm.get("sweeps") == 1, "S7b sweeps 只数成功轮（失败轮不计入）", sm.get("sweeps"))

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())