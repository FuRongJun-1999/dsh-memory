# -*- coding: utf-8 -*-
"""W3 前提探针：写路径与读路径到底共不共用一把锁。

真源：docs/architecture/灵枢1.0_建设路线_v0.1.md
  §6 R1「阶段分离（吞吐 vs 延迟）| 写路径与读路径拆分（**当前共用一把锁**）」→ 首轮「做」
  §9 W3「写/读路径拆分（R1）| 写入 P95 不受检索长尾影响（同机对照）」

# 功能名：W3 前提探针（读路径是否与写锁共用）
# 生效条件：需要判断 W3 有没有可拆之物、或复核 §6 R1 的前提是否仍成立时
# 子功能：
#   ①`lock`  运行期给 fsutil.FileLock 装计数器，分别统计 seed / search / search_rrf 的取锁次数
#   ②`p95`   写入 P95 对照：空载 vs 跨进程并发检索（读者在独立进程，排除 GIL）
#   ③`width` 同机对照的**对照组**：读者只做纯 CPU 忙等（完全不碰锁），用于区分
#            「锁争用」与「GIL/CPU 争用」——只测②不做③会得出错误结论
# 执行：python -X utf8 scripts/probe_w3_read_write_lock.py [--mode lock|p95|all] [--writes N]
# 验证方式：--mode p95 会 fail-closed——窗口内实测检索次数 < 5 即判实验无效，不输出结论
# 不适用条件：不判 KPI 语义；不测吞吐上限；不覆盖多机/容器环境；
#             不替代 KPI 门禁（见 scripts/gate_four_kpi.py）

为什么必须做对照组（width）
    首版本探针只测了「线程内并发检索」→ 写入 P95 放大 43.78x，看起来就是锁争用。
    但把读者换成**纯 CPU 忙等（一行 md_cg 代码都不碰）**，放大到 838.05x。
    一个不取任何锁的对照组比实验组慢 19 倍，说明 43.78x 主要来自 CPython GIL 争用，
    而不是锁。把读者挪到独立进程后放大降到 1.05–1.18x，确证了这一点。
    这类「对照组反而更差」的读数，是本仓已记录过的「自证恒绿」同族事故的反面：
    不做对照就会把一个错误前提写进路线稿，并据此排一个没有交付物的 W3。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

QUERIES = [
    "灵枢记忆内核 并发加锁",
    "写读路径拆分与 P95 延迟",
    "回滚覆盖正文 前像 逐字节",
    "审计台账 不丢账 排他锁",
    "四契约 Write Read Govern SelfCheck",
]

READER_SRC = r'''
# -*- coding: utf-8 -*-
"""子进程读者：每 25 次检索追加一行「时间戳 累计次数」，供主进程按时间窗切片取证。"""
import json, os, sys, time
sys.path.insert(0, r"%REPO%")
from md_cg.mdcos import MdCGOS

root, stopfile, progfile = r"%ROOT%", r"%STOP%", r"%PROG%"
mode = r"%MODE%"
queries = json.loads(r"""%QUERIES%""")


def burn(q):
    """纯 CPU 忙等：不碰 md_cg 任何代码，用作「无锁对照组」。"""
    h = 0
    for ch in (q * 400):
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return h


cg = None if mode == "width" else MdCGOS(root)
n = 0
try:
    while not os.path.exists(stopfile):
        for q in queries:
            if os.path.exists(stopfile):
                break
            if mode == "width":
                burn(q)
            else:
                try:
                    cg.search_rrf(q, k=20)
                except Exception:
                    pass
            n += 1
            if n % 25 == 0:
                with open(progfile, "a", encoding="utf-8") as f:
                    f.write("%.4f %d\n" % (time.time(), n))
                    f.flush()
                    os.fsync(f.fileno())
finally:
    with open(progfile, "a", encoding="utf-8") as f:
        f.write("%.4f %d\n" % (time.time(), n))
        f.flush()
        os.fsync(f.fileno())
    if cg is not None:
        try:
            cg.close()
        except Exception:
            pass
'''


def _p95(xs):
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[max(0, min(len(s) - 1, int(round(0.95 * (len(s) - 1)))))]


def _sandbox(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    os.environ["MDCG_AUX_ROOT"] = d
    os.environ["MDCG_ROOT"] = os.path.join(d, "root")
    os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
    os.environ.pop("MDCG_TEST_LIVE_ROOT", None)
    os.makedirs(os.path.join(d, "root"), exist_ok=True)
    return d, os.path.join(d, "root")


def _seed(cg, n):
    for i in range(n):
        cg.add("seed%03d" % i,
               "第%d号语料：灵枢记忆内核的检索引擎与并发加锁写读路径拆分回滚审计台账四契约。" % i,
               provenance={"src": "probe"}, verification_basis="data")
    cg.flush()


# ---------------------------------------------------------------- mode: lock
def mode_lock(seed_n=120):
    """运行期锁计数：读路径取了多少把 FileLock。"""
    from md_cg import fsutil

    sb, root = _sandbox("w3lock_")
    try:
        from md_cg.mdcos import MdCGOS

        stats = {"n": 0, "phase": "setup", "by_phase": []}
        orig_enter = fsutil.FileLock.__enter__

        def counting_enter(self):
            r = orig_enter(self)
            stats["n"] += 1
            return r

        fsutil.FileLock.__enter__ = counting_enter
        try:
            cg = MdCGOS(root)
            _seed(cg, seed_n)

            def mark(name):
                stats["by_phase"].append((name, stats["n"]))
                stats["phase"] = name

            mark("seed")
            for q in QUERIES:
                cg.search(q, k=5)
            mark("search")
            for q in QUERIES:
                try:
                    cg.search_rrf(q, k=5)
                except Exception:                       # noqa: BLE001
                    pass
            mark("search_rrf")
            cg.close()
        finally:
            fsutil.FileLock.__enter__ = orig_enter

        rows = stats["by_phase"]
        cur = 0
        print("=" * 78)
        print("读路径锁计数（运行期实测，沙箱库根）")
        print("=" * 78)
        for name, total in rows:
            print("  %-14s 累计取锁 %4d   （本阶段 +%d）" % (name, total, total - cur))
            cur = total
        seed_locks = rows[0][1] if rows else 0
        search_locks = (rows[1][1] - rows[0][1]) if len(rows) > 1 else 0
        rrf_locks = (rows[2][1] - rows[1][1]) if len(rows) > 2 else 0
        print()
        print("  建库 %d 节点取锁      : %d" % (seed_n, seed_locks))
        print("  search   ×%d 取锁     : %d" % (len(QUERIES), search_locks))
        print("  search_rrf ×%d 取锁   : %d" % (len(QUERIES), rrf_locks))
        print()
        print("  ⇒ 读路径取锁数：%d" % (search_locks + rrf_locks))
        return 0
    finally:
        shutil.rmtree(sb, ignore_errors=True)


# ----------------------------------------------------------- mode: p95/width
def _read_prog(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        a, b = line.split()
        rows.append((float(a), int(b)))
    return rows


def _ops_in_window(rows, t0, t1):
    if len(rows) < 2:
        return 0.0
    total = 0.0
    for (ta, na), (tb, nb) in zip(rows, rows[1:]):
        dn = nb - na
        if dn <= 0 or tb <= ta:
            continue
        lo, hi = max(ta, t0), min(tb, t1)
        if hi > lo:
            total += dn * (hi - lo) / (tb - ta)
    return total


def mode_p95(writes=300, seed_n=120, reader_mode="search", timeout_s=180):
    """写入 P95 对照：空载 vs 跨进程并发（读者在独立进程）。

    reader_mode="search" → 读者真检索（实验组）
    reader_mode="width"  → 读者纯 CPU 忙等，不碰锁（对照组）
    """
    from md_cg.mdcos import MdCGOS

    sb, root = _sandbox("w3p95_")
    try:
        cg = MdCGOS(root)
        _seed(cg, seed_n)

        def measure(tag, n):
            lat = []
            for i in range(n):
                t0 = time.perf_counter()
                cg.add("%s%03d" % (tag, i),
                       "%s 写入样本 %d：并发加锁与检索长尾对照。" % (tag, i),
                       provenance={"src": "probe"}, verification_basis="data")
                lat.append((time.perf_counter() - t0) * 1000.0)
            return lat

        base = measure("base", writes)
        cg.flush()

        stopf = os.path.join(sb, "STOP")
        prog = os.path.join(sb, "PROGRESS")
        sp = os.path.join(sb, "_reader.py")
        with open(sp, "w", encoding="utf-8") as f:
            f.write(READER_SRC.replace("%REPO%", REPO).replace("%ROOT%", root)
                    .replace("%STOP%", stopf).replace("%PROG%", prog)
                    .replace("%MODE%", reader_mode)
                    .replace("%QUERIES%", json.dumps(QUERIES)))

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        proc = subprocess.Popen([sys.executable, "-X", "utf8", sp],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=sb, env=env)

        # 等读者真正产出，避免空窗测量（fail-closed）
        t_wait = time.time()
        while time.time() - t_wait < 30 and not _read_prog(prog):
            time.sleep(0.1)
        if not _read_prog(prog):
            print("!! 读者 30s 内无任何进展 —— 实验无效，不出结论")
            try:
                open(stopf, "w").close()
            except OSError:
                pass
            proc.kill()
            proc.communicate()
            return 2

        t0 = time.time()
        conc = measure("conc", writes)
        t1 = time.time()
        cg.flush()

        open(stopf, "w").close()
        try:
            _out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            _out, err = proc.communicate()

        rows = _read_prog(prog)
        in_win = _ops_in_window(rows, t0, t1)

        label = "并发检索（子进程）" if reader_mode == "search" else "并发纯CPU忙等（子进程·不碰锁）"
        print("=" * 84)
        print("写入 P95 对照 —— 读者在独立进程（无共享 GIL）")
        print("=" * 84)
        print("  %-34s %5s %9s %9s %9s %9s" % ("场景", "n", "均值", "中位", "P95", "最大"))
        for name, xs in (("空载写入（主进程）", base), (label + "下写入", conc)):
            print("  %-34s %5d %9.2f %9.2f %9.2f %9.2f"
                  % (name, len(xs), statistics.mean(xs), statistics.median(xs), _p95(xs), max(xs)))
        print()
        print("  读者总操作次数          ：%d" % (rows[-1][1] if rows else 0))
        print("  测量窗口长度            ：%.2f s" % (t1 - t0))
        print("  窗口内实操次数（估算）    ：%.0f" % in_win)
        print()

        if in_win < 5:
            print("  ✗ 窗口内实操 %.0f < 5 —— 实验无效（读者没真正并发），不出结论" % in_win)
            return 2

        ratio = _p95(conc) / _p95(base) if _p95(base) else float("inf")
        print("  P95 放大倍数：%.2fx" % ratio)
        print()
        if reader_mode == "search":
            if ratio < 1.5:
                print("  ⇒ 读路径与写锁**不共用**：排除 GIL 后写入 P95 基本不变（%.2fx）。" % ratio)
                print("     路线稿 §6 R1「当前共用一把锁」前提不成立，W3 按原判据无可拆之物。")
            else:
                print("  ⇒ 写入 P95 被放大 %.2fx，确为资源争用，W3 前提成立。" % ratio)
        else:
            print("  ⇒ 对照组读数 %.2fx（对照组完全不取锁）。" % ratio)
            print("     若对照组放大远大于 search 组，说明测量主要反映 GIL/CPU 争用而非锁。")

        if err:
            tail = err.decode("utf-8", "replace").strip().splitlines()[-3:]
            if tail:
                print()
                print("  [读者 stderr]")
                for t in tail:
                    print("    " + t)

        cg.close()
        return 0
    finally:
        shutil.rmtree(sb, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("lock", "p95", "width", "all"), default="all")
    ap.add_argument("--writes", type=int, default=300)
    ap.add_argument("--seed", type=int, default=120)
    a = ap.parse_args(argv)

    if a.mode in ("lock", "all"):
        mode_lock(seed_n=a.seed)
        print()
    if a.mode in ("p95", "all"):
        rc = mode_p95(writes=a.writes, seed_n=a.seed, reader_mode="search")
        if rc != 0:
            return rc
        print()
    if a.mode in ("width", "all"):
        rc = mode_p95(writes=a.writes, seed_n=a.seed, reader_mode="width")
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
