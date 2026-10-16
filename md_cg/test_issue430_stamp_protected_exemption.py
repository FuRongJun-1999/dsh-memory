# -*- coding: utf-8 -*-
# 功能名：stamp 受保护豁免降级的三条公开入口与判据载体单点（issue #430）
# 生效条件：python -X utf8 -m md_cg.test_issue430_stamp_protected_exemption [--mutate]；被测面＝md_cg/lifecycle.py::stamp / md_cg/trust.py::stamp 的保护判据及其三条公开入口（MdCG.set_state / MdCG.set_verification / MdCG.verify-weakened），另钉 md_cg/protect.py::is_protected_fm 载体单点
# 子功能：A 组＝三条公开入口对「不置位的受保护层节点」全部硬拒（零落盘、检索面不消失、零快照零审计）；K 组＝非恒真对照（显式 mark 仍拦、未保护节点照常降级、override/immutable/按分/回升各通路不变）；E 组＝判据载体单点（protect.is_protected_fm 委托 is_protected，三模块不再各养探针）
# 执行：--mutate 时在镜像树里逐条把判据改回两位形态 / 割掉委托 / 过度收紧，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**（多红/少红皆不合格）
# 不适用条件：不判迁移表完备性（属 test_trust / test_lifecycle）；不判 mcp 工具面令牌与并发索引代际（N213 族另守）；不判 freshness 衰减行为面（属 #378 守卫，本守卫只钉其接线形态 E06）；不判 mdcg.add 覆写面的降级裁决（guard_overwrite / guard_move 另族）
"""issue #430 守卫：「受保护豁免降级」判据必须与权威保护单点同源，且三条公开
入口一条不漏。

病象（#430 原报告，实测三面）：`stamp` 的判据只认显式两位
`prot = bool(fm.get("protected") or fm.get("immutable"))` ——**不置位**的
self/anchor 层节点（层保护）与「缺省来源高分」节点（按分保护）在权威
`protect.is_protected` 眼里**不可遗忘**，在状态机眼里却可降级：

  面1 cg.set_state(n_self, "demoted"→"archived")  → 落盘、节点从 _candidates 消失
  面2 cg.set_verification(n_anchor, "doubted")    → 落盘
  面3 cg.verify(node, "weakened")（weakened 分支无条件调 set_verification）
                                                  → vstate=doubted
  读数：零快照（_protected_history=0）、零审计（_protected_audit=0）——无声失忆。

历史脉络：#377（2026-10-14 21:10 落地）已把两处 `stamp` 判据改为
「显式两位 ∪ protect.is_protected」并修好上述三面；#430 在其上收口两件事：
  ① **判据载体单点**——#377/#378 在 lifecycle / trust / freshness 三处各放了一份
     逐字同构的探针载体（issue「同根第四次分叉」，D3）。本批收口进
     `protect.is_protected_fm(fm)`：判据本体（is_protected）与载体都在 protect
     单点，供一切「拿不到 cg 的纯函数」共用（issue 修复建议原文）；
  ② **三面守卫**——#377 只守到 stamp 纯函数与 set_state 出口，面2/面3
     （cg.set_verification / cg.verify-weakened）此前无守卫；本守卫把 #430 点名
     的三条公开入口与「检索面可见 / 零快照零审计」读数全部钉死。

判据面边界（与 #377 守卫同口径）：保护只拦**降级**（回升不受限，K09）；
immutable 位与 override=True 两条既有通路逐位不变（K05/K08）；按分保护只认
缺省/hint 来源（issue50-e，K06/K07）；`guard_forget` 对同一节点硬拒（A09 两闸
同结论腿——issue「同一节点、同一动作，两条闸给出相反结论」的反面）。
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


_TMP = tempfile.mkdtemp(prefix="iss430_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain",
                   "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from md_cg import freshness as F      # noqa: E402
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


def _fm(cg, nid):
    return ((cg.get(nid) or {}).get("frontmatter") or {})


def _snaps(cg, nid):
    d = os.path.join(cg.root, P.HISTORY_DIR, nid)
    if not os.path.isdir(d):
        return 0
    return len([f for f in os.listdir(d) if f.endswith(".md")])


def _audit_rows(cg):
    p = os.path.join(cg.root, P.AUDIT_FILE)
    if not os.path.exists(p):
        return 0
    with open(p, encoding="utf-8") as f:
        return sum(1 for _ in f)


print("== A 组：三条公开入口对不置位的受保护层节点全部硬拒（#430 正题） ==")
# 夹具刻意 importance=0.5 且不打任何位：唯一保护来源是 layer 本身（判别力归零点
# 与 #377 A 组同款）——正是 #430 报告的「权威判 True、状态机放行」裂缝样本。
_cg = _lib("faces")
_cg.add("n_self", _CCG, layer="self", importance=0.5)
_cg.add("n_anchor", _CCG, layer="anchor", importance=0.5)
_cg.add("n_plain", _CCG, layer="knowledge", importance=0.4)

_r = _cg.set_state("n_self", "demoted", reason="iss430")
_check("A01 面1 cg.set_state(n_self, demoted) → ok=False / error=protected",
       _r.get("ok") is False and _r.get("error") == "protected", _r)
_check("A02 面1 盘面：n_self 生命周期停在 active（降级零落盘）",
       L.state_of(_fm(_cg, "n_self")) == "active", _fm(_cg, "n_self").get(L.STATE_FIELD))

_r = _cg.set_verification("n_anchor", "doubted", reason="iss430")
_check("A03 面2 cg.set_verification(n_anchor, doubted) → ok=False / error=protected",
       _r.get("ok") is False and _r.get("error") == "protected", _r)
_check("A04 面2 盘面：n_anchor 验证态停在 unverified（降级零落盘）",
       T.state_of(_fm(_cg, "n_anchor")) == "unverified",
       _fm(_cg, "n_anchor").get(T.STATE_FIELD))

_r = _cg.verify("n_self", "iss430 证据", "weakened")
_ver = (_r or {}).get("verification") or {}
_check("A05 面3 cg.verify(n_self, weakened) 的验证态迁移腿 → ok=False / error=protected",
       _ver.get("ok") is False and _ver.get("error") == "protected", _ver)
_check("A06 面3 盘面：n_self 验证态停在 unverified（doubted 未落盘）",
       T.state_of(_fm(_cg, "n_self")) == "unverified",
       _fm(_cg, "n_self").get(T.STATE_FIELD))

_paths = {str((e or {}).get("path") or "") for e in (_cg._candidates() or [])}
_check("A07 检索面：三面全试之后 n_self / n_anchor 仍在 _candidates（不消失）",
       any(p.endswith("/n_self.md") for p in _paths)
       and any(p.endswith("/n_anchor.md") for p in _paths), sorted(_paths))
_check("A08 零快照零审计：_protected_history 无前像、_protected_audit 0 行"
       "（被拒动作无痕，对照 override 显式放行才有留痕）",
       _snaps(_cg, "n_self") == 0 and _snaps(_cg, "n_anchor") == 0
       and _audit_rows(_cg) == 0,
       (_snaps(_cg, "n_self"), _snaps(_cg, "n_anchor"), _audit_rows(_cg)))
try:
    P.guard_forget(_cg, "n_self")
    _hit = False
except P.ProtectionError:
    _hit = True
_check("A09 两闸同结论：guard_forget 对同一 n_self 硬拒（权威面与状态机不再相反）",
       _hit, "guard_forget 未抛 ProtectionError")

print("== K 组：非恒真对照（修复不得把正常路径一起关掉） ==")
_cg.add("n_mark", _CCG, layer="knowledge", importance=0.4)
P.mark(_cg, "n_mark", "iss430 显式打标")
_r = _cg.set_state("n_mark", "demoted", reason="iss430")
_check("K01 显式 protect.mark 的节点走同一入口仍被拦（既有拦截未回归）",
       _r.get("ok") is False and _r.get("error") == "protected", _r)

_r = _cg.set_state("n_plain", "demoted", reason="iss430")
_check("K02 未保护节点 lifecycle 降级照常放行并落盘",
       _r.get("ok") is True and _r.get("changed") is True
       and L.state_of(_fm(_cg, "n_plain")) == "demoted", _r)

_r = _cg.set_verification("n_plain", "doubted", reason="iss430")
_check("K03 未保护节点验证态降级照常放行并落盘",
       _r.get("ok") is True and _r.get("changed") is True
       and T.state_of(_fm(_cg, "n_plain")) == "doubted", _r)

_r = _cg.verify("n_plain", "iss430 证据", "weakened")
_ver = (_r or {}).get("verification") or {}
_check("K04 未保护节点 verify(weakened) 的验证态腿照常流转 doubted",
       _ver.get("ok") is True and T.state_of(_fm(_cg, "n_plain")) == "doubted",
       (_ver, T.state_of(_fm(_cg, "n_plain"))))

_cg.add("n_self2", _CCG, layer="self", importance=0.5)
_r = _cg.set_state("n_self2", "demoted", reason="iss430", override=True)
_check("K05 override=True 通路仍在（层保护可显式放行）",
       _r.get("ok") is True and _r.get("changed") is True, _r)

_fm1 = {"layer": "knowledge", "importance": 0.9, T.STATE_FIELD: "verified"}
_ok1, _c1, _ = T.stamp(_fm1, "doubted")
_fm2 = {"layer": "knowledge", "importance": 0.9,
        "importance_source": "heuristic", T.STATE_FIELD: "verified"}
_ok2, _c2, _ = T.stamp(_fm2, "doubted")
_check("K06 按分保护腿（trust.stamp）：缺省来源高分被拦、heuristic 高分放行",
       _ok1 is False and _c1 == "protected" and _ok2 is True, (_ok1, _c1, _ok2, _c2))

_fm3 = {"layer": "knowledge", "importance": 0.9, L.STATE_FIELD: "active"}
_ok3, _c3, _ = L.stamp(_fm3, "demoted")
_check("K07 按分保护腿（lifecycle.stamp，对称）：缺省来源高分被拦",
       _ok3 is False and _c3 == "protected", (_ok3, _c3))

_ok4, _c4, _ = T.stamp({"immutable": True, T.STATE_FIELD: "verified"}, "doubted")
_ok5, _c5, _ = L.stamp({"immutable": True, L.STATE_FIELD: "active"}, "converged")
_check("K08 原显式两位判据仍在（immutable 豁免未被删，两状态机同守）",
       _ok4 is False and _c4 == "protected" and _ok5 is False and _c5 == "protected",
       (_ok4, _c4, _ok5, _c5))

_fm6 = {"layer": "anchor", T.STATE_FIELD: "doubted"}
_ok6, _, _ = T.stamp(_fm6, "verified")
_check("K09 保护只拦降级——anchor 层回升 doubted→verified 照常放行", _ok6 is True,
       (_ok6, _fm6))

print("== E 组：判据载体单点（#430 收口腿） ==")
_src_t = inspect.getsource(T.stamp)
_src_l = inspect.getsource(L.stamp)
_check("E01 trust.stamp 体内经 protect.is_protected_fm 接入判据（接线未脱焊）",
       "protect.is_protected_fm(fm)" in _src_t, [l for l in _src_t.splitlines()
                                                 if "is_protected" in l])
_check("E02 lifecycle.stamp 体内经 protect.is_protected_fm 接入判据（接线未脱焊）",
       "protect.is_protected_fm(fm)" in _src_l, [l for l in _src_l.splitlines()
                                                 if "is_protected" in l])
_check("E03 判据本体单点：protect.is_protected_fm 委托 is_protected（零规则复制）",
       "return is_protected(" in inspect.getsource(P.is_protected_fm), "")
_check("E04 载体单份：lifecycle / trust / freshness 均不再自养 _FmProbe/_EntryProbe"
       "（同根第四次分叉收敛）",
       "class _FmProbe" not in inspect.getsource(L)
       and "class _FmProbe" not in inspect.getsource(T)
       and "class _EntryProbe" not in inspect.getsource(F), "")
_check("E05 原显式两位判据仍在（immutable 豁免未被改写，两状态机同守）",
       'bool(fm.get("protected") or fm.get("immutable"))' in _src_t
       and 'bool(fm.get("protected") or fm.get("immutable"))' in _src_l, "")
_check("E06 第四叉同批收口：freshness.protected_floor 亦经 protect.is_protected_fm",
       "protect.is_protected_fm(e)" in inspect.getsource(F.protected_floor), "")

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #430 结果：%d 失败" % len(FAILS))
else:
    print("issue #430 结果：全部通过")


_MUTATIONS = (
    # 注：锚点一律**单行**（工作树为 CRLF，跨行锚点在 Windows 检出上必失配）；
    # 判据块第二行 `or protect.is_protected_fm(fm)[0]` 换成 `or False` 即等价
    # 「回缺陷形态（只认显式两位）」，换成 `or True` 即「恒判受保护」。
    ("M1 trust.stamp 判据回缺陷形态（只认显式两位）", "md_cg/trust.py",
     ('        or protect.is_protected_fm(fm)[0]',
      '        or False'),
     # 机制：收窄判据只认显式两位 ⇒ 面2/面3（都经 trust.stamp）对不置位的
     # anchor/self 层放行并落盘（A03–A06 转红）；按分腿同断（K06）；
     # E01 是源码形态腿（接线被删即脱焊）。
     ("A03", "A04", "A05", "A06", "K06", "E01")),
    ("M2 lifecycle.stamp 判据回缺陷形态（只认显式两位）", "md_cg/lifecycle.py",
     ('        or protect.is_protected_fm(fm)[0]',
      '        or False'),
     # 机制：面1（经 lifecycle.stamp）对不置位的 self 层放行并落盘（A01/A02）；
     # 按分腿同断（K07）；E02 是源码形态腿。
     ("A01", "A02", "K07", "E02")),
    ("M3 载体割掉委托（is_protected_fm 恒判未保护）", "md_cg/protect.py",
     ('    return is_protected(_FmProbe(fm), _FM_PROBE_ID)',
      '    return (False, "")'),
     # 机制：判据单点被架空 ⇒ 两个 stamp 的层保护/按分腿全断，三面全放（A01–A06
     # 中的层腿全红）；E03 是源码形态腿（委托被删）。
     ("A01", "A02", "A03", "A04", "A05", "A06", "K06", "K07", "E03")),
    ("M4 过度收紧（is_protected_fm 恒判受保护）", "md_cg/protect.py",
     ('    return is_protected(_FmProbe(fm), _FM_PROBE_ID)',
      '    return (True, "")'),
     # 机制：恒判受保护 ⇒ 未保护路径全部被误拦（K 组判别力自证：K02/K03/K04
     # 三条未保护通路 + K06 的 heuristic 边界侧）；E03 是源码形态腿（委托被删）。
     ("K02", "K03", "K04", "K06", "E03")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss430_mut_")
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
                         "md_cg.test_issue430_stamp_protected_exemption"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回缺陷形态 / 割掉委托 / 过度收紧，守卫必须按指定项转红")
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
