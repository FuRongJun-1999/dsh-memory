# -*- coding: utf-8 -*-
"""test_issue434_zhizu_value_gate.py · 知足 阈值非数值结构化拒（#434）

缺陷（issue #434，P0；2026-10-16 本会话实跑复现）：
  compiler/compiler.py _instr 的 ZHIZU 分支对操作数裸调 float(val)——
  『知足 验证单元』/『知足 abc』/『知足 情感权重』三形态均抛裸
  ValueError: could not convert string to float，穿透 compile_source
  对 SyntaxError 的窄捕获直接上抛调用方（strict=True/False 皆然；
  pbc.compile_to_pbc / analyzer.analyze_source 同汇此单点，一并裸穿）。
  同族对照：DE 分支（:179-185）有 try/except 结构化拒——同输入
  『德 验证单元』返回 ok=False errors=[…（名实不符）]。

  边界核验：#449（fix/compiler-float-nan-gate 分支，fb60b581）已顺带
  收口本缺陷（isfinite 主修 #435），但该分支未合入本分支——本守卫
  在本分支独立钉住 ValueError 面（措辞与 fb60b581 逐字对齐，便于
  两分支会师时免解冲突；inf/nan isfinite 面归 #435 守卫，此处不涉）。

  守卫盲区实证（issue #434）：api.compile_source 是独立 Python 代码
  生成管线（不经字节码 Compiler），同输入 success=True——两入口结论
  相反属管线分工，本守卫只钉字节码族四入口
  （compile_source 双 strict / compile_to_pbc / analyze_source；
  debugger 面 import 的同为 compile_source）。

修复（#434）：
  ZHIZU 分支对齐 DE 分支——float() 包 try/except (TypeError,
  ValueError) 抛 SyntaxError（compile_source 窄捕转结构化 errors），
  报文沿用「以名举实」口径：L{n} 知足 的阈值必须是数值，得到 '{val}'
  （名实不符）。

对照断言：三形态+句读变体 × 双 strict 全结构化拒（无异常逃逸）；
compile_to_pbc / analyze_source 入口同拒且拒时 .pbc 不落盘；
数值操作数（0.7/1/0/0.15）与裸 知足、完整五指令程序字节码
serialize 逐位不变（锚点为修复前实跑快照）。
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.compiler import compile_source
from compiler.pbc import compile_to_pbc, serialize
from compiler.analyzer import analyze_source

pass_n = fail_n = 0

# 修复前实跑快照（serialize 十六进制）——反向逐位不变锚点
BASELINE = {
    '知足 0.7': '05005a48495a5505666666666666e63f0100000000000000',
    '知足 1': '05005a48495a5505000000000000f03f0100000000000000',
    '知足 0': '05005a48495a550500000000000000000100000000000000',
    '知足 0.15': '05005a48495a5505333333333333c33f0100000000000000',
    '知足': '05005a48495a550500000000000000000100000000000000',
}
FIVE_INSTR_SRC = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。若 信任值 大于 0.3，则 德 0.5；
3。知足 0.7；
4。止。"""
FIVE_INSTR_HEX = ('0c00454e5445525f53485559554500030044414f040f00e696b0e4bfa1'
                  'e4bbbbe8b7afe5be8409004c4f41445f4e414d45040900e4bfa1e4bb'
                  'bbe580bc0a00505553485f434f4e535403333333333333d33f0600434'
                  'd505f4754000d004a554d505f49465f46414c53450208000000000000'
                  '000200444503000000000000e03f04004a554d500208000000000000'
                  '0005005a48495a5505666666666666e63f0b0000000000000003005a'
                  '4849000b0052455455524e5f5354455000')


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name,
                         ' — ' + detail if detail else ''))


def compile_no_crash(src, strict):
    """compile_source 不得让任何异常逃逸（#434 主判据）。"""
    try:
        return compile_source(src, strict=strict), None
    except Exception as e:  # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, e)


print('--- (1) 正向：三形态 + 句读变体 × 双 strict 全结构化拒 ---')
for src in ('知足 验证单元', '知足 abc', '知足 情感权重', '知足 验证单元。'):
    for strict in (True, False):
        (code, r), e = compile_no_crash(src, strict)
        ok = (e is None and r['ok'] is False and code is None
              and len(r['errors']) == 1
              and '知足 的阈值必须是数值' in r['errors'][0]
              and '名实不符' in r['errors'][0])
        check('『%s』strict=%s 结构化拒' % (src, strict), ok,
              e or 'errors=%s' % r['errors'][:1])

print('--- (2) 同族对照：德 分支既有结构化拒不回归 ---')
(code_de, r_de), e_de = compile_no_crash('德 验证单元', True)
check('『德 验证单元』仍结构化拒（同族口径）',
      e_de is None and r_de['ok'] is False
      and any('德 的操作数必须是数值' in x and '名实不符' in x
              for x in r_de['errors']),
      e_de or 'errors=%s' % r_de['errors'][:1])

print('--- (3) pbc / analyzer 入口同拒（拒时 .pbc 不落盘）---')
with tempfile.TemporaryDirectory() as td:
    pbc_path = os.path.join(td, 'reject.pbc')
    try:
        code_p, r_p = compile_to_pbc('知足 验证单元', pbc_path)
        e_p = None
    except Exception as e:  # noqa: BLE001
        code_p, r_p, e_p = None, None, '%s: %s' % (type(e).__name__, e)
    check('compile_to_pbc 结构化拒 + 不落盘',
          e_p is None and code_p is None and r_p['ok'] is False
          and '知足 的阈值必须是数值' in r_p['errors'][0]
          and not os.path.exists(pbc_path),
          e_p or 'errors=%s exists=%s' % (r_p['errors'][:1],
                                          os.path.exists(pbc_path)))
try:
    dump_a, r_a = analyze_source('知足 abc')
    e_a = None
except Exception as e:  # noqa: BLE001
    dump_a, r_a, e_a = None, None, '%s: %s' % (type(e).__name__, e)
check('analyze_source 结构化拒',
      e_a is None and dump_a is None and r_a['ok'] is False
      and '知足 的阈值必须是数值' in r_a['errors'][0],
      e_a or 'errors=%s' % r_a['errors'][:1])

print('--- (4) 反向：数值操作数 / 裸 知足 / 五指令程序逐位不变 ---')
for src, hex_exp in BASELINE.items():
    (code, r), e = compile_no_crash(src, True)
    ok = (e is None and r['ok'] is True
          and serialize(code).hex() == hex_exp)
    check('『%s』字节码逐位不变' % src, ok,
          e or 'len=%d' % (len(serialize(code)) if code else -1))
(code5, r5), e5 = compile_no_crash(FIVE_INSTR_SRC, True)
check('五指令程序（含 知足 0.7）字节码逐位不变',
      e5 is None and r5['ok'] is True
      and serialize(code5).hex() == FIVE_INSTR_HEX,
      e5 or 'len=%d' % (len(serialize(code5)) if code5 else -1))

print('\n=== #434 知足阈值数值闸守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
