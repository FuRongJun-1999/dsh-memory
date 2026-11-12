# -*- coding: utf-8 -*-
# 功能名：前像命名的**孪生等价性**与同秒不互踩（issue #413）
# 生效条件：python -X utf8 -m md_cg.test_issue413_preimage_twin [--mutate]；被测面＝md_cg/protect.py 的 _preimage_name（唯一命名单点）、snapshot（裸守卫 _allow 侧）、snapshot_preimage（执行时点前像侧）、_allow（前像缺失时的放行）
# 子功能：F 组＝孪生等价性（同一单点 + 载体同构 + 形态保持 + 同秒不互踩）；A 组＝_allow「前像缺失」两态可达性取证 + 可见化/登记断言；K 组＝非恒真与过度方向（跨秒、合法后缀、探测有界、无冲突不加后缀）；E 组＝枚举完备性与回退自证（_guard_kit 两骨架）
# 执行：--mutate 时在镜像树里回缺陷（去掉探测）/ 过度（无冲突也加后缀）/ 只加固一侧（snapshot 改回裸名），守卫必须按指定项转红；另调 _guard_kit 两骨架
# 验证方式：全部 PASS 即通过（退出码 0）；变异与骨架红项集合须与预期逐项相符
# 不适用条件：不改 #413 的**语义裁定**（前像缺失时 fail-open 还是 fail-closed 归维护者；本守卫只**登记**现状并让它在返回体/审计里可见）；不判 _protected_history 的保留策略与清理；不判加密库里前像的逐字节可复现性（protect.snapshot_preimage docstring 已登记该边界）；不判 test_mutation_rollback 的读数口径（它已按不变量重钉，本件不改它）
"""issue #413 守卫：**同语义两处实现、只加固了一侧** —— 本件把「孪生等价性」钉成判据。

病象（修前）：`snapshot()`（裸守卫 `_allow` 路径）与 `snapshot_preimage()`（执行时点前像）
**各写一套文件名拼接**：前者裸秒级 `%Y%m%d-%H%M%S`，后者秒级 + 6 位微秒。同一秒内两次
`snapshot()` 会拿到**同一路径** ⇒ 先那张前像被后来者覆盖（回滚句柄指向错误时点）。
#413 修法：抽出**唯一命名单点** `_preimage_name(d, suffix="")`（基名 + suffix，已存在即取
下一个空闲名），两侧都改调它。

**等价性的边界（先问载体，再写断言）**：两侧**载体同构**才可直接比字符串——本件实测：两者都
「写一个 .md 到 `_protected_history/<id>/`」且都**返回相对路径字符串**（载体同构 ✔）；**有意不同**
的是审计 action（`snapshot` vs `preimage`）与 reason ⇒ F 组断言「命名单点等价 + 载体同构」，
并**另行断言那两处差异仍在**（等价性 ≠ 全等）。

⚠ 覆盖边界（如实登记）：本守卫**只读** `protect.py`（#413 已定稿），故「前像缺失仍 override
放行」**不改语义**，只做**取证 + 可见化断言**（返回体 snapshot=None + 审计面留 snapshot:null 的
override 记录）。fail-open/fail-closed 的裁定归维护者。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import _guard_kit as GK        # noqa: E402
from md_cg import protect                 # noqa: E402
from md_cg.mdcos import MdCGOS            # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss413_")
_CCG = chr(10).join(["# 功能名：前像目标节点", "# 生效条件：本地合成库",
                     "# 子功能：无", "# 执行：无", "# 验证方式：test",
                     "# 不适用条件：无", "# 正文：前像目标正文"])


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _prot_lib(tag):
    """合成库 + 一个受保护节点（self 层 ⇒ is_immutable 真 ⇒ guard_write 走 _allow）。"""
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    cg = MdCGOS(d)
    cg.add("pr_t", _CCG, layer="self")
    cg.flush()
    return cg


def _names(cg, nid="pr_t"):
    d = os.path.join(cg.root, protect.HISTORY_DIR, nid)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.endswith(".md"))


print("== F 组：孪生等价性（#326-③ F04 形态） ==")
_SRC = open(os.path.join(_REPO, "md_cg", "protect.py"), encoding="utf-8").read()
_SEC = _SRC           # 全文件口径（"留痕"在本文件出现 2 次，split("留痕")[-1] 只会留尾部——实测踩过）
_check("F01 留痕区里秒级裸名拼接只剩**单点内**那一处（无第三处裸命名；调用点恰 2 处）",
       _SEC.count('strftime("%Y%m%d-%H%M%S"') == 1
       and _SEC.count("_preimage_name(") == 3,   # 实测：def 1 + 调用 2
       (_SEC.count('strftime("%Y%m%d-%H%M%S"'),
        _SEC.count("_preimage_name(")))
_check("F02 两侧都经 _preimage_name（裸守卫侧无 suffix / 执行时点侧带 6 位微秒 suffix）",
       "_preimage_name(d)" in _SEC and "_preimage_name(d, \"-%06d\"" in _SEC)

_cg = _prot_lib("twin")
_calls = []
_orig = protect._preimage_name


def _spy(d, suffix=""):
    _calls.append(suffix)
    return _orig(d, suffix)


with mock.patch.object(protect, "_preimage_name", _spy):
    _r1 = protect.snapshot(_cg, "pr_t")
    _r2 = protect.snapshot_preimage(_cg, "pr_t", action="B", pid="pid_1")
_check("F03 **双链等价性**：两条链都命中同一单点（spy 命中 2 次：suffix 空 / 微秒各一）",
       len(_calls) == 2 and _calls[0] == "" and len(_calls[1]) == 7, _calls)
_check("F04 **载体同构**：两侧都返回 str 相对路径、各写一个 .md（可直接比字符串的前提）",
       isinstance(_r1, str) and isinstance(_r2, str)
       and not os.path.isabs(_r2) and len(_names(_cg)) == 2, (_r1, _r2, _names(_cg)))
_check("F05 两侧产物**互不覆盖**（同秒两张不同文件；修前二者路径相同）",
       _r1 != _r2 and len(set(_names(_cg))) == 2, (_r1, _r2, _names(_cg)))
_check("F06 形态保持：裸守卫侧=秒级（无微秒）；执行时点侧=秒级+6 位微秒（既有守卫钉死）",
       bool(re.fullmatch(r"\d{8}-\d{6}(-\d+)?\.md", os.path.basename(_r1)))
       and bool(re.fullmatch(r"\d{8}-\d{6}-\d{6}(-\d+)?\.md", os.path.basename(_r2))),
       (_r1, _r2))
_r3 = protect.snapshot(_cg, "pr_t")
_r4 = protect.snapshot(_cg, "pr_t")
_check("F07 同侧同秒两次：四条路径两两不同（修前四条全等 ⇒ 前像被踩掉）",
       len({_r1, _r2, _r3, _r4}) == 4, (_r1, _r2, _r3, _r4))
_check("F08 落盘文件数 == 返回路径数（没有「返回了却没写」或「写了却没返回」）",
       len(_names(_cg)) == 4, _names(_cg))
_check("F09 **等价性 ≠ 全等**：两侧审计 action 有意不同（snapshot vs preimage），此差异须仍在",
       "\"snapshot\"" in _SEC and "\"preimage\"" in _SEC)
_cg.close()

print("== A 组：_allow 的「前像缺失」两态取证 + 可见化/登记 ==")
_cga = _prot_lib("allow")
_nx = protect.guard_write(_cga, "no_such_node", override=True)
_check("A01 态①「节点不存在」**不可达** _allow：guard_write 返回 None（不存在即放行）",
       _nx is None, _nx)
_check("A02 且 snapshot(不存在节点) 返回 None（该态自证：前像确实拍不出来）",
       protect.snapshot(_cga, "no_such_node") is None)
# ★2026-10-18 契约变更（80aa70d8 #413-2）：前像拍不出来时**不再放行**——`_allow` 改为
# fail-closed（N228：无前像的 override 不可回滚）。旧断言钉的是「放行 + snapshot=None
# 可观测」的旧契约；现改为钉 fail-closed：抛 ProtectionError、错误串点名前像不可得、
# 审计面留 `<action>_denied` 行（拒绝事件同样不静默）。
_err = None
with mock.patch.object(MdCGOS, "_write_node",
                       side_effect=OSError("模拟前像写盘失败")):
    try:
        _fa = protect.guard_write(_cga, "pr_t", override=True, actor="guard413")
    except protect.ProtectionError as exc:
        _err = str(exc)
        _fa = None
_check("A03 态②「启用但失败」**可达**：前像写失败 ⇒ fail-closed 抛 ProtectionError",
       _err is not None and _fa is None, (_err, _fa))
_check("A04 可见化：错误串点明「前像不可得」且声明 fail-closed（拒绝可观测）",
       bool(_err) and "前像不可得" in _err and "fail-closed" in _err, _err)
_ap = os.path.join(_cga.root, protect.AUDIT_FILE)
_rows = []
if os.path.exists(_ap):
    with open(_ap, encoding="utf-8") as _f:
        _rows = [json.loads(l) for l in _f if l.strip()]
_denied = [r for r in _rows if str(r.get("action") or "").endswith("_denied")]
_check("A05 登记：审计面留有该 `<action>_denied` 行（拒绝不静默）",
       bool(_denied),
       [{"a": r.get("action"), "s": r.get("snapshot")} for r in _rows][-3:])
_check("A06 语义已按 #413-2 收口：前像缺失时**不再**返回 override=True（可回滚优先）",
       _fa is None)
_cga.close()

print("== K 组：非恒真对照与过度方向 ==")
_cgk = _prot_lib("k")
_d = os.path.join(_cgk.root, protect.HISTORY_DIR, "pr_t")
os.makedirs(_d, exist_ok=True)
with mock.patch.object(protect.time, "strftime", side_effect=lambda f, t: "20260101-000001"):
    _k1 = protect._preimage_name(_d)
with mock.patch.object(protect.time, "strftime", side_effect=lambda f, t: "20260101-000002"):
    _k2 = protect._preimage_name(_d)
_check("K01 跨秒：两个名字不同且都**无**冲突后缀（形态不被探测改写）",
       _k1 != _k2
       and bool(re.fullmatch(r"\d{8}-\d{6}\.md", os.path.basename(_k1)))
       and bool(re.fullmatch(r"\d{8}-\d{6}\.md", os.path.basename(_k2))), (_k1, _k2))
with mock.patch.object(protect.time, "strftime", side_effect=lambda f, t: "20260101-000003"):
    open(os.path.join(_d, "20260101-000003.md"), "w", encoding="utf-8").close()
    open(os.path.join(_d, "20260101-000003-1.md"), "w", encoding="utf-8").close()
    _k3 = protect._preimage_name(_d)
_check("K02 已存在 base 与 base-1 ⇒ 取 base-2（不覆盖既有前像）",
       os.path.basename(_k3) == "20260101-000003-2.md", os.path.basename(_k3))
_check("K03 合法后缀名不被误判为空闲：不返回已占用的 base.md / base-1.md",
       os.path.basename(_k3) not in ("20260101-000003.md", "20260101-000003-1.md"))
with mock.patch.object(protect.time, "strftime", side_effect=lambda f, t: "20260101-000004"):
    open(os.path.join(_d, "20260101-000004.md"), "w", encoding="utf-8").close()
    for _i in range(1, 50):
        open(os.path.join(_d, "20260101-000004-%d.md" % _i), "w", encoding="utf-8").close()
    _k4 = protect._preimage_name(_d)
_check("K04 探测有界且正确：50 个连续名占满 ⇒ 取第 51 个（不超时、不跳号）",
       os.path.basename(_k4) == "20260101-000004-50.md", os.path.basename(_k4))
with mock.patch.object(protect.time, "strftime", side_effect=lambda f, t: "20260101-000005"):
    _k5 = protect._preimage_name(_d)
_check("K05 无冲突 ⇒ 名字不含任何后缀（既有形态一字不动）",
       os.path.basename(_k5) == "20260101-000005.md", os.path.basename(_k5))
_cgk.close()

print("== E 组：骨架①枚举完备性 ==")


def _discover(texts):
    """守卫自己的枚举：命中「**绕过单点**直接拼快照文件名」的命名点。"""
    import ast as _ast
    hits = []
    for rel, src in texts.items():
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.FunctionDef):
                continue
            seg = _ast.get_source_segment(src, node) or ""
            if "strftime" in seg and "_preimage_name" not in seg:
                hits.append((rel, node.lineno))
    return hits


_OLD = "def snapshot(cg, nid):" + chr(10) + "    d = getattr(cg, \"root\", \"x\")" + chr(10)
_OLD = _OLD + "    p = os.path.join(d, time.strftime(\"%Y%m%d-%H%M%S\", time.localtime()) + \".md\")"
_OLD = _OLD + chr(10) + "    return p"
_NEW = "def snapshot(cg, nid):" + chr(10) + "    d = getattr(cg, \"root\", \"x\")" + chr(10)
_NEW = _NEW + "    return _preimage_name(d)"
_ok_e, _det_e = GK.assert_enumeration_complete(
    _discover,
    [("应命中·旧形态（绕过单点直拼秒级名）", _OLD, True, "protect_old.py"),
     ("不应命中·新形态（经单点）", _NEW, False, "protect_new.py"),
     ("不应命中·无关函数", "def other():" + chr(10) + "    return 1", False, "x.py")])
_check("E01 骨架①枚举完备性（应命中/不应命中两侧）", _ok_e, _det_e)

print("== 骨架② / 变异 ==")
_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "protect.py"),
                                   "rb").read()[:8192] else "\n"


def _j(*lines):
    return _NL.join(lines)


_PROBE = _j("    _n = 1", "    while os.path.exists(p):",
            "        p = os.path.join(d, \"%s-%d.md\" % (base, _n))", "        _n += 1")
_Q = chr(34)          # 内层双引号一律用 _Q 拼，避免本文件出现转义引号
_M1 = ("M1 回缺陷：去掉探测（同秒互踩）", "md_cg/protect.py",
      [(_PROBE, "    pass  # 变异：不探测（回到 #413 修前）")],
      # F05 不参与判别（两侧本就差一个 suffix）；真正打回缺陷的是 F07/F08（互踩/少落盘）
      ("F07", "F08", "K02", "K03", "K04"))
_M2 = ("M2 过度：无冲突也加后缀（形态被改写）", "md_cg/protect.py",
      [(_j("    p = os.path.join(d, base + " + _Q + ".md" + _Q + ")"),
        _j("    p = os.path.join(d, base + " + _Q + "-1.md" + _Q + ")"))],
      # F06 不参与判别（正则允许 -N 后缀）⇒ 由 K01/K05（无形变）承担
      ("K01", "K05"))
# M3 只加固一侧：把 snapshot 侧改回裸名（另一侧仍走单点）——孪生等价性必须因此转红。
_RAW_SNAP = ("    p = os.path.join(d, time.strftime(" + _Q + "%Y%m%d-%H%M%S" + _Q
             + ", time.localtime()) + " + _Q + ".md" + _Q + ")")
_M3 = ("M3 只加固一侧：snapshot 改回裸名（孪生不等价）", "md_cg/protect.py",
      [("    p = _preimage_name(d)", _RAW_SNAP)],
      # 只加固一侧 ⇒ 结构面（F01 出现第二处裸名）+ 双链（F02/F03）+ 互踩（F07/F08）全红
      ("F01", "F02", "F03", "F07", "F08"))
_MUTATIONS = (_M1, _M2, _M3)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss413_mut_")
    for name in ("md_cg", "scripts"):
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
    env.update({"PYTHONPATH": tree, "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue413_preimage_twin"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-20:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if any(t.count(o) != 1 for o, _n in pairs):
                bad.append("%s 锚点命中 %s" % (desc, [t.count(o) for o, _n in pairs]))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            for o, n in pairs:
                t = t.replace(o, n, 1)
            open(p, "w", encoding="utf-8", newline="").write(t)
            for r, dd, ff in os.walk(tree):
                if os.path.basename(r) == "__pycache__":
                    shutil.rmtree(r, ignore_errors=True)
            rc2, reds2, _o2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s 红项=%d 指定命中=%d/%d" % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望=%s rc=%d" % (desc, hit, sorted(exp), rc2))
                for r in reds2[:6]:
                    print("        FAIL " + r)
        ok_r, det_r = GK.assert_revert_reddens(
            _mirror_build,
            [("md_cg/protect.py", _PROBE.replace("\r\n", "\n"), "    pass  # 回退：不探测")],
            _run_in, ("F07", "F08", "K02", "K03", "K04"), "md_cg/protect.py")
        print("  骨架②回退即红：%s %s" % ("OK" if ok_r else "MISMATCH",
                                          json.dumps(det_r, ensure_ascii=False)[:200]))
        if not ok_r:
            bad.append("骨架②未按预期转红")
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


shutil.rmtree(_TMP, ignore_errors=True)
print("")
print("issue #413 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())