#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_emit 尾部 covered_neg 裸读守卫（v9 留档复测·修复，缺陷迭代第 14 轮）。

缺陷形态（缺陷报告实测，60 knowledge + 8 rejected 临时库，逐位复现）：
  _emit 尾部「把被负记忆覆盖的查询也作为结果条目返回」对 neg_coverage[:3]
  逐条裸 open+nodefile.loads（mdcg.py _emit 尾，不经 self._read 不在读缓存
  包装面）——每条命中负层的查询恒 ≤3 次盘读（Q1 loads=71=全池 60+负层
  扫描 8+尾部 3；Q2 同查询增量恰 3）；负层主面 IO 已被读缓存覆盖（残余项）。

修复口径：尾部改走 self._read(nc)（读缓存覆盖，增量归零）；_read 同款
  _node_disk_path 边界闸（P2-20——索引被污染时不得绕过统一校验读 root 外
  文件）、OSError→(None,None) 与旧 continue 同义；负层写路径（add/
  add_rejected → _stage 标脏带 path）在读缓存脏集精确失效面内——覆写后
  尾部条目即时见新内容，不陈旧。

本守卫（调用计数断言形态，非时间阈值）：
  E1 热缓存后同查询 loads 增量 == 0（旧实现恒 3 → 红）；
  E2 功能在位：rejected 前 3 条仍在结果、covered_neg 计数/tier/scanned
     不变（尾部不是被静默关掉）；
  E3 两轮查询结果 ids 逐位一致（确定性）；
  E4 读缓存开/关（MDCG_READ_CACHE=1/0）同库同查询 ids 逐位一致；
  E5 覆写负层节点后尾部条目见新内容（脏集精确失效联动，不陈旧）。

运行：python -m md_cg.test_emit_negtail_cache
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import nodefile                     # noqa: E402
from md_cg.mdcos import MdCGOS                 # noqa: E402

PASS = 0
FAIL = 0
FAILS = []

N = 60
NNEG = 8
QUERY = "已被否决的做法"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def build_lib(root):
    cg = MdCGOS(root)
    for i in range(N):
        cg.add("mem_%03d" % i,
               "# 功能名：正层样本 %d\n# 正文：蜂群调度 节点 %d" % (i, i),
               layer="knowledge")
    for j in range(NNEG):
        cg.add("r%d" % j,
               "# 假设：%s 第 %d 号\n# 原因：与既有验证结论冲突" % (QUERY, j),
               layer="rejected", verification_basis="test")
    cg.flush()
    return cg


def count_loads(fn):
    st = {"n": 0}
    real = nodefile.loads

    def _spy(*a, **kw):
        st["n"] += 1
        return real(*a, **kw)

    nodefile.loads = _spy
    try:
        return fn(), st["n"]
    finally:
        nodefile.loads = real


def neg_ids(res):
    return [x[0].get("id") for x in res if str(x[0].get("id")).startswith("rejected/")]


def main():
    root = tempfile.mkdtemp(prefix="mdcg_negtail_")
    cg = None
    try:
        os.environ.pop("MDCG_READ_CACHE", None)
        cg = build_lib(root)
        (r1, m1), n1 = count_loads(lambda: cg.search(QUERY))
        ids1 = [x[0].get("id") for x in r1]
        check("E0a 首查口径复现：covered_neg=8、tier=T3、scanned=60",
              len(m1.get("covered_neg") or []) == NNEG
              and m1.get("tier") == "T3_global_scan"
              and m1.get("scanned") == N,
              f"covered={len(m1.get('covered_neg') or [])} "
              f"tier={m1.get('tier')} scanned={m1.get('scanned')}")
        check("E0b rejected 前 3 条在结果（尾部功能在位）",
              neg_ids(r1)[:3] == ["rejected/r0.md", "rejected/r1.md",
                                  "rejected/r2.md"],
              f"neg={neg_ids(r1)[:3]}")

        (r2, m2), n2 = count_loads(lambda: cg.search(QUERY))
        ids2 = [x[0].get("id") for x in r2]
        check("E1a 热缓存后同查询 loads 增量 == 0（旧实现恒 3）",
              n2 == 0, f"loads={n2}")
        check("E2a rejected 前 3 条仍逐位在位、meta 口径不变",
              neg_ids(r2)[:3] == ["rejected/r0.md", "rejected/r1.md",
                                  "rejected/r2.md"]
              and len(m2.get("covered_neg") or []) == NNEG
              and m2.get("tier") == "T3_global_scan"
              and m2.get("scanned") == N)
        check("E3a 两轮查询结果 ids 逐位一致", ids1 == ids2,
              f"n={len(ids1)}/{len(ids2)}")

        # E4 读缓存开/关结果一致
        os.environ["MDCG_READ_CACHE"] = "0"
        try:
            cg0 = MdCGOS(root)
            r_off, m_off = cg0.search(QUERY)
            cg0.close()
            check("E4a 读缓存开/关同库同查询 ids 逐位一致",
                  [x[0].get("id") for x in r_off] == ids2)
        finally:
            os.environ.pop("MDCG_READ_CACHE", None)

        # E5 覆写负层节点 → 尾部条目即时见新内容（脏集精确失效联动）
        cg.add("r0", "# 假设：%s 第 0 号\n# 原因：覆写后的新结论ZZZ" % QUERY,
               layer="rejected", verification_basis="test")
        r3, _ = cg.search(QUERY)
        neg3 = next((x[0] for x in r3
                     if x[0].get("id") == "rejected/r0.md"), None)
        check("E5a 覆写 r0 后尾部条目见新内容（不陈旧）",
              neg3 is not None and "新结论ZZZ" in (neg3.get("content") or ""),
              f"content={str((neg3 or {}).get('content'))[:40]}")
        cg.close()
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
