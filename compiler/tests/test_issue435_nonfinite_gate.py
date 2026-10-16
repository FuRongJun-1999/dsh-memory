# -*- coding: utf-8 -*-
"""test_issue435_nonfinite_gate.py · 德/知足 非有限闸（inf/nan）守卫（issue #435）

缺陷（issue #435 实跑复现）：
  compiler._instr 的 float() 只以「能否转换」判数值，而 Python float() 接受
  'inf'/'nan'/'infinity'（含大小写与符号全形态）——「必须是数值」编译闸被
  穿透：『德 inf』→ ok=True errors=[]、字节码 (DE, inf)、信任寄存器毒化。
  运行期同族：STORE_NAME 写闸只判 isinstance(x,(int,float))（float('inf')
  正是 float ⇒ 放行）；DE 直接 trust_value += arg（无有限性复核）。
  静默错答（比崩溃更危险——编译成功、errors=[]、无 warning）：
    NaN 破坏等式自反性 → 「若 信任值 等于 信任值，则 止。」永不触发；
    inf 恒超任何阈值 → 知足 恒早退，其后所有 止 被跳过。
  传播面：VM 直跑、pbc 落盘往返（8 字节 double 保真）、rust_codegen 的
  Rust 侧执行路径（Rust 面守卫：swarm/tests/test_rust_vm_nonfinite_gate_435.py）。

修复（#435，双闸——N270/N272「编译期/运行期同判」既有模式）：
  ① 编译期单点：德/知足 操作数 float() 后 math.isfinite 拒（SyntaxError
     名实不符）；知足 非数值阈值同收（修复前 float('abc') 的裸 ValueError
     穿透 compile_source 的窄捕获直接上抛调用方）
  ② 运行期写闸：信任值/信任分量 STORE_NAME 补 math.isfinite
     （VMBuiltinError('nonfinite')，拒时寄存器保持有限值不被毒化）
  ③ 运行期 DE：先算后验——NaN/inf 操作数与溢出累积（1e308+1e308）同拒

对照断言：11 个 inf/nan 形态双入口全拒；德 0.5/0/-0.5 与 知足 0.7 的
字节码与终值逐位不变；德 abc/甲乙丙 仍按原判据拦；合法写面不误伤。
"""
import math
import os
import struct
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.compiler import compile_source
from compiler.pbc import compile_to_pbc, deserialize, run_pbc, serialize
from compiler.condition_vm import ConditionVM, Opcode
from compiler import condition_vm as vmm

pass_n = fail_n = 0


# 生效条件：调用须传 name 与 ok，ok 为真时全局 pass_n 加 1、为假时 fail_n 加 1；detail 为真值（非空串）时打印行追加 " — " + detail。
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name,
                         ' — ' + detail if detail else ''))


# issue 双重确认的 11 个穿透形态（inf/INF/Inf/nan/NaN/NAN/infinity/-inf/-nan
# 原九形态 + Infinity/+inf 补全）
NONFINITE_FORMS = ['inf', 'INF', 'Inf', 'nan', 'NaN', 'NAN',
                   'infinity', 'Infinity', '-inf', '-nan', '+inf']

_TMP = tempfile.mkdtemp(prefix='issue435_')

print('--- (1) 编译期闸·双入口：德/知足 非有限全形态拒 ---')

for form in NONFINITE_FORMS:
    # 入口 A：compile_source strict=True（默认入口）
    try:
        code_a, r_a = compile_source('德 %s。\n止。' % form, strict=True)
        ok_a = (code_a is None and r_a.get('ok') is False
                and any('有限' in str(e) for e in r_a.get('errors', [])))
        det_a = 'ok=%s errors=%s' % (r_a.get('ok'),
                                     [str(e)[:60] for e in r_a.get('errors', [])[:1]])
    except Exception as e:  # noqa: BLE001
        ok_a, det_a = False, '裸异常 %s: %s' % (type(e).__name__, e)
    check('①a 德 %s 入口A(strict=True) 拒且报「有限」' % form, ok_a, det_a)

    # 入口 B：compile_to_pbc strict=False（pbc 落盘入口）——须同拒且不落盘
    pbc_path = os.path.join(_TMP, 'a_%s.pbc' % form.replace('+', 'p'))
    try:
        code_b, r_b = compile_to_pbc('德 %s。\n止。' % form, pbc_path, strict=False)
        ok_b = (code_b is None and r_b.get('ok') is False
                and any('有限' in str(e) for e in r_b.get('errors', []))
                and not os.path.exists(pbc_path))
        det_b = 'ok=%s 落盘=%s errors=%s' % (
            r_b.get('ok'), os.path.exists(pbc_path),
            [str(e)[:50] for e in r_b.get('errors', [])[:1]])
    except Exception as e:  # noqa: BLE001
        ok_b, det_b = False, '裸异常 %s: %s' % (type(e).__name__, e)
    check('①b 德 %s 入口B(pbc,strict=False) 同拒且不落盘' % form, ok_b, det_b)

# 知足 同族（阈值面）：inf 恒不可达、nan 比较自反性破坏
for form in ('inf', 'nan', 'infinity'):
    try:
        code_c, r_c = compile_source('知足 %s。\n止。' % form, strict=True)
        ok_c = (code_c is None and r_c.get('ok') is False
                and any('有限' in str(e) for e in r_c.get('errors', [])))
        det_c = 'ok=%s errors=%s' % (r_c.get('ok'),
                                     [str(e)[:60] for e in r_c.get('errors', [])[:1]])
    except Exception as e:  # noqa: BLE001
        ok_c, det_c = False, '裸异常 %s: %s' % (type(e).__name__, e)
    check('①c 知足 %s 阈值拒（恒不可达/自反性破坏）' % form, ok_c, det_c)

# 知足 非数值阈值：结构化拒（修复前 float('abc') 裸 ValueError 穿透窄捕获）
try:
    code_d, r_d = compile_source('知足 abc。\n止。', strict=True)
    ok_d = (code_d is None and r_d.get('ok') is False
            and any('数值' in str(e) for e in r_d.get('errors', [])))
    det_d = 'ok=%s errors=%s' % (r_d.get('ok'),
                                 [str(e)[:60] for e in r_d.get('errors', [])[:1]])
except ValueError as e:
    ok_d, det_d = False, '裸 ValueError 穿透: %s' % e
except Exception as e:  # noqa: BLE001
    ok_d, det_d = False, '裸异常 %s: %s' % (type(e).__name__, e)
check('①d 知足 abc 非数值阈值结构化拒（不再裸 ValueError）', ok_d, det_d)

print('--- (2) 编译期闸不误伤：合法数值逐位不变、原判据不回归 ---')


def de_arg(src):
    code, r = compile_source(src, strict=True)
    if not r.get('ok'):
        return None, r
    for op, arg in code:
        if op == Opcode.DE:
            return arg, r
    return None, r


for lit, want in [('0.5', 0.5), ('0', 0.0), ('1', 1.0), ('-0.5', -0.5)]:
    arg, r = de_arg('德 %s。\n止。' % lit)
    ok = (arg is not None
          and struct.pack('d', arg) == struct.pack('d', want))
    check('②a 德 %s 字节码逐位不变' % lit, ok,
          'arg=%r want=%r' % (arg, want))

code_z, r_z = compile_source('知足 0.7。\n止。', strict=True)
zhizu = [arg for op, arg in (code_z or []) if op == Opcode.ZHIZU]
ok_z = (r_z.get('ok') and len(zhizu) == 1
        and struct.pack('d', zhizu[0][0]) == struct.pack('d', 0.7))
check('②b 知足 0.7 阈值逐位不变', ok_z, 'zhizu=%r ok=%s' % (zhizu, r_z.get('ok')))

# 德 abc / 德 甲乙丙：原「必须是数值」判据（非有限闸之外的面）不回归
for lit in ('abc', '甲乙丙'):
    code_e, r_e = compile_source('德 %s。\n止。' % lit, strict=True)
    ok_e = (code_e is None and r_e.get('ok') is False
            and any('必须是数值' in str(e) and lit in str(e)
                    for e in r_e.get('errors', [])))
    check('②c 德 %s 仍按「必须是数值」拦' % lit, ok_e,
          'errors=%s' % [str(e)[:60] for e in r_e.get('errors', [])[:1]])

# 德 无操作数（默认 0.0）不受影响
code_f, r_f = compile_source('德。\n止。', strict=True)
arg_f = next((a for op, a in (code_f or []) if op == Opcode.DE), 'missing')
check('②d 德 无操作数仍默认 0.0', r_f.get('ok') and arg_f == 0.0,
      'ok=%s arg=%r' % (r_f.get('ok'), arg_f))

print('--- (3) 运行期断言①：STORE_NAME 写闸（手搓字节码/注入面）---')


def store_try(name, value):
    """PUSH_CONST value → STORE_NAME name；返回 (vm, state|None, 异常|None)。"""
    vm = ConditionVM()
    try:
        st = vm.run([(Opcode.PUSH_CONST, value),
                     (Opcode.STORE_NAME, name), (Opcode.ZHI, None)])
        return vm, st, None
    except Exception as e:  # noqa: BLE001
        return vm, None, e


for tag, name, value, keep in [
        ('③a', '信任值', float('inf'), 0.0),
        ('③b', '信任值', float('nan'), 0.0),
        ('③c', 'P_trust', float('inf'), ('trust_parts', 'P_trust', 0.0)),
        ('③d', '情感权重', float('nan'), ('trust_parts', '情感权重', 0.0))]:
    vm, st, exc = store_try(name, value)
    ok = (isinstance(exc, vmm.VMBuiltinError)
          and getattr(exc, 'kind', None) == 'nonfinite'
          and '有限' in str(exc))
    # 拒时寄存器不被毒化（异常先于赋值）
    if ok and isinstance(keep, tuple):
        ok = vm.trust_parts[keep[1]] == keep[2]
    elif ok:
        ok = vm.trust_value == keep
    check('%s %s 写 %s → nonfinite 拒且寄存器不毒化' % (tag, name, value),
          ok, '%s: %s' % (type(exc).__name__ if exc else '未拒', str(exc)[:70]))

# 写闸既有「type」面（字符串）与新「nonfinite」面并存不回归
_, _, exc_t = store_try('信任值', '0.9')
check('③e 信任值 写字符串仍按 type 拒（判据分工不混）',
      isinstance(exc_t, vmm.VMBuiltinError)
      and getattr(exc_t, 'kind', None) == 'type', str(exc_t)[:70])

# 合法有限写不误伤
_, st_ok, _ = store_try('信任值', 0.9)
check('③f 信任值 写 0.9 落寄存器不误伤',
      st_ok is not None and st_ok['trust'] == 0.9, str(st_ok)[:80] if st_ok else '')

print('--- (4) 运行期断言②：DE 累积闸（NaN/inf 操作数与溢出同拒）---')


def de_try(args, trust=0.0):
    vm = ConditionVM()
    try:
        st = vm.run([(Opcode.DE, a) for a in args] + [(Opcode.ZHI, None)],
                    trust=trust)
        return vm, st, None
    except Exception as e:  # noqa: BLE001
        return vm, None, e


for tag, args in [('④a', [float('nan')]), ('④b', [float('inf')]),
                  ('④c', [1e308, 1e308])]:
    vm, st, exc = de_try(args)
    ok = (isinstance(exc, vmm.VMBuiltinError)
          and getattr(exc, 'kind', None) == 'nonfinite')
    # 拒时寄存器保持有限（溢出例：首条 1e308 已过、第二条拒 → 止于 1e308）
    if ok:
        ok = vm.trust_value == 1e308 if tag == '④c' else vm.trust_value == 0.0
    check('%s 德 %s → nonfinite 拒且寄存器保持有限' % (tag, args), ok,
          '%s: %s trust=%r' % (type(exc).__name__ if exc else '未拒',
                               str(exc)[:60], vm.trust_value))

vm_ok, st_ok, _ = de_try([0.5, 0.25])
check('④d 德 0.5/0.25 累积不误伤', st_ok is not None and st_ok['trust'] == 0.75,
      str(st_ok)[:80] if st_ok else '')

print('--- (5) pbc 落盘往返：8 字节 double 保真 + 运行期闸兜底 ---')

for tag, code_rt in [
        ('⑤a', [(Opcode.DE, float('inf'))]),
        ('⑤b', [(Opcode.DE, float('nan'))]),
        ('⑤c', [(Opcode.PUSH_CONST, float('inf')),
                 (Opcode.STORE_NAME, '信任值')])]:
    data = serialize(code_rt)
    # 落盘保真：往返后 inf/nan 仍在（8 字节 double，缺陷面客观存在）
    # → 编译期闸管不到手搓 pbc，须由运行期闸拦
    rt = deserialize(data)
    faithful = any(isinstance(a, float) and not math.isfinite(a) for _, a in rt)
    p = os.path.join(_TMP, 'rt_%s.pbc' % tag[-1])
    with open(p, 'wb') as f:
        f.write(data)
    try:
        run_pbc(p)
        ok, det = False, '未拒'
    except vmm.VMBuiltinError as e:
        ok, det = getattr(e, 'kind', None) == 'nonfinite', str(e)[:70]
    except Exception as e:  # noqa: BLE001
        ok, det = False, '裸异常 %s: %s' % (type(e).__name__, e)
    check('%s pbc 往返（保真=%s）→ 运行期 nonfinite 拒' % (tag, faithful),
          ok and faithful, det)

print('\n=== issue #435 非有限闸守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
