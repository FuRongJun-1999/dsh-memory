# -*- coding: utf-8 -*-
'''P1-4 三级回落链守卫（issue #85「选 A」，2026-10-10 设计者裁定）。

承诺来源：md_cg/test_security_audit_b26.py 的 P1-4e 处理由写明
「三级回落链的完整覆盖见新增守卫 md_cg/test_p14_root_fallback.py
（含正对照与定点变异自证）」——本文件即该承诺件。

语义（md_cg/security.py 的 _whitelist_roots）：
  ① env_var（MDCG_INGEST_ROOT / MDCG_EXPORT_ROOT）已配置 ⇒ 用它（os.pathsep 多根）
  ② 未配置 ⇒ 回落 mdcg 实际配置库根（MDCG_ROOT / paths.json 的 root，
     或该库根目录已存在）
  ③ 连库根也无（空白态）⇒ 以工作区（cwd）为根，并写进用户级 paths.json 的
     root（一次性、幂等）

隔离（不碰真实用户配置、不读仓内 legacy）：
  · MDCG_STATE_ROOT 指向 tempfile 沙箱 ⇒ set_user_root 只写沙箱内 paths.json；
  · datapath.legacy_paths_file 指向沙箱内的空位 ⇒ 兼容读不外溢到 <仓>/data；
  · datapath.set_user_root 加计数 spy ⇒ 可断言写配置的调用次数。

用法：
  python -X utf8 -m md_cg.test_p14_root_fallback
  python -X utf8 -m md_cg.test_p14_root_fallback --mutate
'''
import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

from . import datapath as dp
from . import security as sec

_ENV_PATHS = 'MDCG_STATE_ROOT'
_ENV_MDCG = 'MDCG_ROOT'
_ENV_DATA = 'MDCG_DATA_ROOT'
_ENV_INGEST = 'MDCG_INGEST_ROOT'
_ENV_EXPORT = 'MDCG_EXPORT_ROOT'
_ENV_ALL = (_ENV_PATHS, _ENV_MDCG, _ENV_DATA, _ENV_INGEST, _ENV_EXPORT)

_PASS = []
_FAIL = []


def check(name, cond, extra=''):
    '''记一条判据；extra 仅在该条失败时打印（成功路径不留噪声）。'''
    (_PASS if cond else _FAIL).append(name)
    print(('  PASS ' if cond else '  FAIL ') + name
          + (('  <- ' + str(extra)) if (extra and not cond) else ''))


@contextlib.contextmanager
def sandbox():
    '''空白态沙箱：env 清空、state 落 tempfile、legacy 读口也指到沙箱内。'''
    tmp = tempfile.mkdtemp(prefix='p14_')
    state = os.path.join(tmp, 'state')
    os.makedirs(state, exist_ok=True)
    saved = {k: os.environ.get(k) for k in _ENV_ALL}
    os.environ[_ENV_PATHS] = state
    for k in (_ENV_MDCG, _ENV_DATA, _ENV_INGEST, _ENV_EXPORT):
        os.environ.pop(k, None)
    orig_legacy = dp.legacy_paths_file
    orig_set = dp.set_user_root
    calls = []
    dp.legacy_paths_file = lambda: os.path.join(tmp, 'no-legacy', 'paths.json')

    def spy(path, key='data_root'):
        calls.append((path, key))
        return orig_set(path, key)

    dp.set_user_root = spy
    box = {'tmp': tmp, 'state': state, 'calls': calls,
           'paths_file': os.path.join(state, 'paths.json'),
           'mdcg_root': os.path.join(state, 'data', 'mdcg')}
    try:
        yield box
    finally:
        dp.legacy_paths_file = orig_legacy
        dp.set_user_root = orig_set
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)


def _root_of(pf):
    '''读 paths.json 的 root；文件缺失/损坏时返回 None（不抛——判据要能干净转红）。'''
    try:
        with open(pf, encoding='utf-8') as f:
            d = json.load(f)
        return d.get('root') if isinstance(d, dict) else None
    except Exception:
        return None


def _bytes_of(pf):
    try:
        with open(pf, 'rb') as f:
            return f.read()
    except Exception:
        return None


def _refuses(fn):
    '''调用 fn；抛 PermissionError 记 True，否则 False。'''
    try:
        fn()
        return False
    except PermissionError:
        return True


def c1_env_configured():
    '''①级：env 已配置 ⇒ 用它；根内放行、根外拒；不回落也不写配置。'''
    with sandbox() as sb:
        root_in = os.path.join(sb['tmp'], 'in')
        os.makedirs(root_in, exist_ok=True)
        root_out = tempfile.mkdtemp(prefix='p14_out_')
        try:
            os.environ[_ENV_INGEST] = root_in
            sec.check_path_root(os.path.join(root_in, 'a.md'), _ENV_INGEST, 't')
            check('P14-1a ①级 env 已配置 + 根内=放行', True)
            check('P14-1b ①级 env 已配置 + 根外=拒绝（fail-closed）',
                  _refuses(lambda: sec.check_path_root(
                      os.path.join(root_out, 'b.md'), _ENV_INGEST, 't')))
            check('P14-1c ①级不回落也不写配置（paths.json 未创建、spy 0 次）',
                  (not os.path.isfile(sb['paths_file'])) and (not sb['calls']),
                  (os.path.isfile(sb['paths_file']), sb['calls']))
        finally:
            shutil.rmtree(root_out, ignore_errors=True)


def c2_library_root():
    '''②级：回落 mdcg 实际配置库根（env / paths.json 的 root / 库根目录已存在）。'''
    with sandbox() as sb:
        mem = os.path.join(sb['tmp'], 'mem')
        os.makedirs(mem, exist_ok=True)
        out = tempfile.mkdtemp(prefix='p14_out_')
        try:
            os.environ[_ENV_MDCG] = mem
            check('P14-2a MDCG_ROOT 已配 ⇒ mdcg_root_configured()=True',
                  dp.mdcg_root_configured() is True)
            sec.check_path_root(os.path.join(mem, 'a.md'), _ENV_INGEST, 't')
            check('P14-2b ②级回落库根 + 根内=放行', True)
            check('P14-2c ②级回落库根 + 根外=拒绝',
                  _refuses(lambda: sec.check_path_root(
                      os.path.join(out, 'b.md'), _ENV_INGEST, 't')))
        finally:
            shutil.rmtree(out, ignore_errors=True)
    with sandbox() as sb:
        lib = os.path.join(sb['tmp'], 'lib')
        os.makedirs(lib, exist_ok=True)
        with open(sb['paths_file'], 'w', encoding='utf-8') as f:
            json.dump({'root': lib}, f)
        check('P14-2d paths.json 的 root 已配 ⇒ mdcg_root_configured()=True',
              dp.mdcg_root_configured() is True)
        check('P14-2e paths.json 的 root 作为白名单根生效',
              not _refuses(lambda: sec.check_path_root(
                  os.path.join(lib, 'a.md'), _ENV_INGEST, 't')))
    with sandbox() as sb:
        os.makedirs(sb['mdcg_root'], exist_ok=True)
        out = tempfile.mkdtemp(prefix='p14_out_')
        try:
            check('P14-2f 未显式配置但默认库根目录已存在 ⇒ configured()=False',
                  dp.mdcg_root_configured() is False)
            check('P14-2g 该形态仍用库根（不夺到工作区，防记忆真源分裂）',
                  not _refuses(lambda: sec.check_path_root(
                      os.path.join(sb['mdcg_root'], 'a.md'), _ENV_INGEST, 't')))
            check('P14-2h 该形态根外=拒绝',
                  _refuses(lambda: sec.check_path_root(
                      os.path.join(out, 'b.md'), _ENV_INGEST, 't')))
            check('P14-2i 该形态不写配置（spy 0 次）', not sb['calls'], sb['calls'])
        finally:
            shutil.rmtree(out, ignore_errors=True)


def c3_workspace_fallback():
    '''③级：连库根也无 ⇒ 工作区优先 + 把它配置下来（含幂等）。'''
    with sandbox() as sb:
        cwd = os.path.realpath(os.getcwd())
        out = tempfile.mkdtemp(prefix='p14_out_')
        try:
            check('P14-3 前置：确属空白态（无 env / 无 paths.json / 默认库根不存在）',
                  (dp.mdcg_root_configured() is False)
                  and (not os.path.isdir(dp.mdcg_root())),
                  (dp.mdcg_root_configured(), dp.mdcg_root()))
            check('P14-3a ③级：工作区内=放行',
                  not _refuses(lambda: sec.check_path_root(
                      os.path.join(cwd, 'a.md'), _ENV_INGEST, 't')))
            check('P14-3b ③级：工作区外=拒绝（fail-closed，绝不放开）',
                  _refuses(lambda: sec.check_path_root(
                      os.path.join(out, 'b.md'), _ENV_INGEST, 't')))
            check('P14-3c ③级：根写进用户级 paths.json 的 root，且==realpath(cwd)',
                  _root_of(sb['paths_file']) == cwd.replace(os.sep, '/'),
                  (_root_of(sb['paths_file']), cwd))
            check('P14-3d ③级：env 未被改写 且 set_user_root 恰 1 次',
                  (os.environ.get(_ENV_MDCG) is None) and (len(sb['calls']) == 1),
                  (os.environ.get(_ENV_MDCG), sb['calls']))
            before = _bytes_of(sb['paths_file'])
            _refuses(lambda: sec.check_path_root(
                os.path.join(cwd, 'a.md'), _ENV_INGEST, 't'))
            after = _bytes_of(sb['paths_file'])
            check('P14-3e 幂等：二次调用后 paths.json 逐字节相同且不再写配置',
                  (before is not None) and (before == after)
                  and (len(sb['calls']) == 1),
                  (before, after, sb['calls']))
        finally:
            shutil.rmtree(out, ignore_errors=True)


def c4_no_path_arg():
    '''无路径参数（None/空串/空白）不触回落、不写配置。'''
    with sandbox() as sb:
        for bad in (None, '', '   '):
            sec.check_path_root(bad, _ENV_INGEST, 't')
        check('P14-4 无路径参数=直接返回，不触回落也不写配置',
              (not os.path.isfile(sb['paths_file'])) and (not sb['calls']),
              (os.path.isfile(sb['paths_file']), sb['calls']))


def c5_cwd_unavailable():
    '''兜底：连 cwd 都取不到 ⇒ fail-closed（绝不放开）。'''
    with sandbox() as sb:
        real_getcwd = os.getcwd

        def boom():
            raise OSError('cwd 不可得（构造）')

        os.getcwd = boom
        try:
            check('P14-5 cwd 也取不到 ⇒ PermissionError（绝不回落放开）',
                  _refuses(lambda: sec.check_path_root(
                      os.path.join(sb['tmp'], 'a.md'), _ENV_INGEST, 't')))
        finally:
            os.getcwd = real_getcwd


_CASES = (c1_env_configured, c2_library_root, c3_workspace_fallback,
          c4_no_path_arg, c5_cwd_unavailable)


def _run_all():
    del _PASS[:]
    del _FAIL[:]
    for fn in _CASES:
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001
            check('%s 组抛异常：%s: %s' % (fn.__name__, type(exc).__name__, exc),
                  False)
    return list(_FAIL)


#: 定点变异表：每条必须让**指定判据**转红，否则守卫无判别力（恒真即病）。
#: 名字 -> (施加, 还原, 预期红项集)。
_MUTATIONS = []


def _mutation(name, expected):
    def deco(fn):
        _MUTATIONS.append((name, fn, set(expected)))
        return fn
    return deco


@_mutation('M0 空转对照（new==old，行为零变化）', [])
def _m0_null(ctx):
    ctx['restore'] = lambda: None


@_mutation('M1 ③级不落配置（_persist_workspace_root 改空转）',
           ['P14-3c', 'P14-3d', 'P14-3e'])
def _m1_no_persist(ctx):
    orig = sec._persist_workspace_root
    sec._persist_workspace_root = lambda ws: False
    ctx['restore'] = lambda: setattr(sec, '_persist_workspace_root', orig)


@_mutation('M2 无路径参数也走回落（None 被当成路径）', ['P14-4'])
def _m2_none_falls_back(ctx):
    orig = sec.check_path_root

    def patched(path, env_var, what):
        if path is None or str(path).strip() == '':
            path = '.'
        return orig(path, env_var, what)

    sec.check_path_root = patched
    ctx['restore'] = lambda: setattr(sec, 'check_path_root', orig)


@_mutation('M3 退回旧语义「未配置=放开」（本次裁定推翻的那条）',
           ['P14-3b', 'P14-3c', 'P14-3d', 'P14-3e', 'P14-5'])
def _m3_fail_open(ctx):
    orig = sec.check_path_root

    def patched(path, env_var, what):
        if (not (os.environ.get(env_var) or '').strip()
                and sec._configured_library_root() is None):
            return                      # 旧语义：未配置 = 放开（默认部署零变更）
        return orig(path, env_var, what)

    sec.check_path_root = patched
    ctx['restore'] = lambda: setattr(sec, 'check_path_root', orig)


@_mutation('M4 ②级不认「默认库根目录已存在」', ['P14-2g', 'P14-2i'])
def _m4_drop_isdir(ctx):
    orig = sec._configured_library_root

    def patched():
        return dp.mdcg_root() if dp.mdcg_root_configured() else None

    sec._configured_library_root = patched
    ctx['restore'] = lambda: setattr(sec, '_configured_library_root', orig)


@_mutation('M5 ③级整个缺失（工作区根取不到）',
           ['P14-3a', 'P14-3c', 'P14-3d', 'P14-3e'])
def _m5_no_workspace(ctx):
    orig = sec._workspace_root
    sec._workspace_root = lambda: None
    ctx['restore'] = lambda: setattr(sec, '_workspace_root', orig)


def _run_mutations():
    print('!! 定点变异自证：逐条把机制改回「改动前/错误」形态，守卫必须转红'
          '（红项 = 本轮自身判据，不得用累计值）')
    bad = 0
    for name, fn, expected in _MUTATIONS:
        ctx = {}
        fn(ctx)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                reds = _run_all()
        finally:
            ctx['restore']()
        got = set(r.split(' ', 1)[0] for r in reds)
        okk = (got == expected)
        if not okk:
            bad += 1
        print('  %s %s' % ('PASS' if okk else 'FAIL', name))
        if not okk:
            print('        预期红项=%s  实际红项=%s' % (sorted(expected), sorted(got)))
    print('')
    return bad


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(description='P1-4 三级回落链守卫（issue #85 选 A）')
    ap.add_argument('--mutate', action='store_true',
                    help='定点变异自证：每条变异必须让指定判据转红')
    a = ap.parse_args()
    reds = _run_all()
    print('')
    print('SUMMARY: P1-4 三级回落链守卫：%d 通过，%d 失败' % (len(_PASS), len(reds)))
    rc = 1 if reds else 0
    if reds:
        print('失败判据：' + '; '.join(reds))
    if a.mutate:
        rc = 1 if (_run_mutations() or reds) else 0
        print('SUMMARY: 定点变异自证：%s'
              % ('全部按预期转红' if rc == 0 else '存在偏差（见上）'))
    return rc


if __name__ == '__main__':
    sys.exit(main())
