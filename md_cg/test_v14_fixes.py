# -*- coding: utf-8 -*-
"""v14 第三方验证缺陷回归集（md_cg 侧：B / C / D / E / F / G / H）。

来源：第三方独立验证报告 v14（基线 784e91f）§4 复现取证。本文件把该报告中
**可复跑的观测**固化为机械断言——每条断言对应报告里的一条缺陷，修复前红、
修复后绿；任一回归即红灯。

覆盖（与报告编号一一对应）：
  B  `trust.propagate` 多跳失效传播被 `doubted` 中间节点整体截断（下游永不降级）
  C  `hotcache._query_key` 未覆盖 include_work/roles/paths/fusion/judge_ranking/
     goal_text/query_expand/context/path_weights/recall_only/early_stop_threshold
     → 跨口径串味（roles+include_work 可致资格泄漏）
  D  `coldverify._process` 未检查 `trust.set_state` 返回值 → 迁移被拒却上报
     ok=True（静默撒谎），且 stats.errors 掩盖
  E  `md_cg/units.py` 自持一份 serve 判活口径（ts-only + 5s vs 权威三层 + 15s）
  F  测试面非幂等：旁路执行造出 `_md_cg_wisdom_graph/` 空壳 → runner 由 SKIP 转 FAIL
  G  超边幂等键 `node_id_for` 分隔符未转义/无长度前缀 → 相邻列搬移得同 id
  H  `bench_en_atoms_public.py` 文件尾换行

运行：python -m md_cg.test_v14_fixes
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import time

try:
    from . import coldverify, hotcache, hyperedge, trust, units
    from .mdcos import MdCGOS
except ImportError:                                   # 直接脚本运行
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from md_cg import coldverify, hotcache, hyperedge, trust, units
    from md_cg.mdcos import MdCGOS

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS, FAIL = 0, []


def ok(cond, label):
    global PASS
    if cond:
        PASS += 1
        print("  ok   " + label)
    else:
        FAIL.append(label)
        print("  FAIL " + label)


def phase(name):
    print("--- " + name)


def _ccg(name, deps=None, body=""):
    sub = ("依赖 " + "、".join(deps)) if deps else "无"
    return ("# 功能名：%s\n# 生效条件：无条件\n# 子功能：%s\n# 执行：无\n"
            "# 验证方式：test\n# 不适用条件：无\n\n%s %s" % (name, sub, name, body))


def _st(cg, nid):
    return trust.state_of(cg.index["nodes"].get(nid) or {})


def _load_run_tests():
    """加载 scripts/run_tests.py（非包，按文件路径加载）。"""
    p = os.path.join(_REPO, "scripts", "run_tests.py")
    spec = importlib.util.spec_from_file_location("_v14_run_tests", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hb(jd, pid, age_ms):
    import json
    with open(os.path.join(jd, "_serve.json"), "w", encoding="utf-8") as f:
        json.dump({"ts": time.time() * 1000 - age_ms, "pid": pid, "workers": 1}, f)


# ------------------------------------------------------------------ B
def phase_b(tmp):
    phase("B trust.propagate 多跳传播须穿过 doubted 中间节点")
    ids = {"a": "mem_v14b_a", "b": "mem_v14b_b",
           "c": "mem_v14b_c", "d": "mem_v14b_d"}

    # B1 对照（中间节点非 doubted）：多跳正常
    cg1 = MdCGOS(root=os.path.join(tmp, "b1"))
    cg1.add(ids["a"], _ccg("上游甲"), layer="knowledge")
    cg1.add(ids["b"], _ccg("中间乙", ["甲"]), layer="knowledge",
           depends_on=[ids["a"]])
    cg1.add(ids["c"], _ccg("下游丙", ["乙"]), layer="knowledge",
           depends_on=[ids["b"]])
    cg1.add(ids["d"], _ccg("末端丁", ["丙"]), layer="knowledge",
           depends_on=[ids["c"]])
    ok(ids["b"] in trust.dependents_index(cg1).get(ids["a"], []),
       "B1 反查索引就位（甲 ← 乙）")
    trust.set_state(cg1, ids["a"], "expired", reason="t", actor="t")
    r1 = trust.propagate(cg1, apply=True)
    ok([_st(cg1, ids[k]) for k in ("b", "c", "d")] == ["doubted"] * 3,
       "B2 对照：中间节点非 doubted 时乙/丙/丁全被标 doubted（实得 %s）"
       % [_st(cg1, ids[k]) for k in ("b", "c", "d")])
    ok(r1.get("updated_count") == 3, "B2b updated_count=3（实得 %s）"
       % r1.get("updated_count"))

    # B3 初始 doubts 中间节点：下游仍须可达
    cg2 = MdCGOS(root=os.path.join(tmp, "b2"))
    for k, kw in (("a", {}), ("b", {"depends_on": [ids["a"]]}),
                  ("c", {"depends_on": [ids["b"]]}),
                  ("d", {"depends_on": [ids["c"]]})):
        cg2.add(ids[k], _ccg("甲" + k), layer="knowledge", **kw)
    trust.set_state(cg2, ids["a"], "expired", reason="t", actor="t")
    trust.set_state(cg2, ids["b"], "doubted", reason="t", actor="t")
    r2 = trust.propagate(cg2, apply=True)
    ok([_st(cg2, ids[k]) for k in ("c", "d")] == ["doubted", "doubted"],
       "B3 中间节点已 doubted 时下游丙/丁仍被标 doubted（实得 %s）"
       % [_st(cg2, ids[k]) for k in ("c", "d")])
    ok(r2.get("updated_count") == 2, "B3b updated_count=2（实得 %s）"
       % r2.get("updated_count"))
    ok(ids["b"] not in (r2.get("updated") or []),
       "B3c doubted 中间节点不被重复标记（幂等）")

    # B4 真实序列：先 mark_dependents（预演直接下游）再 propagate
    cg3 = MdCGOS(root=os.path.join(tmp, "b3"))
    for k, kw in (("a", {}), ("b", {"depends_on": [ids["a"]]}),
                  ("c", {"depends_on": [ids["b"]]}),
                  ("d", {"depends_on": [ids["c"]]})):
        cg3.add(ids[k], _ccg("乙" + k), layer="knowledge", **kw)
    trust.set_state(cg3, ids["a"], "expired", reason="t", actor="t")
    trust.mark_dependents(cg3, ids["a"])
    ok(_st(cg3, ids["b"]) == "doubted", "B4 一跳标记生效（乙=doubted）")
    r3 = trust.propagate(cg3, apply=True)
    ok([_st(cg3, ids[k]) for k in ("c", "d")] == ["doubted", "doubted"],
       "B5 真实序列（先 mark_dependents 再 propagate）多跳不失效（实得 %s）"
       % [_st(cg3, ids[k]) for k in ("c", "d")])
    ok(r3.get("updated_count") == 2, "B5b updated_count=2（实得 %s）"
       % r3.get("updated_count"))
    for cg in (cg1, cg2, cg3):
        cg.close()


# ------------------------------------------------------------------ C
def phase_c(tmp):
    phase("C hotcache query 键覆盖全部影响结果的参数")
    cg = MdCGOS(root=os.path.join(tmp, "c"))
    hotcache.attach(cg)
    kw = "v14cache口径"
    good, work = "mem_v14c_good", "mem_v14c_work"
    cg.add(good, _ccg("常规记忆", body=kw), layer="knowledge")
    cg.add(work, _ccg("工具输出", body=kw), layer="knowledge",
           role="tool-output")

    q = kw
    ids = lambda rs: [x[0]["id"] for x in rs]          # noqa: E731

    # C1-C2：**先**以 include_work 口径查询（污染候选规则）
    r1, m1 = cg.search_rrf(q, k=5, include_work=True)
    ok(m1.get("cached") is not True, "C1 include_work 首次查询非缓存")
    ok(work in ids(r1), "C2 include_work=True 时工作角色节点出现（该出的要出）")

    # C3-C4：**随后的首次默认查询**不得复用该口径（报告 C10 资格泄漏）
    r2, m2 = cg.search_rrf(q, k=5)
    ok(work not in ids(r2), "C3 默认查询不得返回工作角色节点（无资格泄漏）")
    ok(m2.get("cached") is not True,
       "C4 默认查询不得复用 include_work 口径缓存（报告 C9/C10）")

    # C5：默认口径自身缓存仍工作（修法不是「一律不缓存」）
    r3, m3 = cg.search_rrf(q, k=5)
    ok(work not in ids(r3) and m3.get("cached") is True,
       "C5 默认口径重复查询命中缓存且结果不含工作角色")

    r4, m4 = cg.search_rrf(q, k=5, paths=("bucket",))          # noqa: F841
    r5, m5 = cg.search_rrf(q, k=5, paths=("lexical",))
    ok(m5.get("cached") is not True, "C6 paths 不同口径不得互相命中（报告 C12）")
    ok("bucket" not in (m5.get("paths") or {}),
       "C7 paths=('lexical',) 的结果不含 bucket 路（实得 %s）"
       % sorted((m5.get("paths") or {}).keys()))

    r6, m6 = cg.search_rrf(q, k=5, fusion="max")                # noqa: F841
    ok(m6.get("cached") is not True, "C8 fusion 不同口径不得互相命中")

    r7, m7 = cg.search_rrf(q, k=5, judge_ranking=True)          # noqa: F841
    ok(m7.get("cached") is not True, "C9 judge_ranking 不同口径不得互相命中")

    r8, m8 = cg.search_rrf(q, k=5, roles=["tool-output"])       # noqa: F841
    ok(m8.get("cached") is not True, "C10 roles 不同口径不得互相命中")

    r9, m9 = cg.search_rrf(                                     # noqa: F841
        q, k=5, paths=("fuzzy",),
        query_expand=lambda _q: {"__source__": "test", kw: 1.0})
    ok(m9.get("cached") is not True,
       "C11 query_expand（自定义可调用）不写不读缓存（无法稳定进键即绕行）")
    _, m9b = cg.search_rrf(
        q, k=5, paths=("fuzzy",),
        query_expand=lambda _q: {"__source__": "test", kw: 1.0})
    ok(m9b.get("cached") is not True, "C11b 绕行为持续生效（非一次性）")

    r10, m10 = cg.search_rrf(q, k=5, goal_text="完全不同目标向量",       # noqa: F841
                             paths=("goal",))
    ok(m10.get("cached") is not True, "C12 goal_text 不同口径不得互相命中")

    # C13-C15 对照（报告 C13）：时间算子启用时读写双侧绕行缓存
    cg.add("mem_v14c_time", _ccg("时间轴记忆", body=kw), layer="knowledge")
    _, mt1 = cg.search_rrf(q, k=5, start_time=0.0, end_time=time.time() + 1e9)
    ok(mt1.get("cached") is not True, "C13 时间算子启用时不写不读缓存（对照）")
    _, mt2 = cg.search_rrf(q, k=5, start_time=0.0, end_time=time.time() + 1e9)
    ok(mt2.get("cached") is not True, "C14 时间算子重复查询仍不命中缓存（对照）")
    rt3, _mt3 = cg.search_rrf(q, k=5)
    ok(work not in ids(rt3),
       "C15 时间算子绕行后默认口径结果不变（无工作角色混入）")

    # C16 同口径确实仍能命中（修法不是「一律不缓存」）
    _, mh1 = cg.search_rrf(q, k=5)
    _, mh2 = cg.search_rrf(q, k=5)
    ok(mh2.get("cached") is True,
       "C16 同口径重复查询仍命中缓存（保留热路径收益）")
    cg.close()


# ------------------------------------------------------------------ D
def phase_d(tmp):
    phase("D coldverify 非法迁移须如实报错（不得静默撒谎）")
    cg = MdCGOS(root=os.path.join(tmp, "d"))
    coldverify.attach(cg)
    q = coldverify.get(cg)

    # D1 doubted + 已过期 → doubted→expired 被 TRANSITIONS 拒绝
    n1 = "mem_v14d_expired_doubted"
    cg.add(n1, _ccg("存疑且过期"), layer="knowledge",
           valid_from="2020-01-01", valid_until="2021-01-01")
    trust.set_state(cg, n1, "doubted", reason="t", actor="t")
    coldverify.enqueue(cg, n1, action="reverify")
    r1 = q.drain(cg)
    ok(r1 and r1[0].get("ok") is False,
       "D1 非法迁移（doubted→expired）上报 ok=False（报告 V6）")
    ok(_st(cg, n1) == "doubted", "D2 节点状态未被迁移（仍 doubted）")
    ok((r1[0].get("error") or ""), "D3 失败原因如实透出（error 非空）")
    ok(q.status()["stats"]["errors"] >= 1,
       "D4 stats.errors 计入（不再掩盖，报告 V7b）")

    # D5 verified + 未生效 → verified→unverified 被拒绝
    n2 = "mem_v14d_notyet_verified"
    cg.add(n2, _ccg("已验证但未生效"), layer="knowledge",
           valid_from="2099-01-01")
    trust.set_state(cg, n2, "verified", reason="t", actor="t")
    coldverify.enqueue(cg, n2, action="reverify")
    r2 = q.drain(cg)
    ok(r2 and r2[0].get("ok") is False,
       "D5 非法迁移（verified→unverified）上报 ok=False（报告 V7）")
    ok(_st(cg, n2) == "verified", "D6 节点状态未被迁移（仍 verified）")

    # D7 合法迁移仍正常（修法不是「一律报错」）
    n3 = "mem_v14d_ok"
    cg.add(n3, _ccg("已验证且过期"), layer="knowledge",
           valid_from="2020-01-01", valid_until="2021-01-01")
    trust.set_state(cg, n3, "verified", reason="t", actor="t")
    coldverify.enqueue(cg, n3, action="reverify")
    r3 = q.drain(cg)
    ok(r3 and r3[0].get("ok") is True and _st(cg, n3) == "expired",
       "D7 合法迁移（verified→expired）仍正常（实得 %s / %s）"
       % (r3[0].get("ok") if r3 else None, _st(cg, n3)))
    cg.close()


# ------------------------------------------------------------------ E
def phase_e(tmp):
    phase("E units 判活口径须与权威三层同口径")
    import hive.serve_start as serve_start

    ok(float(units.FRESH_S) == float(serve_start.FRESH_S),
       "E1 units.FRESH_S 与 serve_start.FRESH_S 同值（实得 %s vs %s）"
       % (units.FRESH_S, serve_start.FRESH_S))
    ok(float(units.FRESH_S) == 15.0, "E2 阈值为权威 15s（实得 %s）"
       % units.FRESH_S)
    src = open(units.__file__, encoding="utf-8").read()
    ok('"pid_alive":' in src and '"pid_is_self_program":' in src,
       "E3 units 透出三层判据明细（新鲜/pid 存活/pid 身份，可审计）")
    ok("def pid_is_self_program" in src, "E4 units 有身份层判据")
    ok("（同 _serve_alive）" not in src,
       "E5 契约注释不再自称「同 _serve_alive」（该断言曾在 v13 后失效）")

    jd = os.path.join(tmp, "hive_jobs")
    os.makedirs(jd, exist_ok=True)
    cases = [("新鲜+本进程+非 hive 映像", os.getpid(), 0),
             ("同类心跳 age=8s", os.getpid(), 8000),
             ("同类心跳 age=20s", os.getpid(), 20000),
             ("pid 不存在", 999999, 0),
             ("pid 不存在且陈旧", 999999, 60000)]
    for label, pid, age in cases:
        _hb(jd, pid, age)
        a = bool(units.serve_state(jd)["alive"])
        b = bool(serve_start.serve_alive(jd))
        ok(a == b, "E6 %s：units=%s / serve_start=%s（须同结论）"
           % (label, a, b))
    with open(os.path.join(jd, "_serve.json"), "w", encoding="utf-8") as f:
        f.write("{ 坏 json")
    ok(bool(units.serve_state(jd)["alive"]) is False,
       "E7 心跳损坏时不判活且不抛")
    os.remove(os.path.join(jd, "_serve.json"))
    ok(bool(units.serve_state(jd)["alive"]) is False, "E8 无心跳时不判活")


# ------------------------------------------------------------------ F
def phase_f(tmp):
    phase("F 测试面幂等：空壳目录不算依赖就绪")
    from . import md_whitebox

    cr = getattr(md_whitebox, "corpus_ready", None)
    if not callable(cr):
        ok(False, "F1 corpus_ready 判据未提供（修复前：只判目录存在）")
    else:
        shell = os.path.join(tmp, "shell")
        os.makedirs(shell)
        ok(cr(shell) is False, "F1 空壳目录不算语料就绪")

        real = os.path.join(tmp, "real", "knowledge")
        os.makedirs(real)
        with open(os.path.join(real, "n.md"), "w", encoding="utf-8") as f:
            f.write("---\nid: x\n---\n正文\n")
        ok(cr(os.path.join(tmp, "real")) is True, "F2 含 md 的目录算就绪")

    missing = os.path.join(tmp, "missing_corpus")
    try:
        md_whitebox.build_db_from_md(root=missing, verbose=False)
        ok(False, "F3 语料缺失须 fail-closed")
    except FileNotFoundError:
        ok(True, "F3 语料缺失 fail-closed（FileNotFoundError）")
    except Exception as exc:                               # noqa: BLE001
        ok(False, "F3 语料缺失 fail-closed（实得 %s: %s）"
           % (type(exc).__name__, exc))
    ok(not os.path.exists(missing), "F4 fail-closed 不产生空壳目录副作用")

    rt = _load_run_tests()
    old_repo = rt._REPO
    try:
        rt._REPO = tmp
        sh = os.path.join(tmp, "_md_cg_wisdom_graph")
        os.makedirs(sh)
        ok(rt._dep_mdroot() is not None,
           "F5 runner：空壳 _md_cg_wisdom_graph 不等于依赖就绪")
        with open(os.path.join(sh, "n.md"), "w", encoding="utf-8") as f:
            f.write("---\nid: x\n---\n")
        ok(rt._dep_mdroot() is None, "F6 runner：含 md 时依赖就绪")
    finally:
        rt._REPO = old_repo

    for rel in ("md_cg/test_md_access_parity.py",
                "md_cg/test_p44_md_whitebox.py",
                "md_cg/test_wisdom_md_store.py"):
        txt = open(os.path.join(_REPO, rel), encoding="utf-8").read()
        ok("SKIP" in txt,
           "F7 %s 自带依赖缺失自辩（SKIP 出口）" % os.path.basename(rel))


# ------------------------------------------------------------------ G / H
def phase_g():
    phase("G 超边幂等键无歧义（长度前缀）")
    base = {"received_at": "t", "verify_id": "a", "commit": "b",
            "verdict": "v", "receipt_job": "j", "iter_id": "i"}
    row1 = dict(base, commit="b\x1fc")
    row2 = dict(base, verify_id="a\x1fb", commit="c")
    ok(hyperedge.node_id_for(row1) != hyperedge.node_id_for(row2),
       "G1 相邻列搬移含 \\x1f 的文本得不同 id（报告 H17）")
    ok(hyperedge.node_id_for(row1) == hyperedge.node_id_for(dict(row1)),
       "G2 同一台账行恒同 id（幂等保持）")
    ok(hyperedge.node_id_for(base).startswith("he_"), "G3 id 前缀不变")
    bad = dict(base, commit="c")
    ok(hyperedge.node_id_for(base) != hyperedge.node_id_for(bad),
       "G4 无分隔符对照组 id 不同（问题是规范化而非哈希碰撞）")

    phase("H 卫生：文件尾换行")
    p = os.path.join(_REPO, "md_cg", "bench_en_atoms_public.py")
    with open(p, "rb") as f:
        ok(f.read().endswith(b"\n"), "H1 bench_en_atoms_public.py 尾换行在位")


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_v14_")
    try:
        phase_b(tmp)
        phase_c(tmp)
        phase_d(tmp)
        phase_e(tmp)
        phase_f(tmp)
        phase_g()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nPASS=%d FAIL=%d" % (PASS, len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        sys.exit(1)


main()
