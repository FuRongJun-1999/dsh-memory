# -*- coding: utf-8 -*-
"""守卫 · 热层增量复用正确性（目标①）：复用不得改变结果。"""
from __future__ import annotations
import os, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import hottier  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402
FAILS = []
def ok(c, n, d=''):
    print(('  PASS ' if c else '  FAIL ') + n + ('' if c else '  ' + str(d)[:160]))
    if not c:
        FAILS.append(n)
def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix='incg_'), actor='t')
    for i in range(120):
        cg.add('i%d' % i, '增量正确性样本 %d 记忆检索文字' % i, layer='knowledge', importance=0.8)
    cg.flush()
    hottier.build(cg)
    a = hottier.load(cg.root)['nodes']
    hottier.build(cg)                      # 走增量复用路径
    b = hottier.load(cg.root)['nodes']
    ok(set(a) == set(b), 'I1 增量后节点集合一致', (len(a), len(b)))
    same = all((a[k].get('preview') == b[k].get('preview')) and (a[k].get('layer') == b[k].get('layer')) for k in a)
    ok(same, 'I2 增量后每条 preview/layer 与全量一致（复用不改变结果）')
    cg.add('i0', '增量正确性样本 0 记忆检索文字【已改动】', layer='knowledge', importance=0.8)
    cg.flush()
    hottier.build(cg)
    c = hottier.load(cg.root)['nodes']
    ok('已改动' in str(c['i0'].get('preview')), 'I3 内容变化 ⇒ 复用失效并更新 preview', c['i0'].get('preview'))
    ok('已改动' not in str(c['i1'].get('preview')), 'I4 未变节点仍复用旧内容（未被串改）')
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0
if __name__ == '__main__':
    sys.exit(main())