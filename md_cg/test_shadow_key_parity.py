# -*- coding: utf-8 -*-
"""验收判据① · 影子回放：新旧键并列（旧形态与会话五元组共存时的分桶结果）。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import bucketindex  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix="k1_"), actor="t")
    # 旧形态（无五元组、可带的会话）与五元组形态混存
    cg.add("old1", "旧形态会话的日常记录", layer="contextual",
           tags=["用途:日常"], session="session-legacy-1")
    cg.add("new1", "五元组会话的维护记录", layer="contextual",
           tags=["用途:修缺陷"], session="s5.dsh.maintainer.D_4_ai.1791340000.aaaaaaaaaaaa")
    cg.add("none1", "没有会话归属的记录", layer="contextual", tags=[])
    cg.flush()

    out = bucketindex.build(cg, write=False)
    ok(out.get("days", 0) >= 1, "K1 日桶成立（≥1 天）", out)
    ok(out.get("sessions", 0) >= 2, "K2 会话桶含旧形态与新形态（并列）", out)
    ok(out.get("unattributed", 0) == 1, "K3 无归属单独计数（不建会话桶）", out)
    ok(out.get("purposes", 0) == 2, "K4 用途副键计数（旧形态+五元组）", out)
    ok(out.get("nodes", 0) == 3, "K5 节点总数", out)

    # 新旧并列可直接复核：桶文件里同时存在 session-… 与 s5.… 前缀
    root = cg.root
    p = os.path.join(root, bucketindex.SESSIONS_FILE)
    if os.path.exists(p):
        import json
        data = json.load(open(p, encoding="utf-8"))
        keys = list(data)
        ok(any(k.startswith("session-") for k in keys) and any(k.startswith("s5.") for k in keys),
           "K6 落盘桶键里新旧形态并存", keys[:5])
    else:
        print("  SKIP K6：未落盘（write=False）")

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
