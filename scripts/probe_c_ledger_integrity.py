#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C 探针：《秤》5.1 账本完整性——状态事件台账的三读数（缺口 / 无账可辨 / 变迁史可查）。

出处：语义时空图补全 P3（《秤》v2.1 §5.1 账本完整性口径；账本面 = `md_cg/state_events.py`
台账 `<root>/_state_events.jsonl` ＋ `md_cg/state_slots.py` 投影 ＋ `stg(op=state_chain)`
查询面）。设计稿：`docs/plans/语义时空图补全_世界模型功能端_设计_v0.1.md` §4 验收跑道。

口径（写定）：
  ① 事件覆盖缺口率 = `--expect-slots` 清单中「台账无任何记录」的槽位占比
     （分子＝无记录槽位数、分母＝清单槽位数；**分子/分母都打印**）。
  ② 无账可辨率   = 对「无记录槽位」＋固定合成不存在槽位逐条查询 `stg(state_chain)`：
     通过判据 `count==0 且 items==[]`——**不编造、不反推**（没账就必须如实报空，
     而不是给一个猜的值）。分子＝通过条数、分母＝查询条数。
  ③ 变迁史可查率 = 台账**有记录**槽位中，`state_chain`（include_retired=True、
     history=True、limit 取足）返回的 history 条数合计 == 台账该槽位记录数 的比例
     （分子＝可查槽位数、分母＝有记录槽位数）。

边界（如实）：
  · 本探针只测**账本面**可辨性（台账/投影/查询面三者的账实一致性）；
    「生成器级无账强答」（LLM 在无账时是否硬答）**不在本探针**——那需要接
    生成器侧读数，后置。
  · 槽位按**标签面**精确匹配（slot 名相等；不做同义归并/模糊匹配）。
  · `alternatives`/`blindspots` 判定口径后置，本探针不涉及。

隐私与确定性（硬性）：
  · 脚本不内嵌任何本机路径字面量——events/expect-slots/out 一律 CLI 参数传入；
  · `--out` 必须落在仓外（脚本内 fail-closed 断言：以本文件上两级为仓根判定）；
  · 确定性：无随机、无时间戳、无路径回显——**同一输入两次运行 stdout 与 --out
    产物字节一致**；
  · 零记忆库写入：隔离 temp root（把 `--events` 拷为该 root 的
    `_state_events.jsonl`）+ `MdCGOS(root)`，全程不在役库 append/落盘；
    `MDCG_STG_STATE` 在进程内临时设置、结束后还原。

用法（中性占位路径）：
  python -X utf8 scripts/probe_c_ledger_integrity.py \\
      --events %TEMP%/state_events.jsonl --expect-slots 住所,房贷,名字 \\
      [--out %TEMP%/probe_c_out]

stdout 末行：`PROBE_C_LEDGER_JSON {...}` 摘要（机器可读）；
--out 时另落 `rates.json` + `probe_c_slots.jsonl` 两件明细（人读/对拍用）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import state_events, stg     # noqa: E402
from md_cg.mdcos import MdCGOS          # noqa: E402

#: 合成不存在槽位（读数②的必空对照组；固定字面量——确定性要求）。
SYNTH_SLOTS = ("__probe_c_no_such_slot_1__", "__probe_c_no_such_slot_2__")

#: state_chain 取足条数（避免 limit 截断污染读数③的 history 条数口径）。
BIG_LIMIT = 10 ** 9


# 生效条件：out_dir 为 CLI 给出的输出目录时——以本脚本上两级目录为仓根，判定其绝对路径是否落在仓内；仓内即 sys.exit 拒绝运行（fail-closed）；不同盘符（commonpath 抛 ValueError）按必在仓外处理。
def assert_outside_repo(out_dir):
    """--out 必须在仓外（fail-closed）：以本脚本上两级目录为仓根判定。"""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_abs = os.path.abspath(out_dir)
    try:
        common = os.path.commonpath([repo, out_abs])
    except ValueError:
        return  # 不同盘符 ⇒ 必在仓外
    if common == repo:
        sys.exit("拒绝运行（fail-closed）：--out 必须落在仓外，当前解析为仓内路径。"
                 "请改用仓外目录（如临时目录）。")


# 生效条件：arg 为 --expect-slots 原串（逗号分隔，可为空串）——按逗号切分、逐项 strip、去空项、按首现序去重后返回清单（空串 → []，即不做缺口读数）。
def parse_slots(arg):
    """--expect-slots 解析：逗号分隔 → 去空白/去空项/保序去重。"""
    out, seen = [], set()
    for s in (arg or "").split(","):
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# 生效条件：path 为台账 jsonl 路径时——逐行 json.loads（空行跳过；解析失败或非对象载荷按坏行跳过，与 state_events.read 同口径），返回 record 列表（落盘序）。
def load_records(path):
    """读台账（坏行跳过，与 `state_events.read` 同口径——同源、不另立判据）。"""
    recs = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                recs.append(rec)
    return recs


# 生效条件：text 为待打印行时——按 UTF-8 显式写 stdout（errors=replace）；流不支持 reconfigure 时跳过（不改变输出内容）。
def _out(text):
    print(text)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="《秤》5.1 账本完整性探针（只读台账；隔离 temp root；确定性输出）")
    ap.add_argument("--events", required=True,
                    help="state_events.jsonl 路径（**仓外**；只读输入）")
    ap.add_argument("--expect-slots", dest="expect_slots", default="",
                    help="逗号分隔的应覆盖槽位清单（可选；省略＝不做缺口读数）")
    ap.add_argument("--out", default=None,
                    help="输出目录（可选；必须落在仓外）")
    a = ap.parse_args()

    if a.out:
        assert_outside_repo(a.out)
    if not os.path.exists(a.events):
        sys.exit("输入台账不存在：%s" % a.events)
    expect = parse_slots(a.expect_slots)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                   # noqa: BLE001
        pass

    root = tempfile.mkdtemp(prefix="probe_c_")
    saved_state = os.environ.get("MDCG_STG_STATE")
    try:
        # 隔离 temp root：把输入台账拷为该 root 的正式台账名（查询面只认这个名字）。
        shutil.copyfile(a.events, os.path.join(root, state_events.STATE_EVENTS_NAME))
        cg = MdCGOS(root)
        recs = load_records(os.path.join(root, state_events.STATE_EVENTS_NAME))
        by_slot = {}
        for r in recs:
            by_slot.setdefault(str(r.get("slot")), []).append(r)

        os.environ["MDCG_STG_STATE"] = "1"      # 进程内临时开（finally 还原）

        # ---- ① 事件覆盖缺口率 ----
        missing = [s for s in expect if s not in by_slot]
        gap = [len(missing), len(expect)]

        # ---- ② 无账可辨率 ----
        targets = ([("expect_missing", s) for s in missing]
                   + [("synthetic", s) for s in SYNTH_SLOTS])
        dist = []
        for kind, s in targets:
            ch = stg.state_chain(cg, slot=s, include_retired=True,
                                 history=True, limit=BIG_LIMIT)
            passed = (ch.get("count") == 0 and (ch.get("items") or []) == [])
            dist.append({"kind": kind, "slot": s, "count": ch.get("count"),
                         "kept": ch.get("kept"), "distinguishable": passed})
        no_ledger = [sum(1 for d in dist if d["distinguishable"]), len(dist)]

        # ---- ③ 变迁史可查率 ----
        hist = []
        for s in sorted(by_slot):
            ch = stg.state_chain(cg, slot=s, include_retired=True,
                                 history=True, limit=BIG_LIMIT)
            total = sum(len(u.get("history") or []) for u in (ch.get("items") or []))
            n = len(by_slot[s])
            hist.append({"slot": s, "ledger_records": n,
                         "chain_count": ch.get("count"), "history_total": total,
                         "queryable": total == n})
        history_queryable = [sum(1 for h in hist if h["queryable"]), len(hist)]
    finally:
        if saved_state is None:
            os.environ.pop("MDCG_STG_STATE", None)
        else:
            os.environ["MDCG_STG_STATE"] = saved_state
        shutil.rmtree(root, ignore_errors=True)

    # ---- 人读读数 ----
    _out("台账：events=%d slots=%d" % (len(recs), len(by_slot)))
    _out("① 事件覆盖缺口率：%d/%d（无记录槽位：%s）"
         % (gap[0], gap[1], "、".join(missing) if missing else "无"))
    _out("② 无账可辨率：%d/%d（判据 count==0 且 items==[]，不编造不反推）"
         % (no_ledger[0], no_ledger[1]))
    _out("③ 变迁史可查率：%d/%d（history 条数 == 台账记录数）"
         % (history_queryable[0], history_queryable[1]))

    # ---- 明细产物（--out，仓外）----
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        detail = {
            "events_total": len(recs),
            "slots_total": len(by_slot),
            "expect_slots": expect,
            "gap": {"num": gap[0], "den": gap[1], "missing": missing},
            "no_ledger_distinguishable": {
                "num": no_ledger[0], "den": no_ledger[1],
                "queries": dist,
            },
            "history_queryable": {
                "num": history_queryable[0], "den": history_queryable[1],
                "slots": hist,
            },
        }
        with open(os.path.join(a.out, "rates.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2)
            f.write("\n")
        with open(os.path.join(a.out, "probe_c_slots.jsonl"), "w",
                  encoding="utf-8", newline="\n") as f:
            rows = ([{"kind": d["kind"], "slot": d["slot"],
                      "ledger_records": len(by_slot.get(d["slot"], [])),
                      "chain_count": d["count"], "history_total": None,
                      "distinguishable": d["distinguishable"]} for d in dist]
                    + [{"kind": "recorded", "slot": h["slot"],
                        "ledger_records": h["ledger_records"],
                        "chain_count": h["chain_count"],
                        "history_total": h["history_total"],
                        "distinguishable": None} for h in hist])
            rows.sort(key=lambda r: (r["kind"], r["slot"]))
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    # ---- 机器可读摘要（末行；键序固定 ⇒ 同输入同字节）----
    summary = {"slots": len(expect), "gap": gap,
               "no_ledger_distinguishable": no_ledger,
               "history_queryable": history_queryable, "events": len(recs)}
    _out("PROBE_C_LEDGER_JSON " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
