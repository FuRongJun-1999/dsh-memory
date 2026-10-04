# -*- coding: utf-8 -*-
"""test_call_arity_n237.py · 调用实参条数须与定义形参表一致（N237）

缺陷（本会话实跑复现）：
  '定义 f（甲，乙）：…甲 = f（1）。' → ok=True / errors=[]，
  code 含 CALL(ip, ['甲','乙']) 却只压 1 个实参；ConditionVM().run
  → IndexError: pop from empty list（condition_vm.py:361-366 按
  len(param_names) 连续 pop，栈内不足即裸穿）。
  '定义 g（甲）：…g（1，2）。' → ok=True / errors=[]、CALL(ip, ['甲'])、
  多余的实参永久残留值栈（静默语义错——不崩溃，更难发现）。
  两形态 api.compile_source 均 success=True。

修复：在同一既有判据处（N236 的函数存在性检查）追加「实参条数 vs 形参表」
比对——① name_checker.__init__/check() 的登记面由「函数名集合」升为
  function_params（函数名 → 形参名列表）；_check_expression 的 CALL_EXPR
  分支按表比对，不等即记 error（两入口共用前端）；
  ② compiler._call_expr 发 CALL 前同样比对，不等即抛 SyntaxError
  （compile_source 已有窄捕获），使 strict=False / pbc 入口亦不产出错配字节码。

本文件把语义钉死：少参/多参两形态两入口均编译 fail、不产出字节码、
VM 不再触达空栈 pop 与残留值栈。纯行为断言，不做源码文本匹配。
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


# 少参（定义 2 形参、调用 1 实参 → 修复前 VM pop 空栈）
SRC_FEW = '定义 f（甲，乙）：返回 甲 加 乙。\n结果 = f（1）。\n止。'
# 多参（定义 1 形参、调用 2 实参 → 修复前残留值栈）
SRC_MANY = '定义 g（甲）：返回 甲。\ng（1，2）。\n止。'


print('--- (1) VM 入口（compiler.compile_source）：少参/多参均 ok=False、无字节码 ---')

for tag, src in [('①a 少参', SRC_FEW), ('①b 多参', SRC_MANY)]:
    code, r = vm_compile(src)
    check('%s → ok=False 且点名实参个数不符' % tag,
          r['ok'] is False and code is None
          and any('实参个数不符' in e for e in r['errors']),
          'ok=%s code=%r errors=%s' % (r['ok'], code, r['errors'][:1]))

# strict=False 亦不得产出错配字节码（pbc.compile_to_pbc 默认走此径）
for tag, src in [('①c 少参', SRC_FEW), ('①d 多参', SRC_MANY)]:
    code_f, r_f = vm_compile(src, strict=False)
    check('%s strict=False 路径仍 ok=False' % tag,
          r_f['ok'] is False and code_f is None,
          'ok=%s code=%r errors=%s' % (r_f['ok'], code_f, r_f['errors'][:1]))


print('--- (2) API 入口（api.compile_source）：success=False、无残缺产物 ---')

for tag, src in [('②a 少参', SRC_FEW), ('②b 多参', SRC_MANY)]:
    res = api_compile(src)
    check('%s → success=False 且不产出代码' % tag,
          res.success is False and res.code == ''
          and any('实参个数不符' in e for e in res.errors),
          'success=%s code=%r errors=%s' % (res.success, res.code, res.errors[:1]))


print('--- (3) 不再走 VM 空栈 pop / 不再残留值栈（无字节码可执行）---')

for tag, src in [('③a 少参', SRC_FEW), ('③b 多参', SRC_MANY)]:
    code3, r3 = vm_compile(src)
    if code3 is not None:
        try:
            ConditionVM().run(code3)
            check('%s 不产出可执行字节码' % tag, False, 'VM 竟执行了错配字节码')
        except Exception as exc:  # noqa: BLE001
            check('%s 不产出可执行字节码' % tag, False,
                  'VM 裸穿 %s: %s' % (type(exc).__name__, exc))
    else:
        check('%s 不产出可执行字节码' % tag, True, 'code=None（无 pop/残留面）')


print('--- (4) 回归对照：条数一致的调用仍编译并执行 ---')

# ④a 二参调用求得正确结果
SRC_OK2 = '定义 加（甲，乙）：返回 甲 加 乙。\n结果 = 加（1，2）。\n止。'
code_ok2, r_ok2 = vm_compile(SRC_OK2, strict=False)
if r_ok2['ok']:
    st2 = ConditionVM().run(code_ok2)
    check('④a 二参调用 加(1,2)=3 仍通过', st2['symbols'].get('结果') == 3.0,
          '结果=%s' % st2['symbols'].get('结果'))
else:
    check('④a 二参调用 加(1,2)=3 仍通过', False, str(r_ok2['errors'])[:60])

# ④b 零参调用（定义 名（）：… → 形参表为空，调用亦须零实参）
SRC_OK0 = '定义 七（）：返回 7。\n结果 = 七（）。\n止。'
code_ok0, r_ok0 = vm_compile(SRC_OK0, strict=False)
if r_ok0['ok']:
    st0 = ConditionVM().run(code_ok0)
    check('④b 零参调用 七()=7 仍通过', st0['symbols'].get('结果') == 7.0,
          '结果=%s' % st0['symbols'].get('结果'))
else:
    check('④b 零参调用 七()=7 仍通过', False, str(r_ok0['errors'])[:60])

# ④c 零参函数被传实参亦须拦
code_bad0, r_bad0 = vm_compile('定义 七（）：返回 7。\n结果 = 七（1）。\n止。')
check('④c 零参函数传 1 实参 → ok=False', r_bad0['ok'] is False and code_bad0 is None,
      'ok=%s errors=%s' % (r_bad0['ok'], r_bad0['errors'][:1]))

# ④d 递归（自身调用条数一致）仍通过
SRC_REC = '定义 阶乘（n）：若 n 小于 2，则 返回 1，否则 返回 n 乘 阶乘（n 减 1）。\n结果 = 阶乘（4）。\n止。'
code_rec, r_rec = vm_compile(SRC_REC, strict=False)
if r_rec['ok']:
    st_rec = ConditionVM().run(code_rec)
    check('④d 递归 阶乘(4)=24 仍通过', st_rec['symbols'].get('结果') == 24.0,
          '结果=%s' % st_rec['symbols'].get('结果'))
else:
    check('④d 递归 阶乘(4)=24 仍通过', False, str(r_rec['errors'])[:60])

# ④e API 合法调用仍 success=True
check('④e API 条数一致调用仍 success=True',
      api_compile(SRC_OK2).success is True,
      'errors=%s' % api_compile(SRC_OK2).errors[:1])


print('\n=== N237 调用实参条数守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
