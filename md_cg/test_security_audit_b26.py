#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全审计修复守卫 B（批次 26，外部审查报告 P1-2/3/4/5/6/7）。

- P1-4：check_path_root 根白名单（env 未设=放开 / 设置=越界即拒）
- P1-5：LEGACY env 身份不再自授 admin（需显式二次开关）
- P1-7：bootstrap_loop AST 沙箱（合法排序函数过 / 恶意样本全拒）
- P1-6 增量：hive read_file 敏感凭据路径拒读
- P1-2/P1-3：TS 侧（roleplay_web）静态断言 + tsc 编译由 gate 覆盖
"""
import importlib.util
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def main():
    from md_cg.security import check_path_root

    print("== P1-4 check_path_root 根白名单 ==")
    tmp = tempfile.mkdtemp(prefix="b26_root_")
    os.environ["MDCG_INGEST_ROOT"] = tmp
    try:
        check_path_root(os.path.join(tmp, "a.jsonl"), "MDCG_INGEST_ROOT", "t")
        check("P1-4a 根内路径放行", True)
        try:
            check_path_root(os.path.join(tmp, "..", "evil.jsonl"),
                            "MDCG_INGEST_ROOT", "t")
            check("P1-4b .. 穿越出根拒绝", False, "未抛")
        except PermissionError:
            check("P1-4b .. 穿越出根拒绝", True)
        try:
            check_path_root("C:/Windows/win.ini", "MDCG_INGEST_ROOT", "t")
            check("P1-4c 根外绝对路径拒绝", False, "未抛")
        except PermissionError:
            check("P1-4c 根外绝对路径拒绝", True)
        check_path_root(None, "MDCG_INGEST_ROOT", "t")
        check("P1-4d 无路径参数（stat 类）放行", True)
    finally:
        os.environ.pop("MDCG_INGEST_ROOT", None)
    check_path_root("C:/Windows/win.ini", "MDCG_INGEST_ROOT", "t")
    check("P1-4e env 未设置=放开（默认部署零变更）", True)

    print("== P1-5 LEGACY env 身份 admin 二次开关 ==")
    saved = {k: os.environ.get(k) for k in
             ("MDCG_TOKEN", "MDCG_LEGACY_ENV_AUTH", "MDCG_CAN_ADMIN",
              "MDCG_LEGACY_ENV_ADMIN", "MDCG_CLEARANCE")}
    try:
        os.environ["MDCG_TOKEN"] = ""
        os.environ["MDCG_LEGACY_ENV_AUTH"] = "1"
        os.environ["MDCG_CAN_ADMIN"] = "1"
        os.environ.pop("MDCG_LEGACY_ENV_ADMIN", None)
        from md_cg.mcp_server import _build_principal
        p, err = _build_principal()
        check("P1-5a 只设 CAN_ADMIN：can_admin 强制 False",
              p is not None and not p.can_admin, f"p={p}")
        check("P1-5b 降级 recorder", p is not None and p.role == "recorder",
              f"role={getattr(p, 'role', None)}")
        os.environ["MDCG_LEGACY_ENV_ADMIN"] = "1"
        p2, _ = _build_principal()
        check("P1-5c 二次开关后 admin 恢复",
              p2 is not None and p2.can_admin and p2.role == "designer",
              f"p2={p2}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print("== P1-7 bootstrap_loop AST 沙箱 ==")
    spec = importlib.util.spec_from_file_location(
        "bl_b26", os.path.join(REPO, "scripts", "bootstrap_loop.py"))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    f = m._safe_exec_gen
    ns = f("def solve(arr):\n"
           "    n = len(arr)\n"
           "    for i in range(n):\n"
           "        for j in range(0, n - i - 1):\n"
           "            if arr[j] > arr[j + 1]:\n"
           "                arr[j], arr[j + 1] = arr[j + 1], arr[j]\n"
           "    return arr\n")
    check("P1-7a 合法排序函数通过且正确", ns["solve"]([3, 1, 2]) == [1, 2, 3])
    bans = [
        "import os", "from subprocess import run", 'open("x")',
        'eval("1")', 'exec("x=1")', '__import__("os")',
        "x.__class__", "getattr(int, 'real')",
    ]
    n_blocked = 0
    for c in bans:
        try:
            f("def f():\n    return " + c if not c.startswith(("import", "from"))
              else c)
        except ValueError:
            n_blocked += 1
        except Exception:               # noqa: BLE001——其它异常也算被拦
            n_blocked += 1
    check(f"P1-7b 恶意样本全拒（{n_blocked}/{len(bans)}）",
          n_blocked == len(bans))

    print("== P1-6 增量：hive read_file 敏感路径拒读 ==")
    spec2 = importlib.util.spec_from_file_location(
        "hx_b26", os.path.join(REPO, "hive", "exec.py"))
    hx = importlib.util.module_from_spec(spec2)
    try:
        spec2.loader.exec_module(hx)
    except SystemExit:
        pass
    home = os.path.expanduser("~").replace("\\", "/")
    check("P1-6a ~/.ssh/id_rsa 拒",
          hx._sensitive_read(os.path.join(home, ".ssh", "id_rsa")) is not None)
    check("P1-6b .env 拒",
          hx._sensitive_read(os.path.join(home, "proj", ".env")) is not None)
    check("P1-6c server.pem 拒",
          hx._sensitive_read(os.path.join(home, "certs", "server.pem"))
          is not None)
    check("P1-6d 普通 md 放行",
          hx._sensitive_read(os.path.join(home, "notes", "readme.md")) is None)
    check("P1-6e 源码 .py 放行",
          hx._sensitive_read(os.path.join(home, "proj", "main.py")) is None)

    print("== P1-2/P1-3 roleplay_web 静态断言（行为由 tsc+集成覆盖）==")
    ts = open(os.path.join(REPO, "src", "lib", "roleplay_web.ts"),
              encoding="utf-8").read()
    check("P1-2 fail-closed（未配置不再 return true）",
          "if (!EDIT_KEY)\n                return false;" in ts
          and "editKeyHint" in ts)
    check("P1-3 角色白名单+危险键拒绝",
          "validRoleId" in ts and "'__proto__'" in ts and "toNullProto" in ts)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    for x in FAILS:
        print(f"  - {x}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
