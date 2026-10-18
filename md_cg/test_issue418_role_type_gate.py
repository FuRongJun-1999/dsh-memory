# -*- coding: utf-8 -*-
# 功能名：工具面 role 类型闸守卫（issue #418，「回执与事实不符」族）
# 生效条件：python -X utf8 -m md_cg.test_issue418_role_type_gate [--mutate]；被测面=**mdcg_remember 工具面**（mcp_server._dispatch）+ nodefile.valid_role 单点谓词 + mdcg 两处引用
# 子功能：A=工具面端到端（非法 role 拒收 / 合法与缺省可读回=回执即事实）；B=单点谓词只有一处实现且三处引用都指向它（源码面）；E=枚举完备性自证（_guard_kit 骨架①）；R=回退即绿自证（_guard_kit 骨架②）
# 执行：--mutate 时先跑双向变异，再跑回退自证（实跑镜像树，不接受推演）
# 验证方式：全部 PASS 即通过；--mutate 下回退后红项须恰为「写面闸 + 单点引用」相关断言集合（实测值）
# 不适用条件：不判 cg(op=write) 面的 role（writepipe 通路，另案）；不判「隔离要可读」（health 四读面不透出隔离，属运维输出契约，本批只登记不改）；不判 recent 事件行的 role 语义（只判它引用了同一单点）
"""issue #418 守卫：非法 role **必须在写入前被拒**，回执必须等于事实。

病象（修前实测）：工具面 mdcg_remember(role=[1,2,3]) 落盘并回执 {"ok":true,
"committed":true}；下次装载时 nodefile.frontmatter_problem 判「role 类型非法」⇒
节点进隔离（不进索引、不改盘）⇒ get=not_found、search 扫不到，而四个运维读面
都不报隔离 —— 用户视角＝「说存住了，其实读不到」。

修法：入口 **fail-closed 拒收**（与 check_recent_event 的 docstring 逐字同款
「类型错 ⇒ 不静默降级」），判据走**单点谓词** nodefile.valid_role（三处引用同一实现）。

★ 本守卫的腿**必须走 mdcg_remember 工具面**（不能直调原语）——#418 的病灶正是
「工具面回执与盘面不符」，直调原语会绕过回执面、把本条最该钉的东西漏掉。
"""
from __future__ import annotations

import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile

_SB = tempfile.mkdtemp(prefix="i418_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SB
os.environ["MDCG_ROOT"] = os.path.join(_SB, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_POLICY_FILE", None)

from . import autonomy_modes as am, mcp_server, nodefile   # noqa: E402
os.environ[am.AUTONOMY_ENV_KEYS["mode"]] = "full"
from .mdcos import MdCGSecure                              # noqa: E402
from .security import Principal                            # noqa: E402
import md_cg._guard_kit as _kit                            # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR = 7
PASS, FAIL = 0, 0
FAILS = []
_KEK = os.urandom(32)
_C_CCG = ("# 功能名：role 类型闸探针\n# 生效条件：当复验 #418 时\n"
          "# 子功能：钉住回执与盘面一致\n# 执行：走 mdcg_remember 工具面\n"
          "# 验证方式：test\n# 不适用条件：无\n\n正文 %s\n")


def _check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:240])


def _mk(tag):
    return MdCGSecure(os.path.join(_SB, "lib_" + tag),
                      principal=Principal(tenant="t1", actor="alice",
                                          role="designer", clearance="secret",
                                          can_write=True, can_admin=True),
                      master_key=_KEK)


def _tool_remember(cg, tag, **extra):
    """★走**工具面**（mdcg_remember），不直调原语。"""
    a = {"content": _C_CCG % tag, "layer": "knowledge", "node_id": "n_" + tag}
    a.update(extra)
    return mcp_server._dispatch(cg, "mdcg_remember", a)


print("== A 组：工具面端到端（回执 == 事实）==")
_CG = _mk("a")

_R_BAD = _tool_remember(_CG, "bad", role=[1, 2, 3])
_check("A01 ★非法 role(list) 必须**非成功**回执（修前 committed=true）",
       _R_BAD.get("ok") is not True and _R_BAD.get("committed") is not True,
       _R_BAD)
_check("A02 ★拒收回执给出机器码与 got_type（可修正，不静默）",
       _R_BAD.get("error") == "role_not_str"
       and _R_BAD.get("got_type") == "list", _R_BAD)
_check("A03 ★非法 role **不得落盘**（盘面不得有该节点）",
       _CG.get("n_bad") is None
       and not os.path.exists(os.path.join(_CG.root, "knowledge", "orphan", "n_bad.md")),
       _CG.get("n_bad"))

_R_OK = _tool_remember(_CG, "ok", role="user")
_R_DEF = _tool_remember(_CG, "dflt")
_check("A04 对照：合法 role / 缺省 role 都必须成功**且能被读回**（回执即事实）",
       _R_OK.get("committed") is True and _R_DEF.get("committed") is True
       and _CG.get("n_ok") is not None and _CG.get("n_dflt") is not None,
       (_R_OK.get("committed"), _R_DEF.get("committed"),
        bool(_CG.get("n_ok")), bool(_CG.get("n_dflt"))))
_check("A05 对照：合法写的 fm.role 与声明一致（不是静默改写成别的）",
       ((_CG.get("n_ok") or {}).get("frontmatter") or {}).get("role") == "user",
       ((_CG.get("n_ok") or {}).get("frontmatter") or {}).get("role"))
# dict / int 两形态同族（报告 §六 提到臂读数另有这两例）
for _i, _bad in enumerate(({"a": 1}, 7)):
    _r = _tool_remember(_CG, "x%d" % _i, role=_bad)
    _check("A06 同族形态 role=%s 同样 fail-closed" % type(_bad).__name__,
           _r.get("ok") is not True and _r.get("error") == "role_not_str", _r)
_CG.close()

print("")
print("== B 组：单点谓词（源码面）==")


def _sources():
    out = {}
    for root, dirs, names in os.walk(os.path.join(_REPO, "md_cg")):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "jobs", "target")]
        for n in names:
            if n.endswith(".py") and not n.startswith("test_"):
                p = os.path.join(root, n)
                out[os.path.relpath(p, _REPO).replace(os.sep, "/")] = io.open(
                    p, encoding="utf-8").read()
    return out


_SRC = _sources()
#: 每文件（定义数, 引用数）——「def valid_role(」同时含「valid_role(」，故引用数要减去定义数。
_CNT = {rel: (t.count("def valid_role("), t.count("valid_role(")) for rel, t in _SRC.items()}
_DEF_FILES = sorted(rel for rel, (d, _u) in _CNT.items() if d)
_USE = {rel: u - d for rel, (d, u) in _CNT.items()}
_USE = {rel: n for rel, n in _USE.items() if n}
_check("B01 ★谓词只有**一处实现**（且该文件内恰 1 个 def）",
       _DEF_FILES == ["md_cg/nodefile.py"] and _CNT["md_cg/nodefile.py"][0] == 1,
       (_DEF_FILES, _CNT.get("md_cg/nodefile.py")))
_check("B01 ★全部引用都指向它（**五处**：nodefile = fm 契约 1；mdcg = recent 写闸 +"
       "读容错 2；mcp_server = 写面入参闸 1 + **identity observe 面闸 1**（第二入口，"
       "2026-10-16 回归：`mdcg_identity`/`cg(op=identity)` 共用 `_identity_call`，"
       "此前未过闸 ⇒ 非法 role 照样落盘后被隔离，回执却是 ok:true））"
       "——新增引用必须显式登记在此",
       _USE == {"md_cg/nodefile.py": 1, "md_cg/mdcg.py": 2,
                "md_cg/mcp_server.py": 2}, _USE)
_check("B02 引用总数 == 5（多一处少一处都红）", sum(_USE.values()) == 5, _USE)

print("")
print("== E 组：枚举完备性自证（_guard_kit 骨架①）==")


def _discover(texts):
    """枚举逻辑：返回「未走单点谓词」的 role 类型判据（各写一遍 isinstance）。"""
    bad = []
    for rel, src in texts.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            if not (isinstance(fn, ast.Name) and fn.id == "isinstance"):
                continue
            s = ast.unparse(n)
            # 只看**判据对象是 role** 的 isinstance（无关字段不得误伤）
            if "role" in s and "valid_role" not in s:
                bad.append((rel, s[:60]))
    return bad


_SAMPLES = [
    ("①各写一遍 isinstance（修前形态）",
     'def f(role):\n    return role is None or isinstance(role, str)\n',
     True, "synthetic/dup.py"),
    ("②走单点谓词（修后形态）",
     'def f(role):\n    return nodefile.valid_role(role)\n',
     False, "synthetic/single.py"),
    ("③无关字段的 isinstance 不得误伤",
     'def f(x):\n    return isinstance(x, int)\n', False, "synthetic/other.py"),
]
_ok_e, _det_e = _kit.assert_enumeration_complete(_discover, _SAMPLES)
_check("E01 ★枚举完备性自证：3 类形态喂同一条枚举逻辑，命中与否须全符预期",
       _ok_e, _det_e)

print("")
print("断言总数 %d（PASS %d / FAIL %d），FLOOR=%d" % (PASS + FAIL, PASS, FAIL, FLOOR))
if PASS + FAIL < FLOOR:
    FAILS.append("FLOOR")
    print("  FAIL 断言总数低于 FLOOR")
if FAILS:
    print("issue #418 结果：%d 失败" % len(FAILS))
    for _f in FAILS:
        print("   - " + _f)
else:
    print("issue #418 结果：全部通过")


# ---------------------------------------------------------------- 镜像树 / 回退
_MIRROR_DIRS = ("md_cg", "data", "scripts")
_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "jobs", "target",
                               "node_modules")


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="i418_mut_")
    for name in _MIRROR_DIRS:
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name), ignore=_SKIP)
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue418_role_type_gate"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.startswith("  FAIL ")]
    return pr.returncode, reds, out


#: 回退 = **本批全部改动**（三个文件）：写面闸摘除 + 两处引用退回各写 isinstance。
_REVERT = [
    ("md_cg/mcp_server.py",
     '        if not _nf418.valid_role(a.get("role")):',
     "        if False:  # 回退：#418 写面闸整段禁用（＝修复前形态）"),
    ("md_cg/mdcg.py",
     "    if role and not nodefile.valid_role(role):",
     "    if role and not isinstance(role, str):"),
    ("md_cg/mdcg.py",
     "    return nodefile.valid_role(r.get(\"role\"))",
     "    return r.get(\"role\") is None or isinstance(r.get(\"role\"), str)"),
]


def _revert_proof():
    print("!! 回退即绿自证（_guard_kit.assert_revert_reddens，实跑）")
    _ok, _det = _kit.assert_revert_reddens(_mirror_build, _REVERT, _run_in,
                                           # 实测值（非推演）：回退后写面闸与单点引用两条腿
                                           # 全红，且镜像里**重现了修前症状**（装载隔离告警 3 个坏节点）
                                           tuple(["A01", "A02", "A03", "A06", "B01", "B02"]), "?")
    print("  %s 红项=%s" % ("OK  " if _ok else "FAIL", _det.get("实际红项")))
    if not _ok:
        print("  不合格：" + str(_det)[:500])
    return 0 if _ok else 1


def main():
    bad = 0
    if "--mutate" in sys.argv:
        bad += _revert_proof()
    return 1 if (FAILS or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
