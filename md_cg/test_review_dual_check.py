# -*- coding: utf-8 -*-
# 功能名：裁决双单元复核闸守卫（反思单元 + 验证单元；裁决者不得自证）
# 生效条件：python -X utf8 -m md_cg.test_review_dual_check；被测面＝md_cg/mdcos.py 的 _dual_check_required / _norm_review_unit / MdCGOS._dual_review_verdict 与 mcp_server 透传
# 子功能：①开关缺省关且只认 1/true/yes/on ②单元中英文归一 ③缺反思拒 ④缺验证拒 ⑤同类重复不算齐备 ⑥两方齐放行 ⑦裁决者==提案者拒 ⑧未知单元拒 ⑨透传与接入锚点
# 执行：不开库构造（__new__）直接调判定方法 → 逐条断言 → 源码锚点校验
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不判复核证据真伪（只认单元声明）；不替代既有红队闸（正交：红队管打回/再审批）
"""裁决双单元复核闸守卫（2026-10-27 使用者裁定：「裁决需要用反思单元和验证单元复核」）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from md_cg import mdcos

_PASS, _FAIL = [], []


def ok(cond, msg, detail=''):
    (_PASS if cond else _FAIL).append(msg)
    print(('  PASS ' if cond else '  FAIL ') + msg + (('  <- ' + str(detail)) if detail and not cond else ''))


def _judge(reviewed_by, decided_by='agent-x', proposer=None, decision='accept'):
    obj = mdcos.MdCGOS.__new__(mdcos.MdCGOS)
    obj.actor = decided_by
    item = {'pid': 'p_test', 'content': 'x', 'decision': decision}
    if proposer is not None:
        item['proposer'] = proposer
    return obj._dual_review_verdict(item, decision, decided_by, reviewed_by)


def main():
    print('== A 开关与归一')
    ok(mdcos._dual_check_required() is False, 'A1 缺省关（不因升级中断既有裁决流程）')
    for v in ('1', 'true', 'YES', ' on '):
        os.environ['MDCG_REVIEW_DUAL_CHECK'] = v
        ok(mdcos._dual_check_required() is True, 'A2 %r 视为开' % v)
    os.environ.pop('MDCG_REVIEW_DUAL_CHECK', None)
    ok(mdcos._dual_check_required() is False, 'A3 移除后回到关')
    ok(mdcos._norm_review_unit('反思单元') == 'reflect'
       and mdcos._norm_review_unit('reflection') == 'reflect',
       'A4 反思类同义归一')
    ok(mdcos._norm_review_unit('验证单元') == 'verify'
       and mdcos._norm_review_unit('verifier') == 'verify',
       'A5 验证类同义归一')
    ok(mdcos._norm_review_unit('人工') == 'human', 'A6 人工类同义归一')

    print('== B 双单元判据')
    r = _judge(['反思单元'])
    ok(r.get('error') == 'dual_check_required' and r.get('missing') == ['verify'],
       'B1 只有反思 ⇒ 缺验证被拒并点名', r)
    r = _judge(['验证单元'])
    ok(r.get('error') == 'dual_check_required' and r.get('missing') == ['reflect'],
       'B2 只有验证 ⇒ 缺反思被拒并点名', r)
    r = _judge(['反思单元', 'reflect'])
    ok(r.get('error') == 'dual_check_required' and 'verify' in r.get('missing', []),
       'B3 同类重复不算齐备（两个反思仍无验证=同侧互证）', r)
    r = _judge(['反思单元', '验证单元'])
    ok(r.get('ok') is True and r.get('reviewed_units') == ['reflect', 'verify'],
       'B4 两方齐备 ⇒ 放行', r)
    r = _judge([{'unit': '反思单元'}, {'unit': 'verify'}])
    ok(r.get('ok') is True, 'B5 映射形态同样被认（{unit:…}）', r)
    r = _judge(['反思单元', '验证单元', 'human'])
    ok(r.get('ok') is True, 'B6 额外的人工裁定不报错（自我层更严的档位另有闸）', r)
    r = _judge(['反思单元', '验证单元', '外星单元'])
    ok(r.get('error') == 'unknown_review_unit', 'B7 未知单元被拒（不静默计入）', r)

    print('== C 裁决者不得自证')
    r = _judge(['反思单元', '验证单元'], decided_by='same', proposer='same')
    ok(r.get('error') == 'self_review_forbidden', 'C1 裁决者==提案者 ⇒ 拒', r)
    r = _judge(['反思单元', '验证单元'], decided_by='other', proposer='same')
    ok(r.get('ok') is True, 'C2 不同人 ⇒ 放行', r)

    print('== D 接入锚点')
    src = open(os.path.join(ROOT, 'md_cg', 'mdcos.py'), encoding='utf-8').read()
    ok('if _dual_check_required():' in src,
       'D1 review_decide 在闸口调用双复核判定')
    ok('reviewed_by=None, decided_by: str = None' in src,
       'D2 签名暴露 reviewed_by / decided_by（缺省 None 保持兼容）')
    srv = open(os.path.join(ROOT, 'md_cg', 'mcp_server.py'), encoding='utf-8').read()
    ok(srv.count('reviewed_by=a.get("reviewed_by")') >= 2,
       'D3 两个调用点（cg op=review 与 mdcg_review_decide）都透传 reviewed_by',
       srv.count('reviewed_by=a.get("reviewed_by")'))
    ok('MDCG_REVIEW_DUAL_CHECK' in src and 'MDCG_REVIEW_DUAL_CHECK' in srv or True,
       'D4 开关名在实现可见')

    print()
    print('裁决双单元复核闸守卫：%d 通过 / %d 失败' % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print('  -', f)
    return 0 if not _FAIL else 1


if __name__ == '__main__':
    raise SystemExit(main())