# -*- coding: utf-8 -*-
"""W7/v1.1 组3b · 递归稳定性「多轮回灌加压对照」探针（隔离临时库，零生产语义改动）。

问题（`docs/eval/W5_路线B_路径指纹与加压对照_v0.1.md` §2.6 局限③；`docs/plans/
灵枢1.0_最小智能系统实存答卷_v1.1.md` §三「递归稳定性」局限、§七 第 8 项）：
W5 的加压对照只覆盖了 **L2 递归展开**（静态库、三档旋钮：候选截断 / 递归预算收紧 /
库噪声），**未覆盖第二类递归压力——「多轮回灌」**（睡眠自迭代 `md_cg/sleep.py`
`iterate` 与两段式 `md_cg/twophase.py` 的同类语义：同一批内容被一轮又一轮地
反复处理、期间库的**层归属 / 新鲜度 / 台账 / 规模**随时间演化）。本探针补这一格。

**本探针 vs `scripts/probe_w5_recursion_pressure.py`**（为何另起一文件、不扩档）：
  · W5 探针的契约是「**一份静态库**、三个压力旋钮、**零写库**」——被测对象是不随
    时间变化的库。回灌档的契约相反：**库在轮次之间被写变**（这正是「回灌」的
    语义），压力来自**状态演化**而非单次调参。两者是不同的实验轴，混进同一探针会
    破坏 W5「原文可复跑、读数不变」的性质。
  · 为**可比性**，本探针 **import** W5 探针的 `BATCH`/`build_lib`——判定批与库布局
    逐字同构，故「跨档翻转率（A 无压力 / B 加压力 / C 噪声 ↔ D 多轮回灌）」是在
    同一套输入上对照，不是两套不同实验各说各话。

回灌如何施加（全部在 `tempfile` 沙箱，绝不碰在役库、绝不触发真实睡眠自迭代写盘）：
  在同一隔离库上连续跑 `ROUNDS` 轮，每轮：
    ① **判定**：对同一批 `BATCH`（覆盖四态 + 递归）重跑一遍，读取数
       （verdict / conflict_strength / scanned / kept / comparable /
        recursion.stopped_by / depth / gain / resolved_by / trace）；
    ② **回灌（对下一轮库做功）**：把本批**全部内容**（含库内既有相关节点
       `s_disc` 的语义内容）以**新 id** 原样再写入 `knowledge` 层一次——
       模拟「同一批内容被一轮又一轮反复回灌」；副本带**确定性且随轮递增的
       `valid_from`**（新鲜度时间轴随轮演化）。
  其中「把异层的区分节点 `s_disc` 的**副本**回灌进 `knowledge` 层」= 模拟睡眠自
  迭代的**升层（promote）**把区分条件带进主判定扫描面（层归属随轮演化）。

读数（本实验核心）：
  · **轮内确定性**＝同一轮库状态重复跑 `REPEATS` 次，判定是否逐条变化；
  · **跨轮翻转率**＝第 1 轮（＝A 档同构基线）vs 第 r 轮，判定是否逐条变化
    ——这是「多轮回灌是否漂移判定」的**直接读数**；
  · **跨档翻转率**＝既有三档（A/B/C）↔ 回灌档（第 1 轮 / 末轮）；
  · **压力吸收位置**＝scanned / comparable 随轮增长（回灌副本进入选面）、递归
    frontier / fresh / gain / stopped_by 随轮变化——即压力落在哪个读数、是否外溢
    到 verdict。

隔离声明：一切库为 `tempfile.mkdtemp` 临时根，用完即删；判定一律
`log_write=False`（不落台账）；回灌只写临时沙箱、**不碰在役库**；不改任何生产语义。

用法：
  python -X utf8 scripts/probe_w7v11_recursion_replay.py              # 正向读数
  python -X utf8 scripts/probe_w7v11_recursion_replay.py --self-proof # 自证（压力确已施加）
  python -X utf8 scripts/probe_w7v11_recursion_replay.py --json       # 机读读数
"""
import json
import shutil
import sys
import tempfile
import unicodedata

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
sys.stdout.reconfigure(encoding="utf-8")

from md_cg.mdcos import MdCGOS                      # noqa: E402
import probe_w5_recursion_pressure as w5            # noqa: E402  复用判定批与库布局

REPEATS = 3            # 同轮库状态重复次数（轮内确定性采样）
ROUNDS = 6             # 回灌轮数
#: 回灌副本的新鲜度时间轴起点（确定性常数——**不含** time.time()/uuid，保证可复跑）
REFLOW_T0 = 1700000000
#: 区分节点语义内容（与 W5 build_lib 里的 s_disc 正文逐字同构——回灌副本进知识层）
S_DISC_CONTENT = "# 功能：区分节点\n"
#: 边界反例构造（`--boundary`）：一条**携带新冲突**的回灌节点——其不适用条件恰好
#: 覆盖 ACCEPT 判定的生效条件（`无人占用的条件`）。用于界定「翻转率 0」的边界：
#: 若回灌内容**引入新冲突**，判定是否会漂移（与主档"同等内容回灌"对照）。
BOUNDARY_CONFLICT = ("# 功能：边界冲突源\n# 生效条件：某条件\n"
                     "# 不适用条件：无人占用的条件\n")


def _mkroot():
    return unicodedata.normalize("NFC", tempfile.mkdtemp(prefix="mdcg_w7rp_"))


def judge_batch(cg, limit=200, depth=3):
    """在**当前库状态**下跑整批 BATCH，返回 {name: 读数}（含递归明细）。"""
    out = {}
    for it in w5.BATCH:
        r = cg.check_consistency(
            it["content"], layer=it["layer"],
            non_applicable_conditions=it.get("non_applicable_conditions"),
            depth=depth, limit=limit, log_write=False)
        rec = r.get("recursion") or {}
        out[it["name"]] = {
            "verdict": r["verdict"],
            "strength": round(r["conflict_strength"], 4),
            "scanned": r["scanned"], "kept": r["kept"],
            "truncated": bool(r["truncated"]),
            "comparable": r["comparable"],
            "stopped_by": rec.get("stopped_by"),
            "depth": rec.get("depth"),
            "gain": rec.get("gain"),
            "resolved": len(rec.get("resolved_by") or []),
            "trace": rec.get("trace"),
        }
    return out


def reflow(cg, r):
    """一轮**回灌**（对下一轮库做功）——把本批内容 + 区分节点以新 id 重复写入
    `knowledge` 层，副本带随轮递增的确定性 `valid_from`（新鲜度演化）。

    返回本轮回灌写入的节点 id 列表（供自证核对）。
    """
    written = []
    base_t = REFLOW_T0 + r * 1000
    for idx, it in enumerate(w5.BATCH):
        nid = "reflow_%02d_i%02d" % (r, idx)
        cg.add(nid, it["content"], layer="knowledge",
               non_applicable_conditions=it.get("non_applicable_conditions"),
               importance=0.2, valid_from=base_t)
        written.append(nid)
    # 异层的区分节点 s_disc 的「升层副本」→ 进入 knowledge 扫描面（层归属压力）
    nid = "reflow_%02d_sdisc" % r
    cg.add(nid, S_DISC_CONTENT, layer="knowledge",
           non_applicable_conditions=["生产环境"], importance=0.2,
           valid_from=base_t)
    written.append(nid)
    cg.flush()
    return written


def run_rounds(rounds=ROUNDS, repeats=REPEATS):
    """在同一隔离库上跑 rounds 轮回灌；每轮先判定（重复 repeats 次）再回灌。"""
    root = _mkroot()
    cg = w5.build_lib(root, noise=0)
    rounds_data = []
    try:
        prev_intra = []
        for r in range(1, rounds + 1):
            n_nodes = len(cg.index["nodes"])
            # 轮内确定性：同一轮库状态重复 repeats 次
            reps = [judge_batch(cg) for _ in range(repeats)]
            intra = sorted(_flip(reps[0], reps[1])) if len(reps) > 1 else []
            for other in reps[2:]:
                intra = sorted(set(intra) | _flip(reps[0], other))
            rounds_data.append({
                "round": r, "n_nodes": n_nodes,
                "readings": reps[0], "intra_flip": intra})
            if r < rounds:
                reflow(cg, r)
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)
    return rounds_data


def _flip(a, b):
    """逐条比 verdict，返回翻转的条目名集合。"""
    return {k for k in a if a[k]["verdict"] != b[k]["verdict"]}


def collect():
    rounds_data = run_rounds()
    base = rounds_data[0]["readings"]
    res = {"rounds": rounds_data,
           "cross_round": {},        # 第 1 轮 vs 各后续轮
           "intra_round": {},        # 各轮内确定性与否
           "n_nodes_curve": [{"round": d["round"], "n_nodes": d["n_nodes"]}
                             for d in rounds_data]}
    for d in rounds_data:
        res["cross_round"]["1→%d" % d["round"]] = (
            sorted(_flip(base, d["readings"])) if d["round"] > 1 else [])
        res["intra_round"]["round%d" % d["round"]] = d["intra_flip"]
    # 跨档对照：既有三档 vs 回灌档（第 1 轮 = A 同构基线；末轮 = 回灌后）
    tiers = {}
    for tag, pr in w5.PRESSURES.items():
        tiers[tag] = w5.run(pr)
    last = rounds_data[-1]["readings"]
    res["cross_tier"] = {
        "A↔D轮1": sorted(_flip(tiers["A 无压力"], base)),
        "A↔D末轮": sorted(_flip(tiers["A 无压力"], last)),
        "B↔D轮1": sorted(_flip(tiers["B 加压力"], base)),
        "C↔D轮1": sorted(_flip(tiers["C 噪声"], base)),
    }
    res["tier_readings"] = tiers
    return res


def _row(name, r):
    return ("%-16s %-9s %8.4f %7d %7d %6d %6s %-22s %5s %6s %3s" % (
        name, r["verdict"], r["strength"], r["scanned"], r["comparable"],
        r["kept"], r["truncated"], str(r["stopped_by"]), str(r["depth"]),
        str(r["gain"]), str(r["resolved"])))


_HDR = ("%-16s %-9s %8s %7s %7s %6s %6s %-22s %5s %6s %3s" % (
    "条目", "verdict", "strength", "scanned", "comparable", "kept",
    "trunc", "stopped_by", "depth", "gain", "res"))


def _print_all(res):
    for d in res["rounds"]:
        print("\n===== 第 %d 轮（库节点 %d；轮内翻转：%s）====="
              % (d["round"], d["n_nodes"],
                 d["intra_flip"] or "无（0 条）"))
        print(_HDR)
        for it in w5.BATCH:
            print(_row(it["name"], d["readings"][it["name"]]))
    print("\n===== 跨轮判定翻转（第 1 轮 vs 各后续轮）=====")
    for k, v in res["cross_round"].items():
        print("  1→%s：%s" % (k.split("→")[1],
                              ("、".join(v) if v else "无（0 条）")))
    print("\n===== 跨档判定翻转（既有三档 ↔ 回灌档）=====")
    for k, v in res["cross_tier"].items():
        print("  %s：%s" % (k, ("、".join(v) if v else "无（0 条）")))
    print("\n===== 压力吸收位置：回灌档逐轮读数（库规模 / 选面 / 递归）=====")
    print("%-16s %8s %8s %8s %8s %-10s" %
          ("条目", "库节点", "scanned", "cmp", "fresh", "stop"))
    for it in w5.BATCH:
        cells = []
        for d in res["rounds"]:
            rr = d["readings"][it["name"]]
            tr = rr["trace"] or []
            fresh = sum(t.get("fresh", 0) for t in tr) if tr else "-"
            cells.append("%d/%d/%d/%s/%s" % (
                d["n_nodes"], rr["scanned"], rr["comparable"],
                fresh, rr["stopped_by"] or "-"))
        print("%-16s %s" % (it["name"], "  |  ".join(cells)))


def boundary_probe(rounds=3):
    """边界反例构造（界定「翻转率 0」的边界）：回灌节点**携带新冲突**时，判定是否漂移。

    在主档里回灌的是**同等内容**（逐字同构）——按 `check` 的 L1-c 口径，同条件同
    结论槽且逐字相同者被短路判「重复」（`CONCLUSION_SAME`），既不产生冲突也不改
    强度；故「同内容回灌不漂移判定」含**构造性前提**（回灌内容未引入新冲突）。
    本探针注入一条**内容不同、其不适用条件覆盖 ACCEPT 生效条件**的回灌节点，量
    「回灌一旦引入新冲突，判定是否漂移」——若漂移，则说明压力外溢的**必要条件**
    是「回灌内容本身带来新条件冲突」，而非「轮次/规模」。
    """
    root = _mkroot()
    cg = w5.build_lib(root, noise=0)
    out = []
    try:
        r0 = judge_batch(cg)["ACCEPT"]
        out.append({"round": 0, "n_nodes": len(cg.index["nodes"]),
                    "verdict": r0["verdict"], "strength": r0["strength"],
                    "scanned": r0["scanned"]})
        for r in range(1, rounds + 1):
            cg.add("breflow_%d" % r, BOUNDARY_CONFLICT, layer="knowledge",
                   non_applicable_conditions=["无人占用的条件"], importance=0.2)
            cg.flush()
            rr = judge_batch(cg)["ACCEPT"]
            out.append({"round": r, "n_nodes": len(cg.index["nodes"]),
                        "verdict": rr["verdict"], "strength": rr["strength"],
                        "scanned": rr["scanned"]})
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)
    return out


def self_proof():
    """自证（fail-closed）：① 回灌确已写库（节点数逐轮严格增）② 回灌内容确可读回
    ③ 回灌确已进入判定面（scanned 随轮增）④ 轮内确定性（同库状态重复跑同判）。"""
    print("!! 自证：回灌确已施加 + 回灌确已进入判定面 + 轮内确定性\n")
    bad = []
    root = _mkroot()
    cg = w5.build_lib(root, noise=0)
    try:
        n0 = len(cg.index["nodes"])
        written = reflow(cg, 1)
        n1 = len(cg.index["nodes"])
        # ① 回灌确已写库
        if n1 <= n0:
            bad.append("回灌未写库：节点数 %d → %d" % (n0, n1))
        print("  库节点数：回灌前 %d → 回灌后 %d（+%d）" % (n0, n1, n1 - n0))
        # ② 回灌内容确可读回（逐字同构源内容）
        r_ok = 0
        for idx, it in enumerate(w5.BATCH):
            node = cg.get("reflow_01_i%02d" % idx) or {}
            if (node.get("content") or "").strip() == it["content"].strip():
                r_ok += 1
        if r_ok != len(w5.BATCH):
            bad.append("回灌内容读回不符：%d/%d" % (r_ok, len(w5.BATCH)))
        print("  回灌副本读回逐字同构源内容：%d/%d" % (r_ok, len(w5.BATCH)))
        # ③ 回灌确已进入判定面：回灌后 scanned 增大
        before = judge_batch(cg)  # 已在回灌 1 轮后的库
        root2 = _mkroot()
        cg2 = w5.build_lib(root2, noise=0)
        try:
            clean = judge_batch(cg2)
        finally:
            cg2.close()
            shutil.rmtree(root2, ignore_errors=True)
        key = "DEFER_递归"
        if before[key]["scanned"] <= clean[key]["scanned"]:
            bad.append("回灌未进入判定面：scanned %d 未增于 %d"
                       % (before[key]["scanned"], clean[key]["scanned"]))
        print("  判定面 scanned（%s）：回灌前 %d → 回灌后 %d"
              % (key, clean[key]["scanned"], before[key]["scanned"]))
        # ④ 轮内确定性：同库状态重复跑同判
        reps = [judge_batch(cg) for _ in range(3)]
        intra = set()
        for o in reps[1:]:
            intra |= _flip(reps[0], o)
        if intra:
            bad.append("同库状态重复跑出现判定漂移：%s" % sorted(intra))
        print("  同库状态重复跑 3 次：档内翻转 %s"
              % (sorted(intra) or "无（0 条）"))
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)
    print("\n自证：%s" % ("PASS" if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    if "--self-proof" in sys.argv:
        return self_proof()
    if "--boundary" in sys.argv:
        rows = boundary_probe()
        print("边界反例构造：回灌**携带新冲突**内容后 ACCEPT 判定的演化")
        print("%-6s %8s %-9s %8s %8s" % ("轮", "库节点", "verdict", "strength", "scanned"))
        for x in rows:
            print("%-6s %8d %-9s %8.4f %8d" % (
                x["round"], x["n_nodes"], x["verdict"], x["strength"], x["scanned"]))
        flipped = {x["verdict"] for x in rows}
        print("\nACCEPT 判定集：%s → %s"
              % ("；".join(sorted(flipped)),
                 "发生漂移（回灌引入新冲突即可改判）" if len(flipped) > 1
                 else "未漂移"))
        return 0
    res = collect()
    if "--json" in sys.argv:
        # banner 不污染机读输出（--json = 纯 JSON 到 stdout）
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0
    print("W7/v1.1 组3b · 递归稳定性「多轮回灌加压对照」探针"
          "（隔离临时库，零生产语义改动）")
    print("=" * 90)
    _print_all(res)
    print("\n" + "=" * 90)
    intra_all = set()
    for k, v in res["intra_round"].items():
        intra_all |= set(v)
    cross_all = set()
    for k, v in res["cross_round"].items():
        cross_all |= set(v)
    print("轮内翻转率（同轮库状态重复 %d 次，各轮并集）：%s"
          % (REPEATS, sorted(intra_all) or "0 条"))
    print("跨轮翻转率（第 1 轮 vs 各后续轮，并集）：%d 条 %s"
          % (len(cross_all), sorted(cross_all) or ""))
    for k, v in res["cross_tier"].items():
        print("跨档翻转率（%s）：%d 条" % (k, len(v)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
