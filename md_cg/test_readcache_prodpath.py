#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索读缓存生产路径守卫（批次 21，issue #31 P2）。

外部报告实测（诚实边界照录）：
  - 567 池单次检索 572 次 builtins.open（~70-86% 耗时）；
  - install_read_cache 6.53x（126→19.3 ms）但只用于 benchmark；
  - path-only 无失效的朴素实现在「写入后检索」场景**陈旧读**（旧内容命中）。

本守卫五项：
  P1 默认关零变更（env 未设 → 行为与改动前逐位一致）；
  P2 开启后检索结果与关闭态一致（缓存不改变结果，只改变速度）；
  P3 写后失效（能红 path-only 无失效实现）：写入新内容 → 检索必须命中
     新内容、不得命中旧内容——哨兵（_dirty 代际）失效的核心断言；
  P4 open 计数：开启后二次检索零磁盘 open（打桩 builtins.open）；
  P5 clear() 强制兜底可用。
"""
import builtins
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGSecure
from md_cg.security import Principal

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
        actor="rc", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))
    for i in range(n):
        cg.add("mem_%03d" % i, "# 功能名：读缓存样本 %d\n# 正文：蜂群调度 节点 %d"
               % (i, i), layer="knowledge")
    cg.flush()
    return cg


def count_opens(fn):
    """打桩 builtins.open 计数（只统计读模式，排除访问日志）。

    访问日志（record_access）的「读后写」是 #31 P5 登记项（环境相关、
    另案缓解），不属本守卫的「节点正文读」度量面——P4 只断言正文零盘。
    """
    n = 0
    real = builtins.open

    def _spy(file, mode="r", *a, **kw):
        nonlocal n
        is_access = "access" in str(file)
        if ("r" in mode and not ("w" in mode or "a" in mode or "+" in mode)
                and not is_access):
            n += 1
        return real(file, mode, *a, **kw)

    builtins.open = _spy
    try:
        return fn(), n
    finally:
        builtins.open = real


def main():
    root = tempfile.mkdtemp(prefix="mdcg_readcache_")
    os.environ.pop("MDCG_READ_CACHE", None)
    cg = build_lib(root)
    try:
        # P1 默认关零变更
        print("== P1 默认关（env 未设）零变更 ==")
        check("P1a 未启用时无 _read_cache 属性", not hasattr(cg, "_read_cache"))
        r0, _ = cg.search("蜂群调度")
        check("P1b 检索正常（基线）", len(r0) >= 1, f"results={len(r0)}")

        # P2/P3/P4 开启态
        print("== P2/P3/P4 MDCG_READ_CACHE=1 ==")
        os.environ["MDCG_READ_CACHE"] = "1"
        import importlib
        import md_cg.readcache as rc
        importlib.reload(rc)
        rc.install(cg)

        r1, m1 = cg.search("蜂群调度")
        check("P2a 开启后结果一致（同库同 query）",
              [x[0].get("id") for x in r1] == [x[0].get("id") for x in r0],
              f"on={[x[0].get('id') for x in r1][:3]} off={[x[0].get('id') for x in r0][:3]}")

        # P3 写后失效（能红 path-only 无失效实现）
        print("== P3 写后失效（能红朴素实现）==")
        cg.add("mem_new", "# 功能名：写入后的新内容BBB\n# 正文：更新后内容BBB 独有标记",
               layer="knowledge")
        cg.flush()
        r3, _ = cg.search("更新后内容BBB")
        ids3 = [x[0].get("id") for x in r3]
        check("P3a 写入后新内容可检索（不陈旧）", "mem_new" in ids3,
              f"ids={ids3[:5]}")
        r3b, _ = cg.search("独有标记")
        check("P3b 独有标记命中新节点", any(
            x[0].get("id") == "mem_new" for x in r3b), f"ids={[x[0].get('id') for x in r3b]}")

        # P4 open 计数：热缓存后二次检索零读盘
        print("== P4 二次检索零磁盘 open ==")
        cg.search("蜂群调度")            # 预热（首检索装缓存）
        (_res, n_open), = (count_opens(lambda: cg.search("蜂群调度")),)
        check("P4a 热缓存后二次检索 open=0（报告基线：572/查询）",
              n_open == 0, f"opens={n_open}")

        # P6 派生物缓存（_doc_norm_bigrams 钩子）：identity 快照断言——
        # 二检后缓存条目的值对象不变（重算必然生成新对象）
        print("== P6 文档侧派生物缓存（_score 88% 热点面）==")
        nbc = getattr(cg, "_norm_bigrams_cache", {})
        snap = {k: v[1] for k, v in nbc.items()}
        check("P6pre 缓存已装载", len(snap) > 0, f"entries={len(snap)}")
        cg.search("蜂群调度")               # 二检
        nbc2 = getattr(cg, "_norm_bigrams_cache", {})
        same = all(nbc2[k][1] is snap[k] for k in snap if k in nbc2)
        check("P6a 热缓存后二次检索派生物零重算（identity 不变）",
              same and len(snap) > 0, f"snap={len(snap)}")

        # P5 clear 兜底（破坏性，放最后）
        n = rc.clear(cg)
        check("P5 clear 返回清空条目数", n > 0, f"cleared={n}")

        # P7 写代际单调（批次 23，issue #31 D-4 / v20 复现场景，能红 len 代际）
        print("== P7 flush 后同量写入不回退（D-4 陈旧读）==")
        cg.add("x_d4", "# 功能名：占位\n# 正文：原始内容AAA 星云", layer="knowledge")
        cg.add("a_d4", "# 功能名：a\n# 正文：填充甲", layer="knowledge")
        cg.add("b_d4", "# 功能名：b\n# 正文：填充乙", layer="knowledge")
        cg.flush()
        cg.add("c_d4", "# 功能名：c\n# 正文：填充丙", layer="knowledge")
        cg.add("d_d4", "# 功能名：d\n# 正文：填充丁", layer="knowledge")
        cg.search("原始内容AAA")                       # 装 x=OLD（此时 dirty len=2）
        cg.add("x_d4", "# 功能名：占位\n# 正文：更新后内容BBB 星云",
               layer="knowledge")                      # 覆写 x=NEW
        cg.flush()                                     # dirty 清零（len 代际在此回退）
        cg.add("e_d4", "# 功能名：e\n# 正文：填充戊", layer="knowledge")
        cg.add("f_d4", "# 功能名：f\n# 正文：填充己", layer="knowledge")  # len 巧合回到 2
        r_new, _ = cg.search("更新后内容BBB 星云")      # 写 NEW 后检索必须见 NEW
        got = next((it[0].get("content") for it in r_new
                    if it[0].get("id") == "x_d4"), None)
        check("P7a flush 回退场景：检索新内容返回 NEW（len 代际实现必返 OLD）",
              got is not None and "BBB" in got,
              f"content={str(got)[:40]}")

        # P7b 哨兵单调性直断：_DirtyDict 变更序列 write_gen 永不回退
        d = __import__("md_cg.mdcg", fromlist=["_DirtyDict"])._DirtyDict()
        gens = []
        d["a"] = 1; gens.append(d.write_gen)
        d["b"] = 2; gens.append(d.write_gen)
        d.clear(); gens.append(d.write_gen)
        d["c"] = 3; gens.append(d.write_gen)
        check("P7b write_gen 单调不回退（clear 后再写仍前进）",
              gens == sorted(gens) and len(set(gens)) == 4,
              f"gens={gens}")

        # 还原
        os.environ.pop("MDCG_READ_CACHE", None)
    finally:
        os.environ.pop("MDCG_READ_CACHE", None)
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
