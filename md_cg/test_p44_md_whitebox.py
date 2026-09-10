# -*- coding: utf-8 -*-
"""P44 · md 原生知识库的白箱问答（端到端实测）。

验证目标
--------
1) 结构等价：md 语料还原库与源库 nodes / edges 计数一致（4355 / 2948）；
2) **数据等价**：逐题比较 `dex_respond` 的**全量候选集**（name+score）——
   这是「md 语料 = 源库知识」的硬证据，不受 top-N 截断与排序影响；
3) **端到端一致**：同一批实际问题上，md 库与源库的 `chat` 回答
   （route / 命中卡 / 分值）逐题一致；同分并列单独标注（排序取决于
   表的物理顺序，非数据差异）；
4) 效果报告：打印每题的 route、命中卡、回答摘要，供人工评估。

源库保护
--------
对比跑在源库的**临时副本**上：白箱问答会 `increment_access` 写库，
绝不能污染随包的只读 `wisdom-book-cloud.db`。

运行：`python -m md_cg.test_p44_md_whitebox`
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))

from .md_whitebox import build_db_from_md  # noqa: E402

SOURCE_DB = os.path.join(_HERE, "whitebox_kb", "wisdom", "wisdom-book-cloud.db")

#: 20 题实际题库：口语提问 × 跨域，覆盖白箱各条确定性检索通路。
QUESTIONS = [
    # —— 翻译表（俗语 → 规范知识词）
    "水烧开是什么现象",
    "为什么会打雷",
    "铁球和羽毛谁落得快",
    "天空为什么是蓝的",
    # —— 学科术语直配
    "什么是熵",
    "什么是勾股定理",
    "什么是光合作用",
    "什么是质数",
    # —— 极短 / 单字学科词
    "熵",
    # —— 领域知识点卡（KCCS 注释索引）
    "古巴比伦有什么文明成就",
    "秦始皇是谁",
    "月亮为什么会有阴晴圆缺",
    "什么是通货膨胀",
    # —— 英文缩写
    "什么是TCP三次握手",
    "KKT条件是什么",
    # —— 系统概念（含「定律」先验）
    "光的反射定律是什么",
    "一天有多少小时",
    # —— 元层 / 理论
    "什么是条件论",
    "什么是存在论",
    # —— 诚实边界（白箱应拒答或降级，而非编造）
    "外星人存在吗",
]


def _probe(db_path, questions, label):
    """在同一引擎上顺序提问，返回逐题结果。

    两库按**同题同序**跑，access 累积轨迹相同，故对比公平。
    候选集用 `dex_respond`（全库打分，不被 graph_retrieve 的
    top-N 早返回截断），端到端用 `chat`（真实入口）。
    """
    from .whitebox_kb.engine import WhiteboxEngine  # 先导入：注入 sys.path
    import semantic_translate as _st  # noqa: E402 —— 平铺导入，需上行先执行

    eng = WhiteboxEngine(db_path=db_path, seed=False)
    out = []
    try:
        dex = eng.dex
        for q in questions:
            try:
                # limit 放大到不截断：截断会让「同分并列」的保留集合
                # 取决于排序，从而把排序差异误判成数据差异。
                _hits = dex.dex_respond(q, limit=10 ** 6, translator=_st)
                _c = {}
                for h in _hits:
                    _sc = round(float(h.get("score") or 0), 4)
                    _c.setdefault(_sc, set()).add(h.get("name") or "")
                cand = {k: frozenset(v) for k, v in _c.items()}
            except Exception as exc:  # 诊断用：不掩盖底层异常
                cand = {"__error__": frozenset([f"{type(exc).__name__}: {exc}"])}
            res = eng.chat(q, session_id=f"p44-{label}")
            hits = res.get("hits") or []
            top = hits[0] if hits else {}
            out.append({
                "q": q, "cand": cand,
                "route": res.get("route") or "",
                "top": top.get("name") or "",
                "score": (round(float(top.get("score") or 0), 4)
                          if hits else None),
                "matched": list(top.get("matched") or []),
                "reply": (res.get("reply") or "").strip(),
            })
    finally:
        eng.close()
    return out


def _count(db_path, table):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        con.close()


def _report(rows):
    print(f"\n===== md 原生知识库 · 白箱回答（{len(rows)} 题） =====")
    print(f"{'#':>2}  {'route':<14} {'score':>6}  {'命中卡':<28} 问题")
    for i, r in enumerate(rows, 1):
        print(f"{i:>2}  {r['route']:<14} {str(r['score']):>6}  "
              f"{r['top'][:26]:<28} {r['q']}")
        if r["reply"]:
            print(f"      └─ {r['reply'][:140]}")


def main():
    ok = True

    # ---- 1) 结构等价 ----
    # force：从 md 语料**重新**还原，保证 access_count 等可变字段与源库快照
    # 同起点（复用旧库会带上此前问答累积的 access，造成假差异）。
    md = build_db_from_md(force=True, verbose=False)
    src_nodes, src_edges = _count(SOURCE_DB, "nodes"), _count(SOURCE_DB, "edges")
    print(f"[结构] md 还原库  nodes={md['nodes']}  edges={md['edges']}")
    print(f"[结构] 源库      nodes={src_nodes}  edges={src_edges}")
    if (md["nodes"], md["edges"]) != (src_nodes, src_edges):
        print("[FAIL] 结构不等价")
        ok = False
    else:
        print("[PASS] 结构等价（nodes / edges 计数一致）")

    # ---- 2) 跑两库（源库用临时副本，绝不写包内库） ----
    tmp_dir = tempfile.mkdtemp(prefix="p44_src_")
    tmp = os.path.join(tmp_dir, "src_copy.db")
    shutil.copy2(SOURCE_DB, tmp)
    try:
        rows_md = _probe(md["db"], QUESTIONS, "md")
        rows_src = _probe(tmp, QUESTIONS, "src")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---- 3) 数据等价：全量候选集逐一比对 ----
    cand_bad = []
    for a, b in zip(rows_md, rows_src):
        if a["cand"] != b["cand"]:
            cand_bad.append({"q": a["q"], "md": a["cand"], "src": b["cand"]})
    print(f"\n[数据] 候选集逐题一致 {len(QUESTIONS) - len(cand_bad)}/{len(QUESTIONS)}"
          f"（dex_respond 全量打分，不受排序影响）")
    if cand_bad:
        ok = False
        print("[FAIL] md 库与源库候选集不一致：")
        for d in cand_bad[:5]:
            print(f"   {d['q']}")
            for tag in ("md", "src"):
                keys = sorted(d[tag], reverse=True)[:6]
                print(f"     {tag:<3}: " + "; ".join(
                    f"{k}={sorted(d[tag][k])[:3]}" for k in keys))
    else:
        print("[PASS] 数据等价（每题候选集完全相同）")

    # ---- 4) 端到端一致：route / 命中卡 / 分值 ----
    diff, parallel = [], []
    for a, b in zip(rows_md, rows_src):
        if a["route"] != b["route"]:
            diff.append((a["q"], "route", a["route"], b["route"]))
        elif a["score"] != b["score"]:
            diff.append((a["q"], "score", a["score"], b["score"]))
        elif a["top"] != b["top"]:
            # 同分并列：两侧 top 都出现在对方候选集内且分值相同
            # → 差异仅来自表的物理遍历顺序，非数据差异
            _an = {n for ns in a["cand"].values() for n in ns}
            _bn = {n for ns in b["cand"].values() for n in ns}
            if (a["score"] == b["score"]
                    and a["top"] in _bn and b["top"] in _an):
                parallel.append((a["q"], a["top"], b["top"], a["score"]))
            else:
                diff.append((a["q"], "top", a["top"], b["top"]))
    same = len(QUESTIONS) - len(diff) - len(parallel)
    print(f"\n[行为] 严格一致 {same}/{len(QUESTIONS)}"
          f" · 同分并列 {len(parallel)} · 不一致 {len(diff)}")
    for q, md_top, src_top, sc in parallel:
        print(f"   并列 {q}（同为 {sc}）：md={md_top} / src={src_top}")
    if diff:
        ok = False
        print("[FAIL] 端到端不一致：")
        for q, field, x, y in diff[:8]:
            print(f"   {q} · {field}: md={x!r} vs src={y!r}")
    else:
        print("[PASS] 端到端一致（差异仅为同分并列的排序）")

    # ---- 5) 效果报告 ----
    _report(rows_md)
    answered = [r for r in rows_md if r["reply"]]
    print(f"\n[效果] 有回答 {len(answered)}/{len(QUESTIONS)}"
          f" · route=self {sum(1 for r in rows_md if r['route'] == 'self')}"
          f" · self_fallback "
          f"{sum(1 for r in rows_md if r['route'] == 'self_fallback')}"
          f" · 命中 KCCS 注释索引 "
          f"{sum(1 for r in rows_md if 'KCCS注释索引' in r['matched'])}")
    print("\n" + ("全部通过" if ok else "存在失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
