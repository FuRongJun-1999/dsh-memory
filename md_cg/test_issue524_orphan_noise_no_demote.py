# -*- coding: utf-8 -*-
# 功能名：#524 scrub.CONTAMINATION[orphan_noise] 删掉不可达的 demote 声明（零行为改动）
# 生效条件：python -u -X utf8 -m md_cg.test_issue524_orphan_noise_no_demote
# 子功能：A1 正向（声明不含 demote）· A2 反向①（规则仍检出 + weaken 仍执行）· A3 其它规则不受影响 · E1 源码面
# 执行：直接跑；全部 PASS 即通过
# 验证方式：断言全过 + 退出码 0
# 不适用条件：① 腿测「声明里没有不可达动作」，**不测「demote 这个动作本身对不对」**；
#   ② 不覆盖 demote 在其他规则（contradiction/expired）下的行为。
# ★ 三段证明（本件「不可达」的证据，实测于 2026-10）：
#   ① audit(min_severity="info") => n_issues=1（orphan_noise 能造出）
#   ② decontaminate => action="applied" 而 done=["weaken"]（demote 未执行；action 是 applied 不是 skip
#      => 排除「被跳过」语义，是「不可达」）
#   ③ audit.issues[0].fix=["weaken","demote"] 而 done 不含 demote（声明 vs 实际）
# ★ 怎么读 scrub 返回体（踩过的坑）：`done` 在 **actions[i]** 里（子键），**不在顶层** ——
#   顶层取 r.get("done") 恒为 None（`None` 无法区分「键不存在」与「没执行」）。
# ★ min_severity 是**严格大于**语义："low" **不放行** low 级 issue，必须用 "info" 才能看到 orphan_noise。
"""#524 守卫。"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASSED, FAILS = [], []
_REF = {'contradiction': ('high', ('weaken', 'demote')),
        'expired': ('high', ('weaken', 'demote')),
        'not_yet': ('info', ('hint',)),
        'duplicate': ('medium', ('hint',)),
        'unverified': ('info', ('hint',))}


def _check(n, c, d=''):
    if c:
        print('  PASS ' + n)
        PASSED.append(n)
    else:
        print('  FAIL ' + n + '  ' + str(d)[:160])
        FAILS.append(n)


def main():
    from md_cg import scrub as S
    from md_cg.mdcg import MdCG
    print('== #524 守卫 ==')
    C = S.CONTAMINATION
    _check('A1 正向：orphan_noise 的 actions 不含 demote',
           'demote' not in C['orphan_noise'][1], C['orphan_noise'])
    _check('A1b orphan_noise 的 actions 仍含 weaken（没删过头）',
           'weaken' in C['orphan_noise'][1], C['orphan_noise'])
    _check('A3 len(CONTAMINATION) 仍为 6', len(C) == 6, len(C))
    bad = [k for k, v in _REF.items() if C.get(k) != v]
    _check('A3 其它 5 条规则的 (severity, actions) 逐条不变',
           not bad, bad)
    # A2 反向①：规则仍能检出，且 weaken 仍执行
    T = tempfile.mkdtemp(prefix='i524_')
    os.environ.update({'MDCG_ROOT': T + '/brain', 'MDCG_STATE_ROOT': T + '/state',
                       'MDCG_AUX_ROOT': T + '/auxstore', 'MDCG_DATA_ROOT': T + '/datastore',
                       'MDCG_EXPORT_ROOT': T, 'MDCG_SUSTAIN': '0', 'MDCG_SLEEP': '0'})
    cg = MdCG(T + '/lib')
    cg.add('orph', '# 功能名：孤立' + chr(10) + '# 不适用条件：无', layer='contextual', importance=0.1)
    cg.flush()
    rep = S.audit(cg, ['orph'], min_severity='info')
    kinds = [i.get('kind') for i in (rep.get('issues') or [])]
    _check('A2 反向①：audit(min_severity=info) 仍检出 orphan_noise',
           'orphan_noise' in kinds, kinds)
    r = S.decontaminate(cg, ['orph'], kinds=['orphan_noise'], dry_run=False,
                        min_severity='info', override=True)
    acts = r.get('actions') or [{}]
    done = acts[0].get('done') or []
    _check('A2 反向①：weaken 仍执行（done 含 weaken）',
           'weaken' in done, done)
    _check('A2b 无 demote（本件后 done 更不可能含它）', 'demote' not in done, done)
    cg.close()
    # E1 源码面：注释写明了「不可达」
    src = open(os.path.join(_REPO, 'md_cg', 'scrub.py'), encoding='utf-8').read()
    _check('E1 源码面：注释写明 demote 不可达（#524）', '#524' in src and '不可达' in src)
    print('=' * 60)
    print('#524 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for x in FAILS:
        print('  红项：' + x)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
