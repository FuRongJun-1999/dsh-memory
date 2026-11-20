# -*- coding: utf-8 -*-
"""退化守卫：把 2026-11-20 实测出的复读 / 固化判据做成可复用检测器。

# 功能名：degrade_guard —— 跨轮复述、句式固化、催稿段、理由缺失的统一检测
# 生效条件：需要判断一组连续输出（多轮链条 / 长会话切片）是否发生退化时；
#           或验收「理由形态」是否退化成套话时
# 子功能：
#   ① cross_turn_sim      相邻轮 bigram Jaccard 与最长公共子串（#996 阈值 0.4 / 20 字）
#   ② nag_runs            同轮内连续 ≥3 行且每行 ≤6 字的祈使句段（#996「催稿」判据）
#   ③ reason_spans        抽取理由段（含 因为/我把它理解成/不确定/依据是 等标记）
#   ④ opening_uniqueness  理由段开头前 8 字的唯一率（防句式固化，主判据）
#   ⑤ check_chain         综合判定：返回 verdict 与逐项读数
# 执行：全部为纯函数，无 IO、无副作用；调用方传入文本列表
# 验证方式：md_cg/test_degrade_guard.py（用 2026-11-20 实测样本做断言）
# 不适用条件：单轮场景无跨轮可比；非中文文本 bigram 口径不适用；
#             本模块只判「形态是否退化」，不判「内容对不对」
"""
import re

#: #996 原文阈值：相邻两轮正文 bigram Jaccard > 0.4 判复述
CROSS_TURN_JACCARD = 0.4
#: #996 原文阈值：相邻两轮最长公共子串 ≥ 20 字判复述
CROSS_TURN_LCS = 20
#: 催稿段：连续 ≥ NAG_RUN_MIN 行，每行去标点后 ≤ NAG_LINE_MAX 字
NAG_RUN_MIN = 3
NAG_LINE_MAX = 6
#: 2026-11-20 实测合格线（reason_form_v2，3 臂 × 2 链 × 6 轮 = 36 份）
#:   三示例臂：理由段 12/12、开头唯一 12/12、Jaccard 0.18 ⇒ 合格
#:   单示例臂：理由段 12/12、开头唯一 5/12、Jaccard 0.21 ⇒ 不合格（固化）
#:   无示例臂：理由段 1/12 ⇒ 不合格（不写）
REASON_PRESENCE_MIN = 10.0 / 12.0
OPENING_UNIQUE_MIN = 8.0 / 12.0

#: 理由标记词（任一出现即视为该句承载理由）
REASON_MARKS = (
    "因为", "我把它理解成", "不确定", "我拿不准", "我判断",
    "理由是", "考虑到", "依据是", "按…处理", "若实际",
)


def _nows(s):
    """去空白（等价 #996 的分词后口径）。"""
    return re.sub(r"\s+", "", s or "")


def bigrams(s):
    return set(s[i:i + 2] for i in range(len(s) - 1))


def jaccard(a, b):
    """bigram Jaccard；任一为空返回 0.0（不判为复述）。"""
    A, B = bigrams(_nows(a)), bigrams(_nows(b))
    if not A or not B:
        return 0.0
    return len(A & B) / float(len(A | B))


def lcs_len(a, b):
    """最长公共子串长度（滚动数组，O(len(a)*len(b)) 时间、O(len(b)) 空间）。"""
    a, b = _nows(a), _nows(b)
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                v = prev[j - 1] + 1
                cur[j] = v
                if v > best:
                    best = v
        prev = cur
    return best


def cross_turn_sim(texts):
    """相邻轮相似度：返回 [(i, jaccard, lcs), ...]，i 表示 texts[i-1] 与 texts[i]。"""
    out = []
    for i in range(1, len(texts or [])):
        out.append((i, jaccard(texts[i - 1], texts[i]), lcs_len(texts[i - 1], texts[i])))
    return out


def nag_runs(text):
    """最长「催稿段」长度：连续若干行，每行去标点后 ≤ NAG_LINE_MAX 字。"""
    best = run = 0
    for line in (text or "").splitlines():
        s = line.strip().strip("。！!；;，,、")
        if 0 < len(s) <= NAG_LINE_MAX:
            run += 1
            if run > best:
                best = run
        else:
            run = 0
    return best


def reason_spans(text):
    """抽取承载理由的句子（按句号/问号/换行切分，命中任一标记词即计入）。"""
    out = []
    for s in re.split(r"[。！？\n]", text or ""):
        s = s.strip()
        if s and any(m in s for m in REASON_MARKS):
            out.append(s)
    return out


def opening_uniqueness(texts, head=8):
    """理由段开头前 head 字的唯一率：返回 (唯一数, 理由段总数)。"""
    heads = []
    for t in texts or []:
        sp = reason_spans(t)
        if not sp:
            continue
        heads.append(_nows(sp[0])[:head])
    if not heads:
        return 0, 0
    return len(set(heads)), len(heads)


def check_chain(texts, *, requirement="general"):
    """综合判定一组连续输出是否退化。

    requirement:
      "general"  只查复述与催稿（#996 两项）
      "reason"   额外查理由形态（存在率 / 开头唯一率 / 复述），三条同时满足才算合格

    返回 dict：verdict ∈ {ok, degraded, insufficient}；各项读数与失败项在 failures 里。
    """
    texts = list(texts or [])
    res = {"verdict": "insufficient", "n_turns": len(texts), "failures": [], "metrics": {}}
    if len(texts) < 2:
        res["failures"].append("轮数不足 2，无法比较跨轮")
        return res
    sims = cross_turn_sim(texts)
    worst_j = max(s[1] for s in sims)
    worst_l = max(s[2] for s in sims)
    worst_nag = max(nag_runs(t) for t in texts)
    res["metrics"].update({
        "max_jaccard": round(worst_j, 4),
        "max_lcs": worst_l,
        "max_nag_run": worst_nag,
    })
    if worst_j > CROSS_TURN_JACCARD:
        res["failures"].append("跨轮复述：Jaccard %.2f > %.2f" % (worst_j, CROSS_TURN_JACCARD))
    if worst_l >= CROSS_TURN_LCS:
        res["failures"].append("跨轮复述：最长公共子串 %d 字 ≥ %d" % (worst_l, CROSS_TURN_LCS))
    if worst_nag >= NAG_RUN_MIN:
        res["failures"].append("催稿段：连续 %d 行短句 ≥ %d" % (worst_nag, NAG_RUN_MIN))
    if requirement == "reason":
        uniq, total = opening_uniqueness(texts)
        presence = total / float(len(texts))
        res["metrics"].update({"reason_presence": round(presence, 4),
                               "opening_unique": "%d/%d" % (uniq, total)})
        if presence < REASON_PRESENCE_MIN:
            res["failures"].append(
                "理由段存在率 %.0f%% < %.0f%%（多半是不写）" % (presence * 100, REASON_PRESENCE_MIN * 100))
        if total and uniq / float(total) < OPENING_UNIQUE_MIN:
            res["failures"].append(
                "理由开头唯一率 %d/%d < %.0f%%（句式固化）" % (uniq, total, OPENING_UNIQUE_MIN * 100))
    res["verdict"] = "degraded" if res["failures"] else "ok"
    return res