# -*- coding: utf-8 -*-
# 功能名：#469 scrub override 透传（_move_layer 增 override 形参并下传 guard_move）
# 生效条件：python -u -X utf8 -m md_cg.test_issue469_scrub_override_passthrough
# 子功能：A 正向（受保护 + override => 层真变）· K 反向①（无 override 被拦 / 非受保护不变 / 失败标记不变）· E 结构（_actions_ok 在位 / AST 钉透传）
# 执行：直接跑；全部 PASS 即通过
# 验证方式：断言全过 + 退出码 0
# 不适用条件：① 不做「issue 级」行为面验证 —— 能产出 demote 类 issue 的 kind 均需高成本夹具；
#   而 orphan_noise 因产出条件 layer==contextual 与 demote 条件 layer!=contextual 互斥、
#   结构上测不到 :777 => 已单开 #524 记录该死代码。本守卫只测 _move_layer 的 override 面。
#   ② 不覆盖「将来别处再漏传 override」（只能钉当前路径）
# ★ 夹具陷阱：同一夹具连续两次调用会把第二次变成空操作（from_layer==to_layer 时静默返回 None），
#   而它看起来像「保护失效」=> 会让人误判「修坏了」。故本守卫 override=True / False 各用一条独立库。
# ★ M2（撤 _actions_ok 接线）只红 E 组是预期：`#411` 已让「失败不记 ok」转绿，本批只能钉「不被撤」。
"""#469 守卫。"""
import ast
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASSED, FAILS = [], []


def _check(n, c, d=''):
    if c:
        print('  PASS ' + n)
        PASSED.append(n)
    else:
        print('  FAIL ' + n + '  ' + str(d)[:170])
        FAILS.append(n)


def _mk(tag, protected=True):
    T = tempfile.mkdtemp(prefix='i469_' + tag + '_')
    os.environ.update({'MDCG_ROOT': T + '/brain', 'MDCG_STATE_ROOT': T + '/state',
                       'MDCG_AUX_ROOT': T + '/auxstore', 'MDCG_DATA_ROOT': T + '/datastore',
                       'MDCG_EXPORT_ROOT': T, 'MDCG_SUSTAIN': '0', 'MDCG_SLEEP': '0'})
    from md_cg.mdcg import MdCG
    cg = MdCG(T + '/lib')
    cg.add('n_x', '# 功能名：节点' + chr(10) + '# 不适用条件：无', layer='knowledge',
           importance=0.9 if protected else 0.5)
    if protected:
        cg.index['nodes']['n_x']['protected'] = True
    cg.flush()
    return cg, T


def group_a():
    print('== A 组：正向 ==')
    cg, _ = _mk('a')
    before = cg.index['nodes']['n_x'].get('layer')
    # ★ A1 包 try：M1（撤 override 透传）会让 _move_layer 抛 ProtectionError；
    #   包了才能红在 A1 这条断言上（可定位），而不是红在「组内异常」兜底。
    raised = None
    try:
        cg._move_layer('n_x', 'contextual', reason='i469', override=True)
    except Exception as e:
        raised = type(e).__name__
    after = cg.index['nodes']['n_x'].get('layer')
    _check('A1 受保护 + override=True => 层真变（%s -> %s）' % (before, after),
           raised is None and after == 'contextual', (raised, before, after))
    cg.close()


def group_k():
    print('== K 组：反向腿① ==')
    cg, _ = _mk('k1')
    raised = None
    try:
        cg._move_layer('n_x', 'contextual', reason='i469', override=False)
    except Exception as e:
        raised = type(e).__name__
    lay = cg.index['nodes']['n_x'].get('layer')
    _check('K1 受保护 + override=False => 抛 ProtectionError 且层不变',
           raised == 'ProtectionError' and lay == 'knowledge', (raised, lay))
    cg.close()
    cg2, _ = _mk('k2', protected=False)
    cg2._move_layer('n_x', 'contextual', reason='i469', override=False)
    lay2 = cg2.index['nodes']['n_x'].get('layer')
    _check('K2 非受保护节点 => 无需 override 也能搬（保护未扩大）',
           lay2 == 'contextual', lay2)
    cg2.close()
    from md_cg import scrub as S
    _check('K3 ACTION_FAIL_MARKS 三项仍在位（demote_state 语义不变）',
           S.ACTION_FAIL_MARKS == ('weaken_failed:', 'demote_failed:', 'demote_state:'),
           S.ACTION_FAIL_MARKS)


def group_e():
    print('== E 组：结构断言 ==')
    src = open(os.path.join(_REPO, 'md_cg', 'scrub.py'), encoding='utf-8').read()
    _check('E1 _actions_ok 仍在位（#411 既有判据，防被撤）',
           'def _actions_ok(' in src and '_ok = _actions_ok(done)' in src)
    msrc = open(os.path.join(_REPO, 'md_cg', 'mdcg.py'), encoding='utf-8').read()
    tree = ast.parse(msrc)
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == 'guard_move':
            calls.append(ast.unparse(node))
    ok = any('override=override' in c for c in calls)
    _check('E2 AST：_move_layer 内 guard_move 显式透传 override（不是字面 False）', ok, calls)


def main():
    print('== #469 守卫 ==')
    for f in (group_a, group_k, group_e):
        try:
            f()
        except Exception as e:
            import traceback
            traceback.print_exc()
            _check('组内异常（fail-closed）', False, str(e)[:100])
    print('=' * 60)
    print('#469 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
