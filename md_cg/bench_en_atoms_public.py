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
    ② 96.8 / 99.8 / 99.8（给定中文关键词的检索侧上界）
    ③ 50.0 / 74.6 / 81.2 · ③a 39.0 / 67.0 / 78.2
    ④（机械归一端到端下界）英文问句→EN_ZH 词表直译→②同链路
    ⑤⑥⑦（②路鲁棒性）query 扰动：漏 20% 关键词 / 插 3 噪词 / 错译 20%

诚实边界：
    1) 池 567 条全为 gold → 零干扰上界，非端到端能力；
    2) 英文原题来自上游 LoCoMo 派生副本（data/external，不入库）——脚本
       公开但英文原题自备（BENCH6_EN_QUESTIONS 可覆盖路径）；中文关键词
       题面在公开集 questions500.jsonl；
    3) ②的 query 是中文关键词语义链（AI 归一化的输出形态）——AI 归一环节
       的质量未纳入本评测；④给出机械词表归一的端到端下界作对照；
    4) ⑤⑥⑦扰动为确定性规则（非随机采样），验证「②路对归一噪声不敏感」，
       扰动口径见各臂注释。
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
from md_cg.semantic.en_normalizer import normalize_en_query  # noqa: E402

DATA = b6.DATA
CORPUS = b6.CORPUS567
QUESTIONS = b6.QUESTIONS500
CHAR_ATOMS = os.path.join(HERE, "md_cg", "lexicon", "char_atoms_clean.json")

ZH_RANGE = ("\u4e00", "\u9fff")

# ⑥ 噪词（日常生活中性词，与对话语料存在真实弱共现 → 严苛口径）
NOISE_ZH = "天气 音乐 旅行"
# ⑦ 错译池（逐题循环取一组，模拟词表错译 20%）
WRONG_POOLS = ["经济 历史 音乐", "天体 地理 化学", "科技 法律 医学"]


# 生效条件：text 非空且 mode 为 drop20/noise3/wrong20 时按 idx 错位扰动并返回新串；text 为空返回 text or ""，mode 不在三者之内时原样返回 text。
def perturb_kw(text, mode, idx):
    """②路 query 关键词扰动（确定性规则，验证归一噪声灵敏度）。

    mode=drop20   每 5 词丢 1（位置随题号错位，模拟归一漏词 20%）
    mode=noise3   尾部插 3 个固定噪词（模拟归一混入无关概念）
    mode=wrong20  每 5 词错译 1（固定错译池循环，模拟词表错译 20%）
    """
    words = [w for w in (text or "").split() if w]
    if not words:
        return text or ""
    if mode == "drop20":
        return " ".join(w for i, w in enumerate(words) if (i + idx) % 5 != 0)
    if mode == "noise3":
        return " ".join(words + NOISE_ZH.split())
    if mode == "wrong20":
        pool = WRONG_POOLS[idx % len(WRONG_POOLS)].split()
        return " ".join(pool[i % len(pool)] if (i + idx) % 5 == 0 else w
                        for i, w in enumerate(words))
    return text


# 生效条件：CHAR_ATOMS 可读时按 data.get("lexicon") or {} 取词库，lexicon 缺失或为假值即返回空字典，否则逐键返回 {ch: str(v.get("en") or "")}（v 缺 "en" 或 "en" 为假值时该键值为空串）。
def load_char_atoms():
    """字级英文原子库：{中文字: 英文短语}。"""
    with io.open(CHAR_ATOMS, encoding="utf-8") as f:
        data = json.load(f)
    lex = data.get("lexicon") or {}
    return {ch: str(v.get("en") or "") for ch, v in lex.items()}


# 生效条件：以 text or "" 逐字符、char_atoms 为字级映射表——字符落在 ZH_RANGE 内时取 char_atoms.get(ch, "")（缺键回落空串），其余字符原样保留，返回 normalize_en(" ".join(parts))；text 为假值（None/空串）时按空串返回 normalize_en("")。
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


# 生效条件：以 normalize_en(str(c.get("text") or "")).split() 为基词集，body_only 为真时只返回该集合的 frozenset；body_only 为假（默认 False）时再并入 zh_map_en(str(c.get("zh") or ""), char_atoms) 拆出的词，返回合并后的 frozenset。
def node_atom_set(c, char_atoms, body_only=False):
    """doc 侧节点原子集：中文五槽字级映射 ∪ 英文正文归一词（双语双路 doc 侧）。

    body_only=True 时只取英文正文归一词——「英文原子直接匹配」最纯形态
    （使用者产品口径：英文 query → 英文原子 → 英文原子库 → 返回英文原文）。
    """
    toks = normalize_en(str(c.get("text") or "")).split()
    if not body_only:
        toks += zh_map_en(str(c.get("zh") or ""), char_atoms).split()
    return frozenset(toks)


# 生效条件：a 或 b 为假值（None/空集）时返回 0.0，否则交集非空返回 len(a & b)/len(a | b)、交集为空亦返回 0.0。
def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b) if inter else 0.0


# 生效条件：对 st.items() 每个值取 round(v, 1) 组成同键字典，st 为空字典时返回空字典。
def round_dict(st):
    return {k: round(v, 1) for k, v in st.items()}


# 生效条件：遍历 questions 逐问评测——qatoms_of(q) 为假值时仅累加 st["n"] 不计命中，否则按 jaccard 对 docs 降序（同分按 nid 升序）排序、以首个 nid 落在 q.get("evidence_turns") or [] 中的 rank 累加 hit@1/5/10 与 1/rank 的 MRR，打印后返回 {k: v/max(st["n"],1)（rr 项）或 v*100.0/max(st["n"],1)}。
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


# 生效条件：CORPUS、QUESTIONS、CHAR_ATOMS 与 b6.EN_QUESTIONS 均可读（en_rows 由 ec.iter_jsonl 读取 b6.EN_QUESTIONS 构建）时，载入语料与题、构建 docs 与 docs_body、逐臂 run_arm 并打印锚点，返回 0。
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
    # 臂④ 机械归一端到端下界：英文问句 → 词表直译为中文词（CEDICT 28294 键
    #     ∪ EN_ZH 手工层，无 AI）→ ②同链路。与②唯一差异 = query 归一来源：
    #     ②=AI 理解式归一的输出形态（标注关键词），④=机械查表归一。
# 生效条件：以 en_rows.get(q.get("qid"), "")（qid 缺键回落空串）取英文题面，经 normalize_en_query 取出的 terms 拼接后由 zh_map_en 映射，返回 frozenset(zh_map_en(" ".join(terms), char_atoms).split())；terms 为空时返回空 frozenset。
    def e4(q):
        terms, _ = normalize_en_query(en_rows.get(q.get("qid"), ""))
        return frozenset(zh_map_en(" ".join(terms), char_atoms).split())
    r4 = run_arm(questions, docs, e4, "④ en→zh·mech")
    # 臂⑤⑥⑦ ②路鲁棒性：query 关键词确定性扰动后走同一 ② 链路
    zh_q = lambda q: str(q.get("question") or "")  # noqa: E731
    r5 = run_arm(questions, docs,
                 lambda q: frozenset(zh_map_en(
                     perturb_kw(zh_q(q), "drop20", questions.index(q)),
                     char_atoms).split()), "⑤ ②-20%kw")
    r6 = run_arm(questions, docs,
                 lambda q: frozenset(zh_map_en(
                     perturb_kw(zh_q(q), "noise3", questions.index(q)),
                     char_atoms).split()), "⑥ ②+3noise")
    r7 = run_arm(questions, docs,
                 lambda q: frozenset(zh_map_en(
                     perturb_kw(zh_q(q), "wrong20", questions.index(q)),
                     char_atoms).split()), "⑦ ②20%wrong")

    print("[en_atoms] 完成（%.0fs）②=%s ③=%s ③a=%s ④=%s ⑤=%s ⑥=%s ⑦=%s"
          % (time.time() - t0,
             *(round_dict(r) for r in (r2, r3, r3a, r4, r5, r6, r7))))
    print("  锚点：② 96.8/99.8/99.8（给定关键词上界） · ③ 81.2 · ④ 机械下界"
          " · ⑤⑥⑦ 鲁棒性（hit@10 应稳 99+）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
