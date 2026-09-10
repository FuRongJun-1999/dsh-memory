# -*- coding: utf-8 -*-
"""§七 · 召回分池与降权（P43 设计态验收）。

对照 `docs/认知图_G4-G8缺口裁定单_v0.1.md` §七：索引/产物类节点（`code_`/`doc_`）
词面更易命中，在 `GLOBAL_CAP` 单条截断点**先把知识节点挤掉**。本项把截断额度
**显式分池**（不是抬高额度），并立四条纪律。

覆盖：
  (1) 契约与默认关闭：catalog/resolve/from_env，`pools=None` 即原行为；
  (2) 硬约束一 · 不隐性提高上限：cap_ratio 之和必须 == 1.0（坏表一律 PoolError）；
  (3) 额度守恒：caps/allocate/take 的总账恒 == total（多组 total 实测）；
  (4) 默认关闭 ≡ 原行为：平截逐位一致、权重恒 1.0、meta 不伪造池账；
  (5) 归池确定性：id 前缀 / 标签 / 负层三类归池，重复调用同结果；
  (6) 分池生效：小额度下索引类不再吃满截断额度（前后张数 + 池账 `cands/lost` + 结果构成口径对比）；
  (7) 空池回流：未用额度回流前序池，`taken` 如实回报，总账不增；
  (8) 硬约束二 · 降权显式可复算：命中分 == 原分 × 表内 weight；
  (9) 硬约束四 · 口径先冻结 + **口径敏感性自检**：P95/中位/截断率/截断损失 + `index_share`/`pool_lost_rate`；
      并断言「成本口径不敏感（delta 恒 0、被标 insensitive）但结果构成口径敏感」——量具先于测量；
  (10) 复测只读：measure/compare 前后**全库文件逐字节不变**；
  (11) 同口径可比：compare 前(关)/后(开) 同查询集 + delta + 副作用归因；
  (12) 坏表不静默降级：非法权重表抛错，而不是当作「关闭」悄悄跑完；
  (13) MCP 接入：mdcg_search 透传 pools + sustain pooling/pool_bench/pool_compare；
  (14) 未知 action 不静默成功。

独立临时根，重跑 ≡ 首跑。运行：python -m md_cg.test_p43_pooling
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile

from . import pooling as PL
from .mdcos import MdCGOS
from .mcp_server import KERNEL_TOOLS, call_tool
import md_cg.mdcg as M
import md_cg.mdcos as MO

PASS = FAIL = 0
FAILS = []

BODY = "召回截断 索引 分池 内容"
QUERY = "召回截断"


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  [FAIL] {label}")


def _snapshot(root):
    """全库文件 → sha256（用于「巡检只读」断言）。"""
    snap = {}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                with open(p, "rb") as f:
                    snap[rel] = hashlib.sha256(f.read()).hexdigest()
            except OSError:
                snap[rel] = "<unreadable>"
    return snap


def _mk(root):
    """6 个索引类（code_/doc_）+ 10 个知识类，正文同源 → 词面完全等价竞争。"""
    cg = MdCGOS(root, actor="test")
    for i in range(4):
        cg.add(f"code_{i}", f"# 功能名：索引条目 {i}\n# 生效条件：条件 I\n\n{BODY} {i}\n",
               layer="knowledge", tags=["index"])
    for i in range(2):
        cg.add(f"doc_{i}", f"# 功能名：文档索引 {i}\n# 生效条件：条件 D\n\n{BODY} {i}\n",
               layer="knowledge", tags=["index"])
    for i in range(10):
        cg.add(f"kp_{i}", f"# 功能名：知识 {i}\n# 生效条件：条件 K\n\n{BODY} {i}\n",
               layer="knowledge")
    cg.add("n_rej", f"# 功能名：被否决\n# 生效条件：条件 R\n\n{BODY} 否\n",
           layer="rejected")
    cg.flush()
    return cg


def _patch_cap(value):
    """把全局额度换成小值以逼出截断点；返回还原函数。"""
    old = (M.GLOBAL_CAP, MO.GLOBAL_CAP)
    M.GLOBAL_CAP = MO.GLOBAL_CAP = value
    return lambda: (setattr(M, "GLOBAL_CAP", old[0]),
                    setattr(MO, "GLOBAL_CAP", old[1]))


def _count(res, prefix):
    return sum(1 for r in res if r[0]["id"].startswith(prefix))


def main():
    print("md 认知图 P43 验收 · §七 召回分池与降权（不隐性提高上限）")
    print("=" * 70)
    root = None
    try:
        root = tempfile.mkdtemp(prefix="mdcg_p43_")
        cg = _mk(root)
        cfg = PL.resolve(True)

        # ============================================= (1) 契约与默认关闭
        print("\n(1) 契约与默认关闭")
        cat = PL.catalog()
        ok(cat["pools"] == ["knowledge", "index", "negative"], "(1) catalog 三池齐备")
        ok("off" in cat["default"], "(1) catalog 明示默认关闭")
        ok(cat["cap_ratio_sum"] == 1.0, "(1) 内置表额度之和为 1.0")
        ok(PL.resolve(None) is None and PL.resolve(False) is None,
           "(1) resolve(None/False) → 关闭")
        ok(set(PL.resolve(True)) == set(PL.POOL_ORDER), "(1) resolve(True) → 三池")
        old_env = os.environ.pop(PL.ENV_SWITCH, None)
        ok(PL.from_env(None) is None, "(1) 环境变量未设 → 关闭")
        ok(PL.from_env(cfg) is cfg, "(1) 显式传表优先于环境变量")
        os.environ[PL.ENV_SWITCH] = "1"
        ok(PL.from_env(None) is True, "(1) 环境变量=1 → 启用内置表")
        if old_env is None:
            os.environ.pop(PL.ENV_SWITCH, None)
        else:
            os.environ[PL.ENV_SWITCH] = old_env

        # ===================================== (2) 硬约束一 · 不隐性提高上限
        print("\n(2) 硬约束一 · 额度之和不为一 → 拒绝")
        bad_cases = {
            "和 0.8": {"knowledge": {"cap_ratio": 0.5}, "index": {"cap_ratio": 0.2},
                       "negative": {"cap_ratio": 0.1}},
            "和 1.1": {"knowledge": {"cap_ratio": 0.8}, "index": {"cap_ratio": 0.2},
                       "negative": {"cap_ratio": 0.1}},
            "缺池": {"knowledge": {"cap_ratio": 1.0}, "index": {"cap_ratio": 0.0}},
            "比率为 0": {"knowledge": {"cap_ratio": 1.0}, "index": {"cap_ratio": 0.0},
                        "negative": {"cap_ratio": 0.0}},
            "权重非正": {"knowledge": {"cap_ratio": 1.0, "weight": 0},
                        "index": {"cap_ratio": 0.0}, "negative": {"cap_ratio": 0.0}},
        }
        raised = 0
        for label, tbl in bad_cases.items():
            try:
                PL.validate(tbl)
            except PL.PoolError:
                raised += 1
        ok(raised == len(bad_cases), f"(2) {len(bad_cases)} 类坏表全部 PoolError")
        ok(PL.validate(PL.WEIGHTS)["index"]["weight"] == 0.6, "(2) 合法表原样通过")
        ok(abs(sum(PL.WEIGHTS[p]["cap_ratio"] for p in PL.POOL_ORDER) - 1.0) < 1e-9,
           "(2) 内置表额度之和恰为 1.0")

        # ============================================== (3) 额度守恒
        print("\n(3) 额度守恒（总账恒 == total）")
        totals_ok = all(sum(PL.caps(t, cfg).values()) == t
                        for t in (3, 4, 8, 20, 100, 500))
        ok(totals_ok, "(3) caps 各池之和恒等于 total（3/4/8/20/100/500）")
        ok(PL.plan(20, True)["cap_sum"] == 20, "(3) plan.cap_sum 与 total 一致")
        docs = [(f"d{i}", {}) for i in range(30)]
        ok(len(PL.allocate(docs, 7, pools=True)) <= 7, "(3) allocate 不超额度")
        ok(len(PL.allocate(docs, 100, pools=True)) <= 30, "(3) 候选不足时不凭空造条目")

        # ============================================ (4) 默认关闭 ≡ 原行为
        print("\n(4) 默认关闭 ≡ 原行为")
        ok(PL.allocate(docs, 5, pools=None) == docs[:5], "(4) 关闭态逐位等于平截")
        ok(PL.weight_of("code_x", {}, None) == 1.0, "(4) 关闭态权重恒 1.0")
        _res, meta_off = cg.search(QUERY, k=20, record=False)
        ok(meta_off["pools"]["enabled"] is False, "(4) 关闭态 meta 如实报 enabled=False")
        ok(not ({"taken", "cands", "lost"} & set(meta_off["pools"])),
           "(4) 关闭态不伪造池账 taken/cands/lost")
        ok(meta_off["pre_cap"] >= 0 and meta_off["cap"] == M.GLOBAL_CAP,
           "(4) 关闭态仍暴露 pre_cap/cap（口径不变）")

        # ============================================== (5) 归池确定性
        print("\n(5) 归池确定性")
        ok(PL.pool_of("code_a") == "index", "(5) code_ 前缀 → 索引池")
        ok(PL.pool_of("doc_b") == "index", "(5) doc_ 前缀 → 索引池")
        ok(PL.pool_of("kp_c") == "knowledge", "(5) 普通 id → 知识池")
        ok(PL.pool_of("n1", {"layer": "rejected"}) == "negative",
           "(5) rejected 层 → 负记忆池（层优先于 id 前缀）")
        ok(PL.pool_of("misc", {"tags": ["index"]}) == "index", "(5) tags 标记 → 索引池")
        ok(PL.pool_of("code_x", {"layer": "unresolved"}) == "negative",
           "(5) 层优先：code_ 落在 unresolved 仍归负池")
        ok(len({PL.pool_of(f"kp_{i}") for i in range(50)}) == 1,
           "(5) 批量归池无抖动")

        # ============================================== (6) 分池生效
        print("\n(6) 分池生效（小额度下不再被索引类吃满）")
        restore = _patch_cap(8)
        try:
            off, m_off = cg.search(QUERY, k=20, record=False)
            on, m_on = cg.search(QUERY, k=20, record=False, pools=True)
        finally:
            restore()
        n_off, n_on = _count(off, "code_") + _count(off, "doc_"), \
            _count(on, "code_") + _count(on, "doc_")
        ok(n_off == 6 and n_on == 2,
           f"(6) 索引类入榜数 6 → 2（实得 off={n_off} on={n_on}）")
        ok(_count(on, "kp_") == 6, f"(6) 知识类入榜数 2 → 6（实得 {_count(on, 'kp_')}）")
        # 注：_emit 会在额度之外追加减负覆盖条目（covered_neg），故入榜总长 = 额度数 + 覆盖数；
        # 分池只重分配，判定口径应为「开关前后总长一致」。
        cov = len(m_off["covered_neg"])
        ok(len(off) == len(on) and (len(on) - cov) == 8,
           f"(6) 总入榜条数不变（分池只重分配；实得 off={len(off)} "
           f"on={len(on)} 覆盖={cov}）")
        ok(m_off["pre_cap"] == m_on["pre_cap"] == 16, "(6) 截断前候选数前后一致")
        ok(m_on["pools"]["caps"] == {"knowledge": 5, "index": 2, "negative": 1},
           f"(6) 计划额度可复算（实得 {m_on['pools']['caps']}）")
        ok(m_on["pools"].get("lost") == {"knowledge": 4, "index": 4, "negative": 0},
           f"(6) 池账含被挤掉数 lost（实得 {m_on['pools'].get('lost')}）")
        ok(m_on["pools"].get("cands") == {"knowledge": 10, "index": 6, "negative": 0},
           f"(6) 池账含各池候选数 cands（实得 {m_on['pools'].get('cands')}）")

        def _ishare(res):
            ids = [r[0]["id"] for r in res]
            return sum(1 for i in ids if PL.pool_of(i) == "index") / max(1, len(ids))
        ok(_ishare(on) < _ishare(off),
           f"(6) 结果构成口径对分池敏感（索引占比 {_ishare(off):.2f} → {_ishare(on):.2f}）")

        # ============================================== (7) 空池回流
        print("\n(7) 空池回流（未用额度给前序池，总账不增）")
        taken = m_on["pools"]["taken"]
        ok(sum(taken.values()) == 8, f"(7) 各池实取之和 == 8（实得 {sum(taken.values())}）")
        ok(taken["negative"] == 0, "(7) 空池实取 0（负池无候选）")
        ok(taken["knowledge"] == 6 > m_on["pools"]["caps"]["knowledge"],
           "(7) 负池未用额度回流给知识池")
        ok(m_on["pools"]["cap_sum"] == 8, "(7) 回流不改计划总账")
        docs_idx = [(f"code_{i}", {}) for i in range(5)]
        ok(len(PL.allocate(docs_idx, 4, pools=True)) == 4,
           "(7) 单池候选充足时额度被用满")

        # ============================================== (8) 降权可复算
        print("\n(8) 硬约束二 · 降权显式可复算")
        sc = {r[0]["id"]: round(r[1], 6) for r in on}
        ok(sc["code_0"] == round(0.6 * 1.0, 6), f"(8) 索引类命中分 == 0.6（实得 {sc.get('code_0')}）")
        ok(max(sc[f"kp_{i}"] for i in range(6)) == 1.0, "(8) 知识类命中分不被削")
        ok(PL.weight_of("code_x", {}, True) == PL.WEIGHTS["index"]["weight"],
           "(8) weight_of 与表内系数一致")
        alt = {"knowledge": {"cap_ratio": 0.5, "weight": 1.0},
               "index": {"cap_ratio": 0.4, "weight": 0.3},
               "negative": {"cap_ratio": 0.1, "weight": 0.5}}
        on2, _m2 = cg.search(QUERY, k=20, record=False, pools=alt)
        sc2 = {r[0]["id"]: round(r[1], 6) for r in on2}
        ok(sc2["code_0"] == 0.3, f"(8) 换表即换行为（实得 {sc2.get('code_0')}）")
        ok(PL.caps(10, PL.resolve(alt)) == {"knowledge": 4, "index": 4, "negative": 2},
           f"(8) 换表额度同步可复算（实得 {PL.caps(10, PL.resolve(alt))}）")

        # ========================================= (9)(10) 口径 + 只读
        print("\n(9) 硬约束四 · 先冻结口径，再复测")
        before = _snapshot(root)
        meas = PL.measure(cg, [QUERY], k=5, pools=True)
        for key in ("p95_scanned", "p50_scanned", "mean_candidates",
                    "truncation_rate", "truncation_loss", "tiers"):
            ok(key in meas, f"(9) 口径字段齐备：{key}")
        ok(meas["readonly"] is True, "(9) 明确标注 read-only")
        ok(meas["proxy"] is True, "(9) 查询集来自库内 → 标注 proxy")
        ok(meas["n_queries"] == 1 and meas["pools"]["enabled"] is True,
           "(9) 复测在启用态下执行")
        cmp_rep = PL.compare(cg, [QUERY], k=5)
        after = _snapshot(root)
        ok(before == after, "(10) 复测前后全库文件逐字节不变（只读）")
        ok(cmp_rep["before"]["pools"]["enabled"] is False
           and cmp_rep["after"]["pools"]["enabled"] is True,
           "(11) compare 前为关闭态、后为启用态")
        ok(all(k in cmp_rep["delta"] for k in
               ("p95_scanned", "mean_candidates", "truncation_loss")),
           "(11) delta 覆盖 P95/候选数/截断损失")
        ok(bool(cmp_rep["attribution"]), "(11) 副作用有归因说明")
        qs = PL.bench_queries(cg, n=5)
        ok(len(qs) == 5 and all(q.strip() for q in qs), f"(11) 确定性取样 {len(qs)} 条")
        ok(PL.bench_queries(cg, n=5) == qs, "(11) 取样可复现")

        # ---- 口径敏感性自检：小额度下「敏感口径」必须动、成本口径可不动 ----
        restore = _patch_cap(8)
        try:
            m_base = PL.measure(cg, [QUERY], k=20, pools=None)
            m_en = PL.measure(cg, [QUERY], k=20, pools=True)
            cmp2 = PL.compare(cg, [QUERY], k=20)
        finally:
            restore()
        ok(m_en["index_share"] < m_base["index_share"],
           f"(9) 结果构成对分池敏感（{m_base['index_share']:.2f} → {m_en['index_share']:.2f}）")
        ok(m_base["pool_lost_rate"] is None and m_en["pool_lost_rate"] is not None,
           f"(9) 池级截断损失仅启用态可算（关={m_base['pool_lost_rate']} "
           f"开={m_en['pool_lost_rate']}）")
        ok(cmp2["delta"]["index_share"] < 0 and "index_share" in cmp2["sensitive_keys"],
           f"(9) 自检把 index_share 归入敏感口径（实得 {cmp2['sensitive_keys']}）")
        ok(cmp2["delta"]["truncation_rate"] == 0
           and "truncation_rate" in cmp2["insensitive_keys"],
           "(9) 成本口径（全局截断率）不敏感被显式标出，不误读为无效")

        # ======================================= (12) 坏表不静默降级
        print("\n(12) 坏表不静默降级")
        raised = 0
        try:
            cg.search(QUERY, k=5, record=False,
                      pools={"knowledge": {"cap_ratio": 0.5},
                             "index": {"cap_ratio": 0.5},
                             "negative": {"cap_ratio": 0.5}})
        except PL.PoolError:
            raised += 1
        ok(raised == 1, "(12) 非法权重表直接抛错（不当成关闭）")
        ok(isinstance(PL.PoolError("x"), ValueError), "(12) PoolError 兼容 ValueError")

        # ============================================= (13) MCP 接入
        print("\n(13) MCP 接入")
        pc = call_tool(cg, "cg", {"op": "sustain", "action": "pooling"})
        ok(pc["cap_ratio_sum"] == 1.0 and pc["default"].startswith("off"),
           "(13) sustain pooling 自描述可用")
        bench = call_tool(cg, "cg", {"op": "sustain", "action": "pool_bench",
                                     "queries": [QUERY], "k": 5, "limit": 5})
        ok(bench["readonly"] is True and bench["proxy"] is True,
           "(13) sustain pool_bench 只读 + proxy")
        ab = call_tool(cg, "cg", {"op": "sustain", "action": "pool_compare",
                                  "queries": [QUERY], "k": 5, "limit": 5})
        ok(ab["delta"]["mean_candidates"] >= 0, "(13) sustain pool_compare 给 delta")
        cat = call_tool(cg, "cg", {"op": "sustain", "action": "catalog"})
        for act in ("pooling", "pool_bench", "pool_compare"):
            ok(act in cat["actions"], f"(13) sustain catalog 含 action={act}")
        sres = call_tool(cg, "mdcg_search", {"query": QUERY, "k": 5, "pools": True})
        ok(sres["meta"]["pools"]["enabled"] is True, "(13) mdcg_search 透传 pools=True")
        ok("taken" in sres["meta"]["pools"], "(13) mdcg_search 回报各池实取数")
        sres2 = call_tool(cg, "mdcg_search", {"query": QUERY, "k": 5})
        ok(sres2["meta"]["pools"]["enabled"] is False,
           "(14) 不传 pools 的既有调用方零影响")
        tool = [t for t in KERNEL_TOOLS if t["name"] == "cg"][0]
        props = tool["inputSchema"]["properties"]
        ok("pools" in props and "queries" in props, "(13) schema 暴露 pools/queries")
        blob = tool["description"] + props["op"]["description"] \
            + props["action"]["description"]
        ok("pool_bench" in blob, "(13) 描述含 pool_bench（防漂移）")
        raised = 0
        try:
            cg.search(QUERY, k=5, record=False, pools={"knowledge": {"cap_ratio": 2.0}})
        except PL.PoolError:
            raised += 1
        ok(raised == 1, "(14) MCP 路径同样拒绝坏表（不静默）")
        raised = 0
        try:
            call_tool(cg, "cg", {"op": "sustain", "action": "pool_nope"})
        except ValueError:
            raised += 1
        ok(raised == 1, "(14) 未知 action 不静默成功")

        print("\n" + "=" * 70)
        print(f"结果：PASS {PASS} / FAIL {FAIL}")
        if FAILS:
            print("失败项：")
            for f in FAILS:
                print(f"  - {f}")
        return 0 if FAIL == 0 else 1
    finally:
        if root:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
