# -*- coding: utf-8 -*-
"""stgidx 守卫：第 3 层结构索引（装载期内存倒排 + 写钩增量 + 读侧直取）。

契约（设计稿 `docs/plans/stg条件化与结构索引_设计_v0.1.md`，2026-10-03 签收）：
  · 等价性为**唯一准入**：`MDCG_STG_INDEX` 关/开两臂，三接口**业务字段逐位一致**
    （除 `scanned` 与新增 `index` 读数——设计稿 §四「除 meta 计数」）；
  · 索引维护不变量：三张表恒为快照 keys 的**划分**（写/删/rebuild/compact/flush 后）；
  · 回退可观测：表缺失/代际不符/旧快照条目/no-condition ⇒ 回退第 1 层全量遍历并带
    reason（**禁止静默**）；
  · 收敛可观测：开臂 `scanned`（遍历面）收窄、`index.size`/`full_nodes` 读数在场；
  · 截断语义继承第 1/2 层（truncated/kept/近期优先逐位不变）；
  · `unassigned`（无会话节点）语义保持现状（只在跨会话视图可见）；
  · 条件资格首验（`MDCG_STG_QUALIFY`）**只上报不过滤**。

断言分组：
  G1 两臂等价（业务字段逐位 + 形态读数钉住，含 >5000 节点在役形态级合成库）
  G2 维护不变量（写/删/层迁移/会话改写/rebuild/compact/flush 后表与快照一致）
  G3 unassigned 语义回归
  G4 截断语义继承
  G5 meta 可观测（诸回退 reason + 表规模 + 自愈 + flag 关不构建）
  G6 资格首验（只上报不过滤；同口径 = read 面单点）
  G7 结构/单点（资格判据唯一调用点、_scan 无切片）

判别力自证（`--branch-baseline`，与 `md_cg/test_issue52_scan_condition_first.py` 同口径）：
  · 逐处**定点变异**（源码级替换 + 运行期装配）：每处必须**恰好**打红预期条数的
    断言（多一条少一条都报红）；
  · **空转断言检查**：任何断言若一处变异都打不红 ⇒ 直接判 FAIL（禁空转）；
  · **变异表完整性自检**（`_table_gaps`，先例 `test_autonomy_modes`）：编号无缺口 +
    表长与显式声明一致——删条目（或注释与元组同删）即机械报错；
  · 锚点漂移报 ANCHOR-MISS 且**退出码 2**（fail-closed，不静默失效）；
  · 基线源 = **运行时源码**（`inspect.getsource`），**禁止以 git HEAD 为基线源**
    （基线绑提交即失效，本仓已有两次教训）。

设计说明（为什么等价性判据同时钉形态读数）：候选集是**超集**时结果不变（逐条精确
判定仍在 `_scan` 侧），故「取数面没收窄/取错序」这类缺陷只改 `scanned` 与条目次序
——只看两臂结果相等的断言抓不住它们。故每个用例的判据 = 「两臂业务字段逐位一致」
**且**「开臂形态读数 == 校准值（path/fallback/count/scanned/index_hit）」。

运行：
  python -X utf8 -m md_cg.test_stgidx_index_parity
  python -X utf8 -m md_cg.test_stgidx_index_parity --branch-baseline
"""
from __future__ import annotations

import ast
import contextlib
import inspect
import io
import os
import re
import shutil
import sys
import tempfile

from . import mdcg as _mdcg
from . import stg as _stg
from . import stgidx as _stgidx
from .mdcos import MdCGOS, MdCGSecure
from .security import Principal

S = _stg                    # 被测 STG 模块（变异模式下 = 变异体命名空间）
_CUR_SRC = None             # 变异模式下 stg 模块的**变异体源码**（G7 的 AST 判据取它）
INDEX_ENV = "MDCG_STG_INDEX"
QUALIFY_ENV = "MDCG_STG_QUALIFY"

_PASS = []
_FAIL = []


def ok(cond, label, extra=""):
    (_PASS if cond else _FAIL).append(label)
    print(("  PASS " if cond else "  FAIL ") + label +
          (("  ← " + str(extra)[:240]) if (extra and not cond) else ""))


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(io.StringIO()):
        yield


@contextlib.contextmanager
def _env(**kv):
    """临时设/清环境变量（两臂开关；退出即还原）。"""
    saved = {}
    try:
        for k, v in kv.items():
            saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def _clean_env():
    with _env(**{INDEX_ENV: None, QUALIFY_ENV: None}):
        yield


def _biz(body):
    """业务字段面：除 `scanned`（遍历面，索引臂按设计收窄）与 `index` 读数外全部。"""
    return {k: v for k, v in body.items() if k not in ("scanned", "index")}


def _ids(body):
    return [i["id"] for i in (body.get("items") or [])]


def _two_arm(cg, fn):
    """同一 cg 上跑关/开两臂；返回 (off_body, on_body)。

    开臂前把 `_stg_index` 置 None ⇒ **每轮从零构建**：夹具跨变异轮复用，若沿用
    上一轮缓存的表，「构建路径」的定点变异（by_time 排序键/分类口径）会被旧表
    遮住而判不出来。
    """
    with _clean_env():
        cg._stg_index = None
        off = fn(cg)
    with _env(**{INDEX_ENV: "1"}):
        cg._stg_index = None
        on = fn(cg)
    return off, on


def _verify(cg):
    ix = getattr(cg, "_stg_index", None)
    if ix is None:
        return None
    return _stgidx.verify(ix, (cg.index or {}).get("nodes") or {})


# ---------------------------------------------------------------- 合成库（系统临时目录）
# 硬边界：不动任何在役数据根——全部库建在 tempfile.mkdtemp 下，用完即删。

def _add(cg, nid, i, layer="knowledge", sess="s0", t=1000.0, window=None, **kw):
    """统一入口：显式落 `condition_space.time_window`（否则 add 以**写入时刻**自动
    填充，库内容将随运行时刻漂移——等价性判据必须可复现）。"""
    tw = [t, t + 10.0] if window is None else window
    cg.add(nid, "# 功能名：节点 %d\n# 生效条件：本地合成库\n# 子功能：守卫夹具\n"
                "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n# 正文：节点 %d"
           % (i, i),
           layer=layer, temporal=t, session=sess,
           condition_space={"time_window": tw,
                            "observation_position": "D%d" % (i % 3)},
           **kw)


def _mk_big(root, name="big"):
    """>5000 节点在役形态：多会话交错 + 无会话节点 + id 字典序与时间序错位 +
    目标会话在索引尾部 + 同刻并列。"""
    cg = MdCGOS(os.path.join(root, name))
    for i in range(5200):
        nid = "k%05d" % i
        sess = None if (i % 37 == 0) else ("s%d" % (i % 4))
        t = 900000.0 - i                     # id 递增、时间递减（错位）
        if i % 100 == 7:                     # 同刻并列
            t = 900000.0 - (i - (i % 100))
        _add(cg, nid, i, sess=sess, t=t)
    for i in range(120):
        _add(cg, "zz_t%03d" % i, i, sess="sess_target", t=900100.0 + i)
    cg.flush()
    return cg


def _mk_mixed(root, name="mixed"):
    """层/无时间/无会话/倒置窗/NaN/并列/仅窗/资格面——小库。"""
    cg = MdCGOS(os.path.join(root, name))
    for i in range(3):
        _add(cg, "anc_%d" % i, i, layer="anchor", sess="sess_L", t=3000.0 + i)
    for i in range(2):
        _add(cg, "kno_%d" % i, i, sess="sess_L", t=2000.0 + i,
             spatial={"bbox": [1, 1, 9, 9]})
    _add(cg, "non_sess_0", 0, sess=None, t=2500.0)      # unassigned
    _add(cg, "notime_0", 0, sess="sess_L", t=2600.0, spatial={"bbox": [1, 1, 9, 9]})
    _add(cg, "inv_0", 0, sess="sess_L", t=2700.0, window=[9000.0, 8000.0])
    _add(cg, "outside_0", 0, sess="sess_L", t=2800.0, window=[50000.0, 51000.0])
    _add(cg, "nan_0", 0, sess="sess_L", t=2900.0)
    _add(cg, "tie_0", 0, sess="sess_L", t=2950.0)
    _add(cg, "tie_1", 1, sess="sess_L", t=2950.0)
    # 仅有时窗、无 temporal 的节点：观察轴区间**走 time_window 回退**——
    # `stgidx.time_of` 若只认 temporal，本条会在时间窗查询里**漏召回**。
    cg.add("win_only_0",
           "# 功能名：仅窗 0\n# 生效条件：本地合成库\n# 子功能：守卫夹具\n"
           "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n# 正文：仅窗节点",
           layer="knowledge", session="sess_L",
           condition_space={"time_window": [2100.0, 2110.0]})
    # 资格面：本条的不适用条件命中 stg 情境（op 名 timeline）⇒ read 面判 REJECT；
    # **只上报不过滤**的判据靠它取证（被打回也仍须出现在返回条目里）。
    _add(cg, "rej_0", 0, sess="sess_L", t=2960.0,
         non_applicable_conditions=["timeline"], verification_basis="test")
    cg.flush()
    cg.index["nodes"]["notime_0"].pop("temporal", None)
    cg.index["nodes"]["notime_0"].pop("time_window", None)
    cg.index["nodes"]["nan_0"]["temporal"] = float("nan")
    return cg


def _mk_legacy(root, name="legacy"):
    """旧快照形态：条目无 temporal/spatial 键 ⇒ `_scan` 走回退读文件分支。"""
    cg = MdCGOS(os.path.join(root, name))
    for i in range(6):
        _add(cg, "a%02d" % i, i, sess="other-sess", t=1000.0 + i)
    for i in range(2):
        _add(cg, "zz_t_%d" % i, i, sess="target-sess", t=5000.0 + i)
    cg.flush()
    for e in list(cg.index["nodes"].values()):
        e.pop("temporal", None)
        e.pop("spatial", None)
    return cg


def _mk_secure(root, name="secure"):
    """可见性红线：3 条 internal（跨会话共享）+ 2 条 private（绑定 sess_A）。"""
    root = os.path.join(root, name)
    wr = Principal(actor="idxwr", clearance="private", can_write=True,
                   can_admin=False, role="designer", session="sess_A",
                   harness="test-harness")
    w = MdCGSecure(root, principal=wr)
    for i in range(3):
        _add(w, "v_pub_%d" % i, i, sess="sess_A", t=4000.0 + i)
    for i in range(2):
        _add(w, "v_priv_%d" % i, i, sess="sess_A", t=4500.0 + i,
             sensitivity="private")
    w.flush()
    rd = Principal(actor="idxrd", clearance="internal", can_write=False,
                   can_admin=False, role="designer", session="sess_B",
                   harness="test-harness")
    return MdCGSecure(root, principal=rd)


class _Fixtures:
    """一次构建、多轮复用（变异核验要重跑 N 轮）——库面只读，变异只改源码。"""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="mdcg_stgidx_")
        self.big = _mk_big(self.tmp)
        self.mixed = _mk_mixed(self.tmp)
        self.legacy = _mk_legacy(self.tmp)
        self.secure = _mk_secure(self.tmp)
        self._n = 0

    def scratch(self, name=None):
        """G2/G5 专用：每轮现建的小库（组内自毁自建，跨变异轮不串味）。"""
        self._n += 1
        return MdCGOS(os.path.join(self.tmp, name or ("g2_%d" % self._n)))

    def drop(self, cg):
        shutil.rmtree(os.path.join(self.tmp, os.path.basename(cg.root)),
                      ignore_errors=True)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# 等价性用例面：(键, 标签, 库, 调用)。
# 预期形态（`_EXPECT`）＝**在该确定性夹具上实测校准**的
# (path, fallback, count, scanned_on, index_hit)：
#   path  = 开臂取数面（index=索引直取 / full=回退全量）
#   count = 该接口的 count 读数（consistency 无 count ⇒ None）
#   scanned_on = 开臂实际遍历/触碰数（收敛读数）
#   index_hit = 经索引服务的条件维数
# 夹具改动（增删节点/改时刻）须同步本表——它是「收敛读数」判据的字面量。
_EXPECT = {
    "A01": ("index", None, 120, 120, 1),
    "A02": ("index", None, 1265, 1265, 1),
    "A03": ("full", "no_condition_dimension", 5320, 5320, 0),
    "A04": ("full", "no_condition_dimension", 5320, 5320, 0),
    "A05": ("index", None, 0, 0, 1),
    "A06": ("index", None, 120, 120, 1),
    "A07": ("index", None, 120, 120, 1),
    "A08": ("index", None, 120, 120, 1),
    "A09": ("index", None, 51, 51, 1),
    "A10": ("index", None, 1002, 1002, 2),
    "A11": ("index", None, 1002, 1002, 1),
    "A12": ("full", "no_condition_dimension", None, 5320, 0),
    "A13": ("index", None, None, 11, 1),
    "A14": ("index", None, 3, 3, 1),
    "A15": ("index", None, 12, 13, 1),
    "A16": ("index", None, 13, 13, 1),
    "A17": ("full", "no_condition_dimension", 3, 14, 0),
    "A18": ("full", "entry_file_read", 2, 8, 0),
    "A19": ("full", "no_condition_dimension", None, 8, 0),
    "A20": ("full", "no_condition_dimension", 3, 3, 0),
    "A21": ("index", None, 3, 3, 1),
}


def _cases(fx):
    stg = S
    return [
        ("A01", "timeline(session=目标会话·索引尾部)", fx.big,
         lambda c: stg.timeline(c, session="sess_target", limit=50)),
        ("A02", "timeline(session=多会话之一)", fx.big,
         lambda c: stg.timeline(c, session="s1", limit=10)),
        ("A03", "timeline(缺省跨会话)", fx.big, lambda c: stg.timeline(c, limit=10)),
        ("A04", "timeline(session=\"*\")", fx.big,
         lambda c: stg.timeline(c, session="*", limit=10)),
        ("A05", "timeline(不存在的会话)", fx.big,
         lambda c: stg.timeline(c, session="no-such", limit=10)),
        ("A06", "timeline(截断 max_scan=7)", fx.big,
         lambda c: stg.timeline(c, session="sess_target", max_scan=7, limit=5)),
        ("A07", "timeline(asc)", fx.big,
         lambda c: stg.timeline(c, session="sess_target", limit=5, desc=False)),
        ("A08", "timeline(limit=0)", fx.big,
         lambda c: stg.timeline(c, session="sess_target", limit=0)),
        ("A09", "anchors(时间窗)", fx.big,
         lambda c: stg.anchors(c, time_window=[899950.0, 900050.0], limit=10)),
        ("A10", "anchors(时间窗+层)", fx.big,
         lambda c: stg.anchors(c, time_window=[899000.0, 900050.0],
                               layer="knowledge", limit=3)),
        ("A11", "anchors(时间窗·截断)", fx.big,
         lambda c: stg.anchors(c, time_window=[899000.0, 900050.0], max_scan=5,
                               limit=3)),
        ("A12", "consistency(全量)", fx.big, lambda c: stg.consistency(c, limit=10)),
        ("A13", "consistency(层)", fx.mixed,
         lambda c: stg.consistency(c, layer="knowledge", limit=20)),
        ("A14", "timeline(层·混库)", fx.mixed,
         lambda c: stg.timeline(c, layer="anchor", limit=20)),
        ("A15", "timeline(会话·混库·含无会话节点)", fx.mixed,
         lambda c: stg.timeline(c, session="sess_L", limit=20)),
        ("A16", "anchors(时间窗·混库·NaN/并列/仅窗)", fx.mixed,
         lambda c: stg.anchors(c, time_window=[1900.0, 3200.0], limit=20)),
        ("A17", "anchors(仅 bbox)", fx.mixed,
         lambda c: stg.anchors(c, bbox=[0, 0, 100, 100], limit=20)),
        ("A18", "旧快照库(回退读文件分支·会话)", fx.legacy,
         lambda c: stg.timeline(c, session="target-sess", limit=10)),
        ("A19", "旧快照库(回退分支·一致性)", fx.legacy,
         lambda c: stg.consistency(c, limit=10)),
        ("A20", "Secure(可见性面)", fx.secure, lambda c: stg.timeline(c, limit=10)),
        ("A21", "anchors(同刻并列窗 2950–2950)", fx.mixed,
         lambda c: stg.anchors(c, time_window=[2950.0, 2950.0], limit=20)),
    ]


# ---------------------------------------------------------------- G1 两臂等价
def g1_parity(fx):
    print("== G1 等价性：关/开两臂业务字段逐位一致 + 形态读数钉住 ==")
    for key, label, cg, fn in _cases(fx):
        off, on = _two_arm(cg, fn)
        ix = on.get("index") or {}
        shape = (ix.get("path"), ix.get("fallback"), on.get("count"),
                 on.get("scanned"), ix.get("index_hit"))
        ok(_biz(off) == _biz(on) and shape == _EXPECT[key],
           "G1 %s %s" % (key, label),
           {"biz_eq": _biz(off) == _biz(on), "shape": shape,
            "want": _EXPECT[key]})
    off, on = _two_arm(fx.big, lambda c: S.timeline(c, session="sess_target", limit=5))
    ok("index" not in off,
       "G1b 关臂不落 index 键（与第 1/2 层返回体逐位一致）", sorted(off))
    ok(on.get("scanned") == 120 and off.get("scanned") == 5320,
       "G1c 开臂遍历面收敛（120 < 全量 5320）",
       (on.get("scanned"), off.get("scanned")))


# ---------------------------------------------------------------- G2 维护不变量
def g2_invariants(fx):
    print("== G2 索引维护：写/删/迁移/rebuild/compact/flush 后表与快照一致 ==")
    cg = fx.scratch()
    for i in range(11):
        _add(cg, "m%02d" % i, i, sess="s0" if i % 2 else None, t=1000.0 + i)
    cg.flush()
    seen = {"set": 0, "rem": 0}
    live_set, live_rem = _mdcg.MdCG._set_index_entry, _mdcg.MdCG._remove_index_entry

    def _spy_set(self, nid, entry):
        seen["set"] += 1
        return live_set(self, nid, entry)

    def _spy_rem(self, nid):
        seen["rem"] += 1
        return live_rem(self, nid)

    try:
        with _env(**{INDEX_ENV: "1"}), \
                contextlib.ExitStack() as _st:
            _st.enter_context(_patch_attr(_mdcg.MdCG, "_set_index_entry", _spy_set))
            _st.enter_context(_patch_attr(_mdcg.MdCG, "_remove_index_entry", _spy_rem))
            S.timeline(cg, limit=1)                   # 首次访问 ⇒ 惰性构建
            ix = cg._stg_index
            ok(ix is not None and ix.index_obj is cg.index
               and _verify(cg) == [],
               "G2a 首次 stg 访问惰性构建（挂在活快照上），三表恒为快照划分",
               _verify(cg))

            _add(cg, "new_zz", 99, sess="s0", t=5000.0)
            bad = _verify(cg)
            body = S.timeline(cg, session="s0", limit=50)
            ok(cg._stg_index is ix and not bad and seen["set"] >= 1,
               "G2b 写路径同钩增量增（经 _set_index_entry；表未整表重建且仍为划分）",
               (bad, seen))
            ok(_ids(body)[0] == "new_zz"
               and (body.get("index") or {}).get("path") == "index"
               and body.get("scanned") == 6,
               "G2c 增量增后的新节点在索引臂立即可见（子集=该会话 6 条）",
               (_ids(body)[:3], body.get("index"), body.get("scanned")))

            _add(cg, "m00", 0, layer="anchor", sess="sX", t=6000.0)   # 层+会话双迁移
            bad = _verify(cg)
            ok(not bad and _ids(S.timeline(cg, layer="anchor", limit=50)) == ["m00"]
               and "m00" not in _ids(S.timeline(cg, session="s0", limit=50)),
               "G2d 覆写（层迁移+会话改写）后 by_layer/by_session 同步搬桶", bad)

            cg._unstage("m01")
            bad = _verify(cg)
            ok(not bad and seen["rem"] >= 1
               and "m01" not in _ids(S.timeline(cg, limit=50))
               and len(ix.by_session.get("s0", [])) == 5,
               "G2e 删除路径同钩增量摘（经 _remove_index_entry，表仍为划分）", bad)

            cg.flush()
            ok(cg._stg_index is ix and _verify(cg) == [],
               "G2f flush 不动内存索引、不失效表（写读交替下不被反复重扫）",
               (cg._stg_index is ix, _verify(cg)))

            cg.rebuild_index()
            stale_rb = cg._stg_index
            S.timeline(cg, limit=1)
            ok(stale_rb is None and cg._stg_index is not None and _verify(cg) == [],
               "G2g rebuild_index 显式失效表并随后按新快照重建（划分不变量成立）",
               (stale_rb, _verify(cg)))

            cg.compact_index()
            stale_cp = cg._stg_index
            S.timeline(cg, limit=1)
            ok(stale_cp is None and _verify(cg) == [],
               "G2h compact_index 显式失效表并随后重建（划分不变量成立）",
               (stale_cp, _verify(cg)))

            off_a, on_a = _two_arm(cg, lambda c: S.timeline(c, session="s0", limit=50))
            off_b, on_b = _two_arm(cg, lambda c: S.timeline(c, layer="anchor", limit=50))
            ok(_biz(off_a) == _biz(on_a) and _biz(off_b) == _biz(on_b)
               and off_a["count"] == 6 and off_b["count"] == 1
               and (on_a.get("index") or {}).get("path") == "index",
               "G2i 一轮增删迁移+rebuild+compact 后仍走直取且两臂逐位等价",
               {"a": (off_a.get("count"), on_a.get("index")),
                "b": (off_b.get("count"), on_b.get("index"))})
    finally:
        assert (_mdcg.MdCG._set_index_entry is live_set
                and _mdcg.MdCG._remove_index_entry is live_rem)
    fx.drop(cg)


@contextlib.contextmanager
def _patch_attr(owner, attr, value):
    live = getattr(owner, attr)
    setattr(owner, attr, value)
    try:
        yield
    finally:
        setattr(owner, attr, live)


# ---------------------------------------------------------------- G3 unassigned
def g3_unassigned(fx):
    print("== G3 unassigned（无会话节点）语义保持现状 ==")
    cg = fx.mixed
    off_v, on_v = _two_arm(cg, lambda c: S.timeline(c, session="sess_L", limit=50))
    off_x, on_x = _two_arm(cg, lambda c: S.timeline(c, session="*", limit=50))
    with _env(**{INDEX_ENV: "1"}):
        S.timeline(cg, limit=1)
        bucket = sorted(cg._stg_index.by_session.get(None, []))
        fb = ((S.timeline(cg, limit=1).get("index") or {}).get("fallback"))
    ok(bucket == ["non_sess_0"]                       # None 桶归属
       and "non_sess_0" not in _ids(on_v)             # 具体会话视图不放大
       and "non_sess_0" not in _ids(off_v)
       and "non_sess_0" in _ids(on_x)                 # 跨会话视图可见
       and _biz(off_v) == _biz(on_v) and _biz(off_x) == _biz(on_x)
       and fb == "no_condition_dimension",            # 跨会话无维可索引 ⇒ 如实回退
       "G3 unassigned 四判据：None 桶归属 / 会话视图不放大 / 跨会话可见 / 如实回退",
       (bucket, _ids(on_v), fb))


# ---------------------------------------------------------------- G4 截断继承
def g4_truncation(fx):
    print("== G4 截断语义继承第 1/2 层 ==")
    off, on = _two_arm(fx.big,
                       lambda c: S.timeline(c, session="sess_target", max_scan=4,
                                            limit=3))
    sigs = [inspect.signature(f).parameters["max_scan"].default
            for f in (S.timeline, S.anchors, S.consistency)]
    ok(off.get("truncated") is True and on.get("truncated") is True
       and off.get("kept") == on.get("kept") == 4
       and off.get("hint") == on.get("hint") == on.get("hint")
       and _ids(off) == _ids(on) == ["zz_t119", "zz_t118", "zz_t117"]
       and off.get("count") == on.get("count") == 120
       and sigs == [5000, 5000, 5000],
       "G4 截断继承：truncated/kept/hint/近期优先/count + max_scan 默认 5000 不动",
       {"off": {k: off.get(k) for k in ("truncated", "kept", "count")},
        "on": {k: on.get(k) for k in ("truncated", "kept", "count")},
        "ids": _ids(on), "sigs": sigs})


# ---------------------------------------------------------------- G5 meta 可观测
def g5_meta(fx):
    print("== G5 可观测：回退 reason / 表规模 / 自愈 / 关臂不建表 ==")
    with _env(**{INDEX_ENV: "1"}):
        cg = fx.scratch("g5")
        for i in range(9):
            _add(cg, "x%02d" % i, i, sess="s0", t=1000.0 + i)
        for i in range(4):                      # 异会话填充：让 s0 成为**真子集**
            _add(cg, "y%02d" % i, i, sess="sX", t=500.0 + i)
        cg.flush()
        S.timeline(cg, limit=1)
        ix = cg._stg_index
        ents = list(cg.index["nodes"].values())
        want = {"nodes": len(ents),
                "sessions": len({e.get("session") for e in ents}),
                "layers": len({e.get("layer") for e in ents}),
                "timed": sum(1 for e in ents if _stgidx.time_of(e) is not None),
                "untimed": sum(1 for e in ents if _stgidx.time_of(e) is None),
                "nonfinite": 0}
        body = S.timeline(cg, session="s0", limit=1)
        ok(ix.size() == want and _verify(cg) == []
           and body["index"]["size"] == want
           and body["index"]["full_nodes"] == len(ents),
           "G5a 表规模读数 == 快照实况（size/full_nodes）且划分不变量成立",
           (ix.size(), want, _verify(cg), body.get("index")))

        # ① tables_missing：构建不可用
        cg._stg_index = None
        live_build = _stgidx.build
        _stgidx.build = lambda *a, **k: None
        try:
            b = S.timeline(cg, session="s0", limit=1)
        finally:
            _stgidx.build = live_build
        ok((b.get("index") or {}).get("fallback") == "tables_missing"
           and b["index"]["path"] == "full" and b["index"]["index_miss"] == 1,
           "G5b 表缺失 ⇒ 回退全量且 reason=tables_missing（禁止静默）",
           b.get("index"))

        # ② generation_mismatch：整体换过快照却没走失效点
        with _clean_env():
            base = S.timeline(cg, session="s0", limit=50)
        S.timeline(cg, session="s0", limit=1)          # 先构建
        live_index = cg.index
        cg.index = dict(live_index)                    # 身份变的同一内容快照
        try:
            b = S.timeline(cg, session="s0", limit=50)
            ok((b.get("index") or {}).get("fallback") == "generation_mismatch"
               and _biz(b) == _biz(base),
               "G5c 代际不符 ⇒ 本次回退全量（结果与基线一致）且 reason 在场",
               b.get("index"))
            ok(cg._stg_index is None,
               "G5d 代际不符当场丢弃陈旧表（下次访问自愈重建）", cg._stg_index)
            # 自愈判据必须在**换回快照之前**测：陈旧表若没被丢弃，本调用仍会
            # 判代际不符 ⇒ 永陷回退（这正是「不修复代」的形态）。
            b2 = S.timeline(cg, session="s0", limit=50)
            ok((b2.get("index") or {}).get("path") == "index"
               and _biz(b2) == _biz(base),
               "G5e 自愈：下一访问重建后回到索引臂且结果不变", b2.get("index"))
        finally:
            cg.index = live_index

        # ③ entry_file_read：迭代期旧快照条目（`_scan` 走回退读文件）
        S.timeline(cg, limit=1)
        cg.index["nodes"]["x00"].pop("temporal", None)
        cg.index["nodes"]["x00"].pop("spatial", None)
        try:
            b = S.timeline(cg, session="s0", limit=50)
            ok((b.get("index") or {}).get("fallback") == "entry_file_read",
               "G5f 旧快照条目（须读文件才知会话/时间）⇒ 回退且 reason 在场",
               b.get("index"))
        finally:
            cg.index["nodes"]["x00"]["temporal"] = None
            cg.index["nodes"]["x00"]["spatial"] = None
            cg._stg_index = None

        # ④⑤⑥ no_condition_dimension / inverted_query_window / time_axis_not_indexed
        b = S.timeline(cg, limit=1)                    # 跨会话且无层 ⇒ 无维可索引
        ok((b.get("index") or {}).get("fallback") == "no_condition_dimension",
           "G5g 无条件下可索引 ⇒ 回退且 reason=no_condition_dimension",
           b.get("index"))
        b = S.anchors(cg, time_window=[9000.0, 8000.0], limit=1)
        ok((b.get("index") or {}).get("fallback") == "inverted_query_window",
           "G5h 倒置查询窗 ⇒ 不索引时间维（预筛会漏 equals）且 reason 在场",
           b.get("index"))
        b = S.anchors(cg, time_window=[1000.0, 2000.0], time_axis="effective",
                      limit=1)
        ok((b.get("index") or {}).get("fallback") == "time_axis_not_indexed",
           "G5i 非观察轴 ⇒ 时间维不索引（表按观察轴建）且 reason 在场",
           b.get("index"))

        # 关臂：不构建、不落键
        cg2 = fx.scratch("g5_off")
        _add(cg2, "y0", 0, sess="s0", t=1.0)
        cg2.flush()
        with _clean_env():
            b = S.timeline(cg2, session="s0", limit=1)
            ok(cg2._stg_index is None and "index" not in b,
               "G5j flag 默认关：不构建表、不落 index 键（零成本默认面）",
               (cg2._stg_index, sorted(b)))
    fx.drop(cg)
    fx.drop(cg2)


# ---------------------------------------------------------------- G6 资格首验
def g6_qualification(fx):
    print("== G6 条件资格首验：只上报不过滤（read 面同口径） ==")
    cg = fx.mixed
    with _env(**{QUALIFY_ENV: None}):
        off = S.timeline(cg, session="sess_L", limit=50)
    with _env(**{QUALIFY_ENV: "1"}):
        on = S.timeline(cg, session="sess_L", limit=50)
    ok(all("qualification" not in it for it in off["items"])
       and all("qualification" in it for it in on["items"]),
       "G6a 开关面：关不带 qualification（默认面零变化）、开逐条带出",
       ([it.get("qualification") for it in off["items"]][:1],
        [it.get("qualification") for it in on["items"]][:1]))
    states = {it["id"]: (it.get("qualification") or {}).get("state")
              for it in on["items"]}
    ok(set(states.values()) <= {"ACCEPT", "REJECT", "DEFER", "BLINDSPOT"}
       and states.get("rej_0") == "REJECT",
       "G6b 资格态取自 read 面四态（含夹具设计的 REJECT 条目）", states)
    ok(_ids(off) == _ids(on) and off["count"] == on["count"]
       and "rej_0" in _ids(on),
       "G6c **只上报不过滤**：被打回条目仍在返回体里、条目集与关臂逐位一致",
       (states.get("rej_0"), _ids(off) == _ids(on)))
    stripped = [{k: v for k, v in it.items() if k != "qualification"}
                for it in on["items"]]
    ok(stripped == off["items"] and
       {k: v for k, v in on.items() if k != "items"} ==
       {k: v for k, v in off.items() if k != "items"},
       "G6d 摘掉 qualification 后返回体与关臂逐位一致（行为零变化）", None)
    from .mdcg import MdCG
    exp = {}
    for it in on["items"]:
        n = cg.get(it["id"])
        exp[it["id"]] = MdCG.judge_qualification(
            {"frontmatter": n["frontmatter"], "content": n["content"]}, "",
            {"stg": "timeline", "session": "sess_L", "layer": None,
             "time_axis": "observed"})
    got = {it["id"]: it.get("qualification") for it in on["items"]}
    ok(got == exp, "G6e 与 read 面单点 judge_qualification 逐条同口径（未另写判据）",
       {k: (got.get(k), exp.get(k)) for k in list(exp)[:2]})


# ---------------------------------------------------------------- G7 结构/单点
def g7_structure(fx):
    print("== G7 结构：资格判据唯一调用点 / _scan 无切片 ==")
    src = _CUR_SRC if _CUR_SRC is not None else inspect.getsource(_stg)
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "judge_qualification"]
    ok(len(calls) == 1,
       "G7a stg 侧 judge_qualification 恰一处调用（不另写第二套资格判据）",
       len(calls))
    fn = None
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == "_scan":
            fn = node
            break
    slices = [] if fn is None else [n for n in ast.walk(fn)
                                    if isinstance(n, ast.Subscript)
                                    and isinstance(n.slice, ast.Slice)]
    ok(fn is not None and not slices,
       "G7b _scan 内无切片子表达式（第 1/2 层条件先行红线不因索引化回退）",
       (fn is None, [getattr(s, "lineno", "?") for s in slices]))


_GROUPS = (g1_parity, g2_invariants, g3_unassigned, g4_truncation, g5_meta,
           g6_qualification, g7_structure)


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
# 每条 = (名字, 属主, 属性名, 旧源码, 新源码, 预期打红条数)。
# 锚点缺失 ⇒ ANCHOR-MISS + 退出码 2（fail-closed）；预期条数不符 ⇒ 报红（「恰好」语义）。
# 编号 ①–⑰ 由 `_table_gaps` 机械核对（防误删：删条目即报缺口）。
_SRC_MUTATIONS = (
    # ① 写路径不再增量维护 ⇒ 表与快照不一致（安全网随即回退，但 G2 组断言必红）
    ("①写钩增量维护摘除（表与快照不一致）", _mdcg.MdCG, "_set_index_entry",
     "        ix = getattr(self, \"_stg_index\", None)\n"
     "        if ix is not None:\n"
     "            ix.add(node_id, entry)\n",
     "", 3),

    # ② 删除路径不摘 ⇒ 已删条目留在表里（幽灵召回、划分不成立）
    ("②删除钩摘除（删后表与快照不一致）", _mdcg.MdCG, "_remove_index_entry",
     "        ix = getattr(self, \"_stg_index\", None)\n"
     "        if ix is not None:\n"
     "            ix.remove(node_id)\n",
     "", 2),

    # ③ 索引臂顺手加限额切片 ⇒ 第 1/2 层红线在索引面回退（G7b 的 AST 判据当场红）
    ("③索引臂加限额切片（条件先行红线回退）", _stg, "_scan",
     "        for nid, e in list(nodes):\n",
     "        for nid, e in list(nodes)[:5000]:\n", 1),

    # ④ 时间维取数不回排物理序 ⇒ 基线候选序无法复现（条目次序变）
    ("④取数序错（时间维不回排物理序）", _stgidx.StgIndex, "subset",
     "        if dims[0] == \"time\":\n"
     "            ids = sorted(ids, key=self.pos.__getitem__)\n",
     "        if False:\n"
     "            ids = sorted(ids, key=self.pos.__getitem__)\n", 3),

    # ⑤ unassigned 桶被混进具体会话视图（会话语义放大）——契约 §待签收点 4 红线
    ("⑤unassigned 桶混进具体会话视图", _stgidx.StgIndex, "subset",
     "            srcs.append(self.by_session.get(session, []))\n",
     "            srcs.append(list(self.by_session.get(session, []))\n"
     "                        + list(self.by_session.get(None, []) or []))\n", 9),

    # ⑥ 时间窗上界漏并列（hi 处同刻节点被排除）⇒ 边界命中漏召回（与基线不等价）
    ("⑥时间窗上界漏并列（边界命中漏召回）", _stgidx.StgIndex, "range_ids",
     "        while b < len(self.by_time) and self.by_time[b][0] == hi:\n"
     "            b += 1\n",
     "", 1),

    # ⑦ by_time 排序键错（乱序）⇒ 区间二分取不到该取的面
    ("⑦by_time 排序键错（乱序）", _stgidx.StgIndex, "_classify",
     "            bisect.insort(self.by_time, (t, nid))\n",
     "            bisect.insort(self.by_time, (-t, nid))\n", 8),

    # ⑧ 索引直取不收窄（子集=全量）⇒ 收敛读数失真（等价性判据的形态面必红）
    ("⑧索引直取不收窄（子集=全量）", _stg, "_index_pairs",
     "    pairs = []\n    for nid in ids:\n",
     "    pairs = []\n    for nid in list(nodes):\n", 14),

    # ⑨ 回退路径静默无 reason ⇒「表缺失/代际不符」不可区分（禁止静默）
    ("⑨回退路径静默无 reason", _stg, "_index_meta_full",
     "            \"index_miss\": want, \"fallback\": reason, \"full_nodes\": full,\n",
     "            \"index_miss\": want, \"fallback\": None, \"full_nodes\": full,\n", 14),

    # ⑩ 资格被当过滤生效（打回条目不入返回体）——契约 §3.4 红线
    ("⑩资格被当过滤生效（REJECT 条目被剔除）", _stg, "_attach_qualification",
     "    for it in items:\n"
     "        nid = it.get(\"id\")\n",
     "    _keep = []\n"
     "    for it in items:\n"
     "        _nd = _qual_node_dict(cg, it.get(\"id\"))\n"
     "        if _nd is not None and MdCG.judge_qualification(\n"
     "                _nd, query, context).get(\"state\") == \"REJECT\":\n"
     "            continue\n"
     "        _keep.append(it)\n"
     "    items = _keep\n"
     "    for it in items:\n"
     "        nid = it.get(\"id\")\n", 4),

    # ⑪ 资格上报面摘除（flag 开了也不带 qualification）
    ("⑪资格上报面摘除（flag 开也不带 qualification）", _stg, "_attach_qualification",
     "    if not items or not _flag_on(_QUALIFY_ENV):\n        return items\n",
     "    return items\n", 3),

    # ⑫ 默认关失效（关臂也建表/落 meta）——契约 §4「先 flag 化」红线
    ("⑫默认关失效（关臂也建表/落 meta）", _stg, "_index_pairs",
     "    if not _flag_on(_INDEX_ENV):\n        return None, None\n",
     "", 3),

    # ⑬ 代际不符不丢陈旧表 ⇒ 永久陷在回退（不修复代）
    ("⑬代际不符不丢陈旧表（永陷回退）", _stg, "_index_bundle",
     "            cg._stg_index = None\n"
     "            return None, \"generation_mismatch\"\n",
     "            return None, \"generation_mismatch\"\n", 2),

    # ⑭ rebuild/compact 不失效表（陈旧表被继续取数）
    ("⑭rebuild/compact 不失效表", _mdcg.MdCG, "_invalidate_stg_index",
     "        \"\"\"第 3 层结构索引的失效单点（整体换索引的三处编排点都调它）。\"\"\"\n"
     "        self._stg_index = None\n",
     "        \"\"\"第 3 层结构索引的失效单点（整体换索引的三处编排点都调它）。\"\"\"\n"
     "        pass\n", 1),

    # ⑯ 层维取数失效（by_layer 查不到即塌成空候选 ⇒ 层条件漏召回）
    ("⑯层维取数失效（候选面塌成空）", _stgidx.StgIndex, "subset",
     "            srcs.append(self.by_layer.get(layer, []))\n",
     "            srcs.append([])\n", 5),

    # ⑰ 分桶键取错字段（by_layer 按 session 建 ⇒ 划分键与条目口径不符）
    ("⑰分桶键取错字段（划分键与条目口径不符）", _stgidx.StgIndex, "_classify",
     "        self.by_layer.setdefault(layer, []).append(nid)\n",
     "        self.by_layer.setdefault(sid, []).append(nid)\n", 12),

    # ⑮ 截断选序回退为字典序 ⇒ 近期优先失效（第 1/2 层语义被改）
    ("⑮截断选序改回字典序（近期优先失效）", _stg, "_cap_hits",
     "    return sorted(hits, key=recency_key, reverse=True)[:cap], True\n",
     "    return sorted(hits, key=str)[:cap], True\n", 1),

)


#: 表内编号（`_table_gaps` 的判据面：编号无缺口 + 表长与声明一致）
_MUTATION_IDS = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
                 "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰")

_ANNOT_RE = re.compile(r"^    # ([①-⑳㉑-㉔])")


def _table_lines(text):
    """取 `_SRC_MUTATIONS = (` 到首个独立 `)` 行之间的表体行（当前工作区源）。"""
    out, on = [], False
    for line in text.split("\n"):
        if not on:
            if line.startswith("_SRC_MUTATIONS = ("):
                on = True
            continue
        if line.rstrip() == ")":
            break
        out.append(line)
    return out


def _table_gaps(text, entries_count, ids=_MUTATION_IDS):
    """变异表完整性判定（纯函数）：返回缺口说明列表（空 = 完好）。

    判据（先例 `test_autonomy_modes._table_gaps`）：
      a. 编号注释被下一**不同**编号覆盖（删元组留注释）⇒ 报该编号；
      b. 编号序列与声明不一致（缺/重复，含注释与元组同删）⇒ 报缺者；
      c. len(_SRC_MUTATIONS) ≠ 声明长度 ⇒ 报「len:n≠m」兜底。
    """
    annot, gaps, pending = [], [], None
    for line in _table_lines(text):
        m = _ANNOT_RE.match(line)
        if m:
            nid = m.group(1)
            if pending is None:
                pending = nid
                annot.append(nid)
            elif nid != pending:
                gaps.append(pending)
                pending = nid
                annot.append(nid)
            continue
        if pending is not None and line.startswith("    ("):
            pending = None
    if pending is not None:
        gaps.append(pending)
    for i in ids:
        if i not in annot:
            gaps.append(i)
        elif annot.count(i) > 1:
            gaps.append(i)
    if entries_count != len(ids):
        gaps.append("len:%d≠%d" % (entries_count, len(ids)))
    seen, uniq = set(), []
    for g in gaps:
        if g not in seen:
            seen.add(g)
            uniq.append(g)
    return uniq


def _table_integrity_check():
    with io.open(os.path.abspath(__file__), encoding="utf-8") as f:
        text = f.read()
    return _table_gaps(text, len(_SRC_MUTATIONS))


def _strip_indent(text, n):
    if not n:
        return text
    out = []
    for line in text.split("\n"):
        out.append(line[n:] if line[:n].strip() == "" else line.lstrip())
    return "\n".join(out)


def _selfcheck_judge() -> bool:
    """`_table_gaps` 自身的判别力自证（合成源，先例 `test_autonomy_modes` F1）。

    只验「删条目/缺口 ⇒ 机械报错」不是空转，不占表内编号：
      ① 删元组留注释（条目注释未被元组消费）⇒ 报该编号；
      ② 注释与元组同删 ⇒ 报缺失编号；
      ③ 表长与声明不符 ⇒ 报 len 兜底；
      ④ 真实表 ⇒ 无缺口（完好判据不误报）。
    """
    ids = ("①", "②", "③")
    # ① 删元组留注释：编号注释直接相邻 ⇒ 前一编号未被子元组消费
    drop_tuple = "x\n_SRC_MUTATIONS = (\n    # ①\n    # ③\n    (\n)\n"
    # ② 注释与元组同删：表体只剩元组行 ⇒ 三个编号全缺
    drop_both = "x\n_SRC_MUTATIONS = (\n    (\n)\n"
    with io.open(os.path.abspath(__file__), encoding="utf-8") as f:
        real = f.read()
    n_real = len(_SRC_MUTATIONS)
    return (_table_gaps(drop_tuple, 2, ids) == ["①", "②", "len:2≠3"]
            and _table_gaps(drop_both, 2, ids) == ["①", "②", "③", "len:2≠3"]
            and _table_gaps(real, n_real - 1) == ["len:%d≠%d" % (n_real - 1, n_real)]
            and _table_gaps(real, n_real) == [])


@contextlib.contextmanager
def _patched(owner, attr, old, new):
    """按字面替换变异目标函数并安装/还原（不落盘、不改源文件）。

    属主是模块（stg/stgidx）时在模块命名空间里 exec；是类时在**其模块**命名空间
    里 exec 后 setattr 到类上（本仓先例：`test_autonomy_modes._patched`）。
    """
    live = getattr(owner, attr)
    src = inspect.getsource(live)
    cut = len(src) - len(src.lstrip(" "))
    src2 = _strip_indent(src, cut)
    old2 = _strip_indent(old, cut)
    new2 = _strip_indent(new, cut)
    if old2 not in src2:
        raise AssertionError("ANCHOR-MISS:%s" % attr)
    if isinstance(owner, type):
        mod = sys.modules[owner.__module__]
        ns = dict(vars(mod))
        ns["__name__"] = mod.__name__
    else:
        ns = dict(vars(owner))
        ns["__name__"] = owner.__name__
    global _CUR_SRC
    mutated = src2.replace(old2, new2)
    exec(compile(mutated, "stgidx_mut.py", "exec"), ns)  # noqa: S102
    setattr(owner, attr, ns[attr])
    # 变异体源码留痕：G7 的 AST 判据（judge_qualification 调用点数 / _scan 无切片）
    # 必须读**当前生效的源码**，否则「模块文件未改但属性被换」的变异对它不可见。
    if owner is _stg and cut == 0:
        # 模块级函数：把变异体贴回**整模块源码**——G7 的 AST 判据解析的是模块
        # 源码，只给函数源码会让「判据只看函数体」的断言失真（③ 会连坐 G7a）。
        _CUR_SRC = inspect.getsource(_stg).replace(src, mutated)
    else:
        _CUR_SRC = None
    try:
        yield
    finally:
        setattr(owner, attr, live)
        _CUR_SRC = None


def _anchor_check():
    """全部变异锚点在**运行时源码**上在位（缺一即 ANCHOR-MISS）。"""
    bad = []
    for name, owner, attr, old, _new, _n in _SRC_MUTATIONS:
        live = getattr(owner, attr, None)
        if live is None:
            bad.append("变异目标缺失：%s.%s" % (getattr(owner, "__name__", owner),
                                            attr))
            continue
        src = inspect.getsource(live)
        cut = len(src) - len(src.lstrip(" "))
        if _strip_indent(old, cut) not in _strip_indent(src, cut):
            bad.append("变异锚点漂移：%s.%s ← %r"
                       % (getattr(owner, "__name__", owner), attr, old[:32]))
    return bad


def _branch_baseline(fx) -> int:
    print("!! 定点变异自证：逐处变异，断言须**恰好**打红预期条数；锚点漂移=ANCHOR-MISS+退出码 2\n")
    if not _selfcheck_judge():
        print("  防误删自检**自身**判别力不足（合成源未按预期报缺口）⇒ FAIL（fail-closed）")
        return 2
    gap_bad = _table_integrity_check()
    anchor_bad = _anchor_check()
    if gap_bad or anchor_bad:
        for g in gap_bad:
            print("  变异表缺口：" + g)
        for a in anchor_bad:
            print("  ANCHOR-MISS " + a)
        print("\n锚点/表完整性自检：FAIL（fail-closed）")
        return 2
    with _quiet():
        clean_red = _run_groups(fx)
    all_labels = set(_PASS) | set(_FAIL)
    if clean_red:
        print("  未变异基线即失败：%s" % clean_red)
        return 1
    print("  未变异基线：%d 条断言全绿（表内 %d 处变异，编号 %s–%s）"
          % (len(all_labels), len(_SRC_MUTATIONS), _MUTATION_IDS[0],
             _MUTATION_IDS[-1]))
    reddened = set()
    bad = []
    for name, owner, attr, old, new, expect in _SRC_MUTATIONS:
        try:
            with _quiet(), _patched(owner, attr, old, new):
                reds = _run_groups(fx)
        except AssertionError as e:
            print("  ANCHOR-MISS %s ← %s" % (name, e))
            return 2
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
    print("\n判别力自证：%s" % ("PASS（十七处变异各自恰好命中，且无空转断言）"
                              if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    fx = _Fixtures()
    try:
        if "--branch-baseline" in sys.argv:
            return _branch_baseline(fx)
        _run_groups(fx)
    finally:
        fx.close()
    print("\nstgidx 守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
