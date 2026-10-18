# -*- coding: utf-8 -*-
# 功能名：#303 五处设计边界收敛——O4 k 越界显式 warning / O5 非法 id 结构化错误
#           （O1/O2/O3 保持现状并在代码内文档化）
# 生效条件：python -u -X utf8 -m md_cg.test_issue303_design_boundaries [--mutate]
# 子功能：O4a-c k 越界 warning（10^18 / 501 / -1 / 0）· O4d 正常 k 不出现 warning
#         · O4e budget_tokens 路同样可见 · O5a-d 非法 id → invalid_node_id
#         · O5e-f 合法形态不存在 / 空串仍 null · O5g valid_node_id 判据单点
#         · E1-E3 文档与实现锚点；M1-M4 定点变异
# 执行：直接跑；--mutate 时回退 read 面判据/告警并替换 valid_node_id，要求指定红项非空
# 验证方式：断言全过 + 退出码 0；--mutate 下每条变异的红项集合必须非空且含指定项
# 不适用条件：① O1（NUL 合法）/O2（未知 content_kind 转审）/O3（op 推导）是
#   维护方裁定「保持现状」的三项，本守卫只钉**文档在位**，不要求行为改变；
#   ② 不覆盖协议真源 protocol.py 的形态表（非本单元授权文件）；
#   ③ 不测 500 条以上的真实分页（只钉信号在场，夹紧语义由 meta.cap 既有守卫覆盖）。
"""#303 守卫：设计边界收敛（O4/O5 修，O1/O2/O3 文档化）。"""
import argparse
import importlib.util
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASSED, FAILS = [], []

CCG = ("# 功能名：红按钮移动\n# 生效条件：问红按钮\n# 子功能：左移\n"
       "# 执行：红按钮控制角色左移\n# 验证方式：test\n# 不适用条件：问蓝按钮\n\n"
       "红按钮控制角色左移")


def _mk_lib():
    from md_cg.mdcos import MdCGOS
    root = tempfile.mkdtemp(prefix='i303_')
    cg = MdCGOS(root)
    for i in range(3):
        cg.add('k%d' % i, CCG.replace('红按钮', '红按钮%d' % i), layer='knowledge')
    return root, cg


def _suite(M=None, label=''):
    if label:
        print('-- %s --' % label)
    if M is None:
        from md_cg import mcp_server as M
    passed, failed = [], []

    def check(name, cond, detail=''):
        if cond:
            print('  PASS ' + name)
            passed.append(name)
        else:
            print('  FAIL ' + name + '  ' + str(detail)[:190])
            failed.append(name)
        return bool(cond)

    from md_cg.mdcg import GLOBAL_CAP
    root, cg = _mk_lib()
    try:
        # ---------- O4 k 越界 warning ----------
        base = M._cg_call(cg, {'op': 'read', 'query': '红按钮'})
        n_base = len(base.get('results') or [])
        w_big = M._cg_call(cg, {'op': 'read', 'query': '红按钮', 'k': 10 ** 18})
        w = w_big.get('warning') or {}
        check('O4a k=10^18 → warning.code=k_out_of_range 且 clamped_to=GLOBAL_CAP',
              w.get('code') == 'k_out_of_range' and w.get('clamped_to') == GLOBAL_CAP
              and w.get('k') == 10 ** 18, w)
        check('O4b k=10^18 结果集与缺省一致（夹紧行为不变，只加信号）',
              len(w_big.get('results') or []) == n_base, w_big.get('results'))
        w501 = M._cg_call(cg, {'op': 'read', 'query': '红按钮',
                               'k': GLOBAL_CAP + 1})
        check('O4c k=GLOBAL_CAP+1 → warning 在场',
              (w501.get('warning') or {}).get('code') == 'k_out_of_range', w501)
        wneg = M._cg_call(cg, {'op': 'read', 'query': '红按钮', 'k': -1})
        w0 = M._cg_call(cg, {'op': 'read', 'query': '红按钮', 'k': 0})
        check('O4d k=-1 → warning；k=0 → warning 且仍是空结果（#M1 语义不变）',
              (wneg.get('warning') or {}).get('k') == -1
              and (w0.get('warning') or {}).get('k') == 0
              and w0.get('results') == [], (wneg.get('warning'), w0.get('results')))
        check('O4e 正常 k=20：无 warning 键（不回归）', 'warning' not in base, base)
        wb = M._cg_call(cg, {'op': 'read', 'query': '红按钮',
                             'budget_tokens': 100000, 'k': 10 ** 18})
        wbn = M._cg_call(cg, {'op': 'read', 'query': '红按钮',
                              'budget_tokens': 100000, 'k': 20})
        check('O4f budget_tokens 路 k=10^18 → warning，且 pack 与缺省一致',
              (wb.get('warning') or {}).get('code') == 'k_out_of_range'
              and len(wb.get('pack') or []) == len(wbn.get('pack') or []), wb)

        # ---------- O5 非法 id 结构化错误 ----------
        bad = {'../etc/passwd': '穿越', 'C:\\Windows\\win.ini': '绝对路径',
               'a\x00b': 'NUL', 'x' * 5000: '超长'}
        for nid, tag in bad.items():
            r = M._cg_call(cg, {'op': 'read', 'node_id': nid})
            check('O5 非法 id（%s）→ 结构化 invalid_node_id（不是 null）' % tag,
                  isinstance(r, dict) and r.get('ok') is False
                  and r.get('error') == 'invalid_node_id' and r.get('node_id') == nid,
                  r)
        miss = M._cg_call(cg, {'op': 'read', 'node_id': 'no_such_node'})
        check('O5 合法形态但不存在 → 仍是协议登记的 null（node_missing 零回归）',
              miss is None, repr(miss)[:120])
        empty = M._cg_call(cg, {'op': 'read', 'node_id': ''})
        check('O5 空串仍是 #274 裁定的显式 node_missing（null，不转检索）',
              empty is None, repr(empty)[:120])
        okv = M._cg_call(cg, {'op': 'read', 'node_id': 'k0'})
        check('O5 合法 id 正路径不回归', isinstance(okv, dict)
              and okv.get('id') == 'k0', str(okv)[:120])

        # ---------- valid_node_id 判据单点 ----------
        from md_cg import mdcos as _MD
        check('O5g valid_node_id 单点：合法/非法矩阵',
              _MD.valid_node_id('k0') is True
              and _MD.valid_node_id('mem_1-2.中文,ok') is True
              and _MD.valid_node_id('../etc/passwd') is False
              and _MD.valid_node_id('a\x00b') is False
              and _MD.valid_node_id('x' * 129) is False
              and _MD.valid_node_id('') is False
              and _MD.valid_node_id(None) is False,
              [_MD.valid_node_id(x) for x in
               ('k0', 'mem_1-2.中文,ok', '../etc/passwd', 'a\x00b', 'x' * 129, '', None)])
        check('O5h restore 判据委派同一单点（_restore_id_ok is valid_node_id 语义）',
              _MD._restore_id_ok('k0') is True
              and _MD._restore_id_ok('../x') is False, '')
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    # ---------- E 文档/实现锚点（O1/O2/O3 保持现状 + 本批修点在场）----------
    msrc = open(os.path.join(_REPO, 'md_cg', 'mcp_server.py'),
                encoding='utf-8').read()
    dsrc = open(os.path.join(_REPO, 'md_cg', 'mdcos.py'),
                encoding='utf-8').read()
    check('E1 O1/O2/O3 裁定文档在位（#303 设计边界裁定块）',
          '#303 设计边界裁定（O1/O2' in msrc
          and 'NUL **判合法**' in msrc
          and '未知 content_kind **不硬拒**' in msrc
          and 'O3 op 缺失按签名推导' in msrc, '')
    check('E2 O4/O5 实现锚点在位（_k_warning / invalid_node_id）',
          'def _k_warning(' in msrc and '_k_warning(_int_arg(a, "k", 20))' in msrc
          and '"error": "invalid_node_id"' in msrc, '')
    check('E3 id 判据单点在 mdcos（valid_node_id 定义 + restore 委派）',
          'def valid_node_id(' in dsrc and 'return valid_node_id(node_id)' in dsrc, '')
    return passed, failed


def _load_mcp_mutant(text, tag):
    path = os.path.join(tempfile.mkdtemp(prefix='i303mut_'),
                        'mcp_server_%s.py' % tag)
    open(path, 'w', encoding='utf-8').write(text)
    name = 'md_cg.mcp_server_mut_%s' % tag
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _mutations():
    src = open(os.path.join(_REPO, 'md_cg', 'mcp_server.py'),
               encoding='utf-8').read()
    anchors = (
        ('M1 回退 O5（非法 id 不再结构化）',
         '            if _nid:\n'
         '                from .mdcos import valid_node_id as _valid_node_id\n'
         '                if not _valid_node_id(_nid):',
         '            if False:\n'
         '                from .mdcos import valid_node_id as _valid_node_id\n'
         '                if not _valid_node_id(_nid):'),
        ('M2 回退 O4 search 路 warning',
         '        if _kwarn:\n'
         '            _out["warning"] = _kwarn\n'
         '        return _out',
         '        if False:\n'
         '            _out["warning"] = _kwarn\n'
         '        return _out'),
        ('M3 回退 O4 budget 路 warning',
         '            if _kwarn and isinstance(_out, dict):',
         '            if False and isinstance(_out, dict):'),
        ('M4 k 判据恒真（warning 永不触发）',
         '    if 1 <= kv <= GLOBAL_CAP:',
         '    if True:'),
    )
    out = []
    for tag, old, new in anchors:
        n = src.count(old)
        if n != 1:
            print('  [FAIL] 变异锚点「%s」命中 %d 次（应为 1）' % (tag, n))
            FAILS.append('变异锚点 ' + tag)
            continue
        out.append((tag, src.replace(old, new)))
    return out


def _run_mutations():
    print('== 变异腿 ==')
    reds = {}
    expect = {
        'M1 回退 O5（非法 id 不再结构化）': 'O5 非法 id（穿越）→ 结构化 invalid_node_id（不是 null）',
        'M2 回退 O4 search 路 warning': 'O4a k=10^18 → warning.code=k_out_of_range 且 clamped_to=GLOBAL_CAP',
        'M3 回退 O4 budget 路 warning': 'O4f budget_tokens 路 k=10^18 → warning，且 pack 与缺省一致',
        'M4 k 判据恒真（warning 永不触发）': 'O4c k=GLOBAL_CAP+1 → warning 在场',
    }
    for i, (tag, text) in enumerate(_mutations()):
        mod = _load_mcp_mutant(text, 'm%d' % i)
        _, fail = _suite(mod, label=tag)
        reds[tag] = sorted(fail)
        print('  %s ⇒ 红项 %s' % (tag, reds[tag]))
        if not fail:
            FAILS.append('变异未转红：' + tag)
        elif expect.get(tag) and expect[tag] not in fail:
            FAILS.append('变异红项不含指定项：' + tag)

    # M5：valid_node_id 判据单点恒真（运行时替换——读面按调用时导入取用）
    print('-- M5 valid_node_id 恒真（合法性与存在性重新混同）--')
    from md_cg import mdcos as _MD
    orig = _MD.valid_node_id
    try:
        _MD.valid_node_id = lambda x: True
        _, fail5 = _suite(None, label='M5')
    finally:
        _MD.valid_node_id = orig
    reds['M5 valid_node_id 恒真'] = sorted(fail5)
    print('  M5 valid_node_id 恒真 ⇒ 红项 %s' % reds['M5 valid_node_id 恒真'])
    want5 = 'O5 非法 id（穿越）→ 结构化 invalid_node_id（不是 null）'
    if not fail5:
        FAILS.append('变异未转红：M5')
    elif want5 not in fail5:
        FAILS.append('变异红项不含指定项：M5')
    print('  变异红项集合：%s' % reds)
    return reds


def main():
    ap = argparse.ArgumentParser(description='#303 设计边界守卫')
    ap.add_argument('--mutate', action='store_true', help='定点变异自证')
    args = ap.parse_args()
    print('== #303 守卫 ==')
    try:
        ps, fs = _suite()
        PASSED.extend(ps)
        FAILS.extend(fs)
    except Exception as e:
        import traceback
        traceback.print_exc()
        FAILS.append('全套判据内异常（fail-closed）')
    if args.mutate:
        try:
            _run_mutations()
        except Exception as e:
            import traceback
            traceback.print_exc()
            FAILS.append('变异腿内异常（fail-closed）')
    print('=' * 60)
    print('#303 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
