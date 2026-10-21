# -*- coding: utf-8 -*-
"""narrow() 各退化出口必须如实暴露首建 / 部分重建成本。

历史取证：r19 复核发现 no_tokens / empty_converge 吞掉 reach_build_docs；
r32 发现 index_unavailable 连部分读盘成本也丢了、且旧测试用 sem=True 使 set(True)
异常被吞掉；r34 发现只计「已入倒排」会漏计「读了很多但都不可读」的情形、且模块级状态不安全。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import reach  # noqa: E402


class StubIdx:
    hash_complete = True
    sem = []          # 必须是真容器：曾写 sem=True，set(True) 报错被吞掉 → 语义分支未真实验证（r32 复核）
    built_now = True
    built_docs = 7
    built_reads = 9
    hashes = {}
    built_at = 0.0

    def postings(self, toks):
        return {"x"}


class ReadStubCG:
    """按 plan 依次返回 cg._read 结果，plan 耗尽后抛错（模拟重建中途失败）。"""

    def __init__(self, root, nodes, plan):
        self.root = root
        self.index = {"nodes": nodes}
        self._plan = list(plan)
        self.calls = 0

    def _read(self, entry):
        self.calls += 1
        if not self._plan:
            raise RuntimeError("simulated rebuild failure")
        return self._plan.pop(0)

    def _open_content(self, nid, fm, c):
        return c


def _tmp_root():
    return tempfile.mkdtemp(prefix="reach_meta_exits_")


def _use(path):
    os.environ["MDCG_REACH_INDEX"] = os.path.join(path, "_reach_index.json")


def main():
    os.environ["MDCG_REACH"] = "1"
    import md_cg.mdcg as mdcg_mod
    orig_with, orig_sem = reach._index_with_meta, mdcg_mod.semantic_on
    mdcg_mod.semantic_on = lambda: True
    reach._index_with_meta = lambda cg, force=False: (StubIdx(), {})
    try:
        # ① 无 token → no_tokens，必须带首建成本
        _, m1 = reach.narrow(object(), [], [], set(), q="")
        assert m1.get("reach") == "no_tokens", m1
        assert m1.get("reach_build_docs") == 7, "no_tokens 出口漏首建成本：%r" % (m1,)
        # ② 语义空收敛 → empty_converge，同样必须带首建成本
        _, m2 = reach.narrow(object(), [], ["甲乙"], {"甲", "乙"}, q="甲乙")
        assert m2.get("reach") == "empty_converge", m2
        assert m2.get("reach_build_docs") == 7, "empty_converge 出口漏首建成本：%r" % (m2,)

        # ③ 未重建时不得虚构成本
        class Cold(StubIdx):
            built_now = False

        reach._index_with_meta = lambda cg, force=False: (Cold(), {})
        _, m3 = reach.narrow(object(), [], [], set(), q="")
        assert "reach_build_docs" not in m3 and "reach_build_reads" not in m3, m3

        # ④ 语义分支确实生效：sem 为真容器时，无词面命中的语义节点也必须入池
        class SemIdx(StubIdx):
            sem = ["p/sem"]

        reach._index_with_meta = lambda cg, force=False: (SemIdx(), {})
        got4, m4 = reach.narrow(object(), [{"path": "p/sem"}], ["甲乙"], {"甲", "乙"}, q="甲乙")
        assert m4.get("reach") == "converged", m4
        assert [e["path"] for e in got4] == ["p/sem"], "sem 分支未真实生效：%r" % (got4,)

        # ⑤ fresh_overflow：未索引节点超上限 → 整段回退，且同时暴露 reach_fresh_nodes 与首建成本
        reach._index_with_meta = lambda cg, force=False: (StubIdx(), {})
        many = [{"path": "x"}] + [{"path": "p/f%04d" % i} for i in range(reach._FRESH_MAX + 1)]
        got5, m5 = reach.narrow(object(), many, ["甲乙"], {"甲", "乙"}, q="甲乙")
        assert got5 is None and m5.get("reach") == "fresh_overflow", m5
        assert m5.get("reach_fresh_nodes") == reach._FRESH_MAX + 1, m5
        assert m5.get("reach_build_docs") == 7, "fresh_overflow 出口漏首建成本：%r" % (m5,)

        # ⑥ r34 反例：读了很多节点但都不可读（None）后失败 → 已读盘量必须如实计数
        reach._index_with_meta = orig_with
        r1 = _tmp_root()
        _use(r1)
        cg_a = ReadStubCG(r1, {"a": {"path": "pa"}, "b": {"path": "pb"}, "c": {"path": "pc"}},
                          [(None, None), (None, None)])
        idx_a, fail_a = reach._index_with_meta(cg_a)
        assert idx_a is None, idx_a
        assert fail_a.get("reach_build_reads") == 2, "不可读读盘未计数：%r" % (fail_a,)
        assert fail_a.get("reach_build_docs") == 0 and fail_a.get("reach_build_partial") is True, fail_a
        # 端到端：narrow 的 index_unavailable 出口也必须带这些字段
        # （每次调用各自独立：本例用**新** stub 与新根，否则上一次调用已把 plan 耗尽）
        r4 = _tmp_root()
        _use(r4)
        cg_a2 = ReadStubCG(r4, {"a": {"path": "pa"}, "b": {"path": "pb"}, "c": {"path": "pc"}},
                           [(None, None), (None, None)])
        got6, m6 = reach.narrow(cg_a2, [], ["甲乙"], {"甲", "乙"}, q="甲乙")
        assert got6 is None and m6.get("reach") == "index_unavailable", m6
        assert m6.get("reach_build_reads") == 2 and m6.get("reach_build_partial") is True, m6

        # ⑦ 部分成功：第一个节点已入倒排后失败 → docs 与 reads 都要如实
        r2 = _tmp_root()
        _use(r2)
        cg_b = ReadStubCG(r2, {"a": {"path": "pa"}, "b": {"path": "pb"}}, [({"id": "a"}, "hello")])
        idx_b, fail_b = reach._index_with_meta(cg_b)
        assert idx_b is None, idx_b
        assert fail_b.get("reach_build_docs") == 1 and fail_b.get("reach_build_reads") == 1, fail_b
        assert fail_b.get("reach_build_partial") is True, fail_b

        # ⑧ 成功路径：无 fail 元数据；首建成本同时暴露读盘数与入索引数（各调用各自独立容器）
        r3 = _tmp_root()
        _use(r3)
        cg_c = ReadStubCG(r3, {"a": {"path": "pa", "content_hash": "h"}}, [({"id": "a"}, "hello")])
        idx_c, fail_c = reach._index_with_meta(cg_c)
        assert idx_c is not None and fail_c == {}, (idx_c, fail_c)
        bm = reach._build_meta(idx_c)
        assert bm.get("reach_build_docs") == 1 and bm.get("reach_build_reads") == 1, bm
        # 重复调用不得把上次成本带下来
        idx_d, fail_d = reach._index_with_meta(cg_c)
        assert fail_d == {}, fail_d
    finally:
        reach._index_with_meta, mdcg_mod.semantic_on = orig_with, orig_sem
        os.environ.pop("MDCG_REACH_INDEX", None)
    print("ALL PASS test_reach_meta_exits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
