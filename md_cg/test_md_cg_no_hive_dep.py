# -*- coding: utf-8 -*-
# 功能名：md_cg 生产码不得依赖 hive（依赖方向单向：外围→核心）
# 生效条件：python -u -X utf8 -m md_cg.test_md_cg_no_hive_dep；扫描面 = md_cg/**/*.py 的 AST import（取自文件实际文本）
# 子功能：P 生产面禁止 import hive · T 测试面允许但必须落在显式登记表内（双向：登记了却不存在即红）· S 自检（真造反例证明本腿能红）
# 执行：直接跑；退出码 0=全绿、1=有红
# 验证方式：全部 PASS；S 段在临时区真造一份 import hive 的 md_cg 生产文件，断言判据转红
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


# 生效条件：root 存在即成立；返回 (生产违规列表, 测试面 import hive 的文件名排序列表, 扫描到的文件总数)。
# 扫描面取自文件**实际文本**（AST）；不截断（一次性取全，打印总数以便核对）。
def scan(root=_MDCG):
    prod_viol, test_hits, total = [], [], 0
    for dp, dn, fns in os.walk(root):
        dn[:] = [d for d in dn if d not in ("__pycache__",)]
        for fn in sorted(fns):
            if not fn.endswith(".py"):
                continue
            total += 1
            p = os.path.join(dp, fn)
            try:
                tree = ast.parse(io.open(p, encoding="utf-8", errors="replace").read())
            except SyntaxError as e:
                prod_viol.append((fn, 0, "SyntaxError: %s" % e))
                continue
            hits = []
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "hive":
                    hits.append((n.lineno, "from %s import ..." % (n.module or "")))
                if isinstance(n, ast.Import):
                    for al in n.names:
                        if al.name.split(".")[0] == "hive":
                            hits.append((n.lineno, "import %s" % al.name))
            if not hits:
                continue
            if fn.startswith("test_"):
                test_hits.append(fn)
            else:
                prod_viol.extend((fn, ln, txt) for ln, txt in hits)
    return prod_viol, sorted(test_hits), total


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
        os.makedirs(sub, exist_ok=True)
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