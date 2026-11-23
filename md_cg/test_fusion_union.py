# -*- coding: utf-8 -*-
"""issue #1005 补充②：配额并集融合（fusion="union"）的口径守卫。

背景（测评端 2026-11-23 实测，29 条候选 / 22 题 / 同一判分器）：
    加权 RRF(0.5/0.5) 77.3%  <  RRF(0.7/0.3) 81.8%  <  配额并集 86.4%
机理：「一路排 1、另一路排 20」的条目融合后掉出前 8，而各取前 4 再合并能保住
两路最好的候选。

本文件守两件事：
1. union_fuse 的**口径**（交错顺序、去重、prov、q 边界）——纯函数，逐值断言；
2. search_rrf 的**接线**（只在显式 fusion="union" 时落 meta["union"]；单路 / 池过
   大时如实报 reason 并回退既有 RRF 口径）。

不适用范围：本文件不测「22 题全中率」，那需要测评端的语料（不在本仓）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import md_cg.mdcos as M
from md_cg.mdcos import MdCGOS

FAILS = []


def ok(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def eq(a, b, msg):
    ok(a == b, "%s（实得 %r）" % (msg, a) if a != b else msg)


def rrf_score(rank, w=1.0):
    return w / (M.RRF_K + rank)


def main():
    print("[A] union_fuse 口径")
    ranked = {"lexical": ["a", "b", "c", "d", "e"],
              "entity": ["c", "a", "f"]}
    order, scores, prov = M.union_fuse(ranked, q=2)
    eq([n for n, _p, _r in order], ["a", "c", "b"],
       "交错序：两路各取前 2，同 nid 只留首次出现（a 在 entity#2 去重）")
    eq([(_p, _r) for _n, _p, _r in order[:2]], [("lexical", 1), ("entity", 1)],
       "定点：首轮先 lexical#1 再 entity#1（路序=传入顺序）")
    ok(all(scores[order[i][0]] > scores[order[i + 1][0]] for i in range(len(order) - 1)),
       "分数严格递减（下游 -score 排序即等于本顺序）")
    eq([p["path"] for p in prov["a"]], ["lexical", "entity"],
       "prov 记**各路**名次（a 在 lexical#1、entity#2，均在 q=2 窗口内）")
    eq([p["path"] for p in prov["c"]], ["entity"],
       "prov 不记窗口外名次（c 在 lexical 是第 3，超 q=2）")
    eq(M.union_fuse({"lexical": ["a"]}, q=4)[0], [("a", "lexical", 1)],
       "单路输入退化为该路前 q")
    eq(M.union_fuse({"lexical": ["a"]}, q=0)[0], [], "q=0 返回空（不静默取默认值）")
    eq(M.union_fuse({}, q=4)[0], [], "空输入返回空")

    print("[B] 口径对照：并集保住单路独有候选，加权 RRF 会把它稀释掉")
    # 现场形态：X 只在 entity 排 1；Y 在 lexical 与 bucket 都排 1。
    # 两路共识的 Y 在 sum 下必然压过单路独有的 X；并集把 X 排在第 2 位。
    x, y = "X_single_route", "Y_two_routes"
    ranked2 = {"lexical": [y] + ["l%d" % i for i in range(1, 25)],
               "entity": [x, y]}
    sum_rrf = {}
    for name, ids in ranked2.items():
        for r, nid in enumerate(ids, 1):
            sum_rrf[nid] = sum_rrf.get(nid, 0.0) + rrf_score(r)
    ok(sum_rrf[y] > sum_rrf[x], "sum 口径下双路共识的 Y 压过单路独有的 X（RRF 的已知稀释）")
    order2, _s2, _p2 = M.union_fuse(ranked2, q=4)
    ids2 = [n for n, _p, _r in order2]
    ok(ids2.index(x) < 2, "union 口径下 X 落在第 2 位（q=4 内两路最优都在）")
    ok(set(ids2[:4]) >= {x, y}, "union 前 4 位同时含 X 与 Y")

    print("[C] 接线：只有显式 fusion='union' 才落 meta['union']")
    tmp = tempfile.mkdtemp(prefix="mdcg_union_")
    root = os.path.join(tmp, "kg")
    os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
    for nid, body in (("mem_u001", "量子纠缠 实验 记录：纠缠对在 4K 下退相干"),
                      ("mem_u002", "水果 与 蔬菜 的 分类 笔记")):
        p = os.path.join(root, "knowledge", nid + ".md")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("---\nid: %s\nlayer: knowledge\nimportance: 0.5\n"
                    "tags: [\"demo\"]\n---\n\n%s\n" % (nid, body))
    cg = MdCGOS(root=root)
    try:
        cg.rescan() if hasattr(cg, "rescan") else None
    except Exception:
        pass
    res_u, meta_u = cg.search_rrf("量子", k=5, paths=("lexical",), judge=False,
                                  record=False, fusion="union")
    ok("union" in meta_u, "fusion='union' 时 meta 落 union 键")
    info = meta_u.get("union") or {}
    ok(info.get("enabled") is False and info.get("reason") == "single_path",
       "单路时如实报 disabled/single_path（不假装启用）")
    res_s, meta_s = cg.search_rrf("量子", k=5, paths=("lexical",), judge=False,
                                  record=False, fusion="sum")
    ok("union" not in meta_s, "默认 sum 口径不落 union 键（既有 meta 逐位不变）")
    eq([r[0]["id"] for r in res_u], [r[0]["id"] for r in res_s],
       "单路 + union 与 sum 的返回一致（并集不启用时不改排序）")
    # 加一条**只有标签命中**的节点：让 entity 路也产出候选（两路都非空）。
    p3 = os.path.join(root, "knowledge", "mem_u003.md")
    with open(p3, "w", encoding="utf-8", newline="\n") as f:
        f.write("---\nid: mem_u003\nlayer: knowledge\nimportance: 0.6\n"
                "tags: [\"量子\"]\n---\n\n（正文不含查询词，只靠标签命中）\n")
    cg2 = MdCGOS(root=root)
    res_e, meta_e = cg2.search_rrf("量子", k=5, paths=("lexical", "entity"),
                                   judge=False, record=False, fusion="union")
    info_e = (meta_e or {}).get("union") or {}
    ok(info_e.get("enabled") is True, "两路都有候选时并集启用（实得 %r）" % info_e)
    ok(set(info_e.get("paths") or []) == {"lexical", "entity"},
       "meta 如实报参与并集的路（%r）" % (info_e.get("paths"),))
    ok(len(res_e) >= 2, "并集把两路的最优候选都带进结果（%d 条）" % len(res_e))
    res_t, meta_t = cg2.search_rrf("量子", k=5, paths=("lexical", "entity"),
                                   judge=False, record=False, fusion="union",
                                   union_max_candidates=0)
    info_t = (meta_t or {}).get("union") or {}
    eq(info_t.get("reason"), "pool_too_large",
       "池超阈值时回退 RRF 并写明 reason=pool_too_large")
    # 并集是**替换**而非叠加：分数必须是 1/(1+pos) 的序列，不是两路 RRF 之和。
    ok(len(res_e) >= 2, "并集模式下结果非空（%d 条）" % len(res_e))
    _expect = [round(1.0 / (1.0 + i), 6) for i in range(len(res_e))]
    eq([r[1] for r in res_e], _expect,
       "并集分数按位次严格递减（替换 RRF 之和，不是叠加）")
    # 配置笔误护栏：q=0 不得清空结果。
    _rq, _mq = cg2.search_rrf("量子", k=5, paths=("lexical", "entity"),
                              judge=False, record=False, fusion="union",
                              union_q=0)
    _iq = (_mq or {}).get("union") or {}
    eq(_iq.get("reason"), "invalid_q", "q=0 判非法并回退（不静默清空结果）")
    ok(len(_rq) >= 1, "q=0 时结果仍非空（fail-safe，%d 条）" % len(_rq))
    # 缓存键含 union 口径：同参数第二次调用命中缓存且 meta 仍带 union 键。
    _r2, _m2 = cg2.search_rrf("量子", k=5, paths=("lexical", "entity"),
                              judge=False, record=False, fusion="union")
    ok("union" in (_m2 or {}), "热缓存命中时 meta 仍带 union 键（不丢口径）")

    # "auto"：小库自动走并集、超阈值自动回退——同一个入口按库规模分档。
    _ra, _ma = cg2.search_rrf("量子", k=5, paths=("lexical", "entity"),
                              judge=False, record=False, fusion="auto")
    ok(((_ma or {}).get("union") or {}).get("enabled") is True,
       "fusion='auto' 在小库上等同并集")
    _rb, _mb = cg2.search_rrf("量子", k=5, paths=("lexical", "entity"),
                              judge=False, record=False, fusion="auto",
                              union_max_candidates=0)
    eq(((_mb or {}).get("union") or {}).get("reason"), "pool_too_large",
       "fusion='auto' 超阈值自动回退 RRF（不静默改排序）")

    print()
    if FAILS:
        print("FAILED %d 项" % len(FAILS))
        for f in FAILS:
            print("  - " + f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
