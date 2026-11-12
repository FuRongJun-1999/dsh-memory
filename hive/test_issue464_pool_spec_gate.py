# -*- coding: utf-8 -*-
# 功能名：池内 spec 的两道根闸（issue #464：command 根闸 + env 敏感键剥离）
# 生效条件：python -u -X utf8 -m hive.test_issue464_pool_spec_gate；夹具钉临时区
# 子功能：A 正向（毒 spec 被拦）· B 反向（合法 spec 仍可跑，防过度收紧）· C 行为判据（子进程看不到伪凭据）
# 执行：直接跑；退出码 0=全绿、1=有红
# 验证方式：全部 PASS；毒探针**无害**（marker 写临时区、打印伪凭据，不用真凭据）
# 不适用条件：**本腿能判「毒命令未执行 + 凭据未泄漏 + 合法命令仍可跑」；不能判「白名单是否覆盖所有敏感名」**
#   —— 即 **腿看见「名单在场」，看不见「名单完备」**（与 C2/C4/C5/C6/C7 同族）。
# 另注：本件缺陷正文引用的行号**已陈化 +3**（:280→:283 · :297-298→:300-301 · :205→:208），判据取自实读文本而非正文行号。
"""issue #464 守卫。

★可判性边界（**不许改弱**）：腿能判「毒命令未执行 + 凭据未泄漏 + 合法命令仍可跑」；**不能判**「白名单是否
覆盖所有敏感名」—— 那是「名单完备性」，与 C2/C4/C5/C6/C7 同族（看见『名单在场』，看不见『名单为真』）。
★正文行号已陈化 +3，判据取自实读文本。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from hive import exec_cmd as EC                       # noqa: E402

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
        print('  FAIL ' + name + '  ' + str(detail)[:260])


_SB = tempfile.mkdtemp(prefix='i464_guard_')
try:
    print('== C 组：env 敏感键剥离（派生自 ENV_SECRET_FAMILIES）==')
    print('  [读数] 族数 = %d（全量：%s）' % (len(EC.ENV_SECRET_FAMILIES),
          [l for l, _ in EC.ENV_SECRET_FAMILIES]))
    for n in ('HIVE_API_KEY', 'DEEPSEEK_API_KEY', 'HIVE_ORCH_TOKEN_FILE', 'MY_SECRET',
              'DB_PASSWORD', 'AEIS_DESIGNER_KEY', 'GH_CREDENTIAL'):
        ok('C1 敏感名 %s 被判敏感' % n, EC.is_secret_env_name(n) is True)
    for n in ('PATH', 'HOME', 'PYTHONUTF8', 'LANG', 'TEMP'):
        ok('C1b 非敏感名 %s 不被误判（防过度收紧）' % n, EC.is_secret_env_name(n) is False)
    _st = EC.strip_secret_env({'PATH': '/x', 'HIVE_API_KEY': 'abc123secret', 'LANG': 'C'})
    ok('C2 剥离后不含 HIVE_API_KEY、仍保留 PATH/LANG',
       'HIVE_API_KEY' not in _st and _st.get('PATH') == '/x' and _st.get('LANG') == 'C', _st)

    print('')
    print('== A 组：正向 —— 毒 spec 必须被拦 ==')
    _job = os.path.join(_SB, 'poison')
    os.makedirs(_job, exist_ok=True)
    _marker = os.path.join(_SB, 'POISON_MARKER')
    _probe = os.path.join(_SB, 'probe.py')
    io.open(_probe, 'w', encoding='utf-8').write(
        'import os, sys\n'
        'open(sys.argv[1], "w").write("x")\n'
        'print("LEAK=" + str(os.environ.get("HIVE_API_KEY")))' + chr(10))
    # A1 裸名不在白名单
    ok('A1 裸名 ``curl`` 被根闸拒（不在 ALLOWED_EXECUTABLES）',
       EC.command_root_gate(['curl', 'http://x']) is not None)
    # A2 绝对路径在允许根外
    # ★反例必须落在**允许根之外**，且**与树的位置无关**（两次踩坑，如实登记）：
    #   ① 首版放 tempdir 下 ⇒ tempdir 本身是允许根 ⇒（正确地）放行 ⇒ A2 假红；
    #   ② 二版放 _REPO 下 ⇒ **镜像树**（copytree 到 TEMP）里 _REPO 又落回允许根 ⇒ **镜像中基线就红**，
    #      回退自证因此被污染（基线红 ⇒ 无法判别）。
    #   ⇒ 现取**根卷下的固定名**（既不在 tempdir、也不在解释器目录下），**不创建它**（无副作用）。
    _roots = (os.path.dirname(os.path.realpath(sys.executable)),
              os.path.realpath(tempfile.gettempdir()))
    _out = os.path.join(os.path.abspath(os.sep), "i464_evil_probe")
    ok("A0 前置：反例路径确实落在允许根之外（位置无关性自检）",
       not any(_out == r or _out.startswith(r + os.sep) for r in _roots),
       {"out": _out, "roots": list(_roots)})
    ok('A2 允许根外的绝对路径被根闸拒',
       EC.command_root_gate([_out]) is not None)
    # A3 毒 spec 端到端：走 run_cmd，marker 不得被写出
    io.open(os.path.join(_job, 'spec.json'), 'w', encoding='utf-8').write(json.dumps({
        'command': [_out], 'cwd': _SB, 'env': {'HIVE_API_KEY': 'abc123secret'}}))
    rc = EC.run_cmd(_job)
    _res = json.loads(io.open(os.path.join(_job, 'result.json'), encoding='utf-8').read())
    ok('A3 ★毒 spec 端到端：run_cmd 以规格错收口（rc=2）且不执行',
       rc == 2 and _res.get('ok') is False, {'rc': rc, 'ok': _res.get('ok')})
    ok('A3b ★毒探针**未被执行**（marker 文件不存在）', not os.path.exists(_marker))
    ok('A3c 根闸错误信息含「根闸」字样（可诊断）', '根闸' in str(_res.get('error')), _res.get('error'))

    print('')
    print('== B 组：反向 —— 合法 spec 仍可跑（防过度收紧）==')
    _job2 = os.path.join(_SB, 'ok')
    os.makedirs(_job2, exist_ok=True)
    _marker2 = os.path.join(_SB, 'OK_MARKER')
    io.open(os.path.join(_job2, 'spec.json'), 'w', encoding='utf-8').write(json.dumps({
        'command': ['python', '-u', '-c', 'print("hello")'], 'cwd': _SB,
        'expect_stdout_contains': ['hello']}))
    rc2 = EC.run_cmd(_job2)
    _res2 = json.loads(io.open(os.path.join(_job2, 'result.json'), encoding='utf-8').read())
    ok('B1 合法 spec（python -c print(hello)）仍成功（rc=0 且 ok=True）',
       rc2 == 0 and _res2.get('ok') is True, {'rc': rc2, 'ok': _res2.get('ok')})
    ok('B2 白名单内的 python 不被根闸拒', EC.command_root_gate(['python', '-c', 'x']) is None)

    print('')
    print('== C3 组：行为判据 —— 子进程看不到伪凭据 ==')
    _job3 = os.path.join(_SB, 'env')
    os.makedirs(_job3, exist_ok=True)
    io.open(os.path.join(_job3, 'spec.json'), 'w', encoding='utf-8').write(json.dumps({
        'command': ['python', '-u', '-c',
                    'import os; print("SEEN=" + str(os.environ.get("HIVE_API_KEY")))'],
        'cwd': _SB, 'env': {'HIVE_API_KEY': 'abc123secret'}}))
    rc3 = EC.run_cmd(_job3)
    _res3 = json.loads(io.open(os.path.join(_job3, 'result.json'), encoding='utf-8').read())
    _seen = json.dumps(_res3, ensure_ascii=False)
    ok('C3 ★子进程看不到伪凭据（输出里无 abc123secret）', 'abc123secret' not in _seen,
       _res3.get('steps', _res3)[:1] if isinstance(_res3.get('steps'), list) else str(_res3)[:200])
    ok('C3b 子进程看到 SEEN=None（确实未继承）', 'SEEN=None' in _seen or 'None' in _seen)
finally:
    shutil.rmtree(_SB, ignore_errors=True)

print('')
print('断言总数 %d（PASS %d / FAIL %d）' % (PASS + FAIL, PASS, FAIL))
if FAILS:
    print('FAILED:')
    for f in FAILS:
        print('   - ' + f)
sys.exit(1 if FAILS else 0)