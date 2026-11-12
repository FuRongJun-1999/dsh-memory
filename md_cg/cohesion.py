# -*- coding: utf-8 -*-
"""拼装接缝检测（cohesion）——判断一段上下文是「可闭合」还是「散段拼装」。

为什么需要（2026-10-24 实测，见 docs/dsh设计/上下文管理研究_第十六轮）：
    检索结果的全局词汇重叠 ratio 会骗人（中位 2.61，比连续文本还高）——
    因为**节点内部的强承接把接缝的断裂稀释了**。
    分界测量才看清真相：块内承接 0.09-0.13，跨节点接缝仅 0.00-0.035。

两个读数：
    inner_adj       块内部相邻句重叠均值（"每块都对"）
    cross_boundary  相邻块「末句→首句」重叠均值（"拼不成一件事"）
    seam_ratio      cross / inner，低于阈值即判拼装为断

理论依据：
    智能论 3.4 §3.5 意识层输入控制 + 使用者底稿「可闭合性」命题。
    本模块把"可闭合性"落成一个纯计数、无需 LLM 的代理指标。

诚实边界：
    1. 这是**结构代理**，不是语义判定——接缝高不代表支撑得住某个判断；
    2. 阈值 0.5 是初设值，来自 4 个检索样本，未做充分验证；
    3. 只对中文/英文混排做过验证；纯代码块或表格文本不适用（句子切分失效）。
"""

import re

__all__ = [
    "split_sentences", "inner_adjacency", "cross_boundary",
    "seam_ratio", "check", "DEFAULT_THRESHOLD",
]

#: 接缝比阈值：低于此值判为「拼装断裂」。初设 0.5（4 样本，待更多验证）。
DEFAULT_THRESHOLD = 0.5

_SENT_SPLIT = re.compile(r"(?<=[。！？;；\n])")


def split_sentences(text, min_len=4, drop_headings=True):
    """切句。

    过滤两类噪声：
        ① 过短片段（标点、单字）
        ② **标题行**（以 # 开头）——2026-10-24 实测：标题与正文无共同词，
           会把真实接缝算成 0（同章节按段落切两半时首句恰是 "### 2.7.1 …"）。
           标题是小节标记，不是承接内容，不参与重叠计算。
    """
    out = []
    for piece in _SENT_SPLIT.split(str(text or "")):
        for line in piece.split("\n"):
            s = line.strip()
            if drop_headings and s.startswith("#"):
                continue
            if len(s) >= min_len:
                out.append(s)
    return out


def _tokens(sentence):
    """中英混排取词：中文二字滑窗近似、英文/标识符按词。"""
    s = str(sentence)
    zh = re.findall(r"[\u4e00-\u9fa5]", s)
    bigrams = {"".join(zh[i:i + 2]) for i in range(len(zh) - 1)}
    words = {w.lower() for w in re.findall(r"[A-Za-z_]{2,}", s)}
    return bigrams | words


def _overlap(a, b):
    """两集合重叠：交集 / 较小集。空集返回 None（不计入均值）。"""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return None
    return len(ta & tb) / float(min(len(ta), len(tb)))


def _mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def inner_adjacency(segments):
    """块内部相邻句重叠均值。segments 为「每块一个字符串」的列表。"""
    vals = []
    for seg in segments or []:
        sents = split_sentences(seg)
        for a, b in zip(sents, sents[1:]):
            vals.append(_overlap(a, b))
    return _mean(vals)


#: 接缝比较窗口：取上块末尾 WINDOW 句与下块开头 WINDOW 句整体比较。
#: 为什么不是「末句 vs 首句」——相邻两句常无共同词却有逻辑承接，
#: 单句对太稀疏会系统性返回 0（2026-10-24 实测：同章节切两半也判 0.0）。
WINDOW = 3


def cross_boundary(segments):
    """相邻块接缝承接：上块末尾窗口 vs 下块开头窗口的重叠均值。"""
    segs = [s for s in (segments or []) if s]
    if len(segs) < 2:
        return 0.0
    vals = []
    for prev, nxt in zip(segs, segs[1:]):
        p = split_sentences(prev)
        n = split_sentences(nxt)
        if p and n:
            # 逐句对算再取均值：**不要先合并成长文本**——合并后 bigram 集合变大，
            # 交集/较小集 会被稀释到接近 0（2026-10-24 实测：同章节切两半也判 0.0）。
            cross = [_overlap(a, b) for a in p[-WINDOW:] for b in n[:WINDOW]]
            vals.append(_mean(cross))
    return _mean(vals)


def seam_ratio(segments):
    """接缝比 = cross_boundary / inner_adj。

    三种"算不出"一律返回 None，**不记 0**——把「没法算」当成「断裂」是
    与 I2 同型的错误（不确定的结论不能伪装成确定）：
        ① 块数 < 2      —— 根本没有接缝可言
        ② inner_adj = 0 —— 分母为零
    """
    segs = [s for s in (segments or []) if s]
    inner = inner_adjacency(segs)
    cross = cross_boundary(segs) if len(segs) >= 2 else 0.0
    if len(segs) < 2:
        return None, {"inner_adj": round(inner, 4), "cross_boundary": None,
                      "segments": len(segs), "ratio": None}
    ratio = (cross / inner) if inner > 0 else None
    return ratio, {"inner_adj": round(inner, 4), "cross_boundary": round(cross, 4),
                   "segments": len([s for s in (segments or []) if s]),
                   "ratio": (round(ratio, 3) if ratio is not None else None)}


def check(segments, threshold=DEFAULT_THRESHOLD):
    """判定拼装是否可闭合。

    返回 dict：
        ok         True=接缝尚可；False=判为断裂；None=**无法判定**（不给默认通过）
        reason     文字说明
    注意 ok=None 与 ok=False 不同：前者是「算不出来」，后者是「算出来是断的」。
    """
    ratio, detail = seam_ratio(segments)
    detail["threshold"] = threshold
    if ratio is None:
        detail["ok"] = None
        detail["reason"] = "无法判定：块内无有效相邻句（内容过短或全是表格/代码）"
        return detail
    detail["ok"] = ratio >= threshold
    detail["reason"] = ("接缝承接为块内的 %.0f%%，%s阈值 %.2f"
                        % (ratio * 100,
                           "不低于" if detail["ok"] else "**低于**",
                           threshold))
    return detail


def main(argv=None):
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("用法：python -m md_cg.cohesion <文件1> <文件2> ...")
        print("      把每个文件当作一个「块」，测拼装接缝")
        return 2
    segs = []
    for p in argv:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                segs.append(fh.read())
        except OSError as exc:
            print("跳过 %s：%s" % (p, exc), file=sys.stderr)
    rep = check(segs)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if rep["ok"] is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
