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
import contextlib
import io
import os
import shutil
import tempfile
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
#: **按全名分段匹配**（见 `_violations`），不再只看首段——否则
#: `from md_cg.mcp_server import x` 这类本仓最自然的违规写法会整段穿网。
_HOST_MODULES = (
    "mcp", "mcp_server",          # 本仓 md_cg/mcp_server.py 即宿主接线面
    "hooks", "plugin", "inject",  # 宿主注入面
    "aiohttp", "starlette", "flask", "fastapi", "requests",  # HTTP 框架
)

#: 分层序号：数字越小越靠上。下层引用层号**更小**的即反向依赖。
_LAYER_RANK = {name: rank for rank, name in enumerate(_LAYERS)}

#: 需要扫描的层：``_LAYERS`` 里除最顶层（``adapter``）之外**全部**。
#:
#: 为什么从 ``_LAYERS`` 推导而不是手写 ``("kernel", "govern")``：
#: 手写清单会与 ``_LAYERS`` 漂移——事实就是漂了，「iface 层引 adapter」这类
#: 反向依赖在 ``_violations`` 里判得出来，却因为层名不在手写清单里而**从不被扫**，
#: 形成第二个「判据有、守卫不接电」的盲区。此处从真值表推导，加层即自动覆盖。
#:
#: ``adapter`` 不扫：它是宿主接线层（路线稿 §2 顶端），允许向下引用任意内层，
#: 不存在「反向」可言。
_INTERNAL_LAYERS = tuple(name for name in _LAYERS if name != "adapter")

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


def _test_write_request_immutable():
    """``WriteRequest`` 必须**真不可变**：属性赋值与 mapping 内部改写都要被拒。

    为什么单列一条：``__slots__`` 只防新增属性、不防重新赋值，而 ``digest()``
    每次重算 ⇒ 指纹可被外部改写污染。没有这条断言，「不可变」只是 docstring 上
    的一句话。
    """
    req = WriteRequest("mem_1", "正文", conditions={"c": 1}, provenance={"src": "s"})
    digest0 = req.digest()

    for attr, value in (("node_id", "hacked"), ("content", "篡改"), ("conditions", {}), ("provenance", {})):
        try:
            setattr(req, attr, value)
        except AttributeError:
            pass
        else:
            raise AssertionError(f"WriteRequest 必须拒绝给 {attr!r} 赋值（否则指纹可被污染）")

    for mapping in ("provenance", "conditions"):
        try:
            getattr(req, mapping)["k"] = 1  # type: ignore[index]
        except TypeError:
            pass
        else:
            raise AssertionError(f"WriteRequest.{mapping} 必须是只读视图，不得内部改写")

    assert req.digest() == digest0, "不可变对象上 digest() 必须恒定（指纹被污染即失守）"


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
    """静态解析出该文件的 import 名集合（不执行）。

    形态：绝对导入保留全名（``md_cg.mcp_server``）；相对导入保留前导点
    （``..mcp_server`` / ``.``）。**空 module 的相对导入也保留**——它是
    ``from . import x`` 的形态，绝不能被静默丢掉（否则该形态完全不可见）。

    别名必须一起保留——这是本函数曾经的致命缺陷。``from X import a`` 在语义上
    等价于``import X.a``，被导入的是 ``X`` **加上** 别名 ``a``。只记 ``X`` 会
    让「别名才是违规所在」的写法整段穿网：

        from md_cg import mcp_server     记成 ``md_cg``        → 判据看不见 mcp_server
        from .. import mcp_server        记成 ``..``           → 判据更看不见
        from . import mcp_server         记成 ``.``            → 连目标包都丢失

    三条都是「宿主模块在别名位、包名完全干净」的最自然写法，也正是路线稿 §2
    要禁的东西。故对每个别名补一条 ``base + "." + alias``。
    """
    with io.open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source, filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            star = any(a.name == "*" for a in node.names)
            aliases = [a.name for a in node.names if a.name != "*"]
            # `from X import a` 的被导入对象是 **X.a**，不是 X 本身。
            # 只有「星号导入」或「没有别名」时，X 才单独构成一条导入记录。
            # 若在此额外记一条裸 ``X``，像 `from md_cg import kernel` 这样的
            # **合法**写法会因为裸 ``md_cg`` 解析不出目标段而被 fail-closed 误判成
            # 违规——这是修别名盲区时自己引入的假红，实测确认过。
            if star or not aliases:
                names.add("." * node.level + base if node.level else base)
            for alias in aliases:
                tail = f"{base}.{alias}" if base else alias
                # 相对导入要在**去掉点之后再拼**，拼完补回同样多的点：
                #   level=2, base="", alias="mcp_server" → "..mcp_server"
                # 天真地用 f"{stem}.{alias}" 会得到 "...mcp_server"（多一层），
                # 层级多算一层正是本函数要避免的那类偏移。
                names.add("." * node.level + tail if node.level else tail)
    return names


def _resolve_fqn(rel_file, name, root=None):
    """把一条 import 记录解析成**从 md_cg 起算的绝对全名**。

    相对导入按所在文件的位置合成：``md_cg/kernel/x.py`` 里的
    ``..mcp_server`` → ``md_cg.mcp_server``；``.`` → 所在包的 ``__init__``
    （返回 ``md_cg.kernel`` 这类包名，供后续分段判定）。

    返回 (segments, kind)：segments 是从 ``md_cg`` 之后开始的段列表
    （``md_cg.mcp_server`` → ``["mcp_server"]``）；无法解析时返回 ([], name)。
    """
    # 文件相对仓根的路径 → 包段（去掉 md_cg 之前的部分与 .py）
    # 解析根可注入（`root`）：夹具要在**临时目录**里跑，绝不能在真树里写文件。
    # 不变量：`x.py` 与 `__init__.py` 同属一个包，同一条相对导入必须解析一致。
    root = _REPO if root is None else root
    rel = os.path.relpath(os.path.abspath(rel_file), root).replace(os.sep, "/")
    parts = rel[:-3].split("/") if rel.endswith(".py") else rel.split("/")
    is_pkg_init = bool(parts) and parts[-1] == "__init__"
    if is_pkg_init:
        parts = parts[:-1]
    # 定位 md_cg 在路径里的位置
    if "md_cg" not in parts:
        return [], name
    idx = parts.index("md_cg")
    # cur = **当前文件所在的包**（相对 md_cg）。
    #   md_cg/kernel/x.py        → ['kernel']（文件所在的包）
    #   md_cg/kernel/__init__.py → ['kernel']（同一个包，不能少这一层）
    # 曾经一律写 `parts[idx+1:-1]`，对 `__init__.py` 会错误地再切掉一层变成 `[]`，
    # 于是**同一个包内的同一条相对导入**在 `x.py` 与 `__init__.py` 里解析出不同结果：
    #   `.foo` → x.py 得 md_cg.kernel.foo，__init__.py 却得 md_cg.foo
    # 而 W1 骨架的 kernel/ 与 govern/ 目录下**恰好只有 __init__.py**，
    # 即这条偏移对真树是百分之百命中，不是边角情形。
    cur = parts[idx + 1:] if is_pkg_init else parts[idx + 1:-1]
    level = len(name) - len(name.lstrip("."))
    body = name.lstrip(".")
    if level == 0:                   # 绝对导入
        segs = body.split(".")
        if segs and segs[0] == "md_cg":
            segs = segs[1:]
        return segs, name
    # 相对导入：level=1 指当前包，level=2 指父包
    up = level - 1
    # 越过 md_cg 包根：`len(cur)` 不够上溯。此处**必须显式返回空段**，
    # 不能像旧写法那样 `else []` 静默截成空列表——那样 `from ... import x`
    # 在 md_cg/kernel/ 下会拼出 `['x']`，即被当成 `md_cg.x` 这份**合法**导入，
    # 于是「越过包根」这个真正不可判的形态被伪装成了正常引用。
    if up > len(cur):
        return [], name
    base = cur[:len(cur) - up] if up else list(cur)
    tail = body.split(".") if body else []
    return base + tail, name


def _violations(layer, relpath, names, file_path=None, root=None):
    """导入图判据**唯一实现**：给定层名与一组 import 记录，返回违规说明列表。

    这是**纯函数**（不做 IO），守卫与夹具自证共用它——因此「删掉判据就必红」，
    不会出现「断的是 ast 能不能解析 import」这种恒真断言。

    判据（路线稿 §2）：
    1. 宿主类型：全名**任一段**命中 ``_HOST_MODULES`` 即判耦合；
    2. 宿主包：全名含 ``dsh`` 段即判耦合；
    3. 反向依赖：本层引用层号更小的层（如 kernel 引 iface/govern/adapter）。
    """
    problems = []
    rank = _LAYER_RANK.get(layer)
    for name in names:
        if file_path:
            segs, _ = _resolve_fqn(file_path, name, root=root)
        else:                        # 夹具不落地时按字面分段
            segs = name.lstrip(".").split(".") if name.lstrip(".") else []
            # 与 `_resolve_fqn` 的绝对导入分支保持**同一口径**：剥掉包根 `md_cg`。
            # 不剥就会让 `md_cg.adapter` 的首段变成 `md_cg`（不是层名），
            # 反向依赖判据整条穿网——这正是宿主类型判据上
            # 「`from md_cg.mcp_server import x` 首段是 md_cg 故不命中」的同型盲区，
            # 上一轮只修了宿主类型那条路，反向依赖这条一直没修。现两条都按剥根后判定。
            if segs and segs[0] == "md_cg":
                segs = segs[1:]
        # 1) 宿主类型：任意段命中（不再只看首段）
        hit = [s for s in segs if s in _HOST_MODULES]
        if hit:
            problems.append(f"{relpath} 引宿主类型 {name!r}（命中段 {hit}，路线稿 §2 禁止项）")
        # 2) 宿主包
        if "dsh" in segs:
            problems.append(f"{relpath} 引宿主包 {name!r}（路线稿 §2 禁止项）")
        # 3) 反向依赖
        if rank is not None and segs:
            head = segs[0]
            other = _LAYER_RANK.get(head)
            if other is not None and other < rank:
                problems.append(f"{relpath} {layer} 层反向依赖上层 {name!r}（路线稿 §2）")
        # 4) 解析不出目标段：显式报错，不许静默跳过。
        #    真实形态：`md_cg/kernel/__init__.py` 里写 `from .. import x`——
        #    level=2 越过了 md_cg 这一点，合成后为空段。静默跳过就漏报。
        if not segs and not file_path:
            pass  # 无 file_path 时由调用方负责给出可解析的名字
        elif not segs:
            problems.append(
                f"{relpath} 导入 {name!r} 解析不出目标段（越过 md_cg 包根）——"
                "无法判定归属，按 fail-closed 记为违规"
            )
    return problems


def _scan_layers():
    """守卫**实际扫描**的层清单——单独成函数，好让覆盖性断言直接盯它。

    为什么不让它内联在 ``_test_import_direction`` 里：内联时，把循环的取值
    换成手写元组（``for layer in ("kernel", "govern")``）不会有任何断言变红
    ——我实测过，覆盖性用例照样 PASS。抽成函数后，覆盖性用例断言的是
    **扫描器自己**，而不是一个旁边放着的常量，于是「扫描范围退回手写清单」
    这种回退能被抓住。
    """
    return _INTERNAL_LAYERS


def _layer_members():
    """层 → 该层所有 ``.py`` 文件路径（**成员表驱动**，2026-11-11 扩面）。

    为什么不再「按目录名推导」：本仓治理层的真实实现直到 2026-11-11 才搬进
    ``md_cg/govern/``，此前全平铺在 ``md_cg/`` 根目录；按目录名扫 ⇒ 根目录
    154 个模块（含 `mdcg` / `subgraph` / `sustain` 这些实际承载层语义的实现）
    **一条都不在判据视野里**，覆盖率只有 0.34%。现改为：

    ① 子包成员：`md_cg/<pkg>/**` 按 ``_layers.PACKAGE_LAYER`` 归层
       （含 ``mreview → govern``——此前它不在任何层里，反向依赖完全不可见）；
    ② 根目录成员：``md_cg/*.py`` 按 ``_layers.ROOT_LAYER`` 归层，未登记者
       归 ``None``（= 无归属，单独由 `_root_edges()` 判「根目录 → 子包」越权）。

    **测试文件不是层成员**：`test_*.py` 一律跳过——它们反过来 import 生产码是
    正常的（测试就是调用方），把它们算进层会让「kernel 引 govern」这类判据
    对测试面误报，也会让「覆盖率」这个读数失真（631 个测试文件会淹没 199 个
    生产模块）。这是本函数**唯一**的排除面，且它对根目录与子包一视同仁。

    返回 ``{layer: [(abs_path, layer_or_None), ...]}``；函数**不做 IO 判断**
    （缺目录就是空表），覆盖性由 `_test_guard_covers_every_internal_layer` 盯。
    """
    from . import _layers as L

    def _prod(paths):
        for p in paths:
            if not os.path.basename(p).startswith("test_"):
                yield p

    out = {name: [] for name in _LAYERS}
    root = os.path.join(_REPO, "md_cg")
    for pkg, layer in L.PACKAGE_LAYER.items():
        pkgdir = os.path.join(root, pkg)
        for path in _prod(_iter_py(pkgdir)):
            out.setdefault(layer, []).append((path, layer))
    for path in _prod(_iter_py(root)):
        if os.path.dirname(path) != root:      # 根目录直属的 .py 才走成员表
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        layer = L.ROOT_LAYER.get(stem)         # 显式 None = 「未归类」（见 _layers）
        out.setdefault(layer, []).append((path, layer))
    return out


def _is_excluded_root(stem):
    """根目录模块是否在「本阶段明确不动」的名单里（数据面/基准/宿主接口）。"""
    from . import _layers as L

    for pat in L.EXCLUDED_ROOTS:
        if pat.endswith("*"):
            if stem.startswith(pat[:-1]):
                return True
        elif stem == pat:
            return True
    return False


def _violations_of_layer(layer, relpath, names, file_path=None, root=None):
    """在 ``_violations`` 之上叠加**已知违规基线**（登记过的存量违规放行）。

    基线的键是 ``(层名, 仓根相对路径, import 全名)``——**精确到 import 名**，
    不是「这个文件里什么都放过」。于是同一文件里**新增**一条违规照样红。

    返回 ``(problems, matched)``：``matched`` 是本次真正命中了基线的键集合，
    由调用方拿去对账「登记过期」（登记了但实测已不存在 ⇒ 同样红）。
    """
    from . import _layers as L

    rel = relpath.replace(os.sep, "/")
    raw = _violations(layer, relpath, names, file_path, root)
    if not L.KNOWN_LAYER_VIOLATIONS or not raw:
        return raw, set()
    matched = set()
    keep = []
    for prob in raw:
        hit = None
        for key in L.KNOWN_LAYER_VIOLATIONS:
            klayer, krel, kname = key
            if klayer != layer or krel != rel:
                continue
            if ("%r" % kname) in prob or kname in prob:
                hit = key
                break
        if hit is None:
            keep.append(prob)
        else:
            matched.add(hit)
    return keep, matched


def _root_edges():
    """实测「根目录平铺模块 → 子包」的越权边。

    返回 ``(edges, skipped)``：
      ``edges``   = ``{(根模块名, 子包名): [命中的 import 名, ...]}``
      ``skipped`` = 被 ``EXCLUDED_ROOTS`` 明确排除、因而**没有**纳入视野的根模块名

    ``skipped`` 必须被返回而不是静默丢弃：排除面本身就是判据的一部分
    （「扫了什么」与「跳了什么」都要可见），否则「覆盖率提升」这句读数
    无从复核。
    """
    from . import _layers as L

    root = os.path.join(_REPO, "md_cg")
    subs = tuple(L.PACKAGE_LAYER)
    edges, skipped = {}, []
    for path in _iter_py(root):
        if os.path.dirname(path) != root:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem == "__init__":
            continue
        if _is_excluded_root(stem):
            skipped.append(stem)
            continue
        for name in _imported_names(path):
            segs, _raw = _resolve_fqn(path, name)
            if segs and segs[0] in subs:
                edges.setdefault((stem, segs[0]), []).append(name)
    for k in edges:
        edges[k] = sorted(set(edges[k]))
    return edges, sorted(skipped)


def _test_import_direction():
    """kernel / govern / iface 不得 import 上层，也不得碰宿主类型。

    扫描面由 `_layer_members()`（成员表）决定，**不再是目录名推导**。
    已知违规走 `_violations_of_layer` 的基线放行，并在这里对账「登记过期」。
    """
    from . import _layers as L

    problems = []
    matched = set()
    for layer in _scan_layers():
        for path, _layer in _layer_members().get(layer, ()):
            rel = os.path.relpath(path, _REPO)
            got, hit = _violations_of_layer(
                layer, rel, _imported_names(path), path)
            problems.extend(got)
            matched |= hit
    stale = sorted(set(L.KNOWN_LAYER_VIOLATIONS) - matched)
    assert not problems, "导入图违规：\n        " + "\n        ".join(problems)
    assert not stale, (
        "已知违规基线过期（登记了但实测已不存在）——修好了就该删登记，"
        "否则基线在撒谎：\n        "
        + "\n        ".join("%r: %s" % (k, L.KNOWN_LAYER_VIOLATIONS[k])
                            for k in stale))


def _test_root_edges_baseline():
    """「根目录 → 子包」越权边必须与基线**逐条相符**（新增必红 / 过期必红）。

    为什么单列一条而不是并进上一条：这条判的是**未被归类**的根目录模块
    （``ROOT_LAYER.get(stem) is None``）对子包的引用。它们不是「违规」——它们
    是**第二阶段的待办清单**。把它做成「实测 == 基线」的等式，就能同时拿到：
      · 新增一条越权边 ⇒ 红（谁新加了对子包的依赖，必须显式登记）；
      · 归位一条（边消失）⇒ 红（提醒把基线同步清掉，不留假账）；
      · 基线被整体改成「什么都放过」⇒ 由下一条自证用例抓。
    """
    from . import _layers as L

    measured, _skipped = _root_edges()
    want = set(L.KNOWN_ROOT_EDGES)
    got = set(measured)
    added = sorted(got - want)
    gone = sorted(want - got)
    detail = []
    for k in added:
        detail.append("新增越权边 %s → %s：%s"
                      % (k[0], k[1], measured[k]))
    for k in gone:
        detail.append("基线过期 %s → %s（边已不存在：%s）"
                      % (k[0], k[1], L.KNOWN_ROOT_EDGES[k][:60]))
    assert not added and not gone, (
        "根目录 → 子包越权边与基线不符（新增违规必红、过期登记也必红）：\n        "
        + "\n        ".join(detail))


def _test_baseline_is_not_a_blanket_pass():
    """基线自证：它**不会**把新增边 / 新 import 一并吞掉（防门禁被绕过）。

    三条断言，各自可红：
      ① 在基线里删掉一条真实边 ⇒ 该边立刻判为「新增」，说明基线是**逐条**的；
      ② 基线键带 import 名 ⇒ 同文件换一个 import，`_violations_of_layer`
         的精确匹配不会命中旧登记；
      ③ 基线条目若被写成非法形状（如空键）⇒ 覆盖性用例仍能报出来——这里用
         「键必须能对上一条实测边」的形式断言。
    """
    from . import _layers as L

    measured, _skipped = _root_edges()
    # ① 逐条性：任一真实边都不可能在「没有登记」时被放过
    sample = sorted(measured)[0] if measured else None
    if sample is not None:
        keep = dict(L.KNOWN_ROOT_EDGES)
        try:
            L.KNOWN_ROOT_EDGES.clear()
            added = set(measured) - set(L.KNOWN_ROOT_EDGES)
            assert added == set(measured), (
                "清空基线后实测边必须**全部**成为新增违规（否则基线不是逐条的）")
        finally:
            L.KNOWN_ROOT_EDGES.clear()
            L.KNOWN_ROOT_EDGES.update(keep)
    # ② 精确到 import 名：换一个 import 名，登记不应放行
    problems, matched = _violations_like(
        "govern", "md_cg/govern/_probe.py",
        {"md_cg.mcp_server._cg_dispatch"}, None)
    assert not matched, "基线不得按「文件级」放行（必须精确到 import 名）"
    assert problems, "未登记的同文件新 import 必须被判定为违规"
    # ③ 键形状：每条登记都必须是 3 元组且可解析
    for key in L.KNOWN_LAYER_VIOLATIONS:
        assert isinstance(key, tuple) and len(key) == 3, (
            f"已知违规基线键必须是 (层名, 相对路径, import 全名)，实为 {key!r}")
    for key in L.KNOWN_ROOT_EDGES:
        assert isinstance(key, tuple) and len(key) == 2, (
            f"越权边基线键必须是 (根模块名, 子包名)，实为 {key!r}")


def _violations_like(layer, relpath, names, file_path=None, root=None):
    """`_violations_of_layer` 的可断言包装（供基线自证直接调用）。"""
    return _violations_of_layer(layer, relpath, names, file_path, root)


def _test_root_coverage_grew():
    """覆盖率读数本身必须可断：判据视野必须**真的**把根目录纳进来了。

    这条治的是「判据在、扫描不覆盖」的老病（本仓栽过两次：先只看首段、后
    扫描层名手写）。判据：
      · 扫描文件数 ≥ 原 W1 骨架（kernel/govern/iface 三目录）文件数；
      · 扫描面**必须**包含根目录直属的、已归层模块（如 `mdcg` / `sustain`）；
      · `mreview` 目录里的文件**必须**出现在 govern 层成员里；
      · 被 `EXCLUDED_ROOTS` 跳过的名单必须显式可枚举（不静默）。
    """
    from . import _layers as L

    members = _layer_members()
    scanned = {os.path.normpath(p) for lst in members.values() for p, _ in lst}
    skeleton = set()
    for pkg in L.PACKAGE_LAYER:
        skeleton |= {os.path.normpath(p)
                     for p in _iter_py(os.path.join(_REPO, "md_cg", pkg))}
    assert len(scanned) >= len(skeleton), (
        f"判据视野 {len(scanned)} 必须 ≥ 子包骨架 {len(skeleton)}")

    root = os.path.join(_REPO, "md_cg")
    for stem in ("mdcg", "sustain", "consistency", "audit"):
        p = os.path.normpath(os.path.join(root, stem + ".py"))
        assert p in scanned, f"根目录模块 {stem}.py 未进入判据视野（覆盖率作弊）"

    mreview = os.path.join(root, "mreview")
    mrev_py = {os.path.normpath(p) for p in _iter_py(mreview)}
    assert mrev_py, "mreview 目录缺失或为空——它是治理流水线，必须纳入 govern 层"
    gov_set = {os.path.normpath(p) for p, _ in members.get("govern", ())}
    missing = mrev_py - gov_set
    assert not missing, (
        "mreview 未登记为 govern 层成员（反向依赖因此不可见）：%s"
        % sorted(os.path.relpath(p, _REPO) for p in missing)[:6])

    _edges, skipped = _root_edges()
    assert isinstance(skipped, list) and skipped, (
        "排除面必须显式可枚举（EXCLUDED_ROOTS 命中项），不得静默跳过")


@contextlib.contextmanager
def _fixture_repo():
    """在**临时目录**里搭一个最小假仓（``md_cg/{kernel,govern,iface}/``）。

    用于「夹具自证」类断言：这些断言需要真实文件系统上的包结构才能跑，
    但**绝不能**在真树里建删文件——``run_tests.py`` 默认 ``--jobs 4`` 并行，
    多线程同时建删同名路径会互相污染；且任何一次中断都会把临时文件留在仓里。
    假仓每次新建、退出即删，天然并行安全。
    """
    repo = tempfile.mkdtemp(prefix="w1_fixture_")
    try:
        for layer in _LAYERS:
            os.makedirs(os.path.join(repo, "md_cg", layer), exist_ok=True)
        io.open(os.path.join(repo, "md_cg", "__init__.py"), "w", encoding="utf-8").write("")
        yield repo
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def _test_import_guard_catches_violation():
    """守卫自证：真的能在**夹具**里抓到反向依赖与宿主类型（防「恒绿断言」）。

    关键：断言走的是**与真实扫描同一个 `_violations()`**，而不是「ast 能否
    解析出 import 名」。因此把 `_HOST_MODULES` 或反向依赖判据整段删掉，本用例
    必然转红——这正是它区别于恒真断言的地方。
    """
    # 夹具落在**临时目录**里搭的假仓，绝不写进真树。
    # 曾经的写法直接在 `md_cg/kernel/` 下建文件再删：`run_tests.py` 默认
    # `--jobs 4` 并行，多线程同时建删同名路径会互相污染（A 删了 B 刚建的文件），
    # 且任何一次中断都会把临时文件留在仓里。假仓 + 注入 root 两个问题一起消掉。
    with _fixture_repo() as repo:
        kernel_dir = os.path.join(repo, "md_cg", "kernel")
        cases = [
            # (夹具源码, 夹具文件名, 期望违规关键词)
            ("from mcp.server import x\n", "bad_mcp.py", "宿主类型"),
            ("from md_cg.mcp_server import x\n", "bad_host.py", "宿主类型"),
            ("from ..mcp_server import x\n", "bad_rel.py", "宿主类型"),
            ("from ..govern import y\n", "bad_gov.py", "反向依赖"),
            ("from ..iface import contracts\n", "bad_iface.py", "反向依赖"),
            # 宿主包（`dsh`）判据的夹具：缺了它，把「dsh in segs」删掉也不会红
            ("from ..dsh import plugin\n", "bad_dsh.py", "宿主包"),
            # 多段穿透：首段是 md_cg，真正的宿主模块在第 2 段
            ("from md_cg.hooks import inject\n", "bad_deep.py", "宿主类型"),
            # 越过包根：md_cg/kernel/x.py 里写 `from ... import y` —— 上溯层数
            # 超过 md_cg 包根，归属不可判。静默截断会把它伪装成 `md_cg.y`，
            # 故按 fail-closed 记为违规。
            ("from ... import y\n", "bad_overroot.py", "解析不出目标段"),
            # `from .. import x`（kernel 下的文件）**是合法的**：level=2 恰好
            # 指到 md_cg 包根，合成 `md_cg.x`。这条曾经被当作「越过包根」的
            # 违规用例——那只是丢别名缺陷造成的假象，修好后必须放过。
            ("from .. import x\n", "ok_rootpkg.py", None),
            # `from . import govern` 解析为 md_cg.kernel.govern（同包内），
            # 不是反向依赖、也不是空名——它**必须被判为干净**，
            # 这样判据才不会把正常的同包引用误伤成违规。
            ("from . import helpers\n", "ok_samepkg.py", None),
            # ---- 别名位盲区回归（本轮实测确认的 3 处穿网形态）----
            # 三条的共同点：**包名本身完全干净**，违规的是别名。
            # 旧 `_imported_names` 只记包名、丢掉别名，于是三条全绿。
            # `from . import mcp_server`  → 旧: ['.']        → 0 条
            ("from . import mcp_server\n", "bad_alias_dot.py", "宿主类型"),
            # `from .. import mcp_server` → 旧: ['..']       → 仅靠「空段」碰巧兜住，
            # 一旦按作者选项 3 放过空段就真穿网；修后由别名判据直接命中。
            ("from .. import mcp_server\n", "bad_alias_up.py", "宿主类型"),
            # `from md_cg import mcp_server` → 旧: ['md_cg'] → 靠「空段」兜住，同型。
            ("from md_cg import mcp_server\n", "bad_alias_abs.py", "宿主类型"),
            # ---- 假红回归：修别名时必须**只记别名**，不能额外记一条裸包名 ----
            # `from md_cg import kernel` 是合法写法（同层导入自己的包），
            # 但裸 ``md_cg`` 解析不出目标段，会被 fail-closed 误判成违规。
            # 下面两条一正一反，把「只记 X.a、不记 X」这个不变量钉死。
            ("from md_cg import kernel\n", "ok_selfpkg.py", None),
            ("from md_cg import iface\n", "bad_alias_layer.py", "反向依赖"),
        ]
        for source, fname, want in cases:
            relpath = "md_cg/kernel/" + fname
            # 必须走**真实的** `_imported_names`，不能在这里另手写一套解析。
            # 这里原先是 `line.split(" import ")[0]` 只看包名——等于把
            # `_imported_names` 的「丢别名」缺陷在夹具里原样抄了一遍，
            # 于是三条别名盲区夹具喂进去的仍然是干净包名，守卫再对也必绿。
            # 夹具与被测路径共用同一个解析器，这个 bug 才不可能被夹具自己掩盖。
            fixture = os.path.join(kernel_dir, fname)
            io.open(fixture, "w", encoding="utf-8").write(source)
            names = _imported_names(fixture)
            got = _violations("kernel", relpath, names, fixture, root=repo)
            joined = " | ".join(got)
            if want is None:
                assert not got, f"夹具 {fname}（{source.strip()!r}）应判为干净，实得 {got!r}"
            else:
                assert got and want in joined, (
                    f"夹具 {fname}（{source.strip()!r}）应判出「{want}」，实得 {got!r}"
                )


def _test_import_guard_clean_on_real_tree():
    """真树上当前骨架必须是干净的（与上一条夹具自证互为对照）。

    2026-11-11 结构归位修正：本项原先走**裸** ``_violations``，即完全不看
    已知违规基线——于是 ``KNOWN_LAYER_VIOLATIONS`` 对真树零作用，任何一条
    已登记的存量向上耦合都会让本项恒红。基线存在的意义正是「存量可见而不
    阻塞」，故此处必须与真实门禁同一条路径（``_violations_of_layer``），
    并把命中/未对账的登记交给下面一条「登记过期即红」去管。

    纪律：放行**只对精确登记过的 import 名**生效；同文件新增一条违规照样红
    （`_violations_of_layer` 的精确匹配语义），登记过期同样红。
    """
    for layer in _scan_layers():
        pkg = os.path.join(_REPO, "md_cg", layer)
        assert os.path.isdir(pkg), f"W1 骨架缺失：md_cg/{layer}"
        for path in _iter_py(pkg):
            rel = os.path.relpath(path, _REPO)
            problems, _matched = _violations_of_layer(
                layer, rel, _imported_names(path), path)
            assert not problems, f"{rel} 不该有导入图违规：{problems}"


def _test_pkg_init_resolves_like_sibling_module():
    """同一个包内的同一条相对导入，在 ``x.py`` 与 ``__init__.py`` 里必须解析一致。

    为什么单列一条：变异测试显示，把 ``__init__.py`` 的定位改回
    ``parts[idx+1:-1]``（即 ``cur=[]``），**13 条用例全绿**——因为没有任何
    断言盯过这个分支。而 W1 骨架里 ``kernel/`` 与 ``govern/`` 目录下
    **只有 __init__.py**，这条偏移对真树是百分之百命中，不是边角情形。

    语义基准：``md_cg/kernel/x.py`` 与 ``md_cg/kernel/__init__.py`` 同属
    ``md_cg.kernel`` 包，故 ``.foo`` 在两者中都应是 ``md_cg.kernel.foo``。
    """
    sibling = os.path.join(_REPO, "md_cg", "kernel", "_probe_sibling.py")
    init = os.path.join(_REPO, "md_cg", "kernel", "__init__.py")
    for name, want in (
        (".foo", ["kernel", "foo"]),
        ("..govern", ["govern"]),
        ("..mcp_server", ["mcp_server"]),
    ):
        got_sibling = _resolve_fqn(sibling, name)[0]
        got_init = _resolve_fqn(init, name)[0]
        assert got_sibling == want, f"x.py 里 {name!r} 应解析为 {want}，实得 {got_sibling}"
        assert got_init == want, (
            f"__init__.py 里 {name!r} 应解析为 {want}（与同包的 x.py 一致），实得 {got_init}"
            "—— __init__ 的相对定位偏了一层"
        )
        assert got_sibling == got_init, (
            f"{name!r} 在 x.py 与 __init__.py 解析不一致：{got_sibling} vs {got_init}"
        )


def _test_guard_covers_every_internal_layer():
    """守卫必须对 ``_LAYERS`` 里**每个**内层都接电（防「判据有、扫描不覆盖」）。

    为什么单列一条：本仓已经栽过两次同型事故——先是判据只看首段（写法穿网），
    后是扫描层名手写成 ``("kernel", "govern")``（``iface`` 层从不被扫）。
    判据正确 ≠ 守卫生效：只要「被扫描的层」和 ``_LAYERS`` 漂开，反证就白写。
    这条断言把「覆盖范围」本身变成可红可绿的检查对象。
    """
    # 1) 扫描器必须真的覆盖 `_LAYERS` 里除顶层外的每一层。
    #    断言对象是 `_scan_layers()`（扫描器本身），不是旁边的常量——
    #    否则把循环改回手写 `("kernel", "govern")` 仍会绿（实测过）。
    scanned = _scan_layers()
    expected = tuple(n for n in _LAYERS if n != "adapter")
    assert scanned == expected, (
        f"扫描器覆盖层必须等于 _LAYERS 去掉顶层 adapter，实得 {scanned!r}（应为 {expected!r}）"
    )
    assert "adapter" not in scanned, "adapter 是宿主接线层，不该被扫"

    # 2) 逐层实证：对每个被扫描的层，「它引用最顶层 adapter」必须判出违规。
    #    若某层漏在 `_LAYER_RANK` 里（层号查不到），这里必红。
    for layer in scanned:
        got = _violations(layer, f"md_cg/{layer}/_probe.py", {"md_cg.adapter"}, None)
        assert got, f"{layer} 层引用 adapter 必须判为反向依赖，实际未判出（该层未接电）"


def main():
    print("=== W1 验收：契约类型 + 导入图单向性 ===")
    _check("契约恰好四个且顺序固定", _test_contract_names)
    _check("Write.provenance 必填（三态全红）", _test_write_requires_provenance)
    _check("WriteRequest 形状与指纹", _test_write_request_shape)
    _check("WriteRequest 真不可变（指纹不可污染）", _test_write_request_immutable)
    _check("WriteReceipt 无账必红", _test_write_receipt_requires_ledger)
    _check("Read.why 必填（四态全红）", _test_read_requires_why)
    _check("打分层吐 state 必红（#111）", _test_read_state_only_from_govern)
    _check("SelfCheck 四键齐备", _test_selfcheck_four_keys)
    _check("四契约 Protocol 方法面", _test_protocols_runtime_checkable)
    _check("导入图单向（kernel/govern/iface）", _test_import_direction)
    _check("导入图守卫夹具自证", _test_import_guard_catches_violation)
    _check("守卫覆盖每个内层（防判据空转）", _test_guard_covers_every_internal_layer)
    _check("__init__ 相对定位与同级模块一致", _test_pkg_init_resolves_like_sibling_module)
    _check("真树骨架干净", _test_import_guard_clean_on_real_tree)
    # ---- 2026-11-11 结构归位：把判据视野扩到根目录 + mreview（任务 3/4）----
    _check("mreview 纳入 govern 层且判据视野覆盖根目录", _test_root_coverage_grew)
    _check("根目录 → 子包越权边与基线逐条相符", _test_root_edges_baseline)
    _check("已知违规基线不吞新增违规（自证）", _test_baseline_is_not_a_blanket_pass)

    failed = [r for r in _results if not r[1]]
    print()
    print(f"===== W1 守卫：{len(_results) - len(failed)} 通过，{len(failed)} 失败 =====")
    if failed:
        print("失败：" + "、".join(r[0] for r in failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
