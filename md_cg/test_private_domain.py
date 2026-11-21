# -*- coding: utf-8 -*-
"""守卫 · 私密域隔离（域:私密 默认不进检索面）。

# 功能名：test_private_domain —— 私密域默认剔除、显式放行、两种结果形状都认
# 生效条件：改动 drop_private_domain / _final_out 后
# 子功能：
#   ① 命中标签 → 剔除，普通条保留
#   ② MDCG_INCLUDE_PRIVATE=1 与 enabled=False 两条放行通道
#   ③ read 的 results 形状（标签在 node.frontmatter）与 pack 形状（标签直挂）都判得中
#   ④ meta 记 private_domain_excluded，不静默
# 执行：python -X utf8 -m md_cg.test_private_domain
# 验证方式：每条断言配反向对照（该删的删、该留的留）
# 不适用条件：只验过滤判据；不验真实跨端可见性（那是部署面）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server as M  # noqa: E402

PASS, FAIL = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:150]))
    (PASS if cond else FAIL).append(name)


def tags_of(it):
    if isinstance(it, dict) and isinstance(it.get('node'), dict):
        it = it['node']
    fm = (it or {}).get('frontmatter') or {}
    return fm.get('tags') or (it or {}).get('tags') or ()


def main():
    print('=== 私密域隔离守卫 ===')
    saved = os.environ.pop('MDCG_INCLUDE_PRIVATE', None)
    try:
        items = [{'id': 'a', 'tags': ['普通']},
                 {'id': 'b', 'tags': [M.PRIVATE_DOMAIN_TAG]},
                 {'id': 'c', 'tags': []}]
        keep, dropped = M.drop_private_domain(items, tags_of)
        ok([x['id'] for x in keep] == ['a', 'c'] and dropped == 1, '① 私密条被剔除', keep)

        os.environ['MDCG_INCLUDE_PRIVATE'] = '1'
        keep2, d2 = M.drop_private_domain(items, tags_of)
        ok(len(keep2) == 3 and d2 == 0, '② env 放行生效', keep2)
        os.environ.pop('MDCG_INCLUDE_PRIVATE', None)

        keep3, d3 = M.drop_private_domain(items, tags_of, enabled=False)
        ok(len(keep3) == 3 and d3 == 0, '② enabled=False 放行', keep3)

        results = [{'node': {'id': 'x', 'frontmatter': {'tags': [M.PRIVATE_DOMAIN_TAG]}}, 'score': 1},
                   {'node': {'id': 'y', 'frontmatter': {'tags': ['普通']}}, 'score': 1}]
        out = M._final_out({'meta': {}, 'results': results}, None, {})
        ok([r['node']['id'] for r in out['results']] == ['y'], '③ results 形状认得出', out['results'])
        ok(out['meta'].get('private_domain_excluded') == 1, '④ meta 记了剔除数', out.get('meta'))

        pack = {'meta': {}, 'pack': [{'id': 'p', 'tags': [M.PRIVATE_DOMAIN_TAG]}, {'id': 'q', 'tags': ['普通']}]}
        outp = M._final_out(pack, None, {})
        ok([i['id'] for i in outp['pack']] == ['q'], '③ pack 形状认得出', outp['pack'])

        mixed = {'meta': {}, 'results': results}
        outi = M._final_out(mixed, None, {'include_private': True})
        ok(len(outi['results']) == 2, '② include_private 参数放行', len(outi['results']))
    finally:
        if saved is None:
            os.environ.pop('MDCG_INCLUDE_PRIVATE', None)
        else:
            os.environ['MDCG_INCLUDE_PRIVATE'] = saved

    print()
    print('守卫结果：%d 通过 / %d 失败' % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())