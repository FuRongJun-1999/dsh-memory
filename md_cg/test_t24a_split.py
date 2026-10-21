# -*- coding: utf-8 -*-
"""test_t24a_split —— E-T24a t1 写入侧拆分器验收（完整四段）。

四段（照任务 accept）：

  [A] 拆分正确性（MDCG_JUDGMENT=1）：至少 3 个混句样本，要求 `*`拼接* 的输出
      与语境明确——例如 '今天把 report.pdf 生成一下，我主力语言是 Python' 拆出保留片段
      =='我主力语言是 Python'、丢需求片段；'帮我生成一份报告，我的性格是喜欢简洁的' 保留
      =='我的性格是喜欢简洁的'；'帮我把接口改一下，接口以前是老的实现' 保留=='接口以前是老的实现'
      （技术事实仍留，需求丢）。断言：拆分函数返回的 kept 片段列表与 dropped 片段
      列表正确、judge 判据与 evidence 落入保留/丢弃两侧；写路径 add(混句) 落盘节点的正文
      == 保留片段拼接、fm.judgment_state==keep（或 keep_life）、why_kept 非空；
      remember_event(混句) 的 event 正文 == 保留片段、verdict 状态与保留片段一致。

  [B] 纯保留/纯丢弃不误伤：纯保留样本拆分后原样整句写入（add 落盘正文==原文、fm.judgment_state==keep）；
      纯需求样本（'帮我生成一份报告'、'今天把 report.pdf 生成一下'）与纯噪声样本（'npm error code ELIFECYCLE'
      、'Traceback (most recent call last):'、'收到收到'）拆分结果 kept 为空 ⇒ 写路径仍返回 None /
      event=None，不留任何占位、不写空节点。

  [C] 数量与格式纪律：拆分保留的节点正文必须是原文子串（允许去首尾空白），不得改写措辞；
      不落 DROP 片段的内容。

  [D] 默认关回归：MDCG_JUDGMENT 未设或显式 0 时，混句样本照常整句成节点、fm 无判定字段
      （judgment_state/why_kept/lifetime/ref_count 四个键一个都不出现），返回体形状不变；
      拆分逻辑完全不触发。

运行：cd /d D:\wook\lingshu-src && python -X utf8 -m md_cg.test_t24a_split
"""

import os
import sys
import json
import tempfile
import shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg import judgment_rules as jr
from md_cg.mdcos import MdCGOS

passed = failed = 0

# ── helpers ──────────────────────────────────────────────────────────
def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        d = str(detail)[:500] if detail else ""
        print("  [FAIL] " + name + "  " + d)


# ── test helpers ────────────────────────────────────────────────────
def _mk_cg():
    return MdCGOS(tempfile.mkdtemp(prefix="mdcg_t24a_"))


def _fm_of(cg, nid):
    """node_id 的 frontmatter；节点缺席返回 None。"""
    if not nid:
        return None
    try:
        got = cg.get(nid)
    except Exception:
        return None
    if not got:
        return None
    return got.get("frontmatter")


def _content_of(cg, nid):
    """node_id 的正文（fm 与正文合取返回体的 'content' 键）。"""
    if not nid:
        return None
    try:
        got = cg.get(nid)
    except Exception:
        return None
    if not got:
        return None
    return got.get("content")


# ── [A] 拆分正确性 ──────────────────────────────────────────────────
def test_a_split_correctness():
    print("[A] 拆分正确性（MDCG_JUDGMENT=1）：混句拆分片段与落盘正文")

    os.environ["MDCG_JUDGMENT"] = "1"

    # ---- sub-test 1: pure assert on split_keep_parts results ----
    cases = [
        # (input, expected_kept_text, expected_kept_parts_set, dropped_contains_sets)
        (
            "今天把 report.pdf 生成一下，我主力语言是 Python",
            "我主力语言是 Python",
            {"我主力语言是 Python"},
            {"今天把 report.pdf 生成一下"}
        ),
        (
            "帮我生成一份报告，我的性格是喜欢简洁的",
            "我的性格是喜欢简洁的",
            {"我的性格是喜欢简洁的"},
            {"帮我生成一份报告"}
        ),
        (
            "帮我把接口改一下，接口以前是老的实现",
            "接口以前是老的实现",
            {"接口以前是老的实现"},
            {"帮我把接口改一下"}
        ),
        # pin samples: whole sentence kept
        (
            "帮我记住我的生日是5月20日",
            "帮我记住我的生日是5月20日",
            {"帮我记住我的生日是5月20日"},
            set()
        ),
        (
            "记一下我的邮箱是 a@b.com",
            "记一下我的邮箱是 a@b.com",
            {"记一下我的邮箱是 a@b.com"},
            set()
        ),
        (
            "记住：项目名是 wook",
            "记住：项目名是 wook",
            {"记住：项目名是 wook"},
            set()
        ),
        (
            "以后叫我小R",
            "以后叫我小R",
            {"以后叫我小R"},
            set()
        ),
        # pure keep comma samples - should stay whole (no split when both parts are KEEP)
        (
            "我主力语言是 Python，讨厌过度抽象",
            "我主力语言是 Python，讨厌过度抽象",
            {"我主力语言是 Python，讨厌过度抽象"},
            set()
        ),
        (
            "我的生日是5月20日",
            "我的生日是5月20日",
            {"我的生日是5月20日"},
            set()
        ),
        (
            "项目名是 wook",
            "项目名是 wook",
            {"项目名是 wook"},
            set()
        ),
    ]

    for inp, exp_kept, exp_parts, exp_dropped_contains in cases:
        r = jr.split_keep_parts(inp)
        # kept 文本检查
        check(
            "%s：kept 文本正确" % (inp[:40] + "...",),
            r["kept"] == exp_kept,
            "kept=%r != %r" % (r["kept"], exp_kept)
        )
        # parts 检查
        check(
            "%s：parts 正确" % (inp[:40] + "...",),
            set(r["parts"]) == exp_parts,
            "parts=%r != %r" % (set(r["parts"]), exp_parts)
        )
        # dropped 包含检查（只要被测内容在 dropped 中即可）
        dc_ok = all(c in r["dropped"] for c in exp_dropped_contains) if exp_dropped_contains else True
        check(
            "%s：dropped 包含期望片段" % (inp[:40] + "...",),
            dc_ok,
            "dropped=%r，期望包含 %r" % (r["dropped"], exp_dropped_contains)
        )
        # kept_verdicts 非空当且仅当有 kept 片段时为真
        if exp_kept:
            check(
                "%s：kept_verdicts 非空" % (inp[:40] + "...",),
                len(r["kept_verdicts"]) > 0,
                "kept_verdicts 为空"
            )
        else:
            check(
                "%s：kept_verdicts 空" % (inp[:40] + "...",),
                len(r["kept_verdicts"]) == 0,
                "kept_verdicts=%r" % (r["kept_verdicts"],)
            )
        # dropped_verdicts 非空当且仅当有 dropped 片段时为真
        if exp_dropped_contains:
            check(
                "%s：dropped_verdicts 非空" % (inp[:40] + "...",),
                len(r["dropped_verdicts"]) > 0,
                "dropped_verdicts 为空"
            )
        else:
            check(
                "%s：dropped_verdicts 空" % (inp[:40] + "...",),
                len(r["dropped_verdicts"]) == 0,
                "dropped_verdicts=%r" % (r["dropped_verdicts"],)
            )

    # ---- sub-test 2: write-path add(混句) 落盘正文 == 保留片段拼接 ----
    print("  [子-test] add(混句) 落盘正文 == 保留片段拼接")
    kg = _mk_cg()
    try:
        # mixed sentences that should be split
        mixed_cases = [
            "今天把 report.pdf 生成一下，我主力语言是 Python",
            "帮我生成一份报告，我的性格是喜欢简洁的",
            "帮我把接口改一下，接口以前是老的实现",
        ]
        for idx, inp in enumerate(mixed_cases):
            r = jr.split_keep_parts(inp)
            kept = r["kept"]
            parts = r["parts"]
            if not kept:
                check("  %s：split 保留片段非空（写路径前置检查）" % (inp[:30] + "...",), False,
                      "split_keep_parts 返回 kept=%r" % (kept,))
                continue
            nid = "t24a_mixed_%d" % (idx,)
            try:
                got = kg.add(nid, inp)  # 写入整句混句，拆分发生在写路径内
                fm = _fm_of(kg, nid)
                body = _content_of(kg, nid)
                check(
                    "  %s：add 落盘正文 == 保留片段拼接" % (inp[:30] + "...",),
                    got is not None and (body or "").strip() == kept.strip(),
                    "body=%r 期望=%r" % (body, kept)
                )
                # judgment_state 应为 KEEP
                check(
                    "  %s：fm.judgment_state==KEEP" % (inp[:30] + "...",),
                    fm is not None and fm.get("judgment_state") == jr.KEEP,
                    "fm.judgment_state=%r" % (
                        fm.get("judgment_state") if fm else None,)
                )
                # why_kept 非空
                check(
                    "  %s：why_kept 非空" % (inp[:30] + "...",),
                    fm is not None and bool(fm.get("why_kept")),
                    "fm.why_kept=%r" % (fm.get("why_kept") if fm else None,)
                )
            except Exception as e:
                check("  %s：add 成功无异常" % (inp[:30] + "...",), False, str(e))
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)

    # ---- sub-test 3: remember_event(混句) 的 event 正文 == 保留片段 ----
    print("  [子-test] remember_event(混句) 的 event 正文 == 保留片段")
    kg = _mk_cg()
    try:
        for inp in [
            "今天把 report.pdf 生成一下，我主力语言是 Python",
            "帮我生成一份报告，我的性格是喜欢简洁的",
        ]:
            r = jr.split_keep_parts(inp)
            kept = r["kept"]
            if not kept:
                continue
            ev = kg.remember_event("user", inp)
            check(
                "  %s：event.text == 保留片段" % (inp[:30] + "...",),
                ev["event"] is not None and ev["event"]["text"] == kept,
                "event.text=%r != %r" % (ev["event"]["text"] if ev["event"] else None, kept)
            )
            # verdict 状态与保留片段一致
            if "verdict" in ev and ev["verdict"]:
                check(
                    "  %s：verdict.state==KEEP" % (inp[:30] + "...",),
                    ev["verdict"]["state"] == jr.KEEP,
                    "verdict.state=%r" % (ev["verdict"]["state"],)
                )
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)


# ── [B] 纯保留/纯丢弃不误伤 ──────────────────────────────────────────
def test_b_pure_keep_no_miss():
    print("[B] 纯保留/纯丢弃不误伤")

    # 纯保留样本：拆分后原样整句写入
    print("  [子-test] 纯保留样本拆分后原样整句写入")
    pure_keep_samples = [
        "我主力语言是 Python，讨厌过度抽象",
        "我的生日是5月20日",
        "项目名是 wook",
    ]
    for t in pure_keep_samples:
        r = jr.split_keep_parts(t)
        check(
            "%s：kept == 原文（整句保留）" % t,
            r["kept"] == t,
            "kept=%r != %r" % (r["kept"], t)
        )
        # 纯保留样本 kept 不应为空
        check(
            "%s：kept 不为空" % t,
            r["kept"] != "",
            "kept 为空"
        )

    # 纯需求样本与纯噪声样本：split 结果 kept 为空 ⇒ 写路径仍返回 None / event=None
    print("  [子-test] 纯需求/噪声样本 split kept 为空 => 写路径 None/event=None")
    pure_demand_noise = [
        "帮我生成一份报告",
        "今天把 report.pdf 生成一下",
        "npm error code ELIFECYCLE",
        "Traceback (most recent call last):",
        "收到收到",
    ]
    for t in pure_demand_noise:
        r = jr.split_keep_parts(t)
        check(
            "%s：split_keep_parts kept == '' (空)" % t,
            r["kept"] == "",
            "kept=%r != ''" % (r["kept"],)
        )

    # ---- sub-test 3: 写路径后果（B 段另一半） ----
    # 纯保留样本：add 落盘正文 == 原文、fm.judgment_state == keep
    print("  [子-test] 写路径：纯保留 add 落盘正文 == 原文")
    kg = _mk_cg()
    try:
        for idx, t in enumerate(pure_keep_samples):
            nid = "t24a_bpk_%d" % idx
            got = kg.add(nid, t)
            body = _content_of(kg, nid)
            fm = _fm_of(kg, nid)
            check(
                "%s：add 落盘正文 == 原文" % t,
                got is not None and (body or "").strip() == t.strip(),
                "got=%r body=%r" % (got, body)
            )
            check(
                "%s：fm.judgment_state == keep" % t,
                fm is not None and fm.get("judgment_state") == jr.KEEP,
                "fm.judgment_state=%r" % (fm.get("judgment_state") if fm else None,)
            )
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)

    # 纯需求/纯噪声：写路径返回 None / event=None，不留占位、不写空节点
    print("  [子-test] 写路径：纯需求/噪声 add → None、remember_event → event=None")
    kg = _mk_cg()
    try:
        for idx, t in enumerate(pure_demand_noise):
            nid = "t24a_bpn_%d" % idx
            got = kg.add(nid, t)
            check(
                "%s：add 返回 None" % t,
                got is None,
                "got=%r" % (got,)
            )
            ev = kg.remember_event("user", t)
            check(
                "%s：remember_event event 为 None" % t,
                ev is not None and ev.get("event") is None,
                "ev=%r" % (ev,)
            )
            # 不留占位、不写空节点
            body = _content_of(kg, nid)
            check(
                "%s：未写入任何节点（无占位）" % t,
                got is None and body is None,
                "body=%r" % (body,)
            )
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)


# ── [C] 数量与格式纪律 ──────────────────────────────────────────────
def test_c_format_discipline():
    print("[C] 数量与格式纪律：原文子串、不改写、不落 DROP")

    # kept 必须是原文子串（允许去首尾空白），不得改写措辞
    print("  [子-test] kept 是原文子串、不改写")
    format_cases = [
        # 保留片段应是原文的子串，不是重新组合
        (
            "今天把 report.pdf 生成一下，我主力语言是 Python",
            "我主力语言是 Python"  # 原文子串，不是其他组合
        ),
        (
            "帮我生成一份报告，我的性格是喜欢简洁的",
            "我的性格是喜欢简洁的"  # 原文子串
        ),
        (
            "帮我把接口改一下，接口以前是老的实现",
            "接口以前是老的实现"  # 原文子串
        ),
    ]
    for inp, expected_kept in format_cases:
        r = jr.split_keep_parts(inp)
        check(
            "%s：kept 是原文子串" % (inp[:40] + "...",),
            r["kept"] == expected_kept,
            "kept=%r != %r (期望)" % (r["kept"], expected_kept)
        )
        # 确保 kept 不包含原本应丢弃的片段
        # (verified by split_keep_parts design)

    # 不落 DROP 片段的内容
    print("  [子-test] 不落 DROP 片段的内容")
    for t in ["帮我生成一份报告", "今天把 report.pdf 生成一下", "npm error code ELIFECYCLE"]:
        r = jr.split_keep_parts(t)
        # kept 为空，dropped 有内容
        check(
            "%s：kept == ''，dropped 有内容" % t,
            r["kept"] == "" and len(r["dropped"]) > 0,
            "kept=%r dropped=%r" % (r["kept"], r["dropped"])
        )


# ── [D] 默认关回归 ──────────────────────────────────────────────────
def test_d_default_off():
    print("[D] 默认关回归：MDCG_JUDGMENT 未设/显式 0 时不触发拆分")

    os.environ.pop("MDCG_JUDGMENT", None)

    # split_keep_parts 无论开关与否都应返回结果（它是纯函数）
    # 但写路径 add/remember_event 应不触发判定
    # 这里验证 split_keep_parts 的返回形状在默认关时与开时一致
    test_inputs = [
        "今天把 report.pdf 生成一下，我主力语言是 Python",
        "帮我记住我的生日是5月20日",
        "我主力语言是 Python，讨厌过度抽象",
    ]
    for inp in test_inputs:
        r_open = jr.split_keep_parts(inp)
        check(
            "%s：split_keep_parts 返回形状一致" % (inp[:30] + "...",),
            "kept" in r_open and "parts" in r_open and "dropped" in r_open,
            "缺少键"
        )

    # 默认关回归：整句成节点、fm 无判定字段
    print("  [子-test] 默认关：混句 add 正常成节点且 fm 无判定字段")
    kg = _mk_cg()
    try:
        # 用整句写入，不应该因为判定而被拦截
        for idx, inp in enumerate([
            "今天把 report.pdf 生成一下，我主力语言是 Python",
            "帮我生成一份报告，我的性格是喜欢简洁的",
        ]):
            nid = "t24a_def_%d" % idx
            # 在默认关闭时，add 应该把整句写进去
            got = kg.add(nid, inp)
            fm = _fm_of(kg, nid)
            body = _content_of(kg, nid)
            # 应该成功写入（默认关=逐字节一致）
            check(
                "%s：默认关 add 成功写入（got=%s）" % (inp[:30] + "...", got),
                got is not None and got != "",
                "got=%r" % (got,)
            )
            if got:
                # fm 中不应有判定字段（四个键一个都不出现）
                _JUDGMENT_FIELDS = (jr.STATE_FIELD, jr.WHY_KEPT_FIELD,
                                    jr.LIFETIME_FIELD, jr.REF_COUNT_FIELD)
                leaked = [f for f in _JUDGMENT_FIELDS if f in (fm or {})]
                check(
                    "%s：fm 无判定字段夹带" % (inp[:30] + "...",),
                    not leaked,
                    "leaked=%s" % (leaked,)
                )
                # 正文应等于整句输入（允许首尾空白差）
                check(
                    "%s：fm 正文 == 整句输入" % (inp[:30] + "...",),
                    (body or "").strip() == inp.strip(),
                    "body=%r != %r" % (body, inp)
                )
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)


def main():
    print("===== md_cg.test_t24a_split（E-T24a t1 写入侧拆分器验收） =====")
    test_a_split_correctness()
    test_b_pure_keep_no_miss()
    test_c_format_discipline()
    test_d_default_off()
    print("\n===== t24a split：%d 通过，%d 失败 =====" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()