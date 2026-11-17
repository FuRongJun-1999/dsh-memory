# -*- coding: utf-8 -*-
"""守卫 · 理论问法快速通道（2026-11-17 实测 130s → 0.02s）。

理论域只有个位数节点，主库全扫一次要 20–30 秒（k 放大后更久）。
故理论问法若在域内命中（top 分 ≥ 0.5），**直接返回**，不再付全扫代价。

  F1 域内命中 ⇒ 走快通道（meta.theory_route.fast_path = true）
  F2 快通道结果排第一就是理论节点
  F3 域内未命中 ⇒ 不冒充快通道（回落主路径）
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    T = tempfile.mkdtemp(prefix='fastpath_')
    try:
        cg = MdCGOS(T, actor='t')
        cg.add('theory_f', '# 理论甲\n\n元认知三阶段：结构位置、递归压力、存在约束。',
               layer='knowledge', tags=['理论真源', '常驻'], aliases=['元认知怎么产生'])
        cg.add('noise_f', '# 干扰\n\n别的。', layer='knowledge', tags=['杂'])

        t0 = time.time()
        r = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '元认知怎么产生', 'k': 3})
        dt = time.time() - t0
        meta = (r or {}).get('meta') or {}
        rows = (r or {}).get('results') or []
        ok(bool((meta.get('theory_route') or {}).get('fast_path')), 'F1 域内命中走快通道', meta.get('theory_route'))
        ok(rows and (rows[0]['node'] or {}).get('id') == 'theory_f', 'F2 第一名是理论节点',
           [(x['node'] or {}).get('id') for x in rows][:3])
        ok(dt < 1.0, 'F2b 快通道耗时 < 1s（实测 0.02s）', round(dt, 3))

        r2 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '信任怎么算', 'k': 3})
        meta2 = (r2 or {}).get('meta') or {}
        ok(not (meta2.get('theory_route') or {}).get('fast_path'), 'F3 触发词命中但域内无对应节点 ⇒ 不冒充快通道',
           meta2.get('theory_route'))
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('理论快通道守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())