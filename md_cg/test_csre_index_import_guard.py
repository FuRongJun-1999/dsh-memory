# -*- coding: utf-8 -*-
"""守卫 · csre 装机态索引导入名（#75①，2026-10-09 DSH 端修复随附）。

修前：csre.py:61 'from md_access import md_conn_or_none' —— 该名不存在
（md_access.py:447 实际定义 '_md_conn_or_none'），build_index() 首行即
ImportError（CPython 自身提示 "Did you mean: '_md_conn_or_none'?"）。

判据（以真跑为主——PR#77 的 AST 静态断言覆盖偏窄，本守卫补真跑面）：
  G1 真跑：临时 sqlite 上 Csre(db).build_index() 返回 dict（修前=ImportError）
  G2 静态：csre.py 里不再出现裸名 md_conn_or_none
  G3 定义面：md_access 有 _md_conn_or_none、无裸名 md_conn_or_none

依赖：numpy（csre 模块级硬依赖）。无 numpy 时 G1 显式 SKIP 并明示原因——
对齐 issue #84「numpy 硬依赖无 SKIP」的口径：宁显式跳过，不静默放绿。

运行：python -m md_cg.test_csre_index_import_guard
      python -m md_cg.test_csre_index_import_guard --self-proof   # 变异自证
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 无 numpy 仅跳过
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WISDOM = os.path.join(HERE, "whitebox_kb", "wisdom")
for _p in (REPO, WISDOM):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PASS = 0
FAIL = 0
SKIP = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def skip(name, why):
    global SKIP
    SKIP += 1
    print("[SKIP] %s  · %s" % (name, why))


def _temp_db(db_path):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE nodes (id TEXT, content TEXT, "
                 "state_attributes TEXT, tags TEXT)")
    conn.execute("INSERT INTO nodes VALUES ('n1', '守卫用测试卡', '{}', "
                 "'knowledge_point')")
    conn.commit()
    conn.close()


def _run_build_index(db_path):
    """返回 (kind, detail)：ok / import_error / other_error / unavailable。"""
    try:
        from md_cg.whitebox_kb.wisdom.csre import Csre
    except Exception as exc:
        return "unavailable", "%s: %s" % (type(exc).__name__, str(exc)[:120])
    try:
        engine = Csre(db_path=db_path)
        result = engine.build_index()
    except ImportError as exc:
        return "import_error", str(exc)[:150]
    except Exception as exc:
        return "other_error", "%s: %s" % (type(exc).__name__, str(exc)[:120])
    if not isinstance(result, dict):
        return "other_error", "返回非 dict：%s" % type(result).__name__
    return "ok", "keys=%s" % sorted(result)[:4]


def _numpy_available():
    try:
        import numpy  # noqa: F401
        return True, ""
    except Exception as exc:
        return False, type(exc).__name__


def run():
    import md_access

    check("G3a md_access 定义 _md_conn_or_none（带下划线）",
          hasattr(md_access, "_md_conn_or_none"), "md_access.py:447")
    check("G3b md_access 无裸名 md_conn_or_none",
          not hasattr(md_access, "md_conn_or_none"), "")

    src = open(os.path.join(WISDOM, "csre.py"), encoding="utf-8").read()
    bare = ("import md_conn_or_none" in src) or ("= md_conn_or_none()" in src)
    check("G2 csre.py 不再出现裸名 md_conn_or_none", not bare,
          ("命中 %d 处" % src.count("md_conn_or_none")) if bare else "")

    has_np, why = _numpy_available()
    if not has_np:
        skip("G1 真跑 build_index（临时库）",
             "csre 模块级 numpy 不可用（%s）——按 #84 口径显式 SKIP" % why)
    else:
        db = os.path.join(tempfile.gettempdir(), "csre_guard_probe.db")
        _temp_db(db)
        kind, detail = _run_build_index(db)
        try:
            os.remove(db)
        except OSError:
            pass
        check("G1 真跑 build_index 返回 dict（修前=ImportError）", kind == "ok",
              "%s｜%s" % (kind, detail))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d ／ 跳过 %d" % (PASS, FAIL, SKIP))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    if FAIL:
        return 1
    if SKIP:
        return 2
    return 0


def self_proof():
    """变异自证：就地把导入名改回错名 → 守卫必红；随后复原。"""
    target = os.path.join(WISDOM, "csre.py")
    original = open(target, encoding="utf-8").read()
    mutated = original.replace("from md_access import _md_conn_or_none",
                               "from md_access import md_conn_or_none")
    mutated = mutated.replace("_md = _md_conn_or_none()", "_md = md_conn_or_none()")
    if mutated == original:
        print("[FAIL] 自证：变异未生效（找不到锚点）")
        return 1
    try:
        open(target, "w", encoding="utf-8").write(mutated)
        print("== 变异已注入（裸名回填）——期望 G1/G2 变红 ==")
        rc = run()
    finally:
        open(target, "w", encoding="utf-8").write(original)
    print("== 已复原 ==")
    ok_red = rc != 0
    print("[%s] 自证：变异后守卫变红并点名（rc=%d）" % ("PASS" if ok_red else "FAIL", rc))
    return 0 if ok_red else 1


if __name__ == "__main__":
    if "--self-proof" in sys.argv:
        sys.exit(self_proof())
    sys.exit(run())
