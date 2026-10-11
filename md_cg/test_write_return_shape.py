# -*- coding: utf-8 -*-
'''写返回体判据守卫（issue #109 相邻面）：committed 必须可机器判定。

背景：`mdcg_remember` 工具面的**同一个返回体**在闸门短路分支给 `committed=False`，
成功分支此前**不给 `committed`** ⇒ 按 `committed` 判「是否落盘」的调用方会把**成功**
读成**未提交**；而按 `ok` 判的调用方会把**待审**读成**已提交**（#109 报的那一面）。
两面同源：**工具面的 committed 不是恒在的判据键**。

权威依据：`md_cg/protocol.py:57-59` 的 `WRITE_TRIO` 铁律（write 任一形态必含
ok/id/committed——「客户端据此判定『是否落盘』而非猜测」）与
`docs/mdcg/灵枢记忆动词协议_v1.0-draft.md:28/:31-32/:43`。

本守卫只钉**可判据面**：committed 恒在且与落盘事实一致；pending 态用 committed 可判。
不改写入语义。

运行：python -X utf8 -m md_cg.test_write_return_shape
      python -X utf8 -m md_cg.test_write_return_shape --mutate
'''
import argparse
import io
import json
import os
import shutil
import sys
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix='write_shape_sandbox_')
os.environ['MDCG_AUX_ROOT'] = _SANDBOX
os.environ['MDCG_ROOT'] = os.path.join(_SANDBOX, 'root')
os.environ['MDCG_MASTER_KEY'] = os.urandom(32).hex()
os.environ.pop('MDCG_TEST_LIVE_ROOT', None)
_pol = os.path.join(_SANDBOX, 'policy.json')
with io.open(_pol, 'w', encoding='utf-8') as _f:
    json.dump({'forbidden': ['FORBIDDEN_WORD'], 'required': ['PASSED']}, _f)
os.environ['MDCG_POLICY_FILE'] = _pol

from . import mcp_server, protocol                # noqa: E402
from .mdcos import MdCGOS                          # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PASS = []
_FAIL = []
_RUN = [0]


def ok(cond, msg, extra=''):
    (_PASS if cond else _FAIL).append(msg)
    print(('  PASS ' if cond else '  FAIL ') + msg
          + (('  <- ' + str(extra)) if (extra and not cond) else ''))


def _lib(tag):
    _RUN[0] += 1
    return MdCGOS(os.path.join(_SANDBOX, '%s_r%d' % (tag, _RUN[0])), autoflush=0)


BODY = '# 功能名：%s' + chr(10) + chr(10) + '# 生效条件：PASSED' + chr(10)


def _args(text, nid):
    return {'content_kind': 'text', 'content': text, 'layer': 'knowledge',
            'node_id': nid, 'verification_basis': 'test'}


def tool_write(cg, text, nid):
    return mcp_server.call_tool(cg, 'mdcg_remember', _args(text, nid))


def verb_write(cg, text, nid):
    a = dict(op='write')
    a.update(_args(text, nid))
    return mcp_server.call_tool(cg, 'cg', a)


def g_tool_success():
    cg = _lib('toolok')
    o = tool_write(cg, BODY % '初版', 'w1')
    ok(o.get('ok') is True, 'G1a 工具面首次写入 ok=True', o.get('ok'))
    ok('committed' in o, 'G1b 工具面成功返回体含 committed（三键铁律）', sorted(o))
    ok(o.get('committed') is True, 'G1c 工具面成功 => committed is True', o.get('committed'))
    ok('初版' in ((cg.get('w1') or {}).get('content') or ''),
       'G1d 与落盘事实一致（正文确在盘上）')


def g_tool_pending():
    cg = _lib('toolpend')
    tool_write(cg, BODY % '初版', 'w2')
    o = tool_write(cg, BODY % '改写版', 'w2')
    ok('committed' in o, 'G2a pending 返回体含 committed', sorted(o))
    ok(o.get('committed') is False, 'G2b pending => committed is False', o.get('committed'))
    ok(bool(o.get('moved_to')), 'G2c 未 committed 必给去向（moved_to）', o.get('moved_to'))
    ok('改写版' not in ((cg.get('w2') or {}).get('content') or ''),
       'G2d 与落盘事实一致（新正文未落盘）')


def g_machine_decidable():
    cg = _lib('decide')
    a = tool_write(cg, BODY % 'A', 'w3')
    b = tool_write(cg, BODY % 'B', 'w3')
    ok(a.get('committed') is True and b.get('committed') is False,
       'G3a 「已提交 / 待审」两态仅凭 committed 即可机器区分（不依赖 ok）',
       (a.get('committed'), b.get('committed')))
    ok(a.get('ok') is True and b.get('ok') is False,
       'G3b #109 修复后：两态 ok **不再相同**（已提交 True / 待审 False）——'
       '「只判 ok」如今也能机器区分；本守卫自此同时钉 ok 与 committed 两路')
    ok(b.get('status') == 'pending_review',
       'G3c 待审态须带 status=pending_review（#109 契约：ok/committed/status 三键同述一态）',
       b.get('status'))


def g_verb_face():
    cg = _lib('verb')
    a = verb_write(cg, BODY % 'VA', 'v1')
    b = verb_write(cg, BODY % 'VB', 'v1')
    for tag, o, want in (('G4a verb 成功', a, True), ('G4b verb 待审', b, False)):
        miss = [k for k in protocol.WRITE_TRIO if k not in o]
        ok(not miss and o.get('committed') is want,
           '%s => 含三键且 committed is %s' % (tag, want), (miss, o.get('committed')))


def _scan_ok_without_committed(src):
    '''找出 return {"ok": True ...} 且同一字典字面量内无 committed 的返回。'''
    bad = []
    lines = src.split(chr(10))
    for n, l in enumerate(lines):
        if 'return {' not in l:
            continue
        if '\"ok\": True' not in l and "'ok': True" not in l:
            continue
        head = chr(10).join(lines[n:n + 6]).split('}')[0]
        if 'committed' not in head:
            bad.append('第 %d 行' % (n + 1))
    return bad


def g_source_no_silent_gap():
    src = io.open(os.path.join(_HERE, 'mcp_server.py'), encoding='utf-8').read()
    i = src.find('if name == \"mdcg_remember\":')
    j = src.find('if name == \"mdcg_recall\":')
    block = src[i:j] if (i >= 0 and j > i) else ''
    ok(bool(block), 'G5a 定位到 mdcg_remember 工具面分支块', (i, j))
    bad = _scan_ok_without_committed(block)
    ok(not bad,
       'G5b 工具面分支内不存在「ok:True 却不给 committed」的返回（防静默回退）', bad)


_CASES = (g_tool_success, g_tool_pending, g_machine_decidable, g_verb_face,
          g_source_no_silent_gap)


def _run_all():
    del _PASS[:]
    del _FAIL[:]
    for fn in _CASES:
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001
            ok(False, '%s 组抛异常：%s: %s' % (fn.__name__, type(exc).__name__, exc))
    return list(_FAIL)


_SYN = (
    ('M0 合成合规源码（同一字典内含 committed）',
     'return {"ok": True, "id": nid, "committed": True}', False),
    ('M1 合成缺 committed（本轮修掉的那一态）',
     'return {"ok": True, "id": nid}', True),
    ('M2 合成 committed 换行后仍在同一字典内',
     'return {"ok": True, "id": nid,' + chr(10) + '        "committed": True}', False),
    ('M3 合成 committed 落在字典之外（应判红）',
     'return {"ok": True, "id": nid}' + chr(10) + 'x = {"committed": True}', True),
)


def _run_mutations():
    print('!! 定点变异自证：给 G5b 判据体喂合成源码，判别力必须成立')
    bad = 0
    for name, src, expect_red in _SYN:
        got = _scan_ok_without_committed(src)
        good = (bool(got) == expect_red)
        if not good:
            bad += 1
        print('  %s %s' % ('PASS' if good else 'FAIL', name))
        if not good:
            print('        预期有红=%s 实际=%s' % (expect_red, got))
    print('')
    return bad


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(description='写返回体判据守卫（issue #109 相邻面）')
    ap.add_argument('--mutate', action='store_true', help='定点变异自证')
    a = ap.parse_args()
    reds = _run_all()
    print('')
    print('SUMMARY: 写返回体判据守卫：%d 通过，%d 失败' % (len(_PASS), len(reds)))
    if reds:
        print('失败判据：' + '; '.join(reds))
    rc = 1 if reds else 0
    if a.mutate:
        rc = 1 if (_run_mutations() or reds) else 0
        print('SUMMARY: 定点变异自证：%s' % ('全部按预期' if rc == 0 else '存在偏差'))
    shutil.rmtree(_SANDBOX, ignore_errors=True)
    return rc


if __name__ == '__main__':
    sys.exit(main())
