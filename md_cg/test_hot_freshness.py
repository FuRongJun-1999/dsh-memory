# -*- coding: utf-8 -*-
"""守卫 · 热层新鲜判据（2026-11-14）：不得“每写一条就全量重建”。"""
from __future__ import annotations
import os, sys, tempfile, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
from md_cg import hottier  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402
FAILS = []
def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:140]))
    if not cond:
        FAILS.append(name)
def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix='hot_'), actor='t')
    cg.add('h1', '热层新鲜判据用例一', layer='knowledge', tags=['用途:做验证'])
    cg.add('h2', '热层新鲜判据用例二', layer='contextual', tags=[])
    cg.flush()
    t0 = time.time(); m1 = hottier.ensure(cg); d1 = time.time() - t0
    ok(m1.get('reused') is False, 'F1 首建 reused=False', m1)
    t0 = time.time(); m2 = hottier.ensure(cg); d2 = time.time() - t0
    ok(m2.get('reused') is True, 'F2 第二次 ensure 复用（不再全量重建）', m2)
    ok(d2 <= d1 + 0.05, 'F3 复用不慢于首建', (round(d1,3), round(d2,3)))
    ok(hottier.is_fresh(cg) is True, 'F4 is_fresh 接受库对象')
    ok(hottier.is_fresh(cg.root) is True, 'F5 is_fresh 接受库根字符串')
    # 不变量：戳相等 ⇒ 永远新鲜（TTL 只用于「戳不等」时放宽旧判据）；TTL=0 ⇒ 戳不等即重建
    cg.add('h3', '热层新鲜判据用例三：写一条让源库戳变化', layer='knowledge')
    cg.flush()
    os.environ['MDCG_HOT_TTL_S'] = '0'
    try:
        ok(hottier.is_fresh(cg) is False, 'F6 TTL=0 且戳已变 ⇒ 判为不新鲜（可配置）')
    finally:
        os.environ.pop('MDCG_HOT_TTL_S', None)
    ok(hottier.is_fresh(cg) is False, 'F7 新增节点 ⇒ 指纹变 ⇒ 不新鲜（新记忆必须能进热层）')
    hottier.ensure(cg)
    cg.add('h1', '热层新鲜判据用例一（只改标签）', layer='knowledge', tags=['用途:做设计'])
    cg.flush()
    ok(hottier.is_fresh(cg) is True, 'F8 只改标签（节点集合未变）⇒ 仍新鲜，不因改标签重建')
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0
if __name__ == '__main__':
    sys.exit(main())