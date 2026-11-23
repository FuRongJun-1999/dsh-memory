# -*- coding: utf-8 -*-
"""读面瘦身（issue #997）的守卫。

# 功能名：test_issue997_read_slim —— read 返回体瘦身的定点断言
# 生效条件：改动 mcp_server._slim_read_out 或 read 出口后
# 子功能：
#   ① 缺省瘦身：顶层与 meta 的 bm25 / path_fingerprint 被摘掉
#   ② detail="full" 与 MDCG_READ_SLIM=0 都能取全量（两条独立通道）
#   ③ 正文一字不动（content 必须原样保留）
#   ④ pack / results 两侧都只留白名单键，frontmatter 只留可读字段
#   ⑤ 非 dict 输入原样返回（不抛）
# 执行：python -X utf8 md_cg/test_issue997_read_slim.py
# 验证方式：每条断言都配一条「不该变的东西没变」的反向对照
# 不适用条件：只验形状裁剪，不验检索结果正确性
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server as M  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:200]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def _sample():
    return {
        'meta': {'k': 1, 'bm25': {'posting_visits': 9}, 'path_fingerprint': {'provenance': [1, 2]},
                 'paths': ['bm25'], 'path_truncation': 0, 'kept': 'yes'},
        'warning': 'w',
        'bm25': {'documents': 100},
        'path_fingerprint': {'x': 1},
        'skipped': [],
        'pack': [{'id': 'n1', 'content': '正文一', 'state': 'ACCEPT', 'score': 0.5,
                  'tokens': 12, 'frontmatter': {'importance': 0.7, 'score_raw': 'x'}}],
        'results': [{'node': {'id': 'n2', 'path': 'knowledge/x.md', 'content': '正文二',
                              'frontmatter': {'layer': 'knowledge', 'tags': ['a'],
                                              'importance': 0.7, 'score_raw': 'y',
                                              'condition_space': {'z': 1}},
                              'verification_state': 'unverified'},
                     'score': 0.9, 'state': 'ACCEPT', 'reason': 'r'}],
    }


def main():
    print('=== issue #997 读面瘦身守卫 ===')
    saved = os.environ.pop('MDCG_READ_SLIM', None)
    try:
        # ① 缺省瘦身
        s = M._slim_read_out(_sample())
        # issue #1011 附带（2026-11-22 全量门禁实测的**本守卫自身的漂移**）：原先这里断言 `bm25` 也被摘，
        # 那等于把「新提交引入的新行为」当成契约钉死——而 `test_bm25.py:229` 的 stdio 用例（2026-11-12，
        # 早于本瘦身）要求 `packed["meta"]["bm25"]["hydrated"]` 可读，且**同一个 op** 不带 budget_tokens 时
        # 它是绿的、带 budget_tokens 就 KeyError ⇒ 瘦身制造了同 op 两种形态的不一致。老契约优先，
        # 「这条路真跑了、hydration 到几条」是判别力，不属可摘的噪声。
        ok('path_fingerprint' not in s and 'bm25' in s, '① 顶层遥测被摘（bm25 诊断保留：老契约钉住）',
           list(s.keys()))
        ok('path_fingerprint' not in s.get('meta', {}) and 'bm25' in s.get('meta', {}),
           '① meta 遥测被摘（bm25 诊断保留）', s.get('meta'))
        ok('paths' not in s.get('meta', {}) and 'path_truncation' not in s.get('meta', {}),
           '① meta 路径块被摘', s.get('meta'))

        # ② 两条全量通道
        f1 = M._slim_read_out(_sample(), detail='full')
        ok('bm25' in f1 and 'path_fingerprint' in f1, '② detail=full 取全量', list(f1.keys()))
        os.environ['MDCG_READ_SLIM'] = '0'
        f2 = M._slim_read_out(_sample())
        ok('bm25' in f2, '② MDCG_READ_SLIM=0 取全量', list(f2.keys()))
        os.environ['MDCG_READ_SLIM'] = '1'
        f3 = M._slim_read_out(_sample())
        ok('bm25' in f3 and 'path_fingerprint' not in f3, '② 开关回 1 后恢复瘦身（bm25 仍保留）',
           list(f3.keys()))
        os.environ.pop('MDCG_READ_SLIM', None)

        # ③ 正文一字不动
        o = _sample()
        s = M._slim_read_out(o)
        ok(s['pack'][0]['content'] == '正文一', '③ pack 正文原样')
        ok(s['results'][0]['node']['content'] == '正文二', '③ results 正文原样')
        ok(o['pack'][0].get('frontmatter') is not None, '③ 原对象未被就地修改（纯函数）')

        # ④ 白名单裁剪
        ok(set(s['pack'][0].keys()) <= set(M._READ_SLIM_KEEP_ITEM), '④ pack 只留白名单键',
           sorted(s['pack'][0].keys()))
        fm = s['results'][0]['node'].get('frontmatter') or {}
        ok('score_raw' not in fm and 'condition_space' not in fm, '④ frontmatter 评分字段被摘', fm)
        ok('layer' in fm and 'tags' in fm and 'importance' in fm, '④ frontmatter 可读字段保留', fm)
        ok(s['results'][0]['node']['id'] == 'n2', '④ node id 保留')
        ok(s['results'][0]['score'] == 0.9 and s['results'][0]['state'] == 'ACCEPT',
           '④ results 评分与状态保留')

        # ⑤ 非 dict 原样
        ok(M._slim_read_out(None) is None, '⑤ None 原样返回')
        ok(M._slim_read_out([1, 2]) == [1, 2], '⑤ list 原样返回')
    finally:
        if saved is None:
            os.environ.pop('MDCG_READ_SLIM', None)
        else:
            os.environ['MDCG_READ_SLIM'] = saved

    print()
    print('守卫结果：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
