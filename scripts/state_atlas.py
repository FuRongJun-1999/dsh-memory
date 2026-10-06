#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""state_atlas —— 多主体状态追踪图（通用常驻件）：语义时空图核心能力的读取视图。

定位（使用者 2026-10-06：「这个功能可以常驻，维护其他角色的状态追踪，这应该
要作为语义时空图的核心功能」）：
  · **常驻形态**＝查询时现算的只读视图（与 `state_slots` 同哲学：不存第二真源）
    ——任何时刻调用即得**最新**追踪图；台账（`_state_events.jsonl`）是唯一真源；
  · **多主体**＝subject 参数化；缺省把库中**全部主体**各出一节（一份图＝全角色
    世界书），`--subject` 可单取；
  · **通用**＝不绑定任何语料/角色专用规则——类别缺省按槽位「·」前缀推断，
    也可传 `--cat-map <json>`（槽位→类别映射表；鲸娘七类表即一例）。

三视图（同 whale_state_atlas）：世界书条目（现值/退役/变迁史＋证据）／大事记
时间线／分幕大纲（可选 `--acts`）；另可 `--worldbook-json` 导出酒馆风格 JSON
（[{keys, content, subject}]——key=槽位名，content=现值＋变迁史文本）。

库根解析（与 zcode MCP 同源，防双库分叉）：`--root` > env `MDCG_ROOT` >
`~/.zcode/cli/config.json` 的 mcp.servers.mdcg env.MDCG_ROOT > `mdcg_root()`。
**只读**（本件不写任何库）；`--out` 必须仓外（fail-closed）。

用法：
  python -X utf8 scripts/state_atlas.py [--root <库根>] [--subject <主体>]
      --out <仓外 .md 路径> [--cat-map <json>] [--acts] [--act-gap 60]
      [--worldbook-json <仓外 .json 路径>]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

KIND_ZH = {"migration": "迁移", "retraction": "撤回", "enablement": "启用",
           "acquisition": "获得", "replacement": "替换"}


def assert_outside_repo(p: str):
    repo = os.path.dirname(HERE)
    out_abs = os.path.abspath(p)
    try:
        if os.path.commonpath([repo, out_abs]) == repo:
            sys.exit("拒绝（fail-closed）：--out 必须落在仓外。")
    except ValueError:
        pass


def resolve_root(explicit: str = None) -> str:
    """与 zcode MCP 同源解析（复用 sync_zcode_session._resolve_root 单点）。"""
    if explicit:
        return explicit
    spec = importlib.util.spec_from_file_location(
        "sync_zcode_session", os.path.join(HERE, "sync_zcode_session.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_root()


def cat_of_slot(slot: str, cat_map: dict) -> str:
    if slot in cat_map:
        return str(cat_map[slot])
    if "·" in slot:
        return slot.split("·", 1)[0]
    return "未分类"


def render_subject(subject, events, units, cat_map, act_gap=None) -> list:
    L = []
    L.append("## %s" % subject)
    L.append("")
    L.append("> %d 条状态事件 ｜ %d 个槽位。" % (len(events), len(units)))
    L.append("")
    # 世界书卡（按类别）
    by_cat = {}
    for u in units:
        by_cat.setdefault(cat_of_slot(u["slot"], cat_map), []).append(u)
    for cat in sorted(by_cat):
        L.append("### %s" % cat)
        L.append("")
        for u in sorted(by_cat[cat], key=lambda x: x["slot"]):
            L.append("#### %s ｜ 状态：%s" % (
                u["slot"], "现役（active）" if u.get("state") == "active"
                else str(u.get("state"))))
            v = u.get("value")
            L.append("- **现值**：%s" % ("（无——已退役/未定）" if v is None else str(v)))
            hist = u.get("history") or []
            if hist:
                L.append("- **变迁史**（%d 条）：" % len(hist))
                for h in hist:
                    old = h.get("old") if h.get("old") is not None else "∅"
                    new = h.get("new") if h.get("new") is not None else "∅（作废）"
                    L.append("  - 轮 %s ［%s］%s → %s　证据：《%s》"
                             % (h.get("seq"), KIND_ZH.get(h.get("kind"), h.get("kind")),
                                str(old)[:30], str(new)[:44],
                                str(h.get("evidence") or "")[:80]))
            L.append("")
    # 大事记时间线（本主体）
    if events:
        L.append("### 大事记时间线")
        L.append("")
        L.append("| 轮 | 类别 | 槽位 | 变更 | 类型 |")
        L.append("|---|---|---|---|---|")
        for e in events:
            old = e.get("old") if e.get("old") is not None else "∅"
            new = e.get("new") if e.get("new") is not None else "∅（作废）"
            L.append("| %s | %s | %s | %s → %s | %s |"
                     % (e.get("seq"), cat_of_slot(e["slot"], cat_map), e["slot"],
                        str(old)[:28], str(new)[:40],
                        KIND_ZH.get(e.get("kind"), e.get("kind"))))
        L.append("")
    # 分幕（可选）
    if act_gap and events:
        acts, cur = [], [events[0]]
        for prev, e in zip(events, events[1:]):
            if (e.get("seq") or 0) - (prev.get("seq") or 0) >= act_gap:
                acts.append(cur)
                cur = [e]
            else:
                cur.append(e)
        acts.append(cur)
        merged = []
        for act in acts:
            if len(act) < 2 and merged:
                merged[-1].extend(act)
            else:
                merged.append(list(act))
        if merged and len(merged[-1]) < 2 and len(merged) > 1:
            merged[-2].extend(merged.pop())
        acts = merged
        L.append("### 分幕大纲（幕界＝事件间隔机械聚类）")
        L.append("")
        for i, act in enumerate(acts, 1):
            lo = act[0].get("seq")
            hi = act[-1].get("seq")
            L.append("#### 第 %d 幕 · 轮 %s–%s（%d 条事件）" % (i, lo, hi, len(act)))
            L.append("")
            for e in act:
                old = e.get("old") if e.get("old") is not None else "∅"
                new = e.get("new") if e.get("new") is not None else "∅（作废）"
                L.append("- 轮 %s ［%s / %s］%s → %s"
                         % (e.get("seq"), e["slot"],
                            KIND_ZH.get(e.get("kind"), e.get("kind")),
                            str(old)[:26], str(new)[:40]))
            snap = {}
            for e in events:
                if (e.get("seq") or 0) <= (hi or 0):
                    snap[e["slot"]] = e.get("new")
            live = {k: v for k, v in snap.items() if v is not None}
            L.append("")
            L.append("- **幕末快照**：%s"
                     % ("；".join("%s＝%s" % (k, str(v)[:26]) for k, v in live.items())
                        or "（全部为空）"))
            L.append("")
    L.append("")
    return L


def main() -> int:
    ap = argparse.ArgumentParser(description="多主体状态追踪图（通用常驻件）")
    ap.add_argument("--root", default=None, help="库根（缺省：env/配置/默认，与 MCP 同源）")
    ap.add_argument("--subject", default=None, help="单取主体（缺省=库中全部主体）")
    ap.add_argument("--out", required=True, help="输出 md（必须仓外）")
    ap.add_argument("--cat-map", default=None, help="槽位→类别 映射表 json（可选）")
    ap.add_argument("--acts", action="store_true", help="附分幕大纲")
    ap.add_argument("--act-gap", type=int, default=60)
    ap.add_argument("--worldbook-json", default=None,
                    help="另出酒馆风格 JSON（[{keys, content, subject}]；须仓外）")
    a = ap.parse_args()

    assert_outside_repo(a.out)
    if a.worldbook_json:
        assert_outside_repo(a.worldbook_json)
    root = resolve_root(a.root)
    cat_map = {}
    if a.cat_map:
        cat_map = json.loads(open(a.cat_map, encoding="utf-8").read())

    from md_cg.mdcos import MdCGOS
    from md_cg import state_events as _se
    from md_cg import state_slots as _ss
    cg = MdCGOS(root)              # 只读使用（本件不写任何库）
    all_events = _se.read(cg)
    units_all = _ss.project(cg, include_retired=True, history=True)

    subjects = [a.subject] if a.subject else sorted(
        {e.get("subject") for e in all_events if e.get("subject")})
    L = ["# 状态追踪图（多主体 · 通用件）", "",
         "> 生成：scripts/state_atlas.py（查询时现算只读视图；台账为唯一真源）。",
         "> 库根：%s ｜ 主体数：%d ｜ 事件总数：%d ｜ 槽位总数：%d"
         % (os.path.basename(root.rstrip("\\/")) or root, len(subjects),
            len(all_events), len(units_all)), ""]
    L += ["---", ""]
    wb = []
    for sub in subjects:
        evs = sorted([e for e in all_events if e.get("subject") == sub],
                     key=lambda e: (e.get("seq") or 0))
        us = [u for u in units_all if u.get("subject") == sub]
        L += render_subject(sub, evs, us, cat_map,
                            act_gap=(max(1, a.act_gap) if a.acts else None))
        for u in us:
            v = u.get("value")
            hist = u.get("history") or []
            lines = ["现值：%s（%s）" % ("（无）" if v is None else v,
                                        u.get("state"))]
            for h in hist:
                lines.append("轮 %s ［%s］%s → %s"
                             % (h.get("seq"), KIND_ZH.get(h.get("kind"), h.get("kind")),
                                h.get("old"), h.get("new")))
            wb.append({"subject": sub, "keys": [u["slot"]],
                       "content": "\n".join(lines)})
    L += ["---", "",
          "*通用件 v1 · 常驻形态＝现算只读视图 · 类别缺省按槽位前缀（·）推断、"
          "可传 --cat-map 覆盖*", ""]

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))
    if a.worldbook_json:
        with open(a.worldbook_json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(wb, f, ensure_ascii=False, indent=1)
    print("ATLAS " + json.dumps(
        {"root_tail": root[-30:], "subjects": subjects, "events": len(all_events),
         "slots": len(units_all), "chars": len("\n".join(L)),
         "worldbook_entries": len(wb)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
