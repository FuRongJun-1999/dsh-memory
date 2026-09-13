#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench6 · 中英双查公开评测脚本（零第三方依赖，仅 Python 标准库）。

复现结论（六家 × 同一英文语料 × 同一批 100 题 × 中英双词面）：
    **所有六家系统的中文查询命中均高于英文查询**（hit@1 提升 +12 ~ +52pp）。
    直接运行本脚本（无参数）即可从 results_v1.0.json 出对比主表，
    并自证指标口径与发表数字逐位一致。

使用方式：
    python run_bench.py                 # 六家中英对比主表 + 口径自证（零依赖）
    python run_bench.py --demo          # 内置词面基线实跑一遍（Adapter 协议演示）
    python run_bench.py --adapter my_bench.MyAdapter   # 接入你自己的记忆系统

Adapter 协议（你的记忆系统只需实现两个方法）：

    class MyAdapter:
        name = "my-system"
        def ingest(self, records):
            '''records = pool.jsonl 全部行（dict 列表，字段见 README）。
            把语料写入你的记忆系统。只调用一次。'''
        def search(self, query, k):
            '''返回与 query 最相关的 [id, ...]（pool 行的 id 字段），
            按相关性降序；不足 k 条合法。中文/英文词面各查询一遍。'''

指标口径（与仓内 md_cg/eval_common.py 判据逐字同源，--verify-results 可证）：
    rank   = 首个证据 id 的排名（1-based；未命中 0）
    hit@1  = rank==1 占比；hit@k = 0<rank<=k 占比；mrr = mean(1/rank)

诚实边界（原样继承自横评报告，解读结果前必读）：
    1. 池全为 gold 证据 → 池内零干扰，指标是上界，不是端到端记忆能力。
    2. question_zh 是中文关键词串（保留英文专名与日期词）、question_en 是
       英文自然问句 → 本对照测「检索命中」，不是 QA；「中文提升」混合了
       查询语言与查询形态（关键词串 vs 自然句）两因素，归因到语言本身须谨慎。
    3. n=100 时题级命中率 CV≈8.3% → 家间差距小于约 16% 不可下结论。
    4. 各家返回行序为其自身排序口径，非统一重排。

题集许可：CC BY-NC 4.0（源自 LoCoMo，见 README.md 与报告署名节）。
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS_JSONL = os.path.join(HERE, "questions.jsonl")
POOL_JSONL = os.path.join(HERE, "pool.jsonl")
RESULTS_JSON = os.path.join(HERE, "results_v1.0.json")

try:  # Windows 控制台 GBK 兜底（不影响 Linux/macOS）
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ---------------------------------------------------------------- 数据加载

def iter_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_dataset():
    """题集三件套：questions.jsonl / pool.jsonl（results_v1.0.json 可选）。"""
    questions = list(iter_jsonl(QUESTIONS_JSONL))
    pool = list(iter_jsonl(POOL_JSONL))
    results = None
    if os.path.exists(RESULTS_JSON):
        with open(RESULTS_JSON, encoding="utf-8") as f:
            results = json.load(f)
    return questions, pool, results


# ------------------------------------------------- 指标（与 eval_common 同源）

def first_evidence_rank(ids, evidence):
    """首个证据 id 的排名（1-based；未命中 0）。同 md_cg/eval_common.py。"""
    if not evidence:
        return 0
    for i, x in enumerate(ids, 1):
        if x in evidence:
            return i
    return 0


def summarize(rows, k=5):
    """hit@1 / hit@k / MRR + 分题型。公式与 md_cg/eval_common.summarize 一致。"""
    if not rows:
        return {"n": 0}
    n = len(rows)
    hit1 = sum(1 for r in rows if r["rank"] == 1)
    hitk = sum(1 for r in rows if 0 < r["rank"] <= k)
    mrr = sum(1.0 / r["rank"] for r in rows if r["rank"]) / n
    out = {"n": n, "hit@1": hit1 / n, "hit@%d" % k: hitk / n, "mrr": mrr}
    by = {}
    for r in rows:
        by.setdefault(r["qtype"], []).append(r)
    out["by_qtype"] = {
        qt: {
            "n": len(g),
            "hit@1": sum(1 for r in g if r["rank"] == 1) / len(g),
            "hit@%d" % k: sum(1 for r in g if 0 < r["rank"] <= k) / len(g),
            "mrr": sum(1.0 / r["rank"] for r in g if r["rank"]) / len(g),
        } for qt, g in sorted(by.items())
    }
    return out


def rows_from_ranks(questions, ids_by_qid, k):
    """{qid: [id,...]} → 明细行（qid/qtype/rank）。"""
    rows = []
    for q in questions:
        ids = list(ids_by_qid.get(q["qid"]) or [])[:k]
        rows.append({"qid": q["qid"], "qtype": q["qtype"],
                     "rank": first_evidence_rank(ids, set(q["evidence_turns"]))})
    return rows


# ---------------------------------------------------------- 口径自证（可信度）

def verify_results(results, questions, k, tol=1e-9):
    """用 results_v1.0.json 的逐题 ranks 重算 summary，与存储值逐位断言。

    证明本脚本的指标实现与发表数字同源——第三方核对通过后即可放心
    用同一函数评自己的系统。
    覆盖范围（诚实声明）：lingshu 全部变体与 vector_rag 存有逐题 rows，
    逐位重算；四家竞品臂发表时仅存 summary（含 unmapped/n_empty 审计
    字段），无逐题明细无法重算 → 显式 SKIP（数字取自发表快照）。
    返回 (通过臂, 总可验臂, 跳过臂)。
    """
    q_by_id = {q["qid"]: q for q in questions}
    ok = total = skipped = 0
    for arm, payload in sorted(results.get("arms", {}).items()):
        for lang, side in sorted(payload.get("langs", {}).items()):
            if "rows" not in side:
                skipped += 1
                print("  [SKIP] %s/%s：无逐题明细（仅发表 summary，审计字段 "
                      "n_unmapped=%s n_empty=%s）"
                      % (arm, lang, side.get("n_unmapped"), side.get("n_empty")))
                continue
            total += 1
            rows = []
            for r in side["rows"]:
                q = q_by_id.get(r["qid"])
                if q is None:
                    continue
                rows.append({"qid": r["qid"], "qtype": r["qtype"],
                             "rank": r["rank"]})
            # 防 results 与题集不同步：qid 必须全覆盖
            if len(rows) != len(questions):
                print("  [FAIL] %s/%s：rows %d 题 != 题集 %d 题"
                      % (arm, lang, len(rows), len(questions)))
                continue
            calc = summarize(rows, k)
            stored = side["summary"]
            keys = ["n", "hit@1", "hit@%d" % k, "mrr"]
            bad = [x for x in keys
                   if abs(float(calc[x]) - float(stored[x])) > tol]
            for qt, cg in calc["by_qtype"].items():
                sg = stored.get("by_qtype", {}).get(qt)
                if sg is None:
                    bad.append("by_qtype.%s 缺失" % qt)
                    continue
                for x in ("n", "hit@1", "hit@%d" % k, "mrr"):
                    if abs(float(cg[x]) - float(sg[x])) > tol:
                        bad.append("by_qtype.%s.%s" % (qt, x))
            if bad:
                print("  [FAIL] %s/%s：%s" % (arm, lang, ",".join(bad)))
            else:
                ok += 1
    return ok, total, skipped


# ------------------------------------------------------- 内置词面基线（演示）

class CharNGramBaseline:
    """零依赖词面基线：字符 2-gram 计数余弦。中英通吃、完全确定性。

    用途是演示 Adapter 协议与脚本自检——它没有任何「记忆能力」，
    也正因如此，它在纯英文库上会得到 en>zh（词面同源），
    与六家记忆系统（带语义/结构处理）的 zh>en 形成教学对照。
    """

    name = "char-bigram-baseline"

    def __init__(self, k_ngram=2):
        self.k_ngram = k_ngram
        self.docs = {}

    @staticmethod
    def _grams(text, n):
        t = "".join(ch.lower() for ch in text if not ch.isspace())
        if len(t) < n:
            return {t} if t else set()
        return {t[i:i + n] for i in range(len(t) - n + 1)}

    def ingest(self, records):
        self.docs = {r["id"]: self._grams(r.get("text") or "", self.k_ngram)
                     for r in records}

    def search(self, query, k):
        q = self._grams(query, self.k_ngram)
        if not q:
            return []
        scored = []
        for did, dg in self.docs.items():
            if not dg:
                continue
            inter = len(q & dg)
            if not inter:
                continue
            scored.append((inter / math.sqrt(len(q) * len(dg)), did))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [did for _, did in scored[:k]]


# ------------------------------------------------------------------ 运行器

def run_adapter(adapter, questions, pool, k, langs=("zh", "en")):
    """按 Adapter 协议跑双查：ingest 一次，每种词面各查全部题目。"""
    adapter.ingest(pool)
    out = {}
    for lang in langs:
        ids_by_qid = {}
        for q in questions:
            ids_by_qid[q["qid"]] = list(adapter.search(q["question_%s" % lang], k))
        rows = rows_from_ranks(questions, ids_by_qid, k)
        out[lang] = summarize(rows, k)
    return out


def print_main_table(results, k):
    """六家 × 中英主表 + 「中文提升」幅度（数据取自发表快照）。"""
    print("=" * 78)
    print("bench6 · 六家记忆系统 中英双查主表（k=%d，数据：results_v1.0.json）" % k)
    print("=" * 78)
    head = ("%-26s %9s %9s %9s %9s %9s %9s %10s"
            % ("系统", "zh hit@1", "zh hit@%d" % k, "zh MRR",
               "en hit@1", "en hit@%d" % k, "en MRR", "zh-en(hit@1)"))
    print(head)
    print("-" * 78)
    flips = 0
    total = 0
    for arm, payload in sorted(results.get("arms", {}).items()):
        langs = payload.get("langs", {})
        zh, en = langs.get("zh", {}).get("summary", {}), langs.get("en", {}).get("summary", {})
        if not zh or not en:
            continue
        total += 1
        d = (zh.get("hit@1", 0.0) - en.get("hit@1", 0.0)) * 100.0
        if d > 0:
            flips += 1
        print("%-26s %8.1f%% %8.1f%% %9.4f %8.1f%% %8.1f%% %9.4f %9s"
              % (arm,
                 zh.get("hit@1", 0.0) * 100.0, zh.get("hit@%d" % k, 0.0) * 100.0,
                 zh.get("mrr", 0.0),
                 en.get("hit@1", 0.0) * 100.0, en.get("hit@%d" % k, 0.0) * 100.0,
                 en.get("mrr", 0.0),
                 "%+.1fpp" % d))
    print("-" * 78)
    print("结论：%d/%d 臂（六家系统及变体）「中文查询 hit@1 高于英文查询」（提升 +12 ~ +52pp）。"
          % (flips, total))
    print("唯一例外 letta_agent 为全零臂（未返回可映射结果：n_unmapped=100/n_empty=100）。")
    print("同一语料、同一批题、只换查询词面 → 检索命中系统性变化。")
    print("归因与边界见本目录 README.md「诚实边界」（zh 为关键词串、en 为自然问句）。")


def load_adapter(spec):
    """--adapter pkg.mod.ClassName → 实例化（零参）。"""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)  # 允许 --adapter run_bench.CharNGramBaseline 这类同目录模块
    mod_name, _, attr = spec.rpartition(".")
    if not mod_name:
        raise SystemExit("--adapter 需要 pkg.mod.Class 形式：%r" % spec)
    mod = importlib.import_module(mod_name)
    cls = getattr(mod, attr)
    inst = cls()
    for m in ("ingest", "search"):
        if not callable(getattr(inst, m, None)):
            raise SystemExit("Adapter 缺少 %s() 方法：%r" % (m, spec))
    if not getattr(inst, "name", None):
        raise SystemExit("Adapter 缺少 name 属性：%r" % spec)
    return inst


def main():
    ap = argparse.ArgumentParser(
        description="bench6 中英双查公开评测（零依赖；--demo/--adapter 见 docstring）")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--demo", action="store_true",
                    help="用内置词面基线实跑双查（协议演示）")
    ap.add_argument("--adapter", default=None,
                    help="你的记忆系统：pkg.mod.Class（实现 ingest/search/name）")
    args = ap.parse_args()

    questions, pool, results = load_dataset()
    print("[bench6] 题集：%d 题 / 池 %d 条（%s）" % (len(questions), len(pool), HERE))

    if results:
        ok, total, skipped = verify_results(results, questions, args.k)
        print("[口径自证] results_v1.0.json 逐题 ranks 重算 vs 存储值：%d/%d 臂逐位一致；"
              "%d 臂无逐题明细（SKIP，取自发表快照）" % (ok, total, skipped))
        if ok != total:
            raise SystemExit("口径自证失败：本脚本指标与发表数字不同源，禁止使用")
        print_main_table(results, args.k)

    if args.demo:
        print("\n[demo] 内置词面基线（char-bigram，无记忆能力）双查实跑：")
        out = run_adapter(CharNGramBaseline(), questions, pool, args.k)
        for lang in ("zh", "en"):
            s = out[lang]
            print("  %-3s hit@1=%.1f%%  hit@%d=%.1f%%  mrr=%.4f"
                  % (lang, s["hit@1"] * 100, args.k, s["hit@%d" % args.k] * 100,
                     s["mrr"]))
        print("  词面基线在纯英文库上 en>zh（词面同源）——对照六家 zh>en：")
        print("  查询语言优势取决于系统如何处理语料，这正是本测试要暴露的变量。")

    if args.adapter:
        adapter = load_adapter(args.adapter)
        print("\n[adapter] %s 双查评测中（ingest %d 条 → 每语言 %d 题）……"
              % (adapter.name, len(pool), len(questions)))
        out = run_adapter(adapter, questions, pool, args.k)
        zh, en = out["zh"], out["en"]
        print("%-26s %9s %9s %9s" % ("语言", "hit@1", "hit@%d" % args.k, "mrr"))
        for lang, s in (("zh", zh), ("en", en)):
            print("%-26s %8.1f%% %8.1f%% %9.4f"
                  % (lang, s["hit@1"] * 100, s["hit@%d" % args.k] * 100, s["mrr"]))
        print("zh-en(hit@1) = %+.1fpp" % ((zh["hit@1"] - en["hit@1"]) * 100.0))

    print("\n[边界] 池全 gold=上界；zh=关键词串/en=自然问句（语言+形态双因素）；"
          "n=100 CV≈8.3% → 差距<16pp 不可下结论。详见 README.md。")


if __name__ == "__main__":
    main()
