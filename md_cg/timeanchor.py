# -*- coding: utf-8 -*-
"""timeanchor · 相对时间锚定（`MDCG_TIME_ANCHOR=1` 开启；缺省关闭，关闭时零调用）。

# 功能名：把正文里的相对/显式时间表达，以观测时刻为参照归一成**事件区间**（派生、可审计）
# 生效条件：MDCG_TIME_ANCHOR=="1"；写入侧仅在节点**无显式 temporal**、非加密密级、规则能解析时落派生字段；查询侧仅在问句含规则表内的日期写法时启用
# 子功能：①规则表（英文/中文相对表达 + 带年份绝对日期）②derive：正文 → 派生字段 ③parse_query：问句 → 区间 ④node_interval：节点 → 事件区间（显式 temporal > 派生 > 观测当日）
# 执行：被 md_cg/mdcg.py::MdCG.add（写入侧）与 md_cg/mdcos.py::MdCGOS.search_rrf（查询侧）调用；本模块纯函数、只用标准库
# 验证方式：md_cg/test_time_anchor.py（守卫 + 定点变异）；md_cg/bench_timeanchor.py（LoCoMo 复现）
# 不适用条件：规则表外的写法（「国庆前后」「上上周」）不解析；时长推理（「多久」）不做；观测时刻不是说话时刻（批量导入统一写成导入时间）时参照日错位

## 为什么有这个文件

对话记忆里事件时间几乎总是相对写法——「昨天」「上周二」「last weekend」「two years
ago」。节点只记了**观测时刻**（`created_at`，即说这句话的时刻），没有**事件时刻**。于是
「2023年5月7日 Caroline 做了什么」这类按日期点名的问句，字面检索与时间算子都落空：
证据写的是 *yesterday*，观测时刻是 5 月 8 日。

## 口径（逐条钉死）

* **派生字段** `temporal_anchor`（`DERIVED_FIELD`）落 frontmatter，形如
  `{"start": "2023-05-07", "end": "2023-05-07", "rule": "en.yesterday",
  "span": [12, 21], "ref": "2023-05-08", "v": 1}`——
  闭区间（ISO 日期串）、命中规则 id、命中位置（字符偏移，**不抄原文**，避免把正文片段
  复制进明文 frontmatter）、参照日、口径版本。
* **不覆盖用户显式写的 `temporal`**：显式 `temporal` 存在即不派生；派生字段也**不并入**
  `trust.time_window_of` 的任何轴（不改既有时间算子语义——只被本特性的查询侧读取）。
* **解析不了就不写、不猜**：正文没有规则表内的时间表达 → 不落字段。查询侧对这类节点按
  「观测当日」处理（与「只按时间戳」同口径，且在排序上排在显式/派生区间之后）。
* **参照日时区**：`created_at` 是 UNIX 秒，按 `MDCG_TIME_ANCHOR_TZ`（相对 UTC 的小时数，
  缺省 0）换算成日历日；非法值回落 0。
* **多条命中**取文本中最靠前者（「day before yesterday」先于其中的 yesterday；同位置按表序）。
* 带年份的绝对日期（`_ABS`）优先于相对表达（`RULES`）。

## 约定（不是事实，见设计文档「可信边界」）

「上周 / last week」取参照日前 7 天的滚动窗口而非日历周；「this weekend」按说话星期推断
过去或将来；缺年份的「5月7日」取不晚于参照日的最近一次；「for N years」按「N 年前」取区间。
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from typing import Callable, List, Optional, Sequence, Tuple

#: 总开关（缺省关）。登记：hotcache._ENV_SWITCHES + config_registry_bulk.ENV_CATEGORY_ROWS。
FLAG = "MDCG_TIME_ANCHOR"
#: 参照日时区（相对 UTC 的小时数，缺省 0）。同上登记。
TZ_FLAG = "MDCG_TIME_ANCHOR_TZ"
#: 派生字段名（frontmatter 键）。
DERIVED_FIELD = "temporal_anchor"
#: 用户显式事件时刻字段（与 trust.OBSERVED_TIME_FIELD 同名；此处不 import trust 免循环）。
EXPLICIT_FIELD = "temporal"
#: 派生口径版本：规则语义变了就加一，存量节点可据此判陈旧。
DERIVE_VERSION = 1

Interval = Tuple[_dt.date, _dt.date]
_D = _dt.date
_TD = _dt.timedelta


# 生效条件：environ（缺省 os.environ）里 FLAG 去空白后恰为 "1" 时返回 True，其余（缺失/空串/"0"/"true"）一律 False。
def enabled(environ=None) -> bool:
    """总开关的唯一读取点（与 MDCG_RANK_CREDIBILITY 同款：只认字面 "1"）。"""
    return (environ or os.environ).get(FLAG, "").strip() == "1"


# 生效条件：environ（缺省 os.environ）里 TZ_FLAG 可被 float() 解析且落在 [-14, 14] 时返回该值，缺失/非法/越界一律回落 0.0（不抛）。
def tz_hours(environ=None) -> float:
    raw = (environ or os.environ).get(TZ_FLAG, "")
    try:
        h = float(raw) if str(raw).strip() else 0.0
    except (TypeError, ValueError):
        return 0.0
    return h if -14.0 <= h <= 14.0 else 0.0


# 生效条件：ts 可被 float() 解析为有限 UNIX 秒时，返回按 tz_hours() 偏移后的公历日；None/非法/溢出返回 None（不猜）。
def ts_to_date(ts, environ=None) -> Optional[_dt.date]:
    if ts is None or isinstance(ts, bool):
        return None
    try:
        sec = float(ts) + 3600.0 * tz_hours(environ)
        return (_dt.datetime(1970, 1, 1) + _TD(seconds=sec)).date()
    except (OverflowError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------- 日历工具
# 生效条件：1<=m<=12 时返回该月首末日闭区间；否则抛 ValueError（由 _first 吞掉判「不可解析」）。
def month_iv(y: int, m: int) -> Interval:
    s = _D(y, m, 1)
    e = (_D(y + 1, 1, 1) if m == 12 else _D(y, m + 1, 1)) - _TD(1)
    return (s, e)


# 生效条件：y 在 date 合法年份内时返回该年 1/1~12/31。
def year_iv(y: int) -> Interval:
    return (_D(y, 1, 1), _D(y, 12, 31))


# 生效条件：d 为日期、n 为整数月偏移时返回偏移后的 (年, 月)。
def shift_month(d: _dt.date, n: int) -> Tuple[int, int]:
    m = d.month - 1 + n
    return d.year + m // 12, m % 12 + 1


# 生效条件：返回 d 之前 7 天的滚动窗口 [d-7, d-1]（约定：不是日历周）。
def week_before(d: _dt.date) -> Interval:
    return (d - _TD(7), d - _TD(1))


# 生效条件：返回严格早于 d 所在周的最近一个周末（周六、周日）；d 为周六/周日时取上一周末。
def weekend_before(d: _dt.date) -> Interval:
    wd = d.weekday()
    sat = d - _TD(8) if wd == 6 else d - _TD(7) if wd == 5 else d - _TD(wd + 2)
    return (sat, sat + _TD(1))


# 生效条件：周一、周二说「这个周末」取刚过去的周末；周六日取当周；周三至周五取即将到来的（约定）。
def this_weekend(d: _dt.date) -> Interval:
    wd = d.weekday()
    if wd <= 1:
        return weekend_before(d)
    sat = d - _TD(wd - 5) if wd >= 5 else d + _TD(5 - wd)
    return (sat, sat + _TD(1))


# 生效条件：返回 d 的下一个日历周的周六、周日。
def next_weekend(d: _dt.date) -> Interval:
    sat = d - _TD(d.weekday()) + _TD(12)
    return (sat, sat + _TD(1))


# 生效条件：返回严格早于 d 的最近一个星期 w（0=周一）；d 本身是星期 w 时取 7 天前（`or 7` 承重）。
def last_wd(d: _dt.date, w: int) -> Interval:
    x = d - _TD((d.weekday() - w) % 7 or 7)
    return (x, x)


# 生效条件：返回严格晚于 d 的最近一个星期 w；d 本身是星期 w 时取 7 天后。
def next_wd(d: _dt.date, w: int) -> Interval:
    x = d + _TD((w - d.weekday()) % 7 or 7)
    return (x, x)


# 生效条件：unit ∈ {day, week, month, year}；day→点、week→以 d-7n 为中心 ±3 天、month→该月、year→该年。
def ago(d: _dt.date, n: int, unit: str) -> Interval:
    if unit == "day":
        x = d - _TD(n)
        return (x, x)
    if unit == "week":
        x = d - _TD(7 * n)
        return (x - _TD(3), x + _TD(3))
    if unit == "month":
        return month_iv(*shift_month(d, -n))
    return year_iv(d.year - n)


_SEASON_ALIAS = {"autumn": "fall", "春": "spring", "夏": "summer", "秋": "fall", "冬": "winter"}


# 生效条件：s 为季节名（英文或「春夏秋冬」）；n=-1 取 d 之前最近一个已结束的该季节，n=0 取 d 所在年的该季节；北半球气象季节（约定）。
def season_iv(d: _dt.date, s: str, n: int) -> Interval:
    s = _SEASON_ALIAS.get(s, s)
    rng = {"spring": (3, 5), "summer": (6, 8), "fall": (9, 11)}
    if s == "winter":
        y = d.year if (n == 0 or d.month >= 3) else d.year - 1
        return (_D(y - 1, 12, 1), month_iv(y, 2)[1])
    a, b = rng[s]
    y = d.year
    if n < 0 and d.month <= b:
        y -= 1
    return (_D(y, a, 1), month_iv(y, b)[1])


# 生效条件：m 为 1..12；返回不晚于 d 的最近一次该月。
def month_recent(d: _dt.date, m: int) -> Interval:
    return month_iv(d.year if m <= d.month else d.year - 1, m)


# 生效条件：(m, day) 构成合法日期时返回不晚于 d 的最近一次该日；非法日期返回 None。
def day_recent(d: _dt.date, m: int, day: int) -> Optional[Interval]:
    for y in (d.year, d.year - 1):
        try:
            x = _D(y, m, day)
        except ValueError:
            return None
        if x <= d:
            return (x, x)
    return None


# 生效条件：1<=n<=31；n 不晚于 d.day 取本月第 n 日，否则取上月第 n 日；日期非法返回 None。
def nth_day(d: _dt.date, n: int) -> Optional[Interval]:
    if not 1 <= n <= 31:
        return None
    try:
        x = _D(d.year, d.month, n) if n <= d.day else _D(*shift_month(d, -1), n)
    except ValueError:
        return None
    return (x, x)


# 生效条件：(y, m, d) 构成合法日期时返回该点区间，否则 None。
def _point(y: int, m: int, d: int) -> Optional[Interval]:
    try:
        x = _D(y, m, d)
    except ValueError:
        return None
    return (x, x)


# ---------------------------------------------------------------- 数词
_EN_MON = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]
MON = {m: i + 1 for i, m in enumerate(_EN_MON)}
MON.update({m[:3]: i + 1 for i, m in enumerate(_EN_MON)})
MON["sept"] = 9
_MONP = (r"(january|february|march|april|may|june|july|august|september|october|november"
         r"|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)")
_EN_WD = {w: i for i, w in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday",
                                       "saturday", "sunday"])}
_EN_WD.update({"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3,
               "fri": 4, "sat": 5, "sun": 6})
_WDP = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|wed|thu(?:rs?)?|fri|sat|sun)"
_EN_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10, "couple of": 2, "few": 3, "several": 3}
_ENNP = r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple of|few|several)"
_UNIT_EN = r"(day|week|month|year)s?"

_CN_DIG = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
           "七": 7, "八": 8, "九": 9}
_CNNP = r"([0-9]{1,4}|[零〇一二两三四五六七八九十百]{1,5}|几)"
_CN_WD = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_CN_UNIT = {"天": "day", "日": "day", "周": "week", "星期": "week", "礼拜": "week",
            "个月": "month", "月": "month", "年": "year"}


# 生效条件：s 为阿拉伯数字串或「零〇一二两三四五六七八九十百」组合时返回其整数值；「几」按 3（约定）；含其它字符或值为 0 返回 None。
def cn_num(s: str) -> Optional[int]:
    if s.isdigit():
        return int(s) or None
    if s == "几":
        return 3
    total, cur = 0, None
    for ch in s:
        if ch in _CN_DIG:
            cur = _CN_DIG[ch]
        elif ch in "十百":
            total += (1 if cur is None else cur) * (10 if ch == "十" else 100)
            cur = None
        else:
            return None
    total += cur or 0
    return total or None


# 生效条件：s 为 _EN_NUM 的键或数字串时返回整数，否则抛 ValueError（由 _first 吞掉）。
def _en_n(s: str) -> int:
    return _EN_NUM.get(s.lower()) or int(s)


def _r(p, flags=re.I):
    return re.compile(p, flags)


# 生效条件：n 为假值（None/0）时返回 None；否则调 f(n)。
def _if_n(n, f):
    return f(n) if n else None


# ---------------------------------------------------------------- 规则表
#: 每条：(规则 id, 编译正则, 构造函数(m, ref_date) → 区间或 None)。
#: id 落进派生字段的 `rule`，审计时可直接指认是哪一条规则给的区间。
Rule = Tuple[str, "re.Pattern", Callable]

RULES: List[Rule] = [
    # ---- 英文（23 条）
    ("en.day_before_yesterday", _r(r"\bday before yesterday\b"), lambda m, d: (d - _TD(2),) * 2),
    ("en.yesterday", _r(r"\byesterday\b|\blast night\b"), lambda m, d: (d - _TD(1),) * 2),
    ("en.tomorrow", _r(r"\btomorrow\b"), lambda m, d: (d + _TD(1),) * 2),
    ("en.last_weekend", _r(r"\b(?:last|past|this past) weekend\b"), lambda m, d: weekend_before(d)),
    ("en.this_weekend", _r(r"\bthis weekend\b"), lambda m, d: this_weekend(d)),
    ("en.last_week", _r(r"\b(?:last|past) week\b|\ba week ago\b"), lambda m, d: week_before(d)),
    ("en.next_week", _r(r"\bnext week\b"), lambda m, d: (d + _TD(1), d + _TD(7))),
    ("en.next_month", _r(r"\bnext month\b"), lambda m, d: month_iv(*shift_month(d, 1))),
    ("en.last_month", _r(r"\blast month\b|\ba month ago\b"), lambda m, d: month_iv(*shift_month(d, -1))),
    ("en.this_month", _r(r"\bthis month\b"), lambda m, d: month_iv(d.year, d.month)),
    ("en.month_last_year", _r(_MONP + r" last year\b"),
     lambda m, d: month_iv(d.year - 1, MON[m.group(1).lower()])),
    ("en.last_year", _r(r"\blast year\b|\ba year ago\b"), lambda m, d: year_iv(d.year - 1)),
    ("en.this_year", _r(r"\bthis year\b"), lambda m, d: year_iv(d.year)),
    ("en.next_year", _r(r"\bnext year\b"), lambda m, d: year_iv(d.year + 1)),
    ("en.last_season", _r(r"\blast (summer|winter|spring|fall|autumn)\b"),
     lambda m, d: season_iv(d, m.group(1).lower(), -1)),
    ("en.n_units_ago", _r(r"\b" + _ENNP + r" " + _UNIT_EN + r" ago\b"),
     lambda m, d: ago(d, _en_n(m.group(1)), m.group(2).lower())),
    ("en.for_n_units", _r(r"\bfor (?:about |almost |over |nearly )?" + _ENNP + r" " + _UNIT_EN + r"\b"),
     lambda m, d: ago(d, _en_n(m.group(1)), m.group(2).lower())),
    ("en.next_weekday", _r(r"\bnext " + _WDP + r"\b"), lambda m, d: next_wd(d, _EN_WD[m.group(1).lower()])),
    ("en.last_weekday", _r(r"\b(?:last|on|this|this past) " + _WDP + r"\b"),
     lambda m, d: last_wd(d, _EN_WD[m.group(1).lower()])),
    # 刻意不含 may：「in may」与情态动词 may 同形，误判代价高于漏判
    ("en.in_month", _r(r"\b(?:in|this|last) (january|february|march|april|june|july|august"
                       r"|september|october|november|december)\b"),
     lambda m, d: month_recent(d, MON[m.group(1).lower()])),
    ("en.on_nth", _r(r"\bon the (\d{1,2})(?:st|nd|rd|th)\b"), lambda m, d: nth_day(d, int(m.group(1)))),
    ("en.in_year", _r(r"\bin (19\d\d|20\d\d)\b"), lambda m, d: year_iv(int(m.group(1)))),
    ("en.today", _r(r"\btoday\b|\btonight\b|\bthis (?:morning|afternoon|evening)\b"), lambda m, d: (d, d)),
    # ---- 中文（27 条）
    ("zh.大前天", _r(r"大前天"), lambda m, d: (d - _TD(3),) * 2),
    ("zh.前天", _r(r"前天"), lambda m, d: (d - _TD(2),) * 2),
    ("zh.昨天", _r(r"昨天|昨晚|昨日|昨儿"), lambda m, d: (d - _TD(1),) * 2),
    ("zh.大后天", _r(r"大后天"), lambda m, d: (d + _TD(3),) * 2),
    ("zh.后天", _r(r"后天"), lambda m, d: (d + _TD(2),) * 2),
    ("zh.明天", _r(r"明天|明晚|明早|明日"), lambda m, d: (d + _TD(1),) * 2),
    ("zh.今天", _r(r"今天|今晚|今早|今日|今儿"), lambda m, d: (d, d)),
    ("zh.上周X", _r(r"(?:上|上个)(?:周|星期|礼拜)([一二三四五六日天末])"),
     lambda m, d: weekend_before(d) if m.group(1) == "末" else last_wd(d, _CN_WD[m.group(1)])),
    ("zh.下周X", _r(r"(?:下|下个)(?:周|星期|礼拜)([一二三四五六日天末])"),
     lambda m, d: next_weekend(d) if m.group(1) == "末"
     else next_wd(d + _TD(6 - d.weekday()), _CN_WD[m.group(1)])),
    ("zh.这周X", _r(r"(?:这|这个|本)(?:周|星期|礼拜)([一二三四五六日天末])"),
     lambda m, d: this_weekend(d) if m.group(1) == "末"
     else (lambda x: (x, x))(d - _TD(d.weekday()) + _TD(_CN_WD[m.group(1)]))),
    ("zh.周X", _r(r"(?<![上下这本个])(?:周|星期|礼拜)([一二三四五六日天])"),
     lambda m, d: last_wd(d, _CN_WD[m.group(1)])),
    ("zh.周末", _r(r"周末"), lambda m, d: this_weekend(d)),
    ("zh.上周", _r(r"(?:上|上个)(?:周|星期|礼拜)"), lambda m, d: week_before(d)),
    ("zh.下周", _r(r"(?:下|下个)(?:周|星期|礼拜)"), lambda m, d: (d + _TD(1), d + _TD(7))),
    ("zh.上月", _r(r"上(?:个)?月"), lambda m, d: month_iv(*shift_month(d, -1))),
    ("zh.下月", _r(r"下(?:个)?月"), lambda m, d: month_iv(*shift_month(d, 1))),
    ("zh.本月", _r(r"(?:这|这个|本)月"), lambda m, d: month_iv(d.year, d.month)),
    ("zh.去年季节", _r(r"去年(?:的)?([春夏秋冬])(?:天|季)"),
     lambda m, d: season_iv(_D(d.year - 1, 12, 31), m.group(1), 0)),
    ("zh.去年X月", _r(r"去年([0-9]{1,2}|[一二三四五六七八九十]{1,3})月"),
     lambda m, d: _if_n(cn_num(m.group(1)), lambda n: month_iv(d.year - 1, n) if n <= 12 else None)),
    ("zh.前年", _r(r"前年"), lambda m, d: year_iv(d.year - 2)),
    ("zh.去年", _r(r"去年"), lambda m, d: year_iv(d.year - 1)),
    ("zh.今年", _r(r"今年"), lambda m, d: year_iv(d.year)),
    ("zh.明年", _r(r"明年"), lambda m, d: year_iv(d.year + 1)),
    ("zh.前几天", _r(r"前几天|几天前|前些天|这几天"), lambda m, d: (d - _TD(7), d - _TD(1))),
    ("zh.N单位前", _r(_CNNP + r"\s*(天|日|周|星期|礼拜|个月|年)(?:以)?前"),
     lambda m, d: _if_n(cn_num(m.group(1)), lambda n: ago(d, n, _CN_UNIT[m.group(2)]))),
    ("zh.X月X日", _r(r"(?<![0-9年])([0-9]{1,2}|[一二三四五六七八九十]{1,3})月"
                     r"([0-9]{1,2}|[一二三四五六七八九十]{1,3})(?:日|号)"),
     lambda m, d: (lambda a, b: day_recent(d, a, b) if a and b and a <= 12 else None)(
         cn_num(m.group(1)), cn_num(m.group(2)))),
    ("zh.X号", _r(r"(?<![上下这本个0-9年月])([0-9]{1,2})号"), lambda m, d: nth_day(d, int(m.group(1)))),
]

#: 带年份的绝对日期（8 条）：写入与查询共用，优先级高于 RULES。构造函数只吃 m。
ABS_RULES: List[Rule] = [
    ("abs.ymd_dash", _r(r"(?<!\d)((?:19|20)\d\d)-(\d{1,2})-(\d{1,2})(?!\d)"),
     lambda m: _point(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    ("abs.ymd_zh", _r(r"((?:19|20)\d\d)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]"),
     lambda m: _point(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    ("abs.dmy_en", _r(r"\b(\d{1,2})(?:st|nd|rd|th)? " + _MONP + r",? ((?:19|20)\d\d)\b"),
     lambda m: _point(int(m.group(3)), MON[m.group(2).lower()], int(m.group(1)))),
    ("abs.mdy_en", _r(r"\b" + _MONP + r" (\d{1,2})(?:st|nd|rd|th)?,? ((?:19|20)\d\d)\b"),
     lambda m: _point(int(m.group(3)), MON[m.group(1).lower()], int(m.group(2)))),
    ("abs.ym_dash", _r(r"(?<!\d)((?:19|20)\d\d)-(\d{1,2})(?![\d-])"),
     lambda m: month_iv(int(m.group(1)), int(m.group(2))) if 1 <= int(m.group(2)) <= 12 else None),
    ("abs.ym_zh", _r(r"((?:19|20)\d\d)\s*年\s*(\d{1,2})\s*月"),
     lambda m: month_iv(int(m.group(1)), int(m.group(2))) if 1 <= int(m.group(2)) <= 12 else None),
    ("abs.my_en", _r(r"\b" + _MONP + r",? ((?:19|20)\d\d)\b"),
     lambda m: month_iv(int(m.group(2)), MON[m.group(1).lower()])),
    ("abs.y_zh", _r(r"((?:19|20)\d\d)\s*年"), lambda m: year_iv(int(m.group(1)))),
]

#: **污染声明**（见设计文档）：lingshu 版开发时看过一次含 test 的失败样例后加的 6 族规则。
#: 只供基准报「去掉这 6 族」的下界用（`bench_timeanchor.py --minus-posthoc`），运行时不读。
POST_HOC_RULE_IDS = frozenset({"en.on_nth", "en.in_year", "en.for_n_units",
                               "en.month_last_year", "en.this_month", "en.this_year"})


# 生效条件：rules 为 (id, pattern, fn) 序列；对每条取 text 中首个命中并调 fn(m, *args)，fn 抛 ValueError/KeyError/TypeError/OverflowError 或返回假值视为不可解析；返回命中位置最靠前（同位置取表序在前）者的 (区间, 规则 id, (start, end))，全无命中返回 None。
def _first(rules: Sequence[Rule], text: str, *args):
    best = None
    for rid, pat, f in rules:
        m = pat.search(text)
        if m is None:
            continue
        try:
            iv = f(m, *args)
        except (ValueError, KeyError, TypeError, OverflowError):
            iv = None
        if iv and (best is None or m.start() < best[2][0]):
            best = (iv, rid, (m.start(), m.end()))
    return best


# 生效条件：text 非空且 ref 为日期时，先认带年份的绝对日期（ABS_RULES），再认相对表达（RULES，以 ref 为参照）；都没有返回 None。返回 (区间, 规则 id, 命中位置)。
def resolve_detail(text: str, ref: Optional[_dt.date], rules: Sequence[Rule] = None,
                   abs_rules: Sequence[Rule] = None):
    if not text or ref is None:
        return None
    return (_first(ABS_RULES if abs_rules is None else abs_rules, text)
            or _first(RULES if rules is None else rules, text, ref))


# 生效条件：同 resolve_detail，只返回区间 (d0, d1) 或 None。
def resolve(text: str, ref: Optional[_dt.date]) -> Optional[Interval]:
    r = resolve_detail(text, ref)
    return r[0] if r else None


# 生效条件：q 非空时先认绝对日期，再以 ref（缺省 = 当前时刻按 tz_hours() 折算的日期）为参照认相对表达；都没有返回 None。返回 (区间, 规则 id)。
def parse_query_detail(q: str, ref: Optional[_dt.date] = None):
    if not q:
        return None
    hit = _first(ABS_RULES, q)
    if hit is None:
        if ref is None:
            import time as _time
            ref = ts_to_date(_time.time())
        hit = _first(RULES, q, ref)
    return (hit[0], hit[1]) if hit else None


# 生效条件：同 parse_query_detail，只返回区间或 None。
def parse_query(q: str, ref: Optional[_dt.date] = None) -> Optional[Interval]:
    r = parse_query_detail(q, ref)
    return r[0] if r else None


# 生效条件：content 为正文、observed_ts 为观测时刻（UNIX 秒）时；参照日不可得或规则全不命中返回 None（不写、不猜）；否则返回派生字段 dict（start/end ISO 日期串、rule、span、ref、v），**不含正文片段**。
def derive(content: str, observed_ts, rules: Sequence[Rule] = None) -> Optional[dict]:
    ref = ts_to_date(observed_ts)
    if ref is None or not isinstance(content, str) or not content:
        return None
    hit = resolve_detail(content, ref, rules=rules)
    if hit is None:
        return None
    (d0, d1), rid, (s, e) = hit
    if d1 < d0:
        return None
    return {"start": d0.isoformat(), "end": d1.isoformat(), "rule": rid,
            "span": [s, e], "ref": ref.isoformat(), "v": DERIVE_VERSION}


# 生效条件：fm 为写入前的 frontmatter（已含 created_at/sensitivity/temporal 等）；开关关、fm 已有显式 temporal（非 None）、fm 已有 DERIVED_FIELD、或密级属 encrypted_levels（缺省 = crypto.ENCRYPTED_LEVELS）时**不动 fm** 返回 None；否则 derive 成功即写 fm[DERIVED_FIELD] 并返回该 dict，失败返回 None。
def apply_on_write(fm: dict, content: str, encrypted_levels=None) -> Optional[dict]:
    """写入侧钩子（`MdCG.add` 调用）：显式 temporal 永远优先，派生只补缺。"""
    if not enabled() or not isinstance(fm, dict):
        return None
    if fm.get(EXPLICIT_FIELD) is not None or fm.get(DERIVED_FIELD) is not None:
        return None
    # 加密密级：正文在盘上是密文，派生区间却是明文 frontmatter —— 等于把正文里的日期
    # 信息漏到明文面。宁可不派生（查询侧对它按观测当日处理）。
    if encrypted_levels is None:
        from .crypto import ENCRYPTED_LEVELS as encrypted_levels   # 懒导入：密级真源
    if fm.get("sensitivity") in set(encrypted_levels):
        return None
    d = derive(content, fm.get("created_at"))
    if d is not None:
        fm[DERIVED_FIELD] = d
    return d


# 生效条件：s 为 ISO 日期串（YYYY-MM-DD）时返回 date，否则 None。
def _iso(s) -> Optional[_dt.date]:
    try:
        return _D.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


#: node_interval 的来源等级（越小越具体；查询侧排序第一键）。
SRC_EXPLICIT, SRC_DERIVED, SRC_OBSERVED = 0, 1, 2


# 生效条件：fm 为节点 frontmatter（或含同名键的索引条目）；parse_ts 为把显式 temporal 解析成 UNIX 秒的函数（传 trust.parse_time，免循环 import）。显式 temporal 可解析 → (当日, 当日, SRC_EXPLICIT)；否则派生字段两端可解析且 start<=end → (start, end, SRC_DERIVED)；否则 created_at 可折算 → (当日, 当日, SRC_OBSERVED)；都不行返回 None。
def node_interval(fm, parse_ts=None):
    if not isinstance(fm, dict):
        return None
    t = fm.get(EXPLICIT_FIELD)
    if t is not None and parse_ts is not None:
        try:
            ts = parse_ts(t)
        except Exception:                                  # noqa: BLE001
            ts = None
        d = ts_to_date(ts)
        if d is not None:
            return (d, d, SRC_EXPLICIT)
    a = fm.get(DERIVED_FIELD)
    if isinstance(a, dict):
        d0, d1 = _iso(a.get("start")), _iso(a.get("end"))
        if d0 is not None and d1 is not None and d0 <= d1:
            return (d0, d1, SRC_DERIVED)
    try:
        ca = float(fm.get("created_at") or 0.0)
    except (TypeError, ValueError):
        ca = 0.0
    d = ts_to_date(ca) if ca > 0 else None
    if d is not None:
        return (d, d, SRC_OBSERVED)
    return None


# 生效条件：两个闭区间有公共日时返回 True。
def overlaps(a0: _dt.date, a1: _dt.date, b0: _dt.date, b1: _dt.date) -> bool:
    return a0 <= b1 and b0 <= a1


# 生效条件：src 为 node_interval 的来源等级、width_days 为区间宽度（天，>=0）时返回 (0,1] 的确定性分数：来源越具体、区间越窄分越高（显式/派生 = 1/(1+w)，观测当日推定再 ×0.5）。
def anchor_score(src: int, width_days: int) -> float:
    base = 1.0 / (1.0 + max(0, int(width_days)))
    return round(base * (0.5 if src == SRC_OBSERVED else 1.0), 6)
