# -*- coding: utf-8 -*-
"""FileLock 跨进程互斥性验证（不猜，直接测）。

N 个进程各做 M 次「锁内 读-加一-写」。若锁真互斥，最终值必然 == N*M。
"""
import os
import sys
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.fsutil import FileLock, atomic_write

# 落点改**系统临时目录 + PID 唯一化**（2026-10-05 复核建议 6）：原落包目录
# `md_cg/_locktest.txt`——并发跑测试/共享仓库检出（copytree、CI 并行）时
# 瞬态文件被无余量扫描撞上（复核两次实测 WinError 2），且不被 .gitignore
# 覆盖易误提交。路径在**父进程**唯一化后经 argv 传给 worker 子进程——
# 子进程是独立 PID，必须显式继承同一路径（v1 初改曾按 PID 各自计算 ⇒
# 父子读不同文件、计数归零的实测教训）。判据不变：N 进程对同一文件加锁。
TARGET = os.path.join(tempfile.gettempdir(),
                      "mdcg_locktest_%d.txt" % os.getpid())


def worker(m, target):
    for _ in range(m):
        with FileLock(target) as lk:
            if not lk.acquired:
                print("LOCK_TIMEOUT", file=sys.stderr)
            try:
                with open(target, encoding="utf-8") as f:
                    v = int(f.read().strip() or 0)
            except (OSError, ValueError):
                v = 0
            atomic_write(target, str(v + 1))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(int(sys.argv[2]), sys.argv[3])
        sys.exit(0)
    N, M = 6, 50
    atomic_write(TARGET, "0")
    ps = [subprocess.Popen([sys.executable, os.path.abspath(__file__), "--worker",
                            str(M), TARGET])
          for _ in range(N)]
    [p.wait() for p in ps]
    with open(TARGET, encoding="utf-8") as f:
        got = int(f.read().strip())
    print(f"期望 {N*M}，实际 {got} → {'互斥正常' if got == N*M else '★锁失效，丢了 %d 次' % (N*M-got)}")
    os.remove(TARGET)
    if os.path.exists(TARGET + ".lock"):
        os.remove(TARGET + ".lock")
