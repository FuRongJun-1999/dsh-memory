# -*- coding: utf-8 -*-
"""守卫 · issue #980 剩余半条：自动保护排除「模型自生成、无人工确认」。

报告原文建议：**自动保护 `importance≥0.7 ⇒ protected` 至少排除「模型自生成、无人工确认」**。

病灶：`protect.is_protected_entry` 的按分分支原为
`imp>=0.7 and (source is None or source == "hint")`——**显式自评直接授权保护**。
报告人实测：外部模型自评 `importance: 0.9` + 该分支 ⇒ 自动 `protected`，
把「演出来的结果」当设定锁死。

修法：`hint` 需带 `importance_confirmed_by`（由设计者身份的写入方落）才按分保护；
`None`（存量/直写）行为不变——避免大规模改变既有保护面。

  T1 自评 hint 0.9 无确认 → 不受保护
  T2 自评 hint 0.9 带确认 → 受保护
  T3 来源 None 0.9 → 仍受保护（存量口径不变）
  T4 heuristic 0.9 → 不受保护（原裁定保留）
  T5 设计者写入带 hint → 落 importance_confirmed_by
  T6 非设计者写入带 hint → 不落确认位
  T7 低于阈值 0.69 → 一律不受保护
"""
import os
import sys
import tempfile
import shutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from md_cg import protect  # noqa: E402
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402

PASSED, FAILED = [], []
BODY = '# 功能名：t\n# 生效条件：a\n# 子功能：b\n# 执行：c\n# 验证方式：d\n# 不适用条件：e\n\n正文'


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def entry(**fm):
    fm.setdefault('layer', 'knowledge')
    return fm


def main():
    print('=== issue #980 · 自评不自动授权保护 ===')
    e = protect.is_protected_entry(entry(importance=0.9, importance_source='hint'))
    ok(e[0] is False, 'T1 自评 hint 0.9 无确认 → 不受保护', e)

    e = protect.is_protected_entry(entry(importance=0.9, importance_source='hint',
                                          importance_confirmed_by='furongjun'))
    ok(e[0] is True, 'T2 自评 hint 0.9 带确认 → 受保护', e)

    e = protect.is_protected_entry(entry(importance=0.9, importance_source=None))
    ok(e[0] is True, 'T3 来源 None 0.9 → 仍受保护（存量不变）', e)

    e = protect.is_protected_entry(entry(importance=0.9, importance_source='heuristic'))
    ok(e[0] is False, 'T4 heuristic 0.9 → 不受保护', e)

    e = protect.is_protected_entry(entry(importance=0.69, importance_source='hint',
                                          importance_confirmed_by='x'))
    ok(e[0] is False, 'T7 0.69 → 一律不受保护', e)

    T = tempfile.mkdtemp(prefix='g980_')
    try:
        for role, tag in (('designer', 'T5'), ('record', 'T6')):
            p = Principal(tenant='default', actor='u_' + role, role=role,
                          can_write=True, can_admin=(role == 'designer'))
            cg = MdCGSecure(os.path.join(T, role), principal=p)
            nid = cg.remember_gated('n_' + role, BODY, layer='contextual',
                                    importance=0.9, role='user')
            rid = nid.get('node_id') if isinstance(nid, dict) else nid
            fm = (cg.get(rid) or {}).get('frontmatter') or {}
            src = fm.get('importance_source')
            conf = fm.get('importance_confirmed_by')
            if tag == 'T5':
                ok(src == 'hint' and bool(conf), 'T5 设计者 hint 落确认位', (src, conf))
            else:
                ok(src == 'hint' and not conf, 'T6 非设计者 hint 不落确认位', (src, conf))
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('守卫结果：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())