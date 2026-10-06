#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""whale_state_atlas —— 鲸娘状态追踪图（世界书式档案 ＋ 大事记时间线 ＋ 分幕大纲）。

使用者 2026-10-06：「整理出完整的状态追踪图……可以追溯故事的完整发展脉络和内容
变化。类似酒馆世界书或者是小说故事的大纲。」

形态（一份 md，三视图同源）：
  ① **世界书条目**（按七类分节）：每个槽位一张卡——现值／状态（active|retired）／
     **变迁史**（old→new、kind、发生时点 seq、≤30 字证据短证）——即酒馆世界书的
     「条目 + 触发后注入内容」，但带可追溯的变更链；
  ② **大事记时间线**：全部状态事件按 seq 一行一条（轮号｜类别｜槽位｜kind｜变更）；
  ③ **分幕大纲**：按事件间隔机械聚类成「幕」（gap ≥ --act-gap 切一刀），每幕给
     轮区间／事件清单／**幕末状态快照**（该时点各槽位现值）——小说大纲式的
     「每章末世界长什么样」。

实现（现有功能单点复用）：v7 事件 jsol → 隔离根经库层 `state_events.append` 落台账
→ `state_slots.project(include_retired=True, history=True)` 投影出权威的现值/退役/
变迁史（不自己重算第二份）。幕末快照由事件序现算（同「查询时现算」口径）。

如实边界：本图是**状态骨架**（状态事件轴），不是全量情节摘要（无情节抽取器）；
短证 ≤30 字、证据含轮号，可回语料原文核对；分幕为机械聚类、非情节判断。

用法：python -X utf8 scripts/whale_state_atlas.py \
        --events <state_events_v7.jsonl> --out <仓外 .md 路径> [--act-gap 100]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import state_events as _se          # noqa: E402
from md_cg import state_slots as _ss           # noqa: E402
from md_cg.mdcos import MdCGOS                 # noqa: E402

#: 七类展示序（事件类别字段 cat → 中文节名）
CAT_ORDER = ["人物", "地点", "时间", "物品", "情感", "事件", "因果"]

KIND_ZH = {"migration": "迁移", "retraction": "撤回", "enablement": "启用",
           "acquisition": "获得", "replacement": "替换"}


def assert_outside_repo(p: str):
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_abs = os.path.abspath(p)
    try:
        if os.path.commonpath([repo, out_abs]) == repo:
            sys.exit("拒绝（fail-closed）：--out 必须落在仓外（私有语料产物）。")
    except ValueError:
        pass


def load_events(path: str):
    evs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    evs.sort(key=lambda e: (e["seq"], e["slot"]))
    return evs


def build_cg(events):
    """隔离根：事件经库层 append 落台账 → 返回 (cg, root)。"""
    root = tempfile.mkdtemp(prefix="whale_atlas_")
    cg = MdCGOS(root)
    for e in events:
        _se.append(cg, e["subject"], e["slot"], old=e.get("old"),
                   new=e.get("new"), kind=e["kind"], seq=e["seq"],
                   evidence=e.get("evidence") or "", actor=e.get("actor") or "")
    return cg, root


def _cat_of(slot: str, events) -> str:
    for e in events:
        if e["slot"] == slot:
            return e.get("cat") or "未分类"
    return "未分类"


def render(events, units, act_gap: int) -> str:
    L = []
    L.append("# 鲸娘 · 状态追踪图 v1（世界书 ＋ 大事记 ＋ 分幕大纲）")
    L.append("")
    L.append("> 生成：scripts/whale_state_atlas.py（现有功能单点复用——事件经库层记账"
             "→ `state_slots` 投影出具现值/退役/变迁史；幕末快照按事件序现算）。")
    L.append("> 口径：**状态骨架**（七类状态事件轴），非全量情节摘要；证据短证 ≤30 字"
             "含轮号，可回语料原文核对；分幕为事件间隔机械聚类（gap ≥ %d 轮），非情节判断。"
             % act_gap)
    L.append("> 总量：%d 条状态事件 ｜ %d 个槽位 ｜ 语料跨度 1546 轮段。"
             % (len(events), len(units)))
    L.append("")
    L.append("---")
    L.append("")

    # ---- ② 大事记时间线 ----
    L.append("## 大事记时间线（全部状态事件，按发生序）")
    L.append("")
    L.append("| 轮 | 类别 | 槽位 | 变更 | 类型 |")
    L.append("|---|---|---|---|---|")
    for e in events:
        old = e.get("old") if e.get("old") is not None else "∅"
        new = e.get("new") if e.get("new") is not None else "∅（作废）"
        L.append("| %d | %s | %s | %s → %s | %s |"
                 % (e["seq"], e.get("cat") or "?", e["slot"],
                    str(old)[:28], str(new)[:40],
                    KIND_ZH.get(e["kind"], e["kind"])))
    L.append("")

    # ---- ① 世界书条目 ----
    L.append("---")
    L.append("")
    L.append("## 世界书条目（按七类；每槽位＝一张卡：现值／状态／变迁史）")
    L.append("")
    by_cat = {}
    for u in units:
        by_cat.setdefault(_cat_of(u["slot"], events), []).append(u)
    for cat in CAT_ORDER + [c for c in by_cat if c not in CAT_ORDER]:
        us = by_cat.get(cat) or []
        if not us and cat not in ("事件", "因果"):
            continue
        L.append("### %s" % cat)
        L.append("")
        if cat == "事件":
            L.append("> 事件类＝台账行族（%d 条五元事件本身，见时间线一节）；不另设槽位。"
                     % len(events))
            L.append("")
        if cat == "因果":
            L.append("> 因果类 v1 以证据链承载（每条事件的轮号＋短证），不做独立槽位"
                     "（词形噪声依据见追踪器文件头）。")
            L.append("")
        for u in sorted(us, key=lambda x: x["slot"]):
            L.append("#### %s ｜ 状态：%s" % (u["slot"],
                      "现役（active）" if u.get("state") == "active" else str(u.get("state"))))
            L.append("")
            v = u.get("value")
            L.append("- **现值**：%s" % ("（无——已退役/未定）" if v is None else str(v)))
            hist = u.get("history") or []
            if hist:
                L.append("- **变迁史**（%d 条）：" % len(hist))
                for h in hist:
                    old = h.get("old") if h.get("old") is not None else "∅"
                    new = h.get("new") if h.get("new") is not None else "∅（作废）"
                    ev = str(h.get("evidence") or "")[:80]
                    L.append("  - 轮 %s ［%s］%s → %s　证据：《%s》"
                             % (h.get("seq"), KIND_ZH.get(h.get("kind"), h.get("kind")),
                                str(old)[:30], str(new)[:44], ev))
            else:
                L.append("- 变迁史：无（未背书）")
            L.append("")

    # ---- ③ 分幕大纲 ----
    L.append("---")
    L.append("")
    L.append("## 分幕大纲（状态骨架版；幕界＝事件间隔机械聚类）")
    L.append("")
    acts, cur = [], [events[0]]
    for prev, e in zip(events, events[1:]):
        if e["seq"] - prev["seq"] >= act_gap:
            acts.append(cur)
            cur = [e]
        else:
            cur.append(e)
    acts.append(cur)
    # 单事件幕并入后一幕（末幕为单则并入前一幕）——机械规则，避免「一幕一事件」碎读
    merged = []
    for act in acts:
        if len(act) < 2 and merged:
            merged[-1].extend(act)
        else:
            merged.append(list(act))
    if merged and len(merged[-1]) < 2 and len(merged) > 1:
        merged[-2].extend(merged.pop())
    acts = merged

    for i, act in enumerate(acts, 1):
        lo, hi = act[0]["seq"], act[-1]["seq"]
        cats, slots = {}, {}
        for e in act:
            cats[e.get("cat") or "?"] = cats.get(e.get("cat") or "?", 0) + 1
            slots[e["slot"]] = slots.get(e["slot"], 0) + 1
        lead = "、".join("%s×%d" % (c, n) for c, n in
                         sorted(cats.items(), key=lambda x: -x[1]))
        tops = "、".join("%s" % s for s, _n in
                         sorted(slots.items(), key=lambda x: -x[1])[:2])
        L.append("### 第 %d 幕 · 轮 %d–%d ｜ %s ｜ %s" % (i, lo, hi, lead, tops))
        L.append("")
        for e in act:
            old = e.get("old") if e.get("old") is not None else "∅"
            new = e.get("new") if e.get("new") is not None else "∅（作废）"
            L.append("- 轮 %d ［%s·%s / %s］%s → %s"
                     % (e["seq"], e.get("cat") or "?", e["slot"],
                        KIND_ZH.get(e["kind"], e["kind"]),
                        str(old)[:26], str(new)[:40]))
        # 幕末快照：处理到 hi 为止的各槽位现值
        snap = {}
        for e in events:
            if e["seq"] > hi:
                break
            snap[e["slot"]] = e.get("new")
        live = {k: v for k, v in snap.items() if v is not None}
        L.append("")
        L.append("- **幕末快照**（该时点现值）：%s" %
                 ("；".join("%s＝%s" % (k, str(v)[:26]) for k, v in live.items())
                  or "（全部为空）"))
        L.append("")

    L.append("---")
    L.append("")
    L.append("*本图 v1 · 生成器 scripts/whale_state_atlas.py · 状态事件源＝"
             "scripts/whale_state_tracker.py（v4 机件单点复用）；"
             "承诺/因果独立抽取未做，见追踪器文件头噪声依据*")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="鲸娘状态追踪图（世界书＋时间线＋分幕大纲）")
    ap.add_argument("--events", required=True, help="state_events_v7.jsonl 路径")
    ap.add_argument("--out", required=True, help="输出 md 路径（必须仓外）")
    ap.add_argument("--act-gap", type=int, default=60, help="分幕事件间隔阈值（轮，默认 60）")
    a = ap.parse_args()

    assert_outside_repo(a.out)
    events = load_events(a.events)
    cg, root = build_cg(events)
    try:
        units = _ss.project(cg, include_retired=True, history=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    md = render(events, units, max(1, a.act_gap))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    print("ATLAS %s" % json.dumps(
        {"events": len(events), "slots": len(units),
         "chars": len(md), "out": os.path.basename(a.out)},
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
