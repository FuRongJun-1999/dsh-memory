# -*- coding: utf-8 -*-
"""#812 守卫：`info(full=true)` 的落盘索引计数必须便宜且可缓存，口径必须写明。

issue #812：软删 1987 条后 `node_count` 不降反升（35884→35886）。
根因：`node_count` 是**内存索引**条目数（外部进程删库后本进程不变），且早先没有区分口径的字段。
修法（已在 main）：`node_count_scope="memory_index"` + `index_mtime` + full 面 `index_node_count` / `index_stale`。
本守卫钉住两件事：
  N1 落盘计数按 (mtime,size) 缓存：第二次调用零成本（防 60MB 每次重解析导致 info 超时）；
  N2 缓存对外部改动失效（mtime 变 ⇒ 重新计数，不会给出陈旧数）。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg.mcp_server import _DISK_COUNT_CACHE, _disk_index_count  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 66)
    print("#812 落盘索引计数：可缓存 + 外部改动失效")
    print("=" * 66)
    tmp = tempfile.mkdtemp(prefix="idxcount_")
    p = os.path.join(tmp, "_index.json")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write('{"nodes": {"a": 1, "b": 2}}')
    c1 = _disk_index_count(p)
    ok(c1 == 2, "N1a 计数正确", c1)

    t = time.time()
    for _ in range(50):
        _disk_index_count(p)
    dt = time.time() - t
    ok(dt < 0.2, "N1b 50 次重复调用走缓存（<0.2s）", round(dt, 3))
    ok(p in _DISK_COUNT_CACHE, "N1c 缓存表已写入")

    time.sleep(0.01)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write('{"nodes": {"a": 1}}')
    os.utime(p, None)
    c2 = _disk_index_count(p)
    ok(c2 == 1, "N2 外部改动（条目 2→1）后计数刷新，不给陈旧数", c2)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())