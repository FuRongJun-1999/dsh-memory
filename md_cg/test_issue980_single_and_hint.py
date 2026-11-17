# -*- coding: utf-8 -*-
"""守卫 · issue #980 问题 3/4（2026-11-17 实测复现后修复）。

问题 3：maintain importance 收了 ids 却不生效——想改一个节点，全库重算（实测 3 个全被改）。
问题 4：content_kind 缺省时闸门判「未知内容类型」→ BLINDSPOT，报错不说人话。

  I3a 传 ids ⇒ 只碰这些节点（其余不动）
  I3b 未知 id 如实列出（unknown_ids）
  I4a 不传 content_kind ⇒ 按 text 判，给可照做的中文缺项清单
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
    T = tempfile.mkdtemp(prefix='i980_')
    try:
        cg = MdCGOS(T, actor='t')
        for i in range(3):
            cg.add('n%d' % i, '# 功能名：n%d\n\n正文%d' % (i, i), layer='knowledge', importance=0.9)

        out = mcp_server.call_tool(cg, 'cg', {'op': 'maintain', 'action': 'importance',
                                              'ids': ['n0'], 'apply': True})
        ok((out or {}).get('nodes_scanned') == 1, 'I3a 传 ids 只扫 1 个节点', (out or {}).get('nodes_scanned'))
        after = {k: (cg.get(k) or {}).get('frontmatter', {}).get('importance') for k in ('n0', 'n1', 'n2')}
        ok(after['n1'] == 0.9 and after['n2'] == 0.9, 'I3a2 其它节点没被顺带改', after)

        out2 = mcp_server.call_tool(cg, 'cg', {'op': 'maintain', 'action': 'importance',
                                               'ids': ['no_such'], 'apply': True})
        ok((out2 or {}).get('unknown_ids') == ['no_such'], 'I3b 未知 id 如实列出', (out2 or {}).get('unknown_ids'))

        w = mcp_server.call_tool(cg, 'cg', {'op': 'write', 'content': '只有一行，没有六要素'})
        v = (w or {}).get('verdict') or {}
        ok(v.get('state') == 'REJECT', 'I4a 缺省 content_kind 按 text 判（不再 BLINDSPOT）', v.get('state'))
        ok('功能名' in str((v.get('detail') or {}).get('missing')), 'I4b 缺项清单具体到要素名', v.get('detail'))
        hint = str((w or {}).get('hint') or '')
        ok('六要素' in hint and '补齐' in hint, 'I4c 顶层提示可照做（中文骨架）', hint[:80])
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('issue #980 守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())