# -*- coding: utf-8 -*-
# 功能名：#278 (c) 分层：负条件 L1 判「是否易混」、L2 判「是否重复」
# 生效条件：python -u -X utf8 -m md_cg.test_issue278_negative_layering
# 子功能：A 正向（prompt 口径负条件不再被拒）· K 反向腿①（L2 仍拦重复 / 域外行为不变 / 两类样本行为不同）
# 执行：直接跑；全部 PASS 即通过
# 验证方式：断言全过 + 退出码 0
# 不适用条件：① 不判「语义是否真的邻近」（L1 只判词面/召回面交集）；② 不新建跨节点去重（L2 的「与已固化节点重复」只保留接口语义）；③ 不覆盖 grounding 阈值本身（0.34 那半不在本件）。
# ★ M2（撤 no_conflict）红 {K1,K3} 中的 **K3 是连带**：K3 断言「两类样本结果不同」，撤 L2 后两类自然相同。
#   **独立面是 K1** —— 故回退自证写「M2 的独立面是 K1；K3 是连带」，不写「M2 命中两项」。
# ★ 形态名「判据自相矛盾」：P=邻近易混（共享领域词）、Q=词面覆盖<0.5（不共享）⇒ P∧Q 无解 ⇒ 系统性拒绝。修法＝分层，不是二选一。
# ★ 形态名「机制在位、数据待补」：绿的原因若是「语料刚好覆盖」，那不是判据强，是语料窄（见 #362c 空表）。
"""#278 (c) 分层守卫。"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import consolidate as C

PASSED, FAILS = [], []
# ★ 夹具**照抄** test_issue278_neg_window.py:59-67（不猜语料；改夹具须两边同改）
BODY = ("dsh-memory 插件升级流程：pnpm 管理依赖，caret 版本写法会让升级范围扩大；"
        "profile 插件升级时须先冻结 lockfile；dsh-memory 插件升级后要重跑门禁。")
POS = ["dsh-memory 插件升级", "pnpm 依赖升级"]
NEAR = ["依赖写 caret", "非 dsh-memory 插件升级", "其他 profile 插件升级"]
FAR = ["在 Linux 或 macOS 上部署时", "面向公开文档的读者"]


def _check(name, cond, detail=''):
    if cond:
        print('  PASS ' + name)
        PASSED.append(name)
    else:
        print('  FAIL ' + name + '  ' + str(detail)[:200])
        FAILS.append(name)


def group_a():
    print('== A 组：正向（L1 允许共享领域词）==')
    for t in NEAR:
        rep = C.replay_check(POS, [t], BODY)
        _check('A 邻近易混负条件放行：' + t, rep['neg_separated'] is True, rep)


def group_k():
    print('== K 组：反向腿① ==')
    # K1 只钉 **L2 面**（no_conflict is False）；**L1 面由 A 组三条钉**。本断言曾同时断言
    # neg_separated=True —— 那使 M1（L1 回带闸）与 A 组重叠，故拆。
    r1 = C.replay_check(POS, ['非 dsh-memory 插件升级'], BODY)
    _check('K1 L2 仍拦「与本条生效条件重叠」的负条件（no_conflict=False）',
           r1['no_conflict'] is False, r1)   # K1 只钉 L2 的面（A 组已钉 L1，避免一个断言承载两个语义）
    r2 = C.replay_check(POS, ['依赖写 caret'], BODY)
    _check('K2 域内但不同条 ⇒ L2 不拦（no_conflict=True）',
           r2['no_conflict'] is True, r2)
    _check('K3 两类样本行为不同 ⇒ L1 与 L2 未混',
           (r1['no_conflict'] is False) != (r2['no_conflict'] is False))
    for t in FAR:
        rep = C.replay_check(POS, [t], BODY)
        _check('K4 完全域外行为不变（neg_separated 仍 True 且不因 L1 改动而变）：' + t,
               rep['neg_separated'] is True, rep)


def main():
    print('== #278 (c) 分层守卫 ==')
    for f in (group_a, group_k):
        try:
            f()
        except Exception as e:
            import traceback
            traceback.print_exc()
            _check('组内异常（fail-closed）', False, str(e)[:100])
    print('=' * 60)
    print('#278 分层守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
