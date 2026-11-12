# -*- coding: utf-8 -*-
# 功能名：工具面 identity_* 写侧密级实参透传对齐守卫（issue #467，族「实参表漏传」）
# 生效条件：python -u -X utf8 -m md_cg.test_issue467_identity_sensitivity_parity [--mutate]；被测面=md_cg/mcp_server.py 的 IDENTITY_SENSITIVITY_PARITY 单点真源表 + _identity_call 的全部 cg.identity_* 调用点 + md_cg/identity.py 的目标函数签名
# 子功能：A=单点真源表四态闭集 + 正向（调用点实参 ⊇ 表要求；新增未登记即红）+ 反向（表内形参必须在目标签名里真实存在；登记却无对应形参即红）+ 过度收紧腿 + 两条非本族态各自的结构判据；E=枚举完备性自证（_guard_kit 骨架①）；R=回退即绿自证（_guard_kit 骨架②）
# 执行：--mutate 时跑双向变异（M1 回退修复＝正向腿红；M2 过度收紧＝只有该腿红），再跑 _guard_kit 的回退即绿自证（都是实跑，不接受推演）
# 验证方式：全部 PASS 即通过（断言总数 ≥ FLOOR）；--mutate 下每条变异的红项集合须与**实测**一致
# 不适用条件：不判「库层该不该让 anchor/trait/contract 也接受 sensitivity」（那是维护者裁定项：三类写入均不接受该形参 ⇒ 调用方无法声明密级、只能落缺省 DEFAULT_SENSITIVITY；可能是 evidence.py 注释记录的同一条链，但定性为**库层缺能力**而非写侧漏传）；不判 identity 的业务语义；不覆盖 links/self_state 之外的第三方同名物
"""issue #467 守卫：工具面 identity_* 写侧的密级实参透传必须由**单点真源**对齐且**双向可核**。

病象（修前）：cg(op=identity, action=observe) 的实参表漏了 sensitivity —— 而 identity.observe
**一直有**该形参。漏传不报错、回执逐字相同，调用方声明的密级被静默丢弃、只能落
DEFAULT_SENSITIVITY=internal。与 #397/#414 同族（实参表漏传）。

★**为什么反向断言必须是 AST 签名比对**（不是「我们选了 AST」，而是这条别的路走不通）：
mdcos 的四个 wrapper 都是 **kw 透传形态 ——
    def identity_anchor(self, subject_id, text, **kw): return identity.set_anchor(self, subject_id, text, **kw)
⇒ 给目标**不存在**该形参的写侧补一个 sensitivity=，**既不会报错、也不会生效**：它经 **kw
直达目标函数，于是变成 identity.set_anchor(..., sensitivity=...) ⇒ TypeError: unexpected
keyword argument —— **运行期才炸**，且只在那条路径被走到时炸。
⇒ 所以「登记了却无对应形参」这类错误：不会被 import 发现、不会被类型检查发现、也不会被
反射式自检发现（**kw 让签名检查通过）。**唯一能在静态面拦住它的判据，是把表里登记的形参名
与目标函数的 AST 签名逐名比对。** 这正是 A04 那一条腿存在的理由。

维护者若裁定「库层应让 anchor/trait/contract 也能声明密级」：把表里对应条目从
n/a-no-param 移成 leaked 即可 —— A04 会**立刻**要求先在 identity.py 给那些函数加形参
（登记了却不存在的形参即红），判据自己把顺序推成「先加能力、再补透传」。
"""
from __future__ import annotations

import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

# 沙箱必须在**任何** md_cg 子模块 import 之前求值（crypto.MASTER_FILE 在导入期落点）。
_SB = tempfile.mkdtemp(prefix="i467_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SB
os.environ["MDCG_ROOT"] = os.path.join(_SB, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_POLICY_FILE", None)

from . import mcp_server as M                                # noqa: E402
import md_cg._guard_kit as _kit                              # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR = 9
PASS, FAIL = 0, 0
FAILS = []

_DISPOSITIONS = ("leaked", "n/a-no-param", "excluded-nonfamily", "import-unused")
#: 只读面（无写侧密级透传问题）——正向全枚举的白名单，**每条都要能说出为什么**。
_READ_ONLY_CALLEES = ("identity_profile", "identity_positions", "identity_history",
                       "identity_catalog", "identity_contract_record",
                       "identity_contracts")


def _check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:240])


def _read(rel):
    with io.open(os.path.join(_REPO, rel), encoding="utf-8", newline="") as f:
        return f.read()


_TBL = M.IDENTITY_SENSITIVITY_PARITY


def _call_sites(src_text, *, func_names=None):
    """AST 抽 cg.identity_*(...) 调用点的**显式关键字实参名**。

    返回 {callee: (显式关键字名 frozenset, 裸 splat 数)}——裸 splat（**kw）会把真源表
    绕开，故单独计数（不可枚举＝判红，不能静默放过）。
    """
    out = {}
    for node in ast.walk(ast.parse(src_text)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.value.id == "cg" and f.attr.startswith("identity_")):
            continue
        if func_names is not None and f.attr not in func_names:
            continue
        kws = frozenset(k.arg for k in node.keywords if k.arg)
        splat = sum(1 for k in node.keywords if k.arg is None)
        prev = out.get(f.attr, (frozenset(), 0))
        out[f.attr] = (prev[0] | kws, prev[1] + splat)
    return out


_MCP_SRC = _read("md_cg/mcp_server.py")
_ID_SRC = _read("md_cg/identity.py")
_CALLS = _call_sites(_MCP_SRC)
_TOOLFACE = [e for e in _TBL if e.get("callee")]
_LEAKED = tuple(sorted(e["callee"] for e in _TOOLFACE
                       if e["disposition"] == "leaked"))
#: 正向判据**要求显式传 sensitivity**的调用点集合（单点）。
#: 正确值 ＝ 表里 disposition=="leaked" 的 callee 集合；A06 断言它**恰为**该集合
#: —— 把要求扩到 n/a-no-param 的站点，就是「把合法缺省当漏传」的过度收紧。
_REQUIRE_AT = ("identity_observe",)


def _sig_params(src_text, fname):
    """identity.py 里 fname 的形参名集合（含 kwonly；*args/**kwargs 不计）。"""
    for node in ast.walk(ast.parse(src_text)):
        if isinstance(node, ast.FunctionDef) and node.name == fname:
            a = node.args
            return set(x.arg for x in list(a.posonlyargs) + list(a.args)
                       + list(a.kwonlyargs))
    return set()


print("== A 组：单点真源表 · 双向断言 ==")
_check("A01 表非空转且 disposition ∈ 四态闭集 + 每条都有非空理由（>=20 字）",
       len(_TBL) >= 5
       and all(e.get("disposition") in _DISPOSITIONS for e in _TBL)
       and all(isinstance(e.get("reason"), str) and len(e["reason"]) >= 20
               for e in _TBL),
       [(e.get("disposition"), e.get("callee") or e.get("site")) for e in _TBL])

_unregistered = sorted(set(_CALLS) - {e["callee"] for e in _TOOLFACE}
                       - set(_READ_ONLY_CALLEES))
_check("A02 ★正向（全枚举）：AST 扫到的每个 cg.identity_* 调用点，或在真源表内、"
       "或在只读白名单内（新增写侧未登记即红）",
       not _unregistered, _unregistered)

_missing = []
for _e in _TOOLFACE:
    if _e["disposition"] != "leaked":
        continue
    _kws, _splat = _CALLS.get(_e["callee"], (frozenset(), 0))
    _lack = [p for p in _e["params"] if p not in _kws]
    if _lack or _splat:
        _missing.append((_e["callee"], _lack, _splat))
print("   [读数] A03 调用点实参=%s" % {k: sorted(v[0]) for k, v in _CALLS.items()})
_check("A03 ★正向（逐条）：leaked 条目的调用点必须显式传全部 params（且不得裸 splat"
       "绕开真源表）",
       not _missing, _missing)

_ghost = []
for _e in _TOOLFACE:
    _fn = (_e["target"] or "").split(".")[-1]
    _sig = _sig_params(_ID_SRC, _fn)
    _bad = [p for p in _e["params"] if p not in _sig]
    if _bad or not _sig:
        _ghost.append((_e["callee"], _e["target"], _bad, bool(_sig)))
_check("A04 ★反向：表里登记的形参名必须在 identity.py 对应函数签名里**真实存在**"
       "（登记了却无对应形参即红 —— 防「给不存在的形参补透传」）",
       not _ghost, _ghost)

_nocall = sorted(e["callee"] for e in _TOOLFACE if e["callee"] not in _CALLS)
_check("A05 ★反向（另一向）：表里登记的工具面条目必须真有调用点（登记了却没有即红）",
       not _nocall, _nocall)

_widened = sorted(set(_REQUIRE_AT) - set(_LEAKED))
_check("A06 ★过度收紧腿：要求显式传 sensitivity 的集合**恰为** leaked 集"
       "（把 n/a-no-param 的合法缺省也要求传＝误伤）",
       set(_REQUIRE_AT) == set(_LEAKED),
       {"要求集": list(_REQUIRE_AT), "leaked": list(_LEAKED), "多出来的": _widened})

_links = _read("md_cg/links.py")
_links_observe = _sig_params(_links, "observe")
_check("A07 excluded-nonfamily 腿：links.py 的 observe 确实存在且**不是** "
       "identity.observe（签名含 peer、不含 subject_id）——族枚举按同构判、不按名字收",
       "peer" in _links_observe and "subject_id" not in _links_observe,
       sorted(_links_observe))

_ss = _read("md_cg/self_state.py")
_ss_calls = re.findall(r"identity_(?:observe|anchor|trait|contract)\s*\(", _ss)
_check("A08 import-unused 腿：self_state.py 只导入 identity 模块、无 identity_* "
       "调用点（⇒ 不适用；后来者不要补不需要的透传）",
       ("from . import identity" in _ss) and not _ss_calls, _ss_calls[:4])

print("")
print("== E 组：枚举完备性自证（_guard_kit 骨架①）==")


def _discover(texts):
    """本守卫自己的那条枚举逻辑：合成源码 → 违反「leaked 必须显式传」的调用点。"""
    hits = []
    for rel, src in texts.items():
        for callee, (kws, splat) in _call_sites(src).items():
            if callee not in _LEAKED:
                continue
            if splat or any(p not in kws for p in ("sensitivity",)):
                hits.append((rel, callee))
    return hits


_SRC_TMPL = ("def _identity_call(cg, a):\n"
             "    return cg.%s(\n"
             "        sid, text,\n"
             "%s"
             "    )\n")
_SAMPLES = [
    ("①写侧·显式传 sensitivity（应不命中）",
     _SRC_TMPL % ("identity_observe", "        sensitivity=a.get(\"sensitivity\"),\n"),
     False, "syn/a.py"),
    ("②写侧·漏传 sensitivity（应命中）",
     _SRC_TMPL % ("identity_observe", "        override=True,\n"),
     True, "syn/b.py"),
    ("③写侧·裸 splat 不可枚举（应命中：绕开真源表）",
     _SRC_TMPL % ("identity_observe", "        **a,\n"),
     True, "syn/c.py"),
    ("④非 leaked 写侧缺 sensitivity（应不命中：合法缺省，过度收紧方向）",
     _SRC_TMPL % ("identity_anchor", "        override=True,\n"),
     False, "syn/d.py"),
    ("⑤只读调用（应不命中）",
     "def f(cg):\n    return cg.identity_profile(sid)\n",
     False, "syn/e.py"),
]
_ok_e, _det_e = _kit.assert_enumeration_complete(_discover, _SAMPLES)
_check("E01 ★枚举完备性自证：5 类形态喂同一条枚举逻辑，命中与否须全符预期",
       _ok_e, _det_e)

print("")
print("断言总数 %d（PASS %d / FAIL %d），FLOOR=%d" % (PASS + FAIL, PASS, FAIL, FLOOR))
if PASS + FAIL < FLOOR:
    FAILS.append("FLOOR")
    print("  FAIL 断言总数低于 FLOOR")
if FAILS:
    print("issue #467 结果：%d 失败" % len(FAILS))
    for _f in FAILS:
        print("   - " + _f)
else:
    print("issue #467 结果：全部通过")

# ---------------------------------------------------------------- 变异/回退
_MIRROR_DIRS = ("md_cg", "data", "scripts")
_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "jobs", "target",
                               "node_modules")


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="i467_mut_")
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
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.test_issue467_identity_sensitivity_parity"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.startswith("  FAIL ")]
    return pr.returncode, reds, out


#: 回退 = **该条修复的全部改动**：把 sensitivity 透传那一行摘掉（＝修复前的实参表）。
_REVERT = [("md_cg/mcp_server.py",
            '            sensitivity=a.get("sensitivity"),' + chr(10)
            + '            override=bool(a.get("override")))' + chr(10)
            + '    if act == "trait":',
            '            override=bool(a.get("override")))' + chr(10)
            + '    if act == "trait":')]
#: 双向变异：正向腿＝回退修复；反向腿＝**过度收紧**（把要求扩到全部写侧站点）。
_MUTATIONS = [
    ("M1 正向腿：摘掉 sensitivity 透传（＝修复前形态）",
     [("md_cg/mcp_server.py",
       '            sensitivity=a.get("sensitivity"),' + chr(10)
       + '            override=bool(a.get("override")))' + chr(10)
       + '    if act == "trait":',
       '            override=bool(a.get("override")))' + chr(10)
       + '    if act == "trait":')],
     ("A03",)),
    # 反向腿＝**过度收紧**：要求集从「leaked 集」扩到「全部写侧站点」——
    # 这正是单点化后最常见的误伤（把 n/a-no-param 的合法缺省当漏传）。
    ("M2 反向腿/过度收紧：把要求集扩到全部写侧站点（合法缺省被当漏传）",
     [("md_cg/test_issue467_identity_sensitivity_parity.py",
       '#: —— 把要求扩到 n/a-no-param 的站点，就是「把合法缺省当漏传」的过度收紧。' + chr(10)
       + '_REQUIRE_AT = ("identity_observe",)',
       '#: —— 把要求扩到 n/a-no-param 的站点，就是「把合法缺省当漏传」的过度收紧。' + chr(10)
       + '_REQUIRE_AT = ("identity_observe", "identity_anchor", "identity_trait",'
       + ' "identity_contract")')],
     ("A06",)),
]


def _apply(tree, edits):
    for rel, old, new in edits:
        p = os.path.join(tree, rel)
        with io.open(p, encoding="utf-8", newline="") as f:
            t = f.read()
        eol = "\r\n" if "\r\n" in t else "\n"
        o = old.replace("\n", eol)
        if t.count(o) != 1:
            return "锚点命中 %d 次：%s" % (t.count(o), rel)
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            f.write(t.replace(o, new.replace("\n", eol), 1))
    return None


def _mutate():
    bad = 0
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("!! 镜像基线：rc=%d 红项=%d（须 rc=0/0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
            bad += 1
        for desc, edits, exp in _MUTATIONS:
            miss = _apply(tree, edits)
            if miss:
                print("  ANCHOR-MISS %s —— %s" % (desc, miss))
                bad += 1
                continue
            rc2, reds2, _o2 = _run_in(tree)
            _apply(tree, [(r, n, o) for r, o, n in edits])
            hit = sorted({e for r in reds2 for e in exp if r.startswith(e + " ")})
            if rc2 != 0 and hit == sorted(exp) and len(reds2) == len(exp):
                print("  OK   %s  红项=%s" % (desc, hit))
            else:
                print("  MISMATCH %s  实际红项=%s 期望=%s" % (desc, reds2, exp))
                bad += 1
    finally:
        shutil.rmtree(tree, ignore_errors=True)
    return bad


def main():
    bad = 0
    if "--mutate" in sys.argv:
        bad += _mutate()
        print("!! 回退即绿自证（_guard_kit.assert_revert_reddens，实跑）")
        _ok, _det = _kit.assert_revert_reddens(_mirror_build, _REVERT, _run_in,
                                               ("A03",), "md_cg/mcp_server.py")
        print("  %s 红项=%s" % ("OK  " if _ok else "FAIL", _det.get("实际红项")))
        if not _ok:
            print("  不合格：" + str(_det)[:400])
            bad += 1
    return 1 if (FAILS or bad) else 0


if __name__ == "__main__":
    sys.exit(main())