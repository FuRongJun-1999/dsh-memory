#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读缓存脏集精确失效守卫（缺陷迭代第 14 轮，high：写读交替整池重装）。

缺陷形态（缺陷报告实测，10k 临时库串行 3rep 中位）：
  readcache._cached 的代际哨兵取**全局单调** write_gen（整池共用一个值），
  _DirtyDict 每次变更 +1——任意一次单节点写使**全部**缓存条目同时 miss，
  下一条查询全池重装（open+parse 全部 N 个节点）：稳态 41.3ms/loads=0 →
  每 rep add 1 节点后同查询 1732.4ms/loads=10001（41.9× 退化），10k/20k/30k
  写后首查 1732/3515/5230ms 线性于 N。生产暴露面：mcp_server 读路径
  （op=read→search/recall）与写路径（op=write→writepipe._executor→cg.add，
  链尾 _commit_visibility→flush）同一常驻实例——写读交替负载 O(每写×全池)。

修复口径：_DirtyDict 簿记**脏 path 代际**（path_gen[path]=标脏时 write_gen），
读缓存按「该 path 最近标脏代际 ≤ 缓存代际」判新鲜——单节点写只失效该节点；
tombstone（_dirty[nid]=None，无 path 可辨）/其余变更形态走 broad_gen 保守
整池失效（与旧整代际口径等价的安全兜底）；clear()（flush/rebuild）只推进
write_gen 不再整池失效——flush 只落索引派生物（分片日志），节点文件的内容
变更在各写路径 `_dirty[nid]=entry`（带 path）时已精确失效；且生产写路径
每次写后 flush（writepipe._commit_visibility），clear 若整池失效会让精确
失效在生产写读交替负载下恒不生效。

本守卫九项（调用计数/复杂度断言形态，非时间阈值）：
  G1 写读交替不整池重装：热缓存后 add 1 节点 → 同查询 loads ≤ 2
     （旧整代际实现 ≈ 池+1 全量 → 红）；
  G2 生产写提交边界（add+flush）后同查询 loads ≤ 2（旧实现 flush 的
     clear() 再叠一次整池 miss → 红）；
  G3 写后不陈旧（正确性保持，P3/V5 同口径）：覆写既有节点 → 检索命中
     新内容、_read 缓存视图见新值；
  G4 写别的节点不误伤：add B 后 A 的缓存条目 identity 不变（不重读）；
  G5 删除保守整池失效：_unstage（tombstone）后同查询 loads ≥ 剩余池规模
     （无 path 可辨 → broad 兜底，与旧整代词语义等价，不陈旧）；
  G6 _DirtyDict 簿记直断：带 path 标脏 → path_gen 推进且 broad_gen 不动；
     tombstone → broad_gen 推进；flush 形态 clear() 不动 path_gen/broad_gen、
     clear(broad=True)（rebuild 收尾）推进 broad_gen；write_gen 单调不回退
     （P7b 口径保留）；
  G7 派生物缓存（_doc_norm_bigrams）同口径精确失效：add 1 节点后旧条目
     identity 不变（不重算）；
  G8 「直写文件 + rebuild_index 收尾」写方（ccgc/crosscheck/backfill 族）
     的缓存可见性：rebuild 的 clear(broad=True) 整池兜底——缓存视图见
     新内容且整池重装（回归面：全量套件 test_ccgc V4c/V5d 曾因 rebuild
     不失效而陈旧红）。

运行：python -m md_cg.test_readcache_precise_inval
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import nodefile                       # noqa: E402
from md_cg.mdcos import MdCGOS                   # noqa: E402

PASS = 0
FAIL = 0
FAILS = []

N = 40
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


def build_lib(root):
    cg = MdCGOS(root)
    for i in range(N):
        cg.add("mem_%03d" % i,
               "# 功能名：精确失效样本 %d\n# 正文：%s 节点 %d" % (i, QUERY, i),
               layer="knowledge")
    cg.flush()
    return cg


def count_loads(fn):
    """打桩 nodefile.loads 计数（节点文件解析唯一入口，_read 内调用）。"""
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
    root = tempfile.mkdtemp(prefix="mdcg_rc_precise_")
    try:
        os.environ.pop("MDCG_READ_CACHE", None)   # 默认开（生产默认态）
        cg = build_lib(root)
        check("G0a 库就绪且读缓存默认装配",
              len(cg.index["nodes"]) == N and hasattr(cg, "_read_cache"),
              f"nodes={len(cg.index['nodes'])}")

        # 预热：首查装缓存，二次查询零重解析（稳态前提）
        cg.search(QUERY)
        _, n_warm2 = count_loads(lambda: cg.search(QUERY))
        check("G0b 稳态二次查询零重解析（loads==0）", n_warm2 == 0,
              f"loads={n_warm2}")

        # G1 写读交替不整池重装：add 1 节点 → 同查询只解析新节点
        print("== G1 写读交替精确失效 ==")
        cg.add("g1_new", "# 功能名：新增节点\n# 正文：%s 新增内容G1" % QUERY,
               layer="knowledge")
        r1, n1 = count_loads(lambda: cg.search(QUERY)[0])
        check("G1a add 1 节点后同查询 loads ≤ 2（旧整代际 ≈ 池+1 全量）",
              n1 <= 2, f"loads={n1} pool={N + 1}")
        check("G1b 新节点可检索（不陈旧）",
              any(x[0].get("id") == "g1_new" for x in r1),
              f"ids={[x[0].get('id') for x in r1][:5]}")

        # G4 写别的节点不误伤：A 的缓存条目 identity 不变
        print("== G4 邻居条目不误伤 ==")
        pa = cg.index["nodes"]["mem_000"]["path"]
        snap = cg._read_cache.get(pa)
        check("G4pre A 条目已在缓存", snap is not None)
        cg.add("g4_other", "# 功能名：邻居写入\n# 正文：%s 邻居G4" % QUERY,
               layer="knowledge")
        count_loads(lambda: cg.search(QUERY))
        cur = cg._read_cache.get(pa)
        check("G4a 写其它节点后 A 缓存条目 identity 不变（不重读）",
              cur is not None and cur is snap,
              f"same={cur is snap}")

        # G2 生产写提交边界：add + flush（writepipe._commit_visibility 等价形态）
        print("== G2 写提交边界（add+flush）不整池重装 ==")
        cg.add("g2_flush", "# 功能名：管线节点\n# 正文：%s 管线G2" % QUERY,
               layer="knowledge")
        cg.flush()
        r2, n2 = count_loads(lambda: cg.search(QUERY)[0])
        check("G2a add+flush 后同查询 loads ≤ 2（clear 不整池失效）",
              n2 <= 2, f"loads={n2} pool={N + 3}")
        check("G2b flush 后新节点可检索（不陈旧）",
              any(x[0].get("id") == "g2_flush" for x in r2),
              f"ids={[x[0].get('id') for x in r2][:5]}")

        # G3 写后不陈旧（正确性保持）：覆写既有节点
        print("== G3 覆写后不陈旧 ==")
        cg.add("mem_000", "# 功能名：覆写样本\n# 正文：%s 更新后内容BBB 独有标记G3" % QUERY,
               layer="knowledge")
        entry = cg.index["nodes"]["mem_000"]
        fm_v, c_v = cg._read(entry)               # 缓存视图（生产读形态）
        check("G3a 覆写后 _read 缓存视图见新内容（不陈旧）",
              c_v is not None and "BBB" in c_v, f"content={str(c_v)[:40]}")
        r3, _ = count_loads(lambda: cg.search("更新后内容BBB 独有标记G3")[0])
        got = next((x[0].get("content") for x in r3
                    if x[0].get("id") == "mem_000"), None)
        check("G3b 覆写后检索命中新内容",
              got is not None and "BBB" in got, f"content={str(got)[:40]}")

        # G7 派生物缓存同口径：add 1 节点后旧条目 identity 不变（不重算）
        print("== G7 派生物缓存（_doc_norm_bigrams）不误伤 ==")
        cg.search(QUERY)                          # 装齐派生物缓存
        nbc = getattr(cg, "_norm_bigrams_cache", {})
        snap_nb = {k: v[1] for k, v in nbc.items()}
        check("G7pre 派生物缓存已装载", len(snap_nb) > 0,
              f"entries={len(snap_nb)}")
        cg.add("g7_new", "# 功能名：派生物样本\n# 正文：%s 派生物G7" % QUERY,
               layer="knowledge")
        cg.search(QUERY)
        nbc2 = getattr(cg, "_norm_bigrams_cache", {})
        same = all(nbc2[k][1] is snap_nb[k] for k in snap_nb if k in nbc2)
        check("G7a 写 1 节点后旧派生物条目零重算（identity 不变）",
              same and len(snap_nb) > 0, f"snap={len(snap_nb)}")

        # G5 删除保守整池失效（tombstone 无 path 可辨 → broad 兜底）
        print("== G5 删除保守整池失效 ==")
        cg._unstage("mem_001")
        left = len(cg.index["nodes"])
        _, n5 = count_loads(lambda: cg.search(QUERY)[0])
        check("G5a _unstage 后同查询整池重装（loads ≥ 剩余池规模）",
              n5 >= left, f"loads={n5} left={left}")

        # G6 _DirtyDict 簿记直断
        print("== G6 _DirtyDict 脏集簿记 ==")
        from md_cg.mdcg import _DirtyDict
        d = _DirtyDict()
        pg = getattr(d, "path_gen", None)
        bg = getattr(d, "broad_gen", None)
        check("G6a path_gen/broad_gen 簿记就位", pg is not None and bg is not None)
        if pg is not None:
            g0 = d.write_gen
            d["n1"] = {"path": "knowledge/n1.md", "layer": "knowledge"}
            g1 = d.write_gen
            check("G6b 带 path 标脏 → path_gen 记录、broad_gen 不动",
                  d.path_gen.get("knowledge/n1.md") == g1 > g0
                  and d.broad_gen == 0)
            d["n2"] = {"path": "knowledge/n2.md", "layer": "knowledge"}
            check("G6c 写另一 path 不推进前一 path 的脏代际",
                  d.path_gen.get("knowledge/n1.md") == g1
                  and d.path_gen.get("knowledge/n2.md") == d.write_gen)
            d["n3"] = None                          # tombstone：无 path 可辨
            check("G6d tombstone → broad_gen 保守推进",
                  d.broad_gen == d.write_gen > g1)
            d.clear()                               # flush 收尾形态
            check("G6e flush 形态 clear() 推进 write_gen 但不动 broad/path_gen",
                  d.write_gen > d.broad_gen
                  and d.path_gen.get("knowledge/n1.md") == g1)
            d["n4"] = 1                             # 非 entry 形态值
            check("G6f 无 path 可辨的值 → broad_gen 保守推进",
                  d.broad_gen == d.write_gen)
            d.clear(broad=True)                     # rebuild_index 收尾形态
            check("G6h clear(broad=True) → broad_gen 推进（rebuild 兜底）",
                  d.broad_gen == d.write_gen)
        gens = []
        d2 = _DirtyDict()
        d2["a"] = {"path": "x"}
        gens.append(d2.write_gen)
        d2["b"] = None
        gens.append(d2.write_gen)
        d2.clear()
        gens.append(d2.write_gen)
        d2["c"] = {"path": "y"}
        gens.append(d2.write_gen)
        check("G6g write_gen 单调不回退（P7b 口径保留）",
              gens == sorted(gens) and len(set(gens)) == 4, f"gens={gens}")

        # G8 「直写文件 + rebuild_index 收尾」写方（ccgc/crosscheck/backfill
        # 族）的缓存可见性：直写不经 _dirty 标脏，靠 rebuild 的
        # clear(broad=True) 整池兜底——回归面：全量套件 test_ccgc V4c/V5d
        # 曾因 rebuild 不失效而陈旧红。
        print("== G8 直写+rebuild 收尾写方缓存可见性 ==")
        cg.search(QUERY)                            # 热缓存
        e8 = cg.index["nodes"]["mem_002"]
        fm8, c8 = cg._read(e8)
        cg._write_node("mem_002", cg._node_disk_path(e8), fm8,
                       "# 功能名：直写样本\n# 正文：%s 直写后内容G8 独有标记" % QUERY)
        cg.rebuild_index()
        _, n8 = count_loads(lambda: cg.search(QUERY)[0])
        check("G8b rebuild 后整池重装（broad 兜底，loads ≥ 池规模）",
              n8 >= len(cg.index["nodes"]),
              f"loads={n8} pool={len(cg.index['nodes'])}")
        e8b = cg.index["nodes"]["mem_002"]
        fm8b, c8b = cg._read(e8b)                   # 缓存视图
        check("G8a 直写+rebuild 后缓存视图见新内容（不陈旧）",
              c8b is not None and "直写后内容G8" in c8b,
              f"content={str(c8b)[:40]}")

        # 收尾清理
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
