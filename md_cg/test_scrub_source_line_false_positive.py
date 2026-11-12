# -*- coding: utf-8 -*-
"""scrub 误判守卫：引用/出处行（「…（源：src_x）」）不得被当成可断言的键值对。"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import scrub   # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


PREFIX = "# 功能名：甲\n\n同一句前缀（源："
TAIL = "src_aaa、src_bbb）"
TAIL2 = "src_ccc）"


class FakeCG:
    def __init__(self, nodes):
        self._n = nodes

    def get(self, nid):
        return self._n.get(nid)


def main():
    print("=" * 68)
    print("scrub · 引用行误判守卫")
    print("=" * 68)
    # A1：括号类键不再被抽出（本地实测：切出来是「…（源」）
    kv = scrub._kv_pairs(PREFIX + TAIL)
    ok(not any("（" in k for k in kv), "A1 含括号的前缀键不再进入断言键集", kv)
    ok(kv == {}, "A1b 该行一个键都不抽", kv)
    # A2：值侧兜底——虽键合法但值是引用 id 列表
    kv2 = scrub._kv_pairs("出处：src_a、src_b")
    ok("出处" not in kv2, "A2 值是 src_ 列表的键被排除", kv2)
    # A3：端到端——同前缀 + 不同源 ⇒ 不得判矛盾
    cg = FakeCG({"peer": {"content": PREFIX + TAIL2}})
    hit = scrub._contradiction(cg, PREFIX + TAIL, [{"node_id": "peer", "via": "lexical"}])
    ok(hit is None, "A3 同前缀不同源不再判 contradiction", hit)
    # A4：真矛盾仍要抓到（键合法、值不同）
    cg2 = FakeCG({"peer2": {"content": "# 功能名：乙\n\n端口：8080"}})
    hit2 = scrub._contradiction(cg2, "# 功能名：甲\n\n端口：9090",
                                [{"node_id": "peer2", "via": "lexical"}])
    ok(bool(hit2) and "同键不同值" in str(hit2.get("why")), "A4 真矛盾仍被抓到", hit2)
    print()
    print("scrub 引用行守卫：%d 项失败" % len(FAILS) if FAILS else "scrub 引用行守卫：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())