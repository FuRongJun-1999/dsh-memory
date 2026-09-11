# -*- coding: utf-8 -*-
"""公开基准评测公共层：LongMemEval-S / LoCoMo → 统一格式 → 机判指标。

评测口径（诚实条款，报告必须原样声明）：
  * hit@K 为「证据命中」机判：Top-K 至少含一条证据 turn（LongMemEval 用
    answer_session_ids 映射的证据集，LoCoMo 用 qrels 标注），非 LLM-judge，
    与论文口径（LLM 判 answer 文本正确）不可直接比较，仅用于系统间同口径对比。
  * 负例拒答（refusal）：Top-1 融合分 < 阈值线判为拒答。线 = 该数据集正例
    hit@1 题 Top-1 分的 10 分位（各数据集独立校准），报告附校准明细与敏感性。
  * LongMemEval-S 实测无 abstention 题（该类仅 M 版有），负例组以 LoCoMo
    adversarial + 自建 bench 噪声层承担。

统一题格式（两个数据集转换后一致；转换产物为 data/external/ 下的本地派生副本）：
    {"qid", "qtype", "question", "answer", "evidence_turns": [turn_id, ...]}
统一语料行：{"id", "text", ...}（建库时日期/说话人内联进文本供词法路召回）

被测 API：MdCGOS(root).add / .search_rrf（四路 RRF：lexical,bucket,entity,graph）。
评测库独立于主库：_md_cg_eval_longmem / _md_cg_eval_locomo（.gitignore 已盖）。

双口径（评测设计核心，报告须分栏声明）：
  口径 A legacy  —— 原始 turn 直接入库（corpus.marks=False 同形的「旧库迁移
                   对照物」）。此形态下 entity 路无 tags 恒空、负路由无条件
                   结构恒不触发、judge 走 legacy 分支：测的是检索底座下界。
  口径 B calibrated —— 确定性白箱标定器把 turn 加工为 CCG 五要素 md 条目
                   （生效/不适用条件、子功能、执行、验证方式 + tags +
                   condition_space），再入库。测的是记忆系统完整形态
                   （写入标定管线 + 四路召回 + 负路由 + 四态）。

标定红线（诚实条款）：
  * 确定性：标定器是纯规则函数，零 LLM、零第三方依赖，同输入必同输出，
    标定器源码随报告公开，第三方可重放；
  * 盲于查询集：标定只读 turn 自身字段（说话人/时间/正文句式），不读任何
    question/answer 字段——否则即数据泄漏，评测作废。
"""
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

EXT = os.path.join(HERE, "data", "external")
RESULTS = os.path.join(EXT, "eval_results")
ROOT_LM = os.path.join(HERE, "_md_cg_eval_longmem")
ROOT_LC = os.path.join(HERE, "_md_cg_eval_locomo")

LM_Q = os.path.join(EXT, "longmemeval", "lme_s_questions.jsonl")
LM_H = os.path.join(EXT, "longmemeval", "lme_s_haystack.jsonl")
LC_Q = os.path.join(EXT, "locomo", "locomo_questions.jsonl")
LC_CORPUS = os.path.join(EXT, "locomo", "locomo_corpus.jsonl")

ROOT_LM_CAL = ROOT_LM + "_cal"      # 口径 B 独立库（标定形态）
ROOT_LC_CAL = ROOT_LC + "_cal"

PATHS = ("lexical", "bucket", "entity", "graph")   # 引擎默认四路 RRF
PATHS_CAL = PATHS + ("semantic",)   # 口径 B：显式启用条件结构路（负路由所在）


def unlock_global_cap():
    """评测口径：解除 GLOBAL_CAP 截断（bench_membench patch_lexical_full 同法）。

    默认 GLOBAL_CAP=500 会把 LIKE 预筛命中按「插入序」截到前 500 条再打分；
    大型英文语料（turn 高度互相似）预筛命中数千条 → 证据 turn 被插入序随机
    截掉，检索质量混入插入序 lottery（sanity：证据原文自检索仅 10% hit@1）。
    评测主口径解除之，只测排序质量。mdcg 与 mdcos 各持一份 from-import 值，
    必须双改（test_p43_pooling 先例）。
    """
    import md_cg.mdcg as m
    import md_cg.mdcos as mo
    m.GLOBAL_CAP = 10 ** 9
    mo.GLOBAL_CAP = 10 ** 9


def use_jaccard():
    """评测口径：词法打分切 jaccard（对称归一化，长度自惩罚）。

    默认 legacy（|qb∩db|/|qb|）只归一化查询侧——长 turn 语料里证据被长文档
    挤出 Top-5，LongMemEval-S 上 precise/temporal/reference 的 hit@1 全为 0%。
    切 jaccard 后同口径实测：precise 0%→8.97% / temporal 0%→6.77% /
    interference 1.28%→20.51% / reference 0%→3.76%（与 Rust
    `mdcg-eval --score jaccard` 及既有 trec_longmem_jac.json 逐位一致）。

    只改 mdcg 一处即可（不像 GLOBAL_CAP 被 mdcos from-import 成副本）：
    `lexical_sim` 在自身模块内引用全局 SCORE_MODE，且 mdcos 的 MdCGOS 继承
    MdCG._score，读的是同一份。

    **仅作评测口径**：主库（短条目）不切——短文档上 jaccard 会退化
    （test_p17_predict G4：可预测锚点由因果起点 a 错配到语义邻居 x）。
    """
    import md_cg.mdcg as m
    m.SCORE_MODE = "jaccard"


def iter_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_questions(ds, qtypes=None):
    """ds: 'lm' | 'lc'。qtypes 过滤题型（None=全部）。"""
    path = LM_Q if ds == "lm" else LC_Q
    rows = list(iter_jsonl(path))
    if qtypes:
        rows = [r for r in rows if r["qtype"] in qtypes]
    return rows


def sample_questions(rows, n, seed=7):
    if not n or n >= len(rows):
        return rows
    return random.Random(seed).sample(rows, n)


# ------------------------------------------------------------------ 建库

def lm_turn_text(t):
    """LongMemEval turn → 入库文本（日期内联，词法路可召回时间词）。"""
    return f"{t['speaker']}: {t['text']} [{t['date']}]" if t.get("speaker") \
        else f"{t['text']} [{t['date']}]"


def lc_turn_text(r):
    """LoCoMo turn → 入库文本（title 含 Data time 时间戳，内联保序）。"""
    return f"{r['text']} [{r['title']}]" if r.get("title") else r["text"]


# ---------------- 白箱标定器（口径 B；纯规则、确定性、盲于查询集） ----------------

# 句首功能词表：`[A-Z][a-z]+` 实体近似会把句首大写词误抽为实体，予以排除。
# 词表固定随报告公开——它决定实体抽取边界，属标定器配置的一部分。
_STOP_HEADS = frozenset(
    "I We You They He She It This That There Then So But And Or What When Where "
    "Why How Did Do Does Have Has Had Will Would Can Could Should My Your Our His "
    "Her Its Their In On At To For With From About After Before During Is Am Are "
    "Was Were The A An That's Let's Yeah Okay Yes No Well Now Just Really Maybe "
    "Let Get Got Know Think Want Need Make Take Say Said Tell Ask See Look Come "
    "Go Going If Because When While How's What's Where's Who's".split())

# 强否定标记：原文含它才生成不适用条件（弱否定不生成，宁缺勿造——
# forgetting.payload 已证明模板骨架会虚高重复度且无判别力）。
_NEG_MARKS = ("n't", " not ", " never ", "nobody", "nothing", "no one", "none of")


def _extract_entities(text, limit=4):
    """确定性实体近似：连续大写词（人名/地名）+ 日期/时间数字。只读 turn 正文。
    纯数字编号（"1."）不是实体——只保留年份/时刻/日期形态，否则列表编号会
    批量污染 tags 与生效条件行（实测教训）。"""
    import re
    ents = []
    for m in re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", text):
        if m.split()[0] not in _STOP_HEADS and m not in ents:
            ents.append(m)
    for m in re.findall(r"\d{4}|\d{1,2}:\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?", text):
        if m not in ents:
            ents.append(m)
    return ents[:limit]


def _date_tag(title):
    """从 title 抽规范化日期串做 tag。整段 title 入 tags 会污染实体路
    （_path_entity 的 `query in t` 方向：长 tag 是误报源）。"""
    if not title:
        return ""
    import re
    m = (re.search(r"\d{4}-\d{2}-\d{2}", title)
         or re.search(r"[A-Za-z]+day\s+\d{1,2}\s+[A-Za-z]+,?\s*\d{4}", title)
         or re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", title))
    return m.group(0) if m else ""


def calibrate_turn(r, date_key=None, title_key=None):
    """turn 行 → (CCG 五要素正文, tags, condition_space)。

    v2 归因修正：自建语料 100% 召回的机制条件是「查询-证据词面同源」
    （对照实验：节点特异词在查询中出现 → 100%；全同质问法 → 11.9%）。
    因此——
      1. 特异词（说话人/日期/实体）必须进五要素**每一行**（词法路对全文打
         Jaccard：条件行的特异词是净增益，同质模板词是净稀释——v1 抽样
         3.3% < legacy 16% 的根源，与 corpus.body 把 dom/point/aspect 内嵌
         每一行同构）；
      2. 模板骨架压到最短（corpus.body 固定尾巴仅 12 字，v1 有 30+ 字同质词）；
      3. 五要素行承担条件结构职责（semantic 路/judge 读），不承诺解决
         查询-证据表述鸿沟——那是公开数据集词法召回的真实天花板。
    tags 用裸词（说话人/日期/实体）：_path_entity 的匹配是 `t in query or
    query in t`，带 `ent:` 前缀的 tag 在自然语言查询下永不命中（实测教训，
    corpus 的 `domain:` 桶 tag 是给 bucket/条件路由用的，两者用途不同）。
    不适用条件仅当原文含强否定标记时生成（对 adversarial「是否说过」类问题
    有真实判别力）；否则显式写「（无）」。
    """
    import re
    text = str(r.get("text") or "").strip()
    speaker = str(r.get("speaker") or "").strip()
    date = str(r.get(date_key) or "").strip() if date_key else ""
    title = str(r.get(title_key) or "").strip() if title_key else ""
    ents = [e for e in _extract_entities(text) if e != speaker]
    who = speaker or (next((e for e in ents if not e[0].isdigit()), None) or "匿名")
    dtag = date or _date_tag(title)
    low = f" {text.lower()} "
    neg = next((m for m in _NEG_MARKS if m in low), None)
    when = f"于{dtag}" if dtag else ""
    ents_head = "/".join(ents[:2])

    body = (
        f"# 功能名：{who}·会话记忆{when}\n"
        f"# 生效条件：查询涉及「{who}」{when}"
        + (f"所述「{ents_head}」" if ents_head else "") + "时生效\n"
        f"# 子功能：{who}的会话条目{when}\n"
        f"# 执行：{who}会话原文回溯\n"
        f"# 验证方式：data\n"
        f"# 不适用条件："
        + (f"断言与原文相反（含{neg.strip()}语义）" if neg else "（无）") + "\n\n"
        + text
    )
    tags = [t for t in (who, dtag) if t] + ents[:3]
    cond_space = {
        "observation_position": f"{who} 的会话陈述" + (f"（{dtag}）" if dtag else ""),
        "observation_tool": "会话记录",
        "existence_constraint": "公开",
    }
    return body, tags, cond_space


def calibrate_lm_turn(t, ctx=None):
    return calibrate_turn(t, date_key="date", ctx=ctx)


def calibrate_lc_turn(r, ctx=None):
    return calibrate_turn(r, title_key="title", ctx=ctx)


# ============ 写入时加工管线（v3）——「查询时的泛化提前到写入时完成」 ============
# 外部对标结论：检索只是链路最后一跳；完整系统在写入时做实体规范化/意图抽象/
# 指代消解，把语料加工成可沿链行走的形态。以下三步全部是**确定性规则近似**
# （纯标准库、盲于查询集、随报告公开词表），不引入任何模型依赖。

def build_canon(corpus_path, min_df=3):
    """离线实体规范化：全语料扫一遍，聚合大写词/人名的文档频次（df）。
    df≥min_df 的是 canonical 实体（会话成员 + 高频专名）——单 turn 局部抽取
    看不见「Alice 在 200 条 turn 里反复出现」这个全库事实，这正是写入时
    （offline）加工区别于查询时（online）匹配的价值所在。"""
    from collections import Counter
    df = Counter()
    import re as _re
    for r in iter_jsonl(corpus_path):
        text = str(r.get("text") or "")
        spk = str(r.get("speaker") or "").strip()
        ws = {spk} if spk else set()
        ws |= set(_re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", text))
        ws = {w.split()[0] for w in ws if w.split()[0] not in _STOP_HEADS}
        df.update(ws)
    return {w for w, c in df.items() if c >= min_df}


# 意图槽位（离线意图抽象的确定性近似）：英文动词短语原样入条件行——
# 保持词面同源（查询 "What did Alice plan" 与条件行 "plan" 直接 bigram 命中），
# 不翻译成中文（同义词表是中文，翻译即断链）。三类槽覆盖 LoCoMo 问题分布：
# 计划/过去事件/偏好。
_INTENT_HEADS = ("plan", "going to", "thinking of", "thinking about", "want to",
                 "will be", "need to", "have to", "decide", "suggest",
                 "remember", "talked about", "talk about", "mention",
                 "last time", "tell you", "told you", "hear",
                 "prefer", "favorite", "love", "hate", "enjoy")


def _intent_of(text):
    low = f" {text.lower()} "
    return [h for h in _INTENT_HEADS if f" {h}" in low]


def calibrate_turn(r, date_key=None, title_key=None, ctx=None):
    """turn 行 → (CCG 五要素正文, tags, condition_space)。

    v3（写入时加工管线）：在 v2（特异词进每一行）之上叠加三步离线加工，
    ctx 携带全库视图：
      - ctx["canon"]：canonical 实体表（build_canon 产物）。条目涉及的
        canonical 实体进生效条件行——查询以人名开头时，词法/实体路沿
        规范化实体直接落到「该人名相关条目」集合（链路第一跳）。
      - ctx["intents"]：意图槽位短语进子功能行——意图抽象的词面同源版。
      - ctx["last_canon"]：前一条的 canonical 实体（写入时序状态）。本条
        无任何实体而前条有 → 条件行附「承接 {last}」——保守指代消解：
        只附加假设、不删原文（判别力交给 RRF 多路共识，虚报风险可控）。
    tags 用裸词（说话人/日期/实体）：_path_entity 的匹配是 `t in query or
    query in t`，带 `ent:` 前缀的 tag 在自然语言查询下永不命中（实测教训）。
    不适用条件仅当原文含强否定标记时生成；否则显式写「（无）」。
    """
    import re
    text = str(r.get("text") or "").strip()
    speaker = str(r.get("speaker") or "").strip()
    date = str(r.get(date_key) or "").strip() if date_key else ""
    title = str(r.get(title_key) or "").strip() if title_key else ""
    canon = (ctx or {}).get("canon") or frozenset()
    ctx_ents = _extract_entities(text)
    canon_hits = [e for e in dict.fromkeys(
        [speaker] if speaker else []) if e in canon]
    if canon:
        local = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", text)
        canon_hits += [w for w in dict.fromkeys(w.split()[0] for w in local)
                       if w in canon and w not in canon_hits]
    else:
        canon_hits += [e for e in ctx_ents if e != speaker]
    last = (ctx or {}).get("last_canon")
    if not canon_hits and last:
        canon_hits = list(last)
    who = speaker or (next((e for e in canon_hits if not e[0].isdigit()), None)
                      or "匿名")
    dtag = date or _date_tag(title)
    low = f" {text.lower()} "
    neg = next((m for m in _NEG_MARKS if m in low), None)
    when = f"于{dtag}" if dtag else ""
    ent_head = "/".join(canon_hits[:3])
    intents = _intent_of(text)

    body = (
        f"# 功能名：{who}·会话记忆{when}\n"
        f"# 生效条件：查询涉及「{ent_head or who}」{when}时生效\n"
        f"# 子功能：{who}的会话条目"
        + (f"（意图：{'/'.join(intents[:3])}）" if intents else "") + "\n"
        f"# 执行：{who}会话原文回溯\n"
        f"# 验证方式：data\n"
        f"# 不适用条件："
        + (f"断言与原文相反（含{neg.strip()}语义）" if neg else "（无）") + "\n\n"
        + text
    )
    tags = [t for t in (who, dtag) if t] + canon_hits[:3]
    cond_space = {
        "observation_position": f"{who} 的会话陈述" + (f"（{dtag}）" if dtag else ""),
        "observation_tool": "会话记录",
        "existence_constraint": "公开",
    }
    return body, tags, cond_space


def build_eval_cg(cg_cls, root, corpus_path, text_of, src_tag, verbose=True,
                  calib_of=None, rebuild=False):
    """幂等建库：节点数已达语料行数则直接复用。返回 cg（不 flush 句柄）。

    calib_of=None → 口径 A（legacy 裸文本）；传入 calibrate_*_turn → 口径 B
    （五要素标定条目 + tags + condition_space）。两口径用不同 root，互不污染。
    rebuild=True 删库重建（标定器改版后必须重建——幂等按节点数判断，识别不了
    同节点数的旧版标定条目）。
    v3：标定口径先全语料 build_canon（离线实体规范化），写入循环维护
    last_canon（时序状态，供保守指代承接）——两遍扫描，仍 O(N)。
    """
    from md_cg.mdcos import MdCGOS
    if rebuild and os.path.isdir(root):
        import shutil
        shutil.rmtree(root, ignore_errors=True)
    n_rows = sum(1 for _ in iter_jsonl(corpus_path))
    cg = cg_cls(root, autoflush=500) if cg_cls else MdCGOS(root, autoflush=500)
    have = len(cg.index["nodes"])
    if have >= n_rows:
        if verbose:
            print(f"  建库复用 {root}：{have} 节点（语料 {n_rows} 行）")
        return cg
    canon = build_canon(corpus_path) if calib_of else frozenset()
    if verbose and calib_of:
        print(f"  写入时加工：canonical 实体 {len(canon)} 个（df≥3）")
    if verbose:
        print(f"  建库 {root}：已有 {have}，语料 {n_rows} 行，开始写入 "
              f"（{'标定口径 B' if calib_of else 'legacy 口径 A'}）…")
    t0 = time.time()
    last_canon = None
    for i, r in enumerate(iter_jsonl(corpus_path), 1):
        if r["id"] in cg.index["nodes"]:
            continue
        if calib_of:
            body, tags, cond_space = calib_of(r, {"canon": canon,
                                                  "last_canon": last_canon})
            cg.add(r["id"], body, layer="contextual", tags=tags,
                   condition_space=cond_space, eval_src=src_tag,
                   verification_basis="data")
            hits = [t for t in tags[1:] if not t.replace(".", "")
                    .replace(":", "").isdigit()]
            last_canon = hits or last_canon
        else:
            cg.add(r["id"], text_of(r), layer="contextual",
                   eval_src=src_tag, verification_basis="data")
        if verbose and i % 20000 == 0:
            print(f"    … {i}/{n_rows}（{time.time() - t0:.0f}s）")
    cg.flush()
    if verbose:
        print(f"  建库完成：{len(cg.index['nodes'])} 节点，{time.time() - t0:.0f}s")
    return cg


def install_read_cache(cg):
    """评测只读：节点文件读进内存，避免逐次检索重复磁盘 I/O。"""
    cache = {}
    orig = cg._read

    def _cached(entry):
        p = entry["path"]
        if p not in cache:
            cache[p] = orig(entry)
        return cache[p]

    cg._read = _cached
    return cache


# ------------------------------------------------------------------ 检索与指标

def run_query(cg, query, k=5, paths=PATHS, judge=False, fusion=None,
              path_weights=None, context=None):
    """单查询，返回 (结果四元组列表, meta)。
    fusion/path_weights 覆盖融合方式与路权重（按路拆解归因用）。

    context 是**条件约束（bucket）路可被开启的唯一入口**：mdcos._path_bucket 在
    `context is None` 时直接 `return []`（mdcos.py:435），而 search_rrf 的默认
    paths 里恰恰含 "bucket"——即「名义四路、实际三路」。传 context 之前，全部
    既有四路 RRF 口径的评测都未曾开启过条件路由（先例：四轴消融 + Rust 空壳）。
    """
    kw = {}
    if fusion:
        kw["fusion"] = fusion
    if path_weights:
        kw["path_weights"] = path_weights
    if context is not None:
        kw["context"] = context
    return cg.search_rrf(query, k=k, paths=paths, judge=judge, record=False, **kw)


def first_evidence_rank(res, evidence):
    """首个证据 turn 的排名（1-based；未命中 0）。"""
    if not evidence:
        return 0
    for i, r in enumerate(res, 1):
        if r[0]["id"] in evidence:
            return i
    return 0


def evaluate_group(cg, questions, k=5, paths=PATHS, judge=False, verbose=True,
                   fusion=None, path_weights=None, context_of=None):
    """一组题 → per-question 明细行。负例组传 judge=False（拒答看分数线）。

    context_of: 可调用 `q -> context dict`（返回 None 表示该题不下发情境）。
    缺省 None → 全组不传 context（**既有行为完全不变**）。传入即开启条件路由，
    是「条件约束路的净效应」单变量实验的开关。
    """
    rows = []
    t0 = time.time()
    for i, it in enumerate(questions, 1):
        ctx = context_of(it) if context_of else None
        res, meta = run_query(cg, it["question"], k=k, paths=paths, judge=judge,
                              fusion=fusion, path_weights=path_weights,
                              context=ctx)
        rank = first_evidence_rank(res, set(it.get("evidence_turns") or []))
        rows.append({
            "qid": it["qid"], "qtype": it["qtype"],
            "rank": rank, "top1_score": res[0][1] if res else 0.0,
            "n_res": len(res),
        })
        if verbose and i % 100 == 0:
            print(f"    查询 {i}/{len(questions)}（{time.time() - t0:.0f}s）")
    return rows


def summarize(rows, k=5):
    """hit@1 / hit@K / MRR + 分题型。score_p10 供拒答线校准。"""
    if not rows:
        return {"n": 0}
    hit1 = sum(1 for r in rows if r["rank"] == 1)
    hitk = sum(1 for r in rows if 0 < r["rank"] <= k)
    mrr = sum(1.0 / r["rank"] for r in rows if r["rank"]) / len(rows)
    top1 = sorted(r["top1_score"] for r in rows)
    out = {
        "n": len(rows),
        "hit@1": hit1 / len(rows),
        f"hit@{k}": hitk / len(rows),
        "mrr": mrr,
        "score_p10": top1[max(0, len(top1) // 10)],
        "score_p50": top1[len(top1) // 2],
    }
    by = {}
    for r in rows:
        by.setdefault(r["qtype"], []).append(r)
    out["by_qtype"] = {
        qt: {
            "n": len(g),
            "hit@1": sum(1 for r in g if r["rank"] == 1) / len(g),
            f"hit@{k}": sum(1 for r in g if 0 < r["rank"] <= k) / len(g),
            "mrr": sum(1.0 / r["rank"] for r in g if r["rank"]) / len(g),
        } for qt, g in sorted(by.items())
    }
    return out


def refusal_metrics(rows, line):
    """负例组：Top-1 分 < line 记为拒答。返回拒答率与明细统计。"""
    n = len(rows)
    if not n:
        return {"n": 0}
    ref = sum(1 for r in rows if r["top1_score"] < line)
    return {"n": n, "refusal_rate": ref / n,
            "refused": ref, "line": line}


def false_refusal_rate(rows, line):
    """正例误杀（被错误拒答的正例比例）：正例 Top-1 分 < line。"""
    n = len(rows)
    if not n:
        return 0.0
    return sum(1 for r in rows if r["top1_score"] < line) / n


def calibrate_line(pos_rows):
    """拒答线 = 正例 hit@1 题 Top-1 分的 10 分位。"""
    scores = sorted(r["top1_score"] for r in pos_rows if r["rank"] == 1)
    if not scores:
        return 0.0
    return scores[max(0, len(scores) // 10)]


def save_result(name, payload):
    """评测结果 JSON 落盘（报告数据源）。"""
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  结果 → {path}")
    return path


def print_table(title, groups, k=5):
    """groups: {组名: summarize 输出}。"""
    print(f"\n== {title}（证据命中口径，k={k}）==")
    print(f"{'组':<28}{'n':>6}{'hit@1':>9}{f'hit@{k}':>9}{'MRR':>8}")
    print("-" * 62)
    for name, s in groups.items():
        if not s.get("n"):
            print(f"{name:<28}{0:>6}   -")
            continue
        print(f"{name:<28}{s['n']:>6}{s['hit@1']:>9.1%}"
              f"{s[f'hit@{k}']:>9.1%}{s['mrr']:>8.3f}")
        for qt, st in s.get("by_qtype", {}).items():
            print(f"  ├ {qt:<24}{st['n']:>6}{st['hit@1']:>9.1%}"
                  f"{st[f'hit@{k}']:>9.1%}{st['mrr']:>8.3f}")


def pct(x):
    return f"{x * 100:.1f}%"
