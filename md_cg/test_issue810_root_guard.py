# -*- coding: utf-8 -*-
"""issue #810：cg 的 `root` 参数在数据面上必须**显式拒绝**（不得静默忽略）。"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg.mcp_server import _ROOT_SCOPED_OPS, _cg_call  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def raises(fn):
    try:
        fn()
    except ValueError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        return "其他异常: " + str(e)[:80]
    return None


def main():
    print("=" * 66)
    print("issue #810 · root 参数不得静默忽略")
    print("=" * 66)
    # A1：允许面 —— ref / index_code / index_doc
    ok(set(_ROOT_SCOPED_OPS) == {"ref", "index_code", "index_doc"},
       "A1 允许面恰好是 ref/index_code/index_doc", _ROOT_SCOPED_OPS)
    # A2：数据面出现 root ⇒ 必须抛，且错误信息点明替代方案
    for op in ("write", "read", "recall", "route", "info"):
        msg = raises(lambda o=op: _cg_call(object(), {"op": o, "root": "/tmp/x"}))
        ok(msg is not None and "MDCG_ROOT" in msg,
           "A2 op=%s 带 root ⇒ ValueError 且提示 MDCG_ROOT" % op, msg)
    # A3：不带 root 的数据面不得被误伤（走到分发层才算过；此处只要求「不是 root 的错」）
    msg = raises(lambda: _cg_call(object(), {"op": "read", "query": "x"}))
    ok(msg is None or "MDCG_ROOT" not in msg, "A3 不带 root 不触发该守卫", msg)
    print()
    print("issue #810：%d 项失败" % len(FAILS) if FAILS else "issue #810：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())