# -*- coding: utf-8 -*-
# 功能名：md_cg 生产码不得依赖 hive（依赖方向单向：外围→核心）
# 生效条件：python -u -X utf8 -m md_cg.test_md_cg_no_hive_dep；扫描面 = md_cg/**/*.py 的 AST import（取自文件实际文本）
# 子功能：P 生产面禁止 import hive · T 测试面允许但必须落在显式登记表内（双向：登记了却不存在即红）· S 自检（真造反例证明本腿能红）· R 相对导入折算逐形态断言
# 执行：直接跑；退出码 0=全绿、1=有红
# 验证方式：全部 PASS；S/R 段在临时区真造 import hive 的 md_cg 生产文件，断言判据转红
# 不适用条件：不判 hive 侧反向依赖 md_cg（那是允许方向，实测生产 3 件）；不判 md_cg 内部子包之间的依赖；不判动态 import（getattr/__import__ 形式不在 AST 的 Import/ImportFrom 面内）
"""C1 落腿：**md_cg 生产码不得 `import hive`**。

出口（why）：依赖方向必须单向 —— **外围（hive / 各端 / scripts）可依赖核心（md_cg），核心不得依赖外围**。
若核心反向依赖外围，则「核心」不再可独立验证：
  · 验证 md_cg 时要先拉起 hive（**T5 独立验证**失效：验证者与被验证者共享同一依赖面）；
  · md_cg 单独发布/单测时会被 hive 的可变性拖住（**A1 真源唯一**在工程上落成「依赖也单向」）。

**该规则出自 #465 的会话裁定**（本会话裁定「hive 侧新建 hive/_append.py，**不得反向依赖 md_cg**」，
并已实测 hive→md_cg 生产 3 件存在、md_cg→hive 生产 0 件）。**在此之前它只是一句会话里的约定、无任何判据载体**；
本件把它落成载体（这是 `docs/theory/形态×定理映射_v0.1.md` 第三节 **C1** 的兑现）。

★两面分开（否则要么误红、要么过度收紧）：
  · **生产面**（文件名不以 `test_` 开头）⇒ **禁止** import hive；
  · **测试面**（`test_*.py`）⇒ **允许**反向引用（用 hive 的产物做夹具是正当用法），但必须落在下方的
    `ALLOWED_TEST_FACE` **显式登记表**里 —— 这才是双向断言：登记了却不存在 ⇒ 红（抓陈化登记）。

★★相对导入必须**按所在文件位置折算**（2026-11-07 补，与 PR #806 同根因）
  旧判据只看 `n.module` 的字面首段，于是：
    · `from .. import hive`  → `module is None` → 首段取空串 → **永不命中**（漏判）；
    · `from ... import hive` → 同上（漏判）；
    · `md_cg/kernel/x.py` 里的 `from ..hive import _append`（= `md_cg.hive`，**并不违规**）
      → 字面首段 `hive` → **误判为违规**（假红）。
  折算口径（full_pkg 为该文件的完整包段，含 `md_cg`）：
    level=0 ⇒ 绝对导入，取 name 本身；
    level>=1 ⇒ keep = len(full_pkg) - (level - 1)，
               keep>0 ⇒ full_pkg[:keep] + name（包内）；
               keep==0 ⇒ 越过 `md_cg` 到顶层 ⇒ 就是 name 本身（**这才是真正的反向依赖**）；
               keep<0  ⇒ 越过仓库根，归属不可判（退回 name 字面名，fail-closed）。
"""
from __future__ import annotations

import ast
import io
import os
import shutil
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MDCG = os.path.join(_REPO, "md_cg")
_PKG = "md_cg"  # 扫描根的包名（与 _MDCG 目录名一致）

#: 测试面允许 import hive 的**全量登记表**（实测 6 件）。
#: 双向语义：①出现未登记的 test_*.py ⇒ 红（新反向依赖须显式登记，带理由）；②登记项已不存在 ⇒ 红（抓陈化）。
ALLOWED_TEST_FACE = (
    "test_issue399_hive_json_shape.py",
    "test_issue400_hive_dirty_args.py",
    "test_issue419_pii_redaction.py",
    "test_server_version.py",
    "test_v14_fixes.py",
    "test_v21r1_package_version.py",
)

PASS = FAIL = 0
FAILS = []


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:220])


# 生效条件：full_pkg 为该文件完整包段（含 _PKG，如 ['md_cg','kernel']），level/name 取自 AST 节点。
# 返回折算后的绝对全名；越过仓库根返回 None（归属不可判）。语义见模块 docstring 的 ★★ 段。
def _resolve_relative(full_pkg, level, name):
    if level <= 0:
        return name or None
    keep = len(full_pkg) - (level - 1)
    if keep < 0:
        return None          # 越过仓库根，不可判
    # ★module 为空（`from .. import hive` 形态）：被导入名在 alias 里，**前缀无从拼接**，
    #   一律返回 None，由 _resolve_names() 退回 alias 名。早期版本在此返回了包根（'md_cg'），
    #   等于把 alias 名整个吃掉 —— 正是 R4 抓到的丢名缺陷。
    if not name:
        return None
    if keep == 0:
        return name          # 越过 md_cg 到顶层 ⇒ name 本身就是绝对名（真反向依赖）
    base = full_pkg[:keep] + name.split(".")
    return ".".join(base)


# 生效条件：full_pkg 为该文件完整包段；返回该文件「所有 import 折算后的绝对全名」列表（带行号）。
def _resolve_names(tree, full_pkg):
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.module:
                full = _resolve_relative(full_pkg, n.level or 0, n.module)
                if full:
                    out.append((n.lineno, full))
                    continue
            # module 为空（`from .. import a, b`）：被导入名在 alias 里，前缀按 level 折算后与之拼接。
            # 例：md_cg/kernel/x.py 的 `from .. import hive` ⇒ keep=1 ⇒ 前缀 md_cg ⇒ md_cg.hive（干净）；
            #     md_cg/x.py 的 `from .. import hive`       ⇒ keep=0 ⇒ 前缀为空 ⇒ hive（真违规）。
            if (n.level or 0) > 0:
                _keep = len(full_pkg) - ((n.level or 0) - 1)
            else:
                _keep = len(full_pkg)
            _prefix = full_pkg[:_keep] if _keep > 0 else []
            for al in n.names:
                _segs = _prefix + al.name.split(".")
                out.append((n.lineno, ".".join(_segs) if _segs else al.name))
        elif isinstance(n, ast.Import):
            for al in n.names:
                out.append((n.lineno, al.name))
    return out


# 生效条件：root 存在即成立；返回 ([(相对路径, 行号, 文本)], [相对路径], 文件总数)。
# 扫描面取自文件**实际文本**（AST）；不截断（一次性取全，打印总数以便核对）。
# 相对路径一律用 "/" 分隔且**相对 root**，这样同名文件在 md_cg/ 与 md_cg/kernel/ 下可区分。
def scan_paths(root=_MDCG):
    prod_viol, test_hits, total = [], [], 0
    root = os.path.abspath(root)
    for dp, dn, fns in os.walk(root):
        dn[:] = [d for d in dn if d not in ("__pycache__",)]
        for fn in sorted(fns):
            if not fn.endswith(".py"):
                continue
            total += 1
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            rel_dir = os.path.dirname(rel)
            sub = [] if not rel_dir else rel_dir.split("/")
            full_pkg = [_PKG] + sub
            try:
                tree = ast.parse(io.open(p, encoding="utf-8", errors="replace").read())
            except SyntaxError as e:
                prod_viol.append((rel, 0, "SyntaxError: %s" % e))
                continue
            hits = []
            for ln, full in _resolve_names(tree, full_pkg):
                if full.split(".")[0] == "hive":
                    hits.append((ln, "import %s" % full))
            if not hits:
                continue
            if fn.startswith("test_"):
                test_hits.append(rel)
            else:
                prod_viol.extend((rel, ln, txt) for ln, txt in hits)
    return prod_viol, sorted(test_hits), total


# 生效条件：同 scan_paths；但按旧口径返回**文件名**（供 C1-P/T1/T2 与既有登记表比对，登记表存的是文件名）。
def scan(root=_MDCG):
    pv, th, total = scan_paths(root)
    prod_viol = [(os.path.basename(r), ln, t) for r, ln, t in pv]
    test_hits = sorted(set(os.path.basename(r) for r in th))
    return prod_viol, test_hits, total


#: 相对/绝对导入的 8 个形态断言：(相对 root 的子目录, 文件名, 源码, 期望违规, 说明)
_REL_CASES = (
    ("", "r_lv2_none.py", "from .. import hive\n", True,
     "md_cg/x.py level=2 越过 md_cg ⇒ 顶层 hive ⇒ 违规"),
    ("", "r_lv1_none.py", "from . import hive\n", False,
     "md_cg/x.py level=1 ⇒ md_cg.hive ⇒ 干净"),
    ("kernel", "r_lv3_none.py", "from ... import hive\n", True,
     "md_cg/kernel/x.py level=3 越过 md_cg ⇒ 顶层 hive ⇒ 违规"),
    ("kernel", "r_lv2_none.py", "from .. import hive\n", False,
     "md_cg/kernel/x.py level=2 ⇒ md_cg.hive ⇒ 干净"),
    ("", "r_lv2_mod.py", "from ..hive import _append\n", True,
     "md_cg/x.py level=2 ⇒ 顶层 hive ⇒ 违规"),
    ("kernel", "r_lv2_mod.py", "from ..hive import _append\n", False,
     "md_cg/kernel/x.py level=2 ⇒ md_cg.hive ⇒ **旧判据在此假红**"),
    ("", "r_abs.py", "from hive import _append\n", True, "绝对导入 ⇒ 违规"),
    ("", "r_mix.py", "from . import hive\nimport hive\n", True,
     "相对干净 + 绝对违规 ⇒ 仍须抓（逐 name 判定，非整文件一刀切）"),
    # ★三层包：只有 keep=2 才能与「永远只取 full_pkg[:1]」区分开。
    #   md_cg/kernel/deep/x.py：level=2 ⇒ keep=3-2+1=2 ⇒ md_cg.kernel.hive（干净）
    #                           level=3 ⇒ keep=1        ⇒ md_cg.hive（干净）
    #                           level=4 ⇒ keep=0        ⇒ 顶层 hive（违规）
    ("kernel/deep", "r3_lv2.py", "from .. import hive\n", False,
     "md_cg/kernel/deep/x.py level=2 ⇒ md_cg.kernel.hive ⇒ 干净（deep 层被保留）"),
    ("kernel/deep", "r3_lv4.py", "from .... import hive\n", True,
     "md_cg/kernel/deep/x.py level=4 越过 md_cg ⇒ 顶层 hive ⇒ 违规"),
    ("kernel/deep", "r3_lv2_mod.py", "from ..hive import _x\n", False,
     "md_cg/kernel/deep/x.py level=2 ⇒ md_cg.kernel.hive ⇒ 干净"),
    ("kernel/deep", "r3_lv3_mod.py", "from ...hive import _x\n", False,
     "md_cg/kernel/deep/x.py level=3 ⇒ md_cg.hive ⇒ 干净（**只取包根会在此假红**）"),
)


def main():
    print("== C1：md_cg 生产码不得 import hive（依赖方向单向：外围→核心）==")
    prod_viol, test_hits, total = scan()
    print("  [扫描面] md_cg/**/*.py 共 %d 件（全量扫描，未截断）" % total)
    print("  [读数] 生产面违规 %d 处：%s" % (len(prod_viol), prod_viol or "（无）"))
    print("  [读数] 测试面 import hive 的文件 %d 件：%s" % (len(test_hits), test_hits))
    ok("C1-P 生产面零处 import hive（违规则全量列出，见上）", not prod_viol,
       "生产面违规全量 = %s" % (prod_viol,))
    _unreg = [f for f in test_hits if f not in ALLOWED_TEST_FACE]
    ok("C1-T1 测试面 import hive 的文件全部已登记（未登记即红）", not _unreg, _unreg)
    _missing = [f for f in ALLOWED_TEST_FACE if f not in test_hits]
    ok("C1-T2 反向腿：登记的允许项必须真的存在（登记了却无引用 ⇒ 红，抓陈化登记）",
       not _missing, "登记了却无此引用（或文件名已改）：%s" % _missing)

    print("")
    print("== C1-S 自检：真造反例，证明本腿**能红**（非「断言某函数被调用过」）==")
    sb = tempfile.mkdtemp(prefix="c1_selfcheck_")
    try:
        sub = os.path.join(sb, "md_cg")
        os.makedirs(os.path.join(sub, "kernel"), exist_ok=True)
        io.open(os.path.join(sub, "okmod.py"), "w", encoding="utf-8").write("import os\n")
        io.open(os.path.join(sub, "badmod.py"), "w", encoding="utf-8").write(
            "from hive import _append\nimport json\n")
        io.open(os.path.join(sub, "test_legit.py"), "w", encoding="utf-8").write(
            "import hive\n")
        _pv, _th, _tot = scan(sub)
        ok("C1-S1 反例面：自造反例树被扫到 3 件（不截断，先报总数）", _tot == 3, _tot)
        ok("C1-S2 ★真造反例：生产文件 import hive ⇒ **判据本体转红**（P 支捕获 1 处）",
           len(_pv) == 1 and _pv[0][0] == "badmod.py", _pv)
        ok("C1-S3 测试面同名反例被**正确归入允许面**而非生产违规（两面确实分开）",
           _th == ["test_legit.py"] and all(v[0] != "test_legit.py" for v in _pv),
           {"test_hits": _th, "prod": _pv})

        print("")
        print("== C1-R 相对导入折算：逐形态断言（防「判据只认绝对导入」的漏判/误判）==")
        for _d, _n, _s, _e, _desc in _REL_CASES:
            _dst = os.path.join(sub, _d, _n)
            if not os.path.isdir(os.path.dirname(_dst)):
                os.makedirs(os.path.dirname(_dst), exist_ok=True)
            io.open(_dst, "w", encoding="utf-8").write(_s)
        # 关键：**一次整树扫描**，靠相对路径区分 md_cg/x.py 与 md_cg/kernel/x.py
        _pv2, _th2, _ = scan_paths(sub)
        _flagged = set(r for r, _ln, _t in _pv2)
        _wrong = []
        for _d, _n, _s, _e, _desc in _REL_CASES:
            _rel = (_d + "/" + _n) if _d else _n
            _got = _rel in _flagged
            print("    %-24s 应判=%-4s 实判=%-4s %s  %s"
                  % (_rel, "违规" if _e else "干净", "违规" if _got else "干净",
                     "OK    " if _got == _e else "***错判***", _desc))
            if _got != _e:
                _wrong.append((_rel, _e, _got, _desc))
        ok("C1-R1 ★12 态相对/绝对导入折算全部判对（含旧判据的 2 处漏判 + 1 处假红）",
           not _wrong, _wrong)
        # 同一字面导入 `from ..hive import _append` 在两层应给出相反结论
        _root_hit = "r_lv2_mod.py" in _flagged
        _kern_hit = "kernel/r_lv2_mod.py" in _flagged
        ok("C1-R2 同一字面导入在不同层级给出相反结论（证明确实按位置折算，非按字面名一刀切）",
           _root_hit is True and _kern_hit is False,
           {"md_cg/ 命中": _root_hit, "md_cg/kernel/ 命中": _kern_hit})

        # ★R3 直接断言**折算出的全名字符串**，而不只是二元判定。
        #   仅判「违规/干净」档位不足：把 full_pkg[:keep] 改成 full_pkg[:1] 会让
        #   kernel/deep 的干净态仍算干净（都落到 md_cg... 前缀），判定不变却错解了位置。
        #   表内 (完整包段, level, module, 期望全名或 None)。
        #   注意：module is None（`from .. import hive` 形态）时，被导入名在 alias 里，
        #   本函数**只折前缀、返回 None**，由 `_resolve_names()` 拼 alias —— 这条路径由 R4 端到端验证。
        _direct = [
            (["md_cg"], 0, "hive", "hive"),
            (["md_cg"], 2, None, None),      # alias 形态：module 为空，前缀不可判 ⇒ None
            (["md_cg"], 1, None, None),      # 同上（alias 会是 md_cg.hive）
            (["md_cg"], 1, "hive", "md_cg.hive"),
            (["md_cg"], 2, "hive", "hive"),
            (["md_cg", "kernel"], 2, None, None),
            (["md_cg", "kernel"], 2, "hive", "md_cg.hive"),
            (["md_cg", "kernel"], 3, "hive", "hive"),
            (["md_cg", "kernel", "deep"], 2, "hive", "md_cg.kernel.hive"),
            (["md_cg", "kernel", "deep"], 3, "hive", "md_cg.hive"),
            (["md_cg", "kernel", "deep"], 4, "hive", "hive"),
            (["md_cg"], 5, "hive", None),   # 越过仓库根 ⇒ 不可判
            (["md_cg", "kernel"], 0, "a.b", "a.b"),
        ]
        _dbad = []
        for pkg, lv, mod, want in _direct:
            got = _resolve_relative(pkg, lv, mod)
            print("    full_pkg=%-32s level=%d module=%-6r -> %-22r 期望 %r %s"
                  % ("/".join(pkg), lv, mod, got, want,
                     "OK" if got == want else "***错***"))
            if got != want:
                _dbad.append((pkg, lv, mod, want, got))
        ok("C1-R3 ★折算结果按**全名字符串**逐条比对（13 态；只比二元判定会漏掉「位置取错但仍非 hive」）",
           not _dbad, _dbad)

        # ★R4 alias 形态（`from .. import hive` / `from ... import hive`）端到端：
        #   module 为空时 _resolve_relative 返回 None，必须由 _resolve_names 退回 alias 名，
        #   否则这两态会整条消失（这正是旧判据的漏判形态）。
        _alias = [
            (["md_cg"], "from .. import hive\n", "hive"),             # 越过 md_cg ⇒ 顶层 hive
            (["md_cg", "kernel"], "from ... import hive\n", "hive"),  # 越过 md_cg ⇒ 顶层 hive
            (["md_cg"], "from . import hive\n", "md_cg.hive"),        # 包内 ⇒ 前缀 md_cg
            (["md_cg", "kernel", "deep"], "from .... import hive\n", "hive"),
        ]
        _abad = []
        for pkg, src, want in _alias:
            names = [f for _ln, f in _resolve_names(ast.parse(src), pkg)]
            print("    pkg=%-26s %-26r -> %s" % ("/".join(pkg), src.strip(), names))
            if want not in names:
                _abad.append((pkg, src.strip(), want, names))
        ok("C1-R4 ★alias 形态（module=None）不丢名：4 态都能解析出 hive（旧判据在此全盲）",
           not _abad, _abad)
    finally:
        shutil.rmtree(sb, ignore_errors=True)

    print("")
    print("断言总数 %d（PASS %d / FAIL %d）" % (PASS + FAIL, PASS, FAIL))
    if FAILS:
        print("FAILED:")
        for f in FAILS:
            print("   - " + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
