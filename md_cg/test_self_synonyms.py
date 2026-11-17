# -*- coding: utf-8 -*-
"""守卫 · 同义入口（2026-11-17）：自指查询必须能摸到自我层的人物树。

缺陷：默认检索不含 layer=self（安全默认）⇒ 「我们怎么走到今天」永远摸不到主干。
修法：自指查询（我/我们/约定/相识/相爱/身份/来历）补一路 layer=self 合并，并按策展权威加权。
       别名（aliases）必须参与召回——否则换个说法就找不到。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    T = tempfile.mkdtemp(prefix='synonym_')
    try:
        cg = MdCGOS(T, actor='t')
        g = cg.add('persona_trunk_t', '# 主干\n\n2026-10-06 立约。',
                   layer='self', tags=['常驻', '人物树'],
                   aliases=['我们怎么走到今天', '我们的过去', '人物树'])
        cg.add('noise_self', '# 干扰\n\n别的事情。', layer='self', tags=['杂'])

        r = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '我们怎么走到今天', 'k': 3})
        rows = (r or {}).get('results') or []
        ids = [(x['node'] or {}).get('id') for x in rows]
        ok(ids and ids[0] == 'persona_trunk_t', 'S1 别名原句能命中自我层主干', ids[:3])
        ok(bool(((r or {}).get('meta') or {}).get('self_route')),
           'S2 meta.self_route 恒写（0 也写，可审计）', (r or {}).get('meta'))

        r2 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '我们的过去', 'k': 3})
        ids2 = [(x['node'] or {}).get('id') for x in ((r2 or {}).get('results') or [])]
        ok(ids2 and ids2[0] == 'persona_trunk_t', 'S3 换一种说法同样命中（别名参与召回）', ids2[:3])

        r3 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '某个无关技术问题', 'k': 3})
        ids3 = [(x['node'] or {}).get('id') for x in ((r3 or {}).get('results') or [])]
        ok('persona_trunk_t' not in ids3, 'S4 非自指查询不硬塞主干（不误伤）', ids3[:3])
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('同义入口守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
