#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py · 设计者视角认知能力验收执行器

读取 cases.jsonl，驱动 scripts/designer.py 的声明/判定/归因核心，输出逐项结果与通过率。
通过率是「技能是否真的生效」的自证，不是自我声称（附录25 工程验证清单）。

用法：
  python selftest.py [--cases tests/cases.jsonl] [--json]
退出码：全通过 0，否则 1。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import designer  # noqa: E402  （路径注入后导入）


def run(cases_path):
    with open(cases_path, encoding="utf-8") as fh:
        cases = [json.loads(line) for line in fh if line.strip()]
    results = designer.run_cases(cases)
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    return results, passed, total


def main(argv=None):
    ap = argparse.ArgumentParser(prog="selftest.py",
                                 description="设计者视角 · 认知能力验收")
    ap.add_argument("--cases", default=os.path.join(HERE, "cases.jsonl"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results, passed, total = run(args.cases)
    rate = (100.0 * passed / total) if total else 0.0

    if args.json:
        print(json.dumps({"passed": passed, "total": total, "rate": round(rate, 2),
                          "results": results}, ensure_ascii=False, indent=2))
    else:
        print("设计者视角 · 认知能力验收（%s）" % os.path.basename(args.cases))
        print("-" * 58)
        for r in results:
            print("%s %-14s [%-8s] %s" % ("PASS" if r["ok"] else "FAIL",
                                          r["id"], r["kind"], r["detail"]))
        print("-" * 58)
        print("通过率：%d/%d = %.1f%%" % (passed, total, rate))
        if passed != total:
            print("未通过项：%s" % "、".join(r["id"] for r in results if not r["ok"]))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
