# -*- coding: utf-8 -*-
"""hive/scoreboard.py —— 对内域评分器（子代理 × 项目完成情况）

# 功能名：蜂巢对内域评分器——按 identity×task×unit 归集 job 产物，产出价值向量与 Δ
# 生效条件：凡要对子代理（蜂巢执行单元）或项目完成情况评分时；凡要复盘「某单元/某任务做得如何」时；
#           凡要把对内域评分晋升进脑库前。触发语=对内域评分、子代理评分、项目完成情况、_scoreboard。
# 子功能：① 解析 job id 四槽（identity/task/unit/编号；task 可含父段）② 扫 jobs/ 取 spec·status·result
#         ③ 算 round（同键重投次数）/E（spec 声明的验收条目通过率）/执行类型/handoff
#         ④ 结算 Δ = max(1, round_half_up(base × 2E/(round+1))) ⑤ 两级输出 by_unit（子代理）与 by_task（项目）
# 执行：python -X utf8 hive/scoreboard.py [--jobs DIR] [--write] [--json]
# 验证方式：hive/test_scoreboard.py（逐条断言 ＋ 定点变异自证：短路一条判据 ⇒ 对应断言恰好转红）
# 不适用条件：不适用于对外域结算（那走 dsh-bounty 账本，两域各记各的）；不适用于把本表当金额
#            （V2：资金发生在站外，本站只做评价）；不适用于未按 id 契约命名的目录（跳过并计入 skipped）。
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import sys

# ---- 口径单点（改口径只改这里）------------------------------------------------

#: 蜂巢五单元闭集（id 契约）。
UNITS = ("记录单元", "反思单元", "验证单元", "输出单元", "维生系统")

#: 单元 → base 档（建议值，须实测标定；见协作架构 v0.2 §7.4）。
UNIT_BASE = {
    "验证单元": 6,
    "反思单元": 6,
    "维生系统": 6,
    "输出单元": 3,
    "记录单元": 3,
}

#: 兜底 base（单元不在表内时；不应发生——闭集外的目录会被 skip）。
BASE_DEFAULT = 3

#: 已终态的 job 状态（未终态者不计入完成度，只计入在途）。
TERMINAL = ("done", "error", "timeout", "killed")

#: 历史命名（id 契约 v2 之前）：h<时间戳>_<hex>。与「真·不合契约」分开统计。
LEGACY_RE = re.compile(r"^h\d+_[0-9a-f]+$")


# ---- 判据（每条 = 一个可定点变异的函数）----------------------------------------


def half_up(x: float) -> int:
    """显式四舍五入（half-up）。禁用内置 round：银行家舍入会静默改分。"""
    return int(math.floor(x + 0.5))


def parse_job_id(job_id: str):
    """job id → (identity, task, unit, number)；不合契约返回 None。

    契约：h_<identity>_<task>_<unit>_<编号>；task 可含父段（成 5 段主体）。
    """
    if not job_id or not job_id.startswith("h_"):
        return None
    parts = job_id.split("_")
    # h + identity + task(1..2 段) + unit + number
    if len(parts) < 5:
        return None
    unit = parts[-2]
    if unit not in UNITS:
        return None
    num = parts[-1]
    if not num.isdigit():
        return None
    identity = parts[1]
    task = "_".join(parts[2:-2])
    if not identity or not task:
        return None
    return identity, task, unit, int(num)


def settle(base: int, e: float, rounds: int):
    """结算：Δ = max(1, half_up(base × 2E/(round+1)))；返回 (delta, formula)。"""
    r = max(0, int(rounds))
    raw = base * 2.0 * e / (r + 1)
    d = max(1, half_up(raw))
    return d, {
        "base": int(base),
        "e": round(float(e), 6),
        "round": r,
        "num": 2,
        "den": r + 1,
        "raw": round(raw, 6),
        "delta": d,
    }


#: `read_json` 的「读件失败」哨兵：文件缺失 / 文件存在但 JSON 解析失败。
#: 为什么不用 None 表达（#511）：合法 JSON 的 `null` 也是 None，三态会被压成两态。
_MISSING = object()
_BAD_JSON = object()

#: 读件形状闭集（`_file_shape` 的返回；#511 的 `bad_files` 出口据此判定）。
SHAPES = ("ok", "missing", "bad_json", "nonmap")


def read_json(path: str):
    """读 JSON：文件缺失返回 `_MISSING`、解析失败返回 `_BAD_JSON`，其余返回 `json.load` 原值。

    fail-soft：评分不因单个坏件中断。**读件失败的命名出口是 `build()["bad_files"]`**
    （由 `job_record` 经 `_file_shape` 逐文件判定）：`bad_json`（坏件）与 `nonmap`
    （合法 JSON 但顶层非映射）计入；`missing` 是另一态、不混入该键——两态由此可分
    （#511 修前 `_obj` 把三态归一成 `{}`，`result.json` 一路在 `build()` 全 9 键上
    与「文件缺失」逐位相同）。
    """
    if not os.path.isfile(path):
        return _MISSING
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return _BAD_JSON


# 生效条件：path 给定时读 JSON 并把**非映射**载荷（合法 JSON 的 list/str/number/null）
# 一律按「读件失败」处理返回 {}；是 dict 则原样返回；缺失/坏件经 read_json 得哨兵 ⇒ {}。
def _obj(path: str) -> dict:
    """读件 → 映射；**非映射一律当读件失败**（issue #399；口径同 #155③ `_read_status`）。

    为什么必须单点：`read_json(...) or {}` **只兜空值**——「合法 JSON 但顶层不是对象」
    （`[1,2,3]` / `"x"` / `123`）会原样留下，下游 `.get(...)` 立刻 AttributeError ⇒ 单个
    坏件把**整张评分表**打崩（本模块 `read_json` 自述契约却是 fail-soft：不因单个坏件中断，
    只计入 bad_files）。#155③ 已在 `hive_mcp/mcp_server.py._read_status` 立过同款判据，
    本处复用同一口径，**不另造第二份**。
    """
    v = read_json(path)
    return v if isinstance(v, dict) else {}


# 生效条件：path 与 obj 给定时返回该读件的形状（`SHAPES` 之一）；obj 必须是同路径的
# `_obj(path)` 结果（`job_record` 的三行既有调用）。
def _file_shape(path: str, obj: dict) -> str:
    """读件形状**单点**（#511）：`ok` / `missing` / `bad_json` / `nonmap`。

    为什么必须单点：`_obj` 已把非映射归一成 `{}`（#399 的 fail-soft 口径）。本函数
    **不复制**它的映射性判据，而是观察它的输出：合法映射时 `_obj` 原样返回盘面载荷
    （与本次读回值相等），非映射时返回 `{}`（任何非映射都不等于 `{}`）⇒ 映射性判据
    仍只有 `_obj` 一处。缺失/解析失败由 `read_json` 的哨兵直接区分（`null` 是「合法
    JSON 非映射」，落 `nonmap`，不再与缺失同态）。

    不适用条件：`obj` 不是 `_obj(path)` 的结果时结论无意义（调用点唯一，不做校验）；
    本函数为判定重读一次文件（评分面小文件；不以读件次数换判据复制）。
    """
    v = read_json(path)
    if v is _MISSING:
        return "missing"
    if v is _BAD_JSON:
        return "bad_json"
    return "ok" if obj == v else "nonmap"


def job_record(job_dir: str):
    """一个 job 目录 → 记录 dict（含 spec/status/result 的关键面）。

    `bad_files`：三个文件里**存在但读不成映射**的那些文件名（`nonmap`/`bad_json`；
    #511 的命名出口）。文件缺失是另一态（`missing`），不混入该键。
    """
    spec = _obj(os.path.join(job_dir, "spec.json"))
    status = _obj(os.path.join(job_dir, "status.json"))
    result = _obj(os.path.join(job_dir, "result.json"))
    _shapes = {nm: _file_shape(os.path.join(job_dir, nm), o)
               for nm, o in (("spec.json", spec), ("status.json", status),
                             ("result.json", result))}
    bad_files = sorted(nm for nm, sh in _shapes.items() if sh in ("nonmap", "bad_json"))
    cmds = spec.get("commands")
    deterministic = bool(cmds) if isinstance(cmds, list) else bool(cmds)
    return {
        "job_id": os.path.basename(job_dir),
        "state": str(status.get("state") or ""),
        "error": str(status.get("error") or ""),
        "created": status.get("created_ts"),
        "elapsed_s": status.get("elapsed_s"),
        "ok": result.get("ok"),
        "has_content": bool(str(result.get("content") or "").strip()),
        "exit_code": result.get("exit_code"),
        "deterministic": deterministic,
        "handoff": bool(result.get("need_continue") or result.get("handoff_ready")),
        "usage": result.get("usage"),
        "bad_files": bad_files,
    }


def _scan_detail(jobs_dir: str):
    """扫 jobs/ → (records, skipped, legacy, bad, bad_files)。

    bad_files 是**全池**的读件失败清单（`<job_id>/<文件名>`，含进了 bad_ids 的件——
    「该件的 status 给不出 state」与「它的 spec/result 读不成映射」是两件事，各有出口）。
    `scan()` 是对外 4 元组形态的兼容包装（#511：只加旁路清单，不改既有返回形状）。
    """
    recs, skipped, legacy, bad, bad_files = [], [], [], [], []
    if not os.path.isdir(jobs_dir):
        return recs, skipped, legacy, bad, bad_files
    for name in sorted(os.listdir(jobs_dir)):
        d = os.path.join(jobs_dir, name)
        if not os.path.isdir(d) or name.startswith("_"):
            continue
        parsed = parse_job_id(name)
        if not parsed:
            (legacy if LEGACY_RE.match(name) else skipped).append(name)
            continue
        ident, task, unit, num = parsed
        r = job_record(d)
        r.update({"identity": ident, "task": task, "unit": unit, "number": num})
        bad_files.extend("%s/%s" % (name, nm) for nm in r["bad_files"])
        if not r["state"]:
            # #158：坏件/空目录**只进 bad_ids，不计分**——修前这里 append 之后仍
            # 无条件 `recs.append(r)`，于是同一件既被标「读件失败」又拿满 Δ，
            # 与 bad 这一分类自相矛盾（S3 的 jobs 计数也据此订正）。
            bad.append(name)
            continue
        recs.append(r)
    return recs, skipped, legacy, bad, bad_files


def scan(jobs_dir: str):
    """扫 jobs/ → (records, skipped, legacy, bad)。

    skipped=不合 id 契约且非历史格式；legacy=历史格式（`h<时间戳>_<hex>`）；
    bad=`status.json` 给不出 state（缺失/坏件/合法 JSON 非映射/空对象）⇒ 只进 bad_ids
    不计分（#158）。`spec.json`/`result.json` 的读件失败**不进** bad_ids——它们不影响
    「该件是否可评分」，经记录的 `bad_files` 出口上报（#511；全池清单见 `_scan_detail`）。
    """
    return _scan_detail(jobs_dir)[:4]


def score(records):
    """记录列表 → 两级评分行（by_unit 子代理级 / by_task 项目级）。"""
    groups = {}
    for r in records:
        key = (r["identity"], r["task"], r["unit"])
        groups.setdefault(key, []).append(r)

    by_unit = []
    for (ident, task, unit), rs in groups.items():
        rs = sorted(rs, key=lambda x: x["number"])
        n = len(rs)
        done = sum(1 for x in rs if x["state"] == "done")
        err = sum(1 for x in rs if x["state"] == "error")
        to = sum(1 for x in rs if x["state"] == "timeout")
        kill = sum(1 for x in rs if x["state"] == "killed")
        pending = sum(1 for x in rs if x["state"] not in TERMINAL)
        # round = 同键重投次数（首个 job 之后的每一次重投）
        rounds = max(0, n - 1)
        base = UNIT_BASE.get(unit, BASE_DEFAULT)
        # E：**实测完成度**（#158 修复）。修前是常量 `e = 1.0`（e_measured=False）⇒
        # 上面算好的 done/error/timeout/killed/pending **一个都没进 settle**，后果：
        # 「单次失败」与「单次成功」同分（都是 base×2），而「失败后重投成功」因
        # round=1 分母翻倍却仍按 E=1 计 ⇒ 反倒低于单次成功（**分数与结果反向**）。
        # 口径：E = done / n（n>0；未终态的 pending 计入 n ⇒ 在途成果完成率如实下降）。
        e = (float(done) / n) if n else 0.0
        e_measured = True
        delta, formula = settle(base, e, rounds)
        by_unit.append({
            "identity": ident, "task": task, "unit": unit,
            "jobs": n, "done": done, "error": err, "timeout": to, "killed": kill,
            "pending": pending, "round": rounds,
            "base": base, "e": e, "e_measured": e_measured, "delta": delta,
            "deterministic": sum(1 for x in rs if x["deterministic"]),
            "handoff": sum(1 for x in rs if x["handoff"]),
            "job_ids": [x["job_id"] for x in rs],
            "formula": formula,
        })
    by_unit.sort(key=lambda x: (-x["delta"], x["identity"], x["task"], x["unit"]))

    by_task = {}
    for row in by_unit:
        t = row["task"]
        agg = by_task.setdefault(t, {"task": t, "units": 0, "jobs": 0, "done": 0,
                                     "error": 0, "timeout": 0, "killed": 0,
                                     "pending": 0, "delta_sum": 0,
                                     "deterministic": 0, "identities": []})
        agg["units"] += 1
        agg["jobs"] += row["jobs"]
        for k in ("done", "error", "timeout", "killed", "pending", "deterministic"):
            agg[k] += row[k]
        agg["delta_sum"] += row["delta"]
        if row["identity"] not in agg["identities"]:
            agg["identities"].append(row["identity"])
    out_tasks = sorted(by_task.values(), key=lambda x: (-x["delta_sum"], x["task"]))
    for a in out_tasks:
        a["identities"].sort()
        # 完成率：done / 已终态（无终态时记 None，不编造）
        term = a["done"] + a["error"] + a["timeout"] + a["killed"]
        a["completion_rate"] = (a["done"] / term) if term else None
    return by_unit, out_tasks


def build(jobs_dir: str):
    recs, skipped, legacy, bad, _bad_files = _scan_detail(jobs_dir)
    by_unit, by_task = score(recs)
    # identity 大小写变体：只按 casefold 分组；**不做模糊合并**（合并是使用者的决定，猜错即改分）。
    _iv = {}
    for r in by_unit:
        _iv.setdefault(r["identity"].casefold(), set()).add(r["identity"])
    identity_variants = {k: sorted(v) for k, v in sorted(_iv.items()) if len(v) > 1}
    # task 命名漂移：一个 task 名是另一个的子串 ⇒ 疑似同一工作的两种叫法（只报不合，不自动归并）。
    _ts = sorted({a["task"] for a in by_task})
    task_prefix_pairs = sorted({(a, b) for a in _ts for b in _ts if a != b and a in b})
    # #511：读件失败的**命名出口**（`<job_id>/<文件名>`，只含「存在但读不成映射」）。
    # 由 `_scan_detail` 在扫池时一次收集（含进了 bad_ids 的件：job 级失败与文件级
    # 失败各有出口，不互相吞掉）。
    bad_files = sorted(_bad_files)
    return {
        "note": ("对内域评分：本站只做评价（V2 资金发生在站外）。"
                 "口径：Δ = max(1, round_half_up(base × 2E/(round+1)))，"
                 "round = 同 (identity,task,unit) 重投次数，base 按单元定档（建议值待标定）。"
                 "★归集粒度由**命名**决定：同一 (identity,task,unit) 下的多个 job 视为同一次交付的多次尝试；"
                 "若某任务的多个 job 实为不同子交付，应按更细的 task 命名区分（id 契约支持 task 含父段）。"
                 "identity 大小写变体与 task 近名只**报不合**，不自动合并。"),
        "totals": {
            "jobs": len(recs),
            "skipped": len(skipped),
            "legacy": len(legacy),
            "bad": len(bad),
            "bad_files": len(bad_files),
            "by_state": {s: sum(1 for r in recs if r["state"] == s)
                         for s in sorted({r["state"] for r in recs})},
            "delta_sum": sum(r["delta"] for r in by_unit),
        },
        "skipped_ids": skipped,
        "legacy_ids": legacy,
        "identity_variants": identity_variants,
        "task_prefix_pairs": task_prefix_pairs,
        "bad_ids": bad,
        "bad_files": bad_files,
        "by_unit": by_unit,
        "by_task": by_task,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="蜂巢对内域评分器（子代理 × 项目完成情况）")
    ap.add_argument("--jobs", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs"))
    ap.add_argument("--write", action="store_true",
                    help="append-only 落盘 hive/jobs/_scoreboard.jsonl（每次运行追加一行）")
    ap.add_argument("--json", action="store_true", help="打印完整 JSON")
    args = ap.parse_args(argv)

    doc = build(args.jobs)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        t = doc["totals"]
        print("job %d ｜ 跳过 %d ｜ 读件失败 %d ｜ Δ 合计 %d" %
              (t["jobs"], t["skipped"], t["bad"], t["delta_sum"]))
        print("状态分布:", json.dumps(t["by_state"], ensure_ascii=False))
        if doc["identity_variants"]:
            print("⚠ identity 大小写变体（同一端两种写法，未合并）:", json.dumps(doc["identity_variants"], ensure_ascii=False))
        if doc["task_prefix_pairs"]:
            print("⚠ task 近名（疑似同一工作的两种叫法，未合并）:", json.dumps(doc["task_prefix_pairs"], ensure_ascii=False))
        if doc["legacy_ids"]:
            print("历史格式目录 %d 个（id 契约 v2 之前，未计入）" % len(doc["legacy_ids"]))
        if doc["bad_files"]:
            # #511：读件失败（存在但读不成映射）的命名出口——与「文件缺失」分开报。
            print("⚠ 读件失败 %d 个（spec/result 存在但读不成映射，缺失不计）:" % len(doc["bad_files"]))
            for bf in doc["bad_files"]:
                print("   ", bf)
        print()
        print("== by_task（项目完成情况，Top 8）==")
        for a in doc["by_task"][:8]:
            cr = "—" if a["completion_rate"] is None else "%.0f%%" % (a["completion_rate"] * 100)
            print("  %-22s units=%-2d jobs=%-3d done=%-3d err=%-2d Δ=%-3d 完成率=%s" %
                  (a["task"][:22], a["units"], a["jobs"], a["done"], a["error"], a["delta_sum"], cr))
        print()
        print("== by_unit（子代理，Top 8）==")
        for r in doc["by_unit"][:8]:
            print("  %-6s %-18s %-5s jobs=%-2d Δ=%-3d det=%-2d" %
                  (r["identity"], r["task"][:18], r["unit"], r["jobs"], r["delta"], r["deterministic"]))
    if args.write:
        # #158：**append-only**（规格 §7.5）。修前用 "w" 覆写单文件 ⇒ 历史运行被静默
        # 丢弃、无法复盘「某一轮评分相对上一轮变了什么」。改为 JSONL：每次运行追加一行
        # （一行 = 一轮快照；读回取末行即最新）。
        p = os.path.join(args.jobs, "_scoreboard.jsonl")
        # #465：改走 hive/_append.py 的**跨进程安全追加**（收口，见该文件 docstring）。
        # 修前逐条 open("a") 无跨进程锁 ⇒ 多 worker 下丢行 + 撕裂半截行（实测 8x2000 丢 9708、768 半截）。
        try:
            from hive._append import append_line as _append_line
        except ImportError:                                # 脚本方式直跑（无包上下文）
            from _append import append_line as _append_line
        _append_line(p, json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n",
                     tag="scoreboard")
        print()
        print("已追加:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
