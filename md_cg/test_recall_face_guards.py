# -*- coding: utf-8 -*-
# 功能名：召回面守卫——负覆盖提示条目的**消费方语义**（H10①②③：按分数不得压过真实答案、
#         条数 ≤ k、D 分母只数真实候选）、负层与目标槽不进正排（H7⑦：同一负节点不双列）、
#         飞轮只对真冲突建单 + 工单语义身份与现场刷新（H11⑥⑦）、CCG 哨兵漏斗同口径（H11⑧）、
#         bucket_health 呼叫点传节点总数（M3）
# 生效条件：md_cg/mdcg.py 的 `_emit`/`_neg_tail`/`_primary_slots`/`_compute_d`/`search`
#           候选收集/`add_unresolved`/`_refresh_unresolved`/`_ticket_slug`/`health`/
#           `flywheel_step`、md_cg/consistency.py 的 `check`（`FLYWHEEL_TRIGGERS` +
#           哨兵漏斗）、md_cg/routing.py 的 `bucket_health(counts, total_nodes)` 在位时；
#           沙箱条件：库根一律 tempfile.mkdtemp，绝不触在役库/在役服务。
# 子功能：
#   N 组 H10①②④（负覆盖尾诚实化·**消费方视角**）：N1 按分数降序排后提示条目不得插进
#     真实候选之前（被断言的正是「任何按 score 排序/取首位的下游」会看到的顺序）、
#     N2 最高分不得是提示、N3 返回条数恒 ≤ k 且 k=1 边界、N4 k=0 → 零结果、
#     N5 提示不得呈现为「有效命中」（state≠ACCEPT ∧ score 不为正 ∧ 负性有独立可判字段）、
#     N6 提示携带的 node_id 可被公共 API 解析回真节点（id/path 仍是落盘路径）、
#     N7 提示只出现在尾部
#   D 组 H10③：_compute_d 的分母只数真实候选（对照断言证明判别力）
#   G 组 H7⑦：同一次结果的**节点身份**无重复（调用方按节点去重必成功）、负层/目标槽不以
#     正候选形态出现、基类与生产路径同口径、include_neg=False 负节点完全不出现
#   F 组 H11⑥：真冲突 REJECT 仍建单（收窄≠关飞轮）、DEFER/BLINDSPOT/写链 DEFER 不建单、
#     判据与声明面同源
#   S 组 H11⑦⑤：措辞不同的同一问题＝同一张工单（零新建）、不同实际态＝不同工单、
#     工单 id 可读可解析、现场刷新（新值在/旧值不在/id 与 created_at 不变）、同输入零写盘
#   C 组 H11⑧：哨兵形态族在直连入口与「不传」同判（同表同口径）、真负条件不被吞（防放宽）
#   H 组 M3：有节点零分桶 ≠ 真空库（两态可区分）、缺省调用与加参数前逐位一致、
#     单桶不再被说成巨桶（判据未放宽）、多桶真巨桶仍报巨桶
# 执行：python -X utf8 -m md_cg.test_recall_face_guards
#       python -X utf8 -m md_cg.test_recall_face_guards --source-mutate=all
#       python -X utf8 -m md_cg.test_recall_face_guards --source-mutate=H10-score
# 验证方式：本文件自跑（自带断言计数与退出码 rc=0/1）；`--source-mutate` = **定点变异
#           自证**——把待验修复**在临时副本的源码文本上**逐点抽回改动前语义（在役工作树
#           只读、字节不变，变异结束用 md5 复核），再以子进程实跑本守卫：必须 rc=1 且
#           打红**预期断言集合**；随后在役树原样复跑必须转绿（无残余）。
# 不适用条件：情感交互｜闲聊｜纯查询无改动；负覆盖条目在 MCP 结果面的**渲染**
#           （`_node_view` 只透 id/path/frontmatter/content）不属本文件面内；
#           「对方节点被覆写但工单未重发」形态无新鲜现场数据可依，不在面内。
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import consistency, mdcos, routing   # noqa: E402
from md_cg.mdcos import MdCGOS                  # noqa: E402
from md_cg.mdcg import MdCG                     # noqa: E402

PASS = 0
FAIL = 0
FAILS = []
_RUN = [0]
_SANDBOX = tempfile.mkdtemp(prefix="mdcg_recall_face_")
_HERE = os.path.dirname(os.path.abspath(__file__))

QUERY = "牛肉面 汤头"
NEG_REJ = "# 假设：牛肉面 用工业浓汤宝\n# 否决原因：偏离手工工艺\n"
NEG_UNR = "# 问题：牛肉面 汤色发黑\n# 目标：（未设定）\n"
#: 哨兵形态语料（现行 ⑧ 的现场：`不适用条件：无` 与 `约束：无` 相撞）
SENT_A = ("# 功能名：部署面端口约定\n"
          "# 生效条件：载体/位置：prod 集群；方法：部署清单核对；约束：无\n"
          "# 子功能：登记各监听端口\n# 执行：核对 manifest 的 ports 段\n"
          "# 验证方式：test\n"
          "# 不适用条件：无\n\n网关监听端口 8080/HTTP\n")
SENT_B = ("# 功能名：构建面产物约定\n"
          "# 生效条件：载体/位置：ci 集群；方法：产物清单核对；约束：无\n"
          "# 子功能：登记产物指纹\n# 执行：核对 manifest 的 artifacts 段\n"
          "# 验证方式：test\n"
          "# 不适用条件：无\n\n构建产物指纹 sha256 前 16 位\n")
#: B 组要一个真「有效命中」（否则 accept=0 时含尾/不含尾两种分母都得 1.0，无判别力）
ACCEPT_NODE = ("# 功能名：汤头工艺基线\n"
               "# 生效条件：牛肉面 汤头\n"
               "# 子功能：登记熬制工艺\n"
               "# 执行：按基线核对\n"
               "# 验证方式：test\n"
               "# 不适用条件：工业化浓汤宝\n\n"
               "牛肉面 汤头 熬制 工艺：小火 6 小时\n")
NEG_ROUTE = ("rejected", "unresolved", "goals")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL %s  %s" % (name, detail))


def check_exc(name, fn):
    """fn() → (cond, detail)。抛异常记为该断言失败（变异运行不得因崩溃丢掉红项读数）。"""
    try:
        cond, detail = fn()
    except Exception as e:                        # noqa: BLE001
        cond, detail = False, "EXC %s: %s" % (type(e).__name__, e)
    check(name, cond, detail)


def _mk(tag):
    return MdCGOS(os.path.join(_SANDBOX, "lib_%s_r%d" % (tag, _RUN[0])),
                  autoflush=0)


def _base(tag):
    return MdCG(os.path.join(_SANDBOX, "base_%s_r%d" % (tag, _RUN[0])))


def _is_neg(r):
    """消费方视角的「这是提示不是候选」判据：独立字段（不从分数位反推）。"""
    return bool((r[0] or {}).get("negative_coverage")
                or (r[2] or {}).get("negative_coverage"))


def _node_key(card):
    """一条结果背后的**节点身份**（提示条目走 node_id，正候选走 frontmatter.id）。

    只看结果里的 id 字符串会被「同一节点两种 id 形态」骗过（正候选用节点 id、
    提示条目用带层前缀的落盘路径）——去重必须落在节点身份上。
    """
    fm = (card or {}).get("frontmatter") or {}
    return (card.get("node_id") or fm.get("id")
            or card.get("id") or card.get("path"))


def _split(res):
    return ([r for r in res if _is_neg(r)], [r for r in res if not _is_neg(r)])


def _neg_lib(tag):
    """2 正候选（与查询**部分**词面重合 → 分数落在 (0,1) 开区间）+ 2 负节点。

    「分数落在开区间」是排序判别力的前提：若真实候选也能拿满分（1.0），
    改动前提示条目的 1.0 与之并列、稳定排序下真实候选仍在前，排序断言就抓不到
    「提示压过真实答案」这件事（实测定点变异实测：满分候选存在时 N1/N2 空转）。
    """
    cg = _mk(tag)
    cg.add("mem_a", "# 功能名：样本a\n# 子功能：牛肉面 汤底 备用配方\n",
           layer="knowledge")
    cg.add("mem_b", "# 功能名：样本b\n# 子功能：汤头 温度 曲线\n",
           layer="knowledge")
    cg.add("r0", NEG_REJ, layer="rejected", verification_basis="test")
    cg.add("u0", NEG_UNR, layer="unresolved", verification_basis="data")
    cg.flush()
    return cg


def _d_lib(tag):
    """1 个 ACCEPT 有效命中 + 2 个非 ACCEPT 正候选 + 2 个负节点（D 分母对照用）。"""
    cg = _mk(tag)
    cg.add("acc_0", ACCEPT_NODE, layer="knowledge", verification_basis="test")
    cg.add("mem_1", "# 功能名：样本1\n# 正文：牛肉面 汤头 备用配方",
           layer="knowledge")
    cg.add("mem_2", "# 功能名：样本2\n# 正文：牛肉面 汤头", layer="knowledge")
    cg.add("r0", NEG_REJ, layer="rejected", verification_basis="test")
    cg.add("u0", NEG_UNR, layer="unresolved", verification_basis="data")
    cg.flush()
    return cg


# ------------------------------------------------------------------ N 组（H10①②④）
def group_n():
    print("\n[N] 负覆盖提示：消费方语义（排序位次 / k 预算 / 不冒充有效命中）")
    cg = _neg_lib("tail")
    res, _meta = cg.search(QUERY, k=4, record=False)
    neg, prim = _split(res)
    check_exc("N0 前置：确有提示条目与真实候选同场，且真实候选分数落在 (0,1) 开区间"
              "（否则排序断言空转——改动前的提示 1.0 与满分候选并列时排不出差别）",
              lambda: (len(neg) == 2 and len(prim) == 2
                       and 0.0 < min(r[1] for r in prim)
                       and max(r[1] for r in prim) < 1.0,
                       "neg=%d prim=%d prim_scores=%s"
                       % (len(neg), len(prim), [r[1] for r in prim])))
    # 真实候选数：按「主候选实取数」= 结果总数 − 提示数
    n_prim = len(prim)

    def _score_sorted_first_k_is_primary():
        order = sorted(range(len(res)), key=lambda i: (-res[i][1], i))
        head = order[:n_prim]
        bad = [i for i in head if _is_neg(res[i])]
        return (not bad), ("降序前 %d 位含提示：%s | 降序=%s"
                           % (n_prim, [res[i][0].get("id") for i in bad],
                              [(res[i][0].get("id"), res[i][1]) for i in order]))

    check_exc("N1 按分数降序排（下游最常见的消费方式）后，前「真实候选数」个位置"
              "全是真实候选——提示条目不会被任何按 score 排序的消费方排到真实答案之前",
              _score_sorted_first_k_is_primary)

    def _top1_not_neg():
        top = max(res, key=lambda r: r[1])
        return (not _is_neg(top),
                "top1=%s score=%s" % (top[0].get("id"), top[1]))

    check_exc("N2 取最高分者不是提示条目（MCP 三处结果面把 score 逐字透给调用方，"
              "调用方按 score 取首位必须命中真实答案）", _top1_not_neg)

    def _neg_le_prim():
        if not neg or not prim:
            return False, "neg=%d prim=%d" % (len(neg), len(prim))
        hi_neg = max(r[1] for r in neg)
        hi_prim = max(r[1] for r in prim)
        return hi_neg < hi_prim, "max(neg)=%s vs max(prim)=%s" % (hi_neg, hi_prim)

    check_exc("N2b 提示条目的分数严格低于最高分真实候选（分数位不承载「更优」语义）",
              _neg_le_prim)

    def _k_budget():
        detail = []
        ok = True
        for k in (1, 2, 3, 5, 20):
            r, m = cg.search(QUERY, k=k, record=False)
            nn, pp = _split(r)
            b = m.get("k_budget") or {}
            detail.append("k=%d len=%d prim=%d neg=%d budget=%s"
                          % (k, len(r), len(pp), len(nn), b))
            if len(r) > k or len(r) != len(pp) + len(nn):
                ok = False
            if nn and b != {"k": k, "primary": len(pp), "neg_tail": len(nn)}:
                ok = False
        return ok, "; ".join(detail)

    check_exc("N3 返回条数恒 ≤ k（提示计入 k 预算：改前 k=3→5、k=5→7，与 k 无关），"
              "且 meta.k_budget 与实取逐位一致", _k_budget)

    def _k0():
        r, m = cg.search(QUERY, k=0, record=False)
        return (r == [] and "k_budget" not in m, "k=0 → %s meta.k_budget=%s"
                % ([x[0].get("id") for x in r], m.get("k_budget")))

    check_exc("N4 k=0 → 零结果（提示也不超发；改前 k=0 仍追加 ≤3 条提示）", _k0)

    def _not_answer():
        bad = []
        for r in neg:
            card, sc, q = r
            if (q or {}).get("state") == "ACCEPT" or sc > 0.0:
                bad.append((card.get("id"), sc, (q or {}).get("state")))
        indep = all((r[0] or {}).get("negative_coverage") is True
                    and (r[2] or {}).get("negative_coverage") is True
                    and r[0].get("neg_layer") in ("rejected", "unresolved")
                    for r in neg)
        return (not bad and indep), "冒充有效命中=%s 独立字段齐备=%s" % (bad, indep)

    check_exc("N5 提示不呈现为「有效命中」：state≠ACCEPT ∧ 分数不为正，"
              "负性由独立字段（card/qual 的 negative_coverage + neg_layer）承载",
              _not_answer)

    def _node_id():
        rows = []
        for r in neg:
            card = r[0]
            nid = card.get("node_id")
            got = cg.get(nid) if nid else None
            ok_path = (card.get("id") == card.get("path")
                       and str(card.get("id") or "").startswith(
                           (card.get("neg_layer") or "") + "/"))
            rows.append((nid, bool(got), ok_path))
        return (all(bool(x[1]) and x[2] for x in rows), str(rows))

    check_exc("N6 提示携带真正可用的节点身份：node_id 能被公共 API 解析回真节点，"
              "而 id/path 仍是落盘路径（既有消费者按路径认路）", _node_id)

    def _tail_only():
        flags = [_is_neg(r) for r in res]
        return (flags == [False] * len(prim) + [True] * len(neg),
                str([(r[0].get("id"), _is_neg(r)) for r in res]))

    check_exc("N7 提示只出现在尾部（全部真实候选之后），位置语义与注释一致",
              _tail_only)
    cg.close()


# ------------------------------------------------------------------ D 组（H10③）
def group_d():
    print("\n[D] _compute_d 分母只数真实候选（提示不进分母，D 不虚高）")
    cg = _d_lib("d")
    res, _m = cg.search(QUERY, k=5, record=False)
    neg, prim = _split(res)
    acc = sum(1 for r in prim if r[1] > 0 and (r[2] or {}).get("state") == "ACCEPT")
    d = cg._compute_d(QUERY, res)
    d_naive = max(0.0, 1.0 - acc / len(res))
    check_exc("D0 前置：确有 1 条 ACCEPT 有效命中（对照断言才有判别力）",
              lambda: (acc == 1 and len(prim) == 3 and len(res) == 5,
                       "acc=%d prim=%d all=%d" % (acc, len(prim), len(res))))
    check_exc("D1 同一批结果喂进去，D 与「只喂真实候选」的 D 逐位一致（分母不含提示）",
              lambda: (abs(d - (1.0 - acc / len(prim))) < 1e-9,
                       "D=%s / 仅真实候选=%s" % (d, 1.0 - acc / len(prim))))
    check_exc("D2 判别力对照：若把提示算进分母，D 会变成另一个数"
              "（说明 D1 的相等不是恒等式）",
              lambda: (abs(d - d_naive) > 1e-9,
                       "D=%s / 含尾分母=%s" % (d, d_naive)))
    check_exc("D3 结果全是提示（无真实候选）→ 如实报「完全空白」1.0，不拿提示条数充数",
              lambda: (cg._compute_d(QUERY, neg) == 1.0, str(d)))
    check_exc("D4 空结果仍 1.0（既有语义未变）",
              lambda: (cg._compute_d(QUERY, []) == 1.0, ""))
    cg.close()


# ------------------------------------------------------------------ G 组（H7⑦）
def group_g():
    print("\n[G] 负层与目标槽不进正排：同一负节点不双列（基类与生产路径同口径）")
    b = _base("dedup")
    b.add("mem_0", "# 功能名：正\n# 子功能：牛肉面 汤头 熬制 工艺\n",
          layer="knowledge")
    b.add("r0", NEG_REJ, layer="rejected", verification_basis="test")
    b.add("u0", NEG_UNR, layer="unresolved", verification_basis="data")
    b.add_goal("牛肉面 汤头 标准化", priority=0.6)
    b.flush()
    res, _meta = b.search(QUERY, k=5, record=False)
    ids = [r[0].get("id") for r in res]
    keys = [_node_key(r[0]) for r in res]

    def _dup_free():
        dups = sorted({k for k in keys if keys.count(k) > 1})
        return (len(keys) == len(set(keys)) and len(ids) == len(set(ids)),
                "ids=%s keys=%s 重复节点=%s" % (ids, keys, dups))

    check_exc("G1 同一次结果里**节点身份**无重复（尾部提示与正候选指向同一节点时只算一次；"
              "调用方按 id/节点去重必成功——改前同一负节点以两种 id 形态出现两次）",
              _dup_free)

    def _no_neg_as_positive():
        bad = []
        for r in res:
            if _is_neg(r):
                continue
            layer = ((r[0].get("frontmatter") or {}).get("layer")
                     or str(r[0].get("id") or "").split("/")[0])
            if layer in NEG_ROUTE:
                bad.append((r[0].get("id"), layer))
        return (not bad, "以正候选形态出现的负层/目标槽节点=%s" % bad)

    check_exc("G2 负层（rejected/unresolved）与目标槽节点不以**正候选**形态出现"
              "（无 negative_coverage 标记的条目的 layer 都不在 NEG_ROUTE_LAYERS）",
              _no_neg_as_positive)

    osr = _mk("dedup_os")
    osr.add("mem_0", "# 功能名：正\n# 子功能：牛肉面 汤头 熬制 工艺\n",
            layer="knowledge")
    osr.add("r0", NEG_REJ, layer="rejected", verification_basis="test")
    osr.add("u0", NEG_UNR, layer="unresolved", verification_basis="data")
    osr.add_goal("牛肉面 汤头 标准化", priority=0.6)
    osr.flush()
    res_os, _m2 = osr.search(QUERY, k=5, record=False)
    check_exc("G3 基类与生产路径（MdCGOS）同口径：同库同查询结果 id 逐位一致",
              lambda: ([r[0].get("id") for r in res_os] == ids,
                       "%s vs %s" % ([r[0].get("id") for r in res_os], ids)))
    res_off, _m3 = b.search(QUERY, k=5, include_neg=False, record=False)
    check_exc("G4 include_neg=False → 负节点完全不出现（改前仍作正候选出现一次）",
              lambda: ([r[0].get("id") for r in res_off] == ["mem_0"],
                       str([r[0].get("id") for r in res_off])))
    check_exc("G5 目标槽不进正排（与生产路径 _candidates 同口径）",
              lambda: (not any(str(i).startswith("goal_") for i in ids), str(ids)))
    b.close()
    osr.close()


# ------------------------------------------------------------------ F 组（H11⑥）
def group_f():
    print("\n[F] 飞轮建单只限真冲突 REJECT（收窄 ≠ 静默关掉飞轮）")

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
    check_exc("F1 判据单点且声明面同源：FLYWHEEL_TRIGGERS == ('REJECT',)，"
              "consistency_catalog() 的 triggers_on 与之逐位一致",
              lambda: (consistency.FLYWHEEL_TRIGGERS == ("REJECT",)
                       and cg.consistency_catalog()["auto_flywheel"]["triggers_on"]
                       == ["REJECT"], str(consistency.FLYWHEEL_TRIGGERS)))
    r = cg.check_consistency("删除生产数据", layer="self", auto_flywheel=True)
    check_exc("F2 真冲突 REJECT 仍建单（收窄不得把飞轮一起关掉）",
              lambda: (r["verdict"] == "REJECT" and bool(r.get("unresolved_id"))
                       and len(_unres(cg)) == 1,
                       "%s / %s / %s" % (r["verdict"], r.get("unresolved_id"),
                                         _unres(cg))))
    n0 = len(_unres(cg))
    r2 = cg.check_consistency("# 功能：生产批处理\n# 生效条件：生产环境\n",
                              layer="knowledge", auto_flywheel=True)
    check_exc("F3 DEFER（条件互斥待确认）不建单，但判定本身照旧返回"
              "（verdict=DEFER 且 strength ≥ CLASH_LOW）",
              lambda: (r2["verdict"] == "DEFER"
                       and r2["conflict_strength"] >= consistency.CLASH_LOW
                       and not r2.get("unresolved_id")
                       and len(_unres(cg)) == n0,
                       "%s/%s/unr=%s/n=%d" % (r2["verdict"],
                                              r2["conflict_strength"],
                                              r2.get("unresolved_id"),
                                              len(_unres(cg)))))
    e = _mk("fw_empty")
    r3 = e.check_consistency("# 功能：某情景\n# 生效条件：某个特殊条件\n",
                             layer="contextual", auto_flywheel=True)
    check_exc("F4 BLINDSPOT（既有节点全无声明 ⇒ 检测前提不存在）不建单"
              "（改前空库上每写一条都建一张工单）",
              lambda: (r3["verdict"] == "BLINDSPOT"
                       and not r3.get("unresolved_id") and not _unres(e),
                       "%s / unr=%s / n=%d" % (r3["verdict"],
                                               r3.get("unresolved_id"),
                                               len(_unres(e)))))
    cg.add("k_x", "# 功能：x\n# 生效条件：离线环境\n", layer="knowledge")
    n1 = len(_unres(cg))
    cg.add("k_y", "# 功能：y\n# 生效条件：生产环境\n", layer="knowledge",
           consistency=True)
    check_exc("F5 写链（add(consistency=True)）的 DEFER 同样不建单"
              "（同一判据，非各写一份）",
              lambda: (len(_unres(cg)) == n1,
                       "%d → %d" % (n1, len(_unres(cg)))))
    cg.close()
    e.close()


# ------------------------------------------------------------------ S 组（H11⑦⑤）
def group_s():
    print("\n[S] 工单身份＝语义 slug（同 slug 即同工单）；同题再检出时现场刷新")
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
    n1 = cg.get(id1) or {}
    fm1, c1 = n1.get("frontmatter") or {}, n1.get("content") or ""
    check_exc("S1a 首次检出建单且带「# 现场：」数值（前置）",
              lambda: (bool(id1) and "# 现场：" in c1 and "0.69" in c1, repr(c1[:80])))
    n_before = len(cg.index["nodes"])
    rep2 = dict(rep1)
    rep2["expected_state"] = "无条件"          # 措辞不同（不进身份）
    rep2["detail"] = [{"type": "same_condition_divergence", "with": "k_x",
                       "same_condition": 1.0, "slot_overlap": 1.0,
                       "conclusion_overlap": 0.12}]
    fw2 = cg.flywheel_step(rep2)
    n2 = cg.get(id1) or {}
    c2, fm2 = n2.get("content") or "", n2.get("frontmatter") or {}
    check_exc("S1 同一主题 + 同一实际态、措辞与现场数值不同的同一问题 → 同一张工单、"
              "零新建（改前按内容哈希各建一张）",
              lambda: (fw2["unresolved_id"] == id1
                       and len(cg.index["nodes"]) == n_before,
                       "%s vs %s / n=%d→%d" % (fw2["unresolved_id"], id1,
                                               n_before, len(cg.index["nodes"]))))
    rep3 = dict(rep2)
    rep3["actual_state"] = "REJECT"
    fw3 = cg.flywheel_step(rep3)
    check_exc("S2 不同实际态＝不同工单（身份含实际态，不误并）",
              lambda: (fw3["unresolved_id"] != id1, str(fw3["unresolved_id"])))
    check_exc("S3 工单身份可读且可用：id 含主题词、能被公共 API 解析回同一节点",
              lambda: (("隔离级别" in str(id1))
                       and (cg.get(id1) or {}).get("frontmatter", {}).get("id")
                       == id1, str(id1)))
    check_exc("S4 现场刷新：新数值在、旧数值不残留（同一张工单的正文就地更新）",
              lambda: ("0.12" in c2 and "0.69" not in c2,
                       repr([l for l in c2.splitlines() if l.startswith("# 现场")])))
    check_exc("S4b 刷新只动正文：id / created_at 保持建单事实不变",
              lambda: (fm2.get("created_at") == fm1.get("created_at")
                       and fm2.get("id") == id1,
                       str({k: fm2.get(k) for k in ("id", "created_at")})))

    def _zero_write():
        ent = cg.index["nodes"].get(id1) or {}
        path = os.path.join(cg.root, ent.get("path") or "")
        st0 = os.stat(path)
        b0 = open(path, "rb").read()
        cg.flywheel_step(rep2)
        st1 = os.stat(path)
        b1 = open(path, "rb").read()
        same = (b0 == b1 and st0.st_mtime_ns == st1.st_mtime_ns
                and st0.st_size == st1.st_size)
        same_c = (cg.get(id1) or {}).get("content") == c2
        return (same and same_c,
                "bytes/mtime 变化=%s content 一致=%s" % (not same, same_c))

    check_exc("S5 同输入再检出 → 零写盘（正文逐字相同即不制造脏写盘）", _zero_write)
    cg.close()


# ------------------------------------------------------------------ C 组（H11⑧）
def group_c():
    print("\n[C] CCG 哨兵直连入口同口径（复用同一张哨兵表，未新造第二张）")
    cg = _mk("sent")
    cg.add("z_a", SENT_A, layer="knowledge")
    cg.flush()
    vd_list = consistency.check(cg, SENT_B, layer="knowledge",
                                non_applicable_conditions=["无"],
                                auto_flywheel=True)
    vd_none = consistency.check(cg, SENT_B, layer="knowledge",
                                auto_flywheel=True)
    check_exc("C1 直连 consistency.check：显式哨兵列表「无」与不传同判"
              "（ACCEPT / strength 0.0 / 无 conflicts / 无工单）",
              lambda: (vd_list["verdict"] == vd_none["verdict"] == "ACCEPT"
                       and float(vd_list["conflict_strength"]) == 0.0
                       and not vd_list.get("unresolved_id")
                       and not (vd_list.get("conflicts") or []),
                       "%s/%s unr=%s" % (vd_list["verdict"],
                                         vd_list["conflict_strength"],
                                         vd_list.get("unresolved_id"))))
    nid = cg.add("z_b", SENT_B, layer="knowledge", consistency=True,
                 non_applicable_conditions=["无"])
    fm = (cg.get("z_b") or {}).get("frontmatter") or {}
    check_exc("C2 引擎入口 cg.add(consistency=True) + 哨兵列表 → ACCEPT（无工单）"
              "（改前 DEFER / strength=1.0 / 建单）",
              lambda: (bool(nid)
                       and (fm.get("consistency") or {}).get("verdict") == "ACCEPT"
                       and not (fm.get("consistency") or {}).get("unresolved_id"),
                       str(fm.get("consistency"))))

    def _family():
        forms = ["无", "（无）", "", "  ", "无。", "N/A", "-"]
        hits = [s for s in forms if mdcos._is_null_condition(s)]
        rows, bad = [], []
        for s in hits:
            v = consistency.check(cg, SENT_B, layer="knowledge",
                                  non_applicable_conditions=[s])
            ok = (v["verdict"] == vd_none["verdict"]
                  and abs(float(v["conflict_strength"])
                          - float(vd_none["conflict_strength"])) < 1e-9
                  and not v.get("unresolved_id") and not (v.get("conflicts") or []))
            rows.append((s, v["verdict"], v["conflict_strength"], ok))
            if not ok:
                bad.append(rows[-1])
        return (len(hits) >= 5 and not bad,
                "哨兵形态 %s | 不同判=%s" % (rows, bad))

    check_exc("C3 哨兵形态族（≥5 种）在直连入口全部与「不传」同判"
              "（同表同口径，不是只认了字面量「无」）", _family)
    real = ("# 功能名：本地开发约定\n"
            "# 生效条件：本地开发环境\n"
            "# 子功能：登记本地端口\n# 执行：核对本地清单\n"
            "# 验证方式：test\n"
            "# 不适用条件：本地开发环境\n\n本地监听端口 8081/HTTP\n")
    vd_real = consistency.check(cg, real, layer="knowledge",
                                non_applicable_conditions=["本地开发环境"],
                                auto_flywheel=True)
    check_exc("C4 防放宽：真负条件（自否定形态）不被哨兵剔除吞掉——仍判 REJECT "
              "且仍建单",
              lambda: (mdcos._is_null_condition("本地开发环境") is False
                       and vd_real["verdict"] == "REJECT"
                       and any(c.get("type") == "self_negation"
                               for c in (vd_real.get("conflicts") or []))
                       and bool(vd_real.get("unresolved_id")),
                       "%s/%s" % (vd_real["verdict"],
                                  vd_real.get("unresolved_id"))))
    cg.close()


# ------------------------------------------------------------------ H 组（M3）
def group_h():
    print("\n[H] bucket_health 呼叫点：把节点总数传进去（空库 vs 有节点零分桶可区分）")
    cg = _mk("m3_nobucket")
    for i in range(3):
        cg.add("s_%d" % i, "# 功能名：自我%d\n# 正文：某内容\n" % i,
               layer="self")
    cg.flush()
    h = cg.health()
    check_exc("H1 有节点但分桶表为空（全 self 层 → buckets=={}）→ 健康度不得报 ok"
              "（改前报 ok=True/reason=empty 冒充真空库）",
              lambda: (cg.index.get("buckets") == {}
                       and h.get("ok") is False
                       and h.get("reason") == "empty_buckets"
                       and h.get("nodes") == 3 and h.get("total_nodes") == 3,
                       "buckets=%s health=%s"
                       % (cg.index.get("buckets"),
                          {k: h.get(k) for k in ("ok", "reason", "nodes",
                                                 "total_nodes")})))
    cg.close()
    empty = _mk("m3_empty")
    h0 = empty.health()
    check_exc("H2 真空库（零节点零桶）→ ok=True/reason=empty（不误报）",
              lambda: (h0.get("ok") is True and h0.get("reason") == "empty"
                       and h0.get("total_nodes") == 0,
                       str({k: h0.get(k) for k in ("ok", "reason", "total_nodes")})))
    empty.close()
    check_exc("H3 两态可区分：同一份「空分桶」读数在两种库上给出不同的 ok/reason，"
              "且 nodes 如实为库内节点数",
              lambda: (h0.get("reason") != h.get("reason")
                       and h0.get("ok") != h.get("ok")
                       and h0.get("nodes") != h.get("nodes"),
                       "%s vs %s" % ({k: h0.get(k) for k in ("ok", "reason",
                                                             "nodes")},
                                     {k: h.get(k) for k in ("ok", "reason",
                                                            "nodes")})))
    check_exc("H4 向后兼容：缺省 total_nodes 的调用（既有调用方只传 counts）"
              "与加参数前逐位一致，且返回键集不因新参数变化",
              lambda: (routing.bucket_health({})
                       == {"ok": True, "reason": "empty", "buckets": 0}
                       and set(routing.bucket_health({"a": 5, "b": 5,
                                                      "c": 5}).keys())
                       == {"ok", "buckets", "nodes", "max_bucket_share",
                           "singleton_ratio", "expected_scan", "problems"},
                       "%s" % routing.bucket_health({})))
    one = _mk("m3_single")
    one.add("one", "# 功能名：单桶\n# 正文：知识面 内容\n", layer="knowledge")
    one.flush()
    h1 = one.health()
    check_exc("H5 单桶库如实读数：ok 仍为 False（判据未放宽）且不再被说成「巨桶」",
              lambda: (h1.get("buckets") == 1 and h1.get("ok") is False
                       and h1.get("problems")
                       and not any("巨桶" in p for p in h1["problems"]),
                       str(h1.get("problems"))))
    one.close()
    check_exc("H6 防放宽：多桶真巨桶（80%）仍被点名「巨桶」",
              lambda: (any("巨桶" in p for p in
                           routing.bucket_health({"a": 8, "b": 1,
                                                  "c": 1})["problems"]),
                       str(routing.bucket_health({"a": 8, "b": 1,
                                                  "c": 1})["problems"])))


_GROUPS = (group_n, group_d, group_g, group_f, group_s, group_c, group_h)


def _run_all():
    global PASS, FAIL, FAILS
    _RUN[0] += 1
    PASS, FAIL, FAILS = 0, 0, []
    for g in _GROUPS:
        g()
    return PASS, list(FAILS)


# ------------------------------------------------------------- 定点变异（自证）
#: 每项 = (文件, 正则, 替换, 期望转红的断言 id, 说明)。正则在**临时副本**的源码文本上
#: 命中恰好 1 处（命中数 ≠1 视为变异未生效，直接判红），把该处修复抽回改动前语义。
_MUTATIONS = {
    "H10-score": (
        "mdcg.py", r"(?m)^NEG_COVERAGE_SCORE = 0\.0\s*$",
        "NEG_COVERAGE_SCORE = 1.0", ["N1", "N2", "N2b", "N5"],
        "提示条目分数退回 1.0（改动前：高过任何真实候选）"),
    "H10-kbudget": (
        "mdcg.py", r"(?m)^\s*return max\(0, int\(k\) - int\(n_tail\)\)\s*$",
        "        return max(0, int(k))", ["N3"],
        "主结果退回 scored[:k]（尾巴在 k 之外 → 结果数 k+3）"),
    "H10-ddenom": (
        "mdcg.py",
        r"(?m)^\s*cands = \[r for r in results if not _is_neg_coverage\(r\[0\]\)\]\s*$",
        "        cands = list(results)", ["D1", "D2"],
        "D 分母退回含提示条目（信息差被虚高）"),
    "H7-negroute": (
        "mdcg.py",
        r"(?m)^(\s*)neg_layer_entries\.append\(e\)\n\s*continue\s*$",
        r"\1neg_layer_entries.append(e)", ["G1", "G2", "G3", "G4", "G5"],
        "抽掉循环里的 continue（负节点重新落进正排候选 = 双列）"),
    "H11-flywheel": (
        "consistency.py", r"(?m)^FLYWHEEL_TRIGGERS = \(\"REJECT\",\)\s*$",
        'FLYWHEEL_TRIGGERS = ("REJECT", "DEFER", "BLINDSPOT")',
        ["F1", "F3", "F4", "F5"], "自动建单面退回三态（DEFER/BLINDSPOT 也建单）"),
    "H11-sentinel": (
        "consistency.py",
        r"(?m)^    if non_applicable_conditions:\n"
        r"        from \.mdcos import _is_null_condition\n"
        r"        non_applicable_conditions = \[x for x in non_applicable_conditions\n"
        r"                                     if not _is_null_condition\(x\)\]\n",
        "    pass  # 变异：哨兵漏斗抽掉\n", ["C1", "C2", "C3"],
        "哨兵漏斗抽掉（直连入口把哨兵当真实条件）"),
    "H11-slug": (
        "mdcg.py", r"(?m)^\s*return _tasks\.slugify\(raw\)\s*$",
        "        return hashlib.sha1(str(question or \"\").encode()).hexdigest()[:10]",
        ["S1", "S3"], "工单身份退回内容哈希（措辞一变就另建一张）"),
    "H11-refresh": (
        "mdcg.py", r"(?m)^\s*fm, old = self\._read\(entry\)\s*$",
        "        return False\n        fm, old = self._read(entry)", ["S4"],
        "刷新抽掉（同 id 直接 return，现场永久冻结）"),
    "M3-health": (
        "mdcg.py",
        r"(?m)^\s*h = routing\.bucket_health\(self\.index\.get\(\"buckets\", \{\}\),\n"
        r"\s*total_nodes=len\(self\.index\[\"nodes\"\]\)\)\s*$",
        '        h = routing.bucket_health(self.index.get("buckets", {}))',
        ["H1", "H3"], "呼叫点退回不传 total_nodes（有节点零分桶仍是 ok=True）"),
}

_ASSERT_RE = re.compile(r"^\s*(?:\[FAIL\]|FAIL)\s+(\S+)")


def _reds(stdout):
    out = []
    for line in (stdout or "").splitlines():
        m = _ASSERT_RE.match(line)
        if m:
            out.append(m.group(1))
    return out


def _md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def _run_guard(cwd):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = cwd
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "md_cg.test_recall_face_guards"],
        cwd=cwd, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")


def _mutate_mode(which):
    repo = os.path.dirname(_HERE)
    names = list(_MUTATIONS) if which == "all" else [which]
    files = sorted({_MUTATIONS[n][0] for n in names
                    if n in _MUTATIONS})
    for n in names:
        if n not in _MUTATIONS:
            print("未知变异 %r（可选：%s）" % (n, sorted(_MUTATIONS)))
            return 2
    before = {f: _md5(os.path.join(_HERE, f)) for f in files}
    targets = []
    rc = 0
    print("\n=== 定点变异自证（在**临时副本**源码上抽掉修复 → 本守卫必红 → "
          "在役树复跑必绿）===")
    print("  基准在役树：%s" % ", ".join("%s=%s" % (f, before[f]) for f in files))
    for name in names:
        fname, pat, sub, want, note = _MUTATIONS[name]
        tmp = tempfile.mkdtemp(prefix="recall_face_mut_")
        try:
            shutil.copytree(_HERE, os.path.join(tmp, "md_cg"),
                            ignore=shutil.ignore_patterns("__pycache__"))
            path = os.path.join(tmp, "md_cg", fname)
            targets.append(path)
            with open(path, encoding="utf-8") as f:
                src = f.read()
            hits = len(re.findall(pat, src))
            if hits != 1:
                print("  FAIL 变异 %s 未生效：源码命中 %d 处（期望 1）" % (name, hits))
                rc = 1
                continue
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(re.sub(pat, sub, src, count=1))
            r = _run_guard(tmp)
            reds = _reds(r.stdout)
            missed = [w for w in want if w not in reds]
            summary = [l for l in (r.stdout or "").splitlines()
                       if l.startswith("====")]
            print("  [%s] %s" % (name, note))
            print("     基准副本 %s（抽掉修复的那份）" % path)
            print("     rc=%d 红项 %d 个：%s" % (r.returncode, len(reds),
                                                " ".join(reds) or "（无）"))
            print("     %s" % (summary[-1] if summary else "（无汇总行）"))
            if r.returncode != 1 or not reds:
                print("  FAIL 变异 %s 未打红（rc=%d，红项 0）——守卫对该修复无判别力"
                      % (name, r.returncode))
                print("     stderr: %s" % (r.stderr or "")[-400:])
                rc = 1
            elif missed:
                print("  FAIL 变异 %s 未打红预期断言：%s" % (name, missed))
                rc = 1
            else:
                print("  ok   变异 %s 打红预期断言 %d 项" % (name, len(want)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("  ok   变异落笔点共 %d 处，全部在临时副本内（在役树零写入由构造保证，"
          "并已 rmtree）：%s" % (len(targets), "; ".join(targets[:2]) + (" …" if
                                                                      len(targets) > 2 else "")))
    after = {f: _md5(os.path.join(_HERE, f)) for f in files}
    if before != after:
        print("  FAIL 在役源码 md5 与基准不同（%s）——本驱动不写在役树，"
              "若确有差异即为**并发改动**落在同一工作树；本轮的变异读数以副本快照为准，"
              "须在稳定树上重跑本模式后再采信。" % after)
        rc = 1
    else:
        print("  ok   在役工作树基准一致（读数为副本快照，落笔面只在临时副本）：%s"
              % ", ".join("%s=%s" % (f, after[f]) for f in files))
    r0 = _run_guard(repo)
    reds0 = _reds(r0.stdout)
    tail0 = [l for l in (r0.stdout or "").splitlines() if l.startswith("====")]
    print("  [恢复] 在役树原样复跑：rc=%d 红项=%d  %s"
          % (r0.returncode, len(reds0), tail0[-1] if tail0 else ""))
    if r0.returncode != 0 or reds0:
        print("  FAIL 恢复后未转绿，残余红项：%s" % (reds0 or "rc≠0"))
        rc = 1
    else:
        print("  ok   无残余红项")
    return rc


def main(argv):
    which = None
    for a in argv:
        if a.startswith("--source-mutate"):
            which = a.split("=", 1)[1] if "=" in a else "all"
    if which is not None:
        return _mutate_mode(which)
    ok, bad = _run_all()
    print("\n==== 召回面守卫（H10/H7/H11/M3 呼叫点）：%d 通过 / %d 失败%s ===="
          % (ok, len(bad), ("：" + "; ".join(bad)) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        _rc = main(sys.argv[1:])
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(_rc)
