#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""expand_en_zh.py · en_normalizer.EN_ZH 机械扩表器（char_atoms_clean 反查）

背景（2026-09-14 裁定路径）：locomo-500 英文题 OOV 90.2%（3213/3563 归一原子
为英文保留词），手工 EN_ZH（135 键）只覆盖开放域词面约 10%，且零星补词对
开放域无效（bench_unified_en 复测实证）。本脚本从 md_cg/lexicon/
char_atoms_clean.json（6321 条字级映射，源 CC-CEDICT）反查英文单词→中文字，
机械扩入 en_normalizer.EN_ZH——以字面量写回源码，保持 EN_ZH 内联零外部
数据依赖的既有裁定。

清理规则（机械、可审计，不做语义发明）：
  · en_raw 下划线还原后按词典释义惯例剥离前缀 "to / a / "（动词/冠词惯用）
  · 还原后须为纯字母单词（fullmatch [a-z]+）——短语/多义项/带标点释义整条排除
  · 长度 >= min_len（默认 3；2 字母缩写域碰撞风险）
  · 既有 STOPWORDS 成员排除；与现有 EN_ZH 键重复时手工表优先（跳过）
  · 同一英文词反查到多个中文字 → 跳过并审计（一词多义不猜优先级，宁缺勿滥）

用法：
    python md_cg/lexicon/expand_en_zh.py analyze           # 收益上界取证
    python md_cg/lexicon/expand_en_zh.py build [--min-len 3]
"""
import collections
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg.semantic.en_normalizer import (   # noqa: E402
    EN_ZH, STOPWORDS, normalize_en_query)

CHAR_ATOMS = os.path.join(HERE, "md_cg", "lexicon", "char_atoms_clean.json")
QUESTIONS = os.path.join(HERE, "data", "external", "locomo_zh",
                         "raw_questions.jsonl")   # = bench6_common.EN_QUESTIONS
NORMALIZER = os.path.join(HERE, "md_cg", "semantic", "en_normalizer.py")
AUTO_BEGIN, AUTO_END = "<<EN_ZH_AUTO>>", "<<END_EN_ZH_AUTO>>"


# 生效条件：无需入参；逐行读取模块常量 QUESTIONS 指向的内容，仅在 line.strip() 为真的行上 json.loads 该行并追加到 qs，最终返回 qs（全为空白行时返回空列表）。
def load_questions():
    qs = []
    with io.open(QUESTIONS, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                qs.append(json.loads(line))
    return qs


# 生效条件：入参 min_len 给定；逐条 lexicon 记录的 en_raw（假值时回落 en，两者皆假值则取空串）转小写、下划线转空格并剥离 to/a/an 前缀后，不在 STOPWORDS 且能 fullmatch [a-z]+ 者计入 wordlike 并仅当长度 ≥ min_len 时并入 en→zh 集合（< min_len 计 too_short 后排除，STOPWORDS 计 stopword 后排除），最终单一 zh 的入 cand、多 zh 的入 conflicts，返回 (cand, conflicts, stat)。
def reverse_map(min_len):
    """char_atoms_clean → (候选 {en: zh}, 冲突 {en: [zh...]}, 统计 dict)"""
    with io.open(CHAR_ATOMS, encoding="utf-8") as f:
        data = json.load(f)
    rev = collections.defaultdict(set)
    stat = {"total": data.get("meta", {}).get("total", 0), "wordlike": 0,
            "prefix_stripped": 0, "stopword": 0, "too_short": 0}
    for zh, rec in data.get("lexicon", {}).items():
        e = str(rec.get("en_raw") or rec.get("en") or "").strip().lower()
        e = e.replace("_", " ")
        stripped = re.sub(r"^(to|a|an) ", "", e)
        if stripped != e:
            stat["prefix_stripped"] += 1
        e = stripped
        if e in STOPWORDS:
            stat["stopword"] += 1
            continue
        if not re.fullmatch(r"[a-z]+", e):
            continue                       # 短语/多义项/带标点——整条排除
        stat["wordlike"] += 1
        if len(e) < min_len:
            stat["too_short"] += 1
            continue
        rev[e].add(zh)
    cand, conflicts = {}, {}
    for en, zhs in rev.items():
        if len(zhs) == 1:
            cand[en] = next(iter(zhs))
        else:
            conflicts[en] = sorted(zhs)
    return cand, conflicts, stat


# 生效条件：required 为空（无入参）；对 QUESTIONS 经 load_questions 读入的题面按 normalize_en_query 的 detail 统计 unknown_keep/proper_noun_keep 词次后，对 min_len=2、3、4 各调一次 reverse_map 打印统计，再对 min_len=3 二次调 reverse_map 取 cand 算命中词次、打印 top15 一对多冲突、并以 extra_map=cand 复跑 normalize_en_query 统计扩表后英文保留词次，全程只打印、返回 None。
def analyze():
    """扩表收益上界：500 题 OOV 词频 × 反查覆盖率（词次口径）。"""
    qs = load_questions()
    n_tok = n_kept = 0
    unk = collections.Counter()            # unknown_keep（词表缺口=扩表靶子）
    proper = collections.Counter()         # proper_noun_keep（设计保留，扩表不解）
    for q in qs:
        text = str(q.get("question") or "")
        _terms, detail = normalize_en_query(text)
        for d in detail:
            n_tok += 1
            w = str(d.get("orig") or "").lower()
            if d.get("action") == "unknown_keep":
                unk[w] += 1
                n_kept += 1
            elif d.get("action") == "proper_noun_keep":
                proper[w] += 1
                n_kept += 1
    print("[analyze] 题 %d / 归一 token %d / 英文保留 token %d（%.1f%%）"
          % (len(qs), n_tok, n_kept, 100.0 * n_kept / max(n_tok, 1)))
    print("[analyze] unknown_keep 去重 %d 词（%d 词次）；proper_noun_keep "
          "去重 %d 词（%d 词次，设计上保留原名，扩表不解）"
          % (len(unk), sum(unk.values()), len(proper), sum(proper.values())))
    print("\n[analyze] 反查候选量级（按 min_len 扫描）：")
    for ml in (2, 3, 4):
        cand, conf, stat = reverse_map(ml)
        print("  min_len=%d → 候选 %d / 一对多冲突 %d 词 / wordlike %d / "
              "前缀剥离 %d / 过短排除 %d"
              % (ml, len(cand), len(conf), stat["wordlike"],
                 stat["prefix_stripped"], stat["too_short"]))
    cand, conf, _stat = reverse_map(3)
    hit_tok = sum(n for w, n in unk.items() if w in cand)
    print("\n[analyze] unknown_keep 词次被 min_len=3 候选覆盖：%d/%d（%.1f%%）"
          % (hit_tok, sum(unk.values()),
             100.0 * hit_tok / max(sum(unk.values()), 1)))
    print("[analyze] top 30 unknown_keep（* = 可被反查覆盖）：")
    for w, n in unk.most_common(30):
        print("  %-4d %-20s %s" % (n, w, "*" if w in cand else ""))
    print("\n[analyze] top 15 一对多冲突（宁缺勿滥跳过）：")
    for w in sorted(conf)[:15]:
        print("  %-20s -> %s" % (w, " ".join(conf[w])))
    # 模拟扩表后的保留率（词次口径；原子级验收以 bench_unified_en 复跑为准）
    n_after = 0
    for q in qs:
        terms, _d = normalize_en_query(str(q.get("question") or ""),
                                       extra_map=cand)
        n_after += sum(1 for t in terms if re.search(r"[A-Za-z]", t))
    print("\n[analyze] 模拟扩表（min_len=3）后英文保留词次：%d → %d"
          % (n_kept, n_after))


# 生效条件：入参 min_len 给定；cand 取 reverse_map(min_len) 中键不在 EN_ZH 的部分，若 NORMALIZER 中匹配到 AUTO_BEGIN…AUTO_END 标记段则整段替换，否则要求锚点行存在（缺失即断言失败不写回）后插入，compile 校验通过则写回 NORMALIZER 并返回 0（conf 仅用于打印）。
def build(min_len):
    """反查扩表 → 字面量写回 en_normalizer.py（幂等标记块，重跑即刷新）。"""
    cand, conf, stat = reverse_map(min_len)
    cand = {w: z for w, z in cand.items() if w not in EN_ZH}
    with io.open(NORMALIZER, encoding="utf-8") as f:
        src = f.read()
    lines = ["    # ---- 机械扩表（char_atoms_clean %d 字反查，"
             "md_cg/lexicon/expand_en_zh.py 生成，勿手改）----"
             % stat["total"],
             "    # %s" % AUTO_BEGIN]
    items = sorted(cand.items())
    per = 4
    for i in range(0, len(items), per):
        chunk = items[i:i + per]
        lines.append("    " + " ".join('"%s": "%s",' % (w, z)
                                       for w, z in chunk))
    lines.append("    # %s" % AUTO_END)
    block = "\n".join(lines)
    pat = re.compile(r"( *)# %s.*?# %s\n" % (re.escape(AUTO_BEGIN),
                                             re.escape(AUTO_END)), re.S)
    if pat.search(src):
        src = pat.sub(block + "\n", src, count=1)
    else:
        anchor = '    "rain": "雨", "snow": "雪",\n'
        assert anchor in src, "EN_ZH 尾部锚点缺失，拒绝写回"
        src = src.replace(anchor, anchor + block + "\n", 1)
    compile(src, NORMALIZER, "exec")       # 语法自检，失败不落盘
    with io.open(NORMALIZER, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print("[build] EN_ZH 扩表 +%d 键（min_len=%d，冲突跳过 %d 词）→ %s"
          % (len(cand), min_len, len(conf), NORMALIZER))
    return 0


# 生效条件：无入参；在模块常量 NORMALIZER 中匹配不到「# ---- 机械扩表 … AUTO_END」段时打印零改动并返回 0，匹配到时删除该段、compile 校验通过后写回并返回 0。
def clean():
    """删除 en_normalizer.py 中的机械扩表段（幂等；段不存在则零改动）。"""
    with io.open(NORMALIZER, encoding="utf-8") as f:
        src = f.read()
    pat = re.compile(r" *# ---- 机械扩表.*?# %s\n" % re.escape(AUTO_END), re.S)
    if not pat.search(src):
        print("[clean] 无机械扩表段，零改动")
        return 0
    src = pat.sub("", src, count=1)
    compile(src, NORMALIZER, "exec")
    with io.open(NORMALIZER, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print("[clean] 机械扩表段已删除 → %s" % NORMALIZER)
    return 0


# 生效条件：无入参；按 sys.argv[1] 分派（长度不超 1 时回落为 "analyze"）——"analyze" 调 analyze() 返回 0；"build" 时 ml 初值 3，若 sys.argv 含 "--min-len" 则取其下一个元素 int() 后覆盖 ml，返回 build(ml)；"clean" 返回 clean()；其余取值（含空串等未知模式）打印 __doc__ 并返回 2。
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    if mode == "analyze":
        analyze()
        return 0
    if mode == "build":
        ml = 3
        if "--min-len" in sys.argv:
            ml = int(sys.argv[sys.argv.index("--min-len") + 1])
        return build(ml)
    if mode == "clean":
        return clean()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
