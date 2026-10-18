# -*- coding: utf-8 -*-
# 功能名：#492 写入链尾观测读数改为显式开启（include_dup_readout），缺省跳过且零成本
# 生效条件：python -u -X utf8 -m md_cg.test_issue492_dup_readout_opt_in [--mutate]
# 子功能：A 不变式（跳过观测不影响落盘与 verdict）· A3 成本不变量（缺省零次调用读数）
#         · E1 缺省不出现 · E2 源码门在位 · E3 一对成立 · E4 必要不充分矩阵
# 执行：直接跑；--mutate 时额外跑两条定点变异并要求红项集合非空
# 验证方式：断言全过 + 退出码 0；--mutate 下每条变异的红项集合必须非空且含指定项
# 不适用条件：① 不测绝对耗时（性能数字属 #492 回帖读数，不是守卫判据——机器相关）；
#             ② 不覆盖 gated 分支的读数；③ 不覆盖 mcp_server 直写面（另开 NEED_FILE）。
# ★ 形态变更（有意，已声明）：缺省路径上 dup_of/overwrite_of 由「有值」变「缺键」——
#   因 src/hooks.ts 的 memorize()（:597-616）从不消费这两个字段。
# ★ 判别力要点：只断言「键不出现」挡不住「无条件算完再藏键」（成本回归）。故 A3/A4
#   用 writepipe.readout_calls() 的整数增量钉「缺省一次都不算、开启恰好算一次」，
#   M1 变异（只撤计算门、保留输出门）正是靠 A3 转红。
"""#492 守卫。"""
import argparse
import importlib.util
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
    return bool(c)


def _sandbox(prefix):
    T = tempfile.mkdtemp(prefix=prefix)
    os.environ.update({'MDCG_ROOT': T + '/brain', 'MDCG_STATE_ROOT': T + '/state',
                       'MDCG_AUX_ROOT': T + '/auxstore', 'MDCG_DATA_ROOT': T + '/datastore',
                       'MDCG_EXPORT_ROOT': T, 'MDCG_SUSTAIN': '0', 'MDCG_SLEEP': '0'})
    return T


def _body():
    b = '# 功能名：t' + chr(10) + '# 生效条件：c' + chr(10) + '# 子功能：s' + chr(10)
    return b + '# 执行：e' + chr(10) + '# 验证方式：v' + chr(10) + '# 不适用条件：n'


# 生效条件：mod 为 writepipe 模块（真身或变异体）；extra 为写参附加键。
# 返回 (out, fm, calls_delta)——calls_delta 取 mod.readout_calls() 的本次增量。
def _run(extra, mod=None):
    T = _sandbox('i492_')
    if mod is None:
        from md_cg import writepipe as mod
    from md_cg.mdcg import MdCG
    cg = MdCG(T + '/lib')
    a = {'content': _body(), 'content_kind': 'text', 'layer': 'knowledge'}
    a.update(extra)
    c0 = mod.readout_calls()
    out = mod.WritePipeline().execute(cg, a)
    delta = mod.readout_calls() - c0
    fm = None
    try:
        fm = (cg.get(out.get('id') or '') or {}).get('frontmatter')
    except Exception:
        fm = None
    return out, fm, delta


def _run_feat(extra, mod=None):
    """双夹具：先写 fc(v1) 造 prior、再写 fd(同内容) 造 dup，然后对 fc 再写一次。"""
    T = _sandbox('i492f_')
    if mod is None:
        from md_cg import writepipe as mod
    from md_cg.mdcg import MdCG
    cg = MdCG(T + '/lib')
    p = mod.WritePipeline()
    base = _body()
    p.execute(cg, {'content': base + ' v1', 'content_kind': 'text', 'layer': 'knowledge', 'node_id': 'fc'})
    p.execute(cg, {'content': base + ' v1', 'content_kind': 'text', 'layer': 'knowledge', 'node_id': 'fd'})
    a = {'content': base + ' v2', 'content_kind': 'text', 'layer': 'knowledge', 'node_id': 'fc'}
    a.update(extra)
    c0 = mod.readout_calls()
    out = p.execute(cg, a)
    delta = mod.readout_calls() - c0
    cg.close()
    return set(out) - {'id'}, delta


_SIX = {'dup_of', 'dup_ratio', 'dup_compared', 'dup_hint', 'overwrite_of', 'overwrite_ratio'}


def _want_gate_in_source():
    src = open(os.path.join(_REPO, 'md_cg', 'writepipe.py'), encoding='utf-8').read()
    return 'include_dup_readout' in src and '_want_readout' in src


def _ccg_line():
    """返回 `def _executor(ctx)` 上方最近的 CCG「生效条件」注释行（陈旧规格行）。"""
    return _ccg_line_src(open(os.path.join(_REPO, 'md_cg', 'writepipe.py'),
                              encoding='utf-8').read())


def _ccg_line_src(src):
    lines = src.splitlines()
    for i, l in enumerate(lines):
        if l.startswith('def _executor(ctx):'):
            for j in range(i - 1, max(-1, i - 12), -1):
                if lines[j].startswith('# 生效条件'):
                    return lines[j]
            return ''
    return ''


def _ccg_line_gated():
    return _ccg_line_gated_src(open(os.path.join(_REPO, 'md_cg', 'writepipe.py'),
                                    encoding='utf-8').read())


def _ccg_line_gated_src(src):
    """#492 随动：该规格行必须声明开关（旧版写「落盘前另取两个读数」= 无条件口径）。"""
    l = _ccg_line_src(src)
    return ('include_dup_readout' in l) and ('无条件执行 cg.add' in l)


def _suite(mod=None, label=''):
    """跑全套判据；返回 (通过项集合, 失败项集合)。mod=None ⇒ 真身模块。"""
    global PASSED, FAILS
    saved = (list(PASSED), list(FAILS))
    PASSED, FAILS = [], []
    off, off_fm, off_calls = _run({}, mod)
    on, on_fm, on_calls = _run({'include_dup_readout': True}, mod)
    _check('A1 缺省与开启时 verdict 逐位相同（跳过观测不影响判定）',
           off.get('verdict') == on.get('verdict'), (off.get('verdict'), on.get('verdict')))
    _VOLATILE = {'id', 'created_at', 'updated_at', 'path', 'shard', 'condition_space'}
    f_off = {k: v for k, v in (off_fm or {}).items() if k not in _VOLATILE}
    f_on = {k: v for k, v in (on_fm or {}).items() if k not in _VOLATILE}
    _check('A2 缺省与开启时**落盘 fm 逐键相同**（剔除 id/时间戳后）',
           bool(f_off) and f_off == f_on, (sorted(f_off.items())[:4], sorted(f_on.items())[:4]))
    # ★ 成本不变量：形状断言挡不住「算完再藏」——必须钉调用次数。
    _check('A3 缺省路径**零次**观测读数调用（成本不变量）', off_calls == 0, off_calls)
    _check('A4 显式开启路径**恰好一次**观测读数调用', on_calls == 1, on_calls)
    _check('E1 缺省：dup_of/overwrite_of **不出现**',
           ('dup_of' not in off) and ('overwrite_of' not in off), sorted(off.keys()))
    _check('E2 显式开启：读数字段**路径已执行**（源码面：_want_readout 门在位）',
           _want_gate_in_source() if mod is None else ('_want_readout' in _mutant_src(mod)))
    _check('E2c CCG「生效条件」行与实现同口径（不再写无条件的「落盘前另取读数」）',
           _ccg_line_gated() if mod is None else _ccg_line_gated_src(_mutant_src(mod)),
           _ccg_line()[:120])
    ka_off = set(_run({}, mod)[0]) - {'id'}
    ka_on = set(_run({'include_dup_readout': True}, mod)[0]) - {'id'}
    _check('E1a 无特征 + 缺省 ⇒ 只有 3 键（无 6 读数键）',
           bool(ka_off) and not (ka_off & _SIX), sorted(ka_off))
    _check('E2a 无特征 + **开启** ⇒ 仍只有 3 键（**开关不是充分条件**）',
           bool(ka_on) and not (ka_on & _SIX), sorted(ka_on))
    kb_off, kb_off_calls = _run_feat({}, mod)
    kb_on, kb_on_calls = _run_feat({'include_dup_readout': True}, mod)
    _check('E1b 有特征 + 缺省 ⇒ 只有 3 键',
           bool(kb_off) and not (kb_off & _SIX), sorted(kb_off))
    _check('E1c 有特征 + 缺省 ⇒ **零次**调用（成本腿，非形状腿）', kb_off_calls == 0, kb_off_calls)
    _check('E2b 有特征 + 开启 ⇒ 键数 > 3（**防空比对真空**）',
           len(kb_on) > 3, sorted(kb_on))
    _check('E2b2 有特征 + 开启 ⇒ 恰含那 6 键（无多无少）',
           (kb_on & _SIX) == _SIX, sorted(kb_on & _SIX))
    # ★ E3 非恒真：缺省**无**且开启**有**（两侧都断言；旧版尾部 `or True` 已删）。
    _check('E3 一对成立：缺省 dup_of 不出现 且 开启 dup_of 出现',
           ('dup_of' not in kb_off) and ('dup_of' in kb_on), (sorted(kb_off), sorted(kb_on)))
    got_pass, got_fail = set(PASSED), set(FAILS)
    if mod is None:
        # 真身：结果留在全局（主流程汇总）；变异体：只回报、不污染主流程读数。
        PASSED, FAILS = saved[0] + list(got_pass), saved[1] + list(got_fail)
    else:
        PASSED, FAILS = saved
    if label:
        print('  [%s] 通过 %d / 失败 %d %s'
              % (label, len(got_pass), len(got_fail), sorted(got_fail)))
    return got_pass, got_fail


# ---- 变异腿 ---------------------------------------------------------------

_ANCHORS = (
    # (名, 旧串, 新串)
    ('M1 只撤计算门（保留输出门）',
     '    if _want_readout:\n'
     '        _prior, _prior_cov, _dup = _dup_readout(cg, a, ctx["nid"])',
     '    if True:\n'
     '        _prior, _prior_cov, _dup = _dup_readout(cg, a, ctx["nid"])'),
    ('M2 整体回退（计算门 + 两处输出门）',
     '    if _want_readout:\n'
     '        _prior, _prior_cov, _dup = _dup_readout(cg, a, ctx["nid"])',
     '    _prior, _prior_cov, _dup = _dup_readout(cg, a, ctx["nid"])'),
    # M3：只把 CCG 规格行改回旧的无条件口径（实现不动）——钉「文档与实现同源」。
    ('M3 CCG 规格行回退为无条件口径',
     '**仅当 a["include_dup_readout"] 为真**时，落盘前另取',
     '落盘前另取'),
)


def _mutant_src(mod):
    return getattr(mod, '_MUTANT_SRC', '')


def _load_mutant(src_text, tag):
    path = os.path.join(tempfile.mkdtemp(prefix='i492mut_'), 'writepipe_%s.py' % tag)
    open(path, 'w', encoding='utf-8').write(src_text)
    name = 'md_cg.writepipe_mut_%s' % tag
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    m._MUTANT_SRC = src_text
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _mutations():
    src = open(os.path.join(_REPO, 'md_cg', 'writepipe.py'), encoding='utf-8').read()
    out = []
    for tag, old, new in _ANCHORS:
        n = src.count(old)
        if n != 1:
            print('  [FAIL] 变异锚点「%s」命中 %d 次（应为 1）' % (tag, n))
            FAILS.append('变异锚点 ' + tag)
            continue
        text = src.replace(old, new)
        if tag.startswith('M2'):
            # 两处输出门同步回退（M2 才是「完整回退」）
            for o2, n2 in (('    if _want_readout and _prior is not None:',
                            '    if _prior is not None:'),
                           ('    if _want_readout and _dup and _dup["with"] and _dup["max"] >= _forgetting.DUP_MERGE:',
                            '    if _dup and _dup["with"] and _dup["max"] >= _forgetting.DUP_MERGE:')):
                if text.count(o2) != 1:
                    print('  [FAIL] M2 输出门锚点命中 %d 次' % text.count(o2))
                    FAILS.append('变异锚点 M2 输出门')
                    break
                text = text.replace(o2, n2)
        out.append((tag, text))
    return out


def _run_mutations():
    print('== 变异腿 ==')
    reds = {}
    # 指定项：M1（只撤计算门）必须被**成本腿**抓到；M2（整体回退）必须被**形状腿**抓到。
    # 注意 M2 用 E1b（有特征夹具）而非 E1（无特征单写）——后者在回退后仍无键，天然不敏感。
    expect = {'M1 只撤计算门（保留输出门）': 'A3 缺省路径**零次**观测读数调用（成本不变量）',
              'M2 整体回退（计算门 + 两处输出门）': 'E1b 有特征 + 缺省 ⇒ 只有 3 键',
              'M3 CCG 规格行回退为无条件口径': 'E2c CCG「生效条件」行与实现同口径（不再写无条件的「落盘前另取读数」）'}
    for tag, text in _mutations():
        mod = _load_mutant(text, 'm%d' % len(reds))
        _, fail = _suite(mod, label=tag)
        reds[tag] = sorted(fail)
        print('  %s ⇒ 红项 %s' % (tag, reds[tag]))
        if not fail:
            FAILS.append('变异未转红：' + tag)
        elif expect.get(tag) and expect[tag] not in fail:
            FAILS.append('变异红项不含指定项：' + tag)
    print('  变异红项集合：%s' % reds)
    return reds


def main():
    ap = argparse.ArgumentParser(description='#492 观测读数显式开启守卫')
    ap.add_argument('--mutate', action='store_true', help='定点变异自证')
    args = ap.parse_args()
    print('== #492 守卫 ==')
    try:
        _suite(None)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _check('全套判据内异常（fail-closed）', False, str(e)[:100])
    if args.mutate:
        try:
            _run_mutations()
        except Exception as e:
            import traceback
            traceback.print_exc()
            _check('变异腿内异常（fail-closed）', False, str(e)[:100])
    print('=' * 60)
    print('#492 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
