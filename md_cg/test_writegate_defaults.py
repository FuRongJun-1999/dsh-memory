# -*- coding: utf-8 -*-
"""守卫 · 写入闸（2026-11-17 使用者裁定：知识层必须带复核结论）。

默认档位 enforce；复核通道**默认未声明**（声明缺失≠能力缺失，探测不是大脑库的事）。
⇒ 未声明通道时知识层一律 deny；声明通道 + 带复核单元 ⇒ 放行。

  W1 缺省档位 enforce、缺省通道为空（未声明）
  W2 无通道 ⇒ 知识层 deny；情景层仍可直写
  W3 声明通道 + reflect ⇒ 知识层放行
  W4 经安全主体真的拦（AccessDenied）
  W5 真实写入：未声明时被拒；两条都声明后成功（不是无解死锁）
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
    ok(writegate.review_channels(clean) == (), 'W1b 缺省通道未声明', writegate.review_channels(clean))

    ok(writegate.decide_write('knowledge', environ=clean)['decision'] == 'deny',
       'W2a 无通道 ⇒ 知识层 deny')
    ok(writegate.decide_write('contextual', environ=clean)['decision'] == 'allow',
       'W2b 情景层仍可直写')

    chan = dict(clean, MDCG_REVIEW_CHANNELS='hive,subagent')
    ok(writegate.decide_write('knowledge', reviewers=('reflect',), environ=chan)['decision'] == 'allow',
       'W3 声明通道 + reflect ⇒ 知识层放行')

    p = security.Principal(actor='t', role='system')
    os.environ.pop('MDCG_REVIEW_CHANNELS', None)
    os.environ['MDCG_WRITE_GATE'] = 'enforce'
    try:
        p.require_layer_write('knowledge', 'internal')
        ok(False, 'W4 知识层应被拦', '竟然通过')
    except Exception as e:
        ok('复核闸' in str(e), 'W4 知识层被拦（未声明通道）', str(e)[:60])

    T = tempfile.mkdtemp(prefix='wg_')
    try:
        cg = MdCGSecure(T)
        body = '# 功能名：x\n# 生效条件：a\n# 子功能：b\n# 执行：c\n# 验证方式：d\n# 不适用条件：e\n\n正文'
        blocked = False
        try:
            cg.add('n_k', body, layer='knowledge', importance=0.6)
        except Exception:
            blocked = True
        ok(blocked, 'W5a 未声明时直写知识层被真的拒绝')
        os.environ['MDCG_REVIEW_CHANNELS'] = 'hive,subagent'
        os.environ['MDCG_REVIEWERS'] = 'reflect'
        try:
            got = cg.add('n_k2', body, layer='knowledge', importance=0.6)
        finally:
            os.environ.pop('MDCG_REVIEWERS', None)
            os.environ.pop('MDCG_REVIEW_CHANNELS', None)
        ok(bool(got), 'W5b 声明通道 + reflect 后写入成功', got)
    finally:
        os.environ.pop('MDCG_WRITE_GATE', None)
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('写入闸守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())