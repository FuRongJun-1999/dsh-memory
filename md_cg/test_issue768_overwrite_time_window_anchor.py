# -*- coding: utf-8 -*-
# 功能名：覆写旧节点后默认 time_window 必须锚在**写入时刻**（issue #768）
# 生效条件：pytest md_cg/test_issue768_overwrite_time_window_anchor.py；被测面＝MdCG.add 的默认观测窗构造 + S2 时间门 _cond_prefilter_pass
# 子功能：G1＝同 id 覆写继承 created_at 时 time_window 右端仍 > now；G2＝覆写后带时间窗查询不被时间门剔除；G3＝调用方**显式**传 time_window 时逐字保留（负向对照，防放宽）
# 执行：每例建独立临时库，直接调库层 API，断言盘面 fm 而非回执
# 验证方式：断言通过即绿；把 mdcg.py 的锚点改回 created_at ⇒ G1/G2 必须变红
# 不适用条件：不判 created_at 是否继承（#766/#732 既有守卫已覆盖）；不判检索排序与打分
"""守卫：issue #768 —— 覆写继承 created_at 之后，默认 time_window 仍以它为锚。

根因：`MdCG.add` 里同一段代码先算 `created_at`（同 id 覆写时继承旧值，出生时间只写一次），
随后在调用方未传 `time_window` 时用 `[created_at, created_at + OBSERVATION_WINDOW_SEC]`
当默认观测窗。于是覆写一条旧节点 ⇒ 观测窗落在**过去**，配合 S2 时间门
（`_cond_prefilter_pass`：双方都有且区间不相交 ⇒ 剔除）⇒ 该节点在带时间窗的查询里永久消失。

本件只钉一件事：**默认观测窗的锚点必须是写入时刻**，不是（可能被继承的）created_at。
"""
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

os.environ.setdefault("MDCG_AUTONOMY", "full")

from md_cg.mdcos import MdCGOS                                   # noqa: E402
from md_cg.mdcg import _cond_prefilter_pass, OBSERVATION_WINDOW_SEC  # noqa: E402

_CCG_V1 = "\n".join([
    "# 功能名：768 守卫节点",
    "# 生效条件：本地临时库",
    "# 子功能：无",
    "# 执行：无",
    "# 验证方式：test",
    "# 不适用条件：无",
    "# 正文：第一版正文",
])
_CCG_V2 = _CCG_V1.replace("第一版正文", "第二版正文")

WEEK = 7 * 86400.0


def _fm(cg, nid):
    return (cg.get(nid) or {}).get("frontmatter") or {}


def _tw(cg, nid):
    return (_fm(cg, nid).get("condition_space") or {}).get("time_window")


def _fresh_cg(tag):
    root = tempfile.mkdtemp(prefix="iss768_%s_" % tag)
    return MdCGOS(root)


def test_overwrite_inherits_created_at_but_anchors_window_at_write_time():
    """G1：覆写旧节点 ⇒ created_at 继承旧值，time_window 右端必须 > 写入时刻。"""
    cg = _fresh_cg("g1")
    try:
        t0 = time.time() - WEEK
        cg.add("n1", _CCG_V1, layer="knowledge", importance=0.5, created_at=t0)
        created_first = _fm(cg, "n1").get("created_at")

        t_write = time.time()
        cg.add("n1", _CCG_V2, layer="knowledge", importance=0.5)

        fm2 = _fm(cg, "n1")
        tw = _tw(cg, "n1")

        # 前置：正文确实换成第二版（覆写真的发生了）
        assert "第二版" in ((cg.get("n1") or {}).get("content") or "")
        # 前置：#766 的契约仍成立——出生时间只写一次
        assert fm2.get("created_at") == created_first, (
            "created_at 应继承首写值，实得 %r vs %r" % (fm2.get("created_at"), created_first))
        assert isinstance(tw, (list, tuple)) and len(tw) == 2, "time_window 形状异常：%r" % (tw,)
        # 判据：默认观测窗锚在写入时刻（右端 > now）
        assert tw[1] > t_write, (
            "覆写后 time_window 右端 %.3f 未大于写入时刻 %.3f（差 %.1fs）——锚点仍是继承来的 created_at"
            % (tw[1], t_write, tw[1] - t_write))
        # 顺带：窗口长度仍是默认值（没有顺手改常量）
        assert abs((tw[1] - tw[0]) - OBSERVATION_WINDOW_SEC) < 1.0
    finally:
        cg.close()


def test_overwritten_old_node_survives_time_window_query():
    """G2：后果面——覆写后带时间窗的查询不得被 S2 时间门剔除。"""
    cg = _fresh_cg("g2")
    try:
        cg.add("n2", _CCG_V1, layer="knowledge", importance=0.5, created_at=time.time() - WEEK)
        t_write = time.time()
        cg.add("n2", _CCG_V2, layer="knowledge", importance=0.5)

        tw = _tw(cg, "n2")
        entry = {"time_window": tw, "condition_space": {"time_window": tw}}
        passed = _cond_prefilter_pass(entry, {"time_window": [t_write - 60, t_write + 60]})
        assert passed, (
            "被覆写过的旧节点在「现在 ±60s」的查询窗下被时间门剔除（time_window=%r）" % (tw,))
    finally:
        cg.close()


def test_explicit_time_window_is_preserved():
    """G3 负向对照：调用方显式给 time_window 时逐字保留，不得被默认锚覆盖。"""
    cg = _fresh_cg("g3")
    try:
        explicit = [time.time() - 7200, time.time() - 3600]
        cg.add("n3", _CCG_V1, layer="knowledge", importance=0.5, created_at=time.time() - WEEK,
               condition_space={"time_window": list(explicit)})
        got = _tw(cg, "n3")
        assert list(got) == explicit, "显式 time_window 被覆盖：期望 %r，实得 %r" % (explicit, got)
        cg.add("n3", _CCG_V2, layer="knowledge", importance=0.5,
               condition_space={"time_window": list(explicit)})
        got2 = _tw(cg, "n3")
        assert list(got2) == explicit, "覆写时显式 time_window 被覆盖：期望 %r，实得 %r" % (explicit, got2)
    finally:
        cg.close()


if __name__ == "__main__":
    _fails = 0
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            try:
                _f()
                print("  PASS " + _n)
            except AssertionError as _e:
                _fails += 1
                print("  FAIL " + _n + "  " + str(_e)[:240])
    print("FAILS %d" % _fails)
    sys.exit(1 if _fails else 0)
