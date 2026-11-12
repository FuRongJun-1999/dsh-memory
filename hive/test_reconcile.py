#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""hive/test_reconcile.py —— hive/reconcile.py 的守卫（断言 ＋ 定点变异自证）

# 功能名：派发留痕对账的守卫——逐条断言 ＋ 每条判据一个定点变异
# 生效条件：凡改动 hive/reconcile.py 后；凡要把对账结论用于实际派发纪律前。
# 子功能：① 临时夹具（4 job 覆盖 终态/非终态/缺产物 + 3 卡片覆盖 正式/仅提及/悬空）
#         ② 8 条断言 ③ 5 条定点变异自证
# 执行：python -X utf8 hive/test_reconcile.py [--mutate]
# 验证方式：基线全绿；变异模式下每条恰好命中声明红项
# 不适用条件：不适用于真实蜂巢 job 的业务正确性（本守卫只测对账逻辑）
"""

import io
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "reconcile.py")
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


def _w(path, text):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def mkfixture():
    """自造确定性夹具：4 job + 3 卡片。"""
    d = tempfile.mkdtemp(prefix="reconcile_fixture_")
    jobs = os.path.join(d, "jobs")
    for jid, status, with_result in (("h_test_001", "done", True),
                                     ("h_test_002", "done", True),
                                     ("h_test_003", "running", False),
                                     ("h_test_004", "error", False)):
        _w(os.path.join(jobs, jid, "spec.json"), json.dumps({"job": jid}))
        _w(os.path.join(jobs, jid, "status.json"), json.dumps({"status": status}))
        if with_result:
            _w(os.path.join(jobs, jid, "result.json"), json.dumps({"ok": True}))
    brain = os.path.join(d, "brain")
    _w(os.path.join(brain, "knowledge", "card_a.md"),
       "---\nnode_id: card_a\nderived_from: [h_test_001]\n---\n\n正式声明。\n")
    _w(os.path.join(brain, "knowledge", "card_b.md"),
       "---\nnode_id: card_b\n---\n\n正文里提了一句 h_test_002，但没声明。\n")
    _w(os.path.join(brain, "knowledge", "card_c.md"),
       "---\nnode_id: card_c\nderived_from:\n  - h_test_999\n---\n\n悬空。\n")
    return d, jobs, brain


def run_checks(mod):
    d, jobs, brain = mkfixture()
    try:
        rep = mod.reconcile(jobs, brain)
        c = rep["counts"]

        ok("R1 正式链接只认 derived_from 声明", rep["linked"] == ["h_test_001"],
           rep["linked"])
        ok("R2 仅内容提及不算正式链接（两分类必须分开）",
           rep["mention_only"] == ["h_test_002"], rep["mention_only"])
        ok("R3 断链＝终态无声明；非终态(running)不算断链",
           rep["unlinked"] == ["h_test_002", "h_test_004"], rep["unlinked"])
        ok("R4 悬空＝卡片声明了不存在的 job",
           rep["dangling"] == [{"job_id": "h_test_999", "card": "knowledge/card_c.md"}],
           rep["dangling"])
        ok("R5 产物缺失＝终态无 result.json", rep["incomplete"] == ["h_test_004"],
           rep["incomplete"])

        v = mod.verify_link(jobs, brain, "h_test_001")
        ok("R6 能红判据：抽一条 job 必须反查到卡片与 result.json",
           v["ok"] is True and v["result_path"] and v["cards"] == ["knowledge/card_a.md"], v)
        v2 = mod.verify_link(jobs, brain, "h_test_002")
        ok("R7 反查必须失败时失败（h_test_002 无声明 ⇒ ok=False）",
           v2["ok"] is False and v2["reason"] == "no_card_declares_it", v2)
        ok("R8 确定性：同输入两次对账逐字段相同",
           mod.reconcile(jobs, brain)["counts"] == c, (c, mod.reconcile(jobs, brain)["counts"]))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # 不编造：无脑库侧时必须明说「未核对」，而不是把它算成 0 风险
    d2 = tempfile.mkdtemp(prefix="reconcile_empty_")
    try:
        empty = os.path.join(d2, "jobs")
        os.makedirs(empty)
        r2 = mod.reconcile(empty, None)
        ok("R9 不编造：未传脑库 ⇒ brain_scanned=False 且不产出断链结论",
           r2["brain_scanned"] is False and r2["counts"]["unlinked"] == 0
           and r2["counts"]["dangling"] == 0, r2["counts"])
    finally:
        shutil.rmtree(d2, ignore_errors=True)


def _load(text, name="reconcile_mut"):
    mod = types.ModuleType(name)
    mod.__file__ = SRC
    exec(compile(text, "<reconcile-mut>", "exec"), mod.__dict__)
    return mod


_MUTATIONS = [
    ("M1 不记仅提及", '                mention_only.setdefault(jid, []).append(c["path"])',
     '                mention_only.setdefault(jid, []).append(c["path"]) if False else None',
     {"R2"}),
    ("M2 不记正式链接", '                linked.setdefault(jid, []).append(c["path"])',
     '                linked.setdefault(jid, []).append(c["path"]) if False else None',
     {"R1", "R3"}),
    ("M3 不判悬空", '                dangling.append({"job_id": jid, "card": c["path"]})',
     '                pass',
     {"R4"}),
    ("M4 产物缺失不判", '            "has_result": os.path.isfile(res),',
     '            "has_result": True,',
     {"R5"}),
    ("M5 终态集放宽含 running", 'TERMINAL = ("done", "error", "timeout", "killed")',
     'TERMINAL = ("done", "error", "timeout", "killed", "running")',
     {"R3", "R5"}),
]


def _mutate_mode():
    print("!! 定点变异自证：逐条短路一条判据，对应断言必须**恰好**转红" + chr(10))
    base = io.open(SRC, encoding="utf-8").read()
    bad = []
    for name, old, new, expect in _MUTATIONS:
        if base.count(old) != 1:
            print("  ANCHOR-MISS %s：锚点命中 %d 次" % (name, base.count(old)))
            bad.append(name)
            continue
        global _red, _quiet
        _red, _quiet = [], True
        try:
            run_checks(_load(base.replace(old, new)))
        except Exception as e:
            _quiet = False
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
        print("定点变异：FAIL —— " + "；".join(bad))
        return 1
    print("定点变异：PASS（逐条恰好命中期望红项）")
    return 0


def main(argv):
    global _red          # 必须声明：否则 _red=[] 成为局部变量，汇总恒报「失败 0」
    if "--mutate" in argv:
        return _mutate_mode()
    print("== hive/reconcile.py 守卫（断言）==")
    _red = []
    run_checks(_load(io.open(SRC, encoding="utf-8").read(), "reconcile_base"))
    print("=" * 70)
    if _red:
        print("通过 %d / 失败 %d" % (9 - len(_red), len(_red)))
        print("失败项：" + " / ".join(_red))
        return 1
    print("通过 9 / 失败 0")
    print("ALL OK（反面证明见 --mutate）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
