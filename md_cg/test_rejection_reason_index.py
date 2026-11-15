# -*- coding: utf-8 -*-
"""守卫 · 否证原因进索引（issue #929 问题3）：事后能答「为什么没记住」。"""
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
def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix='rj_'), actor='t')
    reason = '缺少必需要素：功能名、生效条件'
    nid = cg.add_rejected('测试假设：灵枢明天会飞', reason)
    ent = (cg.index.get('nodes') or {}).get(nid) or {}
    ok(ent.get('layer') == 'rejected', 'R1 落否决层', ent.get('layer'))
    ok(ent.get('rejection_reason') == reason, 'R2 否决原因进索引条目（不再只在正文里）', ent.get('rejection_reason'))
    fm = (cg.get(nid) or {}).get('frontmatter') or {}
    ok(str(fm.get('rejection_reason') or '') == reason, 'R3 frontmatter 同步落盘', fm.get('rejection_reason'))
    body = (cg.get(nid) or {}).get('content') or ''
    ok(reason in body, 'R4 正文原有「否决原因」行未丢（双写不替代）')
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0
if __name__ == '__main__':
    sys.exit(main())