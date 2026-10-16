# -*- coding: utf-8 -*-
# 功能名：hive 台账跨进程追加「不丢行 / 不撕裂 / 不重复」守卫（issue #465）
# 生效条件：python -u -X utf8 -m hive.test_issue465_append_concurrency；被测面=hive/_append.py 与走它的三站点
# 子功能：G01 形态要素（两文件**各自独立**断言）· G02 真并发不丢不撕裂不重复 · G03 单写反向腿 · G04 open 失败仍降级不打断（情形 i）· G05 锁超时仍不打断但留痕（情形 ii）
# 执行：临时区夹具；G02/G05 用真子进程；G02 规模取**能复现缺陷的那一档**
# 验证方式：全部 PASS；本文件先于实现落地时 G02 为预期红
# 不适用条件：不判 hive/src 的 Rust 侧（本件只覆盖 Python 侧三站点）；不判「小规模全绿」（见 G02-b 明确标为不判别）
"""issue #465 守卫：多 worker 并发追加不得丢行。

★判据规模（本件的核心教训）：**规模选择本身是判据的一部分；小规模全绿不能作为通过依据。**
实测：旧实现（逐条 open("a")）8x400 丢 1166 行；候选 (b)（os.open(O_APPEND)+单次 os.write）在
8x400 与 16x400 **全绿**、在 8x2000 **崩**（768 半截、丢 9708）。⇒ 若按 8x400 写本守卫，它对
新旧实现都会绿 —— **这条腿不判别**。故 G02 取 8x2000，并把 8x400 那档显式列为「不判别」。
它与「良性变异必须真的转红」同族，但**更隐蔽：红腿自己不知道自己不判别**。

★「同形」判据有两种写法（本件取后者）：跨文件**比值**比较（脆——md_cg/fsutil.py 合法重构即误报）
与两文件**各自独立断言要素**（只在某一侧真的丢了该要素时红，那正是要抓的漂移）。
⇒ 判据落在「要素是否还在」上，不落在「两处的值此刻是否相等」上。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from hive import _append as AP          # noqa: E402

PASS = FAIL = 0
FAILS = []


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:200])


print("== G01 形态要素：两文件**各自独立**断言（不做跨文件比值）==")
_ELEMS = [(".lock 后缀", "LOCK_SUFFIX"), ]
for _rel in ("hive/_append.py", "md_cg/fsutil.py"):
    _s = io.open(os.path.join(_REPO, _rel), encoding="utf-8").read()
    ok("G01 %s：.lock 锁文件形态在" % _rel, ".lock" in _s or "LOCK_SUFFIX" in _s)
    ok("G01 %s：Windows 分支 msvcrt.LK_NBLCK 在" % _rel, "msvcrt.LK_NBLCK" in _s)
    ok("G01 %s：锁首字节（第三参 1）在" % _rel, ", 1)" in _s)
    ok("G01 %s：POSIX 分支 LOCK_EX 与 LOCK_NB 均在" % _rel,
       "LOCK_EX" in _s and "LOCK_NB" in _s)   # 判「要素是否还在」，不判书写形式（fsutil 写作 fcntl.LOCK_EX | fcntl.LOCK_NB）
    ok("G01 %s：timeout/poll 轮询语义在" % _rel, "poll" in _s and "timeout" in _s)

_W = """
import sys, json
sys.path.insert(0, sys.argv[1])
from hive import _append as AP
path, wid, m = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
for i in range(m):
    AP.append_line(path, json.dumps({"w": wid, "i": i, "pad": "x" * 120}) + "\\n", tag="guard")
"""
_SB = tempfile.mkdtemp(prefix="i465_guard_")
_wp = os.path.join(_SB, "w.py")
io.open(_wp, "w", encoding="utf-8").write(_W)


def _run(N, M, name, must_pass=True):
    p = os.path.join(_SB, "led_%d_%d.jsonl" % (N, M))
    if os.path.exists(p):
        os.remove(p)
    ps = [subprocess.Popen([sys.executable, "-u", "-X", "utf8", _wp, _REPO, p,
                            str(w), str(M)]) for w in range(N)]
    [r.wait() for r in ps]
    lines = [l for l in io.open(p, encoding="utf-8", errors="replace").read().split("\n") if l.strip()]
    good = half = 0
    seen = {}
    for l in lines:
        try:
            o = json.loads(l)
            good += 1
            seen[(o["w"], o["i"])] = seen.get((o["w"], o["i"]), 0) + 1
        except Exception:
            half += 1
    dup = sum(c - 1 for c in seen.values() if c > 1)
    d = {"total": len(lines), "good": good, "half": half,
         "missing": N * M - good, "dup": dup}
    if must_pass:
        ok("G02 %s N=%d M=%d 期望=%d ⇒ %s（total==N*M ∧ half==0 ∧ dup==0）" % (name, N, M, N * M, d),
           len(lines) == N * M and half == 0 and dup == 0, d)
    return d


print("")
print("== G02 真并发：规模取能复现缺陷的那一档 ==")
_d400 = _run(8, 400, "【不判别档·仅记录】", must_pass=False)
print("       [记录] 8x400（**不判别**：旧实现与本实现都可能绿，不得作为通过依据）⇒ %s" % _d400)
_run(8, 2000, "【判别档】")
ok("G03 反向腿1（过度收紧方向）：单进程单写仍通过（加锁不得挡住正常写）",
   _run(1, 100, "single", must_pass=False)["total"] == 100)

print("")
print("== G04/G05 失败语义：一个观测只对应一个原因 ==")
# 单原因场景：目标**本身是目录** ⇒ 锁文件 `isdir.lock` 可建（锁路径无碍），只有「目标不可写」这一个原因。
_f = os.path.join(_SB, "isdir")
os.makedirs(_f, exist_ok=True)
_b0 = AP.DEGRADED["target_unwritable"].get("g04", 0)
_c0 = AP.DEGRADED["lock_file_unavailable"].get("g04", 0)
ok("G04 情形(i)：目标不可写 ⇒ 返回 False**且不抛**（绝不打断任务，:83 语义）",
   AP.append_line(_f, "line\n", tag="g04", timeout=0.3) is False)
ok("G04 情形(i)：只计 target_unwritable（**单原因**，且不误记 lock_file_unavailable）",
   AP.DEGRADED["target_unwritable"].get("g04", 0) == _b0 + 1
   and AP.DEGRADED["lock_file_unavailable"].get("g04", 0) == _c0,
   {"target_unwritable": AP.DEGRADED["target_unwritable"],
    "lock_file_unavailable": AP.DEGRADED["lock_file_unavailable"]})
_HOLD = """
import sys, time
sys.path.insert(0, sys.argv[1])
from hive import _append as AP
f = AP._acquire(sys.argv[2], 5.0, 0.01)
sys.stdout.write("held\\n"); sys.stdout.flush()
time.sleep(6)
"""
_hp = os.path.join(_SB, "hold.py")
io.open(_hp, "w", encoding="utf-8").write(_HOLD)
_tp = os.path.join(_SB, "t.txt")
_h = subprocess.Popen([sys.executable, "-u", "-X", "utf8", _hp, _REPO, _tp],
                      stdout=subprocess.PIPE)
_h.stdout.readline()                    # 等它拿到锁
_t0 = dict(AP.DEGRADED["lock_timeout"])
_r = AP.append_line(_tp, "contended\n", tag="g05", timeout=0.3)
_h.kill()
ok("G05 情形(ii)：锁竞争超时 ⇒ 返回 False**且不抛**（不打断任务）", _r is False, _r)
ok("G05 情形(ii)：超时**必须留痕**（计 lock_timeout，不得静默丢行）",
   AP.DEGRADED["lock_timeout"].get("g05", 0) == _t0.get("g05", 0) + 1,
   AP.DEGRADED["lock_timeout"])
ok("G05 情形(ii) 与 (i) **分别计数、不得共用一个信号**（一个观测只对应一个原因）",
   AP.DEGRADED["lock_timeout"].get("g05", 0) >= 1
   and "g05" not in AP.DEGRADED["target_unwritable"]
   and "g05" not in AP.DEGRADED["lock_file_unavailable"],
   {"target_unwritable": AP.DEGRADED["target_unwritable"],
    "lock_file_unavailable": AP.DEGRADED["lock_file_unavailable"],
    "lock_timeout": AP.DEGRADED["lock_timeout"]})

print("")
print("断言总数 %d（PASS %d / FAIL %d）" % (PASS + FAIL, PASS, FAIL))
if FAILS:
    print("FAILED:")
    for f in FAILS:
        print("   - " + f)
sys.exit(1 if FAILS else 0)