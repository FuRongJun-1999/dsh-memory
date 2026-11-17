# -*- coding: utf-8 -*-
"""守卫 · 写入闸（2026-11-17 使用者裁定：知识层必须带复核结论，直接写不经复核是不负责任）。

默认档位 enforce：知识层=1 档需 reflect；结构层=2 档需 reflect+verify；自我/锚点=3 档另需人工。
复核通道默认 hive,subagent——复核不是没有，是此前没人声明。

  W1 缺省档位 enforce，通道含 hive/subagent
  W2 无复核 ⇒ 知识层 require_review；情景层 allow
  W3 带 reflect ⇒ 知识层放行
  W4 经安全主体真的拦（Principal.require_layer_write 抛 AccessDenied）
  W5 写入侧真的抛（MdCGSecure 写 knowledge 无复核 ⇒ 异常，不是静默放行）
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import security, writegate  # noqa: E402
from md_cg.mdcos import MdCGSecure  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    clean = {k: v for k, v in os.environ.items()
             if k not in ('MDCG_WRITE_GATE', 'MDCG_REVIEW_CHANNELS', 'MDCG_REVIEWERS')}
    ok(writegate.gate_mode(clean) == 'enforce', 'W1a 缺省档位 = enforce', writegate.gate_mode(clean))
    ch = writegate.review_channels(clean)
    ok('hive' in ch and 'subagent' in ch, 'W1b 缺省通道含 hive 与 subagent', ch)

    d1 = writegate.decide_write('knowledge', environ=clean)
    ok(d1['decision'] == 'require_review' and d1['missing'] == ['reflect'],
       'W2a 知识层无复核 ⇒ require_review', d1)
    ok(writegate.decide_write('contextual', environ=clean)['decision'] == 'allow',
       'W2b 情景层直写')
    ok(writegate.decide_write('knowledge', reviewers=('reflect',), environ=clean)['decision'] == 'allow',
       'W3 带 reflect 复核 ⇒ 放行')

    os.environ.pop('MDCG_REVIEWERS', None)
    p = security.Principal(actor='t', role='system')
    try:
        p.require_layer_write('knowledge', 'internal')
        ok(False, 'W4 知识层应被拦', '竟然通过')
    except Exception as e:
        ok('复核闸' in str(e), 'W4 知识层被拦（无复核）', str(e)[:60])

    T = tempfile.mkdtemp(prefix='wg_')
    try:
        cg = MdCGSecure(T)
        body = '# 功能名：x\n# 生效条件：a\n# 子功能：b\n# 执行：c\n# 验证方式：d\n# 不适用条件：e\n\n正文'
        blocked = False
        try:
            cg.add('n_k', body, layer='knowledge', importance=0.6)
        except Exception:
            blocked = True
        ok(blocked, 'W5a 直写知识层（无复核）被真的拒绝')
        os.environ['MDCG_REVIEWERS'] = 'reflect'
        got = cg.add('n_k2', body, layer='knowledge', importance=0.6)
        os.environ.pop('MDCG_REVIEWERS', None)
        ok(bool(got), 'W5b 声明 reflect 复核后写入成功（不是无解死锁）', got)
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('写入闸守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())