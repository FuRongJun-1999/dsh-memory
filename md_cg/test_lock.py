# -*- coding: utf-8 -*-
"""FileLock 跨进程互斥性验证（不猜，直接测）。

N 个进程各做 M 次「锁内 读-加一-写」。若锁真互斥，最终值必然 == N*M。
"""
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.fsutil import FileLock, atomic_write

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_locktest.txt")


def worker(m):
    for _ in range(m):
        with FileLock(TARGET) as lk:
            if not lk.acquired:
                print("LOCK_TIMEOUT", file=sys.stderr)
            try:
                with open(TARGET) as f:
                    v = int(f.read().strip() or 0)
            except (OSError, ValueError):
                v = 0
            atomic_write(TARGET, str(v + 1))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(int(sys.argv[2]))
        sys.exit(0)
    N, M = 6, 50
    atomic_write(TARGET, "0")
    ps = [subprocess.Popen([sys.executable, os.path.abspath(__file__), "--worker", str(M)])
          for _ in range(N)]
    [p.wait() for p in ps]
    with open(TARGET) as f:
        got = int(f.read().strip())
    print(f"期望 {N*M}，实际 {got} → {'互斥正常' if got == N*M else '★锁失效，丢了 %d 次' % (N*M-got)}")
    os.remove(TARGET)
    if os.path.exists(TARGET + ".lock"):
        os.remove(TARGET + ".lock")
