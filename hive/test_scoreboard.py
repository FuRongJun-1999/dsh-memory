#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""hive/test_scoreboard.py —— hive/scoreboard.py 的守卫（断言 ＋ 定点变异自证）

# 功能名：对内域评分器守卫——逐条断言 ＋ 每条判据一个定点变异（短路该判据 ⇒ 对应断言恰好转红）
# 生效条件：凡改动 hive/scoreboard.py 后；凡要把本评分用于实际归集前。
# 子功能：① 合成夹具（不依赖真实 jobs/，保证确定性）② 12 条断言 ③ 8 条定点变异自证
# 执行：python -X utf8 hive/test_scoreboard.py           # 断言
#       python -X utf8 hive/test_scoreboard.py --mutate  # 变异自证（逐条恰好命中期望红项）
# 验证方式：基线全绿 ＋ 变异模式下每条恰好命中声明红项（多红=语义纠缠，少红=判据空转）
# 不适用条件：不适用于真实 jobs/ 的业务正确性（本守卫只测评分器逻辑，夹具自造）
"""

import io
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "scoreboard.py")

_red = []
_quiet = False


def ok(name, cond, detail=""):
    if cond:
        if not _quiet:
            print("  [PASS] " + name)
    else:
        if not _quiet:
            print("  [FAIL] " + name + ("  · " + str(detail)[:160] if detail else ""))
        _red.append(name.split()[0])


def _w(path, obj, raw=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(raw if raw is not None else json.dumps(obj, ensure_ascii=False))


def build_fixture():
    """合成 jobs/ 夹具：覆盖 done/error/坏件/历史格式/不合契约/_ 前缀/大小写变体/task 父段。"""
    root = tempfile.mkdtemp(prefix="sb_fixture_")
    J = os.path.join(root, "jobs")
    def job(jid, state, spec=None, result=None, bad=False):
        d = os.path.join(J, jid)
        os.makedirs(d, exist_ok=True)
        _w(os.path.join(d, "spec.json"), spec or {})
        if bad:
            _w(os.path.join(d, "status.json"), None, raw="{ this is not json")
        else:
            _w(os.path.join(d, "status.json"), {"job_id": jid, "state": state})
        _w(os.path.join(d, "result.json"), result or {})
    # 同键两投（round=1）
    job("h_A端_T1_输出单元_0001", "done", {"commands": [["python", "-c", "print(1)"]]},
        {"ok": True, "content": "x"})
    job("h_A端_T1_输出单元_0002", "done", {}, {"ok": True, "content": "y"})
    # error
    job("h_A端_T1_验证单元_0001", "error", {}, {})
    # task 含父段
    job("h_A端_X_T1_记录单元_0001", "done", {}, {"ok": True, "content": "z"})
    # identity 大小写变体

    # ⚠ Windows 文件系统大小写不敏感：两个目录名若**仅 identity 大小写不同**会被当成同一个目录

    #   （后者覆盖前者）。故此处让 task 也不同 —— 真实库里的变体也来自 task/unit 不同的真实 job。

    job("h_a端_T2_验证单元_0001", "done", {}, {"ok": True, "content": "w"})
    # 坏件（status.json 不可解析 ⇒ bad；仍计入，state 空）
    job("h_A端_T9_输出单元_0001", "", {}, {}, bad=True)
    # 历史格式（id 契约 v2 之前）
    os.makedirs(os.path.join(J, "h1790492122424_3918"), exist_ok=True)
    # 真·不合契约
    os.makedirs(os.path.join(J, "weird_dir"), exist_ok=True)
    # _ 前缀（忽略）
    os.makedirs(os.path.join(J, "_quarantine"), exist_ok=True)
    return root, J


def run_checks(sb):
    """对给定 scoreboard 模块跑全部断言；返回 (doc, root)。"""
    root, J = build_fixture()
    doc = sb.build(J)
    by_unit = {(r["identity"], r["task"], r["unit"]): r for r in doc["by_unit"]}
    by_task = {a["task"]: a for a in doc["by_task"]}

    ok("S1 解析四槽（含 task 父段）",
       sb.parse_job_id("h_A端_T1_输出单元_0001") == ("A端", "T1", "输出单元", 1)
       and sb.parse_job_id("h_A端_X_T1_记录单元_0001") == ("A端", "X_T1", "记录单元", 1),
       (sb.parse_job_id("h_A端_T1_输出单元_0001"), sb.parse_job_id("h_A端_X_T1_记录单元_0001")))

    ok("S2 契约校验：单元不在闭集／无 h_ 前缀／编号非数字 → None",
       sb.parse_job_id("h_A端_T1_未知单元_0001") is None
       and sb.parse_job_id("A端_T1_输出单元_0001") is None
       and sb.parse_job_id("h_A端_T1_输出单元_abc") is None, "")

    ok("S3 扫描分类：legacy／skipped／bad 三分离，_ 前缀忽略",
       doc["legacy_ids"] == ["h1790492122424_3918"]
       and doc["skipped_ids"] == ["weird_dir"]
       and doc["bad_ids"] == ["h_A端_T9_输出单元_0001"]
       # #158 订正：jobs 由 6 → 5。理由＝**断言目标不变**（「jobs 计的是进入评分的件数」），
       # 变的是它算错的那部分：修前坏件既进 bad_ids 又计分，jobs 把坏件也算进去。
       and doc["totals"]["jobs"] == 5, doc["totals"])

    ok("S4 round＝同键重投次数（2 投 ⇒ round=1 ⇒ Δ=3，base=3）",
       by_unit[("A端", "T1", "输出单元")]["round"] == 1
       and by_unit[("A端", "T1", "输出单元")]["delta"] == 3,
       by_unit.get(("A端", "T1", "输出单元")))

    ok("S5 结算式：settle(6,1,0)=12／(6,1,1)=6／(6,1,2)=4／保底 settle(1,1,5)=1",
       [sb.settle(6, 1.0, 0)[0], sb.settle(6, 1.0, 1)[0], sb.settle(6, 1.0, 2)[0],
        sb.settle(1, 1.0, 5)[0]] == [12, 6, 4, 1], "")

    ok("S6 舍入 half-up：2.5→3／4.5→5（与内置 round 分歧：2／4）",
       sb.half_up(2.5) == 3 and sb.half_up(4.5) == 5
       and round(2.5) == 2 and round(4.5) == 4, "")

    ok("S7 base 按单元定档（验证单元 6／输出单元 3）",
       sb.UNIT_BASE["验证单元"] == 6 and sb.UNIT_BASE["输出单元"] == 3
       and by_unit[("A端", "T1", "验证单元")]["base"] == 6, "")

    # #158 订正：Δ 由 15 → 4。理由＝**断言目标不变**（「T1 聚合 = 其各单元 Δ 之和」），
    # 变的是它算错的那部分：修前结算的 E 是常量 1.0 ⇒ T1 的 error 那件也拿 Δ=12；
    # 修后 E 实测（该件 done=0 ⇒ E=0 ⇒ Δ=1），重投那件仍为 3 ⇒ 3+1=4。
    ok("S8 by_task 聚合：T1 jobs=3 done=2 error=1 Δ=4（E 实测后）完成率=2/3",
       by_task["T1"]["jobs"] == 3 and by_task["T1"]["done"] == 2
       and by_task["T1"]["error"] == 1 and by_task["T1"]["delta_sum"] == 4
       and abs(by_task["T1"]["completion_rate"] - 2.0 / 3) < 1e-9, by_task.get("T1"))

    ok("S9 identity 大小写变体被报出（不合并）",
       doc["identity_variants"] == {"a端": ["A端", "a端"]}, doc["identity_variants"])

    ok("S10 task 近名被报出（T1 ⊂ X_T1，不合并）",
       doc["task_prefix_pairs"] == [("T1", "X_T1")], doc["task_prefix_pairs"])

    ok("S11 确定性：同输入两次 build 逐字段相同",
       json.dumps(sb.build(J), sort_keys=True, ensure_ascii=False)
       == json.dumps(sb.build(J), sort_keys=True, ensure_ascii=False), "")

    # #158 订正：本条的**目标不变**＝「不编造完成率」＋「Δ 合计如实」；变的是它算错的
    # 那部分：修前坏件 T9 既进 bad_ids 又拿 Δ=6 并产生一条完成率 None 的任务行，
    # 合计 39 内含这 6 分。修后坏件不产生评分行 ⇒ 改钉「T9 不在 by_task」＋
    # 「无编造完成率（凡有值必在 [0,1]）」＋「合计 22＝3+1+6+12」。
    ok("S12 不编造：坏件不产生评分行（T9 不在 by_task）＋完成率无编造＋Δ 合计=22",
       ("T9" not in by_task)
       and all(a["completion_rate"] is None or 0.0 <= a["completion_rate"] <= 1.0
               for a in doc["by_task"])
       and doc["totals"]["delta_sum"] == 22,
       (sorted(by_task), doc["totals"]["delta_sum"]))

    shutil.rmtree(root, ignore_errors=True)
    return doc


# ---- 定点变异（源码级短路 ⇒ 对应断言必须恰好转红）-----------------------------

_MUTATIONS = (
    ("M1 舍入改内置 round（银行家）",
     "    return int(math.floor(x + 0.5))",
     "    return int(round(x))  # MUT", {"S6"}),
    ("M2 归集层 round 恒 0（不看重投次数）",
     "        rounds = max(0, n - 1)",
     "        rounds = 0  # MUT", {"S4", "S8", "S12"}),
    ("M9 结算层忽略 rounds（settle 内 r 恒 0）",
     "    r = max(0, int(rounds))",
     "    r = 0  # MUT", {"S4", "S5", "S8", "S12"}),
    ("M3 关单元闭集校验（任意单元名放行）",
     "    if unit not in UNITS:",
     "    if False:  # MUT", {"S2"}),
    ("M4 关 identity 变体检测",
     '    identity_variants = {k: sorted(v) for k, v in sorted(_iv.items()) if len(v) > 1}',
     "    identity_variants = {}  # MUT", {"S9"}),
    ("M5 关 task 近名检测",
     "    task_prefix_pairs = sorted({(a, b) for a in _ts for b in _ts if a != b and a in b})",
     "    task_prefix_pairs = []  # MUT", {"S10"}),
    ("M6 关历史格式分流（legacy 并入 skipped）",
     "            (legacy if LEGACY_RE.match(name) else skipped).append(name)",
     "            skipped.append(name)  # MUT", {"S3"}),
    # #158 订正：M7 期望集由 {S12,S7,S8} → {S12,S7}。理由＝**变异目标不变**（「关单元
    # 定档 ⇒ 相关断言转红」），变的是它算错的那部分：E 改实测后，**全失败单元的 Δ 被
    # 保底到 1、与 base 无关**，故 T1 的聚合（3+1=4）不再随 base 变 ⇒ S8 不再敏感。
    ("M7 base 恒兜底（不看单元表）",
     '    base = UNIT_BASE.get(unit, BASE_DEFAULT)',
     "    base = BASE_DEFAULT  # MUT", {"S7", "S12"}),
    # #158 订正：M8 期望集由 {S8,S12} → {S8}。理由＝**变异目标不变**（「编造完成率必须
    # 被抓」），变的是它算错的那部分：S12 改写后钉的是**结构面**（坏件不产生评分行 +
    # 值域 [0,1]），而 1.0 落在值域内 ⇒ S12 不再敏感；编造仍被 S8 的**具体值**
    # `completion_rate == 2/3` 抓住（该任务 3 件里 1 件失败，编造成 1.0 即暴露）⇒
    # 判别力未丢，只是归属从 S12 收到 S8。
    ("M8 完成率恒 1.0（编造）",
     '        a["completion_rate"] = (a["done"] / term) if term else None',
     '        a["completion_rate"] = 1.0  # MUT', {"S8"}),
)


def _load(src_text, name="sb_mut"):
    mod = types.ModuleType(name)
    mod.__file__ = SRC
    exec(compile(src_text, "<sb-mut>", "exec"), mod.__dict__)
    return mod


def _mutate_mode():
    print("!! 定点变异自证：逐条短路一条判据，对应断言必须**恰好**转红\n")
    base = io.open(SRC, encoding="utf-8").read()
    bad = []
    for name, old, new, expect in _MUTATIONS:
        if base.count(old) != 1:
            print("  ANCHOR-MISS %s：锚点命中 %d 次（期望 1）" % (name, base.count(old)))
            bad.append(name)
            continue
        global _red, _quiet
        _red, _quiet = [], True
        mod = _load(base.replace(old, new))
        try:
            run_checks(mod)
        except Exception as e:
            print("  [FAIL] %s 运行异常：%s" % (name, str(e)[:120]))
            bad.append(name)
            continue
        _quiet = False
        got = set(_red)
        flag = "PASS" if got == expect else "FAIL"
        print("  [%s] %s：红项 %d（期望 %d）%s" % (flag, name, len(got), len(expect),
              "" if got == expect else " 实=%s 期=%s" % (sorted(got), sorted(expect))))
        if got != expect:
            bad.append(name)
    print()
    if bad:
        print("定点变异：FAIL —— %s" % "；".join(bad))
        return 1
    print("定点变异：PASS（逐条恰好命中期望红项）")
    return 0


def main(argv):
    global _red          # 必须声明：否则 _red=[] 成为局部变量，汇总恒报「失败 0」
    if "--mutate" in argv:
        return _mutate_mode()
    print("== hive/scoreboard.py 守卫（断言）==")
    _red = []
    run_checks(_load(io.open(SRC, encoding="utf-8").read(), "sb_base"))
    print("=" * 70)
    if _red:
        print("通过 %d / 失败 %d" % (12 - len(_red), len(_red)))
        print("失败项：" + " / ".join(_red))
        return 1
    print("通过 12 / 失败 0")
    print("ALL OK（反面证明见 --mutate）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
