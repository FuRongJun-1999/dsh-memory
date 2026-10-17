# -*- coding: utf-8 -*-
# 功能名：队列写入失败不得静默（issue #426-C：inbox/decisions 落盘失败仍回执「已入审核队列——不需要重试」）
# 生效条件：python -u -X utf8 -m md_cg.test_issue426c_enqueue_not_silent [--mutate]；被测面＝md_cg/fsutil.py 的 append_jsonl(strict=) + md_cg/mdcos.py 的三处队列写入（入队/裁决/级联）
# 子功能：A 组＝正向腿（**失败路径**：注入不可写队列路径 ⇒ 抛错、不返回 pid、**失败被记账**）；K 组＝反向腿①（成功路径逐位不回归 + **strict=False 旧语义逐位不变**（126 处基数）+ 显式 strict 恰 3 处 AST 断言）；E 组＝源码面（strict 分支先记账再抛）；M 组＝反向腿②（--mutate，红项严格相等且不重叠）
# 执行：--mutate 时在镜像树里逐条撤 strict／撤记账，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符，锚点未命中即 fail-closed
# 不适用条件：① 腿看不见「真实磁盘满 / 只读介质 / 权限拒绝」的**全部分支**——只能注入已知失败形态（本次用「路径不可创建」这一真实 OSError 分支）；② 不覆盖**跨进程**下别的写者把 jsonl 删掉的情形（属进程内一致性边界）；③ 不覆盖 `md_cg/` 外的两个调用点（scripts/ 两处，保持默认 strict=False，行为由 K 组代表点断言覆盖）；④ 不判审计行内容与上限（属 U13）。
# 形态名（供按名检索）：⑤ 「**并列读数不得拼因果**」——同一份报告里的两个读数变化（本例：红 171→172 与 豁免 2096→2095）**必须各自定位来源**，不得归成一个因（我写成「一条从豁免变红」，Lead 照抄进派单 ⇒ 链条上多传一手错）。同族：把「相关」当「因果」、把「同时发生」当「同一件事」。
# 形态名（供按名检索）：④ 「**空转假绿**」——操作没落盘，回执却报成功（本例：入队失败仍回 `moved_to=review_queue` +「不需要重试」）。判据面上的同族是「写了却没生效」。
"""issue #426-C 守卫：不能丢的队列写入必须「失败即响」。

病象（修前）：`fsutil.append_jsonl` 早就返回 bool，但 `mdcos` 的三处队列写入
（`inbox_log` 入队 / `decisions_log` 裁决 / 裁决级联）**都不读返回值** ⇒ 落盘失败时
仍返回 pid 并构造「已入审核队列——不需要重试」的成功回执（**空转假绿**）。
修法（两半同批；**跨槽回触声明**：U06 槽内回触 U05 面的三处消费点；理由＝修点(U06)
与消费面(U05)是同一件事的两半，只改一半零行为变化）：
  · U06 半：`append_jsonl(path, record, strict=False)` —— 语义成文在**一处**（不让每个
    调用方各自 if）；strict 时**先记账再上抛**；
  · U05 半：三处队列写入走 strict；失败 ⇒ 回执构造不出来（异常按仓内既有「异常」编码上行，
    **不新增第四种失败编码**）。
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss426c_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore", "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
os.environ.pop("MDCG_READ_CACHE", None)

from md_cg import fsutil as _fs                      # noqa: E402
from md_cg import tokens as _tk                       # noqa: E402
from md_cg.mdcos import MdCGSecure                    # noqa: E402
from md_cg.security import Principal                  # noqa: E402

PASSED, FAILS = [], []
def _readonly_queue(tag):
    """真实失败注入：建一个**只读**文件当队列——读取/前置都正常，写才失败（Windows PermissionError）。"""
    p = os.path.join(_TMP, "ro_%s.jsonl" % tag)
    with open(p, "w", encoding="utf-8") as f:
        f.write("")
    os.chmod(p, 0o444)
    return p


def _pid_of(r):
    return r if isinstance(r, str) else ((r or {}).get("pid") if isinstance(r, dict) else None)


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240])
        FAILS.append(name)


def _ccg(v="队列探针"):
    return ("# 功能名：" + v + chr(10) + "# 生效条件：任何会话" + chr(10)
            + "# 子功能：" + v + chr(10) + "# 执行：" + v + chr(10)
            + "# 验证方式：外部裁决" + chr(10) + "# 不适用条件：无")


def _cg(root):
    sp = _tk.role_spec("designer")
    return MdCGSecure(root, principal=Principal(
        actor="q426c", clearance="secret", can_write=sp["can_write"], can_admin=True,
        role="designer", layers_allow=sp["layers_allow"], ops_allow=sp["ops_allow"]),
        autoflush=1)


def _raise_kind(fn):
    """返回 (是否抛, 异常类名, 返回值)。"""
    try:
        return False, None, fn()
    except OSError as e:
        return True, type(e).__name__, None
    except Exception as e:                              # noqa: BLE001
        return True, type(e).__name__, None


def group_a(tmp):
    print("== A 组：正向腿（失败路径）——队列写不进去就必须响 ==")
    root = os.path.join(tmp, "a")
    cg = _cg(root)
    good_inbox = cg.inbox_log
    cg.inbox_log = _readonly_queue("inbox")              # 注入真实失败（只读文件）
    n0 = _fs.APPEND_FAILURES
    raised, kind, ret = _raise_kind(lambda: cg.propose("q426c_a", _ccg("入队失败探针"),
                                                       info=True))
    _check("A1 入队落盘失败 ⇒ 抛错（不再返回 pid）",
           raised and ret is None, "raised=%s kind=%s ret=%r" % (raised, kind, ret))
    _check("A2 **失败被记账**（不静默：APPEND_FAILURES 增长）",
           _fs.APPEND_FAILURES > n0, "before=%s after=%s" % (n0, _fs.APPEND_FAILURES))
    cg.inbox_log = good_inbox
    ok2, _k2, r2 = _raise_kind(lambda: cg.propose("q426c_b", _ccg("正常入队"), info=True))
    pid = _pid_of(r2)
    _check("A3 恢复可写后正常入队 ⇒ 返回 pid（成功路径不回归）",
           (not ok2) and isinstance(pid, str) and pid.startswith("prop_"), "r=%r" % (r2,))
    good_dec = cg.decisions_log
    cg.decisions_log = _readonly_queue("decisions")      # 裁决面注入失败
    raised3, kind3, ret3 = _raise_kind(lambda: cg.review_decide(pid, "accept", reason="ok"))
    _check("A4 裁决落盘失败 ⇒ 抛错（不返回「已裁决」回执）",
           raised3 and ret3 is None, "raised=%s kind=%s ret=%r" % (raised3, kind3, str(ret3)[:60]))
    cg.decisions_log = good_dec
    rows = []
    if os.path.exists(cg.decisions_log):
        with open(cg.decisions_log, encoding="utf-8") as f:
            rows = [ln for ln in f if ln.strip()]
    _check("A5 失败那次**没有**落进 decisions（不留半条记录）", len(rows) == 0, "rows=%d" % len(rows))
    cg.close()


def group_k(tmp):
    print("== K 组：反向腿①——成功路径不回归 / strict=False 旧语义逐位不变 ==")
    root = os.path.join(tmp, "k")
    cg = _cg(root)
    r1 = cg.propose("q426c_k1", _ccg("成功路径"), info=True)
    pid = _pid_of(r1)
    _check("K1 成功入队：返回 pid 且 rec 落盘（逐位形态不变）",
           isinstance(pid, str) and pid.startswith("prop_") and os.path.exists(cg.inbox_log),
           "r=%r inbox=%s" % (r1, cg.inbox_log))
    r2 = cg.propose("q426c_k1", _ccg("成功路径"), info=True)   # 同内容 ⇒ 幂等 dedup
    _check("K2 同内容再次入队 ⇒ 幂等返回同一 pid（既有 dedup 分支不变）",
           _pid_of(r2) == pid and bool((r2 or {}).get("dedup")), "p1=%s r2=%r" % (pid, r2))
    cg.close()
    n0 = _fs.APPEND_FAILURES
    _ro = _readonly_queue("legacy")
    ok, kind, ret = _raise_kind(lambda: _fs.append_jsonl(_ro, {"a": 1}))
    _check("K3 **strict=False 旧语义逐位不变**：不可写路径下返回 False 且不抛",
           (not ok) and ret is False, "raised=%s ret=%r" % (ok, ret))
    _check("K4 旧语义同样记账（既有 best-effort 记账面未退化）",
           _fs.APPEND_FAILURES > n0, "before=%s after=%s" % (n0, _fs.APPEND_FAILURES))


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _strict_sites():
    tot = st = 0
    sites = []
    for base, dirs, files in os.walk(_REPO):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__",
                                                ".tmp", ".pytest_cache")]
        for f in files:
            if not f.endswith(".py") or f == "test_issue426c_enqueue_not_silent.py":
                continue                      # 本守卫自身含 1 处对照调用，不计入基数
            p = os.path.join(base, f)
            try:
                tree = ast.parse(_src(os.path.relpath(p, _REPO)), p)
            except Exception:                          # noqa: BLE001
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and (
                        (getattr(node.func, "attr", None) or getattr(node.func, "id", None))
                        == "append_jsonl"):
                    tot += 1
                    if any(k.arg == "strict" and getattr(k.value, "value", None) is True
                           for k in node.keywords):
                        st += 1
                        sites.append("%s:%d" % (os.path.relpath(p, _REPO).replace(os.sep, "/"),
                                                node.lineno))
    return tot, st, sorted(sites)


def group_e(tmp):
    print("== E 组：源码面——strict 入口与恰 3 处调用点 ==")
    tot, st, sites = _strict_sites()
    print("  NOTE E1 读数：显式 strict=True 调用点 = %d 处 %s（总数 %d）" % (st, sites, tot))
    joined = "\n".join(sites)
    _check("E1a 入队站点走 strict（mdcos 的 inbox_log 写入）",
           any(":2647" in s or ":2648" in s or ":2649" in s or ":2650" in s for s in sites)
           or len(sites) == 3, "sites=%s" % sites)
    _check("E1b 裁决站点走 strict", len(sites) >= 2, "sites=%s" % sites)
    _check("E1c 级联站点走 strict（第三个静默点一并收口）", len(sites) >= 3, "sites=%s" % sites)
    _check("E2 三处都在 md_cg/mdcos.py（入队/裁决/级联）",
           all(s.startswith("md_cg/mdcos.py:") for s in sites), "sites=%s" % sites)
    # E3 是**读数**不是门（基数随新增守卫/新写点自然变化，钉死会变成「为数字而红」；
    # 向后兼容由 K3/K4 的**行为对照**证明——那才是判据）：
    print("  NOTE E3 调用点读数：总数=%d 显式 strict=%d 保持默认(strict=False)=%d"
          "（本守卫自身那 1 处对照调用不计入）" % (tot, st, tot - st))
    src = _src("md_cg/fsutil.py")
    fn = None
    for node in ast.walk(ast.parse(src, "fsutil.py")):
        if isinstance(node, ast.FunctionDef) and node.name == "append_jsonl":
            fn = node
    strict_raises = 0
    note_calls = 0
    for node in ast.walk(fn) if fn is not None else []:
        if isinstance(node, ast.Raise):
            strict_raises += 1
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_note_append_failure":
            note_calls += 1
    _check("E4 fsutil.append_jsonl 内：记账调用 2 处（两个 OSError 分支各一）+ raise 2 处（strict 各一）",
           note_calls == 2 and strict_raises == 2, "note=%d raise=%d" % (note_calls, strict_raises))


def _guard_group(tag, fn, tmp):
    try:
        fn(tmp)
    except Exception as exc:                              # noqa: BLE001
        import traceback
        _check("%s0 组内异常（fail-closed：异常即红）" % tag, False,
               "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()


def main():
    print("== #426-C 队列入队/裁决不得静默守卫 ==")
    _guard_group("A", group_a, _TMP)
    _guard_group("K", group_k, _TMP)
    _guard_group("E", group_e, _TMP)
    print("=" * 68)
    print("#426-C 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


_MUTATIONS = (
    ("M1 撤三处消费面的 strict（回到 #426-C 病象：失败静默）",
     "md_cg/mdcos.py",
     (("            append_jsonl(self.inbox_log, rec, strict=True)",
       "            append_jsonl(self.inbox_log, rec)"),
      ("            # issue #426-C：紧邻注释自称「裁决记录不能丢」，修前却不读返回值 ⇒ 现走 strict。" + chr(10)
       + "            append_jsonl(self.decisions_log, rec, strict=True)",
       "            # issue #426-C：紧邻注释自称「裁决记录不能丢」，修前却不读返回值 ⇒ 现走 strict。" + chr(10)
       + "            append_jsonl(self.decisions_log, rec)"),
      ("                append_jsonl(self.decisions_log, rec, strict=True)",
       "                append_jsonl(self.decisions_log, rec)")),
     ("A1", "A4", "E1a", "E1b", "E1c")),
    ("M2 撤 fsutil 的记账（strict 分支直接抛，不记账 = 失败静默）",
     "md_cg/fsutil.py",
     (("        _note = _note_append_failure(path, e)" + chr(10)
       + "        if strict:" + chr(10)
       + "            raise                      # strict：失败必须让调用方看见（先记账，再上抛）" + chr(10)
       + "        return _note",
       "        if strict:" + chr(10)
       + "            raise" + chr(10)
       + "        return _note_append_failure(path, e)"),),
     ("A2",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss426c_mut_")
    for name in ("md_cg", "lib"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
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
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT", "MDCG_TOKEN", "MDCG_TOKEN_FILE"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.test_issue426c_enqueue_not_silent"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _apply_text(text, rel, pairs):
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _mutate():
    print("!! 反向腿②：撤 strict／撤记账，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-20:]))
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
            for root, _dd, _ff in os.walk(tree):
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
                for r in reds2[:10]:
                    print("        FAIL " + r)
        print("反向腿②：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
