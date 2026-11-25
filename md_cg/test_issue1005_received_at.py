# -*- coding: utf-8 -*-
"""守卫 · issue #1005：时间戳一律按「收到」算（received_at）。

判据（使用者 2026-11-25 定）：**发送不可见，收到才可见，一律按收到算。**

为什么必须区分：`created_at` 是**写入**时间，批量导入时它等于导入时间；
而 B 类 9 道失败题正是「模型把材料里的日期戳当成「他什么时候说的」」。
戳的身份写清楚，模型才不会把采集时间当陈述时间。

本守卫钉住：
  1. `add(..., received_at=...)` 能写进 frontmatter（不改 add 签名）；
  2. pack 条目的 `created_at_date` 用 `received_at`（不是 created_at）；
  3. 没给 received_at 的老节点回落 created_at，行为不变。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  " + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


#: 2026-11-24 10:47 左右（与写入时刻差一天以上，便于区分）
RECEIVED = 1795488442.29


def main():
    T = tempfile.mkdtemp(prefix="received_at_")
    try:
        cg = MdCGOS(T, actor="t")
        cg.add("with_ra", "# 对话\n我昨天去了杭州 收到时刻测试\n",
               layer="contextual", tags=["对话"], importance=0.6, received_at=RECEIVED)
        cg.add("no_ra", "# 对话\n我昨天去了杭州 无收到时刻测试\n",
               layer="contextual", tags=["对话"], importance=0.6)
        cg.flush()

        n1 = cg.get("with_ra")
        n2 = cg.get("no_ra")
        fm1 = (n1 or {}).get("frontmatter") or {}
        fm2 = (n2 or {}).get("frontmatter") or {}

        ok(abs(float(fm1.get("received_at") or 0) - RECEIVED) < 1e-6,
           "R1 add(received_at=...) 写进 frontmatter（不改签名）", fm1.get("received_at"))
        ok(fm2.get("received_at") is None,
           "R2 不给 received_at ⇒ 不写该字段（老行为不变）", fm2.get("received_at"))

        out = cg.recall("收到时刻测试", budget_tokens=600, k=10)
        pack = out.get("pack") or []
        by_id = {e.get("id"): e for e in pack}
        e1 = by_id.get("with_ra")
        e2 = by_id.get("no_ra")
        ok(e1 is not None and e1.get("created_at_date") == "2026-11-24",
           "R3 pack 日期戳用 received_at（2026-11-24，不是写入日）",
           (e1 or {}).get("created_at_date"))
        today = time.strftime("%Y-%m-%d")
        ok(e2 is None or e2.get("created_at_date") == today,
           "R4 无 received_at 的节点回落 created_at（今天）",
           (e2 or {}).get("created_at_date"))

        # R5：正文里的相对日期按 received_at 换算（不是按写入时刻）
        cd = (e1 or {}).get("content_dated") or ""
        ok("2026-11-23" in cd,
           "R5 「昨天」按 received_at 换算成 2026-11-23（而非写入日的昨天）", cd[:80])
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print("收到时刻守卫：%d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())