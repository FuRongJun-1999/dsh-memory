#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索读缓存默认开启守卫（issue #31 P2 后续：生产入口 O(n) 全池扫描修复）。

背景（缺陷报告实测）：生产检索入口（mcp_server mdcg_search → MdCGSecure.
(MdCGOS).search → _read_many，mdcos.py:841）默认态每查询把全池节点文件
逐个 open+2×realpath+frontmatter 解析——3300 节点池实测中位 ~602ms/查询、
万级外推 ~2s+，线性 O(n)。读缓存（readcache.install）早已存在但默认关
（零变更纪律），生产恒不装配——「开关已存在，只差默认值」。

本守卫断言（调用计数/复杂度形态，非时间阈值）：
  D1 默认装配：env 未设 MDCG_READ_CACHE → 构造即装（hasattr _read_cache）；
  D2 二次检索零重解析：默认态下第二次 search 期间 nodefile.loads 调用数为 0
     （旧默认：=候选池节点数，每查询全量重读 → 本断言红）；
  D3 装载恰一次：同实例 3 次检索累计 loads ≤ 池节点数（复杂度 O(装载1次)，
     不是 O(查询数×池)）；
  D4 opt-out 退出阀：MDCG_READ_CACHE=0 → 无 _read_cache 属性、检索照常；
  D5 默认态写后不陈旧（哨兵失效仍生效）：写新节点 → 检索命中新内容；
  D6 结果一致：默认开与显式关（=0）同库同 query 结果 id 序一致（缓存只改
     速度不改结果）。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import nodefile                       # noqa: E402
from md_cg.mdcos import MdCGSecure               # noqa: E402
from md_cg.security import Principal             # noqa: E402

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def build_lib(root, n=12):
    cg = MdCGSecure(root, principal=Principal(
        actor="rd", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))
    for i in range(n):
        cg.add("mem_%03d" % i,
               "# 功能名：默认缓存样本 %d\n# 正文：蜂群调度 节点 %d" % (i, i),
               layer="knowledge")
    cg.flush()
    return cg


def count_loads(fn):
    """打桩 nodefile.loads 计数（节点文件解析的唯一入口，_read 内调用）。"""
    n = 0
    real = nodefile.loads

    def _spy(*a, **kw):
        nonlocal n
        n += 1
        return real(*a, **kw)

    nodefile.loads = _spy
    try:
        return fn(), n
    finally:
        nodefile.loads = real


def main():
    root = tempfile.mkdtemp(prefix="mdcg_readcache_def_")
    try:
        # D1 默认装配（env 未设 → 默认开）
        print("== D1 默认装配 ==")
        os.environ.pop("MDCG_READ_CACHE", None)
        cg = build_lib(root)
        check("D1a env 未设时构造即装读缓存（hasattr _read_cache）",
              hasattr(cg, "_read_cache"))
        pool_n = len(cg.index["nodes"])
        check("D1b 库就绪（12 节点）", pool_n == 12, f"nodes={pool_n}")

        # D2/D3 装载复杂度（计数断言，能红 O(查询×池) 的旧默认态）
        print("== D2/D3 装载恰一次 / 二次检索零重解析 ==")
        total = 0
        _, n1 = count_loads(lambda: cg.search("蜂群调度"))
        total += n1
        check("D3a 首次检索装载 ≤ 池节点数", n1 <= pool_n,
              f"first={n1} pool={pool_n}")
        _, n2 = count_loads(lambda: cg.search("蜂群调度"))
        total += n2
        check("D2a 二次检索零重解析（loads==0）", n2 == 0, f"second={n2}")
        _, n3 = count_loads(lambda: cg.search("样本 节点"))
        total += n3
        check("D3b 3 次检索累计装载 ≤ 池节点数（O(装载1次)，旧默认为 3×池）",
              total <= pool_n, f"total={total} pool={pool_n}")

        # D5 默认态写后不陈旧（哨兵失效在默认开下仍生效）
        print("== D5 写后失效 ==")
        cg.add("mem_new", "# 功能名：写入后的新内容BBB\n# 正文：更新后内容BBB 独有标记",
               layer="knowledge")
        cg.flush()
        r5, _ = cg.search("更新后内容BBB")
        check("D5a 写入后新内容立即可检索（不陈旧）",
              any(x[0].get("id") == "mem_new" for x in r5),
              f"ids={[x[0].get('id') for x in r5][:5]}")

        # D6 结果一致（默认开 vs 显式关）：同库同 query 的 id 序一致
        print("== D6 开/关结果一致 ==")
        r_on, _ = cg.search("蜂群调度")

        os.environ["MDCG_READ_CACHE"] = "0"
        try:
            # 关态独立实例（同库——节点已在盘上，构造扫描即装载索引）
            cg0 = MdCGSecure(root, principal=Principal(
                actor="rd", clearance="secret", can_write=True,
                role="designer", auth_mode="test"))
            r_off, _ = cg0.search("蜂群调度")
            ids_on = [x[0].get("id") for x in r_on]
            ids_off = [x[0].get("id") for x in r_off]
            check("D6a 开/关同库同 query 结果 id 序一致",
                  ids_on == ids_off,
                  f"on={ids_on[:5]} off={ids_off[:5]}")
            check("D6b 关态退出阀生效（无 _read_cache 属性）",
                  not hasattr(cg0, "_read_cache"))
        finally:
            os.environ.pop("MDCG_READ_CACHE", None)

        # D4 opt-out 退出阀（独立段，防顺序依赖）
        print("== D4 opt-out 退出阀 ==")
        os.environ["MDCG_READ_CACHE"] = "0"
        try:
            root4 = os.path.join(root, "optout")
            os.makedirs(root4, exist_ok=True)
            cg4 = MdCGSecure(root4, principal=Principal(
                actor="rd", clearance="secret", can_write=True,
                role="designer", auth_mode="test"))
            cg4.add("m1", "# 功能名：a\n# 正文：蜂群调度 内容", layer="knowledge")
            cg4.flush()
            check("D4a MDCG_READ_CACHE=0 → 未装缓存（零变更退出阀）",
                  not hasattr(cg4, "_read_cache"))
            cg4.search("蜂群调度")              # 预热（无缓存，恒读盘）
            _, n4 = count_loads(lambda: cg4.search("蜂群调度"))
            check("D4b 关态二次检索仍逐节点重解析（loads>0，证明退出阀真关）",
                  n4 > 0, f"loads={n4}")
        finally:
            os.environ.pop("MDCG_READ_CACHE", None)
    finally:
        os.environ.pop("MDCG_READ_CACHE", None)
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
