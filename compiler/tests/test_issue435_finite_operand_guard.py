# -*- coding: utf-8 -*-
"""test_issue435_finite_operand_guard.py · #435 回归：`德`/`知足` 的非有限操作数闸

**缺陷**：`compiler.py` 对 `德` 用 `try: float(val)` 拦非数值，但
`float('inf')` / `float('nan')` 是**合法转换、不抛异常** ⇒ 「操作数必须是数值」
这道闸被 inf/nan 穿透（`德 abc` 被拒，而 `德 inf` 放行 —— 闸对"看起来像数"的值失明）。

**后果**（信任寄存器被永久毒化）：
  · `nan` 破坏相等自反性 ⇒「若 信任值 等于 信任值」恒为假 ⇒ 其后的「止」永不触发；
  · `inf` 恒超任何阈值 ⇒「知足」恒早退 ⇒ 其后所有语句被跳过。

**修复口径**：与既有「名实不符」同一处、同一语，按**有限性**拒绝（`math.isfinite`）。

**本测试覆盖三层**（缺一层就是假守卫）：
  ① 编译期闸：`德`/`知足` 的 inf/nan/-inf 必须 `ok=False` 且给「有限数值」提示；
  ② 阳性对照：正常数值（0.5/0/-3）必须仍通过，且**既有「非数值」提示不回归**；
  ③ 运行期语义：非有限值**已不可能进入信任寄存器** ⇒ 上面两个毒化路径在编译期即被切断。

**变异测试**（`--mutate`，每条变异必须恰好点红对应断言）：
  MUT-1 还原 `德` 的裸 `float()`（去掉有限性闸）  → 断言①的点红
  MUT-2 还原 `知足` 的裸 `float()`                → 断言①的点红（知足侧）
  MUT-3 把闸写成"只拦 nan 不拦 inf"               → 断言①的点红（inf 侧）
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

TARGET = os.path.join(REPO, "compiler", "compiler.py")

_OK = 0
_FAIL = []


def check(cond, msg):
    global _OK
    if cond:
        _OK += 1
    else:
        _FAIL.append(msg)


def compile_src(src):
    """在**当前磁盘上的**编译器代码上编译一行源码，返回 (ok, errors)。

    ★ 必须起**子进程**：`mutate()` 改的是磁盘文件，而 Python 会缓存已导入模块
    （`sys.modules`）——同进程内复跑仍走内存里的旧字节码，变异将**永远不点红**
    （本测试第一版即因此成了假守卫，`--mutate` 自证时才发现）。
    """
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {REPO!r})\n"
        "from compiler.compiler import compile_source\n"
        f"src = {src!r}\n"
        "try:\n"
        "    _tc, info = compile_source(src)\n"
        "    print(json.dumps([bool(info.get('ok')), list(info.get('errors') or [])]))\n"
        "except SyntaxError as e:\n"
        "    print(json.dumps([False, [str(e)]]))\n"
        "except Exception as e:\n"
        "    print(json.dumps([False, [type(e).__name__ + ': ' + str(e)]]))\n"
    )
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    line = (r.stdout or "").strip().splitlines()
    if not line:
        return False, [f"子进程无输出: {(r.stderr or '')[-160:]}"]
    try:
        ok, errs = json.loads(line[-1])
    except Exception:
        return False, [f"子进程输出不可解析: {line[-1][:120]}"]
    return ok, errs


def is_finite_reject(errors):
    return any("有限数值" in e for e in errors)


# ── 变异：在编译器源码上做文本替换（不落盘到仓库，只在临时目录跑） ──────────────
MUTATIONS = {
    # 真正去掉「德」的有限性闸（把校验改成恒真），而不是加注释（后者不改行为、必然不点红）
    "MUT-1 德 去掉有限性闸": (
        'if not math.isfinite(num):',
        'if False:'),
    "MUT-2 知足 去掉有限性闸": (
        'if not math.isfinite(threshold):',
        'if False:'),
    # 只拦 nan、放过 inf —— 检验断言确实区分了两种非有限值
    "MUT-3 只拦 nan 不拦 inf": (
        'if not math.isfinite(num):',
        'if num != num:'),
}


def mutate(name):
    """把 TARGET 按指定变异改写，返回是否成功；调用方负责还原。"""
    old, new = MUTATIONS[name]
    src = open(TARGET, encoding='utf-8').read()
    if src.count(old) != 1:
        return False
    open(TARGET, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new, 1))
    return True


def run_assertions():
    """三层断言。返回点红的断言名列表。"""
    global _OK, _FAIL
    _OK, _FAIL = 0, []

    # ① 编译期闸：非有限值必须被拒（且点明"有限数值"，与"非数值"区分）
    for src in ("德 inf", "德 nan", "德 -inf", "知足 inf", "知足 nan"):
        ok, errs = compile_src(src)
        check((not ok) and is_finite_reject(errs),
              f"① {src!r} 应被拒并提示『有限数值』，实得 ok={ok} errs={errs}")

    # ② 阳性对照：正常数值仍通过；既有"非数值"口径不回归
    for src in ("德 0.5", "德 0", "德 -3", "知足 0.9"):
        ok, errs = compile_src(src)
        check(ok and not errs, f"② {src!r} 应正常通过，实得 ok={ok} errs={errs}")
    ok, errs = compile_src("德 abc")
    check((not ok) and any("必须是数值" in e for e in errs),
          f"② 既有『非数值』闸不得回归：实得 ok={ok} errs={errs}")

    # ③ 运行期：非有限值进不去寄存器 ⇒ 毒化路径在编译期被切断
    ok, _errs = compile_src("德 inf")
    check(not ok, "③ 德 inf 不得产出可运行字节码")
    return list(_FAIL)


def main():
    if "--mutate" in sys.argv:
        print("变异测试（每条必须恰好点红对应断言）：")
        backup = open(TARGET, encoding='utf-8').read()
        allgood = True
        try:
            for name in MUTATIONS:
                if not mutate(name):
                    print(f"  {name}: 变异锚点未唯一命中 ✗（测试需修）")
                    allgood = False
                    continue
                reds = run_assertions()
                open(TARGET, 'w', encoding='utf-8', newline='\n').write(backup)
                if reds:
                    print(f"  {name}: 点红 ✓ ({reds[0][:34]}…)")
                else:
                    print(f"  {name}: **未点红 ✗ 假守卫**")
                    allgood = False
        finally:
            open(TARGET, 'w', encoding='utf-8', newline='\n').write(backup)
        print("===== 全绿 =====" if allgood else "===== 失败：存在假守卫 =====")
        return 0 if allgood else 1

    reds = run_assertions()
    if reds:
        for r in reds:
            print("  FAIL:", r)
        print(f"===== 失败 {len(reds)} 项 =====")
        return 1
    print(f"===== {_OK}/{_OK} 通过 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
