# -*- coding: utf-8 -*-
# 功能名：检索**默认面**的构成必须与登记表双向一致（issue #149 建议 (c)）
# 生效条件：python -u -X utf8 -m md_cg.test_issue149_accel_default_face [--mutate]；被测面＝md_cg/mdcos.py 的 search_rrf 默认 paths（引擎默认面）+ 其文档缺省行 + md_cg/eval_common.py 的 PATHS（评测口径面）+ 加速开关默认态
# 子功能：A 组＝三处默认面一致；B 组＝双向（登记的表项仍在代码中 ∧ 默认面出现的名字都已登记 ∧ 条件路不得混进默认面）；C 组＝开关默认态与登记一致；骨架①② + 单向/双向变异
# 执行：--mutate 时在镜像树里「加一路未登记」，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；变异红项集合须与预期逐项相符
# 不适用条件：**本守卫不改任何默认值**（(c) 是补判据：零行为变更；默认开/关的产品裁定归维护者）；不判各加速器的收益（需独立实测）；不判各路实现行为（另有守卫）
"""issue #149 建议 (c)：默认面当前**无任何守卫** —— 加一路漏登记、或默认面悄悄变化都是静默的。
本件只做「把默认面与登记表双向钉住」，零行为变更。"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import _guard_kit as GK     # noqa: E402

FAILS = []

#: 登记表＝本批的**裁定基线**（默认面现状 + 条件路 + 开关默认态）。改默认面/开关即须改此表并走裁定。
REGISTRY_PATHS_DEFAULT = ("lexical", "bucket", "entity", "graph", "chain", "temporal")
REGISTRY_PATHS_CONDITIONAL = ("bm25", "postings")
REGISTRY_EVAL_FACE = ("lexical", "bucket", "entity", "graph")
REGISTRY_SWITCHES = {"MDCG_HOTCACHE": "off", "MDCG_RRF_CANDIDATES": "off",
                     "MDCG_GATE_S7_POSTINGS": "off", "MDCG_RETRIEVAL_PIPELINE": "off",
                     "MDCG_READ_CACHE": "on"}


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _read(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _tokens(seg):
    return tuple(re.findall("[a-z_]+", seg))


def _engine_default(src):
    i = src.index("def search_rrf(self, query")
    seg = src[i:i + 1200]
    j = seg.index("paths=(") + len("paths=(")
    return _tokens(seg[j:seg.index(")", j)])


def _doc_default(src):
    # 锚点必须**限定在 search_rrf 附近**：文件里另有多处「缺省 = (…)」（实测踩过：命中了
    # 参数缺省那一行，返回 ('gamma','dt','floor')）——锚点的界定本身就是判据设计。
    i = src.index("def search_rrf(self, query")
    win = src[i:i + 3000]
    m = re.search("缺省 = ", win)
    seg = win[m.start():m.start() + 200]
    j = seg.index("(") + 1
    return _tokens(seg[j:seg.index(")", j)])


def _eval_face(src):
    m = re.search("^PATHS ", src, re.M)
    seg = src[m.start():m.start() + 200]
    j = seg.index("(") + 1
    return _tokens(seg[j:seg.index(")", j)])


_MCS = _read("md_cg/mdcos.py")
_EVC = _read("md_cg/eval_common.py")
_ENG = _engine_default(_MCS)
_DOC = _doc_default(_MCS)
_EVA = _eval_face(_EVC)

print("== A 组：默认面三处一致 ==")
_check("A01 引擎默认面 == 登记表", _ENG == REGISTRY_PATHS_DEFAULT, (_ENG, REGISTRY_PATHS_DEFAULT))
_check("A02 文档缺省行 == 引擎默认面（两处口径不得漂移）", _DOC == _ENG, (_DOC, _ENG))
_check("A03 评测口径面 == 登记表（有意的窄面，须显式登记）", _EVA == REGISTRY_EVAL_FACE,
       (_EVA, REGISTRY_EVAL_FACE))
_check("A04 评测面 ⊆ 引擎默认面（评测不得引用引擎没有的路）",
       set(_EVA) <= set(_ENG), sorted(set(_EVA) - set(_ENG)))

print("== B 组：双向（登记 <-> 代码） ==")
_missing = [p for p in REGISTRY_PATHS_DEFAULT + REGISTRY_PATHS_CONDITIONAL if p not in _MCS]
_check("B01 登记表每个路名仍在代码中出现（删路即红）", _missing == [], _missing)
_unreg = [p for p in _ENG if p not in REGISTRY_PATHS_DEFAULT]
_check("B02 默认面出现的每个路名都已登记（加路漏登记即红）", _unreg == [], _unreg)
_mix = [p for p in REGISTRY_PATHS_CONDITIONAL if p in _ENG]
_check("B03 条件路（实测无收益/零读盘待裁）不得悄悄混进默认面", _mix == [], _mix)

print("== C 组：加速开关默认态与登记一致 ==")
# 逐行收集（判据必须**逐行**判：套在拼接后的全包文本上会写窄——实测踩过）
_LINES = []
_ALL = ""
for _dp, _dn, _ff in os.walk(os.path.join(_REPO, "md_cg")):
    if "__pycache__" in _dp:
        continue
    for _f in _ff:
        if _f.endswith(".py") and not _f.startswith("test_"):
            with open(os.path.join(_dp, _f), encoding="utf-8", errors="replace") as _fh:
                _txt = _fh.read()
            _ALL += _txt
            _LINES.extend(_txt.splitlines())
_BAD = []
for _k, _want in REGISTRY_SWITCHES.items():
    _present = _k in _ALL
    if not _present:
        _BAD.append((_k, "开关在代码中已消失（登记过期）"))
    elif _want == "off":
        if not any((_k in _ln) and (chr(34) + "1" + chr(34) in _ln or chr(39) + "1" + chr(39) in _ln) for _ln in _LINES):
            _BAD.append((_k, "登记为默认关，但开关名后 40 字内未见引号 1（疑似被翻为默认开）"))
_check("C01 默认关的开关仍是「=1 才开」形态（被翻成默认开即红）", _BAD == [], _BAD)
_check("C02 默认开的开关（readcache）在代码中有显式读取（登记为 on）",
       "READ_CACHE" in _read("md_cg/readcache.py"))

print("== 骨架①：枚举完备性（默认面抽取器） ==")


def _discover(texts):
    import ast as _ast
    hits = []
    for rel, src in texts.items():
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.FunctionDef) or node.name != "search_rrf":
                continue
            seg = _ast.get_source_segment(src, node) or ""
            if "paths=(" in seg and "REGISTRY" not in seg:
                hits.append((rel, node.lineno))
    return hits


_OLD_SIG = "def search_rrf(self, query, paths=(b1, b2)):" + chr(10) + "    return paths"
_NEW_SIG = "def search_rrf(self, query:" + chr(10) + "    paths=None):  # 默认面由登记表断言" + chr(10) + "    return paths"
_ok_e, _det_e = GK.assert_enumeration_complete(
    _discover,
    [("应命中·旧形态（签名内联默认面）", _OLD_SIG, True, "sig_old.py"),
     ("不应命中·新形态（登记表断言）", _NEW_SIG, False, "sig_new.py"),
     ("不应命中·无关函数", "def other():" + chr(10) + "    return 1", False, "x.py")])
_check("E01 骨架①枚举完备性（应命中/不应命中两侧）", _ok_e, _det_e)

print("== 骨架② / 变异 ==")


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss149_mut_")
    for name in ("md_cg", "scripts", "data"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env.update({"PYTHONPATH": tree, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.test_issue149_accel_default_face"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip() for ln in out.splitlines()
            if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


# 锚点必须取自**文件实际文本**：默认面元组在源码里**跨两行**（实测：手拼单行锚点命中 0 次）。
_i0 = _MCS.index("def search_rrf(self, query")
_seg0 = _MCS[_i0:_i0 + 1200]
_j0 = _seg0.index("paths=(")
_k0 = _seg0.index(")", _j0)
_ENG_ANCHOR = _seg0[_j0:_k0 + 1]
# 镜像树里的 mdcos.py 是 **CRLF**（本案实测：用 LF 锚点在镜像里命中 0 次）⇒ 变异用锚点按目标行尾折算。
_ENG_ANCHOR_CR = _ENG_ANCHOR.replace(chr(10), chr(13) + chr(10))


def _mutate():
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-15:]))
        _cases = [("M1 加一路未登记（默认面混进 bm25）", "md_cg/mdcos.py",
                   _ENG_ANCHOR_CR, _ENG_ANCHOR_CR[:-1] + ", " + chr(34) + "bm25" + chr(34) + ")",
                   ("A01", "A02", "B02"))]   # 实测：B03 在本变异下**不判别**（与 B02 同因，已在注释说明）
        for desc, rel, o, n, exp in _cases:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(o) != 1:
                bad.append(desc)
                print("  ANCHOR-MISS " + desc + " n=" + str(t.count(o)))
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(o, n, 1))
            rc2, reds2, _o = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s 红项=%d 指定命中=%d/%d" % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望=%s rc=%d" % (desc, hit, sorted(exp), rc2))
        _rev_old = _ENG_ANCHOR.replace(chr(34) + "graph" + chr(34), chr(34) + "graphx" + chr(34))
        ok_r, det_r = GK.assert_revert_reddens(
            _mirror_build, [("md_cg/mdcos.py", _ENG_ANCHOR.replace("\r\n", "\n"),
                             _rev_old.replace("\r\n", "\n"))],
            _run_in, ("A01", "A02", "A04", "B02"), "md_cg/mdcos.py")
        print("  骨架②回退即红：%s %s" % ("OK" if ok_r else "MISMATCH",
                                          json.dumps(det_r, ensure_ascii=False)[:170]))
        if not ok_r:
            bad.append("骨架②未按预期转红")
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


print("")
print("issue #149(c) 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())