# -*- coding: utf-8 -*-
"""test_time_anchor · 相对时间锚定守卫（MDCG_TIME_ANCHOR=1；缺省关闭）

# 功能名：写入侧派生事件区间 temporal_anchor + 查询侧点名日期的 time_anchor 路（md_cg/timeanchor.py 接线于 mdcg.MdCG.add 与 mdcos.MdCGOS.search_rrf）
# 生效条件：改动 md_cg/timeanchor.py、md_cg/mdcg.py::MdCG.add 的派生钩子、md_cg/mdcos.py::search_rrf / _path_time_anchor、md_cg/hotcache.py 的 _ENV_SWITCHES/_KEYED_EXTRA 之后必跑
# 子功能：①规则表（英文/中文/绝对日期，固定参照日）②问句解析 ③缺省关：零调用、fm 无派生键、meta/paths 无 time_anchor ④点名日期把写「yesterday / 昨天」的证据拉到 top-1（关时不在 top-1）⑤无日期问句开/关逐位相同 ⑥显式 temporal 不被覆盖、解析不了不写、加密密级不派生 ⑦TZ ⑧登记（hotcache 键 + config registry）⑨定点变异（文本级，只改内存副本）
# 执行：python -X utf8 -m md_cg.test_time_anchor
# 验证方式：末行「通过 N / 失败 M」；变异段逐条打印「变异前 -> 变异后」读数，变异未转红即判失败
# 不适用条件：不测 LoCoMo 读数（见 md_cg/bench_timeanchor.py）；不碰在役库（全程 tempfile 沙箱）
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_TMP = tempfile.mkdtemp(prefix="mdcg_timeanchor_")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "root")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxstore")
os.environ.setdefault("MDCG_MASTER_KEY", "00" * 32)
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
os.environ.pop("MDCG_TIME_ANCHOR", None)
os.environ.pop("MDCG_TIME_ANCHOR_TZ", None)

from md_cg import hotcache                                           # noqa: E402
from md_cg import mdcg as _mdcg                                      # noqa: E402
from md_cg import mdcos as _mdcos                                    # noqa: E402
from md_cg import timeanchor as T                                    # noqa: E402
from md_cg.config_registry_bulk import ENV_CATEGORY_ROWS             # noqa: E402
from md_cg.mdcos import MdCGOS                                       # noqa: E402

PASS, FAILS = 0, []
D = dt.date
REF = D(2023, 7, 20)  # 周四


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


# 生效条件：(y,m,d,h) 合法时返回该 UTC 时刻的 UNIX 秒。
def _ts(y, m, d, h=12):
    return (dt.datetime(y, m, d, h) - dt.datetime(1970, 1, 1)).total_seconds()


RULE_CASES = [
    ("I joined a new group last Tues.", (D(2023, 7, 18),) * 2),
    ("Yesterday was crazy", (D(2023, 7, 19),) * 2),
    ("the day before yesterday", (D(2023, 7, 18),) * 2),
    ("We went biking last weekend", (D(2023, 7, 15), D(2023, 7, 16))),
    ("Started hitting the gym last week", (D(2023, 7, 13), D(2023, 7, 19))),
    ("I took this picture last month", (D(2023, 6, 1), D(2023, 6, 30))),
    ("my trip last year", (D(2022, 1, 1), D(2022, 12, 31))),
    ("camping last summer", (D(2022, 6, 1), D(2022, 8, 31))),
    ("I started two years ago", (D(2021, 1, 1), D(2021, 12, 31))),
    ("my album dropped on the 11th", (D(2023, 7, 11),) * 2),
    ("met in August last year", (D(2022, 8, 1), D(2022, 8, 31))),
    ("see you next Monday", (D(2023, 7, 24),) * 2),
    ("I may go hiking", None),                       # 情态动词 may 不是五月
    ("昨天去了公园", (D(2023, 7, 19),) * 2),
    ("上周二加入了一个团体", (D(2023, 7, 18),) * 2),
    ("上周末去骑车", (D(2023, 7, 15), D(2023, 7, 16))),
    ("三天前", (D(2023, 7, 17),) * 2),
    ("上个月拍的", (D(2023, 6, 1), D(2023, 6, 30))),
    ("去年夏天", (D(2022, 6, 1), D(2022, 8, 31))),
    ("5月7日那天", (D(2023, 5, 7),) * 2),
    ("下周三见", (D(2023, 7, 26),) * 2),
    ("2023年5月7日", (D(2023, 5, 7),) * 2),
    ("on 7 May 2023", (D(2023, 5, 7),) * 2),
    ("2023-05-07 的记录", (D(2023, 5, 7),) * 2),
    ("今天天气不错", (REF, REF)),
    ("没有任何时间词", None),
    ("I love painting", None),
]

QUERY_CASES = [
    ("Caroline 2023年5月7日", (D(2023, 5, 7),) * 2),
    ("What did Caroline do on May 7, 2023", (D(2023, 5, 7),) * 2),
    ("Caroline May 2023", (D(2023, 5, 1), D(2023, 5, 31))),
    ("2023-05", (D(2023, 5, 1), D(2023, 5, 31))),
    ("卡罗琳 上周二 做了什么", (D(2023, 7, 18),) * 2),
    ("Caroline 喜欢什么", None),
    ("When did Caroline go to the LGBTQ support group?", None),
]

EVENT = "Caroline: I went to a LGBTQ support group yesterday and it was so powerful."
EVENT_TS = _ts(2023, 5, 8)
NOISE = ["Caroline: Painting is how I express myself.",
         "Caroline: The pottery class was so much fun, 2023 has been a good year.",
         "Melanie: My kids love the beach.",
         "Caroline: I'm so thankful for my friends and mentors.",
         "Caroline: Let's catch up again soon!"]
#: 观测当日（5 月 7 日）说的、没有时间表达的话：只凭「观测当日」推定与问句有交集。
SAME_DAY = "Caroline: I'm so thankful for my friends, May is great."
ZH_EVENT = "卡罗琳：昨天去了一个支持小组，很有力量。"
ZH_NOISE = ["卡罗琳：画画是我表达自己的方式。", "卡罗琳：陶艺课很好玩，2023 是个好年份。",
            "梅兰妮：孩子们喜欢海滩。", "卡罗琳：感谢我的朋友和导师。"]


# 生效条件：cls 为 MdCGOS 或其变异副本、tag 为子目录名、on 为写入期开关；建一个隔离库写入 EVENT/NOISE/SAME_DAY 与中文同构语料，返回 (cg, ids)；调用方负责 close。
def build(cls, tag, on):
    _set(on)
    cg = cls(os.path.join(_TMP, tag, "root"))
    cg.add("ev", EVENT, layer="contextual", created_at=EVENT_TS)
    for i, t in enumerate(NOISE):
        cg.add("n%d" % i, t, layer="contextual", created_at=_ts(2023, 6, 1 + i))
    cg.add("sd", SAME_DAY, layer="contextual", created_at=_ts(2023, 5, 7, 9))
    cg.add("zev", ZH_EVENT, layer="contextual", created_at=EVENT_TS)
    for i, t in enumerate(ZH_NOISE):
        cg.add("zn%d" % i, t, layer="contextual", created_at=_ts(2023, 6, 10 + i))
    # 显式 temporal（事件时刻）+ 正文写 yesterday：派生绝不覆盖显式
    cg.add("ex", "Caroline: the support group meeting yesterday", layer="contextual",
           created_at=EVENT_TS, temporal="2023-01-01")
    cg.flush()
    return cg


def _set(on):
    if on:
        os.environ["MDCG_TIME_ANCHOR"] = "1"
    else:
        os.environ.pop("MDCG_TIME_ANCHOR", None)


def _fm(cg, nid):
    return cg._read(cg.index["nodes"][nid])[0] or {}


def _ids(res):
    return [r[0]["id"] for r in res]


#: 与「2023-05-07」有交集的节点（ev/zev 派生自 yesterday/昨天；sd 观测当日推定）。
_ANCHORED = {"ev", "zev", "sd"}


def _anchored_first(ids):
    """有交集者是否全部排在无交集者之前。"""
    flags = [i in _ANCHORED for i in ids]
    return flags == sorted(flags, reverse=True) and any(flags)


def _sig(res):
    """结果的可比签名（id / 融合分 / 资格 / 命中路），不含 frontmatter（开时多一个派生键）。"""
    return [(r[0]["id"], r[1], (r[2] or {}).get("state"), r[3]) for r in res]


# 生效条件：cls/mod 为 (MdCGOS, timeanchor) 或其变异副本；返回点名日期场景的读数 dict（关/开 top-1、meta）。
def date_case(cls, tag, ta_mod=None):
    saved = (_mdcg._timeanchor, _mdcos._timeanchor)
    if ta_mod is not None:
        _mdcg._timeanchor = ta_mod
        sys.modules[cls.__module__].__dict__["_timeanchor"] = ta_mod
    try:
        cg_off = build(cls, tag + "_off", on=False)
        _set(False)
        off_en = _ids(cg_off.search_rrf("Caroline 7 May 2023", k=5, record=False)[0])
        off_zh = _ids(cg_off.search_rrf("卡罗琳 2023年5月7日", k=5, record=False)[0])
        cg_off.close()
        cg_on = build(cls, tag + "_on", on=True)
        res_en, meta_en = cg_on.search_rrf("Caroline 7 May 2023", k=5, record=False)
        res_zh, _m = cg_on.search_rrf("卡罗琳 2023年5月7日", k=5, record=False)
        r = {"off_en": off_en, "off_zh": off_zh, "on_en": _ids(res_en), "on_zh": _ids(res_zh),
             "meta_en": meta_en.get("time_anchor"),
             "ev_fm": _fm(cg_on, "ev").get(T.DERIVED_FIELD),
             "ex_fm": (_fm(cg_on, "ex").get("temporal"), _fm(cg_on, "ex").get(T.DERIVED_FIELD))}
        cg_on.close()
        return r
    finally:
        _set(False)
        _mdcg._timeanchor, _mdcos._timeanchor = saved
        sys.modules[cls.__module__].__dict__["_timeanchor"] = saved[1]


# 生效条件：mod 为被变异模块、patches 为 [(锚点原文, 替换文本)]；锚点必须逐字命中（漂移即硬失败），返回 exec 后的独立模块（不改盘上文件）。
def mutant(mod, patches, name):
    src = open(mod.__file__, encoding="utf-8").read()
    for a, b in patches:
        assert a in src, "变异锚点未命中：%r" % a[:70]
        src = src.replace(a, b)
    m = types.ModuleType("md_cg._mut_" + name)
    m.__package__, m.__file__ = "md_cg", mod.__file__
    sys.modules[m.__name__] = m
    exec(compile(src, "<mutant:%s>" % name, "exec"), m.__dict__)   # noqa: S102
    return m


M1_ANCHOR = ("    x = d - _TD((d.weekday() - w) % 7 or 7)\n    return (x, x)\n\n\n"
             "# 生效条件：返回严格晚于 d")
M2_ANCHOR = "            fused_all.sort(key=lambda kv: _ta_tier.get(kv[0], 2))\n"
M3_ANCHOR = "    d = derive(content, fm.get(\"created_at\"))\n"
M4_ANCHOR = "    if fm.get(EXPLICIT_FIELD) is not None or fm.get(DERIVED_FIELD) is not None:\n"
M5_ANCHOR = "        _ta_q = _timeanchor.parse_query_detail(query) if _timeanchor.enabled() else None\n"


def main():
    print("=== 相对时间锚定守卫（MDCG_TIME_ANCHOR）===")

    print("\n[1] 规则表（参照日 2023-07-20 周四）")
    for text, want in RULE_CASES:
        got = T.resolve(text, REF)
        check("resolve(%r)" % text, got == want, got)
    got = T.resolve("last Tuesday", D(2023, 7, 18))
    check("周二说 last Tuesday = 上周二（不是当天）", got == (D(2023, 7, 11),) * 2, got)
    en = sum(1 for r in T.RULES if r[0].startswith("en."))
    zh = sum(1 for r in T.RULES if r[0].startswith("zh."))
    check("规则条数：英文 23 / 中文 27 / 绝对日期 8", (en, zh, len(T.ABS_RULES)) == (23, 27, 8),
          (en, zh, len(T.ABS_RULES)))
    ids = [r[0] for r in T.RULES + T.ABS_RULES]
    check("规则 id 唯一", len(ids) == len(set(ids)))
    check("污染声明的 6 族全部是真实规则 id", T.POST_HOC_RULE_IDS <= set(ids),
          sorted(T.POST_HOC_RULE_IDS - set(ids)))
    d = T.derive("Caroline: yesterday", _ts(2023, 5, 8))
    check("derive：区间/规则/位置/参照日/版本，且**不含正文片段**",
          d == {"start": "2023-05-07", "end": "2023-05-07", "rule": "en.yesterday",
                "span": [10, 19], "ref": "2023-05-08", "v": T.DERIVE_VERSION}, d)
    check("derive：无时间表达 → None（不写、不猜）", T.derive("I love painting", _ts(2023, 5, 8)) is None)

    print("\n[2] 问句解析（绝对日期优先；相对写法以 ref 为参照）")
    for q, want in QUERY_CASES:
        got = T.parse_query(q, ref=REF)
        check("parse_query(%r)" % q, got == want, got)

    print("\n[3] 缺省关：零调用、fm 无派生键、meta/paths 无 time_anchor")
    check("enabled() 缺省 False", T.enabled() is False)
    check("只认字面 \"1\"", T.enabled({"MDCG_TIME_ANCHOR": "true"}) is False
          and T.enabled({"MDCG_TIME_ANCHOR": " 1 "}) is True)
    calls = []
    _orig = (T.apply_on_write, T.parse_query_detail, MdCGOS._path_time_anchor)
    T.apply_on_write = lambda *a, **k: (calls.append("write"), _orig[0](*a, **k))[1]
    T.parse_query_detail = lambda *a, **k: (calls.append("parse"), _orig[1](*a, **k))[1]
    MdCGOS._path_time_anchor = lambda self, *a, **k: (calls.append("path"), _orig[2](self, *a, **k))[1]
    try:
        cg = build(MdCGOS, "off_calls", on=False)
        res, meta = cg.search_rrf("Caroline 7 May 2023", k=5, record=False)
        fm_keys_off = set(_fm(cg, "ev"))
        cg.close()
    finally:
        T.apply_on_write, T.parse_query_detail, MdCGOS._path_time_anchor = _orig
    check("关：写入钩子/问句解析/锚定路 调用次数 = 0", calls == [], calls)
    check("关：fm 无 temporal_anchor 键", T.DERIVED_FIELD not in fm_keys_off, sorted(fm_keys_off))
    check("关：meta 无 time_anchor 键、paths 无 time_anchor 路",
          "time_anchor" not in meta and "time_anchor" not in meta["paths"],
          (sorted(meta), meta["paths"]))
    check("关：path_fingerprint.paths.per_path 无 time_anchor（hash 不受影响）",
          "time_anchor" not in meta["path_fingerprint"]["paths"]["per_path"])

    print("\n[4] 点名日期 → 写「yesterday / 昨天」的证据 top-1")
    r = date_case(MdCGOS, "fixed")
    print("    读数：off_en=%s on_en=%s | off_zh=%s on_zh=%s" % (r["off_en"][:3], r["on_en"][:3],
                                                              r["off_zh"][:3], r["on_zh"][:3]))
    check("关：英文点名时证据不在 top-1（改前落空）", r["off_en"][:1] != ["ev"], r["off_en"])
    check("开：英文点名「Caroline 7 May 2023」证据 top-1", r["on_en"][:1] == ["ev"], r["on_en"])
    check("关：中文点名时证据不在 top-1", r["off_zh"][:1] != ["zev"], r["off_zh"])
    check("开：中文点名「卡罗琳 2023年5月7日」证据 top-1", r["on_zh"][:1] == ["zev"], r["on_zh"])
    check("开：区间有交集者（ev/zev/sd）全部排在无交集者之前（稳定前置）",
          _anchored_first(r["on_en"]), r["on_en"])
    check("开：观测当日推定（sd）排在派生证据之后", "sd" in r["on_en"]
          and r["on_en"].index("sd") > r["on_en"].index("ev"), r["on_en"])
    check("开：meta.time_anchor 记区间/规则/来源分布（不含正文）",
          (r["meta_en"] or {}).get("interval") == ["2023-05-07", "2023-05-07"]
          and r["meta_en"].get("rule") == "abs.dmy_en"
          and r["meta_en"].get("sources", {}).get("derived", 0) >= 1, r["meta_en"])

    print("\n[5] 无日期问句：开 / 关 逐位相同")
    _set(False)
    cg_a = build(MdCGOS, "nodate_off", on=False)
    sig_off = {q: _sig(cg_a.search_rrf(q, k=8, record=False)[0])
               for q in ("Caroline support group", "卡罗琳 支持小组", "Melanie beach kids")}
    meta_off = cg_a.search_rrf("Caroline support group", k=8, record=False)[1]
    cg_a.close()
    cg_b = build(MdCGOS, "nodate_on", on=True)
    sig_on = {q: _sig(cg_b.search_rrf(q, k=8, record=False)[0]) for q in sig_off}
    meta_on = cg_b.search_rrf("Caroline support group", k=8, record=False)[1]
    cg_b.close()
    _set(False)
    for q in sig_off:
        check("无日期问句 %r：开/关 (id, 分, 资格, 命中路) 逐位相同" % q, sig_on[q] == sig_off[q])
    _strip = lambda m: {k: v for k, v in m.items() if k != "cached"}   # noqa: E731
    check("无日期问句：开/关 meta 逐位相同（含 path_fingerprint.hash）",
          _strip(meta_on) == _strip(meta_off),
          (meta_off.get("path_fingerprint", {}).get("hash"), meta_on.get("path_fingerprint", {}).get("hash")))

    print("\n[6] 显式 temporal 不被覆盖 / 解析不了不写 / 加密密级不派生")
    check("显式 temporal 原样保留、且不派生 temporal_anchor", r["ex_fm"] == ("2023-01-01", None), r["ex_fm"])
    check("正文写 yesterday 的节点派生成 5 月 7 日", (r["ev_fm"] or {}).get("start") == "2023-05-07",
          r["ev_fm"])
    _set(True)
    try:
        fm_p = {"created_at": EVENT_TS, "sensitivity": "private"}
        T.apply_on_write(fm_p, "yesterday")
        fm_n = {"created_at": EVENT_TS}
        T.apply_on_write(fm_n, "I love painting")
        fm_x = {"created_at": EVENT_TS, T.DERIVED_FIELD: {"start": "2020-01-01", "end": "2020-01-01"}}
        T.apply_on_write(fm_x, "yesterday")
    finally:
        _set(False)
    check("加密密级（private）不派生（明文 fm 不漏正文日期）", T.DERIVED_FIELD not in fm_p, fm_p)
    check("解析不了 → 不写", T.DERIVED_FIELD not in fm_n, fm_n)
    check("已有派生字段 → 不覆盖", fm_x[T.DERIVED_FIELD]["start"] == "2020-01-01", fm_x)
    iv = T.node_interval({"temporal": "2023-01-01", T.DERIVED_FIELD: {"start": "2023-05-07",
                                                                      "end": "2023-05-07"},
                          "created_at": EVENT_TS}, _mdcg.trust.parse_time)
    check("node_interval：显式 temporal 优先于派生", iv == (D(2023, 1, 1), D(2023, 1, 1), T.SRC_EXPLICIT), iv)

    print("\n[7] 时区（MDCG_TIME_ANCHOR_TZ）")
    ts = _ts(2023, 5, 7, 20)
    check("缺省 UTC：20:00 仍是 5 月 7 日", T.ts_to_date(ts) == D(2023, 5, 7), T.ts_to_date(ts))
    check("TZ=8：顺延到 5 月 8 日", T.ts_to_date(ts, {"MDCG_TIME_ANCHOR_TZ": "8"}) == D(2023, 5, 8))
    check("TZ 非法/越界回落 0", T.tz_hours({"MDCG_TIME_ANCHOR_TZ": "abc"}) == 0.0
          and T.tz_hours({"MDCG_TIME_ANCHOR_TZ": "99"}) == 0.0)

    print("\n[8] 登记（hotcache 键 + config registry）")
    check("hotcache._ENV_SWITCHES 含两个开关",
          {"MDCG_TIME_ANCHOR", "MDCG_TIME_ANCHOR_TZ"} <= set(hotcache._ENV_SWITCHES))
    check("hotcache._KEYED_EXTRA 含 time_anchor", "time_anchor" in hotcache._KEYED_EXTRA)
    names = {row[0] for row in ENV_CATEGORY_ROWS}
    check("config_registry_bulk 登记两个开关", {"MDCG_TIME_ANCHOR", "MDCG_TIME_ANCHOR_TZ"} <= names)

    print("\n[9] 定点变异（文本级：只改内存副本，不改盘上文件）")
    m1 = mutant(T, [(M1_ANCHOR, M1_ANCHOR.replace(" or 7)", ")"))], "m1_last_wd")
    g1 = m1.resolve("last Tuesday", D(2023, 7, 18))
    print("    M1 去掉 last_wd 的 `or 7`：last Tuesday（周二说）%s -> %s"
          % ((D(2023, 7, 11),) * 2, g1))
    check("M1 变异转红：周二说 last Tuesday 被算成当天", g1 != (D(2023, 7, 11),) * 2, g1)

    m2 = mutant(_mdcos, [(M2_ANCHOR, "            pass\n")], "m2_no_partition")
    r2 = date_case(m2.MdCGOS, "m2")
    print("    M2 拆掉融合后的「交集者前置」：on_en top-3 %s -> %s" % (r["on_en"][:3], r2["on_en"][:3]))
    check("M2 变异转红：无交集节点越过有交集节点（前置契约被破坏）",
          not _anchored_first(r2["on_en"]) or not _anchored_first(r2["on_zh"]),
          (r2["on_en"], r2["on_zh"]))

    m3 = mutant(T, [(M3_ANCHOR, "    d = None\n")], "m3_no_derive")
    r3 = date_case(MdCGOS, "m3", ta_mod=m3)
    print("    M3 写入侧不派生（只剩观测当日）：on_en top-3 %s -> %s" % (r["on_en"][:3], r3["on_en"][:3]))
    check("M3 变异转红：yesterday 证据不再 top-1", r3["on_en"][:1] != ["ev"], r3["on_en"])

    m4 = mutant(T, [(M4_ANCHOR, "    if False:\n")], "m4_overwrite")
    r4 = date_case(MdCGOS, "m4", ta_mod=m4)
    print("    M4 去掉「显式 temporal / 已有派生 → 不派生」：ex 的 (temporal, 派生) %s -> %s"
          % (r["ex_fm"], r4["ex_fm"]))
    check("M4 变异转红：显式 temporal 节点被派生", r4["ex_fm"][1] is not None, r4["ex_fm"])

    m5 = mutant(_mdcos, [(M5_ANCHOR, M5_ANCHOR.replace("if _timeanchor.enabled()", "if True"))],
                "m5_always_parse")
    _set(False)
    cg5 = m5.MdCGOS(os.path.join(_TMP, "m5", "root"))
    cg5.add("ev", EVENT, layer="contextual", created_at=EVENT_TS)
    _r5, meta5 = cg5.search_rrf("Caroline 7 May 2023", k=5, record=False)
    cg5.close()
    print("    M5 查询侧无视开关：关时 meta.time_anchor %s -> %s" % (None, meta5.get("time_anchor")))
    check("M5 变异转红：开关关时 meta 出现 time_anchor（零变更被破坏）",
          "time_anchor" in meta5, sorted(meta5))

    print("\n" + "=" * 68)
    print("通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
