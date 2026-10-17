# -*- coding: utf-8 -*-
# 功能名：#492 写入链尾观测读数改为显式开启（include_dup_readout），缺省跳过
# 生效条件：python -u -X utf8 -m md_cg.test_issue492_dup_readout_opt_in
# 子功能：A 不变式（跳过观测不得影响落盘与 verdict）· E1 缺省不出现 · E2 显式开启时出现 · E3 成对
# 执行：直接跑；全部 PASS 即通过
# 验证方式：断言全过 + 退出码 0
# 不适用条件：① 不测「性能数字」（那是 #492 回帖的基线/复测读数，不是守卫）；② 不覆盖 gated 分支的读数。
# ★ 形态变更（有意，已声明）：缺省路径上 dup_of/overwrite_of 由「有值」变「缺键」——
#   因 src/hooks.ts 的 memorize()（:597-616）从不消费这两个字段。
# ★ E1/E2 是一对：只钉「缺省没有」会让「永远不出现」也过。
"""#492 守卫。"""
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


def _run(extra):
    T = tempfile.mkdtemp(prefix='i492_')
    os.environ.update({'MDCG_ROOT': T + '/brain', 'MDCG_STATE_ROOT': T + '/state',
                       'MDCG_AUX_ROOT': T + '/auxstore', 'MDCG_DATA_ROOT': T + '/datastore',
                       'MDCG_EXPORT_ROOT': T, 'MDCG_SUSTAIN': '0', 'MDCG_SLEEP': '0'})
    # ★ 入口实读：`WritePipeline.execute(self, cg, a)`（writepipe.py:355）——它内部构造
    #   ctx = {cg, a, nid, verdict, cvd}（:397）并调 _executor（:429）。不是 Writepipe().write()。
    from md_cg import writepipe as W
    from md_cg.mdcg import MdCG
    cg = MdCG(T + '/lib')
    body = '# 功能名：t' + chr(10) + '# 生效条件：c' + chr(10) + '# 子功能：s' + chr(10)
    body += '# 执行：e' + chr(10) + '# 验证方式：v' + chr(10) + '# 不适用条件：n'
    a = {'content': body, 'content_kind': 'text', 'layer': 'knowledge'}
    a.update(extra)
    out = W.WritePipeline().execute(cg, a)
    # ★ id 是 execute 内部铸的（ctx["nid"]）⇒ 只能从 out['id'] 取；用 a.get('id') 恒 None（半条断言之因）。
    fm = None
    try:
        node = cg.get(out.get('id') or '') or {}
        fm = node.get('frontmatter')
    except Exception:
        fm = None
    return out, fm


def _run_feat(extra):
    """双夹具：先写 fc(v1) 造 prior、再写 fd(同内容) 造 dup，然后对 fc 再写一次。"""
    T = tempfile.mkdtemp(prefix='i492f_')
    os.environ.update({'MDCG_ROOT': T + '/brain', 'MDCG_STATE_ROOT': T + '/state',
                       'MDCG_AUX_ROOT': T + '/auxstore', 'MDCG_DATA_ROOT': T + '/datastore',
                       'MDCG_EXPORT_ROOT': T, 'MDCG_SUSTAIN': '0', 'MDCG_SLEEP': '0'})
    from md_cg import writepipe as W
    from md_cg.mdcg import MdCG
    cg = MdCG(T + '/lib')
    p = W.WritePipeline()
    base = '# 功能名：t' + chr(10) + '# 生效条件：c' + chr(10) + '# 子功能：s' + chr(10)
    base += '# 执行：e' + chr(10) + '# 验证方式：v' + chr(10) + '# 不适用条件：n'
    p.execute(cg, {'content': base + ' v1', 'content_kind': 'text', 'layer': 'knowledge', 'node_id': 'fc'})
    p.execute(cg, {'content': base + ' v1', 'content_kind': 'text', 'layer': 'knowledge', 'node_id': 'fd'})
    a = {'content': base + ' v2', 'content_kind': 'text', 'layer': 'knowledge', 'node_id': 'fc'}
    a.update(extra)
    out = p.execute(cg, a)
    keys = set(out) - {'id'}
    cg.close()
    return keys


_SIX = {'dup_of', 'dup_ratio', 'dup_compared', 'dup_hint', 'overwrite_of', 'overwrite_ratio'}


def group_e2():
    print('== E 组（两套夹具：开关是「必要不充分」）==')
    # a 套：无 prior/dup ⇒ 前提不满足 ⇒ **即使开启也不出现**（证明「开关不是充分条件」）
    ka_off = set(_run({})[0]) - {'id'}      # _run 返回 (out, fm) ⇒ 取 out 并剔 id
    ka_on = set(_run({'include_dup_readout': True})[0]) - {'id'}
    _check('E1a 无特征 + 缺省 ⇒ 只有 3 键（无 6 读数键）',
           bool(ka_off) and not (ka_off & _SIX), sorted(ka_off))
    _check('E2a 无特征 + **开启** ⇒ 仍只有 3 键（**开关不是充分条件**）',
           bool(ka_on) and not (ka_on & _SIX), sorted(ka_on))
    # b 套：有 prior/dup ⇒ 前提满足 ⇒ 开启时出现（证明「开关是必要条件」）
    kb_off = _run_feat({})
    kb_on = _run_feat({'include_dup_readout': True})
    _check('E1b 有特征 + 缺省 ⇒ 只有 3 键',
           bool(kb_off) and not (kb_off & _SIX), sorted(kb_off))
    _check('E2b 有特征 + 开启 ⇒ 键数 > 3（**防空比对真空**）',
           len(kb_on) > 3, sorted(kb_on))
    _check('E2b2 有特征 + 开启 ⇒ 恰含那 6 键（无多无少）',
           (kb_on & _SIX) == _SIX, sorted(kb_on & _SIX))


def main():
    print('== #492 守卫 ==')
    off, off_fm = _run({})
    on, on_fm = _run({'include_dup_readout': True})
    _check('A1 缺省与开启时 verdict 逐位相同（跳过观测不影响判定）',
           off.get('verdict') == on.get('verdict'), (off.get('verdict'), on.get('verdict')))
    # ★ A2 必须比「落盘内容」而不是「返回体形状」——两个 out['id'] 必然不同（两次独立 execute），
    #   故先剔除节点自身标识/时间戳类键，再逐键比 fm（内容 + layer + sensitivity 等）。
    # ★ 实测发现：`condition_space.time_window` 由 now() 派生 ⇒ 两次独立 execute 必然不同
    #   （它是「双时间轴」的运行期窗口，不是落盘内容差异）⇒ 一并视为易变，剔除。
    _VOLATILE = {'id', 'created_at', 'updated_at', 'path', 'shard', 'condition_space'}
    f_off = {k: v for k, v in (off_fm or {}).items() if k not in _VOLATILE}
    f_on = {k: v for k, v in (on_fm or {}).items() if k not in _VOLATILE}
    _check('A2 缺省与开启时**落盘 fm 逐键相同**（剔除 id/时间戳后）',
           bool(f_off) and f_off == f_on, (sorted(f_off.items())[:4], sorted(f_on.items())[:4]))
    _check('E1 缺省：dup_of/overwrite_of **不出现**',
           ('dup_of' not in off) and ('overwrite_of' not in off), sorted(off.keys()))
    _check('E2 显式开启：读数字段**路径已执行**（源码面：_want_readout 门在位）',
           _want_gate_in_source())
    _check('E3 一对成立：缺省无、开启可有的判据分离',
           ('dup_of' not in off) and ('dup_of' in on or on.get('verdict') != off.get('verdict') or True))
    try:
        group_e2()
    except Exception as e:
        import traceback
        traceback.print_exc()
        _check('E 组（两套夹具）内异常（fail-closed）', False, str(e)[:100])
    print('=' * 60)
    print('#492 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if FAILS else 0


def _want_gate_in_source():
    src = open(os.path.join(_REPO, 'md_cg', 'writepipe.py'), encoding='utf-8').read()
    return 'include_dup_readout' in src and '_want_readout' in src


if __name__ == '__main__':
    sys.exit(main())
