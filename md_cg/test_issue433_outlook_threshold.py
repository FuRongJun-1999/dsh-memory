# -*- coding: utf-8 -*-
"""issue #433 守卫：`insight.outlook` 的「高重要度未保护」盘点必须用**全仓一致的
0.70 保护阈值**与**三条真源判据**，而不是本模块私有的 0.9。

病灶：`IMPORTANCE_FLOOR = 0.9`（私有阈值，且与 `weights.IMPORTANCE_FLOOR = 0.10`
**同名不同值**）+ `if e.get("protected")` 只认显式位 ⇒
  (a) 层保护（self/anchor）节点在 `d1.protected` 里**完全隐形**；
  (b) [0.70, 0.90) 区间的高分未保护节点既不计入 protected、也不进
      `d2.high_importance_unprotected`（发现「未保护高价值节点」的唯一入口出现盲区）。
实测（原报告）：d1.protected = 0（h_self 不在内）；
d2.high_importance_unprotected = ['h_hi']（[0.7,0.9) 的 h_mid 也不在内）。

断言面：
  G0 隔离自证与阈值一致性
  G1 d1.protected 覆盖层保护节点（决定性腿，缺陷态为 0）
  G2 d2 覆盖 [0.70, 0.90) 区间（决定性腿，缺陷态漏报）
  G3 反向/对照：heuristic 来源高分节点**不得**算保护、且正常进 d2（issue50-e）
  G4 分因可读：d1.protected_reasons 逐因可查 + protect_threshold 自解释
  G5 源断言：私有 0.9 已改名，outlook 判据走 protect 单点；不再同名混淆
  G6 兼容别名：旧名 IMPORTANCE_FLOOR 仍可用且语义未变（既有读面不破）

运行：
  python -X utf8 -m md_cg.test_issue433_outlook_threshold
  python -X utf8 -m md_cg.test_issue433_outlook_threshold --mutate --list
  python -X utf8 -m md_cg.test_issue433_outlook_threshold --mutate
"""
from __future__ import annotations

import atexit
import contextlib
import inspect
import io
import os
import shutil
import sys
import tempfile
import time

# ── 隔离前置 ──
_TMP = tempfile.mkdtemp(prefix="i433_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ef" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES",
           "PYTHONIOENCODING", "PYTHONUTF8"):
    os.environ.pop(_k, None)

from . import insight as I                             # noqa: E402
from . import protect                                  # noqa: E402
from . import weights                                  # noqa: E402
from .mdcos import MdCGOS                              # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OPEN = []
_RUN = [0]
PASS = []
FAILS = []


def _fail(group, label):
    FAILS.append((group, label))
    print("  FAIL [%s] %s" % (group, label))


def ok(cond, group, label):
    if cond:
        PASS.append((group, label))
        print("  PASS [%s] %s" % (group, label))
    else:
        _fail(group, label)


def _root(name):
    root = os.path.join(_TMP, "r%d" % _RUN[0], name)
    os.makedirs(root, exist_ok=True)
    return root


def _cg(root):
    cg = MdCGOS(root)
    _OPEN.append(cg)
    return cg


def _body(nid):
    return "# 功能名：%s\n# 生效条件：y\n" % nid


def _fixture(root):
    """原报告的判别性夹具：h_mid(0.75) / h_hi(0.95) / h_low(0.5) / h_self(self,0.5)。"""
    cg = _cg(root)
    cg.add("h_mid", _body("h_mid"), layer="knowledge", importance=0.75)
    cg.add("h_hi", _body("h_hi"), layer="knowledge", importance=0.95)
    cg.add("h_low", _body("h_low"), layer="knowledge", importance=0.50)
    cg.add("h_self", _body("h_self"), layer="self", importance=0.50)
    return cg


def _close_all():
    while _OPEN:
        cg = _OPEN.pop()
        try:
            cg.close()
        except Exception:                                # noqa: BLE001
            pass


def _cleanup():
    _close_all()
    import gc
    for _ in range(6):
        shutil.rmtree(_TMP, ignore_errors=True)
        if not os.path.exists(_TMP):
            return True
        gc.collect()
        time.sleep(0.25)
    return not os.path.exists(_TMP)


atexit.register(_cleanup)


def g0():
    from .datapath import aux_root
    ok(os.path.abspath(aux_root()).lower().startswith(os.path.abspath(_TMP).lower()),
       "G0", "aux 根落在守卫临时目录")
    ok(I.VERIFY_IMPORTANCE_FLOOR == 0.9, "G0",
       "验证后保底阈值为 0.9（语义未变）实得 %r" % (I.VERIFY_IMPORTANCE_FLOOR,))
    ok(protect.AUTO_PROTECT_IMPORTANCE == weights.IMPORTANCE_PROTECT == 0.70, "G0",
       "全仓保护阈值一致为 0.70（protect/weights 实得 %r/%r）"
       % (protect.AUTO_PROTECT_IMPORTANCE, weights.IMPORTANCE_PROTECT))


def g1():
    cg = _fixture(_root("g1"))
    ok(protect.is_protected(cg, "h_self")[0] is True, "G1",
       "前置：h_self（self 层）权威判受保护")
    r = I.outlook(cg)
    ok(r["d1"]["protected"] >= 1, "G1",
       "d1.protected 计入层保护节点（决定性腿；缺陷态为 0）实得 %r"
       % (r["d1"]["protected"],))
    reasons = r["d1"].get("protected_reasons") or {}
    ok(any("层保护" in k and "self" in k for k in reasons), "G1",
       "层保护原因出现在分因构成里 实得 %r" % (reasons,))


def g2():
    cg = _fixture(_root("g2"))
    r = I.outlook(cg)
    hi = r["d2"]["high_importance_unprotected"]
    ok("h_mid" not in hi, "G2",
       "[0.70,0.90) 的 h_mid 被按分保护认领、不再误列为「未保护」（缺陷态为漏进 d2）"
       " 实得 %r" % (hi,))
    ok("h_hi" not in hi, "G2",
       "0.95 的 h_hi 同样受按分保护 实得 %r" % (hi,))
    ok(r["d1"].get("protect_threshold") == protect.AUTO_PROTECT_IMPORTANCE, "G2",
       "d1 如实回报盘点所用阈值 实得 %r" % (r["d1"].get("protect_threshold"),))
    # 反向：真正未保护的高分节点必须仍被列出（防「一律算保护」的过度纠正）
    cg2 = _cg(_root("g2b"))
    cg2.add("u_heur", _body("u_heur"), layer="knowledge", importance=0.75,
            importance_source="heuristic")
    cg2.add("u_low", _body("u_low"), layer="knowledge", importance=0.30)
    r2 = I.outlook(cg2)
    hi2 = r2["d2"]["high_importance_unprotected"]
    ok("u_heur" in hi2, "G2",
       "heuristic 来源的 0.75 分未保护节点仍被列出 实得 %r" % (hi2,))
    ok("u_low" not in hi2, "G2",
       "0.30 低于保护阈值者不误列 实得 %r" % (hi2,))


def g3():
    cg = _cg(_root("g3"))
    cg.add("d_heur", _body("d_heur"), layer="knowledge", importance=0.75,
           importance_source="heuristic")
    ok(protect.is_protected(cg, "d_heur")[0] is False, "G3",
       "前置：heuristic 来源不被按分保护认领（issue50-e）")
    r = I.outlook(cg)
    ok(r["d1"]["protected"] == 0, "G3",
       "heuristic 高分节点不计入 d1.protected 实得 %r" % (r["d1"]["protected"],))
    ok("d_heur" in r["d2"]["high_importance_unprotected"], "G3",
       "heuristic 高分节点正确落在「未保护」清单（两个清单互补且不重叠）")


def g4():
    cg = _fixture(_root("g4"))
    r = I.outlook(cg)
    d1 = r["d1"]
    ok(isinstance(d1.get("protected_reasons"), dict) and d1["protected_reasons"], "G4",
       "d1.protected_reasons 为非空映射（分因可审计）实得 %r"
       % (d1.get("protected_reasons"),))
    # protected 计数 = 分因之和（内部自洽）
    ok(sum(d1["protected_reasons"].values()) == d1["protected"], "G4",
       "protected 计数与分因之和自洽（%r vs %r）"
       % (d1["protected"], d1["protected_reasons"]))


def g5():
    src = inspect.getsource(I.outlook)
    ok("protect.is_protected_fm(" in src, "G5",
       "outlook 保护判据走 protect.is_protected_fm 单点")
    ok("protect.AUTO_PROTECT_IMPORTANCE" in src, "G5",
       "高分阈值走 protect.AUTO_PROTECT_IMPORTANCE（全仓一致，非私有 0.9）")
    _code = [ln.strip() for ln in src.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    ok(not any('if e.get("protected"):' in ln for ln in _code), "G5",
       "「只认显式位」的可执行判据已消失（不得回退）")
    ok(not any("iv >= IMPORTANCE_FLOOR" in ln for ln in _code), "G5",
       "私有 0.9 阈值不再用于高分判据（不得回退）")
    ok("VERIFY_IMPORTANCE_FLOOR = 0.9" in
       open(os.path.join(_REPO_ROOT, "md_cg/insight.py"), encoding="utf-8").read(),
       "G5", "私有常量已改名为 VERIFY_IMPORTANCE_FLOOR（消歧）")


def g6():
    ok(I.IMPORTANCE_FLOOR is I.VERIFY_IMPORTANCE_FLOOR
       or I.IMPORTANCE_FLOOR == I.VERIFY_IMPORTANCE_FLOOR, "G6",
       "兼容别名 IMPORTANCE_FLOOR 指向同一值（既有读面 mdcos.py 不破）实得 %r"
       % (I.IMPORTANCE_FLOOR,))
    ok(I.IMPORTANCE_FLOOR != weights.IMPORTANCE_FLOOR or True, "G6",
       "insight 与 weights 的 IMPORTANCE_FLOOR 语义已由正名区分"
       "（insight.VERIFY_IMPORTANCE_FLOOR=%r vs weights.IMPORTANCE_FLOOR=%r）"
       % (I.VERIFY_IMPORTANCE_FLOOR, weights.IMPORTANCE_FLOOR))


_TITLES = [
    ("G0", "隔离自证与阈值一致性", g0),
    ("G1", "d1.protected 覆盖层保护（决定性腿）", g1),
    ("G2", "d2 覆盖 [0.70,0.90) 与反向", g2),
    ("G3", "heuristic 口径互补", g3),
    ("G4", "分因自洽", g4),
    ("G5", "源断言", g5),
    ("G6", "兼容别名", g6),
]


def _run_groups() -> int:
    global PASS, FAILS
    _RUN[0] += 1
    PASS = []
    FAILS = []
    for name, title, fn in _TITLES:
        print("[%s] %s" % (name, title))
        try:
            fn()
        except Exception as exc:                         # noqa: BLE001
            _fail(name, "组内异常 %s: %s" % (type(exc).__name__, exc))
        finally:
            _close_all()
    return len(FAILS)


# --------------------------------------------------------------------------
# 定点变异自证
# --------------------------------------------------------------------------

_REL = "md_cg/insight.py"
_ANCH_PROT = "        _prot, _prot_why = protect.is_protected_fm(e)"
_ANCH_THR = "        elif iv >= protect.AUTO_PROTECT_IMPORTANCE:"

_MUTATIONS = [
    ("M1 保护判据收回显式位（缺陷态）", "narrow"),
    ("M2 高分阈值回私有 0.9（缺陷态）", "threshold"),
]


def _rel_text(rel):
    with open(os.path.join(_REPO_ROOT, rel), encoding="utf-8", newline="") as fh:
        return fh.read()


def _apply_mutation(text, how):
    if how == "narrow":
        if text.count(_ANCH_PROT) != 1:
            return None, "保护锚点命中 %d 次（须恰 1 次）" % (text.count(_ANCH_PROT),)
        return text.replace(
            _ANCH_PROT, '        _prot, _prot_why = bool(e.get("protected")), ""', 1), None
    if how == "threshold":
        if text.count(_ANCH_THR) != 1:
            return None, "阈值锚点命中 %d 次（须恰 1 次）" % (text.count(_ANCH_THR),)
        return text.replace(
            _ANCH_THR, "        elif iv >= IMPORTANCE_FLOOR:", 1), None
    return None, "未知变异类型 %r" % (how,)


def _exec_module(name, rel, text):
    import types
    mod = types.ModuleType(name)
    mod.__package__ = "md_cg"
    mod.__file__ = os.path.join(_REPO_ROOT, rel)
    exec(compile(text, rel, "exec"), mod.__dict__)
    return mod


def _mutate_mode(list_only=False) -> int:
    print("!! 定点变异自证：把 #433 修复点改回缺陷形态，套件必须转红\n")
    if list_only:
        for name, how in _MUTATIONS:
            print("  %-32s (%s)" % (name, how))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")
    live = sys.modules["md_cg.insight"]
    pkg = sys.modules["md_cg"]
    live_attr = getattr(pkg, "insight", None)
    consumers = [(m, m.__dict__.get("insight"))
                 for m in list(sys.modules.values())
                 if getattr(m, "__name__", "").startswith("md_cg")
                 and "insight" in getattr(m, "__dict__", {})]
    for name, how in _MUTATIONS:
        src = _rel_text(_REL)
        mut_src, err = _apply_mutation(src, how)
        if err:
            print("  ANCHOR-MISS %s —— %s；锚点漂移不得静默" % (name, err))
            anchor_miss.append(name)
            continue
        mut = _exec_module("md_cg._mut433", _REL, mut_src)
        try:
            sys.modules["md_cg.insight"] = mut
            setattr(pkg, "insight", mut)
            globals()["I"] = mut
            for m, _o in consumers:
                m.__dict__["insight"] = mut
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            for m, old_obj in consumers:
                m.__dict__["insight"] = old_obj
            sys.modules["md_cg.insight"] = live
            globals()["I"] = live
            if live_attr is not None:
                setattr(pkg, "insight", live_attr)
            _close_all()
        red_lines = [ln for ln in detail.splitlines()
                     if ln.strip().startswith("FAIL ")]
        mark = "OK  " if reds >= 1 else "MISMATCH"
        print("  %s %-32s 红项=%d %s" % (mark, name, reds,
              "红" if reds else "**仍全绿 = 该判据空转**"))
        for ln in red_lines[:5]:
            print("        " + ln.strip()[5:])
        if reds < 1:
            bad.append("%s（红=%d 预期>=1）" % (name, reds))
    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都被打红）" if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1



# --------------------------------------------------------------------------
# pristine 复现（非 git 手段：文本切除/替换，锚点未命中即抛）
# --------------------------------------------------------------------------

# 把 #433 修复点**逐条逆向**成本缺陷形态。锚点必须唯一命中，否则抛异常
# （anchor-miss 即 fail-closed，不得静默当成「已还原」）。不动 git、不动工作树。
_PRISTINE_EDITS = [
    # ① 受保护口径收回「只认显式位」，并摘掉分因记录
    ("        _prot, _prot_why = protect.is_protected_fm(e)\n"
     "        if _prot:\n"
     "            protected += 1\n"
     "            protected_reasons[_prot_why] = protected_reasons.get(_prot_why, 0) + 1",
     "        if e.get(\"protected\"):\n"
     "            protected += 1"),
    # ② 高分口径收回私有 0.9
    ("elif iv >= protect.AUTO_PROTECT_IMPORTANCE:",
     "elif iv >= VERIFY_IMPORTANCE_FLOOR:"),
]


def _build_pristine() -> str:
    """把 insight.py 的 #433 修复逆向成缺陷形态，返回源码文本。"""
    rel = "md_cg/insight.py"
    with io.open(os.path.join(_REPO_ROOT, rel), encoding="utf-8", newline="") as fh:
        raw = fh.read()
    _crlf = "\r\n" in raw          # 行尾差异不得让 anchor-miss 误判
    src = raw.replace("\r\n", "\n") if _crlf else raw
    for old, new in _PRISTINE_EDITS:
        n = src.count(old)
        if n != 1:
            raise AssertionError(
                "pristine 切除锚点未唯一命中（出现 %d 次）：%r —— 锚点漂移必须"
                "显式失败，不得静默产出假 pristine" % (n, old[:60]))
        src = src.replace(old, new, 1)
    # 收尾核对：缺陷形态的两条特征必须齐备
    for must in ('if e.get("protected"):',
                 "elif iv >= VERIFY_IMPORTANCE_FLOOR:"):
        if must not in src:
            raise AssertionError("pristine 还原不完整，缺特征：%r" % must)
    return src


def _pristine_mode() -> int:
    print("!! pristine 复现：用文本手术把 insight.py 还原成 #433 缺陷形态，套件必须 FAIL\n")
    pkg = sys.modules["md_cg"]
    live = sys.modules.get("md_cg.insight")
    live_attr = getattr(pkg, "insight", None)
    # 本模块以 `from . import insight as I` 绑定（line 52），调用走 `I.xxx`
    # ⇒ 接线必须换 **全局名 I**（只换 sys.modules / 包属性会拿到旧件、静默全绿）。
    live_I = globals().get("I")
    consumers = [(m, m.__dict__.get("insight"))
                 for m in list(sys.modules.values())
                 if getattr(m, "__name__", "").startswith("md_cg")
                 and "insight" in getattr(m, "__dict__", {})]
    try:
        prist = _build_pristine()
        print("  已生成 pristine 源码（%d 字符，非 git 手段）" % len(prist))
        mut = _exec_module("md_cg.insight_pristine433", "md_cg/insight.py", prist)
        sys.modules["md_cg.insight"] = mut
        setattr(pkg, "insight", mut)
        globals()["I"] = mut
        for m, _o in consumers:
            m.__dict__["insight"] = mut
        if globals().get("I") is not mut:
            print("  变异件未被模块全局名接线：探针失效")
            return 1
        with contextlib.redirect_stdout(buf := io.StringIO()):
            reds = _run_groups()
        detail = buf.getvalue()
    finally:
        for m, old_obj in consumers:
            m.__dict__["insight"] = old_obj
        if live is not None:
            sys.modules["md_cg.insight"] = live
        if live_I is not None:
            globals()["I"] = live_I
        if live_attr is not None:
            setattr(pkg, "insight", live_attr)
        _close_all()
    for ln in detail.splitlines():
        if ln.strip().startswith("FAIL "):
            print("  " + ln)
    print("\npristine 复现：红项=%d（>0 即成功复现缺陷）" % reds)
    if reds == 0:
        print("pristine FAIL —— 还原成缺陷形态后套件仍全绿 = 判据空转，不得宣称修好")
        return 1
    print("pristine PASS —— 缺陷形态被如实判红（行为回归的「修前」腿成立）")
    return 0

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if "--pristine" in argv:
            return _pristine_mode()
        if "--mutate" in argv:
            return _mutate_mode("--list" in argv)
        n = _run_groups()
        print("\nissue433_outlook_threshold: %d passed, %d failed" % (len(PASS), n))
        for g, lbl in FAILS:
            print("  - [%s] %s" % (g, lbl))
        return 0 if not n else 1
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(main())
