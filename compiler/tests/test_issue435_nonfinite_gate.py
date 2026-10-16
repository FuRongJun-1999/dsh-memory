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

技术审返工（PR #449 复审，ybyz2 09:04）补三面：
  ④ 超 double 域整数面（阻断①）：math.isfinite 对 10**400 抛 OverflowError
     而非返回 False——裸调使 `STORE 信任值 <- 10**400` 由 base 的成功变为
     head 的裸 OverflowError。三处改全函数 _finite_num（OverflowError →
     False）；DE 补操作数预检（隐式 int→float 转换处不再裸穿）。
  ⑤ 知足 运行期阈值面（阻断②）：ZHIZU(inf/-inf/nan/超域 int) 阈值补
     isfinite——-inf 使判定反向（恒达标早退、止 被跳过）、inf 恒不可达、
     nan 恒不达标。
  ⑥ 初值注入面（阻断②）：run(trust=…)/symbols 种子合并终值补 isfinite
     （单点在 reset；分量种子数值但非有限同拒，非数值仍走 N270 丢弃口径）。

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

print('--- (6) 超 double 域整数面：裸 OverflowError 回归收口（返工·阻断①）---')

# ⑥a/⑥b：STORE 写闸——base 成功、返工前 head 裸 OverflowError，须 nonfinite
for tag, name, keep in [
        ('⑥a', '信任值', 0.0),
        ('⑥b', 'P_trust', ('trust_parts', 'P_trust', 0.0))]:
    vm, st, exc = store_try(name, 10 ** 400)
    ok = (isinstance(exc, vmm.VMBuiltinError)
          and getattr(exc, 'kind', None) == 'nonfinite')
    if ok and isinstance(keep, tuple):
        ok = vm.trust_parts[keep[1]] == keep[2]
    elif ok:
        ok = vm.trust_value == keep
    check('%s STORE %s <- 10**400 → nonfinite（非裸 OverflowError）且寄存器不毒化'
          % (tag, name), ok,
          '%s: %s' % (type(exc).__name__ if exc else '未拒', str(exc)[:60]))

# ⑥c：assemble('PUSH_CONST 9**400')（展开十进制 → int 常量）经 STORE 同拒
try:
    code_h = vmm.assemble('PUSH_CONST %d' % 9 ** 400)
    is_int = len(code_h) == 1 and isinstance(code_h[0][1], int)
    try:
        ConditionVM().run(code_h + [(Opcode.STORE_NAME, '信任值'),
                                    (Opcode.ZHI, None)])
        exc_h = None
    except Exception as e:  # noqa: BLE001
        exc_h = e
    check("⑥c assemble('PUSH_CONST 9**400') 经 STORE → nonfinite（非裸 OverflowError）",
          is_int and isinstance(exc_h, vmm.VMBuiltinError)
          and getattr(exc_h, 'kind', None) == 'nonfinite',
          'int常量=%s %s: %s' % (is_int, type(exc_h).__name__ if exc_h else '未拒',
                                 str(exc_h)[:60] if exc_h else ''))
except Exception as e:  # noqa: BLE001
    check("⑥c assemble('PUSH_CONST 9**400') 经 STORE → nonfinite", False,
          'assemble/run 阶段裸异常 %s: %s' % (type(e).__name__, str(e)[:60]))

# ⑥d：DE 超域 int 操作数——隐式 int→float 转换不再裸穿（预检同归 nonfinite）
vm, st, exc = de_try([10 ** 400])
ok = (isinstance(exc, vmm.VMBuiltinError)
      and getattr(exc, 'kind', None) == 'nonfinite'
      and vm.trust_value == 0.0)
check('⑥d 德 10**400 操作数 → nonfinite（非裸 OverflowError）', ok,
      '%s: %s trust=%r' % (type(exc).__name__ if exc else '未拒',
                           str(exc)[:60], vm.trust_value))

# ⑥e：int 寄存器 + 超域 int 累积（Python bigint 和不经转换）→ 累积闸同拒
vm_e = ConditionVM()
try:
    vm_e.run([(Opcode.PUSH_CONST, 5), (Opcode.STORE_NAME, '信任值'),
              (Opcode.DE, 10 ** 400), (Opcode.ZHI, None)])
    exc_e = None
except Exception as e:  # noqa: BLE001
    exc_e = e
check('⑥e 信任值=5 后 德 10**400（bigint 和非有限）→ nonfinite',
      isinstance(exc_e, vmm.VMBuiltinError)
      and getattr(exc_e, 'kind', None) == 'nonfinite'
      and vm_e.trust_value == 5,
      '%s: %s trust=%r' % (type(exc_e).__name__ if exc_e else '未拒',
                           str(exc_e)[:60], vm_e.trust_value))

# 对照：有限 int 不误伤（写面与初值面都不只放 float）
_, st_int, _ = store_try('信任值', 5)
check('⑥f STORE 信任值 <- 5（有限 int）不误伤',
      st_int is not None and st_int['trust'] == 5,
      str(st_int)[:60] if st_int else '')

print('--- (7) 运行期知足阈值面：ZHIZU 非有限阈值拒（返工·阻断②）---')


def zhizu_try(threshold, trust=0.0, addr=3):
    """ZHIZU (threshold, addr) → DE 0.1 → ZHI；返回 (vm, state|None, 异常|None)。"""
    vm = ConditionVM()
    try:
        st = vm.run([(Opcode.ZHIZU, (threshold, addr)),
                     (Opcode.DE, 0.1), (Opcode.ZHI, None)], trust=trust)
        return vm, st, None
    except Exception as e:  # noqa: BLE001
        return vm, None, e


for tag, th in [('⑦a', float('-inf')), ('⑦b', float('inf')),
                ('⑦c', float('nan')), ('⑦d', 10 ** 400)]:
    vm_z, st_z, exc_z = zhizu_try(th)
    ok = (isinstance(exc_z, vmm.VMBuiltinError)
          and getattr(exc_z, 'kind', None) == 'nonfinite')
    check('%s ZHIZU 阈值 %s → nonfinite 拒（判定不得反向/永假）' % (tag, th), ok,
          '%s: %s' % (type(exc_z).__name__ if exc_z else '未拒（早退/未跳）',
                      str(exc_z)[:60]))

# ⑦e：pbc 往返（8 字节 double 保真）——编译期闸管不到的落盘注入面
data_z = serialize([(Opcode.ZHIZU, (float('-inf'), 1)), (Opcode.ZHI, None)])
rt_z = deserialize(data_z)
faithful_z = (rt_z[0][1][0] == float('-inf'))
p_z = os.path.join(_TMP, 'zhizu_ninf.pbc')
with open(p_z, 'wb') as f:
    f.write(data_z)
try:
    run_pbc(p_z)
    exc_p = None
except Exception as e:  # noqa: BLE001
    exc_p = e
check('⑦e pbc 往返 ZHIZU -inf（保真=%s）→ 运行期 nonfinite 拒' % faithful_z,
      faithful_z and isinstance(exc_p, vmm.VMBuiltinError)
      and getattr(exc_p, 'kind', None) == 'nonfinite',
      '%s: %s' % (type(exc_p).__name__ if exc_p else '未拒', str(exc_p)[:60]))

# 对照：有限阈值双向不误伤（早退语义 SEMANTICS.md §3 逐位保持）
_, st_hit, _ = zhizu_try(0.7, trust=0.9)
check('⑦f 知足 0.7 / trust=0.9 达标早退（halt=None、不再累积）',
      st_hit is not None and st_hit['halt'] is None and st_hit['trust'] == 0.9,
      str(st_hit)[:70] if st_hit else '')
_, st_miss, _ = zhizu_try(0.7, trust=0.5)
check('⑦g 知足 0.7 / trust=0.5 未达标走 止（halt=halt、trust=0.6）',
      st_miss is not None and st_miss['halt'] == 'halt'
      and abs(st_miss['trust'] - 0.6) < 1e-12,
      str(st_miss)[:70] if st_miss else '')

print('--- (8) 初值注入面：run/reset 初值非有限拒（返工·阻断②）---')


def init_try(**kw):
    vm = ConditionVM()
    try:
        st = vm.run([(Opcode.ZHI, None)], **kw)
        return vm, st, None
    except Exception as e:  # noqa: BLE001
        return vm, None, e


for tag, kw in [
        ('⑧a', dict(trust=float('inf'))),
        ('⑧b', dict(trust=float('nan'))),
        ('⑧c', dict(trust=10 ** 400)),
        ('⑧d', dict(symbols={'信任值': float('inf')})),
        ('⑧e', dict(symbols={'P_trust': float('nan')}))]:
    vm_i, st_i, exc_i = init_try(**kw)
    ok = (isinstance(exc_i, vmm.VMBuiltinError)
          and getattr(exc_i, 'kind', None) == 'nonfinite' and '有限' in str(exc_i))
    check('%s %s → nonfinite 拒（止 被跳过面收口）' % (tag, kw), ok,
          '%s: %s' % (type(exc_i).__name__ if exc_i else '未拒', str(exc_i)[:60]))

# 对照：有限初值（含 int/种子/分量种子）不误伤；既有口径不回归
_, st_t, _ = init_try(trust=0.4)
check('⑧f run(trust=0.4) 不误伤', st_t is not None and st_t['trust'] == 0.4,
      str(st_t)[:60] if st_t else '')
_, st_s, _ = init_try(symbols={'信任值': 0.5})
check('⑧g 种子 信任值=0.5 归一不误伤', st_s is not None and st_s['trust'] == 0.5,
      str(st_s)[:60] if st_s else '')
_, st_p, _ = init_try(symbols={'P_trust': 0.3})
check('⑧h 分量种子 P_trust=0.3 不误伤',
      st_p is not None and st_p['trust_parts']['P_trust'] == 0.3,
      str(st_p)[:60] if st_p else '')
_, st_d, _ = init_try(symbols={'P_trust': 'abc'})
check('⑧i 非数值分量种子仍静默丢弃（N270 口径不回归）',
      st_d is not None and st_d['trust_parts']['P_trust'] == 0.0,
      str(st_d)[:60] if st_d else '')
_, _, exc_tt = init_try(symbols={'信任值': 'abc'})
check('⑧j 信任值 种子非数值仍按 type 拒（判据分工不混）',
      isinstance(exc_tt, vmm.VMBuiltinError)
      and getattr(exc_tt, 'kind', None) == 'type', str(exc_tt)[:60])

print('\n=== issue #435 非有限闸守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
