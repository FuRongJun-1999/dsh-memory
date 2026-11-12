# -*- coding: utf-8 -*-
"""untrusted_audit · 误判率巡检读数（使用者裁定 2026-10-21 第 1 条）

背景：untrusted 标记会让条目**不进 recall（上下文）**，误判 = 合法记忆消失。
故需要可复算的读数：命中了多少条、按理由/按 marker 分布、以及供人工抽检的样本。

口径（只读，不改任何节点）：
  · 遍历 knowledge 层节点正文（去掉 frontmatter），跑 untrusted.classify；
  · 计数按 reason（line_start_or_after_colon / instruction_frame / multi_marker）分组；
  · 抽样默认 5 条，给 id + markers + 前 80 字，供人工判真伪。

用法：
  python -m md_cg.untrusted_audit --root <库根> [--limit 2000] [--sample 5]
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os

from . import untrusted as U


def _body(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def scan(root: str, limit: int = 2000, sample: int = 5) -> dict:
    """扫描 knowledge 层节点，返回误判巡检读数（不写任何东西）。"""
    pattern = os.path.join(root, "knowledge", "**", "*.md")
    files = sorted(glob.glob(pattern, recursive=True))[:max(1, int(limit))]
    flagged = 0
    by_reason = {}
    by_marker = {}
    samples = []
    for path in files:
        try:
            text = io.open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        body = _body(text)
        r = U.classify(body)
        if not r.get("untrusted"):
            continue
        flagged += 1
        reason = r.get("reason") or "unknown"
        by_reason[reason] = by_reason.get(reason, 0) + 1
        for m in r.get("markers") or []:
            by_marker[m] = by_marker.get(m, 0) + 1
        if len(samples) < max(0, int(sample)):
            samples.append({
                "path": os.path.relpath(path, root).replace("\\", "/"),
                "markers": r.get("markers"),
                "reason": reason,
                "excerpt": body.strip().replace("\n", " ")[:80],
            })
    total = len(files)
    return {
        "root": root,
        "scanned": total,
        "flagged": flagged,
        "flag_ratio": round(flagged / total, 6) if total else 0.0,
        "by_reason": by_reason,
        "by_marker": by_marker,
        "samples": samples,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="untrusted 误判率巡检读数")
    ap.add_argument("--root", required=True)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--sample", type=int, default=5)
    a = ap.parse_args(argv)
    print(json.dumps(scan(a.root, limit=a.limit, sample=a.sample),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
