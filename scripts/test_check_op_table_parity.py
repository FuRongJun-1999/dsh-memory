# -*- coding: utf-8 -*-
"""`scripts/check_op_table_parity.py` 的自证测试（issue #133 + #140）。

为什么需要它：本守卫的判据是「三向对账 + 定点变异必红」——如果守卫自己空转
（基线不绿、变异不红），它就是假绿灯。本测试把守卫当**被测对象**：

  A 基线绿：对账在**本仓现状**上必须通过（含失败编码运行时抽样）。
  B 变异必红：守卫自带的 5 条定点变异**逐条**必须转红，且红项关键词命中。
  C 判据有判别力（合成语料）：手工构造「枚举多一项 / 表少一项 / require 词不符」
    三类残骸喂给守卫的纯函数 `parity()`，必须各自报出对应失败项。
  D 守卫自身可运行：`--selftest` / `--json` / `--mutate` 三个入口退出码正确。
  E 与既有守卫不冲突：`md_cg.test_tool_face` / `md_cg.test_protocol` /
    `md_cg.test_write_return_shape` 仍全绿（重构前后对外行为不变——本批硬要求）。

运行：python -m scripts.test_check_op_table_parity
（也可：python -X utf8 scripts/test_check_op_table_parity.py）
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_ok = 0
_fail: list = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _fail.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


def _load_guard():
    """把守卫当模块载入（不走包，避免 scripts 无 __init__ 的导入差异）。"""
    path = os.path.join(_HERE, "check_op_table_parity.py")
    spec = importlib.util.spec_from_file_location("_op_table_parity_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ==================== A. 基线绿 ====================
print("-- A 基线：对账在本仓现状必须通过 --")
G = _load_guard()
_tmp, _restore = G.enter_sandbox()
try:
    _base = G.collect()
    _rep = G.parity(_base)
    check("A1 三向对账基线无失败项", not _rep["errors"], _rep["errors"])
    r = _rep["readings"]
    check("A2 enum == dispatch == 表（各 38）",
          r["n_enum"] == r["n_dispatch"] == r["n_table"] == 38,
          (r["n_enum"], r["n_dispatch"], r["n_table"]))
    check("A3 段落面 37 段（help 无段）", r["n_sections"] == 37, r["n_sections"])
    check("A4 参数归属无缺口（并集 %d + 通用 %d == schema %d − 1）"
          % (r["n_params_union"], r["n_generic"], r["n_props"]),
          r["n_params_union"] + r["n_generic"] == r["n_props"] - 1,
          (r["n_params_union"], r["n_generic"], r["n_props"]))
    _allacts = [a for t in _base["table"].values() for a in (t.get("actions") or ())]
    check("A5 二级子 op 已登记且含 rounds/handshake/catalog",
          all(p in _allacts for p in ("rounds", "handshake", "catalog")),
          {o: _base["table"][o]["actions"] for o in ("review", "link")
           if o in _base["table"]})
    check("A6 tool_face 无写死 op 计数", r["tool_face_hardcoded_counts"] == 0,
          r["tool_face_hardcoded_counts"])
    check("A7 失败编码形态登记 = 3 类且未统一（待裁）",
          len(r["failure_forms"]) == 3 and r["failure_forms_unified"] is False,
          r["failure_forms"])
    check("A8 require 词映射读出 state_event→write",
          r["require_map"].get("state_event") == "write", r["require_map"])
    _wire = G.probe_failure_forms()
    check("A9 失败编码运行时抽样与登记一致（3 形态逐位）", not _wire, _wire)
finally:
    _restore()


# ==================== B. 定点变异必红 ====================
print("-- B 定点变异：逐条抽掉修复 ⇒ 必红 --")
_mut = G.mutations()
check("B1 变异表 ≥5 条", len(_mut) >= 5, len(_mut))
for _name, _fn, _kw in _mut:
    _t2, _r2 = G.enter_sandbox()
    try:
        _b2 = G.collect()
        _clean = G.parity(_b2)
        _mutrep = G.parity(_fn(_b2))
    finally:
        _r2()
    _hit = [e for e in _mutrep["errors"] if _kw in e]
    check("B2 变异转红：%s" % _name, (not _clean["errors"]) and bool(_hit),
          "基线=%s 命中=%s" % (_clean["errors"][:1], _hit[:1]))

# 复现 issue 原始变异：只删枚举串里的 ccg（表与 dispatch 保留）⇒ 必红
_t3, _r3 = G.enter_sandbox()
try:
    _b3 = G.collect()
    _b3 = dict(_b3)
    _b3["enum"] = [o for o in _b3["enum"] if o != "ccg"]
    _mut3 = G.parity(_b3)
finally:
    _r3()
check("B3 复现 issue 原始变异（只删枚举串 ccg）⇒ 转红",
      any("enum ↔ dispatch 不相等" in e for e in _mut3["errors"]),
      _mut3["errors"][:2])


# ==================== C. 合成语料：判据有判别力 ====================
print("-- C 合成语料：三类残骸各报其错 --")
_t4, _r4 = G.enter_sandbox()
try:
    _b4 = G.collect()
    # C1 枚举多一项（幻影枚举）
    _x = dict(_b4)
    _x["enum"] = list(_b4["enum"]) + ["__ghost_op__"]
    check("C1 枚举多一项 ⇒ 报「不相等」",
          any("不相等" in e for e in G.parity(_x)["errors"]),
          G.parity(_x)["errors"][:1])
    # C2 表里登记一个 schema 不存在的参数（幻影参数）
    _y = dict(_b4)
    _y["params_of"] = dict(_b4["params_of"])
    _y["params_of"] = {k: (list(v) + (["__ghost_param__"] if k == "read" else []))
                       for k, v in _b4["params_of"].items()}
    check("C2 登记幻影参数 ⇒ 报「幻影参数」",
          any("幻影参数" in e for e in G.parity(_y)["errors"]),
          G.parity(_y)["errors"][:1])
    # C3 require 词不符
    _z = dict(_b4)
    _z["src_ms"] = _b4["src_ms"].replace(
        '        _p.require_op("write" if op == "state_event" else op)',
        '        _p.require_op("read")')
    import ast as _ast
    _z["tree_ms"] = _ast.parse(_z["src_ms"])
    check("C3 require 词不符 ⇒ 报「require 词对不上」",
          any("require 词对不上" in e for e in G.parity(_z)["errors"]),
          G.parity(_z)["errors"][:1])
finally:
    _r4()


# ==================== D. 守卫入口可运行 ====================
print("-- D 守卫入口：退出码正确 --")
_env = dict(os.environ)
_env["PYTHONUTF8"] = "1"
_guard_path = os.path.join(_HERE, "check_op_table_parity.py")


def _run(args):
    return subprocess.run([sys.executable, "-X", "utf8", _guard_path] + args,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_env, cwd=_REPO)


_r = _run(["--selftest"])
check("D1 --selftest 退 0", _r.returncode == 0, _r.stdout[-200:])
_r = _run(["--mutate"])
check("D2 --mutate 退 0（5/5 转红）", _r.returncode == 0, _r.stdout[-300:])
_r = _run(["--json"])
check("D3 --json 退 0 且 ok=true",
      _r.returncode == 0 and '"ok": true' in _r.stdout, _r.stdout[-200:])
_r = _run([])
check("D4 默认入口退 0", _r.returncode == 0, _r.stdout[-200:])


# ==================== E. 既有守卫仍全绿（对外行为不变） ====================
print("-- E 既有守卫回归：重构前后对外行为不变 --")
for _m in ("md_cg.test_tool_face", "md_cg.test_protocol",
           "md_cg.test_write_return_shape", "md_cg.test_action_derive",
           "md_cg.test_state_event_op", "md_cg.test_read_face_input_gates"):
    _r = subprocess.run([sys.executable, "-X", "utf8", "-m", _m],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=_env, cwd=_REPO)
    check("E %s 仍全绿" % _m, _r.returncode == 0, _r.stdout[-160:])

print("")
print("%d passed, %d failed" % (_ok, len(_fail)))
if _fail:
    print("失败项：" + "; ".join(_fail))
sys.exit(1 if _fail else 0)
