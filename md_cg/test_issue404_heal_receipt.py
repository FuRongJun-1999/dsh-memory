# -*- coding: utf-8 -*-
# 功能名：heal 的动作回执与台账必须等于事实（issue #404）
# 生效条件：python -X utf8 -m md_cg.test_issue404_heal_receipt [--mutate]；被测面＝md_cg/sustain.py 的 heal 动作回执（sweep_temps 的 _sweep）与 _audit 台账行
# 子功能：A 组＝全失败（只读致败）回执==事实；B 组＝全成功；C 组＝空路径集（无事可做不是失败）；D 组＝部分成功如实；E 组＝结构性（applied=执行过/ok=按事实 的既有口径不被改义、审计行必带结果、单点）；F 组＝同族枚举登记；骨架①② + 双向变异
# 执行：--mutate 时在镜像树里回缺陷（吞异常）/ 过度（空路径集也判失败）/ 审计面回退，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；变异与骨架红项集合须与预期逐项相符
# 不适用条件：不判 stale_temps 的 severity 分级（info 是既有裁定）；不判 heal 顶层 ok 的语义（它是**诊断面**读数 after["ok"]，非动作聚合，见 E05）；不判 repeat_guard 的退避记忆是否受假成功影响（issue 自陈未实测，另单）；删除失败在 Windows 用真实只读位，在 POSIX 对指定合成件注入 PermissionError，不将权限位差异误判为业务缺陷
"""issue #404 守卫：自愈动作**不得把「一个都没删掉」上报成成功**。

病象（修前，本守卫 A 组即复现）：sustain.py 的 _sweep 逐个 os.remove 并 `except OSError: pass`，
返回 None ⇒ act 的 _bad_result(None) 为假 ⇒ 回执行 `{applied: True, ok: True}`，_audit 同时
照写「清理 N 个陈旧临时文件」——而盘面一个都没删掉。台账因此留一行**与事实相反**的记录
（审计面是外部可见读数）。

修法（本件）：① _sweep **按实际结果**回报（removed/planned/errors），paths 非空而一个都没删掉
时**抛错**（fail-loud）；② act 的异常分支把错误摘要并入 detail 后再 _audit ⇒ 台账不再写假行。
**applied 语义不改义**：沿用仓内既有口径（scrub.py 的 #411 修法）——「applied=动作跑过、
ok=按事实判」。改义会反转既有读者（含 dry_run 行用 applied=False 表示「未执行」）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import _guard_kit as GK       # noqa: E402
from md_cg import sustain                # noqa: E402
from md_cg.mdcos import MdCGOS           # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss404_")
_Q = chr(34)
# POSIX 删除权限由父目录决定，chmod(0444) 不能像 Windows 只读位那样阻止 unlink。
# 仅在这些合成夹具路径上注入同一种 PermissionError；Windows 保留真实只读位置景。
_DELETE_DENIED = set()


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _mk(tag, n_temps, readonly_idx=()):
    """合成库 + n_temps 个「直接落在层目录下」的陈旧临时件（只读位由 readonly_idx 指定）。"""
    root = os.path.join(_TMP, tag)
    os.makedirs(root, exist_ok=True)
    cg = MdCGOS(root)
    cg.add("n_x", "# 功能：X" + chr(10) + "# 执行：无", layer="knowledge")
    cg.flush()
    paths = []
    for i in range(n_temps):
        p = os.path.join(root, "knowledge", ".n_t%d.md.tmp-ab%02d" % (i, i))
        with open(p, "w", encoding="utf-8") as f:
            f.write("临时件 %d" % i)
        old = time.time() - 30 * 24 * 3600
        os.utime(p, (old, old))
        if i in readonly_idx:
            os.chmod(p, 0o444)
            _DELETE_DENIED.add(os.path.abspath(p))
        paths.append(p)
    return cg, root, paths


def _rows(cg, root, paths):
    remove = os.remove

    def fixture_remove(path, *args, **kwargs):
        if os.name != "nt" and os.path.abspath(path) in _DELETE_DENIED:
            raise PermissionError("fixture: synthetic read-only temporary file")
        return remove(path, *args, **kwargs)

    with patch.object(sustain.os, "remove", fixture_remove):
        r = sustain.heal(cg, name="md_cg")
    row = [a for a in r.get("actions", []) if a.get("code") == "sweep_temps"]
    ap = os.path.join(root, "_sustain.jsonl")
    led = []
    if os.path.exists(ap):
        with open(ap, encoding="utf-8") as f:
            led = [json.loads(l) for l in f if l.strip()]
    sweep_led = [l for l in led if l.get("action") == "sweep_temps"]
    return r, (row[0] if row else None), sweep_led, led


print("== A 组：全失败（只读致败）⇒ 回执与台账必须等于事实 ==")
_cg, _root, _paths = _mk("a_fail", 1, readonly_idx=(0,))
_r, _row, _led, _all = _rows(_cg, _root, _paths)
_check("A01 动作回执 ok=False（修前 True）", _row and _row.get("ok") is False, _row)
_check("A02 动作回执 error 非空且点名「一个都没删掉」",
       bool(_row) and "一个都没删掉" in str(_row.get("error")), (_row or {}).get("error"))
_check("A03 applied 仍为 True（=动作跑过，未被改义）", (_row or {}).get("applied") is True, _row)
_check("A04 盘面事实：临时件仍在（回执与事实一致）", os.path.exists(_paths[0]))
_check("A05 台账行**不得**只写「清理 N 个」——必须带结果（失败）",
       bool(_led) and "失败" in str(_led[0].get("detail"))
       and "清理 1 个陈旧临时文件" == str(_led[0].get("detail")).split(" → ")[0], _led)
for _p in _paths:
    try:
        os.chmod(_p, 0o666)
    except OSError:
        pass
_cg.close()

print("== B 组：全成功 ⇒ removed 计数如实 ==")
_cg, _root, _paths = _mk("b_ok", 2)
_r, _row, _led, _all = _rows(_cg, _root, _paths)
_check("B01 ok=True 且 removed==2/planned==2（修前无计数、无可判事实）",
       _row and _row.get("ok") is True and (_row.get("result") or {}).get("removed") == 2
       and (_row.get("result") or {}).get("planned") == 2, _row)
_check("B02 盘面事实：两个临时件都已不在（回执==事实）",
       not any(os.path.exists(p) for p in _paths))
_check("B03 台账行正常形态（未被我改动污染）：仍以「清理 N 个」开头并带结果摘要",
       bool(_led) and str(_led[0].get("detail")).startswith("清理 2 个陈旧临时文件"), _led)
_cg.close()

print("== C 组：空路径集（无事可做不是失败） ==")
# 可达构造：diagnose 先报 stale_temps（第一次调用返回真路径），随后**执行前**路径已消失
# （第二次调用返回 []）——这正是生产上「诊断与处置之间被别的进程清掉」的形态。
# 不这么造，本态经 heal 根本不可达（无 stale_temps 就不会有该动作）。
_cg, _root, _paths = _mk("c_empty", 0)
_cg.add("n_c", "# 功能：C" + chr(10) + "# 执行：无", layer="knowledge")
_cg.flush()
_ghost = os.path.join(_root, "knowledge", ".n_gone.md.tmp-zz99")
with open(_ghost, "w", encoding="utf-8") as f:
    f.write("诊断时还在")
_oldt = time.time() - 30 * 24 * 3600
os.utime(_ghost, (_oldt, _oldt))
_calls = {"n": 0}
_orig_list = sustain._list_stale_temps


def _list_then_gone(root, older):
    _calls["n"] += 1
    if _calls["n"] == 1:
        return _orig_list(root, older)
    return []                    # 执行前已被清掉 ⇒ 路径集为空


sustain._list_stale_temps = _list_then_gone
try:
    _r, _row, _led, _all = _rows(_cg, _root, [])
finally:
    sustain._list_stale_temps = _orig_list
_check("C01 路径集为空（诊断后已被清掉）⇒ removed==0 且 ok=True（不得把「无事可做」判成失败）",
       _row and _row.get("ok") is True
       and (_row.get("result") or {}).get("removed") == 0, _row)
_cg.close()

print("== D 组：部分成功 ⇒ 如实（ok=False + removed 计数） ==")
_cg, _root, _paths = _mk("d_part", 2, readonly_idx=(1,))
_r, _row, _led, _all = _rows(_cg, _root, _paths)
_check("D01 一成功一失败 ⇒ ok=False 且 removed==1、errors 非空",
       _row and _row.get("ok") is False and (_row.get("result") or {}).get("removed") == 1
       and (_row.get("result") or {}).get("errors"), _row)
_check("D02 盘面事实：成功那个已删、失败那个仍在",
       (not os.path.exists(_paths[0])) and os.path.exists(_paths[1]))
for _p in _paths:
    try:
        os.chmod(_p, 0o666)
    except OSError:
        pass
_cg.close()

print("== E 组：结构性（口径与单点） ==")
_S = open(os.path.join(_REPO, "md_cg", "sustain.py"), encoding="utf-8").read()
_SW = _S.split("def _sweep():")[1].split(chr(10) + "        act(")[0]
_check("E01 _sweep 不再吞异常（无 `except OSError:` 后接 pass 的形态），且返回计数",
       "except OSError as e:" in _SW and "removed" in _SW
       and not re.search(r"except OSError:\s*\n\s*pass", _SW))
_check("E02 全失败即抛（fail-loud）：_sweep 内含 raise OSError 且判据是 done == 0",
       "raise OSError" in _SW and "done == 0" in _SW)
_ACT = _S.split("        except Exception as e:")[1].split("else:")[0]
_check("E03 审计面：act 的异常分支把错误并入 detail（否则台账照写假行）",
       "detail = " in _ACT and "失败" in _ACT, _ACT.strip()[:120])
_S_NOSP = _S.replace(" ", "")
_check("E04 口径未改义：applied 行仍恒 True（执行过），ok 由 _bad_result/异常判",
       _S_NOSP.count(chr(34) + "applied" + chr(34) + ":True") >= 1
       and chr(34) + "ok" + chr(34) + ":notbad" in _S_NOSP, )
_check("E05 顶层 ok 是**诊断面**读数（after[ok]）而非动作聚合——不得被当成动作回执改掉",
       chr(34) + "ok" + chr(34) + ":after[" in _S_NOSP)

print("== F 组：同族枚举登记（applied 站点逐个判） ==")
_FAMILY = (
    ("md_cg/sustain.py::act", "自愈动作回执", "本件修复点：ok 按事实判 + 审计行带结果"),
    ("md_cg/scrub.py::applied 行", "去污动作回执", "已是同口径（#411：ok=_actions_ok(done)、applied=跑过）——本件的语义先例"),
    ("md_cg/mdcos.py:applied=True", "演化/裁决记录形参", "非同族：不是自愈回执，无「已执行→已生效」混淆"),
    ("md_cg/mdcg.py:applied=True", "同上（记录形参）", "非同族"),
    ("sleep.py 的 committed 回执", "睡眠提交回执", "非同族：无 pathspec 时如实记 committed=False/reason"),
)
_check("F01 同族枚举表已登记且逐条给出判定（防漏判未登记）", len(_FAMILY) == 5
       and all(len(x) == 3 and x[2] for x in _FAMILY))
_check("F02 语义先例在位：scrub 仍按 _actions_ok 判 ok（本件与之同口径）",
       "applied" in open(os.path.join(_REPO, "md_cg", "scrub.py"), encoding="utf-8").read()
       and "_actions_ok" in open(os.path.join(_REPO, "md_cg", "scrub.py"), encoding="utf-8").read())

print("== 骨架①：枚举完备性（吞异常后报成功） ==")


def _discover(texts):
    """守卫自己的枚举：命中「try 里 os.remove + except 后 pass（失败被吞、函数仍返回）」的函数。"""
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
            if "os.remove(" not in seg:
                continue
            if "removed" in seg or "raise OSError" in seg:
                continue
            hits.append((rel, node.lineno))
    return hits


_OLD_SWEEP = (
    "def _sweep():" + chr(10)
    + "    for p in paths:" + chr(10)
    + "        try:" + chr(10)
    + "            os.remove(p)" + chr(10)
    + "        except OSError:" + chr(10)
    + "            pass")
_NEW_SWEEP = (
    "def _sweep():" + chr(10)
    + "    done, failed = 0, []" + chr(10)
    + "    for p in paths:" + chr(10)
    + "        try:" + chr(10)
    + "            os.remove(p)" + chr(10)
    + "        except OSError as e:" + chr(10)
    + "            failed.append(str(e))" + chr(10)
    + "    if paths and done == 0:" + chr(10)
    + "        raise OSError(" + _Q + "none" + _Q + ")" + chr(10)
    + "    return {" + _Q + "removed" + _Q + ": done}")
_ok_e, _det_e = GK.assert_enumeration_complete(
    _discover,
    [("应命中·旧形态（吞异常后仍返回）", _OLD_SWEEP, True, "sustain_old.py"),
     ("不应命中·新形态（计数 + 全失败即抛）", _NEW_SWEEP, False, "sustain_new.py"),
     ("不应命中·无关函数", "def other():" + chr(10) + "    return 1", False, "x.py")])
_check("E06 骨架①枚举完备性（应命中/不应命中两侧）", _ok_e, _det_e)

print("== 骨架② / 变异 ==")
_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "sustain.py"),
                                   "rb").read()[:8192] else "\n"


def _j(*lines):
    return _NL.join(lines)


_SWEEP_BODY = _j("            done, failed = 0, []",
                 "            for p in paths:",
                 "                try:",
                 "                    os.remove(p)",
                 "                except OSError as e:",
                 "                    failed.append(\"%s: %s\" % (os.path.basename(p), e))",
                 "                else:",
                 "                    done += 1",
                 "            if paths and done == 0:",
                 "                raise OSError(\"陈旧临时件一个都没删掉（%d/%d）：%s\"",
                 "                              % (done, len(paths), \"；\".join(failed[:3])))",
                 "            return {\"ok\": not failed, \"removed\": done, \"planned\": len(paths),",
                 "                    \"errors\": failed[:3]}")
_M1 = ("M1 回缺陷：_sweep 吞异常且返回 None（回到修前）", "md_cg/sustain.py",
       [(_SWEEP_BODY, _j("            for p in paths:",
                         "                try:",
                         "                    os.remove(p)",
                         "                except OSError:",
                         "                    pass"))],
       # 实测：回缺陷连带把源码面腿也打红（E01/E02 判据即「不再吞异常」），C01 亦红
       ("A01", "A02", "A05", "B01", "C01", "D01", "E01", "E02"))
_M2 = ("M2 过度：空路径集也判失败（把「无事可做」当失败）", "md_cg/sustain.py",
       [(_j("            if paths and done == 0:"), _j("            if done == 0:"))], ("C01",))
_M3 = ("M3 审计面回退：异常分支不改 detail（台账照写假行）", "md_cg/sustain.py",
       [(_j("            detail = \"%s → 失败：%s: %s\" % (detail, type(e).__name__, e)"),
         _j("            pass  # 变异：审计行不带结果"))], ("A05", "E03"))
_MUTATIONS = (_M1, _M2, _M3)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss404_mut_")
    for name in ("md_cg", "scripts", "data"):     # data/ ＝ 判据所需的非 .py 数据面
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
                         "md_cg.test_issue404_heal_receipt"],
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
            _mirror_build, [("md_cg/sustain.py", _SWEEP_BODY.replace("\r\n", "\n"),
                             _j("            for p in paths:",
                                "                try:",
                                "                    os.remove(p)",
                                "                except OSError:",
                                "                    pass"))],
            # 骨架内部按目标文件行尾折算 ⇒ 这里必须传 LF 锚点（传 CRLF 会被再折一次 ⇒ 命中 0 次）
            _run_in, ("A01", "A02", "A05", "B01", "C01", "D01", "E01", "E02"),
            "md_cg/sustain.py")
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
print("issue #404 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
