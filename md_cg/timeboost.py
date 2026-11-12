# -*- coding: utf-8 -*-
"""时间桶重排（timeboost）——主库的「章节 = 写入日期」版结构信号。

为什么不是章节路由（实测，2026-11-09）：主库 34,218 节点里**没有章节结构**，
tag 是 `code` / `domain:*` / 项目名这类，而 `created_at` 100% 覆盖、按天聚集
（2026-11-08 一天 77 条、2026-09-29 一天 67 条）。
使用者口径：**每日写信息的时间就是章节**。故结构信号应按天路由，而不是按标题。

设计（与 structboost 同一纪律）：
  · 从查询里解析**显式日期**（2026-11-08 / 11月8日 / 11-08）与**相对词**（今天/昨天/前天）；
  · 命中的日期集合为空 ⇒ 本条信号**整条不生效**（绝不猜日期）；
  · 命中 ⇒ 该日期内的候选 × TIME_BOOST（乘性提升，不硬过滤——日期可能记错）；
  · 时钟必须由调用方传入（`now`），不内部取 time.time()，保证可回放。
"""
from __future__ import annotations

import re
import time

#: 命中日期的提升倍数（与 structboost 的章节提升同量级）。
TIME_BOOST = 2.0

#: 相对词 → 往前几天。**长词必须排在短词之前**（「大前天」含「前天」，顺序错就会少算一天）。
_REL = {"大前天": 3, "今天": 0, "今日": 0, "昨天": 1, "昨日": 1, "前天": 2}


def _date_of(ts):
    "把一个 epoch 秒转成本地日期字符串 YYYY-MM-DD。"
    try:
        return time.strftime("%Y-%m-%d", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return None


_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_or_int(s):
    """「三」/「十三」/「二十三」/「12」→ 整数；解析不出返回 None（不猜）。"""
    s = str(s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    if "十" in s:
        head, _, tail = s.partition("十")
        h = _CN_NUM.get(head, 1) if head else 1
        t = _CN_NUM.get(tail, 0) if tail else 0
        return h * 10 + t
    return None


#: 中文数字星期 → 0..6（周一=0）
_WD = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
       "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}


def _day_start(ts):
    """把 epoch 秒对齐到本地当天 00:00（用于「按天」运算）。"""
    lt = time.localtime(float(ts))
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _add_days(ts, n):
    return _day_start(ts) + n * 86400


def _weekday_dates(q, now):
    """「上周三 / 这周三 / 本周三 / 上周天」→ 单个日期；无修饰的「周三」不解析（歧义太大）。"""
    out = set()
    for m in re.finditer(r"(上周|上星期|这周|这星期|本周|本星期)([一二三四五六日天1-7])", q):
        wd = _WD.get(m.group(2))
        if wd is None:
            continue
        back_weeks = 1 if m.group(1).startswith(("上周", "上星期")) else 0
        today = _day_start(now)
        lt = time.localtime(today)
        cur_wd = lt.tm_wday          # 周一=0
        target = today + (wd - cur_wd) * 86400 - back_weeks * 7 * 86400
        out.add(_date_of(target))
    return out


def _week_range(q, now):
    """「上周 / 这周 / 本周」→ 整周 7 天（周一..周日）。"""
    out = set()
    if not any(w in q for w in ("上周", "上星期", "这周", "这星期", "本周", "本星期")):
        return out
    # 与「上周三」这类**单日**写法互斥：出现星期字符时只取单日（避免把整周都塞进去）
    if re.search(r"(上周|上星期|这周|这星期|本周|本星期)[一二三四五六日天1-7]", q):
        return out
    back = 1 if any(w in q for w in ("上周", "上星期")) else 0
    today = _day_start(now)
    monday = today - time.localtime(today).tm_wday * 86400 - back * 7 * 86400
    for i in range(7):
        out.add(_date_of(monday + i * 86400))
    return out


def _month_range(q, now):
    """「上个月 / 上月 / 本月 / 这个月」→ 整月日期（最多 31 天）。"""
    out = set()
    back = None
    if any(w in q for w in ("上个月", "上月")):
        back = 1
    elif any(w in q for w in ("这个月", "本月")):
        back = 0
    if back is None:
        return out
    lt = time.localtime(float(now))
    y, m = lt.tm_year, lt.tm_mon - back
    if m <= 0:
        y, m = y - 1, m + 12
    for d in range(1, 32):
        try:
            t = time.mktime((y, m, d, 0, 0, 0, 0, 0, -1))
        except (ValueError, OverflowError):
            break
        if time.localtime(t).tm_mon != m:
            break
        out.add(_date_of(t))
    return out


def query_dates(query, now):
    """从查询里解析目标日期集合（确定性）；解析不出返回空集合。"""
    q = str(query or "")
    out = set()
    # 1) 完整日期：2026-11-08 / 2026/11/08
    for m in re.finditer(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", q):
        out.add("%04d-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3))))
    # 2) 月日：「11月8日」——年份取 now 的年份（跨年场景留给调用方补全年份）
    for m in re.finditer(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", q):
        y = time.localtime(float(now)).tm_year
        out.add("%04d-%02d-%02d" % (y, int(m.group(1)), int(m.group(2))))
    # 3) 相对词：今天/昨天/前天/大前天
    # 长词优先 + **已命中的长词吸收其子串**（否则「大前天」会同时命中「前天」，多算一天）
    _matched = []
    for word, back in sorted(_REL.items(), key=lambda kv: -len(kv[0])):
        if any(word in m for m in _matched):
            continue
        if word in q:
            _matched.append(word)
            out.add(_date_of(float(now) - back * 86400))
    # 4) 「N 天前 / N 天以前」——N 支持阿拉伯数字与中文数字（「三天前」在真实语料里更常见）
    for m in re.finditer(r"(\d{1,3}|[一二两三四五六七八九十]{1,3})\s*天\s*(?:以)?前", q):
        n = _cn_or_int(m.group(1))
        if n is not None:
            out.add(_date_of(float(now) - n * 86400))
    # 5) 「N 天前 / N 天后」的兄弟写法：「前 N 天」「N 天后」不解析（指向未来或无锚）
    # 6) 星期：上周三 / 这周三 / 本周三 / 周三
    out.update(_weekday_dates(q, float(now)))
    # 7) 周区间：上周 / 这周 / 本周（整周 7 天）
    out.update(_week_range(q, float(now)))
    # 8) 月区间：上个月 / 上月 / 本月 / 这个月（整月，最多 31 天）
    out.update(_month_range(q, float(now)))
    return {d for d in out if d}


def node_date(node):
    """候选节点的写入日期（created_at → 本地日期）。"""
    fm = node.get("frontmatter") or {}
    ts = fm.get("created_at") or fm.get("valid_from")
    return _date_of(ts) if ts else None


def rerank(results, query, now, k=None):
    """按「查询提到的日期」做稳定重排（同分保持原序，确定性）。

    `now` 必须由调用方给（时钟显式）。日期集合为空 ⇒ 原样返回（零变更）。
    """
    dates = query_dates(query, now)
    items = list(results or ())
    if not dates or not items:
        return items[:k] if k else items
    scored = []
    for idx, item in enumerate(items):
        node = item[0]
        try:
            score = float(item[1])
        except (TypeError, ValueError, IndexError):
            score = 0.0
        d = node_date(node)
        factor = TIME_BOOST if (d and d in dates) else 1.0
        scored.append((score * factor, idx, item))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out = [t[2] for t in scored]
    return out[:k] if k else out


def scoped_recall(store, query, now, cap=8):
    """按查询提到的日期做**二次召回**（时间算子），返回额外候选（可追加到包里）。

    为什么不是「重排」：主库实测（34,218 节点）——查询带日期时 top-5 里同日期占比
    重排前 5.0%、重排后 8.3%，因为候选集里**根本没有那天的节点**；
    只有把那天窗口内的节点捞出来，日期才真正起作用。

    成本控制：只在查询**解析出日期**时才多跑一次检索（普通查询零开销）。
    返回 [(node, score, qual, prov)]，与 search_rrf 同构，score 为 0.0（只补召回、不抢名次）。
    """
    dates = query_dates(query, now)
    if not dates:
        return []
    day = sorted(dates)[0]
    try:
        start = time.mktime(time.strptime(day + " 00:00:00", "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return []
    end = start + 86400
    try:
        res, _meta = store.search_rrf(query, k=cap, start_time=start,
                                      end_time=end, start_operator="gte",
                                      end_operator="lt")
    except Exception:          # noqa: BLE001 —— 二次召回失败不拖崩主检索
        return []
    out = []
    for item in res or ():
        node = item[0]
        out.append((node, 0.0, {"reason": "time_scope"}, []))
    return out