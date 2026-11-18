# -*- coding: utf-8 -*-
"""Issue #434 硬前置 #2 守卫：切断 md_cg/stg.py ↔ md_cg/mcp_server.py 双向惰性循环。

背景（`lingshu` 文档《docs/plans/插件化拆分_同仓多包_准备_v0.1.md》§二.2）：
    `mcp_server.py`（adapter 层）在 `_stg_call` 内惰性 `from . import stg`；
    此前 `stg.py` 在 `_env_session_authority` / `_view_session` /
    `_session_declaration_ignored` 三处反向 `from .mcp_server import _normalize_session`，
    构成 `stg ↔ mcp_server` 双向循环。

修复：
    将无宿主依赖的会话归一化函数下沉到公共叶模块 `md_cg/session_norm.py`；
    `stg.py` 与 `mcp_server.py` 单向共消费 `session_norm`，`mcp_server._stg_call`
    通过 `normalize_session` 可选参数保留测试替身注入兼容性，外部对
    `mcp_server._normalize_session` / `_is_dsh_session` / `_is_session5_like`
    的导入面保持不变。

判据：
    G1 静态 AST：`stg.py` 零 `mcp_server` 导入边（含相对/绝对/别名/importlib）；
       `session_norm.py` 零 `stg`/`mcp_server` 反向导入边。
    G2 隔离运行：子进程阻断 `sys.modules["md_cg.mcp_server"] = None` 时，
       `stg` 可独立导入且 `_view_session` / `timeline` 仍正确执行 DSH 归一化，
       不触发 `mcp_server` 加载。
    G3 兼容等价：`mcp_server` 保留的转发函数与 `session_norm` 结果一致，且
       `_stg_call` 兼容对 `mcp_server._normalize_session` 的替身替换。
    G4 定点变异自证（`--mutate`）：注入假反向导入或动态 `import_module` 边必红，
       还原后全绿。

运行：
    python -X utf8 -m md_cg.test_issue434_stg_mcp_cycle_guard
    python -X utf8 -m md_cg.test_issue434_stg_mcp_cycle_guard --mutate
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Set, Tuple

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STG_PATH = _HERE / "stg.py"
SESSION_NORM_PATH = _HERE / "session_norm.py"

PASS = 0
FAIL = 0
FAILS: List[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s%s" % (name, ("  · " + detail) if detail else ""))


def find_forbidden_imports(source: str, forbidden_targets: Set[str], filename: str = "<mem>") -> List[str]:
    """静态 AST 扫描：捕获指向 forbidden_targets 的静态/相对/动态导入边。"""
    tree = ast.parse(source, filename=filename)
    hits: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                segs = alias.name.split(".")
                if any(t in segs for t in forbidden_targets):
                    hits.append("L%d: import %s" % (node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            mod_segs = mod.split(".") if mod else []
            alias_names = [a.name for a in node.names]
            if any(t in mod_segs for t in forbidden_targets) or any(t in alias_names for t in forbidden_targets):
                dots = "." * (getattr(node, "level", 0) or 0)
                hits.append("L%d: from %s%s import %s" % (
                    node.lineno, dots, mod, ", ".join(alias_names)))
        elif isinstance(node, ast.Call):
            fn = node.func
            fn_name = ""
            if isinstance(fn, ast.Name):
                fn_name = fn.id
            elif isinstance(fn, ast.Attribute):
                fn_name = fn.attr
            if fn_name in ("import_module", "__import__") and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    segs = arg0.value.split(".")
                    if any(t in segs for t in forbidden_targets):
                        hits.append("L%d: %s(%r)" % (node.lineno, fn_name, arg0.value))
    return hits


_ISOLATED_PROBE = r'''
import json, os, sys, tempfile
sys.path.insert(0, os.getcwd())
sys.modules["md_cg.mcp_server"] = None  # 阻断反向导入 mcp_server
from md_cg import stg
from md_cg.mdcg import MdCG

dsh_missing = "session-11111111-2222-3333-4444-555555555555"
dsh_present = "session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

with tempfile.TemporaryDirectory(prefix="stg_iso_") as tmp:
    sroot = os.path.join(tmp, "sessions")
    os.makedirs(os.path.join(sroot, "proj", dsh_present), exist_ok=True)
    cg = MdCG(os.path.join(tmp, "brain"))
    saved_root = os.environ.get("MDCG_DSH_SESSIONS_ROOT")
    saved_sess = os.environ.pop("MDCG_SESSION", None)
    saved_dsh = os.environ.pop("DSH_SESSION_ID", None)
    os.environ["MDCG_DSH_SESSIONS_ROOT"] = sroot
    try:
        v_missing = stg._view_session(dsh_missing)
        v_present = stg._view_session(dsh_present)
        tl_missing = stg.timeline(cg, session=dsh_missing)
        tl_present = stg.timeline(cg, session=dsh_present)
    finally:
        if saved_root is None:
            os.environ.pop("MDCG_DSH_SESSIONS_ROOT", None)
        else:
            os.environ["MDCG_DSH_SESSIONS_ROOT"] = saved_root
        if saved_sess is not None:
            os.environ["MDCG_SESSION"] = saved_sess
        if saved_dsh is not None:
            os.environ["DSH_SESSION_ID"] = saved_dsh

print(json.dumps({
    "mcp_loaded": sys.modules.get("md_cg.mcp_server") is not None,
    "v_missing": v_missing,
    "v_present": v_present,
    "tl_missing_session": tl_missing.get("session"),
    "tl_present_session": tl_present.get("session"),
}, ensure_ascii=False))
'''


def _run_assertions() -> int:
    global PASS, FAIL, FAILS
    PASS, FAIL = 0, 0
    FAILS = []

    # G1: 静态 AST 导入边检查
    stg_src = STG_PATH.read_text(encoding="utf-8")
    sn_src = SESSION_NORM_PATH.read_text(encoding="utf-8")
    stg_hits = find_forbidden_imports(stg_src, {"mcp_server"}, str(STG_PATH))
    sn_hits = find_forbidden_imports(sn_src, {"mcp_server", "stg"}, str(SESSION_NORM_PATH))
    _check("G1a stg.py 零 mcp_server 导入边", not stg_hits, repr(stg_hits))
    _check("G1b session_norm.py 零 stg/mcp_server 反向导入边", not sn_hits, repr(sn_hits))

    # G2: 隔离子进程验证（阻断 md_cg.mcp_server 后 stg 仍可独立导入与正确归一）
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", _ISOLATED_PROBE],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    probe = None
    if proc.returncode == 0:
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                probe = json.loads(line)
                break
    _check(
        "G2a 阻断 mcp_server 时 stg 独立导入与 timeline 正常执行",
        proc.returncode == 0 and isinstance(probe, dict),
        "rc=%d stderr=%s" % (proc.returncode, (proc.stderr or "")[-200:]),
    )
    if isinstance(probe, dict):
        _check("G2b sys.modules 未加载 md_cg.mcp_server", probe.get("mcp_loaded") is False, repr(probe))
        _check(
            "G2c stg 独立状态下 DSH 会话正确归一（缺失→anonymous / 存在→原样）",
            probe.get("v_missing") == "anonymous"
            and probe.get("tl_missing_session") == "anonymous"
            and probe.get("v_present") == "session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            and probe.get("tl_present_session") == "session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            repr(probe),
        )

    # G3: 兼容与真源一致性
    from md_cg import mcp_server as ms
    from md_cg import session_norm as sn
    from md_cg import session5 as s5
    from md_cg.mdcg import MdCG

    dsh_missing = "session-11111111-2222-3333-4444-555555555555"
    dsh_present = "session-22222222-3333-4444-5555-666666666666"
    s5_id = s5.make_session5("dsh", "agent", "proj_x", 1791340000, "hello")
    with tempfile.TemporaryDirectory(prefix="stg_compat_") as tmp:
        sroot = os.path.join(tmp, "sessions")
        os.makedirs(os.path.join(sroot, "proj", dsh_present), exist_ok=True)
        saved_root = os.environ.get("MDCG_DSH_SESSIONS_ROOT")
        saved_sess = os.environ.pop("MDCG_SESSION", None)
        saved_dsh = os.environ.pop("DSH_SESSION_ID", None)
        os.environ["MDCG_DSH_SESSIONS_ROOT"] = sroot
        try:
            samples = ["", "  ", "sess_abc", "plain-id", dsh_missing, dsh_present, s5_id]
            parity_ok = all(ms._normalize_session(x) == sn.normalize_session(x) for x in samples)
            dsh_ok = all(ms._is_dsh_session(x) == sn.is_dsh_session(x) for x in samples)
            s5_ok = all(ms._is_session5_like(x) == sn.is_session5_like(x) for x in samples)
            _check("G3a mcp_server 兼容转发与 session_norm 逐例一致", parity_ok and dsh_ok and s5_ok)

            cg = MdCG(os.path.join(tmp, "brain"))
            orig_norm = ms._normalize_session
            try:
                ms._normalize_session = lambda raw: "SENTINEL_" + str(raw)
                res = ms._stg_call(cg, {"op": "timeline", "session": "probe"})
            finally:
                ms._normalize_session = orig_norm
            _check(
                "G3b _stg_call 兼容 mcp_server._normalize_session 注入（哨兵可见）",
                res.get("session") == "SENTINEL_probe",
                repr(res.get("session")),
            )
        finally:
            if saved_root is None:
                os.environ.pop("MDCG_DSH_SESSIONS_ROOT", None)
            else:
                os.environ["MDCG_DSH_SESSIONS_ROOT"] = saved_root
            if saved_sess is not None:
                os.environ["MDCG_SESSION"] = saved_sess
            if saved_dsh is not None:
                os.environ["DSH_SESSION_ID"] = saved_dsh

    print("\n通过 %d / 失败 %d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


def _mutate_selftest() -> int:
    """定点变异自证：对内存/临时副本注入反向或动态导入边，校验精确点红。"""
    stg_orig = STG_PATH.read_text(encoding="utf-8")
    sn_orig = SESSION_NORM_PATH.read_text(encoding="utf-8")

    arms: List[Tuple[str, str, Set[str], str, bool]] = [
        ("M0_clean_stg", stg_orig, {"mcp_server"}, "stg.py", False),
        ("M1_stg_relative_from", stg_orig + "\nfrom .mcp_server import _normalize_session\n", {"mcp_server"}, "stg.py", True),
        ("M2_stg_from_dot", stg_orig + "\nfrom . import mcp_server\n", {"mcp_server"}, "stg.py", True),
        ("M3_stg_abs_import", stg_orig + "\nimport md_cg.mcp_server\n", {"mcp_server"}, "stg.py", True),
        ("M4_stg_importlib", stg_orig + "\nfrom importlib import import_module\nimport_module('md_cg.mcp_server')\n", {"mcp_server"}, "stg.py", True),
        ("M5_session_norm_reverse", sn_orig + "\nfrom . import stg\n", {"mcp_server", "stg"}, "session_norm.py", True),
        ("M6_clean_session_norm", sn_orig, {"mcp_server", "stg"}, "session_norm.py", False),
    ]

    bad = 0
    for name, src, targets, fname, expect_hit in arms:
        hits = find_forbidden_imports(src, targets, fname)
        got_hit = bool(hits)
        ok = got_hit == expect_hit
        if not ok:
            bad += 1
        print("  %-26s hit=%s(expect=%s) hits=%s VERDICT=%s" % (
            name, got_hit, expect_hit, hits, "PASS" if ok else "FAIL"))
    print("OVERALL=%s" % ("PASS" if bad == 0 else "FAIL"))
    return 0 if bad == 0 else 1


def main() -> int:
    if "--mutate" in sys.argv[1:]:
        return _mutate_selftest()
    return _run_assertions()


if __name__ == "__main__":
    sys.exit(main())
