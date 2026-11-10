# -*- coding: utf-8 -*-
"""相对日期绝对化——把文本里的「上周五」补成「上周五（2026-11-06）」。

判据（使用者 2026-11-12 定）：**所有相对日期后，用确定性规则补绝对日期。**

为什么必须由算法做、且必须内联在正文里：
  · 外测实证（Ornn8 B 类）：模型面对「周一/昨天」这类相对表述会照抄，不换算；
    状态视图那节明明给了绝对日期，判官仍写「只按周一/昨天相对表述，未给出具体日期」
    ——**平行章节会被忽略，只有正文里的内联标注才会被读到**。
  · 整条路线的立足点就是「时序归纳不该由模型做」，相对日期换算同理。

确定性规则（全部以**陈述时刻**为锚，即节点 created_at；不用"今天"）：
  今天/今日 0 · 昨天/昨日 −1 · 前天 −2 · 大前天 −3 · 明天 +1 · 后天 +2
  N 天前／N 天后（中文数字或阿拉伯数字）
  上周X／这周X／本周X／下周X（X = 一二三四五六日天，周一为周首）
  上个月／下个月（按整月区间标注）

不适用与边界（不猜）：
  · 锚点缺失或不可解析 ⇒ 原样返回，不标注；
  · 文本里已有紧随其后的（YYYY-MM-DD）⇒ 跳过（幂等，重复调用不叠加）；
  · 无年份的裸「周五」不标注（可属任一周，标了就是编造）；
  · 「上周」「今年」这类区间只在能确定起止时标注，否则不动。
"""
from __future__ import annotations

import datetime as _dt
import re

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
           "八": 8, "九": 9, "十": 10}
_CN_NUM.update({"十" + c: 10 + v for c, v in zip("一二三四五六七八九", range(1, 10))})
_CN_NUM.update({"二十": 20, "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24,
                "二十五": 25, "二十六": 26, "二十七": 27, "二十八": 28,
                "二十九": 29, "三十": 30, "三十一": 31})

_WD = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

_FIXED = (("大前天", -3), ("大后天", 3), ("前天", -2), ("后天", 2),
          ("昨天", -1), ("昨日", -1), ("今天", 0), ("今日", 0),
          ("明天", 1), ("明日", 1))

_NDAY = re.compile(r"(\d{1,2}|[一二两三四五六七八九十]{1,3})\s*天\s*([前后])")
_WEEKX = re.compile(r"(上|这|本|下)\s*(?:个)?\s*周\s*([一二三四五六日天])")
_MONTH = re.compile(r"(上|下)\s*个?\s*月")
_ANNOTATED = re.compile(r"^\s*[（(]\d{4}-\d{2}-\d{2}[）)]")


def _num(s):
    """中文/阿拉伯数字 → int；不能解析返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    return _CN_NUM.get(s)


def anchor_date(ts):
    """陈述时刻 → date；不可解析返回 None（**不猜今天**）。"""
    if ts is None:
        return None
    try:
        return _dt.datetime.fromtimestamp(float(ts)).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _resolve(expr, base):
    """单个相对表达式 → (起始 date, 结束 date)；区间表达式起止不同，点日期相同。"""
    for word, delta in _FIXED:
        if expr == word:
            d = base + _dt.timedelta(days=delta)
            return (d, d)
    m = _NDAY.fullmatch(expr)
    if m:
        n = _num(m.group(1))
        if not n:
            return None
        d = base + _dt.timedelta(days=(-n if m.group(2) == "前" else n))
        return (d, d)
    m = _WEEKX.fullmatch(expr)
    if m:
        rel = {"上": -1, "这": 0, "本": 0, "下": 1}[m.group(1)]
        monday = base - _dt.timedelta(days=base.weekday())
        d = monday + _dt.timedelta(days=7 * rel + _WD[m.group(2)])
        return (d, d)
    m = _MONTH.fullmatch(expr)
    if m:
        y, mo = base.year, base.month + (-1 if m.group(1) == "上" else 1)
        y, mo = (y + (mo - 1) // 12, (mo - 1) % 12 + 1)
        first = _dt.date(y, mo, 1)
        nxt = _dt.date(y + (mo // 12), mo % 12 + 1, 1)
        return (first, nxt - _dt.timedelta(days=1))
    return None


def _fmt(span):
    a, b = span
    if a == b:
        return a.isoformat()
    return "%s~%s" % (a.isoformat(), b.isoformat())


def annotate(text, ts):
    """在相对日期后**内联**补（YYYY-MM-DD）——幂等；锚点不可解析则原样返回。"""
    body = str(text or "")
    base = anchor_date(ts)
    if not body or base is None:
        return body
    hit = []
    for word, _delta in _FIXED:
        for m in re.finditer(re.escape(word), body):
            hit.append((m.start(), m.end(), word))
    for rx in (_NDAY, _WEEKX, _MONTH):
        for m in rx.finditer(body):
            hit.append((m.start(), m.end(), m.group(0)))
    if not hit:
        return body
    hit.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    picked, last_end = [], -1
    for st, en, expr in hit:
        if st < last_end:
            continue
        picked.append((st, en, expr))
        last_end = en
    out, cursor = [], 0
    for st, en, expr in picked:
        out.append(body[cursor:en])
        span = _resolve(expr, base)
        if span is not None and not _ANNOTATED.match(body[en:en + 16]):
            out.append("（%s）" % _fmt(span))
        cursor = en
    out.append(body[cursor:])
    return "".join(out)