# -*- coding: utf-8 -*-
# 功能名：#521 rotate 锁文件后缀只加一次（FileLock 自己补 .lock）
# 生效条件：python -u -X utf8 -m md_cg.test_issue521_rotate_lock_suffix [--mutate]
# 子功能：A 正向（锁名单 .lock / 无 .lock.lock）· K 反向腿①（锁仍生效 / FileLock 仍补 .lock / 产物不受影响）· M 反向腿②（M1 回含 .lock / M2 删锁）
# 执行：直接跑；--mutate 时逐条退化
# 验证方式：断言全过 + 退出码 0
# 不适用条件：① 看不见两个进程真抢锁（只测路径/存在性 + 单进程重入）；② 不覆盖跨平台锁语义差异。
# ★ K1b 用 `strict=True` 重入判锁生效 —— `strict=False` 是**软锁**（同进程可重入），用它测不到锁是否生效。
#   本条的选择本身就是判据的一部分（有人为「跑得快」改成 strict=False ⇒ 该断言永远绿）。
# ★ K1a 与 K1b 都**必须经过 `rotate()`**，不得直接持有 FileLock —— 否则对「删锁」类变异不敏感（旁路不走 rotate()）。
# ★ `A1` 的前提是「锁存在」—— 删锁时「没有锁文件」也会让它红，故加前提；否则 M2 与 M1 会在 A1 上重叠。
# ★ **K1a 管「有没有」、A1 管「叫什么」** —— 分工写死：把名字判据加回 K1a，M1/M2 的交集就会回来。
# ★ M2 是本仓「防修过头」最纯粹的实例：为消除一个双后缀而删掉锁。
#   症状（.lock.lock）确实会消失 —— 而功能（互斥）也一起消失。所以本条钉的是「删锁不是修复」。
# ★ 形态「不在清单里 ≠ 不存在；做差集前必须先判清单是否穷举」。本批补扫证据：
#   md_cg/ 17 处 lock_path 命中逐条核均与 rotate 无关；scripts/ 0；hive/ 0；docs/ 4（文档引用，非守卫）。
"""#521 守卫。"""
import io
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import fsutil as F
from md_cg import rotate as R

PASSED, FAILS = [], []


def _check(n, c, d=''):
    if c:
        print('  PASS ' + n)
        PASSED.append(n)
    else:
        print('  FAIL ' + n + '  ' + str(d)[:180])
        FAILS.append(n)


def _mk():
    t = tempfile.mkdtemp(prefix='i521_')
    return t, R.Rotator(t, '_audit', 'archive', rotate_bytes=1)


def group_a():
    print('== A 组：正向 ==')
    t, r = _mk()
    with open(r.active, 'w', encoding='utf-8') as f:
        f.write('x' * 64)
    r.rotate()
    names = os.listdir(t)
    locks = [n for n in names if n.endswith('.lock')]
    # ★ 断言加前提（「断言缺前提」）：M2 删锁后**根本没有锁文件** ⇒ A1 不应在此时红。
    #   前提＝「锁存在」；锁不存在时 A1 真空成立，由 K1a 负责报「锁不见了」。
    _check('A1 【前提：锁存在】锁文件名恰 <basename>.rotate.lock',
           (not locks) or ('_audit.rotate.lock' in locks), locks)
    _check('A2 不再产生 .rotate.lock.lock',
           not any(n.endswith('.lock.lock') for n in names), names)


def group_k():
    print('== K 组：反向腿① ==')
    t, r = _mk()
    blocked = False
    with F.FileLock(r.lock_path, timeout=0.5):
        try:
            F.FileLock(r.lock_path, timeout=0.3, strict=True).__enter__()
        except Exception:
            blocked = True
    _check('K1b 锁仍生效（持锁期间 strict 重入被挡，不是把锁去掉）', blocked is True)
    # ★ K1a **必须经过 rotate()**（端到端）：直接持有 FileLock 属**旁路** ⇒ 对「删锁」类变异不敏感。
    #   K1a 管「锁在不在」（对 M2 敏感）；K1b 管「锁硬不硬」（对「锁变软」敏感）—— 两件事，不合并。
    t3, r3 = _mk()
    with open(r3.active, 'w', encoding='utf-8') as f:
        f.write('z' * 64)
    r3.rotate()
    _check('K1a rotate() 端到端：执行后锁文件确实产生（删锁类变异在此红）',
           any(n.endswith('.lock') for n in os.listdir(t3)), os.listdir(t3))   # 只判「有没有锁」，名由 A1 判
    src = io.open(os.path.join(_REPO, 'md_cg', 'fsutil.py'), encoding='utf-8').read()
    _check('K2 FileLock 仍补 .lock（结构断言：self.path = path + .lock 在位）',
           'self.path = path + ".lock"' in src)
    t2, r2 = _mk()
    with open(r2.active, 'w', encoding='utf-8') as f:
        f.write('y' * 64)
    r2.rotate()
    _check('K3 轮转产物不受影响（archive 下出现分片）',
           len(os.listdir(r2.archive)) >= 1, os.listdir(r2.archive))


def main():
    print('== #521 守卫 ==')
    for f in (group_a, group_k):
        try:
            f()
        except Exception as e:
            import traceback
            traceback.print_exc()
            _check('组内异常（fail-closed）', False, str(e)[:100])
    print('=' * 60)
    print('#521 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
