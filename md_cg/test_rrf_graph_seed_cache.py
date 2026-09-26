#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_rrf 图路种子读缓存守卫（v9:92 / v13 留档复测·修复，第 14 轮）。

缺陷形态（缺陷报告实测，40 带 tags/edges 节点临时库，逐位复现）：
  _path_graph 种子腿 mdcos.py `node = self.get(n["id"])` 在边循环前执行——
  get 裸 open+nodefile.loads（mdcg.py get 不在 readcache 包装面，install 只包
  cg._read），search_rrf 默认 paths 含 graph → 每查询固定 ≤5 次盘读
  （Q1 loads=45=词法 40+种子 5；Q2 增量恰 5、get 恒 5/查；graph 零产出也
  在边循环前发生）。边目标（:1017）早已走 self._read 同形。

修复口径：种子读改走 self._read(by_id[...])（读缓存覆盖，Q2 增量归零）；
种子 fm.id≠文件名等 by_id 不含形态回落 get 保旧口径（冷路径，正确性优先）。
种子来自 lexical（entries/_candidates 派生，MdCGSecure._candidates 已过
_readable）——绕过 get 的读隔离门无损失；图路扩展产物本就由
MdCGSecure.search_rrf 终态二次过滤兜底。

本守卫（调用计数断言形态，非时间阈值）：
  S1 热缓存后同查询 loads 增量 == 0（旧实现恒 5 → 红）；
  S2 热缓存后同查询 get 调用 == 0（旧实现恒 5 → 红）；
  S3 图路功能在位：词法零命中的「幽灵」节点经种子边一跳进入结果
     （graph 路不是被静默关掉）；
  S4 两轮查询结果 ids 逐位一致（确定性）；meta.paths 含四路计数；
  S5 开/关读缓存（MDCG_READ_CACHE=1 vs 0）同库同查询 ids 逐位一致
     （缓存只改速度不改结果）。

运行：python -m md_cg.test_rrf_graph_seed_cache
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

QUERY = "蜂群调度"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def build_lib(root, n=40):
    cg = MdCGOS(root)
    for i in range(n):
        edges = []
        if i % 4 == 0:                 # 部分节点带边（指向池内目标）
            edges = [{"target": "mem_%03d" % ((i + 1) % n),
                      "relation_type": "related_to"}]
        if i == 0:
            # 幽灵目标：词法零命中（正文无查询词），只经种子边一跳可达
            edges.append({"target": "ghost_x", "relation_type": "related_to"})
        cg.add("mem_%03d" % i,
               "# 功能名：图路样本 %d\n# 正文：%s 节点 %d" % (i, QUERY, i),
               layer="knowledge",
               tags=["tag_%d" % (i % 5)] if i % 3 == 0 else None,
               edges=edges)
    cg.add("ghost_x", "# 功能名：幽灵目标\n# 正文：完全不相关的孤岛内容",
           layer="knowledge")
    cg.flush()
    return cg


def counters(cg, fn):
    """同时计数 nodefile.loads 与实例 get。"""
    st = {"loads": 0, "gets": 0}
    real_loads = nodefile.loads
    real_get = MdCGOS.get

    def _spy_loads(*a, **kw):
        st["loads"] += 1
        return real_loads(*a, **kw)

    def _spy_get(self, node_id):
        st["gets"] += 1
        return real_get(self, node_id)

    nodefile.loads = _spy_loads
    cg.get = _spy_get.__get__(cg, MdCGOS)
    try:
        return fn(), st
    finally:
        nodefile.loads = real_loads
        del cg.get


def main():
    root = tempfile.mkdtemp(prefix="mdcg_rrf_seed_")
    cg = None
    try:
        os.environ.pop("MDCG_READ_CACHE", None)
        cg = build_lib(root)
        (r1, m1), c1 = counters(cg, lambda: cg.search_rrf(QUERY))
        ids1 = [x[0].get("id") for x in r1]
        check("S0a 首查正常（40+1 节点池，词法+图路融合）",
              len(r1) >= 1 and c1["loads"] > 0,
              f"n={len(r1)} loads={c1['loads']}")

        (r2, m2), c2 = counters(cg, lambda: cg.search_rrf(QUERY))
        ids2 = [x[0].get("id") for x in r2]
        check("S1a 热缓存后同查询 loads 增量 == 0（旧实现恒 5）",
              c2["loads"] == 0, f"loads={c2['loads']}")
        check("S2a 热缓存后同查询 get 调用 == 0（旧实现恒 5，种子改走 _read）",
              c2["gets"] == 0, f"gets={c2['gets']}")
        check("S3a 图路功能在位：词法零命中的 ghost 经种子边一跳进入结果",
              "ghost_x" in ids1, f"ghost in={('ghost_x' in ids1)}")
        paths_meta = (m2.get("paths") or {})
        check("S3b meta.paths 四路计数在位（graph 未被静默关掉）",
              {"lexical", "graph"} <= set(paths_meta),
              f"paths={paths_meta}")
        check("S4a 两轮查询结果 ids 逐位一致", ids1 == ids2,
              f"n={len(ids1)}/{len(ids2)}")

        # S5 开/关读缓存结果一致（新实例同库同查询）
        r_on = ids2
        os.environ["MDCG_READ_CACHE"] = "0"
        try:
            cg0 = MdCGOS(root)
            r_off, _ = cg0.search_rrf(QUERY)
            cg0.close()
            check("S5a 读缓存开/关同库同查询 ids 逐位一致",
                  [x[0].get("id") for x in r_off] == r_on,
                  f"off={[x[0].get('id') for x in r_off][:5]}")
        finally:
            os.environ.pop("MDCG_READ_CACHE", None)
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
