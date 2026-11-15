# -*- coding: utf-8 -*-
"""守卫 · 项目/用途接进检索路由（issue #929 问题5）。"""
from __future__ import annotations
import os, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402
FAILS = []
def ok(c, n, d=''):
    print(('  PASS ' if c else '  FAIL ') + n + ('' if c else '  ' + str(d)[:170]))
    if not c:
        FAILS.append(n)
def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix='pp_'), actor='t')
    for i in range(20):
        cg.add('p%d' % i, '天元项目服务端容量压测结论 %d' % i, layer='knowledge',
               tags=['项目:天元45', '用途:修缺陷'])
    for i in range(20):
        cg.add('q%d' % i, '天元项目服务端容量压测结论 %d' % i, layer='knowledge',
               tags=['项目:其他', '用途:做设计'])
    cg.flush()
    os.environ['MDCG_TAGS_MIN_COVERAGE'] = '0'
    try:
        r1 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '容量压测', 'k': 5, 'project': '天元45'})
        r2 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '容量压测', 'k': 5, 'purpose': '做设计'})
    finally:
        os.environ.pop('MDCG_TAGS_MIN_COVERAGE', None)
    m1 = (r1 or {}).get('meta') or {}
    ok(m1.get('search_path') == 'single_preferred', 'P1 project 参数走标签优先域（路由生效）', m1.get('search_path'))
    # 注：工具面自身还有 judge 等既有过滤（与本改动无关）⇒ 用**库层同标签对拍**验证映射语义
    lib1, _ = cg.search('容量压测', k=5, tags_any=['项目:天元45'])
    ids1 = [str((it[0] if isinstance(it, tuple) else it).get('id')) for it in (lib1 or [])]
    ok(bool(ids1) and all(i.startswith('p') for i in ids1), 'P2 项目标签只命中该项目节点', ids1[:5])
    lib2, _ = cg.search('容量压测', k=5, tags_any=['用途:做设计'])
    ids2 = [str((it[0] if isinstance(it, tuple) else it).get('id')) for it in (lib2 or [])]
    ok(bool(ids2) and all(i.startswith('q') for i in ids2), 'P3 用途标签只命中该用途节点', ids2[:5])
    r3 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '容量压测', 'k': 5})
    ok(((r3 or {}).get('meta') or {}).get('search_path') != 'single_preferred',
       'P4 不传 project/purpose ⇒ 不走优先域（零行为变更）')
    # P5/P6：工具面端到端（复核意见：库层对拍不证明参数解析→路由组装→响应序列化）
    ok((m1 or {}).get('tags_scope') == 'preferred', 'P5 工具面响应里带 tags_scope=preferred（标签确实装配到检索）', m1.get('tags_scope'))
    ok('tags_coverage' in (m1 or {}), 'P6 工具面响应里带 tags_coverage（覆盖率读数随响应透出）', list((m1 or {}).keys())[:6])
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0
if __name__ == '__main__':
    sys.exit(main())