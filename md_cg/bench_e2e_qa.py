# -*- coding: utf-8 -*-
"""端到端 QA 评测：pinpoint / answerability / decision-making（2026-09-23 · 外部建议）

评测问题（外部建议口径：hit@k 是上界，端到端要答对题）：
  pinpoint        干扰浓度升高（level 0 → 4），reader 从候选记忆中抽取正确事实的
                  QA 准确率退化多少？
  answerability   adversarial 题（上游设计 gold 为空、正确行为=拒答）：reader 会不会
                  被干扰节点骗去编答案？
  decision-making 裁决层是否改变下游行为——同一 reader，候选分别来自
                  arm_base（裸融合 top10）与 arm_firewall（证据防火墙重排 top10），
                  QA 准确率有无差异？

管线（全部真实 LLM，deepseek-chat，temperature=0，带缓存）：
  检索（与 bench_e2e_judge 同池同采样同臂）→ reader 只据候选卡作答
  （不足则答「无法确定」）→ judge 对 gold 语义判等（correct/incorrect/refused）。
  gold 答案来自上游 LoCoMo 原始标注（mteb/LoCoMo 1976 题英文题面 ↔
  snap-research/locomo10.json 逐题文本精确匹配，500/500 覆盖；
  113 题 adversarial 的 gold 为空 = 拒答语义）。

诚实边界：
  · reader 同时拿中文关键词串与上游英文原题（真实用户问题面），记忆卡为中文，
    judge 对英文 gold 做跨语语义判等——这是双语口径，非纯单语评测。
  · judge 亦为 LLM（LLM-as-a-judge），其判分自身有方差；refused 由 judge 判
    reader 文本，边界例（半猜测半拒答）按 judge 裁决计入，不人工复核（v1）。
  · level 2 不入 QA 层（0 vs 4 已给退化区间，节省调用）。

跑法：
  python -X utf8 -m md_cg.bench_e2e_qa --quick          # 冒烟 3 题
  python -X utf8 -m md_cg.bench_e2e_qa                  # 全量 120 题 × 4 组
依赖：DEEPSEEK_API_KEY；answers_map 由上游对齐生成（见 --answers 默认路径）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg.bench_e2e_judge import (                     # noqa: E402
    DEFAULT_ROOT, load_src, speakers_by_scene, build_pool, run_det_arms,
    llm_chat)

READER_SYS = (
    "你是记忆问答器。只根据给定的记忆卡回答问题，不要用记忆卡以外的知识。"
    "记忆卡不足以确定答案时，回答「无法确定」。答案尽量简短（不超过20字），"
    "不要解释。\n只输出一行 JSON：{\"answer\": \"…\"}"
)

JUDGE_SYS = (
    "你是 QA 评分器。给定问题、参考答案（gold）与模型回答，判一个结论：\n"
    "- correct：回答与 gold 语义等价（中英跨语判等；日期/人名/实体须一致，"
    "表述差异可容忍）\n"
    "- incorrect：回答了但语义与 gold 不等价（含被错误记忆误导的答案）\n"
    "- refused：回答表示无法确定/不知道/记忆未提及\n"
    "gold 为空字符串时（对抗题）：回答「无法确定」= correct，给出任何具体"
    "答案 = incorrect。\n只输出一行 JSON：{\"verdict\": \"correct\"}"
)


def _cache_call(cache_dir, kind, payload_key, fn):
    """LLM 调用缓存：payload_key 相同直接回放（qa 层可复现性与省钱）。"""
    hexk = hashlib.md5(payload_key.encode("utf-8")).hexdigest()
    path = os.path.join(cache_dir, f"{kind}_{hexk}.json")
    if os.path.isfile(path):
        d = json.load(open(path, encoding="utf-8"))
        return d["out"], d.get("tokens", 0), 0.0, True
    out, usage, dt = fn()
    json.dump({"out": out, "tokens": int(usage.get("total_tokens") or 0)},
              open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return out, int(usage.get("total_tokens") or 0), dt, False


def parse_json_field(raw, field):
    s = raw or ""
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(s[i:j + 1]).get(field)
        except ValueError:
            pass
    return None


def run_qa_one(cfg, cache_dir, q, ans, cand_nodes, arm, level):
    """一题一组：reader 作答 → judge 判分。返回行（异常行 error 字段）。"""
    cards = "\n\n".join(
        f"【{i}】{str(nd.get('content') or '')[:400]}"
        for i, nd in enumerate(cand_nodes, 1))
    r_user = (f"问题（中文关键词）：{q['question']}\n"
              f"问题（英文原题）：{ans.get('en_q') or ''}\n\n候选记忆卡：\n{cards}")
    tag = f"{q['qid']}|{arm}|L{level}"

    def call_reader():
        return llm_chat(cfg["model"], cfg["base"], cfg["key"],
                        [{"role": "system", "content": READER_SYS},
                         {"role": "user", "content": r_user}],
                        timeout=cfg["timeout"], max_tokens=300)

    def call_judge():
        return llm_chat(cfg["model"], cfg["base"], cfg["key"],
                        [{"role": "system", "content": JUDGE_SYS},
                         {"role": "user", "content":
                          f"问题：{ans.get('en_q') or q['question']}\n"
                          f"gold：{ans.get('answer') or ''}\n"
                          f"模型回答：{row['answer']}"}],
                        timeout=cfg["timeout"], max_tokens=200)

    row = {"qid": q["qid"], "qtype": q.get("qtype"), "arm": arm,
           "level": level, "gold": ans.get("answer") or ""}
    try:
        raw, tok_r, dt_r, _c = _cache_call(
            cache_dir, "reader", cfg["model"] + "|" + r_user, call_reader)
        ans_txt = parse_json_field(raw, "answer")
        if ans_txt is None:
            ans_txt = (raw or "").strip()[:80]
        row["answer"] = ans_txt
        raw2, tok_j, dt_j, _c2 = _cache_call(
            cache_dir, "judge",
            cfg["model"] + "|" + row["gold"] + "|" + ans_txt + "|"
            + (ans.get("en_q") or ""), call_judge)
        verdict = parse_json_field(raw2, "verdict")
        row["verdict"] = verdict if verdict in ("correct", "incorrect",
                                                "refused") else None
        row["tokens"] = tok_r + tok_j
        row["latency"] = dt_r + dt_j
        if row["verdict"] is None:
            row["error"] = f"judge 不可解析：{(raw2 or '')[:80]}"
    except Exception as exc:                            # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"
        row.setdefault("answer", "")
        row["verdict"] = None
        row["tokens"] = row.get("tokens", 0)
        row["latency"] = row.get("latency", 0.0)
    row["_tag"] = tag
    return row


def qa_report(rows):
    n = len(rows)
    ok = [r for r in rows if r.get("verdict")]
    adv = [r for r in ok if r.get("qtype") == "adversarial"]
    norm = [r for r in ok if r.get("qtype") != "adversarial"]
    c = lambda rs, v: sum(1 for r in rs if r["verdict"] == v)   # noqa: E731
    st = {
        "n": n, "judged": len(ok), "errors": n - len(ok),
        "acc": c(ok, "correct") / max(len(ok), 1),
        "incorrect": c(ok, "incorrect"), "refused": c(ok, "refused"),
        "norm_n": len(norm),
        "norm_acc": c(norm, "correct") / max(len(norm), 1),
        "norm_refused": c(norm, "refused"),
        "adv_n": len(adv),
        "adv_correct_refusal": c(adv, "correct"),
        "adv_fooled": c(adv, "incorrect"),
        "tokens": sum(r.get("tokens", 0) for r in rows),
    }
    return st


def main(argv=None):
    ap = argparse.ArgumentParser(description="端到端 QA：pinpoint/answerability")
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    ap.add_argument("--answers",
                    default=os.path.join(DEFAULT_ROOT, "upstream",
                                         "answers_map.json"))
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--levels", default="0,4")
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--base-url", default="https://api.deepseek.com/v1")
    ap.add_argument("--key", default="")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    if a.quick:
        a.n = 3
    key = a.key or os.environ.get("DEEPSEEK_API_KEY") or ""
    if not key:
        print("[error] 需要 DEEPSEEK_API_KEY 或 --key")
        return 2
    if not os.path.isfile(a.answers):
        print(f"[error] 找不到答案映射 {a.answers}（先跑上游对齐生成）")
        return 2

    levels = [int(x) for x in a.levels.split(",") if x.strip() != ""]
    cache_dir = os.path.join(a.data_root, "qa_cache")
    os.makedirs(cache_dir, exist_ok=True)
    res_dir = os.path.join(a.data_root, "results")
    os.makedirs(res_dir, exist_ok=True)

    import random
    corpus, questions = load_src()
    corpus_map = {c["id"]: c for c in corpus}
    spk = speakers_by_scene(corpus)
    answers = json.load(open(a.answers, encoding="utf-8"))
    sample = sorted(random.Random(a.seed).sample(
        questions, min(a.n, len(questions))), key=lambda q: q["qid"])
    print(f"[e2e_qa] 采样 {len(sample)} 题（seed={a.seed}）× levels={levels}"
          f" × 候选臂 base/firewall × {a.model}")

    cfg = {"model": a.model, "base": a.base_url, "key": key,
           "timeout": a.timeout}
    all_rows, summary = [], {"meta": {"seed": a.seed, "n": len(sample),
                                      "model": a.model, "levels": levels}}
    for lv in levels:
        cg, n_synth = build_pool(lv, corpus, questions, corpus_map, spk,
                                 a.data_root)
        det = []
        for q in sample:
            r = run_det_arms(cg, q, k=a.k)
            r["q"] = q
            det.append(r)
        tasks = []
        for r in det:
            for arm in ("base", "firewall"):
                nodes = r["base_nodes"][:a.k] if arm == "base" \
                    else r["fw_nodes"][:a.k]
                tasks.append((r["q"], answers.get(r["q"]["qid"], {}),
                              nodes, arm, lv))
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            rows = list(ex.map(lambda t: run_qa_one(cfg, cache_dir, *t),
                               tasks))
        all_rows.extend(rows)
        print(f"\n===== level {lv}（池={len(corpus)+n_synth}）"
              f" · QA 耗时 {time.time()-t0:.1f}s =====")
        print(f"{'臂':<10}{'QA准确率':>9}{'常规准确率':>10}{'常规拒答':>8}"
              f"{'对抗正确拒答':>12}{'对抗被骗':>8}{'判分失败':>8}")
        for arm in ("base", "firewall"):
            st = qa_report([r for r in rows if r["arm"] == arm])
            print(f"{arm:<10}{st['acc']*100:>8.1f}%{st['norm_acc']*100:>9.1f}%"
                  f"{st['norm_refused']:>7d}/{st['norm_n']}"
                  f"{st['adv_correct_refusal']:>10d}/{st['adv_n']}"
                  f"{st['adv_fooled']:>7d}"
                  f"{st['errors']:>7d}")
            summary[f"L{lv}_{arm}"] = st
    out = os.path.join(res_dir,
                       f"qa_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump({"summary": summary,
               "rows": [{k: v for k, v in r.items() if k != "q"}
                        for r in all_rows]},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[e2e_qa] 完成。明细 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
