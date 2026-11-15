# -*- coding: utf-8 -*-
"""守卫 · S1 域闸覆盖率前置判据（issue #929 问题2）。

夹具策略（复核意见：不要依赖 MDCG_RETRIEVAL_PIPELINE 的开关顺序）——
直接往索引条目里注入 big_domain，把「闸判据」与「写路径填充」解耦，
并按覆盖率参数化（0 / 0.5 / 0.6 / 1.0）。
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

def _fixture(n_total, n_domain):
    os.environ.pop('MDCG_RETRIEVAL_PIPELINE', None)
    cg = MdCGOS(tempfile.mkdtemp(prefix='s1_'), actor='t')
    for i in range(n_total):
        cg.add('x%d' % i, '记忆系统检索架构的说明 %d' % i, layer='knowledge')
    cg.flush()
    nodes = cg.index.get('nodes') or {}
    for i, (nid, ent) in enumerate(sorted(nodes.items())):
        if i < n_domain and isinstance(ent, dict):
            ent['big_domain'] = '计算机'
    return cg

def _run(cg, min_cov=None):
    os.environ['MDCG_RETRIEVAL_PIPELINE'] = '1'
    if min_cov is not None:
        os.environ['MDCG_GATE_S1_MIN_COVERAGE'] = str(min_cov)
    try:
        r, meta = cg.search('记忆系统检索架构', k=5)
        return ((meta or {}).get('gates') or {}).get('s1') or {}
    finally:
        os.environ.pop('MDCG_RETRIEVAL_PIPELINE', None)
        os.environ.pop('MDCG_GATE_S1_MIN_COVERAGE', None)

def main():
    s1 = _run(_fixture(10, 0))
    ok(s1.get('skipped_reason') == 'big_domain_coverage_low', 'S1a 覆盖率 0 ⇒ 跳过并标注', s1)
    ok(s1.get('coverage') == 0.0, 'S1b 覆盖率读数透出 0.0', s1.get('coverage'))

    s2 = _run(_fixture(10, 5))
    ok(s2.get('skipped_reason') == 'big_domain_coverage_low', 'S1c 覆盖率 0.5 < 0.6 ⇒ 跳过', s2)

    s3 = _run(_fixture(10, 6))
    ok('skipped_reason' not in s3, 'S1d 覆盖率 0.6 ⇒ 正常收敛（边界）', s3)

    s4 = _run(_fixture(10, 10))
    ok('skipped_reason' not in s4, 'S1e 覆盖率 1.0 ⇒ 正常收敛', s4)

    s5 = _run(_fixture(10, 0), min_cov=0)
    ok('skipped_reason' not in s5, 'S1f 阈值置 0 ⇒ 恢复收敛（明确回退方式）', s5)

    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0

if __name__ == '__main__':
    sys.exit(main())
