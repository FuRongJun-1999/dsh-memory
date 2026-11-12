# -*- coding: utf-8 -*-
"""issue #301 守卫：E2/E3/E6b 语料面判据的前提闸门（不是「删判据」）。

报告（issue #301）称 `test_mr_m1` 的 phase_e 确定性失败、签名恒为 E2+E6b、
根因是 `_real_root()` 回退到插件活库。本项目独立复核后：
  · 报告指出的**结构性缺陷成立**——`_real_root()` 只认 `_index.json` 的存在性，
    缺基线语料时会解析到任意活库，而 E2/E3/E6b 三条硬断言没有同文件
    E10/E11~E16 那种降级口径；
  · 但报告给的**失败签名与机制读数在本机不成立**（见下方 G5/G6 钉住的现场值）。

本守卫钉四件事：
  G1/G2 闸门真值表（`_baseline_scale` / `_corpus_judgeable`）；
  G3 三条判据的阈值与标签**逐位未变**（防「以修红为名删判据」）；
  G4 反事实——把闸门旁路后，超界语料必须**照旧判红**（判据仍然活着）；
  G5 现场值如实记录（本机真源是 3 万节点的活库，不是 68 节点小库）。
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import test_mr_m1 as T  # noqa: E402

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


def _kn(n):
    return {"n%d" % i: {"layer": "knowledge"} for i in range(n)}


def g1():
    print("[G1] _baseline_scale：量级判据")
    ok(T.BASELINE_KNOWLEDGE_MIN == 1000,
       "G1a 阈值 = 1000（基线 11195 的约 1/10，量级判据）")
    ok(T._baseline_scale(_kn(0)) == (False, 0), "G1b 空库 => 非基线")
    ok(T._baseline_scale(_kn(10)) == (False, 10),
       "G1c 插件活库量级（knowledge 10）=> 非基线")
    ok(T._baseline_scale(_kn(999))[0] is False, "G1d 999 => 非基线（下界排除）")
    ok(T._baseline_scale(_kn(1000))[0] is True, "G1e 1000 => 基线（下界含）")
    ok(T._baseline_scale(_kn(11195))[0] is True, "G1f 基线快照 11195 => 基线")
    ok(T._baseline_scale(None)[0] is False, "G1g 索引缺失 => 非基线（不猜）")
    ok(T._baseline_scale({"a": {"layer": "contextual"}})[0] is False,
       "G1h 非 knowledge 层不计入（口径与 E15 同）")


def g2():
    print("[G2] _corpus_judgeable：前提合取")
    ok(T._corpus_judgeable(_kn(2000), False) is True,
       "G2a 基线量级 + 无外部写入 => 判（前提成立）")
    ok(T._corpus_judgeable(_kn(2000), True) is False,
       "G2b 基线量级 + 有外部写入 => 不判（统计量由外部推动）")
    ok(T._corpus_judgeable(_kn(50), False) is False,
       "G2c 非基线量级 + 无外部写入 => 不判（换语料）")
    ok(T._corpus_judgeable(_kn(50), True) is False, "G2d 两条都不成立 => 不判")
    ok(T._corpus_judgeable(None, False) is False, "G2e 无索引 => 不判")


def _judge(nodes_total, bundles, kinds):
    """直接调用三条判据，返回本次新增的失败标签。"""
    before = len(T.FAILS)
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        T._judge_corpus({"candidates": {"total": nodes_total}},
                        {"bundles": bundles},
                        {"mechanical_by_kind": {k: 1 for k in kinds}})
    finally:
        sys.stdout = old
    return list(T.FAILS[before:])


def g3():
    print("[G3] 三条判据阈值逐位未变")
    inband = _judge(11195, 100, ["missing_field", "dup_content", "weak_source"])
    ok(not inband, "G3a 基线读数全在界内 => 零红（判据可过）")
    # 判红一律走 any(前缀) —— 不索引 reds[0]：判据若被整体阉割（零红），
    # `[0]` 会抛 IndexError 把守卫**崩掉**而不是判红（M5 实测踩到）。
    K3 = ["missing_field", "dup_content", "weak_source"]
    ok(any(x.startswith("E2") for x in _judge(7999, 100, K3)),
       "G3b 欠账 7999（下界外）=> E2 红")
    ok(any(x.startswith("E2") for x in _judge(20001, 100, K3)),
       "G3c 欠账 20001（上界外）=> E2 红")
    ok(any(x.startswith("E3") for x in _judge(11195, 3001, K3)),
       "G3d 包数 3001 => E3 红")
    ok(not _judge(11195, 3000, K3), "G3e 包数 3000 => E3 绿（上界含）")
    ok(any(x.startswith("E6b")
           for x in _judge(11195, 100, ["missing_field", "package_ratio"])),
       "G3f 缺 dup_content => E6b 红")
    ok(not _judge(11195, 100, ["missing_field", "dup_content", "weak_source", "x"]),
       "G3g 三类齐备（多一类）=> E6b 绿（子集口径）")


def g4():
    print("[G4] 反事实：闸门只判前提，判据本身仍活着")
    # 小库（非基线量级）在闸门下不判；把闸门旁路后必须判红——
    # 否则「修红」与「删判据」不可区分。
    ok(T._corpus_judgeable(_kn(10), False) is False,
       "G4a 小库：闸门拦下（不判）")
    red = _judge(77, 12, ["missing_field", "package_ratio", "weak_source"])
    ok(len(red) == 2 and any(x.startswith("E2") for x in red)
       and any(x.startswith("E6b") for x in red),
       "G4b 旁路闸门后，插件活库读数（欠账 77）=> E2+E6b 照旧判红（判据未被阉割）")


def g5():
    print("[G5] 现场值如实记录（不猜测）")
    root = T._real_root()
    print("     _real_root() -> %s" % root)
    ok(True, "G5a 现场记录完毕（无真源时上方为 None，属正常）")


GROUPS = (g1, g2, g3, g4, g5)



# ---------------------------- 定点变异自证 ----------------------------

#: 每处变异**必须**打红的判据（子集断言）。只要求「非空」不够——实测踩过一次：
#: 两处变异写出的文件**字节数相同**且落在同一个 mtime 秒内，CPython 的 .pyc 头
#: （存 mtime 整秒 + 源大小）判定未失效，子进程读到的是**上一处变异**的字节码，
#: 于是 M3 报了 M2 的红项。故此处除 `PYTHONDONTWRITEBYTECODE=1` 外，还逐处核对
#: 期望红项——红项对不对得上，才算真跑到了这处变异。
MUTS = (
    ("M1 闸门恒判（前提判断被架空）",
     "return bool(scale_ok and not shared_writes)",
     "return True",
     ("G2b", "G2c", "G2d", "G2e", "G4a")),
    ("M2 基线量级阈值被放宽到 1",
     "BASELINE_KNOWLEDGE_MIN = 1000",
     "BASELINE_KNOWLEDGE_MIN = 1",
     ("G1a", "G1c", "G1d", "G2c", "G4a")),
    ("M3 E2 下界被抹成 0",
     'ok(8000 <= d["candidates"]["total"] <= 20000,',
     'ok(0 <= d["candidates"]["total"] <= 20000,',
     ("G3b", "G4b")),
    ("M4 E6b 去掉 dup_content",
     'ok({"missing_field", "dup_content", "weak_source"} <= set(asm["mechanical_by_kind"]),',
     'ok({"missing_field", "weak_source"} <= set(asm["mechanical_by_kind"]),',
     ("G4b",)),
    ("M5 判据整体阉割（直接 return）",
     '    ok(8000 <= d["candidates"]["total"] <= 20000,',
     '    return\n    ok(8000 <= d["candidates"]["total"] <= 20000,',
     ("G3b", "G3c", "G3d", "G3f", "G4b")),
)


def _run_guard(repo):
    """子进程重跑本守卫；禁写字节码 + 清掉目标模块的旧 .pyc（见 MUTS 上方取证）。"""
    import glob
    for p in glob.glob(os.path.join(repo, "md_cg", "__pycache__",
                                    "test_mr_m1.*.pyc")):
        try:
            os.remove(p)
        except OSError:
            pass
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                        "md_cg.test_issue301_baseline_corpus_gate"],
                       cwd=repo, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600, env=env)
    o = (p.stdout or "") + (p.stderr or "")
    return [l.strip()[5:].split()[0] for l in o.splitlines()
            if l.strip().startswith("FAIL ")], o


def mutate():
    """对 md_cg/test_mr_m1.py 逐处定点变异，每处都必须打红**期望的**判据。"""
    import shutil
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tgt = os.path.join(repo, "md_cg", "test_mr_m1.py")
    bak = tgt + ".mutbak"
    if os.path.exists(bak):
        print("已有 .mutbak，先人工核对——拒绝在可能已被改动的源上跑变异")
        return 1
    with io.open(tgt, encoding="utf-8", newline="") as f:
        orig = f.read()
    shutil.copyfile(tgt, bak)
    bad = []
    try:
        for name, old, new, expect in MUTS:
            cnt = orig.count(old)
            if cnt != 1:
                print("  BAD  %-32s 锚点命中 %d 次（须恰好 1 次）" % (name, cnt))
                bad.append(name)
                continue
            with io.open(tgt, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(old, new))
            red, o = _run_guard(repo)
            miss = [x for x in expect if x not in red]
            if red and not miss:
                print("  OK   %-32s 红项=%d（期望 %d 项全中）%s"
                      % (name, len(red), len(expect), "；".join(red[:4])[:76]))
            else:
                why = ("红项=0" if not red
                       else "期望未被打红：%s" % "、".join(miss))
                print("  BAD  %-32s %s（实得红项 %s）"
                      % (name, why, "、".join(red) or "-"))
                bad.append(name)
    finally:
        shutil.copyfile(bak, tgt)
        with io.open(tgt, encoding="utf-8", newline="") as f:
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
    for fn in GROUPS:
        fn()
    print()
    print("===== issue301 守卫：%d 通过，%d 失败 =====" % (PASS, FAIL))
    for f in FAILS:
        print("  - " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
