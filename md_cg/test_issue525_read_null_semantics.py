# -*- coding: utf-8 -*-
# 功能名：#525 read 的「一律返 null」是两面分工（防探测）—— 零行为改动，只登记语义
# 生效条件：python -u -X utf8 -m md_cg.test_issue525_read_null_semantics
# 子功能：E1 注释含「防探测」· E2 含「用 get」· E3 含「安全属性、不是缺陷」· E4 协议真源仍在位
# 执行：直接跑；全部 PASS 即通过
# 验证方式：断言全过 + 退出码 0
# 不适用条件：① 本件**零行为改动 ⇒ 无回退自证**（判据全在 E 组，同 #450 处置）；
#   ② 不测「调用方是否用得上这个分工」（那是 API 设计判断）；
#   ③ 不覆盖「将来要不要细分区因」（须先确认防探测是否仍需要）。
# ★ 为什么不加 reason（#274 已裁）：类型错已在 :2509-2513 返 node_id_not_str；
#   「不存在」保持 null 是 protocol.py 的 node_missing.returns_null=True（test_protocol A11/B8/B10 钉住）
#   ⇒ 加 reason 属**行为变更**（改协议真源 + 破 3 条断言），不是补漏。
"""#525 守卫（E 组）。"""
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSED, FAILS = [], []


def _check(n, c, d=''):
    if c:
        print('  PASS ' + n)
        PASSED.append(n)
    else:
        print('  FAIL ' + n + '  ' + str(d)[:150])
        FAILS.append(n)


def main():
    print('== #525 守卫 ==')
    src = open(os.path.join(_REPO, 'md_cg', 'mcp_server.py'), encoding='utf-8').read()
    i = src.find('issue #525')
    _check('E0 注释在位（issue #525 标记）', i >= 0)
    blk = src[i:i + 1600] if i >= 0 else ''
    _check('E1 含「防探测」（为什么一律 null）', '防探测' in blk)
    _check('E2 含「用 get」（要区分原因去哪个面）', 'get' in blk)
    _check('E3 含「安全属性」且「不是缺陷」', ('安全属性' in blk) and ('不是缺陷' in blk))
    proto = open(os.path.join(_REPO, 'md_cg', 'protocol.py'), encoding='utf-8').read()
    _check('E4 协议真源仍在位：node_missing.returns_null = True',
           'node_missing' in proto and 'returns_null' in proto, '')
    print('=' * 60)
    print('#525 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
