#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_isolation_imports · swarm 层「隔离根可导入」守卫（issue #125）

# 功能名：swarm 层隔离导入守卫（顶层硬导入不得进隔离根）
# 生效条件：改动 swarm/*.py 的导入面之后必跑；尤其新增对 compiler / md_cg 的**顶层**导入时
# 子功能：①隔离根（只放 swarm 面）下 4 个子模块逐个 import（子进程，逐条 rc）
#         ②对照：同隔离根补上 compiler 面后仍全绿（证明①的红确实源于缺 compiler，而非环境偶然）
#         ③3 条定点变异（延迟导入还原成顶层 / 只还原一半 / 包级 eager 导入）⇒ **必须转红**
# 执行：python -X utf8 -m swarm.test_isolation_imports
# 验证方式：末行「通过 N / 失败 M」；变异段逐条打印 (模块, rc, 首条 stderr) 读数
# 不适用条件：只测**导入期**隔离（不测运行期功能、不跑 cargo/Rust 面）；沙箱一律 tempfile，
#             不触碰在役库与真实工作树（变异只写沙箱副本）

## 缺陷现场（issue #125）
swarm/rust_codegen.py 顶层 from compiler.compiler import compile_source /
from compiler.pbc import save_pbc, serialize（旧 18-19 行），配合
swarm/rust_swarm.py -> swarm/swarm_cli.py 的顶层相对导入**二级/三级传导**，
使「只放 swarm 面」的隔离根下 **3/4 子模块** ModuleNotFoundError: No module named 'compiler'。
反方向（compiler/cli/__init__.py:444 -> swarm.rust_codegen）本就是**函数内延迟导入**
—— 方向不对称即本缺陷。修法：三处均改为函数内延迟导入，对外 API 不变。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))       # .../swarm/tests
REPO = os.path.dirname(os.path.dirname(HERE))           # 仓库根（本守卫落在 swarm/tests/，需上溯两级）
SWARM = os.path.dirname(HERE)                            # .../swarm（本守卫的源码面；勿用 HERE，它是 tests/）
MODS = ["swarm", "swarm.rust_codegen", "swarm.rust_swarm", "swarm.swarm_cli"]
IGNORE = shutil.ignore_patterns("rust_runtime", "__pycache__", "*.pyc", "target")

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


def _env():
    """子进程环境：剔除 PYTHONPATH（否则仓根会被带进 sys.path，隔离根失效）。"""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONUTF8"] = "1"
    return env


def _root(sandbox, tag, patches=None, with_compiler=False):
    """建隔离根：只放 swarm（可选 compiler），并按 patches 对**副本**做文本级变异。"""
    dst = os.path.join(sandbox, tag)
    os.makedirs(dst, exist_ok=True)
    shutil.copytree(SWARM, os.path.join(dst, "swarm"), ignore=IGNORE)
    if with_compiler:
        shutil.copytree(os.path.join(REPO, "compiler"), os.path.join(dst, "compiler"), ignore=IGNORE)
    for rel, reps in (patches or {}).items():
        p = os.path.join(dst, "swarm", rel)
        with open(p, encoding="utf-8") as f:
            text = f.read()
        for a, b in reps:
            if a == "@@APPEND@@":
                text = text + b
                continue
            assert a in text, "变异锚点未命中：%s %r" % (rel, a[:70])
            text = text.replace(a, b)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    return dst


def _imp(root, mod):
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", "import " + mod],
                       cwd=root, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_env(), shell=False, timeout=300)
    tail = (p.stderr or "").strip().splitlines()
    return p.returncode, (tail[-1][:110] if tail else "")


DEFER_SRC = "    from compiler.compiler import compile_source\n"
DEFER_PBC = "    from compiler.pbc import save_pbc, serialize\n"
TOP_ANCHOR = '\nALGO = "rust_codegen-0.1"'
TOP_BOTH = ('\nfrom compiler.compiler import compile_source\n'
            'from compiler.pbc import save_pbc, serialize\n'
            '\nALGO = "rust_codegen-0.1"')


def main():
    sandbox = tempfile.mkdtemp(prefix="swarm_iso125_")
    try:
        print("=== swarm 隔离导入守卫（issue #125）===")

        print("\n[1] 隔离根（只放 swarm 面，无 compiler / md_cg）：4 个子模块逐个 import")
        base = _root(sandbox, "base")
        print("    隔离根 = %s" % base)
        rc1 = {}
        for m in MODS:
            rc, err = _imp(base, m)
            rc1[m] = rc
            print("      rc=%-3s %-22s %s" % (rc, m, err))
        check("隔离根下 4/4 子模块可导入（修复前 3/4 红）",
              all(v == 0 for v in rc1.values()), rc1)

        print("\n[2] 对照：同隔离根补上 compiler 面后仍 4/4（证明①的红源于缺 compiler）")
        full = _root(sandbox, "with_compiler", with_compiler=True)
        rc2 = {}
        for m in MODS:
            rc, err = _imp(full, m)
            rc2[m] = rc
            print("      rc=%-3s %-22s %s" % (rc, m, err))
        check("补 compiler 后 4/4 可导入（隔离根构造有效）", all(v == 0 for v in rc2.values()), rc2)

        print("\n[3] 定点变异（只改沙箱副本，不碰真实工作树）")
        m1 = _root(sandbox, "m1_top_both", patches={"rust_codegen.py": [
            (DEFER_SRC, ""), (DEFER_PBC, ""), (TOP_ANCHOR, TOP_BOTH)]})
        r1 = {m: _imp(m1, m) for m in MODS}
        print("    M1 两行 compiler 导入还原到模块顶层：%s" % {k: v[0] for k, v in r1.items()})
        check("M1 还原顶层 ⇒ rust_codegen 必须转红（swarm 包仍绿）",
              r1["swarm"][0] == 0 and r1["swarm.rust_codegen"][0] != 0,
              {k: v[0] for k, v in r1.items()})
        check("M1 下游**不再连坐**（rust_swarm/swarm_cli 仍 rc=0 —— 本次延迟化的直接收益；"
              "修复前形态下这两个与 rust_codegen 同为红）",
              r1["swarm.rust_swarm"][0] == 0 and r1["swarm.swarm_cli"][0] == 0,
              {k: v[0] for k, v in r1.items()})

        m2 = _root(sandbox, "m2_top_pbc_only", patches={"rust_codegen.py": [
            (DEFER_PBC, ""),
            (TOP_ANCHOR, '\nfrom compiler.pbc import save_pbc, serialize' + TOP_ANCHOR)]})
        r2 = _imp(m2, "swarm.rust_codegen")
        print("    M2 只把 pbc 那行还原顶层 ⇒ rust_codegen rc=%s · %s" % (r2[0], r2[1]))
        check("M2 两行都必须延迟（只还原一半也转红）", r2[0] != 0, r2)

        m3 = _root(sandbox, "m3_pkg_eager", patches={"__init__.py": [
            ("@@APPEND@@", "\nfrom compiler.compiler import compile_source  # MUTANT\n")]})
        r3 = _imp(m3, "swarm")
        print("    M3 包级 eager 导入 compiler（__init__.py 追加）⇒ swarm rc=%s · %s" % (r3[0], r3[1]))
        check("M3 包级 eager ⇒ import swarm 本身转红", r3[0] != 0, r3)

        print("\n[4] 对外 API 面（惰性 re-export）在隔离根下仍可用")
        api = ("from swarm.rust_swarm import build_rust_exe; "
               "from swarm.swarm_cli import generate_rust_project, make_swarm_config, "
               "run_swarm, verify_wal_signatures; print('API_OK')")
        p4 = subprocess.run([sys.executable, "-X", "utf8", "-c", api], cwd=base,
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            env=_env(), shell=False, timeout=300)
        print("    [包内符号] rc=%s out=%s" % (p4.returncode, (p4.stdout or "").strip()[:60]))
        check("惰性 re-export 保持**包内**符号的属性面（from ... import 名 仍可用）",
              p4.returncode == 0, (p4.stderr or "").strip().splitlines()[-1:] or "")

        api_x = "from swarm.rust_codegen import compile_source"
        p4x = subprocess.run([sys.executable, "-X", "utf8", "-c", api_x], cwd=base,
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             env=_env(), shell=False, timeout=300)
        print("    [跨包符号 compile_source] rc=%s" % p4x.returncode)
        check("**跨包**符号（compile_source，真身在 compiler 包）在无 compiler 的隔离根下"
              "按预期不可用 —— 边界语义，非缺陷",
              p4x.returncode != 0, p4x.returncode)

        m4 = _root(sandbox, "m4_no_lazy", patches={"rust_swarm.py": [
            ('    "build_rust_exe": ".rust_codegen",\n', "")]})
        r4 = _imp(m4, "swarm.rust_swarm")
        p4b = subprocess.run([sys.executable, "-X", "utf8", "-c",
                              "from swarm.rust_swarm import build_rust_exe"], cwd=m4,
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             env=_env(), shell=False, timeout=300)
        print("    M4 删掉惰性表项 ⇒ import 本身 rc=%s，from ... import build_rust_exe rc=%s"
              % (r4[0], p4b.returncode))
        check("M4 惰性表被打坏 ⇒ 属性面 import 转红（导入本身仍绿——证明二者是两面）",
              r4[0] == 0 and p4b.returncode != 0, (r4[0], p4b.returncode))

        print("\n" + "=" * 68)
        print("通过 %d / 失败 %d" % (PASS, len(FAILS)))
        if FAILS:
            print("失败项：" + "、".join(FAILS))
        print("=" * 68)
        return 1 if FAILS else 0
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
