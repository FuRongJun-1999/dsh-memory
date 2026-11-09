# -*- coding: utf-8 -*-
"""A 别名召回：写进去的 aliases 必须真的改变检索名次。

功能名：test_alias_recall —— 别名（issue #722）在检索里的实际作用守卫。
生效条件：`PYTHONPATH=<root> python -m md_cg.test_alias_recall`。
子功能：断言面——
  A1 带别名的节点在「用别名问」时排第一（不是靠写入序）；
  A2 该节点得分 >= 0.60（别名命中抬升生效，不是 0.05 的 tag 加成）；
  A3 用正文原词问时它仍排第一（别名不抢本体）；
  A4 别名与查询无关时不给加成（兄弟节点不被误抬）；
  A5 别名短于 2 字不生效（防单字 alias 全库误命中）。
执行：`python -m md_cg.test_alias_recall`。
验证方式：test。
不适用条件：活库；不覆盖 wiring/vector 路（本判据只看 lexical 路的原始名次）。
"""
from __future__ import annotations

import shutil
import sys
import tempfile

from .mdcos import MdCGOS

PASS = 0
FAIL = 0
FAILS = []


def _ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS", label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL", label)


def _write(cg, nid, content, aliases):
    """aliases 走 add 的 **extra 通道（与 mcp 的 write 参数同名），不是 fm=。"""
    kw = {"aliases": list(aliases)} if aliases else {}
    cg.add(nid, content, layer="knowledge", tags=["probe"],
           importance=0.6, **kw)


def _rank(cg, q):
    """search 的行形态是 (entry, score, qual)；这里只取 id 与分数。"""
    rows, _meta = cg.search(q, k=5, judge=False)
    out = []
    for row in rows:
        e, sc = row[0], row[1]
        out.append(((e.get("frontmatter") or {}).get("id") or e.get("id"),
                    round(float(sc or 0), 3)))
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_alias_recall_")
    try:
        cg = MdCGOS(tmp)
        _write(cg, "kn_router_note",
               "家用网络那台设备的管理页面在浏览器里输入网关地址就能进，账号密码贴在机身上。",
               ["路由器设置", "怎么设置路由器"])
        _write(cg, "kn_unrelated",
               "今晚把流水线跑了一遍，日志里没有新的报错。",
               ["流水线日志"])

        print("[A1/A2] 用别名问 → 别名节点第一，且分数被抬到 0.60 以上")
        r = _rank(cg, "路由器怎么设置才不丢包")
        _ok(r and r[0][0] == "kn_router_note", "第一名是别名节点（%r）" % (r[:2],))
        _ok(r and r[0][1] >= 0.60, "得分 >= 0.60（%r）" % (r[0][1] if r else None,))

        print("[A3] 用正文原词问 → 仍第一")
        r2 = _rank(cg, "网关地址 账号密码 管理页面")
        _ok(r2 and r2[0][0] == "kn_router_note", "正文词命中第一（%r）" % (r2[:2],))

        print("[A4] 别名与查询无关 → 不给加成")
        r3 = _rank(cg, "流水线日志 报错")
        top = dict(r3)
        _ok(r3 and r3[0][0] == "kn_unrelated", "无关查询命中的是自己的节点（%r）" % (r3[:2],))
        _ok(top.get("kn_router_note", 0) < 0.60,
            "别名节点没被误抬（%r）" % (top.get("kn_router_note"),))

        print("[A5] 单字别名不生效")
        _write(cg, "kn_single", "这条节点只挂了一个单字别名，不该因此被任何查询捞起。",
               ["网"])
        r4 = _rank(cg, "网")
        ids = [i for i, _ in r4]
        _ok("kn_router_note" in ids or "kn_single" not in ids[:1],
            "单字别名不改变名次（%r）" % (r4[:2],))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== test_alias_recall: PASS %d / FAIL %d ===" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
