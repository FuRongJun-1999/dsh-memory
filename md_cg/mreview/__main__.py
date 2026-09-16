# -*- coding: utf-8 -*-
"""M1 机械层入口（零写入）：

    python -m md_cg.mreview [--root R] [--out dump.json] [--full] [--limit N]

默认只打印/落盘**摘要 + 包清单 + 机械聚合**；``--full`` 追加条目明细与逐条机械 issue
（真源全量 dump 会很大，默认裁剪是为可审查性服务，不是隐藏内容）。
"""
from __future__ import annotations

import argparse
import collections
import json
import os

from .. import conformance as CF
from ..datapath import mdcg_root
from . import bundle as BD
from . import candidates as CD
from . import ruleset as RS


def run(root=None, *, sources=CD.SOURCES, cold_limit=500, patrol_window=200,
        max_per_bundle=50, limit=None, patrol_offset=None, rules_dir=None,
        full=False) -> dict:
    root = root or mdcg_root()
    nodes = CF.load_index(root) or {}       # load_index 直接返回 nodes 字典
    gen = CD.generate(root, sources=sources, nodes=nodes, limit=limit,
                      cold_limit=cold_limit, patrol_window=patrol_window,
                      patrol_offset=patrol_offset, with_report=True)
    bd = BD.bundle(gen["candidates"], nodes=nodes, root=root,
                   max_per_bundle=max_per_bundle)
    asm = RS.assemble_all(bd, rules_dir=rules_dir)
    by_rule = collections.Counter(i["rule_id"] for p in asm["packages"] for i in p["mechanical"])
    out = {
        "root": root,
        "candidates": {"by_source": gen["by_source"], "total_raw": gen["total_raw"],
                       "total": gen["total"], "skipped": gen["skipped"]},
        "report": gen.get("report"),
        "assertions": gen.get("assertions"),
        "bundles": [{"bundle_id": b["bundle_id"], "group_kind": b["group_kind"],
                     "group_key": b["group_key"], "size": b["size"], "refs": b["refs"]}
                    for b in bd["bundles"]],
        "bundle_stats": bd["stats"],
        "content_missing": bd["content_missing"],
        "assemble_stats": asm["stats"],
        "mechanical_by_rule": dict(by_rule),
        "llm_checks": sorted({(c["rule_id"], c["check"]) for p in asm["packages"]
                              for c in p["llm"]}),
    }
    if full:
        out["candidates_full"] = gen["candidates"]
        out["bundles_full"] = bd["bundles"]
        out["packages_full"] = asm["packages"]
    return out


def _fmt_summary(d: dict) -> str:
    c, b, a = d["candidates"], d["bundle_stats"], d["assemble_stats"]
    lines = ["", "== M1 机械层（候选 → 捆绑 → 规则装配） ==",
             "真源：%s" % d["root"],
             "候选：原始 %d 条 → 去重后 %d 条（按源：%s）"
             % (c["total_raw"], c["total"],
                ", ".join("%s=%d" % kv for kv in sorted(c["by_source"].items()))),
             "跳过（未落盘/无节点）：%d 条" % len(c["skipped"]),
             "捆绑：%d 包（最大 %d 条/包；分组类型 %s）"
             % (b["bundles"], b["largest"], b["by_group_kind"]),
             "正文缺失：%d 条（读盘失败计入，不冒充内容）" % d["content_missing"],
             "规则：%d 条（%s）" % (len(a["rules"]), ", ".join(a["rules"])),
             "机械检查：%d 条 issue（按类 %s）" % (a["mechanical_total"], a["mechanical_by_kind"]),
             "待 LLM 检查项：%d 条（%s）"
             % (a["llm_checks"], ", ".join("%s:%s" % t for t in d["llm_checks"]))]
    asr = d.get("assertions") or {}
    if asr:
        lines.append("断言集交叉核对：verdict=%s，未达标项 %s"
                     % (asr.get("verdict"), ", ".join(asr.get("failed") or []) or "无"))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m md_cg.mreview",
                                 description="M1 机械层：候选生成→捆绑→规则装配（只读零写入）")
    ap.add_argument("--root", default=None, help="认知图根（缺省 MDCG_ROOT/默认路径）")
    ap.add_argument("--sources", default=",".join(CD.SOURCES))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--cold-limit", type=int, default=500)
    ap.add_argument("--patrol-window", type=int, default=200)
    ap.add_argument("--patrol-offset", type=int, default=None)
    ap.add_argument("--max-per-bundle", type=int, default=50)
    ap.add_argument("--rules-dir", default=None)
    ap.add_argument("--out", default=None, help="落盘 dump（JSON）")
    ap.add_argument("--full", action="store_true", help="含条目明细与逐条 issue")
    a = ap.parse_args(argv)
    d = run(a.root, sources=tuple(s for s in a.sources.split(",") if s),
            cold_limit=a.cold_limit, patrol_window=a.patrol_window, limit=a.limit,
            patrol_offset=a.patrol_offset, max_per_bundle=a.max_per_bundle,
            rules_dir=a.rules_dir, full=a.full)
    print(_fmt_summary(d))
    if a.out:
        with open(os.path.abspath(a.out), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print("已落盘：%s" % os.path.abspath(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
