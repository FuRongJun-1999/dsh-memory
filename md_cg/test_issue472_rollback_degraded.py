# -*- coding: utf-8 -*-
# 功能名：rollback 退化路径的守卫（issue #472 · **站点 2** 的载体）
# 生效条件：python -u -X utf8 -m md_cg.test_issue472_rollback_degraded；夹具钉临时区
# 子功能：D1 退化仍能落盘 · D2 退化不静默（stderr 留痕）· D3 落下的行带 chain=AUDIT_KNOWN_DEGRADED · D4 该行 => known_degraded 而非 unknown_foreign
# 执行：直接跑；退出码 0=全绿
# 验证方式：全部 PASS；cg 替身的 _audit 真抛异常（**真造退化**，不 mock 返回值）
# 不适用条件：不判「链密钥的信任根是否被持有者换过」（那属权限模型，见主守卫的可判性边界）
#
# ★档 3 的完整表述（Lead 确认；本会话判据理论的一格）：
#   档 3 有**两个条件，缺一不可**：
#     (i) **每个站点各自被其对应的红项抓住**（**前提**：每站点有腿）；
#     (ii) **各站点的红项集合不重叠**（归因不串）。
#   只满足 (ii) 而不满足 (i)，形式上是「**只有一个站点被抓住**」，**不是档 3**。
#   （本件实测：站点 1 回退转红 3 条；站点 2 在 D 组落地前回退零红 ⇒ 当时只满足 (ii)。）
#
# ★回退自证的前置约束（同一形态第 3 次，落成明确要求）：
#   **回退自证前，镜像树必须与真树同构（含全部子包）**；
#   **裁剪镜像 ⇒ 基线即红 ⇒ 读数无效（那不是腿不红，是夹具坏了）**。
#   实测三次：C1 首跑 · #472 首跑（裁 whitebox_kb/lexicon/semantic ⇒ No module named md_cg.whitebox_kb）。
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from md_cg import mdcos as M                          # noqa: E402
from md_cg import rollback as RB                      # noqa: E402

PASS = FAIL = 0
FAILS = []


def ok(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('  PASS ' + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print('  FAIL ' + name + '  ' + str(detail)[:220])


class _CgStub:
    def __init__(self, root):
        self.root = root

    def _audit(self, *a, **k):
        raise RuntimeError('stub: _audit 不可用（模拟退化）')


sb = tempfile.mkdtemp(prefix='i472_d_')
try:
    stub = _CgStub(sb)
    res = {'method': 'byte-copy', 'bytes_equal_preimage': True}
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        good = RB._audit_rollback(stub, 'n1', 'restore', 'p1', res, actor='a', reason='r')
    ok('D1 退化路径仍能落盘（返回 True，best-effort 不打断）', good is True, good)
    ok('D2 ★退化不再静默：stderr 有留痕', '退化直写' in err.getvalue(), err.getvalue()[:140])
    p = os.path.join(sb, '_audit.jsonl')
    rec = json.loads([l for l in io.open(p, encoding='utf-8') if l.strip()][-1])
    ok('D3 ★落下的行带 chain=AUDIT_KNOWN_DEGRADED', rec.get('chain') == M.AUDIT_KNOWN_DEGRADED, rec)
    v, r, d = M._audit_chain_verify(p)
    ok('D4 ★该行 => known_degraded（软信号），不是 unknown_foreign（硬失败）',
       v == 'known_degraded' and r == M.AUDIT_KNOWN_DEGRADED, (v, r, d))
finally:
    shutil.rmtree(sb, ignore_errors=True)

print('')
print('断言总数 %d（PASS %d / FAIL %d）' % (PASS + FAIL, PASS, FAIL))
if FAILS:
    print('FAILED:')
    for f in FAILS:
        print('   - ' + f)
sys.exit(1 if FAILS else 0)