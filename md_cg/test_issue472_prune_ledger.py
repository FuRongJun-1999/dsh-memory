# -*- coding: utf-8 -*-
# 功能名：剪枝留痕的守卫（issue #472 · **站点 3** 的载体）
# 生效条件：python -u -X utf8 -m md_cg.test_issue472_prune_ledger；夹具钉临时区
# 子功能：C1 剪前写对账单（被剪分片名+各自行数+汇总）· C2 对账单不在 shards() 命名空间内 · C3 对账单不被同一 prune 剪掉 · C4 反向：未超限不剪且不新增对账单
# 执行：直接跑；退出码 0=全绿
# 验证方式：全部 PASS；真造分片实数行数（不 mock）
# 不适用条件：不判「谁有权改对账单」（那属权限模型）；不判对账单自身的完整性（本件未给它加链）
#
# ★回退自证前置约束（同一形态第 3 次）：镜像树必须与真树同构（含全部子包）；
#   裁剪镜像 => 基线即红 => **读数无效（不是腿不红）**。
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from md_cg import rotate as R                         # noqa: E402

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


def _mk_shards(root, n=4):
    rot = R.Rotator(root, 'ledger', 'archive', keep_shards=2)
    os.makedirs(rot.archive, exist_ok=True)
    for i in range(1, n + 1):
        name = '%s.%06d.jsonl' % (rot.basename, i)
        io.open(os.path.join(rot.archive, name), 'w', encoding='utf-8').write(
            ''.join(json.dumps({'i': i, 'j': j}) + chr(10) for j in range(i)))
    return rot


sb = tempfile.mkdtemp(prefix='i472_prune_')
try:
    rot = _mk_shards(sb)
    print('  [读数] 造分片前 shards() = %s' % rot.shards())
    led = os.path.join(rot.archive, R.PRUNE_LEDGER)
    gone = rot.prune()
    ok('C1a prune 返回被剪分片（2 个）', len(gone) == 2, gone)
    ok('C1b ★剪前写了对账单', os.path.exists(led), led)
    recs = [json.loads(l) for l in io.open(led, encoding='utf-8') if l.strip()]
    print('  [读数] 对账单行数 = %d（全量内容：%s）' % (len(recs), recs))
    last = recs[-1] if recs else {}
    ok('C1c ★对账单含被剪分片名', sorted(last.get('pruned') or []) == sorted(gone), last.get('pruned'))
    ok('C1d ★对账单含各自行数（3 号 3 行、4 号 4 行）',
       (last.get('lines') or {}).get(gone[0]) == int(gone[0].split('.')[-2]) if gone else False,
       last.get('lines'))
    ok('C1e ★对账单含汇总 lines_total（=各被剪分片行数之和）',
       last.get('lines_total') == sum(v for v in (last.get('lines') or {}).values() if v),
       last.get('lines_total'))
    ok('C2 ★对账单 basename 不在 shards() 命名空间内（否则会被同一 prune 剪掉）',
       os.path.basename(led) not in rot.shards(),
       {'led': os.path.basename(led), 'shards': rot.shards()})
    _before = len([l for l in io.open(led, encoding='utf-8') if l.strip()])
    rot2 = _mk_shards(sb)
    rot2.prune()
    ok('C3 ★再 prune 一次后，对账单仍在（未被同一 prune 剪掉）', os.path.exists(led))
    _after = len([l for l in io.open(led, encoding='utf-8') if l.strip()])
    # ★「不红」的两类（本会话新形式化）：
    #   ① **反例构造无效**（腿没问题，是探针没打在被测面上）=> 改**反例**；
    #   ② **真判据缺口**（腿偏弱，断言的是弱化版性质）=> **加强腿**。
    #   两者处置方向相反；不分就会「腿弱也去改探针」或「探针错也去改腿」——**两个方向都会把问题藏起来**。
    #   实例（站点 3 首轮回退）：B（命名空间）属 ①（反例前缀写错：_audit.999999.jsonl 不匹配 ledger.）；
    #     C（只追加）属 ②（原 C3b 只断言「行数不减少」，一次写下与覆盖写无差别 => 腿偏弱）。
    ok('C3b ★只追加（a 语义）：两次 prune => 对账单**恰 2 行**', _after == 2,
       {'before': _before, 'after': _after})
    _recs2 = [json.loads(l) for l in io.open(led, encoding='utf-8') if l.strip()]
    ok('C3c ★第一行仍在（**覆盖写会让它消失**——这正是 C 站点要抓的性质）',
       bool(_recs2) and _recs2[0].get('pruned') == list(gone),
       {'first': _recs2[0] if _recs2 else None, 'expect': list(gone)})
    sb2 = tempfile.mkdtemp(prefix='i472_prune2_')
    try:
        rot3 = _mk_shards(sb2, n=4)
        rot3.keep_shards = 10
        led3 = os.path.join(rot3.archive, R.PRUNE_LEDGER)
        g3 = rot3.prune()
        ok('C4 ★反向（防过度收紧）：未超限 => 不剪任何分片（返回 []）', g3 == [], g3)
        ok('C4b 未剪 => 对账单未被创建（无剪枝就无对账）', not os.path.exists(led3))
    finally:
        shutil.rmtree(sb2, ignore_errors=True)
finally:
    shutil.rmtree(sb, ignore_errors=True)

print('')
print('断言总数 %d（PASS %d / FAIL %d）' % (PASS + FAIL, PASS, FAIL))
if FAILS:
    print('FAILED:')
    for f in FAILS:
        print('   - ' + f)
sys.exit(1 if FAILS else 0)