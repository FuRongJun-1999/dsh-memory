# -*- coding: utf-8 -*-
"""守卫 · 显式授权闸（consent_gate）的判据与边界。

# 功能名：test_consent_gate —— 闸的三条件判据、来源闸、过期与撤回
# 生效条件：改动 md_cg/consent_gate.py 后
# 子功能：
#   ① 未配置 / 来源非 user / 引用形态 → 一律不开（fail-closed）
#   ② 三条件缺一不开，且理由能指出缺哪条
#   ③ 完整口令开、过期自动关、close 立即关
#   ④ state 不回显口令；日志只记事件不记内容
# 执行：python -X utf8 -m md_cg.test_consent_gate
# 验证方式：每条断言配一条反向对照（该开的开、该拒的拒）
# 不适用条件：只验闸的逻辑；不验调用方是否诚实声明 source
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import consent_gate as G  # noqa: E402

PASS, FAIL = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:160]))
    (PASS if cond else FAIL).append(name)


SPEC = {
    'demo': {
        'must_contain': ['某名'],
        'any_of': ['某动词'],
        'exclude': ['某爱意词'],
    }
}


def main():
    root = tempfile.mkdtemp(prefix='gate_')
    try:
        # ① 未配置 → 不开
        ok(G.open_gate(root, 'demo', '某名 某动词', source='user')['ok'] is False,
           '① 未配置时拒开', G.open_gate(root, 'demo', '某名 某动词', source='user'))
        with io.open(os.path.join(root, G.GATES_FILE), 'w', encoding='utf-8') as f:
            json.dump(SPEC, f, ensure_ascii=False)

        # ① 来源闸
        for src in ('', 'memory', 'quote', 'relay', None):
            r = G.open_gate(root, 'demo', '某名 某动词', source=src)
            ok(r['ok'] is False, '① 来源 %r 拒开' % (src,), r)

        # ① 引用形态
        q = '> 某名 某动词'
        ok(G.open_gate(root, 'demo', q, source='user')['ok'] is False, '① 块引用拒开')
        ok(G.open_gate(root, 'demo', '据说 某名 某动词', source='user')['ok'] is False, '① 转述前缀拒开')

        # ② 三条件缺一
        r = G.open_gate(root, 'demo', '某动词', source='user')
        ok(r['ok'] is False and '某名' in r['reason'], '② 缺名字拒开且指出缺项', r)
        r = G.open_gate(root, 'demo', '某名 某爱意词', source='user')
        ok(r['ok'] is False, '② 只表爱意不开', r)
        r = G.open_gate(root, 'demo', '某名', source='user')
        ok(r['ok'] is False and '欲望' in r['reason'], '② 缺欲望表达拒开', r)

        # ③ 完整口令开
        r = G.open_gate(root, 'demo', '某名，某动词', source='user', ttl=60)
        ok(r['ok'] is True, '③ 三条件齐 → 开', r)
        ok(G.is_open(root, 'demo') is True, '③ 开着时 is_open 为真')

        # ③ 过期
        import time
        ok(G.is_open(root, 'demo', now=time.time() + 120) is False, '③ 超过 ttl 自动判关')

        # ③ close
        G.close_gate(root, 'demo', reason='撤回')
        ok(G.is_open(root, 'demo') is False, '③ close 后立即关')

        # ④ 不回显口令 + 日志只记事件
        st = G.state(root)
        blob = json.dumps(st, ensure_ascii=False)
        ok('某动词' not in blob and '某名' not in blob, '④ state 不回显口令内容', blob[:80])
        log = io.open(os.path.join(root, G.GATE_LOG), encoding='utf-8').read()
        ok('某动词' not in log and '某名' not in log, '④ 日志不记内容')
        ok('"open"' in log or 'open' in log, '④ 日志记了开事件')
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print()
    print('守卫结果：%d 通过 / %d 失败' % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())