# -*- coding: utf-8 -*-
# 功能名：租户 × 根解析（_resolve_root）的反查面覆盖「声明了未登记租户」这条路径（issue #319）
# 生效条件：python -X utf8 -m md_cg.test_issue319_tenant_unregistered_bypass [--mutate]；被测面=md_cg/mcp_server.py 的 _resolve_root
# 子功能：A 组=单元面判据（未登记租户不得绕过身份与根对照，且合法登记/自建根不被误拒）；B 组=子进程实跑 rc（入口 fail-closed 真触发）
# 执行：--mutate 时逐条把判据改回改动前形态，守卫必须转红（定点变异自证）
# 验证方式：全部 PASS 即通过；--mutate 下每条变异的「指定命中」须与预期一致
# 不适用条件：不判令牌签发/作用域（属 tokens.py）；不覆盖 POSIX 腿；登记表损坏时的回落是既有 N124 口径，本守卫只如实断言不收紧
"""issue #319 守卫：未登记租户不得成为 #98 身份-根对照的绕过口。

病象（修前）：_resolve_root 里 t_root 只在 `if tenant:` 内赋值，而 #98 的反查面挂在
`else:`（仅 tenant 为假时执行）。tenant 为真但**未登记**时 t_root 为 None、`else:` 不
跑，程序直接用 MDCG_ROOT 不做任何对照 ⇒ 只多设一个 MDCG_TENANT=default（未登记）
就能拿自己的令牌打开别的已登记租户的根。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from md_cg import mcp_server  # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss319_")
# 目录名避开 Windows 保留设备名（aux/nul/...）：启动守卫会 fail-closed。
_ROOT_B = os.path.abspath(os.path.join(_TMP, "rootB"))
_ROOT_OWN = os.path.abspath(os.path.join(_TMP, "rootOwn"))
_ROOT_C = os.path.abspath(os.path.join(_TMP, "rootC"))
_REG = os.path.join(_TMP, "tenants.json")
_REG_BAD = os.path.join(_TMP, "tenants_bad.json")

with io.open(_REG, "w", encoding="utf-8") as f:
    json.dump({"schema": 1, "tenants": {
        "B": {"root": _ROOT_B, "clearance_cap": "internal",
              "description": ""}}}, f, ensure_ascii=False)
with io.open(_REG_BAD, "w", encoding="utf-8") as f:
    f.write("{ 这不是 JSON")


def _r(**env):
    e = dict(env)
    e.setdefault("MDCG_TENANT_REGISTRY", _REG)
    return mcp_server._resolve_root(e)


print("== A 组：单元面判据 ==")

_a1 = _r(MDCG_ROOT=_ROOT_B)
_check("A1 未声明租户 + 根=B 的登记根 → fail-closed（#98 既有面不退化）",
       _a1[0] is None and "未声明 MDCG_TENANT" in (_a1[1] or ""), _a1)

_a2 = _r(MDCG_ROOT=_ROOT_B, MDCG_TENANT="default")
_check("A2 声明**未登记**租户 default + 根=B 的登记根 → fail-closed（#319 收口）",
       _a2[0] is None and "MDCG_TENANT=default" in (_a2[1] or "")
       and "未登记" in (_a2[1] or ""), _a2)

_a3 = _r(MDCG_ROOT=_ROOT_OWN, MDCG_TENANT="default")
_check("A3 未登记租户 + **自建**根 → 放行（不误拒，零变更）",
       _a3 == (_ROOT_OWN, None), _a3)

_a4 = _r(MDCG_ROOT=_ROOT_B, MDCG_TENANT="B")
_check("A4 已登记租户 B + B 自己的根 → 放行（合法路径不误拒）",
       _a4 == (_ROOT_B, None), _a4)

_a5 = _r(MDCG_ROOT=_ROOT_C, MDCG_TENANT="B")
_check("A5 已登记租户 B + 别人的根 C → fail-closed（既有冲突面不退化）",
       _a5[0] is None and "不一致" in (_a5[1] or ""), _a5)

_a6 = _r(MDCG_TENANT="B")
_check("A6 已登记租户 B + 未设根 → 取登记根 B（不误拒）",
       _a6 == (_ROOT_B, None), _a6)

_a7 = _r(MDCG_ROOT=_ROOT_B, MDCG_TENANT="default", MDCG_TENANT_REGISTRY=_REG_BAD)
_check("A7 登记表损坏 → 仍回落放行（N124 既有口径，只开口不收紧；本守卫只断言不扩面）",
       _a7 == (_ROOT_B, None), _a7)

_a8 = _r(MDCG_ROOT=_ROOT_OWN)
_check("A8 未声明租户 + 自建根 → 放行（#98 不误伤自建根）",
       _a8 == (_ROOT_OWN, None), _a8)

print("== B 组：子进程实跑（入口 fail-closed 真触发）==")

_ENV0 = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
             MDCG_AUX_ROOT=os.path.join(_TMP, "auxstore"),
             MDCG_STATE_ROOT=os.path.join(_TMP, "state"),
             MDCG_DATA_ROOT=os.path.join(_TMP, "datastore"),
             MDCG_EXPORT_ROOT=_TMP,
             MDCG_SUSTAIN="0", MDCG_SLEEP="0")


def _boot(**env):
    e = dict(_ENV0)
    e.update(env)
    e.setdefault("MDCG_TENANT_REGISTRY", _REG)
    p = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                       input="", capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=e, cwd=_REPO,
                       timeout=300)
    return p.returncode, (p.stderr or "")


_rc1, _e1 = _boot(MDCG_ROOT=_ROOT_B, MDCG_TENANT="default")
_check("B1 攻击腿：未登记租户 default + B 的登记根 → rc=2 且报「身份与根未对照」",
       _rc1 == 2 and "MDCG_TENANT=default" in _e1, (_rc1, _e1[-200:]))

_rc2, _e2 = _boot(MDCG_ROOT=_ROOT_B)
_check("B2 对照腿：未声明租户 + B 的登记根 → rc=2（#98 既有面）",
       _rc2 == 2 and "未声明 MDCG_TENANT" in _e2, (_rc2, _e2[-200:]))

_rc3, _e3 = _boot(MDCG_ROOT=_ROOT_OWN, MDCG_TENANT="default")
_check("B3 反例腿：未登记租户 + 自建根 → 不因根对照被拒（rc!=2）",
       _rc3 != 2, (_rc3, _e3[-200:]))

_rc4, _e4 = _boot(MDCG_ROOT=_ROOT_B, MDCG_TENANT="B")
_check("B4 反例腿：已登记租户 B + B 的根 → 不因根对照被拒（rc!=2）",
       _rc4 != 2, (_rc4, _e4[-200:]))

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #319 结果：%d 失败" % len(FAILS))
else:
    print("issue #319 结果：全部通过")


# ---------------------------------------------------------------- 定点变异

_MUTATIONS = (
    ("V1 反查面条件回到修前形态（只覆盖「未声明租户」）",
     "md_cg/mcp_server.py",
     "    if not (tenant and t_root):",
     "    if not tenant:",
     ("A2", "B1")),
    ("V2 反查面整体停用（#98 与本修一起失效）",
     "md_cg/mcp_server.py",
     "    if not (tenant and t_root):",
     "    if False:",
     ("A1", "A2", "B1", "B2")),
    ("V3 无条件反查（合法登记路径被误拒 = 放宽的反向：过度收紧）",
     "md_cg/mcp_server.py",
     "    if not (tenant and t_root):",
     "    if True:",
     ("A4", "A6", "B4")),
    # 注：原拟的「t_root 挪回 if tenant 分支内」变异**不是有效变异**——条件式
    # `tenant and t_root` 在 tenant 为假时短路，根本不会读 t_root，故 hoist 与否
    # 在本修里不承重（hoist 只是可读性）。改成对**失败文案**的变异：文案是报告
    # 自己点名的面（「拒绝文案要从『未声明 MDCG_TENANT』改成按实际情况」）。
    ("V4 失败文案回到恒说「未声明 MDCG_TENANT」（明明声明了却报未声明）",
     "md_cg/mcp_server.py",
     "                        f\"但本进程{_decl} —— 身份与根未对照，\"",
     "                        f\"但本进程未声明 MDCG_TENANT —— 身份与根未对照，\"",
     ("A2", "B1")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss319_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__",
                                                         "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue319_tenant_unregistered_bypass"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=3600)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）"
              % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = io.open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次"
                           % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            io.open(p, "w", encoding="utf-8", newline="").write(
                t.replace(old, new, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            io.open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            if rc2 != 0 and len(hit) == len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())