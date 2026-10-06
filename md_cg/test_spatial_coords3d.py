# -*- coding: utf-8 -*-
"""test_spatial_coords3d · spatial 直存透传守卫（0.8.0 身体×脑对接 · 四条裁定之二）。

契约：`docs/plans/灵枢身体×脑_世界模型对接设计_v0.1.md` §四.2——
`spatial.coords3d` 自定义键**直存**米制（可选 bbox 投影后补）；不改既有
`fm.spatial.bbox` 的 2D 语义、stg 四 op 零位移。

断言分组：

  A 落盘直存——`remember_gated(gated=False)` 带 spatial → 节点 fm["spatial"] 与
    输入**逐位相等**；索引条目在场；**新实例重载**（磁盘回读）逐位不变。
  B 形态与边界——coords3d 与 bbox 并存原样落；零值/负值原样；spatial 缺省
    **不落键**（fm 形态零回归）；spatial 非 dict 原样透传（透传层不校验——
    形态校验归调用方，如实边界）。
  C MCP 面接线——`mcp_server._dispatch` 经 mdcg_remember（gated=false）带 spatial
    → 落盘可见（上游半段）；且三处映射在场：gated 分支透传 / 复现 meta 键 /
    非 gated add 透传 / TOOLS schema 声明（防未来只删一处致两路径元数据不等价）。
  D 既有语义零位移——同节点不带 spatial 写入形态与旧口径一致（无 spatial 键）；
    spatial 不影响 conditions/tags/importance 各既有键。

隔离：全部落临时目录（`tempfile.mkdtemp`）；env 里的根变量全程移除，**绝不动
在役库**（本文件不含任何真实数据根路径字面量）。

运行：python -X utf8 -m md_cg.test_spatial_coords3d
      python -X utf8 -m md_cg.test_spatial_coords3d --mutate   # 定点变异自证

退出码（fail-closed）：0 = 全绿 / 变异自证 PASS；1 = 断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到——实现改了却没同步本表即硬失败）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

from .mdcos import MdCGOS

_PASS = []
_FAIL = []
_GEN = [0]
_TMP = tempfile.mkdtemp(prefix="mdcg_sp_")
_SAVED = {}
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


# 生效条件：无入参；把根相关 env 键现值存入 _SAVED 并逐个移除（隔离：任何经 env 取根的路径都不得落到在役库）。
def _sandbox_env():
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_STG_STATE"):
        _SAVED[k] = os.environ.get(k)
        os.environ.pop(k, None)


# 生效条件：无入参；把 _SAVED 逐个还原（原值 None 则移除键）。
def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# 生效条件：无入参；在 _TMP 下新建自增代次目录并返回其上的 MdCGOS 实例（组间零串味）。
def _fresh_cg():
    _GEN[0] += 1
    return MdCGOS(os.path.join(_TMP, "gen%d" % _GEN[0], "root"))


# 生效条件：cg 为沙箱实例、spatial 为附加键（可为 None=不带）时写一条场景节点并返回 (nid, 写入返回体)。
def _write_scene(cg, nid, spatial, content=None):
    kw = dict(layer="contextual", gated=False, importance=0.6,
              tags=["spatial", "cat:fatfish", "ent:肥鱼", "world_model"])
    if spatial is not None:
        kw["spatial"] = spatial
    content = content or "场景实体 肥鱼（fatfish）位于 (0,0.85,5.0)，状态 shy"
    return nid, cg.remember_gated(nid, content, **kw)


# 生效条件：cg 为新实例、nid 为节点 id 时返回其 frontmatter（无节点返回 {}）。
def _entry_fm(cg, nid):
    e = cg.get(nid) or {}
    return e.get("frontmatter") or {}


# 生效条件：同上；返回 frontmatter.spatial（键缺返回哨兵 '__MISSING__'，与 None 值区分）。
def _entry_spatial(cg, nid):
    return _entry_fm(cg, nid).get("spatial", "__MISSING__")


SP_A = {"coords3d": {"x": 0.0, "y": 0.85, "z": 5.0}}


# 生效条件：无入参；A 组——直存逐位 + 索引在场 + 磁盘重载逐位（返回红项数）。
def group_a():
    n0 = len(_FAIL)
    cg = _fresh_cg()
    nid, out = _write_scene(cg, "sp_a1", SP_A)
    ok(out.get("verdict") == "ACCEPT", "A1 写入 ACCEPT（bypass 直写路径）", out)
    ok(_entry_spatial(cg, nid) == SP_A, "A2 索引条目 spatial 与输入逐位相等",
       _entry_spatial(cg, nid))
    cg2 = MdCGOS(cg.root)          # 新实例：从磁盘重载索引（落盘不回读不算数）
    ok(_entry_spatial(cg2, nid) == SP_A, "A3 新实例重载后 spatial 逐位不变",
       _entry_spatial(cg2, nid))
    fm, _content = cg2._read(cg2.get(nid))
    ok((fm or {}).get("spatial") == SP_A, "A4 磁盘 fm.spatial 逐位相等（_read 直读）",
       (fm or {}).get("spatial"))
    return len(_FAIL) - n0


# 生效条件：无入参；B 组——形态与边界（返回红项数）。
def group_b():
    n0 = len(_FAIL)
    cg = _fresh_cg()
    sp_b = {"coords3d": {"x": -1.5, "y": 0.0, "z": 2.25}, "bbox": [10, 20, 30, 40]}
    nid, _ = _write_scene(cg, "sp_b1", sp_b)
    ok(_entry_spatial(cg, nid) == sp_b, "B1 coords3d 与 bbox 并存原样落盘（零重写）",
       _entry_spatial(cg, nid))
    # 缺省不落键（键缺，而非值 None）
    nid2, _ = _write_scene(cg, "sp_b2", None)
    ok("spatial" not in _entry_fm(cg, nid2),
       "B2 spatial 缺省不落键（fm 形态零回归）", sorted(_entry_fm(cg, nid2).keys()))
    # 非 dict 原样透传（透传层不校验）
    nid3, out3 = _write_scene(cg, "sp_b3", "not-a-dict")
    ok(out3.get("verdict") == "ACCEPT" and _entry_spatial(cg, nid3) == "not-a-dict",
       "B3 spatial 非 dict 原样透传不抛（边界如实）", _entry_spatial(cg, nid3))
    return len(_FAIL) - n0


# 生效条件：无入参；C 组——MCP 面上游半段行为 + 四处映射在场（返回红项数）。
def group_c():
    n0 = len(_FAIL)
    from . import mcp_server
    cg = _fresh_cg()
    res = mcp_server._dispatch(cg, "mdcg_remember", {
        "node_id": "sp_c1", "layer": "contextual", "gated": False,
        "content": "场景实体 桌子（table）位于 (1.5,0.45,6.0)，状态 neutral",
        "importance": 0.6,
        "tags": ["spatial", "cat:table", "ent:桌子", "world_model"],
        "spatial": {"coords3d": {"x": 1.5, "y": 0.45, "z": 6.0}},
    })
    ok(bool(res.get("ok")), "C1 _dispatch(mdcg_remember) 经 MCP 面写入 ok", res)
    ok(_entry_spatial(cg, "sp_c1") == {"coords3d": {"x": 1.5, "y": 0.45, "z": 6.0}},
       "C2 经 MCP 面 spatial 同样直存", _entry_spatial(cg, "sp_c1"))
    src = open(os.path.join(_REPO, "md_cg", "mcp_server.py"), encoding="utf-8").read()
    ok(src.count("**_spatial_kw(a)") >= 2 and "def _spatial_kw(a)" in src,
       "C3 透传映射在场：gated 分支与非 gated add 两处经同一单点（≥2 次+助手定义）",
       src.count("**_spatial_kw(a)"))
    i = src.find("_meta = {k: a[k] for k in")
    ok(i >= 0 and '"spatial"' in src[i:i + 900],
       "C4 复现 meta 键在场（入队后 accept 与直接落盘的元数据等价）")
    ok('spatial=_p("object"' in src, "C5 TOOLS schema 声明 spatial 参数（客户端可见）")
    return len(_FAIL) - n0


# 生效条件：无入参；D 组——既有键零位移（返回红项数）。
def group_d():
    n0 = len(_FAIL)
    cg = _fresh_cg()
    nid, _ = _write_scene(cg, "sp_d1", SP_A)
    e = _entry_fm(cg, nid)
    ok(e.get("tags") == ["spatial", "cat:fatfish", "ent:肥鱼", "world_model"],
       "D1 tags 原样（spatial 不干扰）", e.get("tags"))
    ok(e.get("importance") == 0.6, "D2 importance 原样", e.get("importance"))
    ok(not (e.get("condition_space") or {}).get("spatial"),
       "D3 既定 condition_space 零位移（spatial 走独立键）")
    return len(_FAIL) - n0


def run_all():
    print("== A 落盘直存 =="); group_a()
    print("== B 形态与边界 =="); group_b()
    print("== C MCP 面接线 =="); group_c()
    print("== D 既有键零位移 =="); group_d()


# ---------------------------------------------------------------------------
# 定点变异自证
# ---------------------------------------------------------------------------

_ANCHOR = "**_spatial_kw(a)"


# 生效条件：无入参；M1 行为变异——把 MdCGOS.add 的 spatial 剔除（模拟透传丢失），
# A2 单条断言应恰好转红 1 项；结束还原原方法。
def _mut_m1():
    real = MdCGOS.add

    def _stripped(self, node_id, content, layer="knowledge", **kw):
        kw.pop("spatial", None)
        return real(self, node_id, content, layer=layer, **kw)

    MdCGOS.add = _stripped
    try:
        n0 = len(_FAIL)
        cg = _fresh_cg()
        nid, _ = _write_scene(cg, "sp_m1", SP_A)
        ok(_entry_spatial(cg, nid) == SP_A, "M1 变异下 A2 断言（应转红）",
           _entry_spatial(cg, nid))
        return len(_FAIL) - n0
    finally:
        MdCGOS.add = real


# 生效条件：无入参；M2 源码变异——删一处透传调用，C3 计数断言应恰好转红 1 项。
def _mut_m2():
    p = os.path.join(_REPO, "md_cg", "mcp_server.py")
    src = open(p, encoding="utf-8").read()
    if _ANCHOR not in src:
        return None                       # ANCHOR-MISS 由调用方判 2
    mut = src.replace(_ANCHOR, "None  # mutated", 1)
    n0 = len(_FAIL)
    ok(mut.count(_ANCHOR) >= 2 and "def _spatial_kw(a)" in mut,
       "M2 变异下 C3 计数断言（应转红）", mut.count(_ANCHOR))
    return len(_FAIL) - n0


def run_mutate():
    ok(len(_FAIL) == 0 and len(_PASS) >= 0, "前置：变异轮前无失败")
    print("== 定点变异自证 ==")
    verdict = 0
    base_fail = len(_FAIL)
    red1 = _mut_m1()
    if red1 != 1:
        print(f"  FAIL M1 预期恰好 1 红，实得 {red1}")
        verdict = 1
    red2 = _mut_m2()
    if red2 is None:
        print("  ANCHOR-MISS：源码透传锚点不在场（实现已改而本表未同步）")
        verdict = 2
    elif red2 != 1:
        print(f"  FAIL M2 预期恰好 1 红，实得 {red2}")
        verdict = 1
    if verdict == 0:
        print("  MUTATE=PASS（两处定点变异各自恰好命中 1 项）")
    # 变异轮的落红不计入正式判定
    del _FAIL[base_fail:]
    return verdict


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    _sandbox_env()
    try:
        if "--mutate" in argv:
            rc = run_mutate()
        else:
            run_all()
            print()
            print(f"===== SUMMARY {len(_PASS)}/{len(_PASS) + len(_FAIL)} 通过 =====")
            rc = 1 if _FAIL else 0
        return rc
    finally:
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
