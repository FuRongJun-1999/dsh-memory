# -*- coding: utf-8 -*-
"""守卫 · 理论问法能检索到理论节点（2026-11-17）。

缺口：节点立了却查不到。实测四个理论问法三个落空或命中 doc_* 切片——
因为理论节点只有个位数，而 doc_* 切片几十万级，融合检索会被淹没。

修法：理论名词（智能系统/元认知/协定式/红线/信任…）触发**专用路**：
      收窄到 tags 含「理论真源」的域，域内按「别名×3 + 正文×1」的 bigram 重合度排序，结果**置顶**。
守卫用临时夹具，不依赖真实库。
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
    T = tempfile.mkdtemp(prefix='theoryq_')
    try:
        cg = MdCGOS(T, actor='t')
        cg.add('theory_x', '# 理论甲', layer='knowledge',
               tags=['理论真源', '常驻'], aliases=['元认知怎么产生'], importance=0.5)
        cg.add('theory_y', '# 理论乙', layer='knowledge',
               tags=['理论真源', '常驻'], aliases=['信任怎么算'], importance=0.5)
        cg.add('doc_noise', '# doc 切片：元认知怎么产生的说明', layer='knowledge',
               tags=['doc'], importance=0.9)

        r = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '元认知怎么产生', 'k': 3})
        rows = (r or {}).get('results') or []
        ids = [(x['node'] or {}).get('id') for x in rows]
        meta = (r or {}).get('meta') or {}
        ok(ids and ids[0] == 'theory_x', 'Q1 理论问法命中理论节点并置顶', ids[:3])
        ok(bool(meta.get('theory_route')), 'Q2 meta.theory_route 可审计（域大小 + 用了几条）',
           meta.get('theory_route'))

        r2 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '信任怎么算', 'k': 3})
        ids2 = [(x['node'] or {}).get('id') for x in ((r2 or {}).get('results') or [])]
        ok(ids2 and ids2[0] == 'theory_y', 'Q3 另一条理论问法同样命中', ids2[:3])

        r3 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '帮我改一下这个脚本', 'k': 3})
        meta3 = (r3 or {}).get('meta') or {}
        ok(not meta3.get('theory_route'), 'Q4 非理论问法不触发专用路（不误伤）', meta3.get('theory_route'))
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('理论问法守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())