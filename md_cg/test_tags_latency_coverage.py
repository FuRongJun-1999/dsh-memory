# -*- coding: utf-8 -*-
"""守卫 · 时延与覆盖率（目标③）：优先域必须可观测、不回退成全库慢路。"""
from __future__ import annotations
import os, sys, tempfile, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.mdcos import MdCGOS  # noqa: E402
FAILS = []
def ok(c, n, d=''):
    print(('  PASS ' if c else '  FAIL ') + n + ('' if c else '  ' + str(d)[:160]))
    if not c:
        FAILS.append(n)
def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix='tm_'), actor='t')
    for i in range(300):
        cg.add('g%d' % i, '记忆检索性能基线样本 第 %d 条 说明文字' % i, layer='knowledge',
               tags=['用途:做设计'])
    for i in range(300):
        cg.add('b%d' % i, '记忆检索性能基线样本 第 %d 条 其他文字' % i, layer='knowledge', tags=[])
    cg.flush()
    t0 = time.time(); r_full, m_full = cg.search('记忆检索性能基线', k=20); d_full = time.time() - t0
    os.environ['MDCG_TAGS_MIN_COVERAGE'] = '0'
    try:
        t0 = time.time(); r_pref, m_pref = cg.search('记忆检索性能基线', k=20, tags_any=['用途:做设计']); d_pref = time.time() - t0
    finally:
        os.environ.pop('MDCG_TAGS_MIN_COVERAGE', None)
    ok('tags_coverage' in (m_pref or {}), 'T1 覆盖率可观测（meta.tags_coverage）', m_pref)
    ok((m_pref or {}).get('tags_scope') == 'preferred', 'T2 优先域语义有标注', m_pref)
    ok(d_pref <= d_full * 3 + 0.05, 'T3 优先域不慢于全库（3 倍容差）', (round(d_full, 4), round(d_pref, 4)))
    ok(len(r_full) == len(r_pref) or abs(len(r_full) - len(r_pref)) <= 0,
       'T4 优先域与全库同样拿到 k 条（不漏）', (len(r_full), len(r_pref)))
    ok(d_full < 60 and d_pref < 60, 'T5 时延在阈值内（<60s，回归护栏）', (round(d_full, 3), round(d_pref, 3)))
    print('  实测：全库 %.4fs / 优先域 %.4fs' % (d_full, d_pref))
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0
if __name__ == '__main__':
    sys.exit(main())