# -*- coding: utf-8 -*-
"""W4 情绪→决策通路守卫：`autonomy.proposals` 的**情绪排序加分** `emotion_bonus`。

背景（`docs/eval/W4_情绪决策通路_设计_v0.1.md` ＋ 其末尾「设计者定稿（5 点）」；
`docs/eval/设计者首批裁定_v0.1.md` 第 4 条：只做排序/建议、一处、默认关）：
  情绪读数（信息差二阶 `d2`）此前止于读数/卡字段/建议，无命名消费位。本改动在
  `proposals()` 的排序键 `sort_score` 上加一个由 `d2_mean=d2_sum/samples` 派生的
  `emotion_bonus`（默认 `0.0`），**只加排序分**、不改 `score`（资格定价器）、不改
  `gain_gate`（σ(Gain) 筛选）、不改 `explore()` 终态。

覆盖（正向）：
  P1 默认关反向腿：未设 / "0" / "false" ⇒ 与「恒 bonus=0.0 基线」**逐位一致**
  P2 开启腿：approaching ⇒ +ε；avoiding ⇒ −ε；stable ⇒ 0.0；|bonus| ≤ ε；
     判别力（异号 ⇒ 排序翻转）；确定性；观测面（reason/返回体）；台账可回读
  P3 资格面不变量：`score` 纯 ΔD、`score<=0` 资格集合开/关逐位同、`gain_gate`
     判据开/关逐位同、`sort_score=score+d_meta+emotion`

定点变异自证（`--self-proof`，fail-closed）：就地变异**运行中的实现源码**
（`inspect.getsource`，**不读 git**——把基线绑到某提交会在下次改动即失效），
逐条要求**恰好**命中期望红项；锚点漂移 ⇒ ANCHOR-MISS + 退出码 2。

运行：
  python -X utf8 -m md_cg.test_autonomy_emotion              # 正向
  python -X utf8 -m md_cg.test_autonomy_emotion --self-proof # 变异自证
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap

from . import autonomy, metacognition
from .fsutil import append_jsonl
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(label, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _sig(cg, t, query, d2, states):
    append_jsonl(cg.reflection_log,
                 {"t": t, "query": query, "d_prev": 1.0, "d_curr": 1.0,
                  "d_delta": 0.0, "d2": d2, "states": states,
                  "n_results": 3, "feedback": None})


def _root():
    return tempfile.mkdtemp(prefix="mdcg_emo_")


def _sortface(pl):
    """排序面：只取本次改动**不该改变**的既有排序键（反向腿对拍口径）。"""
    return [(p["query"], p["score"], p["d_meta_bonus"], p["sort_score"])
            for p in pl]


def _efaces(pl):
    """情绪读数面：跨两次运行须逐位同（确定性）。"""
    return [(p["query"], p["emotion_bonus"], p["emotion"]["bias"],
             p["emotion"]["d2_mean"]) for p in pl]


# ===================== 定点变异基础设施（就地变异运行中的实现源码） =====================
# 锚点定位在**去缩进后的实现源码**上；每条变异声明**期望转红的断言项前缀集**，
# 实跑红项必须与期望**恰好相等**（多红=断言语义纠缠，少红=该判据空转）。
_STRIP = ("emotion_bonus = (round(W_EMO * eps * sign, 4) if emotion_on else 0.0)",
          "emotion_bonus = 0.0")
_A_SWITCH = 'emotion_on = os.environ.get(EMOTION_ENV) == "1"'
_A_BONUS = ("emotion_bonus = (round(W_EMO * eps * sign, 4) "
            "if emotion_on else 0.0)")
_A_SCORE = 'a["score"] = round(score, 4)'
_ANCHORS = (_A_SWITCH, _A_BONUS, _A_SCORE)

#: (名, old, new, 期望红项前缀集合)
_MUTATIONS = (
    ("①开关忽略环境变量（恒开）", _A_SWITCH, "emotion_on = True",
     {"P1.1", "P1.2", "P1.3", "P1.4", "P1.5", "P2.5"}),
    ("②去掉 ε 上限（bonus 放大×10）", _A_BONUS,
     "emotion_bonus = (round(W_EMO * eps * sign * 10.0, 4) "
     "if emotion_on else 0.0)",
     {"P2.1", "P2.2", "P2.4"}),
    ("③把 emotion_bonus 误加到 score（资格泄漏）", _A_SCORE,
     'a["score"] = round(score + emotion_bonus, 4)',
     {"P3.1", "P3.3"}),
)


def _source():
    return textwrap.dedent(inspect.getsource(autonomy.proposals))


def _load_variant(*pairs):
    """按 (old,new) 替换对就地生成 proposals 变体（锚点须恰好命中 1 次）。"""
    src = _source()
    for old, new in pairs:
        n = src.count(old)
        if n != 1:
            raise RuntimeError("ANCHOR 命中 %d 次（期望 1）：%r" % (n, old[:60]))
        src = src.replace(old, new)
    ns = dict(vars(autonomy))
    exec(compile(src, "<w4emo-variant>", "exec"), ns)   # noqa: S102
    return ns["proposals"]


def _anchor_preflight():
    src = _source()
    bad = [(a, src.count(a)) for a in _ANCHORS if src.count(a) != 1]
    if not bad:
        return 0
    for a, n in bad:
        print("  ANCHOR-MISS 锚点漂移（命中 %d 次，期望恰好 1）：%r" % (n, a[:70]))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed；请同步 _MUTATIONS 锚点）")
    return 2


# ===================== 断言组（正向 / 变异体复用同一组） =====================


def _group(root, baseline_fn):
    """在隔离临时库上跑 P1–P3。`autonomy.proposals` 为实际被测（可被变异重绑），
    `baseline_fn` 为「恒 bonus=0.0 基线」（反向腿对拍源，不随变异改变）。"""
    cg = MdCGOS(root)
    _sig(cg, 1.0, "甲", -0.06, {})     # d2_mean=-0.06 < -0.05 → approaching
    _sig(cg, 2.0, "乙", 0.06, {})      # d2_mean=+0.06 > +0.05 → avoiding
    _sig(cg, 3.0, "丙", 0.04, {})      # |0.04| < 0.05 → stable
    _sig(cg, 4.0, "丁", 0.0, {})       # 零信号 → 不提案（资格面）
    eps = metacognition.D2_EMOTION
    env_name = autonomy.EMOTION_ENV
    saved = os.environ.get(env_name)

    def _set(v):
        if v is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = v

    try:
        # ---------- P1 反向腿：默认关 ⇒ 与「恒 bonus=0.0 基线」逐位一致 ----------
        _set(None)
        pr_off = autonomy.proposals(cg, limit=10)
        base = baseline_fn(cg, limit=10)
        off = pr_off["proposals"]
        ok("P1.1 默认关（env 未设）每条 emotion_bonus==0.0",
           all(p["emotion_bonus"] == 0.0 for p in off))
        ok("P1.2 默认关 sort_score == round(score + d_meta_bonus, 4)（逐位退化）",
           all(p["sort_score"] == round(p["score"] + p["d_meta_bonus"], 4)
               for p in off))
        ok("P1.3 默认关：排序面与『恒 bonus=0.0 基线』逐位一致",
           _sortface(off) == _sortface(base["proposals"]))
        ok("P1.5 默认关：返回体 emotion.enabled is False、cap==ε",
           pr_off["emotion"]["enabled"] is False
           and pr_off["emotion"]["cap"] == eps)

        _set("0")
        pr_off0 = autonomy.proposals(cg, limit=10)
        _set("false")
        pr_offf = autonomy.proposals(cg, limit=10)
        ok("P1.4 非 \"1\"（\"0\"/\"false\"）同样恒 0.0 且 sort_score 退化",
           all(p["emotion_bonus"] == 0.0
               and p["sort_score"] == round(p["score"] + p["d_meta_bonus"], 4)
               for p in pr_off0["proposals"] + pr_offf["proposals"])
           and pr_off0["emotion"]["enabled"] is False
           and pr_offf["emotion"]["enabled"] is False)

        # ---------- P2 开启腿 ----------
        _set("1")
        pr_on = autonomy.proposals(cg, limit=10)
        pr_on2 = autonomy.proposals(cg, limit=10)
        on = {p["query"]: p for p in pr_on["proposals"]}
        ok("P2.1 approaching（d2_mean<-阈值）→ +ε",
           on.get("甲", {}).get("emotion", {}).get("bias") == "approaching"
           and on.get("甲", {}).get("emotion_bonus") == round(1.0 * eps, 4)
           and on.get("甲", {}).get("emotion", {}).get("d2_mean") == -0.06)
        ok("P2.2 avoiding（d2_mean>+阈值）→ −ε",
           on.get("乙", {}).get("emotion", {}).get("bias") == "avoiding"
           and on.get("乙", {}).get("emotion_bonus") == round(-1.0 * eps, 4))
        ok("P2.3 stable（|d2_mean|<=阈值）→ 0.0",
           on.get("丙", {}).get("emotion", {}).get("bias") == "stable"
           and on.get("丙", {}).get("emotion_bonus") == 0.0)
        ok("P2.4 硬上限恒成立 |emotion_bonus| <= ε",
           all(abs(p["emotion_bonus"]) <= eps for p in pr_on["proposals"]))
        off_order = [p["query"] for p in off]
        on_order = [p["query"] for p in pr_on["proposals"]]
        ok("P2.5 判别力：异号 d2_mean ⇒ 排序翻转且 approaching 前置",
           off_order != on_order and on_order[0] == "甲")
        ok("P2.6 确定性：同窗口两次开启跑同值",
           _efaces(pr_on["proposals"]) == _efaces(pr_on2["proposals"]))
        ok("P2.7 观测面：reason 含情绪读数、返回体含 emotion 块",
           all("情绪" in p["reason"] and "d2_mean" in p["reason"]
               for p in pr_on["proposals"])
           and pr_on["emotion"]["enabled"] is True
           and pr_on["emotion"]["w_emo"] == autonomy.W_EMO
           and pr_on["emotion"]["cap"] == eps)
        need = {"query", "d2_sum", "d2_abs", "blindspot", "defer", "samples",
                "last_t", "score", "d_meta_bonus", "sort_score", "reason",
                "emotion", "emotion_bonus", "gain_gate"}
        ok("P2.8 只增不改：既有键全在，新增 emotion/emotion_bonus",
           all(need <= set(p) for p in pr_on["proposals"]))

        # ---------- P3 资格面不变量（开/关对照） ----------
        ok("P3.1 score 仍是纯 ΔD 定价（开/关两态逐位不变）",
           all(p["score"] == round(autonomy.W_D2 * p["d2_abs"]
                                   + autonomy.W_BLINDSPOT * p["blindspot"]
                                   + autonomy.W_DEFER * p["defer"], 4)
               for p in off + pr_on["proposals"]))
        ok("P3.2 资格集合不变（score>0 者一致；零信号查询两态均不提案）",
           {p["query"] for p in off} == {p["query"] for p in pr_on["proposals"]}
           == {"甲", "乙", "丙"}
           and pr_off["n_signals"] == pr_on["n_signals"] == 4
           and all(p["query"] != "丁" for p in pr_on["proposals"]))
        ok("P3.3 sort_score == score + d_meta_bonus + emotion_bonus",
           all(p["sort_score"] == round(p["score"] + p["d_meta_bonus"]
                                        + p["emotion_bonus"], 4)
               for p in pr_on["proposals"]))
        ok("P3.4 gain_gate 判据开/关两态逐位相同（未泄漏进 σ(Gain)）",
           {p["query"]: p.get("gain_gate") for p in off}
           == {p["query"]: p.get("gain_gate") for p in pr_on["proposals"]})

        # ---------- 台账可回读（explore 已把 proposals 原样并入 _explore.jsonl） ----------
        autonomy.explore(cg, actor="test")
        led = []
        with open(autonomy._explore_log_path(cg), encoding="utf-8") as fh:
            recs = [json.loads(x) for x in fh if x.strip()]
        led = recs[-1]["proposals"] if recs else []
        ok("P2.9 台账 _explore.jsonl 回读含 emotion_bonus 与 bias",
           bool(led) and all("emotion_bonus" in p and "emotion" in p
                             for p in led)
           and any(p["emotion"]["bias"] == "approaching" for p in led))
    finally:
        _set(saved)


def _run_group(root, baseline_fn):
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _group(root, baseline_fn)
    return {n.split(" ", 1)[0] for n in FAILS}


# ===================== 定点变异自证（--self-proof） =====================


def _self_proof():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：就地变异运行中的实现源码（不读 git），"
          "逐条要求恰好命中期望红项\n")
    base_fn = _load_variant(_STRIP)      # 恒 bonus=0.0 基线（反向腿对拍源）
    orig = autonomy.proposals
    root = _root()
    bad = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            base_red = _run_group(root, base_fn)
        print("  未变异基线：红项 %d %s"
              % (len(base_red), "（应为 0）" if base_red else ""))
        if base_red:
            bad.append("未变异基线即转红：%s" % sorted(base_red))
        marks = "①②③"
        for i, (name, old, new, expect) in enumerate(_MUTATIONS):
            mroot = _root()              # 每变异体独立库（隔离 explore 台账串味）
            try:
                autonomy.proposals = _load_variant((old, new))
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        red = _run_group(mroot, base_fn)
                except Exception as exc:                       # noqa: BLE001
                    red = {"<变异体运行异常:%s>" % type(exc).__name__}
            finally:
                autonomy.proposals = orig
                shutil.rmtree(mroot, ignore_errors=True)
            hit = red == expect
            if not hit:
                bad.append("变异%s %s：红项 %s ≠ 期望 %s"
                           % (marks[i], name, sorted(red), sorted(expect)))
            print("  变异%s %-40s 红项 %d（期望 %d）%s"
                  % (marks[i], name, len(red), len(expect),
                     "PASS" if hit else "**FAIL** 实=%s 期=%s"
                     % (sorted(red), sorted(expect))))
    finally:
        autonomy.proposals = orig
        shutil.rmtree(root, ignore_errors=True)
    print("\n变异自证：%s"
          % ("PASS（三处接线逐条恰好命中期望红项）" if not bad
             else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    print("W4 情绪→决策通路 · proposals 情绪排序加分守卫"
          "（默认关逐位一致 + 资格不变量 + 变异自证）")
    print("=" * 70)
    root = _root()
    base_fn = _load_variant(_STRIP)
    try:
        red = _run_group(root, base_fn)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print()
    if red:
        print("FAILED: %d 项 → %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("ALL OK: %d 项（情绪排序加分守卫全绿）" % PASS)
    return 0


if __name__ == "__main__":
    if "--self-proof" in sys.argv:
        sys.exit(_self_proof())
    sys.exit(main())
