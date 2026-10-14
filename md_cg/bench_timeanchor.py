# -*- coding: utf-8 -*-
"""bench_timeanchor · 相对时间锚定在 **search_rrf 主路径** 上的 LoCoMo 复现。

# 功能名：LoCoMo（英文原版 locomo10.json）category-2 temporal 题的三组读数（开关关/开、dev/test、去 6 族下界）
# 生效条件：本地有 locomo10.json（snap-research/locomo @ cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc，sha256 79fa87e9…）；用 --data 指路（缺省 data/locomo10.json）
# 子功能：①每段对话一个独立 MdCGOS 库，turn 以会话时刻（UTC）+ 序号秒为 created_at 写入 ②独立 gold 解析器（与 md_cg/timeanchor.py 不共用代码）③三组读数 ④逐对话分片落 JSON + 汇总
# 执行：python -X utf8 -m md_cg.bench_timeanchor --all --out <目录>        （全量；单机约数分钟）
#       python -X utf8 -m md_cg.bench_timeanchor --conv 3 --mode on --out <目录>   （分片：单段对话单配置）
#       python -X utf8 -m md_cg.bench_timeanchor --aggregate <目录>
# 验证方式：汇总表三组读数 + 每片耗时；off 配置与 on 配置的「原题面 hit@10」应相等
# 不适用条件：不是端到端问答（不判答案文本）；只测「证据 turn 能否被找回」与「事件区间是否落在 gold 内」

三组读数（dev = 对话 0–4，test = 对话 5–9）：
  日期正确率   证据 turn 的事件区间 ⊆ gold 区间。事件区间取 `timeanchor.node_interval`
               （显式 temporal > 派生 temporal_anchor > 观测当日）；关闭时无派生字段 ⇒
               恒为「会话当日」（= 只有时间戳的系统）。
  日期点名检索 问句 =「说话人 + gold 日期」（英文写法 / 中文写法各一组，无内容词），
               证据 turn 进 top-10 / top-1 / MRR@10。
  原题面       原问句（When did … ?）top-10 证据命中；问句不含日期 ⇒ 开关前后应逐位相同。
gold 只认能解析成日期区间的答案（228/321）；时长类（「4 years」）与非日期答案不计。

配置（--mode）：off = 开关关（写入与查询都关）；on = 开关开；on_minus6 = 开关开但从规则表
剔除 `timeanchor.POST_HOC_RULE_IDS`（污染声明里的 6 族，写入与查询两侧同时剔除）——报下界。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
DATA_COMMIT = "cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc"
MODES = ("off", "on", "on_minus6")
K = 10

MONS = ["january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december"]
M = {m: i + 1 for i, m in enumerate(MONS)}
M.update({m[:3]: i + 1 for i, m in enumerate(MONS)})
WD = {w: i for i, w in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday",
                                  "saturday", "sunday"])}
D, TD = dt.date, dt.timedelta


# ---------------- gold 解析（测量侧，独立于 md_cg/timeanchor.py） ----------------
# 生效条件：1<=m<=12 时返回该月闭区间。
def _month(y, m):
    return (D(y, m, 1), (D(y + 1, 1, 1) if m == 12 else D(y, m + 1, 1)) - TD(1))


def _wk_before(d):
    return (d - TD(7), d - TD(1))


def _we_before(d):
    w = d.weekday()
    s = d - TD(8) if w == 6 else d - TD(7) if w == 5 else d - TD(w + 2)
    return (s, s + TD(1))


# 生效条件：x 为「7 May 2023 / May 7, 2023」形态（容忍粘连、序数后缀、janury 笔误）时返回 date，否则 None。
def _date(x):
    x = re.sub(r"(\d)([a-z])", r"\1 \2", x)
    x = re.sub(r"([a-z])(\d)", r"\1 \2", x).replace("janury", "january").replace(",", " ")
    p = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", x).split()
    try:
        if len(p) == 3 and p[0].isdigit() and p[1][:3] in M:
            return D(int(p[2]), M[p[1][:3]], int(p[0]))
        if len(p) == 3 and p[1].isdigit() and p[0][:3] in M:
            return D(int(p[2]), M[p[0][:3]], int(p[1]))
    except ValueError:
        return None
    return None


# 生效条件：a 为 LoCoMo 答案文本；能解析成日期区间（「the sunday before 25 May 2023」「May 2023」「2022」…）返回 (d0, d1)，否则 None（不计入题集）。
def gold(a):
    a = str(a).strip().lower().rstrip(".").strip()
    a = re.sub(r"^(?:on |approximately |about |around )?(?:a |the )?", "", a)
    m = re.match(r"^(two weekends|\w+) before (.+)$", a)
    if m and _date(m.group(2)):
        k, d = m.group(1), _date(m.group(2))
        if k == "two weekends":
            return _we_before(_we_before(d)[0])
        if k in WD:
            x = d - TD((d.weekday() - WD[k]) % 7 or 7)
            return (x, x)
        return {"week": _wk_before(d), "weekend": _we_before(d), "day": (d - TD(1), d - TD(1)),
                "month": _month(*((d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1))),
                "year": (D(d.year - 1, 1, 1), D(d.year - 1, 12, 31)),
                "days": (d - TD(7), d - TD(1))}.get(k)
    m = re.match(r"^weekend of (.+)$", a)
    if m and _date(m.group(1)):
        d = _date(m.group(1))
        return (d - TD(1), d + TD(1))
    m = re.match(r"^(first|second|third|last) week of (\w+),? (\d{4})$", a)
    if m and m.group(2)[:3] in M:
        s, e = _month(int(m.group(3)), M[m.group(2)[:3]])
        if m.group(1) == "last":
            return (e - TD(6), e)
        k = ["first", "second", "third"].index(m.group(1))
        return (s + TD(7 * k), s + TD(7 * k + 6))
    m = re.match(r"^(summer|spring|fall|autumn) (?:of )?(\d{4})$", a)
    if m:
        y = int(m.group(2))
        a0, b0 = {"spring": (3, 5), "summer": (6, 8), "fall": (9, 11), "autumn": (9, 11)}[m.group(1)]
        return (D(y, a0, 1), _month(y, b0)[1])
    if _date(a):
        d = _date(a)
        return (d, d)
    m = re.match(r"^(?:in )?(?:early |late |mid-?)?(\w+),? (\d{4})$", a)
    if m and m.group(1)[:3] in M:
        return _month(int(m.group(2)), M[m.group(1)[:3]])
    m = re.match(r"^(?:in )?(\d{4})$", a)
    if m:
        y = int(m.group(1))
        return (D(y, 1, 1), D(y, 12, 31))
    return None


# 生效条件：s 为 LoCoMo 会话时刻串（「1:56 pm on 8 May, 2023」）时返回 naive datetime（按 UTC 解释）。
def session_dt(s):
    m = re.search(r"(\d{1,2}):(\d{2})\s*([ap]m) on (\d{1,2}) (\w+),? (\d{4})", s.lower())
    h = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
    return dt.datetime(int(m.group(6)), M[m.group(5)[:3]], int(m.group(4)), h, int(m.group(2)))


# 生效条件：g 为 gold 区间；点→「7 May 2023」、整月→「May 2023」、整年→「in 2023」、其余（周/周末）取起点日。
def q_en(sp, g):
    if g[0] == g[1]:
        return f"{sp} {g[0].day} {MONS[g[0].month - 1].capitalize()} {g[0].year}"
    if g[0].day == 1 and g[1] == _month(g[0].year, g[0].month)[1]:
        return f"{sp} {MONS[g[0].month - 1].capitalize()} {g[0].year}"
    if g[0] == D(g[0].year, 1, 1) and g[1] == D(g[0].year, 12, 31):
        return f"{sp} in {g[0].year}"
    return f"{sp} {g[0].day} {MONS[g[0].month - 1].capitalize()} {g[0].year}"


# 生效条件：同 q_en 的中文写法（2023年5月7日 / 2023年5月 / 2023年）。
def q_zh(sp, g):
    if g[0] == g[1]:
        return f"{sp} {g[0].year}年{g[0].month}月{g[0].day}日"
    if g[0].day == 1 and g[1] == _month(g[0].year, g[0].month)[1]:
        return f"{sp} {g[0].year}年{g[0].month}月"
    if g[0] == D(g[0].year, 1, 1) and g[1] == D(g[0].year, 12, 31):
        return f"{sp} {g[0].year}年"
    return f"{sp} {g[0].year}年{g[0].month}月{g[0].day}日"


# 生效条件：path 存在时返回 (对话列表, sha256 是否与 DATA_SHA256 相等)。
def load_data(path):
    raw = open(path, "rb").read()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest() == DATA_SHA256


# 生效条件：mode ∈ MODES；设置/清除 MDCG_TIME_ANCHOR，on_minus6 时把 timeanchor.RULES 换成剔除 POST_HOC_RULE_IDS 的副本；返回还原函数。
def _apply_mode(mode):
    from md_cg import timeanchor as T
    saved_rules, saved_env = T.RULES, os.environ.get(T.FLAG)
    if mode == "off":
        os.environ.pop(T.FLAG, None)
    else:
        os.environ[T.FLAG] = "1"
    if mode == "on_minus6":
        T.RULES = [r for r in saved_rules if r[0] not in T.POST_HOC_RULE_IDS]

    def restore():
        T.RULES = saved_rules
        if saved_env is None:
            os.environ.pop(T.FLAG, None)
        else:
            os.environ[T.FLAG] = saved_env
    return restore


# 生效条件：conv 为 locomo10.json 的一段对话、mode ∈ MODES；在临时目录建独立 MdCGOS 库写入全部 turn，跑 category-2 可解析题的三组读数；返回计数 dict（含写入/查询耗时）。临时库用完即删。
def run_conv(ci, conv, mode):
    from md_cg import timeanchor as T
    from md_cg import trust
    from md_cg.mdcos import MdCGOS
    restore = _apply_mode(mode)
    tmp = tempfile.mkdtemp(prefix="bench_ta_%d_%s_" % (ci, mode))
    try:
        cg = MdCGOS(os.path.join(tmp, "root"), autoflush=500)
        c = conv["conversation"]
        sday = {}
        t0w = time.time()
        for k in sorted((k for k in c if re.match(r"session_\d+$", k)),
                        key=lambda k: int(k.split("_")[1])):
            s0 = session_dt(c[k + "_date_time"])
            ts = (s0 - dt.datetime(1970, 1, 1)).total_seconds()
            for j, t in enumerate(c[k]):
                nid = "t_" + re.sub(r"[^0-9A-Za-z_]", "_", t["dia_id"])
                cg.add(nid, f"{t['speaker']}: {t['text']}", layer="contextual",
                       created_at=ts + j, verification_basis="data")
                sday[t["dia_id"]] = (nid, t["speaker"])
        cg.flush()
        write_s = time.time() - t0w
        id2dia = {v[0]: k for k, v in sday.items()}
        n_derived = 0
        acc = dict(n=0, date_ok=0, en_h10=0, en_h1=0, en_mrr=0.0, zh_h10=0, zh_h1=0,
                   zh_mrr=0.0, raw_h10=0, raw_ranks=[])
        for nid in id2dia:
            fm, _c = cg._read(cg.index["nodes"][nid])
            n_derived += bool((fm or {}).get(T.DERIVED_FIELD))
        t0q = time.time()
        for q in conv["qa"]:
            if q.get("category") != 2:
                continue
            g = gold(q["answer"])
            ev = [x for x in q.get("evidence", []) if x in sday]
            if g is None or not ev:
                continue
            acc["n"] += 1
            nid, sp = sday[ev[0]]
            fm, _c = cg._read(cg.index["nodes"][nid])
            iv = T.node_interval(fm, trust.parse_time)
            acc["date_ok"] += int(iv is not None and g[0] <= iv[0] and iv[1] <= g[1])
            evs = set(ev)
            for tag, qq in (("en", q_en(sp, g)), ("zh", q_zh(sp, g))):
                res, _m = cg.search_rrf(qq, k=K, record=False)
                rk = [id2dia.get(r[0]["id"]) for r in res]
                p = next((i for i, x in enumerate(rk) if x in evs), None)
                if p is not None:
                    acc[tag + "_h10"] += 1
                    acc[tag + "_h1"] += int(p == 0)
                    acc[tag + "_mrr"] += 1.0 / (p + 1)
            res, _m = cg.search_rrf(q["question"], k=K, record=False)
            rk = [id2dia.get(r[0]["id"]) for r in res]
            acc["raw_h10"] += int(any(x in evs for x in rk))
            acc["raw_ranks"].append(rk)          # 逐位对照用（off/on 应完全相同）
        acc["query_s"] = round(time.time() - t0q, 2)
        acc["write_s"] = round(write_s, 2)
        acc["turns"] = len(sday)
        acc["derived"] = n_derived
        cg.close()
        return acc
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


# 生效条件：out 目录存在分片 JSON（conv_<i>_<mode>.json）时按 dev/test × mode 汇总并返回行列表；缺片的组合标 missing。
def aggregate(out):
    rows = []
    for mode in MODES:
        for part, rng in (("dev", range(0, 5)), ("test", range(5, 10))):
            tot, missing = None, []
            for ci in rng:
                p = os.path.join(out, "conv_%d_%s.json" % (ci, mode))
                if not os.path.exists(p):
                    missing.append(ci)
                    continue
                a = json.load(open(p, encoding="utf-8"))
                if tot is None:
                    tot = {k: 0 for k, v in a.items() if isinstance(v, (int, float))}
                for k in tot:
                    tot[k] += a.get(k, 0)
            if tot is None:
                rows.append(dict(mode=mode, part=part, missing=missing))
                continue
            n = tot["n"] or 1
            rows.append(dict(
                mode=mode, part=part, n=tot["n"], missing=missing,
                date_acc=round(tot["date_ok"] / n, 3),
                en_h10=round(tot["en_h10"] / n, 3), en_h1=round(tot["en_h1"] / n, 3),
                en_mrr10=round(tot["en_mrr"] / n, 3),
                zh_h10=round(tot["zh_h10"] / n, 3), zh_h1=round(tot["zh_h1"] / n, 3),
                zh_mrr10=round(tot["zh_mrr"] / n, 3),
                raw_h10=round(tot["raw_h10"] / n, 3),
                turns=tot["turns"], derived=tot["derived"],
                write_s=round(tot["write_s"], 1), query_s=round(tot["query_s"], 1)))
    # 原题面逐位对照：off 与 on 的每题 top-10 序列
    same, total = 0, 0
    for ci in range(10):
        pa = os.path.join(out, "conv_%d_off.json" % ci)
        pb = os.path.join(out, "conv_%d_on.json" % ci)
        if os.path.exists(pa) and os.path.exists(pb):
            ra = json.load(open(pa, encoding="utf-8"))["raw_ranks"]
            rb = json.load(open(pb, encoding="utf-8"))["raw_ranks"]
            total += len(ra)
            same += sum(1 for x, y in zip(ra, rb) if x == y)
    return rows, {"raw_identical": same, "raw_total": total}


# 生效条件：命令行三种用法之一（--conv/--mode 分片、--all 全量、--aggregate 汇总）；数据路径缺失时退出码 2。
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/locomo10.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--conv", type=int, default=None)
    ap.add_argument("--mode", choices=MODES, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--aggregate", default=None)
    a = ap.parse_args(argv)
    if a.aggregate:
        rows, raw = aggregate(a.aggregate)
        print("| 配置 | 切分 | 题数 | 日期正确率 | 英文点名 hit@10 / hit@1 / MRR@10 | "
              "中文点名 hit@10 / hit@1 / MRR@10 | 原题面 hit@10 | 写入s | 查询s |")
        print("|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            if "n" not in r:
                print("| %s | %s | 缺片 %s |" % (r["mode"], r["part"], r["missing"]))
                continue
            print("| %s | %s | %d | %.1f%% | %.1f%% / %.1f%% / %.3f | %.1f%% / %.1f%% / %.3f | %.1f%% | %.1f | %.1f |%s"
                  % (r["mode"], r["part"], r["n"], 100 * r["date_acc"], 100 * r["en_h10"],
                     100 * r["en_h1"], r["en_mrr10"], 100 * r["zh_h10"], 100 * r["zh_h1"],
                     r["zh_mrr10"], 100 * r["raw_h10"], r["write_s"], r["query_s"],
                     (" 缺片 %s" % r["missing"]) if r["missing"] else ""))
        print("原题面 top-10 逐位相同（off vs on）：%d / %d" % (raw["raw_identical"], raw["raw_total"]))
        json.dump({"rows": rows, **raw}, open(os.path.join(a.aggregate, "summary.json"), "w",
                                             encoding="utf-8"), ensure_ascii=False, indent=1)
        return 0
    if not os.path.exists(a.data):
        print("缺数据：%s（snap-research/locomo @ %s 的 data/locomo10.json）" % (a.data, DATA_COMMIT))
        return 2
    convs, sha_ok = load_data(a.data)
    if not sha_ok:
        print("警告：locomo10.json 的 sha256 与登记值不符，读数不可与文档对照")
    out = a.out or tempfile.mkdtemp(prefix="bench_ta_out_")
    os.makedirs(out, exist_ok=True)
    jobs = ([(a.conv, a.mode)] if a.conv is not None and a.mode
            else [(ci, m) for m in MODES for ci in range(len(convs))] if a.all else [])
    if not jobs:
        ap.error("需要 --conv N --mode M，或 --all，或 --aggregate DIR")
    for ci, mode in jobs:
        t0 = time.time()
        acc = run_conv(ci, convs[ci], mode)
        acc["wall_s"] = round(time.time() - t0, 2)
        acc["sha256_ok"] = sha_ok
        json.dump(acc, open(os.path.join(out, "conv_%d_%s.json" % (ci, mode)), "w",
                            encoding="utf-8"), ensure_ascii=False)
        print("conv %d %-9s n=%d date_ok=%d en_h10=%d zh_h10=%d raw_h10=%d derived=%d/%d %.1fs"
              % (ci, mode, acc["n"], acc["date_ok"], acc["en_h10"], acc["zh_h10"],
                 acc["raw_h10"], acc["derived"], acc["turns"], acc["wall_s"]))
    if a.all:
        return main(["--aggregate", out])
    return 0


if __name__ == "__main__":
    # 隔离：不碰在役库（aux/root/主密钥一律指向临时目录，调用方已显式设的尊重）
    _TMP_ENV = tempfile.mkdtemp(prefix="bench_ta_env_")
    os.environ.setdefault("MDCG_AUX_ROOT", os.path.join(_TMP_ENV, "aux"))
    os.environ.setdefault("MDCG_ROOT", os.path.join(_TMP_ENV, "root"))
    os.environ.setdefault("MDCG_MASTER_KEY", "00" * 32)
    os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
    sys.exit(main())
