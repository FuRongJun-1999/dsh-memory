# -*- coding: utf-8 -*-
"""test_undefined_call_n236.py · 未定义函数调用编译期拦截（N236）

缺陷（本会话实跑复现）：
  compiler.compile_source('甲 = 未知函数（）。') → ok=True / errors=[]
  code=[('STORE_NAME','甲')]——实参留栈、无 CALL；ConditionVM().run 该码
  → IndexError: pop from empty list（run 仅捕 VMHalt/MemoryError，裸穿透）。
  裸语句形态 '未知函数（）。' → code=[]（整句静默丢弃）。
  api.compile_source 同形：success=True + 残缺 Python 产物，违反
  api.py:192-194 自述契约「不支持的操作必须编译 fail，而非 success＋残缺产物」。

修复：把「被调函数名未定义」升为编译期 error——
  ① name_checker._check_expression 的 CALL_EXPR 分支：expr.name 不在
     function_params（顶层 FUNC_DEF 预扫描）即记 error（两入口共用前端）；
  ② compiler._call_expr：不在 self.funcs 即抛 SyntaxError（compile_source
     已有窄捕获），使 strict=False / pbc 入口亦不产出残缺字节码。

本文件把语义钉死：两入口 ok=False、不产出字节码、VM 不再触达空栈 pop。
纯行为断言，不做源码文本匹配。
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.compiler import compile_source as vm_compile
from compiler.condition_vm import ConditionVM
from compiler.api import compile_source as api_compile

pass_n = fail_n = 0


# 生效条件：调用须传 name 与 ok，ok 为真时全局 pass_n 加 1、为假时 fail_n 加 1；detail 为真值时追加 ' — ' + detail。
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name, ' — ' + detail if detail else ''))


print('--- (1) VM 入口（compiler.compile_source）：ok=False、无残缺字节码 ---')

for tag, src in [('①a', '甲 = 未知函数（）。'), ('①b', '未知函数（）。')]:
    code, r = vm_compile(src)
    check('%s %r → ok=False 且点名未定义函数' % (tag, src),
          r['ok'] is False and code is None
          and any('未定义函数' in e for e in r['errors']),
          'ok=%s code=%r errors=%s' % (r['ok'], code, r['errors'][:1]))

# strict=False 亦不得产出残缺字节码（pbc.compile_to_pbc 默认走此径）
code_f, r_f = vm_compile('甲 = 未知函数（）。', strict=False)
check('①c strict=False 路径仍 ok=False（无残缺字节码）',
      r_f['ok'] is False and code_f is None,
      'ok=%s code=%r errors=%s' % (r_f['ok'], code_f, r_f['errors'][:1]))


print('--- (2) API 入口（api.compile_source）：success=False、无残缺产物 ---')

for tag, src in [('②a', '甲 = 未知函数（）。'), ('②b', '未知函数（）。')]:
    res = api_compile(src)
    check('%s %r → success=False 且不产出代码' % (tag, src),
          res.success is False and res.code == ''
          and any('未定义函数' in e for e in res.errors),
          'success=%s code=%r errors=%s' % (res.success, res.code, res.errors[:1]))


print('--- (3) 不再走 VM 空栈 pop（无字节码可执行 → 无 IndexError）---')

code4, r4 = vm_compile('甲 = 未知函数（）。')
reached_vm = code4 is not None
if reached_vm:
    try:
        ConditionVM().run(code4)
        check('③ 未定义调用不产出可执行字节码', False, 'VM 竟执行了残缺字节码')
    except Exception as exc:  # noqa: BLE001
        check('③ 未定义调用不产出可执行字节码', False,
              'VM 裸穿 %s: %s' % (type(exc).__name__, exc))
else:
    check('③ 未定义调用不产出可执行字节码', True, 'code=None（无空栈 pop 面）')


print('--- (4) 回归对照：合法函数调用仍编译并执行 ---')

# ④a 递归
code_r, r_r = vm_compile('定义 阶乘（n）：若 n 小于 2，则 返回 1，否则 返回 n 乘 阶乘（n 减 1）。\n结果 = 阶乘（4）。\n止。', strict=False)
if r_r['ok']:
    st = ConditionVM().run(code_r)
    check('④a 递归 阶乘(4)=24 仍通过', st['symbols'].get('结果') == 24.0,
          '结果=%s' % st['symbols'].get('结果'))
else:
    check('④a 递归 阶乘(4)=24 仍通过', False, str(r_r['errors'])[:60])

# ④b 前向引用（调用点先于定义点）
code_fw, r_fw = vm_compile('定义 计算（y）：返回 双倍（y）加 1。\n定义 双倍（x）：返回 x 乘 2。\n结果 = 计算（5）。\n止。', strict=False)
if r_fw['ok']:
    st_fw = ConditionVM().run(code_fw)
    check('④b 前向引用互调（双倍(5)+1=11）仍通过', st_fw['symbols'].get('结果') == 11.0,
          '结果=%s' % st_fw['symbols'].get('结果'))
else:
    check('④b 前向引用互调（双倍(5)+1=11）仍通过', False, str(r_fw['errors'])[:60])

# ④c API 入口合法函数定义仍 success=True
res_ok = api_compile('定义 双倍（x）：返回 x 乘 2。')
check('④c API 合法函数定义仍 success=True', res_ok.success is True,
      'success=%s errors=%s' % (res_ok.success, res_ok.errors[:1]))


print('\n=== N236 未定义函数调用拦截守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
