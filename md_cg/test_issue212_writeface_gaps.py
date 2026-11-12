# -*- coding: utf-8 -*-
"""issue #212 守卫：工具面写入的四个缺口（本波修缺口 1/3/4；缺口 2 待 #142 口径裁定）。

# 功能名：工具面写入的硬上限闸 + 尝试账本总开关 + 尝试账本归档感知读面
# 生效条件：改动 md_cg/mcp_server.py 的 mdcg_remember 分支、md_cg/writepipe.py 的
#           oversize_response / _append_attempt / attempt_history、md_cg/rotate.py 的
#           Rotator.read_records 之后必跑
# 子功能：① 工具面按写入硬上限硬拒，且与动词面同源（逐键相等）② 判据边界不误伤
#         （== 上限放行 / 上限+1 拒，单元级直接钉比较算子）③ 尝试账本总开关有效
#         （缺省开；0/false/no/off 停用）且停用不改写入语义——**走动词面测**：工具面
#         根本不进 writepipe 的 before 链，故它在尝试账本上恒 0 行（缺口 2 的现状，
#         W4e 如实钉住）④ 轮转后读面不归零
#         （归档感知），只读活动文件的旧口径为 0 行 ⑤ 判别力对照（撤掉接线 ⇒ ① 转红）
#         ⑥ 源码级防回退
# 执行：python -X utf8 -m md_cg.test_issue212_writeface_gaps
# 验证方式：末行「通过 N / 失败 M」；红基线：修复前 main 上 ①②④ 为红
# 不适用条件：缺口 2（工具面对两本账零覆盖）**不在本守卫红绿面内**——它需先裁定
#             #142 的两本账口径（工具面出口集与动词面不同，且 test_twophase ⑧2 钉
#             「未落盘的分支不产生 intent」）；不碰在役库（全程 tempfile 隔离）
#             不测「恰好等于上限的正文真的落盘」——那条路会命中 audit.redact_forbidden
#             的二次方开销（见下），本守卫不把 16 分钟写进红绿面；比较算子改在单元级
#             直接钉（W3），接线另在集成级钉（W1 拒 / W3d 放行小正文）。

## 缺陷现场（issue #212）
同一内容走两条通路结论相反：cg(op=write) 被 MAX_WRITE_BYTES 硬拒，mdcg_remember
却 committed=True 落盘。根因＝判据与字段集被写了两份、只有动词面那份被接线。
本守卫 W2 直接断言「两面响应体（按工具面键集）逐键相等」——这条比「工具面也有
gate 键」更强：它同时钉住「不是复制出来的第二份字段集」。

## 与二次方脱敏的关系（本波实测，另案）
W3 用单元级钉边界，是因为集成级的「恰好上限」正文会走 audit.redact_forbidden，
而该函数在**长小写字母串**上二次方退化（实测 64 KiB=3.9s / 256 KiB=61.3s，外推
1 MiB≈16min；嫌疑模式 = data/policy.json 的
形如「小写字母打头、[a-z0-9+.-]* 任意长、后接 :// 用户:口令@」的 URL 凭据规则
——贪心前缀吃掉整段后逐位回溯找 ://）。
该缺陷**不属于 #212 的四个缺口**（本波如实另案上报，不在本件改动面内）。

## 轮转口径（缺口 4，重要）
本账此前**只有写面、没有任何读面**（全仓对 _write_attempts 的引用只有写入点与
注释）。W5 的判别口径是「读面不归零」，不是「一条不丢」：超出 keep_shards 的旧
分片被淘汰是**有界保留＝设计**；W5a 同时钉住「只读活动文件的旧口径在轮转后为 0
行」，故 W5b 非空不是恒真。
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

# 沙箱必须在**任何** md_cg 子模块 import 之前设好（crypto.MASTER_KEY 等在模块导入时
# 求值）——与 md_cg/test_issue211_export_target.py 同款装置。子目录名不得用 aux /
# con / prn / nul / com1-9 / lpt1-9：Windows 保留设备名，makedirs 会抛 WinError 267。
_SANDBOX = tempfile.mkdtemp(prefix="i212_sandbox_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_SANDBOX, "auxstore")
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "libroot")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_EXPORT_ROOT", None)
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)
os.environ.pop("MDCG_WRITE_ATTEMPT_LEDGER", None)
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
os.makedirs(os.environ["MDCG_ROOT"], exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import mcp_server, protocol, writepipe        # noqa: E402
from md_cg.fsutil import read_jsonl                      # noqa: E402
from md_cg.mdcos import MdCGOS                           # noqa: E402
from md_cg.rotate import Rotator                         # noqa: E402

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
LIMIT = writepipe.MAX_WRITE_BYTES


def _args(text, nid):
    return {'content_kind': 'text', 'content': text, 'layer': 'knowledge',
            'node_id': nid, 'verification_basis': 'test'}


def _ccg(tag):
    """动词面会过 audit 的 required 规则（CCG 六要素），故**动词面夹具必须齐六行**；
    工具面不进审核链，短文即可。W4 用本函数，正是为了让「账本 +1」测的是开关而不是
    审核结论（用三行短文会被 REJECT，于是账本行数不增，测出来的红是夹具缺陷）。"""
    # 六行**取值互不相同**：一致性的自否定判据会拿「不适用条件」去比「生效条件/正文」，
    # 六行都写同一个哑值会被判「条件自相矛盾」转 review_queue（本守卫初版即踩此坑）。
    return ('# 功能名：%s' % tag + chr(10)
            + '# 生效条件：当尝试账本开关未显式停用时' + chr(10)
            + '# 子功能：尝试账本的记账与开关' + chr(10)
            + '# 执行：进程内 call_tool 写一条正文' + chr(10)
            + '# 验证方式：比对账本行数差' + chr(10)
            + '# 不适用条件：不涉及轮转与归档分片' + chr(10))


def _pad(n):
    """造**恰好 n 字节**的正文。填充用大写字母：小写长串会命中
    audit.redact_forbidden 的二次方退化（见模块 docstring），本守卫不测那个。"""
    head = BODY % 'p'
    return head + ('Z' * (n - len(head.encode('utf-8'))))


def tool_write(cg, text, nid):
    return mcp_server.call_tool(cg, 'mdcg_remember', _args(text, nid))


def verb_write(cg, text, nid):
    return mcp_server.call_tool(cg, 'cg', dict(op='write', **_args(text, nid)))


def _rows(cg):
    p = os.path.join(cg.root, writepipe.ATTEMPT_LOG_FILE)
    if not os.path.isfile(p):
        return 0
    with io.open(p, encoding='utf-8') as f:
        return sum(1 for l in f if l.strip())


def _need(shape):
    return set(protocol.VERB_SPECS['write']['shapes'][shape]['required'])


def _env_guard(key):
    old = os.environ.get(key)
    os.environ.pop(key, None)
    return old


def _env_restore(key, old):
    if old is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = old


def w1_tool_face_hard_limit():
    cg = _lib('w1')
    big = _pad(LIMIT + 8)
    o = tool_write(cg, big, 'w1_big')
    ok(o.get('committed') is False,
       'W1a 工具面超限 => committed is False（修复前为 True）', o.get('committed'))
    ok(o.get('gate') == 'writelimit_size',
       'W1b 工具面超限 => gate=writelimit_size', o.get('gate'))
    miss = [k for k in protocol.WRITE_TRIO if k not in o]
    ok(not miss, 'W1c 工具面超限返回体含三键（ok/id/committed）', sorted(o))
    need = _need('gate_hard_reject')
    ok(not [k for k in need if k not in o],
       'W1d 工具面超限返回体命中协议形态 gate_hard_reject', sorted(o))
    ok('w1_big' not in cg.index['nodes'],
       'W1e 超限内容未落盘（索引里无该节点）', list(cg.index['nodes'])[:5])
    ok(o.get('bytes') == len(big.encode('utf-8')) and o.get('limit') == LIMIT,
       'W1f 读数自洽：bytes = 正文实际字节数，limit = 上限',
       (o.get('bytes'), len(big.encode('utf-8')), o.get('limit')))


def w2_two_faces_identical():
    """两条通路必须给**同一个**响应体（按工具面键集）——比「工具面也有 gate 键」
    更强：它同时钉住「不是复制出来的第二份字段集」。
    动词面外层多一个 action_source（动词面信封），故按工具面键集取子集比对。"""
    cg = _lib('w2')
    big = _pad(LIMIT + 8)
    o_t = tool_write(cg, big, 'same_id')
    o_v = verb_write(cg, big, 'same_id')
    sub = {k: o_v[k] for k in o_t if k in o_v}
    ok(o_t == sub,
       'W2a 同内容 + 同 id：工具面响应体 == 动词面对应键集（同源，非复制）',
       (sorted(o_t), sorted(o_v), o_t.get('gate'), o_v.get('gate')))
    ok(set(o_t) <= set(o_v),
       'W2b 工具面键集是动词面键集的子集（动词面只多信封键）',
       sorted(set(o_t) - set(o_v)))


def w3_boundary_no_false_positive():
    """比较算子（> 上限 才拒）在**唯一构造点**上直接钉——不落盘，故不触发
    redact_forbidden 的二次方开销。"""
    a = {'content': _pad(LIMIT), 'content_kind': 'text'}
    ok(writepipe.oversize_response('n', a) is None,
       'W3a 恰好 == 上限（%d 字节）=> 放行（比较算子是 >，不误伤）' % LIMIT,
       writepipe.oversize_response('n', a))
    a2 = {'content': _pad(LIMIT + 1), 'content_kind': 'text'}
    r2 = writepipe.oversize_response('n', a2)
    ok(isinstance(r2, dict) and r2.get('committed') is False,
       'W3b 上限 +1 字节 => 拒', r2)
    ok(r2 and r2.get('bytes') == LIMIT + 1,
       'W3c 上限 +1 的 bytes 读数 = %d' % (LIMIT + 1), r2 and r2.get('bytes'))
    cg = _lib('w3')
    small = BODY % '小正文'
    o = tool_write(cg, small, 'w3_small')
    ok(o.get('committed') is True,
       'W3d 小正文仍正常落盘（补闸未误伤常规写入）', o)


def w4_ledger_switch():
    cg = _lib('w4')
    key = writepipe.ATTEMPT_LEDGER_ENV
    old = _env_guard(key)
    try:
        b = _rows(cg)
        o = verb_write(cg, _ccg('开关未设'), 'w4_a')
        ok(_rows(cg) - b == 1 and o.get('committed') is True,
           'W4a 未设 %s => 账本 +1 行（缺省开，与修复前逐位一致）' % key,
           _rows(cg) - b)
        for i, val in enumerate(('0', 'false', 'no', 'off', 'OFF', ' false ')):
            os.environ[key] = val
            b = _rows(cg)
            o = verb_write(cg, _ccg('开关' + str(i)), 'w4_off%d' % i)
            ok(_rows(cg) - b == 0,
               'W4b %s=%r => 账本 +0 行（修复前该 env 无效、仍写 1 行）' % (key, val),
               _rows(cg) - b)
            ok(o.get('committed') is True,
               'W4c %s=%r 停用只停留痕、不改写入语义' % (key, val), o)
        os.environ[key] = '1'
        b = _rows(cg)
        verb_write(cg, _ccg('开关1'), 'w4_one')
        ok(_rows(cg) - b == 1, 'W4d %s=1 => 账本 +1 行' % key, _rows(cg) - b)
        # 如实钉住**缺口 2 的现状**（本件不修）：工具面根本不进 writepipe 的 before
        # 链，故它的写入在尝试账本上是 0 行。若将来 #142 的伞状裁定把工具面也接进
        # 记账面，本项会转红——那正是「把断言升级为『两面一致』」的信号（同
        # md_cg/test_write_return_shape.py 的 H2/H3「现状记录·待裁定」惯例）。
        b = _rows(cg)
        tool_write(cg, BODY % '工具面不记账', 'w4_tool')
        ok(_rows(cg) - b == 0,
           'W4e 现状（缺口 2，待 #142 裁定）：工具面写入不产生尝试账本行',
           _rows(cg) - b)
    finally:
        _env_restore(key, old)


def w5_history_survives_rotation():
    """判别口径是「读面**不归零**」，不是「一条不丢」：超出 keep_shards 的旧分片
    被淘汰是有界保留＝设计。W5a 同时钉住「只读活动文件的旧口径在轮转后为 0 行」，
    故 W5b 非空不是恒真。"""
    cg = _lib('w5')
    key = writepipe.ATTEMPT_LEDGER_ENV
    old = _env_guard(key)
    try:
        rot = Rotator(cg.root, writepipe.ATTEMPT_BASENAME,
                      writepipe.ATTEMPT_ARCHIVE_DIR,
                      rotate_bytes=1, keep_shards=2)
        for k in range(6):
            for j in range(6):
                writepipe._append_attempt(cg, 'w5_%d_%d' % (k, j),
                                          {'content_kind': 'text',
                                           'layer': 'knowledge'},
                                          writepipe.ATTEMPT_COMMITTED,
                                          out={'id': 'x'})
            r = rot.rotate()
            ok(r is not None, 'W5 第 %d 次轮转切出分片' % (k + 1), r)
        active_only = list(read_jsonl(os.path.join(cg.root,
                                                   writepipe.ATTEMPT_LOG_FILE)))
        hist = writepipe.attempt_history(cg, limit=0)
        ok(len(active_only) == 0,
           'W5a 只读活动文件的旧口径：轮转后 0 行（缺陷现场）', len(active_only))
        ok(len(hist) > 0,
           'W5b 归档感知读面：轮转后**不归零**', len(hist))
        ok(len(hist) == 12,
           'W5c 读面 = 存活分片（keep_shards=2 × 6 行）+ 活动文件', len(hist))
        ok([r['id'] for r in hist][-1] == 'w5_5_5',
           'W5d 时间序正确（末条 = 最后一次写入）', [r['id'] for r in hist][-1:])
        ok(len(writepipe.attempt_history(cg, limit=3)) == 3,
           'W5e limit 生效（取尾部 3 条）',
           len(writepipe.attempt_history(cg, limit=3)))
    finally:
        _env_restore(key, old)


def w6_discriminator():
    """判别力对照：把唯一构造点撤成 no-op（等价修复前形态）⇒ 工具面又落盘成功。
    证明 W1 不是恒真。"""
    cg = _lib('w6')
    big = _pad(LIMIT + 8)
    real = writepipe.oversize_response
    try:
        writepipe.oversize_response = lambda nid, a: None
        o = tool_write(cg, big, 'w6_big')
        ok(o.get('committed') is True,
           'W6a 撤掉接线 => 工具面又落盘成功（W1 有判别力）', o)
    finally:
        writepipe.oversize_response = real


def w7_source_no_regress():
    src = io.open(os.path.join(_HERE, 'mcp_server.py'), encoding='utf-8').read()
    i = src.find('if name == "mdcg_remember":')
    j = src.find('if name == "mdcg_recall":')
    block = src[i:j] if (i >= 0 and j > i) else ''
    ok('oversize_response' in block,
       'W7a 工具面分支仍调用动词面的同一实现（防回退到「各写一份判据」）',
       '（本项红说明接线被撤）')
    ws = io.open(os.path.join(_HERE, 'writepipe.py'), encoding='utf-8').read()
    ok('def oversize_response' in ws,
       'W7b writepipe 仍有唯一构造点 oversize_response')
    ok('def attempt_history' in ws,
       'W7c writepipe 仍有归档感知读面 attempt_history')
    ok('def read_records' in io.open(os.path.join(_HERE, 'rotate.py'),
                                     encoding='utf-8').read(),
       'W7d Rotator 仍有归档感知读原语 read_records')
    ok(writepipe.ATTEMPT_LEDGER_ENV == 'MDCG_WRITE_ATTEMPT_LEDGER',
       'W7e 开关名就是 issue #212 点名的那一个（不是另起新名）',
       writepipe.ATTEMPT_LEDGER_ENV)
    ok(writepipe.oversize_response('n', {'content': 'x'}) is None,
       'W7f 唯一构造点可直接调用（两面的共用入口没被私有化）')


_CASES = (w1_tool_face_hard_limit, w2_two_faces_identical,
          w3_boundary_no_false_positive, w4_ledger_switch,
          w5_history_survives_rotation, w6_discriminator,
          w7_source_no_regress)


def _run_all():
    del _PASS[:]
    del _FAIL[:]
    for fn in _CASES:
        print(chr(10) + '== %s' % fn.__name__)
        try:
            fn()
        except Exception as exc:            # noqa: BLE001
            import traceback
            _FAIL.append('%s 抛异常' % fn.__name__)
            print('  FAIL %s 抛异常：%s: %s'
                  % (fn.__name__, type(exc).__name__, exc))
            traceback.print_exc()
    print(chr(10) + '通过 %d / 失败 %d' % (len(_PASS), len(_FAIL)))
    for m in _FAIL:
        print('  - ' + m)
    return 1 if _FAIL else 0


if __name__ == '__main__':
    raise SystemExit(_run_all())
