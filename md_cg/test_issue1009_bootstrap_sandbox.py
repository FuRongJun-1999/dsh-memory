# -*- coding: utf-8 -*-
"""LLM 产出代码沙箱的帧取道（issue #1009 第 5 项最后一条）。

【守什么】
scripts/bootstrap_loop.py 的 _safe_exec_gen 与 verifier.py 子进程执行器
（_EXEC_RUNNER_SRC 里的 _ast_gate）都靠**属性名 denylist** 拦反射逃逸。
实测可绕（生成器帧链，属性名都不带 dunder）：

    def g():
        gl = gen.gi_frame.f_back.f_back.f_globals
        yield gl['os']
    gen = g()
    for mod in gen:
        mod.remove('<victim>')     # 沙箱内删掉了沙箱外的文件

【改法】属性面是开放集合，denylist 必然漏：
  · bootstrap_loop：属性面改**白名单** _GEN_SAFE_ATTRS（纯计算够用），默认拒；
  · verifier：单元表有合法 dunder 用法（拦 dunder 会误伤 19 条），故保持最小集，
    但把**帧/生成器/协程/回溯**属性补进 _ESCAPE_ATTRS（unit 表对这些名称零命中）。

运行：python -X utf8 -m md_cg.test_issue1009_bootstrap_sandbox
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OK = 0
_BAD = []


def ok(cond, name, extra=''):
    global _OK
    if cond:
        _OK += 1
        print('  ok   %s %s' % (name, extra))
    else:
        _BAD.append(name)
        print('  FAIL %s %s' % (name, extra))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    # dataclasses 需要模块已在 sys.modules 里（否则 cls.__module__ 查不到）。
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


ESCAPE = (
    'def g():\n'
    '    gl = gen.gi_frame.f_back.f_back.f_globals\n'
    '    yield gl["os"]\n'
    'gen = g()\n'
    'for mod in gen:\n'
    '    mod.remove(%r)\n'
)


def main():
    print('=== issue #1009 第 5 项：帧取道（生成器 → 宿主 globals）===')
    bl = _load('bl_sbx', os.path.join('scripts', 'bootstrap_loop.py'))
    f = bl._safe_exec_gen

    d = tempfile.mkdtemp()
    victim = os.path.join(d, 'victim.txt')
    with open(victim, 'w', encoding='utf-8') as fh:
        fh.write('hi')
    payload = ESCAPE % victim.replace('\\', '/')
    try:
        f(payload)
        blocked = False
    except ValueError:
        blocked = True
    ok(blocked, 'B1 bootstrap 沙箱拒绝帧取道（此前可执行）')
    ok(os.path.exists(victim), 'B2 沙箱外文件未被删')

    for attr in ('gi_frame', 'gi_code', 'f_back', 'f_globals', 'f_locals',
                 'cr_frame', 'ag_frame', 'tb_frame'):
        try:
            f('x = obj.%s\n' % attr)
            hit = False
        except ValueError:
            hit = True
        ok(hit, 'B3 属性 .%s 被拒' % attr)

    legit = [
        ('def s(arr):\n    arr.sort()\n    return arr\n', 's', [3, 1, 2], [1, 2, 3]),
        ('def s(x):\n    return x.strip().upper()\n', 's', '  ab ', 'AB'),
        ("def s(d):\n    return d.get('a', 0) + d.get('b', 0)\n", 's', {'a': 1, 'b': 2}, 3),
        ('def s(n):\n    return sum(x*x for x in range(n))\n', 's', 4, 14),
        ('def s(xs):\n    return sorted(set(xs))\n', 's', [3, 1, 1], [1, 3]),
    ]
    n_ok = 0
    for code, fn, arg, want in legit:
        try:
            if f(code)[fn](arg) == want:
                n_ok += 1
        except Exception:               # noqa: BLE001
            pass
    ok(n_ok == len(legit), 'B4 合法纯计算仍可用（%d/%d）' % (n_ok, len(legit)))

    src = open(os.path.join(REPO, 'scripts', 'bootstrap_loop.py'), encoding='utf-8').read()
    ok('_GEN_SAFE_ATTRS' in src and 'node.attr not in _GEN_SAFE_ATTRS' in src,
       'B5 bootstrap 属性面是白名单（not in 判据）')

    # ---- verifier：直接跑它子进程执行器源码里的 _ast_gate ----
    vf = _load('vf_sbx', os.path.join('md_cg', 'whitebox_kb', 'wisdom', 'verifier.py'))
    ns = {'__name__': 'runner_gate_probe'}
    try:
        exec(compile(vf._EXEC_RUNNER_SRC, '<runner>', 'exec'), ns)
    except BaseException:              # noqa: BLE001——其 main() 会读 sys.argv，跑到就 IndexError
        pass
    gate = ns.get('_ast_gate')
    ok(callable(gate), 'V1 取到子进程执行器的 _ast_gate')
    try:
        gate(payload)
        vblocked = False
    except ValueError:
        vblocked = True
    ok(vblocked, 'V2 verifier 拒绝帧取道（此前可执行）')
    for attr in ('gi_frame', 'gi_code', 'f_back', 'f_globals', 'cr_frame', 'tb_frame'):
        try:
            gate('x = obj.%s\n' % attr)
            hit = False
        except ValueError:
            hit = True
        ok(hit, 'V3 verifier 拒 .%s' % attr)
    try:
        gate('def solve(arr):\n    arr.sort()\n    return arr\n')
        vok = True
    except ValueError:
        vok = False
    ok(vok, 'V4 verifier 对合法纯计算不误伤')

    print()
    print('沙箱帧取道守卫：%d 通过，%d 失败' % (_OK, len(_BAD)))
    if _BAD:
        print('失败项：' + ' / '.join(_BAD))
    return 1 if _BAD else 0


if __name__ == '__main__':
    sys.exit(main())
