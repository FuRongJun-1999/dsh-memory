# -*- coding: utf-8 -*-
# 功能名：写内容入口的硬上限闸覆盖（issue #557 R2 / #82.3 追评）
# 生效条件：python -u -X utf8 -m md_cg.test_issue557_r2_write_entries_size_gate；被测面＝mcp_server._dispatch 的 rejected/unresolved/propose 三入口 + cg(op=goal)
# 子功能：A 组＝四入口（rejected/unresolved/propose + cg(op=goal)）在超大入参下必须返回拒收体（gate 字段点名硬上限）；K 组＝正常大小不得被拒（不得误伤）
# 执行：直接调 _dispatch(cg, '<entry>', {...}) 判返回体；超大用 writepipe.MAX_WRITE_BYTES + 8
# 验证方式：全部 PASS 即通过（退出码 0）
# 不适用条件：不判只读入口（recall/search/get…）；不判 whitebox/service_info/remember（已由 #212 覆盖）
import os
import sys
import tempfile

from . import mcp_server
from . import writepipe
from .mdcos import MdCGSecure
from .security import Principal

LIMIT = writepipe.MAX_WRITE_BYTES
BIG = 'x' * (LIMIT + 8)

PASS = 0
FAIL = 0
FAILS = []


def ok(cond, title, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('  PASS %s' % title)
    else:
        FAIL += 1
        FAILS.append(title)
        print('  FAIL %s  <- %r' % (title, str(detail)[:100]))


tmp = tempfile.mkdtemp(prefix='i_r2_')
os.environ.update({'MDCG_ROOT': os.path.join(tmp, 'brain'),
                    'MDCG_STATE_ROOT': os.path.join(tmp, 'state'),
                    'MDCG_AUX_ROOT': os.path.join(tmp, 'auxstore'),
                    'MDCG_DATA_ROOT': os.path.join(tmp, 'data'),
                    'MDCG_EXPORT_ROOT': tmp, 'MDCG_SUSTAIN': '0', 'MDCG_SLEEP': '0'})
from . import crypto
os.environ[crypto.MASTER_ENV] = 'ab' * 32
cg = MdCGSecure(os.environ['MDCG_ROOT'],
                principal=Principal(tenant='t', actor='a', role='designer',
                                    clearance='private'))


def _gate_of(out):
    return ((out or {}).get('gate') or {}).get('kind') or ((out or {}).get('detail') or {}).get('gate')


print('== A 组：三入口超大入参必须被拒 ==')
for entry, payload in (
        ('mdcg_rejected', {'hypothesis': BIG, 'reason': 'r'}),
        ('mdcg_unresolved', {'question': BIG}),
        ('mdcg_propose', {'node_id': 'n_big', 'content': BIG}),
        # 2026-10-19 复跑 #557 R2：`op=goal` 是**唯一**仍不判上限的入口（1.26 MB goal
        # ⇒ 2.5 MB 文件落盘）。补闸后并入本腿，防回退。
        ('cg', {'op': 'goal', 'action': 'add', 'goal': BIG}),
):
    out = mcp_server._dispatch(cg, entry, dict(payload))
    # 判据用**闸标记**而不是「有没有 id/pid 键」——拒收体同样带 id（与写面同构造点），
    # 本守卫首版即因此假红（三条 A 全红而其实全被拦）。
    rejected = bool(out) and out.get('ok') is False \
        and out.get('gate') == 'writelimit_size'
    ok(rejected, 'A %-16s 超大入参被拒（gate=writelimit_size）' % entry, out)

print('== K 组：正常大小不得被拒 ==')
_r = mcp_server._dispatch(cg, 'mdcg_rejected', {'hypothesis': 'h', 'reason': 'r'})
ok(bool((_r or {}).get('id')), 'K mdcg_rejected 正常大小通过', _r)
_u = mcp_server._dispatch(cg, 'mdcg_unresolved', {'question': 'q'})
ok(bool((_u or {}).get('id')), 'K mdcg_unresolved 正常大小通过', _u)
_p = mdcg = mcp_server._dispatch(cg, 'mdcg_propose', {'node_id': 'n_ok', 'content': 'c'})
ok(bool((_p or {}).get('pid')), 'K mdcg_propose 正常大小通过', _p)
_g = mcp_server._dispatch(cg, 'cg', {'op': 'goal', 'action': 'add', 'goal': 'g'})
ok(bool((_g or {}).get('id')), 'K cg(op=goal) 正常大小通过', _g)

print('')
print('=' * 56)
print('通过 %d / 失败 %d' % (PASS, FAIL))
for f in FAILS:
    print('  - %s' % f)
sys.exit(0 if FAIL == 0 else 1)