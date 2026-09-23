# -*- coding: utf-8 -*-
"""端到端干扰池评测：确定性裁决层 vs LLM-as-judge（2026-09-23 · 外部建议里程碑）

评测问题：公开数据集 locomo-zh-500 上，当候选池里「错误答案长得像正确答案」时——
  arm_base      裸五路融合排序（无裁决对照）
  arm_firewall  灵枢确定性裁决层（judge_qualification 四态 + judge_ranking 防火墙）
  arm_llm       LLM-as-judge（同一候选面逐卡资格裁决，语义阅读）
  三臂谁能把 gold 守在 top1？退化曲线随干扰浓度如何变化？

公平性三原则：
  1) 同管线：gold 与全部合成干扰走同一 CCG 六要素写入函数，生效条件由节点自身
     字段机械合成（主体/时间窗口/主题），不看题面——两个裁决器都无题面捷径可抄。
  2) 同候选：三臂共享同一融合候选（五路 sum RRF）；firewall 与 LLM 都只做资格
     裁决，裁决机制不同（词面条件四态 vs 语义阅读）。
  3) 可证伪：合成干扰不设任何「方便防火墙剔除」的标记（不适用条件一律诚实写
     「无」）——防火墙若无效、LLM 若翻车，都如实报，不粉饰。

干扰家族（每题合成、按家族顺序截断到 level 条；id 前缀 x_ 保证排在 gold 之后，
  平局兜底偏向 gold——对我方保守）：
  D2 实体互换  摘要中双方名字互换 + 主体换人：「谁说的/谁做的」答案错，词面几乎同款
  D3p/D3m 时间错位  同一事实 ±1 年：查询不含时间词时原则上不可区分（诚实边界）
  D4 否定澄清  「澄清：此前所说「…」并不属实」：否认该事实，词面高度重叠
  D1 同话题硬负例不合成——语料其余 566 条 turn 即天然干扰池，全 level 在场

浓度梯度：level∈{0,1,2,4} = 每题注入前 level 条合成干扰（500 题全部注入、池共享；
  level=0 即零干扰锚点池）。家族级归因在 level=4 池上做。

指标：hit@1/5/10、MRR（各臂排序）；top1 置换归因（gold/x_d2/x_d3/x_d4/天然）；
  gold 被合成干扰压过率；LLM 臂加报 gold-qualified 率 / 弃权率 / 两轮自一致性。

诚实边界：
  · 本评测为 CCG 化写入（已发布 locomo 主链路成绩是五槽裸串口径），零干扰锚点
    与 94.6% 只做量级对照，不做逐位复现声明。
  · 题面为关键词串（与检索同源）；LLM 拿到的查询与引擎完全同面。位置偏差以
    逐位 qualified 率诊断呈现，v1 不做候选旋转。
  · LLM temperature=0 仍非严格确定，以两轮独立调用的一致性量化；结果含缓存
    （--data-root/llm_cache，键含轮次），重跑命中缓存不重复计费。

跑法：
  python -X utf8 -m md_cg.bench_e2e_judge --quick        # 冒烟 20题×level 0,1×无LLM
  python -X utf8 -m md_cg.bench_e2e_judge                # 全量 120题×4级×3臂+LLM两轮
  python -X utf8 -m md_cg.bench_e2e_judge --skip-llm     # 只跑确定性两臂
环境：DEEPSEEK_API_KEY（LLM 臂）；数据落 --data-root（默认 D:/program/test/e2e_judge）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg.mdcos import MdCGOS                             # noqa: E402
from md_cg import nodefile                                 # noqa: E402

DATA_SRC = os.path.join(HERE, "data", "benchmarks", "locomo-zh-500")
DEFAULT_ROOT = r"D:\program\test\e2e_judge"
FUSION_KW = dict(paths=("lexical", "bucket", "entity", "graph", "fuzzy"),
                 fusion="sum")
LEVELS_DEFAULT = (0, 1, 2, 4)
FAMILIES = ("D2", "D3p", "D3m", "D4")       # 每题合成顺序；level 截断
FAM_PREFIX = {"D2": "x_d2", "D3p": "x_d3p", "D3m": "x_d3m", "D4": "x_d4"}


# ---------------------------------------------------------------- 数据装载
def load_src():
    corpus = [json.loads(ln) for ln
              in open(os.path.join(DATA_SRC, "corpus567.jsonl"),
                      encoding="utf-8") if ln.strip()]
    questions = [json.loads(ln) for ln
                 in open(os.path.join(DATA_SRC, "questions500.jsonl"),
                         encoding="utf-8") if ln.strip()]
    return corpus, questions


def speakers_by_scene(corpus):
    m = {}
    for c in corpus:
        scene = c["id"].split("_session")[0]
        m.setdefault(scene, set()).add(c.get("speaker") or "")
    return {k: sorted(v) for k, v in m.items() if len(v) >= 2}


# ---------------------------------------------------------------- CCG 写入面
def ccg_card(summary, identity, time_s, terms, node_id):
    """gold 与合成干扰共用同一写入函数（公平性原则 1）。

    生效条件只含节点自身字段（主体/时间窗口/主题），不含任何题面信息；
    不适用条件一律诚实写「无」——合成干扰不携带可被负条件路剔除的标记。
    """
    terms_s = "、".join(terms)
    lines = [f"{summary}（{identity}，{time_s}）",
             f"# 功能名：会话记忆 {node_id}",
             f"# 生效条件：主体={identity}；时间窗口={time_s}；主题={terms_s}",
             "# 子功能：episodic 会话片段（对话摘要转写）",
             "# 执行：陈述会话事实",
             "# 验证方式：据会话记录核对",
             "# 不适用条件：无"]
    return "\n".join(lines) + "\n"


def _shift_year(time_s, delta):
    return re.sub(r"(\d{4})", lambda m: str(int(m.group(1)) + delta),
                  str(time_s), count=1)


def _swap_names(text, a, b):
    return text.replace(a, "\x00").replace(b, a).replace("\x00", b)


def synth_for_question(q, corpus_map, spk):
    """一题的合成干扰（全家族），返回 [(fam, node_id, card), ...]。"""
    evs = [corpus_map[t] for t in (q.get("evidence_turns") or [])
           if t in corpus_map]
    if not evs:
        return []
    ev = evs[0]
    zf = ev.get("zh_fields") or {}
    summary = str(zf.get("summary") or ev.get("zh") or "")
    identity = str(zf.get("identity") or ev.get("speaker") or "")
    time_s = str(zf.get("time") or "")
    terms = [str(t) for t in (zf.get("terms") or [])]
    scene = ev["id"].split("_session")[0]
    pair = spk.get(scene) or []
    other = next((s for s in pair if s and s != identity), None)
    qid = q["qid"]
    out = []
    if other:                                   # D2 实体互换
        s2 = _swap_names(summary, identity, other)
        t2 = [_swap_names(t, identity, other) for t in terms]
        out.append(("D2", f"{FAM_PREFIX['D2']}_{qid}",
                    ccg_card(s2, other, time_s, t2, f"{FAM_PREFIX['D2']}_{qid}")))
    if time_s:                                  # D3p / D3m 时间错位
        for fam, d in (("D3p", 1), ("D3m", -1)):
            t3 = _shift_year(time_s, d)
            nid = f"{FAM_PREFIX[fam]}_{qid}"
            out.append((fam, nid, ccg_card(summary, identity, t3, terms, nid)))
    s4 = f"澄清：此前所说「{summary}」并不属实"     # D4 否定澄清
    nid = f"{FAM_PREFIX['D4']}_{qid}"
    out.append(("D4", nid, ccg_card(s4, identity, time_s, terms, nid)))
    return out


# ---------------------------------------------------------------- 池构建
def build_pool(level, corpus, questions, corpus_map, spk, root_dir):
    """level=每题注入的合成干扰条数（按 FAMILIES 顺序截断）。带指纹缓存。"""
    synth_all = []          # 全 500 题都合成（池共享、更真实）
    for q in questions:
        synth_all.append(synth_for_question(q, corpus_map, spk))
    n_synth = sum(len(s[:level]) for s in synth_all)
    fp_src = hashlib.md5(
        json.dumps([len(corpus), len(questions)]).encode()).hexdigest()[:8]
    root = os.path.join(root_dir, "pools", f"level{level}")
    manifest = os.path.join(root, "_manifest.json")
    want = {"fp": fp_src, "level": level, "corpus": len(corpus),
            "synth": n_synth}
    if os.path.isfile(manifest):
        try:
            if json.load(open(manifest, encoding="utf-8")) == want \
               and os.path.isdir(os.path.join(root, "mem")):
                return MdCGOS(os.path.join(root, "mem")), n_synth
        except Exception:
            pass                                   # 陈化即重建
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(root, exist_ok=True)
    cg = MdCGOS(os.path.join(root, "mem"))
    cards = {}
    for c in corpus:                              # gold 天然面
        zf = c.get("zh_fields") or {}
        nid = c["id"]
        cards[nid] = ccg_card(str(zf.get("summary") or c.get("zh") or ""),
                              str(zf.get("identity") or c.get("speaker") or ""),
                              str(zf.get("time") or ""),
                              [str(t) for t in (zf.get("terms") or [])], nid)
    for s in synth_all:
        for fam, nid, card in s[:level]:
            assert nid not in cards, f"干扰 id 冲突 {nid}"
            cards[nid] = card
    bad = [nid for nid, cd in cards.items()
           if not nodefile.ccg_completeness(cd)["complete"]]
    assert not bad, f"CCG 六要素不全（不应发生）: {bad[:3]}"
    for nid, card in cards.items():
        cg.add(nid, card, layer="knowledge", verification_basis="data")
    json.dump(want, open(manifest, "w", encoding="utf-8"))
    return cg, n_synth


# ---------------------------------------------------------------- 检索两臂
def run_det_arms(cg, q, k=10):
    gold = set(q.get("evidence_turns") or [])
    base, _mb = cg.search_rrf(q["question"], k=k, judge=False, **FUSION_KW)
    fw, _mf = cg.search_rrf(q["question"], k=k, judge=True,
                            judge_ranking=True, **FUSION_KW)
    return {"gold": gold,
            "base": [r[0]["id"] for r in base],
            "firewall": [r[0]["id"] for r in fw],
            "fw_states": [((r[2] or {}).get("state") if len(r) > 2 else None)
                          for r in fw],
            "base_nodes": [r[0] for r in base],
            "fw_nodes": [r[0] for r in fw]}


# ---------------------------------------------------------------- LLM 裁决
LLM_SYS = (
    "你是记忆系统的资格裁决器。给定一个查询和若干条候选记忆卡，逐条判断该卡"
    "是否有资格作为回答该查询的证据。判定标准：卡的内容真实包含查询所问的事实"
    "（主题一致且事实成立；澄清/否认类内容不构成该事实的证据；主体或时间与查询"
    "冲突时同样不合格）。\n"
    "只输出一行 JSON，不要解释、不要代码围栏，格式：\n"
    '{"verdicts":[{"no":1,"qualified":true,"reason":"不超过20字"},...]}'
)


def llm_chat(model, base, key, messages, timeout=120, max_tokens=1500,
             temperature=0.0, extra_payload=None):
    body = {"model": model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens}
    if extra_payload:
        body.update(extra_payload)
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"].get("content") or ""
    return content, (data.get("usage") or {}), time.time() - t0


def llm_user_prompt(q, cand_nodes):
    lines = [f"查询：{q['question']}", "", "候选记忆卡："]
    for i, nd in enumerate(cand_nodes, 1):
        content = str(nd.get("content") or "")[:400]
        lines.append(f"【{i}】{content}")
        lines.append("")
    lines.append("请逐卡输出资格判定 JSON。")
    return "\n".join(lines)


def parse_verdicts(raw, n):
    """解析 LLM 裁决 JSON → {no: qualified}；解析失败返回 None（≠空判定）。"""
    s = raw or ""
    i, j = s.find("{"), s.rfind("}")
    verdicts = {}
    if i >= 0 and j > i:
        try:
            obj = json.loads(s[i:j + 1])
            for v in obj.get("verdicts") or []:
                no = v.get("no")
                if isinstance(no, int) and 1 <= no <= n:
                    verdicts[no] = bool(v.get("qualified"))
        except ValueError:
            pass
    if not verdicts:                            # 解析失败=该题无裁决（计入 err）
        return None
    return verdicts


def llm_judge_one(cfg, q, cand_nodes, rnd, cache_dir):
    """一轮 LLM 资格裁决（含缓存）。返回 (qualified_ids, tokens, dt, cached)。"""
    prompt = llm_user_prompt(q, cand_nodes)
    key_hex = hashlib.md5(json.dumps(
        [cfg["model"], cfg["base"], prompt, rnd], ensure_ascii=False)
        .encode("utf-8")).hexdigest()
    cpath = os.path.join(cache_dir, key_hex + ".json")
    if os.path.isfile(cpath):
        d = json.load(open(cpath, encoding="utf-8"))
        return (d["qualified"], d["tokens"], 0.0, True)
    raw, usage, dt = llm_chat(cfg["model"], cfg["base"], cfg["key"],
                              [{"role": "system", "content": LLM_SYS},
                               {"role": "user", "content": prompt}],
                              timeout=cfg["timeout"])
    v = parse_verdicts(raw, len(cand_nodes))
    if v is None:
        raise ValueError(f"LLM 输出不可解析：{raw[:120]!r}")
    ids = [cand_nodes[no - 1]["id"] for no in sorted(v) if v[no]]
    d = {"qualified": ids, "raw": raw[:800],
         "tokens": int(usage.get("total_tokens") or 0), "round": rnd}
    json.dump(d, open(cpath, "w", encoding="utf-8"), ensure_ascii=False)
    return ids, d["tokens"], dt, False


def llm_reorder(base_ids, qualified):
    """qualified 优先（保持基序），其余殿后——与防火墙 keep-降权同构。"""
    qs = [i for i in base_ids if i in set(qualified)]
    rest = [i for i in base_ids if i not in set(qualified)]
    return qs + rest


# ---------------------------------------------------------------- 指标
def rank_of(gold, ids):
    return next((i for i, nid in enumerate(ids, 1) if nid in gold), 0)


def classify(nid):
    for fam, p in FAM_PREFIX.items():
        if nid.startswith(p + "_"):
            return fam
    return "natural" if not nid.startswith("x_") else "x_other"


def arm_metrics(rows, key):
    n = len(rows)
    st = {"h1": 0, "h5": 0, "h10": 0, "mrr": 0.0,
          "top1": {"gold": 0, "D2": 0, "D3p": 0, "D3m": 0, "D4": 0,
                   "natural": 0, "x_other": 0},
          "gold_outranked_by_synth": 0}
    for r in rows:
        ids = r[key]
        gold = r["gold"]
        rk = rank_of(gold, ids)
        if rk == 1:
            st["h1"] += 1
        if 0 < rk <= 5:
            st["h5"] += 1
        if 0 < rk <= 10:
            st["h10"] += 1
        if rk:
            st["mrr"] += 1.0 / rk
        st["top1"][classify(ids[0])] += 1 if ids else 0
        gr = rk
        synth_before_gold = any(
            nid.startswith("x_")
            for nid in ids[:(gr - 1 if gr else len(ids))])
        if synth_before_gold:
            st["gold_outranked_by_synth"] += 1
    return st


def fmt_row(name, st, n):
    t1 = st["top1"]
    return (f"  {name:<10} hit@1={100*st['h1']/n:5.1f}%  hit@5={100*st['h5']/n:5.1f}%"
            f"  hit@10={100*st['h10']/n:5.1f}%  MRR={st['mrr']/n:.4f}"
            f"  top1置换[D2={t1['D2']} D3={t1['D3p']+t1['D3m']} D4={t1['D4']}"
            f" 天然={t1['natural']}]")


# ---------------------------------------------------------------- 主流程
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="端到端干扰池评测：确定性裁决层 vs LLM-as-judge")
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    ap.add_argument("--n", type=int, default=120, help="评测题数（种子采样）")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--levels", default="0,1,2,4")
    ap.add_argument("--arms", default="base,firewall,llm")
    ap.add_argument("--rounds", type=int, default=2, help="LLM 独立轮数")
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--base-url", default="https://api.deepseek.com/v1")
    ap.add_argument("--key", default="")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--quick", action="store_true", help="冒烟：20题×0,1级×无LLM")
    ap.add_argument("--skip-llm", action="store_true")
    a = ap.parse_args(argv)

    if a.quick:
        a.n, a.levels, a.skip_llm = 20, "0,1", True
    levels = [int(x) for x in a.levels.split(",") if x.strip() != ""]
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    use_llm = ("llm" in arms) and not a.skip_llm
    key = a.key or os.environ.get("DEEPSEEK_API_KEY") or ""
    if use_llm and not key:
        print("[error] LLM 臂需要 DEEPSEEK_API_KEY 或 --key（或 --skip-llm）")
        return 2

    os.makedirs(os.path.join(a.data_root, "results"), exist_ok=True)
    cache_dir = os.path.join(a.data_root, "llm_cache")
    os.makedirs(cache_dir, exist_ok=True)

    corpus, questions = load_src()
    corpus_map = {c["id"]: c for c in corpus}
    spk = speakers_by_scene(corpus)
    rnd = random.Random(a.seed)
    sample = sorted(rnd.sample(questions, min(a.n, len(questions))),
                    key=lambda q: q["qid"])
    print(f"[e2e_judge] 语料 {len(corpus)} · 题目 {len(questions)} · "
          f"采样 {len(sample)}（seed={a.seed}） · levels={levels} · arms={arms}"
          + (f" · LLM={a.model}×{a.rounds}轮" if use_llm else " · 无LLM"))
    print(f"[e2e_judge] 数据根：{a.data_root}")

    all_out = {"meta": {"seed": a.seed, "n": len(sample), "levels": levels,
                        "model": a.model if use_llm else None,
                        "k": a.k}, "levels": {}}
    for lv in levels:
        t0 = time.time()
        cg, n_synth = build_pool(lv, corpus, questions, corpus_map, spk,
                                 a.data_root)
        print(f"\n===== level {lv}（池={len(corpus)+n_synth} 节点，"
              f"合成干扰 {n_synth} 条）· 建池 {time.time()-t0:.1f}s =====")
        rows = []
        for q in sample:
            det = run_det_arms(cg, q, k=a.k)
            rows.append({"qid": q["qid"], "qtype": q.get("qtype"),
                         "question": q["question"], **det})
        n = len(rows)
        lv_out = {"pool": len(corpus) + n_synth, "synth": n_synth,
                  "rows_count": n}
        for arm in ("base", "firewall"):
            if arm in arms:
                st = arm_metrics(rows, arm)
                print(fmt_row(arm, st, n))
                lv_out[arm] = st
        # 四态分布（firewall 诊断面）
        if "firewall" in arms:
            sd = {"ACCEPT": 0, "DEFER": 0, "REJECT": 0, "BLINDSPOT": 0}
            for r in rows:
                for s in r["fw_states"]:
                    sd[s] = sd.get(s, 0) + 1
            tot = sum(sd.values()) or 1
            print("  firewall四态(top10): " + " ".join(
                f"{k2}={v}({100*v/tot:.0f}%)" for k2, v in sd.items() if v))
            lv_out["fw_states"] = sd
        # LLM 臂
        if use_llm:
            cfg = {"model": a.model, "base": a.base_url, "key": key,
                   "timeout": a.timeout}
            llm_rows = []
            t1 = time.time()

            def work(args):
                r, rd = args
                qobj = {"qid": r["qid"], "question": r["question"]}
                try:
                    qids, toks, dt, cached = llm_judge_one(
                        cfg, qobj, r["base_nodes"], rd, cache_dir)
                    return {"qid": r["qid"], "round": rd, "qualified": qids,
                            "tokens": toks, "latency": dt, "cached": cached,
                            "order": llm_reorder(r["base"], qids),
                            "gold": r["gold"], "base": r["base"]}
                except Exception as exc:                   # noqa: BLE001
                    return {"qid": r["qid"], "round": rd, "error":
                            f"{type(exc).__name__}: {exc}", "gold": r["gold"],
                            "base": r["base"], "order": r["base"],
                            "qualified": None, "tokens": 0, "latency": 0.0,
                            "cached": False}
            tasks = [(r, rd) for rd in range(1, a.rounds + 1) for r in rows]
            with ThreadPoolExecutor(max_workers=a.workers) as ex:
                llm_rows = list(ex.map(work, tasks))
            for rd in range(1, a.rounds + 1):
                rr = [x for x in llm_rows if x["round"] == rd]
                for x in rr:
                    x_ref = next(y for y in rows if y["qid"] == x["qid"])
                    x["order"] = (llm_reorder(x_ref["base"], x["qualified"])
                                  if x["qualified"] is not None
                                  else x_ref["base"])
                rd_rows = [{"gold": x["gold"], "llm": x["order"]} for x in rr]
                st = arm_metrics(
                    [{"gold": d["gold"], "llm": d["llm"]} for d in rd_rows],
                    "llm")
                errs = sum(1 for x in rr if x.get("error"))
                cached = sum(1 for x in rr if x.get("cached"))
                toks = sum(x["tokens"] for x in rr)
                print(fmt_row(f"llm(r{rd})", st, n)
                      + f"  err={errs} cache={cached} tok={toks}")
                lv_out[f"llm_r{rd}"] = st
                lv_out[f"llm_r{rd}_diag"] = {"errors": errs,
                                             "cached": cached, "tokens": toks}
            # gold-qualified 率 + 弃权率（round1）
            r1 = {x["qid"]: x for x in llm_rows if x["round"] == 1}
            gq = ab = 0
            for x in r1.values():
                if x["qualified"] is None:
                    continue
                if not x["qualified"]:
                    ab += 1
                elif set(x["qualified"]) & x["gold"]:
                    gq += 1
            print(f"  llm诊断: gold获qualified={100*gq/n:.1f}%  "
                  f"全弃权={100*ab/n:.1f}%")
            lv_out["llm_diag"] = {"gold_qualified": gq, "abstain": ab}
            # 两轮自一致性
            if a.rounds >= 2:
                r2 = {x["qid"]: x for x in llm_rows if x["round"] == 2}
                same_top = agree_v = pair = 0
                for qid, x1 in r1.items():
                    x2 = r2.get(qid)
                    if not x2 or x1["qualified"] is None \
                       or x2["qualified"] is None:
                        continue
                    pair += 1
                    if x1["order"][:1] == x2["order"][:1]:
                        same_top += 1
                    s1, s2 = set(x1["qualified"]), set(x2["qualified"])
                    if s1 == s2:
                        agree_v += 1
                if pair:
                    print(f"  llm自一致性: top1一致={100*same_top/pair:.1f}%  "
                          f"qualified集一致={100*agree_v/pair:.1f}%  "
                          f"(n={pair})")
                lv_out["llm_selfconsistency"] = {
                    "top1": same_top, "set": agree_v, "pairs": pair}
            print(f"  LLM 臂耗时 {time.time()-t1:.1f}s")
            # 逐题留档（gold 序列化-safe）
            for x in llm_rows:
                if isinstance(x.get("gold"), set):
                    x["gold"] = sorted(x["gold"])
            lv_out["llm_rows"] = llm_rows
        all_out["levels"][lv] = lv_out
        # 行级明细落盘（报告取证用；文件名含采样指纹，防不同规模运行互相覆盖）
        detail = [{"qid": r["qid"], "qtype": r["qtype"], "gold":
                   sorted(r["gold"]), "base": r["base"],
                   "firewall": r["firewall"]} for r in rows]
        json.dump(detail, open(os.path.join(
            a.data_root, "results",
            f"detail_L{lv}_n{len(sample)}_s{a.seed}.json"), "w",
            encoding="utf-8"), ensure_ascii=False, indent=1)

    out_path = os.path.join(a.data_root, "results",
                            f"summary_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(all_out, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n[e2e_judge] 完成。汇总 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
