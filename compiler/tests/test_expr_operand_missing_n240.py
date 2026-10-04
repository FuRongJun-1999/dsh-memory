# -*- coding: utf-8 -*-
"""test_expr_operand_missing_n240.py · 表达式操作数缺失不得静默成常量（N240）

缺陷（本会话实跑复现）：
  `parser._parse_expression` 的兜底分支（`else`）在找不到任何操作数 token 时
  返回 `LiteralNode("", "string")`；且其停止集 `_EXPR_STOP` 不含 RPAREN
  （`）`/`)`），右括号被当字符串吃进操作数——
    · `甲 = 1 + 。`      → code 含 ('PUSH_CONST','')；
    · `甲 = （1 + ）。`   → code 含 ('PUSH_CONST','）')；
    · `甲 = 1 +`（行尾截断）→ ('PUSH_CONST','')；
    · `若 甲 大于 。，则 德 0.5。` → ('PUSH_CONST','') 当比较操作数。
  两者（compile_source / api.compile_source）均 ok=True/success=True、errors=[]、
  warnings=[]——缺失的操作数被静默编译为空串常量，产出静默错误结果。

修复：① `_EXPR_STOP` 补入 `TokenType.RPAREN`（右括号即表达式边界）；
  ② 兜底分支收集到的文本为空时记 `self.errors`（表达式缺少操作数），仍返回
  占位 LiteralNode 保持 AST 完整——由既有 errors 通道终止编译（两入口同口径）。

本文件把语义钉死：四形态两入口均编译 fail、不产出字节码；合法括号/算术/
比较一字不动。纯行为断言，不做源码文本匹配。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.compiler import compile_source as vm_compile
from compiler.condition_vm import ConditionVM, Opcode
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


# 生效条件：code 为字节码列表时返回其中所有 PUSH_CONST 的常量值列表，否则空列表。
def pushed_consts(code):
    return [arg for op, arg in (code or []) if op == Opcode.PUSH_CONST]


BAD = [('①a 算术右缺', '甲 = 1 + 。'),
       ('①b 括号内右缺', '甲 = （1 + ）。'),
       ('①c 行尾截断', '甲 = 1 +'),
       ('①d 条件右缺', '甲 = 1。\n若 甲 大于 。，则 德 0.5。')]

print('--- (1) VM 入口：四形态均 ok=False、不产出字节码 ---')
for tag, src in BAD:
    code, r = vm_compile(src, strict=False)
    check('%s %r → ok=False 且记「缺少操作数」' % (tag, src),
          r['ok'] is False and code is None
          and any('缺少操作数' in e for e in r['errors']),
          'ok=%s code=%r errors=%s' % (r['ok'], code, r['errors'][:1]))

print('--- (2) API 入口：success=False、不产出残缺产物 ---')
for tag, src in BAD:
    res = api_compile(src)
    check('%s → success=False 且不产出代码' % tag,
          res.success is False and res.code == ''
          and any('缺少操作数' in e for e in res.errors),
          'success=%s errors=%s' % (res.success, res.errors[:1]))

print('--- (3) 不得再产出空串/「）」常量（缺陷指纹）---')
for tag, src in BAD:
    code, r = vm_compile(src, strict=False)
    consts = pushed_consts(code)
    check('%s 字节码不含空串/右括号常量' % tag,
          code is None or all(c not in ('', '）', ')') for c in consts),
          'PUSH_CONST=%r' % (consts,))

print('--- (4) 回归对照：合法括号/算术/比较一字不动 ---')
code_plain, r_plain = vm_compile('甲 = 1 + 2。', strict=False)
code_paren, r_paren = vm_compile('甲 = （1 + 2）。', strict=False)
check('④a 无括号算式仍编译且无操作数错误',
      r_plain['ok'] and pushed_consts(code_plain) == [1.0, 2.0],
      'ok=%s const=%r err=%s' % (r_plain['ok'], pushed_consts(code_plain),
                                 r_plain['errors'][:1]))
check('④b 括号算式仍编译且与无括号同码',
      r_paren['ok'] and code_paren == code_plain,
      'ok=%s code=%r' % (r_paren['ok'], code_paren))

code_nest, r_nest = vm_compile('甲 = （（1 + 2） 乘 （3 减 1））。', strict=False)
if r_nest['ok']:
    st = ConditionVM().run(code_nest)
    check('④c 嵌套括号 (1+2)*(3-1)=6 仍正确',
          st['symbols'].get('甲') == 6.0, '甲=%s' % st['symbols'].get('甲'))
else:
    check('④c 嵌套括号 (1+2)*(3-1)=6 仍正确', False, str(r_nest['errors'])[:60])

src_cond = '甲 = 1。\n若 甲 大于 0，则 德 0.5。\n止。'
code_cond, r_cond = vm_compile(src_cond, strict=False)
if r_cond['ok']:
    st_c = ConditionVM().run(code_cond)
    check('④d 合法比较仍走对分支（trust=0.5/halt=halt）',
          st_c['trust'] == 0.5 and st_c['halt'] == 'halt',
          'trust=%s halt=%s' % (st_c['trust'], st_c['halt']))
    check('④e 合法比较字节码无空串常量',
          all(c not in ('', '）', ')') for c in pushed_consts(code_cond)),
          'PUSH_CONST=%r' % (pushed_consts(code_cond),))
else:
    check('④d 合法比较仍编译', False, str(r_cond['errors'])[:60])

print('\n=== N240 表达式操作数缺失守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
