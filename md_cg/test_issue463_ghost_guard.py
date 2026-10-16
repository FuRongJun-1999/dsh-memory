# -*- coding: utf-8 -*-
# 功能名：幽灵条目摘除的受保护闸（issue #463）——refindex/reconcile 不得无闸 _unstage 受保护节点
# 生效条件：python -X utf8 -m md_cg.test_issue463_ghost_guard [--mutate]；
#           被测面＝md_cg/refindex.py::_ghost_protected/_partition_ghosts/prune_dangling 与
#           md_cg/reconcile.py::reconcile_state(apply=True) 的 ghost 摘除段
# 子功能：A 组＝prune_dangling（实跑+dry_run 分流）；B 组＝reconcile（apply+dry-run）；
#         K 组＝非恒真对照（非保护照常摘、文件仍在不动、层保护保留）；E 组＝源码钉子
# 执行：--mutate 时就地短路一条判据（撤两处保护闸 / 过度收紧 / 删透出键），指定断言须恰好转红
# 不适用条件：不判 _unstage 本身（基础原语，其它删除流程另行接线）；不判 soft-delete 的可 restore 面
"""issue #463 守卫：幽灵摘除无 guard_forget。

病象（修前）：受保护（importance≥0.7 / 层保护 self·anchor）的 code/doc 节点被外部删掉
.md 后成为「幽灵态」（索引条目仍在），refindex._drop_ghosts 与 reconcile 的 ghost 摘除段
直接 _unstage——无 guard、无快照、无审计、不可逆；同节点走 _forget_many→forget 则被
guard_forget 拦下，两面口径分叉。

修复语义：摘除前过 protect.is_protected（层保护 / 显式保护位 / 按分保护）；受保护或
判定异常（fail-closed）者保留条目并透出（prune 的 skipped_protected / reconcile 的
kept_protected），其余照旧摘除。缺省行为对非保护 ghost 逐位不变。
"""
from __future__ import annotations

import ast
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_CHECKS = []
FAILS = []


def _check(name, cond, detail=""):
    if name not in _CHECKS:
        _CHECKS.append(name)
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _fresh(prefix="iss463_"):
    from md_cg.mdcg import MdCG
    d = tempfile.mkdtemp(prefix=prefix)
    cg = MdCG(os.path.join(d, "cg"))
    return d, cg


def _make_ghost(cg, nid):
    os.remove(os.path.join(cg.root, cg.index["nodes"][nid]["path"]))


def _write_pair(cg, layer_prot=False):
    cg.add("g_prot", "protected code ghost body", layer="knowledge",
           tags=["code"], importance=0.9)
    cg.add("g_plain", "plain code ghost body", layer="knowledge",
           tags=["code"], importance=0.3)
    if layer_prot:
        cg.add("g_layer", "anchor layer code ghost body", layer="anchor",
               tags=["code"])
    cg.flush()


def _assertions():
    from md_cg import refindex, reconcile
    print("== A 组：refindex.prune_dangling 分流 ==")
    d, cg = _fresh()
    try:
        _write_pair(cg, layer_prot=True)
        _check("A01 前提：三节点均在索引（受保护/非保护/层保护）",
               all(n in cg.index["nodes"] for n in ("g_prot", "g_plain", "g_layer")))
        for n in ("g_prot", "g_plain", "g_layer"):
            _make_ghost(cg, n)
        rep = refindex.prune_dangling(cg)
        skipped = {x.get("node_id") for x in (rep.get("skipped_protected") or [])}
        _check("A02 ★行：非保护幽灵照常摘除（g_plain）",
               "g_plain" not in cg.index["nodes"]
               and "g_plain" in (rep.get("ghost_pruned") or []), rep)
        _check("A03 ★行：按分保护幽灵保留（g_prot）并点名原因",
               "g_prot" in cg.index["nodes"] and "g_prot" in skipped
               and any("importance" in (x.get("error") or "") for x in rep.get("skipped_protected") or []),
               rep)
        _check("A04 ★行：层保护幽灵保留（g_layer）",
               "g_layer" in cg.index["nodes"] and "g_layer" in skipped, rep)
        d2, cg2 = _fresh()
        try:
            _write_pair(cg2)
            _make_ghost(cg2, "g_prot")
            _make_ghost(cg2, "g_plain")
            rep_d = refindex.prune_dangling(cg2, dry_run=True)
            sk_d = {x.get("node_id") for x in (rep_d.get("skipped_protected") or [])}
            _check("A05 ★行：dry_run 同样分流（受保护不入计划、非保护入计划）",
                   "g_prot" in sk_d and "g_plain" in (rep_d.get("ghost_pruned") or [])
                   and "g_plain" not in sk_d, rep_d)
            _check("A06 dry_run 零写：两者条目都还在",
                   all(n in cg2.index["nodes"] for n in ("g_prot", "g_plain")))
        finally:
            cg2.close()
            shutil.rmtree(d2, ignore_errors=True)
    finally:
        cg.close()
        shutil.rmtree(d, ignore_errors=True)

    print("== B 组：reconcile_state 幽灵摘除分流 ==")
    d3, cg3 = _fresh()
    try:
        _write_pair(cg3)
        _make_ghost(cg3, "g_prot")
        _make_ghost(cg3, "g_plain")
        _err3 = io.StringIO()
        with contextlib.redirect_stderr(_err3):
            rep3 = reconcile.reconcile_state(cg3, apply=True)
        _warn3 = _err3.getvalue()
        _check("B01 ★行：受保护幽灵进 kept_protected、未被摘",
               rep3.get("kept_protected") == ["g_prot"]
               and "g_prot" in cg3.index["nodes"], rep3)
        _check("B02 ★行：非保护幽灵照常摘除（unstaged=1）",
               "g_plain" not in cg3.index["nodes"]
               and (rep3.get("repaired") or {}).get("unstaged") == 1, rep3)
        _check("B04 ★行：告警如实标注「受保护·保留，未摘除」",
               "受保护·保留，未摘除）: g_prot" in _warn3
               and "→摘除）: g_plain" in _warn3, _warn3[-400:])
        d4, cg4 = _fresh()
        try:
            _write_pair(cg4)
            _make_ghost(cg4, "g_prot")
            rep4 = reconcile.reconcile_state(cg4, apply=False)
            _check("B03 dry-run：ghost_entries 检出受保护条目但不动索引",
                   "g_prot" in (rep4.get("ghost_entries") or [])
                   and "g_prot" in cg4.index["nodes"]
                   and (rep4.get("repaired") or {}).get("unstaged", 0) == 0, rep4)
        finally:
            cg4.close()
            shutil.rmtree(d4, ignore_errors=True)
    finally:
        cg3.close()
        shutil.rmtree(d3, ignore_errors=True)

    print("== K 组：非恒真对照 ==")
    d5, cg5 = _fresh()
    try:
        _write_pair(cg5)
        rep5 = refindex.prune_dangling(cg5)          # 文件都在：无 ghost、零摘除
        _check("K01 文件仍在时零 ghost、受保护节点不被误摘",
               (rep5.get("ghosts") in (0, None)) and "g_prot" in cg5.index["nodes"]
               and not (rep5.get("ghost_pruned") or []), rep5)
    finally:
        cg5.close()
        shutil.rmtree(d5, ignore_errors=True)

    print("== E 组：源码钉子 ==")
    with io.open(os.path.join(_REPO, "md_cg/refindex.py"), encoding="utf-8") as fh:
        rg_src = fh.read()
    _check("E01 ★钉子：refindex 保护判定单点用 protect.is_protected",
           "def _ghost_protected" in rg_src and "protect.is_protected(cg, nid)" in rg_src)
    _check("E02 ★钉子：prune_dangling 调用 _partition_ghosts 分流",
           "_partition_ghosts(cg, ghost_plan)" in rg_src)
    with io.open(os.path.join(_REPO, "md_cg/reconcile.py"), encoding="utf-8") as fh:
        rc_src = fh.read()
    _check("E03 ★钉子：reconcile 幽灵摘除前过 protect.is_protected 且透出 kept_protected",
           "protect.is_protected(cg, nid)" in rc_src
           and 'rep["kept_protected"] = kept_protected' in rc_src)


def _run_assertions():
    global FAILS
    FAILS = []
    del _CHECKS[:]
    _assertions()
    print("通过 %d / 失败 %d" % (len(_CHECKS) - len(FAILS), len(FAILS)))
    return len(FAILS)


def _subprocess_fail_names():
    r = subprocess.run([sys.executable, "-X", "utf8", _SELF, "--assert-only"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_REPO, timeout=600)
    names = set(re.findall(r"(?m)^\s*FAIL\s+([A-Z]\d+)", r.stdout or ""))
    return names, (r.stdout or "") + (r.stderr or "")


_ARMS = {
    "M1": (
        "md_cg/refindex.py",
        "        protected, why = _ghost_protected(cg, nid)\n        if protected:\n",
        "        protected, why = _ghost_protected(cg, nid)\n        if False:\n",
        {"A03", "A04", "A05"},
    ),
    "M2": (
        "md_cg/reconcile.py",
        "            if _p:\n                kept_protected.append(nid)\n                continue\n",
        "            if False:\n                kept_protected.append(nid)\n                continue\n",
        {"B01", "B02", "B04"},
    ),
    "M3": (
        "md_cg/refindex.py",
        "        protected, why = _ghost_protected(cg, nid)\n        if protected:\n",
        "        protected, why = _ghost_protected(cg, nid)\n        if True:\n",
        {"A02", "A05"},
    ),
    "M4": (
        "md_cg/reconcile.py",
        '    if kept_protected:\n        rep["kept_protected"] = kept_protected\n',
        "",
        {"B01", "E03"},
    ),
}


def _mutate(argv):
    want = ""
    for a in argv:
        if a == "--mutate":
            want = want or "ALL"
        elif a.startswith("--mutate="):
            want = a.split("=", 1)[1]
    if not want:
        return 0
    ids = sorted(_ARMS) if want == "ALL" else [want]
    red = 0
    for mid in ids:
        if mid not in _ARMS:
            print("[ANCHOR-MISS] %s：未登记该变异臂" % mid)
            return 2
        rel, old, new, expect = _ARMS[mid]
        target = os.path.join(_REPO, *rel.split("/"))
        with open(target, "rb") as fh:
            orig = fh.read()
        try:
            text = orig.decode("utf-8")
            nl = "\r\n" if "\r\n" in text else "\n"
            norm = text.replace("\r\n", "\n")
            _cnt = norm.count(old)
            if _cnt != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）⇒ 无法变异，判据失效"
                      % (mid, _cnt))
                return 2
            with open(target, "wb") as fh:
                fh.write(norm.replace(old, new).replace("\n", nl).encode("utf-8"))
            actual, out = _subprocess_fail_names()
            if actual == expect:
                print("[MUTATE-OK]   %s：指定断言转红 %s" % (mid, sorted(actual)))
            else:
                print("[MUTATE-FAIL] %s：期望红 %s，实际红 %s"
                      % (mid, sorted(expect), sorted(actual)))
                for line in out.splitlines():
                    if line.strip().startswith("FAIL"):
                        print("    " + line)
                red += 1
        finally:
            with open(target, "wb") as fh:
                fh.write(orig)
    print("反证结果：%d 条变异，%s" % (len(ids), "全部恰好命中" if red == 0 else "%d 条未命中" % red))
    return 1 if red else 0


if __name__ == "__main__":
    _f = _run_assertions()
    if "--assert-only" in sys.argv:
        sys.exit(1 if _f else 0)
    _m = _mutate(sys.argv[1:])
    sys.exit(1 if (_f or _m) else 0)
