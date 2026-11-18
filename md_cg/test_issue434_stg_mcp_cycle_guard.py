# -*- coding: utf-8 -*-
"""守卫 · issue #994：切断 stg ↔ mcp_server 双向惰性循环（#434 硬前置第 2 项）。

背景：`md_cg/stg.py` 曾三处 `from .mcp_server import _normalize_session`，
而 `mcp_server.py` 有 `from . import stg` ⇒ stg 无法在屏蔽 mcp_server 的
隔离环境独立导入或拆包。

修法：三个判定下沉到 `md_cg/session_norm.py`（零反向依赖：os + 延迟 session5），
stg 单向依赖 session_norm；mcp_server 保留同名薄包装。

四组判据：
  G1 AST 零反向边：stg.py 内不含任何 module 名含 mcp_server 的 ImportFrom
  G2 叶模块零依赖：session_norm.py 的顶层 import 只允许 os / __future__ / session5
  G3 隔离导入：子进程把 sys.modules["md_cg.mcp_server"] 置 None 后，
     import md_cg.stg 与 session_norm.normalize_session 仍可用且行为不变
  G4 变异自证（--mutate）：临时把一条反向边注回 stg 副本，G1 必须转红

用法：
    python -X utf8 md_cg/test_issue434_stg_mcp_cycle_guard.py
    python -X utf8 md_cg/test_issue434_stg_mcp_cycle_guard.py --mutate
"""
import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STG = os.path.join(REPO, "md_cg", "stg.py")
NORM = os.path.join(REPO, "md_cg", "session_norm.py")

_PASS, _FAIL = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:180]))
    (_PASS if cond else _FAIL).append(name)
    return bool(cond)


def reverse_edges(path):
    """返回 [(lineno, module, names)]——module 名含 mcp_server 的 ImportFrom。"""
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    return [(n.lineno, n.module, [a.name for a in n.names])
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module and "mcp_server" in n.module]


def top_imports(path):
    """模块顶层（非函数内）import 的顶层包名集合。"""
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    mods = set()
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            mods.add((n.module or "").split(".")[0])
    mods.discard("")
    return mods


def g1_ast():
    edges = reverse_edges(STG)
    return ok(not edges, 'G1 stg 无 mcp_server 反向边', edges)


def g2_leaf():
    allowed = {"__future__", "os", "session5"}
    mods = top_imports(NORM)
    extra = sorted(m for m in mods if m not in allowed)
    return ok(not extra, 'G2 session_norm 顶层只依赖 os/__future__/session5', extra)


def g3_isolated():
    code = (
        "import sys; sys.modules['md_cg.mcp_server']=None\n"
        "import md_cg.stg as s\n"
        "from md_cg import session_norm as sn\n"
        "assert sn.normalize_session('') == 'anonymous'\n"
        "assert sn.normalize_session('abc') == 'abc'\n"
        "assert s._view_session('abc') == 'abc'\n"
        "print('ISOLATED-OK')\n"
    )
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    # 会话 env 权威在场时 _view_session 会归到 env 值（既有契约），
    # 本组只验「隔离导入后函数可用」，故摘掉 env 让结果确定。
    env.pop("MDCG_SESSION", None)
    env.pop("DSH_SESSION_ID", None)
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, shell=False)
    good = r.returncode == 0 and "ISOLATED-OK" in (r.stdout or "")
    return ok(good, 'G3 屏蔽 mcp_server 后 stg 仍可导入并使用',
              (r.stdout or '') + (r.stderr or '')[-400:])


def g4_mutate():
    tmp = tempfile.mkdtemp(prefix="mut434_")
    try:
        victim = os.path.join(tmp, "stg_mut.py")
        src = io.open(STG, encoding="utf-8").read()
        # 在文件末尾注入一条反向边（模拟回归）
        io.open(victim, "w", encoding="utf-8").write(
            src + "\n\nfrom .mcp_server import _normalize_session  # 变异注入\n")
        edges = reverse_edges(victim)
        red = bool(edges)
        print('  MUTATE 注入反向边 → G1 判据命中: %s %s' % (red, edges[:1]))
        return ok(red, 'G4 变异自证：注入反向边后判据转红')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print('=== issue #994 · stg ↔ mcp_server 循环守卫 ===')
    g1_ast()
    g2_leaf()
    g3_isolated()
    if "--mutate" in sys.argv:
        g4_mutate()
    print()
    print('守卫结果：%d 通过 / %d 失败' % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())