# -*- coding: utf-8 -*-
# 功能名：密文判定/验签/本地复写的可验证证据判据（issue #446 #453 #403）
# 生效条件：python -u -X utf8 -m md_cg.test_issue446_453_403_verified_evidence [--mutate]
# 子功能：A 组＝行为面（#446 判据分离 4 条 + #453/#403 谓词直调六态表）
# 执行：--mutate 时逐条退化，守卫须按指定项转红
# 验证方式：全部 PASS 即通过；红项须与预期逐项相符
# 不适用条件：① 看不见 dek 是否正确/被轮转；② 看不见攻击者同时伪造 tag；③ 不判性能。
# ★ M1a 红 {A1,A6,E2} 中的 **A6 是连带**：M1a 让结构验证恒真 => 伪造块也被
#   `_actor_has_ciphertext` 认作密文（真因果）。**A6 的独立面由 M2 钉住。**
# ★ M1a 与 M1b **是一对变异而非一条**：M1a 打 `dek=None` 路径、M1b 打 `dek` 路径。
#   **`A4` 钉的是「有 dek 时必须真试算」；它不钉「无 dek 时的结构验证强度」**（后者由 A1 与 K1 钉）。
# ★ 本通道放行的包**未经验签**；`reasons` 里含未验证说明。若调用方需要机器可读的
#   「未验证」标志，请向 Lead 申请扩 `mode_parity` 白名单后再加键（现在不加是为了不改返回体形状）。
# ★ M3 钉的是「**无 sig 键必须拒**」这一支（不是「声明为空」那支）。
# ★ 形态名「判据方向反转」：语法对/跑得通/无异常，但语义正好相反（该拦的放行）。
#   唯一抓法＝**逐态核对**：任何返回布尔的判据函数，必须给一张「输入态 × 期望真值」表（≥3 态）。
# ★ verify_encrypted 的 **AAD 必须与 seal_node 时用的 (node_id, tenant, actor) 一致**；不一致则解密必失败，
#   而**失败表现为 False，与「内容不是密文」同形** ⇒ 用错参数会得出「它不是密文」的错误结论。
# ★ **A4（正确 dek ⇒ True）与 K2（错 dek ⇒ False 且不抛）是一对，不是两条独立断言**：
#   A4 抓「恒 False」、K2 抓「恒 True 或抛异常」；**缺任一条，另一个方向就漏**（本批 A4 已实证抓到真缺陷）。
# ★ 形态名「以声明值作为豁免凭据」：sig.signer = null 就让空签名绕过拒绝（#453）。
# ★ 侧 B（旧包覆写新本地）由 #191-B 的重放闸保证 ⇒ E6 钉住那道闸不被删。
"""U03 守卫（#446/#453/#403）。"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import crypto as _c
from md_cg import evidence as _e

PASSED, FAILS = [], []
DEK = b'k' * 32
GOOD = _c.seal_node('hello world', DEK, 'n1', 't', 'a')
FAKE = _c.ENC_PREFIX + 'fp123456:!!!!' + _c.ENC_SUFFIX


def _check(name, cond, detail=''):
    if cond:
        print('  PASS ' + name)
        PASSED.append(name)
    else:
        print('  FAIL ' + name + '  ' + str(detail)[:200])
        FAILS.append(name)


def group_a():
    print('== A 组：行为面 ==')
    _check('A1 判据分离：伪造块 is_encrypted=True / verify_encrypted=False',
           _c.is_encrypted(FAKE) is True and _c.verify_encrypted(FAKE) is False)
    _check('A4 真密文 + 正确 dek -> verify True（不把功能关掉）',
           _c.verify_encrypted(GOOD, DEK, 'n1', 't', 'a') is True)
    try:
        _c.open_node(FAKE, DEK, 'n1', 't', 'a')
        raised = False
    except _c.CryptoError:
        raised = True
    _check('A3 坏块 open_node -> CryptoError', raised)
    # 临时件一律落 `.tmp/<单元>/`（派工书 §0）；用完即删，不在仓外留痕。
    _r6 = os.path.join(_REPO, '.tmp', 'u03', 'a6')
    os.makedirs(_r6, exist_ok=True)
    try:
        with open(os.path.join(_r6, 'fake.md'), 'w', encoding='utf-8') as _f:
            _f.write(_c.ENC_PREFIX + _c.identity_fingerprint('t', 'a') + ':!!!!' + _c.ENC_SUFFIX)
        _check('A6 :396 短路不认伪造块（_actor_has_ciphertext 对只含伪造块的根 => False）',
               _c._actor_has_ciphertext(_r6, 't', 'a') is False,
               'got=%r' % (_c._actor_has_ciphertext(_r6, 't', 'a'),))
    finally:
        import shutil as _sh
        _sh.rmtree(_r6, ignore_errors=True)
    _check('A5b 本地节点一律阻断（索引无 updated_at ⇒ 不做时间比较；#191-C 逐字）',
           _e._local_generation_blocks('x', {'tags': [], 'created_at': 999999}, 100) is True
           and _e._local_generation_blocks('x', {'tags': []}, 100) is True
           and _e._local_generation_blocks('x', {'tags': [], 'updated_at': 1}, 100) is True)
    _check('A2 #453 谓词：空签名 + 自报 signed=False -> **拒**（True；自报值不是凭据）',
           _e._signer_declaration_rejected({'sig': {'signer': 'null', 'signature': '', 'signed': False}}, '') is True)
    _check('A2b3 声称签了（signed 非 False）但空签名 -> 拒（(b) 的边界）',
           _e._signer_declaration_rejected({'sig': {'signer': 'x', 'signature': '', 'signed': True}}, '') is True)
    _check('A2b4 无 sig 键 -> 拒（结构性缺失）',
           _e._signer_declaration_rejected({}, '') is True)
    _check('A2b #453 谓词：有签名 -> 不拒（False）',
           _e._signer_declaration_rejected({'sig': {}}, 'abc') is False)
    _check('A2c #453 谓词：空串签名（任意自报块）一律拒（三态一致）',
           all(_e._signer_declaration_rejected(
               {'sig': {'signer': s, 'signature': '', 'signed': b}}, '') is True
               for s in ('null', '', 'hmac-local') for b in (False, True)))
    tbl = [
        ('本地节点存在（任意时间戳）⇒ 阻断', {'tags': [], 'created_at': 999999}, 100, True),
        ('本地节点存在但时间戳更旧 ⇒ **仍阻断**（索引无代际键，按 #191-C 一律不覆写）',
         {'tags': [], 'updated_at': 50}, 100, True),
        ('无 prev', None, 100, False),
        ('xnode 跨节点', {'tags': [_e.TAG_XNODE], 'updated_at': 200}, 100, False),
        ('无任何时间戳的本地节点 ⇒ 阻断', {'tags': []}, 100, True),
    ]
    for label, prev, created, exp in tbl:
        got = _e._local_generation_blocks('x', prev, created)
        _check('A5 六态表 · ' + label + ' -> ' + str(exp), got is exp, 'got=%r' % (got,))


def group_k():
    print('== K 组：反向腿① ==')
    _check('K1 真密文（无 dek 结构验证）-> True', _c.verify_encrypted(GOOD) is True)
    ok = True
    try:
        r = _c.verify_encrypted(GOOD, b'w' * 32, 'n1', 't', 'a')
    except Exception:
        ok = False
        r = None
    _check('K2 错 dek -> 返回 False 且**不抛**（抓「恒 True/抛异常」）', ok and r is False,
           'raised=%r r=%r' % (not ok, r))
    _check('K3 明文不受影响（两个判定都 False）',
           _c.verify_encrypted('plain') is False and _c.is_encrypted('plain') is False)
    _check('K4 真密文 open_node 往返一致',
           _c.open_node(GOOD, DEK, 'n1', 't', 'a') == 'hello world')


def _src(rel):
    with open(os.path.join(_REPO, 'md_cg', rel), encoding='utf-8') as f:
        return f.read()


def _fn(rel, name):
    import ast as _ast
    for node in _ast.walk(_ast.parse(_src(rel), rel)):
        if isinstance(node, _ast.FunctionDef) and node.name == name:
            return _ast.unparse(node)
    return ''


def group_e():
    print('== E 组：AST 结构断言 ==')
    ie = _fn('crypto.py', 'is_encrypted')
    _check('E1 is_encrypted 未改（仍 startswith + ENC_PREFIX）',
           'startswith' in ie and 'ENC_PREFIX' in ie)
    ve = _fn('crypto.py', 'verify_encrypted')
    _check('E2 verify_encrypted 含 _b64d + NONCE_LEN',
           '_b64d' in ve and 'NONCE_LEN' in ve)
    _check('E3 :396 所在函数经 verify_encrypted',
           'verify_encrypted' in _fn('crypto.py', '_actor_has_ciphertext'))
    _bb = _fn('evidence.py', 'import_pack')
    _check('E4 import_pack 体内无 null 豁免（AST 函数体口径，不是全文文本）',
           chr(34) + 'null' + chr(34) not in _bb and chr(39) + 'null' + chr(39) not in _bb)
    _check('E5 evidence 有 _local_generation_blocks 谓词',
           '_local_generation_blocks' in _src('evidence.py'))
    _check('E6 【侧 B 的保证】#191-B 重放闸 created <= last 在位',
           'created <= last' in _src('evidence.py'))
    _check('E7 #403 判据载体在循环外先代际探活（import_pack 体内调 _maybe_reload_index）',
           '_maybe_reload_index' in _bb)
    _check('E8 #453 站点2 created_at 上界常量被 import_pack 消费',
           'MAX_PACK_FUTURE_SKEW' in _bb and 'MAX_PACK_FUTURE_SKEW' in _src('evidence.py'))


def group_t():
    """端到端（真库、真签名器）：#453 未来时间戳 / #403 陈旧索引。"""
    print('== T 组：端到端 ==')
    import contextlib, io, json, tempfile, time
    from unittest.mock import patch
    from md_cg import signer as _sg, tokens as _tk
    from md_cg.mdcos import MdCGSecure as _CG
    from md_cg.mcp_server import call_tool as _call

    d = tempfile.mkdtemp(prefix='u03_guard_')
    env = {'MDCG_ROOT': d + '/brain', 'MDCG_STATE_ROOT': d + '/state',
           'MDCG_AUX_ROOT': d + '/auxstore', 'MDCG_DATA_ROOT': d + '/data',
           'MDCG_EXPORT_ROOT': d, 'MDCG_TOKEN_FILE': d + '/auxstore/tokens.json',
           'MDCG_SIGNERS_FILE': d + '/auxstore/_signers.json',
           'MDCG_SIGNER_KEY_FILE': d + '/auxstore/_signer.key',
           'MDCG_SWARM_DIR': d + '/swarm', 'MDCG_SUSTAIN': '0', 'MDCG_SLEEP': '0'}
    with patch.dict(os.environ, env), contextlib.redirect_stderr(io.StringIO()):
        tf = env['MDCG_TOKEN_FILE']

        def _pr():
            return _tk.verify_token(_tk.issue('designer', actor='u03g', path=tf)['token'], path=tf)

        _sg.set_policy(_e.SUBSYSTEM, signer='hmac-local',
                       sign_on=['handshake', 'evidence'],
                       require_peer_signature=True, on_verify_fail='reject')

        def _pack(pid, created, node_id='o1', text='x'):
            p = {'schema': 1, 'kind': _e.KIND, 'from_node': 'peer-a',
                 'from_root': '', 'theory': [], 'created_at': created,
                 'subjects': [], 'pack_id': pid,
                 'items': [{'subject': 'peer:alice', 'node_id': node_id,
                            'text': text, 'sensitivity': 'internal',
                            'layer': 'knowledge', 'importance': 0.5,
                            'verification_basis': 'data'}]}
            s = _sg.sign_for(_e.SUBSYSTEM, _e._pack_payload(p), action=_e.SIGN_ACTION)
            p['sig'] = {'signer': s.get('signer'), 'signature': s.get('signature') or '',
                        'signed': bool(s.get('signed'))}
            f = os.path.join(d, pid + '.json')
            io.open(f, 'w', encoding='utf-8').write(json.dumps(p, ensure_ascii=False))
            return f

        # A9：#453 站点1 的**接线**（不是只测谓词）——策略不要求对端签名时，
        # verify_for 会放行空签名；唯一拦得住的是 import_pack 对谓词的消费点。
        # 三种对端自报形态都必须被拒，否则「伪造 source:<任意节点>」复活。
        _sg.set_policy(_e.SUBSYSTEM, signer='hmac-local',
                       sign_on=['handshake', 'evidence'],
                       require_peer_signature=False, on_verify_fail='degrade')
        cg_u = _CG(env['MDCG_ROOT'], principal=_pr(), autoflush=1)
        for _tag, _sig in (('A9a 无 sig 键', None),
                           ('A9b signer=null/空签/signed=False',
                            {'signer': 'null', 'signature': '', 'signed': False}),
                           ('A9c signer=空/空签/signed=False',
                            {'signer': '', 'signature': '', 'signed': False}),
                           ('A9d signer=null/空签/signed=True',
                            {'signer': 'null', 'signature': '', 'signed': True})):
            _p = {'schema': 1, 'kind': _e.KIND, 'from_node': 'peer-victim',
                  'from_root': '', 'theory': [], 'created_at': time.time(),
                  'subjects': [], 'pack_id': 'pk9' + str(abs(hash(_tag)) % 10000),
                  'items': [{'subject': 'peer:victim', 'node_id': 'orig-1',
                             'text': '无凭据来源声明', 'sensitivity': 'internal',
                             'layer': 'knowledge', 'importance': 0.5,
                             'verification_basis': 'data'}]}
            if _sig is not None:
                _p['sig'] = _sig
            _f = os.path.join(d, 'pk9.json')
            io.open(_f, 'w', encoding='utf-8').write(json.dumps(_p, ensure_ascii=False))
            _r = _e.import_pack(cg_u, _f, archive=False)
            _check(_tag + ' -> 拒收（接线：空签名在 import_pack 被拦，不只谓词）',
                   _r.get('ok') is False and _r.get('rejected') is True
                   and _r.get('imported') in (None, 0), 'got=%r' % (_r,))
        _sg.set_policy(_e.SUBSYSTEM, signer='hmac-local',
                       sign_on=['handshake', 'evidence'],
                       require_peer_signature=True, on_verify_fail='reject')
        cg_u.close()

        # A7：未来时间戳整包拒收
        cg = _CG(env['MDCG_ROOT'], principal=_pr(), autoflush=1)
        r = _e.import_pack(cg, _pack('pack-future', 9e15), archive=False)
        _check('A7 #453 站点2：created_at=9e15 -> 整包拒收（ok=False）',
               r.get('ok') is False and r.get('rejected') is True, 'got=%r' % (r,))
        r2 = _e.import_pack(cg, _pack('pack-legit', time.time() + 1), archive=False)
        _check('A7b 紧接合法包 -> 能导入（台账未被未来时间戳毒化）',
               r2.get('ok') is True and r2.get('imported') == 1, 'got=%r' % (r2,))
        cg.close()

        # A8：#403 陈旧索引（他进程写入）——导入不得覆写本地节点
        # 独立 node_id（o403）：与上面 A7 组已导入的 o1 隔离，否则「陈旧索引」前置不成立。
        cg_stale = _CG(env['MDCG_ROOT'], principal=_pr(), autoflush=1)
        xid = _e._xnode_id('peer-a', 'o403')
        cg_w = _CG(env['MDCG_ROOT'], principal=_pr(), autoflush=1)   # 「他进程」
        cg_w.add(xid, '本地原文：只有属主知道的口令 X', layer='knowledge',
                 sensitivity='internal')
        cg_w.close()
        _check('A8a 前置：本进程索引确实陈旧（不含 xid）',
               xid not in (cg_stale.index.get('nodes') or {}))
        r3 = _e.import_pack(cg_stale, _pack('pack-403', time.time() + 1,
                                           node_id='o403'), archive=False)
        disk = ''
        for root, _ds, fs in os.walk(env['MDCG_ROOT']):
            for fn in fs:
                if fn.endswith(xid + '.md'):
                    disk = io.open(os.path.join(root, fn), encoding='utf-8').read()
        _check('A8 #403：陈旧索引下同名本地节点不被覆写（imported=0/skipped=1/盘面原文）',
               r3.get('imported') == 0 and r3.get('skipped') == 1
               and '只有属主知道的口令 X' in disk,
               'got=%r disk_local=%r' % (r3, '只有属主知道的口令 X' in disk))
        cg_stale.close()


def main():
    print('== U03 守卫 ==')
    try:
        group_a()
        group_k()
        group_e()
        group_t()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        _check('A0 组内异常（fail-closed）', False, str(exc)[:100])
    print('=' * 60)
    print('U03 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if (FAILS or (_mutate() if '--mutate' in sys.argv else 0)) else 0


_MUT = (
    ('M1a 退化 dek=None 结构验证（_b64d -> 常量）',
     'md_cg/crypto.py',
     (("        raw = _b64d(body)", "        raw = b'x' * 64"),),
     ('A1', 'A6', 'E2')),
    ('M1b dek 路径恒 False', 'md_cg/crypto.py', (('        open_node(content, dek, node_id, tenant, actor)', '        raise ValueError(1)'),), ('A4',)),
    ('M2 :396 短路改回前缀',
     'md_cg/crypto.py',
     (("            if verify_encrypted(content) and enc_id_fp(content) == fp:",
       "            if is_encrypted(content) and enc_id_fp(content) == fp:"),),
     ('A6', 'E3')),
    ('M3 恢复「自报 signed=False 即豁免」（谓词恒 False）',
     'md_cg/evidence.py',
     (('    return not (signature or "").strip()',
       '    return False'),),
     ('A2', 'A2b3', 'A2b4', 'A2c', 'A9a', 'A9b', 'A9c', 'A9d')),
    ('M4 撤本地节点阻断（_local_generation_blocks 恒 False）',
     'md_cg/evidence.py',
     (('    return True', '    return False'),),
     ('A5', 'A5b', 'A8')),
    ('M5 撤 created_at 上界（未来时间戳可推进台账）',
     'md_cg/evidence.py',
     (("    if created > time.time() + MAX_PACK_FUTURE_SKEW:",
       "    if False:"),),
     ('A7', 'A7b')),
    ('M6 撤循环外代际探活（陈旧索引复活 #403）',
     'md_cg/evidence.py',
     (('    _reload = getattr(cg, "_maybe_reload_index", None)',
       '    _reload = None'),),
     ('A8', 'E7')),
    ('M7 断开谓词与消费点（#453 接线：谓词仍在但 import_pack 不再调用）',
     'md_cg/evidence.py',
     (('    if _signer_declaration_rejected(pack, signature):',
       '    if False:'),),
     ('A9a', 'A9b', 'A9c', 'A9d')),
)


def _mutate():
    import shutil, subprocess, tempfile
    print('!! 反向腿②')
    tree = tempfile.mkdtemp(prefix='u03_mut_')
    shutil.copytree(os.path.join(_REPO, 'md_cg'), os.path.join(tree, 'md_cg'),
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    bad = []
    try:
        def run():
            env = dict(os.environ)
            env['PYTHONPATH'] = tree + os.pathsep + _REPO   # 后者供 utf8_boot（仓根模块）
            env['PYTHONUTF8'] = '1'
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            pr = subprocess.run([sys.executable, '-u', '-X', 'utf8', '-m',
                                 'md_cg.test_issue446_453_403_verified_evidence'],
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', cwd=tree, env=env, timeout=900)
            out = (pr.stdout or '') + (pr.stderr or '')
            return pr.returncode, [l.split('FAIL ', 1)[1].strip() for l in out.splitlines()
                                   if l.strip().startswith('FAIL ')], out
        rc, reds, out = run()
        print('  镜像基线：rc=%d 红项=%d' % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append('基线即红')
            print(chr(10).join(out.splitlines()[-8:]))
        for desc, rel, pairs, exp in _MUT:
            p = os.path.join(tree, rel)
            bak = open(p, encoding='utf-8', newline='').read()
            mut, miss = bak, ''
            for o, n in pairs:
                if mut.count(o) != 1:
                    miss = '命中 %d 次' % mut.count(o)
                    break
                mut = mut.replace(o, n, 1)
            if miss:
                bad.append(desc)
                print('  ANCHOR-MISS ' + desc + ' ' + miss)
                continue
            open(p, 'w', encoding='utf-8', newline='').write(mut)
            for r2, _d, _f in os.walk(tree):
                if os.path.basename(r2) == '__pycache__':
                    shutil.rmtree(r2, ignore_errors=True)
            rc2, reds2, _o = run()
            open(p, 'w', encoding='utf-8', newline='').write(bak)
            hit = sorted({r.split(' ')[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print('  OK   %s 红项=%d 命中=%s' % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print('  MISMATCH %s 实际=%s 期望=%s' % (desc, hit, sorted(exp)))
        print('反向腿②：%s（%d 不合格）' % ('PASS' if not bad else 'FAIL', len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
