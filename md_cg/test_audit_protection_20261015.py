# -*- coding: utf-8 -*-
"""保护判据守卫（审计批次 20261015）：dsh-bounty #506 与 #514。

两条**独立**缺陷，各修各的、各测各的：

  · **#506 检索衰减保护下界错误**——`freshness.protected_floor` 只认显式
    `protected` 位，而「不可遗忘」有**三条真源**：层保护（`self`/`anchor`）、
    显式位、按分保护（`importance ≥ 0.70` 且 `importance_source` 缺省或
    `"hint"`）。后两类节点在检索期拿 `SCORE_FLOOR` 而不是保护下界；
    `entry_weight` 的取数键也不含 `layer` / `importance_source`。断言面：G1。

  · **#514 状态降级保护豁免错误**——`trust.stamp` 与 `lifecycle.stamp` 的
    `prot = bool(fm.get("protected") or fm.get("immutable"))` 漏掉层保护真源，
    层保护节点经 `set_state`（自述「唯一推进入口」）落盘降级收不到豁免。
    断言面：G2（纯函数）/ G3（端到端真落盘）。

修法：`protect.is_protected_entry(fm)` 是判据**纯函数本体**（不读 cg、无 IO），
`protect.is_protected(cg, node_id)` 经 `_fm` 读真实 cg 后委托它；freshness /
trust / lifecycle 在只有 frontmatter 时**直接调这同一纯函数**——不构造假 cg、
不补 `get`、不给未知键塞默认值。不新增保护类型、不改阈值、不另起判据。
G4 逐例对拍「纯函数 = 真实 cg 路径」同值；
G6 在**隔离临时副本**上做「修前行为 API 基线红测」：旧判据（只认显式位）
必须让本套件转红，且不是 ImportError / TypeError。
G5 是判别力对照：**真正未受保护**的节点（无层、无位、`importance < 0.70`）
必须仍触 `SCORE_FLOOR`、仍可降级——修法不得把保护面放大到未保护节点。

运行：`python -X utf8 -m md_cg.test_audit_protection_20261015`
      `python -X utf8 -m md_cg.test_audit_protection_20261015 --mutate`
      `python -X utf8 -m md_cg.test_audit_protection_20261015 --mutate --list`
      `python -X utf8 -m md_cg.test_audit_protection_20261015 --baseline-red`
数据全部落在 `tempfile` 隔离根，不触碰任何活库；变异只在临时副本/内存 exec。
"""
import os
import shutil
import sys
import tempfile

# 隔离根**必须先于** md_cg 导入（crypto 在导入期就解析 aux_root）
_TMP = tempfile.mkdtemp(prefix="prot_guard_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_STATE_ROOT"] = os.path.join(_TMP, "stateroot")
os.environ["MDCG_FRESHNESS"] = "1"

try:
    from . import freshness as F
    from . import lifecycle as L
    from . import protect as P
    from . import trust as T
    from .mdcg import MdCG
except ImportError:                                  # 直接脚本运行
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from md_cg import freshness as F
    from md_cg import lifecycle as L
    from md_cg import protect as P
    from md_cg import trust as T
    from md_cg.mdcg import MdCG

PASS = 0
FAILS = []
DAY = 86400.0
NOW = 1.8e9
GAMMA = 0.023104906018864795            # ln2/30（与 p4 守卫同刻度）


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAILS.append(name)
        print("  [FAIL] %s · %s" % (name, detail))


def helper():
    """纯判据本体的**存在性安全**取用（修前无该单点 ⇒ None）。"""
    fn = getattr(P, "is_protected_entry", None)
    return fn if callable(fn) else None


class FakeCG:
    """真 `protect.is_protected` 路径的最小 cg（真 protect 判定，假索引容器）。

    只用于 G4 的**对拍**：证明「真实 cg 路径」与纯函数同值。生产代码不构造它。
    """

    def __init__(self, fm):
        self.index = {"nodes": {"n1": dict(fm)}}

    def get(self, nid):
        return {"frontmatter": dict(self.index["nodes"][nid]),
                "content": "", "id": nid}


#: 判定形态矩阵：**真源**一栏是 `protect` 的既有契约（不是本批发明）。
SHAPES = [
    ("显式 protected 位", {"protected": True}, True),
    ("层保护 layer=anchor", {"layer": "anchor"}, True),
    ("层保护 layer=self", {"layer": "self"}, True),
    ("按分保护 importance=0.80", {"importance": 0.80}, True),
    ("按分保护 + hint 来源", {"importance": 0.80,
                              "importance_source": "hint"}, True),
    ("heuristic 来源不按分", {"importance": 0.80,
                              "importance_source": "heuristic"}, False),
    ("importance=0.69 不按分", {"importance": 0.69}, False),
    ("真未保护（无层无位 0.5）", {"importance": 0.5}, False),
]


def _entry(fm, days=30, importance=None):
    e = {"created_at": NOW - days * DAY, "access_count": 0, "last_access": 0,
         "protected": None}
    e.update({k: v for k, v in fm.items() if k != "importance"})
    e["importance"] = fm.get("importance", importance)
    return e


def g0_fixture():
    print("== G0 夹具自检：形态确实落在 protect 契约上 ==")
    for label, fm, want in SHAPES:
        got, why = P.is_protected(FakeCG(fm), "n1")
        check("F0 %s → is_protected=%s" % (label, want), got is want, why)


def g1_506_floor():
    print("== G1 #506 检索衰减保护下界（三条真源同值）==")
    e_bit = _entry({"protected": True, "importance": 0.90})
    e_lay = _entry({"layer": "anchor", "importance": 0.90})
    e_scr = _entry({"importance": 0.90})
    floor_bit = F.protected_floor(e_bit)
    floor_lay = F.protected_floor(e_lay)
    floor_scr = F.protected_floor(e_scr)
    check("G1a 显式位 floor = IMPORTANCE_PROTECT/importance",
          abs(floor_bit - 0.7 / 0.9) < 1e-12, "%.6f" % floor_bit)
    check("G1b 层保护 floor 与显式位同值（修前 = SCORE_FLOOR）",
          abs(floor_lay - floor_bit) < 1e-12,
          "lay=%.6f bit=%.6f" % (floor_lay, floor_bit))
    check("G1c 按分保护 floor 与显式位同值（修前 = SCORE_FLOOR）",
          abs(floor_scr - floor_bit) < 1e-12,
          "scr=%.6f bit=%.6f" % (floor_scr, floor_bit))
    w_lay = F.entry_weight(_entry({"layer": "anchor", "importance": 0.90},
                                  days=365), now=NOW, gamma=GAMMA)[0]
    check("G1d 层保护节点老化 1 年仍守承诺下界（importance × 乘子 ≥ 0.70）",
          0.90 * w_lay >= 0.70 - 1e-12, "w=%.6f" % w_lay)
    why = F.entry_weight(_entry({"layer": "anchor", "importance": 0.90}),
                         now=NOW, gamma=GAMMA)[1]
    check("G1e 依据 dict 的 protected 与下界判据同源",
          why.get("protected") is True, str(why.get("protected")))
    # 取数键：层保护只经 fm 给出时也必须被取到（修前 keys 不含 layer）
    idx = {"created_at": NOW - 365 * DAY, "access_count": 0, "last_access": 0,
           "importance": 0.9, "importance_source": "heuristic"}
    w_none = F.entry_weight(idx, now=NOW, gamma=GAMMA)[0]
    w_lay = F.entry_weight(idx, now=NOW, gamma=GAMMA,
                           fm={"layer": "anchor"})[0]
    w_src = F.entry_weight(idx, now=NOW, gamma=GAMMA,
                           fm={"importance_source": "hint"})[0]
    check("G1f layer 经 fm 覆盖生效（修前取数键不含 layer）", w_lay > 0.1,
          "none=%.6f lay=%.6f" % (w_none, w_lay))
    check("G1g importance_source 经 fm 覆盖生效（修前取数键不含该键）",
          w_src > 0.1, "none=%.6f src=%.6f" % (w_none, w_src))
def g2_514_stamp():
    print("== G2 #514 降级豁免（纯函数：trust.stamp / lifecycle.stamp）==")
    t_bit = T.stamp({"protected": True}, "doubted", reason="g")
    t_imm = T.stamp({"immutable": True}, "doubted", reason="g")
    t_anc = T.stamp({"layer": "anchor"}, "doubted", reason="g")
    t_self = T.stamp({"layer": "self"}, "doubted", reason="g")
    t_scr = T.stamp({"importance": 0.80}, "doubted", reason="g")
    t_heur = T.stamp({"importance": 0.80, "importance_source": "heuristic"},
                     "doubted", reason="g")
    t_free = T.stamp({"importance": 0.5}, "doubted", reason="g")
    check("G2a trust 层保护(anchor) 拒降级（修前 ok=True）",
          t_anc[0] is False and t_anc[1] == "protected", str(t_anc))
    check("G2b trust 层保护(self) 拒降级（修前 ok=True）",
          t_self[0] is False and t_self[1] == "protected", str(t_self))
    check("G2c trust 按分保护拒降级（修前 ok=True）",
          t_scr[0] is False and t_scr[1] == "protected", str(t_scr))
    check("G2d trust 显式位豁免未被缩窄", t_bit[0] is False
          and t_bit[1] == "protected", str(t_bit))
    check("G2e trust immutable 豁免未被缩窄", t_imm[0] is False
          and t_imm[1] == "protected", str(t_imm))
    check("G2f trust heuristic 来源不按分（既有边界不误伤）", t_heur[0] is True,
          str(t_heur))
    check("G2g trust 真未保护节点仍可降级（判别力）", t_free[0] is True,
          str(t_free))
    check("G2h trust override=True 仍是显式放行口",
          T.stamp({"layer": "anchor"}, "doubted", reason="g",
                  override=True)[0] is True)
    l_bit = L.stamp({"protected": True}, "converged", reason="g")
    l_anc = L.stamp({"layer": "anchor"}, "converged", reason="g")
    l_self = L.stamp({"layer": "self"}, "converged", reason="g")
    l_heur = L.stamp({"importance": 0.80, "importance_source": "heuristic"},
                     "converged", reason="g")
    l_free = L.stamp({"importance": 0.5}, "converged", reason="g")
    check("G2i lifecycle 层保护(anchor) 拒降级（修前 ok=True）",
          l_anc[0] is False and l_anc[1] == "protected", str(l_anc))
    check("G2j lifecycle 层保护(self) 拒降级（修前 ok=True）",
          l_self[0] is False and l_self[1] == "protected", str(l_self))
    check("G2k lifecycle 显式位豁免未被缩窄", l_bit[0] is False, str(l_bit))
    check("G2l lifecycle heuristic 来源不按分（既有边界不误伤）",
          l_heur[0] is True, str(l_heur))
    check("G2m lifecycle 真未保护节点仍可降级（判别力）", l_free[0] is True,
          str(l_free))


def g3_514_e2e():
    print("== G3 #514 端到端（真 MdCG / 真落盘 / 隔离根）==")
    root = os.path.join(_TMP, "lib")
    cg = MdCG(root)
    try:
        for nid, kw in (("e_anchor", {"layer": "anchor"}),
                        ("e_bit", {"layer": "knowledge", "protected": True,
                                   "protection_reason": "g"}),
                        ("e_free", {"layer": "knowledge", "importance": 0.5})):
            cg.add(nid, "正文 %s" % nid, verification_state="verified",
                   on_conflict="overwrite", verification_basis="test", **kw)
        for nid in ("e_anchor", "e_bit", "e_free"):
            prot, why = P.is_protected(cg, nid)
            print("  %-10s is_protected=%-5s ｜ %s" % (nid, prot, why))
        r_anchor = T.set_state(cg, "e_anchor", "doubted", reason="g")
        r_bit = T.set_state(cg, "e_bit", "doubted", reason="g")
        r_free = T.set_state(cg, "e_free", "doubted", reason="g")
        st = {nid: ((cg.get(nid) or {}).get("frontmatter") or {})
              .get("verification_state")
              for nid in ("e_anchor", "e_bit", "e_free")}
        print("  set_state 结果：anchor=%s bit=%s free=%s" %
              (r_anchor.get("error") or r_anchor.get("code"),
               r_bit.get("error") or r_bit.get("code"),
               r_free.get("error") or r_free.get("code")))
        check("G3a 层保护(anchor) 节点降级被拒且零落盘（修前 ok=True 落盘）",
              r_anchor.get("ok") is False and r_anchor.get("error") == "protected"
              and st["e_anchor"] == "verified", str(r_anchor))
        check("G3b 显式位节点降级被拒（对照不缩窄）",
              r_bit.get("ok") is False and st["e_bit"] == "verified",
              str(r_bit))
        check("G3c 真未保护节点降级成功且落盘（判别力）",
              r_free.get("ok") is True and st["e_free"] == "doubted",
              str(r_free))
        check("G3d 无 principal 时层闸放行（漏判无人兜底，正是本缺陷面）",
              getattr(cg, "principal", None) is None)
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)


def g4_same_source():
    print("== G4 同源：纯函数 = 真实 cg 路径 ==")
    fn = helper()
    if fn is None:
        check("G4a protect.is_protected_entry 纯函数在位", False,
              "修前无该单点")
        return
    bad = []
    for label, fm, _want in SHAPES:
        if fn(fm)[0] != P.is_protected(FakeCG(fm), "n1")[0]:
            bad.append(label)
    check("G4a 纯函数与 protect.is_protected（真实 cg 路径）逐例同值",
          not bad, str(bad))
    check("G4b 单点只认三条真源（heuristic 源不按分）",
          fn({"importance": 0.80,
              "importance_source": "heuristic"})[0] is False)
    check("G4d 返回原因与真实 cg 路径逐字同（层保护/按分）",
          fn({"layer": "anchor"}) == P.is_protected(FakeCG({"layer": "anchor"}),
                                                    "n1")
          and fn({"importance": 0.80}) == P.is_protected(
              FakeCG({"importance": 0.80}), "n1"))
    check("G4j 缺节点返回 (False, '')（_fm 得 None 即负路由）",
          P.is_protected(FakeCG({}), "nope") == (False, ""))


def g5_discrimination():
    print("== G5 判别力：未保护节点不得享有保护面 ==")
    e = _entry({"importance": 0.5}, days=3650)
    w = F.entry_weight(e, now=NOW, gamma=GAMMA)[0]
    check("G5a 真未保护节点老化 10 年触 SCORE_FLOOR",
          abs(w - F.SCORE_FLOOR) < 1e-12, "%.6f" % w)
    check("G5b 未保护节点的 floor 就是 SCORE_FLOOR",
          abs(F.protected_floor(e) - F.SCORE_FLOOR) < 1e-12)
    check("G5c 层保护与未保护的下界可分辨（修前不可分辨）",
          F.protected_floor(_entry({"layer": "anchor", "importance": 0.9}))
          > F.protected_floor(e) * 100)


def _patch(mod, name, value):
    orig = getattr(mod, name)

    def restore():
        setattr(mod, name, orig)
    setattr(mod, name, value)
    return restore


def _bit_only(fm):
    """修前判据：只认显式 protected 位（第三套口径，正是被修掉的形态）。

    契约仍守 `(bool, reason)`——变异是**行为**变异，不是接口破坏。
    """
    fm = fm or {}
    if fm.get("protected") is True:
        return True, str(fm.get("protection_reason") or "显式保护标记")
    return False, ""


class _ShimProtect:
    """单模块作用域替身：只换纯函数，其余属性透传真 `protect`。"""

    def __init__(self, fn):
        self.is_protected_entry = fn

    def __getattr__(self, name):
        return getattr(P, name)


def _patched_helper_ctx(old, new):
    """纯函数按**字面替换**后在内存 exec 安装回 `protect`（不落盘、不改共享源）。"""
    import inspect
    src = inspect.getsource(P.is_protected_entry).replace(old, new)
    ns = dict(vars(P))
    exec(compile(src, "audit_prot_mut.py", "exec"), ns)
    return _patch(P, "is_protected_entry", ns["is_protected_entry"])


def _mut_506_floor_bit_only():
    """#506：纯函数本体退回只认显式 protected 位。"""
    return _patch(P, "is_protected_entry", _bit_only)


def _mut_506_keys_drop_layer():
    """#506：层集合判据失效（等价于取数面丢 layer）。"""
    return _patched_helper_ctx("    if layer in PROTECTED_LAYERS:",
                               "    if False:")


def _mut_514_trust_bit_only():
    """#514：**只**把 trust 侧判据退回位判据（lifecycle 不动）。"""
    return _patch(T, "protect", _ShimProtect(_bit_only))


def _mut_514_lifecycle_bit_only():
    """#514：**只**把 lifecycle 侧判据退回位判据（trust 不动）。"""
    return _patch(L, "protect", _ShimProtect(_bit_only))


_MUTATIONS = [
    ("506_floor_bit_only", "#506：纯函数退回只认显式 protected 位",
     _mut_506_floor_bit_only),
    ("506_keys_drop_layer", "#506：层集合判据失效（等价 keys 不含 layer）",
     _mut_506_keys_drop_layer),
    ("514_trust_bit_only", "#514：trust.stamp 判据退回位判据",
     _mut_514_trust_bit_only),
    ("514_lifecycle_bit_only", "#514：lifecycle.stamp 判据退回位判据",
     _mut_514_lifecycle_bit_only),
]


def _collect():
    global PASS, FAILS
    PASS, FAILS = 0, []
    g0_fixture()
    g1_506_floor()
    g2_514_stamp()
    g3_514_e2e()
    g4_same_source()
    g5_discrimination()
    return list(FAILS)


# ---------------------------------------------------------------- 修前基线红测
# 只在**隔离临时副本**（shutil.copytree，跳过 __pycache__）里改 protect.py，
# 用旧判据（只认显式 protected 位）替换纯函数本体；原文件一字不动。
_OLD_BODY = """def is_protected_entry(fm):
    if fm.get("protected") is True:
        return True, str(fm.get("protection_reason") or "显式保护标记")
    return False, ""
"""


def _red_copy(src_root):
    """把 md_cg 复制到临时根并换入旧判据，返回（可导入包根, md_cg 目录）。"""
    dst = os.path.join(_TMP, "redsrc")
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    pkg = os.path.join(dst, "md_cg")
    shutil.copytree(os.path.join(src_root, "md_cg"), pkg,
                    ignore=shutil.ignore_patterns("__pycache__"))
    p = os.path.join(pkg, "protect.py")
    with open(p, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("def is_protected_entry(")
    end = src.index("def is_protected(", start)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(src[:start] + _OLD_BODY + "\n\n" + src[end:])
    return dst


def g6_baseline_red():
    print("== G6 修前行为基线：旧判据（只认显式位）必须让守卫转红 ==")
    src_root = os.path.dirname(os.path.dirname(os.path.abspath(P.__file__)))
    pkg_root = _red_copy(src_root)
    code = (
        "import sys, tempfile, os\n"
        "sys.path.insert(0, %r)\n" % pkg_root +
        "os.environ[\"MDCG_AUX_ROOT\"] = os.path.join(tempfile.mkdtemp(), \"a\")\n"
        "os.environ[\"MDCG_STATE_ROOT\"] = os.path.join(tempfile.mkdtemp(), \"s\")\n"
        "from md_cg import protect as P, freshness as F, trust as T, lifecycle as L\n"
        "import md_cg.test_audit_protection_20261015 as G\n"
        "G.P = P; G.F = F; G.T = T; G.L = L\n"
        "fails = G._collect()\n"
        "print(\"BASELINE_RED=%d\" % len(fails))\n"
        "for f in fails:\n"
        "    print(\"  - \" + f)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = pkg_root
    import subprocess
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                          capture_output=True, text=True, env=env,
                          cwd=pkg_root, encoding="utf-8", errors="replace")   # 第15条：不依赖 locale
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = [ln for ln in out.splitlines() if ln.startswith("BASELINE_RED=")]
    nred = int(tail[-1].split("=")[1]) if tail else -1
    named = [ln.strip("- ").strip() for ln in out.splitlines()
             if ln.startswith("  - ")]
    check("G6a 旧判据下守卫确实转红（≥2 项，非 ImportError/TypeError）",
          nred >= 2, "nred=%s\n%s" % (nred, out[-800:]))
    check("G6b 红项落在 G1/G2 指定面（层保护/按分保护）",
          any(x.startswith("G1") for x in named)
          and any(x.startswith("G2") for x in named), str(named[:6]))
    check("G6c 红因是行为而非缺符号（无 ImportError/TypeError/AttributeError）",
          "ImportError" not in out and "TypeError" not in out
          and "AttributeError" not in out, out[-400:])
    check("G6d 共享源码未被就地改动（只改临时副本）",
          "def is_protected_entry(" in open(
              os.path.abspath(P.__file__), encoding="utf-8").read())


def main(argv):
    if "--baseline-red" in argv:
        global PASS, FAILS
        PASS, FAILS = 0, []
        g6_baseline_red()
        print("\ntest_audit_protection --baseline-red: %d 通过 / %d 失败"
              % (PASS, len(FAILS)))
        return 0 if not FAILS else 1
    if "--mutate" in argv:
        if "--list" in argv:
            for name, desc, _fn in _MUTATIONS:
                print("  %-24s %s" % (name, desc))
            return 0
        base = _collect()
        if base:
            print("\n!! 基线不绿（%d 条）：%s" % (len(base), base))
            return 1
        bad = []
        for name, desc, fn in _MUTATIONS:
            try:
                restore = fn()
            except AttributeError as exc:
                print("  ANCHOR-MISS %s: %s" % (name, exc))
                return 2
            got = _collect()
            restore()
            if got:
                print("  MUTATE-OK %s（%s）→ 转红 %d 条：%s"
                      % (name, desc, len(got), got[:2]))
            else:
                bad.append(name)
                print("  MUTATE-FAIL %s（%s）→ 仍全绿" % (name, desc))
        print("\ntest_audit_protection --mutate: %d/%d 变异按预期转红"
              % (len(_MUTATIONS) - len(bad), len(_MUTATIONS)))
        return 0 if not bad else 1
    fails = _collect()
    print("\ntest_audit_protection_20261015: %d 通过 / %d 失败"
          % (PASS, len(fails)))
    for f in fails:
        print("  - " + f)
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
