# -*- coding: utf-8 -*-
"""test_compile_entry_n102_recursion.py · N102 回归：编译主入口 RecursionError 结构化

缺陷（N102）：超长算术链/深嵌套（约 500 运算符）使 parser 右递归
（parser.py _parse_binary_tail→_parse_expression）触发未捕获 RecursionError，
api.compile_source 与 compiler.compile_source 两个官方编译主入口均裸崩
（异常逃逸，不返回结构化结果），CLI 同样裸崩——一行约 1500 字符输入即崩
（资源耗尽/DoS 面，零前置条件）。

修复语义（窄捕获，只拦 RecursionError，不掩盖其他异常）：
  两入口 parse_tokens 包 try/except RecursionError → 转结构化错误随正常
  错误流返回：api 侧 success=False + errors（CompileResult 契约）、
  compiler 侧 (None, {ok:False, errors})；CLI 经既有失败路径得
  「编译失败」+ exit=1，无 Traceback。
黄金基线零影响：纯「崩溃→报错」转换，正常输入（含 50 运算符链）
编译结果逐位不变。
"""
import os
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.api import compile_source as api_compile
from compiler.compiler import compile_source as bc_compile

pass_n = fail_n = 0
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


CHAIN_500 = "甲 = 1" + "加1" * 500 + "。"   # 约 1500 字符，500 运算符
CHAIN_50 = "甲 = 1" + "加1" * 50 + "。"     # 合法量级——基线锚

# ① api.compile_source：500 链 → 结构化失败（不抛异常）
try:
    r = api_compile(CHAIN_500)
    check('① api 入口 500 链结构化拒绝',
          r.success is False and r.ast is None
          and any("RecursionError" in e or "递归" in e for e in r.errors),
          'success=%s errors[0]=%s' % (r.success,
                                       r.errors[0][:40] if r.errors else '-'))
except RecursionError as e:
    check('① api 入口 500 链结构化拒绝', False, 'RecursionError 裸穿透: %s' % str(e)[:40])
except Exception as e:
    check('① api 入口 500 链结构化拒绝', False, '%s: %s' % (type(e).__name__, str(e)[:40]))

# ② compiler.compile_source：500 链 → (None, ok=False, errors)
try:
    code, r = bc_compile(CHAIN_500)
    check('② 字节码入口 500 链结构化拒绝',
          code is None and r.get("ok") is False
          and any("RecursionError" in e or "递归" in e for e in r.get("errors", [])),
          'ok=%s errors[0]=%s' % (r.get("ok"),
                                  r["errors"][0][:40] if r.get("errors") else '-'))
except RecursionError as e:
    check('② 字节码入口 500 链结构化拒绝', False, 'RecursionError 裸穿透: %s' % str(e)[:40])
except Exception as e:
    check('② 字节码入口 500 链结构化拒绝', False, '%s: %s' % (type(e).__name__, str(e)[:40]))

# ③ CLI compile 面：500 链 → exit=1、无 Traceback、「编译失败」（有界子进程）
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="n102_guard_")
src = os.path.join(tmp, "chain.proto")
with open(src, "w", encoding="utf-8") as f:
    f.write(CHAIN_500 + "\n")
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
p = subprocess.run([sys.executable, "-m", "compiler.cli", "compile", src,
                    "-o", os.path.join(tmp, "out")],
                   cwd=REPO, env=env, capture_output=True, timeout=120)
err = p.stderr.decode("utf-8", "replace")
out = p.stdout.decode("utf-8", "replace")
check('③ CLI 500 链干净失败（exit=1·无 Traceback）',
      p.returncode == 1 and "Traceback" not in err and "编译失败" in out,
      'exit=%d traceback=%s' % (p.returncode, "yes" if "Traceback" in err else "no"))

# ④ 合法链（50 运算符）双入口照常编译成功——窄捕获不误伤正常输入
try:
    r50 = api_compile(CHAIN_50)
    code50, r50b = bc_compile(CHAIN_50)
    check('④ 合法 50 运算符链双入口不受影响',
          r50.success and r50b.get("ok") is True,
          'api.success=%s bc.ok=%s' % (r50.success, r50b.get("ok")))
except Exception as e:
    check('④ 合法 50 运算符链双入口不受影响', False,
          '%s: %s' % (type(e).__name__, str(e)[:40]))

print(f'\n=== N102 编译入口递归守卫: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)
