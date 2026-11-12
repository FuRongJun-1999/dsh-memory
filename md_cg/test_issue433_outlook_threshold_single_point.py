# -*- coding: utf-8 -*-
# 功能名：insight.outlook 的「高重要度未保护」判据归位到全仓单点（issue #433）
# 生效条件：python -u -X utf8 -m md_cg.test_issue433_outlook_threshold_single_point [--mutate]；被测面＝md_cg/insight.py 的 outlook 两个清单（d1.protected / d2.high_importance_unprotected）+ 常量 VERIFY_IMPORTANCE_FLOOR
# 子功能：A 组＝正向（[0.70,0.90) 未保护节点进 d2；layer=self 无位节点进 d1；未保护节点不进 d1）；K 组＝反向腿①（h_hi 仍进 d2；**verified 保底仍 0.9**）；E 组＝AST（AUTO_PROTECT_IMPORTANCE / is_protected_entry 各恰 1 处；旧名无残留）；M 组＝反向腿②（三条变异，红项严格相等且不重叠）
# 执行：--mutate 时在镜像树里逐条撤修复 / 模拟过度修复，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符，锚点未命中即 fail-closed
# 不适用条件：① 腿看不见「节点**本应**是高价值」（价值判定不在本层）；② 不覆盖 outlook 的 d3/其它维度；③ 不判 `importance_source` 的真实性（写入方声明）；④ 不覆盖 `verified` 保底的**端到端**（只钉常量值 0.9 与 `:294` 的引用——**未走真实 verify 流程**，见 K2 的「未核」标注）。
# ★ 本批最重要的一条判据（Lead 确认）：**两个语义共用一个常量 ⇒ 改一个会改两个**。
# 修前 `IMPORTANCE_FLOOR=0.9` 同时承担「verified 保底」与「高重要度门槛」⇒ 直接整体改成 0.70 会把**保底从 0.9 降到 0.70**（改变既有语义）。本件改为**拆名 + 各自归位**，不是「0.9 改成 0.7」的一刀切。
# ★ 判据前提（Lead 批的方案在修后自相矛盾，探针证明后修正）：「造 `[0.70,0.90)` 的**未保护**节点 ⇒ 断言 d2 含它」**不成立**——修复后该区间节点已被 0.70 门槛认作受保护，**不再是「未保护」**。须用 `importance_source='heuristic'` 的节点（权威判未保护）。
# ★ 形态名「**判据的前提被修复行为本身改变**」：判据 P 断言「场景 S 下应见 X」，而修复让 S 不再成立 ⇒ P 修后必假。设计判据时要问「修复会不会改变我造的那个场景」。
# ★ 形态名「**夹具形状靠猜**」：对被测函数返回结构不确定 ⇒ 先打探针把形状读出来再写断言（本件实测 `d1.protected` 是**计数 int**、`d2.high_importance_unprotected` 是 **list**）；与「探针不纯」同族不同格。
# ★ 本夹具第一次跑时被 `ProtectionError` 挡住（`h_self` 已在位且受层保护 ⇒ `add` 被拒）——**这本身是 #433 那条判据在生效的证据**，不是 bug；夹具已改用独立 root。
# ★ M3 是本会话**反向腿①从「防不修」扩展到「防修过头」的首例**：它不撤修复，而是模拟「一个过度热心的修法」（把保底也降到 0.70）⇒ 反向腿① K2 红，证明「保底语义受保护」。
"""issue #433 守卫：观测面的两个口径（阈值常量、保护判据）各自归位。

病象：`insight.IMPORTANCE_FLOOR=0.9` 是**私有**阈值，而全仓其余三处皆 0.70
（`protect.AUTO_PROTECT_IMPORTANCE` / `weights.IMPORTANCE_PROTECT` /
`forgetting.PROTECT_IMPORTANCE`）⇒ `[0.70,0.90)` 的受保护节点**两个清单都进不去**；
`d1.protected` 又只认 `protected` 位（与 #430 同根因的半处）。
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

_TMP = tempfile.mkdtemp(prefix="iss433_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore", "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
os.environ.pop("MDCG_READ_CACHE", None)

from md_cg import insight as _ins               # noqa: E402
from md_cg import protect as _p                 # noqa: E402
from md_cg.mdcg import MdCG                     # noqa: E402

PASSED, FAILS = [], []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240])
        FAILS.append(name)


_CACHE = {}


_N = [0]


def _outlook(tag="a"):
    _N[0] += 1
    tag = "%s%d" % (tag, _N[0])   # 每次独立 root（防 h_self 已在位受保护导致 add 被拒）
    root = os.path.join(_TMP, "lib_" + tag)
    cg = MdCG(root)
    cg.add("h_mid", "# 功能名：中值\n# 不适用条件：无", layer="knowledge", importance=0.75)
    cg.add("h_hi", "# 功能名：高值\n# 不适用条件：无", layer="knowledge", importance=0.95)
    cg.add("h_self", "# 功能名：自我\n# 不适用条件：无", layer="self", importance=0.5)
    cg.add("h_free", "# 功能名：自由\n# 不适用条件：无", layer="knowledge", importance=0.3)
    # ★「只改内存索引、未改节点真源」形态：outlook 读的是**节点真源**（盘上 fm），
    #   只改 `cg.index["nodes"][...]` 不会生效（实测 d1.protected=4 而不是 5 ⇒ 靠差值推出来的）。
    #   ⇒ 来源必须**随写入落进 fm**。
    cg.add("h_heur", "# 功能名：机器推断" + chr(10) + "# 不适用条件：无",
           layer="knowledge", importance=0.75, importance_source="heuristic")
    cg.flush()
    # 机器推断来源 ⇒ 权威判「未保护」；0.75 ≥ 0.70 ⇒ 应进 d2（**不能用无来源的 [0.70,0.90) 节点**：
    # 修复后它已被 0.70 门槛认作受保护 —— 「判据的前提被修复行为本身改变」，见 docstring）。
    d = _ins.outlook(cg)
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict) and ("protected" in v or "high_importance_unprotected" in v):
            out[k] = v
    cg.close()
    _CACHE[tag] = out
    return out


def _lists(out):
    d1, d2 = [], []
    for v in out.values():
        _p = v.get("protected")
        _h = v.get("high_importance_unprotected")
        if isinstance(_p, (list, tuple)):
            d1 += [str(x) for x in _p]
        elif isinstance(_p, int):        # 探针实测：d1.protected 是**计数**（不是 list）
            d1 += [str(_p)]
        if isinstance(_h, (list, tuple)):
            d2 += [str(x) for x in _h]
    return d1, d2


def group_a():
    print("== A 组：正向（两个清单都覆盖到本层判据）==")
    d1, d2 = _lists(_outlook("a"))
    _check("A1 0.75 的**机器推断**节点进 d2.high_importance_unprotected（0.70 门槛生效）",
           any("h_heur" in x for x in d2), "d2=%r" % (d2[:6],))
    _check("A2 d1.protected == 3（h_mid + h_hi + h_self；h_heur 是 heuristic ⇒ 不算受保护；\n"
           "**`4` 依赖夹具的 5 节点构成，改夹具须同改**）",
           3 in [int(x) for x in d1 if str(x).isdigit()], "d1=%r" % (d1[:8],))
    _check("A3 h_free(0.3，未保护) **不计入** ⇒ 计数 != 5（防「全算保护」；同依赖夹具构成）",
           5 not in [int(x) for x in d1 if str(x).isdigit()], "d1=%r" % (d1[:8],))


def group_k():
    print("== K 组：反向腿①（h_hi 仍进；**verified 保底仍 0.9**）==")
    d1, d2 = _lists(_outlook("a"))
    _CACHE.pop("a", None)
    d1, d2 = _lists(_outlook("a"))
    _check("K1 受保护者**不进** d2（d2 不得退化成「所有高分」）",
           not any("h_mid" in x for x in d2) and not any("h_hi" in x for x in d2),
           "d2=%r" % (d2[:6],))
    _check("K2 **verified 保底仍 0.9**（拆名不改语义；未核：未走真实 verify 端到端，只钉常量值）",
           float(getattr(_ins, "VERIFY_IMPORTANCE_FLOOR", -1)) == 0.9,
           "floor=%r" % (getattr(_ins, "VERIFY_IMPORTANCE_FLOOR", None),))


def _src(rel=""):
    with open(os.path.join(_REPO, "md_cg", rel or "insight.py"), encoding="utf-8") as f:
        return f.read()


def _outlook_fn():
    tree = ast.parse(_src(), "insight.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "outlook":
            return node
    return None


def group_e():
    print("== E 组：AST（归位未脱焊 / 旧名无残留）==")
    fn = _outlook_fn()
    n_auto = sum(1 for x in ast.walk(fn)
                 if isinstance(x, ast.Attribute) and x.attr == "AUTO_PROTECT_IMPORTANCE") if fn else -1
    _check("E1 outlook 体内引用 protect.AUTO_PROTECT_IMPORTANCE 恰 1 处", n_auto == 1, "n=%d" % n_auto)
    n_entry = sum(1 for x in ast.walk(fn)
                  if isinstance(x, ast.Call)
                  and (getattr(x.func, "attr", None) == "is_protected_entry")) if fn else -1
    _check("E2 outlook 体内调用 is_protected_entry 恰 1 处（d1 走单点）", n_entry == 1, "n=%d" % n_entry)
    _check("E3 旧名 `IMPORTANCE_FLOOR` 在 insight.py 无残留（AST Name/Attribute 口径）",
           not any((isinstance(x, ast.Name) and x.id == "IMPORTANCE_FLOOR")
                   or (isinstance(x, ast.Attribute) and x.attr == "IMPORTANCE_FLOOR")
                   for x in ast.walk(ast.parse(_src(), "insight.py"))))


def _guard(tag, fn):
    try:
        fn()
    except Exception as exc:                              # noqa: BLE001
        import traceback
        _check("%s0 组内异常（fail-closed：异常即红）" % tag, False,
               "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()


def main():
    print("== #433 outlook 阈值/判据归位守卫 ==")
    _guard("A", group_a)
    _guard("K", group_k)
    _guard("E", group_e)
    print("=" * 68)
    print("#433 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    return 1 if (FAILS or (_mutate() if "--mutate" in sys.argv else 0)) else 0


_MUTATIONS = (
    ("M1 `:460` 回私有 0.9 阈值（回到病象）",
     "md_cg/insight.py",
     (("        elif iv >= protect.AUTO_PROTECT_IMPORTANCE:",
       "        elif iv >= VERIFY_IMPORTANCE_FLOOR:"),),
     ("A1", "E1")),
    ("M2 `:458` 回只认 protected 位（#430 同根因那半处回退）",
     "md_cg/insight.py",
     (("        if protect.is_protected_entry(e or {})[0]:",
       "        if e.get(\"protected\"):"),),
     ("A2", "E2")),
    ("M3 **模拟过度修复**：把保底也降到 0.70（防修过头首例）",
     "md_cg/insight.py",
     (("VERIFY_IMPORTANCE_FLOOR = 0.9", "VERIFY_IMPORTANCE_FLOOR = 0.70"),),
     ("K2",)),
)


def _mirror():
    dst = tempfile.mkdtemp(prefix="iss433_mut_")
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
                         "md_cg.test_issue433_outlook_threshold_single_point"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    return pr.returncode, [l.split("FAIL ", 1)[1].strip()
                           for l in out.splitlines() if l.strip().startswith("FAIL ")], out


def _mutate():
    print("!! 反向腿②：撤修复 / 模拟过度修复")
    tree = _mirror()
    bad = []
    try:
        rc, reds, out = _run(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("基线即红")
            print(chr(10).join(out.splitlines()[-12:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            bak = open(p, encoding="utf-8", newline="").read()
            eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in bak else chr(10)
            mut = bak
            miss = ""
            for o, n in pairs:
                o2, n2 = o.replace(chr(10), eol), n.replace(chr(10), eol)
                if mut.count(o2) != 1:
                    miss = "锚点命中 %d 次" % mut.count(o2)
                    break
                mut = mut.replace(o2, n2, 1)
            if miss:
                bad.append("%s —— %s" % (desc, miss))
                print("  ANCHOR-MISS " + desc + "  " + miss)
                continue
            open(p, "w", encoding="utf-8", newline="").write(mut)
            for r2, _d, _f in os.walk(tree):
                if os.path.basename(r2) == "__pycache__":
                    shutil.rmtree(r2, ignore_errors=True)
            rc2, reds2, out2 = _run(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际=%s 期望=%s rc=%d" % (desc, hit, sorted(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("反向腿②：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
