# -*- coding: utf-8 -*-
"""test_read_position_undeclared_n271.py · 读取位置未声明即编译期 error（N271）

缺陷（2026-10-05 本会话实跑复现；编号续 N269）：
  『若 甲 大于 0.5，则 止。』（甲未声明）——compiler.api.compile_source
  返回 success=True 零警告（compiler.compile_source strict=True 亦 ok=True）；
  运行期 VM LOAD_NAME 才炸 NameError（名实两套：静态的「隐式自动声明」
  把**读取位置**也当「声明」处理，掩蔽 NameError 到运行期）。
  同族：赋值右值（『甲 = 乙 加 1。』）、调用实参（『结果 = f（乙）；』）、
  条件/比较/循环条件/返回值的未声明标识符——全部静默过审。

修复（N271）：
  name_checker._check_identifier 增位置语义——读取位置（经 _check_expression
  的标识符面：条件/比较/右值/返回/实参/嵌套调用实参）未声明即编译期
  error；**指令操作数位置保留既有宽松**（多词短语如 新信任路径 自动声明
  ＝文档化的有意设计，不得收紧）。函数形参在函数体检查上下文中登记为
  已声明（检查后还原，不污染外层）。两入口一致（compiler.compile_source
  与 api.compile_source 共用 name_checker 前端）。

对照断言：未声明读取→拒（双入口）；先赋后读→过；操作数短语→过；
形参/预定义/嵌套实参/自引用（先赋）各面不误伤。
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.api import compile_source as api_compile
from compiler.compiler import compile_source as vm_compile

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name, ' — ' + detail if detail else ''))


def api_no_crash(src):
    try:
        return api_compile(src), None
    except Exception as e:  # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, e)


def rejected_pair(src, name, needle='未声明'):
    """同一源码双入口均拒（api success=False / compiler strict=True ok=False）。"""
    r, e = api_no_crash(src)
    ok_a = (e is None and r is not None and r.success is False
            and any(needle in x for x in r.errors))
    check('%s api 拒绝（%s）' % (name, needle), ok_a,
          e or 'success=%s errors=%s' % (getattr(r, 'success', None),
                                         [str(x)[:70] for x in getattr(r, 'errors', [])[:1]]))
    try:
        code, rr = vm_compile(src, strict=True)
        ok_v = (rr.get('ok') is False and any(needle in str(x) for x in rr.get('errors', [])))
        check('%s compiler 同拒' % name, ok_v,
              'ok=%s errors=%s' % (rr.get('ok'), [str(x)[:70] for x in rr.get('errors', [])[:1]]))
    except Exception as e2:  # noqa: BLE001
        check('%s compiler 同拒' % name, False, '%s: %s' % (type(e2).__name__, e2))


def legal_pair(src, name):
    r, e = api_no_crash(src)
    ok_a = e is None and r is not None and r.success is True
    check('%s api 仍成功' % name, ok_a,
          e or 'success=%s errors=%s' % (getattr(r, 'success', None),
                                         [str(x)[:70] for x in getattr(r, 'errors', [])[:1]]))
    try:
        code, rr = vm_compile(src, strict=True)
        check('%s compiler 仍成功' % name, rr.get('ok') is True,
              'ok=%s errors=%s' % (rr.get('ok'), [str(x)[:70] for x in rr.get('errors', [])[:1]]))
    except Exception as e2:  # noqa: BLE001
        check('%s compiler 仍成功' % name, False, '%s: %s' % (type(e2).__name__, e2))


print('--- (1) 主守卫：未声明读取不得静默过审（修复前 success=True 零警告）---')

rejected_pair('若 甲 大于 0.5，则 止。', '①a 条件读取（主守卫）')

print('--- (2) 读取位置各面（条件/右值/实参/返回/循环/比较右操作数）---')

rejected_pair('甲 = 乙 加 1。', '②a 赋值右值')
rejected_pair('定义 f（x）：返回 x；\n结果 = f（乙）；\n止。', '②b 实参（语句级调用）')
rejected_pair('定义 f（x）：返回 x；\n结果 = 1 加 f（乙）；\n止。', '②c 实参（表达式内嵌套调用）')
rejected_pair('返回 甲。', '②d 返回值')
rejected_pair('当 计数 小于 3 执行 德 0.1。', '②e 循环条件')
rejected_pair('甲 = 1。\n若 甲 大于 乙，则 止。', '②f 比较右操作数')

print('--- (3) 不误伤：先赋后读 / 操作数短语 / 形参 / 预定义 / 注入面 ---')

legal_pair('甲 = 0.9\n若 甲 大于 0.5，则 止。', '③a 先赋后读')
legal_pair('甲 = 1。\n甲 = 甲 加 1。\n止。', '③b 自引用（先赋）')
legal_pair('道 新信任路径\n止。', '③c 操作数短语 新信任路径（宽松不得收紧）')
legal_pair('术曰：\n1。道 新信任路径；\n2。自然 恢复默认。', '③d 操作数短语（道/自然 双入口合法）')
r3d, e3d = api_no_crash('术曰：\n1。德 累积信任值；\n2。自然 恢复默认。')
check('③d2 德 累积信任值 经 api 入口仍成功（操作数宽松）',
      e3d is None and r3d is not None and r3d.success is True,
      e3d or 'success=%s errors=%s' % (getattr(r3d, 'success', None),
                                       [str(x)[:70] for x in getattr(r3d, 'errors', [])[:1]]))
legal_pair('止 情感权重 等于 阈值。', '③e 操作数位置的普通词（阈值）')
legal_pair('若 信任值 大于 0.2，则 德 0.5。', '③f 预定义符号读取')
legal_pair('定义 f（x）：返回 x 加 1；\n结果 = f（4）；\n止。', '③g 函数读形参')
legal_pair('定义 斐波那契（n）：若 n 小于 2，则 返回 n 否则 返回 斐波那契（n 减 1）加 斐波那契（n 减 2）；\n结果 = 斐波那契（6）；\n止。',
           '③h 递归+嵌套实参（形参面）')
legal_pair('定义 最大公约数（甲，乙）：若 甲 等于 乙，则 返回 甲，否则 若 甲 大于 乙，则 返回 最大公约数（甲 减 乙，乙），否则 返回 最大公约数（甲，乙 减 甲）；\n结果 = 最大公约数（48，36）；\n止。',
           '③i 多形参+嵌套条件')

print('--- (4) 形参作用域隔离：函数体检查后形参还原（不污染外层同名）---')

# 形参名与外层变量同名：外层先声明再定义函数，函数体读形参、外层读外层值
legal_pair('甲 = 7。\n定义 改（甲）：返回 甲 乘 10；\n结果 = 改（2）；\n止。', '④a 形参遮蔽外层同名（两处均合法）')
# 形参不泄漏到函数体之外：函数体之外的读取仍须已声明
rejected_pair('定义 f（x）：返回 x；\n结果 = x。\n止。', '④b 形参不得泄漏出函数体（外层读 x 应拒）')

print('\n=== N271 读取位置未声明守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
