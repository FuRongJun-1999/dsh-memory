#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_en_atoms_public.py · 双语双路英文原子检索公开复现（2026-09-14）

背景：
    使用者终局裁定（2026-09-14）：英文检索路线回归双语双路架构——
    「英文原题 → 英文原子 → Jaccard 直接匹配」（REPRODUCE.md 双语双路裁定）。
    同日判决：en→zh 词级归一→纯中文库（u2）机械上界 hit@10=33.6%
    （bench_unified_en 五连探针证据链：归一路 bug=0 / 距离超窗=0 /
    缺口 100%=题面无词的 8 倍信息差），不再作为英文路线。
    本脚本是 README「中英双语检索差距」②③ 行的本仓复现入口。

口径（md_cg/semantic/REPRODUCE.md）：
    doc 侧节点原子集 = 中文五槽条目逐字字级英文映射（lexicon/char_atoms_clean.json，
    6320 字）∪ 英文正文 normalize_en 归一词 —— 两语素合并为节点原子集合；
    query 侧两臂：
      臂②（zh_kw_map）  中文关键词 → 逐字字级英文映射 → normalize_en 词集
                        （与①共用中文关键词语义链，只换词面编码）
      臂③（en_query）   英文原题 → normalize_en → 词集（跨过同义改写鸿沟）
    打分：Jaccard = |q∩d| / |q∪d|（对称归一，eval_common.use_jaccard 同判据），
    全池 567 节点排序，evidence_turns 任一命中记 hit。

跑法：

    python -m md_cg.bench_en_atoms_public

锚点（README ②③ 行）：
    ② 52-53 / 79-81 / 87-88（hit@1/5/10）
    ③ 48.8 / 73.8 / 79.0

诚实边界：
    1) 池 567 条全为 gold → 零干扰上界，非端到端能力；
    2) 英文原题来自上游 LoCoMo 派生副本（data/external，不入库）——脚本
       公开但英文原题自备（BENCH6_EN_QUESTIONS 可覆盖路径）；中文关键词
       题面在公开集 questions500.jsonl；
    3) ②③ 差值（87 vs 79）是同义词鸿沟的直接隔离证据，不是工程缺陷。
"""
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg import bench6_common as b6            # noqa: E402
from md_cg import eval_common as ec              # noqa: E402
from md_cg.mdcg import normalize_en              # noqa: E402

DATA = b6.DATA
CORPUS = b6.CORPUS567
QUESTIONS = b6.QUESTIONS500
CHAR_ATOMS = os.path.join(HERE, "md_cg", "lexicon", "char_atoms_clean.json")

ZH_RANGE = ("\u4e00", "\u9fff")


def load_char_atoms():
    """字级英文原子库：{中文字: 英文短语}。"""
    with io.open(CHAR_ATOMS, encoding="utf-8") as f:
        data = json.load(f)
    lex = data.get("lexicon") or {}
    return {ch: str(v.get("en") or "") for ch, v in lex.items()}


def zh_map_en(text, char_atoms):
    """中文逐字→英文短语映射串；英文/数字原样保留（交 normalize_en 归一）。"""
    lo, hi = ZH_RANGE
    parts = []
    for ch in (text or ""):
        if lo <= ch <= hi:
            parts.append(char_atoms.get(ch, ""))
        else:
            parts.append(ch)
    return normalize_en(" ".join(parts))


def node_atom_set(c, char_atoms, body_only=False):
    """doc 侧节点原子集：中文五槽字级映射 ∪ 英文正文归一词（双语双路 doc 侧）。

    body_only=True 时只取英文正文归一词——「英文原子直接匹配」最纯形态
    （使用者产品口径：英文 query → 英文原子 → 英文原子库 → 返回英文原文）。
    """
    toks = normalize_en(str(c.get("text") or "")).split()
    if not body_only:
        toks += zh_map_en(str(c.get("zh") or ""), char_atoms).split()
    return frozenset(toks)


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b) if inter else 0.0


def run_arm(questions, docs, qatoms_of, label):
    """单臂评测：全池 Jaccard 排序，hit@1/5/10 + MRR。"""
    st = {"h1": 0, "h5": 0, "h10": 0, "rr": 0.0, "n": 0}
    for q in questions:
        ev = set(q.get("evidence_turns") or [])
        qa = qatoms_of(q)
        if not qa:
            st["n"] += 1
            continue
        scored = sorted(((jaccard(qa, na), nid) for nid, na in docs),
                        key=lambda t: (-t[0], t[1]))
        rank = next((r for r, (s, nid) in enumerate(scored, 1) if nid in ev), 0)
        st["n"] += 1
        if rank == 1:
            st["h1"] += 1
        if 0 < rank <= 5:
            st["h5"] += 1
        if 0 < rank <= 10:
            st["h10"] += 1
        if rank:
            st["rr"] += 1.0 / rank
    n = max(st["n"], 1)
    print("  %-14s hit@1=%5.1f%%  hit@5=%5.1f%%  hit@10=%5.1f%%  MRR=%.4f  (n=%d)"
          % (label, st["h1"] * 100.0 / n, st["h5"] * 100.0 / n,
             st["h10"] * 100.0 / n, st["rr"] / n, st["n"]))
    return {k: (v / n if k == "rr" else v * 100.0 / n) for k, v in st.items()}


def main():
    t0 = time.time()
    with io.open(CORPUS, encoding="utf-8") as f:
        corpus = [json.loads(ln) for ln in f if ln.strip()]
    with io.open(QUESTIONS, encoding="utf-8") as f:
        questions = [json.loads(ln) for ln in f if ln.strip()]
    char_atoms = load_char_atoms()
    docs = [(c["id"], node_atom_set(c, char_atoms)) for c in corpus]
    docs_body = [(c["id"], node_atom_set(c, char_atoms, body_only=True))
                 for c in corpus]
    print("[en_atoms] locomo-zh-500 · 语料 %d / 题 %d · 字级原子 %d 字"
          % (len(corpus), len(questions), len(char_atoms)))

    # 臂② 中文关键词 → 字级英文原子（与①共用语义链，只换词面编码）
    r2 = run_arm(questions, docs,
                 lambda q: frozenset(zh_map_en(str(q.get("question") or ""),
                                               char_atoms).split()),
                 "② zh→en atoms")
    # 臂③ 英文原题 → 归一化英文原子（跨同义改写鸿沟）
    # 英文原题行字段=question（raw_questions.jsonl，上游派生不入库）
    en_rows = {r.get("qid"): str(r.get("question") or "")
               for r in ec.iter_jsonl(b6.EN_QUESTIONS)}
    en_q = lambda q: frozenset(normalize_en(          # noqa: E731
        en_rows.get(q.get("qid"), "")).split())
    r3 = run_arm(questions, docs, en_q, "③ en query")
    # 臂③a 纯英文正文直接匹配（产品最纯形态：doc=英文正文原子，无加工面辅助）
    r3a = run_arm(questions, docs_body, en_q, "③a en·body")

    print("[en_atoms] 完成（%.0fs）②=%s ③=%s ③a=%s"
          % (time.time() - t0,
             {k: round(v, 1) for k, v in r2.items()},
             {k: round(v, 1) for k, v in r3.items()},
             {k: round(v, 1) for k, v in r3a.items()}))
    print("  锚点：② 52-53/79-81/87-88 · ③ 48.8/73.8/79.0（hit@1/5/10）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
