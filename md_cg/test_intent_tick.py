# -*- coding: utf-8 -*-
"""守卫 · 主动队列：心跳接上「起身」（2026-11-18）。

背景：心跳连跑 5.6 小时 `task_running: false`，而库里躺着 61 条 unresolved、2 条 goals——
**想做的事早就有，缺的是「没人提问时去取一条」的那一跳**。

  I1 pick 选 unresolved 层，且确定性（两次同结果）
  I2 step 只追加 _intent.jsonl，**不改库**（节点内容/last_access 不变）
  I3 off 档零动作
  I4 台账字段齐（t / node_id / layer / next_action）
  I5 空库不抛，如实返回「没有待办」
  I6 心跳循环里真的接了第七档（sustain._run 含 _tick_intent 调度）
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from md_cg import intent_tick  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    print('=== 主动队列守卫（心跳 → 起身）===')
    os.environ.pop('MDCG_INTENT_TICK', None)
    T = tempfile.mkdtemp(prefix='intentguard_')
    try:
        cg = MdCGOS(T, actor='t')
        # I5 空库
        r0 = intent_tick.step(cg)
        ok(r0.get('ok') is True and r0.get('picked') is None,
           'I5 空库不抛，如实返回没有待办', r0)

        cg.add('u1', '# 问题：为何 X 未解\n# 生效条件：待查', layer='unresolved')
        cg.add('u2', '# 问题：为何 Y 未解\n# 生效条件：待查', layer='unresolved')
        cg.add('g1', '# 功能名：目标 A\n# 执行：待定', layer='goals')

        p1, p2 = intent_tick.pick(cg), intent_tick.pick(cg)
        ok(p1 == p2 and p1 in ('u1', 'u2'), 'I1 pick 确定性且选 unresolved 层', (p1, p2))

        before = (cg.get(p1) or {})
        r1 = intent_tick.step(cg)
        after = (cg.get(p1) or {})
        same = ((before.get('content') == after.get('content'))
                and ((before.get('frontmatter') or {}).get('last_access')
                     == (after.get('frontmatter') or {}).get('last_access')))
        ok(same, 'I2 step 不改库（正文与 last_access 逐位不变）')

        recs = intent_tick.recent(cg)
        ok(len(recs) == 1, 'I4a 台账只追加一行', len(recs))
        keys = set((recs[0] if recs else {}).keys())
        ok({'t', 'node_id', 'layer', 'next_action'} <= keys, 'I4b 台账字段齐', sorted(keys))

        os.environ['MDCG_INTENT_TICK'] = 'off'
        n_before = len(intent_tick.recent(cg))
        r2 = intent_tick.step(cg)
        ok(r2.get('ok') is False and len(intent_tick.recent(cg)) == n_before,
           'I3 off 档零动作', r2)
        os.environ.pop('MDCG_INTENT_TICK', None)
    finally:
        shutil.rmtree(T, ignore_errors=True)

    src = open(os.path.join(REPO, 'md_cg', 'sustain.py'), encoding='utf-8').read()
    ok('self._tick_intent()' in src and 'next_intent' in src,
       'I6 心跳循环已接第七档（_tick_intent 调度在位）')

    print()
    print('守卫结果：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())