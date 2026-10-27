# -*- coding: utf-8 -*-
# 功能名：hive serve 配置解析的机器级 env 回落守卫（进程 env 优先 · 机器级兜底 · 缺仍 fail fast）
# 生效条件：python -X utf8 hive/test_serve_env_fallback.py；被测面＝hive/serve_start.py 的 resolve / _machine_env / load_config
# 子功能：①字符串直值 ②{"env":X} 先读进程 env ③进程 env 空时回落 Windows 机器级同名变量 ④两者皆空仍返回 None（保持 fail fast 语义）⑤进程 env 显式值优先于机器级 ⑥{"file":…} 形态不变 ⑦真实 config.local.json 可解析（若存在）
# 执行：纯函数断言 + 临时配置文件跑 load_config 的通过/失败两态
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不判非 Windows 平台的机器级回落（该分支直接返回 None）；不判 serve 进程本身能否存活（那是集成面）
"""hive serve 配置解析的机器级 env 回落守卫（2026-10-27 根治）。

病象：`config.local.json` 的 `HIVE_API_KEY` 写成 `{"env":"DEEPSEEK_API_KEY"}`，
读的是**调用进程** env；DSH 主进程未继承机器级变量 ⇒ `serve_start` 报
「配置项解析失败（来源 env 未设）」⇒ 调用方误判「蜂巢不可用」而全程降级。
本机实测：进程 env 无、机器级有（35 字符）。
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from hive import serve_start as s

_PASS, _FAIL = [], []


def ok(cond, msg, detail=''):
    (_PASS if cond else _FAIL).append(msg)
    print(('  PASS ' if cond else '  FAIL ') + msg + (('  <- ' + str(detail)) if detail and not cond else ''))


def main():
    print('== A 三形态解析')
    ok(s.resolve('abc') == 'abc', 'A1 字符串直值原样')
    os.environ['__HIVE_T_ENV'] = 'from-process'
    ok(s.resolve({'env': '__HIVE_T_ENV'}) == 'from-process', 'A2 进程 env 可读')
    ok(s.resolve({'env': '__HIVE_T_NOPE__'}) is None,
       'A3 进程与机器级都没有 ⇒ None（保持 fail fast 语义）')
    ok(s.resolve({'env': ''}) is None, 'A4 空变量名 ⇒ None')
    fd, p = tempfile.mkstemp(suffix='.txt')
    os.write(fd, b'  file-value  \n')
    os.close(fd)
    ok(s.resolve({'file': p}) == 'file-value', 'A5 file 形态仍工作（strip）')
    os.unlink(p)

    print('== B 机器级回落（Windows）')
    if os.name == 'nt':
        mv = s._machine_env('DEEPSEEK_API_KEY')
        ok(mv is None or len(str(mv)) > 0,
           'B1 _machine_env 读机器级变量（有值或 None，不抛异常）', type(mv))
        ok(s._machine_env('__NO_SUCH_MACHINE_VAR__') is None, 'B2 未知名返回 None')
        if mv:
            rv = s.resolve({'env': 'DEEPSEEK_API_KEY'})
            ok(rv == str(mv).strip(), 'B3 进程 env 空时回落机器级（值一致）')
            os.environ['DEEPSEEK_API_KEY'] = 'explicit-override'
            ok(s.resolve({'env': 'DEEPSEEK_API_KEY'}) == 'explicit-override',
               'B4 进程 env 显式值**优先**于机器级（不覆盖显式配置）')
            os.environ.pop('DEEPSEEK_API_KEY', None)
    else:
        ok(s._machine_env('ANY') is None, 'B1 非 Windows ⇒ 机器级回落直接 None')

    print('== C load_config 两态')
    d = tempfile.mkdtemp(prefix='servestart_')
    good = os.path.join(d, 'good.json')
    json.dump({'A': 'x', '_comment': 'skip'}, open(good, 'w', encoding='utf-8'))
    env, err = s.load_config(good)
    ok(err is None and env == {'A': 'x'}, 'C1 正常配置通过（下划线键跳过）', (env, err))
    bad = os.path.join(d, 'bad.json')
    json.dump({'MISSING': {'env': '__HIVE_T_NOPE__'}}, open(bad, 'w', encoding='utf-8'))
    env2, err2 = s.load_config(bad)
    ok(env2 is None and err2 and 'MISSING' in err2,
       'C2 解析不到的键仍 fail fast 并点名', (env2, err2))
    real = os.path.join(HERE, 'config.local.json')
    if os.path.exists(real):
        env3, err3 = s.load_config(real)
        ok(err3 is None and env3 and env3.get('HIVE_API_KEY'),
           'C3 本机 config.local.json 全键可解析（含机器级回落的 HIVE_API_KEY）', err3)

    os.environ.pop('__HIVE_T_ENV', None)
    print()
    print('serve env 回落守卫：%d 通过 / %d 失败' % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print('  -', f)
    return 0 if not _FAIL else 1


if __name__ == '__main__':
    raise SystemExit(main())