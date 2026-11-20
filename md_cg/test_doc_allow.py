# -*- coding: utf-8 -*-
"""单独放行白名单（_doc_allow.json）的守卫。

# 功能名：test_doc_allow —— 检索面「单独放行」白名单的定点断言
# 生效条件：改动 mcp_server.drop_doc_nodes / doc_allow_ids 后
# 子功能：
#   ① 白名单内 doc_ 不被过滤，白名单外仍被过滤
#   ② 文件缺失 / 非法 JSON / 无 allow 键 → 空集（fail-closed 到"不放行"）
#   ③ 变异锚：把 allow 置空，原本放行的样本必须重新被过滤
# 执行：python -X utf8 md_cg/test_doc_allow.py
# 验证方式：自证——每条断言带一条反向对照
# 不适用条件：只验证过滤判据，不验证检索排序
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server as M  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:160]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def write_allow(root, payload):
    p = os.path.join(root, M.DOC_ALLOW_FILE)
    with open(p, 'w', encoding='utf-8') as f:
        if isinstance(payload, str):
            f.write(payload)
        else:
            json.dump(payload, f, ensure_ascii=False)


def main():
    print('=== doc_allow 守卫 ===')
    items = [{'id': 'doc_a'}, {'id': 'doc_b'}, {'id': 'mem_c'}]
    idf = lambda it: it.get('id')  # noqa: E731

    base = tempfile.mkdtemp(prefix='docallow_')
    try:
        # ① 白名单内放行、白名单外仍过滤
        write_allow(base, {'allow': ['doc_a']})
        allow = M.doc_allow_ids(root=base)
        ok(allow == frozenset(['doc_a']), '① 白名单读取正确', allow)
        kept, dropped = M.drop_doc_nodes(items, idf, enabled=True, allow=allow)
        ids = [x['id'] for x in kept]
        ok('doc_a' in ids, '① 白名单内 doc 被放行', ids)
        ok('doc_b' not in ids, '① 白名单外 doc 仍被过滤', ids)
        ok(dropped == 1, '① 丢弃计数正确（1 个 doc_b）', dropped)

        # ② fail-closed：缺失 / 非法 / 无 allow 键 → 空集
        shutil.rmtree(base, ignore_errors=True)
        os.makedirs(base, exist_ok=True)
        ok(M.doc_allow_ids(root=base) == frozenset(), '② 文件缺失 → 空集（不放行）')
        write_allow(base, '{not json')
        ok(M.doc_allow_ids(root=base) == frozenset(), '② 非法 JSON → 空集（不放行）')
        write_allow(base, {'note': 'no allow key'})
        ok(M.doc_allow_ids(root=base) == frozenset(), '② 无 allow 键 → 空集（不放行）')

        # ③ 变异锚：allow 置空后，原本放行的样本重新被过滤
        write_allow(base, {'allow': []})
        allow2 = M.doc_allow_ids(root=base)
        kept2, dropped2 = M.drop_doc_nodes(items, idf, enabled=True, allow=allow2)
        ok('doc_a' not in [x['id'] for x in kept2], '③ allow 置空后 doc_a 重新被过滤')
        ok(dropped2 == 2, '③ 丢弃计数回到 2', dropped2)

        # ③b 关掉过滤时一律不过滤（enabled=False 不受白名单影响）
        kept3, dropped3 = M.drop_doc_nodes(items, idf, enabled=False, allow=())
        ok(len(kept3) == 3 and dropped3 == 0, '③ enabled=False 时不过滤', (kept3, dropped3))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print()
    print('守卫结果：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
