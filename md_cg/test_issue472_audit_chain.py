# -*- coding: utf-8 -*-
# 功能名：审计追加段哈希链的守卫（issue #472 · 站点 1+2 的载体）
# 生效条件：python -u -X utf8 -m md_cg.test_issue472_audit_chain；夹具钉临时区
# 子功能：C1 三档 reason 互异 · C2 已登记偏差被钉住（回落字面量 == 真源值）· A 链校验四档 · B 反向防过度收紧
# 执行：直接跑；退出码 0=全绿
# 验证方式：全部 PASS；A 组**真造反例**（篡改/插入/截断），不 mock
# 不适用条件：**不能判**「哈希链的信任根是否被持有者换过」—— 若被审计方同时握有链密钥与写权限，
#   它可以**重算整条链**使校验通过；那已越出「可判」，进入「权限模型」（与 C2/C5/C7 同族）。
from __future__ import annotations

import ast, io, json, os, shutil, sys, tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from md_cg import mdcos as M                          # noqa: E402

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


ok('C1 三档 reason 值互不相同（不同原因不得产出同一信号）',
   len({M.AUDIT_CHAIN_BROKEN, M.AUDIT_KNOWN_DEGRADED, M.AUDIT_UNKNOWN_FOREIGN}) == 3,
   [M.AUDIT_CHAIN_BROKEN, M.AUDIT_KNOWN_DEGRADED, M.AUDIT_UNKNOWN_FOREIGN])

_src = io.open(os.path.join(_REPO, 'md_cg', 'rollback.py'), encoding='utf-8').read()
_lits = []
for _n in ast.walk(ast.parse(_src)):
    if isinstance(_n, ast.Assign) and any(getattr(t, 'id', '') == '_KD' for t in _n.targets):
        if isinstance(_n.value, ast.Constant) and isinstance(_n.value.value, str):
            _lits.append(_n.value.value)
print('  [读数] rollback.py 中 _KD 字面量赋值 %d 处（全量：%s）' % (len(_lits), _lits))
ok('C2 已登记的已知偏差被钉住：回落字面量 == mdcos.AUDIT_KNOWN_DEGRADED（真源值）',
   bool(_lits) and all(x == M.AUDIT_KNOWN_DEGRADED for x in _lits),
   {'lits': _lits, 'truth': M.AUDIT_KNOWN_DEGRADED})

sb = tempfile.mkdtemp(prefix='i472_guard_')
try:
    log = os.path.join(sb, '_audit.jsonl')
    for i in (1, 2):
        rec = {'t': 1.0 * i, 'op': 'add', 'id': 'n%d' % i, 'actor': 'a'}
        M._audit_chain_link(log, rec)
        io.open(log, 'a', encoding='utf-8').write(json.dumps(rec, ensure_ascii=False) + chr(10))
    raw = io.open(log, encoding='utf-8').read().splitlines()
    ok('A0 基线两行链内行 => ok', M._audit_chain_verify(log)[0] == 'ok')
    o = json.loads(raw[1]); o['op'] = 'TAMPERED'
    p2 = os.path.join(sb, 't.jsonl')
    io.open(p2, 'w', encoding='utf-8').write(raw[0] + chr(10) + json.dumps(o, ensure_ascii=False) + chr(10))
    v, r, d = M._audit_chain_verify(p2)
    ok('A1 链内被改行 => tampered / AUDIT_CHAIN_BROKEN（硬失败）',
       v == 'tampered' and r == M.AUDIT_CHAIN_BROKEN, (v, r, d))
    p3 = os.path.join(sb, 'd.jsonl')
    io.open(p3, 'w', encoding='utf-8').write(raw[0] + chr(10) + json.dumps(
        {'t': 2.0, 'op': 'add', 'id': 'x', 'chain': M.AUDIT_KNOWN_DEGRADED}, ensure_ascii=False) + chr(10))
    v, r, d = M._audit_chain_verify(p3)
    ok('A2 已知退化链外行 => known_degraded / AUDIT_KNOWN_DEGRADED（软信号）',
       v == 'known_degraded' and r == M.AUDIT_KNOWN_DEGRADED, (v, r, d))
    p4 = os.path.join(sb, 'f.jsonl')
    io.open(p4, 'w', encoding='utf-8').write(raw[0] + chr(10) + json.dumps(
        {'t': 2.0, 'op': 'insert', 'id': 'y'}, ensure_ascii=False) + chr(10))
    v, r, d = M._audit_chain_verify(p4)
    ok('A3 未知链外插入 => unknown_foreign / AUDIT_UNKNOWN_FOREIGN（硬失败）',
       v == 'unknown_foreign' and r == M.AUDIT_UNKNOWN_FOREIGN, (v, r, d))
    p5 = os.path.join(sb, 'tr.jsonl')
    io.open(p5, 'w', encoding='utf-8').write(raw[0] + chr(10) + raw[1][:max(1, len(raw[1]) // 2)] + chr(10))
    v, r, d = M._audit_chain_verify(p5)
    ok('A4 截断尾行 => tampered / AUDIT_CHAIN_BROKEN', v == 'tampered' and r == M.AUDIT_CHAIN_BROKEN, (v, r, d))
    p6 = os.path.join(sb, 'e.jsonl')
    io.open(p6, 'w', encoding='utf-8').write('')
    v, r, d = M._audit_chain_verify(p6)
    ok('B 反向（防过度收紧）：空文件 => ok，不误红', v == 'ok' and r is None, (v, r, d))
finally:
    shutil.rmtree(sb, ignore_errors=True)

print('')
print('断言总数 %d（PASS %d / FAIL %d）' % (PASS + FAIL, PASS, FAIL))
if FAILS:
    print('FAILED:')
    for f in FAILS:
        print('   - ' + f)
sys.exit(1 if FAILS else 0)