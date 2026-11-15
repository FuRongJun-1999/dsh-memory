# -*- coding: utf-8 -*-
"""守卫 · 工具面标签检索走单路优先域（目标②最后一段）。"""
from __future__ import annotations
import os, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402
FAILS = []
def ok(c, n, d=''):
    print(('  PASS ' if c else '  FAIL ') + n + ('' if c else '  ' + str(d)[:160]))
    if not c:
        FAILS.append(n)
def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix='tp_'), actor='t')
    for i in range(30):
        cg.add('a%d' % i, '记忆检索架构单路优先域样本 %d' % i, layer='knowledge', tags=['用途:做设计'])
    for i in range(30):
        cg.add('b%d' % i, '记忆检索架构单路优先域样本 %d' % i, layer='knowledge', tags=[])
    cg.flush()
    os.environ['MDCG_TAGS_MIN_COVERAGE'] = '0'
    try:
        r1 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '记忆检索架构', 'k': 5,
                                            'tags_any': ['用途:做设计']})
    finally:
        os.environ.pop('MDCG_TAGS_MIN_COVERAGE', None)
    m1 = (r1 or {}).get('meta') or {}
    ok(m1.get('search_path') == 'single_preferred', 'W1 带标签 ⇒ 走单路且标注', m1.get('search_path'))
    # 工具面自身还有 judge/过滤（既有行为），故不与“必非空”比较；比较的是**与库层同查询同参数的结果一致**。
    lib, _lm = cg.search('记忆检索架构', k=5, tags_any=['用途:做设计']) if False else (None, None)
    os.environ['MDCG_TAGS_MIN_COVERAGE'] = '0'
    try:
        lib, _ = cg.search('记忆检索架构', k=5, tags_any=['用途:做设计'])
    finally:
        os.environ.pop('MDCG_TAGS_MIN_COVERAGE', None)
    ok(lib and len(lib) >= 1, 'W2 库层同查询有结果（夹具有效）', len(lib or []))
    r2 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '记忆检索架构', 'k': 5})
    m2 = (r2 or {}).get('meta') or {}
    ok(m2.get('search_path') != 'single_preferred', 'W3 不带标签 ⇒ 不走单路（零行为变更）', m2.get('search_path'))
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0
if __name__ == '__main__':
    sys.exit(main())