# -*- coding: utf-8 -*-
"""冷路径队列跨实例丢条目守卫（issue #265）。

【守什么】
#265 报：多实例共用同一记忆库根时 `_coldverify.jsonl` **静默丢条目**——
后落盘者把先落盘者刚写的任务整段抹掉，两边都 rc=0、都报成功。

复核**成立**（实测读数与报告逐字一致）：
  两进程各自入队 → `DISK disk_lines=1 node_ids=['liveA']`；
  同进程两实例     → `IN_PROCESS disk_lines=1 node_ids=['nodeB']`。

病灶：`_persist()` 是**全量覆写**（写的是「本实例内存的快照」），`enqueue` 在
**进程内** `threading.Lock` 下 append 后直接调它 ⇒ 跨实例没有任何互斥或合并。
生产可达：`attach(cg)` 给**每个 cg 实例**各建一个队列，而
`writepipe._after_trust` 每次写入都 enqueue。

修法（报告建议 1/2/3，代价见 S8）：
  ① `enqueue` 走 `_append_persisted`——**追加**，物理上抹不掉别人的条目；
  ② `drain` 走 `_drop_persisted`——FileLock + atomic_write 读改写，**只删
     自己消费的**（Counter 按 (node_id, action, enqueued_at) 逐条扣减）；
  ③ 半截行：追加前用 `ends_mid_line` 补换行；`_load_persisted` 改**逐行容错**
     （改前 json 异常由包住整个循环的 except 捕获 ⇒ 一行坏、整份都不恢复）。

判据：
  S1  结构：enqueue 走追加、drain 走「只删自己消费的」；_persist 不再被二者调用。
  S2  ★ 两进程（真并发、同根）各自入队 ⇒ 盘上 **2** 条（报告的核心读数）。
  S3  同进程两实例 ⇒ 盘上 **2** 条。
  S4  drain 只删自己消费的：他实例未消费的条目**留在盘上**。
  S5  半截行：整份队列仍恢复（改前 0 条），且后续追加不与之粘连。
  S6  反陈化：三处理由在源码里（#265 / 追加抹不掉别人 / 只删自己消费的）。
  S7  修复前原形：git log -S 定位引入提交取父版本；**未提交时回落 HEAD**
      （不假设 HEAD 处于某历史状态——项目方在 #277 踩过该坑）。
  S8  代价不退化：300 次入队中位 < 5ms/次（报告要求「同量级」；实测改前
      0.407ms、改后 0.189ms——全量覆写是 O(队列长度)，追加是 O(1)）。
  S9  既有语义不破：clear() 仍清空；加载白名单仍拒非法 action 并计 skipped；
      **dry_run 逐字节不动盘**（#72 的 G2 判据）。
  S10 墓碑：`_done` 条目加载时跳过（既有语义，S4 的读改写也据此清理）。

运行：python -X utf8 -m md_cg.test_issue265_coldverify_multiproc
      python -X utf8 -m md_cg.test_issue265_coldverify_multiproc --mutate
"""
from __future__ import annotations

import io
import json
import os
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time

_TMP = tempfile.mkdtemp(prefix="i265g_")
# ★ 目录名不可用 "aux"——AUX 是 Windows 保留设备名（#245 实测踩到）。
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxstore")
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import coldverify as CV          # noqa: E402
from md_cg.fsutil import read_jsonl         # noqa: E402

_OK = 0
_BAD = []
_N = [0]


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _root():
    _N[0] += 1
    r = os.path.join(_TMP, "r%d" % _N[0])
    os.makedirs(r, exist_ok=True)
    return r


def _qpath(root):
    return os.path.join(root, CV.QUEUE_FILE)


def _tasks(root):
    p = _qpath(root)
    return list(read_jsonl(p)) if os.path.exists(p) else []


def _ids(root):
    return sorted(t.get("node_id") for t in _tasks(root))


class _NoCG:
    """drain 的 cg 替身：get() 恒 None ⇒ reverify 走 node_not_found 分支，
    不碰真库（本件只关心**落盘**，不关心验证结论）。"""

    def get(self, nid):
        return None


def _src(rel):
    return io.open(os.path.join(_REPO, rel), encoding="utf-8",
                   errors="replace").read()


def _cold_body(name):
    src = _src(os.path.join("md_cg", "coldverify.py"))
    i0 = src.index("    def %s(" % name)
    nxt = src.find("\n    def ", i0 + 10)
    return src[i0:nxt if nxt > 0 else len(src)]


def s1():
    print("== S1 结构：追加 + 只删自己消费的 ==")
    enq = _cold_body("enqueue")
    dr = _cold_body("drain")
    _check("S1a enqueue 走 _append_persisted", "_append_persisted(task)" in enq)
    _check("S1b enqueue **不再**走 _persist（全量覆写）",
           "_persist()" not in enq, enq[-200:])
    _check("S1c drain 走 _drop_persisted", "_drop_persisted(batch)" in dr)
    _check("S1d drain **不再**走 _persist", "_persist()" not in dr)
    _check("S1e _append_persisted 用 O_APPEND 追加",
           "os.O_APPEND" in _cold_body("_append_persisted"))
    _check("S1f _drop_persisted 用 FileLock(strict=True) + atomic_write",
           "strict=True" in _cold_body("_drop_persisted")
           and "_atomic_write" in _cold_body("_drop_persisted"))


def _child_script():
    p = os.path.join(_TMP, "child.py")
    if not os.path.exists(p):
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent('''
                import os, sys, time
                sys.path.insert(0, r"%s")
                from md_cg.coldverify import ColdVerifyQueue
                tag, root, tmp = sys.argv[1], sys.argv[2], sys.argv[3]
                q = ColdVerifyQueue(root=root)
                open(os.path.join(tmp, "ready_" + tag), "w").write("1")
                while not (os.path.exists(os.path.join(tmp, "ready_liveA"))
                           and os.path.exists(os.path.join(tmp, "ready_liveB"))):
                    time.sleep(0.02)
                q.enqueue(tag, action="reverify")
            ''') % _REPO)
    return p


def s2():
    print("== S2 ★ 两进程（真并发、同根）各自入队 ==")
    root = _root()
    child = _child_script()
    try:
        procs = [subprocess.Popen(
            [sys.executable, "-X", "utf8", child, t, root, _TMP],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE) for t in
            ("liveA", "liveB")]
        for pr in procs:
            pr.communicate(timeout=180)
    except Exception as exc:                       # noqa: BLE001
        _check("S2 起子进程失败：%s" % exc, False)
        return
    got = _ids(root)
    _check("S2a 盘上 **2** 条（改前=1，后写者抹掉先写者）", len(got) == 2, got)
    _check("S2b 两条分别是 liveA 与 liveB", got == ["liveA", "liveB"], got)


def s3():
    print("== S3 同进程两实例（各自先构造再各自入队）==")
    root = _root()
    q1 = CV.ColdVerifyQueue(root=root)
    q2 = CV.ColdVerifyQueue(root=root)
    q1.enqueue("nodeA", action="reverify")
    q2.enqueue("nodeB", action="reverify")
    got = _ids(root)
    _check("S3a 盘上 **2** 条（改前=1）", len(got) == 2, got)
    _check("S3b 两实例内存各 1 条（内存面本就独立）",
           len(q1._queue) == 1 and len(q2._queue) == 1)


def s4():
    print("== S4 drain 只删自己消费的 ==")
    root = _root()
    qa = CV.ColdVerifyQueue(root=root)
    qb = CV.ColdVerifyQueue(root=root)
    qb.enqueue("consume_me_A", action="reverify")     # 盘：[consume_me_A]
    qa.enqueue("keep_me_B", action="reverify")        # 盘：[consume_me_A, keep_me_B]
    _check("S4-pre 盘上两条都在（追加生效）",
           _ids(root) == ["consume_me_A", "keep_me_B"], _ids(root))
    # qc 加载盘面后**只消费其中一条**（模拟「本实例消费，他实例那条还没被消费」）
    qc = CV.ColdVerifyQueue(root=root)
    qc._queue = type(qc._queue)(
        [t for t in qc._queue if t["node_id"] == "consume_me_A"])
    _check("S4-pre2 qc 只认 consume_me_A",
           [x["node_id"] for x in qc._queue] == ["consume_me_A"])
    qc.drain(_NoCG())
    got = _ids(root)
    _check("S4a 自己消费的已从盘上摘除", "consume_me_A" not in got, got)
    _check("S4b ★ 他实例未消费的条目**留在盘上**", "keep_me_B" in got, got)
    _check("S4c 盘上恰 1 条", len(got) == 1, got)


def s5():
    print("== S5 半截行：整份队列仍恢复，且后续追加不粘连 ==")
    root = _root()
    qf = _qpath(root)
    with io.open(qf, "w", encoding="utf-8") as f:
        f.write(json.dumps({"node_id": "ok1", "action": "reverify"}) + "\n")
        f.write(json.dumps({"node_id": "ok2", "action": "reverify"}) + "\n")
        f.write('{"node_id": "half", "act')      # 上一个写者被杀在中途
    q = CV.ColdVerifyQueue(root=root)
    _check("S5a ★ 半截行不阻断整份恢复（改前=0 条）",
           q.status()["queue_size"] == 2, q.status()["queue_size"])
    q.enqueue("after_half", action="reverify")
    got = _ids(root)
    _check("S5b 追加的新条目可读（未粘在半截行上）", "after_half" in got, got)
    _check("S5c 两行好条目仍在", {"ok1", "ok2"} <= set(got), got)


def s6():
    print("== S6 反陈化：三处理由在源码里 ==")
    src = _src(os.path.join("md_cg", "coldverify.py"))
    _check("S6a 标注 issue #265", "issue #265" in src)
    _check("S6b 写明「追加在物理上抹不掉别人的条目」",
           "抹不掉" in src)
    _check("S6c 写明「只删自己消费的」", "只删自己消费的" in src
           or "只删自己消费" in src)
    _check("S6d 写明半截行/整份不恢复的旧病象",
           "整份队列都不恢复" in src)
    _check("S6e 写明跨进程 FileLock 的必要性（与读改写互斥）",
           "读改写" in src)


def _prepatch_src():
    def _g(*a):
        return subprocess.run(list(a), cwd=_REPO, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=60)
    lg = _g("git", "log", "-S_append_persisted", "--format=%H", "--",
            "md_cg/coldverify.py")
    if lg.returncode == 0:
        shas = [x.strip() for x in (lg.stdout or "").splitlines() if x.strip()]
        if shas:
            s = _g("git", "show", shas[-1] + "^:md_cg/coldverify.py")
            if s.returncode == 0:
                return s.stdout, "引入提交 %s 的父版本" % shas[-1][:8]
    s = _g("git", "show", "HEAD:md_cg/coldverify.py")
    if s.returncode != 0:
        return None, "git show HEAD rc=%s" % s.returncode
    return s.stdout, "HEAD（本改动尚未提交）"


def s7():
    print("== S7 修复前原形（提交前/后都稳定）==")
    t, how = _prepatch_src()
    if t is None:
        _check("S7 取修复前源失败：%s" % how, False)
        return
    print("       （修复前源取自 %s）" % how)
    _check("S7a 修复前无 _append_persisted", "_append_persisted" not in t)
    _check("S7b 修复前无 _drop_persisted", "_drop_persisted" not in t)
    _check("S7c ★ 修复前的 _persist 确是「全量覆写」原形",
           "持久化当前队列（全量覆写）" in t)


def s8():
    print("== S8 代价不退化（报告要求「同量级」）==")
    root = _root()
    q = CV.ColdVerifyQueue(root=root)
    n = 300
    ts = []
    for i in range(n):
        t0 = time.perf_counter()
        q.enqueue("n%d" % i, action="reverify")
        ts.append((time.perf_counter() - t0) * 1000.0)
    med = statistics.median(ts)
    first = statistics.median(ts[:50])
    last = statistics.median(ts[-50:])
    print("       中位=%.3fms 首50=%.3fms 末50=%.3fms（改前实测中位 0.407ms）"
          % (med, first, last))
    _check("S8a 入队中位 < 5ms/次（宽裕上界，防退化）", med < 5.0, med)
    # 追加是 O(1)：末段不得显著慢于首段（全量覆写会随队列增长而变慢）
    _check("S8b 追加是 O(1)：末 50 次 ≤ 首 50 次的 3 倍",
           last <= max(first * 3.0, 1.0), (first, last))


def s9():
    print("== S9 既有语义不破 ==")
    root = _root()
    q = CV.ColdVerifyQueue(root=root)
    q.enqueue("mem_crash_test", action="reverify")
    q2 = CV.ColdVerifyQueue(root=root)
    _check("S9a 崩溃恢复：新实例恢复未处理任务",
           q2.status()["queue_size"] >= 1)
    q2.clear()
    _check("S9b clear() 仍清空队列文件", _tasks(root) == [], _tasks(root))

    # 加载白名单（v15-1）：非法 action 拒收并计 skipped
    root2 = _root()
    with io.open(_qpath(root2), "w", encoding="utf-8") as f:
        f.write(json.dumps({"node_id": "bad", "action": "rm_rf"}) + "\n")
        f.write(json.dumps({"node_id": "good", "action": "reverify"}) + "\n")
    q3 = CV.ColdVerifyQueue(root=root2)
    _check("S9c 加载路径只收合法 action", q3.status()["queue_size"] == 1,
           q3.status()["queue_size"])
    _check("S9d 非法 action 计入 skipped（可审计）",
           q3.status()["stats"]["skipped"] >= 1)

    # #72 的 G2：dry_run 逐字节不动盘
    root3 = _root()
    q4 = CV.ColdVerifyQueue(root=root3)
    q4.enqueue("d1", action="reverify")
    before = io.open(_qpath(root3), "rb").read()
    q4.drain(_NoCG(), dry_run=True)
    after = io.open(_qpath(root3), "rb").read()
    _check("S9e ★ dry_run 前后队列文件**逐字节不变**（#72 G2）",
           before == after)


def s10():
    print("== S10 墓碑：_done 条目加载时跳过 ==")
    root = _root()
    with io.open(_qpath(root), "w", encoding="utf-8") as f:
        f.write(json.dumps({"node_id": "done1", "action": "reverify",
                            "_done": True}) + "\n")
        f.write(json.dumps({"node_id": "live1", "action": "reverify"}) + "\n")
    q = CV.ColdVerifyQueue(root=root)
    _check("S10a _done 条目不恢复", q.status()["queue_size"] == 1,
           q.status()["queue_size"])
    _check("S10b 未消费条目照常恢复",
           [t.get("node_id") for t in q._queue] == ["live1"])


_GROUPS = (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10)


def _run_groups():
    global _OK
    _OK = 0
    _BAD.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                   # noqa: BLE001
            _check("断言组 %s 抛异常：%s" % (g.__name__, exc), False)
            import traceback
            print(traceback.format_exc()[-600:])
    return len(_BAD)


def main():
    n = _run_groups()
    print()
    print("冷路径跨实例守卫：%d 通过，%d 失败" % (_OK, n))
    return 1 if n else 0


_MUTATIONS = (
    ("V1 enqueue 回到全量覆写（本件病象）",
     "            self._append_persisted(task)\n",
     "            self._persist()\n", "S2"),
    ("V2 drain 回到全量覆写（抹掉他实例的条目）",
     "        self._drop_persisted(batch)\n",
     "        with self._lock:\n            self._persist()\n", "S4"),
    ("V3 追加前不补换行（半截行粘连）",
     '                if _ends_mid_line(self._queue_path):\n                    line = "\\n" + line\n',
     "", "S5"),
)


def _reload():
    import importlib
    from md_cg import coldverify as _c
    importlib.reload(_c)
    globals()["CV"] = _c


def _mutate():
    bad = []
    p = os.path.join(_REPO, "md_cg", "coldverify.py")
    with io.open(p, encoding="utf-8", newline="") as f:
        pristine = f.read()
    if "_append_persisted" not in pristine:
        print("  SOURCE-ALREADY-MUTATED：coldverify.py 缺 _append_persisted")
        return 1
    for name, anchor, repl, want in _MUTATIONS:
        with io.open(p, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        try:
            if a_ not in orig:
                print("  ANCHOR-MISS %s" % name)
                bad.append(name)
                continue
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            _reload()
            _run_groups()
            reds = list(_BAD)
            hit = any(x.startswith(want) for x in reds)
            print("  %-4s %-48s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want,
                     "是" if hit else "否"))
            if not hit:
                bad.append(name)
        finally:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)
            with io.open(p, encoding="utf-8", newline="") as f:
                if f.read() != pristine:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
            _reload()
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print()
    print("定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
