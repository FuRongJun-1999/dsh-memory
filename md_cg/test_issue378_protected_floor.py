# -*- coding: utf-8 -*-
# 功能名：freshness 衰减下界与取数面接入既有保护规则（issue #378）
# 生效条件：python -X utf8 -m md_cg.test_issue378_protected_floor [--mutate]；被测面＝md_cg/freshness.py::protected_floor + entry_weight
# 子功能：A 组＝#378 正题（层保护 / 显式位 / 缺省来源高分三条输入共用同一保护下界，且**正常检索取数入口**也吃到）；K 组＝非恒真对照（保护规则两侧边界、公式不变、未保护节点仍触 floor、取数优先级与依据字段不变）；E 组＝接线单点存在性
# 执行：--mutate 时在镜像树里逐条把判据改回改动前形态 / 摘掉取数面漏掉的键 / 过度收紧，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**（多红/少红皆不合格）
# 不适用条件：不判检索总分的排序正确性（属 test_p4_* 与 _score 相关守卫）；不判 Rust 侧 sort_path/freshness.rs（另一实现面，本守卫只盖 Python 面）；不判写入路径与 recalc(apply=True) 的档位闸；不判 weights.IMPORTANCE_PROTECT 的取值（只断言同源）
"""issue #378 守卫：衰减下界必须与**既有保护规则**同源。

病象（修前）：`protected_floor` 只读 `entry["protected"]` 一位 ⇒ `layer` 为
anchor/self 或「缺省来源高分（importance ≥ 0.70）」的节点拿到普通下界
（`SCORE_FLOOR`），衰减可把它们推过保护线——正是本模块 §7.3 要挡的「自动失去
保护」；而 `entry_weight` 的取数键集又漏了 `layer` / `importance_source`，
于是**只改下界函数覆盖不到正常检索入口**（`_score` → `entry_weight` →
`protected_floor`）。

修法：下界判据改为「原显式 `protected` 位 **∪** `protect.is_protected`」
（层保护 self/anchor ∪ 显式位 ∪ 按分保护 ≥0.70 且来源缺省/hint），取数键集补上
`layer` 与 `importance_source`。衰减公式、`IMPORTANCE_PROTECT` 取值、
`refresh_factor` 三档与返回体结构**一律不动**。

**⚠ 这是一次检索行为变更（不是纯 bug fix）**：importance ≥ 0.70 且来源缺省的
节点，其衰减下界从 `0.001` 抬到 `0.70/importance`。本守卫的 K01/K02/K03/K04
把这四条边界**显式钉住**（享有 / 不享有各两侧），使这次变更以测试形式进仓，
而不是只表现为某条既有夹具的修改。

**与 md_cg/test_p4_freshness.py G4 的关系（一轮裁定记录）**：该组原夹具
`{"importance": 0.8}`（无来源标注）按本规则**是受保护节点**，与「未保护节点
不享有下界」的断言前提冲突；经 Lead 裁定补 `"importance_source": "heuristic"`，
断言一字未动。
"""
import inspect
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import freshness as F    # noqa: E402
from md_cg import protect as P      # noqa: E402
from md_cg import weights as W      # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


#: 固定参照时刻（不在役库、不读 wall clock ⇒ 读数可复现）。
REF = 2000000000.0
DAY = F.SECONDS_PER_DAY
#: issue 原文的探针距离：365 天（远超半衰期 ⇒ 衰减项被下界兜住）。
FAR = REF - 365 * DAY
#: 受保护下界期望值：IMPORTANCE_PROTECT / 0.9 = 0.7777…
_PFLOOR_09 = W.IMPORTANCE_PROTECT / 0.9


def _close(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


print("== A 组：#378 正题——三条输入共用同一保护下界 ==")
_v = F.protected_floor({"importance": 0.9, "protected": True})
_check("A01 显式 protected 位（修前既有行为，一字不变）",
       _close(_v, _PFLOOR_09), _v)

_v = F.protected_floor({"importance": 0.9, "layer": "anchor"})
_check("A02 layer=anchor（修前 0.001000，层保护未接线）",
       _close(_v, _PFLOOR_09), _v)

_v = F.protected_floor({"importance": 0.9})
_check("A03 缺省来源高分（修前 0.001000，按分保护未接线）",
       _close(_v, _PFLOOR_09), _v)

_v = F.protected_floor({"importance": 0.9, "layer": "self"})
_check("A04 layer=self 同样受保护（不是 anchor 特例）",
       _close(_v, _PFLOOR_09), _v)

_v = F.protected_floor({"importance": 0.9, "importance_source": None})
_check("A05 来源键显式为 None（＝缺省来源）同样受保护",
       _close(_v, _PFLOOR_09), _v)

# 正常检索入口：_score → entry_weight → protected_floor 的取数面
_w, _why = F.entry_weight({"created_at": FAR, "importance": 0.9,
                           "layer": "anchor"}, now=REF, enabled=True)
_check("A06 取数面接线①：entry_weight 的 floor 依据读数吃到层保护（不是只有下界函数）",
       _close(_why.get("floor"), _PFLOOR_09), (_w, _why))
_check("A07 取数面接线②：365 天后的乘子由 0.001000 回到约 0.777778（issue 原报告探针读数）",
       _close(_w, _PFLOOR_09), _w)

_w2, _why2 = F.entry_weight({}, now=REF, enabled=True,
                            fm={"created_at": FAR, "importance": 0.9,
                                "layer": "anchor"})
_check("A08 fm 覆盖路径同样带上 layer（写面刚落的新值不被取数面丢掉）",
       _close(_why2.get("floor"), _PFLOOR_09), (_w2, _why2))

# 层保护的**唯一**保护来源腿：importance 低于保护线 ⇒ 只有 layer 能救它
_w3, _why3 = F.entry_weight({"created_at": FAR, "importance": 0.5,
                             "layer": "anchor"}, now=REF, enabled=True)
_check("A09 取数面必须带 layer：importance=0.5 的 anchor 节点唯一保护来源是层（下界 1.0）",
       _close(_why3.get("floor"), 1.0), (_w3, _why3))

print("== K 组：非恒真对照（保护规则两侧边界 + 未保护路径不得被关掉） ==")
# —— Lead 强制附加项（#378 是一次检索行为变更，必须显式钉住）：下方 K01–K04 ——
_v = F.protected_floor({"importance": 0.9})
_check("K01 【强制·享有侧】importance≥AUTO_PROTECT_IMPORTANCE(0.70) 且**无 importance_source** → 享有保护下界（与写侧自动保护规则一致）",
       _close(_v, _PFLOOR_09) and _v > F.SCORE_FLOOR, _v)

_v = F.protected_floor({"importance": 0.5})
_check("K02 【强制·不享有侧】importance<0.70 → 不享有（仍是 SCORE_FLOOR）",
       _close(_v, F.SCORE_FLOOR), _v)

_v = F.protected_floor({"importance": 0.9, "importance_source": "heuristic"})
_check("K03 【强制·不享有侧】importance_source 为显式非 hint 来源（heuristic）→ 不享有",
       _close(_v, F.SCORE_FLOOR), _v)

_v = F.protected_floor({"importance": 0.9, "importance_source": "hint"})
_check("K04 【强制·享有侧】importance_source == hint → 享有（边界另一侧）",
       _close(_v, _PFLOOR_09), _v)

_check("K05 规则的唯一权威是 protect.is_protected（本模块不复制）",
       P.AUTO_PROTECT_IMPORTANCE == W.IMPORTANCE_PROTECT
       and _close(P.AUTO_PROTECT_IMPORTANCE, 0.70), P.AUTO_PROTECT_IMPORTANCE)

_v = F.protected_floor({"importance": 0.5, "protected": True})
_check("K06 公式不变：floor == max(SCORE_FLOOR, min(1.0, IMPORTANCE_PROTECT/importance))",
       _close(_v, 1.0), _v)

_v = F.protected_floor({"importance": 0.2, "protected": True})
_check("K07 下界被夹到 ≤1.0（importance<0.70 的受保护节点不衰减，也不放大）",
       _close(_v, 1.0), _v)

# 夹具用低分：高分本身会经**按分保护**触发，测不出层位边界。
_v = F.protected_floor({"importance": 0.5, "layer": "knowledge"})
_check("K08 层保护只认 self/anchor：knowledge 层（低分、无来源）不受保护",
       _close(_v, F.SCORE_FLOOR), _v)

_v = F.protected_floor({})
_check("K09 空映射 / 无任何保护信号 → SCORE_FLOOR（不误判）",
       _close(_v, F.SCORE_FLOOR), _v)

_w4, _why4 = F.entry_weight({"created_at": FAR, "importance": 0.8,
                             "importance_source": "heuristic"},
                            now=REF, enabled=True)
_check("K10 未保护节点在**正常检索入口**仍触 floor（与 test_p4_freshness G4 同型，判别力在位）",
       _close(_w4, F.SCORE_FLOOR) and _close(_why4.get("floor"), F.SCORE_FLOOR),
       (_w4, _why4))

_w5, _why5 = F.entry_weight({"created_at": FAR, "importance": 0.9,
                             "importance_source": "heuristic"},
                            now=REF, enabled=True)
_check("K11 取数面必须带 importance_source：heuristic 不得被误读成缺省来源而认回保护",
       _close(_why5.get("floor"), F.SCORE_FLOOR), (_w5, _why5))

_r5 = F.entry_weight({"created_at": FAR, "importance": 0.9,
                      "importance_source": "heuristic"}, now=REF, enabled=False)
_check("K12 enabled=False 早退仍 (1.0, {'disabled': True})（未受本批扰动）",
       _close(_r5[0], 1.0) and _r5[1] == {"disabled": True}, _r5)

_w6, _why6 = F.entry_weight({"created_at": FAR, "importance": 0.9,
                             "protected": True, "layer": "anchor"},
                            now=REF, enabled=True)
_check("K13 依据 dict 的键集未变（gamma/dt_days/unit/decay/refresh/floor/protected）",
       sorted(_why6) == sorted(["gamma", "dt_days", "unit", "decay", "refresh",
                                "floor", "protected"]), sorted(_why6))

_w7, _why7 = F.entry_weight({"created_at": 0, "importance": 0.9,
                             "layer": "anchor"}, now=REF, enabled=True)
_check("K14 取数优先级未变：缺 created_at 仍判无穷远、由 floor 兜住（不因新键改变口径）",
       _why7.get("dt_days") == float("inf") and _close(_w7, _PFLOOR_09),
       (_w7, _why7))

print("== E 组：接线单点存在性 ==")
_src = inspect.getsource(F.protected_floor)
_check("E01 protected_floor 体内经 _is_protected_entry 接入判据（接线未脱焊）",
       "_is_protected_entry(e)" in _src, [l for l in _src.splitlines()
                                          if "_is_protected_entry" in l])
_check("E02 探针交给 protect.is_protected（判据本体不在本模块复制）",
       "protect.is_protected(" in inspect.getsource(F._is_protected_entry), "")
_src_w = inspect.getsource(F.entry_weight)
_check("E03 entry_weight 取数键集含 layer 与 importance_source",
       '"layer"' in _src_w and '"importance_source"' in _src_w, "")
_probe = F._EntryProbe({"layer": "anchor"})
_check("E04 取数面不读盘：探针提供 get()（保护面回退分支得 None）且无 _maybe_reload_index（检索热路径零 IO）",
       callable(getattr(_probe, "get", None)) and _probe.get("x") is None
       and not hasattr(_probe, "_maybe_reload_index"), "")

print("")
if FAILS:
    print("issue #378 结果：%d 失败" % len(FAILS))
else:
    print("issue #378 结果：全部通过")


_MUTATIONS = (
    ("M1 回缺陷：下界只读显式 protected 位", "md_cg/freshness.py",
     ('    if not (e.get("protected") or _is_protected_entry(e)[0]):',
      '    if not e.get("protected"):'),
     # 机制：旧判据只认显式位 ⇒ 层保护/按分保护两支全断（A 组正题），
     # 依据读数与乘子同步回落 0.001（K01/K04/K14 的享有侧亦随之转红）；
     # E01 是源码形态腿（接线被删即脱焊，本就该红）。
     ("A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09",
      "K01", "K04", "K14", "E01")),
    ("M2 取数面漏键：keys 摘掉 layer / importance_source", "md_cg/freshness.py",
     ('            "protected", "layer", "importance_source")',
      '            "protected")'),
     # 机制：取数面少了 layer ⇒ 层保护的**唯一**来源腿（A09）落到 floor；
     # 少了 importance_source ⇒ heuristic 被误读成缺省来源而认回保护（K10/K11）；
     # E03 是源码形态腿。
     ("A09", "E03", "K10", "K11")),
    ("M3 过度收紧：恒判受保护", "md_cg/freshness.py",
     ('    if not (e.get("protected") or _is_protected_entry(e)[0]):',
      '    if not (e.get("protected") or True):'),
     # 机制：恒判受保护 ⇒ 不享有侧全部被误保护（K 组判别力自证）；
     # E01 是源码形态腿（判据块被整体替换）。
     ("K02", "K03", "K08", "K09", "K10", "K11", "E01")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss378_mut_")
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


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue378_protected_floor"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态 / 摘键 / 过度收紧，守卫必须按指定项转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        bad = []
        for desc, rel, (old, new), exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次" % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:10]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
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
