# -*- coding: utf-8 -*-
"""issue #52 守卫：stg「条件先行于限额」+「截断可观测」（第 1/2 层）。

背景（外部报告 bixianzuose，2026-10-03 核实成立）：`md_cg/stg.py::_scan` 旧实现
`list(cg.index["nodes"].items())[:max_scan]`（max_scan 默认 5000）在**条件过滤
之前**按 id 字典序切片 ⇒ 库超 5000 节点后：
  (a) 条件命中（本会话记忆/layer/时间窗）落在切片外即被**永久排除**（在役库实测
      `timeline(session=…)` 默认口径 count=25 且全为 code_*，被切 204 条含 15 条
      mem_*；今天新归档的记忆一条都召不回）；
  (b) 选面按 id 字典序（无意义序）——新写入节点恰在索引尾部必被切；
  (c) 截断完全静默（返回体无任何标记）——「读不全」与「读不到」不可区分；
  (d) 被排除集合随索引重排漂移（运行期 dict 追加 vs 重建后 sorted 写盘）。
三接口 timeline/anchors/consistency 共用 `_scan` 同病；MCP 面 `_stg_call` 不透传
max_scan（永远默认口径）；DSH 侧 hooks.ts:423 auto-recall 直连 timeline 默认口径。

本批修法（设计者裁定 2026-10-03，原文）：「遇到更多的检索节点，应该要建立索引，
明确检索条件，和不适用条件，而不是扩大节点数」⇒ 只落「条件先行 + 截断可观测」
两层。【禁止面】max_scan 数值不放大；默认不改 None（全量）；时间倒序只作**截断
发生时的兜底选序**，不作条件先行的替代。第 3 层（session/layer/time 结构索引 +
条件资格进 stg）另立 `docs/plans/stg条件化与结构索引_设计_v0.1.md`。

断言分组（每组判据都有定点变异把它打红，见 `_MUTATIONS`）：
  G1 条件先行：条件命中不再被索引序切片吞掉——含 >5000 的**真实规模**场景
     （只带 index 的最小 cg 替身，5001 条目走快照路径）与「追加序 / 重建序」两形态；
  G2 截断可观测：truncated/scanned/kept/hint 在场且取值正确（hint 含「细化生效
     条件/不适用条件」「条件索引」语义）；count 恒为条件命中总数（在役对照
     25→229 的合成等价）；MCP 面 stg 透传同一批读数；
  G3 兜底选序：命中集超限时按时间倒序保留近期（无时间区间者先被截）；
  G4 语义红线：max_scan 默认 5000 不动、旧调用签名兼容、desc/limit/session="*"
     既有语义不变、_sec 可见性单点先于截断（不占 kept 名额）、旧快照回退读文件
     路径在、layer 过滤在；
  G5 结构：`_scan` 内不再有索引序切片（AST 判据，非源文本在场）。

判别力自证（与 `md_cg/test_neg_condition_hits.py` 同口径）：
  · `--branch-baseline`：逐处**定点变异**（源码级，含契约点名的三处：条件过滤移回
    截断之后 / 去掉 truncated 上报 / 截断选序改回字典序，另加 _scan 切片回退、
    默认值改全量、_sec 闸绕过、快照回退删分支、layer 过滤失效共八处）——每处必须
    **恰好**打红预期条数的断言（多一条少一条都报红），且**所有**断言至少被一处
    变异打红（一条都没被打红的＝空转，直接判 FAIL）。锚点漂移报 ANCHOR-MISS 且
    **退出码 2**（fail-closed，不静默失效）。
  · `--legacy-baseline`：把「修前形态」（切片先于条件 + 无截断上报）在运行时源码上
    原地重建，断言必须转红——证明本守卫抓得住 #52 这个缺陷本身，而非只抓得住
    我们自造的变异。
  · 基线源＝**运行时源码**（`inspect.getsource(stg)`），**不是 git HEAD**——基线绑
    提交即失效（本仓已有两次教训）；锚点都写在 `_MUTATIONS` 里，实现改动致锚点
    漂移时会当场报 ANCHOR-MISS。

运行：python -X utf8 -m md_cg.test_issue52_scan_condition_first
      python -X utf8 -m md_cg.test_issue52_scan_condition_first --branch-baseline
      python -X utf8 -m md_cg.test_issue52_scan_condition_first --legacy-baseline
"""
from __future__ import annotations

import ast
import contextlib
import inspect
import io
import os
import shutil
import sys
import tempfile
import types

from . import stg as _stg
from .mdcos import MdCGOS, MdCGSecure
from .security import Principal

S = _stg                    # 当前被测 STG 模块（变异模式 = exec 出的变异体命名空间）
_CUR_SRC = None             # 变异模式下当前的变异体源码（G5 的 AST 判据取它）
_PASS = []
_FAIL = []


def ok(cond, label, extra=""):
    (_PASS if cond else _FAIL).append(label)
    print(("  PASS " if cond else "  FAIL ") + label +
          (("  ← " + str(extra)[:200]) if (extra and not cond) else ""))


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def _ids(body):
    return [i["id"] for i in (body.get("items") or [])]


# ---------------------------------------------------------------- 合成库（系统临时目录）
# 硬边界：不动任何在役数据根——全部库建在 tempfile.mkdtemp 下，用完即删。

def _mk_small(root, name, rebuild=False):
    """8 节点：6 填充（session=other-sess，id 字典序在前）+ 2 目标（session=target-sess，
    id 字典序在后）。max_scan=3 的显式小值＝「库超 5000」的等价放大（id 序尾部必被切）。"""
    cg = MdCGOS(os.path.join(root, name))
    for i in range(6):
        cg.add("a%02d" % i, "# 功能名：填充 %d\n# 正文：填充节点 %d" % (i, i),
               layer="knowledge", temporal=1000.0 + i, session="other-sess")
    for i in range(2):
        cg.add("zz_target_%d" % i,
               "# 功能名：目标 %d\n# 正文：目标节点 %d" % (i, i),
               layer="knowledge", temporal=5000.0 + i, session="target-sess")
    cg.flush()
    if rebuild:
        cg.rebuild_index()      # 索引序=字典序（sorted 写盘）
    return cg


def _mk_layers(root, name):
    """5 节点：3 条 anchor 层 + 2 条 knowledge 层（同会话，id 前缀区分层序）。"""
    cg = MdCGOS(os.path.join(root, name))
    for i in range(3):
        cg.add("anc_%d" % i, "# 功能名：锚 %d\n# 正文：锚节点 %d" % (i, i),
               layer="anchor", temporal=3000.0 + i, session="sess_L")
    for i in range(2):
        cg.add("kno_%d" % i, "# 功能名：知 %d\n# 正文：知识节点 %d" % (i, i),
               layer="knowledge", temporal=2000.0 + i, session="sess_L")
    cg.flush()
    return cg


def _mk_trunc(root, name):
    """13 节点：3 填充（session=other-sess）+ 10 命中（session=sess_T，temporal 递增，
    id 形如 t00..t09——字典序与时间序同向，故「字典序切片」保最旧、「时间倒序」保最新，
    两侧可判别）。"""
    cg = MdCGOS(os.path.join(root, name))
    for i in range(3):
        cg.add("a_fill_%d" % i, "# 功能名：填充 %d\n# 正文：填充" % i,
               layer="knowledge", temporal=100.0 + i, session="other-sess")
    for i in range(10):
        cg.add("t%02d" % i, "# 功能名：命中 %d\n# 正文：命中节点 %d" % (i, i),
               layer="knowledge", temporal=1000.0 + i, session="sess_T")
    cg.flush()
    return cg


def _mk_anchor_bbox(root, name):
    """10 节点：4 条无时间（仅 spatial bbox）+ 6 条有 temporal（bbox 同名）。
    空间查询 bbox=[0,0,100,100] 时 10 条全是条件命中；截断时无时间者应先被截。
    注：add() 对未给 time_window 的节点会以**写入时刻**自动填充（_interval 注释
    记载的既有行为），故 4 条「无时间」节点须把索引快照里的 time_window 键摘掉
    ——快照路径由此得到 iv=None（幂等：重复跑无副作用）。"""
    cg = MdCGOS(os.path.join(root, name))
    for i in range(4):
        cg.add("a_notime_%d" % i, "# 功能名：无时间 %d\n# 正文：无时间节点" % i,
               layer="knowledge", spatial={"bbox": [1, 1, 9, 9]}, session="sess_B")
    for i in range(6):
        cg.add("z_timed_%d" % i, "# 功能名：有时间 %d\n# 正文：有时间节点" % i,
               layer="knowledge", temporal=2000.0 + i,
               spatial={"bbox": [1, 1, 9, 9]}, session="sess_B")
    cg.flush()
    for i in range(4):
        cg.index["nodes"]["a_notime_%d" % i].pop("time_window", None)
    return cg


def _mk_cons_recency(root, name):
    """10 节点：7 条自洽（temporal=i）+ 3 条**最新**且时间倒置（condition_space.time_window
    [9000,8000]）。consistency 截断到 3 时，保留的应是最近 3 条 ⇒ issues 恰为这 3 条。"""
    cg = MdCGOS(os.path.join(root, name))
    for i in range(7):
        cg.add("c%02d" % i, "# 功能名：自洽 %d\n# 正文：自洽节点 %d" % (i, i),
               layer="knowledge", temporal=1000.0 + i, session="sess_C")
    for i in range(7, 10):
        cg.add("c%02d" % i, "# 功能名：倒置 %d\n# 正文：倒置节点 %d" % (i, i),
               layer="knowledge", session="sess_C",
               condition_space={"time_window": [9000 + i, 8000 + i]})
    cg.flush()
    return cg


def _mk_live(root, name, n_hits=229, n_fill=3):
    """在役对照的合成等价：229 条 session=sess_live 命中 + 3 条异会话填充。"""
    cg = MdCGOS(os.path.join(root, name))
    for i in range(n_fill):
        cg.add("a_fill_%d" % i, "# 功能名：填充 %d\n# 正文：填充" % i,
               layer="knowledge", temporal=1.0 + i, session="other-sess")
    for i in range(n_hits):
        cg.add("m%04d" % i, "# 功能名：在役对照 %d\n# 正文：对照节点 %d" % (i, i),
               layer="knowledge", temporal=1000.0 + i, session="sess_live")
    cg.flush()
    return cg


def _mk_secure(root, name):
    """可见性红线库：3 条 internal（跨会话共享）+ 2 条 private（绑定 sess_A）。
    读侧是 sess_B / clearance=internal / 非 admin ⇒ 只应看见 3 条。"""
    root = os.path.join(root, name)
    wr = Principal(actor="i52wr", clearance="private", can_write=True,
                   can_admin=False, role="designer", session="sess_A",
                   harness="test-harness")
    w = MdCGSecure(root, principal=wr)
    for i in range(3):
        w.add("v_pub_%d" % i, "# 功能名：共享 %d\n# 正文：共享节点 %d" % (i, i),
              layer="knowledge", temporal=4000.0 + i, session="sess_A")
    for i in range(2):
        w.add("v_priv_%d" % i, "# 功能名：私有 %d\n# 正文：私有节点 %d" % (i, i),
              layer="knowledge", temporal=4500.0 + i, session="sess_A",
              sensitivity="private")
    w.flush()
    rd = Principal(actor="i52rd", clearance="internal", can_write=False,
                   can_admin=False, role="designer", session="sess_B",
                   harness="test-harness")
    return MdCGSecure(root, principal=rd)


def _mk_snapshot_legacy(root, name):
    """旧快照形态库：构造后把索引条目的 temporal/spatial 键摘掉 ⇒ 走「回退读文件」路径。"""
    cg = MdCGOS(os.path.join(root, name))
    cg.add("a_fill", "# 功能名：填充\n# 正文：填充节点", layer="knowledge",
           temporal=900.0, session="other-sess")
    for i in range(2):
        cg.add("zz_target_%d" % i, "# 功能名：目标 %d\n# 正文：目标" % i,
               layer="knowledge", temporal=5000.0 + i, session="target-sess")
    cg.flush()
    for e in list(cg.index["nodes"].values()):    # 快照迭代（H-4(a)：裸迭代即红）
        e.pop("temporal", None)
        e.pop("spatial", None)
    return cg


class _IndexOnly:
    """只带 index/_read/get 的最小 cg 替身——驱动 stg 的**快照路径**（不落盘、不建库）。

    用途：把「库超 max_scan（默认 5000）」做到**真实规模**（5001 个索引条目，今日
    新写入的目标节点在 id 字典序尾部）而不写 5001 个文件。除 `_read`（只被预览调用）
    外，走的是与真库逐位相同的 stg 代码路径：`_scan` 全部命中快照分支（条目带
    temporal 键，不触发回退读文件）。
    """

    def __init__(self, entries):
        self.index = {"nodes": entries}

    def get(self, nid):
        e = self.index["nodes"].get(nid)
        return {"frontmatter": dict(e), "content": ""} if e else None

    def _read(self, e):
        return (dict(e), "")


def _mk_index_only(n_bulk=5000):
    """5000 条旧节点（sess_other，id 形如 k00000 字典序在前）+ 1 条今日新记忆
    （sess_today，id=zz_new_mem 字典序在**尾部**）。"""
    entries = {}
    for i in range(n_bulk):
        entries["k%05d" % i] = {"layer": "knowledge", "path": "knowledge/k%d.md" % i,
                                "temporal": 1000.0 + i, "spatial": None,
                                "session": "sess_other", "time_window": None}
    entries["zz_new_mem"] = {"layer": "knowledge", "path": "knowledge/zz_new_mem.md",
                             "temporal": 10 ** 6, "spatial": None,
                             "session": "sess_today", "time_window": None}
    return _IndexOnly(entries)


def _mk_index_mcp(n_hits=5100, n_fill=100):
    """MCP 面截断场景：5100 条 sess_mcp 命中（默认 max_scan=5000 下命中集超限）
    + 100 条异会话填充（id 字典序在前——M1 类切片在这些条目上先消耗限额）。"""
    entries = {}
    for i in range(n_fill):
        entries["a_fill_%03d" % i] = {"layer": "knowledge",
                                      "path": "knowledge/af%d.md" % i,
                                      "temporal": 10.0 + i, "spatial": None,
                                      "session": "sess_other", "time_window": None}
    for i in range(n_hits):
        entries["m%05d" % i] = {"layer": "knowledge", "path": "knowledge/m%d.md" % i,
                                "temporal": 1000.0 + i, "spatial": None,
                                "session": "sess_mcp", "time_window": None}
    return _IndexOnly(entries)


class _Fixtures:
    """一次构建、多轮复用（变异核验要重跑 N 轮）——库面与变异面正交（变异只改 stg 源码）。

    库都是只读消费（唯一例外 _mk_snapshot_legacy 的摘键是幂等的，第二次跑无副作用）。
    """

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="mdcg_i52_")
        self.small = _mk_small(self.tmp, "small")                 # 追加序
        self.small_rb = _mk_small(self.tmp, "small_rb", rebuild=True)   # 重建序
        self.layers = _mk_layers(self.tmp, "layers")
        self.trunc = _mk_trunc(self.tmp, "trunc")
        self.abox = _mk_anchor_bbox(self.tmp, "abox")
        self.cons = _mk_cons_recency(self.tmp, "cons")
        self.live = _mk_live(self.tmp, "live")
        self.secure = _mk_secure(self.tmp, "secure")
        self.snap = _mk_snapshot_legacy(self.tmp, "snap")
        self.index_only = _mk_index_only()
        self.index_mcp = _mk_index_mcp()

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------- G1 条件先行
def g1_condition_first(fx):
    print("== G1 条件先行：条件命中不再被索引序切片吞掉 ==")
    tl = S.timeline(fx.small, session="target-sess", max_scan=3)
    ok(tl.get("count") == 2 and _ids(tl) == ["zz_target_1", "zz_target_0"],
       "A1 运行期追加序：会话条件命中不被切片吞掉（count=2、两条目标都在；修前 count=0）",
       (tl.get("count"), _ids(tl)))

    tl_rb = S.timeline(fx.small_rb, session="target-sess", max_scan=3)
    ok(_ids(tl_rb) == ["zz_target_1", "zz_target_0"] and _ids(tl_rb) == _ids(tl),
       "A2 重建索引（字典序写盘）后逐位一致——被排除集合不随索引重排漂移",
       _ids(tl_rb))

    tl_cross = S.timeline(fx.small, max_scan=3)
    ok(tl_cross.get("count") == 8,
       "A3 跨会话视图 count=全库 8（修前被静默切为 3）", tl_cross.get("count"))

    an = S.anchors(fx.small, time_window=[4900, 5100], max_scan=3)
    ok(an.get("count") == 2 and set(_ids(an)) == {"zz_target_0", "zz_target_1"},
       "A4 anchors 时间窗条件命中同样先于限额（count=2；修前 count=0）",
       (an.get("count"), _ids(an)))

    co = S.consistency(fx.small, max_scan=3)
    ok(co.get("scanned") == 8,
       "A5 consistency 遍历面=全库 8（修前 scanned=3，截断静默）", co.get("scanned"))

    ok(S.timeline(fx.layers, layer="anchor", max_scan=3).get("count") == 3
       and S.timeline(fx.layers, layer="knowledge", max_scan=3).get("count") == 2,
       "A6 layer 面条件命中不被切片吞掉（anchor 3 / knowledge 2）",
       (S.timeline(fx.layers, layer="anchor", max_scan=3).get("count"),
        S.timeline(fx.layers, layer="knowledge", max_scan=3).get("count")))

    # A7：**真实规模**（5001 索引条目，默认 max_scan=5000）——今日新记忆在 id 字典序尾部
    tl_big = S.timeline(fx.index_only, session="sess_today")
    ok(tl_big.get("count") == 1 and _ids(tl_big) == ["zz_new_mem"],
       "A7 库超 5000：字典序尾部的今日新记忆仍召得回（修前 count=0——#52 的临床面）",
       (tl_big.get("count"), _ids(tl_big)))
    ok(tl_big.get("scanned") == 5001 and tl_big.get("kept") == 1
       and tl_big.get("truncated") is False,
       "A8 库超 5000：遍历读数=5001、命中未超限不标记截断",
       {k: tl_big.get(k) for k in ("scanned", "kept", "truncated")})


# ---------------------------------------------------------------- G2 截断可观测
def g2_truncation_reads(fx):
    print("== G2 截断可观测：truncated/scanned/kept/hint + count 语义 ==")
    tl = S.timeline(fx.trunc, session="sess_T", max_scan=4)
    ok(tl.get("truncated") is True, "B1 命中集超限 ⇒ truncated=True（修前无此键）",
       tl.get("truncated"))
    ok(tl.get("kept") == 4 and tl.get("scanned") == 13,
       "B2 读数：scanned=候选 13 / kept=截断后 4",
       (tl.get("scanned"), tl.get("kept")))
    hint = tl.get("hint") or ""
    ok(bool(hint) and "细化生效条件" in hint and "不适用条件" in hint
       and "条件索引" in hint,
       "B3 截断附可操作 hint（细化生效条件/不适用条件 or 建立条件索引，禁止静默）",
       hint)
    ok(tl.get("count") == 10,
       "B4 count=条件命中总数 10（不再受切片影响；修前 count=3）", tl.get("count"))

    tl0 = S.timeline(fx.small, session="target-sess", max_scan=3)
    ok(tl0.get("truncated") is False and "hint" not in tl0,
       "B5 未超限：truncated=False 且不附 hint（逐位兼容）",
       {k: tl0.get(k) for k in ("truncated", "hint")})

    an = S.anchors(fx.abox, bbox=[0, 0, 100, 100], max_scan=3)
    ok(an.get("truncated") is True and an.get("kept") == 3 and an.get("count") == 10,
       "B6 anchors：truncated/kept/count 三读数在场且正确",
       {k: an.get(k) for k in ("truncated", "kept", "count")})

    co = S.consistency(fx.cons, max_scan=3)
    ok(co.get("truncated") is True and co.get("kept") == 3 and co.get("scanned") == 10,
       "B7 consistency：truncated/kept/scanned 三读数在场且正确",
       {k: co.get(k) for k in ("truncated", "kept", "scanned")})

    tl_live = S.timeline(fx.live, session="sess_live", max_scan=25)
    ok(tl_live.get("count") == 229 and tl_live.get("kept") == 25
       and tl_live.get("truncated") is True,
       "B8 在役对照合成等价：count=229（修前 25）、kept=25、truncated=True",
       {k: tl_live.get(k) for k in ("count", "kept", "truncated")})

    # MCP 面：默认口径（max_scan 不在 MCP 入参面）下的截断——5100 条命中 > 5000，
    # 读数随返回体自动透传（本层不裁剪）。入参里带 max_scan 本批也无效（契约不加）。
    from .mcp_server import _stg_call
    mcp = _stg_call(fx.index_mcp, {"op": "timeline", "session": "sess_mcp",
                                   "limit": 3, "max_scan": 2})
    ok(mcp.get("count") == 5100 and mcp.get("truncated") is True
       and mcp.get("kept") == 5000 and mcp.get("scanned") == 5200
       and bool(mcp.get("hint")) and len(mcp.get("items") or []) == 3,
       "B9 MCP 面 stg：默认口径超限的截断读数随返回体透传（kept=5000 而非入参 2）",
       {k: mcp.get(k) for k in ("count", "truncated", "kept", "scanned")})


# ---------------------------------------------------------------- G3 兜底选序
def g3_recency(fx):
    print("== G3 截断兜底选序：时间倒序保留近期（非主修法，只作超限时选序）==")
    tl = S.timeline(fx.trunc, session="sess_T", max_scan=4)
    ok(_ids(tl) == ["t09", "t08", "t07", "t06"],
       "C1 timeline 超限保留最近 4 条（字典序切片会保最旧的 t00..t03）", _ids(tl))

    an = S.anchors(fx.abox, bbox=[0, 0, 100, 100], max_scan=3)
    ok(all(h.get("time") is not None for h in (an.get("items") or []))
       and _ids(an) == ["z_timed_5", "z_timed_4", "z_timed_3"],
       "C2 anchors 超限：无时间区间者先被截，保留最近 3 条定时命中",
       [(h.get("id"), h.get("time")) for h in (an.get("items") or [])])

    co = S.consistency(fx.cons, max_scan=3)
    ok({i["id"] for i in (co.get("items") or [])} == {"c07", "c08", "c09"},
       "C3 consistency 超限后检查的是最近 3 条（issues 恰为这 3 条倒置节点）",
       [i["id"] for i in (co.get("items") or [])])


# ---------------------------------------------------------------- G4 语义红线
def g4_redlines(fx):
    print("== G4 语义红线：默认值/签名兼容/既有语义/可见性/回退路径 ==")
    for fn, label in ((S.timeline, "D1a timeline"), (S.anchors, "D1b anchors"),
                      (S.consistency, "D1c consistency")):
        d = inspect.signature(fn).parameters["max_scan"].default
        ok(d == 5000, "%s max_scan 默认 5000 保留（禁止调大/禁止默认 None）" % label, d)

    out = S.timeline(fx.small, limit=5)
    ok("count" in out and "items" in out and out.get("truncated") is False
       and isinstance(out.get("scanned"), int),
       "D2a 旧调用签名兼容：不传 max_scan 正常返回且读数在场",
       {k: out.get(k) for k in ("count", "truncated", "scanned")})
    an = S.anchors(fx.small, time_window=[1000, 6000], limit=5)
    ok(an.get("count") == 8 and an.get("truncated") is False,
       "D2b anchors 旧调用兼容（count=8、未截断）",
       {k: an.get(k) for k in ("count", "truncated")})
    co = S.consistency(fx.small, limit=5)
    ok(co.get("scanned") == 8 and isinstance(co.get("kept"), int)
       and co.get("truncated") is False,
       "D2c consistency 旧调用兼容（scanned=8、读数在场）",
       {k: co.get(k) for k in ("scanned", "kept", "truncated")})

    # D3 _sec 可见性单点：先于一切（含截断）——不可见节点不占 kept 名额、不泄露 id
    sec = S.timeline(fx.secure, max_scan=2)
    ok(sec.get("scanned") == 3, "D3a 可见性先于遍历读数：候选只有 3 条共享档",
       sec.get("scanned"))
    ok(sec.get("count") == 3, "D3b 命中数=可见面 3（私有档不进条件命中集）",
       sec.get("count"))
    ok(not ({"v_priv_0", "v_priv_1"} & set(_ids(sec))),
       "D3c 绑定档 id 不出现在返回体（不泄露存在性）", _ids(sec))
    ok(sec.get("kept") == 2 and sec.get("truncated") is True,
       "D3d 截断名额只给可见候选（可见性判定不得重排为截断之后）",
       {k: sec.get(k) for k in ("kept", "truncated")})

    # D4 旧索引快照（无 temporal/spatial 键）回退读文件路径保持
    snap = S.timeline(fx.snap, session="target-sess", max_scan=3)
    ok(snap.get("count") == 2 and set(_ids(snap)) == {"zz_target_0", "zz_target_1"},
       "D4 旧快照缺键回退读文件路径保持（命中仍可见）",
       (snap.get("count"), _ids(snap)))

    # D5 layer 过滤在（_scan 内，条件面之一）
    ok(S.timeline(fx.layers, layer="anchor", max_scan=3).get("count") == 3
       and S.timeline(fx.layers, layer="knowledge", max_scan=3).get("count") == 2,
       "D5 layer 过滤仍生效（anchor 3 / knowledge 2）",
       (S.timeline(fx.layers, layer="anchor", max_scan=3).get("count"),
        S.timeline(fx.layers, layer="knowledge", max_scan=3).get("count")))

    # D6 既有 desc/limit/session 语义逐位不变
    z = S.timeline(fx.small, session="target-sess", limit=0, max_scan=3)
    ok(z.get("items") == [] and z.get("count") == 2,
       "D6a limit=0 取空 items 但 count 仍为条件命中总数", (z.get("items"), z.get("count")))
    asc = S.timeline(fx.small, session="target-sess", desc=False, max_scan=3)
    ok(_ids(asc) == ["zz_target_0", "zz_target_1"],
       "D6b desc=False 升序（(start,end,id) 序不变）", _ids(asc))
    star = S.timeline(fx.small, session="*", max_scan=3)
    ok(star.get("count") == 8 and star.get("count") == S.timeline(
        fx.small, max_scan=3).get("count"),
       "D6c session=\"*\" 与缺省同义（跨会话读全）", star.get("count"))


# ---------------------------------------------------------------- G5 结构
def g5_structure(fx):
    print("== G5 结构：_scan 内不再有索引序切片（AST 判据） ==")
    src = _CUR_SRC if _CUR_SRC is not None else inspect.getsource(_stg)
    fn = None
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == "_scan":
            fn = node
            break
    slices = [] if fn is None else [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice)]
    ok(fn is not None and not slices,
       "E1 _scan 存在且内无切片子表达式（旧 `list(...items())[:max_scan]` 回退即红；"
       "定义消失同样红——不静默空转）",
       (fn is None, [getattr(s, "lineno", "?") for s in slices]))


_GROUPS = (g1_condition_first, g2_truncation_reads, g3_recency,
           g4_redlines, g5_structure)


def _run_groups(fx) -> list:
    """跑全部分组，返回失败标签列表（静默模式复用；单组异常记为 EXC 标签）。"""
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g(fx)
        except Exception as e:                     # noqa: BLE001  变异可能炸——记标签不中断
            label = "EXC:%s:%s" % (g.__name__, type(e).__name__)
            _FAIL.append(label)
            print("  FAIL " + label + "  ← " + str(e)[:160])
    return list(_FAIL)


# ---------------------------------------------------------------- 定点变异表
# 每条 = (名字, [(旧源码, 新源码), ...], 预期打红条数)。
# 锚点缺失 ⇒ ANCHOR-MISS + 退出码 2（fail-closed）；预期条数不符 ⇒ 报红（「恰好」语义）。
_M1 = [
    ("    items = []\n    for n in _scan(cg, layer=layer):",
     "    items = []\n    for n in _scan(cg, layer=layer)[:max_scan]:"),
    ("    hits = []\n    for n in _scan(cg, layer=layer):",
     "    hits = []\n    for n in _scan(cg, layer=layer)[:max_scan]:"),
    ("    cand = list(_scan(cg, layer=layer))",
     "    cand = list(_scan(cg, layer=layer))[:max_scan]"),
]
_M2 = [
    ("    out.update({\"scanned\": scanned, \"kept\": kept, \"truncated\": truncated})\n"
     "    if truncated:\n"
     "        out[\"hint\"] = _CAP_HINT % (hits, max_scan, kept)\n"
     "    return out",
     "    return out"),
]
_M3 = [
    ("_cap_hits(items, max_scan, _tl_recent)",
     "_cap_hits(items, max_scan, (lambda x: ()))"),
    ("_cap_hits(hits, max_scan, _an_recent)",
     "_cap_hits(hits, max_scan, (lambda x: ()))"),
    ("_cap_hits(cand, max_scan, lambda n: _co_recent(n, time_axis))",
     "_cap_hits(cand, max_scan, (lambda n: ()))"),
]
_MUTATIONS = (
    ("①条件过滤移回截断之后（三接口候选集切片）", _M1, 24),
    ("②去掉 truncated 上报（读数/hint 一并消失）", _M2, 15),
    ("③截断选序改回字典序", _M3, 3),
    ("④_scan 恢复索引序切片（回退 5000）",
     [("    for nid, e in list(cg.index[\"nodes\"].items()):",
       "    for nid, e in list(cg.index[\"nodes\"].items())[:5000]:")], 4),
    ("⑤max_scan 默认改 None（全量，契约禁止面）",
     [("max_scan=5000", "max_scan=None")], 4),
    ("⑥_sec 可见性闸绕过",
     [("        if _sec is not None and not _sec(e):\n            continue",
       "        if False:\n            continue")], 3),
    ("⑦去掉旧快照回退读文件分支",
     [("            fm, _content = cg._read(e)",
       "            fm, _content = None, None")], 1),
    ("⑧layer 过滤失效",
     [("        if layer and e.get(\"layer\") != layer:\n            continue",
       "        if False:\n            continue")], 2),
)

_LEGACY_REPLS = _M1 + _M2        # 修前形态重建：切片先于条件 + 无截断上报


def _build_mutant(replacements):
    """在**运行时源码**上做替换并 exec 成模块命名空间。

    返回 (attr_ns, raw_ns, src)；锚点缺失返回 (None, None, None)。attr_ns 供 S.x
    取用（函数各自的 globals 仍是 raw_ns ⇒ 变异体内部自洽）。
    """
    src = _CUR_SRC if _CUR_SRC is not None else inspect.getsource(_stg)
    for old, new in replacements:
        if old not in src:
            return None, None, None
        src = src.replace(old, new)
    ns = {"__name__": "md_cg._stg_mutant", "__package__": "md_cg",
          "__file__": getattr(_stg, "__file__", "<stg>")}
    exec(compile(src, "<stg-mutant>", "exec"), ns)   # noqa: S102  测试内变异自证
    return types.SimpleNamespace(**ns), ns, src


def _activate(mod, raw_ns, src):
    """把变异体的可调用面临时挂上真源模块（_stg_call 等经属性取用 → 变异可见）。"""
    global S, _CUR_SRC
    saved = {}
    for k in list(_stg.__dict__):
        if k.startswith("__") or k not in raw_ns:
            continue
        saved[k] = _stg.__dict__[k]
        setattr(_stg, k, raw_ns[k])
    S = mod
    _CUR_SRC = src
    return saved


def _deactivate(saved):
    global S, _CUR_SRC
    for k, v in saved.items():
        setattr(_stg, k, v)
    S = _stg
    _CUR_SRC = None


def _branch_baseline(fx) -> int:
    print("!! 定点变异自证：逐处变异，断言须**恰好**打红预期条数；锚点漂移=ANCHOR-MISS+退出码 2\n")
    with _quiet():
        clean_red = _run_groups(fx)
    all_labels = set(_PASS) | set(_FAIL)
    if clean_red:
        print("  未变异基线即失败：%s" % clean_red)
        return 1
    print("  未变异基线：%d 条断言全绿" % len(all_labels))
    reddened = set()
    bad = []
    for name, repls, expect in _MUTATIONS:
        mod, raw_ns, src = _build_mutant(repls)
        if mod is None:
            print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步 _MUTATIONS）" % name)
            return 2
        saved = _activate(mod, raw_ns, src)
        try:
            with _quiet():
                reds = _run_groups(fx)
        finally:
            _deactivate(saved)
        reddened |= set(reds)
        hit = len(reds) == expect
        print("  变异「%s」→ 打红 %d 条（预期 %d）%s"
              % (name, len(reds), expect, "OK" if hit else "**不符**"))
        if not hit:
            bad.append("%s：红 %d ≠ 预期 %d" % (name, len(reds), expect))
            for r in sorted(reds):
                print("      red: " + r)
    never = sorted(all_labels - reddened)
    if never:
        print("  **空转断言（无任何变异能打红）**：%s" % "、".join(never))
        bad.append("空转断言 %d 条" % len(never))
    print("\n判别力自证：%s" % ("PASS（八处变异各自恰好命中，且无空转断言）"
                             if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def _legacy_baseline(fx) -> int:
    print("!! 修前形态重建（切片先于条件 + 无截断上报）：断言应当转红\n")
    mod, raw_ns, src = _build_mutant(_LEGACY_REPLS)
    if mod is None:
        print("  ANCHOR-MISS —— 修前形态重建的锚点漂移")
        return 2
    saved = _activate(mod, raw_ns, src)
    try:
        with _quiet():
            reds = _run_groups(fx)
    finally:
        _deactivate(saved)
    print("  修前形态下打红 %d 条：%s" % (len(reds), "、".join(sorted(reds))))
    core = {l for l in reds if l.startswith("A1 ") or l.startswith("A3 ")}
    miss = {"A1/A3（条件先行的核心断言）"} if len(core) < 2 else set()
    print("\n修前形态判定：%s" % ("PASS（核心断言转红——本守卫抓得住 #52 本身）"
                              if not miss else "FAIL —— 核心断言未转红：%s" % miss))
    return 0 if not miss else 1


def main() -> int:
    if "--branch-baseline" in sys.argv:
        fx = _Fixtures()
        try:
            return _branch_baseline(fx)
        finally:
            fx.close()
    if "--legacy-baseline" in sys.argv:
        fx = _Fixtures()
        try:
            return _legacy_baseline(fx)
        finally:
            fx.close()
    fx = _Fixtures()
    try:
        _run_groups(fx)
    finally:
        fx.close()
    print("\nissue52 守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
