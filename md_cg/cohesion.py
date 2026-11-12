# -*- coding: utf-8 -*-
"""上下文质量读数（cohesion）——接缝 + 信噪比两个读数。

本模块提供上下文失效三种形态中的两种的读数：
    * **断裂** → seam_ratio（接缝/块内）
    * **稀释** → signal_ratio（目标词占全部实词的比例）
第三种（丢弃）由 constraint_watch 覆盖。三者合起来对应框架 v5 第二节。

——以下为原始说明（接缝部分）——

判断一段上下文是「可闭合」还是「散段拼装」。

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

**适用边界（2026-10-24 实测补充，重要）**：
    本模块测的是**词汇承接**，它区分的是「连续叙述」与「章节并列」，
    而**不是**「好」与「坏」。同样低的接缝比，含义取决于文本类型：

        连续叙述（原文段落、论文正文）→ 低接缝 = 真断裂
        结构化文档（报告、设计稿）      → 低接缝 = 正常（章节本就并列，
                                          读者靠标题层级导航，不靠句间重叠）

    实测证据：本研究系列 17 份研究文档（结构化写作）中有 3 份被本模块判为
    「断裂」（ratio 0.128 / 0.339 / 0.386），但它们逻辑上均连贯。

    因此正确用法是**两步**：
        ① 先定任务需要哪种形态——L1「查事实」并列够用；L3「理解论证」需连续；
        ② 再测接缝比；仅当「任务需要连续而 ratio 低」时才判为缺陷。
    单看 ratio 下结论是错的（见 docs/dsh设计/上下文管理研究_第十八轮）。
"""

import re

__all__ = [
    "split_sentences", "inner_adjacency", "cross_boundary",
    "seam_ratio", "check", "DEFAULT_THRESHOLD",
    "signal_ratio", "SIGNAL_LOW", "SIGNAL_OK",
    "logic_flow", "LOGIC_LOW", "LOGIC_OK", "CONNECTORS",
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


def _token_list(text):
    """实词**列表**（不去重，保留词次）。用于稀释度量。"""
    s = str(text or "")
    zh = re.findall(r"[\u4e00-\u9fa5]", s)
    bigrams = ["".join(zh[i:i + 2]) for i in range(len(zh) - 1)]
    words = [w.lower() for w in re.findall(r"[A-Za-z_]{2,}", s)]
    return bigrams + words


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


#: 信噪比参考线（2026-10-24 第三十四轮实测）：
#: 233 字上下文目标占 16.5%，1 万字上下文仅 0.45%。
#: 低于 1% 视为「严重稀释」——目标事实被淹没。
SIGNAL_LOW = 0.01
SIGNAL_OK = 0.05


def signal_ratio(target_text, context_text):
    """信噪比：目标文本的实词占上下文全部实词的比例。

    这是「稀释」这一种损失的读数（框架 v5 第二节）。
    回答的不是「目标在不在」，而是「**目标有多显眼**」——
    在不在由 constraint_watch 判，显不显眼由本函数判。

    返回 dict：
        ok       True=占比不低于 SIGNAL_OK；
                 False=低于 SIGNAL_LOW（严重稀释）；
                 None=**介于两者之间**（说不清，不给默认通过）
        ratio    目标词占全部实词的比例
        verdict  'clear' / 'thin' / 'drowned' / 'unknown'
    """
    # 按**词次**而非词种：稀释的本质是「占用空间」，
    # 若用 set 去重，重复内容不占空间，稀释就测不出来
    # （2026-10-24 守卫抓到：'无关内容。'×400 用去重法得 70.8% clear，实为严重稀释）。
    tgt_list = _token_list(target_text)
    if not tgt_list:
        return {"ok": None, "ratio": None, "verdict": "unknown",
                "reason": "目标文本没有实词"}
    ctx_list = _token_list(context_text)
    if not ctx_list:
        return {"ok": None, "ratio": None, "verdict": "unknown",
                "reason": "上下文为空"}
    tgt_set = set(tgt_list)
    hit = sum(1 for w in ctx_list if w in tgt_set)
    ratio = hit / float(len(ctx_list))
    tgt = tgt_set
    ctx = ctx_list
    if ratio >= SIGNAL_OK:
        ok, verdict = True, "clear"
    elif ratio < SIGNAL_LOW:
        ok, verdict = False, "drowned"
    else:
        ok, verdict = None, "thin"
    return {"ok": ok, "ratio": round(ratio, 4), "verdict": verdict,
            "target_words": len(tgt), "hit_words": hit,
            "context_words": len(ctx),
            "note": "占比 %.2f%%（%d/%d 实词）" % (ratio * 100, hit, len(ctx))}


#: 逻辑连接词（2026-10-24 第四十三轮发现「词汇接缝测不出逻辑过渡」后补）：
#: 好的过渡往往**刻意用不同词汇**，靠逻辑连接而非重复上节的词。
#: 故词汇接缝低可能是好现象——需要一个独立的逻辑度量来区分
#: 「逻辑连贯但用词不同」与「真的跳跃」。
CONNECTORS = (
    "因为", "所以", "因此", "因而", "于是", "故", "这就",
    "但是", "然而", "不过", "可是", "但",
    "而且", "并且", "此外", "同时", "更重要的是",
    "总之", "综上", "可见", "这说明", "也就是说", "换言之",
    "例如", "比如", "譬如", "具体说",
    "换言之", "换句话说", "归根结底", "说到底",
    "第一", "第二", "第三", "首先", "其次", "最后",
)
#: 参考线：句首连接词占比。低于 LOW 视为「缺显式逻辑标记」。
LOGIC_LOW = 0.15
LOGIC_OK = 0.30


def logic_flow(segments):
    """连接词密度——**注意：这测的是文风，不是连贯**（2026-10-24 实测证伪）。

    初衷：第四十三轮发现「词汇接缝测不出逻辑过渡」，想加一个逻辑度量来区分
    「逻辑连贯但用词不同」与「真的跳跃」。

    **实测失败**：同一文本打乱句序后，连接词句数**不变**（纲要 5 → 5）。
    因为本指标是与**顺序无关**的统计量——它数的是「文本里有多少句以连接词开头」，
    而不是「连接词是否真的连接了上下文」。

    所以：
        * 它能告诉你「这份文本用不用显式连接词」（文风）；
        * **不能**告诉你「逻辑是否连贯」——后者依赖语义，与词形无关，
          和第十八轮「词频与嵌入看不见结构」同型。

    **不要把它的 ok/verdict 当作连贯性判据。** 保留它只因为文风本身有参考价值。

    返回 dict：
        ok        True=不低于 LOGIC_OK；False=低于 LOGIC_LOW；None=之间
        rate      句首连接词占比
        verdict   'marked' / 'sparse' / 'bare' / 'unknown'
    """
    all_sents = []
    for seg in (segments or []):
        all_sents.extend(split_sentences(seg))
    if not all_sents:
        return {"ok": None, "rate": None, "verdict": "unknown",
                "reason": "没有可分析的句子"}
    marked = 0
    for s in all_sents:
        # 先剥掉 Markdown 标记（**、#、>、-、*）与序号——
        # 否则「**但这里…**」的 startswith("但") 永远失败
        # （2026-10-24 实测：不剥标记时纲要报 0%，与打乱文本无法区分）。
        head = s.lstrip("\u3000 \t*#>-·•0123456789.、)）]】")
        if any(head.startswith(c) for c in CONNECTORS):
            marked += 1
    rate = marked / float(len(all_sents))
    if rate >= LOGIC_OK:
        ok, verdict = True, "marked"
    elif rate < LOGIC_LOW:
        ok, verdict = False, "bare"
    else:
        ok, verdict = None, "sparse"
    return {"ok": ok, "rate": round(rate, 4), "verdict": verdict,
            "sentences": len(all_sents), "marked": marked,
            "note": "句首连接词 %d/%d = %.1f%%" % (marked, len(all_sents), rate * 100)}


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
