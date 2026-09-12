# -*- coding: utf-8 -*-
"""bench6 · 六家横评统一评分（竞品侧结果与主进程臂合并出表）。

竞品四臂跑在各自 venv（外部评测工作区的 bench6 适配脚本），只回吐
`{qid: [id...]}`（顺序即相关性降序）；本模块读回后与主进程臂
（灵枢 5 个口径 + 纯向量 RAG，落在 `bench6_arms_result.json`）一起走
**同一个** `bc.rows_from_hits` → `ec.summarize`，保证六家同口径。

指标口径与主进程臂完全一致：`ec.unlock_global_cap()` + `ec.use_jaccard()`，
排名复用 `ec.first_evidence_rank`（要求 hits 里的 id 是池内真实 id）。

用法：
    python -m md_cg.bench6_competitors            # 读外部工作区 out 目录
    python -m md_cg.bench6_competitors --k 5
"""
from __future__ import annotations

import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg import bench6_common as bc      # noqa: E402
from md_cg import eval_common as ec        # noqa: E402

# 竞品臂运行目录：优先 BENCH6_COMPET；默认取与本仓库平级的外部评测工作区
COMPET = os.environ.get("BENCH6_COMPET") or os.path.join(os.path.dirname(HERE), "_competitor")
ARM_OUT = os.path.join(COMPET, "_eval", "bench6", "out")

# 竞品臂文件名 → 表内标签（顺序即主表顺序）
COMPETITOR_ARMS = [
    ("mem0", "mem0"),
    ("graphiti", "Graphiti"),
    ("graphrag", "GraphRAG"),
    ("letta_archival", "Letta·归档直插"),
    ("letta_agent", "Letta·agent自主"),
]

# 主进程臂 key → 表内标签（与 bench6_arms.main 的 table 键一致）
MAIN_ARMS = [
    ("lingshu_lex", "灵枢·单词法"),
    ("lingshu_rrf4", "灵枢·四路(真开bucket)"),
    ("lingshu_rrf4_noref", "灵枢·四路(名义)"),
    ("lingshu_lex_meta", "灵枢·词法+meta"),
    ("lingshu_rrf4_nometa", "灵枢·四路(无meta)"),
    ("vector_rag", "纯向量RAG"),
]

LANGS = ("zh", "en")


def _score_hits(questions, hits, k):
    rows = bc.rows_from_hits(questions, hits, k=k)
    return ec.summarize(rows, k=k), rows


def load_main(manifest_note):
    """读主进程臂结果（含灵枢 5 口径 + 向量基线）。"""
    path = os.path.join(ec.RESULTS, "bench6_arms_result.json")
    if not os.path.exists(path):
        print("[warn] 缺 %s：主进程臂未跑，主表将只有竞品" % path)
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("results") or {}


def load_competitor(arm, questions, k):
    path = os.path.join(ARM_OUT, "%s.json" % arm)
    if not os.path.exists(path):
        return None, "缺文件 %s（该臂未跑或跑失败）" % path
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {"raw_meta": {kk: raw.get(kk) for kk in
                        ("arm", "note", "pool_n", "questions_n", "ingest",
                         "n_episodes", "n_text_units", "index_rc",
                         "search_field_path", "ingest_probe")}}
    out["langs"] = {}
    for lang in LANGS:
        blk = (raw.get("langs") or {}).get(lang) or {}
        hits = blk.get("hits") or {}
        summary, rows = _score_hits(questions, hits, k)
        out["langs"][lang] = {
            "summary": summary, "rows": rows, "hits": hits,
            "n_unmapped": blk.get("n_unmapped"), "n_empty": blk.get("n_empty"),
            "unmapped_rate": blk.get("unmapped_rate"),
            "seconds": blk.get("seconds"),
        }
    out["errors"] = raw.get("errors") or []
    return out, None


def print_matrix(rows, k):
    """六家 × 两语言主表（hit@1 / hit@k / MRR）。"""
    head = ("系统", "zh hit@1", "zh hit@%d" % k, "zh MRR",
            "en hit@1", "en hit@%d" % k, "en MRR", "未回收率(zh/en)")
    w = [22, 9, 10, 8, 9, 10, 8, 16]
    line = "  ".join(h.ljust(wi) for h, wi in zip(head, w))
    print("\n" + line)
    print("-" * len(line))
    for label, r in rows:
        cells, ok = [label], all(r["langs"].get(l) for l in LANGS)
        if not ok:
            print("  ".join(cells + ["—"] * (len(head) - 1)))
            continue
        for lang in LANGS:
            s = r["langs"][lang]["summary"]
            cells += ["%.1f%%" % (s["hit@1"] * 100),
                      "%.1f%%" % (s["hit@%d" % k] * 100),
                      "%.4f" % s["mrr"]]
        um = "/".join(
            "n/a" if r["langs"][l].get("unmapped_rate") is None
            else "%.1f%%" % (100 * r["langs"][l]["unmapped_rate"]) for l in LANGS)
        cells.append(um)
        print("  ".join(c.ljust(wi) for c, wi in zip(cells, w)))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    k = 5
    if "--k" in argv:
        k = int(argv[argv.index("--k") + 1])

    ec.unlock_global_cap()
    ec.use_jaccard()

    data = bc.load()
    questions = data["questions"]
    print("[bench6] 题 %d / 池 %d / 竞品目录 %s"
          % (len(questions), len(data["pool"]), ARM_OUT))

    main_res = load_main(None)
    out_rows, table, payload = [], {}, {"k": k, "arms": {}, "missing": []}

    for key, label in MAIN_ARMS:
        r = main_res.get(key)
        if r:
            out_rows.append((label, r))
            payload["arms"][key] = {"langs": r["langs"], "source": "main"}
        else:
            payload["missing"].append(key)

    for arm, label in COMPETITOR_ARMS:
        r, err = load_competitor(arm, questions, k)
        if r is None:
            payload["missing"].append(arm)
            print("[competitor] %s -> %s" % (arm, err))
            continue
        out_rows.append((label, r))
        payload["arms"][arm] = {
            "label": label, "index_rc": r["raw_meta"].get("index_rc"),
            "ingest": r["raw_meta"].get("ingest"),
            "note": r["raw_meta"].get("note"),
            "ingest_probe": r["raw_meta"].get("ingest_probe"),
            "search_field_path": r["raw_meta"].get("search_field_path"),
            "errors_n": len(r.get("errors") or []),
            "errors_head": (r.get("errors") or [])[:5],
            "langs": {l: {kk: r["langs"][l][kk] for kk in
                          ("summary", "n_unmapped", "n_empty",
                           "unmapped_rate", "seconds")} for l in LANGS},
        }

    print_matrix(out_rows, k)

    # 分题型附表（中文查询，六家可比）
    by_qtype = {}
    for label, r in out_rows:
        zh = r["langs"].get("zh")
        if not zh:
            continue
        per = {}
        for row in zh["rows"]:
            per.setdefault(row["qtype"], []).append(row)
        by_qtype[label] = {qt: ec.summarize(v, k=k) for qt, v in per.items()}
    payload["by_qtype_zh"] = {lbl: {qt: s for qt, s in v.items()}
                              for lbl, v in by_qtype.items()}

    if by_qtype:
        qts = sorted({qt for v in by_qtype.values() for qt in v})
        head = ["系统"] + qts
        w = [22] + [max(8, len(q)) for q in qts]
        line = "  ".join(h.ljust(wi) for h, wi in zip(head, w))
        print("\n分题型 hit@1（中文查询，括号内为题数）")
        print(line)
        print("-" * len(line))
        n_by_qt = {}
        for qt in qts:
            n_by_qt[qt] = sum(1 for q in questions if q["qtype"] == qt)
        head = ["系统"] + ["%s(%d)" % (q, n_by_qt[q]) for q in qts]
        w = [22] + [max(8, len(h)) for h in head[1:]]
        for label, v in by_qtype.items():
            cells = [label] + ["%.0f%%" % (v[q]["hit@1"] * 100) if q in v else "—"
                               for q in qts]
            print("  ".join(c.ljust(wi) for c, wi in zip(cells, w)))

    ec.save_result("bench6_all_result.json", payload)
    print("\n[bench6] 六家汇总落盘 bench6_all_result.json"
          "（缺 %d 项：%s）" % (len(payload["missing"]),
                                ",".join(payload["missing"]) or "无"))
    return payload


if __name__ == "__main__":
    main()
