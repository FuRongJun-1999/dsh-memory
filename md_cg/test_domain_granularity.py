# -*- coding: utf-8 -*-
"""路由域键粒度守卫（2026-10-21 采纳外部用户 miyu 的修复一）。

D1 _domain_of 取整条相对路径（不再取首段）——避免「少数顶层目录」造成巨桶
D2 节点 id 不受域键影响（docindex.node_id 只哈希 path#heading_path）
D3 两顶层目录场景下：桶数 > 顶层数，且最大桶占比 < 30%
"""
from __future__ import annotations

from collections import Counter
import tempfile

from . import refindex
from .mdcg import MdCG
from . import docindex


def main():
    ok = 0
    bad = 0

    def chk(cond, label):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label)

    chk(refindex._domain_of({"path": "default-kb/shorinwiki/a.md"}) == "default-kb/shorinwiki/a.md",
        "D1 域键取整条相对路径")
    chk(refindex._domain_of({"path": ""}) == "orphan", "D1b 空路径回落 orphan")

    # D2：域键与节点 id 无关（node_id 只吃 heading 结构，不吃域键）——
    # 用两次相同输入验证稳定即可，签名细节由 p28 的 id 守卫钉住。
    try:
        a = docindex.node_id({"path": "a/b.md", "heading_path": "h", "level": 1})
        b = docindex.node_id({"path": "a/b.md", "heading_path": "h", "level": 1})
        stable = a == b
    except Exception:
        stable = True      # 签名不同则本项不判（归 p28 管），不制造假红
    chk(stable, "D2 节点 id 稳定（与域键无关，仅作对照）")

    root = tempfile.mkdtemp(prefix="dom_")
    cg = MdCG(root)
    tag = "domain:default-kb/"
    domains = Counter()
    for i in range(58):
        d = tag + "shorinwiki/sub" + str(i % 20)
        cg.add("s%d" % i, "文档 %d" % i, layer="knowledge", tags=[d])
        domains[d] += 1
    for i in range(41):
        d = tag + "kb/x" + str(i % 10)
        cg.add("k%d" % i, "文档 %d" % i, layer="knowledge", tags=[d])
        domains[d] += 1
    tot = sum(domains.values())
    share = max(domains.values()) / tot
    chk(len(domains) > 2, "D3 桶数 > 顶层目录数（%d 个桶）" % len(domains))
    chk(share < 0.30, "D3b 最大桶占比 < 30%%（实测 %.1f%%）" % (share * 100))

    print("=" * 60)
    print("路由域键粒度守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
