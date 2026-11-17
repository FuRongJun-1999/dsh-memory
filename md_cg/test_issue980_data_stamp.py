# -*- coding: utf-8 -*-
"""守卫 · 数据面水位与索引陈旧检测（issue #980 问题 2 收尾）。

`stale_on_disk` 只比**代码代际**；数据文件被外部改动时它恒 False。
本守卫钉住新的数据面读数：`info.data_stale` / `info.data_stamp`，以及 TTL 缓存。

  S1 手改 .md 后 data_stale=True（且给出 files/newest/index mtime）
  S2 未改动时为 False
  S3 TTL 内复用（不重复全库扫描）
"""
import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import freshness, mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    T = tempfile.mkdtemp(prefix='datanew_')
    try:
        cg = MdCGOS(T, actor='t')
        cg.add('n0', '# 功能名：n0\n\n正文', layer='knowledge', importance=0.5)
        cg.rebuild_index()   # 索引落盘：只有索引存在，才有「索引 vs 磁盘」的老化可比
        time.sleep(0.2)
        freshness._DATA_STAMP['at'] = 0.0
        info0 = mcp_server.call_tool(cg, 'cg', {'op': 'info'})
        ok(info0.get('data_stale') is False, 'S2 未改动 ⇒ data_stale=False', info0.get('data_stale'))

        path = None
        for dp, _, fs in os.walk(T):
            if 'n0.md' in fs:
                path = os.path.join(dp, 'n0.md')
        time.sleep(6.0)   # 超过 5s 容差（容差是给异步 flush 留的窗口）
        txt = io.open(path, encoding='utf-8').read() + chr(10) + '手改'
        io.open(path, 'w', encoding='utf-8', newline='').write(txt)
        freshness._DATA_STAMP['at'] = 0.0
        info1 = mcp_server.call_tool(cg, 'cg', {'op': 'info'})
        ok(info1.get('data_stale') is True, 'S1 手改后 data_stale=True', info1.get('data_stale'))
        ds = info1.get('data_stamp') or {}
        ok(ds.get('files') == 1 and ds.get('newest_mtime', 0) > ds.get('index_mtime', 0),
           'S1b 给出文件数/最新 mtime/索引 mtime', ds)
        ok('data_hint' in info1, 'S1c 陈旧时给可执行提示', list(info1.keys())[-3:])

        t0 = time.time()
        freshness.data_stamp(T)
        dt = time.time() - t0
        ok(dt < 0.05, 'S3 TTL 内直接复用缓存（未重扫）', round(dt, 4))
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('数据面水位守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())