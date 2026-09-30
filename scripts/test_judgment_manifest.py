# -*- coding: utf-8 -*-
"""test_judgment_manifest —— 判据面覆盖完备性守卫（issue #36）

背景：判据面清单曾漏冻 hive 的 6 个 Python 测试（88KB，判据主体最大一块）
及 compiler/swarm/scripts 的测试——弱化它们 digest 不变、A3 承重墙对它们
天然免疫。本守卫把「跑什么 ⊆ 冻结什么」与「弱化必红」固化为断言。

运行：python -X utf8 scripts/test_judgment_manifest.py
"""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile

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


# 生效条件：files（相对 HERE 的正斜杠路径列表）与 tmp（目标根）给定时，逐个把 HERE/<rel>
# copyfile 到 tmp/<rel>（父目录按需 makedirs），全部成功时返回物化文件数；任一 copyfile
# 失败即抛出（不静默跳过、不吞错）。
def _materialize(files, tmp):
    """把判据面物化成临时实验面（弱化实验的唯一落笔面，在役判据面全程只读）。

    仓内先例：scripts/test_verify_open_encoding.py:310 `_materialize_surface`
    （shutil.copyfile 物化扫描面）+ 同文件 :93「定点变异：完整扫描面临时副本上注入」；
    scripts/criteria_fingerprint.py:38 `worktree_of`（git archive → tempfile.mkdtemp）。
    """
    n = 0
    for rel in files:
        dst = os.path.join(tmp, rel)
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copyfile(os.path.join(HERE, rel), dst)
        n += 1
    return n


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
    target_rel = "hive/test_exec_tools.py"
    target = os.path.join(HERE, target_rel)
    orig = open(target, "rb").read()
    d0 = jm.digest(m)
    st0 = os.stat(target)
    # 并行安全收口（2026-09-30）：弱化实验只在**临时副本**上做——在役判据面全程只读。
    # 旧实现就地改写**被追踪的仓内文件**（append 弱化标记 → 再写回原字节还原），在
    # run_tests --jobs 4 下结构上并行不安全：窗口内任何并发读/导入该文件的进程都会
    # 看到被弱化的版本。实测至少两条触发路径：
    #   ① 嵌套套件再起一个本守卫实例：md_cg/test_interop_judgment.py:202 真跑
    #      `run_tests.py scripts -k judgment`（**默认 --jobs 4**）→ 内层套件会执行
    #      本模块（模块名含 judgment），两实例 append/采集/还原交错，先还原者吞掉
    #      后写者的标记（或把标记留在盘面）→ 本守卫自身「弱化必变/还原复原」红
    #      （实测 277/278 那次即此形态；这就是「偶发不可复现」的结构性成因）。
    #   ② 并发读者读到弱化字节：按 digest 判定的消费面 hive/verify_runner.py:139
    #      （A3 走 `judgment_manifest.py --digest`）与 md_cg/interop.py:104 在窗口内
    #      采样 → 判据面假漂移。
    # 处置选型（复用仓内既有机制，不新造一套）：物化临时实验面（见 _materialize）。
    # 未采用 run_tests._SERIAL_ONLY（并行时跳过）：那是**调度侧移除**——默认跑法
    # （--jobs 4）会把 #36 覆盖守卫整条移出执行集（守卫自身不再运行），且治不了嵌套
    # 套件/手跑并发的第二实例（跳过符只对本层 run_tests 生效）。文件锁同理：并发读者
    # 不持锁，「被读到弱化版本」锁不住，只把窗口换成阻塞。
    with tempfile.TemporaryDirectory(prefix="jm_guard_") as _exp:
        _n = _materialize([f["path"] for f in m["files"]], _exp)
        check("判据面已物化为临时实验面（并行安全的前提）",
              _n == len(m["files"]), (_n, len(m["files"])))
        copy = os.path.join(_exp, target_rel)   # 实验对象 = 副本，**非**在役被追踪文件
        saved_here = jm.HERE
        jm.HERE = _exp                          # 只换根：覆盖规则 PATTERNS 不变
        try:
            m_exp = jm.collect()
            check("实验面清单 == 判据面清单（同路径集，物化无遗漏）",
                  [f["path"] for f in m_exp["files"]]
                  == [f["path"] for f in m["files"]],
                  [f["path"] for f in m_exp["files"]][:4])
            check("实验面目标文件 == 在役目标字节（实验对象即真字节）",
                  [f["sha256"] for f in m_exp["files"]
                   if f["path"] == target_rel]
                  == [hashlib.sha256(orig).hexdigest()],
                  [f["sha256"] for f in m_exp["files"]
                   if f["path"] == target_rel])
            d_exp0 = jm.digest(m_exp)
            # 字节级有效变更（追加弱化标记行）。注：#36 原实验的 assert→pass
            # 替换在本文件是空操作（hive 测试用自写 check 框架、无 assert 字面量
            # ——这也说明「弱化形式」必须按判据文件实际写法设计）。
            # with 收句柄：Windows 上未关句柄会让 TemporaryDirectory 清理失败
            # （rmtree 删不掉被占文件）——不能靠 CPython 引用计数兜底。
            with open(copy, "ab") as _fh:
                _fh.write(b"\n# weakened-by-guard\n")
            d_exp1 = jm.digest(jm.collect())
            check("弱化 hive/test_exec_tools.py 后 digest 必变（#36 前不变）",
                  d_exp1 != d_exp0, f"{d_exp0[:16]}… vs {d_exp1[:16]}…")
        finally:
            jm.HERE = saved_here
    st1 = os.stat(target)
    check("实验面在临时副本上：在役被追踪文件全程零写入（字节/size/mtime 不变）",
          open(target, "rb").read() == orig
          and (st1.st_size, st1.st_mtime_ns) == (st0.st_size, st0.st_mtime_ns),
          (st0.st_size, st0.st_mtime_ns, st1.st_size, st1.st_mtime_ns))
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

    print("[4] --verify 缺参 fail-closed（CI/钩子参数拼空不得假成功）")
    # v6 N27：旧实现 `len(sys.argv) >= 3 and sys.argv[1] == "--verify"` 缺参时
    # 条件不成立 → 静默回落打印全量清单并 exit 0——比对从未发生（假成功）。
    import subprocess
    p = subprocess.run(
        [sys.executable, "-X", "utf8",
         os.path.join(HERE, "scripts", "judgment_manifest.py"), "--verify"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=HERE)
    check("--verify 缺参必须非零退出（不得静默回落 exit 0）", p.returncode != 0,
          f"EXIT={p.returncode}")
    check("--verify 缺参不得在 stdout 倾倒全量 manifest（比对从未发生）",
          '"files"' not in (p.stdout or ""), (p.stdout or "")[:120])

    print(f"\njudgment_manifest 守卫: {passed} 通过 / {failed} 失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
