# -*- coding: utf-8 -*-
# 功能名：weights 保护下限判据接入既有保护规则 + recalc 写盘守卫（issue #431）
# 生效条件：python -X utf8 -m md_cg.test_issue431_weights_protected_floor [--mutate]；被测面＝md_cg/weights.py::node_importance + recalc(apply 分支)
# 子功能：A 组＝#431 正题（层保护/按分保护无位节点享有 IMPORTANCE_PROTECT 下限；apply 面补 guard_overwrite：缺省 fail-closed、override=True 快照+审计）；K 组＝非恒真对照（两侧边界、位支/未保护支不回归、常量同源、键集不变、override 缺省）；E 组＝接线单点存在性（is_protected_fm 判据 / guard_overwrite 紧邻 _write_node / 载体零 IO）
# 执行：--mutate 时在镜像树里逐条把判据改回改动前形态 / 摘守卫 / 过度收紧 / 硬编码 override，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**（多红/少红皆不合格）
# 不适用条件：不判 freshness 衰减面（#378/#430 已钉）；不判 rollback() 与 mdcos/mcp 工具面对 override 的暴露（issue 只处方 recalc apply 分支——工具面旋钮属维护者策略裁量）；不判 e_gate 档位闸（test_autonomy_modes M2⑥ 已钉）；不判 Rust 侧
"""issue #431 守卫：结构重要性的保护下限必须与**既有保护规则**同源，apply 写盘必须过双闸。

病象（修前，probeB2 实测）：`node_importance` 的下限判据只读 `e["protected"]`
一位 ⇒ `layer` 为 self/anchor（不置位）或「缺省来源高分」的节点拿到 0.10 普通
下限，`recalc(apply=True)` 把自我层/锚点节点 importance 0.5→035 系统性压低
（maintain / sustain 后台巡检面），且 `_write_node` 裸调——零快照、零
`_protected_audit` 行。与 `freshness.protected_floor`（#378/#430 修的同根分叉）
同判据：**层保护 ∪ 显式位 ∪ 按分保护（≥0.70 且来源缺省/hint）**。

修法：下限判据改为「原显式 `protected` 位 ∪ `protect.is_protected_fm` 单点」
（#430 收口的载体，零规则复制零 IO）；`recalc` 的 apply 分支在 `_write_node`
前过 `protect.guard_overwrite`（对照 `insight.verify` / `forgetting.reinforce`
同款接线），`override` 形参缺省 False ⇒ 受保护节点 fail-closed 抛
`ProtectionError`；显式 override=True ⇒ 先快照后写、留审计行——「保护不等于
黑箱」。分量公式、`IMPORTANCE_PROTECT` 取值、返回体结构、dry-run 纯度**一律
不动**。
"""
import inspect
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

from md_cg import protect as P      # noqa: E402
from md_cg import weights as W      # noqa: E402
from md_cg.mdcos import MdCGOS      # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name.split(" ")[0])


def _close(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


#: 无入边、无验证基底时的结构分（0.40×0.25 + 0.35×0 + 0.25×1）——普通下限不夹。
_SCORE_BARE = 0.35


class _Lib:
    """独立合成库（每轮独立子根：变异模式连跑多轮，共用目录会读到上一轮盘面）。"""

    _N = [0]

    def __init__(self, tag="lib"):
        _Lib._N[0] += 1
        self.root = tempfile.mkdtemp(
            prefix="iss431_%s_r%d_" % (tag, _Lib._N[0]))
        self.cg = MdCGOS(self.root, autoflush=0)

    def imp(self, nid):
        return float(((self.cg.get(nid) or {}).get("frontmatter") or {})
                     .get("importance") or 0.0)

    def close(self):
        try:
            self.cg.close()
        finally:
            shutil.rmtree(self.root, ignore_errors=True)


def _four_node_lib(tag="a"):
    """issue 原文探针口径：四节点全 importance=0.5（隔离「层保护无位」支——
    0.9 会被 cg.add 的自动打位（≥0.7）掩盖，判别力为零）。"""
    lib = _Lib(tag)
    lib.cg.add("w_self", "# 自我\n\n自我层内容。", layer="self", importance=0.5)
    lib.cg.add("w_anchor", "# 锚点\n\n锚点层内容。", layer="anchor",
               importance=0.5)
    lib.cg.add("w_mark", "# 标记\n\n知识层内容。", layer="knowledge",
               importance=0.5, protected=True, protection_reason="显式位")
    lib.cg.add("w_free", "# 自由\n\n知识层内容。", layer="knowledge",
               importance=0.5)
    lib.cg.flush()
    return lib


def _audit_rows(lib):
    p = os.path.join(lib.root, "_protected_audit.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(ln) for ln in open(p, encoding="utf-8") if ln.strip()]


# —— 档位夹具专用（不在生产码里读/写档位）：apply 腿在 confirm 档下跑，
#    免得宿主环境残留 MDCG_AUTONOMY=plan 让 e_gate 拦住、把保护腿误读成档位腿。
class _ConfirmMode:
    def __enter__(self):
        self._old = os.environ.get("MDCG_AUTONOMY")
        os.environ["MDCG_AUTONOMY"] = "confirm"
        return self

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("MDCG_AUTONOMY", None)
        else:
            os.environ["MDCG_AUTONOMY"] = self._old


print("== A 组：#431 正题——保护下限三真源 + apply 写盘双闸 ==")
_lib = _four_node_lib()
try:
    _i = W.node_importance(_lib.cg, "w_self")
    _check("A01 层保护 self（无位）：protected_floor=True 且 after=IMPORTANCE_PROTECT"
           "（修前 0.35 被降破）",
           _i["protected_floor"] is True and _close(_i["after"], 0.7), _i)

    _i = W.node_importance(_lib.cg, "w_anchor")
    _check("A02 层保护 anchor（无位）：同享保护下限（修前 0.35）",
           _i["protected_floor"] is True and _close(_i["after"], 0.7), _i)

    _i = W.node_importance(_lib.cg, "w_mark")
    _check("A03 显式位支不回归：位节点 after=0.7（修前既有行为一字不变）",
           _i["protected_floor"] is True and _close(_i["after"], 0.7), _i)

    _i = W.node_importance(_lib.cg, "w_free")
    _check("A04 未保护支不回归：普通节点 after≈0.35（不因本批被抬高）",
           _i["protected_floor"] is False and _close(_i["after"], _SCORE_BARE),
           _i)

    _dr = W.recalc(_lib.cg, apply=False, min_delta=0.0001)
    _got = {s["node_id"]: s["after"] for s in _dr["samples"]}
    _check("A05 预演报表读数：w_self/w_anchor 0.5→0.7（修前 →0.35）、"
           "w_mark→0.7、w_free→0.35，dry_run=True",
           _dr["dry_run"] is True
           and _close(_got.get("w_self"), 0.7) and _close(_got.get("w_anchor"), 0.7)
           and _close(_got.get("w_mark"), 0.7)
           and _close(_got.get("w_free"), _SCORE_BARE), _got)

    _check("A06 预演纯度：apply=False 后四节点盘面 importance 仍 0.5（纯预演不改盘）",
           all(_close(_lib.imp(n), 0.5)
               for n in ("w_self", "w_anchor", "w_mark", "w_free")),
           [_lib.imp(n) for n in ("w_self", "w_anchor", "w_mark", "w_free")])

    with _ConfirmMode():
        _raised = False
        try:
            W.recalc(_lib.cg, apply=True, min_delta=0.0001)
        except P.ProtectionError:
            _raised = True
    _check("A07 apply 缺省 override=False ⇒ ProtectionError（fail-closed："
           "层保护节点不得静默覆写；修前无异常直接压低）",
           _raised is True, _raised)

    _check("A08 拒绝即零改盘：raise 后 w_self/w_anchor 盘面 importance 仍 0.5"
           "（修前 0.5→0.35）",
           _close(_lib.imp("w_self"), 0.5) and _close(_lib.imp("w_anchor"), 0.5),
           (_lib.imp("w_self"), _lib.imp("w_anchor")))

    _check("A09 拒绝即零快照零审计：_protected_history 空、审计无 override 行"
           "（修前写盘发生而快照/审计为零——本腿钉「零来自拒绝，不是来自裸写」）",
           P.history(_lib.cg, "w_self") == [] and P.history(_lib.cg, "w_anchor") == []
           and not [r for r in _audit_rows(_lib)
                    if r.get("action") in ("override_write", "snapshot")],
           _audit_rows(_lib))
finally:
    _lib.close()

_lib2 = _Lib("ov")
try:
    _lib2.cg.add("w_self", "# 自我\n\n自我层内容。", layer="self", importance=0.5)
    _lib2.cg.add("w_free", "# 自由\n\n知识层内容。", layer="knowledge",
                 importance=0.5)
    _lib2.cg.flush()
    with _ConfirmMode():
        _r2 = W.recalc(_lib2.cg, apply=True, min_delta=0.0001, override=True,
                       actor="ov_actor")
    _check("A10 apply override=True ⇒ 层保护节点放行：w_self 盘面 0.5→0.7"
           "（保护下限在写盘方向兑现，不再是纯报表）",
           int(_r2["written"]) == 2 and _close(_lib2.imp("w_self"), 0.7),
           (_r2["written"], _lib2.imp("w_self")))

    _rows = _audit_rows(_lib2)
    _acts = {r.get("action") for r in _rows}
    _check("A11 override 路径留痕：快照数=1、审计含 snapshot+override_write、"
           "override 行 actor=传入值（保护不等于黑箱）",
           len(P.history(_lib2.cg, "w_self")) == 1
           and {"snapshot", "override_write"} <= _acts
           and any(r.get("action") == "override_write" and r.get("actor") == "ov_actor"
                   for r in _rows),
           (list(P.history(_lib2.cg, "w_self")), _acts))

    _check("A12 override 路径不误伤普通节点：同批 w_free 0.5→0.35（既有维护行为）",
           _close(_lib2.imp("w_free"), _SCORE_BARE), _lib2.imp("w_free"))
finally:
    _lib2.close()

print("== K 组：非恒真对照（两侧边界 + 既有支不回归） ==")
# entry 直喂（node_importance 的 entry 形参）：隔离「按分保护无位」支——
# 经 cg.add 写 0.75 会被写侧自动打位（≥0.7 → protected=True），判别力为零。
_e = {"layer": "knowledge", "importance": 0.75}
_i = W.node_importance(None, "probe_score", indeg={}, red={}, entry=dict(_e))
_check("K01 【享有侧】按分保护·缺省来源（0.75 无 importance_source）→ 下限 0.70",
       _i["protected_floor"] is True and _close(_i["after"], 0.7), _i)

_i = W.node_importance(None, "probe_hint", indeg={}, red={},
                       entry=dict(_e, importance_source="hint"))
_check("K02 【享有侧】importance_source == hint（显式声明）→ 享有",
       _i["protected_floor"] is True and _close(_i["after"], 0.7), _i)

_i = W.node_importance(None, "probe_heur", indeg={}, red={},
                       entry=dict(_e, importance_source="heuristic"))
_check("K03 【不享有侧】importance_source == heuristic（机器推断分）→ 不享有"
           "（issue50-e 口径不被本批翻转）",
       _i["protected_floor"] is False and _close(_i["after"], _SCORE_BARE), _i)

_i = W.node_importance(None, "probe_kn", indeg={}, red={},
                       entry={"layer": "knowledge", "importance": 0.5})
_check("K04 【不享有侧】层保护只认 self/anchor：knowledge 低分无来源 → 0.35",
       _i["protected_floor"] is False and _close(_i["after"], _SCORE_BARE), _i)

_i = W.node_importance(None, "probe_empty", indeg={}, red={}, entry={})
_check("K05 【不享有侧】空条目/无任何保护信号 → 0.35（不误判）",
       _i["protected_floor"] is False and _close(_i["after"], _SCORE_BARE), _i)

_i = W.node_importance(None, "probe_bit", indeg={}, red={},
                       entry={"layer": "knowledge", "importance": 0.5,
                              "protected": True})
_check("K06 位支一字不变：显式 protected 位（低分 knowledge）→ 下限 0.70",
       _i["protected_floor"] is True and _close(_i["after"], 0.7), _i)

_check("K07 常量同源：W.IMPORTANCE_PROTECT == P.AUTO_PROTECT_IMPORTANCE == 0.70"
           "（保护线单一真源）",
       W.IMPORTANCE_PROTECT == P.AUTO_PROTECT_IMPORTANCE
       and _close(W.IMPORTANCE_PROTECT, 0.70), W.IMPORTANCE_PROTECT)

_i = W.node_importance(None, "probe_keys", indeg={}, red={},
                       entry={"layer": "knowledge", "importance": 0.5})
_check("K08 返回体键集不变（after/before/components/node_id/protected/"
           "protected_floor）",
       sorted(_i) == sorted(["after", "before", "components", "node_id",
                             "protected", "protected_floor"]), sorted(_i))

_check("K09 override 形参缺省 False（不显式传即 fail-closed，对照 "
           "forgetting.reinforce 同口径）",
       inspect.signature(W.recalc).parameters["override"].default is False, "")

print("== E 组：接线单点存在性（判据载体收口 protect.is_protected_fm） ==")
_src_n = inspect.getsource(W.node_importance)
_check("E01 node_importance 体内经 protect.is_protected_fm(e) 接入判据（接线未脱焊）",
       "protect.is_protected_fm(e)" in _src_n,
       [l for l in _src_n.splitlines() if "is_protected" in l])

_src_r = inspect.getsource(W.recalc)
_check("E02 recalc 体内 guard_overwrite 紧邻 _write_node（守卫在写盘之前，#416 裁定）",
       _src_r.count("protect.guard_overwrite(") == 1
       and _src_r.count("cg._write_node(") == 1
       and _src_r.index("protect.guard_overwrite(")
       < _src_r.index("cg._write_node("), "")

_check("E03 判据本体不在本模块复制：weights 不自养探针载体（#430 分叉收敛），"
       "is_protected_fm 委托 is_protected",
       "_FmProbe" not in inspect.getsource(W)
       and "return is_protected(" in inspect.getsource(P.is_protected_fm), "")

_probe = P._FmProbe({"layer": "anchor"})
_check("E04 判据零 IO：载体 get() 恒 None（保护面回退分支无文件可读）且无 "
       "_maybe_reload_index（node_importance 是 O(1) 判据面，不读盘）",
       callable(getattr(_probe, "get", None)) and _probe.get("x") is None
       and not hasattr(_probe, "_maybe_reload_index"), "")

print("")
if FAILS:
    print("issue #431 结果：%d 失败" % len(FAILS))
else:
    print("issue #431 结果：全部通过")


_MUTATIONS = (
    ("M1 回缺陷：下限判据只读显式 protected 位", "md_cg/weights.py",
     ('    protected = bool(e.get("protected")) or protect.is_protected_fm(e)[0]',
      '    protected = bool(e.get("protected"))'),
     # 机制：旧判据只认位 ⇒ 层保护/按分保护两支全断——A01/A02 的 floor 与 after
     # 回落 0.35、A05 预演读数同步回落；A10 的 override 写盘方向也写成 0.35；
     # K01/K02 是按分两侧边界；E01 是源码形态腿（接线被删即脱焊）。
     ("A01", "A02", "A05", "A10", "K01", "K02", "E01")),
    ("M2 摘守卫：recalc apply 分支的 guard_overwrite 换成 pass", "md_cg/weights.py",
     ('            protect.guard_overwrite(cg, nid, layer=fm.get("layer"), sensitivity=fm.get("sensitivity"), override=override, actor=actor)',
      '            pass'),
     # 机制：守卫被摘 ⇒ 缺省 apply 不再抛（A07）、层保护节点被静默压低 0.5→0.35
     # （A08 盘面读数）、override 路径零快照零审计（A11）；E02 是源码形态腿。
     ("A07", "A08", "A11", "E02")),
    ("M3 过度收紧：下限判据恒真", "md_cg/weights.py",
     ('    protected = bool(e.get("protected")) or protect.is_protected_fm(e)[0]',
      '    protected = True'),
     # 机制：恒判受保护 ⇒ 不享有侧全被误保护——A04/A05/A12 的普通节点支抬到
     # 0.7、K03/K04/K05 的边界腿全红；E01 是源码形态腿（判据块被整体替换）。
     ("A04", "A05", "A12", "K03", "K04", "K05", "E01")),
    ("M4 旋钮焊死：override 硬编码 True（fail-closed 姿态丢失）", "md_cg/weights.py",
     ('sensitivity=fm.get("sensitivity"), override=override, actor=actor)',
      'sensitivity=fm.get("sensitivity"), override=True, actor=actor)'),
     # 机制：守卫形同虚设 ⇒ 缺省 apply 不抛（A07）、层保护节点被改写（A08 盘面
     # 0.5→0.7 而非 0.5）且拒绝路径出现快照/审计（A09 的「零来自拒绝」失真）。
     ("A07", "A08", "A09")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss431_mut_")
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
    env["MDCG_AUTONOMY"] = "confirm"     # apply 腿不因宿主残留档位而误红
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue431_weights_protected_floor"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态 / 摘守卫 / 过度收紧 / 焊死旋钮，"
          "守卫必须按指定项转红")
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
