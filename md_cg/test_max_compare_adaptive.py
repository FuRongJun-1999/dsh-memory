# -*- coding: utf-8 -*-
"""守卫 · 重复度比对自适应上限（issue #929 问题4）。"""
from __future__ import annotations
import os, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import forgetting  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402
FAILS = []
def ok(c, n, d=''):
    print(('  PASS ' if c else '  FAIL ') + n + ('' if c else '  ' + str(d)[:170]))
    if not c:
        FAILS.append(n)
def main():
    ok(forgetting._adaptive_limit(100) == forgetting.MAX_COMPARE, 'L1 小池 ⇒ 沿用 240', forgetting._adaptive_limit(100))
    ok(forgetting._adaptive_limit(1000) == 1000, 'L2 大池 ⇒ 尽量全比（1000→1000）', forgetting._adaptive_limit(1000))
    ok(forgetting._adaptive_limit(99999) == forgetting.MAX_COMPARE_CAP, 'L3 病态大池 ⇒ 封顶', forgetting._adaptive_limit(99999))
    cg = MdCGOS(tempfile.mkdtemp(prefix='cmp_'), actor='t')
    body = '记忆检索架构说明：同一主题下的近似表述，用于制造同层大量候选'
    for i in range(400):
        cg.add('c%d' % i, body + ' 编号 %d' % i, layer='contextual')
    cg.flush()
    out = forgetting.redundancy(cg, body + ' 新写入的一条', layer='contextual')
    ct = (out or {}).get('candidate_total')
    ok(bool(ct and ct > forgetting.MAX_COMPARE), 'L4 夹具确实造出 >240 的同层池', ct)
    ok(not (out or {}).get('truncated'), 'L5 自适应后不再截断（不漏比；缺键=未截断）', out)
    ok((out or {}).get('compared', 0) > 240, 'L6 比对量确实放大（>240）', (out or {}).get('compared'))
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0
if __name__ == '__main__':
    sys.exit(main())