# -*- coding: utf-8 -*-
"""守卫 · 身份中文名对照表（使用者裁定「甲」：机器形态不变，展示侧中文）。"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import identity_names as nm  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:160])
        FAILS.append(name)


def main():
    ok(nm.human_unit("agent") == "执行者" and nm.human_unit("designer") == "设计者",
       "I1 已知身份有中文名")
    ok(nm.human_unit("未知身份xyz") == "未知身份xyz", "I2 未登记身份原样返回（不猜）")
    ok(nm.human_unit("") == "未登记身份", "I2b 空值给明确文案")
    parsed = nm.parse_identity("s5.dsh.agent.D_4_ai.1791340000.3f9a2b7c1d05")
    ok(parsed.get("unit") == "agent" and parsed.get("harness") == "dsh",
       "I3 解析出的原始段值保持小写（形态不变）", parsed)
    ok(parsed.get("unit_cn") == "执行者" and parsed.get("harness_cn") == "DSH 端",
       "I4 示例会话可解析并给中文展示名", parsed)
    ok(nm.parse_identity("session-abc") == {}, "I4b 非五元组标识返回空（不硬解析）")
    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
