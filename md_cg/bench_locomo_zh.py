# -*- coding: utf-8 -*-
"""LoCoMo 千题规模中文层四项能力探针（zh_mad 的 LoCoMo 扩展）。

与 `bench_zh_mad.py` 的关系：后者是 20 条 gold turn 的**方向性**探针（池 20 条，
±1 题 = ±5pp）。本脚本把同一套写入侧四轴消融搬到 **LoCoMo 全证据覆盖**规模：

  轴 1 实体规范化  —— 全库 df 聚合出的 canonical 词 + 人物/地点/时间 → tags（entity 路）
  轴 2 指代消解    —— **仅当本条自身无实体**时承接**前一条自身**的 canonical
  轴 3 意图抽象    —— 摘要 → 规范意图类目；类目 + 动词原形 → tags，类目 → 正文子功能行
  轴 4 关系图遍历  —— 人物/事件/时间/身份/地点/条件 多维关系 → edges（graph 路）

本脚本**复用** `bench_zh_mad` 的 `parse_zh` / `build_tables` / `axis_values` /
`normalize_terms` / `intent_of` / `build_arm`——保证中文层 schema 与四轴实现
与 20 条基准**逐位同源**，差异只在语料规模与题库。

数据集与规模（使用者已裁决）：
  * 数据集：LoCoMo（mteb/LoCoMo BEIR 转制版）500 题。
  * 写入侧口径：**全证据覆盖**——所有 `evidence_turns` 去重后的 turn 全部入池。
    实测：500 题引用的证据 turn 去重 568 个，其中 **567 个在语料中存在**，
    `scene_3_session_10_turn_19` 为数据集悬空引用（语料无此 turn，见「数据完整性」
    条款）。
  * 干扰项：**第一轮不加**（池仅证据 turn）。池内每一条都是某题的 gold →
    「零干扰」理想条件，指标为**上界**，报告必须声明（干扰池为独立对照轮次）。
  * 查询侧：500 题的中文查询词。

数据完整性条款（诚实条款，报告必须原样声明）：
  * LoCoMo 的 BEIR 转制版中，题 `scene_3_q_58`（multi_hop）引用的
    `scene_3_session_10_turn_19` 在 `locomo_corpus.jsonl` 中**不存在**——
    数据集自身的悬空引用。本题另有 6 条有效证据，故不影响其可命中性；
    但「证据 turn 总数」准确值是 **567** 而非 568。

诚实条款（报告必须原样声明）：
  * **中文层与中文查询均为本次新增产出**（会话模型逐条产出），**非既有真源**——
    与 20 条基准（`manual_zh.json` / `manual_q.json`，既有产物）性质不同。
  * 写入侧加工（四轴）仍是**确定性纯规则**（零 LLM、零第三方依赖、同输入必同输出），
    词表随源码公开，第三方可重放。
  * 加工**盲于查询集**：canonical 判定只用全库 df 与中文层自身字段，
    不读 `zh_queries/` 的任何内容——否则即数据泄漏，评测作废。
  * 池 567 条、题 500 道；随机基线 hit@1 = 1/567 ≈ 0.18%。但池内**全是 gold**，
    故 0.18% 不是有意义的基线——「零干扰」才是本轮真正的条件限制。

跑法：
    python -m md_cg.bench_locomo_zh dump      # 派生 raw_turns/raw_questions（零标注）
    python -m md_cg.bench_locomo_zh status    # 产出进度与缺口
    python -m md_cg.bench_locomo_zh prepare   # 合并中文层 → corpus567/questions500
    python -m md_cg.bench_locomo_zh build     # 建 5 臂
    python -m md_cg.bench_locomo_zh run       # Rust 评测（--dataset lc，5 组）
    python -m md_cg.bench_locomo_zh seed      # graph 种子口径对照
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg import bench_zh_mad as bz   # noqa: E402  复用四轴实现（同源保证）

EXT = os.path.join(HERE, "data", "external")
LC = os.path.join(EXT, "locomo")
WORK = os.path.join(EXT, "locomo_zh")
ZH_TURNS = os.path.join(WORK, "zh_turns")      # 分批落盘：{turn_id: 中文层串}
ZH_QUERIES = os.path.join(WORK, "zh_queries")  # 分批落盘：{qid: 中文查询词}

RAW_TURNS = os.path.join(WORK, "raw_turns.jsonl")
RAW_QUESTIONS = os.path.join(WORK, "raw_questions.jsonl")
CORPUS567 = os.path.join(WORK, "corpus567.jsonl")
QUESTIONS500 = os.path.join(WORK, "questions500.jsonl")

# LoCoMo 组映射（与 rust/src/main.rs `groups_of("lc")` 逐项一致）
GROUPS = ("precise", "temporal", "interference", "negative", "reference")
POS_GROUPS = ("precise", "temporal", "interference")
QTYPE_OF_GROUP = {
    "precise": "single_hop",
    "temporal": "temporal_reasoning",
    "interference": "multi_hop",
    "negative": "adversarial",
    "reference": "open_domain",
}

# 已知的悬空引用（数据集自身缺陷，见模块头数据完整性条款）
KNOWN_DANGLING = {"scene_3_session_10_turn_19"}

# graph 边的 df 上限：自由参数，随池规模标定（见 rescale 说明）。
# 20 条基准用 5（= 25% 池）；本脚本缺省按 5% 池标定，另跑固定 5 作敏感性对照。
MAX_DF_FIXED = 5


def max_df_auto(n_pool):
    """池规模 → edges 的 df 上限。

    原值 5 是 20 条池上的**绝对**阈值（= 池的 25%）。thousand-scale 直接照搬会
    把常见词（人名/常用名词）全部过滤 → 图路无边可走；反之过宽则生成巨型团
    （「全连通，零信息量只注入噪声」）。此处按池规模取 5% 作为标定值，
    并在报告中附 max_df=5 的敏感性列——**结论不建立在单一参数上**。
    """
    return max(MAX_DF_FIXED, int(round(0.05 * n_pool)))


def iter_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_chunks(d):
    """合并目录下全部分片 JSON（后者覆盖前者，便于修订单条）。"""
    out = {}
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        part = load_json(os.path.join(d, name))
        if not isinstance(part, dict):
            raise SystemExit(f"[失败] 分片非对象：{os.path.join(d, name)}")
        out.update(part)
    return out


# ------------------------------------------------------------------ dump
_SPEAKER_RE = re.compile(r"^([A-Za-z][A-Za-z .'\-]{0,24}): ")
_DATE_RE = re.compile(r"Data time: (\d{1,2}:\d{2} [AP]M on \w+ \d{1,2} \w+, \d{4})")


def cmd_dump(verbose=True):
    """确定性派生：证据 turn 全集 + 题库 → raw_turns/raw_questions（零标注）。"""
    os.makedirs(ZH_TURNS, exist_ok=True)
    os.makedirs(ZH_QUERIES, exist_ok=True)
    corpus = {r["id"]: r for r in iter_jsonl(os.path.join(LC, "locomo_corpus.jsonl"))}
    questions = list(iter_jsonl(os.path.join(LC, "locomo_questions.jsonl")))

    ev = sorted({t for q in questions for t in (q.get("evidence_turns") or [])})
    missing = sorted(t for t in ev if t not in corpus)
    rows = []
    for tid in ev:
        if tid not in corpus:
            continue
        c = corpus[tid]
        text = str(c.get("text") or "")
        title = str(c.get("title") or "")
        m = _SPEAKER_RE.match(text)
        d = _DATE_RE.search(title)
        rows.append({"id": tid, "text": text, "speaker": m.group(1) if m else "",
                     "date": d.group(1) if d else "", "title": title})

    with open(RAW_TURNS, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(RAW_QUESTIONS, "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    if verbose:
        print(f"证据 turn：去重 {len(ev)}，语料中存在 {len(rows)}，悬空 {missing}")
        unknown = [t for t in missing if t not in KNOWN_DANGLING]
        if unknown:
            print(f"[警告] 出现未登记的悬空引用：{unknown}")
        print(f"→ {RAW_TURNS}（{len(rows)} 条）")
        print(f"→ {RAW_QUESTIONS}（{len(questions)} 道）")
        ntype = {}
        for q in questions:
            ntype[q["qtype"]] = ntype.get(q["qtype"], 0) + 1
        print("题型分布：" + ", ".join(f"{k}={v}" for k, v in sorted(ntype.items())))
    return rows, questions


# ------------------------------------------------------------------ status
def cmd_status(verbose=True, head=12):
    """产出进度：中文层 / 中文查询的覆盖与缺口（分批产出时用）。"""
    turns, questions = cmd_dump(verbose=False)
    zt = load_chunks(ZH_TURNS)
    zq = load_chunks(ZH_QUERIES)
    t_ids = [r["id"] for r in turns]
    q_ids = [q["qid"] for q in questions]
    miss_t = [t for t in t_ids if t not in zt]
    miss_q = [q for q in q_ids if q not in zq]
    extra_t = [k for k in zt if k not in set(t_ids)]
    extra_q = [k for k in zq if k not in set(q_ids)]
    if verbose:
        print(f"写入侧中文层：{len(t_ids) - len(miss_t)}/{len(t_ids)}"
              f"（缺 {len(miss_t)}）")
        print(f"查询侧中文词：{len(q_ids) - len(miss_q)}/{len(q_ids)}"
              f"（缺 {len(miss_q)}）")
        if extra_t:
            print(f"[警告] 多余 turn 键（不在证据集内）：{extra_t[:head]}")
        if extra_q:
            print(f"[警告] 多余 qid 键（不在题库内）：{extra_q[:head]}")
        if miss_t:
            print(f"  待补 turn（前 {head}）：{miss_t[:head]}")
        if miss_q:
            print(f"  待补 qid（前 {head}）：{miss_q[:head]}")
        # 结构校验：已产出的中文层必须能被 parse_zh 解出五槽
        bad = []
        for tid in t_ids:
            if tid not in zt:
                continue
            f = bz.parse_zh(zt[tid])
            if not (f["identity"] and f["time"] and f["summary"] and f["terms"]):
                bad.append(tid)
        if bad:
            print(f"[警告] 中文层槽位不全（{len(bad)} 条）：{bad[:head]}")
    return {"n_turn": len(t_ids), "n_turn_done": len(t_ids) - len(miss_t),
            "n_q": len(q_ids), "n_q_done": len(q_ids) - len(miss_q),
            "miss_turns": miss_t, "miss_qids": miss_q,
            "bad": bad if verbose else []}


# ------------------------------------------------------------------ prepare
def cmd_prepare(verbose=True):
    """合并中文层 → corpus567.jsonl + questions500.jsonl（幂等覆盖）。"""
    turns, questions = cmd_dump(verbose=False)
    zt = load_chunks(ZH_TURNS)
    zq = load_chunks(ZH_QUERIES)

    miss_t = [r["id"] for r in turns if r["id"] not in zt]
    miss_q = [q["qid"] for q in questions if q["qid"] not in zq]
    if miss_t or miss_q:
        raise SystemExit(
            f"[失败] 中文层未产出完：缺 {len(miss_t)} 条 turn、{len(miss_q)} 道题。"
            f"先跑 `status` 看缺口。")

    # 语料：按 (scene, session, turn) 数值序 —— 「承接前一条」需要确定的时间序
    def sort_key(tid):
        m = re.match(r"scene_(\d+)_session_(\d+)_turn_(\d+)$", tid)
        if not m:
            raise SystemExit(f"[失败] turn id 无法解析：{tid}")
        return tuple(int(x) for x in m.groups())

    corpus = []
    for r in sorted(turns, key=lambda r: sort_key(r["id"])):
        raw = zt[r["id"]]
        corpus.append({
            "id": r["id"], "text": r["text"], "speaker": r["speaker"],
            "date": r["date"], "zh": raw, "zh_fields": bz.parse_zh(raw),
        })

    out_q = []
    for q in questions:
        out_q.append({
            "qid": q["qid"], "qtype": q["qtype"],
            "question": zq[q["qid"]], "answer": str(q.get("answer") or ""),
            "evidence_turns": list(q.get("evidence_turns") or []),
        })

    with open(CORPUS567, "w", encoding="utf-8") as f:
        for r in corpus:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(QUESTIONS500, "w", encoding="utf-8") as f:
        for q in out_q:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    if verbose:
        print(f"语料 {len(corpus)} 条 → {CORPUS567}")
        print(f"题库 {len(out_q)} 条 → {QUESTIONS500}")
        ntype = {}
        for q in out_q:
            ntype[q["qtype"]] = ntype.get(q["qtype"], 0) + 1
        print("题型分布：" + ", ".join(f"{k}={v}" for k, v in sorted(ntype.items())))
        lt = sum(len(r["zh_fields"]["terms"]) for r in corpus)
        lc_ = sum(len(r["zh"]) for r in corpus)
        print(f"中文层：词项合计 {lt}（均 {lt / len(corpus):.1f}/条），"
              f"字符合计 {lc_}（均 {lc_ / len(corpus):.0f}/条）")
    return corpus, out_q


# ------------------------------------------------------------------ build
def cmd_build(max_df=None, verbose=True):
    corpus, _ = cmd_prepare(verbose=False)
    md = max_df if max_df is not None else max_df_auto(len(corpus))
    print(f"== 建库（消融 {len(bz.ARMS)} 臂，池 {len(corpus)} 条，"
          f"max_df={md}（自动，5% 池；固定基线 {MAX_DF_FIXED}））==")
    roots = {}
    for arm in bz.ARMS:
        roots[arm["name"]] = bz.build_arm(
            corpus, arm, max_df=md, root_base=f"_md_cg_eval_lczh_{arm['name']}")
    return roots


# ------------------------------------------------------------------ run
RUST_BIN = os.path.join(HERE, "rust", "target", "release", "mdcg-eval.exe")
ROW_RE = re.compile(
    r"^\s*(precise|temporal|interference|negative|reference)\s+(\d+)\s+"
    r"([\d.]+)%\s+([\d.]+)%\s+([\d.]+)\s*$", re.M)
GATE_RE = re.compile(r"拒答率：([\d.]+)%")
LINE_RE = re.compile(r"拒答线（正例 hit@1 题 Top-1 分 p10）：([\d.]+)")


def run_one(name, lib, qfile, extra=None):
    """调用 Rust 评测器跑一臂（--dataset lc 的组映射 + 显式 lib/qfile）。

    命令执行走 subprocess argv 列表 + 显式 UTF-8 + PYTHONUTF8=1（不经 Windows shell）。
    """
    import subprocess

    if not os.path.exists(RUST_BIN):
        raise SystemExit(f"[失败] 未找到 Rust 评测器：{RUST_BIN}（先 cargo build --release）")
    argv = [RUST_BIN, "--dataset", "lc", "--tag", name,
            "--lib", lib, "--qfile", qfile]
    if extra:
        argv += list(extra)
    env = dict(os.environ, PYTHONUTF8="1")
    p = subprocess.run(argv, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=HERE)
    if p.returncode != 0:
        raise SystemExit(f"[失败] {name}：{(p.stderr or '')[-900:]}")
    got = {}
    for m in ROW_RE.finditer(p.stdout):
        g, n, h1, h5, mrr = m.groups()
        got[g] = (int(n), float(h1), float(h5), float(mrr))
    if not got:
        raise SystemExit(f"[失败] {name}：未解析到组指标\n{p.stdout[-1500:]}")
    neg = GATE_RE.search(p.stdout)
    line = LINE_RE.search(p.stdout)
    return got, (float(neg.group(1)) if neg else None), \
        (float(line.group(1)) if line else None)


def print_table(title, rows, baseline=None):
    """rows: [(label, got, note)]；baseline = 参照行 label（算 Δ）。"""
    print(f"\n== {title} ==")
    hdr = (f"{'臂':<16}" + "".join(f"{g[:11]:>14}" for g in GROUPS)
           + f"{'正例hit@1':>12}{'正例MRR':>10}")
    print(hdr)
    print("-" * len(hdr))
    ref = None
    for label, got, note in rows:
        cells, sh1, sn, smrr = [], 0.0, 0, 0.0
        for g in GROUPS:
            n, h1, _h5, mrr = got[g]
            cells.append(f"{h1:.1f}%/{mrr:.3f}")
            if g in POS_GROUPS:
                sh1 += h1 / 100.0 * n
                sn += n
                smrr += mrr * n
        ov_h1 = sh1 / max(1, sn)
        ov_mrr = smrr / max(1, sn)
        if baseline is not None and label == baseline:
            ref = (ov_h1, ov_mrr)
        delta = ""
        if ref is not None and label != baseline:
            delta = f"  (Δ{(ov_h1 - ref[0]) * 100:+.1f}pp)"
        suffix = f"  {note}" if note else ""
        print(f"{label:<16}" + "".join(f"{c:>14}" for c in cells)
              + f"{ov_h1 * 100:>10.1f}%{ov_mrr:>10.3f}{delta}{suffix}")


def cmd_run(max_df=None, seeds=None):
    """消融主表（5 组；正例 hit@1/MRR = precise+temporal+interference）。"""
    roots = cmd_build(max_df=max_df)
    extra = ["--graph-seeds", "sorted"] if seeds == "sorted" else None
    rows = []
    for arm in bz.ARMS:
        name = arm["name"]
        got, neg, line = run_one(name, roots[name], QUESTIONS500, extra)
        note = f"拒答率={neg:.1f}%" if neg is not None else ""
        rows.append((name, got, note))
    total = sum(got[g][0] for g in GROUPS for _, got, _ in rows[:1])
    print_table(f"LoCoMo 千题中文层消融（Rust，--dataset lc，k=5，池 {total} 条证据 turn，"
                f"种子口径={seeds or '索引序'}）", rows, baseline=bz.ARMS[0]["name"])
    print(f"\n池 {total} 条**全为某题 gold**（零干扰）→ 指标为**上界**；"
          "干扰池为独立对照轮次，报告须声明。")
    return rows


def cmd_seed(max_df=None):
    """对照：同一个 a4 库，只切换 graph 路种子口径（隔离种子缺陷与边质量）。"""
    roots = cmd_build(max_df=max_df)
    lib = roots[bz.ARMS[-1]["name"]]
    rows = [
        ("a4/index", run_one("lczh_a4_index", lib, QUESTIONS500)[0],
         "现状：seeds=索引枚举序前 5"),
        ("a4/sorted", run_one("lczh_a4_sorted", lib, QUESTIONS500,
                              ("--graph-seeds", "sorted"))[0],
         "文档语义：seeds=top-5 词法"),
    ]
    print_table("graph 种子口径对照（库内容完全相同，只换种子，池 567）", rows,
                baseline="a4/index")
    return rows


def cmd_show(kind, start, end, width=240):
    """打印 [start, end) 区间的待标注项（分批产出时读原文用）。

    经 python 输出而非 shell 拼接：turn 正文含 `|`、引号等，直接进 shell 会被
    cmd.exe 解释（纪律 15 的动机）。
    """
    rows = list(iter_jsonl(RAW_TURNS if kind == "turn" else RAW_QUESTIONS))
    for i, r in enumerate(rows[start:end], start + 1):
        if kind == "turn":
            print(f"{i}\t{r['id']}\t{r['speaker']}\t{r['date']}\t{r['text'][:width]}")
        else:
            print(f"{i}\t{r['qid']}\t{r['qtype']}\t{r['question'][:width]}")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    max_df = None
    seeds = None
    for i, a in enumerate(argv):
        if a == "--max-df":
            max_df = int(argv[i + 1])
        if a == "--seeds":
            seeds = argv[i + 1]
    if cmd == "show":
        cmd_show(argv[2], int(argv[3]), int(argv[4]))
    elif cmd == "dump":
        cmd_dump()
    elif cmd == "status":
        cmd_status()
    elif cmd == "prepare":
        cmd_prepare()
    elif cmd == "build":
        cmd_build(max_df=max_df)
    elif cmd == "run":
        cmd_run(max_df=max_df, seeds=seeds)
    elif cmd == "seed":
        cmd_seed(max_df=max_df)
    else:
        raise SystemExit(
            f"未知子命令：{cmd}"
            "（可用：dump / status / prepare / build / run / seed）")


if __name__ == "__main__":
    main(sys.argv)
