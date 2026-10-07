# -*- coding: utf-8 -*-
"""盲区 → 目标生成器（goal_gen.candidates）验证 + 定点变异自证。

功能名：test_goal_gen —— goal_gen 生成器守卫（隔离临时库 + 定点变异自证）。
生效条件：`python -m md_cg.test_goal_gen`（run_tests.py md_cg 组内自动发现）。
子功能：断言面——
  ① 六源各自映射（S1 unresolved / S2 insight pending / S3 固化候补 /
     S6 缺失维度 + S4 BLINDSPOT / S5 空路由）——候选字段正确；
  ② 确定性：同输入两次生成同 goal_text 列表（不含时间戳/随机）；
  ③ 幂等：同信号重复 apply → 同 id 覆盖更新（add_goal sha1 契约）；
  ④ 分档（裁定第 9 条）：维护类走 decide(A_ADD)——confirm 档 allow 自动登记、
     plan 档 fail-closed 不登记；探索类入审核队列（不入 goals）；越权类丢弃且
     记 boundary_refused；
  ⑤ dry_run 零落库（apply=False → goals/review 层零新增）；
  ⑥ 不进自动循环（sleep.py / sustain.py 不引用 goal_gen）；
  ⑦ 白箱闸（F3）：生成器不直调 `_write_node`、经 `add_goal` 公开 API 落库。
  定点变异自证（表内每项 = 说明 + 逐字锚点替换 + 预期 ≥1 红）：去掉越权判定 /
    apply=False 也落库 / 绕过 add 直调 _write_node / 去掉 decide 调用——各自转红；
    自证后**复原**（变异只在内存副本，不落盘）、复跑基线全绿。
执行：`python -m md_cg.test_goal_gen`（默认含变异自证）。
验证方式：test。
不适用条件：活库（一切读写都在 tempfile.mkdtemp 内，绝不碰在役数据根）。
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile

from . import goal_gen, insight
from . import autonomy_modes
from .fsutil import append_jsonl
from .mdcos import MdCGOS

#: 档位 env 键名**经唯一入口常量取**（不写第二处字面量——与
#: test_autonomy_modes G 组「全仓只有 autonomy_modes 读档位 env」的静态判据相容）。
_ENV_MODE_KEY = autonomy_modes.AUTONOMY_ENV_KEYS["mode"]

PKG_DIR = os.path.dirname(os.path.abspath(goal_gen.__file__))
GEN_PATH = os.path.abspath(goal_gen.__file__)

PASS = FAIL = 0
FAILS = []


def _note(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  [FAIL] {label}")


def _mk(tmp, name):
    root = os.path.join(tmp, name)
    os.makedirs(root, exist_ok=True)
    return MdCGOS(root)


def _sig(cg, t, query, states):
    """直写一条反思记录（与 test_blindspot_tickets._sig 同构：只造信号面）。"""
    append_jsonl(cg.reflection_log,
                 {"t": t, "query": query, "d_prev": 1.0, "d_curr": 1.0,
                  "d_delta": 0.0, "d2": 0.1, "states": states,
                  "n_results": 1, "feedback": None})


def _fill_nobasis(cg, n=6, layer="knowledge"):
    """造 n 个无验证基底的节点（触发 S3 固化候补读数）。"""
    for i in range(n):
        cg.add("nb_%d" % i, "# 功能名：测试节点 %d\n# 不适用条件：无\n正文\n" % i,
               layer=layer)
    return n


# ---------------------------------------------------------------- 断言检查（返回 bool）

def c1_s1_mapping(tmp, gen):
    cg = _mk(tmp, "c1")
    cg.add_unresolved("如何审计 gossip 收敛性")
    r = gen.candidates(cg, sources=["S1"])
    cs = r["candidates"]
    return (r["n_candidates"] == 1 and cs[0]["source"] == "S1"
            and cs[0]["goal_text"] == "消解未解问题：如何审计 gossip 收敛性"
            and cs[0]["class"] == gen.CLASS_EXPLORE
            and cs[0]["moved_to"] == "dry_run"
            and cs[0]["conditions"])


def c2_s2_threshold(tmp, gen):
    cg = _mk(tmp, "c2")
    insight.record(cg, "洞见甲")
    insight.record(cg, "洞见乙")
    lo = gen.candidates(cg, sources=["S2"])
    insight.record(cg, "洞见丙")
    r = gen.candidates(cg, sources=["S2"])
    texts = sorted(c["goal_text"] for c in r["candidates"])
    return (lo["n_candidates"] == 0 and r["n_candidates"] == 3
            and texts == sorted(["裁决待验证洞见：洞见甲",
                                 "裁决待验证洞见：洞见乙",
                                 "裁决待验证洞见：洞见丙"]))


def c3_s6_mapping(tmp, gen):
    from . import evolution
    cg = _mk(tmp, "c3")
    for i in range(3):
        evolution.record(cg, pattern="缺维度测试 %d" % i, missing="验证方式")
    r = gen.candidates(cg, sources=["S6"])
    cs = [c for c in r["candidates"] if c["source"] == "S6"]
    return (len(cs) == 1 and cs[0]["goal_text"] == "补条件维度：验证方式"
            and cs[0]["class"] == gen.CLASS_MAINTAIN)


def c4_determinism(tmp, gen):
    cg = _mk(tmp, "c4")
    cg.add_unresolved("问题甲")
    cg.add_unresolved("问题乙")
    a = [c["goal_text"] for c in gen.candidates(cg, sources=["S1"])["candidates"]]
    b = [c["goal_text"] for c in gen.candidates(cg, sources=["S1"])["candidates"]]
    return a == b and len(a) == 2 and a == sorted(a)


def c5_s4_mapping(tmp, gen):
    cg = _mk(tmp, "c5")
    _sig(cg, 1.0, "未知领域查询", {"BLINDSPOT": 3})
    r = gen.candidates(cg, sources=["S4"])
    cs = [c for c in r["candidates"] if c["source"] == "S4"]
    from . import metacognition
    return (len(cs) == 1
            and cs[0]["goal_text"] == "补条件消解高频盲区：%s"
            % metacognition._key("未知领域查询")
            and cs[0]["class"] == gen.CLASS_EXPLORE)


def c6_s5_empty_route(tmp, gen):
    cg = _mk(tmp, "c6")
    _sig(cg, 1.0, "库内无锚点的盲区面", {"BLINDSPOT": 2})
    r = gen.candidates(cg, sources=["S5"])
    cs = [c for c in r["candidates"] if c["source"] == "S5"]
    from . import metacognition
    key = metacognition._key("库内无锚点的盲区面")
    return (len(cs) == 1
            and cs[0]["goal_text"] == "补锚点/边：%s 推演路由为空" % key
            and cs[0]["class"] == gen.CLASS_EXPLORE)


def c7_maintain_confirm_autoreg(tmp, gen):
    cg = _mk(tmp, "c7")
    _fill_nobasis(cg, 6)
    r = gen.candidates(cg, sources=["S3"], apply=True)
    ms = [c for c in r["candidates"] if c["class"] == gen.CLASS_MAINTAIN]
    goals = {g["goal"] for g in cg.list_goals()}
    return (len(ms) == 1 and ms[0]["moved_to"] == "goals"
            and ms[0]["goal_text"] in goals and r["created"] == 1)


def c8_maintain_plan_failclosed(tmp, gen):
    cg = _mk(tmp, "c8")
    _fill_nobasis(cg, 6)
    os.environ[_ENV_MODE_KEY] = "plan"
    try:
        r = gen.candidates(cg, sources=["S3"], apply=True)
    finally:
        os.environ.pop(_ENV_MODE_KEY, None)
    return (r["created"] == 0 and r["forbidden"] == 1
            and len(cg.list_goals()) == 0)


def c9_explore_to_queue(tmp, gen):
    cg = _mk(tmp, "c9")
    _sig(cg, 1.0, "未知领域查询", {"BLINDSPOT": 3})
    r = gen.candidates(cg, sources=["S4"], apply=True)
    es = [c for c in r["candidates"] if c["class"] == gen.CLASS_EXPLORE]
    return (len(es) == 1 and es[0]["moved_to"] == "review_queue"
            and bool(es[0]["pid"]) and len(cg.review_list()) == 1
            and len(cg.list_goals()) == 0)


def c10_boundary_refused(tmp, gen):
    cg = _mk(tmp, "c10")
    cg.add_unresolved("是否要对外发送本批次报告")
    r = gen.candidates(cg, sources=["S1"], apply=True)
    cs = r["candidates"]
    return (len(cs) == 1 and cs[0]["class"] == gen.CLASS_REFUSE
            and cs[0]["moved_to"] == "boundary_refused"
            and r["refused"] == 1
            and len(cg.list_goals()) == 0 and len(cg.review_list()) == 0)


def c11_dry_run_zero_write(tmp, gen):
    cg = _mk(tmp, "c11")
    _sig(cg, 1.0, "未知领域查询", {"BLINDSPOT": 3})
    cg.add_unresolved("问题X")
    _fill_nobasis(cg, 6)
    r = gen.candidates(cg, apply=False)
    return (len(cg.list_goals()) == 0 and len(cg.review_list()) == 0
            and r["created"] == 0 and r["queued"] == 0
            and all(c["moved_to"] == "dry_run" for c in r["candidates"]))


def c12_idempotent(tmp, gen):
    cg = _mk(tmp, "c12")
    _fill_nobasis(cg, 6)
    r1 = gen.candidates(cg, sources=["S3"], apply=True)
    ids1 = {g["id"] for g in cg.list_goals()}
    r2 = gen.candidates(cg, sources=["S3"], apply=True)
    ids2 = {g["id"] for g in cg.list_goals()}
    return (r1["created"] == 1 and r2["created"] == 1
            and len(ids1) == len(ids2) == 1 and ids1 == ids2)


def c13_not_in_autoloop(tmp, gen):
    """不进自动循环：sleep.py / sustain.py 不引用 goal_gen。"""
    for f in ("sleep.py", "sustain.py"):
        p = os.path.join(PKG_DIR, f)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                if "goal_gen" in fh.read():
                    return False
    return True


def c14_whitebox_gate(tmp, gen):
    """F3：生成器不直调 _write_node，落库经 add_goal 公开 API。"""
    src = getattr(gen, "__source__", None)
    if src is None:
        with open(GEN_PATH, encoding="utf-8") as fh:
            src = fh.read()
    return "._write_node(" not in src and "add_goal(" in src


def c15_log_trace(tmp, gen):
    """留痕：每轮生成 append 一条 _goal_gen.jsonl 记录。"""
    cg = _mk(tmp, "c15")
    cg.add_unresolved("问题甲")
    gen.candidates(cg, sources=["S1"])
    p = gen.goal_log_path(cg)
    return os.path.exists(p) and os.path.getsize(p) > 0


_CHECKS = (
    ("①S1 映射", c1_s1_mapping),
    ("①S2 阈值(pending>=3)", c2_s2_threshold),
    ("①S6 映射", c3_s6_mapping),
    ("②确定性(同输入同文本)", c4_determinism),
    ("①S4 映射", c5_s4_mapping),
    ("①S5 空路由映射", c6_s5_empty_route),
    ("④维护类 confirm 自动登记", c7_maintain_confirm_autoreg),
    ("④维护类 plan 档 fail-closed", c8_maintain_plan_failclosed),
    ("④探索类入审核队列", c9_explore_to_queue),
    ("④越权类 boundary_refused", c10_boundary_refused),
    ("⑤dry_run 零落库", c11_dry_run_zero_write),
    ("③幂等同 id 覆盖", c12_idempotent),
    ("⑥不进自动循环", c13_not_in_autoloop),
    ("⑦白箱闸(不直调 _write_node)", c14_whitebox_gate),
    ("留痕 _goal_gen.jsonl", c15_log_trace),
)


def _run_suite(tmp, gen):
    """跑全部检查（异常按失败计），返回失败标签列表——供变异自证复用。

    每轮**独立子目录**（run_tmp）：变异模式连跑多轮，共用目录会读到上一轮盘面。
    """
    run_tmp = tempfile.mkdtemp(prefix="run_", dir=tmp)
    fails = []
    for label, fn in _CHECKS:
        try:
            ok = bool(fn(run_tmp, gen))
        except Exception as exc:            # noqa: BLE001
            ok = False
            label = "%s（异常 %s）" % (label, type(exc).__name__)
        if not ok:
            fails.append(label)
    return fails


# ---------------------------------------------------------------- 定点变异自证
# 表内每项 = (说明, ((锚点原文, 替换文), ...))。锚点须**逐字**出现在生成器源码里，
# 漂移即 ANCHOR-MISS（fail-closed）。
_MUTATIONS = (
    ("M1 去掉越权类判定（边界词面检查恒假）",
     (("if hits_boundary(_cand_blob(cand)):",
       "if False and hits_boundary(_cand_blob(cand)):"),)),
    ("M2 让 apply=False 也落库",
     (("        if apply:\n", "        if True:\n"),)),
    ("M3 绕过 add 直调 _write_node",
     (("cg.add_goal(cand[\"goal_text\"]", "cg._write_node(cand[\"goal_text\"]"),)),
    ("M4 去掉 decide 调用（plan 档仍落卡）",
     (("        dec = autonomy_modes.decide(autonomy_modes.A_ADD)",
       "        dec = {\"decision\": autonomy_modes.ALLOW}"),)),
)


def _load_mutated(name, src):
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "md_cg"
    mod.__source__ = src
    sys.modules[name] = mod
    exec(compile(src, name, "exec"), mod.__dict__)
    return mod


def _mutate_and_run(tmp, idx, label, repls):
    with open(GEN_PATH, encoding="utf-8") as fh:
        src = fh.read()
    for old, new in repls:
        if old not in src:
            _note(False, f"变异{idx} ANCHOR-MISS（锚点漂移，fail-closed）：{label}")
            return
        src = src.replace(old, new, 1)
    name = "md_cg.goal_gen_mut_%d" % idx
    mod = _load_mutated(name, src)
    try:
        fails = _run_suite(tmp, mod)
    finally:
        sys.modules.pop(name, None)
    _note(len(fails) >= 1,
          f"变异{idx} 转红（{len(fails)} 红 ≥1）：{label}"
          + ("；红项=" + "/".join(fails[:4]) if fails else ""))


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_goal_gen_")
    try:
        print("[一] 基线全绿（真实生成器，隔离临时库）")
        base_fails = {f.split("（异常")[0] for f in _run_suite(tmp, goal_gen)}
        for label, _fn in _CHECKS:
            _note(label not in base_fails, label)

        print("\n[二] 定点变异自证（内存副本，不落盘；自证后基线不受影响）")
        for i, (label, repls) in enumerate(_MUTATIONS, 1):
            _mutate_and_run(tmp, i, label, repls)

        print("\n[三] 复核：变异后真实生成器仍全绿（复原验证）")
        re_fails = _run_suite(tmp, goal_gen)
        _note(not re_fails, "复原后基线仍全绿")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== test_goal_gen: PASS {PASS} / FAIL {FAIL} ===")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
