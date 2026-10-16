# -*- coding: utf-8 -*-
# 功能名：写链两出口实参表对齐守卫（issue #414，族 1「实参表漏传」）
# 生效条件：python -X utf8 -m md_cg.test_issue414_write_args_parity [--mutate]；被测面=md_cg/writepipe.py 的 _write_values / _OUTLET_PARAMS / _OUTLET_ONLY / _outlet_kwargs 及两处调用点（_gate_gated → cg.remember_gated / _executor → cg.add）
# 子功能：A=两出口端到端逐键等价（7 项漏传已补齐）；B=表结构 + **AST 抽取两处调用实参名做全表双向断言**；K=防衍生（importance/importance_hint 两条专门断言 + 出口专有登记双向核对 + 过度收紧对照）；E=枚举完备性自证（_guard_kit 骨架①）；R=回退即绿自证（_guard_kit 骨架②）
# 执行：--mutate 时先跑双向定点变异，再跑 _guard_kit 的回退即绿自证（都是实跑，不接受推演）
# 验证方式：全部 PASS 即通过（断言总数 ≥ FLOOR）；--mutate 下每条变异的指定命中须与预期一致、回退后红项集合须恰为 {"A02","A06","A07","B03"}
# 不适用条件：不判 mdcos.remember_gated 内部的裁决语义（那是 forgetting 面）；不判超边写入是否该走 gated（属**待裁口径**，本守卫只登记不裁）；不覆盖 MCP 工具面 mdcg_remember 的 gated 分支（另一入口）
"""issue #414 守卫：同一入口两条出口的实参表必须由**一份真源**生成且逐键对齐。

病象（修前实测，见 A 组读数）：cg(op=write) 的两条真实落盘出口各写一张实参表
——_gate_gated（gated=true）与 _executor（链尾直连）——于是同一份声明在直连面落盘、
在 gated 面静默丢弃 7 项（depends_on / valid_from / valid_until / verification_state /
check_strength / session / uncertain_refs），且两次回执逐字相同（调用方看不出来）。
本仓已在该族上修过三次（B2 sensitivity / #186 session / A1 check_strength）。

本守卫的**面**（防「声称的面 > 实际覆盖的面」）：
  · B03 用 AST 抽取**两处调用的真实实参名**，与 _OUTLET_PARAMS 做**双向**全表断言
    —— 漏传 / 新增未登记 / 登记了却没有，三者都红；
  · E 组用 _guard_kit 的枚举完备性自证：把「漏一项 / 多一项未登记 / 改成裸 splat
    不可枚举」三类形态做成合成样本喂给**同一条枚举逻辑**，必须命中；
  · R 组用 _guard_kit 的回退即绿自证：把修复**真的回退**一次，实跑看是否转红。
"""
from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

# 沙箱必须在**任何** md_cg 子模块 import 之前求值（crypto.MASTER_FILE 在导入期落点）。
_SB = tempfile.mkdtemp(prefix="i414_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SB
os.environ["MDCG_ROOT"] = os.path.join(_SB, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_POLICY_FILE", None)

from . import autonomy_modes as am, nodefile, writepipe      # noqa: E402
os.environ[am.AUTONOMY_ENV_KEYS["mode"]] = "full"            # 档位面不在本件射程
from .mdcos import MdCGSecure                                # noqa: E402
from .security import Principal                              # noqa: E402
import md_cg._guard_kit as _kit                              # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR = 22
PASS, FAIL = 0, 0
FAILS = []


def _check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:240])


# ---------------------------------------------------------------- 被测面
_SRC = io.open(os.path.join(_REPO, "md_cg", "writepipe.py"),
               encoding="utf-8", newline="").read()
_GATED_COL = {p[0]: p[1] for p in writepipe._OUTLET_PARAMS}
_DIRECT_COL = {p[0]: p[2] for p in writepipe._OUTLET_PARAMS}
_GATED_PARAMS = {v for v in _GATED_COL.values() if v is not None}
_DIRECT_PARAMS = {v for v in _DIRECT_COL.values() if v is not None}
#: 每个出口**允许**的裸 splat（裸 splat 会把真源表绕开，故必须白名单化）。
#: 真源表本身的 splat（_outlet_kwargs）由 B03 单独钉，不在本表里。
_SPLAT_ALLOWED = {"remember_gated": (), "add": ("_hyperedge_extra",)}

#: 允许在调用点**手写**的实参名（＝不进真源表的出口专有键）。每条的**理由**在
#: _EXPLICIT_ONLY 里；B03 对它做**双向**核对（用到的必须登记、登记的必须被用到）。
_EXPLICIT_ALLOWED = ("layer",)
_EXPLICIT_ONLY = {
    "layer": (
        "两出口的 layer **缺省不同**（gated=contextual / direct=knowledge），是设计差异"
        "而非漏传；进真源表会把该缺省差异抹成同一个值。故必须在调用点就地声明，"
        "并由 K04 断言它**不在** _OUTLET_PARAMS 里。"),
}


def _extract_calls(src_text):
    """从源码文本抽取两出口调用的实参名。

    返回 {"remember_gated": [(显式名集, 裸splat 文本列表)], "add": [...]}——
    只认 cg.<name>(...) 这一形态（与该单点调用方的唯一形态一致）。
    """
    out = {"remember_gated": [], "add": []}
    try:
        tree = ast.parse(src_text)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.value.id == "cg" and f.attr in out):
            continue
        names = set()
        splats = []
        for kw in node.keywords:
            if kw.arg is None:
                splats.append(ast.unparse(kw.value))
            else:
                names.add(kw.arg)
        out[f.attr].append((names, splats))
    return out


_CALLS = _extract_calls(_SRC)


def _violations(texts):
    """枚举逻辑（供 _guard_kit 喂合成样本）：返回「未走真源表」的问题清单。

    #414 的修法是**单点生成**：调用点不再手写实参名，而是
    cg.<出口>(..., **_outlet_kwargs("<出口>", ctx))。故判据不是「实参名逐字对齐」
    （那正是修前的形态），而是**这条契约本身**——四类偏离各自命中：
      ① 调用点又出现**手写实参名**（绕过真源表，表改了它不跟）⇒ 命中；
      ② 缺真源表 splat（把整张表写回手写形态）⇒ 命中；
      ③ 用了**别的出口**的字面量（如 direct 点写 _outlet_kwargs('gated')）⇒ 命中
         （出口串了，两列会各取一半）；
      ④ 出现非白名单的裸 splat（不可枚举）⇒ 命中。白名单按出口分列。
    非 cg.<出口> 形态的调用（o.add / self.add）⇒ 不误伤。
    """
    bad = []
    for rel, src in texts.items():
        calls = _extract_calls(src)
        for callee in ("remember_gated", "add"):
            lit = "_outlet_kwargs('" + ("gated" if callee == "remember_gated"
                                        else "direct")
            allow = _SPLAT_ALLOWED[callee]
            for names, splats in calls[callee]:
                stray = sorted(names - set(_EXPLICIT_ALLOWED))
                if stray:
                    bad.append((rel, callee, "手写实参绕过真源表：%s" % stray))
                if not [s for s in splats if lit in s]:
                    bad.append((rel, callee, "缺真源表 splat：%s" % lit))
                strange = [s for s in splats
                           if lit not in s and not any(w in s for w in allow)]
                if strange:
                    bad.append((rel, callee, "非白名单 splat：%s" % strange))
    return bad
# ---------------------------------------------------------------- A 组：端到端逐键等价
print("== A 组：两出口端到端逐键等价（修前 7 项漏传）==")

_KEK = os.urandom(32)
_CCG = ("# 功能名：写链两出口对拍探针\n"
        "# 生效条件：当对拍 gated 两出口时\n"
        "# 子功能：断言同一份声明在两条出口的落盘 fm 逐键一致\n"
        "# 执行：逐键对照\n"
        "# 验证方式：test\n"
        "# 不适用条件：无\n\n正文 probe %s\n")
#: 修前实测两条出口不一致的键（报告 §二 的读数面）；本组断言它们现已逐键相等。
_TARGET_KEYS = ("depends_on", "valid_from", "valid_until", "verification_state",
                "check_strength", "session", "uncertain_refs")


def _mk_cg(tag):
    return MdCGSecure(
        os.path.join(_SB, "lib_" + tag),
        principal=Principal(tenant="t1", actor="alice", role="designer",
                            clearance="secret", can_write=True, can_admin=True),
        master_key=_KEK)


def _run_outlet(gated):
    tag = "g" if gated else "d"
    cg = _mk_cg(tag)
    cg.add("n_dep", _CCG % "dep", layer="knowledge", verification_basis="test")
    a = {"content_kind": "text", "content": _CCG % tag, "layer": "contextual",
         "node_id": "n_" + tag, "gated": gated, "verification_basis": "test",
         "tags": ["t_decl"], "condition_space": {"conditions": ["arm"]},
         "non_applicable_conditions": ["情感交互"], "importance": 0.62,
         "override": False, "derived_from": ["n_dep"], "relation": "derived_from",
         "depends_on": ["n_dep"], "valid_from": "2026-01-01",
         "valid_until": "2027-01-01", "verification_state": "verified",
         "check_strength": "hoop", "session": "arm_sess"}
    out = writepipe.install_default_gates(writepipe.WritePipeline()).execute(cg, a)
    e = cg.index["nodes"].get("n_" + tag)
    fm = {}
    if e:
        with io.open(cg._node_disk_path(e), encoding="utf-8") as f:
            fm, _c = nodefile.loads(f.read())
    return out, fm


try:                              # 表与取值单点脱节时在此报红，不崩
    _OUT_D, _FM_D = _run_outlet(False)
    _OUT_G, _FM_G = _run_outlet(True)
    _RUN_ERR = None
except Exception as _e:                                    # noqa: BLE001
    _OUT_D = _OUT_G = _FM_D = _FM_G = {}
    _RUN_ERR = "%s: %s" % (type(_e).__name__, _e)
_check("A00 前置：两条出口端到端可跑通（真源表与取值单点脱节时在此显式报红）",
       _RUN_ERR is None, _RUN_ERR)

_check("A01 前置：两条出口都真的落盘（防「被拒所以看不出差异」的假绿）",
       _OUT_D.get("committed") is True and _OUT_G.get("committed") is True,
       (_OUT_D.get("moved_to"), _OUT_G.get("moved_to")))
_check("A01 前置：回执三项逐字相同（调用方看不出差异＝本族的危害形态）",
       all(_OUT_D.get(k) == _OUT_G.get(k) for k in ("ok", "committed", "moved_to")),
       (_OUT_D.get("ok"), _OUT_G.get("ok")))

_DIFF = [k for k in _TARGET_KEYS if _FM_D.get(k) != _FM_G.get(k)]
_check("A02 ★两出口逐键等价（7 项漏传已补齐）", not _DIFF,
       [(k, _FM_D.get(k), _FM_G.get(k)) for k in _DIFF])

_check("A03 importance 两出口同值（拼写等价的落盘证据：importance↔importance_hint）",
       _FM_D.get("importance") == _FM_G.get("importance")
       and _FM_D.get("importance") == 0.62,
       (_FM_D.get("importance"), _FM_G.get("importance")))

_check("A04 ★设计差异**必须保持不等价**：importance_source 直连=None / gated=hint"
       "（若有人「顺手补齐」把两者改成同值，本条转红——补齐会拆掉 gated 的裁决语义）",
       _FM_D.get("importance_source") is None
       and _FM_G.get("importance_source") == "hint",
       (_FM_D.get("importance_source"), _FM_G.get("importance_source")))

_BLANK = writepipe._write_values({"a": {}, "verdict": None})
_check("A05 过度收紧对照：直连面缺省 0.5 / gated 面 hint 为 None，两者缺省语义未被改成同一个",
       _BLANK["importance"] == 0.5 and _BLANK["importance_hint"] is None, _BLANK)
_ZERO = writepipe._write_values({"a": {"importance": 0.0}, "verdict": None})
_check("A05 过度收紧对照：显式 0.0 不被当假值丢掉（与 add 缺省同口径）",
       _ZERO["importance"] == 0.0 and _ZERO["importance_hint"] == 0.0, _ZERO)

# A06：补的键不只是「传进去了」，而是**真的落盘**（盘面 fm 直读）
_check("A06 gated 面回执与盘面一致：落盘键集与 fm 真值同源（不靠回执自述）",
       _FM_G.get("depends_on") == ["n_dep"] and _FM_G.get("check_strength") == "hoop"
       and _FM_G.get("valid_from") == "2026-01-01",
       {k: _FM_G.get(k) for k in _TARGET_KEYS})

# A07：A2 幽灵引用标记（uncertain_refs）——链序上 ghostref 早于 gated，
# 故两出口都能取到同一个值；修前 gated 面整项丢（实测 None）。
_GHOST = ("# 功能名：幽灵引用对拍探针\n# 生效条件：当对拍幽灵引用时\n"
          "# 子功能：对照两出口\n# 执行：逐键对照\n# 验证方式：test\n"
          "# 不适用条件：无\n\n上次说的那批帐篷 %s\n")


def _run_ghost(gated):
    tag = "gh" if gated else "gd"
    cg = _mk_cg(tag)
    out = writepipe.install_default_gates(writepipe.WritePipeline()).execute(cg, {
        "content_kind": "text", "content": _GHOST % tag, "layer": "contextual",
        "node_id": "n_" + tag, "gated": gated, "verification_basis": "test"})
    e = cg.index["nodes"].get("n_" + tag)
    with io.open(cg._node_disk_path(e), encoding="utf-8") as f:
        fm, _c = nodefile.loads(f.read())
    return out, fm


try:
    _GO_D, _GF_D = _run_ghost(False)
    _GO_G, _GF_G = _run_ghost(True)
    _GHOST_ERR = None
except Exception as _e:                                    # noqa: BLE001
    _GO_D = _GO_G = _GF_D = _GF_G = {}
    _GHOST_ERR = "%s: %s" % (type(_e).__name__, _e)
_check("A07 前置：幽灵引用对拍可跑通（同上，脱节时显式报红）", _GHOST_ERR is None,
       _GHOST_ERR)
_check("A07 ★幽灵引用标记（uncertain_refs）两出口同类：修前 gated 面为 None",
       bool(_GF_D.get("uncertain_refs")) and _GF_D.get("uncertain_refs") == _GF_G.get("uncertain_refs"),
       (_GF_D.get("uncertain_refs"), _GF_G.get("uncertain_refs")))
_check("A07 幽灵引用**出口告警**仍在直连面（gated 面缺该字段＝回执面同族缺口，"
       "已登记、本批不擅改——见汇报「待裁」项）",
       bool(_GO_D.get("ghost_refs")), sorted(_GO_G.keys()))

# ---------------------------------------------------------------- B 组：表结构 + AST 全表
print("")
print("== B 组：真源表结构 + AST 全表双向断言 ==")

_VALS = writepipe._write_values({"a": {}, "verdict": None})
_check("B01 语义键集 == _write_values 的返回键集（表与取值单点不脱节）",
       set(_VALS) == set(_GATED_COL) == set(_DIRECT_COL),
       (sorted(set(_VALS) - set(_GATED_COL)), sorted(set(_GATED_COL) - set(_VALS))))
_rows = [p for p in writepipe._OUTLET_PARAMS if not (isinstance(p, tuple) and len(p) == 3)]
_check("B01 _OUTLET_PARAMS 每行都是三元组、键唯一",
       not _rows and len(set(_GATED_COL)) == len(writepipe._OUTLET_PARAMS), _rows)
_check("B01 表非空转：语义键数 >= 15（防表被清空后恒真）",
       len(writepipe._OUTLET_PARAMS) >= 15, len(writepipe._OUTLET_PARAMS))
_check("B01 归一单点：depends_on 经 trust.as_deps 归一（不各自 split，避免第二套口径）",
       writepipe._write_values({"a": {"depends_on": ["n_x"]},
                                "verdict": None})["depends_on"]
       == writepipe.trust.as_deps(["n_x"]),
       writepipe._write_values({"a": {"depends_on": ["n_x"]},
                                "verdict": None})["depends_on"])

_check("B02 单点调用：writepipe 内 cg.remember_gated 恰 1 处、cg.add 恰 1 处"
       "（多处则本表覆盖不全，须扩表）",
       len(_CALLS["remember_gated"]) == 1 and len(_CALLS["add"]) == 1,
       (len(_CALLS["remember_gated"]), len(_CALLS["add"])))

_g_names, _g_splats = _CALLS["remember_gated"][0]
_d_names, _d_splats = _CALLS["add"][0]
#: 调用点真实传出的形参名 = 真源表经 _outlet_kwargs 求值的结果（**这一步才是
#: 「实际实参名 == 表」的机械断言**——调用点本身只写一个 splat，见下一条）。
try:
    _KW_G = set(writepipe._outlet_kwargs("gated", {"a": {}, "verdict": None}))
    _KW_D = set(writepipe._outlet_kwargs("direct", {"a": {}, "verdict": None}))
    _KW_ERR = None
except Exception as _e:          # noqa: BLE001 —— 表与取值单点脱节时报红，不崩
    _KW_G, _KW_D, _KW_ERR = set(), set(), "%s: %s" % (type(_e).__name__, _e)
_check("B03 前置：_outlet_kwargs 对两出口可求值（表键 ⊆ 取值单点键，脱节即红不崩）",
       _KW_ERR is None, _KW_ERR)
_check("B03 ★全表双向断言（一）：_outlet_kwargs 求出的形参名集 == 真源表两列"
       "（漏 / 多都红）",
       _KW_G == _GATED_PARAMS and _KW_D == _DIRECT_PARAMS,
       {"gated": (sorted(_GATED_PARAMS - _KW_G), sorted(_KW_G - _GATED_PARAMS)),
        "direct": (sorted(_DIRECT_PARAMS - _KW_D), sorted(_KW_D - _DIRECT_PARAMS))})
_USED_EXPLICIT = _g_names | _d_names
_check("B03 ★全表双向断言（二）：调用点手写的实参名 == 出口专有白名单"
       "（未登记的手写即红；登记了却没被用到也红）",
       _USED_EXPLICIT == set(_EXPLICIT_ALLOWED),
       {"未登记的": sorted(_USED_EXPLICIT - set(_EXPLICIT_ALLOWED)),
        "登记了却没用到": sorted(set(_EXPLICIT_ALLOWED) - _USED_EXPLICIT)})
_check("B03 ★全表双向断言（三）：两处调用各自的真源 splat 字面量正确"
       "（出口串了就各取一半）",
       any("_outlet_kwargs('gated'" in s for s in _g_splats)
       and any("_outlet_kwargs('direct'" in s for s in _d_splats),
       (_g_splats, _d_splats))
_check("B03 裸 splat 白名单按出口分列（gated 不容许额外 splat；direct 只容许超边扩展键）",
       all(any(w in s for w in _SPLAT_ALLOWED["remember_gated"])
           or "_outlet_kwargs('gated'" in s for s in _g_splats)
       and all(any(w in s for w in _SPLAT_ALLOWED["add"])
               or "_outlet_kwargs('direct'" in s for s in _d_splats),
       (_g_splats, _d_splats))
# 枚举逻辑自身的判别力：直接把它喂给**真实源码**，必须 0 命中（否则守卫在自欺）
_check("B03 枚举逻辑对**真实 writepipe 源码**判定 0 命中",
       not _violations({"md_cg/writepipe.py": _SRC}),
       _violations({"md_cg/writepipe.py": _SRC}))

_none_cells = {(k, "gated") for k, g, _d in writepipe._OUTLET_PARAMS if g is None}
_none_cells |= {(k, "direct") for k, _g, d in writepipe._OUTLET_PARAMS if d is None}
_reg = set(writepipe._OUTLET_ONLY)
_check("B04 ★出口专有登记**双向**核对：None 格 ⊆ 登记 且 登记 ⊆ None 格"
       "（单向会退化成「登记一次永久免死」）",
       _none_cells == _reg, {"未登记": sorted(_none_cells - _reg),
                             "登记了却没有": sorted(_reg - _none_cells)})
_check("B04 登记理由非空且够具体（>=20 字，防占位式登记）",
       all(isinstance(v, str) and len(v) >= 20
           for v in writepipe._OUTLET_ONLY.values()),
       [(k, len(str(v))) for k, v in writepipe._OUTLET_ONLY.items()
        if not (isinstance(v, str) and len(v) >= 20)])

try:
    writepipe._outlet_kwargs("nope", {"a": {}, "verdict": None})
    _check("B05 出口名拼错即抛 ValueError（fail-closed，不静默落空）", False, "未抛")
except ValueError:
    _check("B05 出口名拼错即抛 ValueError（fail-closed，不静默落空）", True)
except Exception as _e:                                        # noqa: BLE001
    _check("B05 出口名拼错即抛 ValueError（fail-closed，不静默落空）", False, _e)
# ---------------------------------------------------------------- K 组：防衍生
print("")
print("== K 组：防衍生（importance 等价性两条 + 出口专有 + 过度收紧）==")

_RG_SRC = ""
_rg = os.path.join(_REPO, "md_cg", "mdcos.py")
if os.path.exists(_rg):
    _RG_SRC = io.open(_rg, encoding="utf-8", newline="").read()
_check("K01 ★「同一语义键两拼写」的 callee 面证据仍在（remember_gated 的 kw.pop 双拼写）"
       "——这条是 importance 不进漏传集的唯一依据",
       'kw.pop("importance_hint", kw.get("importance"))' in _RG_SRC,
       "mdcos.remember_gated 的双拼写 pop 不见了 ⇒ importance 的等价性判定依据失效")

_check("K02 ★落盘值不等价**不得被当成漏传补齐**：断言 gated 面**不传** importance、"
       "direct 面**不传** importance_hint（判据取自**真源表派生的形参集**；"
       "若误用调用点手写名，本条会空转）",
       "importance" not in _KW_G and "importance_hint" not in _KW_D,
       (sorted(_KW_G & {"importance"}), sorted(_KW_D & {"importance_hint"})))

_check("K03 role 是**出口专有**（add 无该形参）：direct 面不得传 role",
       "role" not in _KW_D and "role" in _KW_G, sorted(_KW_D & {"role"}))
_check("K03 同向：uncertain_refs / depends_on / valid_from / valid_until / "
       "verification_state / check_strength / session 七项两侧都传（漏传集已补齐）",
       all(k in _KW_G and k in _KW_D for k in _TARGET_KEYS),
       [k for k in _TARGET_KEYS if not (k in _KW_G and k in _KW_D)])

_check("K04 过度收紧方向：layer / content_kind **不在**真源表里"
       "（两出口 layer 缺省不同：contextual vs knowledge；进表会抹掉该缺省差异）",
       "layer" not in _VALS and "content_kind" not in _VALS,
       sorted({"layer", "content_kind"} & set(_VALS)))

# ---------------------------------------------------------------- E 组：枚举完备性自证
print("")
print("== E 组：枚举完备性自证（_guard_kit 骨架①）==")


def _call_src(callee, names, splat=None):
    tail = "".join(", %s=1" % n for n in sorted(names))
    if splat:
        tail += ", **%s" % splat
    return ("def f(cg, nid, c):\n"
            "    return cg.%s(nid, c%s)\n" % (callee, tail))


def _splat_src(callee, outlet, extra=None):
    tail = ", **_outlet_kwargs('%s', ctx)" % outlet
    if extra:
        tail += ", **%s" % extra
    return ("def f(cg, nid, c, ctx, a):\n"
            "    return cg.%s(nid, c%s)\n" % (callee, tail))


_SAMPLES = [
    ("①gated 点**手写实参**绕过真源表（表改了它不跟）",
     "def f(cg, nid, c, ctx):\n"
     "    return cg.remember_gated(nid, c, **_outlet_kwargs('gated', ctx), tags=1)\n",
     True, "synthetic/handwrite_gated.py"),
    ("②direct 点**用错出口字面量**（出口串了 ⇒ 两列各取一半）",
     _splat_src("add", "gated"), True, "synthetic/wrong_outlet.py"),
    ("③缺真源表 splat（退回修前的手写两表形态）",
     _call_src("add", _DIRECT_PARAMS), True, "synthetic/no_splat.py"),
    ("④gated 正确形态（合法的单点 splat，不得误判）",
     _splat_src("remember_gated", "gated"), False, "synthetic/ok_gated.py"),
    ("⑤direct 正确形态（单点 splat + 白名单超边 splat）",
     _splat_src("add", "direct", extra="_hyperedge_extra(a)"),
     False, "synthetic/ok_direct.py"),
    ("⑥gated 点出现非白名单的额外 splat",
     _splat_src("remember_gated", "gated", extra="_whatever(x)"),
     True, "synthetic/alien_splat.py"),
    ("⑦只手写 layer（白名单内，合法）",
     "def f(cg, nid, c, ctx):\n"
     "    return cg.add(nid, c, layer='knowledge', **_outlet_kwargs('direct', ctx))\n",
     False, "synthetic/ok_layer.py"),
    ("⑧非 cg.<出口> 形态（不得误伤）",
     "def f(o, nid, c):\n    return o.add(nid, c, whatever=1)\n",
     False, "synthetic/other.py"),
]
_ok_e, _det_e = _kit.assert_enumeration_complete(_violations, _SAMPLES)
_check("E01 ★枚举完备性自证：%d 类形态（手写绕过/串出口/缺 splat/非白名单 splat/"
       "两种合法/白名单 layer/不误伤）喂同一条枚举逻辑，命中与否须全符预期"
       % len(_SAMPLES), _ok_e, _det_e)

print("")
print("断言总数 %d（PASS %d / FAIL %d），FLOOR=%d" % (PASS + FAIL, PASS, FAIL, FLOOR))
if PASS + FAIL < FLOOR:
    FAILS.append("FLOOR")
    print("  FAIL 断言总数低于 FLOOR —— 探针面疑似失效（防假绿）")

if FAILS:
    print("issue #414 结果：%d 失败" % len(FAILS))
    for _f in FAILS:
        print("   - " + _f)
else:
    print("issue #414 结果：全部通过")
# ---------------------------------------------------------------- 镜像树 / 变异 / 回退
_MIRROR_DIRS = ("md_cg", "data", "scripts")
_MIRROR_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "jobs", "target",
                                      "node_modules")
_TARGET = "md_cg/writepipe.py"

#: 双向定点变异：V1 覆盖方向（漏传回归）/ V2 过度收紧（把缺省不同的键塞进表）/
#: V3 防衍生（拆掉 hint 语义）/ V4 登记方向（撤登记）。
_MUTATIONS = (
    ("V1 覆盖方向：depends_on 的 gated 列改成 None（漏传回归）",
     '    ("depends_on", "depends_on", "depends_on"),',
     '    ("depends_on", None, "depends_on"),',
     ("A02", "A06", "B04", "K03")),
    ("V2 过度收紧方向：把 layer 塞进真源表（抹掉两出口缺省差异）",
     '    ("sensitivity", "sensitivity", "sensitivity"),',
     '    ("sensitivity", "sensitivity", "sensitivity"),\n'
     '    ("layer", "layer", "layer"),',
     ("A00", "B01", "B03")),
    ("V3 防衍生方向：gated 面改传 importance（拆掉 hint 语义）",
     '    ("importance_hint", "importance_hint", None),',
     '    ("importance_hint", "importance", None),',
     ("K02",)),
    ("V4 登记方向：撤掉 role 的出口专有登记（双向核对失守）",
     '    ("role", "direct"): (',
     '    ("role", "direct_UNREGISTERED"): (',
     ("B04",)),
)


def _mirror_build():
    """镜像树：拷 md_cg/data/scripts + 根级 .py（真实工作树只读）。"""
    dst = tempfile.mkdtemp(prefix="i414_mut_")
    for name in _MIRROR_DIRS:
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name), ignore=_MIRROR_SKIP)
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _fold(text, eol):
    """按目标文件实际行尾折算（本仓 CRLF/LF 混合）。"""
    return text.replace("\r\n", "\n").replace("\n", eol)


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue414_write_args_parity"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    # 只认断言行的 FAIL（摘要行含 FAIL 字样，不能计入）
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.startswith("  FAIL ")]
    return pr.returncode, reds, out


def _apply(tree, rel, old, new):
    p = os.path.join(tree, rel.replace("/", os.sep))
    with io.open(p, encoding="utf-8", newline="") as f:
        t = f.read()
    eol = "\r\n" if "\r\n" in t else "\n"
    o, n = _fold(old, eol), _fold(new, eol)
    if t.count(o) != 1:
        return None, "锚点命中 %d 次" % t.count(o)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t.replace(o, n, 1))
    return t, ""


def _mutate():
    print("!! 双向定点变异自证（镜像树）")
    tree = _mirror_build()
    bad = 0
    try:
        rc0, reds0, out0 = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（须 rc=0 且 0 红）" % (rc0, len(reds0)))
        if rc0 != 0 or reds0:
            bad += 1
            print("\n".join(out0.splitlines()[-20:]))
        for desc, old, new, exp in _MUTATIONS:
            bak, why = _apply(tree, _TARGET, old, new)
            if bak is None:
                bad += 1
                print("  ANCHOR-MISS %s —— %s" % (desc, why))
                continue
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with io.open(os.path.join(tree, _TARGET.replace("/", os.sep)),
                         "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and all(e in hit for e in exp):
                print("  OK   %s  红项=%d 命中=%s" % (desc, len(reds2), hit))
            else:
                bad += 1
                print("  MISMATCH %s  实际红项=%s  期望含=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
    finally:
        shutil.rmtree(tree, ignore_errors=True)
    return bad


#: **回退即绿自证**（_guard_kit 骨架② / task-16 要求 2 / #421 的指控点）：把修复本体
#: **真的回退**一次（两处编辑：本地 hint 计算的恢复 + 显式实参表的恢复），实跑守卫看
#: 红项是否恰为 {"A02","A06","A07","B03"} —— 不接受推演（**实测值**，非推演）。
_REVERT = [
    ("md_cg/writepipe.py",
     "    # #414：hint 的取值（含 importance 回落）已收进 _write_values 单点。",
     '    hint = a.get("importance_hint")\n'
     '    if hint is None and a.get("importance") is not None:\n'
     '        hint = float(a["importance"])'),
    ("md_cg/writepipe.py",
     '    res = cg.remember_gated(\n'
     '        ctx["nid"], a.get("content", ""), layer=a.get("layer") or "contextual",\n'
     '        **_outlet_kwargs("gated", ctx))',
     '    res = cg.remember_gated(\n'
     '        ctx["nid"], a.get("content", ""), layer=a.get("layer") or "contextual",\n'
     '        sensitivity=a.get("sensitivity"),\n'
     '        role=a.get("role"), tags=a.get("tags"),\n'
     '        condition_space=a.get("condition_space"),\n'
     '        verification_basis=(a.get("verification_basis")\n'
     '                            or (ctx.get("verdict") or {}).get("basis")),\n'
     '        non_applicable_conditions=a.get("non_applicable_conditions"),\n'
     '        importance_hint=hint, override=bool(a.get("override")),\n'
     '        consistency=False,\n'
     '        derived_from=_split_ids(a.get("derived_from")),\n'
     '        relation=a.get("relation"))'),
]


def _revert_proof():
    print("!! 回退即绿自证（_guard_kit.assert_revert_reddens，实跑）")
    _ok, _det = _kit.assert_revert_reddens(_mirror_build, _REVERT, _run_in,
                                           # 实测：回退后 4 个判据面同时转红
                                           # （A02/A06=盘面、A07=幽灵标记、B03=splat 契约）
                                           tuple(["A02", "A06", "A07", "B03"]), "?")
    print("  %s 红项=%s" % ("OK  " if _ok else "FAIL", _det.get("实际红项")))
    if not _ok:
        print("  不合格：" + str(_det)[:600])
    return 0 if _ok else 1


def main():
    bad = 0
    if "--mutate" in sys.argv:
        bad += _mutate()
        if bad == 0:
            bad += _revert_proof()
    return 1 if (FAILS or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
