# -*- coding: utf-8 -*-
# 功能名：#434/#435 编译期「必须是数值」闸的三层收口（本批补 pbc 汇编路径）
# 生效条件：python -u -X utf8 -m md_cg.test_issue434_435_float_gate
# 子功能：A1 主路径(_finite_operand) · A2 pbc 旁路径(本批) · A3 双路径不误伤 · A4 见 docstring(M1)
# 执行：直接跑；全部 PASS 即通过
# 验证方式：断言全过 + 退出码 0
# 不适用条件：① 腿测「float() 输入闸」，**不测「Opcode.DE 的语义是否正确」**；
#   ② 不测运行期写闸（condition_vm.py:92 的 isfinite 由既有守卫负责）。
# ★ 三层归属（「落地 > 声称」）：
#   本批：condition_vm.py 的两处 isfinite（pbc 汇编路径 DE/ZHIZU）
#   非本批：compiler.py:45 的 isfinite（编译期主路径，已存在）
#   非本批：condition_vm.py:92 的 isfinite（运行期写闸，已存在）
# ★ A1 的 abc 条是**不变式断言**：它走 except (TypeError, ValueError) 那条，与 isfinite 无关
#   ⇒ 在 M1（撤 isfinite）下它**仍绿是正确的** ⇒ 它的「会红条件」= **撤 except (TypeError, ValueError) 那半**
#   ⇒ 若有人以为「M1 漏了它」⇒ 那是误读：M1 的期望红项里**本就不该有它**。
# ★ M1（撤三处）：compiler.py:45（**非本批**）+ condition_vm.py 两处（本批）
#   —— 变异只为验证判据，不为归属。期望 A1 与 A2 都红；A3 应仍绿（正常值不依赖 isfinite）。
"""#434/#435 守卫：三层数值闸。"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from compiler.compiler import _finite_operand
from compiler.condition_vm import assemble, Opcode

PASSED, FAILS = [], []


def _check(n, c, d=''):
    if c:
        print('  PASS ' + n)
        PASSED.append(n)
    else:
        print('  FAIL ' + n + '  ' + str(d)[:160])
        FAILS.append(n)


def _raises(fn, *a):
    try:
        fn(*a)
        return None
    except Exception as e:
        return e


def group_a():
    print('== A1 主路径 compiler._finite_operand（非本批，回归面）==')
    for v in ('abc', 'inf', 'nan', '1e999'):
        e = _raises(_finite_operand, v, 1, '德')
        _check('A1 _finite_operand(%r) => SyntaxError' % (v,),
               e is not None and type(e).__name__ == 'SyntaxError', repr(e)) 
    _check('A1 正常值 0.7 通过且数值正确', _finite_operand('0.7', 1, '德') == 0.7)
    print('== A2 pbc 旁路径（本批新增）==')
    for src, tag in (('DE inf', 'DE inf'), ('DE nan', 'DE nan'),
                     ('DE -inf', 'DE -inf'), ('ZHIZU inf', 'ZHIZU inf')):
        e = _raises(assemble, src)
        msg = str(e) if e is not None else ''
        _check('A2 pbc %s => SyntaxError' % tag,
               e is not None and type(e).__name__ == 'SyntaxError', repr(e))
        _check('A2 pbc %s 的消息带层前缀 pbc（两层可分辨）' % tag, 'pbc' in msg, msg[:80])
    print('== A3 不误伤（两条路径都测）==')
    _check('A3 pbc DE 0.7 => [(Opcode.DE, 0.7)]',
           assemble('DE 0.7') == [(Opcode.DE, 0.7)], assemble('DE 0.7'))
    _check('A3 pbc DE -1.5 => [(Opcode.DE, -1.5)]',
           assemble('DE -1.5') == [(Opcode.DE, -1.5)], assemble('DE -1.5'))
    _check('A3 主路径 0 / -1 / 1.5 / 1e9 全通过',
           all(_finite_operand(v, 1, 'x') == float(v) for v in ('0', '-1', '1.5', '1e9')))


def main():
    print('== #434/#435 守卫 ==')
    try:
        group_a()
    except Exception as e:
        import traceback
        traceback.print_exc()
        _check('组内异常（fail-closed）', False, str(e)[:100])
    print('=' * 60)
    print('#434/#435 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
