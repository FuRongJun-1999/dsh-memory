# -*- coding: utf-8 -*-
# 功能名：保护判据的条目口径单点 + 四类落点收口（issue #431 / #432 / #468；#430 已由 #377 修复，本批只收口其遗留的两份 _FmProbe 副本）
# 生效条件：python -u -X utf8 -m md_cg.test_issue431_432_468_protect_single_point [--mutate]；被测面＝md_cg/protect.py 的 is_protected_entry + is_protected 委派，与 lifecycle/trust/weights/consolidate/forgetting 五处落点
# 子功能：A 组＝四类落点与权威一致 + 两口径同源；K 组＝反向腿①（位支仍拦 / 预演不落盘 / hint 不回归）；E 组＝**AST 结构断言**（is_protected 体内无独立判据实现）；M 组＝反向腿②（逐落点变异，红项严格相等且不重叠）
# 执行：--mutate 时在镜像树里逐条撤「改为走单点」，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符，锚点未命中即 fail-closed
# 不适用条件：① 腿看不见「该节点**本应**属于不可遗忘层」（层归属由写入时决定）；② 腿看不见 `importance_source` 的**真实性**（来源是写入方声明的）；③ 不覆盖 #433（insight.outlook 的私有 0.9 阈值 = **常量未单点**，根因不同，整件单独走）；④ 不覆盖 ev/vb 那条 longterm 理由（#468 是**窄修**，只补按分分支的来源门）。
# 形态名：⑦「**半条变异**」（Lead 定名）——一条变异只让**源码面**变红、行为面不红 ⇒ 它证明的是「代码改了」，不是「行为变了」。判据：**每条变异必须至少红一条行为面断言**；只红源码面 ⇒ **该变异不合格**（不是期望不合格）。
# 自证两条（本波最好的两处）：①「**K1 原是假绿（探针不纯）**」——用 `active→archived` 时先被 `illegal_transition` 拒，追到 `lifecycle.TRANSITIONS` 才查明，改成合法降级的 `active→converged` 后变异才闭合；②「**A5 原先只证明池里没有这些节点，没证明是保护过滤挡掉的**」——产出侧有三道闸、谓词只有一道 ⇒ 改为直接断言谓词 `pool_eligible`。
# 形态名：⑥「**一窄一宽**」——同族判据在两份实现里各漏一个方向（只认位＝窄；漏来源门＝宽），是「同一语义两份实现」的指纹。
"""保护判据单点守卫（U01 批）。

病象：`weights` / `consolidate` / `forgetting._tier_of` 各自读 `e.get("protected")` 位（**窄**：
漏层保护与按分保护），`_tier_of` 的按分分支又**漏 `importance_source` 门**（**宽**：heuristic 高分
被当不可遗忘）——一窄一宽，正是「同一语义两份实现」的指纹。
★ #468 的直接证据（本守卫 A6 引用）：`heuristic 0.9` 节点**权威判「未保护」**，而 `_tier_of`
修前把它判进 `longterm` ⇒ 「**权威口径已对、消费面仍错**」。
修法：`protect.is_protected_entry(fm)` 为条目口径单点（三条真源），`is_protected(cg,nid)` 体内
**只做委派**（两口径同一个函数）；四类落点改为调用它。
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

_TMP = tempfile.mkdtemp(prefix="iss431_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore", "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
os.environ.pop("MDCG_READ_CACHE", None)

from md_cg import consolidate as _cons            # noqa: E402
from md_cg import forgetting as _fg              # noqa: E402
from md_cg import lifecycle as _lc               # noqa: E402
from md_cg import protect as _p                  # noqa: E402
from md_cg import trust as _tr                   # noqa: E402
from md_cg import weights as _w                  # noqa: E402
from md_cg.mdcg import MdCG                      # noqa: E402

PASSED, FAILS = [], []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240])
        FAILS.append(name)


def _ccg(v):
    return "# 功能名：" + v + chr(10) + "# 不适用条件：无"


def _lib(tag):
    root = os.path.join(_TMP, tag)
    cg = MdCG(root)
    cg.add("n_self", _ccg("自我"), layer="self", importance=0.5)
    cg.add("n_mark", _ccg("位标"), layer="knowledge", importance=0.5)
    cg.add("n_free", _ccg("自由"), layer="knowledge", importance=0.5)
    for _i in range(1, 5):          # A5 需要**成簇**才测得出「该排除没排除」
        cg.add("s%d" % _i, _ccg("同簇自我"), layer="self", importance=0.5)
    cg.flush()
    cg.index["nodes"]["n_mark"]["protected"] = True
    return cg


def group_a(tmp):
    print("== A 组：四类落点与权威一致 + 两口径同源 ==")
    cg = _lib("a")
    n = cg.index["nodes"]
    e_self, e_mark, e_free = n["n_self"], n["n_mark"], n["n_free"]
    _check("A1a 两口径同源（self：条目 vs (cg,nid)）",
           _p.is_protected_entry(e_self)[0] == _p.is_protected(cg, "n_self")[0] is True)
    _check("A1b 两口径同源（显式位）",
           _p.is_protected_entry(e_mark)[0] == _p.is_protected(cg, "n_mark")[0] is True)
    _check("A1c 两口径同源（未保护）",
           _p.is_protected_entry(e_free)[0] == _p.is_protected(cg, "n_free")[0] is False)
    _check("A1d 两口径同源（按分 hint / heuristic）",
           _p.is_protected_entry({"importance": 0.8, "importance_source": "hint"})[0] is True
           and _p.is_protected_entry({"importance": 0.9,
                                      "importance_source": "heuristic"})[0] is False)
    _check("A2 lifecycle.stamp 的判据 == 权威（层保护无位节点）",
           _lc._is_protected_fm(e_self) == _p.is_protected_entry(e_self))
    _check("A3 trust.stamp 的判据 == 权威（同节点）",
           _tr._is_protected_fm(e_self) == _p.is_protected_entry(e_self))
    w_self = _w.node_importance(cg, "n_self")
    w_free = _w.node_importance(cg, "n_free")
    _check("A4 weights floor：层保护（无位）节点取保护下限（>=0.70）",
           float(w_self.get("after") or 0) >= 0.69, "after=%r" % (w_self.get("after"),))
    _check("A4b weights 对照：未保护节点仍取普通下限（!= 保护下限）",
           float(w_free.get("after") or 0) < 0.69, "after=%r" % (w_free.get("after"),))
    # induce_memories(cg_or_root, ...) 接受**路径**（内部自建 MdCGOS）⇒ 传 cg.root。
    # **判据面换成谓词**（方案 A）：产出侧有多道闸，谓词只有一道 ⇒ 只有断言谓词，变异才闭合。
    # H-4(a) G1a：从 cg.index 取回的 nodes 必须先取快照再迭代（并发写会 dictionary changed size）。
    _nodes_snap = dict(cg.index["nodes"])
    _self_entries = [(_nid, _nodes_snap[_nid]) for _nid in ("n_self", "s1", "s2", "s3", "s4")]
    ids = [nid for nid, _e in _self_entries if not _cons.pool_eligible(_e, "self")]
    _check("A5 池过滤谓词：5 个层保护（无位）节点全部判为不合格入池",
           len(ids) == 5, "被谓词接受的有=%r" % (ids,) )
    _check("A6 【#468 直接证据】heuristic 0.9 权威判**未保护**而 _tier_of 判 working（不再入 longterm）",
           _p.is_protected_entry({"importance": 0.9, "importance_source": "heuristic"})[0] is False
           and _fg._tier_of({"importance": 0.9, "importance_source": "heuristic"}) == "working",
           "tier=%r" % (_fg._tier_of({"importance": 0.9, "importance_source": "heuristic"}),))
    _check("A6b hint 0.9 仍入 longterm（真源覆盖面未被一刀切）",
           _fg._tier_of({"importance": 0.9, "importance_source": "hint"}) == "longterm")
    cg.close()


def group_k(tmp):
    print("== K 组：反向腿①（位支仍拦 / 预演不落盘 / hint 不回归）==")
    cg = _lib("k")
    fm = dict(cg.index["nodes"]["n_self"])
    # 探针必须**只差保护判据**：active→converged 是合法降级（TRANSITIONS 内、is_downgrade 真），
    # 唯一可能的拒绝理由就是「受保护不接受降级」；用 archived 会先被 illegal_transition 拒掉
    # ⇒ K1 绿是假绿（探针不纯，Lead 指出的正是这条）。
    ok, code, _why = _lc.stamp(fm, "converged")
    _check("K1 位支/层保护仍拦：lifecycle.stamp 对 self 层降级 ⇒ ok=False",
           ok is False, "ok=%r code=%r" % (ok, code))
    before = cg.index["nodes"]["n_self"].get("importance")
    _w.recalc(cg, apply=False)
    after = cg.index["nodes"]["n_self"].get("importance")
    _check("K2 apply=False 纯预演不落盘（importance 未变）",
           float(before or 0) == float(after or 0), "before=%r after=%r" % (before, after))
    _check("K3 hint 高分仍判保护（覆盖面不回归）",
           _p.is_protected_entry({"importance": 0.75, "importance_source": "hint"})[0] is True)
    cg.close()


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _fn(rel, name):
    tree = ast.parse(_src(rel), rel)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def group_e(tmp):
    print("== E 组：AST 结构断言（is_protected 体内无独立判据实现）==")
    fn = _fn("md_cg/protect.py", "is_protected")
    n_cmp = sum(1 for x in ast.walk(fn) if isinstance(x, ast.Compare)) if fn else -1
    n_bool = sum(1 for x in ast.walk(fn) if isinstance(x, ast.BoolOp)) if fn else -1
    _check("E1 is_protected 体内 Compare/BoolOp 节点数 == 0（只允许委派或取 fm）",
           n_cmp == 0 and n_bool == 0, "Compare=%d BoolOp=%d" % (n_cmp, n_bool))
    entry = _fn("md_cg/protect.py", "is_protected_entry")
    e_cmp = sum(1 for x in ast.walk(entry) if isinstance(x, ast.Compare)) if entry else 0
    _check("E2 真源确实在 is_protected_entry 内（Compare 节点 >= 2，防「两边都空」）",
           e_cmp >= 2, "Compare=%d" % e_cmp)
    for tag, rel in (("E3a", "md_cg/lifecycle.py"), ("E3b", "md_cg/trust.py"),
                     ("E3c", "md_cg/weights.py"), ("E3d", "md_cg/consolidate.py")):
        # AST 口径（**注释不计**）：文本口径会被我自己注释里那串函数名骗——本会话已在
        # #439 E2b 栽过一次，U01 批我又栽了一次 ⇒ **结构约束比注意力靠得住**。
        _t = ast.parse(_src(rel), rel)
        _n = sum(1 for _x in ast.walk(_t)
                 if isinstance(_x, ast.Call)
                 and (getattr(_x.func, "attr", None)
                      or getattr(_x.func, "id", None)) == "is_protected_entry")
        _check("%s %s 落点**调用** is_protected_entry 恰 1 处（AST；注释不计）" % (tag, rel.split("/")[-1]),
               _n == 1, "calls=%d" % _n)
    tier = _fn("md_cg/forgetting.py", "_tier_of")
    has_src_gate = any(isinstance(x, ast.Constant) and x.value == "importance_source"
                       for x in ast.walk(tier)) if tier else False
    _check("E4 #468 窄修在位：_tier_of 体内出现 importance_source 门（AST）", has_src_gate)


def _guard_group(tag, fn, tmp):
    try:
        fn(tmp)
    except Exception as exc:                              # noqa: BLE001
        import traceback
        _check("%s0 组内异常（fail-closed：异常即红）" % tag, False,
               "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()


def main():
    print("== U01 批：保护判据单点守卫 ==")
    _guard_group("A", group_a, _TMP)
    _guard_group("K", group_k, _TMP)
    _guard_group("E", group_e, _TMP)
    print("=" * 68)
    print("U01 单点守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


_MUTATIONS = (
    ("M1 撤 is_protected 的委派（在体内内联一份窄判据）",
     "md_cg/protect.py",
     (("    return is_protected_entry(_fm(cg, node_id))",
       "    _f2 = _fm(cg, node_id)" + chr(10)
       + "    return (bool(_f2.get(\"protected\") or _f2.get(\"immutable\")) if _f2 else False), \"\""),),
     ("A1a", "E1")),
    ("M2 撤 lifecycle 的收口（回内联只认位）",
     "md_cg/lifecycle.py",
     (("    return protect.is_protected_entry(fm)   # #431 批：_FmProbe 副本收口到条目口径单点",
       "    return bool(fm.get(\"protected\")), \"\""),),
     ("A2", "E3a", "K1")),
    ("M3 撤 weights 的收口（回内联只认位）",
     "md_cg/weights.py",
     (("    protected = protect.is_protected_entry(e)[0]",
       "    protected = bool(e.get(\"protected\"))"),),
     ("A4", "E3c")),
    ("M4 撤 consolidate 池过滤的收口（回内联只认位）",
     "md_cg/consolidate.py",
     (("        and not protect.is_protected_entry(e)[0] " + chr(92),
       "        and not (e or {}).get(\"protected\") " + chr(92)),),
     ("A5", "E3d")),
    ("M5 撤 _tier_of 的来源门（#468 窄修回退）",
     "md_cg/forgetting.py",
     (("    if (e.get(\"protected\")" + chr(10)
       + "            or (imp >= PROTECT_IMPORTANCE and e.get(\"importance_source\") in (None, \"hint\"))" + chr(10)
       + "            or (ev >= 3 and vb in VERIFIED_BASES)):",
       "    if e.get(\"protected\") or imp >= PROTECT_IMPORTANCE or (ev >= 3 and vb in VERIFIED_BASES):"),),
     ("A6", "E4")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss431_mut_")
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
                         "md_cg.test_issue431_432_468_protect_single_point"],
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
        n_old = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n_old, 1)
    return text, ""


def _mutate():
    print("!! 反向腿②：逐落点撤「改为走单点」，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-15:]))
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
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("反向腿②：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
