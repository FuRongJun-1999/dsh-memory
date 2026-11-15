# -*- coding: utf-8 -*-
"""守卫 · S1 域闸覆盖率前置判据（issue #929 问题2）。

关键事实（2026-11-14 实测）：big_domain 由 MDCG_RETRIEVAL_PIPELINE=1 的写入路径自动填充；
未开启时索引里恒为 0（真实库 0/35,300）。故夹具必须**先关管线写入、再开管线检索**，
否则写入期自动打域会让覆盖率恒为 1，测不出闸门。
"""
from __future__ import annotations
import os, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.mdcos import MdCGOS  # noqa: E402
FAILS = []

def ok(c, n, d=''):
    print(('  PASS ' if c else '  FAIL ') + n + ('' if c else '  ' + str(d)[:170]))
    if not c:
        FAILS.append(n)

def main():
    os.environ.pop('MDCG_RETRIEVAL_PIPELINE', None)
    cg = MdCGOS(tempfile.mkdtemp(prefix='s1_'), actor='t')
    for i in range(10):
        cg.add('x%d' % i, '记忆系统检索架构的说明 %d' % i, layer='knowledge')
    cg.flush()
    cov0 = sum(1 for e in (cg.index.get('nodes') or {}).values() if (e or {}).get('big_domain'))
    ok(cov0 == 0, 'S1a 夹具前置：未开管线时索引无 big_domain', cov0)
    os.environ['MDCG_RETRIEVAL_PIPELINE'] = '1'
    try:
        r, meta = cg.search('记忆系统检索架构', k=5)
        gates = (meta or {}).get('gates') or {}
        s1 = gates.get('s1') or {}
        ok(bool(s1), 'S1b 开管线后 gates.s1 存在', s1)
        ok(s1.get('skipped_reason') == 'big_domain_coverage_low', 'S1c 覆盖率 0 ⇒ 跳过并标注原因', s1)
        _cov = s1.get('coverage')
        ok(_cov is not None and float(_cov) == 0.0, 'S1d 覆盖率读数如实透出', _cov)
        ok(s1.get('dropped') == 0, 'S1e 跳过时 dropped=0（无误杀）', s1)
        os.environ['MDCG_GATE_S1_MIN_COVERAGE'] = '0'
        r2, meta2 = cg.search('记忆系统检索架构', k=5)
        s1b = ((meta2 or {}).get('gates') or {}).get('s1') or {}
        ok('skipped_reason' not in s1b, 'S1f 阈值调低后恢复收敛（可配置不写死）', s1b)
        os.environ.pop('MDCG_GATE_S1_MIN_COVERAGE', None)
    finally:
        os.environ.pop('MDCG_RETRIEVAL_PIPELINE', None)
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
