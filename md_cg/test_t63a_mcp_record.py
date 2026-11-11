# -*- coding: utf-8 -*-
"""MCP 召回面恢复记数守卫（E-T63a t2 / 2026-10-11）。

运行（两路都必须能跑）：
  python D:\\wook\\lingshu-src\\md_cg\\test_t63a_mcp_record.py     （直接跑）
  python -m md_cg.run_tests md_cg -k t63a                        （仓根，-m 路）

病灶（Lead 侦察钉死）
--------------------
服务器侧（serve / MCP）**召回从不记 access**：`mcp_server.py` 有两处对
`cg.search` 显式传了 `record=False`，于是「谁被反复引用」在服务器侧永远是空表：

  · `op=route` 的 intent 搜索（原 mcp_server.py:2380-2381）
  · `mdcg_reflect`（原 mcp_server.py:24-3803）

而 `op=read` 的 query 分支（mcp_server.py:247-2448）本就没传 `record`，
走缺省 `True` —— 它一直在记，**本套不许它被改动**。

判据（对应 accept ①②③④⑤）
---------------------------
  G1 **静态**：`mcp_server.py` 源文本里，route / reflect 两个调用点不再出现
     `record=False`（且全文件已无任何 `record=False`）；`__init__.py` 之外
     的 read query 分支仍**不传** record（保持缺省 True），逐字不动。
  G2 **动态·route**：临时库写节点 → 走**真实** `_cg_dispatch(cg, {"op":
     "route", ...})` → 断言 `_access.log` 新增了命中节点那一行。
     这条证明的不只是「文本改了」，而是 `record` 真的**流到了** `cg.search`。
  G3 **动态·reflect**：走真实 `_dispatch(cg, "mdcg_reflect", {...})`，
     同样断言 `_access.log` 记上了一行。
  G4 **对照·read**：`op=read` 的 query 分支也照记（它本来就记）—— 作为
     「record 生效」的正向对照，防止 G2/G3 的绿是**假绿**（例如日志根本没
     被读、路径找错）。
  G5 **反向对照**：显式 `cg.search(record=False)` **不**记 —— 证明 `_access.log`
     的增长确实由 `record` 参数驱动，而不是任何搜索都会写。
  G6 **缺省即 True**：`cg.search(...)` 不传 record 时**记**——这是 route/
     reflect 改动后依赖的那条缺省语义，必须钉住（否则改法一失效就静默回归）。

沙箱注记：全程在 tempfile 临时目录里造库，**绝不碰真实 ~/.mdcg**；
`_access.log` 路径取 `cg.access_log`（mdcg.py:2097 单点），不自己拼路径。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__:
    from . import mcp_server as ms
    from .mdcos import MdCG
else:                                  # 直接 `python md_cg/test_t63a_mcp_record.py` 也能跑
    sys.path.insert(0, _REPO)
    from md_cg import mcp_server as ms
    from md_cg.mdcos import MdCG

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_MCP_SRC = os.path.join(_REPO, "md_cg", "mcp_server.py")

QUERY = "苹果 章节 认知图"

_PASS = []
_FAIL = []


# 生效条件：cond 为真记录 PASS 并返回 True，否则记录 FAIL 并返回 False；n 为断言名。
def ok(cond: bool, n: str) -> bool:
    if cond:
        _PASS.append(n)
    else:
        _FAIL.append(n)
    return bool(cond)


# 生效条件：无前置；返回 mcp_server.py 的源文本（UTF-8，读不出则空串）。
def _src() -> str:
    try:
        with open(_MCP_SRC, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


# 生效条件：给定 src 文本，抽出 `if op == "route":` 起、到下一个顶层 `if ` 前的代码段（找不到返回 ""）。
def _block(src: str, anchor: str, stop: str = "\n    if ") -> str:
    i = src.find(anchor)
    if i < 0:
        return ""
    j = src.find(stop, i + len(anchor))
    return src[i:] if j < 0 else src[i:j]


# 生效条件：无前置；读 _access.log 的原始文本（不存在返回 ""）。
def _log_text(cg) -> str:
    try:
        with open(cg.access_log, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


# 生效条件：在 root 造一个临时库并写两条可被 QUERY 命中的节点，返回该 MdCG 实例。
def _mk(root) -> "MdCG":
    cg = MdCG(root)
    cg.add("n_apple", "苹果 章节：认知图的第一条论据", layer="knowledge")
    cg.add("n_pear", "梨 与 苹果 的对比章节", layer="knowledge")
    return cg


# 生效条件：无前置；静态断言 mcp_server.py 里 route / reflect 两处调用点不再含 record=False，
# 且 read 的 query 分支保持不传 record（缺省 True），返回 True 表示全部通过。
def _g1_static():
    src = _src()
    ok(bool(src), "G1 前置：mcp_server.py 源文本可读")
    if not src:
        # 源读不出时后续行号断言全部无意义，直接报明。
        ok(False, "G1 源读不出，静态判据无法评估")
        return

    ok("record=False" not in src,
       "G1a 全文件已无 record=False（route/reflect 两处均已恢复缺省记数）")

    rb = _block(src, 'if op == "route":')
    ok(bool(rb), "G1b route 分支可定位")
    ok("cg.search" in rb, "G1c route 分支仍调用 cg.search")
    ok("record=False" not in rb, "G1d route 的 intent 搜索不再关记数")

    fb = _block(src, 'if name == "mdcg_reflect":')
    ok(bool(fb), "G1e mdcg_reflect 分支可定位")
    ok("cg.search" in fb, "G1f mdcg_reflect 仍调用 cg.search")
    ok("record=False" not in fb, "G1g mdcg_reflect 不再关记数")

    # read 的 query 分支：**逐字不动** —— 非 budget 分支那条 cg.search 仍不传 record。
    qb = _block(src, "from . import refindex")
    ok(bool(qb), "G1h read 的 query 分支可定位")
    ok("cg.search" in qb, "G1i read query 分支仍调用 cg.search")
    ok("record" not in qb.split("cg.search", 1)[1].split("return", 1)[0],
       "G1j read query 分支保持不传 record（缺省 True，逐字不动）")


# 生效条件：临时库 cg 就绪时走真实 op=route 派发，断言 _access.log 新增命中行；返回 True 表示通过。
def _g2_route_records(cg):
    before = _log_text(cg)
    n_before = len([ln for ln in before.splitlines() if ln.strip()])
    try:
        out = ms._cg_dispatch(cg, {"op": "route", "intent": QUERY, "k": 5})
    except Exception as exc:                              # noqa: BLE001
        ok(False, "G2 route 派发未抛异常：%r" % (exc,))
        return
    ok(isinstance(out, dict) and bool(out.get("knowledge")),
       "G2 前置：route 确有召回结果（否则无命中可记）")
    after = _log_text(cg)
    lines = [ln for ln in after.splitlines() if ln.strip()]
    ok(len(lines) > n_before,
       "G2a route 命中后 _access.log 新增行（%d → %d）" % (n_before, len(lines)))
    ok("n_apple" in after or "n_pear" in after,
       "G2b 新增行含命中节点 id（record 确已流到 cg.search）")


# 生效条件：临时库 cg 就绪时走真实 mdcg_reflect 派发，断言 _access.log 新增行；返回 True 表示通过。
def _g3_reflect_records(cg):
    before = len([ln for ln in _log_text(cg).splitlines() if ln.strip()])
    try:
        out = ms._dispatch(cg, "mdcg_reflect", {"query": QUERY, "k": 5})
    except Exception as exc:                              # noqa: BLE001
        ok(False, "G3 reflect 派发未抛异常：%r" % (exc,))
        return
    ok(out is not None, "G3 前置：mdcg_reflect 返回非 None")
    after = _log_text(cg)
    lines = [ln for ln in after.splitlines() if ln.strip()]
    ok(len(lines) > before,
       "G3a reflect 命中后 _access.log 新增行（%d → %d）" % (before, len(lines)))


# 生效条件：临时库 cg 就绪时走真实 op=read 的 query 分支，断言它也记账（正向对照，证明 record 生效可观测）。
def _g4_read_records(cg):
    before = len([ln for ln in _log_text(cg).splitlines() if ln.strip()])
    try:
        out = ms._cg_dispatch(cg, {"op": "read", "query": QUERY, "k": 5})
    except Exception as exc:                              # noqa: BLE001
        ok(False, "G4 read 派发未抛异常：%r" % (exc,))
        return
    ok(isinstance(out, dict) and "results" in out, "G4 前置：read 返回 results 形状")
    after = _log_text(cg)
    lines = [ln for ln in after.splitlines() if ln.strip()]
    ok(len(lines) > before,
       "G4 read query 分支照常记数（%d → %d）——它本就缺省 True，不许动"
       % (before, len(lines)))


# 生效条件：在临时子库里验证 record=False 不记、缺省 True 记（反向对照 + 缺省语义钉死）。
def _g5_g6_record_semantics(tmp):
    d = os.path.join(tmp, "semantics")
    os.makedirs(d, exist_ok=True)
    cg = _mk(d)

    n0 = len([ln for ln in _log_text(cg).splitlines() if ln.strip()])
    cg.search(QUERY, k=5, record=False)
    n1 = len([ln for ln in _log_text(cg).splitlines() if ln.strip()])
    ok(n1 == n0, "G5 record=False 不记账（反向对照：%d → %d）" % (n0, n1))

    cg.search(QUERY, k=5)
    n2 = len([ln for ln in _log_text(cg).splitlines() if ln.strip()])
    ok(n2 > n1, "G6 不传 record 即记（缺省 True：%d → %d）" % (n1, n2))


def main() -> int:
    if not os.path.isfile(_MCP_SRC):
        print("源文件缺失：%s" % _MCP_SRC)
        return 1
    tmp = tempfile.mkdtemp(prefix="t63a_")
    try:
        _g1_static()
        cg = _mk(os.path.join(tmp, "mcp"))
        _g2_route_records(cg)
        _g3_reflect_records(cg)
        _g4_read_records(cg)
        _g5_g6_record_semantics(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for n in _FAIL:
        print("  FAIL  %s" % n)
    print("\nt63a MCP 召回面恢复记数守卫：%d 通过，%d 失败"
          % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
