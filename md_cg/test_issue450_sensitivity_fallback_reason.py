# -*- coding: utf-8 -*-
# 功能名：#450 写面层闸缺 sensitivity 键回落 internal 的安全语义登记（**零行为改动**）
# 生效条件：python -u -X utf8 -m md_cg.test_issue450_sensitivity_fallback_reason
# 子功能：E 组三条 —— 注释三要素逐条在位（为什么 internal / 安全代价 / 何时改 fail-closed）
# 执行：直接跑；全部 PASS 即通过
# 验证方式：断言全过 + 退出码 0
# 不适用条件：① **本件零行为改动 ⇒ 无退路自证 ⇒ 判据全在 E 组**；② 不覆盖读面 recent_events（属 #447）；
#   ③ 不覆盖 #298 的口径（待核，不阻塞本件）。
# ★ 为什么只钉注释、不改行为：『缺键节点的真实密级』在本机不可观测（活库 3 个 .md 全缺键、layer 也读不到，非有效样本）
#   ⇒ 无法支持『系统性 fail-open』⇒ 按『成本>收益时取小』改为登记理由；且 #359 已是『补理由 + 保留 internal』的先例（向已修的那处靠）。
"""#450 守卫（E 组三条）。"""
import os
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
    print('== #450 守卫：注释三要素 ==')
    src = open(os.path.join(_REPO, 'md_cg', 'protect.py'), encoding='utf-8').read()
    i = src.find('issue #450')
    _check('E0 注释在位（issue #450 标记）', i >= 0)
    blk = src[i:i + 2000] if i >= 0 else ''
    _check('E1 要素①：为什么回落 internal（含 DEFAULT_SENSITIVITY 或 unknown 视同缺省）',
           ('DEFAULT_SENSITIVITY' in blk) or ('unknown 视同缺省' in blk))
    _check('E2 要素②：安全代价（含 fail-open 或 越权）',
           ('fail-open' in blk) or ('越权' in blk))
    _check('E3 要素③：什么条件下改 fail-closed（含 改为 fail-closed 或 缺键且真实密级应为高密级）',
           ('改为 fail-closed' in blk) or ('缺键且真实密级应为高密级' in blk))
    _check('E4 同口径证明：引用 #359 原文（同源）', '#359' in blk and 'private 已被记录' in blk)
    _check('E5 已知缺口：写明 #447 不覆盖', '#447' in blk)
    print('=' * 60)
    print('#450 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
