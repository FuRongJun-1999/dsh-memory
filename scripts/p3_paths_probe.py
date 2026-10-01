# -*- coding: utf-8 -*-
"""P3 图检索路（因果 / 时间）**可复算探针**·同一命令在读改前树与改后树上都能跑。

用途（设计稿 §5.4 / §〇.3-15 的「把改动前的对照读数先落盘」）：把改前 commit
检出到独立 worktree，在两侧跑**完全相同**的本命令，逐位比对读数。

只使用**两侧都存在**的公开面（`MdCGOS.search_rrf` / `mcp_server._dispatch` /
`sleep.parse_window`），因此不需要为「改前树」改造任何东西——改后新增的
`MDCG_CHAIN_TYPES` / `MDCG_TEMPORAL_GAMMA` 在改前树上被忽略（正是要看的读数差）。

用法：
    python -X utf8 scripts/p3_paths_probe.py            # 人读 + JSON
    python -X utf8 scripts/p3_paths_probe.py --json     # 只打 JSON

退出码：0 = 探针跑完（读数不判绿红——绿红由守卫判）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import nodefile, sleep as S                    # noqa: E402
from md_cg.fsutil import atomic_write                     # noqa: E402
from md_cg.mdcos import MdCGOS                            # noqa: E402

#: 语料的时间基准（**固定相对量**，不依赖 wall clock → 两侧可逐位比对）
REF = 1_800_000_000.0
DAY = 86400.0

_BODY = ("# 功能名：{n}\n# 生效条件：无条件\n# 子功能：无\n"
         "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n{txt}\n")


def _mk(root, nid, txt, fm_extra=None):
    fm = {"id": nid, "layer": "knowledge", "created_at": REF, "tags": []}
    fm.update(fm_extra or {})
    d = os.path.join(root, "knowledge")
    os.makedirs(d, exist_ok=True)
    atomic_write(os.path.join(d, nid + ".md"),
                 nodefile.dumps(fm, _BODY.format(n=nid, txt=txt)))


def _chain_corpus(root):
    """doc_ref 型语料：**只有** reference 边 + 父章节结构边（无 causal）。"""
    _mk(root, "ch1", "苹果 章节一",
        {"edges": [{"target": "ch2", "relation_type": "reference",
                    "confidence": 0.6}],
         "subgraph": {"nodes": ["ch2"]}})
    _mk(root, "ch2", "第二章 内容")


def _rank_corpus(root):
    """含 causal 边的语料：验证「进默认检索后排序是否变、变了多少」。"""
    _mk(root, "u1", "苹果 上游条件",
        {"edges": [{"target": "d1", "relation_type": "causal",
                    "confidence": 0.9}]})
    _mk(root, "d1", "下游结论 葡萄")
    _mk(root, "x1", "苹果 无关旁支")
    _mk(root, "x2", "苹果 另一旁支")


def _time_corpus(root):
    _mk(root, "t0", "时刻 今天", {"created_at": REF,
                                  "effective_from": REF})
    _mk(root, "t7", "时刻 七天前", {"created_at": REF - 7 * DAY,
                                    "effective_from": REF - 7 * DAY})
    _mk(root, "t30", "时刻 三十天前", {"created_at": REF - 30 * DAY,
                                       "effective_from": REF - 30 * DAY})


def probe():
    tmp = tempfile.mkdtemp(prefix="p3_probe_")
    out = {"repo_head": None}
    try:
        # ── R1 缺省检索路集合（search_rrf 直调）──────────────────────────
        r1 = os.path.join(tmp, "r1")
        _rank_corpus(r1)
        cg = MdCGOS(r1)
        res, meta = cg.search_rrf("苹果", k=5, record=False)
        out["R1_search_rrf_默认路集"] = sorted((meta.get("paths") or {}).keys())
        out["R1_search_rrf_默认路候选数"] = meta.get("paths")
        out["R1_top5"] = [[n["id"], s] for n, s, _q, _p in
                          [(r[0], r[1], r[2], r[3]) for r in res]]
        out["R1_provenance"] = {k: sorted(p["path"] for p in v)
                                for k, v in (meta.get("provenance")
                                             or {}).items()}

        # ── R2 mcp_server 缺省调用点（mdcg_recall）──────────────────────
        from md_cg import mcp_server as MS
        pack = MS._dispatch(cg, "mdcg_recall", {"query": "苹果", "k": 5})
        pm = (pack.get("meta") or {})
        out["R2_recall_默认路集"] = sorted((pm.get("paths") or {}).keys())
        out["R2_recall_pack_ids"] = [it.get("id") for it in (pack.get("pack")
                                                             or [])]
        pack4 = MS._dispatch(cg, "mdcg_recall",
                             {"query": "苹果", "k": 5, "causal": False})
        out["R2b_recall_causal关闭路集"] = sorted(
            ((pack4.get("meta") or {}).get("paths") or {}).keys())
        cg.close()

        # ── R3 因果路在 doc_ref 语料上的候选数（默认集 vs 显式集）───────
        r3 = os.path.join(tmp, "r3")
        _chain_corpus(r3)
        env0 = os.environ.pop("MDCG_CHAIN_TYPES", None)
        try:
            c3 = MdCGOS(r3)
            _r, m3 = c3.search_rrf("苹果", k=5, record=False,
                                   paths=("lexical", "chain"))
            out["R3_chain_默认集_候选"] = (m3.get("paths") or {}).get("chain")
            c3.close()
            os.environ["MDCG_CHAIN_TYPES"] = "reference,part_of"
            c4 = MdCGOS(r3)
            r4, m4 = c4.search_rrf("苹果", k=5, record=False,
                                   paths=("lexical", "chain"))
            out["R3_chain_显式集_候选"] = (m4.get("paths") or {}).get("chain")
            out["R3_chain_显式集_top"] = [t[0]["id"] for t in r4]
            c4.close()
        finally:
            os.environ.pop("MDCG_CHAIN_TYPES", None)
            if env0 is not None:
                os.environ["MDCG_CHAIN_TYPES"] = env0

        # ── R4 时间路（固定窗口，索引标量）──────────────────────────────
        r4d = os.path.join(tmp, "r4")
        _time_corpus(r4d)
        c5 = MdCGOS(r5 := r4d)
        _r5, m5 = c5.search_rrf("时刻", k=5, record=False,
                                start_time=REF - 100 * DAY, end_time=REF)
        out["R4_temporal_候选"] = (m5.get("paths") or {}).get("temporal")
        out["R4_路集"] = sorted((m5.get("paths") or {}).keys())
        c5.close()

        # ── R5 睡眠窗口：非法形态的判定面 ───────────────────────────────
        out["R5_parse_window_乱写"] = S.parse_window("乱写")
        out["R5_in_window_乱写_12:00"] = S.in_window("乱写", "12:00")
        out["R5_in_window_乱写_03:00"] = S.in_window("乱写", "03:00")
        out["R5_in_window_留空_12:00"] = S.in_window("", "12:00")

        # ── R6 N137：搬迁前后边集合 ─────────────────────────────────────
        r6 = os.path.join(tmp, "r6")
        _mk(r6, "m1", "搬迁节点",
            {"edges": [{"target": "m2", "relation_type": "causal",
                        "confidence": 0.8}],
             "subgraph": {"nodes": ["m2"]}})
        _mk(r6, "m2", "下游")
        c6 = MdCGOS(r6)
        e0 = dict(c6.index["nodes"]["m1"])
        c6._move_layer("m1", "contextual", reason="probe")
        e1 = c6.index["nodes"]["m1"]
        out["R6_搬迁前_edges"] = len(e0.get("edges") or [])
        out["R6_搬迁后_edges"] = len(e1.get("edges") or [])
        out["R6_搬迁后_subgraph"] = e1.get("subgraph")
        out["R6_搬迁后_edges相等"] = ((e1.get("edges") or [])
                                      == (e0.get("edges") or []))
        c6.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = probe()
    print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
