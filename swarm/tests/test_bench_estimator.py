# -*- coding: utf-8 -*-
"""issue #302 守卫：bench_swarm_parallel 的**加速比估计量**性质。

报告（issue #302）称该基准是「单样本毫秒级墙钟 + 2× 硬阈值」的结构性 flaky。
本守卫钉住修复后的判定构造，使「把基准改成稳健估计」与「偷偷放宽阈值」可区分：
  G1 加速比公式（串行参照 = t1×N，逐位不变）；
  G2 阈值 2.0 **未放宽**，且边界为严格大于（与旧口径一致）；
  G3 稳健性：5 次采样中 1 次离群不翻盘（单样本口径下会翻盘）；
  G4 功率面：多数样本位移仍判红（稳健 ≠ 免疫）；
  G5 估计量性质（全等样本取原值、单调、REPS 为奇数且 ≥3）；
  G6 反事实：报告实测的 1.69× 读数恒判红（该构造仍能抓到真回退）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from swarm.tests import bench_swarm_parallel as B

PASS, FAIL = 0, 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL " + label)


def pair(ratio, n=B.N):
    """构造一对 (t1, tN) 使加速比恰为 ratio（t1=1.0 ⇒ tN = n/ratio）。"""
    return (1.0, float(n) / ratio)


def g1():
    print("[G1] 加速比公式")
    ok(B.speedup_of(1.0, 1.0, 8) == 8.0, "G1a t1=tN ⇒ 加速比 = N")
    ok(abs(B.speedup_of(2.0, 4.0, 8) - 4.0) < 1e-12, "G1b (2.0, 4.0, N=8) ⇒ 4.0")
    ok(abs(B.speedup_of(*pair(2.5)) - 2.5) < 1e-12, "G1c pair(2.5) 自洽 ⇒ 2.5")
    ok(B.N == 8 and B.R == 4, "G1d N=8 / R=4 与基线逐位一致")


def g2():
    print("[G2] 阈值未放宽 + 严格大于")
    ok(B.THRESHOLD == 2.0, "G2a 阈值 = 2.0（未放宽）")
    ok(B.verdict(2.0) is False, "G2b 恰为 2.0 ⇒ 不过（边界不算过）")
    ok(B.verdict(2.0001) is True, "G2c 略高于 2.0 ⇒ 过")
    ok(B.verdict(1.9999) is False, "G2d 略低于 2.0 ⇒ 不过")
    ok(B.verdict(8.0) is True, "G2e 理论上限 8× ⇒ 过")


def g3():
    print("[G3] 稳健性：单次离群不翻盘")
    good, bad = pair(2.9), pair(1.0)
    five = [good, good, good, good, bad]
    ok(abs(B.robust_speedup(five) - 2.9) < 1e-12,
       "G3a 5 次里 1 次 1.0×（塌陷）⇒ 稳健值仍 2.9×")
    ok(B.verdict(B.robust_speedup(five)) is True, "G3b 该次判过（单样本口径下会误判红）")
    # 反证：旧口径若恰好抽到那一次离群，就会红
    ok(B.verdict(B.speedup_of(*bad)) is False,
       "G3c 旧口径抽到该次离群 ⇒ 判红（正是 #302 的误报形态）")
    ok(abs(B.robust_speedup([pair(1.0), good, good]) - 2.9) < 1e-12,
       "G3d 3 次里 1 次离群 ⇒ 中位仍是 2.9×")


def g4():
    print("[G4] 功率面：多数位移仍判红（稳健 ≠ 免疫）")
    good, bad = pair(2.9), pair(1.0)
    three_bad = [bad, bad, bad, good, good]
    ok(abs(B.robust_speedup(three_bad) - 1.0) < 1e-12,
       "G4a 5 次里 3 次塌陷 ⇒ 稳健值 1.0×")
    ok(B.verdict(B.robust_speedup(three_bad)) is False, "G4b 判红（持续回退抓得住）")
    ok(abs(B.robust_speedup([pair(1.5)] * 5) - 1.5) < 1e-12,
       "G4c 整体回退到 1.5× ⇒ 稳健值 1.5×、判红")
    ok(B.verdict(B.robust_speedup([pair(1.5)] * 5)) is False, "G4d 同上判红")


def g5():
    print("[G5] 估计量性质")
    ok(B.REPS >= 3, "G5a REPS ≥ 3（单样本口径已废弃）")
    ok(B.REPS % 2 == 1, "G5b REPS 为奇数（中位数落在真实样本上，非插值）")
    ok(abs(B.robust_speedup([pair(3.3)] * B.REPS) - 3.3) < 1e-12,
       "G5c 全等样本 ⇒ 稳健值等于该值（无偏置）")
    rs = [B.robust_speedup([pair(x)] * B.REPS) for x in (1.2, 2.0, 3.0, 4.5)]
    ok(rs == sorted(rs), "G5d 对加速比单调（不引入非单调假象）")
    ok(abs(B.robust_speedup([pair(2.9), pair(2.9), pair(1.0), pair(1.0), pair(2.9)])
           - 2.9) < 1e-12, "G5e 3 好 2 坏 ⇒ 取好值（中位数的定义面）")


def g6():
    print("[G6] 反事实：报告实测读数恒判红")
    for r in (1.69, 1.91, 1.5, 1.0):
        ok(B.verdict(B.robust_speedup([pair(r)] * B.REPS)) is False,
           "G6 %s 加速比 ⇒ 判红（构造仍能抓到真回退）" % r)


# ---------------------------- 定点变异自证 ----------------------------

#: 每处变异**必须**打红的判据（子集断言）。只要求「红项非空」不够——
#: 变异写出的文件若与上一处字节数相同且同 mtime 秒，CPython 的 .pyc 头判定
#: 未失效会读到上一处的字节码（#301 实测踩过），故逐处核对期望红项。
MUTS = (
    ("M1 中位改最小值（best-of 高估）",
     "    return statistics.median([speedup_of(a, b, n) for a, b in pairs])",
     "    return min(speedup_of(a, b, n) for a, b in pairs)",
     ("G3a", "G3b")),
    ("M2 中位改均值（离群仍拖）",
     "    return statistics.median([speedup_of(a, b, n) for a, b in pairs])",
     "    return statistics.mean([speedup_of(a, b, n) for a, b in pairs])",
     ("G3a",)),
    ("M3 阈值放宽到 1.0",
     "THRESHOLD = 2.0",
     "THRESHOLD = 1.0",
     ("G2a", "G2b", "G2d")),
    ("M4 严格大于改成大于等于",
     "    return speedup > threshold",
     "    return speedup >= threshold",
     ("G2b",)),
    ("M5 加速比公式漏掉 N",
     "    return (t1 * n) / tN",
     "    return t1 / tN",
     ("G1a", "G1b", "G1c")),
    ("M6 退回单样本（REPS=1）",
     "REPS = 5",
     "REPS = 1",
     # 只钉 G5a：REPS=1 仍是奇数，G5b（奇偶性）本就该绿——期望写错是守卫的账，不是 G5b 的账
     ("G5a",)),
)


def _run_guard(repo):
    """子进程重跑本守卫；禁写字节码 + 清掉被测模块的旧 .pyc（见 MUTS 上方取证）。"""
    import glob
    import subprocess
    for p in glob.glob(os.path.join(repo, "swarm", "tests", "__pycache__",
                                    "bench_swarm_parallel.*.pyc")):
        try:
            os.remove(p)
        except OSError:
            pass
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                        "swarm.tests.test_bench_estimator"],
                       cwd=repo, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600, env=env)
    o = (p.stdout or "") + (p.stderr or "")
    return [l.strip()[5:].split()[0] for l in o.splitlines()
            if l.strip().startswith("FAIL ")], o


def mutate():
    """对 swarm/tests/bench_swarm_parallel.py 逐处定点变异。"""
    import io as _io
    import shutil
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tgt = os.path.join(repo, "swarm", "tests", "bench_swarm_parallel.py")
    bak = tgt + ".mutbak"
    if os.path.exists(bak):
        print("已有 .mutbak，先人工核对——拒绝在可能已被改动的源上跑变异")
        return 1
    with _io.open(tgt, encoding="utf-8", newline="") as f:
        orig = f.read()
    shutil.copyfile(tgt, bak)
    bad = []
    try:
        for name, old, new, expect in MUTS:
            cnt = orig.count(old)
            if cnt != 1:
                print("  BAD  %-30s 锚点命中 %d 次（须恰好 1 次）" % (name, cnt))
                bad.append(name)
                continue
            with _io.open(tgt, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(old, new))
            red, o = _run_guard(repo)
            miss = [x for x in expect if x not in red]
            if red and not miss:
                print("  OK   %-30s 红项=%d（期望 %d 项全中）%s"
                      % (name, len(red), len(expect), "；".join(red[:4])[:70]))
            else:
                why = ("红项=0" if not red else "期望未被打红：%s" % "、".join(miss))
                print("  BAD  %-30s %s（实得红项 %s）"
                      % (name, why, "、".join(red) or "-"))
                bad.append(name)
    finally:
        shutil.copyfile(bak, tgt)
        with _io.open(tgt, encoding="utf-8", newline="") as f:
            restored = f.read()
        os.remove(bak)
    if restored != orig:
        print("源未逐字节还原——中止")
        return 1
    print()
    if bad:
        print("定点变异自证：FAIL -- " + "、".join(bad))
        return 1
    print("定点变异自证：PASS（每处变异的期望判据全部被打红）")
    return 0


def main():
    if "--mutate" in sys.argv:
        return mutate()
    for fn in (g1, g2, g3, g4, g5, g6):
        fn()
    print()
    print("== bench 估计量守卫：%d 通过 / %d 失败 ==" % (PASS, FAIL))
    for f in FAILS:
        print("  - " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
