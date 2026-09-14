#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cedict_en_zh.py · 词级 en→zh 反查表构建器（CC-CEDICT 词级，补字级反查缺口）

背景（2026-09-14 裁定路径）：u2c 归因臂实证「语义路机制+doc 侧上界 hit@10=99.2%」，
瓶颈 100% 在 query 侧 en→zh 归一覆盖（u2=23.8 vs u2c=99.2）。字级 char_atoms_clean
反查对剩余 OOV 词次覆盖仅 ~15%（expand_en_zh analyze 实证），且字级产物与 doc 侧
整词原子形态不齐（music→单字 vs 摘要「音乐」整词原子）。本脚本从 CC-CEDICT 词级
词典反查英文词→中文词，产出 md_cg/lexicon/cedict_en_zh.json（独立数据文件）——
许可 CC-BY-SA 4.0，故**不内联**进 MIT 的 en_normalizer.EN_ZH，独立文件+署名。

清理规则（与 expand_en_zh.py 同纪律，机械可审计，不做语义发明）：
  · 释义列剥括号注（(Taiwan pr. ...) 等）→ 剥 "to /a /an " 前缀 → 按非字母拆词
  · 纯字母 fullmatch [a-z]+；min_len>=3（2 字母缩写域碰撞）
  · STOPWORDS 排除；与手工 EN_ZH 重复 → 手工优先（build 时写入 excluded）
  · 同一英文词反查到多个中文词 → 冲突跳过并计数（宁缺勿滥）

用法：
    python md_cg/lexicon/build_cedict_en_zh.py download   # 拉 CEDICT 原始 gz（gitignored）
    python md_cg/lexicon/build_cedict_en_zh.py build      # 反查 → cedict_en_zh.json
    python md_cg/lexicon/build_cedict_en_zh.py analyze    # 500 题 OOV 覆盖上界取证

产物许可：本仓 cedict_en_zh.json 为 CC-CEDICT 派生数据，依 CC-BY-SA 4.0 署名：
    CC-CEDICT (https://www.mdbg.net/chinese/dictionary, CC BY-SA 4.0)
"""
import collections
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg.semantic.en_normalizer import EN_ZH, STOPWORDS  # noqa: E402

RAW_DIR = os.path.join(HERE, "data", "external", "cedict")
RAW_GZ = os.path.join(RAW_DIR, "cedict_1_0_ts_utf-8_mdbg.txt.gz")
RAW_TXT = os.path.join(RAW_DIR, "cedict.txt")
OUT_JSON = os.path.join(HERE, "md_cg", "lexicon", "cedict_en_zh.json")
QUESTIONS = os.path.join(HERE, "data", "external", "locomo_zh",
                         "raw_questions.jsonl")
CEDICT_URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[[^\]]+\]\s+/(.+)/\s*$")


def download():
    os.makedirs(RAW_DIR, exist_ok=True)
    req = urllib.request.Request(
        CEDICT_URL, headers={"User-Agent": "Mozilla/5.0 (dsh-memory lexicon builder)"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        blob = resp.read()
    with io.open(RAW_GZ, "wb") as f:
        f.write(blob)
    with gzip.open(RAW_GZ, "rb") as f:
        raw = f.read()
    with io.open(RAW_TXT, "w", encoding="utf-8", newline="\n") as f:
        f.write(raw.decode("utf-8", errors="replace"))
    print("[download] %d bytes → %s（%d 行）"
          % (len(blob), RAW_TXT, raw.count(b"\n")))
    return 0


def iter_entries():
    """CEDICT 行 → (简体, [英文释义段])。注释/空行跳过。"""
    with io.open(RAW_TXT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = LINE_RE.match(line)
            if not m:
                continue
            yield m.group(2), m.group(3)


def reverse_map(min_len=3):
    """词级反查 → (候选 {en: zh}, 冲突 {en: [zh...]}, 统计 dict)。

    条目级子段反查：释义按 / 段 → 括号注剥离 → 按 ;, 切子段 → 子段清洗后
    **恰为单个英文词**才收（"music album" 等复合短语被纯字母 fullmatch 滤除，
    不再以复合词条身份污染反查——首轮实证 4.4% 覆盖的根因）。
    """
    rev = collections.defaultdict(set)
    stat = {"entries": 0, "glosses": 0, "bracket_stripped": 0,
            "prefix_stripped": 0, "stopword": 0, "too_short": 0,
            "phrase_skipped": 0}
    for zh, gloss in iter_entries():
        stat["entries"] += 1
        for seg in gloss.split("/"):
            seg = re.sub(r"\([^)]*\)", "", seg)          # 剥括号注
            if seg != gloss:
                stat["bracket_stripped"] += 1
            for sub in re.split(r"[;,]", seg):           # 子段
                sub = sub.strip().lower()
                sub = re.sub(r"^(to|a|an) ", "", sub)
                if sub != sub.strip().lower():
                    stat["prefix_stripped"] += 1
                if not re.fullmatch(r"[a-z]+", sub):
                    stat["phrase_skipped"] += 1
                    continue
                if sub in STOPWORDS:
                    stat["stopword"] += 1
                    continue
                if len(sub) < min_len:
                    stat["too_short"] += 1
                    continue
                stat["glosses"] += 1
                rev[sub].add(zh)
    cand, conflicts = {}, {}
    for en, zhs in rev.items():
        if len(zhs) == 1:
            cand[en] = next(iter(zhs))
        else:
            conflicts[en] = sorted(zhs)
    return cand, conflicts, stat


def _corpus_text():
    """领域语料全文（zh 正文+五槽摘要）——冲突集频次消歧用。

    消歧本质=doc 侧自监督：query 词要匹配的对象就是 doc 侧原子，
    「公园」在语料高频、「园囿」零出现——频次直接裁决，与匹配目标自洽。
    """
    from md_cg import bench6_common as b6
    buf = []
    with io.open(b6.CORPUS567, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            parts = [c.get("zh") or ""]
            for v in (c.get("zh_fields") or {}).values():
                if isinstance(v, str):
                    parts.append(v)
            buf.append("".join(parts))
    return "\n".join(buf)


def _atoms_texts():
    """doc 侧同构消歧空间（2026-09-14 消歧口径升级）。

    取证：tattoo 冲突集（刺字/刺花/刺青/文身/纹…）整词形在语料 count 全零
    → 旧口径整词丢弃；而真实用词「纹身」在摘要 fm.semantic 落盘形态是
    切分碎片「纹 身」——消歧 count 的字符串空间与匹配面形态从未对齐，
    11257 个英文词（高频多义词重灾区）因此被整词丢弃。

    返回 (摘要原子串, 正文原子串)：候选词经 semantic_atoms 切分后以
    「原子 空格 原子」形态计数——与检索打分面（pair_hits 的 doc 侧输入）
    完全同构。摘要优先（fm.semantic 是语义路唯一 doc 侧），正文兜底
    （词法路匹配面）。
    """
    from md_cg import bench6_common as b6
    from md_cg.semantic.canonical import semantic_atoms
    sums, bodys = [], []
    with io.open(b6.CORPUS567, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            s = str((c.get("zh_fields") or {}).get("summary") or "").strip()
            if not s:
                s = str(c.get("zh") or "").strip()
            if s:
                sums.append(" ".join(semantic_atoms(s)))
            body = str(c.get("zh") or "").strip()
            if body:
                bodys.append(" ".join(semantic_atoms(body)))
    return "\n".join(sums), "\n".join(bodys)


def _disambiguate(en, zhs, texts):
    """单英文词冲突集三级消歧：摘要碎片串 → 正文碎片串 → 碎片字级和。

    返回 (胜出中文词, 级别) 或 (None, -1)（全零丢弃，宁缺勿滥——不发明词形）。
    切分形态计数与 doc 侧匹配面同构（纹身→「纹 身」对「纹 身」count）；
    字级兜底只解决「词条整词与语料词形微差」（文身 vs 纹身 异形词——
    「文」「身」碎片分别可数）。候选恒限定词典集合内，不做语义发明。
    """
    from md_cg.semantic.canonical import semantic_atoms
    sums, bodys = texts
    scored = []
    for z in sorted(zhs):
        if not 2 <= len(z) <= 4:
            continue
        frag = " ".join(semantic_atoms(z))
        n = sums.count(frag)
        if n > 0:
            scored.append((n, 0, len(z), z))
    if not scored:
        for z in sorted(zhs):
            if not 2 <= len(z) <= 4:
                continue
            frag = " ".join(semantic_atoms(z))
            n = bodys.count(frag)
            if n > 0:
                scored.append((n, 1, len(z), z))
    if not scored:
        for z in sorted(zhs):
            if not 2 <= len(z) <= 4:
                continue
            atoms = semantic_atoms(z)
            n = sum(sums.count(" ".join(atoms[i:i + 1])) for i in range(len(atoms)))
            if n > 0:  # 字级兜底门槛试验（>=4）实测 u2 逐位一致：字级回收词
                       # 为开放域词，locomo 题面零出现，无噪声代价，保留全覆盖
                scored.append((n, 2, len(z), z))
    if not scored:
        return None, -1
    scored.sort(key=lambda t: (-t[0], t[1], t[2], t[3]))
    return scored[0][3], scored[0][1]


def build(min_len=3, domain=True):
    cand, conf, stat = reverse_map(min_len)
    stat["disambiguated"] = 0
    stat["disambiguated_body"] = 0
    stat["disambiguated_char"] = 0
    stat["disambiguated_dropped"] = 0
    if domain and conf:
        # 冲突消歧（2026-09-14 口径升级）：doc 侧同构三级裁决
        # （摘要碎片串→正文碎片串→碎片字级和）——候选词按 semantic_atoms
        # 切分形态计数，与 fm.semantic 匹配面完全同构；旧口径整词形 count
        # 与摘要落盘形态（纹 身）错位，高频多义词（accept/describe/tattoo）
        # 重灾区 11257 词被整词丢弃。词级候选 len 2-4——单字频次虚高排除；
        # 全零丢弃（宁缺勿滥，不发明词形）。
        texts = _atoms_texts()
        for en in sorted(conf):
            z, lv = _disambiguate(en, conf[en], texts)
            if z:
                cand[en] = z
                stat["disambiguated"] += 1
                if lv == 1:
                    stat["disambiguated_body"] += 1
                elif lv == 2:
                    stat["disambiguated_char"] += 1
                conf.pop(en)
            else:
                stat["disambiguated_dropped"] += 1
    overlap = sorted(set(cand) & set(EN_ZH))
    for w in overlap:
        cand.pop(w)                                       # 手工表优先
    out = {
        "meta": {
            "name": "cedict_en_zh",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": "CC-CEDICT (https://www.mdbg.net/chinese/dictionary)",
            "license": "CC BY-SA 4.0（派生数据，独立文件署名，不入 MIT 内联表）",
            "min_len": min_len,
            "rules": "剥括号注/to-a-an 前缀；条目级子段（单词条释义才收）；"
                     "纯字母；STOPWORDS 排除；冲突集 doc 语料频次消歧"
                     "（三级同构：摘要碎片串→正文碎片串→碎片字级和，"
                     "候选 2-4 字）；手工 EN_ZH 优先",
            "domain_disambiguation": (
                "locomo corpus567 摘要/正文 semantic_atoms 原子串同构计数裁决"
                "（与 fm.semantic 匹配面形态一致），评测特化产物"
                if domain else "无（纯唯一映射）"),
            "stats": stat,
            "n_map": len(cand), "n_conflict": len(conf),
            "n_handmade_overlap": len(overlap),
        },
        "map": dict(sorted(cand.items())),
    }
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("[build] 词级映射 %d 键（消歧 %d / 冲突跳过 %d / 手工重叠让位 %d）→ %s"
          % (len(cand), stat["disambiguated"], len(conf), len(overlap), OUT_JSON))
    print("[build] 统计: %s" % json.dumps(stat, ensure_ascii=False))
    return 0


def analyze():
    """集成后 normalize 的最终残留取证（en_normalizer 已加载 cedict_en_zh.json，
    此处 unknown_keep 即全链路翻译后的真 OOV）。"""
    from md_cg.semantic.en_normalizer import normalize_en_query
    unk = collections.Counter()
    with io.open(QUESTIONS, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            q = json.loads(line)
            terms, detail = normalize_en_query(str(q.get("question") or ""))
            for d in detail:
                if d.get("action") == "unknown_keep":
                    unk[str(d.get("orig") or "").lower()] += 1
    total_tokens = 0
    kept_tokens = 0
    with io.open(QUESTIONS, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            q = json.loads(line)
            total_tokens += len(normalize_en_query(str(q.get("question") or ""))[0])
    print("[analyze] 集成后最终 OOV：去重 %d 词 / %d 词次（残留原子序列长度 %d）"
          % (len(unk), sum(unk.values()), total_tokens))
    print("\n[analyze] top 30 最终残留（真缺口，只配手工定向补）：")
    for w, n in unk.most_common(30):
        print("  %4d  %s" % (n, w))
    return 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    if mode == "download":
        return download()
    if mode == "build":
        return build()
    if mode == "analyze":
        return analyze()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
