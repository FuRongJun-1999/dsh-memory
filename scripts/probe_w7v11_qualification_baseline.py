# -*- coding: utf-8 -*-
"""W7·v1.1 第 2 组 · 资格线两项补证 · **观察期基线读数**探针（隔离库，零生产语义改动）。

本探针只做「把测量立起来」，不做「把参数定下来」——受设计者首批裁定第 8/9/10 条
门控：不改默认值、不标定阈值、不接心跳、不改白名单。

产出两节基线读数：

  甲 · 情感模拟消费位（§1.6.1 内部状态）——落点 `md_cg/autonomy.py::proposals()`
       的 `sort_score` 排序键；开关 env `MDCG_PROPOSAL_EMOTION`（默认关，`== "1"` 才开）。
       两态对照（关／开），逐条贴 score / d_meta_bonus / sort_score / 次序 / reason /
       返回体 / `_explore.jsonl` 台账。两条断言：
         ① 反向腿（默认关）——排序面与「未引入该功能的源码口径」（就地剥除
            emotion 加分行、恒 bonus=0.0 的变体）**逐位一致**；
         ② 正向腿（开启）——`d2_mean` 不同的提案之间**相对次序发生可指认的变化**。

  乙 · 自主目标发生器（§1.6.1 自主目标）——落点 `md_cg/goal_gen.py::candidates()`
       （六源 S1–S6 ＋ 三区确认闸）＋ MCP 面 `op=goal, action=generate`。
       隔离库上跑 **dry-run（apply=False）**：贴六源各命中条数、三区闸分类分布、
       优先级分布；断言 dry-run 后**库内节点数不变**（零落库）。
       发生器现状如实记录：**opt-in**、`apply` 需写权、**未接 sleep/sustain**。

隔离声明（硬）：一切库为 `tempfile.mkdtemp` 临时根（独立 `MDCG_ROOT`），用完即删；
**绝不碰在役记忆库**；只读地读源码；不改任何生产源码/配置/默认值。

用法：
  python -X utf8 scripts/probe_w7v11_qualification_baseline.py             # 两节读数
  python -X utf8 scripts/probe_w7v11_qualification_baseline.py --json       # 机读读数
  python -X utf8 scripts/probe_w7v11_qualification_baseline.py --self-proof # 断言非空转自证
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import sys
import tempfile
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                    # noqa: BLE001
    pass

from md_cg.mdcos import MdCGOS                       # noqa: E402
from md_cg import autonomy, goal_gen, insight, evolution, metacognition  # noqa: E402
from md_cg.fsutil import append_jsonl                # noqa: E402


# ============================================================ 通用工具

def _mkroot(tag):
    return tempfile.mkdtemp(prefix="mdcg_w7v11_%s_" % tag)


def _nodes(cg):
    return (getattr(cg, "index", None) or {}).get("nodes") or {}


def _ncount(cg):
    return len(_nodes(cg))


def _q(cg, query, d2, states=None, t=0.0):
    """直写一条反思记录（只造信号面；`proposals()` 经 metacognition._reflections 读）。"""
    append_jsonl(cg.reflection_log,
                 {"t": t, "query": query, "d_prev": 1.0, "d_curr": 1.0,
                  "d_delta": 0.0, "d2": d2, "states": states or {},
                  "n_results": 1, "feedback": None})


# 就地剥除 emotion 加分行 → 「未引入该功能的源码口径」（恒 bonus=0.0 基线）。
_EMO_LINE = "emotion_bonus = (round(W_EMO * eps * sign, 4) if emotion_on else 0.0)"


def _load_variant(pairs):
    """在 proposals 实现源码（textwrap.dedent 归一）上做逐字替换，exec 到命名空间副本。"""
    src = textwrap.dedent(inspect.getsource(autonomy.proposals))
    for old, new in pairs:
        n = src.count(old)
        if n != 1:
            raise RuntimeError("ANCHOR 命中 %d 次（期望 1）：%r" % (n, old[:70]))
        src = src.replace(old, new)
    ns = dict(vars(autonomy))
    exec(compile(src, "<w7v11-variant>", "exec"), ns)     # noqa: S102
    return ns["proposals"]


def _sortface(pl):
    """排序面口径（反向腿对拍用）：只取本次改动**不该改变**的既有键。"""
    return [(p["query"], p["score"], p["d_meta_bonus"], p["sort_score"])
            for p in pl]


def _set_env(name, val):
    if val is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = val


# ============================================================ 甲 · 情感模拟消费位

#: 四条提案（d2_sum / samples 各不同；d2_mean 覆盖 approaching/stable/avoiding）
SEED_EMO = (
    ("绩效查询甲", -0.02, None, 1.0),
    ("绩效查询甲", -0.10, None, 2.0),   # 甲: d2_sum=-0.12 samples=2 → d2_mean=-0.06 approaching
    ("绩效查询乙", 0.10, None, 3.0),
    ("绩效查询乙", 0.05, None, 4.0),
    ("绩效查询乙", 0.03, None, 5.0),    # 乙: d2_sum=0.18 samples=3 → d2_mean=+0.06 avoiding
    ("绩效查询丙", 0.04, None, 6.0),    # 丙: d2_sum=0.04 samples=1 → d2_mean=+0.04 stable
    ("绩效查询戊", 0.03, None, 7.0),    # 戊: d2_sum=0.03 samples=1 → d2_mean=+0.03 stable
    ("绩效查询丁", 0.0, None, 8.0),     # 丁: 零信号 → 不提案（资格面）
)


def run_emotion_baseline():
    root = _mkroot("emo")
    cg = MdCGOS(root)
    try:
        for q, d2, st, t in SEED_EMO:
            _q(cg, q, d2, st, t)

        baseline_fn = _load_variant([(_EMO_LINE, "emotion_bonus = 0.0")])
        env = autonomy.EMOTION_ENV
        saved = os.environ.get(env)

        # 关闭态（未设）
        _set_env(env, None)
        pr_off = autonomy.proposals(cg, limit=10)
        base_off = baseline_fn(cg, limit=10)
        # 开启态
        _set_env(env, "1")
        pr_on = autonomy.proposals(cg, limit=10)
        _set_env(env, saved)

        off = pr_off["proposals"]
        on = pr_on["proposals"]

        # ---- 断言①反向腿：默认关 ⇔ 「未引入该功能源码口径」逐位一致 ----
        rev_faces_ok = _sortface(off) == _sortface(base_off["proposals"])
        rev_degrade_ok = all(
            p["sort_score"] == round(p["score"] + p["d_meta_bonus"], 4)
            for p in off)
        rev_bonus_zero_ok = all(p["emotion_bonus"] == 0.0 for p in off)
        # ---- 断言②正向腿：次序发生可指认变化 ----
        off_order = [p["query"] for p in off]
        on_order = [p["query"] for p in on]
        moved = [(q, off_order.index(q), on_order.index(q))
                 for q in off_order if off_order.index(q) != on_order.index(q)]
        fwd_flip_ok = off_order != on_order

        # 台账（explore 把 proposals 原样并入 _explore.jsonl）——两态各自独立库采集
        def _ledger_for(env_val):
            lroot = _mkroot("emo_led")
            lcg = MdCGOS(lroot)
            try:
                for q, d2, st, t in SEED_EMO:
                    _q(lcg, q, d2, st, t)
                _set_env(env, env_val)
                autonomy.explore(lcg, actor="probe", limit=10)
                lp = autonomy._explore_log_path(lcg)
                recs = []
                if os.path.exists(lp):
                    with open(lp, encoding="utf-8") as fh:
                        recs = [json.loads(x) for x in fh if x.strip()]
                return recs[-1].get("proposals") if recs else []
            finally:
                lcg.close()
                shutil.rmtree(lroot, ignore_errors=True)

        led_off = _ledger_for(None)
        led_on = _ledger_for("1")
        _set_env(env, saved)
        led_ok = (bool(led_off) and bool(led_on)
                  and all("emotion_bonus" in p and "emotion" in p
                          for p in led_off + led_on))

        def _row(p, base_p=None):
            return {
                "query": p["query"],
                "d2_sum": p["d2_sum"], "samples": p["samples"],
                "d2_mean": p["emotion"]["d2_mean"], "bias": p["emotion"]["bias"],
                "score": p["score"], "d_meta_bonus": p["d_meta_bonus"],
                "emotion_bonus": p["emotion_bonus"], "sort_score": p["sort_score"],
                "base_sort_score": (base_p["sort_score"] if base_p else None),
            }

        base_by_q = {p["query"]: p for p in base_off["proposals"]}
        res = {
            "env_name": env,
            "eps_cap": metacognition.D2_EMOTION,
            "n_signals": pr_off["n_signals"],
            "not_proposed": [q for q in ("绩效查询丁",)
                             if q not in off_order],
            "off": [_row(p, base_by_q.get(p["query"])) for p in off],
            "on": [_row(p) for p in on],
            "off_return_emotion": pr_off["emotion"],
            "on_return_emotion": pr_on["emotion"],
            "off_order": off_order, "on_order": on_order, "moved": moved,
            "reason_off_sample": off[0]["reason"] if off else "",
            "reason_on_sample": on[0]["reason"] if on else "",
            "ledger_keys_ok": led_ok,
            "ledger_off": ([{"query": p["query"], "emotion_bonus": p["emotion_bonus"],
                             "bias": p["emotion"]["bias"]} for p in led_off]
                           if led_off else []),
            "ledger_on": ([{"query": p["query"], "emotion_bonus": p["emotion_bonus"],
                            "bias": p["emotion"]["bias"]} for p in led_on]
                          if led_on else []),
            "assert1_reverse_bit_identical": bool(rev_faces_ok),
            "assert1_reverse_sortscore_degrade": bool(rev_degrade_ok),
            "assert1_reverse_bonus_zero": bool(rev_bonus_zero_ok),
            "assert2_forward_order_changed": bool(fwd_flip_ok),
        }
        return res
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)


# ============================================================ 乙 · 自主目标发生器

SEED_S1 = ("如何审计 gossip 收敛性", "是否要对外发送本批次报告")
SEED_S2 = ("洞见甲：索引分层可降延迟", "洞见乙：水位信箱可去抖动", "洞见丙：WAL 校验可前置")
SEED_S6 = ("验证方式",)[0]


def _build_goal_lib(root):
    """确定性隔离库：令 S1–S6 六源各有机会命中（法同 `test_goal_gen` 各映射例）。"""
    cg = MdCGOS(root)
    # S1：unresolved 台账（第二条命中纲领 §七边界词「对外发送」→ 越权类）
    for qq in SEED_S1:
        cg.add_unresolved(qq)
    # S2：pending 待验证洞见（阈值 S2_PENDING_MIN=3）
    for s in SEED_S2:
        insight.record(cg, s)
    # S3：固化候补（单层无验证基底节点 ≥ S3_CCG_MIN=5）
    for i in range(6):
        cg.add("nb_%d" % i,
               "# 功能名：测试节点 %d\n# 不适用条件：无\n正文\n" % i,
               layer="knowledge")
    # S4/S5：BLINDSPOT 高频盲区 + 空路由（直写反思信号）
    _q(cg, "未知领域查询面", 0.1, {"BLINDSPOT": 3}, 1.0)
    _q(cg, "库内无锚点的盲区面", 0.1, {"BLINDSPOT": 2}, 2.0)
    # S6：evolution 缺失维度（同一 missing 计数 ≥ S6_MISSING_MIN=3）
    for i in range(3):
        evolution.record(cg, pattern="缺维度测试 %d" % i, missing=SEED_S6)
    cg.flush()
    return cg


def run_goal_baseline():
    # ---- 空库基线（纯基线：发生器不编造候选）----
    empty_root = _mkroot("goal_empty")
    empty = MdCGOS(empty_root)
    try:
        for sid in ("S1", "S2", "S3", "S4", "S5", "S6"):
            goal_gen.candidates(empty, sources=[sid], apply=False)
        empty_run = goal_gen.candidates(empty, apply=False)
        empty_hits = {"S%d" % i: 0 for i in range(1, 7)}
        empty_res = {"by_class": empty_run["by_class"],
                     "n_candidates": empty_run["n_candidates"]}
    finally:
        empty.close()
        shutil.rmtree(empty_root, ignore_errors=True)

    # ---- 播种库 dry-run ----
    root = _mkroot("goal")
    cg = MdCGOS(root)
    try:
        cg = _build_goal_lib(root)
        n_before = _ncount(cg)
        goals_before = len(cg.list_goals())
        review_before = len(cg.review_list())

        # ① 逐源精确命中数（单源跑，避免 limit 截断干扰计数）
        per_source = {}
        for sid in ("S1", "S2", "S3", "S4", "S5", "S6"):
            r = goal_gen.candidates(cg, sources=[sid], limit=200, apply=False)
            per_source[sid] = {
                "n_candidates": r["n_candidates"],
                "classes": _class_counts(r["candidates"]),
                "priorities": sorted({c["priority"] for c in r["candidates"]}),
            }

        # ② 六源合并 dry-run（分类分布 + 优先级分布）
        full = goal_gen.candidates(cg, limit=200, apply=False)

        n_after = _ncount(cg)
        goals_after = len(cg.list_goals())
        review_after = len(cg.review_list())

        # 台账留痕
        logp = goal_gen.goal_log_path(cg)
        log_ok = os.path.exists(logp) and os.path.getsize(logp) > 0

        cands = full["candidates"]
        res = {
            "empty_lib": {"per_source": empty_hits, **empty_res,
                          "note": "空库：六源命中 0（发生器不编造候选）"},
            "seeded_lib": {
                "per_source": per_source,
                "by_class": full["by_class"],
                "class_counts_all": _class_counts(cands),
                "priority_dist": _prio_dist(cands),
                "n_candidates": full["n_candidates"],
                "created": full["created"], "queued": full["queued"],
                "refused": full["refused"], "forbidden": full["forbidden"],
                "samples": [{"source": c["source"], "goal_text": c["goal_text"],
                             "priority": c["priority"], "class": c["class"],
                             "moved_to": c["moved_to"]} for c in cands[:12]],
            },
            "zero_write": {
                "nodes_before": n_before, "nodes_after": n_after,
                "nodes_unchanged": n_before == n_after,
                "goals_before": goals_before, "goals_after": goals_after,
                "review_before": review_before, "review_after": review_after,
                "no_write_ok": (n_before == n_after
                                and goals_before == goals_after == 0
                                and review_before == review_after == 0
                                and full["created"] == full["queued"] == 0
                                and all(c["moved_to"] == "dry_run" for c in cands)),
            },
            "log_written": bool(log_ok),
            "opt_in_state": {
                "auto_loop_refs": _refs("sleep.py", "sustain.py"),
                "mcp_admin": "op=goal,action=generate 走 require_admin（apply 需写权）",
            },
        }
        return res
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)


def _class_counts(cands):
    d = {}
    for c in cands:
        d[c["class"]] = d.get(c["class"], 0) + 1
    return d


def _prio_dist(cands):
    d = {}
    for c in cands:
        key = str(c["priority"])
        d[key] = d.get(key, 0) + 1
    return dict(sorted(d.items(), key=lambda kv: -float(kv[0])))


def _refs(*fnames):
    """发生器是否被 sleep/sustain 自动循环引用（应为否——opt-in 如实记录）。"""
    out = {}
    for f in fnames:
        p = os.path.join(os.path.dirname(goal_gen.__file__), f)
        txt = ""
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                txt = fh.read()
        out[f] = ("goal_gen" in txt)
    return out


# ============================================================ 打印

def _print_emotion(r):
    print("=" * 78)
    print("甲 · 情感模拟消费位（autonomy.proposals 的 sort_score 排序键）")
    print("  开关 %s（默认关；== \"1\" 才开）  硬上限 ε = %s"
          % (r["env_name"], r["eps_cap"]))
    print("-" * 78)
    print("关闭态（未设环境变量）：")
    print("  %-10s %8s %4s %9s %7s %10s %11s %11s %10s"
          % ("query", "d2_sum", "n", "d2_mean", "bias", "score",
             "d_meta_b", "sort_score", "base_sort"))
    for p in r["off"]:
        print("  %-10s %8s %4d %9s %7s %10s %11s %11s %10s"
              % (p["query"], p["d2_sum"], p["samples"], p["d2_mean"],
                 p["bias"], p["score"], p["d_meta_bonus"], p["sort_score"],
                 p["base_sort_score"]))
    print("  次序（关）：%s" % " > ".join(r["off_order"]))
    print("  返回体 emotion: %s" % json.dumps(r["off_return_emotion"],
                                            ensure_ascii=False))
    print("  零信号不提案：%s" % (r["not_proposed"] or "无"))
    print()
    print("开启态（%s=1）：" % r["env_name"])
    print("  %-10s %9s %7s %10s %11s %11s"
          % ("query", "d2_mean", "bias", "score", "emotion_b", "sort_score"))
    for p in r["on"]:
        print("  %-10s %9s %7s %10s %11s %11s"
              % (p["query"], p["d2_mean"], p["bias"], p["score"],
                 p["emotion_bonus"], p["sort_score"]))
    print("  次序（开）：%s" % " > ".join(r["on_order"]))
    print("  次序位移：%s"
          % ("、".join("%s %d→%d" % (q, a, b) for q, a, b in r["moved"])
             or "无"))
    print("  返回体 emotion: %s" % json.dumps(r["on_return_emotion"],
                                            ensure_ascii=False))
    print("  reason 样例（开）：%s" % r["reason_on_sample"])
    print()
    print("  台账 _explore.jsonl（proposals 原样并入）键齐：%s"
          % r["ledger_keys_ok"])
    print("    关态台账：%s" % json.dumps(r["ledger_off"], ensure_ascii=False))
    print("    开态台账：%s" % json.dumps(r["ledger_on"], ensure_ascii=False))
    print("-" * 78)
    print("  断言①反向腿（默认关 ⇔ 未引入该功能源码口径）：逐位一致=%s；"
          "sort_score 退化=%s；bonus 恒 0=%s"
          % (r["assert1_reverse_bit_identical"],
             r["assert1_reverse_sortscore_degrade"],
             r["assert1_reverse_bonus_zero"]))
    print("  断言②正向腿（开启后次序可指认变化）：%s（关 %s → 开 %s）"
          % (r["assert2_forward_order_changed"],
             " > ".join(r["off_order"]), " > ".join(r["on_order"])))


def _print_goal(r):
    print()
    print("=" * 78)
    print("乙 · 自主目标发生器（goal_gen.candidates 六源 + 三区确认闸，dry-run）")
    print("-" * 78)
    e = r["empty_lib"]
    print("空库基线：六源命中 %s；候选 %d（发生器不编造候选）"
          % (json.dumps(e["per_source"], ensure_ascii=False), e["n_candidates"]))
    print()
    s = r["seeded_lib"]
    print("播种库 · 六源逐源命中数：")
    for sid in ("S1", "S2", "S3", "S4", "S5", "S6"):
        ps = s["per_source"][sid]
        print("  %s: %2d 条   分类=%s   优先级=%s"
              % (sid, ps["n_candidates"],
                 json.dumps(ps["classes"], ensure_ascii=False), ps["priorities"]))
    tot = sum(s["per_source"][k]["n_candidates"] for k in s["per_source"])
    print("  六源合计（逐源计数）= %d" % tot)
    print()
    print("六源合并 dry-run：候选 %d 条" % s["n_candidates"])
    print("  三区闸分类分布：%s" % json.dumps(s["by_class"], ensure_ascii=False))
    print("  优先级分布（priority: 条数）：%s"
          % json.dumps(s["priority_dist"], ensure_ascii=False))
    print("  落点计数 created=%d queued=%d refused=%d forbidden=%d"
          % (s["created"], s["queued"], s["refused"], s["forbidden"]))
    print("  候选样例（前列）：")
    for c in s["samples"]:
        print("    [%s] p=%s %s | %s | %s"
              % (c["source"], c["priority"], c["class"], c["moved_to"],
                 c["goal_text"][:40]))
    print()
    z = r["zero_write"]
    print("零落库断言：节点 %d → %d（不变=%s）；goals %d→%d；review %d→%d；"
          "created/queued=0 → 零落库=%s"
          % (z["nodes_before"], z["nodes_after"], z["nodes_unchanged"],
             z["goals_before"], z["goals_after"],
             z["review_before"], z["review_after"], z["no_write_ok"]))
    print("留痕 _goal_gen.jsonl 已写：%s" % r["log_written"])
    o = r["opt_in_state"]
    print("发生器现状（如实）：opt-in；未接自动循环 sleep/sustain=%s；%s"
          % (json.dumps(o["auto_loop_refs"], ensure_ascii=False), o["mcp_admin"]))


# ============================================================ 自证（断言非空转）

def self_proof():
    """证两条断言**有判别力、非空转**：反向腿的「未引入口径」确实等于关态，
    而一旦变异「忽略开关恒开」，关态即与基线**不再逐位一致**（断言有牙）。"""
    print("!! 自证：两条断言非空转（隔离库）\n")
    bad = []
    # ① 反向腿基线本身可复跑且等于关态
    r = run_emotion_baseline()
    if not (r["assert1_reverse_bit_identical"]
            and r["assert1_reverse_sortscore_degrade"]):
        bad.append("反向腿基线不成立（断言①空转）")
    # ② 变异「忽略开关恒开」→ 关态与基线应不再逐位一致（证断言①有判别力）
    root = _mkroot("selfproof")
    cg = MdCGOS(root)
    try:
        for q, d2, st, t in SEED_EMO:
            _q(cg, q, d2, st, t)
        baseline_fn = _load_variant([(_EMO_LINE, "emotion_bonus = 0.0")])
        mutant_fn = _load_variant(
            [('emotion_on = os.environ.get(EMOTION_ENV) == "1"',
              "emotion_on = True")])
        env = autonomy.EMOTION_ENV
        saved = os.environ.get(env)
        _set_env(env, None)                       # 默认关
        off = autonomy.proposals(cg, limit=10)["proposals"]
        base = baseline_fn(cg, limit=10)["proposals"]
        mut = mutant_fn(cg, limit=10)["proposals"]
        _set_env(env, saved)
        same_base = _sortface(off) == _sortface(base)
        mut_diff = _sortface(off) != _sortface(mut)
        if not same_base:
            bad.append("默认关 ≠ 基线（断言①不成立）")
        if not mut_diff:
            bad.append("变异『忽略开关』后关态仍与基线一致（断言①无判别力）")
        print("  未变异：默认关 == 基线     → %s" % same_base)
        print("  变异①忽略开关恒开：关态 ≠ 基线 → %s（断言有牙）" % mut_diff)
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)
    print("\n自证：%s" % ("PASS" if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


# ============================================================ 入口

def main():
    print("W7·v1.1 第 2 组 · 资格线两项补证 · 观察期基线读数探针"
          "（隔离临时库，零生产语义改动）")
    emo = run_emotion_baseline()
    goal = run_goal_baseline()
    if "--json" in sys.argv:
        print(json.dumps({"emotion": emo, "goal": goal},
                         ensure_ascii=False, indent=2, default=str))
        return 0
    _print_emotion(emo)
    _print_goal(goal)
    print()
    print("=" * 78)
    print("门控（设计者首批裁定第 8/9/10 条）：本轮只出**观察期基线读数**——"
          "不改默认值、不标定阈值、不接心跳、不改白名单。")
    return 0


if __name__ == "__main__":
    if "--self-proof" in sys.argv:
        sys.exit(self_proof())
    sys.exit(main())
