# -*- coding: utf-8 -*-
"""配对测试：scripts/check_relation_types.py（G2 分布统计）。

# 功能名：check_relation_types 的配对测试
# 生效条件：每次 run_tests.py 收集 scripts/test_*.py 时
# 子功能：①脚本可导入且有 main ②无库根时 fail-closed 退 2 ③库根不存在退 2
#         ④白名单纯函数不读环境变量（C1 回归）
# 执行：python scripts/test_check_relation_types.py
# 验证方式：本文件自身；孤儿判定由 scripts/check_guard_coverage.py 复核
# 不适用条件：不测真实库分布（那由 tests/test_relation_type_whitelist_guard.py 的实库断言覆盖）
"""
from __future__ import annotations
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("   [PASS] " + name + (("  · " + detail) if detail else ""))
    else:
        print("   [FAIL] " + name + (("  · " + detail) if detail else ""))
        FAILS.append(name)


def _load():
    p = os.path.join(HERE, "check_relation_types.py")
    spec = importlib.util.spec_from_file_location("check_relation_types", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    m = _load()
    check("脚本可导入且有 main", callable(getattr(m, "main", None)))

    # fail-closed：缺库根 -> 2
    rc = m.main(["--root", ""])
    check("缺库根退 2（fail-closed）", rc == 2, "rc=%s" % rc)

    # fail-closed：库根不存在 -> 2
    rc = m.main(["--root", os.path.join(REPO, "__no_such_lib__")])
    check("库根不存在退 2", rc == 2, "rc=%s" % rc)

    # 白名单纯函数不读 env（C1 回归）。
    # 用 AST 判定而非字符串包含——首版用 "os.environ" not in src，被本模块 docstring
    # 里引述历史的那句话误伤（自检假红）。AST 只看真实代码节点，不受注释影响。
    import ast
    from md_cg import relations as R
    src = open(os.path.join(REPO, "md_cg", "relations.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    env_reads = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and n.attr == "environ"]
    check("relations.py 不读 os.environ（AST 判定）",
          not env_reads, "命中 %d 处 Attribute(environ)" % len(env_reads))
    check("resolve_mode 非法值回落默认",
          R.resolve_mode("nonsense") == R.DEFAULT_MODE
          and R.resolve_mode(None) == R.DEFAULT_MODE
          and R.resolve_mode("enforce") == "enforce")

    print("")
    if FAILS:
        print("配对测试：失败 %d 项 -> %s" % (len(FAILS), FAILS))
        return 1
    print("配对测试：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
