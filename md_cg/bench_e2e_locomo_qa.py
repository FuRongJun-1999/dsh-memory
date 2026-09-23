# -*- coding: utf-8 -*-
"""LoCoMo QA 同口径对照评测：完整对话做记忆 · 自然问句做查询（2026-09-23）

目的（使用者口径）：与 Mem0/Letta/Zep 等同设定直接比数字——**对话做记忆、自然问句做
查询、LLM reader + LLM judge**，不再以「摘要卡/关键词串」口径差异回避对照。

与同行的对齐面：
  · 记忆面：LoCoMo 全量 5882 turn 完整对话（mteb/LoCoMo BEIR corpus，id 与仓内
    evidence_turns 逐字对齐已验证）→ LLM 译为中文（人名保留）→ 逐 turn 写入灵枢
    （对话原文，不做摘要加工——写入侧加工差异正是各记忆系统的被测对象本身）
  · 查询面：上游英文自然问句 → LLM 译为中文自然问句
  · 答题面：reader 只据注入记忆作答（不足答「无法确定」）→ judge 对上游 gold
    语义判等（correct/incorrect/refused；adversarial gold 空=正确行为拒答）
  · 两臂：
      retrieval     灵枢检索注入（cg.search 阶梯路 top-10，与生产主形态同路）
      full_context  整段对话全量注入（对标 Mem0 论文 Table 2 的 Full-context 72.90）

标尺（Mem0 论文 arXiv:2504.19413 Table 2，agent=GPT-4o-mini）：
  Full-context 72.90 · Mem0ᵍ 68.44 · Mem0 66.88 · Zep 65.99 · LangMem 58.10 ·
  OpenAI memory 52.90 · A-Mem 48.38；Letta Filesystem 复测 74.0（letta.com 2025-08）。
  本评测 reader/judge=deepseek-chat（与同行 GPT-4o-mini 不同档，绝对分含模型差，
  对照时声明；同标尺内两臂之差是检索质量的净效应，与模型无关）。

跑法：
  python -X utf8 -m md_cg.bench_e2e_locomo_qa --translate   # 翻译 5882 turn + 500 问句
  python -X utf8 -m md_cg.bench_e2e_locomo_qa               # 全量 500 题 × 2 臂
  python -X utf8 -m md_cg.bench_e2e_locomo_qa --quick       # 冒烟 3 题（须先完成翻译）
环境：DEEPSEEK_API_KEY；建议 MDCG_UNIFY_QUERY=0（中文问句含英文名时批次15归一有
形态缺陷，见 docs/eval/端到端干扰池评测_v1.1 §4）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg.bench_e2e_judge import DEFAULT_ROOT, llm_chat       # noqa: E402
from md_cg.bench_e2e_qa import (                              # noqa: E402
    JUDGE_SYS, READER_SYS, _cache_call, parse_json_field)

UP = os.path.join(DEFAULT_ROOT, "upstream")
CORPUS_PQ = os.path.join(UP, "corpus.parquet")
ANSWERS = os.path.join(UP, "answers_map.json")
ZH_TURNS = os.path.join(UP, "zh_turns.json")
ZH_QUERIES = os.path.join(UP, "zh_queries.json")
T_CACHE = os.path.join(UP, "translate_cache")

TRANS_TURN_SYS = (
    "你是对话翻译器。把英文对话 turn 逐条译成中文：忠实原义、不压缩不增删；"
    "人名与专有名词保留英文原文（如 Caroline / Ed Sheeran）；说话人前缀保留"
    "（格式「名字： 译文」）。\n只输出一行 JSON：{\"x1\": \"名字： 译文\", ...}"
)
TRANS_Q_SYS = (
    "你是问题翻译器。把英文问句译成自然的中文问句：语气自然、不逐词直译；"
    "人名与专有名词保留英文原文。\n只输出一行 JSON：{\"x1\": \"中文问句\", ...}"
)


def load_corpus():
    import pyarrow.parquet as pq
    t = pq.read_table(CORPUS_PQ)
    ids = t.column("id").to_pylist()
    txts = t.column("text").to_pylist()
    return ids, txts


def _batch(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def translate_all(key, model_cfg, items, batch_n, sys_prompt, out_path,
                  max_tokens=4000):
    """items=[(k, en_text)] → {k: zh}，分片缓存、断点续跑。"""
    os.makedirs(T_CACHE, exist_ok=True)
    out = {}
    if os.path.isfile(out_path):
        out = json.load(open(out_path, encoding="utf-8"))
    todo = [(k, t) for k, t in items if k not in out]
    print(f"[translate:{key}] 已有 {len(out)} / 待译 {len(todo)}"
          f" · engine={model_cfg['model']}@{model_cfg['base']}")
    jobs = list(enumerate(_batch(todo, batch_n)))

    def work(item):
        idx, job = item
        cpath = os.path.join(T_CACHE, f"{key}_{idx:04d}.json")
        if os.path.isfile(cpath):
            return json.load(open(cpath, encoding="utf-8"))
        mapping = {f"x{i}": k for i, (k, _t) in enumerate(job)}
        user = "\n".join(f"x{i}. {t}" for i, (_k, t) in enumerate(job))
        try:
            raw, _u, _d = llm_chat(
                model_cfg["model"], model_cfg["base"], model_cfg["key"],
                [{"role": "system", "content": sys_prompt},
                 {"role": "user", "content": user}],
                timeout=model_cfg["timeout"], max_tokens=max_tokens,
                extra_payload=model_cfg.get("extra"))
            s = re.sub(r"<think>.*?</think>", "", str(raw), flags=re.S)
            obj = {}
            _i, _j = s.find("{"), s.rfind("}")
            if _i >= 0 and _j > _i:
                try:
                    obj = json.loads(s[_i:_j + 1])
                except ValueError:
                    obj = {}
            res = {}
            for tag, zh in obj.items():
                if tag in mapping and isinstance(zh, str) and zh.strip():
                    res[mapping[tag]] = zh.strip()
            if len(res) == len(job):
                json.dump(res, open(cpath, "w", encoding="utf-8"),
                          ensure_ascii=False)
            return res
        except Exception:                                   # noqa: BLE001
            return {}

    n_ok = 0
    with ThreadPoolExecutor(max_workers=model_cfg["workers"]) as ex:
        for res in ex.map(work, jobs):
            out.update(res)
            n_ok += len(res)
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[translate:{key}] 本轮完成 {n_ok}，总 {len(out)}/{len(items)}")
    return out


def build_dialog_pool(ids, zh_turns, root_dir):
    """5882 中文 turn 逐条写入灵枢（对话原文做记忆，无摘要加工）。"""
    root = os.path.join(root_dir, "pools", "dialog_zh")
    if os.path.isfile(os.path.join(root, "_manifest.json")):
        try:
            m = json.load(open(os.path.join(root, "_manifest.json"),
                               encoding="utf-8"))
            if m == {"turns": len(ids)}:
                from md_cg.mdcos import MdCGOS
                return MdCGOS(os.path.join(root, "mem"))
        except Exception:
            pass
    import shutil
    from md_cg.mdcos import MdCGOS
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(root, exist_ok=True)
    cg = MdCGOS(os.path.join(root, "mem"))
    for nid in ids:
        cg.add(nid, zh_turns.get(nid) or "", layer="knowledge",
               verification_basis="data")
    json.dump({"turns": len(ids)},
              open(os.path.join(root, "_manifest.json"), "w", encoding="utf-8"))
    return cg


READER_USER = "问题：{q}\n\n候选记忆：\n{cards}"


def run_one(cfg, cache_dir, qid, qtype, zh_q, en_q, gold, cards_text, arm):
    row = {"qid": qid, "qtype": qtype, "arm": arm, "gold": gold}

    def call_reader():
        return llm_chat(cfg["model"], cfg["base"], cfg["key"],
                        [{"role": "system", "content": READER_SYS},
                         {"role": "user", "content": READER_USER.format(
                             q=zh_q, cards=cards_text)}],
                        timeout=cfg["timeout"], max_tokens=300)

    def call_judge():
        return llm_chat(cfg["model"], cfg["base"], cfg["key"],
                        [{"role": "system", "content": JUDGE_SYS},
                         {"role": "user", "content":
                          f"问题：{en_q}\ngold：{gold or ''}\n"
                          f"模型回答：{row['answer']}"}],
                        timeout=cfg["timeout"], max_tokens=200)

    try:
        pkey = f"{cfg['model']}|{arm}|{qid}|{cards_text[:200]}"
        raw, _t1, _d1, _c1 = _cache_call(cache_dir, "reader",
                                         hashlib.md5(
                                             pkey.encode()).hexdigest(),
                                         call_reader)
        a = parse_json_field(raw, "answer")
        row["answer"] = a if a is not None else (raw or "").strip()[:80]
        jkey = f"{cfg['model']}|{en_q}|{gold}|{row['answer']}"
        raw2, _t2, _d2, _c2 = _cache_call(
            cache_dir, "judge", hashlib.md5(jkey.encode()).hexdigest(),
            call_judge)
        v = parse_json_field(raw2, "verdict")
        row["verdict"] = v if v in ("correct", "incorrect", "refused") else None
        if row["verdict"] is None:
            row["error"] = f"judge 不可解析 {(raw2 or '')[:60]}"
    except Exception as exc:                                # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"
        row.setdefault("answer", "")
        row["verdict"] = None
    return row


def report(rows, title):
    ok = [r for r in rows if r.get("verdict")]
    n = max(len(ok), 1)
    acc = sum(1 for r in ok if r["verdict"] == "correct")
    out = {"n": len(rows), "judged": len(ok), "acc": acc,
           "acc_pct": 100.0 * acc / n, "refused": sum(
               1 for r in ok if r["verdict"] == "refused")}
    by = {}
    for qt in ("single_hop", "multi_hop", "temporal_reasoning",
               "adversarial", "open_domain"):
        rs = [r for r in ok if r["qtype"] == qt]
        if rs:
            c = sum(1 for r in rs if r["verdict"] == "correct")
            by[qt] = f"{100.0*c/len(rs):.1f}%({c}/{len(rs)})"
    print(f"  {title:<14} QA准确率={out['acc_pct']:5.1f}%"
          f"（{acc}/{len(ok)}）  拒答={out['refused']}  分题型: {by}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="LoCoMo QA 同口径对照（中文全对话）")
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    ap.add_argument("--n", type=int, default=0, help="题数（0=全量500）")
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--base-url", default="https://api.deepseek.com/v1")
    ap.add_argument("--key", default="")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--translate", action="store_true",
                    help="只做翻译阶段（5882 turn + 500 问句）")
    ap.add_argument("--lm-studio", action="store_true",
                    help="翻译走 LM Studio 本地模型（localhost:1234/v1，"
                         "自动探测模型名；reader/judge 仍用 --model）")
    ap.add_argument("--batch-turns", type=int, default=8,
                    help="翻译每请求 turn 数（LM Studio 建议 5）")
    ap.add_argument("--batch-q", type=int, default=10,
                    help="问句翻译每请求数（LM Studio 建议 6）")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    if a.quick:
        a.n = 3
    key = a.key or os.environ.get("DEEPSEEK_API_KEY") or ""
    if not key:
        print("[error] 需要 DEEPSEEK_API_KEY 或 --key")
        return 2
    cfg = {"model": a.model, "base": a.base_url, "key": key,
           "timeout": a.timeout, "workers": a.workers}
    print(f"[locomo_qa] 归一层开关 MDCG_UNIFY_QUERY="
          f"{os.environ.get('MDCG_UNIFY_QUERY', '1')}（建议 0，见模块头注）")

    ids, txts = load_corpus()
    answers = json.load(open(ANSWERS, encoding="utf-8"))
    ours = [json.loads(l) for l in open(os.path.join(
        HERE, "data", "benchmarks", "locomo-zh-500", "questions500.jsonl"),
        encoding="utf-8") if l.strip()]
    qs = ours[:a.n] if a.n else ours

    if a.translate or not (os.path.isfile(ZH_TURNS)
                           and os.path.isfile(ZH_QUERIES)):
        tcfg = cfg
        if a.lm_studio:
            with urllib.request.urlopen(
                    "http://localhost:1234/v1/models", timeout=8) as r:
                mids = [m["id"] for m in
                        json.loads(r.read().decode("utf-8"))["data"]
                        if "embed" not in m["id"].lower()]
            if not mids:
                print("[error] LM Studio 无已加载 LLM（仅有 embedding 模型）")
                return 2
            tcfg = {"model": mids[0], "base": "http://localhost:1234/v1",
                    "key": "lm-studio", "timeout": 600,
                    "workers": min(a.workers, 3),
                    # 顶层 reasoning_effort=none 是实测唯一能压住思考的传法
                    # （chat_template_kwargs/enable_thinking 均无效，思考仍吃满
                    # max_tokens；矩阵实验 2026-09-23：none → 0 reasoning 4s/批）
                    "extra": {"reasoning_effort": "none"}}
            print(f"[lm-studio] 使用本地模型 {mids[0]}（并发 {tcfg['workers']}）")
        items_t = list(zip(ids, txts))
        zh_turns = translate_all("turn", tcfg, items_t, a.batch_turns,
                                 TRANS_TURN_SYS, ZH_TURNS,
                                 max_tokens=2000 if a.lm_studio else 4000)
        items_q = [(q["qid"], answers[q["qid"]]["en_q"]) for q in ours
                   if q["qid"] in answers]
        zh_qs = translate_all("q", tcfg, items_q, a.batch_q,
                              TRANS_Q_SYS, ZH_QUERIES,
                              max_tokens=2000 if a.lm_studio else 4000)
        miss_t = len(ids) - len(zh_turns)
        miss_q = len(items_q) - len(zh_qs)
        print(f"[translate] 缺口 turn={miss_t} q={miss_q}"
              f"（缺口>0 可重跑 --translate 续传）")
        if a.translate:
            return 0 if (miss_t == 0 and miss_q == 0) else 1

    zh_turns = json.load(open(ZH_TURNS, encoding="utf-8"))
    zh_qs = json.load(open(ZH_QUERIES, encoding="utf-8"))
    cache_dir = os.path.join(a.data_root, "lq_cache")
    os.makedirs(cache_dir, exist_ok=True)
    from md_cg.mdcos import MdCGOS
    cg = build_dialog_pool(ids, zh_turns, a.data_root)
    # scene → 全对话中文（full-context 臂用）
    scene_turns = {}
    for nid in ids:
        scene_turns.setdefault(nid.split("_session")[0], []).append(nid)

    tasks = []
    for q in qs:
        qid = q["qid"]
        if qid not in answers or qid not in zh_qs:
            continue
        gold = answers[qid]["answer"] or ""
        zh_q = zh_qs[qid]
        en_q = answers[qid]["en_q"]
        # 臂1：灵枢检索注入（生产主形态阶梯路；judge 关——对话原文无 CCG 面）
        res, _m = cg.search(zh_q, k=a.k, judge=False, record=False)
        cards = "\n\n".join(f"【{i}】{zh_turns.get(r[0]['id'], '')}"
                            for i, r in enumerate(res, 1))
        tasks.append((qid, q.get("qtype"), zh_q, en_q, gold, cards,
                      "retrieval"))
        # 臂2：full-context（该 scene 全对话）
        scene = qid.split("_q_")[0]
        full = "\n".join(zh_turns.get(t, "") for t in scene_turns[scene])
        tasks.append((qid, q.get("qtype"), zh_q, en_q, gold, full[:110000],
                      "full_context"))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        rows = list(ex.map(lambda t: run_one(cfg, cache_dir, *t), tasks))
    print(f"[locomo_qa] {len(tasks)} 次 reader+judge 耗时 {time.time()-t0:.0f}s")
    errs = sum(1 for r in rows if r.get("error"))
    print(f"判分失败 {errs} 行\n")
    summary = {"meta": {"model": a.model, "n_q": len(qs), "k": a.k,
                        "unify": os.environ.get("MDCG_UNIFY_QUERY", "1")}}
    for arm in ("retrieval", "full_context"):
        summary[arm] = report([r for r in rows if r["arm"] == arm], arm)
    out = os.path.join(a.data_root, "results",
                       f"locomo_qa_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump({"summary": summary, "rows": rows},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[locomo_qa] 明细 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
