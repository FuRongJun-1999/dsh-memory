# -*- coding: utf-8 -*-
r"""t14a 守卫 · 保留规则第一块（md_cg/retain.py）—— 判定 + 只读盘点。

钉住两件事，二者互相独立，缺一条这个模块就不可信：

**A 判定语义**（G1–G5）：`retain_verdict` 对每一种节点形态给出**唯一且可读**
的结论，且 not-retained 的两种成因（判据没过 / 节点取不到）必须可分。
    G1 access_count=5（≥keep=3）        ⇒ retained=True 且 why 含 'access_count'
    G2 access_count=0 且 importance 低  ⇒ retained=False 且 why 可读（两条原因都在）
    G3 importance=0.9（access_count=0） ⇒ retained=True 且 why 含 '保护'
    G4 protected=true（access_count=0） ⇒ retained=True
    G5 get 取不到的 id                  ⇒ retained=False 且 why=='node_not_found'

**B 只读与可配**（G6–G8）：盘点面不改盘面，阈值来自策略而非硬编码。
    G6 retain_scan 跑前后**全库文件列表 + mtime 逐位一致**（零写盘）
    G7 临时策略文件把 keep_access_count 改成 1 ⇒ access_count=1 即 retained
    G8 env MDCG_LIFECYCLE_FILE 指向第三方文件 ⇒ policy_source=='env'

## 判据为何不恒真（反例守卫）
- G1/G2 必须**成对**在场：只测「高 access_count 留」的话，一个恒返回
  retained=True 的桩函数能全过；只测「低 access_count 不留」的话，恒 False
  的桩也能过。两个方向都断言才排得掉常量蒙混。
- G3 与 G1 的分界是**同一条线两侧**：G3 的节点 access_count=0（走不到第一条
  判据），importance=0.9（越过 protected_importance=0.7）——若实现把
  「达线」写成 `>` 而非 `>=`，G3 会红。G3 因此同时钉住了比较符方向。
- G6 的零写盘必须查**文件列表 + mtime**：只比内容哈希抓不到「原地重写同样
  内容」的写（那仍是一次写盘，且会把 mtime 推新、影响下游按 mtime 的判据）。
- G7 若不临时改阈值，「access_count=1 即 retained」这条断言在默认 keep=3 下
  恒假、根本判不了——阈值可配这条只能靠**真造一个策略文件**取证。
- G8 的 env 工况必须让包内默认文件**同时在场且取值不同**，否则「读到 env」
  与「回落到包内默认」两种解释在结果上同形。

## RETAIN_FLOOR_IMPORTANCE 与 sink 保护线的**分离**（G9）
0.35 是 retained 的**下限地板**、0.70 是 sink 跳过全部处置的**保护闸门**。
两者若被实现混同，会在 [0.35, 0.70) 区间产生「既不算保留、也不受保护」的
节点——盘点里凭空蒸发。G9 直接钉住常量取值与它**不等于** sink 的保护线。

沙箱注记：本套不起子进程，与 CreatePipe 禁令无涉；全部临时目录建在系统
临时区，用后 `rmtree` 回收，不读不写任何真实数据根。

运行：python D:\wook\lingshu-src\md_cg\test_t14a_retain_verdict.py
退出码：0 全绿 ／ 1 有失败项
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import retain as _retain          # noqa: E402
from md_cg import sink as _sink              # noqa: E402
from md_cg.mdcg import MdCG                  # noqa: E402

#: 本套全部断言沿用 unittest 的 self.assert*；下面的工具函数只负责**造夹具**。
#: 环境变量名从 sink 取（不在本文件里写第二遍字面量——两处写必然漂移）。
LIFECYCLE_ENV = _sink.SINK_ENV


# 生效条件：恒返回一个新造的临时目录绝对路径（调用方负责 rmtree）；前缀便于
# 排查时一眼看出是 t14a 的残留。
def _mk_tmp(prefix="t14a_retain_"):
    return tempfile.mkdtemp(prefix=prefix)


# 生效条件：传入已建的 cg（MdCG 实例）、节点 id、正文与 fm 覆盖键时，先 cg.add
# 建节点，再把覆盖键逐个写进该节点 frontmatter 并经 cg._write_node 落盘，最后
# cg.rebuild_index() 使内存索引与盘面一致；返回该节点 id。走的是引擎唯一正路
# （_write_node + rebuild_index），不自己拼文件、不手改 _index.json。
def _make_node(cg, nid, content, access_count=None, importance=None,
               protected=None, layer="knowledge"):
    """造一个带指定 frontmatter 的**真实落盘**节点（临时库内）。"""
    cg.add(nid, content, layer=layer)
    node = cg.get(nid)
    fm = node["frontmatter"]
    if access_count is not None:
        fm["access_count"] = access_count
    if importance is not None:
        fm["importance"] = importance
    if protected is not None:
        fm["protected"] = protected
    path = os.path.join(cg.root, (cg.index.get("nodes") or {}).get(nid, {})
                        .get("path") or "%s.md" % nid)
    cg._write_node(nid, path, fm, node.get("content") or "")
    cg.rebuild_index()
    return nid


# 生效条件：os.walk 遍历 root 下**所有**文件（不限后缀——写盘可能落在任意
# 辅助文件上），返回 {相对路径（/ 分隔）: mtime_ns} 的全量映射；mtime 用
# st_mtime_ns 取整型纳秒，避免浮点比较的精度噪声把「没变」误判成「变了」。
def _tree_mtimes(root):
    """影子根盘面指纹：全库文件列表 + 每个文件的 mtime（纳秒）。"""
    out = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root).replace("\\", "/")
            try:
                out[rel] = os.stat(fp).st_mtime_ns
            except OSError as exc:                       # 读不到也如实记，不静默跳过
                out[rel] = "stat_error:%s" % type(exc).__name__
    return out


# 生效条件：恒返回 (文件列表 dict 的键集合, 两个 mtime dict 的差异 dict)——
# 断言失败时用它打印可读证据，直接看出「哪个文件出现了/消失了/时间变了」。
def _tree_diff(before, after):
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = {k: (before[k], after[k]) for k in set(before) & set(after)
               if before[k] != after[k]}
    return added, removed, changed


# 生效条件：在 tmp 下写入一份合法生命周期策略 JSON（只写调用方点名要覆盖的键，
# 其余键留空由 sink 回落内置默认），返回该文件绝对路径；不设 env、不改全局状态。
def _write_policy(tmp, name="policy.json", **overrides):
    """造一份**临时策略文件**（只覆盖点名的键）。"""
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(overrides, f)
    return path


# 生效条件：以「env 未设」为前提调 fn()；进入时清掉 LIFECYCLE_ENV 并在退出时
# 恢复原值（即使 fn 抛异常也恢复）；恒返回 fn 的返回值。
def _without_env(fn):
    """在**不设** MDCG_LIFECYCLE_FILE 的前提下跑 fn（退出时恢复）。"""
    with mock.patch.dict(os.environ, {}, clear=False):
        saved = os.environ.pop(LIFECYCLE_ENV, None)
        try:
            return fn()
        finally:
            if saved is not None:
                os.environ[LIFECYCLE_ENV] = saved


class RetainVerdictTest(unittest.TestCase):
    """A 组：retain_verdict 的判定语义（G1–G5）。"""

    def setUp(self):
        self.tmp = _mk_tmp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cg = MdCG(root=os.path.join(self.tmp, "lib"))

    # G1：access_count ≥ keep_access_count ⇒ retained=True 且 why 含 'access_count'。
    def test_g1_access_count_at_threshold_is_retained(self):
        nid = _make_node(self.cg, "acc5", "用过五次的节点", access_count=5)
        got = _without_env(lambda: _retain.retain_verdict(self.cg, nid))
        self.assertTrue(got["retained"], "access_count=5 ≥ keep=3 应判 retained：%r" % (got,))
        self.assertIn("access_count", got["why"], "why 须含判据关键字：%r" % (got,))
        # 反例方向：同一函数对**没过线**的节点必须给 False，否则本断言
        # 对一个恒 True 的桩函数也成立（G2 是它的对照，此处再钉一次邻近值）。
        below = _make_node(self.cg, "acc2", "只用过两次", access_count=2,
                           importance=0.1)
        got_below = _without_env(lambda: _retain.retain_verdict(self.cg, below))
        self.assertFalse(got_below["retained"],
                         "access_count=2 < keep=3 且不受保护，不应判 retained：%r"
                         % (got_below,))

    # G2：access_count=0 且不受保护 ⇒ retained=False 且 why 可读（两条原因都在）。
    def test_g2_low_access_is_not_retained_with_readable_why(self):
        nid = _make_node(self.cg, "acc0", "没被用过", access_count=0,
                         importance=0.1)
        got = _without_env(lambda: _retain.retain_verdict(self.cg, nid))
        self.assertFalse(got["retained"], "不该判 retained：%r" % (got,))
        why = got["why"]
        self.assertTrue(why and why.strip(), "why 不得为空：%r" % (got,))
        self.assertNotEqual(why, "node_not_found",
                            "节点在场，不得报 not_found：%r" % (got,))
        # 逐条原因：两条都要在场（只写一条等于没有归因）。
        self.assertIn("access_count", why, "why 须给出 access_count 原因：%r" % (why,))
        self.assertIn("未受保护", why, "why 须给出未受保护原因：%r" % (why,))

    # G3：importance=0.9 且 access_count=0 ⇒ retained=True 且 why 含 '保护'。
    def test_g3_high_importance_is_retained(self):
        nid = _make_node(self.cg, "imp9", "很重要但没被用过", access_count=0,
                         importance=0.9)
        got = _without_env(lambda: _retain.retain_verdict(self.cg, nid))
        self.assertTrue(got["retained"],
                        "importance=0.9 ≥ protected_importance=0.7 应判 retained：%r"
                        % (got,))
        self.assertIn("保护", got["why"], "why 须含 '保护'：%r" % (got,))
        # 比较符方向：恰好等于保护线也必须算「达线」（>= 而非 >）。
        edge = _make_node(self.cg, "imp7", "恰好在线上", access_count=0,
                          importance=0.7)
        got_edge = _without_env(lambda: _retain.retain_verdict(self.cg, edge))
        self.assertTrue(got_edge["retained"],
                        "importance 恰等于保护线应算达线（>=）：%r" % (got_edge,))

    # G4：protected=true 且 access_count=0 ⇒ retained=True（importance 保持低位，
    # 确保留下的是 protected 位而不是重要性）。
    def test_g4_protected_flag_is_retained(self):
        nid = _make_node(self.cg, "prot", "被打了保护位", access_count=0,
                         importance=0.05, protected=True)
        got = _without_env(lambda: _retain.retain_verdict(self.cg, nid))
        self.assertTrue(got["retained"], "protected=true 应判 retained：%r" % (got,))
        self.assertIn("保护", got["why"], "why 须含 '保护'：%r" % (got,))
        # 反例方向：同一 importance=0.05、只是不设 protected，必须不 retained
        # ——两条一起才排得掉「importance 才是原因」的解释。
        plain = _make_node(self.cg, "plain", "没保护位", access_count=0,
                           importance=0.05)
        got_plain = _without_env(lambda: _retain.retain_verdict(self.cg, plain))
        self.assertFalse(got_plain["retained"],
                         "同一 importance 但不设 protected 位应不 retained：%r"
                         % (got_plain,))

    # G5：cg.get 取不到的 id ⇒ retained=False 且 why=='node_not_found'。
    def test_g5_missing_node_reports_node_not_found(self):
        got = _without_env(lambda: _retain.retain_verdict(self.cg, "no_such_id"))
        self.assertFalse(got["retained"], "取不到节点不得判 retained：%r" % (got,))
        self.assertEqual(got["why"], "node_not_found",
                         "缺失节点的 why 应是稳定的机器可读串：%r" % (got,))
        # 恒不抛异常：即便 cg.get 自己抛，也不得把异常漏给调用方。
        class BoomCg:
            root = self.tmp
            index = {"nodes": {}}

            def get(self, _nid, probe=True):
                raise RuntimeError("boom")

        got_boom = _without_env(lambda: _retain.retain_verdict(BoomCg(), "x"))
        self.assertFalse(got_boom["retained"],
                         "cg.get 抛异常时也必须返回 dict：%r" % (got_boom,))
        self.assertIn("node_not_found", got_boom["why"],
                      "读失败仍应归到 node_not_found 族：%r" % (got_boom,))


class RetainScanTest(unittest.TestCase):
    """B 组：只读盘点与阈值可配（G6–G8）。"""

    def setUp(self):
        self.tmp = _mk_tmp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cg = MdCG(root=os.path.join(self.tmp, "lib"))

    # G6：retain_scan 在影子根上只读——跑前后全库文件列表 + mtime 逐位一致。
    def test_g6_scan_is_read_only(self):
        _make_node(self.cg, "keep", "高频使用", access_count=5)
        _make_node(self.cg, "drop", "没人用", access_count=0, importance=0.1)
        _make_node(self.cg, "prot", "保护位", access_count=0, importance=0.05,
                   protected=True)

        before = _tree_mtimes(self.cg.root)
        out = _without_env(lambda: _retain.retain_scan(self.cg))
        after = _tree_mtimes(self.cg.root)

        added, removed, changed = _tree_diff(before, after)
        self.assertEqual(added, [], "retain_scan 不得新建文件：%r" % (added,))
        self.assertEqual(removed, [], "retain_scan 不得删除文件：%r" % (removed,))
        self.assertEqual(changed, {},
                         "retain_scan 不得改动任何文件（含 mtime）：%r" % (changed,))

        # 三组清单都要有内容，否则「零写盘」可能只是因为它什么都没干。
        self.assertEqual(sorted(r["id"] for r in out["retained"]),
                         ["keep", "prot"],
                         "retained 桶内容不符：%r" % (out["retained"],))
        self.assertEqual([r["id"] for r in out["not_retained"]], ["drop"],
                         "not_retained 桶内容不符：%r" % (out["not_retained"],))
        self.assertEqual([r["id"] for r in out["protected"]], ["prot"],
                         "protected 是正交标记，只装 protected 位为真的节点：%r"
                         % (out["protected"],))
        for rec in out["retained"] + out["not_retained"] + out["protected"]:
            for key in ("id", "access_count", "importance", "why"):
                self.assertIn(key, rec, "每条记录须含 %s：%r" % (key, rec))
        self.assertIn("policy_source", out, "返回体须带 policy_source：%r" % (out,))
        self.assertIn("t", out, "返回体须带基准时间 t：%r" % (out,))

    # G6b：空库上跑也不许造文件（最容易被忽略的一条路径）。
    def test_g6b_scan_on_empty_library_is_read_only(self):
        before = _tree_mtimes(self.cg.root)
        out = _without_env(lambda: _retain.retain_scan(self.cg))
        after = _tree_mtimes(self.cg.root)
        self.assertEqual(before, after, "空库上 retain_scan 也不得动盘面")
        self.assertEqual(out["retained"], [])
        self.assertEqual(out["not_retained"], [])
        self.assertEqual(out["protected"], [])

    # G7：临时策略文件覆盖 keep_access_count=1 ⇒ access_count=1 即 retained。
    def test_g7_policy_file_overrides_threshold(self):
        nid = _make_node(self.cg, "acc1", "只用过一次", access_count=1,
                         importance=0.1)
        # 先在**默认**策略下取证：keep=3 时这条不该被 retain。
        base = _without_env(lambda: _retain.retain_verdict(self.cg, "acc1"))
        self.assertFalse(base["retained"],
                         "默认 keep_access_count=3 下 access_count=1 不应 retained：%r"
                         % (base,))
        # 再用临时策略把阈值压到 1：同一条节点必须翻成 retained。
        pol_path = _write_policy(self.tmp, "keep1.json", keep_access_count=1)
        got = _without_env(
            lambda: _retain.retain_verdict(self.cg, nid, policy=_sink.load_policy(pol_path)))
        self.assertTrue(got["retained"],
                        "keep_access_count=1 时 access_count=1 应 retained：%r" % (got,))
        self.assertEqual(got["policy_source"], "arg",
                         "显式传策略文件应记为 arg 来源：%r" % (got,))
        # 盘点面同一条阈值也要生效（判定与盘点共用策略，不得各读一份）。
        scanned = _without_env(
            lambda: _retain.retain_scan(
                self.cg, policy=_sink.load_policy(pol_path)))
        self.assertEqual([r["id"] for r in scanned["retained"]], [nid],
                         "盘点面未使用同一份策略：%r" % (scanned["retained"],))

    # G8：env MDCG_LIFECYCLE_FILE 指向第三方文件 ⇒ policy_source=='env'，
    # 且生效值确实来自该文件（不是回落到包内默认的同值巧合）。
    def test_g8_env_policy_source_is_env(self):
        nid = _make_node(self.cg, "envnode", "env 工况", access_count=1,
                         importance=0.1)
        third = _write_policy(self.tmp, "third_party.json", keep_access_count=1)
        with mock.patch.dict(os.environ, {LIFECYCLE_ENV: third}):
            got = _retain.retain_verdict(self.cg, nid)
            scanned = _retain.retain_scan(self.cg)
        self.assertEqual(got["policy_source"], "env",
                         "env 指第三方文件时 policy_source 应为 'env'：%r" % (got,))
        self.assertTrue(got["retained"],
                        "生效值须真来自 env 文件（keep=1 ⇒ access_count=1 保留）：%r"
                        % (got,))
        self.assertEqual(scanned["policy_source"], "env",
                         "盘点面也要如实标来源：%r" % (scanned.get("policy_source"),))
        # 反例方向：去掉 env 后同一条必须变回 not-retained——否则「读到 env」
        # 与「碰巧本来就保留」在结果上同形，本断言就判不了来源。
        back = _without_env(lambda: _retain.retain_verdict(self.cg, "envnode"))
        self.assertFalse(back["retained"],
                         "撤掉 env 后应回到默认阈值（不 retained）：%r" % (back,))
        self.assertNotEqual(back["policy_source"], "env",
                            "撤掉 env 后不得再报 'env'：%r" % (back,))


class RetainFloorSeparateTest(unittest.TestCase):
    """G9：RETAIN_FLOOR_IMPORTANCE=0.35 与 sink 的保护线必须**分离**。"""

    # G9：常量取值正确，且**不等于** sink 的 protected_importance——
    # 两者混同会在 [0.35, 0.70) 区间造出「既不留也不受保护」的蒸发节点。
    def test_g9_floor_is_separate_from_protect_line(self):
        self.assertEqual(_retain.RETAIN_FLOOR_IMPORTANCE, 0.35,
                         "retained 的重要性下限应为 0.35")
        self.assertIsInstance(_retain.RETAIN_FLOOR_IMPORTANCE, float,
                              "应为浮点常量，便于与 importance 直接比较")
        sink_line = _sink.BUILTIN_DEFAULTS["protected_importance"]
        self.assertEqual(sink_line, 0.7, "sink 保护线基线应为 0.70")
        self.assertNotEqual(_retain.RETAIN_FLOOR_IMPORTANCE, sink_line,
                            "0.35 是保留下限、0.70 是保护闸门，两者不得混同")
        # 边界语义：恰在 0.35 上的节点**不是**被这条线 retain 的——retain 的
        # 第二判据用的是 sink 的保护线（0.70），0.35 只是可读的地板口径。
        tmp = _mk_tmp()
        self.addCleanup(shutil.rmtree, tmp, True)
        cg = MdCG(root=os.path.join(tmp, "lib"))
        nid = _make_node(cg, "floor", "恰好在地板上", access_count=0,
                         importance=_retain.RETAIN_FLOOR_IMPORTANCE)
        got = _without_env(lambda: _retain.retain_verdict(cg, nid))
        self.assertFalse(got["retained"],
                         "0.35 不是保护线，处在该值的节点不应因它被 retain：%r"
                         % (got,))


# 生效条件：unittest 入口——发现本模块全部用例并运行，退出码由 unittest
# 决定（0 全绿 / 1 有失败或错误）。
if __name__ == "__main__":
    unittest.main(verbosity=2)
