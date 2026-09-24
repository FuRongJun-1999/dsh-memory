# -*- coding: utf-8 -*-
"""test_judgment_manifest —— 判据面覆盖完备性守卫（issue #36）

背景：判据面清单曾漏冻 hive 的 6 个 Python 测试（88KB，判据主体最大一块）
及 compiler/swarm/scripts 的测试——弱化它们 digest 不变、A3 承重墙对它们
天然免疫。本守卫把「跑什么 ⊆ 冻结什么」与「弱化必红」固化为断言。

运行：python -X utf8 scripts/test_judgment_manifest.py
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

spec = importlib.util.spec_from_file_location(
    "judgment_manifest", os.path.join(HERE, "scripts", "judgment_manifest.py"))
jm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jm)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:200])


def main():
    print("[1] 覆盖完备性（issue #36 主诉）：跑什么 ⊆ 冻结什么")
    m = jm.collect()
    # v20 D-36-1 重构后签名：coverage_gap(discovered_files, patterns)——
    # 域覆盖判定（不再吃现算 manifest，那会使差集恒空=守卫假牙）
    rt_spec = importlib.util.spec_from_file_location(
        "run_tests_rt", os.path.join(HERE, "scripts", "run_tests.py"))
    rt = importlib.util.module_from_spec(rt_spec)
    rt_spec.loader.exec_module(rt)
    gap = jm.coverage_gap(rt._discovered_files())
    check("run_tests 实际执行清单全部在判据面覆盖域内", not gap, gap[:8])
    # 能红断言（v20 D-36-1 对照场景固化）：发现规则新增目录而 PATTERNS 未跟
    # → 域外文件必须报出（旧「现算集合差」实现恒 PASS，此处必红）
    gap2 = jm.coverage_gap(["md_cg/test_ok.py", "newdir/test_drift.py"])
    check("域外文件（发现规则漂移）必报缺口", gap2 == ["newdir/test_drift.py"],
          gap2)
    check("域内文件正确地不报（collect 会收、digest 自动含）",
          "md_cg/test_ok.py" not in gap2)
    groups = m.get("groups") or {}
    check("分组计数显式化（digest 构成可读）", bool(groups), groups)
    check("groups 计数总和 == files 数",
          sum(groups.values()) == len(m["files"]),
          (sum(groups.values()), len(m["files"])))
    for need in ("hive/test_*.py", "compiler/tests/*.py", "swarm/tests/*.py",
                 "scripts/test_*.py"):
        check(f"#36 缺口已补：{need} 在清单内（≥1 文件）", groups.get(need, 0) >= 1,
              groups.get(need))
    paths = {f["path"] for f in m["files"]}
    check("hive 最大判据载荷 test_exec_tools.py 已入判据面",
          "hive/test_exec_tools.py" in paths)

    print("[2] 弱化必红（issue #36 复现实验固化为断言）")
    target = os.path.join(HERE, "hive", "test_exec_tools.py")
    orig = open(target, "rb").read()
    d0 = jm.digest(m)
    try:
        # 字节级有效变更（追加弱化标记行）。注：#36 原实验的 assert→pass
        # 替换在本文件是空操作（hive 测试用自写 check 框架、无 assert 字面量
        # ——这也说明「弱化形式」必须按判据文件实际写法设计）。
        open(target, "ab").write(b"\n# weakened-by-guard\n")
        d1 = jm.digest(jm.collect())
        check("弱化 hive/test_exec_tools.py 后 digest 必变（#36 前不变）",
              d1 != d0, f"{d0[:16]}… vs {d1[:16]}…")
    finally:
        open(target, "wb").write(orig)
    check("还原后 digest 复原", jm.digest(jm.collect()) == d0)

    print("[3] run_tests._discover 与 _discovered_files 同源")
    rt_spec = importlib.util.spec_from_file_location(
        "run_tests", os.path.join(HERE, "scripts", "run_tests.py"))
    rt = importlib.util.module_from_spec(rt_spec)
    rt_spec.loader.exec_module(rt)
    disc = rt._discover()
    check("四组齐全（md_cg/compiler|swarm/scripts/hive）",
          {g for g, _, _ in disc} == {"md_cg", "compiler", "swarm",
                                      "scripts", "hive"},
          sorted({g for g, _, _ in disc}))
    check("discover 数量 == discovered_files 数量",
          len(disc) == len(rt._discovered_files()))

    print(f"\njudgment_manifest 守卫: {passed} 通过 / {failed} 失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
