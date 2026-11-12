# -*- coding: utf-8 -*-
"""汇总模型层直调 pilot（run_api_pilot.py 的产物）。

  python docs/规范/实验/summarize_api_pilot.py --runs .tmp/workbuddy_exp/api_runs
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_workbuddy import lang_stats, score_task  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=".tmp/workbuddy_exp/api_runs")
    ap.add_argument("--out", default=".tmp/workbuddy_exp")
    args = ap.parse_args()

    runs = Path(args.runs)
    rows = []
    for f in sorted(runs.glob("T*_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if "content" not in d:
            rows.append({**d, "file": str(f), "score": 0, "violation": 0, "checks": [False] * 4})
            continue
        sc = score_task(d["task"], d["content"])
        rows.append(
            {
                **d,
                "file": str(f),
                "reasoning_lang": lang_stats(d.get("reasoning") or ""),
                "answer_lang": lang_stats(d.get("content") or ""),
                "score": sc["score"],
                "violation": sc["violation"],
                "checks": sc["checks"],
            }
        )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "api_scores.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# 模型层直调 pilot · 自动判分汇总", ""]
    lines.append("> 通道：GLM-5.3-Flash（WorkBuddy 同款模型）OpenAI 兼容端点直调，**非 WorkBuddy 界面**。")
    lines.append("> 系统提示词恒定；仅用户提示词尾部的思考语言指令不同。")
    lines.append("")
    lines.append("| 臂 | n | 违规数 | 任务均分 | 思考语言(全文) | 思考开场词 | 输出语言 | 思考中文占比中位 | 开场遵守率 | completion tokens 合计 | 时延中位(s) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for arm in ["ZH_THINK", "EN_THINK", "DEFAULT"]:
        rs = [r for r in rows if r.get("arm") == arm and "reasoning_lang" in r]
        if not rs:
            continue
        think = Counter(r["reasoning_lang"]["label"] for r in rs)
        head = Counter(r["reasoning_lang"].get("opener", "?") for r in rs)
        ans = Counter(r["answer_lang"]["label"] for r in rs)
        zh = [r["reasoning_lang"]["zh_ratio"] for r in rs]
        if arm == "ZH_THINK":
            comply = sum(1 for r in rs if r["reasoning_lang"].get("opener") == "ZH") / len(rs)
        elif arm == "EN_THINK":
            comply = sum(1 for r in rs if r["reasoning_lang"].get("opener") == "EN") / len(rs)
        else:
            comply = None
        toks = sum(int((r.get("usage") or {}).get("completion_tokens") or 0) for r in rs)
        lat = [r.get("latency_s") or 0 for r in rs]
        lines.append(
            "| {} | {} | {} | {:.2f} | {} | {} | {} | {:.2f} | {} | {} | {} |".format(
                arm,
                len(rs),
                sum(r["violation"] for r in rs),
                statistics.mean(r["score"] for r in rs),
                ", ".join(f"{k}:{v}" for k, v in sorted(think.items())),
                ", ".join(f"{k}:{v}" for k, v in sorted(head.items())),
                ", ".join(f"{k}:{v}" for k, v in sorted(ans.items())),
                statistics.median(zh),
                f"{comply:.0%}" if comply is not None else "-",
                toks,
                round(statistics.median(lat), 1),
            )
        )

    lines += ["", "## 逐条（按任务×臂）", ""]
    lines.append("| 任务 | 臂 | 分数 | 违规 | 思考 | 输出 | 思考中文占比 | 时延(s) | 答案摘要 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x.get("task") or "", ["ZH_THINK", "EN_THINK", "DEFAULT"].index(x.get("arm")) if x.get("arm") in ("ZH_THINK", "EN_THINK", "DEFAULT") else 9)):
        if "reasoning_lang" not in r:
            lines.append(f"| {r.get('task')} | {r.get('arm')} | ERROR | - | - | - | - | - | {r.get('error','')[:80]} |")
            continue
        summary = " ".join((r.get("content") or "").split())[:90].replace("|", "/")
        lines.append(
            "| {} | {} | {}/4 | {} | {} | {} | {:.2f} | {} | {} |".format(
                r["task"],
                r["arm"],
                r["score"],
                r["violation"],
                r["reasoning_lang"]["label"],
                r["answer_lang"]["label"],
                r["reasoning_lang"]["zh_ratio"],
                r.get("latency_s"),
                summary,
            )
        )

    lines += ["", "## 思考原文抽样（前 200 字）", ""]
    for r in sorted(rows, key=lambda x: (x.get("task") or "", x.get("arm") or "")):
        if "reasoning_lang" not in r:
            continue
        lines.append(f"### {r['task']} · {r['arm']}")
        lines.append(f"- 思考语言：{r['reasoning_lang']}；输出语言：{r['answer_lang']}")
        lines.append("- 思考：```" + " ".join((r.get("reasoning") or "").split())[:200] + "```")
        lines.append("")

    (out / "api_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"\n# wrote {out/'api_scores.json'} and {out/'api_report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
