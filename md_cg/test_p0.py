# -*- coding: utf-8 -*-
"""md 认知图 P0 验收测试 · 逐条对应四个风险

跑法（用带 aeis 的解释器，基线对比需要真实 LayeredStore）：
    python -m md_cg.test_p0
"""
import os
import io
import sys
import json
import time
import sqlite3
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcg import (MdCG, TIER_BUCKET_LIKE, TIER_BUCKET_SCAN,
                        TIER_GLOBAL_LIKE, TIER_GLOBAL_SCAN)
from md_cg import routing
from md_cg.migrate import migrate

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "wisdom-book-cloud-new.db")
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "_md_cg_p0")
CONC_ROOT = ROOT + "_conc"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    return cond


# ---------------------------------------------------------------- 并发子进程入口
def _conc_worker(root, wid, n):
    # wid 形如 "0_3"（轮次_进程序号）；域按进程序号定，保证跨进程可复现
    dom = int(str(wid).split("_")[-1]) % 3
    cg = MdCG(root, autoflush=7)
    for i in range(n):
        cg.add(f"w{wid}_{i}", f"并发写入 worker{wid} 第{i}条 记忆内容",
               tags=[f"domain:并发域{dom}"], importance=0.5)
    cg.flush()
    cg.close()


def main():
    print("=" * 68)
    print("md 认知图 P0 验收 · 四风险逐条验证")
    print("=" * 68)

    # ============================================================ 风险1
    print("\n【风险1】分桶键退化 —— 归一化路由键 vs 文档原方案")
    # 迁移是幂等的（按 node id 原子覆盖），不需要清空目录重来
    cg, rep = migrate(DB, ROOT, verbose=False)
    print(f"  迁移：sqlite {rep['sqlite_nodes']} 节点 → md {rep['md_nodes']} 节点，"
          f"边 {rep['edges_total']} 条")
    check("迁移节点数等价", rep["count_equal"], f"{rep['sqlite_nodes']}=={rep['md_nodes']}")
    check("全量字段等价（content/tags/importance/edges）",
          rep["field_mismatches"] == 0, f"不一致 {rep['field_mismatches']} 个 {rep['samples']}")

    h = cg.health()
    print(f"  归一化路由键：{h['buckets']} 桶 / {h['total_nodes']} 节点，"
          f"最大桶 {h['max_bucket_share']:.1%}，单例桶率 {h['singleton_ratio']:.1%}，"
          f"期望扫描 {h['expected_scan']:.1%}")
    check("分区健康度自检通过", h["ok"], str(h.get("problems")))
    check("期望扫描占比 < 10%（条件路由确实非全量）", h["expected_scan"] < 0.10,
          f"{h['expected_scan']:.1%}")

    # 对照：文档原方案（原始四元组哈希）在同一批数据上的表现
    con = sqlite3.connect(DB)
    raw = {}
    for (cs,) in con.execute("select condition_space from nodes"):
        raw[routing.bucket_dir(json.dumps(json.loads(cs or "{}"), sort_keys=True))] = \
            raw.get(routing.bucket_dir(json.dumps(json.loads(cs or "{}"), sort_keys=True)), 0) + 1
    raw_h = routing.bucket_health(raw)
    print(f"  对照·原四元组哈希：{raw_h['buckets']} 桶，单例桶率 {raw_h['singleton_ratio']:.1%}")
    check("原方案确被判定为退化（自检能抓到）", not raw_h["ok"], str(raw_h["problems"]))

    # ============================================================ 风险2
    print("\n【风险2】检索情境入参 —— 有/无 context 的行为都必须是显式定义的")
    total = len(cg.index["nodes"])
    r_no, m_no = cg.search("知识点", layer="knowledge", k=10, context=None)
    check("无 context 时不做条件路由（bucket=None）", m_no["bucket"] is None)
    check("无 context 时走全量阶梯", m_no["tier"] in (TIER_GLOBAL_LIKE, TIER_GLOBAL_SCAN),
          m_no["tier"])

    ctx = {"tags": ["domain:计算机科学"]}
    r_ctx, m_ctx = cg.search("知识点", layer="knowledge", k=10, context=ctx)
    check("有 context 时命中路由桶", m_ctx["bucket"] is not None, m_ctx["bucket"])
    check("有 context 时扫描量远小于全库", m_ctx["scanned"] < total * 0.10,
          f"扫 {m_ctx['scanned']} / 全库 {total} = {m_ctx['scanned']/total:.1%}")
    check("写入侧与查询侧路由键同构（桶内确实有节点）", m_ctx["candidates"] > 0,
          f"候选 {m_ctx['candidates']}")

    # ============================================================ 风险3
    print("\n【风险3】回退阶梯 —— 桶内落空不得返回空，且必须自报命中层级")
    # 情境正确但查询词在该桶内不存在 → 必须继续往下走，而不是"分区隔离，预期无"
    r_fb, m_fb = cg.search("量子色动力学夸克禁闭", layer="knowledge", k=5, context=ctx)
    check("桶内落空后仍有结果（未被条件分区误杀）", len(r_fb) > 0,
          f"{len(r_fb)} 条 @ {m_fb['tier']}")
    check("回退结果自报层级", m_fb["tier"] in (TIER_BUCKET_SCAN, TIER_GLOBAL_LIKE,
                                              TIER_GLOBAL_SCAN), m_fb["tier"])
    # 情境完全不存在的桶 → 直接落到全量阶梯
    r_gh, m_gh = cg.search("能量守恒", layer="knowledge", k=5,
                           context={"tags": ["domain:根本不存在的域xyz"]})
    check("不存在的路由桶 → 落到全量阶梯而非返回空", len(r_gh) > 0,
          f"{len(r_gh)} 条 @ {m_gh['tier']}")
    tiers = {}
    for q in ("能量守恒", "二分查找", "贝塞尔不等式", "不存在词zzz999", "细胞呼吸"):
        _, m = cg.search(q, layer="knowledge", k=5, context=ctx)
        tiers[q] = m["tier"]
    print(f"  层级分布：{json.dumps(tiers, ensure_ascii=False)}")

    # ============================================================ 风险4
    print("\n【风险4】检索不得变成写操作")
    sample = list(cg.index["nodes"].values())[:200]
    before = {e["path"]: os.path.getmtime(os.path.join(ROOT, e["path"])) for e in sample}
    idx_before = os.path.getmtime(cg.index_path)
    ilog_before = sum(os.path.getsize(os.path.join(cg.index_log_dir, f))
                      for f in os.listdir(cg.index_log_dir)) \
        if os.path.isdir(cg.index_log_dir) else 0
    log_before = os.path.getsize(cg.access_log) if os.path.exists(cg.access_log) else 0
    time.sleep(0.05)
    for q in ("能量守恒", "二分查找", "知识点", "细胞", "函数"):
        cg.search(q, layer="knowledge", k=10, context=ctx)
    after = {p: os.path.getmtime(os.path.join(ROOT, p)) for p in before}
    check("检索未修改任何节点 .md（mtime 全不变）", before == after,
          f"变动 {sum(1 for p in before if before[p] != after[p])} 个")
    check("检索未重写索引快照", os.path.getmtime(cg.index_path) == idx_before)
    check("检索未写索引日志",
          (sum(os.path.getsize(os.path.join(cg.index_log_dir, f))
               for f in os.listdir(cg.index_log_dir))
           if os.path.isdir(cg.index_log_dir) else 0) == ilog_before)
    log_after = os.path.getsize(cg.access_log)
    check("访问计数写入了 append-only 日志", log_after > log_before,
          f"{log_before} → {log_after} 字节")
    counts, _last = cg.access_counts()
    check("日志可聚合出访问计数", len(counts) > 0, f"{len(counts)} 个节点有计数")
    hot = max(counts, key=counts.get)
    n_compact = cg.compact_access()
    fm = cg.get(hot)["frontmatter"]
    check("compact 后计数落盘到 frontmatter", fm.get("access_count", 0) > 0,
          f"{hot} access_count={fm.get('access_count')}，共合并 {n_compact} 节点")
    check("compact 后日志被截断", os.path.getsize(cg.access_log) == 0)

    # ============================================================ 索引可重建 / 并发
    print("\n【附加】索引可重建（单点风险）与多进程写")
    n_before = len(cg.index["nodes"])
    cg.compact_index()
    os.remove(cg.index_path)
    cg2 = MdCG(ROOT)
    check("删掉 _index.json 后能从 md 目录完整重建", len(cg2.index["nodes"]) == n_before,
          f"{len(cg2.index['nodes'])} == {n_before}")
    with open(cg2.index_path, "w", encoding="utf-8") as f:
        f.write("{ 这不是合法 json")
    cg3 = MdCG(ROOT)
    check("索引损坏能自愈重建", len(cg3.index["nodes"]) == n_before,
          f"{len(cg3.index['nodes'])}")

    # 并发跑多轮：索引竞态是间歇性的，单轮通过说明不了问题。
    # 各轮用不同 id 前缀写进同一目录（幂等，不需要清理），校验「本轮写入的 id
    # 是否一条不少地进了索引」——这比比总数更严格，能定位到是谁丢的。
    W, N, ROUNDS = 6, 40, 3
    ok_disk, ok_idx = True, True
    for rd in range(ROUNDS):
        procs = [subprocess.Popen([sys.executable, os.path.abspath(__file__),
                                   "--worker", CONC_ROOT, f"{rd}_{i}", str(N)],
                                  cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                 for i in range(W)]
        rc = [p.wait() for p in procs]
        expect = {f"w{rd}_{i}_{j}" for i in range(W) for j in range(N)}
        cgc = MdCG(CONC_ROOT)
        missing_idx = expect - set(cgc.index["nodes"])
        missing_disk = expect - set(cgc.rebuild_index()["nodes"])
        if not all(x == 0 for x in rc) or missing_disk:
            ok_disk = False
            print(f"    轮次 {rd}：磁盘缺 {len(missing_disk)} 条")
        if missing_idx:
            ok_idx = False
            print(f"    轮次 {rd}：索引缺 {len(missing_idx)} / {W * N} 条")
    check(f"多进程写：磁盘文件无丢失（{ROUNDS} 轮 × {W} 进程 × {N} 条）", ok_disk)
    check(f"多进程写：索引无覆盖丢失（{ROUNDS} 轮 × {W} 进程 × {N} 条）", ok_idx)

    # ============================================================ 基线对比
    print("\n【基线】md 版 vs sqlite 版 search_content 的召回一致性")
    try:
        from aeis.core import LayeredStore, MemoryLayer
        store = LayeredStore(DB)
        queries = ["能量守恒", "二分查找", "细胞呼吸", "贝塞尔不等式", "牛顿第二定律",
                   "数据结构 排序", "光合作用", "文明礼貌", "内力与截面法", "熵增"]
        rows = []
        for q in queries:
            sq = store.search_content(q, layers=[MemoryLayer.KNOWLEDGE], limit=10)
            sids = [n.id for n, _ in sq]
            mres, mmeta = cg.search(q, layer="knowledge", k=10, context=None, record=False)
            mids = [r[0]["id"] for r in mres]
            inter = len(set(sids) & set(mids))
            rec = inter / len(sids) if sids else 1.0
            rows.append((q, len(sids), len(mids), inter, rec, mmeta["tier"]))
        print(f"  {'query':<16}{'sqlite':>7}{'md':>5}{'交集':>6}{'recall@10':>11}  tier")
        for q, a, b, i, r, t in rows:
            print(f"  {q:<16}{a:>7}{b:>5}{i:>6}{r:>10.0%}  {t}")
        avg = sum(r[4] for r in rows) / len(rows)
        check("平均 recall@10 ≥ 0.9（无 context 时与 sqlite 同路径）", avg >= 0.9,
              f"avg={avg:.1%}")
    except ImportError as e:
        print(f"  [SKIP] 未装 aeis，跳过基线对比：{e}")

    print("\n" + "=" * 68)
    print(f"通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        _conc_worker(sys.argv[2], sys.argv[3], int(sys.argv[4]))
        sys.exit(0)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
