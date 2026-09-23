# -*- coding: utf-8 -*-
"""bucket_zh 中文别名回填（issue #33：S1b 跨语言收敛；幂等、支持 --dry-run）。

用法：
  python -X utf8 -m md_cg.backfill_bucket_zh --root <库根> [--dry-run] [--limit N]

为何需要：别名是**写入侧**新增元数据（英文桶键节点落 `fm.bucket_zh`），存量
节点没有——不回填则 S1b 对存量英文桶键仍走 cross_lang_no_match 审计兜底。
回填后中文 query 可收敛到英文桶（别名参与 domain_similarity，零翻译依赖）。
"""
import argparse
import json
import sys

from .mdcg import MdCG


# 生效条件：无条件解析参数（root 必填，dry_run/limit 可选）、以 MdCG(root) 打开库、调用 backfill_bucket_zh 并把统计 dict 以 JSON 打印，返回 0。
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="库根目录")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="只统计不改盘")
    ap.add_argument("--limit", type=int, default=None, help="最多补写多少个节点")
    a = ap.parse_args(argv)
    cg = MdCG(a.root)
    st = cg.backfill_bucket_zh(dry_run=a.dry_run, limit=a.limit)
    print(json.dumps(st, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
