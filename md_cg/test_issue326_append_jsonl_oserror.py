# -*- coding: utf-8 -*-
# 功能名：append_jsonl 的 OSError 不得击穿公开 API（issue #326-④）
# 生效条件：python -X utf8 -m md_cg.test_issue326_append_jsonl_oserror [--mutate]；被测面＝md_cg/fsutil.py::append_jsonl 的失败契约（best-effort ⇒ 写失败返回 False 而非上抛）
# 子功能：A 组＝写失败兜住且返回 False（makedirs/open/write 三条腿 + 目录型目标真 OSError）、成功返回 True、只兜 OSError（KeyboardInterrupt/SystemExit/TypeError 照常上抛）；K 组＝非恒真对照（过度收紧方向：正常写入不得被误判失败；过度放宽方向：不得吞 BaseException 与编程错误；往返读回/坏行容忍不受扰）
# 执行：--mutate 时在镜像树里逐条把契约改回「无 except」/过度收紧（恒 False）/过度放宽（兜 BaseException），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**（多红/少红皆不合格），锚点未命中即 fail-closed
# 不适用条件：不覆盖 ShardedLog（另立机制）；不判 O_APPEND 并发交错丢记录的平台差异（docstring 已声明，非本批）；不覆盖各调用点的业务语义；不判 0o600 权限位在 Windows 的实际效果（属 #326-⑤ 面）
"""issue #326-④ 守卫：append_jsonl 自陈 best-effort，实现却只有 try/finally。

病象（修前）：os.makedirs / os.open / os.write 的 OSError（磁盘满、只读介质、
权限拒绝、路径过长）**击穿**调用方——把「簿记写入失败」升级成「业务路径失败」，
与 docstring 的「丢一条无所谓」直接矛盾。

修法：兜住 OSError 并返回 False（成功 True）；**只**兜 OSError——KeyboardInterrupt /
SystemExit 是 BaseException，Type/ValueError（record 不可 JSON 序列化）是编程错误，
一概照常上抛（except BaseException 与「恒返回 False」两个方向的过度修正都被本守卫钉死）。
"""
from __future__ import annotations

import ast
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


_TMP = tempfile.mkdtemp(prefix="iss326d_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from md_cg import fsutil                         # noqa: E402

_REAL_OS = fsutil.os


class _OsShim:
    """os 模块代理：只覆盖指定函数，其余转发（不改进程全局 os）。"""

    def __init__(self, **over):
        self._over = over

    def __getattr__(self, name):
        if name in self._over:
            return self._over[name]
        return getattr(os, name)


def _raises(exc):
    def _f(*_a, **_k):
        raise exc
    return _f


def _err(fn):
    """调 fn：正常返回 ("", "")；抛异常（**含 BaseException**）返回 (类型名, 文本)。"""
    try:
        fn()
        return "", ""
    except BaseException as exc:                 # noqa: BLE001 —— 本守卫要判 KI/SE 是否被吞
        return type(exc).__name__, str(exc)


def _p(tag):
    return os.path.join(_TMP, tag + ".jsonl")


def _text(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


# 生效条件：path/rec 给定时调 fsutil.append_jsonl——正常返回其返回值；抛异常（含 BaseException）
# 返回 "raise:<类型名>"。**变异态必须产出命名红项而不是崩栈**（崩栈会让守卫在首个夹具处中断、
# 红得不可归因；task-8 的教训）——故组内所有直接调用一律经本包装，断言只判返回值形态。
def _append(path, rec):
    try:
        return fsutil.append_jsonl(path, rec)
    except BaseException as exc:                 # noqa: BLE001
        return "raise:" + type(exc).__name__

print("== A 组：#326-④ 正题——写失败必须兜住并返回 False ==")
_p1 = _p("normal")
_r1 = _append(_p1, {"a": 1})
_check("A01 正常写入返回 True，内容逐字正确（紧凑分隔符）",
       _r1 is True and _text(_p1) == json.dumps({"a": 1}, ensure_ascii=False,
                                                separators=(",", ":")) + chr(10),
       (_r1, _text(_p1)))
_r2 = _append(_p1, {"b": 2})
_check("A02 追加语义不变：第二次仍 True 且共 2 行",
       _r2 is True and len([l for l in _text(_p1).split(chr(10)) if l]) == 2,
       (_r2, _text(_p1)))
_p2 = _p("midline")
with open(_p2, "w", encoding="utf-8") as f:
    f.write(chr(123) + chr(34) + "z" + chr(34) + ":0" + chr(125))   # 不带换行 ⇒ 半行
_r3 = _append(_p2, {"c": 3})
_rows = [json.loads(l) for l in _text(_p2).split(chr(10)) if l.strip()]
_check("A03 半行文件仍先补换行（两行各自可解析，不粘连）",
       _r3 is True and _rows == [{"z": 0}, {"c": 3}], _rows)
# —— 真实 OSError：目标是**目录**（跨平台均为 OSError 子类） ——
_dir = os.path.join(_TMP, "adir")
os.makedirs(_dir, exist_ok=True)
_t4, _m4 = _err(lambda: fsutil.append_jsonl(_dir, {"d": 4}))
_check("A04 目标为目录（真 OSError）→ 兜住不抛", _t4 == "", (_t4, _m4))
_check("A05 目标为目录 → 返回 False（不是 None、不是 True）",
       _append(_dir, {"d": 4}) is False, "")
# —— 三条腿的模拟失败 ——
for _tag, _over, _nm in (("write", {"write": _raises(OSError(28, "No space left"))},
                          "os.write ENOSPC"),
                         ("open", {"open": _raises(OSError(13, "Permission denied"))},
                          "os.open EACCES"),
                         ("makedirs", {"makedirs": _raises(OSError(36, "name too long"))},
                          "os.makedirs ENAMETOOLONG")):
    _pp = _p("sim_" + _tag)
    fsutil.os = _OsShim(**_over)
    try:
        _t, _m = _err(lambda: fsutil.append_jsonl(_pp, {"e": _tag}))
    finally:
        fsutil.os = _REAL_OS
    _check("A06 %s → 兜住不抛" % _nm, _t == "", (_t, _m))
    fsutil.os = _OsShim(**_over)
    try:
        _rv = _append(_pp, {"e": _tag})
    finally:
        fsutil.os = _REAL_OS
    _check("A07 %s → 返回 False" % _nm, _rv is False, _rv)
# —— 只兜 OSError：BaseException 与编程错误必须照常上抛 ——
for _exc, _nm, _id in ((KeyboardInterrupt(), "KeyboardInterrupt", "A08"),
                       (SystemExit(3), "SystemExit", "A09")):
    _pp = _p("esc_" + _nm)
    fsutil.os = _OsShim(write=_raises(_exc))
    try:
        _t, _ = _err(lambda: fsutil.append_jsonl(_pp, {"f": 1}))
    finally:
        fsutil.os = _REAL_OS
    _check("%s %s 不被吞（BaseException 不在兜住面内）" % (_id, _nm),
           _t == _nm, _t)
_t10, _m10 = _err(lambda: fsutil.append_jsonl(_p("bad"), {"g": object()}))
_check("A10 record 不可 JSON 序列化（编程错误）→ TypeError 照常上抛、不伪装成丢一条",
       _t10 == "TypeError", (_t10, _m10))
_check("A11 返回值契约恒定是 bool（成功 True / 失败 False）",
       _append(_p("bool1"), {"h": 1}) is True
       and _append(_dir, {"h": 1}) is False, "")

print("== K 组：非恒真对照 ==")
# 过度收紧方向：正常写入不得被误判失败
_pk = _p("k_normal")
_oks = [_append(_pk, {"i": _i}) for _i in range(5)]
_check("K01 连续 5 次正常写入全部 True（不得恒 False）",
       _oks == [True] * 5, _oks)
_check("K02 5 条记录逐条可解析且非 ASCII 不转义（ensure_ascii=False 语义不变）",
       [json.loads(l) for l in _text(_pk).split(chr(10)) if l]
       == [{"i": _i} for _i in range(5)], _text(_pk)[:80])
_pk2 = _p("k_cjk")
_append(_pk2, {"ming": "鲸娘", "zhi": "海景别墅"})
_check("K03 中文键值往返一致（编码面不受本次改动影响）",
       "鲸娘" in _text(_pk2) and list(fsutil.read_jsonl(_pk2))
       == [{"ming": "鲸娘", "zhi": "海景别墅"}], _text(_pk2))
# 过度放宽方向：编程错误不得被降级为 False（返回值面只表达 I/O 失败）
_t14, _ = _err(lambda: fsutil.append_jsonl(_p("bad2"), {"j": object()}))
_check("K04 编程错误不得被降级为 False（TypeError 照常上抛）",
       _t14 == "TypeError", _t14)
# 相邻读数不受扰
_pk3 = _p("k_roundtrip")
_append(_pk3, {"k": 1})
with open(_pk3, "a", encoding="utf-8") as f:
    f.write("{broken" + chr(10))
_append(_pk3, {"k": 3})
_rows3 = list(fsutil.read_jsonl(_pk3))
_check("K05 坏行容忍不受扰（坏行跳过、好行照读）",
       _rows3 == [{"k": 1}, {"k": 3}], _rows3)
_pnew = _p("k_missing")
_check("K06 目标不存在时 ends_mid_line 为假且写入成功（新文件单行、无前导换行）",
       fsutil.ends_mid_line(_pnew) is False
       and _append(_pnew, {"l": 1}) is True
       and _text(_pnew).count(chr(10)) == 1 and not _text(_pnew).startswith(chr(10)),
       _text(_pnew))
_check("K07 失败不污染后续（目录型失败后再写正常目标仍成功、行数正确）",
       _append(_dir, {"m": 1}) is False
       and _append(_p("k_after"), {"m": 1}) is True
       and len([l for l in _text(_p("k_after")).split(chr(10)) if l]) == 1, "")

# —— B 面：写失败在**源头**记账（让「静默」在结构上不可能） ——
_n0 = fsutil.APPEND_FAILURES
_s0 = len(fsutil._APPEND_FAIL_SAMPLES)
_cfail = _p("bfail")
_dirfail = os.path.join(_TMP, "adir_fail")
os.makedirs(_dirfail, exist_ok=True)
_rvb = _append(_dirfail, {"bf": 1})
_check("A12 写失败（目标为目录）⇒ 源头也记账：APPEND_FAILURES +1",
       _rvb is False and fsutil.APPEND_FAILURES == _n0 + 1,
       (_rvb, _n0, fsutil.APPEND_FAILURES))
_check("A13 写失败 ⇒ 源头留有**有界样本**（path/类型名/文本）",
       len(fsutil._APPEND_FAIL_SAMPLES) == min(_s0 + 1, fsutil._APPEND_FAIL_SAMPLE_CAP)
       and len(fsutil._APPEND_FAIL_SAMPLES) > 0, fsutil._APPEND_FAIL_SAMPLES)

print("== E 组：AST 钉子——被 except OSError 覆盖的 append_jsonl 调用不得是裸调用 ==")


def _has_oserror_handler(node):
    for h in node.handlers:
        ty = h.type
        parts = ty.elts if isinstance(ty, ast.Tuple) else [ty]
        for x in parts:
            if x is not None and getattr(x, "id", getattr(x, "attr", "")) == "OSError":
                return True
    return False


def _bare_append_in(node):
    """返回该节点内「裸调用」append_jsonl（返回值被丢弃，形态为表达式语句）的行号。"""
    out = []
    for x in ast.walk(node):
        if isinstance(x, ast.Expr) and isinstance(x.value, ast.Call) \
                and isinstance(x.value.func, ast.Name) \
                and x.value.func.id == "append_jsonl":
            out.append(x.value.lineno)
    return out


_guarded, _naked = 0, []
for _dp, _dn, _fns in os.walk(os.path.join(_REPO, "md_cg")):
    if "__pycache__" in _dp:
        continue
    for _fn in sorted(_fns):
        if not _fn.endswith(".py"):
            continue
        _fp = os.path.join(_dp, _fn)
        try:
            with open(_fp, encoding="utf-8") as _fh:
                _src = _fh.read()
            _tree = ast.parse(_src)
        except (OSError, SyntaxError):
            continue
        for _n in ast.walk(_tree):
            if not isinstance(_n, ast.Try) or not _has_oserror_handler(_n):
                continue
            _has_call = any(
                isinstance(_c, ast.Call) and isinstance(_c.func, ast.Name)
                and _c.func.id == "append_jsonl" for _c in ast.walk(_n))
            if not _has_call:
                continue
            _guarded += 1
            for _ln in _bare_append_in(_n):
                _naked.append((os.path.relpath(_fp, _REPO), _ln))
_check("E11 ★钉子：凡 append_jsonl 被 except OSError 覆盖的 try，其调用必须**消费返回值**"
       "（裸调用即转红——#326-④ 改失败契约后曾一次性静默 15 条通路）",
       _naked == [], _naked)
_check("E12 钉子非空转：确实扫到了覆盖 append_jsonl 的 try 块（≥15 处）",
       _guarded >= 15, _guarded)

# —— B 面的非恒真对照 ——
_check("K08 源头记账不得误伤成功路径（正常写入后 APPEND_FAILURES 不变）",
       (lambda n: _append(_p("bok"), {"ok": 1}) is True
        and fsutil.APPEND_FAILURES == n)(fsutil.APPEND_FAILURES), fsutil.APPEND_FAILURES)
_check("K09 源头告警**有界**（样本与 stderr 告警都不随失败次数无限增长）",
       len(fsutil._APPEND_FAIL_SAMPLES) <= fsutil._APPEND_FAIL_SAMPLE_CAP
       and fsutil._APPEND_FAIL_WARN_CAP == fsutil._APPEND_FAIL_SAMPLE_CAP,
       (len(fsutil._APPEND_FAIL_SAMPLES), fsutil._APPEND_FAIL_WARN_CAP))

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #326-④ 结果：%d 失败" % len(FAILS))
else:
    print("issue #326-④ 结果：全部通过")

# ---------------------------------------------------------------- 定点变异表
# 锚点跨行用 chr(10) 拼接；_apply_text 按目标文件**实际行尾**折算（fsutil.py 为 CRLF）。
_OLD_BODY = chr(10).join([
    "    d = os.path.dirname(os.path.abspath(path)) or \".\"",
    "    os.makedirs(d, exist_ok=True)",
    "    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)",
    "    try:",
    "        os.write(fd, line.encode(\"utf-8\"))",
    "    finally:",
    "        os.close(fd)",
])
_NEW_BODY = chr(10).join([
    "    d = os.path.dirname(os.path.abspath(path)) or \".\"",
    "    try:",
    "        os.makedirs(d, exist_ok=True)",
    "        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)",
    "    except OSError as e:",
    "        return _note_append_failure(path, e)",
    "    try:",
    "        os.write(fd, line.encode(\"utf-8\"))",
    "        return True",
    "    except OSError as e:",
    "        return _note_append_failure(path, e)",
    "    finally:",
    "        try:",
    "            os.close(fd)",
    "        except OSError:",
    "            pass",
])
_SUCCESS = chr(10).join([
    "        os.write(fd, line.encode(\"utf-8\"))",
    "        return True",
])

_MUTATIONS = (
    # M1 回缺陷（原实现：只有 try/finally、无 except）⇒ 三条模拟腿与真实 OSError 全部击穿上抛
    #（A04/A06/A07），成功路径返回 None（A01/A02/A03/A11/K01/K02/K06/K07 的 is True 断言随之转红）。
    # A08/A09/A10（BaseException/编程错误上抛）两态皆抛 ⇒ 恒绿（如实）；
    # K02/K03/K05 只判**内容**不判返回值 ⇒ 两态皆绿（如实：本变异不改写入内容）。
    ("M1 回缺陷：去掉 except（OSError 击穿公开 API）", "md_cg/fsutil.py",
     ((_NEW_BODY, _OLD_BODY),),
     ("A01", "A02", "A03", "A04", "A05", "A06", "A07", "A11", "A12", "A13",
      "K01", "K06", "K07", "K08")),
    # M2 过度收紧：成功路径也返回 False（写失败与写成功不再可分辨）⇒ 一切「成功必须 True」的
    # 断言转红；失败面（A04–A07）本就走 False ⇒ 恒绿（如实）；K02/K03/K05 只判内容 ⇒ 恒绿（如实）。
    ("M2 过度收紧：成功路径也返回 False", "md_cg/fsutil.py",
     ((_SUCCESS, chr(10).join([_SUCCESS.split(chr(10))[0], "        return False"])),),
     ("A01", "A02", "A03", "A11", "K01", "K06", "K07", "K08")),
    # M3 过度放宽：兜 BaseException（把 KeyboardInterrupt/SystemExit 也吞掉）⇒ A08/A09 转红；
    # 其余断言不看这两条路径 ⇒ 恒绿（如实）。
    # M4 钉子回退：把某一处调用点改回**裸调用**（返回值被丢弃）⇒ E11 立即转红——
    # 这正是「后来者再让某处靠异常拿信号」时会被当场抓住的那条钉子。
    ("M4 钉子回退：调用点改回裸调用（返回值被丢弃）", "md_cg/reconcile.py",
     (("        _ok = append_jsonl(trace_path(cg), record)",
       "        append_jsonl(trace_path(cg), record)"),),
     ("E11",)),
    # M5 源头记账回退：_note_append_failure 不再累加 ⇒ B 面失效（失败又变静默）⇒ A12 转红；
    # A13 仍绿（本变异只去掉计数，样本追加那一行未动——如实：样本面与计数面是两处）。
    ("M5 源头记账回退：写失败不再累加计数", "md_cg/fsutil.py",
     (("    APPEND_FAILURES += 1", "    pass   # 变异：不再累加"),),
     ("A12",)),
    ("M3 过度放宽：兜 BaseException（吞掉中断与退出）", "md_cg/fsutil.py",
     ((_NEW_BODY, _NEW_BODY.replace("except OSError as e:", "except BaseException as e:")),),
     ("A08", "A09")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss326d_mut_")
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
                         "md_cg.test_issue326_append_jsonl_oserror"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把失败契约改回缺陷/过度收紧/过度放宽形态，守卫必须按指定项转红")
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
