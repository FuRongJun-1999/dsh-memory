# -*- coding: utf-8 -*-
# 功能名：E 面接线边界登记表守卫（issue #408，「声称的面 > 实际覆盖的面」族）
# 生效条件：python -X utf8 -m md_cg.test_issue408_eface_registry [--mutate]；被测面=md_cg/autonomy_modes.py 的 E_FACE_ENTRIES / _render_e_face_boundary / e_gate.__doc__，以及全仓写·裁决入口的 AST 枚举面
# 子功能：A=登记表与 AST 全集的**双向**断言（wired 实调验证 / 登记却不存在即红 / 新增未登记即红）+ docstring 由表渲染；E=枚举完备性自证（_guard_kit 骨架①）；R=回退即绿自证（_guard_kit 骨架②）
# 执行：--mutate 时跑回退自证（实跑镜像树，不接受推演）
# 验证方式：全部 PASS 即通过；--mutate 下红项集合须与实测一致
# 不适用条件：不判「E 类归属该怎么定」（issue §五 明请维护者裁；本批只做**登记**，pending_decision 项的动作交维护者）；不判「接线后行为」（本批零行为变更：未改任何写盘路径）；docstring 改为由表渲染属**文档面变更**（同 render_discipline 先例），如实登记于此
"""issue #408 守卫：E 面接线边界清单必须是**单点真源**且**双向可核**。

病象（修前）：e_gate() 的边界清单是 docstring 里的**自由文本**，没有判据面 ⇒
issue #408 照它核账即发现 insight.verify / MdCGSecure.verify 两处**写 E 类字段
却不在清单里**（plan 档照旧写盘：importance 0.5→0.9 并置 protected=True）。
且全仓同族候选远不止这两处（AST 实测 27 处写/裁决入口）。

修法：清单收成模块级 E_FACE_ENTRIES（单点真源，disposition ∈ wired /
exempt_with_reason / pending_decision），docstring 由它渲染；本守卫用 AST 枚举
全仓写/裁决入口做**双向**全表断言 —— 单向会退化成免死金牌。
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

from . import autonomy_modes as A

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR = 7
PASS, FAIL = 0, 0
FAILS = []
_NAME_RE = ("verify", "recalc", "set_state", "stamp", "backfill", "reinforce",
            "mark", "weaken", "decontaminate", "apply")
_WRITE_CALLS = ("_write_node", "_stage(", "add(", "stamp(", "atomic_write")
_DISPOSITIONS = ("wired", "exempt_with_reason", "pending_decision")


def _check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:220])


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


def _entries():
    rows = []
    for rel, t in sorted(_SRC.items()):
        try:
            tree = ast.parse(t)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in _NAME_RE:
                continue
            seg = ast.get_source_segment(t, node) or ""
            rows.append((rel, node.name,
                         any(k in seg for k in _WRITE_CALLS),
                         "e_gate(" in seg))
    return rows


_ROWS = _entries()
_UNREGISTERED = sorted({r[1] for r in _ROWS if r[2] and not r[3]})
_ENTRY_TEXT = " ".join(e["entry"] for e in A.E_FACE_ENTRIES)

print("== A 组：登记表 vs AST 全集（双向）==")
_check("A01 E_FACE_ENTRIES 非空转且 disposition ∈ 三值闭集",
       len(A.E_FACE_ENTRIES) >= 10
       and all(e.get("disposition") in _DISPOSITIONS for e in A.E_FACE_ENTRIES),
       [(e.get("entry"), e.get("disposition")) for e in A.E_FACE_ENTRIES])
_check("A01 每条都有 entry + 非空 reason（>=20 字，防占位式登记）",
       all(e.get("entry") and isinstance(e.get("reason"), str)
           and len(e["reason"]) >= 20 for e in A.E_FACE_ENTRIES),
       [e.get("entry") for e in A.E_FACE_ENTRIES
        if not (e.get("entry") and len(str(e.get("reason") or "")) >= 20)])

_MISS = [fn for fn in _UNREGISTERED if fn not in _ENTRY_TEXT]
_check("A02 ★双向（一）：AST 枚举到的「写盘∧未接闸」入口全部已登记（新增未登记即红）",
       not _MISS, _MISS)

# ---- 幽灵判据（#408 收尾，2026-10-15 按 Lead 裁定放宽）------------------------
# 改前：`any(枚举到的函数名 in entry)` —— 枚举规则只覆盖「函数名 ∈ _NAME_RE ∧ 有写盘
# 调用」这一**窄面**，而登记表里存在语义上真实、却不落在该窄面内的条目（同一条目还
# 可能用「A 的 B」/「X / Y」这种带修饰的写法）⇒ 两条**误报**。
# 改后：条目的**标识符 token 至少一个能在 md_cg 源码里找到**，全找不到才是真幽灵。
# 关键前提：检索语料必须**剔除登记表自身的字面块**——否则条目文本自己就把 token 命中
# 成自证，幽灵检查退化成恒不报（这正是「判据自己证明自己」的形态）。
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _corpus_without_table():
    """md_cg 生产码拼接语料，**剔除 E_FACE_ENTRIES 字面块**。

    不剔的话：被查的 token 就写在语料里（表本身在 autonomy_modes.py），
    任意字符串都能「在源码里找到」——判据恒真、幽灵一条也报不出来。
    """
    parts = []
    for rel, t in sorted(_SRC.items()):
        if rel.endswith("autonomy_modes.py"):
            i = t.find("E_FACE_ENTRIES = (")
            if i >= 0:
                j = t.find(chr(10) + ")" + chr(10), i)
                t = t[:i] + (t[j + 3:] if j > 0 else "")
        parts.append(t)
    return chr(10).join(parts)


_CORPUS = _corpus_without_table()


def _ghost_entry(entry) -> bool:
    """条目的标识符 token（长度 ≥ 4，滤掉 add/and 这类噪声）**全部**找不到 ⇒ 幽灵。"""
    toks = [t for t in _IDENT_RE.findall(str(entry or "")) if len(t) >= 4]
    return not toks or not any(t in _CORPUS for t in toks)


_GHOST = [e["entry"] for e in A.E_FACE_ENTRIES if _ghost_entry(e["entry"])]
print("   [读数] A02(二) 语料长度=%d 幽灵=%s" % (len(_CORPUS), _GHOST))
_check("A02 ★双向（二）：登记表的每条都指向真实存在的入口（登记却不存在即红；"
       "判据=标识符 token 至少一个能在**剔除登记表字面块**的 md_cg 源码里找到)",
       not _GHOST, _GHOST)

_wired = [e["entry"] for e in A.E_FACE_ENTRIES if e["disposition"] == "wired"]
_ok_wired, _bad_wired = 0, []
for _e in _wired:
    _fn = _e.split(".")[-1]
    if any(r[1] == _fn and r[3] for r in _ROWS):
        _ok_wired += 1
    else:
        _bad_wired.append(_e)
_check("A03 ★wired 项全部经 AST 实测确已接 e_gate（%d/%d）" % (_ok_wired, len(_wired)),
       not _bad_wired, _bad_wired)

_doc = A.e_gate.__doc__ or ""
_check("A04 e_gate docstring 的边界段由 E_FACE_ENTRIES **渲染**（单一真源）",
       "E_FACE_ENTRIES 渲染" in _doc and "@@E_FACE_BOUNDARY@@" not in _doc,
       _doc[-160:])
_check("A04 渲染段含全部三条 disposition 分组标签",
       all(k in _doc for k in ("已接闸", "明确不接", "归属待裁")), _doc[-200:])

print("")
print("== E 组：枚举完备性自证（_guard_kit 骨架①）==")
import md_cg._guard_kit as _kit                                  # noqa: E402


def _discover(texts):
    bad = []
    for rel, src in texts.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in _NAME_RE:
                continue
            seg = ast.get_source_segment(src, node) or ""
            if any(k in seg for k in _WRITE_CALLS) and "e_gate(" not in seg:
                bad.append((rel, node.name))
    return bad


def _sample(fn, body):
    return "def %s(cg, x=None):\n    %s\n" % (fn, body)


_SAMPLES = [
    ("①写盘且未接闸（应命中）",
     _sample("verify", "return cg._write_node(1, 2, 3, 4)"), True, "synthetic/a.py"),
    ("②写盘且已接闸（不得误伤）",
     _sample("verify", "_dec = A.e_gate()\n    return cg._write_node(1, 2, 3, 4)"),
     False, "synthetic/b.py"),
    ("③不写盘（不是入口，不得误伤）",
     _sample("verify", "return x"), False, "synthetic/c.py"),
    ("④名字不属入口族（不得误伤）",
     _sample("helper", "return cg._write_node(1, 2, 3, 4)"), False, "synthetic/d.py"),
]
_ok_e, _det_e = _kit.assert_enumeration_complete(_discover, _SAMPLES)
_check("E01 ★枚举完备性自证：4 类形态喂同一条枚举逻辑，命中与否须全符预期",
       _ok_e, _det_e)

print("")
print("断言总数 %d（PASS %d / FAIL %d），FLOOR=%d" % (PASS + FAIL, PASS, FAIL, FLOOR))
if PASS + FAIL < FLOOR:
    FAILS.append("FLOOR")
    print("  FAIL 断言总数低于 FLOOR")
if FAILS:
    print("issue #408 结果：%d 失败" % len(FAILS))
    for _f in FAILS:
        print("   - " + _f)
else:
    print("issue #408 结果：全部通过")


_MIRROR_DIRS = ("md_cg", "data", "scripts")
_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "jobs", "target",
                               "node_modules")


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="i408_mut_")
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
                         "md_cg.test_issue408_eface_registry"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.startswith("  FAIL ")]
    return pr.returncode, reds, out


#: 回退 = **本批全部改动**：把两处 issue 点名的 pending 条目摘掉（＝修复前
#: 「清单里没有 verify 面」的形态）。
#:
#: **实测（不是推演）**：回退后 rc=1、红项**两条**——
#:   · A02（一）点名 ['verify']（清单里没有 verify 面 ＝ 修复前形态）；
#:   · A02（二）点名 ['____removed_by_revert', …]（放宽后的幽灵判据把改名的条目判成
#:     真幽灵 —— 这一条同时证明「(二) 的放宽没有把判据放空」）。
#: 两条都归前缀 "A02"，故 assert_revert_reddens 的 expect_prefixes=("A02",) 成立；
#: 前一位假设的「仅 (一) 转红」与实测不符，已按实测改正（本会话常规：期望值＝实测值）。
_REVERT = [
    ("md_cg/autonomy_modes.py",
     '    {"entry": "insight.verify", "disposition": "pending_decision",',
     '    {"entry": "____removed_by_revert", "disposition": "pending_decision",'),
    ("md_cg/autonomy_modes.py",
     '    {"entry": "MdCGSecure.verify", "disposition": "pending_decision",',
     '    {"entry": "____removed_by_revert2", "disposition": "pending_decision",'),
]


def _revert_proof():
    print("!! 回退即绿自证（_guard_kit.assert_revert_reddens，实跑）")
    _ok, _det = _kit.assert_revert_reddens(_mirror_build, _REVERT, _run_in,
                                           tuple(["A02"]), "?")
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
