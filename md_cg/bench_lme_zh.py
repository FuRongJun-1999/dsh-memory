# -*- coding: utf-8 -*-
"""LongMemEval-S 中文结构层小样本探针（默认 20 题 gold + 180 干扰 = 池 200）。

被测假设（用户提出）：写入时把英文 turn「翻译为结构化中文」，让中文查询也能
零-LLM 检索；同时保留英文原文供词法路，避免「翻译即断链」。

先验（eval_common.calibrate_turn 注释）：v1 五要素模板是**同质模板词**，
抽样 3.3% < legacy 16% —— 同质模板对词法是净稀释。故中文层设计红线：
  · 只放**特异词**（人名/日期/实体/意图/主题），禁「用户/会话/记录/关于」等同质词；
  · 极短（≤60 汉字），不加任何固定槽位前缀（前缀=全体同质词=纯稀释）；
  · 英文原文一字不动，中文层是**附加**而非替换。

四臂（只变 写入内容 / 查询语言，其余全同）：
  A legacy   裸文本                + 英文原问
  B jaccard  裸文本                + 英文原问   ← 已修底座
  C jaccard  裸文本 + 中文层(20条)  + 英文原问   ← 测「稀释」
  D jaccard  裸文本 + 中文层(20条)  + 中文问     ← 测「增益」

池 200 条 = 20 条 gold（20 题各取 evidence_turns[0]）+ 180 条随机干扰。
随机基线 hit@1 = 20/200 = 10%（报告须以此为参照，不能只看 0 个百分点）。

跑法：
    python -m md_cg.bench_lme_zh --build        # 采样池 + 调 LLM 生成中文层（落缓存）
    python -m md_cg.bench_lme_zh                # 四臂评测
    python -m md_cg.bench_lme_zh --n-q 20 --n-distract 180
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from md_cg import eval_common as ec
from md_cg.bench_longmem import GROUPS

MODEL = os.environ.get("ZH_PROBE_MODEL") or "deepseek-flash"
BASE = "https://api.deepseek.com/v1"
DIR = os.path.join(ec.EXT, "zh_probe")
POOL = os.path.join(DIR, "pool.jsonl")
CACHE = os.path.join(DIR, "cache.json")
# 中文层 / 中文查询词的**真源文件**：由会话模型直接产出并落盘，脚本只读。
MAN_ZH = os.path.join(DIR, "manual_zh.json")
MAN_Q = os.path.join(DIR, "manual_q.json")
ROOT_A = os.path.join(ec.HERE, "_md_cg_eval_zhprobe_a")
# 版本化 root：写入加工改版必须换名。build_eval_cg 的幂等按**节点数**判断
# （have >= n_rows），同节点数的旧加工库会被静默复用——首轮 C 臂就会因此
# 拿到旧的「整句翻译」中文层，实验白跑。
ROOT_C = os.path.join(ec.HERE, "_md_cg_eval_zhprobe_c2_bag")
# 「中文层做唯一索引、原文只做载荷」架构的验证库：正文只放中文层，英文原文不入库。
ROOT_E = os.path.join(ec.HERE, "_md_cg_eval_zhprobe_e_zhonly")
ROOT_F = os.path.join(ec.HERE, "_md_cg_eval_zhprobe_f_zhpool")
POOL20 = os.path.join(DIR, "pool20.jsonl")     # 只含 20 条 gold（隔离语言隔离假象）

# 探针实测（2026-09-11）三则：
#  1) deepseek-flash / deepseek-v4-pro **均为推理模型**（简单任务 reasoning_tokens
#     就占 36/38）。**长 prompt 让推理失控**：「6 条硬约束+示例」版在
#     max_tokens=2000 时 completion 全烧在 reasoning 上、content 返回空串
#     （finish_reason=length）→ prompt 必须极短，额度须 ≥1200。
#  2) 首版 prompt「译成中文检索词」被模型理解成**整句翻译**（均 89.9 字，且带
#     「用户/我/的」等同质词）→ 实测 C 15% < B 20%，即**净稀释**。本轮改真词袋。
#  3) 写入侧若是词袋，查询侧必须**同样词袋化**（自然语言长句与词袋的 bigram 交集
#     很小）→ 否则两侧不同源，「翻译即断链」的变体。
# 另：首轮 zh_question 只给 max_tokens=120 → 推理烧空 content → 静默 fallback
# 英文原问，导致 D 臂逐项等于 C 臂（假结论）。额度不足即为该类静默失效的根源。
ZH_PROMPT = """从下面英文里抽出中文关键词：只输出名词与动词的中文词，逗号分隔，一行。不要句子、不要「我/你/的/了/是/在」这类虚词、不要解释。英文：
"""

ZH_Q_PROMPT = """从下面英文问题里抽出中文关键词：只输出名词与动词的中文词，逗号分隔，一行。不要句子、不要虚词、不要解释。问题："""


# ------------------------------------------------------------------ LLM
def _llm(messages, max_tokens=400, retries=3):
    from md_cg.bench_task_ab_llm import llm_chat
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("需要 DEEPSEEK_API_KEY")
    last = None
    for i in range(retries):
        try:
            content, usage, dt = llm_chat(MODEL, BASE, key, messages,
                                          timeout=120, max_tokens=max_tokens,
                                          temperature=0.0)
            return content, usage
        except Exception as exc:                     # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"LLM 调用失败：{type(last).__name__}: {last}")


# 条件空间字段名：中文标签 → eval_common 口径
_COND_KEYS = {"观测位置": "observation_position", "观测工具": "observation_tool",
              "时间窗口": "time_window", "存在约束": "existence_constraint"}
_DEFAULT_COND = {"observation_position": "会话陈述", "observation_tool": "会话记录",
                 "existence_constraint": "公开"}


def _load_json(p):
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load_manual():
    """读入会话模型直接产出的中文层 / 中文查询词（零 API 依赖）。

    为什么不由本脚本调 LLM：探针实测（2026-09-11）deepseek-flash 与
    deepseek-v4-pro **都是推理模型**，该任务上 completion 全烧在 reasoning
    上、content 返回空串（首轮 0/20；次轮 13/20 且形态是整句翻译）。故改为
    会话模型本人产出并落盘、脚本只读文件——顺带消除「额度不足 → 静默
    fallback 成英文原问」这类失效模式（次轮 D 臂逐项等于 C 臂即由此而来）。
    """
    return _load_json(MAN_ZH), _load_json(MAN_Q)


def _cond_of(z):
    """从中文层的「条件=观测位置:…|观测工具:…|…」抽条件空间 dict。"""
    m = re.search(r"条件=([^；;]+)", z or "")
    if not m:
        return None
    out = {}
    for part in re.split(r"[|｜]", m.group(1)):
        kv = re.split(r"[:：]", part, 1)
        if len(kv) == 2 and kv[0].strip() in _COND_KEYS:
            out[_COND_KEYS[kv[0].strip()]] = kv[1].strip()
    return out or None


def _load_cache():
    if os.path.isfile(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(c):
    os.makedirs(DIR, exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)


def zh_layer(turn, cache):
    """一条 turn → 中文词袋。缓存 key 带版本号：prompt 改版必须失效旧缓存。

    不传 speaker：角色标签（user/assistant）是**全体同质词**，翻成「用户」只会
    稀释词法信号（首轮实测即如此）。date 保留——它是特异词。
    """
    key = "L2:" + turn["id"]
    if key in cache:
        return cache[key]
    msg = [{"role": "user", "content":
            ZH_PROMPT + json.dumps({"date": turn.get("date"),
                                    "text": turn.get("text")},
                                   ensure_ascii=False)}]
    s = ""
    for mt in (1200, 2600):          # 推理模型额度被 reasoning 吃光 → 空 content，故加额重试
        content, _u = _llm(msg, max_tokens=mt)
        s = content or ""
        s = re.sub(r"```.*?```", " ", s, flags=re.S)
        s = re.sub(r"(人物|日期|实体|意图|主题)\s*[:：|]", " ", s)
        s = " ".join(s.split()).strip(" ,，、|")
        if s:
            break
    cache[key] = s
    return s


def zh_question(q, cache):
    """英文问题 → 中文关键词（与写入侧同源；额度须 ≥1200，否则推理烧空 content）。"""
    key = "Q2:" + q["qid"]
    if key in cache:
        return cache[key]
    content, _u = _llm([{"role": "user",
                         "content": ZH_Q_PROMPT + q["question"]}], max_tokens=1200)
    s = re.sub(r"```.*?```", " ", content or "", flags=re.S)
    cache[key] = " ".join(s.split()).strip(" ,，、")
    if not cache[key]:
        raise RuntimeError("查询侧关键词为空（额度被 reasoning 吃光）")
    return cache[key]


# ------------------------------------------------------------------ 池
def build_pool(n_q, n_distract, seed=7):
    """采样：n_q 题（分组覆盖）各取 evidence_turns[0] 为 gold，再取干扰。"""
    if os.path.isfile(POOL):
        with open(POOL, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    rows = list(ec.iter_jsonl(ec.LM_H))
    byid = {r["id"]: r for r in rows}
    qs = ec.load_questions("lm")
    rng = random.Random(seed)
    per = max(1, n_q // len(GROUPS))
    picked, gold_ids, chosen = [], set(), []
    for gname in GROUPS:
        qtypes = GROUPS[gname]
        cand = [q for q in qs if q["qtype"] in qtypes and q.get("evidence_turns")]
        rng.shuffle(cand)
        for q in cand:
            if len([p for p in picked if p["_g"] == gname]) >= per:
                break
            tid = q["evidence_turns"][0]
            if tid not in byid or tid in gold_ids:
                continue
            gold_ids.add(tid)
            picked.append({**byid[tid], "_g": gname, "_gold": True})
            chosen.append(q)
    pool = list(picked)
    rest = [r for r in rows if r["id"] not in gold_ids]
    pool += rng.sample(rest, min(n_distract, len(rest)))
    os.makedirs(DIR, exist_ok=True)
    with open(POOL, "w", encoding="utf-8") as f:
        for r in pool:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(DIR, "questions.json"), "w", encoding="utf-8") as f:
        json.dump(chosen, f, ensure_ascii=False, indent=1)
    return pool


def load_questions_zh():
    with open(os.path.join(DIR, "questions.json"), encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ 建库 / 评测
def build(root, pool, zh_of=None, rebuild=False, zh_only=False, corpus=None):
    """zh_of: turn_id → 中文层；None = 裸文本库。

    zh_only=True → **纯中文索引**：正文只放中文层，英文原文不入库（供「中文检索、
    原文只做载荷回填」架构验证）。无中文层的行退化为裸英文——本轮 180 条干扰项
    未译，故 E 臂存在「语言隔离」：中文查询几乎不可能命中英文干扰项，其 hit 是
    上界而非全译库真值。故另设 F 臂（池只含 20 条 gold、正文全中文）隔离该假象，
    单测中文层自身的可区分性。
    """
    def calib(r, ctx=None):
        z = zh_of.get(r["id"]) if zh_of else None
        cs = dict(_DEFAULT_COND)
        if z:
            cs = _cond_of(z) or cs      # 条件空间逐条来自中文层，而非全局写死
        if zh_only:
            return (z or ec.lm_turn_text(r)), [], cs
        body = ec.lm_turn_text(r)
        if z:
            body = body + "\n" + z
        return body, [], cs
    return ec.build_eval_cg(None, root, corpus or POOL, ec.lm_turn_text, "lmezh",
                            calib_of=calib if zh_of else None, rebuild=rebuild)


def eval_arm(cg, questions, qtext_of, k=5):
    rows = []
    for q in questions:
        qq = dict(q)
        qq["question"] = qtext_of(q)
        rows += ec.evaluate_group(cg, [qq], k=k, paths=ec.PATHS, verbose=False)
    return ec.summarize(rows, k=k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-q", type=int, default=20)
    ap.add_argument("--n-distract", type=int, default=180)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--build", action="store_true", help="只生成池与中文层")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    pool = build_pool(args.n_q, args.n_distract)
    golds = [r for r in pool if r.get("_gold")]
    qs = load_questions_zh()
    print(f"池 {len(pool)} 条（gold {len(golds)} / 干扰 "
          f"{len(pool) - len(golds)}），题 {len(qs)} 道，随机基线 hit@1="
          f"{len(golds) / len(pool):.1%}")

    cache = _load_cache()
    man_zh, man_q = _load_manual()
    for tid, v in man_zh.items():        # 会话模型产出 → 直接进缓存，零 API
        cache["L2:" + tid] = v
    for qid, v in man_q.items():
        cache["Q2:" + qid] = v
    print(f"中文层：本地 {len(man_zh)} 条（查询词本地 {len(man_q)} 条），"
          f"缓存合计 {len(cache)} 条，模型 {MODEL}（本轮不调用）")

    def work(r):
        try:
            return r["id"], zh_layer(r, cache), None
        except Exception as exc:                      # noqa: BLE001
            return r["id"], "", f"{type(exc).__name__}: {exc}"

    zh = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (tid, s, err) in enumerate(ex.map(work, golds), 1):
            if err:
                print(f"  [{i}/{len(golds)}] {tid} 失败：{err}")
            else:
                zh[tid] = s
    _save_cache(cache)
    okzh = [v for v in zh.values() if v]
    print(f"中文层成功 {len(okzh)}/{len(golds)}，平均长度 "
          f"{sum(len(v) for v in okzh) / max(1, len(okzh)):.1f} 字")
    for t in okzh[:5]:
        print("   ·", t[:110])

    if args.build:
        print("（--build 只生成，不评测）")
        return
    if not okzh:
        print("中文层为空，终止")
        return 1

    qzh = {}
    for q in qs:
        try:
            qzh[q["qid"]] = zh_question(q, cache)
        except Exception as exc:                      # noqa: BLE001
            print(f"  问题翻译失败 {q['qid']}：{exc}")
            qzh[q["qid"]] = q["question"]
    _save_cache(cache)

    en = lambda q: q["question"]
    zhq = lambda q: qzh.get(q["qid"]) or q["question"]

    # 只含 gold 的 20 条池：E 臂的「语言隔离」假象在其中被消除（全部是中文文档）
    with open(POOL20, "w", encoding="utf-8") as f:
        for r in golds:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    import md_cg.mdcg as m
    results = {}
    arms = (
        ("A legacy  裸+英问", ROOT_A, POOL, False, False, en, "legacy"),
        ("B jaccard 裸+英问", ROOT_A, POOL, False, False, en, "jaccard"),
        ("C jaccard 中+英问", ROOT_C, POOL, True, False, en, "jaccard"),
        ("D jaccard 中+中问", ROOT_C, POOL, True, False, zhq, "jaccard"),
        ("E 纯中索引+中问", ROOT_E, POOL, True, True, zhq, "jaccard"),
        ("F 纯中池+中问", ROOT_F, POOL20, True, True, zhq, "jaccard"),
        ("G 纯中池+英问", ROOT_F, POOL20, True, True, en, "jaccard"),
    )
    for tag, root, corpus, usezh, zonly, qf, mode in arms:
        m.SCORE_MODE = mode
        cg = build(root, pool, zh_of=zh if usezh else None, rebuild=args.rebuild,
                   zh_only=zonly, corpus=corpus)
        ec.install_read_cache(cg)
        results[tag] = eval_arm(cg, qs, qf, k=args.k)
        print(f"  {tag}: hit@1 {results[tag]['hit@1']:.1%} "
              f"hit@{args.k} {results[tag][f'hit@{args.k}']:.1%} "
              f"MRR {results[tag]['mrr']:.3f}")

    # 命中后回填原始英文原文：原文不进索引、只做载荷 → 验证「中文检索→英文返回」链路
    m.SCORE_MODE = "jaccard"
    cg_e = build(ROOT_E, pool, zh_of=zh, corpus=POOL, zh_only=True)
    ec.install_read_cache(cg_e)
    payload = {r["id"]: ec.lm_turn_text(r) for r in pool}
    line = results["E 纯中索引+中问"]["score_p10"]
    print(f"\n回填验证（中文命中 → 确认匹配 → 返回英文原文；原文不在索引内）："
          f"\n  匹配确认线 = 正例 Top-1 分 p10 = {line:.4f}"
          f"（低于线判未匹配，不回填原文）")
    conf_n = conf_hit = 0
    for q in qs:
        res, _meta = ec.run_query(cg_e, zhq(q), k=1, paths=ec.PATHS)
        sc = res[0][1] if res else 0.0
        if sc >= line:
            conf_n += 1
            if ec.first_evidence_rank(res, set(q.get("evidence_turns") or [])):
                conf_hit += 1
    print(f"  确认匹配 {conf_n}/{len(qs)} 题，其中真命中 {conf_hit} → "
          f"确认后精度 {conf_hit / max(1, conf_n):.1%}")
    for q in qs[:2]:
        res, _meta = ec.run_query(cg_e, zhq(q), k=2, paths=ec.PATHS)
        print(f"  中文查询: {zhq(q)}")
        for it in res[:2]:
            nid, sc = it[0]["id"], it[1]
            verdict = "确认匹配→回填" if sc >= line else "未确认→不回填"
            print(f"   · {nid} 分={sc:.4f} [{verdict}] 载荷原文: "
                  f"{payload.get(nid, '')[:70]}")

    ec.print_table("LongMemEval-S 中文层探针（%d 题 / 池 %d）"
                   % (len(qs), len(pool)), results, k=args.k)
    ec.save_result("zh_probe.json", {
        "dataset": "LongMemEval-S slice", "model": MODEL,
        "pool": len(pool), "n_q": len(qs), "baseline_hit1": len(golds) / len(pool),
        "arms": results,
        "zh_layer_samples": okzh[:20],
        "questions_zh": qzh,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
