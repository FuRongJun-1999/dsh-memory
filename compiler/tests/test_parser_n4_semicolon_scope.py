# -*- coding: utf-8 -*-
"""test_parser_n4_semicolon_scope.py · 『；』续接作用域守卫（v3 N4 legacy）

缺陷（v3 N4 多轮留账）：_parse_condition 的 then/else 体与 _parse_func_def 的
函数体用 _parse_single_statement 单语句解析，而 _parse_loop 的循环体用
_parse_statement_or_block（『。终止/；续接』正确实现，缺陷① 2026-09-14）——
同一分隔符两套语义：

  『若 X 则 A；B。』 的 B 不进 then 体，静默漂移为顶层无条件执行
    （AST: then=单语句 top=2 条；api 产物 B 缩进 0 格；VM 字节码
    [... JUMP_IF_FALSE, DE 0.1, JUMP, DE 0.2] —— DE 0.2 恒执行）；
  『定义 f（）：A；B。』 的 B 同样泄漏顶层。
  双入口假成功零诊断，条件执行语义静默反转为恒执行——比崩溃更危险。

修复语义：then/else/函数体三处改调同文件既有 _parse_statement_or_block，
与循环体同一分隔符语义（SEMANTICS.md §2 既有契约：「循环体/条件体若要写
多条语句，用分号」）；单语句形态经 len==1 分支原样返回语句本身，既有合法
输入编译输出逐位不变；『。』终止语义不变（B 不被吞进条件体，缺陷①不回归）。

本文件把这些语义钉死，防止回归。
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.api import compile_source as api_compile
from compiler.compiler import compile_source as vm_compile
from compiler.parser import parse_tokens, NodeType
from compiler.lexer import tokenize

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name, ' — ' + detail if detail else ''))


def parse_shape(src):
    """返回 (顶层语句数, 首语句节点, 语法错误列表)"""
    tokens, _ = tokenize(src)
    errs = []
    ast = parse_tokens(tokens, errs)
    stmts = list(getattr(ast, 'statements', []))
    return len(stmts), (stmts[0] if stmts else None), errs


def body_len(node):
    """then/else/body 字段的语句数（None=0；单语句=1；Block=N）"""
    if node is None:
        return 0
    if node.type == NodeType.BLOCK:
        return len(node.statements)
    return 1


print('--- (1) then 体：「；」续接须留在条件体内（缺陷主形态）---')

n, s, e = parse_shape('若 甲 大于 0，则 德 0.1；德 0.2。')
check('①a then 体含两条语句', body_len(s.then_body) == 2,
      'then=%s len=%d' % (s.then_body.type.name, body_len(s.then_body)))
check('①b 不再泄漏顶层（顶层仅 1 条语句）', n == 1, 'top=%d' % n)
check('①c 零语法错误（合法书写）', not e, str(e[:1]))

print('--- (2) else 体与函数体同语义 ---')

n2, s2, _ = parse_shape('若 甲 大于 0，则 德 0.1 否则 德 0.2；德 0.3。')
check('②a else 体含两条语句', body_len(s2.else_body) == 2,
      'else=%s len=%d' % (s2.else_body.type.name, body_len(s2.else_body)))
check('②b else 体不泄漏顶层', n2 == 1, 'top=%d' % n2)

n3, s3, _ = parse_shape('定义 f（）：道 路径；德 0.5。')
check('②c 函数体含两条语句', body_len(s3.body) == 2,
      'fnbody=%s len=%d' % (s3.body.type.name, body_len(s3.body)))
check('②d 函数体不泄漏顶层', n3 == 1, 'top=%d' % n3)

print('--- (3) 循环体对照 + 单语句形态不回归（len==1 原样返回）---')

n4, s4, _ = parse_shape('当 甲 大于 0 执行 德 0.1；德 0.2。')
check('③a 循环体仍 Block[2]（既有正确行为）', body_len(s4.body) == 2 and n4 == 1,
      'body len=%d top=%d' % (body_len(s4.body), n4))

n5, s5, _ = parse_shape('若 甲 大于 0，则 德 0.1。')
check('③b then 单语句仍为语句本身（非 Block）',
      n5 == 1 and s5.then_body is not None and s5.then_body.type == NodeType.INSTRUCTION_STMT,
      'then=%s' % s5.then_body.type.name)

n6, s6, _ = parse_shape('若 甲 大于 0，则 德 0.1。德 0.2。')
check('③c 「。」终止不回归——B 不被吞进条件体（缺陷①）',
      n6 == 2 and body_len(s6.then_body) == 1,
      'top=%d then_len=%d' % (n6, body_len(s6.then_body)))

n7, s7, _ = parse_shape('定义 f（）：德 0.5。')
check('③d 函数体单语句仍为语句本身', n7 == 1 and body_len(s7.body) == 1,
      'fnbody len=%d top=%d' % (body_len(s7.body), n7))

print('--- (4) 双入口产物语义：B 须受条件门控 ---')

r8 = api_compile('若 甲 大于 0，则 德 0.1；德 0.2。')
_indented = [ln for ln in r8.code.splitlines() if '_runtime.accumulate_trust' in ln]
check('④a api success=True', r8.success is True, 'errors=%s' % r8.errors[:1])
check('④b 两处 德 调用均缩进（在 if 体内）',
      len(_indented) == 2 and all(ln.startswith('    _runtime') for ln in _indented),
      str(_indented))

code8, res8 = vm_compile('若 甲 大于 0，则 德 0.1；德 0.2。')
ops8 = [op.name for op, _ in code8]
check('④c vm ok=True', res8['ok'] is True, str(res8.get('errors', [])[:1]))
check('④d vm 字节码：两个 DE 均在 JUMP_IF_FALSE 与 JUMP 之间（同受门控）',
      ops8[:4] == ['LOAD_NAME', 'PUSH_CONST', 'CMP_GT', 'JUMP_IF_FALSE']
      and ops8[4:6] == ['DE', 'DE'] and ops8[6] == 'JUMP',
      str(ops8))

print('--- (5) 步骤号边界不回归：「；」后紧跟步骤号仍终止块 ---')

n9, s9, _ = parse_shape('术曰：1。若 甲 大于 0，则 德 0.1；2。德 0.5。')
_shuyue = s9
_steps = _shuyue.steps if _shuyue is not None and _shuyue.type == NodeType.SHUYUE else []
_cond = None
for _st in _steps:
    if _st.statement is not None and _st.statement.type == NodeType.CONDITION_STMT:
        _cond = _st.statement
check('⑤a then 体在步骤号前终止（不吞步骤 2）',
      _cond is not None and body_len(_cond.then_body) == 1 and len(_steps) == 2,
      'steps=%d then_len=%s' % (len(_steps),
                                body_len(_cond.then_body) if _cond else 'n/a'))

print('\n=== N4 『；』续接作用域守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
