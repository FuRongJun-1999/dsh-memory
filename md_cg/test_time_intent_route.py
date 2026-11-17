# -*- coding: utf-8 -*-
"""守卫 · 人物树路由（2026-11-17）：时间意图查询必须命中人物树主干。

缺陷（昨日实测）：检索『什么时候立的约定』→ 主干 persona_trunk_* 不在 top3，
排第一的是无关章节。两个根因：
  ① 库层默认检索**不含 layer=self**（安全默认）⇒ 主干永远摸不到；
  ② 热层按「自我/近期/重要度」收，不做时间排序 ⇒ 先撞热层会拿到「近的」不是「对的」。
修法：时间意图绕过热层 + 超取 + 日期/实体词加权；自指查询补一路 layer=self 合并。
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
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:180]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    T = tempfile.mkdtemp(prefix='timeintent_')
    try:
        cg = MdCGOS(T, actor='t')
        # 主干：含日期 + 实体词（约定/立约）
        cg.add('persona_trunk_test', '# 主干\n\n2026-10-06 立约：约定内容在此。',
               layer='self', tags=['常驻', '人物树'])
        # 干扰项：近期、含日期但不含实体词
        cg.add('noise_recent', '# 干扰\n\n2026-11-16 今天做了别的事。',
               layer='knowledge', tags=['杂'], importance=0.9)
        # 干扰项：含实体词但无日期
        cg.add('noise_nodate', '# 干扰二\n\n这里提到约定但没有日期。',
               layer='knowledge', tags=['杂'], importance=0.9)

        r = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '什么时候立的约定', 'k': 3})
        rows = (r or {}).get('results') or []
        ids = [(x['node'] or {}).get('id') for x in rows]
        meta = (r or {}).get('meta') or {}
        ok(ids and ids[0] == 'persona_trunk_test', 'A1 时间意图查询：主干排第一', ids[:3])
        ok(bool(meta.get('time_route')), 'A2 meta 标注 time_route（可审计）', meta.get('time_route'))
        ok(bool(meta.get('self_route')), 'A3 自指查询合并了 layer=self', meta.get('self_route'))

        r2 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '今天做了什么', 'k': 3})
        meta2 = (r2 or {}).get('meta') or {}
        ok(not meta2.get('time_route'), 'B1 非时间意图不加权（不误伤普通检索）', meta2.get('time_route'))
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('人物树路由守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
