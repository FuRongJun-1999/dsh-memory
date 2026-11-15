# -*- coding: utf-8 -*-
"""守卫 · 标签预筛的两道安全阀（验证单元复核要求）。"""
from __future__ import annotations
import os, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.mdcos import MdCGOS  # noqa: E402
FAILS = []
def ok(c, n, d=''):
    print(('  PASS ' if c else '  FAIL ') + n + ('' if c else '  ' + str(d)[:150]))
    if not c:
        FAILS.append(n)
def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix='sv_'), actor='t')
    cg.add('t1', '记忆系统检索架构说明', layer='knowledge', tags=['用途:做设计'])
    for i in range(9):
        cg.add('n%d' % i, '记忆系统检索杂项 %d' % i, layer='knowledge', tags=[])
    cg.flush()
    # 覆盖率 = 1/10 = 0.10 < 0.60 ⇒ 应禁止过滤
    res, meta = cg.search('记忆系统检索', k=5, tags_any=['用途:做设计'])
    ok(meta.get('tags_any_disabled') == 'coverage_low', 'S1 覆盖率低 ⇒ 禁止过滤并标注', meta)
    ok(len(res) >= 1 and any((r[0]['id'] if isinstance(r, tuple) else r['id']).startswith('n') for r in res),
       'S2 覆盖率低时未打标签的节点仍可达（不漏召回）')
    os.environ['MDCG_TAGS_MIN_COVERAGE'] = '0'
    try:
        res2, meta2 = cg.search('记忆系统检索', k=5, tags_any=['用途:做设计'])
        ids = {(r[0]['id'] if isinstance(r, tuple) else r['id']) for r in res2}
        ok(ids == {'t1'} or ids <= {'t1'}, 'S3 允许过滤时只返回带标签节点', ids)
        # 真不变量：预筛导致空、但全库非空 ⇒ 必须回退并标注（不是报空）
        res3, meta3 = cg.search('检索杂项', k=5, tags_any=['用途:做设计'])
        ok(meta3.get('fallback') == 'tags_any_empty' or meta3.get('tags_any_disabled'),
           'S4 预筛空且可回退 ⇒ 必须留下回退/禁用标记（不得静默）', meta3)
        ok(len(res3) >= 1, 'S4b 回退后确实拿到结果（未静默报空）', len(res3))
    finally:
        os.environ.pop('MDCG_TAGS_MIN_COVERAGE', None)
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0
if __name__ == '__main__':
    sys.exit(main())