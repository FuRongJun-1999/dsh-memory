# -*- coding: utf-8 -*-
"""守卫 · 检索标签预筛（目标②）：先收敛候选，再打分；缺省不过滤。"""
from __future__ import annotations
import os, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.mdcos import MdCGOS  # noqa: E402
FAILS = []
def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:150]))
    if not cond:
        FAILS.append(name)
def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix='pf_'), actor='t')
    for i in range(20):
        cg.add('d%d' % i, '记忆检索架构设计的第 %d 条说明' % i, layer='knowledge',
               tags=['用途:做设计'])
    for i in range(20):
        cg.add('o%d' % i, '记忆检索架构设计的第 %d 条杂项' % i, layer='knowledge', tags=['其他'])
    cg.flush()
    full, meta_full = cg.search('记忆检索架构设计', k=10)
    filt, meta_filt = cg.search('记忆检索架构设计', k=10, tags_any=['用途:做设计'])
    ok(len(full) == 10, 'P1 全库检索可达 k', len(full))
    ok(len(filt) >= 1, 'P2 带标签预筛仍有结果（未误杀）', len(filt))
    ids_full = {r[0]['id'] if isinstance(r, tuple) else r['id'] for r in full}
    ids_filt = {r[0]['id'] if isinstance(r, tuple) else r['id'] for r in filt}
    ok(ids_filt.issubset(ids_full), 'P3 预筛结果是全库结果的子集（无凭空多出）', (len(ids_filt), len(ids_full)))
    ok(all(str(i).startswith('d') for i in ids_filt), 'P4 预筛只返回带标签的节点', sorted(ids_filt)[:3])
    sc_full = (meta_full or {}).get('scanned'); sc_filt = (meta_filt or {}).get('scanned')
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0
if __name__ == '__main__':
    sys.exit(main())