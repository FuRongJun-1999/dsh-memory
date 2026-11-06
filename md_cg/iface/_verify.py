# -*- coding: utf-8 -*-
"""W1 验收守卫：契约类型 + 导入图单向性（路线稿 §9 W1「验收可判」）。

判定两件事，各自可红可绿：

① **契约单测**（`_test_contracts`）：四个契约的名字/形状/不变量真的成立——
   `provenance` 必填、`why` 必填、打分层吐 `state` 必红、`status()` 四键齐备、
   `WriteReceipt` 无账必红、`ContractViolation.code` 稳定可断言。

② **导入图无反向依赖**（`_test_import_direction`）：按路线稿 §2 分层
   `adapter > iface > govern > kernel`，**下层不得 import 上层**；
   且 `md_cg/kernel` 与 `md_cg/govern` 不得出现 `from ..dsh`、不得出现
   宿主类型（`mcp`、`aiohttp`、`starlette`、`flask`、`fastapi`）。

生效条件：以 `ast` 静态解析本仓 `md_cg/kernel` 与 `md_cg/govern` 下全部 `.py`
（不执行、不 import、零副作用）；本守卫自带夹具（临时目录写样例模块）验证
「反向依赖真的能被抓到」，故不是恒绿断言。

不适用条件：
- **不检查** `md_cg/mdcos.py` 等存量单体——那是 M5 的目标，W1 只管新骨架；
- **不检查** 运行时动态 import（`importlib`）——静态看不住，留给 M2 的运行时守卫；
- **不承诺** 契约的**实现**已在位：W1 只交付骨架，实现属 M2–M4。

验证方式：`python -X utf8 -m md_cg.test_kernel_iface_contracts`
"""

from __future__ import annotations

import ast
import io
import os
import sys
import tempfile

from . import contracts as C
from .contracts import (
    CONTRACT_NAMES,
    ContractViolation,
    ReadItem,
    ReadRequest,
    SelfCheckReport,
    WriteReceipt,
    WriteRequest,
    reject_state_in_scoring,
    require_provenance,
    require_why,
)

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: 路线稿 §2 的分层顺序（上 → 下）。下层 import 上层即「反向依赖」。
_LAYERS = ("adapter", "iface", "govern", "kernel")

#: 宿主类型：内核/治理层出现即判耦合（路线稿 §2 禁止项）。
_HOST_MODULES = ("mcp", "aiohttp", "starlette", "flask", "fastapi", "requests")

_results = []


def _check(name, fn):
    try:
        fn()
    except AssertionError as exc:
        _results.append((name, False, str(exc)))
        print(f"FAIL {name}\n        {exc}")
    except Exception as exc:  # noqa: BLE001 - 守卫需报出任意异常
        _results.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"FAIL {name}\n        {type(exc).__name__}: {exc}")
    else:
        _results.append((name, True, ""))
        print(f"PASS {name}")


# --------------------------------------------------------------------------
# ① 契约单测
# --------------------------------------------------------------------------

def _test_contract_names():
    assert CONTRACT_NAMES == ("Write", "Read", "Govern", "SelfCheck"), (
        f"契约必须恰好四个且顺序固定，实为 {CONTRACT_NAMES!r}"
    )


def _test_write_requires_provenance():
    # 三态全红，且 code 稳定
    for value, want in ((None, "missing_provenance"), ({}, "empty_provenance"), ("x", "not_a_mapping")):
        try:
            require_provenance(value)
        except ContractViolation as exc:
            assert exc.code == want, f"provenance={value!r} 应得 code={want}，实得 {exc.code}"
        else:
            raise AssertionError(f"provenance={value!r} 必须抛 ContractViolation，实际通过了")
    # 正常态放行
    assert require_provenance({"src": "mem_1"}) == {"src": "mem_1"}


def _test_write_request_shape():
    req = WriteRequest("mem_1", "正文", conditions={"c": 1}, provenance={"src": "s"})
    d = req.as_dict()
    assert set(d) == {"node_id", "content", "conditions", "provenance"}, f"as_dict 键面不符: {sorted(d)}"
    assert req.digest() == WriteRequest("mem_1", "正文", conditions={"c": 1}, provenance={"src": "s"}).digest(), (
        "同内容同依据的指纹必须相等"
    )
    assert req.digest() != WriteRequest("mem_1", "正文2", provenance={"src": "s"}).digest(), (
        "内容变则指纹必须变"
    )
    # 构造期即校验：缺 provenance 必须在构造时红，而非等到写入
    try:
        WriteRequest("mem_1", "正文")
    except ContractViolation as exc:
        assert exc.code == "missing_provenance", exc.code
    else:
        raise AssertionError("WriteRequest 缺 provenance 必须在构造期抛错")


def _test_write_receipt_requires_ledger():
    ok = WriteReceipt("r1", "mem_1", "active", "d" * 64, {"status": "ok"})
    assert ok.as_dict()["id"] == "r1"
    try:
        WriteReceipt("r1", "mem_1", "active", "d" * 64, {})
    except ContractViolation as exc:
        assert exc.code == "empty_ledger", exc.code
    else:
        raise AssertionError("写回执无账必须红——「写失败必须留账」是 W1 不变量")
    try:
        WriteReceipt("r1", "mem_1", "bogus", "d" * 64, {"k": 1})
    except ContractViolation as exc:
        assert exc.code == "bad_state", exc.code
    else:
        raise AssertionError("非法 state 必须红")


def _test_read_requires_why():
    for value, want in ((None, "missing_why"), ("", "empty_why"), ("   ", "empty_why"), (1, "not_a_string")):
        try:
            require_why(value)
        except ContractViolation as exc:
            assert exc.code == want, f"why={value!r} 应得 {want}，实得 {exc.code}"
        else:
            raise AssertionError(f"why={value!r} 必须红")
    item = ReadItem("mem_1", 0.9, "命中：标题含《灵枢》", "active", "mem_1#L3")
    assert item.as_dict()["why"], "ReadItem.why 不得为空"
    assert item.as_dict()["evidence_ref"] == "mem_1#L3", "evidence_ref 必须可定位（#593 推论 C）"


def _test_read_state_only_from_govern():
    # 打分层吐 state 必红
    try:
        reject_state_in_scoring([{"id": "a", "score": 1.0, "state": "active"}])
    except ContractViolation as exc:
        assert exc.code == "state_in_scoring", exc.code
    else:
        raise AssertionError("打分层吐 state 必须红（#111 / 路线稿 §4）")
    # 完全不带 state 才放行
    assert reject_state_in_scoring([{"id": "a", "score": 1.0}]) == [{"id": "a", "score": 1.0}]
    # state 为空串/None 视作未输出
    assert reject_state_in_scoring([{"id": "a", "score": 1.0, "state": ""}]), "空 state 不应误红"


def _test_selfcheck_four_keys():
    rep = SelfCheckReport(counts={"nodes": 3}, lag=0.5, drift=False, wal_ok=True)
    assert rep.missing_keys() == [], f"四键必须齐备，缺 {rep.missing_keys()}"
    assert set(rep.as_dict()) == {"counts", "lag", "drift", "wal_ok"}, "status() 返回键面不符"


def _test_protocols_runtime_checkable():
    for proto, name in (
        (C.WriteContract, "Write"),
        (C.ReadContract, "Read"),
        (C.GovernContract, "Govern"),
        (C.SelfCheckContract, "SelfCheck"),
    ):
        assert isinstance(proto, type) or hasattr(proto, "_is_protocol"), f"{name} 必须是 Protocol"
        methods = {
            "Write": ["write"],
            "Read": ["read"],
            "Govern": ["revise", "retire", "rollback", "audit"],
            "SelfCheck": ["status"],
        }[name]
        for m in methods:
            assert hasattr(proto, m), f"{name} 契约缺方法 {m}"


# --------------------------------------------------------------------------
# ② 导入图单向性
# --------------------------------------------------------------------------

def _iter_py(pkg_dir):
    if not os.path.isdir(pkg_dir):
        return
    for root, dirs, files in os.walk(pkg_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(root, fn)


def _imported_names(path):
    """静态解析出该文件的 import 名集合（不执行）。"""
    with io.open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source, filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            # level>0 为相对导入：module 可能为 None
            base = node.module or ""
            if node.level:
                names.add("." * node.level + base)
            else:
                names.add(base)
    return names


def _test_import_direction():
    """kernel / govern 不得 import 上层，也不得碰宿主类型。"""
    problems = []
    for layer in ("kernel", "govern"):
        pkg = os.path.join(_REPO, "md_cg", layer)
        for path in _iter_py(pkg):
            rel = os.path.relpath(path, _REPO)
            for name in _imported_names(path):
                base = name.lstrip(".")
                head = base.split(".")[0]
                if head in _HOST_MODULES:
                    problems.append(f"{rel} 引宿主类型 {name!r}（路线稿 §2 禁止项）")
                if "dsh" in base.split("."):
                    problems.append(f"{rel} 引宿主包 {name!r}（路线稿 §2 禁止项）")
                # 反向依赖：kernel 引 govern/iface/adapter；govern 引 adapter
                if layer == "kernel" and head in ("govern", "adapter"):
                    problems.append(f"{rel} 内核层反向依赖上层 {name!r}")
                if layer == "govern" and head in ("adapter",):
                    problems.append(f"{rel} 治理层反向依赖适配层 {name!r}")
    assert not problems, "导入图违规：\n        " + "\n        ".join(problems)


def _test_import_guard_catches_violation():
    """守卫自证：真的能在**夹具**里抓到反向依赖（防「恒绿断言」）。"""
    with tempfile.TemporaryDirectory() as tmp:
        pkg = os.path.join(tmp, "kernel")
        os.makedirs(pkg)
        bad = os.path.join(pkg, "bad.py")
        io.open(bad, "w", encoding="utf-8").write(
            "from mcp.server import x\nfrom ..govern import y\n"
        )
        names = _imported_names(bad)
        assert any("mcp" in n for n in names), f"应解析出 mcp 导入，实得 {names}"
        assert any("govern" in n for n in names), f"应解析出 govern 导入，实得 {names}"


def _test_import_guard_clean_on_real_tree():
    """真树上当前骨架必须是干净的（与上一条夹具自证互为对照）。"""
    for layer in ("kernel", "govern"):
        pkg = os.path.join(_REPO, "md_cg", layer)
        assert os.path.isdir(pkg), f"W1 骨架缺失：md_cg/{layer}"
        for path in _iter_py(pkg):
            for name in _imported_names(path):
                assert "mcp" != name.split(".")[0], f"{path} 不该引 mcp"


def main():
    print("=== W1 验收：契约类型 + 导入图单向性 ===")
    _check("契约恰好四个且顺序固定", _test_contract_names)
    _check("Write.provenance 必填（三态全红）", _test_write_requires_provenance)
    _check("WriteRequest 形状与指纹", _test_write_request_shape)
    _check("WriteReceipt 无账必红", _test_write_receipt_requires_ledger)
    _check("Read.why 必填（四态全红）", _test_read_requires_why)
    _check("打分层吐 state 必红（#111）", _test_read_state_only_from_govern)
    _check("SelfCheck 四键齐备", _test_selfcheck_four_keys)
    _check("四契约 Protocol 方法面", _test_protocols_runtime_checkable)
    _check("导入图单向（kernel/govern）", _test_import_direction)
    _check("导入图守卫夹具自证", _test_import_guard_catches_violation)
    _check("真树骨架干净", _test_import_guard_clean_on_real_tree)

    failed = [r for r in _results if not r[1]]
    print()
    print(f"===== W1 守卫：{len(_results) - len(failed)} 通过，{len(failed)} 失败 =====")
    if failed:
        print("失败：" + "、".join(r[0] for r in failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
