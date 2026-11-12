# -*- coding: utf-8 -*-
# 功能名：幽灵态摘除不得绕过保护面（issue #463，SEC·P0）
# 生效条件：python -u -X utf8 -m md_cg.test_issue463_ghost_prune_guard [--mutate]；被测面＝refindex._drop_ghosts + prune_dangling 的 ghost 路径 + reconcile 收口点
# 子功能：A 组＝正向（A1 不摘 / A2 记入 _LAST_SKIPPED / A3a 跳过数不多不少 / A4 witness / **A3b+A3c 同一场景的端到端**）；K 组＝反向腿①；E 组＝AST 结构断言；M 组＝反向腿②
# 执行：--mutate 时在镜像树里逐条撤闸，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；红项须与预期逐项相符，锚点未命中即 fail-closed
# 不适用条件：① 看不见「幽灵态是误删还是真删」（按「节点 .md 不存在」判）；② 不覆盖跨进程并发两次摘除；③ reconcile 入口只做源码面 E3（其行为面需接管文件系统）；④ 不判 skipped_protected 排序。
# ★ A3b（闸面：不在 ghost_pruned）与 A3d（合并面：在 skipped_protected）**拆开**：否则一个断言同时覆盖两道改动，M1/M2 必共红它（本波「一个断言承载两个语义」的第二次踩坑）。
# ★ A3d 断言 _LAST_SKIPPED 是 skipped_protected 的**子集**：撤闸时前者为空 ⇒ 子集真空成立（**这是有意的**：
#   本条只测「合并」，不测「闸」（闸由 A3b 测）。**若有人把它改成「含某个具体 id」，就会重新耦合闸与合并，M1/M2 将再次重叠。**
# ★ 本守卫的 A3 曾同时承载「闸侧跳过数」与「合并后含它」两语义 ⇒ M1/M2 共红；拆为 A3a/A3b 后 A3d 又因「含具体 id」重新耦合 ⇒ 再改子集断言。
#   **一个断言承载两个语义，是两个变异共红它的充分原因。**
# ★ 形态名「闸的层级错配」：外层漏 / 内层双重闸且悄悄改写原语语义；正确层＝所有必经路径都过且只过一处。
# ★ M3 用 AST 而非行为变异：双重闸行为上无害（no-op）⇒ 行为面不可分辨；本条防「有人把闸挪进原语」。
# ★ M1 红 {A1,A2,A3a,A4,E2,K2} 中 A4/K2 是**连带**（撤闸后两个都摘 ⇒ witness 变、计数变 0），独立面是 A1/A2/A3a/E2。
# ★ A3a/A3b 拆分原因：一个断言承载两个语义（_drop_ghosts 侧跳过数 vs 调用点合并后返回字典）必让两个变异共红它。
# ★ **M2 曾是不合格的「半条变异」**（A3b 原为源码面断言）；现 A3b/A3c 改为**同一次 prune_dangling 的端到端**断言 ⇒ M2 合格。
"""issue #463 守卫：幽灵摘除的保护闸。"""
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

_TMP = tempfile.mkdtemp(prefix="iss463_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore", "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
os.environ.pop("MDCG_READ_CACHE", None)

from md_cg import protect as _p                  # noqa: E402
from md_cg import refindex as _ri                # noqa: E402
from md_cg.mdcg import MdCG                      # noqa: E402

PASSED, FAILS = [], []
_N = [0]


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name); PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240]); FAILS.append(name)


def _ccg(v):
    return "# 功能名：" + v + chr(10) + "# 不适用条件：无"


def _lib():
    _N[0] += 1
    cg = MdCG(os.path.join(_TMP, "lib%d" % _N[0]))
    cg.add("code_anchor", _ccg("受保护"), layer="knowledge", importance=0.9, tags=["code"])
    cg.add("code_free", _ccg("自由"), layer="knowledge", importance=0.3, tags=["code"])
    cg.flush()
    return cg


def _snap_audit(cg, nid):
    d = os.path.join(cg.root, _p.HISTORY_DIR, nid)
    n_snap = len(os.listdir(d)) if os.path.isdir(d) else 0
    ap = os.path.join(cg.root, _p.AUDIT_FILE)
    n_aud = 0
    if os.path.exists(ap):
        with open(ap, encoding="utf-8") as f:
            n_aud = len([l for l in f if nid in l])
    return n_snap, n_aud


def group_a():
    print("== A 组：正向 ==")
    cg = _lib()
    dropped = _ri._drop_ghosts(cg, ["code_anchor", "code_free"])
    skipped = list(getattr(_ri, "_LAST_SKIPPED", []))
    _check("A1 受保护 ghost 不被摘（仍在索引）", "code_anchor" in cg.index["nodes"])
    _check("A2 受保护 ghost 记入 _LAST_SKIPPED", "code_anchor" in skipped, "skipped=%r" % (skipped,))
    _check("A3a 跳过数不多不少：==1 且恰是它", len(skipped) == 1 and skipped[0] == "code_anchor",
           "skipped=%r" % (skipped,))
    _check("A4 witness：非受保护 ghost 照常被摘",
           dropped == ["code_free"] and "code_free" not in cg.index["nodes"], "dropped=%r" % (dropped,))
    cg.close()
    # A3b/A3c **同一次** prune_dangling（ghost 判据＝索引条目有 code/doc 标签且 path 指向不存在文件）
    cg2 = _lib()
    for _n2 in ("code_anchor", "code_free"):
        cg2.index["nodes"][_n2]["path"] = "gone_" + _n2 + ".py"
    e2e = _ri.prune_dangling(cg2, dry_run=False)
    gp = list(e2e.get("ghost_pruned") or [])
    sp = list(e2e.get("skipped_protected") or [])
    _check("A3b 端到端（闸面）：受保护 ghost 不在 ghost_pruned",
           "code_anchor" not in gp, "ghost_pruned=%r" % (gp[:4],))
    _check("A3d 端到端（合并面，**与闸解耦**）：_LAST_SKIPPED 是 skipped_protected 的子集",
           set(list(getattr(_ri, "_LAST_SKIPPED", []))) <= set(sp), "sp=%r" % (sp[:4],))
    _check("A3c 端到端 witness：非受保护 ghost 被摘（同一场景，防「全不摘」也能过 A3b）",
           "code_free" in gp, "ghost_pruned=%r" % (gp[:4],))
    cg2.close()


def group_k():
    print("== K 组：反向腿① ==")
    cg = _lib()
    _ri._drop_ghosts(cg, ["code_anchor"])
    n_snap, n_aud = _snap_audit(cg, "code_anchor")
    _check("K1 受保护被跳过时：快照数==0 且审计数==0（防「摘了又恢复」）",
           n_snap == 0 and n_aud == 0, "snap=%d audit=%d" % (n_snap, n_aud))
    try:
        _p.guard_forget(cg, "code_anchor"); raised = False
    except _p.ProtectionError:
        raised = True
    _check("K2 guard_forget 本体对受保护仍拦（不回归）", raised)
    _check("K3 对照：非受保护不拦（防全拦）", _p.guard_forget(cg, "code_free") is None)
    cg.close()


def _src(rel):
    with open(os.path.join(_REPO, "md_cg", rel), encoding="utf-8") as f:
        return f.read()


def _fn(rel, name):
    for node in ast.walk(ast.parse(_src(rel), rel)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _calls(fn, name):
    if fn is None:
        return []
    return [x for x in ast.walk(fn) if isinstance(x, ast.Call)
            and (getattr(x.func, "attr", None) or getattr(x.func, "id", None)) == name]


def group_e():
    print("== E 组：AST 结构断言 ==")
    un = _fn("mdcg.py", "_unstage")
    _check("E1 【M3 的 AST 替代】_unstage 体内不含 guard_forget",
           un is not None and len(_calls(un, "guard_forget")) == 0,
           "calls=%d" % len(_calls(un, "guard_forget")))
    dg = _fn("refindex.py", "_drop_ghosts")
    _check("E2 _drop_ghosts 体内有 guard_forget（闸在位）",
           len(_calls(dg, "guard_forget")) == 1, "calls=%d" % len(_calls(dg, "guard_forget")))
    _check("E3 reconcile 收口点有 guard_forget（源码面）", "guard_forget" in _src("reconcile.py"))
    pd = _fn("refindex.py", "prune_dangling")
    _check("E4 prune_dangling 体内出现 _LAST_SKIPPED（AST；计数对齐在位）",
           any(isinstance(x, ast.Name) and x.id == "_LAST_SKIPPED"
               for x in ast.walk(pd)) if pd is not None else False)


def _guard(tag, fn):
    try:
        fn()
    except Exception as exc:
        import traceback
        _check("%s0 组内异常（fail-closed）" % tag, False, "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()


def main():
    print("== #463 幽灵摘除保护闸守卫 ==")
    _guard("A", group_a); _guard("K", group_k); _guard("E", group_e)
    print("=" * 68)
    print("#463 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    return 1 if (FAILS or (_mutate() if "--mutate" in sys.argv else 0)) else 0


_MUT = (
    ("M1 撤 _drop_ghosts 的保护闸（回到病象）", "md_cg/refindex.py",
     (("            _prot.guard_forget(cg, nid)", "            pass"),),
     ("A1", "A2", "A3a", "A3b", "A4", "E2", "K2")),
    ("M2 撤调用点的计数对齐（跳过的不并入 skipped_protected）", "md_cg/refindex.py",
     (("    blocked = list(blocked) + [x for x in _LAST_SKIPPED if x not in blocked]", "    pass"),),
     ("A3d", "E4")),
)


def _mirror():
    dst = tempfile.mkdtemp(prefix="iss463_mut_")
    for name in ("md_cg", "lib"):
        s = os.path.join(_REPO, name)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT", "MDCG_TOKEN", "MDCG_TOKEN_FILE"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.test_issue463_ghost_prune_guard"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    return pr.returncode, [l.split("FAIL ", 1)[1].strip() for l in out.splitlines()
                           if l.strip().startswith("FAIL ")], out


def _mutate():
    print("!! 反向腿②（M3 由 E1 的 AST 断言替代）")
    tree = _mirror()
    bad = []
    try:
        rc, reds, out = _run(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("基线即红"); print(chr(10).join(out.splitlines()[-12:]))
        for desc, rel, pairs, exp in _MUT:
            p = os.path.join(tree, rel)
            bak = open(p, encoding="utf-8", newline="").read()
            eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in bak else chr(10)
            mut, miss = bak, ""
            for o, n in pairs:
                o2, n2 = o.replace(chr(10), eol), n.replace(chr(10), eol)
                if mut.count(o2) != 1:
                    miss = "锚点命中 %d 次" % mut.count(o2); break
                mut = mut.replace(o2, n2, 1)
            if miss:
                bad.append(desc); print("  ANCHOR-MISS " + desc + "  " + miss); continue
            open(p, "w", encoding="utf-8", newline="").write(mut)
            for r2, _d, _f in os.walk(tree):
                if os.path.basename(r2) == "__pycache__":
                    shutil.rmtree(r2, ignore_errors=True)
            rc2, reds2, out2 = _run(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望=%s rc=%d" % (desc, hit, sorted(exp), rc2))
                for r in reds2[:6]:
                    print("        FAIL " + r)
        print("反向腿②：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
