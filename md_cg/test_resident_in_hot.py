# -*- coding: utf-8 -*-
"""守卫 · 常驻节点必在热层（2026-11-17）。

起因：智能论 §1.6.3 五红线、1_ai 四份文档、人物树主干与分段——理论真源与自我锚，
却因「不新、重要度不够」被热层挤出（热层只收自我/锚点/近 7 天/重要度>=0.7）。
修法：hottier 新增常驻组（组 3，高于 self/anchor）——标签含「常驻」的节点永远在热层。
本守卫钉住：加了标签却没进热层 ⇒ 红。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import hottier  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    T = tempfile.mkdtemp(prefix='resident_')
    try:
        cg = MdCGOS(T, actor='t')
        cg.add('resident_low', '# 常驻低分', layer='knowledge', tags=['常驻'], importance=0.05)
        cg.add('normal_high', '# 普通高分', layer='knowledge', tags=['杂'], importance=0.95)
        cg.add('self_anchor_x', '# 自我锚', layer='self', tags=['自我'])

        hottier.ensure(cg, force=True)
        nodes = (hottier.load(cg.root) or {}).get('nodes') or {}
        ok('resident_low' in nodes, 'R1 常驻节点必在热层（即使重要度 0.05）', list(nodes)[:5])
        ok('normal_high' in nodes, 'R2 高分节点照旧进热层（未被常驻挤掉）')
        ok('self_anchor_x' in nodes, 'R3 自我层照旧进热层')

        hottier.ensure(cg, force=True, max_nodes=2)
        n2 = (hottier.load(cg.root) or {}).get('nodes') or {}
        ok('resident_low' in n2, 'R4 名额紧张时常驻仍保留（优先级最高）', list(n2))
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('常驻守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())