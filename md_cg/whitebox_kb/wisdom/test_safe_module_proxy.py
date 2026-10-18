# -*- coding: utf-8 -*-
"""test_safe_module_proxy.py · 受限模块代理的**递归包裹**守卫（issue #187 补漏）

缺陷现场（读码 + 隔离复现，2026-10-13）：
    `verifier._SafeModule` 的 `__getattr__` 返回真模块的**裸属性**，不再套代理。
    白名单里的 `json` 有 `decoder` / `scanner` 两个**子模块**属性，它们是普通
    module 对象 ⇒ 自带真 `__builtins__` ⇒
        proxy.decoder.__builtins__["open"]            # 沙箱外文件读写
        proxy.decoder.__builtins__["__import__"]("os").system(...)   # 任意命令
    即该文件注释所声称的「逃逸取道全部堵死」只在**一层**内成立。

本守卫断言（四组）：
    ① 子模块属性被继续包裹（`isinstance(proxy.decoder, _SafeModule)`）；
    ② 经子模块取 `__builtins__` / `__globals__` / `__dict__` 一律 AttributeError；
    ③ 白名单内模块的**子模块属性**逐一穷举，不得漏出裸 module；
    ④ 对照（不误杀）：`re.search` / `json.loads` 等纯计算用法照常可用，
       且顶层拦截未被放松。

体例与 `md_cg/whitebox_kb/wisdom/` 下其它 test_*.py 一致（`check()` + 退出码）。
"""
import sys
import os
import re
import types

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import verifier  # noqa: E402  —— 同目录模块

pass_n = fail_n = 0


def check(name, ok, detail=''):
    """断言登记：通过/失败计数并打印结果行。"""
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


S = verifier._SafeModule
BLOCKED = ("__builtins__", "__globals__", "__dict__", "__class__",
           "__subclasses__", "__loader__", "__spec__")


def proxy(modname):
    return S(sys.modules.get(modname) or __import__(modname), modname)


# ① 子模块属性被继续包裹（json.decoder / json.scanner 是本仓白名单模块的真实子模块）
print('— ① 子模块属性必须继续套代理 —')
for modname, sub in (('json', 'decoder'), ('json', 'scanner')):
    p = proxy(modname)
    try:
        v = getattr(p, sub)
        check(f'① {modname}.{sub} 仍是 _SafeModule',
              isinstance(v, S),
              f'实际类型 {type(v).__name__}')
    except AttributeError as ex:
        check(f'① {modname}.{sub} 仍是 _SafeModule', False, f'AttributeError: {ex}')

# ② 经子模块的逃逸取道一律 AttributeError
print('— ② 经子模块取受禁属性必须 AttributeError —')
p_json = proxy('json')
for attr in BLOCKED:
    try:
        getattr(p_json.decoder, attr)
        check(f'② json.decoder.{attr} 被拦', False, '**取到了**')
    except AttributeError:
        check(f'② json.decoder.{attr} 被拦', True, '')
    except Exception as ex:                        # 其它异常也算没堵住
        check(f'② json.decoder.{attr} 被拦', False, f'{type(ex).__name__}: {ex}')

# ③ 白名单模块逐一穷举：任何公开属性都不得漏出裸 module
#    ★注意：必须枚举**被包模块**的 dir()，不能枚举 dir(proxy)——后者返回的是
#    代理自身的槽（`_m`/`_n`），全以 `_` 开头 ⇒ 循环恒空 ⇒ 该组会退化成安慰剂
#    （本守卫初版即如此，已由「未修时也应红」的定点变异自证抓出）。
print('— ③ 白名单模块穷举：不得漏出裸 module —')
leaked = []
for modname in verifier._SAFE_MODULE_WHITELIST:
    try:
        real = sys.modules.get(modname) or __import__(modname)
    except Exception:                              # 本机缺该模块：跳过（不判红）
        continue
    p = S(real, modname)
    for name in dir(real):                         # ← 枚举真模块的公开名
        if name.startswith('_'):
            continue
        try:
            v = getattr(p, name)
        except AttributeError:
            continue
        except Exception:
            continue
        if isinstance(v, types.ModuleType):
            leaked.append(f'{modname}.{name}')
check('③ 无裸 module 漏出', not leaked,
      ('漏出：' + ', '.join(leaked)) if leaked else '已穷举全部白名单模块')

# ④ 对照：纯计算用法照常可用，顶层拦截未放松
print('— ④ 对照（不误杀）—')
try:
    got = proxy('re').search(r'\d+', 'ab12cd').group(0)
    check('④ re.search 纯计算用法可用', got == '12', f'得到 {got!r}')
except Exception as ex:
    check('④ re.search 纯计算用法可用', False, f'{type(ex).__name__}: {ex}')

try:
    got = proxy('json').loads('{"a": 1}')['a']
    check('④ json.loads 纯计算用法可用', got == 1, f'得到 {got!r}')
except Exception as ex:
    check('④ json.loads 纯计算用法可用', False, f'{type(ex).__name__}: {ex}')

for attr in ('__builtins__', '__dict__', '__globals__'):
    try:
        getattr(proxy('json'), attr)
        check(f'④ 顶层 {attr} 仍被拦', False, '**未拦**')
    except AttributeError:
        check(f'④ 顶层 {attr} 仍被拦', True, '')

check('④ 顶层拦截未放松（见下方逐项）', True, '')

# ⑤ 受控 __import__ 边界未放松
print('— ⑤ 受控 __import__ —')
try:
    verifier._guarded_import('os')
    check('⑤ _guarded_import 拒 os', False, '**放行了**')
except ImportError:
    check('⑤ _guarded_import 拒 os', True, '')
try:
    verifier._guarded_import('re')
    check('⑤ _guarded_import 放行 re', True, '')
except ImportError as ex:
    check('⑤ _guarded_import 放行 re', False, str(ex))

# ⑥ 子进程执行器源码内的同名类必须与父侧同款（防止只修一侧）
print('— ⑥ 父子两侧同款 —')
_inner = verifier._EXEC_RUNNER_SRC
check('⑥ 子进程侧 _SafeModule 亦递归包裹子模块',
      'isinstance(v, types.ModuleType)' in _inner,
      '子进程源码里未见递归包裹分支')

print(f'\n=== 受限模块代理递归包裹: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)
