# -*- coding: utf-8 -*-
"""守卫 · 审计记录属工作记录（情景层），不得占结构层，且不得进注入块。

判据来源：使用者 2026-11-14 裁定——审计是「工作/检查/审批」用途，
只在项目内有效，不是「自身结构事件」（如修改智能论理论），不得与后者等同。
"""
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
    cg = MdCGOS(tempfile.mkdtemp(prefix='aud_'), actor='t')
    rec = {'record_node_id': cg._audit_node_id('prop_a1', 1), 'record_hash': 'h' * 40,
           'pid': 'prop_a1', 'round': 1, 'decision': 'accept', 'status': 'accepted',
           'redteam_verdict': 'absent', 'issues': [], 'verify_hash': None,
           'actor': 'test', 't': 1792300000.0, 'target_id': ''}
    nid = cg._write_review_record(rec)
    ent = (cg.index.get('nodes') or {}).get(nid) or {}
    fm = (cg.get(nid) or {}).get('frontmatter') or {}
    tags = [str(t) for t in (fm.get('tags') or [])]
    ok(ent.get('layer') == 'contextual', 'A1 审计记录落情景层（工作记录，不占结构层）', ent.get('layer'))
    ok('用途:跑审计' in tags, 'A2 带用途标签=跑审计', tags)
    ok(any(t.startswith('项目:') for t in tags), 'A3 带项目标签（用户定义；缺省未登记）', tags)
    ok(any(t.startswith('项目:未登记') for t in tags), 'A4 未提供项目 ⇒ 显式「未登记」，不猜项目名', tags)
    ok(float(fm.get('importance') or 1) <= 0.3, 'A5 重要度低（不与理论变更等同）', fm.get('importance'))
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0
if __name__ == '__main__':
    sys.exit(main())