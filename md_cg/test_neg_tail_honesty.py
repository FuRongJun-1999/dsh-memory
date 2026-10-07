# -*- coding: utf-8 -*-
# 功能名：负覆盖条目诚实化（H10 ①②③④）· 基类与生产路径同口径（H7⑦）· 飞轮建单只限
#         REJECT（H11⑥）· 工单语义 slug 身份与现场刷新（⑤⑦）· CCG 哨兵直连入口同口径（⑧）
#         · M3 呼叫点传节点总数
# 生效条件：md_cg/mdcg.py 的 `_neg_tail`/`_primary_slots`/`_emit`/`_compute_d`/
#           `search` 候选收集/`add_unresolved`/`_refresh_unresolved`/`_ticket_slug`/
#           `health`·`flywheel_step`、md_cg/consistency.py 的 `check`（哨兵漏斗 +
#           `FLYWHEEL_TRIGGERS`）、md_cg/routing.py 的 `bucket_health(counts,
#           total_nodes)`、md_cg/mdcos.py 的 `_candidates` 负层过滤（真源导入
#           `NEG_ROUTE_LAYERS`，不留同值副本——C6/C7）同口径时成立；
#           沙箱条件：所有库根一律 tempfile.mkdtemp，
#           绝不触在役库/在役服务。
# 子功能：
#   A 负覆盖尾诚实化：①分数＝哨兵 0.0 + 负性走独立字段（不再冒充 1.0 候选）
#     ②条数计入 k 预算（len(results) ≤ k，含 k=0/1 边界）④位置在尾部、真 id 走
#     `node_id` 字段（`id` 仍是落盘路径——既有消费者口径一字不动）
#     ＋ H10 修订（2026-10-07，缺陷：k ≤ 提示数时真实命中归零）：**真实命中优先**
#     ——提示条数＝min(NEG_COVERAGE_MAX, max(0, k − 真实命中数))，不是 min(3, k)。
#     故 A 组的尾断言改在 **k=5**（3 真命中 + 2 尾条正好用满 k）取样；A5 除
#     「总数 ≤ k / k_budget 逐位一致」外，钉住「主结果条数＝min(k, 真实命中数)」
#     （改前 k=2/3 时为 0——本组对旧口径的判别力所在）。
#   B `_compute_d` 分母只数真实候选（提示条目不进分母，D 不再被虚高）
#   C 基类与生产路径同口径：负记忆/目标槽不进正排，同一负节点不再双列
#     （负层元组真源单点：mdcos 直接导入 mdcg.NEG_ROUTE_LAYERS，不留同值副本）
#   D 飞轮只对真冲突 REJECT 建单；DEFER/BLINDSPOT 不再自动建单（判定照旧返回）
#   E CCG 哨兵「不适用条件：无」的直连入口形态（consistency.check / cg.add）与
#     mdcos 入口同口径，且真负条件仍判冲突（防放宽）
#   F 工单身份＝语义 slug（同 slug 即同工单）；同题再检出时「# 现场：」刷新、
#     id/created_at 不变、零新建、同输入零写盘
#   G M3：节点总数传进 bucket_health（空库 vs 有节点零分桶可区分）
# 执行：python -X utf8 -m md_cg.test_neg_tail_honesty
#       python -X utf8 -m md_cg.test_neg_tail_honesty --drop-fix=all
#       python -X utf8 -m md_cg.test_neg_tail_honesty --drop-fix=neg_score
# 验证方式：本文件自跑（自带断言计数与退出码 rc=0/1）；定点变异自证见 --drop-fix
#           （把每处修复逐点抽回改动前语义 → 本守卫必红，且红项必须覆盖预期集合；
#           恢复后必须转绿且无残余）。
# 不适用条件：情感交互｜闲聊｜纯查询无改动；「对方节点被覆写但工单**未**重发」这一
#           形态不在本守卫面内（无新鲜现场数据可依，重算需持久化结构化现场——见
#           FixReport 的 gaps）；负覆盖条目在 MCP 结果面的呈现（`_node_view` 只透
#           id/path/frontmatter/content）不在本文件面内，属调用方渲染层。
import hashlib
import inspect
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import consistency, mdcos, nodefile, routing   # noqa: E402
from md_cg import mdcg as _mdcg                           # noqa: E402
from md_cg.mdcos import MdCGOS                            # noqa: E402

PASS = 0
FAIL = 0
FAILS = []
_RUN = [0]
_SANDBOX = tempfile.mkdtemp(prefix="mdcg_neghon_")

QUERY = "牛肉面 汤头"
NEG_REJ = "# 假设：牛肉面 用工业浓汤宝\n# 否决原因：偏离手工工艺\n"
NEG_UNR = "# 问题：牛肉面 汤色发黑\n# 目标：（未设定）\n"
SENT = ("# 功能名：部署面端口约定\n"
        "# 生效条件：载体/位置：prod 集群；方法：部署清单核对；约束：无\n"
        "# 子功能：登记各监听端口\n# 执行：核对 manifest 的 ports 段\n"
        "# 验证方式：test\n"
        "# 不适用条件：无\n\n网关监听端口 8080/HTTP\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _mk(tag):
    return MdCGOS(os.path.join(_SANDBOX, "lib_%s_r%d" % (tag, _RUN[0])),
                  autoflush=0)


def _neg_lib(tag):
    """3 正候选（含查询词）+ 2 负节点（rejected/unresolved，含查询词）。"""
    cg = _mk(tag)
    for i in range(3):
        cg.add("mem_%d" % i,
               "# 功能名：样本%d\n# 子功能：牛肉面 汤头 熬制 工艺\n" % i,
               layer="knowledge")
    cg.add("r0", NEG_REJ, layer="rejected", verification_basis="test")
    cg.add("u0", NEG_UNR, layer="unresolved", verification_basis="data")
    cg.flush()
    return cg


#: CCG 六要素齐备 + 生效条件命中查询词 → 资格判定 ACCEPT（B 组要一个真「有效命中」，
#: 否则 accept=0 时「含尾/不含尾」两种分母都得 1.0，对照断言没有判别力）。
ACCEPT_NODE = ("# 功能名：汤头工艺基线\n"
               "# 生效条件：牛肉面 汤头\n"
               "# 子功能：登记熬制工艺\n"
               "# 执行：按基线核对\n"
               "# 验证方式：test\n"
               "# 不适用条件：工业化浓汤宝\n\n"
               "牛肉面 汤头 熬制 工艺：小火 6 小时\n")


def _d_lib(tag):
    """1 个 ACCEPT 正候选 + 2 个非 ACCEPT 正候选 + 2 负节点（B 组分母对照用）。"""
    cg = _mk(tag)
    cg.add("acc_0", ACCEPT_NODE, layer="knowledge",
           verification_basis="test")
    cg.add("mem_1", "# 功能名：样本1\n# 正文：牛肉面 汤头 备用配方",
           layer="knowledge")
    cg.add("mem_2", "# 功能名：样本2\n# 正文：牛肉面 汤头", layer="knowledge")
    cg.add("r0", NEG_REJ, layer="rejected", verification_basis="test")
    cg.add("u0", NEG_UNR, layer="unresolved", verification_basis="data")
    cg.flush()
    return cg


def _count_calls(obj, name, fn):
    st = {"n": 0}
    real = getattr(obj, name)

    def _spy(*a, **kw):
        st["n"] += 1
        return real(*a, **kw)

    setattr(obj, name, _spy)
    try:
        return fn(), st["n"]
    finally:
        setattr(obj, name, real)


# ---------------------------------------------------------------- A 组（H10①②④）
def group_a():
    print("\n[A] 负覆盖尾诚实化：分数哨兵 / 独立字段 / k 预算 / 位置")
    cg = _neg_lib("tail")
    # k=5：本库 3 条真实命中（_neg_lib 的 mem_*）< 5 → 尾条按 k 预算出现
    # （H10 修订后 k=3 时 3 条真命中已用满 k，尾条为 0——见 A5 的新契约断言）。
    res, meta = cg.search(QUERY, k=5, record=False)
    tail = [r for r in res if (r[2] or {}).get("negative_coverage")]
    prim = [r for r in res if not (r[2] or {}).get("negative_coverage")]
    check("A1 负覆盖条目不冒充候选：分数恒字面量 0.0（哨兵常量本身也是 0.0），"
          "不带 negative_coverage 的候选分数都 ≥ 它",
          len(tail) == 2
          and _mdcg.NEG_COVERAGE_SCORE == 0.0
          and all(r[1] == 0.0 for r in tail)
          and min([r[1] for r in prim] + [float("inf")]) >= 0.0,
          "tail=%s prim=%s const=%s" % ([r[1] for r in tail],
                                        [r[1] for r in prim],
                                        _mdcg.NEG_COVERAGE_SCORE))
    check("A2 独立字段承载负性（card.negative_coverage/neg_layer，"
          "机器可判，不靠分数位反推）",
          all(r[0].get("negative_coverage") is True
              and r[0].get("neg_layer") in ("rejected", "unresolved")
              for r in tail)
          and all("negative_coverage" not in r[0] for r in prim),
          str([(r[0].get("id"), r[0].get("neg_layer")) for r in tail]))
    check("A3 真 id 走独立字段 node_id（id/path 仍是落盘路径——既有消费者口径不动）",
          [(r[0].get("id"), r[0].get("path"), r[0].get("node_id"))
           for r in tail] == [("rejected/r0.md", "rejected/r0.md", "r0"),
                              ("unresolved/u0.md", "unresolved/u0.md", "u0")],
          str([(r[0].get("id"), r[0].get("path"), r[0].get("node_id"))
               for r in tail]))
    check("A4 位置在**尾部**（主结果全在前；旧注释「（首条）」与代码相反）",
          [bool((r[2] or {}).get("negative_coverage")) for r in res]
          == [False] * len(prim) + [True] * len(tail),
          str([(r[0].get("id"), (r[2] or {}).get("negative_coverage"))
               for r in res]))

    print("\n[A'] k 预算：真实命中优先 + 总数恒 ≤ k"
          "（H10 修订：改前 k=2/3 真实命中归零）")
    #: 本库的真实命中数：`_neg_lib` 的 3 条 mem_*（含查询词）过质量闸（score > 0）；
    #: 负层节点不进正排（另 2 条）。改前提示按 min(3, k) 先占位 → k ≤ 3 时主结果为 0。
    n_real = 3
    ok_len = True
    detail = []
    for k in (1, 2, 3, 5, 20):
        r, m = cg.search(QUERY, k=k, record=False)
        nt = len([x for x in r if (x[2] or {}).get("negative_coverage")])
        np = len(r) - nt
        b = m.get("k_budget") or {}
        detail.append("k=%d len=%d prim=%d neg=%d budget=%s" % (k, len(r), np, nt, b))
        if len(r) > k:
            ok_len = False
        # 真实命中永不被提示挤占：主结果恰为 min(k, 真实命中数) 条（改前 k≤3 → 0）
        if np != min(k, n_real):
            ok_len = False
        # 「产生信息才落键」：有尾条时 k_budget 与实取逐位一致，无尾条时不落键
        if nt and b != {"k": k, "primary": np, "neg_tail": nt}:
            ok_len = False
        if not nt and "k_budget" in m:
            ok_len = False
    check("A5 结果总数 ≤ k、主结果条数＝min(k, 真实命中数)（真实命中不被提示挤占）、"
          "且 meta.k_budget 与实取逐位一致（尾巴计入预算）",
          ok_len, "; ".join(detail))
    check("A6 主结果实取 = k − 提示条数（_primary_slots 单点）",
          _mdcg.MdCG._primary_slots(3, 2) == 1
          and _mdcg.MdCG._primary_slots(1, 2) == 0
          and _mdcg.MdCG._primary_slots(0, 0) == 0
          and _mdcg.MdCG._primary_slots(5, 3) == 2,
          "slots=%s" % [_mdcg.MdCG._primary_slots(*x)
                        for x in ((3, 2), (1, 2), (0, 0), (5, 3))])
    r0, m0 = cg.search(QUERY, k=0, record=False)
    check("A7 k=0 → 零结果（提示条目也不超发；改前 k=0 仍返回 3 条提示）",
          r0 == [] and "k_budget" not in m0, str(r0))

    print("\n[A''] 审计面与卡片同源")
    res3, meta3 = cg.search(QUERY, k=5, record=False)
    rows = meta3.get("neg_coverage_tail") or []
    cards = [r for r in res3 if (r[2] or {}).get("negative_coverage")]
    check("A8 meta.neg_coverage_tail 与入榜条目逐条同源（含 node_id/score=0.0）",
          len(rows) == len(cards) == 2
          and all(row["id"] == c[0]["id"] and row["node_id"] == c[0]["node_id"]
                  and row["score"] == c[1] == 0.0
                  and row["layer"] == c[0]["neg_layer"]
                  for row, c in zip(rows, cards)),
          "%s vs %s" % (rows, [c[0]["id"] for c in cards]))
    check("A9 meta.covered_neg 口径不变（全部覆盖路径，不只入榜者）",
          meta3.get("covered_neg") == ["rejected/r0.md", "unresolved/u0.md"],
          str(meta3.get("covered_neg")))
    cg.close()
    return cg


# ---------------------------------------------------------------- B 组（H10③）
def group_b():
    print("\n[B] _compute_d 分母只数真实候选（提示条目不进分母）")
    cg = _d_lib("d")
    res, _m = cg.search(QUERY, k=5, record=False)
    prim = [r for r in res if not (r[2] or {}).get("negative_coverage")]
    acc = sum(1 for r in prim if r[1] > 0 and r[2]["state"] == "ACCEPT")
    d = cg._compute_d(QUERY, res)
    d_naive = max(0.0, 1.0 - acc / len(res))
    check("B0 前置：确有 1 条 ACCEPT 有效命中（对照断言才有判别力）",
          acc == 1 and len(prim) == 3 and len(res) == 5,
          "acc=%d prim=%d all=%d" % (acc, len(prim), len(res)))
    check("B1 同批结果的 D 与「只喂正排候选」的 D 一致（分母不含提示）",
          abs(d - (1.0 - acc / len(prim))) < 1e-9,
          "D=%s / 仅正排=%s" % (d, 1.0 - acc / len(prim)))
    check("B2 对照：若把提示算进分母，D 会变成另一个数（断言有判别力）",
          abs(d - d_naive) > 1e-9,
          "D=%s / 含尾分母=%s" % (d, d_naive))
    check("B3 结果全是提示（无正排候选）→ 如实报「完全空白」1.0，不拿提示充数",
          cg._compute_d(QUERY, [r for r in res
                                if (r[2] or {}).get("negative_coverage")]) == 1.0)
    check("B4 空结果仍 1.0（既有语义未变）", cg._compute_d(QUERY, []) == 1.0)
    cg.close()
    return cg


# ---------------------------------------------------------------- C 组（H7⑦）
def group_c():
    print("\n[C] 基类与生产路径同口径：负记忆/目标槽不进正排（不双列）")
    from md_cg.mdcg import MdCG
    root = os.path.join(_SANDBOX, "lib_base_r%d" % _RUN[0])
    b = MdCG(root)
    b.add("mem_0", "# 功能名：正\n# 子功能：牛肉面 汤头 熬制 工艺\n",
          layer="knowledge")
    b.add("r0", NEG_REJ, layer="rejected", verification_basis="test")
    b.add("u0", NEG_UNR, layer="unresolved", verification_basis="data")
    b.add_goal("牛肉面 汤头 标准化", priority=0.6)
    b.flush()
    res, meta = b.search(QUERY, k=5, record=False)
    ids = [r[0].get("id") for r in res]
    check("C1 同一负节点不再双列（一次作正候选、一次作覆盖尾 → 改后只出现一次）",
          len(ids) == len(set(ids))
          and sorted(ids) == ["mem_0", "rejected/r0.md", "unresolved/u0.md"],
          str(ids))
    check("C2 负记忆 ID 形态唯一（带层前缀的路径），无「无前缀版」孪生条目",
          not any(str(i).startswith("r0") or str(i).startswith("u0")
                  for i in ids), str(ids))
    osr = MdCGOS(os.path.join(_SANDBOX, "lib_os_r%d" % _RUN[0]))
    osr.add("mem_0", "# 功能名：正\n# 子功能：牛肉面 汤头 熬制 工艺\n",
            layer="knowledge")
    osr.add("r0", NEG_REJ, layer="rejected", verification_basis="test")
    osr.add("u0", NEG_UNR, layer="unresolved", verification_basis="data")
    osr.add_goal("牛肉面 汤头 标准化", priority=0.6)
    osr.flush()
    res_os, _m2 = osr.search(QUERY, k=5, record=False)
    check("C3 基类与生产路径（MdCGOS）结果 id 逐位一致（同口径，非各写一份）",
          [r[0].get("id") for r in res_os] == ids,
          "%s vs %s" % ([r[0].get("id") for r in res_os], ids))
    check("C4 目标槽（goals）不进正排（与 _candidates 同口径）",
          not any(str(i).startswith("goal_") for i in ids), str(ids))
    res_off, _m3 = b.search(QUERY, k=5, include_neg=False, record=False)
    check("C5 include_neg=False → 负节点完全不出现（改前仍作正候选出现一次）",
          [r[0].get("id") for r in res_off] == ["mem_0"],
          str([r[0].get("id") for r in res_off]))
    # ---- 真源单点（2026-09-30 补强）：生产路径不留同值字面量副本 ----
    # mdcos._candidates 旧写作裸元组 ("rejected","unresolved","goals")——与 mdcg 的
    # NEG_ROUTE_LAYERS 同值异构：改一处漏一处，正是 C 组「同口径」要防的漂移。
    check("C6 生产路径（mdcos）不留负层元组字面量副本",
          '("rejected", "unresolved", "goals")' not in inspect.getsource(mdcos),
          "mdcos.py 仍有字面量副本")
    check("C7 MdCGOS 与基类共用同一常量对象（导入非同值重写）",
          mdcos.NEG_ROUTE_LAYERS is _mdcg.NEG_ROUTE_LAYERS,
          "%r vs %r" % (mdcos.NEG_ROUTE_LAYERS, _mdcg.NEG_ROUTE_LAYERS))
    b.close()
    osr.close()
    return b


# ---------------------------------------------------------------- D 组（H11⑥）
def group_d():
    print("\n[D] 飞轮建单只限真冲突 REJECT")

    def _unres(cg):
        return [n for n, e in list((cg.index.get("nodes") or {}).items())
                if e.get("layer") == "unresolved"]

    cg = _mk("fw")
    cg.add("discipline_prod", "# 功能：生产纪律\n# 执行：禁止删除生产数据\n",
           layer="self", tags=["discipline"],
           non_applicable_conditions=["删除生产数据"])
    cg.add("k_offline",
           "# 功能：离线批处理\n# 生效条件：离线环境\n# 不适用条件：生产环境\n",
           layer="knowledge", non_applicable_conditions=["生产环境"])
    cg.flush()
    check("D1 判据单点：FLYWHEEL_TRIGGERS == ('REJECT',)",
          consistency.FLYWHEEL_TRIGGERS == ("REJECT",)
          and cg.consistency_catalog()["auto_flywheel"]["triggers_on"]
          == ["REJECT"], str(consistency.FLYWHEEL_TRIGGERS))
    r = cg.check_consistency("删除生产数据", layer="self", auto_flywheel=True)
    check("D1b 真冲突 REJECT 仍建单（收窄≠静默关掉飞轮）",
          r["verdict"] == "REJECT" and bool(r.get("unresolved_id"))
          and len(_unres(cg)) == 1,
          "%s / %s / %s" % (r["verdict"], r.get("unresolved_id"), _unres(cg)))
    n0 = len(_unres(cg))
    r = cg.check_consistency("# 功能：生产批处理\n# 生效条件：生产环境\n",
                             layer="knowledge", auto_flywheel=True)
    check("D2 DEFER（待确认）不建单，判定仍如实返回",
          r["verdict"] == "DEFER" and r["conflict_strength"] >= consistency.CLASH_LOW
          and not r.get("unresolved_id") and len(_unres(cg)) == n0,
          "%s/%s/unr=%s/n=%d" % (r["verdict"], r["conflict_strength"],
                                 r.get("unresolved_id"), len(_unres(cg))))
    e = _mk("fw_empty")
    r = e.check_consistency("# 功能：某情景\n# 生效条件：某个特殊条件\n",
                            layer="contextual", auto_flywheel=True)
    check("D3 BLINDSPOT（空库无可比对）不建单（改前每写一条建一张工单）",
          r["verdict"] == "BLINDSPOT" and not r.get("unresolved_id")
          and not _unres(e),
          "%s / unr=%s / n=%d" % (r["verdict"], r.get("unresolved_id"),
                                  len(_unres(e))))
    # 写链（writepipe）与 add() 的自动建单同口径：REJECT 才建
    cg.add("k_x", "# 功能：x\n# 生效条件：离线环境\n", layer="knowledge")
    n1 = len(_unres(cg))
    cg.add("k_y", "# 功能：y\n# 生效条件：生产环境\n", layer="knowledge",
           consistency=True)
    check("D4 add(consistency=True) 的 DEFER 同样不建单（同一判据，非各写一份）",
          len(_unres(cg)) == n1, "%d → %d" % (n1, len(_unres(cg))))
    cg.close()
    e.close()
    return cg


# ---------------------------------------------------------------- E 组（⑧）
def group_e():
    print("\n[E] CCG 哨兵直连入口同口径（不新造第二张哨兵表）")
    cg = _mk("sent")
    cg.add("z_a", SENT, layer="knowledge")
    cg.flush()
    vd_list = consistency.check(cg, SENT, layer="knowledge",
                               non_applicable_conditions=["无"],
                               auto_flywheel=True)
    vd_none = consistency.check(cg, SENT, layer="knowledge",
                                auto_flywheel=True)
    check("E1 直连 consistency.check：显式哨兵列表「无」与不传同判"
          "（ACCEPT / strength 0.0 / 无工单）",
          vd_list["verdict"] == vd_none["verdict"] == "ACCEPT"
          and float(vd_list["conflict_strength"]) == 0.0
          and not vd_list.get("unresolved_id")
          and not (vd_list.get("conflicts") or []),
          "%s/%s unr=%s" % (vd_list["verdict"], vd_list["conflict_strength"],
                            vd_list.get("unresolved_id")))
    nid = cg.add("z_b", SENT, layer="knowledge", consistency=True,
                 non_applicable_conditions=["无"])
    fm = (cg.get("z_b") or {}).get("frontmatter") or {}
    check("E2 引擎直连入口 cg.add(consistency=True) + 哨兵列表 → ACCEPT"
          "（改前 DEFER/strength=1.0/建单）",
          bool(nid) and (fm.get("consistency") or {}).get("verdict") == "ACCEPT"
          and not (fm.get("consistency") or {}).get("unresolved_id"),
          str(fm.get("consistency")))
    check("E3 哨兵表复用单点：mdcos._is_null_condition 判「无」为真值、"
          "真条件为假（未新造第二张表）",
          mdcos._is_null_condition("无") is True
          and mdcos._is_null_condition("（无）") is True
          and mdcos._is_null_condition("无法确定") is False,
          "%s/%s" % (mdcos._is_null_condition("无"),
                     mdcos._is_null_condition("无法确定")))
    # 防放宽：哨兵剔除不得把真负条件一起吞掉
    real = ("# 功能名：本地开发约定\n"
            "# 生效条件：本地开发环境\n"
            "# 子功能：登记本地端口\n# 执行：核对本地清单\n"
            "# 验证方式：test\n"
            "# 不适用条件：本地开发环境\n\n本地监听端口 8081/HTTP\n")
    vd_real = consistency.check(cg, real, layer="knowledge",
                               non_applicable_conditions=["本地开发环境"],
                               auto_flywheel=True)
    check("E4 防放宽：真负条件（自否定形态）仍判 REJECT 且仍建单",
          vd_real["verdict"] == "REJECT"
          and any(c.get("type") == "self_negation"
                  for c in (vd_real.get("conflicts") or []))
          and bool(vd_real.get("unresolved_id")),
          "%s/%s" % (vd_real["verdict"], vd_real.get("unresolved_id")))
    cg.close()
    return cg


# ---------------------------------------------------------------- F 组（⑤⑦）
def group_f():
    print("\n[F] 工单身份＝语义 slug；同题再检出时「# 现场：」刷新")
    cg = _mk("ticket")
    cg.add("k_x", "# 功能名：对方节点\n# 生效条件：条件A\n", layer="knowledge")
    cg.flush()
    Q = "牛肉面 汤头 隔离级别"
    rep1 = {"query": Q, "expected_state": "ACCEPT", "actual_state": "DEFER",
            "missing": "缺区分条件",
            "detail": [{"type": "same_condition_divergence", "with": "k_x",
                        "same_condition": 1.0, "slot_overlap": 1.0,
                        "conclusion_overlap": 0.69}]}
    fw1 = cg.flywheel_step(rep1)
    id1 = fw1["unresolved_id"]
    c1 = (cg.get(id1) or {}).get("content") or ""
    fm1 = (cg.get(id1) or {}).get("frontmatter") or {}
    check("F1 工单身份＝slug（可读 id：`unr_<slugify(topic)>`，且过节点 id 判据）",
          id1.startswith("unr_") and "隔离级别" in id1
          and _mdcg._NODE_ID_RE.match(id1) is not None, id1)
    check("F2 首次建单带「# 现场：」且含数值",
          "# 现场：" in c1 and "结论差异 0.69" in c1, repr(c1[:120]))

    # 覆盖写：对方节点被改写（同 id 覆写既有节点）
    nid_over = cg.add("k_x", "# 功能名：对方节点\n# 生效条件：条件B\n",
                      layer="knowledge", override=True)
    check("F3 前置：对方节点确已覆写（正文换新且同 id）",
          nid_over == "k_x"
          and "条件B" in ((cg.get("k_x") or {}).get("content") or ""),
          str(nid_over))
    # 同题再检出（措辞不同、现场数值已变）→ 同一张工单、现场刷新
    n_before = len(cg.index["nodes"])
    rep2 = dict(rep1)
    rep2["detail"] = [{"type": "same_condition_divergence", "with": "k_x",
                       "same_condition": 1.0, "slot_overlap": 1.0,
                       "conclusion_overlap": 0.12}]
    fw2 = cg.flywheel_step(rep2)
    c2 = (cg.get(id1) or {}).get("content") or ""
    fm2 = (cg.get(id1) or {}).get("frontmatter") or {}
    check("F4 措辞/数值不同的同一问题 → 同 id、零新建（不重复建单）",
          fw2["unresolved_id"] == id1 and len(cg.index["nodes"]) == n_before,
          "%s vs %s / n=%d→%d" % (fw2["unresolved_id"], id1, n_before,
                                  len(cg.index["nodes"])))
    check("F5 「# 现场：」已刷新为新数值（旧数值不再残留）",
          "结论差异 0.12" in c2 and "结论差异 0.69" not in c2,
          repr([l for l in c2.splitlines() if l.startswith("# 现场")]))
    check("F6 刷新只动正文：id/created_at/归属（fm）保持建单事实不变",
          fm2.get("created_at") == fm1.get("created_at")
          and fm2.get("id") == id1
          and not (fm2.get("consistency") or {}).get("verdict"),
          str({k: fm2.get(k) for k in ("id", "created_at", "session")}))
    # 幂等：同输入再调 → 零写盘
    (_r, nw) = _count_calls(cg, "_write_node",
                            lambda: cg.flywheel_step(rep2))
    check("F7 同现场再检出不制造脏写盘（正文逐字相同即零写入）",
          nw == 0 and (cg.get(id1) or {}).get("content") == c2,
          "writes=%d" % nw)
    # 身份含实际态：不同故障态是不同工单
    rep3 = dict(rep2)
    rep3["actual_state"] = "REJECT"
    fw3 = cg.flywheel_step(rep3)
    check("F8 身份含实际态：DEFER 与 REJECT 是两张工单（不误并）",
          fw3["unresolved_id"] != id1, str(fw3["unresolved_id"]))
    # ⑦ 的判据面：**问题模板/期望态措辞**不进身份——同一主题+同一实际态换个写法
    # 仍是同一张工单（改前 sha1(整段 question) 会各建一张）
    n_b3 = len(cg.index["nodes"])
    rep4 = dict(rep2)
    rep4["expected_state"] = "无条件"
    fw4 = cg.flywheel_step(rep4)
    check("F10 期望态措辞不同（同一主题/实际态）→ 同 id、零新建",
          fw4["unresolved_id"] == id1 and len(cg.index["nodes"]) == n_b3,
          "%s vs %s / n=%d" % (fw4["unresolved_id"], id1,
                               len(cg.index["nodes"])))
    # 语义 slug 单点：规范化后再 slug（空白/非法字符差异不产生新工单）
    a = cg.add_unresolved("为何 X 出现 DEFER？", topic="某主题|DEFER")
    b = cg.add_unresolved("为何  X   出现 DEFER？ ", topic="某主题|DEFER")
    check("F9 同 topic 的空白/标点差异不新建（规范化→slug 同一身份）",
          a == b, "%s vs %s" % (a, b))
    cg.close()
    return cg


# ---------------------------------------------------------------- G 组（M3）
def group_g():
    print("\n[G] M3：节点总数传进 bucket_health（空库 vs 有节点零分桶）")
    # 有节点但零分桶：全节点落在非分桶层（BUCKETED_LAYERS 只有 knowledge）
    cg = _mk("m3_nobucket")
    for i in range(3):
        cg.add("s_%d" % i, "# 功能名：自我%d\n# 正文：某内容\n" % i,
               layer="self")
    cg.flush()
    h = cg.health()
    check("G1 有节点但分桶表为空 → ok=False / reason=empty_buckets（不冒充健康）",
          cg.index.get("buckets") == {} and h.get("total_nodes") == 3
          and h.get("ok") is False and h.get("reason") == "empty_buckets"
          and h.get("nodes") == 3,
          "buckets=%s health=%s" % (cg.index.get("buckets"),
                                    {k: h.get(k) for k in ("ok", "reason",
                                                           "nodes", "total_nodes")}))
    cg.close()
    empty = _mk("m3_empty")
    h0 = empty.health()
    check("G2 真空库（零节点零桶）→ ok=True / reason=empty（不误报）",
          h0.get("ok") is True and h0.get("reason") == "empty"
          and h0.get("total_nodes") == 0,
          str({k: h0.get(k) for k in ("ok", "reason", "total_nodes")}))
    empty.close()
    one = _mk("m3_single")
    one.add("one", "# 功能名：单桶\n# 正文：知识面 内容\n", layer="knowledge")
    one.flush()
    h1 = one.health()
    check("G3 单桶库如实读数（不再说成「巨桶」；ok 仍为 False 未放宽）",
          h1.get("buckets") == 1 and h1.get("ok") is False
          and h1.get("problems")
          and not any("巨桶" in p for p in h1["problems"]),
          str(h1.get("problems")))
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "mdcg.py"), encoding="utf-8").read()
    check("G4 传参契约在呼叫点显式可见（health 传 total_nodes=，非靠默认值）",
          re.search(r"routing\.bucket_health\(self\.index\.get\(\"buckets\", \{\}\),"
                    r"\s*\n\s*total_nodes=len\(self\.index\[\"nodes\"\]\)\)",
                    src) is not None,
          "呼叫点未传 total_nodes")
    one.close()
    return one


# ---------------------------------------------------------------- 变异（自证）
def _pre_fix_neg_score():
    _mdcg.NEG_COVERAGE_SCORE = 1.0          # 改动前：提示条目分数恒 1.0


def _pre_fix_k_budget():
    _mdcg.MdCG._primary_slots = staticmethod(lambda k, n_tail: int(k))


def _pre_fix_neg_budget():
    """改前口径：提示条数上界恒为 min(NEG_COVERAGE_MAX, |覆盖|)，不看 k 预算
    （H10 修订前）——k ≤ 提示数时真实命中被挤成 0（本组 A5 的判别力所在）。"""
    _orig = _mdcg.MdCG.__dict__["_neg_tail"]
    _mdcg.MdCG._neg_tail = lambda self, neg_coverage, budget: _orig(
        self, neg_coverage, _mdcg.NEG_COVERAGE_MAX)


def _pre_fix_d_denom():
    _mdcg._is_neg_coverage = lambda card: False   # 改动前：分母含提示条目


def _pre_fix_base_dup():
    _mdcg.NEG_ROUTE_LAYERS = ()             # 改动前：负层/目标槽进正排


def _pre_fix_sentinel():
    mdcos._is_null_condition = lambda value: False  # 改动前：哨兵当真实条件


def _pre_fix_flywheel_scope():
    consistency.FLYWHEEL_TRIGGERS = ("REJECT", "DEFER", "BLINDSPOT")


def _pre_fix_ticket_slug():
    _mdcg.MdCG._ticket_slug = staticmethod(
        lambda question, topic=None: hashlib.sha1(
            str(question or "").encode("utf-8")).hexdigest()[:10])


def _pre_fix_refresh():
    _mdcg.MdCG._refresh_unresolved = lambda self, node_id, entry, content: False


def _pre_fix_health_total():
    _orig = routing.bucket_health
    routing.bucket_health = lambda counts, total_nodes=None: _orig(counts)


_MUTATIONS = {
    "neg_score": (_pre_fix_neg_score, ["A1", "A8"]),
    # k_budget：主结果退回 scored[:k]（尾巴在 k 之外）——A6 钉公式；本库 scored
    # 短于 k（3 条真命中）故 A5 的「≤ k」不再被它打红，溢出判别力归新守卫
    # md_cg/test_neg_coverage_budget.py 的 T3 全量兜底场景（scored ≥ k 且真命中 < k）。
    "k_budget": (_pre_fix_k_budget, ["A6"]),
    # neg_budget：把 H10 修订抽回改前口径（提示按 min(3,·) 先占位）——A5 必红
    "neg_budget": (_pre_fix_neg_budget, ["A5"]),
    "d_denom": (_pre_fix_d_denom, ["B1"]),
    "base_dup": (_pre_fix_base_dup, ["C1", "C2", "C4", "C5"]),
    "sentinel": (_pre_fix_sentinel, ["E1", "E2"]),
    "flywheel_scope": (_pre_fix_flywheel_scope, ["D2", "D3"]),
    "ticket_slug": (_pre_fix_ticket_slug, ["F1", "F9", "F10"]),
    "refresh": (_pre_fix_refresh, ["F5"]),
    "health_total": (_pre_fix_health_total, ["G1"]),
}


def _snapshot():
    # 静态方法必须取**原始描述符**（`MdCG.__dict__[...]`）：`getattr` 会经描述符
    # 协议退回裸函数，写回时就会被当成实例方法（多收一个 self）——变异自证第一轮
    # 实测踩过（`_primary_slots() takes 2 positional arguments but 3 were given`）。
    return {"NEG_COVERAGE_SCORE": _mdcg.NEG_COVERAGE_SCORE,
            "_primary_slots": _mdcg.MdCG.__dict__["_primary_slots"],
            "_neg_tail": _mdcg.MdCG.__dict__["_neg_tail"],
            "_is_neg_coverage": _mdcg._is_neg_coverage,
            "NEG_ROUTE_LAYERS": _mdcg.NEG_ROUTE_LAYERS,
            "_is_null_condition": mdcos._is_null_condition,
            "FLYWHEEL_TRIGGERS": consistency.FLYWHEEL_TRIGGERS,
            "_ticket_slug": _mdcg.MdCG.__dict__["_ticket_slug"],
            "_refresh_unresolved": _mdcg.MdCG.__dict__["_refresh_unresolved"],
            "bucket_health": routing.bucket_health}


def _restore(snap):
    _mdcg.NEG_COVERAGE_SCORE = snap["NEG_COVERAGE_SCORE"]
    _mdcg.MdCG._primary_slots = snap["_primary_slots"]
    _mdcg.MdCG._neg_tail = snap["_neg_tail"]
    _mdcg._is_neg_coverage = snap["_is_neg_coverage"]
    _mdcg.NEG_ROUTE_LAYERS = snap["NEG_ROUTE_LAYERS"]
    mdcos._is_null_condition = snap["_is_null_condition"]
    consistency.FLYWHEEL_TRIGGERS = snap["FLYWHEEL_TRIGGERS"]
    _mdcg.MdCG._ticket_slug = snap["_ticket_slug"]
    _mdcg.MdCG._refresh_unresolved = snap["_refresh_unresolved"]
    routing.bucket_health = snap["bucket_health"]


def _run_all():
    global PASS, FAIL, FAILS
    _RUN[0] += 1
    PASS, FAIL, FAILS = 0, 0, []
    group_a()
    group_b()
    group_c()
    group_d()
    group_e()
    group_f()
    group_g()
    return PASS, list(FAILS)


def main(argv):
    which = None
    for a in argv:
        if a.startswith("--drop-fix"):
            which = a.split("=", 1)[1] if "=" in a else "all"
    if which is None:
        ok, bad = _run_all()
        print("\n==== 负覆盖诚实化守卫：%d 通过%s ====" % (
            ok, "，%d 失败：%s" % (len(bad), "; ".join(bad)) if bad else ""))
        return 1 if bad else 0
    names = list(_MUTATIONS) if which == "all" else [which]
    rc = 0
    print("\n=== 定点变异自证（抽掉修复 → 守卫必红 → 恢复 → 转绿）===")
    for name in names:
        if name not in _MUTATIONS:
            print("  未知变异 %r（可选：%s）" % (name, sorted(_MUTATIONS)))
            return 2
        fn, want = _MUTATIONS[name]
        snap = _snapshot()
        fn()
        ok, bad = _run_all()
        hit = [n for n in want
               if any(b.split()[0] == n or b.startswith(n) for b in bad)]
        missed = [n for n in want if n not in hit]
        print("  [%s] 红项 %d 个：%s" % (name, len(bad), "; ".join(bad) or "（无）"))
        if missed or not bad:
            print("  FAIL 变异 %s 未打红预期断言：%s" % (name, missed or "全绿"))
            rc = 1
        else:
            print("  ok   变异 %s 打红预期断言 %d 项" % (name, len(hit)))
        _restore(snap)
        ok2, bad2 = _run_all()
        if bad2:
            print("  FAIL 变异 %s 恢复后未转绿，残余红项：%s" % (name, bad2))
            rc = 1
        else:
            print("  ok   变异 %s 恢复后转绿（%d 通过，无残余）" % (name, ok2))
    return rc


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        _rc = main(sys.argv[1:])
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(_rc)
