# -*- coding: utf-8 -*-
# 功能名：trust / lifecycle 的状态降级判据接入层保护（issue #377）
# 生效条件：python -X utf8 -m md_cg.test_issue377_layer_protect_stamp [--mutate]；被测面＝md_cg/trust.py::stamp 与 md_cg/lifecycle.py::stamp（及其 set_state 出口）
# 子功能：A 组＝层保护拦下状态降级（anchor / self，被拒后原状态与原历史均不被改写）；K 组＝非恒真对照（未保护层放行、override 通路仍在、immutable/protected 位照旧、回升不受限、按分保护口径精确共用、隔离库落盘对照）；E 组＝接线单点存在性
# 执行：--mutate 时在镜像树里逐条把判据改回改动前形态 / 过度收紧，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**（多红/少红皆不合格）
# 不适用条件：不判迁移表完备性（属 test_trust / test_lifecycle）；不判 principal 层闸（protect.require_layer）；不覆盖 mcp 工具面令牌面与并发索引代际；不判 freshness 衰减下界（属 issue #378 守卫）
"""issue #377 守卫：状态降级判据必须**共用**既有保护规则 `protect.is_protected`。

病象（修前）：`trust.stamp` 与 `lifecycle.stamp` 用同一条**收窄**判据
`prot = bool(fm.get("protected") or fm.get("immutable"))` —— 只认显式两位，
没有这两个位的 **anchor / self 层**节点照样被降级（trust：verified→doubted；
lifecycle：active→converged），而同一节点在 `protect.is_protected` 眼里是
**不可遗忘**的。两条写面（`set_state`）随之无声改写 frontmatter 并落盘。

修法：判据改为「原显式两位 **∪** `protect.is_protected`」——**超集**，原判据
一字不减（immutable 位照旧、`override=True` 短路通路照旧）；判据本体仍是
`protect` 的单点，两个模块各用一份**零规则载体**的 frontmatter→(cg, node_id)
探针把它喂进去，不复制规则。

**判据面边界（本守卫钉住的口径）**：保护只拦**降级**（`is_downgrade`），回升
不受限（K08/K09）；按分保护只对**缺省来源或显式 hint** 生效，`heuristic` 等
显式来源的高分不得触发（K10/K11）；`self_state` 只豁免 `is_immutable`
（不可覆盖），**不**豁免 `is_protected`（不可遗忘）——故 self 层自我状态卡的
降级同样被层保护拦下（K12，protect.py 既有口径，非本批新造）。
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

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss377_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain",
                   "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from md_cg import lifecycle as L      # noqa: E402
from md_cg import protect as P        # noqa: E402
from md_cg import trust as T          # noqa: E402
from md_cg.mdcos import MdCGOS        # noqa: E402

_CCG = chr(10).join(["# 功能名：守卫夹具节点", "# 生效条件：守卫运行时",
                     "# 子功能：无", "# 执行：无",
                     "# 验证方式：守卫断言", "# 不适用条件：无"])


def _lib(tag):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    return MdCGOS(d)


print("== A 组：层保护拦下状态降级（#377 正题） ==")
_fm = {"layer": "anchor", T.STATE_FIELD: "verified"}
_ok, _code, _why = T.stamp(_fm, "doubted")
_check("A01 trust：anchor 层 verified→doubted → 拒（code=protected）",
       _ok is False and _code == "protected", (_ok, _code, _why))
_check("A02 trust：A01 被拒后原状态与验证史均未被改写",
       _fm[T.STATE_FIELD] == "verified" and T.HISTORY_FIELD not in _fm, _fm)

_fm = {"layer": "self", T.STATE_FIELD: "verified"}
_ok, _code, _ = T.stamp(_fm, "doubted")
_check("A03 trust：self 层同样受层保护（同一判据，不是 anchor 特例）",
       _ok is False and _code == "protected" and _fm[T.STATE_FIELD] == "verified",
       (_ok, _code, _fm))

_fm = {"layer": "anchor", L.STATE_FIELD: "active"}
_ok, _code, _why = L.stamp(_fm, "converged")
_check("A04 lifecycle：anchor 层 active→converged → 拒（code=protected）",
       _ok is False and _code == "protected", (_ok, _code, _why))
_check("A05 lifecycle：A04 被拒后原状态与状态史均未被改写",
       _fm[L.STATE_FIELD] == "active" and L.HISTORY_FIELD not in _fm, _fm)

_fm = {"layer": "self", L.STATE_FIELD: "active"}
_ok, _code, _ = L.stamp(_fm, "converged")
_check("A06 lifecycle：self 层同样受层保护",
       _ok is False and _code == "protected" and _fm[L.STATE_FIELD] == "active",
       (_ok, _code, _fm))

# 夹具刻意用 importance=0.5：importance≥0.70 时写侧会**自动置 protected 位**，
# 那样这条腿就被显式位挡住、测不出「层保护」这一支（判别力归零）。0.5 ⇒ 唯一
# 保护来源是 layer=anchor 本身，正是 #377 要接线的那一支。
_cg = _lib("anchor_lib")
_cg.add("n_anchor", _CCG, layer="anchor", importance=0.5)
_before = ((_cg.get("n_anchor") or {}).get("frontmatter") or {}).get(T.STATE_FIELD)
_r = T.set_state(_cg, "n_anchor", "doubted")
_check("A07 隔离库：anchor 节点 set_state 降级 → ok=False / error=protected",
       _r.get("ok") is False and _r.get("error") == "protected", _r)
_after = ((_cg.get("n_anchor") or {}).get("frontmatter") or {}).get(T.STATE_FIELD)
_check("A08 隔离库：A07 零落盘（盘面验证态停在降级前的值，且未被写成 doubted）",
       _before == _after and _after != "doubted", (_before, _after))
_r = L.set_state(_cg, "n_anchor", "converged")
_check("A09 隔离库：anchor 节点 lifecycle set_state 降级 → ok=False / error=protected",
       _r.get("ok") is False and _r.get("error") == "protected", _r)

print("== K 组：非恒真对照（修复不得把正常路径一起关掉） ==")
_fm = {"layer": "knowledge", T.STATE_FIELD: "verified"}
_ok, _code, _ = T.stamp(_fm, "doubted")
_check("K01 trust：knowledge 层（未保护）verified→doubted → 照常放行并写入",
       _ok is True and _code == "ok" and _fm[T.STATE_FIELD] == "doubted",
       (_ok, _code, _fm))

_fm = {T.STATE_FIELD: "verified"}
_ok, _code, _ = T.stamp(_fm, "doubted")
_check("K02 trust：无 layer 键的存量 fm → 照常放行（不误拦）",
       _ok is True and _fm[T.STATE_FIELD] == "doubted", (_ok, _code))

_fm = {"layer": "anchor", T.STATE_FIELD: "verified"}
_ok, _code, _ = T.stamp(_fm, "doubted", override=True)
_check("K03 trust：override=True 通路仍在（层保护可显式放行）",
       _ok is True and _code == "ok" and _fm[T.STATE_FIELD] == "doubted",
       (_ok, _code, _fm))

_fm = {"layer": "anchor", L.STATE_FIELD: "active"}
_ok, _code, _ = L.stamp(_fm, "converged", override=True)
_check("K04 lifecycle：override=True 通路仍在",
       _ok is True and _fm[L.STATE_FIELD] == "converged", (_ok, _code))

_fm = {"immutable": True, T.STATE_FIELD: "verified"}
_ok, _code, _ = T.stamp(_fm, "doubted")
_check("K05 trust：原 immutable 位仍在判据内（豁免未被删）",
       _ok is False and _code == "protected", (_ok, _code))

_fm = {"immutable": True, L.STATE_FIELD: "active"}
_ok, _code, _ = L.stamp(_fm, "converged")
_check("K06 lifecycle：原 immutable 位仍在判据内",
       _ok is False and _code == "protected", (_ok, _code))

_fm = {"protected": True, T.STATE_FIELD: "verified"}
_ok, _code, _ = T.stamp(_fm, "doubted")
_check("K07 trust：显式 protected 位照旧",
       _ok is False and _code == "protected", (_ok, _code))

_fm = {"layer": "anchor", T.STATE_FIELD: "doubted"}
_ok, _code, _ = T.stamp(_fm, "verified")
_check("K08 trust：保护只拦降级——anchor 层回升 doubted→verified 照常放行",
       _ok is True and _fm[T.STATE_FIELD] == "verified", (_ok, _code))

_fm = {"layer": "anchor", L.STATE_FIELD: "converged"}
_ok, _code, _ = L.stamp(_fm, "active")
_check("K09 lifecycle：anchor 层回升 converged→active 照常放行",
       _ok is True and _fm[L.STATE_FIELD] == "active", (_ok, _code))

_fm = {"layer": "knowledge", "importance": 0.9,
       "importance_source": "heuristic", T.STATE_FIELD: "verified"}
_ok, _code, _ = T.stamp(_fm, "doubted")
_check("K10 按分保护只认缺省/hint 来源：heuristic 高分不得触发（issue50-e 口径被精确共用）",
       _ok is True and _fm[T.STATE_FIELD] == "doubted", (_ok, _code))

_fm = {"layer": "knowledge", "importance": 0.9, T.STATE_FIELD: "verified"}
_ok, _code, _ = T.stamp(_fm, "doubted")
_check("K11 缺省来源高分（importance≥0.70）→ 按分保护生效、降级被拦",
       _ok is False and _code == "protected", (_ok, _code))

_fm = {"layer": "self", "self_state": True, T.STATE_FIELD: "verified"}
_ok, _code, _ = T.stamp(_fm, "doubted")
_check("K12 self_state 只豁免不可覆盖、不豁免层保护 → 自我状态卡降级同样被拦（protect 既有口径）",
       _ok is False and _code == "protected", (_ok, _code))

_cg2 = _lib("know_lib")
_cg2.add("n_know", _CCG, layer="knowledge")
_r = T.set_state(_cg2, "n_know", "doubted")
_disk = ((_cg2.get("n_know") or {}).get("frontmatter") or {}).get(T.STATE_FIELD)
_check("K13 隔离库：knowledge 节点同样降级 → 照常放行并落盘（对照 A07/A08）",
       _r.get("ok") is True and _r.get("changed") is True and _disk == "doubted",
       (_r, _disk))
_r = L.set_state(_cg2, "n_know", "converged")
_check("K14 隔离库：knowledge 节点 lifecycle 降级 → 照常放行并落盘（对照 A09）",
       _r.get("ok") is True and _r.get("changed") is True, _r)

print("== E 组：接线单点存在性 ==")
_src_t = inspect.getsource(T.stamp)
_src_l = inspect.getsource(L.stamp)
_check("E01 trust.stamp 体内经 _is_protected_fm 接入判据（接线未脱焊）",
       "_is_protected_fm(fm)" in _src_t, [l for l in _src_t.splitlines()
                                          if "_is_protected" in l])
_check("E02 lifecycle.stamp 体内经 _is_protected_fm 接入判据（接线未脱焊）",
       "_is_protected_fm(fm)" in _src_l, [l for l in _src_l.splitlines()
                                          if "_is_protected" in l])
# 前缀匹配：`is_protected_entry` 与 `is_protected` 同属 protect 单点族；本条钉的是
# 「不走本地实现」，**不是「函数名必须叫 is_protected」** —— 不是为了让腿绿而放宽
# （U01 批：两份 _FmProbe 副本收口到条目口径单点 protect.is_protected_entry）。
_check("E03 两处探针都交给 protect 单点族（判据本体不在本模块复制）",
       "protect.is_protected" in inspect.getsource(T._is_protected_fm)
       and "protect.is_protected" in inspect.getsource(L._is_protected_fm), "")
_check("E04 原显式两位判据仍在（immutable 豁免未被改写）",
       'bool(fm.get("protected") or fm.get("immutable"))' in _src_t
       and 'bool(fm.get("protected") or fm.get("immutable"))' in _src_l, "")

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #377 结果：%d 失败" % len(FAILS))
else:
    print("issue #377 结果：全部通过")


_MUTATIONS = (
    ("M1 trust 去接线（回改动前的收窄判据）", "md_cg/trust.py",
     ('    prot = bool(fm.get("protected") or fm.get("immutable")) \\' + chr(10)
      + '        or _is_protected_fm(fm)[0]',
      '    prot = bool(fm.get("protected") or fm.get("immutable"))'),
     # 机制：收窄判据只认显式两位 ⇒ 无 protected/immutable 位的 anchor/self 层
     # 与「缺省来源高分」「self_state 卡」一律不再受保护，降级照常写入；
     # E01 是源码形态腿（接线被删即脱焊，本就该红）。
     ("A01", "A02", "A03", "A07", "A08", "K11", "K12", "E01")),
    ("M2 lifecycle 去接线（回改动前的收窄判据）", "md_cg/lifecycle.py",
     ('    prot = bool(fm.get("protected") or fm.get("immutable")) \\' + chr(10)
      + '        or _is_protected_fm(fm)[0]',
      '    prot = bool(fm.get("protected") or fm.get("immutable"))'),
     ("A04", "A05", "A06", "A09", "E02")),
    ("M3 trust 过度收紧（恒判受保护）", "md_cg/trust.py",
     ('    prot = bool(fm.get("protected") or fm.get("immutable")) \\' + chr(10)
      + '        or _is_protected_fm(fm)[0]',
      '    prot = True'),
     # 机制：恒判受保护 ⇒ 未保护路径全部被误拦（K 组判别力自证）；
     # E01/E04 是源码形态腿（判据块被整体替换，接线与显式两位串都不再出现在源码里）。
     ("K01", "K02", "K10", "K13", "E01", "E04")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss377_mut_")
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
                         "md_cg.test_issue377_layer_protect_stamp"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态 / 过度收紧，守卫必须按指定项转红")
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
    # fail-closed：正向断言失败与「变异未按预期转红」都返回非零
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
