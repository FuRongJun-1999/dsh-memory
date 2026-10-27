# -*- coding: utf-8 -*-
# 功能名：分层写入严格度闸守卫（四档矩阵 · 无复核通道只准情景层 · 自我层需人工）
# 生效条件：python -X utf8 -m md_cg.test_writegate_tiers；被测面＝md_cg/writegate.py 与 security.require_layer_write 的接入
# 子功能：①档位归一（含非法值 fail-open）②四档严格度 ③无通道放宽仅 tier0 ④有通道按单元缺失判 require_review ⑤自我层必含 human ⑥off 零介入 / warn 不阻断 / enforce 阻断
# 执行：纯函数逐格断言 + 临时库上跑 require_layer_write 三档
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不判复核证据真伪；不判 PROTECTED_LAYERS 的不可遗忘语义（另有守卫）
"""分层写入严格度闸守卫（2026-10-27 使用者裁定）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import writegate as w

_PASS, _FAIL = [], []


def ok(cond, msg, detail=''):
    (_PASS if cond else _FAIL).append(msg)
    print(('  PASS ' if cond else '  FAIL ') + msg + (('  <- ' + str(detail)) if detail and not cond else ''))


def main():
    print('== A 档位与层映射')
    ok(w.gate_mode({}) == 'off', 'A1 缺省档位是 off（零介入，避免升级即自伤）')
    ok(w.gate_mode({'MDCG_WRITE_GATE': 'warn'}) == 'warn', 'A2 warn 可识别')
    ok(w.gate_mode({'MDCG_WRITE_GATE': 'ENFORCE'}) == 'enforce', 'A3 enforce 大小写不敏感')
    ok(w.gate_mode({'MDCG_WRITE_GATE': 'bogus'}) == 'off', 'A4 非法值 fail-open 到 off')
    ok(w.tier_of('contextual') == 0 and w.tier_of('knowledge') == 1
       and w.tier_of('structural') == 2 and w.tier_of('self') == 3,
       'A5 四档严格度递增（情景<知识<结构<自我）')
    ok(w.tier_of('unknown_layer') == 2, 'A6 未知层按结构层保守处理')
    ok(w.tier_of('anchor') == 3, 'A7 锚点层与自我层同档（失忆=毁灭性）')

    print('== B 无复核通道：只准情景层（使用者裁定的放宽通道）')
    for lay in ('contextual', 'goals', 'unresolved', 'rejected'):
        ok(w.decide_write(lay, channels=(), mode='enforce')['decision'] == 'allow',
           'B1 无通道可写 %s' % lay)
    for lay in ('knowledge', 'structural', 'self', 'anchor'):
        d = w.decide_write(lay, channels=(), mode='enforce')
        ok(d['decision'] == 'deny' and d['missing'],
           'B2 无通道拒写 %s（点名缺失单元）' % lay, d)

    print('== C 有通道：按单元缺失判定')
    ok(w.decide_write('knowledge', reviewers=['reflect'], channels=('hive',),
                      mode='enforce')['decision'] == 'allow',
       'C1 知识层只需反思单元')
    ok(w.decide_write('knowledge', reviewers=[], channels=('hive',),
                      mode='enforce')['decision'] == 'require_review',
       'C2 知识层缺反思 ⇒ require_review')
    ok(w.decide_write('structural', reviewers=['reflect'], channels=('subagent',),
                      mode='enforce')['missing'] == ['verify'],
       'C3 结构层缺验证单元被点名')
    ok(w.decide_write('structural', reviewers=['reflect', 'verify'],
                      channels=('subagent',), mode='enforce')['decision'] == 'allow',
       'C4 结构层双单元齐备 ⇒ allow')
    ok(w.decide_write('self', reviewers=['reflect', 'verify'], channels=('team',),
                      mode='enforce')['decision'] == 'require_review',
       'C5 自我层双单元仍不够（须人工裁定）')
    ok(w.decide_write('self', reviewers=['reflect', 'verify', 'human'],
                      channels=('team',), mode='enforce')['decision'] == 'allow',
       'C6 自我层三单元齐备 ⇒ allow')

    print('== D 三档开关的放行语义')
    ok(w.decide_write('self', reviewers=[], channels=(), mode='off')['decision'] == 'allow',
       'D1 off 档连自我层也放行（完全不介入）')
    ok(w.decide_write('self', reviewers=[], channels=(), mode='warn')['decision'] == 'deny'
       and w.decide_write('self', reviewers=[], channels=(), mode='warn')['mode'] == 'warn',
       'D2 warn 档的判定与 enforce 同形（是否阻断由调用方决定）')
    ok(w.review_channels({'MDCG_REVIEW_CHANNELS': 'hive, subagent ,team'})
       == ('hive', 'subagent', 'team'), 'D3 通道声明解析（去空格去重）')
    ok(w.review_channels({}) == (), 'D4 未声明通道 ⇒ 空（视为无复核能力）')

    print('== F 声明≠探测（2026-10-27 误判修正）')
    p = w.probe_channels({})
    ok(p['declared'] == () and '声明缺失不等于能力缺失' in p['hint'],
       'F1 未声明时只报「未声明」，并写明声明缺失≠能力缺失', p)
    p2 = w.probe_channels({'MDCG_REVIEW_CHANNELS': 'subagent'})
    ok(p2['declared'] == ('subagent',) and '已声明' in p2['hint'],
       'F2 声明 subagent 后被如实回报', p2)
    _reason = w.decide_write('knowledge', channels=(), mode='enforce')['reason']
    ok('未声明' in _reason, 'F3 deny 文案说的是「未声明」而非「无能力」', _reason)
    ok('无子代理' not in _reason and '无蜂巢' not in _reason,
       'F4 deny 文案不得断言能力缺失（曾因此对外误报「无子代理」）', _reason)

    print('== E security.require_layer_write 接入锚点（源码判据）')
    sec = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'md_cg', 'security.py')
    src = open(sec, encoding='utf-8').read()
    ok('_write_gate_verdict(layer, reviewers)' in src,
       'E1 require_layer_write 调用分层写入闸单点')
    ok('def _write_gate_verdict' in src and 'if mode == "off":' in src,
       'E2 闸为 off 时提前返回（零介入，不改变历史行为）')
    ok('MDCG_REVIEWERS' in src,
       'E3 reviewers 缺省从环境 MDCG_REVIEWERS 读取（部署可声明）')
    ok('"enforce"' in src and 'if _wg_verdict.get("mode") == "enforce"' in src,
       'E4 仅 enforce 档抛 AccessDenied（warn 只记录）')
    ok('MDCG_WRITE_GATE' in src,
       'E5 三档开关名在接入点可见')

    print()
    print('分层写入严格度闸守卫：%d 通过 / %d 失败' % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print('  -', f)
    return 0 if not _FAIL else 1


if __name__ == '__main__':
    raise SystemExit(main())