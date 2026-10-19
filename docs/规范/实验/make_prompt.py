# -*- coding: utf-8 -*-
"""生成某个实验臂的完整提示词（任务正文 + 思考语言后缀）。

用法：
  python docs/规范/实验/make_prompt.py T1 ZH_THINK
  python docs/规范/实验/make_prompt.py T1 ZH_THINK --out .tmp/workbuddy_exp/prompt.txt
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("arm", choices=["ZH_THINK", "EN_THINK", "DEFAULT"])
    ap.add_argument("--set", default=str(Path(__file__).with_name("任务集_v1.0.json")))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = json.loads(Path(args.set).read_text(encoding="utf-8"))
    tasks = {t["id"]: t for t in cfg["tasks"]}
    if args.task not in tasks:
        raise SystemExit(f"unknown task {args.task}; choose from {sorted(tasks)}")
    suffix = cfg["arms"][args.arm]["suffix"]
    prompt = tasks[args.task]["prompt"] + suffix
    if args.out:
        Path(args.out).write_text(prompt, encoding="utf-8")
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
