# -*- coding: utf-8 -*-
"""守卫 · 批量面前的条件重建（issue #980 问题 2 收尾，2026-11-17）。

反思单元结论（已实测确认三条前提）：
  ① 判据必须 ttl=0（5 分钟缓存等于没测）——真实库扫描约 1.2s；
  ② 内存有未落盘写时不得重建（否则重建与 async flush 互相覆盖，形成正反馈）；
  ③ 只在 apply/写盘批次入口做，预演与单节点不付这个代价。

  F1 干净库：不重建（rebuilt=False）
  F2 手改文件后（超容差）：重建并生效（rebuilt=True）
  F3 pending_dirty>0：跳重建并给出原因（不制造正反馈）
"""
import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import freshness  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    T = tempfile.mkdtemp(prefix='batchfresh_')
    try:
        cg = MdCGOS(T, actor='t')
        cg.add('n0', '# 功能名：n0\n\n正文', layer='contextual', importance=0.5)
        cg.rebuild_index()
        freshness._DATA_STAMP['at'] = 0.0
        r1 = cg.ensure_index_fresh_for_batch(reason='t1')
        ok(r1['rebuilt'] is False, 'F1 干净库不重建', r1)

        path = None
        for dp, _, fs in os.walk(T):
            if 'n0.md' in fs:
                path = os.path.join(dp, 'n0.md')
        time.sleep(6.0)
        io.open(path, 'w', encoding='utf-8', newline='').write(
            io.open(path, encoding='utf-8').read() + chr(10) + '手改')
        freshness._DATA_STAMP['at'] = 0.0
        r2 = cg.ensure_index_fresh_for_batch(reason='t2')
        ok(r2['rebuilt'] is True, 'F2 手改后触发重建', r2)

        class _Stub:
            pass
        orig = cg.flush_state
        cg.flush_state = lambda: {'pending_dirty': 3, 'async': True}
        try:
            freshness._DATA_STAMP['at'] = 0.0
            time.sleep(6.0)
            io.open(path, 'w', encoding='utf-8', newline='').write(
                io.open(path, encoding='utf-8').read() + chr(10) + '再改')
            freshness._DATA_STAMP['at'] = 0.0
            r3 = cg.ensure_index_fresh_for_batch(reason='t3')
            ok(r3['rebuilt'] is False and 'pending_dirty' in str(r3.get('skipped', '')),
               'F3 有未落盘写时跳重建并说明原因', r3)
        finally:
            cg.flush_state = orig
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('批量重建守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())