# -*- coding: utf-8 -*-
# 功能名：孪生编译器不得丢失「术曰」块内赋值——双链字节码等价性回归（issue #326-②）
# 生效条件：python -X utf8 -m md_cg.test_issue326_twin_parser_parity [--mutate]；被测面＝md_cg/whitebox_kb/wisdom/core/parser.py 的 IDENTIFIER 分支 lookahead（对照 compiler/parser.py 的同款修复）
# 子功能：A 组＝报告源码的双链等价（指令数 14、初始化赋值在、无「未编译语句类型」告警）；K 组＝非恒真对照（多词短语/裸标识符的**合并路径**不得被 lookahead 劫持、条件内赋值、混合样本、等价不是「两边都失败」）；E 组＝源码面（两链同款 lookahead）
# 执行：--mutate 时在镜像树里逐条把 lookahead 改回缺陷形态 / 过度收紧（无条件走 assign-or-call），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：不判「多词短语合并在编译期仍报未编译语句类型」这一**既有**限制（两链一致、非本批）；不覆盖名实校验/代码生成面；不判 pbc 序列化形态
"""issue #326-② 守卫：孪生副本必须与 compiler/parser.py 产出**同一字节码**。

病象（修前）：孪生 `core/parser.py` 的 IDENTIFIER 分支**无条件**走 `_merge_identifiers()`，
从不探视其后是否紧跟 `=` 或 `(`；而 `compiler/parser.py` 已于 2026-09-14 修复并定性为
「静默错值，比崩溃更危险」。⇒ 同一中文源码在两条链上产出不同字节码（实测 14 vs 12，
孪生缺初始化赋值，且**不报错**——只降级为一条 warning）。该修复此前**无任何测试守护**，
这正是孪生漏回移长期未被发现的原因；本守卫即为该守护。

「守卫必须能在变异态下跑完」（task-8/④ 的教训）：本守卫的取数与解析全部经 `_try()`
包装把异常折成可命名的返回值形态，绝不让变异态在夹具处崩栈中断（红得不可归因）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss326b_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from compiler.compiler import compile_source as _ref_cs             # noqa: E402
from md_cg.whitebox_kb.wisdom.core.compiler import compile_source as _twin_cs  # noqa: E402

_NL = chr(10)


def _try(fn):
    """调 fn：正常返回 ("", 结果)；抛异常（含 BaseException）返回 (类型名, None)。"""
    try:
        return "", fn()
    except BaseException as exc:                 # noqa: BLE001
        return type(exc).__name__, None


def _norm(code):
    """字节码归一成可比形态：[(op 名, arg 的确定性 JSON), ...]；None → []。"""
    out = []
    for item in (code or []):
        op, arg = item
        try:
            a = json.dumps(arg, ensure_ascii=False, default=str, sort_keys=True)
        except (TypeError, ValueError):
            a = repr(arg)
        out.append((getattr(op, "name", str(op)), a))
    return out


def _run(cs, src):
    """编译一段源码：返回 (异常名, code, result)——异常折成可命名形态，绝不崩栈。"""
    t, pair = _try(lambda: cs(src))
    if t:
        return t, None, {}
    code, res = pair
    return "", code, res


#: 报告逐字给的复现源码（issue #326-②）。
_SRC_REPORT = ("术曰：" + _NL + "1。计数 = 0；" + _NL
               + "2。当 计数 小于 3 执行 计数 = 计数 + 1；" + _NL
               + "3。止。" + _NL)

#: 等价性语料（每条都在两链上编译并逐条比对）。
_CORPUS = {
    "report": _SRC_REPORT,
    "assign": "术曰：" + _NL + "1。计数 = 0；" + _NL + "2。止。" + _NL,
    "multiword": "术曰：" + _NL + "1。甲 乙 丙；" + _NL + "2。止。" + _NL,
    "bare_ident": "术曰：" + _NL + "1。甲；" + _NL + "2。止。" + _NL,
    "assign_in_if": ("术曰：" + _NL + "1。若 1 小于 2 则 计数 = 1；" + _NL
                     + "2。止。" + _NL),
    "mixed": ("术曰：" + _NL + "1。甲 = 1；" + _NL + "2。当 甲 小于 3 执行 甲 = 甲 + 1；"
              + _NL + "3。乙 丙 丁；" + _NL + "4。止。" + _NL),
}

print("== A 组：#326-② 正题——孪生链必须与 compiler/ 产出同一字节码 ==")
_te, _tcode, _tres = _run(_twin_cs, _SRC_REPORT)
_re, _rcode, _rres = _run(_ref_cs, _SRC_REPORT)
_tn, _rn = _norm(_tcode), _norm(_rcode)
_check("A01 孪生链编译成功且无异常（不引入新错误）",
       _te == "" and _tres.get("ok") is True and _tres.get("errors") == [],
       (_te, _tres.get("errors")))
_check("A02 报告读数：孪生链指令数 = 14（修前 12）", len(_tn) == 14, len(_tn))
_check("A03 报告读数：对照链接口数 = 14", len(_rn) == 14, len(_rn))
_check("A04 初始化赋值已回移（ENTER_SHUYUE 之后紧跟 PUSH_CONST + STORE_NAME）",
       [n for n, _ in _tn[:3]] == ["ENTER_SHUYUE", "PUSH_CONST", "STORE_NAME"],
       [n for n, _ in _tn[:3]])
_check("A05 修前那条告警消失（warnings 不含「未编译语句类型: IDENTIFIER」）",
       not any("未编译语句类型" in str(w) for w in (_tres.get("warnings") or [])),
       _tres.get("warnings"))
_check("A06 双链字节码**逐条等价**（op 名 + 归一化 arg）", _tn == _rn,
       [n for n, _ in _tn][:6] + ["..."] + [n for n, _ in _rn][:6])
_check("A07 双链 warnings/errors 等值",
       (_tres.get("warnings") or []) == (_rres.get("warnings") or [])
       and (_tres.get("errors") or []) == (_rres.get("errors") or []),
       (_tres.get("warnings"), _rres.get("warnings")))

print("== K 组：非恒真对照（lookahead 不得劫持合并路径） ==")
_bad = []
_n = 0
for _k, _src in sorted(_CORPUS.items()):
    _n += 1
    _a, _ac, _ares = _run(_twin_cs, _src)
    _b, _bc, _bres = _run(_ref_cs, _src)
    if _a == "" and _b == "" and _norm(_ac) == _norm(_bc):
        continue
    _bad.append((_k, _a, _b, len(_norm(_ac)), len(_norm(_bc))))
_check("K01 六条语料全部双链等价（%d/%d）" % (_n - len(_bad), _n), not _bad, _bad)
_mw_e, _mw_c, _mw_res = _run(_twin_cs, _CORPUS["multiword"])
_bare_e, _bare_c, _ = _run(_twin_cs, _CORPUS["bare_ident"])
_check("K02 多词短语语句仍走**合并**路径（不得被 lookahead 劫持成 assign/call）"
       "——与对照链逐条相同且仍是「未编译语句类型」既有形态",
       _mw_e == "" and _norm(_mw_c) == _norm(_run(_ref_cs, _CORPUS["multiword"])[1])
       and any("IDENTIFIER" in str(w) for w in (_mw_res.get("warnings") or [])),
       (_mw_e, _mw_res.get("warnings")))
_check("K03 裸标识符语句同样保持既有形态（不回退也不冒进）",
       _bare_e == "" and _norm(_bare_c) == _norm(_run(_ref_cs, _CORPUS["bare_ident"])[1]),
       _bare_e)
_assign_e, _assign_c, _ = _run(_twin_cs, _CORPUS["assign"])
_check("K04 赋值路径确实生效（孪生链含 STORE_NAME 且与对照链相同）",
       _assign_e == "" and any(n == "STORE_NAME" for n, _ in _norm(_assign_c))
       and _norm(_assign_c) == _norm(_run(_ref_cs, _CORPUS["assign"])[1]),
       [n for n, _ in _norm(_assign_c)])
_if_e, _if_c, _ = _run(_twin_cs, _CORPUS["assign_in_if"])
_check("K05 条件内赋值也生效（分支语句不受本次回移影响）",
       _if_e == "" and any(n == "STORE_NAME" for n, _ in _norm(_if_c))
       and _norm(_if_c) == _norm(_run(_ref_cs, _CORPUS["assign_in_if"])[1]),
       [n for n, _ in _norm(_if_c)])
_check("K06 等价判据不是「两边都失败」（对照链 ok 且指令非空）",
       _rres.get("ok") is True and len(_rn) > 0 and len(_tn) > 0,
       (_rres.get("ok"), len(_rn), len(_tn)))

print("== E 组：源码面（两链同款 lookahead） ==")


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


_TWIN = "md_cg/whitebox_kb/wisdom/core/parser.py"
_REF = "compiler/parser.py"
_LOOK = "_nxt.type in (TokenType.EQUALS,"
_check("E01 孪生链 IDENTIFIER 分支已带 lookahead（与对照链同款形态）",
       _LOOK in _src(_TWIN), "缺 lookahead")
_check("E02 对照链同款 lookahead 仍在（两链同形，防单边回退）",
       _LOOK in _src(_REF), "对照链缺 lookahead")
_check("E03 孪生链仍保留合并腿（lookahead 未把 _merge_identifiers 顶掉）",
       "_parse_assign_or_call()" in _src(_TWIN)
       and "_merge_identifiers()" in _src(_TWIN), "")
_check("E04 孪生链 _peek_next 仍在（lookahead 的依赖件）",
       "def _peek_next" in _src(_TWIN), "")

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #326-② 结果：%d 失败" % len(FAILS))
else:
    print("issue #326-② 结果：全部通过")

# ---------------------------------------------------------------- 定点变异表
# 锚点跨行用 chr(10) 拼接；_apply_text 按目标文件**实际行尾**折算（孪生 parser 为 LF）。
_LOOKAHEAD = chr(10).join([
    "            _nxt = self._peek_next()",
    "            if _nxt is not None and _nxt.type in (TokenType.EQUALS,",
    "                                                  TokenType.LPAREN):",
    "                return self._parse_assign_or_call()",
    "            merged = self._merge_identifiers()",
])
_MERGE_ONLY = "            merged = self._merge_identifiers()"
_ALWAYS_ASC = chr(10).join([
    "            _nxt = self._peek_next()",
    "            if _nxt is not None:",
    "                return self._parse_assign_or_call()",
    "            merged = self._merge_identifiers()",
])

_MUTATIONS = (
    # M1 回缺陷（孪生链原先无条件合并）⇒ 赋值腿再次丢失：指令数 12、初始化缺失、
    # 告警重现、双链等价破裂；含赋值的语料（report/assign/assign_in_if/mixed）随之转红。
    # E01（源码面 lookahead 消失）同步转红——回缺陷时「源码面」与「行为面」双证都亮。
    # 恒绿项如实说明：K02/K03（纯合并语料）两态相同；**K05 实测不敏感**——条件内赋值
    # 不经本 IDENTIFIER 分支的 lookahead，故本变异不改变它（不是漏测，是该腿与本变异无关）。
    ("M1 回缺陷：孪生链无条件合并（丢块内赋值）",
     "md_cg/whitebox_kb/wisdom/core/parser.py",
     ((_LOOKAHEAD, _MERGE_ONLY),),
     ("A02", "A04", "A05", "A06", "A07", "E01", "K01", "K04")),
    # M2 过度收紧（下一个 token 只要存在就走 assign-or-call）⇒ **合并路径被劫持**：
    # 多词短语语句不再与对照链等价（这正是 K 组守的方向），E01 源码面同步转红。
    # 恒绿项如实说明：K03（裸标识符「甲；」）实测不敏感——该形态下 assign-or-call 与合并
    # 产出同一字节码；K04/K05（含赋值的语料）两态皆走 assign ⇒ 恒绿（如实）。
    ("M2 过度收紧：无条件走 assign-or-call（劫持合并路径）",
     "md_cg/whitebox_kb/wisdom/core/parser.py",
     ((_LOOKAHEAD, _ALWAYS_ASC),),
     ("E01", "K01", "K02")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss326b_mut_")
    for name in ("md_cg", "scripts", "compiler"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _apply_text(text, rel, pairs):
    """按目标文件实际行尾折算锚点后逐条替换；任一锚点命中数 != 1 返回 (None, 原因)。"""
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT",
              "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue326_twin_parser_parity"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把 lookahead 改回缺陷/过度收紧形态，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-25:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:12]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
