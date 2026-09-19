# -*- coding: utf-8 -*-
"""big_domain 域标签回填（S1 大域收敛的前置元数据；幂等、支持 --dry-run）。

用法：
  python -X utf8 -m md_cg.backfill_bigdomain --root <库根> [--dry-run] [--limit N]

为何需要单独的回填入口：域标签是**写入侧**新增的元数据，存量节点没有；
S1 要按域收敛，就必须先把存量补齐（契约 §8.1）。
"""
import argparse
import json
import sys

from .mdcg import MdCG


# 生效条件：无条件解析参数（root 必填，dry_run/limit 可选）、以 MdCG(root) 打开库、调用 backfill_big_domain 并把统计 dict 以 JSON 打印，返回 0。
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="库根目录")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="只统计不改盘")
    ap.add_argument("--limit", type=int, default=None, help="最多补写多少个节点")
    a = ap.parse_args(argv)
    cg = MdCG(a.root)
    st = cg.backfill_big_domain(dry_run=a.dry_run, limit=a.limit)
    print(json.dumps(st, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
