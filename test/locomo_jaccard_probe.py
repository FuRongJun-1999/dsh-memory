#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LoCoMo 第三方独立评测 · 第二组：灵枢「英文主路线」口径的独立复现与拆解

目的：
  灵枢 README/REPRODUCE 宣称「英文（中文语义归一化桥接）96.8/99.8/99.8」，
  来源是 md_cg/bench_en_atoms_public.py 臂②。该链路**不经过 MdCG 检索引擎**，
  而是：灵枢组件抽取原子集 + 全池 567 节点 Jaccard 暴力排序。

第三方做法：
  · 特征抽取只用灵枢自身资产：mdcg.normalize_en、lexicon/char_atoms_clean.json；
  · Jaccard 排序/打分是公开通用算法，由我实现（属评测脚手架，非被测能力；
    若换成灵枢的 bench 脚本则由灵枢自评，违反第三方性）；
  · 命中判定 hit@1/5/10、MRR 由我独立实现。

拆解臂（唯一变量 = doc 侧原子集构成，query 侧恒为「中文关键词→字级英文映射」）：
  J2_full  doc = 中文五槽字级映射 ∪ 英文正文归一词      ← 复现灵枢臂②（应得 96.8/99.8/99.8）
  J2_body  doc = 仅英文正文归一词（无 AI 摘要层）        ← 纯「标准归一化」能力
  J2_zh    doc = 仅中文五槽字级映射（无英文归一化）      ← 纯「AI 摘要层」能力
  J0_raw   doc = 英文正文原词（不做归一化）              ← 归一化增益的下界对照
"""
import io, json, os, sys
from collections import defaultdict

REPO = "/root/lingshu-test/repo"
DATA = os.path.join(REPO, "data/benchmarks/locomo-zh-500")
sys.path.insert(0, REPO)

from md_cg.mdcg import normalize_en     # 灵枢资产：英文归一化

CHAR_ATOMS = os.path.join(REPO, "md_cg", "lexicon", "char_atoms_clean.json")
ZH_RANGE = ("\u4e00", "\u9fff")


# 生效条件：解析模块级常量 CHAR_ATOMS 指向的 JSON 得 data，取 lex = data.get("lexicon") or {}，返回 {ch: str(v.get("en") or "")}；lexicon 缺失或为假值时 lex 为 {}，返回空 dict；
def load_char_atoms():
    with io.open(CHAR_ATOMS, encoding="utf-8") as f:
        data = json.load(f)
    lex = data.get("lexicon") or {}
    return {ch: str(v.get("en") or "") for ch, v in lex.items()}


# 生效条件：遍历 (text or "") 的每个字符，落在模块级常量 ZH_RANGE 的 [lo, hi] 区间内时取 char_atoms.get(ch, "")（仅该键缺失才回落空串），否则保留原字符，以空格连接后交 normalize_en；text 为假值（None/空串）时 parts 为空列表，返回 normalize_en("")；
def zh_map_en(text, char_atoms):
    lo, hi = ZH_RANGE
    parts = [char_atoms.get(ch, "") if lo <= ch <= hi else ch for ch in (text or "")]
    return normalize_en(" ".join(parts))


# 生效条件：打开模块级常量 DATA 下的 corpus567.jsonl 与 questions500.jsonl，各自只对 l.strip() 为真的行执行 json.loads，按行序返回 (c, q)；
def load():
    c, q = [], []
    with io.open(os.path.join(DATA, "corpus567.jsonl"), encoding="utf-8") as f:
        c = [json.loads(l) for l in f if l.strip()]
    with io.open(os.path.join(DATA, "questions500.jsonl"), encoding="utf-8") as f:
        q = [json.loads(l) for l in f if l.strip()]
    return c, q


# 生效条件：a、b 均为真值（非空集合）时算 inter = len(a & b)，inter 为 0 返回 0.0，否则返回 len(a & b)/len(a | b)；a 或 b 为假值时提前返回 0.0；
def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b) if inter else 0.0


# 生效条件：遍历 questions 时，ev = set(q.get("evidence_turns") or []) 为假值的 q 直接跳过且不计入任何计数；否则先 st["n"] 加 1，若 qatoms_of(q) 为假值则再 st["empty"] 加 1 并 continue，其余 q 按 (-jaccard(qa, na), nid) 升序取首个 nid 命中 ev 的位次 rank（无命中为 0），rank==1 时 st 与 qtype 计 h1、0 < rank <= 5 时计 h5、0 < rank <= 10 时 st 与 qtype 计 h10、rank 为真时 st 与 qtype 各累加 1.0/rank、rank 为 0 时把 q["qid"] 记入 miss，并以 q.get("qtype") or "?" 归组；最终返回以 n = max(st["n"], 1) 为分母的 n/hit1/hit5/hit10/mrr/qtype/miss 字典（verbose_qtype 为真值时先逐 qtype 打印分行）；
def run(questions, docs, qatoms_of, label, verbose_qtype=False):
    st = dict(h1=0, h5=0, h10=0, rr=0.0, n=0, empty=0)
    qt = defaultdict(lambda: dict(n=0, h1=0, h10=0, rr=0.0))
    miss = []
    for q in questions:
        ev = set(q.get("evidence_turns") or [])
        if not ev:
            continue
        qa = qatoms_of(q)
        st["n"] += 1
        if not qa:
            st["empty"] += 1
            continue
        scored = sorted(((jaccard(qa, na), nid) for nid, na in docs),
                        key=lambda t: (-t[0], t[1]))
        rank = next((r for r, (_s, nid) in enumerate(scored, 1) if nid in ev), 0)
        d = qt[q.get("qtype") or "?"]
        d["n"] += 1
        if rank == 1: st["h1"] += 1; d["h1"] += 1
        if 0 < rank <= 5: st["h5"] += 1
        if 0 < rank <= 10: st["h10"] += 1; d["h10"] += 1
        if rank:
            st["rr"] += 1.0 / rank
            d["rr"] += 1.0 / rank
        else:
            miss.append(q["qid"])
    n = max(st["n"], 1)
    print("  %-10s hit@1=%5.1f%%  hit@5=%5.1f%%  hit@10=%5.1f%%  MRR=%.4f  (n=%d, 空query=%d)"
          % (label, st["h1"] * 100.0 / n, st["h5"] * 100.0 / n,
             st["h10"] * 100.0 / n, st["rr"] / n, st["n"], st["empty"]))
    if verbose_qtype:
        for k, d in sorted(qt.items(), key=lambda x: -x[1]["n"]):
            print("      ├ %-20s n=%3d  hit@1 %5.1f%%  hit@10 %5.1f%%  MRR %.4f"
                  % (k, d["n"], d["h1"] * 100.0 / d["n"], d["h10"] * 100.0 / d["n"],
                     d["rr"] / d["n"]))
    return dict(n=n, hit1=st["h1"] / n, hit5=st["h5"] / n, hit10=st["h10"] / n,
                mrr=st["rr"] / n,
                qtype={k: dict(n=v["n"], hit1=v["h1"] / v["n"],
                               hit10=v["h10"] / v["n"], mrr=v["rr"] / v["n"])
                       for k, v in qt.items()},
                miss=miss)


def main():
    corpus, questions = load()
    ca = load_char_atoms()
    print("语料 %d · 题 %d · 字级原子库 %d 字\n" % (len(corpus), len(questions), len(ca)))

# 生效条件：返回 frozenset(normalize_en(str(c.get("text") or "")).split())；c 的 "text" 键缺失或其值为假值（None/空串）时按 "" 处理，得空 frozenset；
    def body_norm(c):     return frozenset(normalize_en(str(c.get("text") or "")).split())
# 生效条件：返回 frozenset(str(c.get("text") or "").lower().split())，即不做 normalize，仅转小写后按空白切词；c 的 "text" 键缺失或其值为假值时按 "" 处理，得空 frozenset；
    def body_raw(c):      return frozenset(str(c.get("text") or "").lower().split())
# 生效条件：返回 frozenset(zh_map_en(str(c.get("zh") or ""), ca).split())，其中 ca 取自其所在的 main 作用域；c 的 "zh" 键缺失或其值为假值时按 "" 处理，得空 frozenset；
    def zh_only(c):       return frozenset(zh_map_en(str(c.get("zh") or ""), ca).split())
# 生效条件：返回 frozenset(list(body_norm(c)) + list(zh_only(c)))，即正文归一化词表与中文映射词表合并去重后的集合；
    def full(c):          return frozenset(list(body_norm(c)) + list(zh_only(c)))

# 生效条件：返回 frozenset(zh_map_en(str(q.get("question") or ""), ca).split())；q 的 "question" 键缺失或其值为假值时按 "" 处理，得空 frozenset；
    def q_atoms(q):
        return frozenset(zh_map_en(str(q.get("question") or ""), ca).split())

    arms = [
        ("J2_full", [(c["id"], full(c)) for c in corpus]),
        ("J2_body", [(c["id"], body_norm(c)) for c in corpus]),
        ("J2_zh",   [(c["id"], zh_only(c)) for c in corpus]),
        ("J0_raw",  [(c["id"], body_raw(c)) for c in corpus]),
    ]
    out = {}
    for name, docs in arms:
        out[name] = run(questions, docs, q_atoms, name, verbose_qtype=(name == "J2_full"))
    with open("/tmp/locomo_jaccard_res.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n已保存 /tmp/locomo_jaccard_res.json")


if __name__ == "__main__":
    main()