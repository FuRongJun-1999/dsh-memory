# -*- coding: utf-8 -*-
# 功能名：模块内 SKIP 不得冒充 PASS（issue #284，量具失效/CI 假绿）
# 生效条件：python -X utf8 -m md_cg.test_issue284_skip_not_pass [--mutate]；被测面＝scripts/run_tests.py 的模块内 SKIP 识别与汇总计数
# 子功能：A 组＝复现（缺依赖 ⇒ 模块内 SKIP+return 0 曾被记 PASS；真件面 test_logref 端到端）+ 判据升级（带 canonical SKIP 行的模块**不得出现在 PASS 列表**）；K 组＝双向对照（过度收紧：正文里出现「SKIP」字样不得误判；过度放宽：rc!=0 的 SKIP 行不得掩盖真失败）；E 组＝结构化判据与汇总可见性在位
# 执行：--mutate 时在镜像树里把 SKIP 分类改回 rc==0（回缺陷）／把行首锚去掉（过度收紧）／不看 rc（过度放宽），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：**不裁定「CI 该装 zstandard 还是缺依赖即 FAIL」**——本守卫只证「模块内 SKIP 不再冒充 PASS」，装不装依赖都不改变该结论；不判那两条守卫自身的红（本机真跑 rc=1 属既知，见 #284 正文与 MDCG_INGEST_ROOT 白名单面）；不判 stg/rust 面
"""issue #284 守卫：CI 假绿的**必要机制**有两个，本守卫各钉一条。

① `run_tests.py` 的 PASS 判据修前只有 `rc == 0`，而守卫在缺依赖时「模块内打印 SKIP +
   `return 0`」⇒ 汇总记 PASS；② `:368` 只在 `not ok` 时打印输出尾部 ⇒ 那行 SKIP **永不进
   CI 日志**。故读者看到的是裸 `PASS md_cg.test_logref`。

修法（本守卫验的面）：模块内 SKIP 变成**结构化可判**——解析**行首** canonical SKIP 行，
命中且 `rc==0` ⇒ 归类 SKIP（带原因、**不计入通过数**、汇总单列）；`rc!=0` 一律真失败。
这与本仓自己写下的口径一致（`docs/eval/优化第三批_…_v1.0.md:530`「SKIP 一律配『计入通过数 0』
且永不出 [PASS]」）⇒ 补齐既有口径的未覆盖面。
"""
from __future__ import annotations

import io
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


#: 合成模块：① SKIP+rc0（**假绿形态**）② SKIP+rc1（真失败）③ 纯通过 ④ 纯失败
#: ⑤ 行内含「SKIP」字样但**非行首**（过度收紧方向的对照）。
_PROBES = {
    "md_cg/test_zz_iss284_skip0.py": (
        "import sys" + chr(10) +
        "print(\"SKIP  md_cg.test_zz_iss284_skip0：缺依赖 zstandard（合成探针）\")" + chr(10) +
        "sys.exit(0)" + chr(10)),
    "md_cg/test_zz_iss284_skip1.py": (
        "import sys" + chr(10) +
        "print(\"SKIP  缺依赖 zstandard（合成探针，但下面 rc!=0）\")" + chr(10) +
        "sys.exit(1)" + chr(10)),
    "md_cg/test_zz_iss284_pass.py": (
        "import sys" + chr(10) +
        "print(\"结果：全部通过\")" + chr(10) +
        "sys.exit(0)" + chr(10)),
    "md_cg/test_zz_iss284_fail.py": (
        "import sys" + chr(10) +
        "print(\"结果：1 失败\")" + chr(10) +
        "sys.exit(1)" + chr(10)),
    "md_cg/test_zz_iss284_midline.py": (
        "import sys" + chr(10) +
        "print(\"已检查 0 项 SKIP 登记（**非行首**，不得被当成模块内跳过）\")" + chr(10) +
        "print(\"结果：全部通过\")" + chr(10) +
        "sys.exit(0)" + chr(10)),
}


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss284_mut_")
    for name in ("md_cg", "scripts"):
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
    for rel, body in _PROBES.items():
        with io.open(os.path.join(dst, rel), "w", encoding="utf-8") as f:
            f.write(body)
    return dst


def _run_tests(tree, k, extra_env=None, timeout=1800):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for kk in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_INGEST_ROOT"):
        env.pop(kk, None)
    env.update(extra_env or {})
    pr = subprocess.run([sys.executable, "-X", "utf8", "scripts/run_tests.py",
                         "-k", k, "--jobs", "1"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", cwd=tree, env=env,
                        timeout=timeout)
    return pr.returncode, (pr.stdout or "") + (pr.stderr or "")


def _lines(out, prefix):
    return [ln.strip() for ln in out.splitlines() if ln.strip().startswith(prefix)]


_TREE = _mirror_build()
print("== A 组：#284 复现与判据升级（合成探针做 A/B） ==")
_rc, _out = _run_tests(_TREE, "iss284")
_pass_lines = _lines(_out, "PASS ")
_skip_lines = _lines(_out, "SKIP ")
_fail_lines = _lines(_out, "FAIL ")
_check("A01 ★：SKIP+rc0 的模块**不得出现在 PASS 列表**（修前它被记 PASS）",
       not any("skip0" in l for l in _pass_lines), _pass_lines)
_check("A02 ★：SKIP+rc0 的模块以 `SKIP  <名>  （原因）` 出现（**带原因**）",
       any("skip0" in l and "缺依赖 zstandard" in l for l in _skip_lines),
       _skip_lines)
_check("A03 真失败不被掩盖：SKIP+rc1 的模块判 FAIL（而非 SKIP）",
       any("skip1" in l for l in _fail_lines)
       and not any("skip1" in l for l in _skip_lines),
       (_fail_lines, _skip_lines))
_check("A04 ★不可见等于没修：汇总行带跳过计数与「模块内跳过 N 条」",
       any(("模块内跳过" in l and "跳过" in l) for l in _out.splitlines()
           if l.strip().startswith("===== SUMMARY")),
       [l for l in _out.splitlines() if l.strip().startswith("=====")])
_check("A05 判据升级点：通过数**不含**被跳过的模块",
       any(l.strip().startswith("===== SUMMARY 2/")
           for l in _out.splitlines()),
       [l for l in _out.splitlines() if l.strip().startswith("=====")])

print("== A 组：真件面（端到端，缺 zstandard 臂） ==")
_stub = tempfile.mkdtemp(prefix="iss284_stub_")
with io.open(os.path.join(_stub, "zstandard.py"), "w", encoding="utf-8") as f:
    f.write("raise ImportError(\"stub: zstandard absent\")" + chr(10))
_rc2, _out2 = _run_tests(_REPO, "logref",
                         extra_env={"PYTHONPATH": _stub + os.pathsep + _REPO})
_check("A06 ★端到端：缺 zstandard 时 `test_logref` 记 SKIP 而非 PASS"
       "（修前 = CI 假绿的同形读数）",
       any("test_logref" in l for l in _lines(_out2, "SKIP "))
       and not any("test_logref" in l for l in _lines(_out2, "PASS ")),
       _lines(_out2, "PASS ") + _lines(_out2, "SKIP "))
shutil.rmtree(_stub, ignore_errors=True)

print("== K 组：双向对照（过度收紧 / 过度放宽） ==")
_check("K01 正常通过的模块照旧 PASS（不误判）",
       any("iss284_pass" in l for l in _pass_lines), _pass_lines)
_check("K02 正常失败的模块照旧 FAIL（不误判）",
       any("iss284_fail" in l for l in _fail_lines), _fail_lines)
_check("K03 ★过度收紧方向：行内（**非行首**）出现「SKIP」字样不得被当成模块内跳过",
       any("iss284_midline" in l for l in _pass_lines)
       and not any("iss284_midline" in l for l in _skip_lines),
       (_pass_lines, _skip_lines))
_check("K04 ★过度放宽方向：rc!=0 的 SKIP 行不得被当成「跳过」（真红必须保住）",
       any("iss284_skip1" in l for l in _fail_lines), _fail_lines)

print("== E 组：结构化判据与汇总可见性在位 ==")


def _src(rel):
    with io.open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


_RT = _src("scripts/run_tests.py")
_check("E01 判定面是**结构化**的：有 canonical 行首正则 + 识别函数（非「print 里含 SKIP」散判）",
       "_SKIP_LINE_RE = re.compile" in _RT and "def _module_skip_reason(" in _RT
       and "^[ \\t]*(?:\\[SKIP\\]|SKIP)[:：\\s]" in _RT, "")
_check("E02 判据在 rc==0 分支内读它（rc!=0 不参与跳过判定）",
       "if r.returncode == 0:" in _RT and "_module_skip_reason(r.stdout, r.stderr)" in _RT,
       "")
_check("E03 跳过者**不出 PASS 行**且计入 mod_skips（源码面：`continue` 在 print PASS 之前）",
       _RT.index("mod_skips.append((name, skip_reason))")
       < _RT.index('print(("PASS  " if ok else "FAIL  ") + name'), "")
_check("E04 汇总计数把跳过者从通过数里减去",
       "len(runnable) - len(bad) - len(mod_skips)" in _RT, "")

# ---------------------------------------------------------------- 定点变异表
_SKIP_BRANCH = chr(10).join([
    "            if r.returncode == 0:",
    "                _reason = _module_skip_reason(r.stdout, r.stderr)",
    "                if _reason:",
    "                    return name, False, tail, _reason",
])
_SKIP_OFF = "            # 变异：去掉模块内 SKIP 识别（回缺陷）"
_RE_ANCHORED = '_SKIP_LINE_RE = re.compile(r"^[ \\t]*(?:\\[SKIP\\]|SKIP)[:：\\s]", re.M)'
_RE_LOOSE = '_SKIP_LINE_RE = re.compile(r"(?:\\[SKIP\\]|SKIP)[:：\\s]", re.M)'
_RC_GUARD = chr(10).join([
    "            if r.returncode == 0:",
    "                _reason = _module_skip_reason(r.stdout, r.stderr)",
])
_RC_LOOSE = chr(10).join([
    "            if True:   # 变异：不看 rc（过度放宽）",
    "                _reason = _module_skip_reason(r.stdout, r.stderr)",
])
_MUTATIONS = (
    # M1 回缺陷（模块内 SKIP 识别摘掉）⇒ 假绿复现：A01/A02/A04/A05/A06 红。
    ("M1 回缺陷：摘掉模块内 SKIP 识别（回到 rc==0 即 PASS）", "scripts/run_tests.py",
     ((_SKIP_BRANCH, _SKIP_OFF),),
     ("A01", "A02", "A04", "A05", "A06", "E02")),
    # M2 **过度收紧**：正则去掉行首锚 ⇒ 行内出现「SKIP」也被当成模块内跳过：K03 红。
    ("M2 过度收紧：SKIP 正则去掉行首锚", "scripts/run_tests.py",
     ((_RE_ANCHORED, _RE_LOOSE),),
     ("A05", "E01", "K03")),
    # M3 **过度放宽**：不看 rc ⇒ rc!=0 的 SKIP 行掩盖真失败：A03/K04 红。
    ("M3 过度放宽：跳过判定不看 rc", "scripts/run_tests.py",
     ((_RC_GUARD, _RC_LOOSE),),
     ("A03", "E02", "K04")),
)


def _apply_text(text, rel, pairs):
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _run_guard(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue284_skip_not_pass"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：回缺陷（摘掉 SKIP 识别）＋ 过度收紧（去锚）＋ 过度放宽（不看 rc）")
    bad = []
    for desc, rel, pairs, exp in _MUTATIONS:
        tree = _mirror_build()
        try:
            rc0, reds0, out0 = _run_guard(tree)
            if rc0 != 0 or reds0:
                bad.append("未变异镜像基线即红：%s" % desc)
                print("  基线即红（%s）：%s" % (desc, reds0[:4]))
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
            rc2, reds2, out2 = _run_guard(tree)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        finally:
            shutil.rmtree(tree, ignore_errors=True)
    print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
    for b in bad:
        print("  不合格：" + b)
    return len(bad)


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
shutil.rmtree(_TREE, ignore_errors=True)
print("")
if FAILS:
    print("issue #284 结果：%d 失败" % len(FAILS))
else:
    print("issue #284 结果：全部通过")

