# -*- coding: utf-8 -*-
"""#804 守卫：tick 失败必须带可定位信息（traceback 摘要），而不是只有「类名: 消息」。

issue #804：scrub 档累计失败 5 次，台账只有
`RuntimeError: dictionary changed size during iteration` —— 没有栈、没有行号，
pid 还五次全不同 ⇒ 在现有观测面下无法定位。
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg.sustain import _tick_error_summary  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def _boom_dict_changed():
    d = {"a": 1}
    for _k in d:
        d["b"] = 2


def main():
    print("=" * 66)
    print("#804 tick 失败的定位信息")
    print("=" * 66)
    try:
        _boom_dict_changed()
    except Exception as e:          # noqa: BLE001
        s = _tick_error_summary(e)
    else:
        s = ""
    ok(s.startswith("RuntimeError: dictionary changed size"), "T1 保留类名与消息", s[:60])
    ok(" @ " in s, "T2 追加栈摘要（含 @ 分隔）", s[:120])
    ok(":" in s.split(" @ ")[-1], "T3 栈摘要含 文件:行", s.split(" @ ")[-1][:80])
    ok("\n" not in s, "T4 仍是单行（不破坏 _heartbeat.jsonl 逐行 JSON 契约）", repr(s[:40]))

    # 无栈异常也要给类名+消息，不能崩
    plain = _tick_error_summary(ValueError("x"))
    ok(plain.startswith("ValueError: x"), "T5 无回溯时退化为类名+消息", plain)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())